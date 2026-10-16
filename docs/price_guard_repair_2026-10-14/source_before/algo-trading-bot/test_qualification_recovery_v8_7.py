"""V8.7 regressions: synthetic public inputs, ephemeral fixtures; actual HTTP forbidden."""
from dataclasses import replace
from decimal import Decimal as D
import pytest

from exchange.base_exchange import ExchangeError
from exchange.certification_runtime import CertificationContextProvider
from exchange.order_lifecycle import OrderRequest
import exchange.testnet_qualification as module
from test_testnet_qualification import qualification
from test_live_exchange_execution import live
from test_exchange_migration import NOW


def context(c):
    c.live.executor.recovery.recover()
    req=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc')
    return c.live.provider.load(req)


def test_three_lots_fail_but_two_lots_are_selected(qualification):
    c=qualification;ctx=context(c)
    ctx=replace(ctx,quote=replace(ctx.quote,bid_quantity=D('.006'),ask_quantity=D('.0025')))
    with pytest.raises(ExchangeError,match='BOTH_SIDES_DEPTH_EXCEEDED'):
        module.check_entry(ctx,OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'),c.p,NOW)
    p=module.propose_qualification(ctx,c.live.client,'fixture-source','fixture-policy')
    assert D(p.quantity)==D('.0002')
    assert D(p.quantity)*D(p.entry_limit)>=10


def test_margin_bound_selects_smaller_valid_size(qualification):
    c=qualification;ctx=context(c)
    ctx=replace(ctx,active_asset=dict(ctx.active_asset,availableToTrade=['17','17']))
    p=module.propose_qualification(ctx,c.live.client,'fixture-source','fixture-policy')
    assert D(p.quantity)==D('.0002')


def test_stale_clock_is_recovered_before_readiness_snapshot(qualification,monkeypatch):
    c=qualification;clock=c.live.clock
    clock.observed_ms=NOW-31001
    original=c.live.market.get_orderbook;calls=[]
    def advancing(symbol):
        c.live.fixture.now+=1;c.live.fixture.book['time']=c.live.fixture.now
        calls.append(symbol);return original(symbol)
    monkeypatch.setattr(c.live.market,'get_orderbook',advancing)
    provider_type=getattr(module,'QualificationContextProvider',CertificationContextProvider)
    provider=provider_type(c.live.market,c.live.account,c.live.signer.address,clock,c.live.rate,
        reconciliation_ready=lambda:True,feed_ready=lambda:True)
    provider.trigger_aware=True
    ctx=provider.load(OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'))
    assert clock.healthy
    assert ctx.readiness.clock_healthy and ctx.readiness.account_ready


@pytest.mark.parametrize('bid,ask,expected',[
    ('.01','.01','.0003'),('.0025','.01','.0002'),('.01','.0025','.0002'),
    ('.0003','.01',None),('.01','.0003',None),('.0019','.01',None),('0','.01',None),('.01','0',None)])
def test_solver_respects_both_book_sides_and_never_rounds_up(qualification,bid,ask,expected):
    c=qualification;ctx=context(c);ctx=replace(ctx,quote=replace(ctx.quote,bid_quantity=D(bid),ask_quantity=D(ask)))
    s=module.find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    assert s['ready']==(expected is not None)
    if expected:
        assert D(s['selected_quantity'])==D(expected)
        assert D(s['bid_depth_utilization'])<=D('.1') and D(s['ask_depth_utilization'])<=D('.1')
        assert 10<=D(s['entry_notional'])<=25
    else:assert not s.get('proposal')
    assert not c.live.transport.signed_payloads


def test_two_lots_below_opening_minimum_are_rejected(qualification):
    c=qualification;ctx=context(c)
    # Actual runtime lot stays .0001; at this isolated price two lots < $10.
    q=replace(ctx.quote,bid=D('39990'),ask=D('40000'),mid=D('39995'),mark=D('40000'),oracle=D('40000'),
              bid_quantity=D('.0025'),ask_quantity=D('.0025'))
    s=module.find_largest_safe_qualification_quantity(replace(ctx,quote=q),c.live.client,'fixture-source','fixture-policy')
    assert not s['ready'] and s['rejection']=='QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS'
    assert D(s['largest_bounded_quantity'])==D('.0002')


@pytest.mark.parametrize('damage',[
    'stale_quote','stale_account','stale_readiness','stale_mark','held','spread','oracle','team','api',
    'wrong_active_team','leverage','zero_margin','metadata','feed','unreconciled'])
def test_solver_cannot_use_smaller_size_to_evade_non_size_gates(qualification,damage):
    c=qualification;ctx=context(c)
    if damage=='stale_quote':ctx=replace(ctx,quote=replace(ctx.quote,timestamp_ms=NOW-5001))
    if damage=='stale_account':ctx=replace(ctx,account_ms=NOW-5001)
    if damage=='stale_readiness':ctx=replace(ctx,readiness=replace(ctx.readiness,observed_ms=NOW-5001))
    if damage=='stale_mark':ctx=replace(ctx,quote=replace(ctx.quote,mark_timestamp_ms=NOW-5001))
    if damage=='held':ctx=replace(ctx,positions={'par:BTC':object()})
    if damage=='spread':ctx=replace(ctx,quote=replace(ctx.quote,bid=D(81000),mid=(D(81000)+ctx.quote.ask)/2))
    if damage=='oracle':ctx=replace(ctx,quote=replace(ctx.quote,oracle=D(79000)))
    if damage=='team':ctx=replace(ctx,readiness=replace(ctx.readiness,team_address='0x'+'99'*20))
    if damage=='api':ctx=replace(ctx,readiness=replace(ctx.readiness,signer_address='0x'+'99'*20))
    if damage=='wrong_active_team':ctx=replace(ctx,active_asset=dict(ctx.active_asset,user='0x'+'99'*20))
    if damage=='leverage':ctx=replace(ctx,active_asset=dict(ctx.active_asset,leverage=dict(type='cross',value=20)))
    if damage=='zero_margin':ctx=replace(ctx,active_asset=dict(ctx.active_asset,availableToTrade=['0','0']))
    if damage=='metadata':ctx=replace(ctx,metadata_hash='changed')
    if damage=='feed':ctx=replace(ctx,feed_ready=False)
    if damage=='unreconciled':ctx=replace(ctx,reconciled=False)
    s=module.find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    assert not s['ready'];assert not c.live.transport.signed_payloads


@pytest.mark.parametrize('symbol',['par:ETH','par:HYPE'])
def test_other_markets_do_not_inherit_btc_sell_evidence(qualification,symbol):
    c=qualification;ctx=context(c);spec=c.live.client.market(symbol)
    price=D(2500) if symbol.endswith('ETH') else D(82)
    quote=replace(ctx.quote,symbol=symbol,bid=price,ask=price+D('.01'),mid=price+D('.005'),mark=price,oracle=price,
                  bid_quantity=D(10),ask_quantity=D(10))
    ctx=replace(ctx,spec=spec,quote=quote,active_asset=dict(ctx.active_asset,coin=symbol))
    s=module.find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    assert not s['ready'] and s['rejection']=='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL'


def test_changed_btc_precision_cannot_reuse_one_lot_scope(qualification):
    c=qualification;ctx=context(c)
    ctx=replace(ctx,spec=replace(ctx.spec,size_decimals=5))
    s=module.find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    assert not s['ready'];assert not c.live.transport.signed_payloads


def provider(c,**kwargs):
    return module.QualificationContextProvider(c.live.market,c.live.account,c.live.signer.address,c.live.clock,c.live.rate,
        reconciliation_ready=lambda:True,feed_ready=lambda:True,**kwargs)


def advance_books(c,monkeypatch,wrong_count=0):
    original=c.live.market.get_orderbook;reads=[]
    def book(symbol):
        c.live.fixture.now+=1;c.live.fixture.book['time']=c.live.fixture.now
        result=original(symbol);reads.append(symbol)
        return replace(result,timestamp_ms=result.timestamp_ms-50000) if len(reads)<=wrong_count else result
    monkeypatch.setattr(c.live.market,'get_orderbook',book);return reads


def test_clock_unhealthy_then_genuinely_recovers_with_bounded_reads(qualification,monkeypatch):
    c=qualification;reads=advance_books(c,monkeypatch,wrong_count=1);waits=[]
    p=provider(c,wait=waits.append)
    ctx=p.load(OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'))
    assert ctx.readiness.account_ready and c.live.clock.healthy and len(reads)<=6
    assert len(p.observations)==2 and p.observations[0]['result']=='QUALIFICATION_CLOCK_NOT_HEALTHY'
    assert p.observations[1]['result']=='CONSISTENT_FRESH_CONTEXT' and waits==[.25]


def test_clock_unhealthy_stays_blocked_and_is_not_overwritten(qualification,monkeypatch):
    c=qualification;reads=advance_books(c,monkeypatch,wrong_count=100);p=provider(c,wait=lambda _:None)
    with pytest.raises(ExchangeError,match='CLOCK_NOT_HEALTHY'):
        p.load(OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'))
    assert len(reads)==4 and len(p.observations)==2 and not c.live.clock.healthy
    assert not c.live.transport.signed_payloads


@pytest.mark.parametrize('stale',['account','readiness','book','mark'])
def test_inconsistent_clock_account_quote_pair_has_only_one_retry(qualification,monkeypatch,stale):
    c=qualification;ctx=context(c)
    if stale=='account':ctx=replace(ctx,account_ms=NOW-5001)
    if stale=='readiness':ctx=replace(ctx,readiness=replace(ctx.readiness,observed_ms=NOW-5001))
    if stale=='book':ctx=replace(ctx,quote=replace(ctx.quote,timestamp_ms=NOW-5001))
    if stale=='mark':ctx=replace(ctx,quote=replace(ctx.quote,mark_timestamp_ms=NOW-5001))
    monkeypatch.setattr(CertificationContextProvider,'load',lambda *a,**k:ctx)
    p=provider(c,wait=lambda _:None)
    with pytest.raises(ExchangeError,match='PAIR_NOT_READY'):
        p.load(OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'))
    assert len(p.observations)==2


def test_budget_wait_precedes_clock_and_reconciliation(qualification,monkeypatch):
    c=qualification;events=[];blocked=[True]
    monkeypatch.setattr(c.live.rate,'_usage',lambda:1000 if blocked[0] else 0)
    reads=advance_books(c,monkeypatch)
    def wait(seconds):events.append('budget_wait');blocked[0]=False
    def reconcile():events.append('reconcile');assert c.live.clock.healthy;return type('Ready',(),{'ready':True})()
    p=provider(c,wait=wait,reconcile_before_load=reconcile)
    ctx=p.load(OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc'))
    assert ctx.readiness.account_ready and events==['budget_wait','reconcile'] and len(reads)==4
    assert p.observations[0]['reconciled_ms']>=p.observations[0]['clock_synchronized']['last_reference_ms']


def install_proposal(c,p):
    c.p=p;c.a=replace(c.a,proposal_hash=p.identity)
    c.auth=module.QualificationAuthorization(p,c.a,c.live.journal,clock_ms=lambda:c.live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    c.venue.auth=c.auth;c.live.executor.proposal=p
    c.sequence=module.QualificationSequence(c.live.executor,p,c.auth)


@pytest.mark.parametrize('entry_fraction,exit_fraction',[(D(1),D(1)),(D('.5'),D(1)),(D(1),D('.5'))])
def test_dynamic_two_lot_entry_full_partial_and_residual_exit(qualification,monkeypatch,entry_fraction,exit_fraction):
    c=qualification;ctx=context(c);ctx=replace(ctx,quote=replace(ctx.quote,ask_quantity=D('.0025')))
    p=module.propose_qualification(ctx,c.live.client,'fixture-source','fixture-policy');install_proposal(c,p)
    c.live.fixture.book['levels'][1][0]['sz']='.0025'
    c.venue.partial_entry=entry_fraction;c.venue.partial_exit=exit_fraction
    original=c.venue.transmit
    def transmit(payload):
        result=original(payload)
        if payload['action']['orders'][0]['r']:c.venue.partial_exit=D(1)
        return result
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run();assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert r['final_flat'] and 'ENTRY_FILLED' in r['qualification_stages'] and 'EXIT_RECONCILED' in r['qualification_stages']
    assert c.venue.calls[0]['orders'][0]['s']=='0.0002'
    assert all(a['orders'][0]['r'] is True and a['orders'][0]['b'] is False for a in c.venue.calls[1:])
    assert len(c.venue.calls)<=3 and not r['normal_protection_certified']


def test_second_exit_without_fill_keeps_one_lot_and_stops(qualification):
    c=qualification;ctx=context(c);ctx=replace(ctx,quote=replace(ctx.quote,ask_quantity=D('.0025')))
    install_proposal(c,module.propose_qualification(ctx,c.live.client,'fixture-source','fixture-policy'))
    c.venue.partial_exit=D('.5')
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert len(c.venue.calls)==3 and c.live.account.get_position(c.p.symbol).quantity==D('.0001')
    assert not r.get('final_flat',False) and c.auth.revoked


def test_execution_composition_uses_ordered_provider_without_guard_revocation(qualification):
    c=qualification;c.live.executor.recovery.recover()
    c.live.executor.context_provider=provider(c)
    c.live.executor.context_provider.reconciliation_ready=lambda:c.live.executor.recovery.account_truth_ready
    r=c.sequence.run();assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert r['final_flat'] and len(c.venue.calls)==2


def test_changed_liquidity_blocks_already_prepared_size_without_resizing(qualification):
    c=qualification;c.live.fixture.book['levels'][1][0]['sz']='.0025'
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert not c.venue.calls and not c.live.transport.signed_payloads
    # It is a proposal review failure, not permission to replace .0003 by .0002.
    assert c.live.journal.control('qualification_entry_consumed') is None


def test_no_fill_consumes_only_one_entry_and_never_qualifies(qualification):
    c=qualification;c.venue.partial_entry=D(0);r=c.sequence.run()
    assert r['status']=='NO_FILL_VERIFIED' and r['final_flat'] and len(c.venue.calls)==1
    assert 'ENTRY_NOT_FILLED' in r['qualification_stages'] and 'ENTRY_FILLED' not in r['qualification_stages']
    proof=module.whitelist_trade_proof(c.sequence,r,actual_transport=False)
    assert not proof['fill_verified'] and proof['executed_notional'] is None


def test_approval_expiry_after_entry_halts_writes_preserving_actual_fixture_exposure(qualification,monkeypatch):
    c=qualification;original=c.venue.transmit
    def transmit(payload):
        result=original(payload);c.live.fixture.now+=300001;c.live.fixture.book['time']=c.live.fixture.now
        return result
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert len(c.venue.calls)==1 and c.live.account.get_position(c.p.symbol).quantity==D(c.p.quantity)
    assert not r.get('final_flat',False) and r['recovery_steps'] and c.auth.revoked


@pytest.mark.parametrize('damage',['expired_proposal','expired_approval','wrong_hash','wrong_wallet','wrong_api','source','policy'])
def test_exact_authorization_failures_never_sign(qualification,damage):
    c=qualification
    if damage=='expired_proposal':c.auth.approval=replace(c.a,approved_ms=NOW+300001,expires_ms=NOW+600001);c.live.fixture.now=NOW+300001
    if damage=='expired_approval':c.live.fixture.now=NOW+300001
    if damage=='wrong_hash':c.auth.approval=replace(c.a,proposal_hash='wrong')
    if damage=='wrong_wallet':c.auth.proposal=replace(c.p,team_wallet='0x'+'99'*20)
    if damage=='wrong_api':c.auth.proposal=replace(c.p,api_wallet='0x'+'99'*20)
    if damage=='source':c.auth.source_hash=lambda:'changed'
    if damage=='policy':c.auth.policy_hash=lambda:'changed'
    r=c.sequence.run();assert r['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls and not c.live.transport.signed_payloads


@pytest.mark.parametrize('damage',['no_entry','wrong_oid','wrong_side','wrong_size','no_actual_transport','wrong_scope'])
def test_whitelist_proof_requires_matched_entry_and_actual_evidence_scope(qualification,damage):
    c=qualification;r=c.sequence.run();r['evidence_scope']='ACTUAL_TESTNET_ACCOUNT'
    row=c.live.journal.intents()[0]
    if damage=='no_entry':c.live.journal.db.execute('DELETE FROM intents WHERE intent_key=?',(row['intent_key'],))
    if damage=='wrong_oid':c.live.journal.update(row['intent_key'],row['state'],NOW,oid='999999')
    if damage=='wrong_side':
        c.live.executor.recovery.state.fills={k:replace(f,side='SELL') if f.side=='BUY' else f for k,f in c.live.executor.recovery.state.fills.items()}
    if damage=='wrong_size':
        c.live.executor.recovery.state.fills={k:replace(f,quantity=D('.0001')) if f.side=='BUY' else f for k,f in c.live.executor.recovery.state.fills.items()}
    if damage=='wrong_scope':r['evidence_scope']='OFFLINE_SIGNED_FIXTURE'
    p=module.whitelist_trade_proof(c.sequence,r,actual_transport=damage!='no_actual_transport')
    assert not p['fill_verified'] and p['executed_notional'] is None


def test_matched_reported_fill_proof_logic_offline_not_real_qualification(qualification):
    c=qualification;r=c.sequence.run()
    # Exercise the positive pure predicate with exchange-shaped fixture records;
    # this test has no actual transport and certifies no funded account.
    hypothetical=dict(r,evidence_scope='ACTUAL_TESTNET_ACCOUNT')
    p=module.whitelist_trade_proof(c.sequence,hypothetical,actual_transport=True)
    assert p['fill_verified'] and p['final_flat_verified'] and D(p['executed_notional'])==D(c.p.quantity)*D(c.p.entry_limit)
    assert p['fill_ids'] and p['timestamps_ms'] and not p['organizer_whitelisting_confirmed']
    actual_fixture=module.whitelist_trade_proof(c.sequence,r,actual_transport=False)
    assert not actual_fixture['fill_verified'] and not actual_fixture['final_flat_verified']


def launcher():
    import importlib.util,sys
    from pathlib import Path
    name='qualification_launcher_v8_7_test';path=Path(__file__).resolve().parents[1]/'scripts/run_testnet_qualification.py'
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod


def test_terminal_summary_exposes_limits_without_authorization(qualification,tmp_path):
    c=qualification;ctx=context(c);s=module.find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    r=dict(status='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED',selected_proposal=s['proposal'],
        selected_proposal_hash=module.QualificationProposal(**s['proposal']).identity,
        candidates=[dict(symbol=c.p.symbol,sizing=s,spread_bps=s['spread_bps'],residual_close_scope=s['residual_close_scope'])],
        test_receipt='OFFLINE_FIXTURE_ONLY',notional=s['entry_notional'],approval_deadline_ist='OFFLINE_FIXTURE_ONLY',
        estimated_round_trip_fee_at_reviewed_limits='0.05',expected_immediate_exit_limit=s['estimated_exit_limit'])
    result=launcher().preparation_summary(r,tmp_path)
    assert result['status']=='QUALIFICATION_PROPOSAL_READY' and result['qualification_state']=='AWAITING_HUMAN_APPROVAL'
    assert result['proposal_file']==str(tmp_path/'proposal.json') and result['approval_template']==str(tmp_path/'approval_REQUIRED_UNFILLED.json')
    assert result['maximum_notional']=='25' and result['entry_attempts']==1 and result['exit_attempts']==2
    assert result['qualification_spread_ceiling_bps']==50 and result['production_spread_ceiling_bps']==15
    assert not result['actual_order_authorization_supplied'] and not result['protection_verified']


@pytest.mark.parametrize('damage',['hash','xml_hash','totals','baseline','phase0','freeze','source_after','missing_xml'])
def test_full_receipt_source_counts_and_safety_checks_are_verified(qualification,tmp_path,monkeypatch,damage):
    import json,hashlib
    import exchange.paper_operations as operations
    monkeypatch.setattr(operations,'active_source_hash',lambda root:'fixture-source')
    totals=dict(tests=1682,failures=0,errors=0,skipped=0)
    receipt=dict(passed=True,source_hash='fixture-source',source_hash_after='fixture-source',totals=totals,
        checks_before={n:dict(exit_code=0,result=dict(passed=True)) for n in ('phase0','strategy_freeze')})
    xml=tmp_path/'regression.xml';xml.write_text('<testsuites><testsuite tests="1682" failures="0" errors="0" skipped="0"/></testsuites>')
    receipt['xml_sha256']=hashlib.sha256(xml.read_bytes()).hexdigest()
    if damage=='hash':receipt['source_hash']='other'
    if damage=='xml_hash':receipt['xml_sha256']='other'
    if damage=='totals':receipt['totals']=dict(totals,tests=9999)
    if damage=='baseline':
        xml.write_text('<testsuites><testsuite tests="1600" failures="0" errors="0" skipped="0"/></testsuites>')
        receipt['xml_sha256']=hashlib.sha256(xml.read_bytes()).hexdigest();receipt['totals']=dict(totals,tests=1600)
    if damage=='phase0':receipt['checks_before']['phase0']['result']['passed']=False
    if damage=='freeze':receipt['checks_before']['strategy_freeze']['exit_code']=1
    if damage=='source_after':receipt['source_hash_after']='other'
    if damage=='missing_xml':xml.unlink()
    p=tmp_path/'test_receipt.json';p.write_text(json.dumps(receipt))
    with pytest.raises(ExchangeError,match='SOURCE_BOUND_FULL_REGRESSION_REQUIRED'):
        module.require_qualification_regression(tmp_path,p)


@pytest.mark.parametrize('damage',['missing_orders','missing_positions','failed_reconciliation','missing_time','position','order'])
def test_preflight_flat_needs_both_authoritative_reads_and_reconciliation(damage):
    r=dict(final_positions=[],final_orders=[],account_observed_ms=NOW,final_reconciliation=dict(ready=True))
    if damage=='missing_orders':del r['final_orders']
    if damage=='missing_positions':del r['final_positions']
    if damage=='failed_reconciliation':r['final_reconciliation']['ready']=False
    if damage=='missing_time':del r['account_observed_ms']
    if damage=='position':r['final_positions']=[{'quantity':'.0001'}]
    if damage=='order':r['final_orders']=[{'oid':1}]
    assert not launcher().preflight_flat_proven(r)


@pytest.mark.parametrize('ask_depth,expected',[(D('.0025'),D('.0002')),(D('.0003'),None)])
def test_real_prepare_composition_offline_is_read_only_and_finally_refreshed(qualification,tmp_path,monkeypatch,ask_depth,expected):
    from exchange.execution_safety import ClockHealthMonitor,HyperliquidRateLimitManager
    c=qualification;mod=launcher();c.live.fixture.book['levels'][1][0]['sz']=str(ask_depth)
    # Deterministic fixture limiter/clock, not evidence about the actual venue.
    created=[];rates=[]
    def rate(journal,**kwargs):
        created.append(journal)
        result=HyperliquidRateLimitManager(journal,clock_ms=lambda:c.live.fixture.now,**kwargs)
        monkeypatch.setattr(result,'_usage',lambda:123);rates.append(result);return result
    def client(**kwargs):c.live.client.rate_limits=kwargs['rate_limits'];return c.live.client
    monkeypatch.setattr(mod,'HyperliquidRateLimitManager',rate)
    monkeypatch.setattr(mod,'HyperliquidClient',client)
    monkeypatch.setattr(mod,'ClockHealthMonitor',lambda **kw:ClockHealthMonitor(monotonic_ms=lambda:c.live.fixture.now,**kw))
    monkeypatch.setattr(mod,'current_test_receipt',lambda *args:tmp_path/'OFFLINE_RECEIPT_ONLY')
    original_read=c.live.client.transport
    def advancing_public_read(payload):
        if payload['type']=='l2Book':
            c.live.fixture.now+=1;c.live.fixture.book['time']=c.live.fixture.now
        return original_read(payload)
    # prepare constructs its own market adapter, so advance the shared public
    # fixture rather than only the earlier adapter used by the fixture setup.
    monkeypatch.setattr(c.live.client,'transport',advancing_public_read)
    out=tmp_path/'read_only'
    r=mod.prepare(out)
    assert len(created)==1 and r['public_read_weight_before_reopen']==r['public_read_weight_after_reopen']==123
    assert not c.venue.calls and not c.live.transport.signed_payloads
    assert r['actual_action_rows']==dict(intents=0,api_actions=0,signed_management=0)
    import json
    proof=json.loads((out/'WHITELIST_TRADE_PROOF.json').read_text())
    assert not proof['fill_verified'] and not proof['final_flat_verified']
    assert proof['preflight_flat_observed']
    if expected:
        assert r['status']=='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED',r
        assert D(r['selected_proposal']['quantity'])==expected
        row=next(x for x in r['candidates'] if x['symbol']=='par:BTC')
        assert row['proposal']['observed_ms']>row['initial_review']['proposal']['observed_ms']
        ack=json.loads((out/'approval_REQUIRED_UNFILLED.json').read_text())
        assert ack['operator_approval']=='' and ack['unverified_stop_risk_accepted'] is False
    else:
        assert r['status']=='QUALIFICATION_LOCKED' and not (out/'proposal.json').exists()
        assert next(x for x in r['candidates'] if x['symbol']=='par:BTC')['sizing']['largest_bounded_quantity']=='0.0000'


def test_invalid_regression_locks_prepare_before_client_or_signer(tmp_path,monkeypatch):
    mod=launcher()
    monkeypatch.setattr(mod,'HyperliquidClient',lambda **kw:pytest.fail('NO_CLIENT_BEFORE_VALID_RELEASE'))
    r=mod.prepare(tmp_path/'blocked',tmp_path/'NONEXISTENT_RECEIPT')
    assert r['status']=='QUALIFICATION_LOCKED' and r['blocker']=='SOURCE_BOUND_FULL_REGRESSION_REQUIRED'
    assert r['actual_wallet_signatures']==r['exchange_submissions']==0


def test_valid_full_receipt_is_reused_for_identical_source(tmp_path,monkeypatch):
    import json,hashlib
    import exchange.paper_operations as operations
    monkeypatch.setattr(operations,'active_source_hash',lambda root:'fixture-source')
    xml=tmp_path/'regression.xml';xml.write_text('<testsuites><testsuite tests="1682" failures="0" errors="0" skipped="0"/></testsuites>')
    receipt=dict(passed=True,source_hash='fixture-source',source_hash_after='fixture-source',
        totals=dict(tests=1682,failures=0,errors=0,skipped=0),xml_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),
        checks_before={n:dict(exit_code=0,result=dict(passed=True)) for n in ('phase0','strategy_freeze')})
    p=tmp_path/'test_receipt.json';p.write_text(json.dumps(receipt))
    assert module.require_qualification_regression(tmp_path,p)==p.resolve()
