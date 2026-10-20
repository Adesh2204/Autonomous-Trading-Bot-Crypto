"""Synthetic failure injection for account locks/compliance; exchange HTTP denied."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from decimal import Decimal as D
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from exchange.base_exchange import ExchangeError, Position
from exchange.compliance_guard import ActionPermit, CompliancePolicy
from exchange.compliance_report import compliance_summary, export_compliance
from exchange.execution_journal import ExecutionJournal
from exchange.order_lifecycle import OrderRequest, OrderState
from exchange.single_position_guard import AccountExecutionLease, SinglePositionGuard
from test_live_exchange_execution import live, permission, response
from test_production_reliability import ProtectionVenue, live_session, protected
from test_exchange_migration import NOW, TEAM


def request(*, symbol='par:BTC', side='BUY', qty='.2', price='100', reduce=False, key=None):
    return OrderRequest(symbol,side,qty,price,reduce_only=reduce,client_order_id=key)


def evaluate(live, req=None, *, context=None, token=None, modify_oid=None):
    req=req or request()
    context=context or live.provider.load(req,critical=req.reduce_only)
    token=token or permission(req,reason='VERIFIED_EXIT' if req.reduce_only else None)
    pos=live.executor.position_guard.evaluate(req,context,NOW)
    return live.executor.compliance_guard.evaluate(req,context,token,pos,modify_oid=modify_oid)


def events(live, kind):
    return [json.loads(r['data']) for r in live.journal.db.execute('SELECT data FROM events WHERE kind=?',(kind,))]


def test_restart_starts_unknown_even_after_flat_checkpoint(live):
    guard=live.executor.position_guard
    assert guard.state.value=='UNKNOWN'
    assert evaluate(live).allowed
    restarted=SinglePositionGuard(live.journal,clock_ms=lambda:NOW)
    assert restarted.state.value=='UNKNOWN' and not restarted.report()['entry_permission']
    restarted.reconcile(live.provider.load(request()),NOW)
    assert restarted.state.value=='FLAT'


@pytest.mark.parametrize('held,side,symbol',[('.2','BUY','par:BTC'),('.2','SELL','par:ETH'),
    ('-.2','BUY','par:ETH'),('-.2','SELL','par:BTC'),('.0001','BUY','par:ETH')])
def test_any_actual_exposure_blocks_second_entry(live,held,side,symbol):
    live.fixture.position(held)
    req=request(symbol=symbol,side=side)
    decision=evaluate(live,req)
    assert not decision.allowed and decision.code=='POSITION_LIMIT'
    assert not live.transport.signed_payloads


def test_first_valid_entry_has_durable_lock_and_complete_audit(live):
    req=request(key='first')
    live.transport.responses=[response({'resting':{'oid':11}})]
    order=live.executor.submit(req,permission=permission(req))
    assert order.state==OrderState.OPEN
    assert live.journal.control('global_position_lock')['entry_key']=='first'
    audit=events(live,'COMPLIANCE_ACTION_AUTHORIZED')[0]
    assert audit['cloid']==order.cloid and audit['candidate_id']=='candidate:1'
    assert audit['order_classification']=='STRATEGY_ENTRY'
    decision=events(live,'COMPLIANCE_DECISION')[0]
    assert decision['provenance']['risk_decision']['allowed'] and decision['provenance']['execution_decision']['allowed']
    assert {'bid','ask','mid','mark','oracle'}==set(decision['checks']['reference_prices'])


@pytest.mark.parametrize('state',['PREPARED','SUBMITTED','UNKNOWN','OPEN','CANCEL_PENDING','PARTIALLY_FILLED'])
def test_unresolved_entry_never_allows_next_symbol(live,state):
    req=request(key='pending')
    ctx=live.provider.load(req)
    live.executor.position_guard.reconcile(ctx,NOW)
    live.journal.reserve('pending',asdict(req),'first',NOW,position_guard=live.executor.position_guard)
    live.journal.update('pending',state,NOW)
    assert evaluate(live,request(symbol='par:ETH')).code=='POSITION_LIMIT'


def test_filled_response_without_actual_fills_does_not_unlock(live):
    req=request(key='summary_only')
    live.transport.responses=[response({'filled':{'oid':11,'totalSz':'.2','avgPx':'100'}})]
    assert live.executor.submit(req,permission=permission(req)).state==OrderState.FILLED
    live.executor.entries_paused=False
    decision=evaluate(live,request(symbol='par:ETH'))
    assert decision.code=='UNKNOWN_ACCOUNT_STATE'
    assert live.executor.position_guard.reason=='ACTUAL_FILL_FLAT_EVIDENCE_REQUIRED'


def test_partial_exit_remains_occupied_then_reconciled_flat_unlocks(live,monkeypatch):
    from test_crypto_paper_infrastructure import signal_scan
    venue=ProtectionVenue(live,monkeypatch)
    owner,protection=live_session(live,venue)
    owner.startup();owner.consume_scan(signal_scan(NOW))
    initial=live.account.get_position('par:BTC').quantity
    venue.close_fraction=D('.5')
    owner._close('par:BTC','Target Hit')
    assert 0<live.account.get_position('par:BTC').quantity<initial
    assert not evaluate(live,request(symbol='par:ETH')).allowed
    venue.close_fraction=D(1)
    owner._close('par:BTC','Target Hit')
    assert not live.account.get_positions() and not live.account.get_frontend_open_orders()
    ctx=live.provider.load(request())
    ctx=replace(ctx,fills=tuple(owner.recovery.state.fills.values()))
    live.executor.position_guard.reconcile(ctx,NOW)
    assert live.executor.position_guard.state.value=='FLAT'
    assert not owner.managers['par:BTC'].has_open_position


def test_exit_pending_and_obsolete_protection_keep_account_locked(live):
    live.fixture.position('.2')
    req=request(side='SELL',reduce=True,key='exit')
    row,_=live.journal.reserve('exit',asdict(req),'position:1',NOW)
    live.journal.update('exit','OPEN',NOW,oid='11')
    live.fixture.orders=[dict(coin='par:BTC',oid=11,side='A',sz='.2',limitPx='100',reduceOnly=True)]
    assert evaluate(live,request(symbol='par:ETH')).code=='POSITION_LIMIT'
    assert live.executor.position_guard.state.value=='EXIT_PENDING'
    live.fixture.position('0')
    live.journal.update('exit','CANCELLED',NOW)
    assert not evaluate(live,request(symbol='par:ETH')).allowed
    live.fixture.orders=[]
    assert evaluate(live,request(symbol='par:ETH')).allowed


@pytest.mark.parametrize('damage',['reconciliation','old_account','future_account','unready'])
def test_unknown_account_cannot_enter(live,damage):
    ctx=live.provider.load(request())
    ctx=replace(ctx,reconciled=False) if damage=='reconciliation' else replace(ctx,account_ms=NOW-5001) if damage=='old_account' else replace(ctx,account_ms=NOW+1) if damage=='future_account' else replace(ctx,readiness=replace(ctx.readiness,status='ACCOUNT_NOT_READY',reasons=('UNVERIFIED',)))
    assert evaluate(live,context=ctx).code=='UNKNOWN_ACCOUNT_STATE'


def test_two_actual_positions_are_detected_and_paused(live):
    ctx=live.provider.load(request())
    positions={s:Position(s,D('.2'),D(100),D(0),D(10),None) for s in ('par:BTC','par:ETH')}
    ctx=replace(ctx,positions=positions)
    assert evaluate(live,context=ctx).code=='UNKNOWN_ACCOUNT_STATE'
    assert live.executor.position_guard.state.value=='RECOVERING'
    assert live.executor.position_guard.reason=='UNEXPECTED_CONCURRENT_EXPOSURE'


def test_disconnect_revokes_lease_before_an_entry_can_sign(live):
    from exchange.live_account_stream import LiveAccountStream
    from exchange.live_recovery import LiveAccountRecovery
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    recovery.position_guard=live.executor.position_guard
    live.executor.recovery=recovery
    recovery.recover()
    stream=LiveAccountStream(TEAM,recovery,live.executor,clock_ms=lambda:NOW,connector=lambda *_:None)
    stream.disconnect()
    assert live.executor.position_guard.state.value=='UNKNOWN' and live.executor.entries_paused
    assert not recovery.last_report.ready


def test_simultaneous_reservations_on_two_sqlite_connections_only_one_wins(live):
    ctx=live.provider.load(request())
    other=ExecutionJournal(live.journal.path,session_id='offline:test',team_address=TEAM)
    guard2=SinglePositionGuard(other,clock_ms=lambda:NOW)
    live.executor.position_guard.reconcile(ctx,NOW)
    barrier=threading.Barrier(2)
    def attempt(args):
        journal,guard,key=args
        barrier.wait()
        try:
            journal.reserve(key,asdict(request(key=key)),key,NOW,position_guard=guard)
            return 'RESERVED'
        except ExchangeError as exc:
            return str(exc)
    try:
        with ThreadPoolExecutor(2) as pool:
            result=list(pool.map(attempt,[(live.journal,live.executor.position_guard,'a'),(other,guard2,'b')]))
        assert sorted(result)==['POSITION_LIMIT','RESERVED']
        assert len(live.journal.intents())==1
    finally:
        other.close()


def test_account_change_during_preflight_invalidates_snapshot(live,monkeypatch):
    original=live.account.get_positions
    count=[0]
    def changing():
        count[0]+=1
        if count[0]==3:live.fixture.position('.2')
        return original()
    monkeypatch.setattr(live.account,'get_positions',changing)
    with pytest.raises(ExchangeError,match='ACCOUNT_CHANGED_DURING_PREFLIGHT'):
        live.provider.load(request())
    assert not live.transport.signed_payloads


def test_generation_change_during_context_read_cannot_overwrite_entry_lock(live):
    guard=live.executor.position_guard
    ctx=live.provider.load(request())
    generation=live.journal.control('global_position_lock')['generation']
    guard.reconcile(ctx,NOW)
    live.journal.reserve('other',asdict(request(key='other')),'other',NOW,position_guard=guard)
    with pytest.raises(ExchangeError,match='PREFLIGHT_INVALIDATED'):
        guard.evaluate(request(),ctx,NOW,expected_generation=generation)
    assert live.journal.control('global_position_lock')['entry_key']=='other'


def test_generation_change_between_validation_and_reservation_is_blocked(live):
    assert evaluate(live).allowed
    generation=live.journal.control('global_position_lock')['generation']
    live.executor.position_guard.revoke('ACCOUNT_EVENT')
    with pytest.raises(ExchangeError,match='PREFLIGHT_INVALIDATED'):
        live.journal.reserve('stale',asdict(request()),'stale',NOW,
            position_guard=live.executor.position_guard,position_generation=generation)
    assert not live.journal.intents()


@pytest.mark.parametrize('held,own_side,own_price,side,price',[
    ('.2','B','100.02','SELL','100'),('-.2','A','99.98','BUY','100')])
def test_own_crossing_orders_are_blocked(live,held,own_side,own_price,side,price):
    live.fixture.position(held)
    live.fixture.orders=[dict(coin='par:BTC',oid=11,side=own_side,sz='.1',limitPx=own_price)]
    decision=evaluate(live,request(side=side,price=price,reduce=True))
    assert decision.code=='SELF_CROSS_RISK'


def test_non_crossing_own_order_does_not_block_legitimate_reduce_only_protection(live):
    live.fixture.position('.2')
    live.fixture.orders=[dict(coin='par:BTC',oid=11,side='B',sz='.1',limitPx='99')]
    req=request(side='SELL',reduce=True)
    token=permission(req,reason='EMERGENCY_RISK_EXIT')
    token=replace(token,provenance=replace(token.provenance,classification='PROTECTIVE_EXIT',action_type='RISK_PROTECTION'))
    assert evaluate(live,req,token=token).allowed


def test_unknown_trigger_is_visible_and_never_ignored(live):
    live.fixture.position('.2')
    live.fixture.orders=[dict(coin='par:BTC',oid=99,side='A',sz='.2',limitPx='90',isTrigger=True,
                             reduceOnly=False,triggerPx='90')]
    assert evaluate(live,request(side='SELL',reduce=True)).code=='UNKNOWN_PROTECTION_ORDER'
    assert any(p['type']=='frontendOpenOrders' for p in live.fixture.calls)


def test_same_candidate_with_different_cloid_is_not_a_new_setup(live):
    req=request(key='first')
    live.transport.responses=[response({'error':'Insufficient margin'})]
    live.executor.submit(req,permission=permission(req))
    live.executor.entries_paused=False
    second=request(key='another-key')
    with pytest.raises(ExchangeError,match='DUPLICATE_ORDER'):
        live.executor.submit(second,permission=permission(second))
    assert len(live.transport.signed_payloads)==1


def test_timeout_retry_returns_existing_intent_and_logs_block(live):
    req=request(key='timeout')
    live.transport.responses=[{'fixture_timeout':True}]
    first=live.executor.submit(req,permission=permission(req))
    assert first.state==OrderState.UNKNOWN
    assert live.executor.submit(req,permission=permission(req))==first
    assert len(live.transport.signed_payloads)==1
    assert events(live,'COMPLIANCE_DECISION')[-1]['code']=='DUPLICATE_ORDER_BLOCKED'


@pytest.mark.parametrize('damage,code',[
    ('missing','MISSING_STRATEGY_PROVENANCE'),('candidate','MISSING_STRATEGY_PROVENANCE'),
    ('future','MISSING_STRATEGY_PROVENANCE'),('old','MISSING_STRATEGY_PROVENANCE'),
    ('no_risk','MISSING_STRATEGY_PROVENANCE'),('no_execution','MISSING_STRATEGY_PROVENANCE'),
    ('unknown','UNEXPLAINED_ORDER'),('setup','UNEXPLAINED_ORDER'),('coordination','COORDINATED_INPUT_BLOCK')])
def test_provenance_is_required_and_cannot_hide_unknown_or_coordinated_orders(live,damage,code):
    req=request();token=permission(req)
    changes={'candidate':dict(candidate_id='another'),'future':dict(signal_timestamp_ms=NOW+1),
        'old':dict(signal_timestamp_ms=NOW-180001),'no_risk':dict(risk_decision={'allowed':False}),
        'no_execution':dict(execution_decision={'allowed':False}),'unknown':dict(classification='UNKNOWN'),
        'setup':dict(setup_type='VOLUME_FARMING'),'coordination':dict(input_source='OTHER_TEAM_SIGNAL')}
    token=replace(token,provenance=None if damage=='missing' else replace(token.provenance,**changes[damage]))
    assert evaluate(live,req,token=token).code==code


@pytest.mark.parametrize('damage,code',[('price','ABNORMAL_PRICE'),('oracle','STALE_PRICE_CONTEXT'),
    ('mark','STALE_PRICE_CONTEXT'),('book','STALE_PRICE_CONTEXT'),('divergence','MARK_ORACLE_DIVERGENCE'),
    ('thin','BOOK_MANIPULATION_RISK')])
def test_off_market_stale_and_thin_book_orders_are_blocked(live,damage,code):
    req=request(price='150' if damage=='price' else '100')
    ctx=live.provider.load(req)
    if damage=='oracle':ctx=replace(ctx,oracle_ms=NOW-60001)
    if damage=='mark':ctx=replace(ctx,quote=replace(ctx.quote,mark_timestamp_ms=NOW-60001))
    if damage=='book':ctx=replace(ctx,quote=replace(ctx.quote,timestamp_ms=NOW-5001))
    if damage=='divergence':ctx=replace(ctx,quote=replace(ctx.quote,mark=D(101)))
    if damage=='thin':ctx=replace(ctx,quote=replace(ctx.quote,ask_quantity=D('.1')))
    assert evaluate(live,req,context=ctx).code==code


def test_strategy_exit_requires_source_position_and_protection_must_reduce(live):
    live.fixture.position('.2');req=request(side='SELL',reduce=True)
    token=permission(req,reason='EXIT')
    token=replace(token,provenance=replace(token.provenance,source_position_id=None))
    assert evaluate(live,req,token=token).code=='MISSING_SOURCE_POSITION'
    token=permission(request())
    token=replace(token,provenance=replace(token.provenance,classification='PROTECTIVE_EXIT',action_type='RISK_PROTECTION'))
    assert not evaluate(live,request(),token=token).allowed


def test_controlled_test_needs_explicit_bounded_authorization(live):
    req=request();token=permission(req)
    p=replace(token.provenance,classification='CONTROLLED_TEST_ORDER',action_type='CONTROLLED_TEST_ORDER')
    assert evaluate(live,req,token=replace(token,provenance=p)).code=='UNAUTHORIZED_TEST_ORDER'
    a=dict(operator_authorization='SYNTHETIC_AUTHORIZATION_ONLY',objective='SYNTHETIC_ACCOUNT_CERTIFICATION',
        market=req.symbol,expected_quantity=str(req.quantity),timestamp_ms=NOW,expires_ms=NOW+1000,
        exit_procedure='EXPLICIT_REDUCE_ONLY_EXIT_AND_FLAT_RECONCILIATION')
    decision=evaluate(live,req,token=replace(token,provenance=replace(p,test_authorization=a)))
    assert decision.allowed and decision.checks['performance_statistics']=='EXCLUDE_CONTROLLED_TEST'


@pytest.mark.parametrize('action_type',['spotSend','usdSend','sendAsset','withdraw3','approveAgent'])
def test_transfer_and_admin_actions_cannot_reach_signing(live,action_type):
    action={'type':action_type}
    ctx=live.provider.load(request())
    with pytest.raises(ExchangeError,match='COMPLIANCE_MANAGEMENT_BLOCKED'):
        live.executor.compliance_guard.authorize_management(action,ctx,lambda:None)
    assert not live.transport.signed_payloads


def test_alternate_executor_plain_callback_or_forged_permit_cannot_sign(live):
    req=request()
    _,action=live.transport.order_action(req,'0x'+'9'*32)
    with pytest.raises(ExchangeError,match='COMPLIANCE_ACTION_PERMIT_REQUIRED'):
        live.transport.perform('order',(),{},action,lambda:None)
    forged=ActionPermit(live.executor.compliance_guard,action,lambda:None)
    with pytest.raises(ExchangeError,match='COMPLIANCE_ACTION_PERMIT_REQUIRED'):
        live.transport.perform('order',(),{},action,forged)
    assert not live.transport.signed_payloads


def test_action_permit_cannot_authorize_an_altered_wire(live):
    req=request(key='wire')
    normalized,ctx,result,decision=live.executor._validated(req,permission(req))
    row,_=live.journal.reserve('wire',asdict(normalized),'candidate:1',NOW,position_guard=live.executor.position_guard)
    _,action=live.transport.order_action(normalized,row['cloid'])
    action['orders'][0]['s']='100'
    with pytest.raises(ExchangeError,match='WIRE_MISMATCH'):
        live.executor._permit(action,decision,normalized,ctx,result.checked_ms,entry_key='wire')
    assert not live.transport.signed_payloads


def test_position_arriving_after_preflight_is_blocked_at_sdk_boundary(live,monkeypatch):
    original=live.transport.perform
    def changed(*args,**kwargs):
        live.fixture.position('.4')
        return original(*args,**kwargs)
    monkeypatch.setattr(live.transport,'perform',changed)
    req=request(key='late-account-change')
    order=live.executor.submit(req,permission=permission(req))
    assert order.state==OrderState.UNKNOWN and live.executor.entries_paused
    assert not live.transport.signed_payloads
    assert events(live,'COMPLIANCE_SIGNING_BLOCK')[0]['reason']=='ACCOUNT_CHANGED_BEFORE_SIGNING'


def test_approved_order_cannot_skip_durable_global_slot(live):
    req=request(key='no-reservation')
    normalized,ctx,result,decision=live.executor._validated(req,permission(req))
    _,action=live.transport.order_action(normalized,'0x'+'8'*32)
    with pytest.raises(ExchangeError,match='DURABLE_COMPLIANCE_INTENT_REQUIRED'):
        live.executor.compliance_guard.authorize(action,decision,normalized,ctx,lambda:None)
    assert not live.transport.signed_payloads and not live.journal.intents()


def test_alternate_callback_cannot_bypass_executor_clock_checks(live):
    req=request(key='fixed-boundary')
    normalized,ctx,result,decision=live.executor._validated(req,permission(req))
    row,_=live.journal.reserve('fixed-boundary',asdict(normalized),'candidate:1',NOW,
                              position_guard=live.executor.position_guard)
    _,action=live.transport.order_action(normalized,row['cloid'])
    permit=live.executor.compliance_guard.authorize(action,decision,normalized,ctx,lambda:None,
                                                   entry_key='fixed-boundary')
    assert not live.clock.observe(None,NOW,NOW)
    with pytest.raises(ExchangeError,match='CLOCK_HEALTH_REQUIRED'):
        permit.require(live.transport,action)
    assert not live.transport.signed_payloads


def test_account_owner_lease_covers_different_process_and_tmpdir(tmp_path):
    address='0x'+'b'*40
    lease=AccountExecutionLease(address)
    try:
        with pytest.raises(ExchangeError,match='ALREADY_LEASED'):
            AccountExecutionLease(address)
        code='from exchange.single_position_guard import AccountExecutionLease\nfrom exchange.base_exchange import ExchangeError\ntry:\n AccountExecutionLease("'+address+'")\nexcept ExchangeError as e:\n print(str(e))\n'
        import os
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,
            env=dict(os.environ,TMPDIR=str(tmp_path)),capture_output=True,text=True,timeout=10)
        assert 'TEAM_ACCOUNT_ALREADY_LEASED' in result.stdout
    finally:
        lease.close()
    with pytest.raises(ExchangeError,match='LEASE_REQUIRED'):lease.require()


@pytest.mark.parametrize('maximum',[2,3,0,True])
def test_future_multi_position_is_inactive(live,maximum):
    with pytest.raises(ExchangeError,match='ONE_GLOBAL_POSITION_REQUIRED'):
        SinglePositionGuard(live.journal,clock_ms=lambda:NOW,max_positions=maximum)


def test_summary_never_certifies_empty_or_synthetic_evidence(live,tmp_path):
    summary=compliance_summary(live.journal,mode='OFFLINE_SIGNED_FIXTURE',position_guard=live.executor.position_guard)
    assert summary['compliance_state']=='REVIEW_REQUIRED' and summary['maximum_simultaneous_positions_observed'] is None
    evaluate(live)
    evaluate(live,request(price='150'))
    summary=export_compliance(tmp_path/'report',live.journal,mode='OFFLINE_SIGNED_FIXTURE',position_guard=live.executor.position_guard)
    assert summary['orders_allowed']==1 and summary['orders_blocked']==1 and summary['abnormal_price_blocks']==1
    assert summary['autonomous_usdpr_external_transfers']==0 and summary['external_wallet_transfers_observed'] is None
    assert summary['compliance_state']=='REVIEW_REQUIRED'
    assert compliance_summary(live.journal,mode='LIVE_TESTNET',position_guard=live.executor.position_guard)['compliance_state']=='REVIEW_REQUIRED'
    exported=[json.loads(s) for s in (tmp_path/'report/compliance_events.jsonl').read_text().splitlines()]
    assert all({'processed_ts','received_ts','exchange_ts'}<=set(e) for e in exported)


def test_policy_cannot_relax_frozen_risk_or_book_participation():
    for kwargs in (dict(depth_participation=D('.2')),dict(max_mark_oracle_bps=D(51)),dict(max_order_book_bps=D(101))):
        with pytest.raises(ExchangeError):CompliancePolicy(**kwargs)


def test_central_entry_guard_cannot_increase_baseline_leverage(live):
    context=replace(live.provider.load(request()),leverage=2)
    assert evaluate(live,context=context).code=='INVALID_LEVERAGE'
    assert not live.transport.signed_payloads
