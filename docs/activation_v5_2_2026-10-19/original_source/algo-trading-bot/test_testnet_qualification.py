"""Qualification regressions: ephemeral signatures, synthetic venue, no HTTP."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import json
import pytest

from exchange.base_exchange import ExchangeError, MarketSpec
from exchange.certification_runtime import CertificationRecovery
from exchange.execution_journal import ExecutionJournal
from exchange.order_lifecycle import OrderRequest
from exchange.testnet_certification import require_safe_partial_path
from exchange.testnet_qualification import (QualificationProposal,QualificationApproval,
    QualificationAuthorization,QualificationExecution,QualificationSequence,
    propose_qualification,check_entry,residual_close_assessment,whitelist_trade_proof,
    prime_read_only_clock)
from test_live_exchange_execution import live
from test_exact_full_close_v8_6 import runtime_mapping
from test_testnet_certification_v8 import FakeCertificationVenue
from test_exchange_migration import NOW,TEAM


@pytest.fixture
def qualification(live,monkeypatch):
    import exchange.testnet_certification as mod
    monkeypatch.setattr(mod,'TEAM',TEAM);monkeypatch.setattr(mod,'API',live.signer.address)
    runtime_mapping(live)
    live.fixture.book.update(levels=[[dict(px='82276',sz='.0578')],[dict(px='82672',sz='.0609')]])
    live.fixture.contexts=[dict(markPx='82424',oraclePx='82424',funding='.0001',openInterest='10')
                           for _ in live.fixture.metadata['universe']]
    live.fixture.active['markPx']='82424'
    prime_read_only_clock(live.market,live.clock,'par:BTC')
    request=OrderRequest('par:BTC','BUY','.0003','82713',tif='Ioc')
    context=live.provider.load(request)
    p=propose_qualification(context,live.client,'fixture-source','fixture-policy')
    a=QualificationApproval(p.identity,'SYNTHETIC_RISK_ACCEPTANCE_ONLY',NOW,NOW+300000,
                            True,True,True,True,True,True)
    auth=QualificationAuthorization(p,a,live.journal,clock_ms=lambda:live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    recovery=CertificationRecovery(live.account,live.journal,initial_start_ms=NOW)
    live.provider.reconciliation_ready=lambda:recovery.account_truth_ready
    executor=QualificationExecution(live.client,proposal=p,transport=live.transport,
        account=live.account,journal=live.journal,context_provider=live.provider,
        validator=live.validator,recovery=recovery,clock_health=live.clock,rate_limits=live.rate)
    live.executor=executor
    venue=FakeCertificationVenue(live,monkeypatch,auth)
    return SimpleNamespace(live=live,p=p,a=a,auth=auth,venue=venue,
                           sequence=QualificationSequence(executor,p,auth))


def test_qualification_round_trip_is_never_protection_certification(qualification):
    c=qualification;r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert r['final_flat'] and not r['normal_protection_certified'] and not r['certification_passed']
    assert not r['practice_ready'] and not r['live_ready'] and not r['organizer_whitelisting_confirmed']
    assert r['execution_mode']=='TESTNET_QUALIFICATION' and r['evidence_scope']=='OFFLINE_SIGNED_FIXTURE'
    assert len(c.venue.calls)==2 and not any('trigger' in a['orders'][0]['t'] for a in c.venue.calls)
    assert c.live.journal.control('qualification_entry_consumed')==c.p.identity
    assert D(r['realized_pnl']['net_realized_pnl'])<0
    proof=whitelist_trade_proof(c.sequence,r,actual_transport=False)
    assert not proof['fill_verified'] and not proof['final_flat_verified'] and proof['executed_notional'] is None


@pytest.mark.parametrize('quantity',['.0001','.0002','.0003'])
def test_all_possible_btc_partial_entries_have_exact_closure(qualification,quantity):
    c=qualification;c.venue.partial_entry=D(quantity)/D(c.p.quantity)
    r=c.sequence.run();assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert D(c.venue.calls[1]['orders'][0]['s'])==D(quantity)
    assert c.venue.calls[1]['orders'][0]['r'] is True and c.venue.calls[1]['orders'][0]['b'] is False
    assert r['final_flat'] and not r['protection_accepted']


@pytest.mark.parametrize('failure,expected',[
    ('entry_rejected','NO_FILL_VERIFIED'),('timeout_before','EMERGENCY_EXIT_REQUIRED'),
    ('timeout_after_fill','TRADE_CLOSED_RECONCILED'),('summary_without_fill','EMERGENCY_EXIT_REQUIRED'),
    ('disconnect_after_fill','EMERGENCY_EXIT_REQUIRED')])
def test_uncertain_entry_never_repeats_or_invents_fill(qualification,failure,expected):
    c=qualification;c.venue.fail=failure;r=c.sequence.run()
    assert r['status']==expected,r
    assert len([a for a in c.venue.calls if not a['orders'][0]['r']])==1
    if expected not in {'TRADE_CLOSED_RECONCILED','NO_FILL_VERIFIED'}:assert not r.get('final_flat',False)
    again=QualificationSequence(c.live.executor,c.p,c.auth).run()
    assert again['status']=='PREFLIGHT_BLOCKED' and len(c.venue.calls)<=2


def test_partial_exits_reconcile_remaining_exact_lot(qualification):
    c=qualification;c.venue.partial_exit=D('.66');r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert [D(a['orders'][0]['s']) for a in c.venue.calls]==[D('.0003'),D('.0003'),D('.0001')]
    assert r['final_flat']


@pytest.mark.parametrize('failure',['rejected','unknown','gap'])
def test_exit_failure_keeps_residual_and_operator_escalation(qualification,monkeypatch,failure):
    c=qualification;original=c.venue.transmit
    def transmit(payload):
        if payload['action']['orders'][0]['r']:
            if failure=='rejected':
                from test_live_exchange_execution import response
                c.auth.claim_transmission(payload['action']);c.venue.calls.append(payload['action'])
                return response({'error':'Order must have minimum value of $10.'})
            raise TimeoutError('OFFLINE_EXIT_UNKNOWN')
        result=original(payload)
        if failure=='gap':
            c.live.fixture.book['levels']=[[dict(px='75000',sz='1')],[dict(px='75001',sz='1')]]
        return result
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert c.live.account.get_position('par:BTC').quantity==D('.0003')
    assert not r.get('final_flat',False) and r['operator_action_required']
    assert len(c.venue.calls)<=3


@pytest.mark.parametrize('field',[
    'unverified_stop_risk_accepted','qualification_spread_limit_accepted',
    'possible_manual_residual_recovery_accepted','sole_signer_host_confirmed',
    'manually_verified_wallets','maximum_one_entry'])
def test_all_human_risk_and_identity_acknowledgements_required(qualification,field):
    c=qualification;c.auth.approval=replace(c.a,**{field:False})
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls and not c.live.transport.signed_payloads


@pytest.mark.parametrize('field,value',[('max_notional','50'),('quantity','.0004'),
    ('mode','LIVE'),('entry_side','SELL'),('entry_rule','MANUAL'),('qualification_spread_bps','51'),
    ('max_exit_attempts',3),('max_signed_actions',6),('asset_id',1),('network','mainnet'),
    ('protection_status','VERIFIED')])
def test_qualification_cannot_expand_proposal(qualification,field,value):
    with pytest.raises(ExchangeError):replace(qualification.p,**{field:value}).require()


@pytest.mark.parametrize('damage',['spread','stale_book','stale_account','depth','leverage','team',
    'fee','margin','changed_ask','held','oracle','metadata'])
def test_boundary_rechecks_fresh_market_and_account(qualification,damage):
    c=qualification;c.live.executor.recovery.recover()
    req=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc')
    ctx=c.live.provider.load(req)
    if damage=='spread':ctx=replace(ctx,quote=replace(ctx.quote,bid=D(82000),mid=(D(82000)+ctx.quote.ask)/2))
    if damage=='stale_book':ctx=replace(ctx,quote=replace(ctx.quote,timestamp_ms=NOW-5001))
    if damage=='stale_account':ctx=replace(ctx,account_ms=NOW-5001)
    if damage=='depth':ctx=replace(ctx,quote=replace(ctx.quote,bid_quantity=D('.0001')))
    if damage=='leverage':ctx=replace(ctx,active_asset=dict(ctx.active_asset,leverage={'type':'cross','value':20}))
    if damage=='team':ctx=replace(ctx,active_asset=dict(ctx.active_asset,user='0x'+'99'*20))
    if damage=='fee':ctx=replace(ctx,readiness=replace(ctx.readiness,fees={'userCrossRate':'.001'}))
    if damage=='margin':ctx=replace(ctx,active_asset=dict(ctx.active_asset,availableToTrade=['1','1']))
    if damage=='changed_ask':ctx=replace(ctx,quote=replace(ctx.quote,ask=D(82750),mid=(D(82750)+ctx.quote.bid)/2))
    if damage=='held':ctx=replace(ctx,positions={'par:BTC':object()})
    if damage=='oracle':ctx=replace(ctx,quote=replace(ctx.quote,oracle=D(81000)))
    if damage=='metadata':ctx=replace(ctx,spec=replace(ctx.spec,asset_id=2671000))
    with pytest.raises(ExchangeError):check_entry(ctx,req,c.p,NOW)
    assert not c.live.transport.signed_payloads


@pytest.mark.parametrize('symbol,decimals,asset,qty,floor',[
    ('par:ETH',4,2670001,'.009','2450'),('par:HYPE',2,2670002,'.29','82'),
    ('par:BTC',4,2670000,'.0003','40000')])
def test_unverified_long_close_shapes_still_block(symbol,decimals,asset,qty,floor):
    assert not residual_close_assessment(MarketSpec(symbol,decimals,20,asset),qty,floor)['ready']


def test_normal_protection_gate_remains_blocked(qualification):
    c=qualification
    with pytest.raises(ExchangeError,match='SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED'):
        require_safe_partial_path(c.live.client.market('par:BTC'),c.p)
    with pytest.raises(ExchangeError,match='STOP_UNVERIFIED'):
        c.sequence.e.protection._plan()


def test_restart_cannot_resume_or_create_second_entry(qualification):
    c=qualification;c.venue.fail='timeout_before';c.sequence.run()
    new_auth=QualificationAuthorization(c.p,c.a,c.live.journal,clock_ms=lambda:NOW,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    r=QualificationSequence(c.live.executor,c.p,new_auth).run()
    assert r['status']=='PREFLIGHT_BLOCKED' and len(c.venue.calls)==1
    path=c.live.journal.path
    assert c.live.journal.control('qualification_entry_consumed')==c.p.identity
    reopened=ExecutionJournal(path,session_id='offline:test',team_address=TEAM)
    try:assert reopened.control('qualification_entry_consumed')==c.p.identity
    finally:reopened.close()


def test_replayed_wire_is_consumed_before_retransmission(qualification):
    c=qualification;c.sequence.run();c.auth.revoked=False
    c.live.journal.db.execute('DELETE FROM controls WHERE name=?',('certification_completed:'+c.p.identity,))
    with pytest.raises(ExchangeError,match='ALREADY_CONSUMED'):
        c.auth.claim_transmission(c.venue.calls[0])


def test_synthetic_report_cannot_become_actual_proof(qualification):
    c=qualification;r=c.sequence.run()
    p=whitelist_trade_proof(c.sequence,r,actual_transport=True)
    assert not p['fill_verified']  # Actual transport flag alone cannot upgrade scope.
    assert not p['final_flat_verified']
    assert p['executed_notional'] is None
