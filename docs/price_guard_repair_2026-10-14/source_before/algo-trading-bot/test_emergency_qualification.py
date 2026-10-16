"""P0 real composition with ephemeral SDK signing and synthetic account records.
HTTP is forbidden; these tests never certify an actual wallet or protective stop.
"""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal as D
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from exchange.base_exchange import ExchangeError,BookLevel,OrderBook,MarketSpec
from exchange.certification_runtime import CertificationRecovery
from exchange.order_lifecycle import OrderRequest
from exchange.compliance_guard import ComplianceGuard
from exchange.emergency_qualification import (EmergencyProposal,EmergencyApproval,EmergencyAuthorization,
    EmergencyContextProvider,EmergencyExecution,EmergencySequence,EmergencyComplianceScope,
    inspect_market,propose,check_entry,permission,policy_hash,POLICY,realized,build_runtime)
from exchange.testnet_qualification import QualificationAuthorization,whitelist_trade_proof
from test_live_exchange_execution import live,response
from test_exact_full_close_v8_6 import runtime_mapping
from test_testnet_certification_v8 import FakeCertificationVenue
from test_exchange_migration import NOW,TEAM


@pytest.fixture
def emergency(live,monkeypatch):
    import exchange.testnet_certification as mod
    monkeypatch.setattr(mod,'TEAM',TEAM);monkeypatch.setattr(mod,'API',live.signer.address)
    runtime_mapping(live)
    live.fixture.book.update(levels=[[dict(px='83400',sz='.1'),dict(px='83350',sz='.2')],
        [dict(px='83440',sz='.0006'),dict(px='83480',sz='.001')]])
    live.fixture.contexts=[dict(markPx='83500',oraclePx='83500',funding='.0001',openInterest='10')
        for _ in live.fixture.metadata['universe']]
    live.fixture.active.update(markPx='83500',availableToTrade=['1000','1000'])
    recovery=CertificationRecovery(live.account,live.journal,initial_start_ms=NOW)
    def wait_seconds(seconds):
        live.fixture.now+=int(seconds*1000)
        live.fixture.book['time']=live.fixture.now
    provider=EmergencyContextProvider(live.market,live.account,live.signer.address,live.clock,live.rate,
        reconciliation_ready=lambda:recovery.account_truth_ready,feed_ready=lambda:True,wait=wait_seconds)
    recovery.recover()
    context=provider.load(OrderRequest('par:BTC','BUY','.0002','83606',tif='Ioc'))
    p,checks=propose(context,live.client,'fixture-source','fixture-policy',provider.last_book,
                     tif='Ioc',candidate_hash='real-synthetic-book-hash')
    a=EmergencyApproval(p.identity,'SYNTHETIC_EXACT_RISK_ONLY',NOW,NOW+300000,True,True,True,
        policy_hash(),True,True,True,True,True)
    auth=EmergencyAuthorization(p,a,live.journal,clock_ms=lambda:live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    e=EmergencyExecution(live.client,proposal=p,transport=live.transport,account=live.account,
        journal=live.journal,context_provider=provider,validator=live.validator,recovery=recovery,
        clock_health=live.clock,rate_limits=live.rate)
    live.executor=e;live.provider=provider
    venue=FakeCertificationVenue(live,monkeypatch,auth)
    seq=EmergencySequence(e,p,auth)
    return SimpleNamespace(live=live,p=p,a=a,auth=auth,venue=venue,sequence=seq,context=context,checks=checks)


def resting(c,monkeypatch,tif='Gtc',partial=None,fill_on_cancel=False):
    p,checks=propose(c.context,c.live.client,'fixture-source','fixture-policy',c.live.provider.last_book,
        tif=tif,candidate_hash='synthetic-resting-book')
    c.p=p;c.a=replace(c.a,proposal_hash=p.identity);c.auth.proposal=p;c.auth.approval=c.a
    c.live.executor.proposal=p;c.live.executor.compliance_guard.qualification_scope=EmergencyComplianceScope(p,c.live.provider)
    original=c.venue.transmit
    pending={}
    def fill(amount):
        row=pending['row'];qty=D(amount);px=D(row['limitPx']);fee=qty*px*D('.0003')
        c.live.fixture.position(qty,str(px));c.live.fixture.fill(qty,price=str(px),oid=row['oid'],tid=row['oid'],fee=str(fee))
        c.live.fixture.spot['balances'][0]['total']=str(D(c.live.fixture.spot['balances'][0]['total'])-fee)
        row['sz']=str(D(row['origSz'])-qty)
        if D(row['sz'])==0:
            c.live.fixture.orders=[];c.venue.statuses[str(row['oid'])]['order']['status']='filled'
    def transmit(payload):
        action=payload['action']
        if action['type']=='order' and not action['orders'][0]['r']:
            c.live.transport.check(action);c.auth.claim_transmission(action)
            c.live.transport.signed_payloads.append(deepcopy(payload));c.venue.calls.append(deepcopy(action))
            w=action['orders'][0];c.venue.oid+=1
            row=dict(coin='par:BTC',side='B',oid=c.venue.oid,cloid=w['c'],sz=w['s'],origSz=w['s'],
                     limitPx=w['p'],isTrigger=False,reduceOnly=False,timestamp=c.live.fixture.now)
            c.live.fixture.orders=[row];pending['row']=row
            record=dict(status='order',order=dict(order=row,status='open',statusTimestamp=c.live.fixture.now))
            c.venue.statuses[str(row['oid'])]=record;c.venue.statuses[w['c']]=record
            return response({'resting':{'oid':row['oid']}})
        if action['type']=='cancel' and fill_on_cancel:fill(p.quantity)
        return original(payload)
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    def wait():
        c.live.fixture.now+=1000;c.live.fixture.book['time']=c.live.fixture.now
        if partial is not None and pending and not c.live.fixture.fills:fill(partial)
    c.sequence=EmergencySequence(c.live.executor,p,c.auth,wait=wait,monotonic=lambda:c.live.fixture.now/1000)
    return c


def test_ioc_real_composition_and_smallest_lot_not_cap_target(emergency):
    c=emergency;r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert D(c.p.quantity)==D('.0002') and D(c.p.quantity)*D(c.p.entry_limit)<25
    assert c.p.max_notional=='1000' and c.p.max_signed_actions==4
    assert len(c.venue.calls)==2 and r['final_flat']
    assert not r['protection_accepted'] and not r['certification_passed'] and not r['live_ready']
    proof=whitelist_trade_proof(c.sequence,r,actual_transport=False)
    assert not proof['fill_verified'] and not proof['final_flat_verified']


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_ioc_zero_partial_full_one_entry_only(emergency,fraction):
    c=emergency;c.venue.partial_entry=D(fraction);r=c.sequence.run()
    assert r['status']==('NO_FILL_VERIFIED' if fraction=='0' else 'TRADE_CLOSED_RECONCILED'),r
    entries=[a for a in c.venue.calls if a['type']=='order' and not a['orders'][0]['r']]
    assert len(entries)==1 and r['final_flat']
    if fraction!='0':assert D(c.venue.calls[-1]['orders'][0]['s'])==D(c.p.quantity)*D(fraction)
    count=len(c.venue.calls)
    assert EmergencySequence(c.live.executor,c.p,c.auth).run()['status']=='PREFLIGHT_BLOCKED'
    assert len(c.venue.calls)==count


@pytest.mark.parametrize('tif',['Gtc','Alo'])
def test_resting_unfilled_one_real_cancel_then_flat(emergency,monkeypatch,tif):
    c=resting(emergency,monkeypatch,tif);r=c.sequence.run()
    assert r['status']=='NO_FILL_VERIFIED',r
    assert [a['type'] for a in c.venue.calls]==['order','cancel']
    assert len(r['entry_monitor'])>=2 and r['final_flat']
    assert not c.live.fixture.fills and not c.live.account.get_frontend_open_orders()
    assert c.live.fixture.now>=NOW+30000


@pytest.mark.parametrize('tif',['Gtc','Alo'])
@pytest.mark.parametrize('amount',['.0001','.0002'])
def test_resting_partial_or_full_actual_fill_cancels_remainder_before_close(emergency,monkeypatch,tif,amount):
    c=resting(emergency,monkeypatch,tif,partial=amount);r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert [a['type'] for a in c.venue.calls]==(['order','cancel','order'] if amount=='.0001' else ['order','order'])
    assert D(c.venue.calls[-1]['orders'][0]['s'])==D(amount)
    assert r['final_flat'] and D(r['realized_pnl']['actual_entry_fee'])==D(amount)*D(c.p.entry_limit)*D('.0003')


def test_fill_during_cancel_reconciles_new_actual_quantity(emergency,monkeypatch):
    c=resting(emergency,monkeypatch,fill_on_cancel=True);r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert D(c.venue.calls[-1]['orders'][0]['s'])==D(c.p.quantity)


def test_uncertain_cancel_stops_without_exit_or_replacement(emergency,monkeypatch):
    c=resting(emergency,monkeypatch,partial='.0001');c.venue.cancel_uncertain=True
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert [a['type'] for a in c.venue.calls]==['order','cancel']
    assert c.live.account.get_positions() and c.live.account.get_frontend_open_orders()
    assert not r.get('final_flat',False) and r['operator_action_required']


@pytest.mark.parametrize('fail',['entry_rejected','timeout_before','timeout_after_fill',
    'summary_without_fill','disconnect_after_fill'])
def test_entry_failures_never_blindly_repeat(emergency,fail):
    c=emergency;c.venue.fail=fail;r=c.sequence.run()
    assert r['status']==({'entry_rejected':'NO_FILL_VERIFIED','timeout_after_fill':'TRADE_CLOSED_RECONCILED'}.get(fail,'EMERGENCY_EXIT_REQUIRED')),(r['status'],r.get('error'))
    assert len([a for a in c.venue.calls if a['type']=='order' and not a['orders'][0]['r']])==1
    if r['status']=='EMERGENCY_EXIT_REQUIRED':assert not r.get('final_flat',False)


@pytest.mark.parametrize('kind',['rejected','timeout','price_gap'])
def test_failed_close_preserves_exposure_and_bounded_attempts(emergency,monkeypatch,kind):
    c=emergency;original=c.venue.transmit
    def transmit(payload):
        action=payload['action']
        if action['orders'][0]['r']:
            if kind=='timeout':raise TimeoutError('SYNTHETIC_EXIT_UNKNOWN')
            c.auth.claim_transmission(action);c.venue.calls.append(deepcopy(action))
            return response({'error':'Order must have minimum value of $10.'})
        result=original(payload)
        if kind=='price_gap':c.live.fixture.book['levels']=[[dict(px='75000',sz='1')],[dict(px='75010',sz='1')]]
        return result
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert c.live.account.get_positions() and not r.get('final_flat',False)
    assert len(c.venue.calls)<=3


def test_partial_exit_closes_exact_residual_without_increase(emergency):
    c=emergency;c.venue.partial_exit=D('.6');r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert [D(a['orders'][0]['s']) for a in c.venue.calls]==[D('.0002'),D('.0002'),D('.0001')]


@pytest.mark.parametrize('field',['manually_verified_wallets','sole_signer_host_confirmed','maximum_one_entry',
    'unverified_stop_risk_accepted','l2_and_50bps_qualification_policy_accepted',
    'possible_manual_residual_recovery_accepted','maximum_1000_is_not_loss_guarantee_accepted',
    'one_cancel_two_exits_and_lifetime_accepted'])
def test_all_exact_human_acknowledgements_mandatory(emergency,field):
    c=emergency;c.auth.approval=replace(c.a,**{field:False})
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


@pytest.mark.parametrize('field,value',[('proposal_hash','old-hash'),('qualification_policy_hash','old-policy'),
    ('operator_approval',''),('expires_ms',NOW),('expires_ms',NOW+300001),('approved_ms',NOW+1)])
def test_invalid_approval_no_actual_order(emergency,field,value):
    c=emergency;c.auth.approval=replace(c.a,**{field:value})
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


def test_old_qualification_authorization_cannot_accept_new_policy(emergency):
    c=emergency;a=QualificationAuthorization(c.p,c.a,c.live.journal,clock_ms=lambda:NOW,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    with pytest.raises(ExchangeError):a.require(TEAM,c.live.signer.address)


@pytest.mark.parametrize('damage',['source','reliability','expiry'])
def test_source_policy_expiry_before_any_signature(emergency,damage):
    c=emergency
    if damage=='source':c.auth.source_hash=lambda:'changed'
    if damage=='reliability':c.auth.policy_hash=lambda:'changed'
    if damage=='expiry':c.live.fixture.now=NOW+300000
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.live.transport.signed_payloads


def test_entry_insufficient_time_for_recovery_consumes_no_transmission(emergency):
    c=emergency;c.auth.approval=replace(c.a,expires_ms=NOW+89000)
    r=c.sequence.run()
    assert not c.venue.calls and not c.live.transport.signed_payloads
    assert r['status'] in {'EMERGENCY_EXIT_REQUIRED','PREFLIGHT_BLOCKED'}


@pytest.mark.parametrize('field,value',[('max_notional','1001'),('max_notional','25'),('quantity','.02'),
    ('entry_tif','Foo'),('order_lifetime_seconds',1),('qualification_policy_hash','old'),
    ('max_signed_actions',5),('max_exit_attempts',3),('entry_side','SELL'),('network','mainnet'),
    ('dex','pa'),('entry_rule','discretionary'),('protection_status','VERIFIED')])
def test_policy_exact_cap_type_route_bounds(emergency,field,value):
    with pytest.raises(ExchangeError):replace(emergency.p,**{field:value}).require()


def test_l2_capability_keeps_original_bbo_policy_false(emergency):
    c=emergency;row=inspect_market(c.context.spec,c.live.provider.last_book,NOW)
    assert row['potential'] and not row['old_10_percent_bbo_passed']
    c.live.executor.entries_paused=False
    req=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc',strategy_id='TESTNET_CERTIFICATION_ENTRY')
    c.live.executor.compliance_guard=ComplianceGuard(c.live.journal,c.live.executor.position_guard,
        clock_ms=c.live.client.clock_ms,transport=c.live.transport,execution_owner=c.live.executor)
    c.live.transport._compliance_guard=c.live.executor.compliance_guard
    with pytest.raises(ExchangeError,match='BOOK_MANIPULATION_RISK'):
        c.live.executor.submit(req,permission=permission(req,c.p,NOW))
    assert not c.venue.calls


def test_fifty_dollar_controlled_cap_only_replaced_inside_exact_scope(emergency):
    c=emergency
    c.live.fixture.book['levels']=[[dict(px='600000',sz='1')],[dict(px='600100',sz='1')]]
    c.live.fixture.contexts=[dict(markPx='600050',oraclePx='600050',funding='.0001',openInterest='0')
        for _ in c.live.fixture.metadata['universe']]
    c.live.fixture.active['markPx']='600050'
    ctx=c.live.provider.load(OrderRequest('par:BTC','BUY','.0001','601300',tif='Ioc'))
    p,_=propose(ctx,c.live.client,'fixture-source','fixture-policy',c.live.provider.last_book,
        tif='Ioc',candidate_hash='synthetic-high-lot-notional')
    c.auth.proposal=p;c.auth.approval=replace(c.a,proposal_hash=p.identity)
    e=c.live.executor;e.proposal=p;e.compliance_guard.qualification_scope=EmergencyComplianceScope(p,c.live.provider)
    seq=EmergencySequence(e,p,c.auth);r=seq.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert D(p.quantity)*D(p.entry_limit)>50 and D(p.quantity)*D(p.entry_limit)<1000


@pytest.mark.parametrize('damage',['depth','spread','oracle','stale','duplicate_price','unsorted','wrong_symbol'])
def test_authentic_l2_and_price_constraints(emergency,damage):
    c=emergency;b=c.live.provider.last_book;ctx=c.context.contexts[c.p.symbol]
    if damage=='depth':b=replace(b,asks=(BookLevel(D('83440'),D('.0001')),))
    if damage=='spread':b=replace(b,asks=(BookLevel(D('85000'),D('1')),))
    if damage=='oracle':ctx=dict(ctx,oraclePx='100000')
    if damage=='stale':b=replace(b,timestamp_ms=NOW-5001)
    if damage=='duplicate_price':b=replace(b,asks=(b.asks[0],b.asks[0]))
    if damage=='unsorted':b=replace(b,asks=tuple(reversed(b.asks)))
    if damage=='wrong_symbol':b=replace(b,symbol='par:ETH')
    assert not inspect_market(c.context.spec,b,NOW,asset_context=ctx)['potential']


@pytest.mark.parametrize('symbol,decimals,asset,price',[
    ('par:ETH',4,2670001,'2500'),('par:HYPE',2,2670002,'80'),('par:BRENT',2,2670006,'100'),
    ('par:GOLD',4,2670007,'4000'),('par:EWJ',3,2670005,'100')])
def test_all_partial_residuals_required_even_with_large_opening_liquidity(symbol,decimals,asset,price):
    spec=MarketSpec(symbol,decimals,20,asset);px=D(price)
    b=OrderBook(symbol,NOW,(BookLevel(px,D('100')),),(BookLevel(px*D('1.001'),D('100')),))
    row=inspect_market(spec,b,NOW)
    assert not row['potential'] and row['blocker']=='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL'


def test_subminimum_entry_still_blocked(emergency):
    c=emergency
    with pytest.raises(ExchangeError):replace(c.p,quantity='.0001').require()


def test_restart_durable_consumed_attempt_no_repeat(emergency):
    c=emergency;c.venue.fail='timeout_before';c.sequence.run()
    assert c.live.journal.control('qualification_entry_consumed')==c.p.identity
    auth=EmergencyAuthorization(c.p,c.a,c.live.journal,clock_ms=lambda:NOW,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    assert EmergencySequence(c.live.executor,c.p,auth).run()['status']=='EMERGENCY_EXIT_REQUIRED'
    assert len(c.venue.calls)==1


def test_wrong_scope_type_rejected(emergency):
    c=emergency
    with pytest.raises(ExchangeError,match='P0_EXACT_COMPLIANCE_SCOPE_REQUIRED'):
        ComplianceGuard(c.live.journal,c.live.executor.position_guard,clock_ms=lambda:NOW,
            transport=c.live.transport,qualification_scope=SimpleNamespace(validate=lambda *a:True))


def test_shared_rate_limit_blocks_notional_without_signing(emergency,monkeypatch):
    c=emergency
    def denied(**kwargs):raise ExchangeError('SYNTHETIC_RATE_BUDGET_EXHAUSTED')
    monkeypatch.setattr(c.live.rate,'reserve_action',denied)
    r=c.sequence.run();assert not c.venue.calls and not c.live.transport.signed_payloads
    assert r['status']=='EMERGENCY_EXIT_REQUIRED'


def test_handoff_has_real_cli_and_unfilled_risk_template(emergency,tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('p0launcher',Path(__file__).resolve().parents[1]/'scripts/run_emergency_qualification.py')
    import sys;sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    template=module.approval_template(emergency.p)
    assert template['operator_approval']=='' and template['approved_ms'] is None
    assert not template['unverified_stop_risk_accepted']
    h=module.handoff(emergency.p,tmp_path,tmp_path/'receipt.json')
    assert '--execute' in h['execute_command'] and not h['actual_fill_verified']
    assert h['actual_entry_exposure']!=h['maximum_policy_exposure']


@pytest.mark.parametrize('quantity',['.0003','.001','.01'])
def test_no_manual_upsize_or_non_algorithmic_quantity_even_below_cap(emergency,quantity):
    c=emergency;p=replace(c.p,quantity=quantity).require()
    req=OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif=p.entry_tif)
    with pytest.raises(ExchangeError,match='P0_MINIMUM_VALID_QUANTITY_RULE_REQUIRED'):
        check_entry(c.context,req,p,NOW,c.live.provider.last_book)


@pytest.mark.parametrize('damage',['leverage','margin','identity','api','account_age','fees','unexpected_order','unexpected_position'])
def test_fresh_actual_preflight_constraints_independent_of_l2_policy(emergency,damage):
    c=emergency;ctx=c.context
    if damage=='leverage':ctx=replace(ctx,active_asset=dict(ctx.active_asset,leverage=dict(type='cross',value=20)))
    if damage=='margin':ctx=replace(ctx,active_asset=dict(ctx.active_asset,availableToTrade=['1','1']))
    if damage=='identity':ctx=replace(ctx,active_asset=dict(ctx.active_asset,user='0x'+'2'*40))
    if damage=='api':ctx=replace(ctx,readiness=replace(ctx.readiness,signer_address='0x'+'1'*40))
    if damage=='account_age':ctx=replace(ctx,account_ms=NOW-5001)
    if damage=='fees':ctx=replace(ctx,readiness=replace(ctx.readiness,fees=dict(ctx.readiness.fees,userCrossRate='.001')))
    if damage=='unexpected_order':ctx=replace(ctx,open_orders=({'oid':123},))
    if damage=='unexpected_position':ctx=replace(ctx,positions={'par:BTC':SimpleNamespace(quantity=D('.0001'))})
    with pytest.raises(ExchangeError):check_entry(ctx,OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'),c.p,NOW,c.live.provider.last_book)


def test_depth_beyond_limit_cannot_support_ioc(emergency):
    c=emergency;b=replace(c.live.provider.last_book,asks=(BookLevel(D('83440'),D('.0001')),BookLevel(D('90000'),D('100'))))
    r=inspect_market(c.context.spec,b,NOW)
    assert not r['potential'] and r['blocker']=='P0_ENTRY_DEPTH_REQUIRED'


def test_gtc_can_rest_when_taker_depth_fails_without_faking_executable_depth(emergency):
    c=emergency;b=replace(c.live.provider.last_book,asks=(BookLevel(D('83440'),D('.0001')),))
    ioc=inspect_market(c.context.spec,b,NOW,tif='Ioc');gtc=inspect_market(c.context.spec,b,NOW,tif='Gtc')
    assert not ioc['potential'] and gtc['potential']
    assert D(gtc['entry_depth']['available_quantity'])==0 and not gtc['old_10_percent_bbo_passed']


def test_gtc_disconnection_with_resting_order_requires_recovery(emergency,monkeypatch):
    c=resting(emergency,monkeypatch)
    def disconnected():
        c.venue.rest_down=True
        raise ExchangeError('SYNTHETIC_DISCONNECT')
    c.sequence.wait=disconnected;r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and len(c.venue.calls)==1
    assert c.live.fixture.orders and not r.get('final_flat',False)


def test_gtc_unknown_status_does_not_replace_original_order(emergency,monkeypatch):
    c=resting(emergency,monkeypatch);original=c.venue.read
    def read(payload):
        if payload['type']=='orderStatus':return dict(status='unknownOid')
        return original(payload)
    c.live.client.transport=read
    # A contradictory unknownOid with a visible original open order is uncertainty,
    # never permission to replace it. Exact cancellation may still be prevented.
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and not r.get('final_flat',False)
    assert len([a for a in c.venue.calls if a['type']=='order' and not a['orders'][0]['r']])==1


def test_cancellation_ack_without_readback_does_not_claim_flat(emergency,monkeypatch):
    c=resting(emergency,monkeypatch);original=c.live.transport.transmit
    def transmit(payload):
        if payload['action']['type']=='cancel':
            c.live.transport.check(payload['action']);c.auth.claim_transmission(payload['action'])
            c.venue.calls.append(deepcopy(payload['action']));return response('success','cancel')
        return original(payload)
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert c.live.fixture.orders and not r.get('final_flat',False)


def test_stop_cannot_be_submitted_using_new_qualification_authority(emergency):
    c=emergency;r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED'
    assert not any('trigger' in a.get('orders',[{}])[0].get('t',{}) for a in c.venue.calls)
    assert c.live.executor.protection._plan
    with pytest.raises(ExchangeError,match='STOP_UNVERIFIED'):c.live.executor.protection._plan()


def test_historical_btc_shape_does_not_certify_all_larger_subminimum_residuals(emergency):
    c=emergency;b=replace(c.live.provider.last_book,
        bids=(BookLevel(D('49000'),D('100')),),asks=(BookLevel(D('49010'),D('100')),))
    r=inspect_market(c.context.spec,b,NOW)
    assert not r['potential'] and r['blocker']=='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL'
    assert r['residuals']['first_unverified_quantity']=='0.0002'


def test_no_risk_acceptance_does_not_construct_actual_client_or_key(emergency,tmp_path,monkeypatch):
    import exchange.emergency_qualification as module
    import strategy_freeze
    import exchange.practice_preflight as preflight
    import exchange.hyperliquid_client as client
    monkeypatch.setattr(module,'require_emergency_regression',lambda *a:None)
    monkeypatch.setattr(strategy_freeze,'verify_strategy_freeze',lambda:True)
    def prohibited(*a,**k):raise AssertionError('ACTUAL_CLIENT_OR_KEY_PROHIBITED')
    monkeypatch.setattr(preflight,'read_api_key',prohibited);monkeypatch.setattr(client,'HyperliquidClient',prohibited)
    a=replace(emergency.a,unverified_stop_risk_accepted=False)
    with pytest.raises(ExchangeError,match='EXACT_NEW_P0_POLICY'):
        build_runtime(tmp_path,emergency.p,a,test_receipt=tmp_path/'none.json')
