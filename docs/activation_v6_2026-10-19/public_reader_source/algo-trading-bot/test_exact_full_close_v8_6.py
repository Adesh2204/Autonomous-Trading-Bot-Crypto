"""Ephemeral OFFLINE SDK fixtures only; real HTTP and actual wallet signing prohibited."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import json
import pytest

from exchange.base_exchange import ExchangeError, MarketSpec, Position
from exchange.full_position_close import FULL_POSITION_CLOSE, SCOPES, observed_scope
from exchange.partial_fill_safety import scoped_exact_full_close_size, exact_full_close_size
from exchange.order_lifecycle import OrderRequest, OrderState
from exchange.sdk_transport import build_exchange
from exchange.execution_journal import ExecutionJournal
from exchange.testnet_certification import (CertificationSequence, CertificationAuthorization,
    CertificationProtection, require_safe_partial_path)
from exchange.certification_runtime import CertificationRuntime
from test_live_exchange_execution import live, permission, response
from test_testnet_certification_v8 import cert
from test_exchange_migration import NOW


def runtime_mapping(l):
    # Match the observed runtime testnet DEX index; synthetic prices stay synthetic.
    l.fixture.dexes = [None]*257+[dict(name='par')]
    names = ['par:'+s for s in ('BTC','ETH','HYPE','SP500','EWY','EWJ','BRENT','GOLD','USDEUR','USDJPY')]
    l.fixture.metadata['universe'].sort(key=lambda row:names.index(row['name']))
    l.client.startup()
    from exchange.execution_journal import fingerprint
    l.provider.metadata_hash = fingerprint(l.client.metadata)
    l.transport._sdk.session.close(); l.transport._sdk.info.session.close()
    l.transport._sdk = build_exchange(l.signer, l.client, l.nonces, l.transport, offline=True)


@pytest.fixture
def scoped(live):
    runtime_mapping(live)
    live.fixture.position('.0001')
    return live


@pytest.fixture
def scoped_cert(cert):
    runtime_mapping(cert.live)
    p = replace(cert.proposal, asset_id=cert.live.client.market('par:BTC').asset_id)
    a = replace(cert.approval, proposal_hash=p.identity)
    # Same ephemeral signer, synthetic authorization and no HTTP sink.
    auth = CertificationAuthorization(p, a, cert.live.journal, clock_ms=lambda:cert.live.fixture.now,
        source_hash=lambda:'fixture-source', policy_hash=lambda:'fixture-policy')
    cert.proposal, cert.approval, cert.auth = p, a, auth
    cert.venue.auth = auth
    CertificationProtection(cert.live.executor, p)
    cert.sequence = CertificationSequence(cert.live.executor, p, auth,
                                         verified_full_position_closes=True)
    return cert


def request(side='SELL', size='.0001', **kwargs):
    return OrderRequest('par:BTC', side, size, '100', reduce_only=True,
        strategy_id='EXACT_FULL_POSITION_CLOSE', tif='Ioc', **kwargs)


def allowed(l, req=None, **changes):
    req = req or request()
    ctx = l.provider.load(req)
    ctx = replace(ctx, **changes) if changes else ctx
    token = permission(req, reason='REDUCE_ONLY_EXIT')
    return l.validator.validate(req, ctx, token, NOW, operation=FULL_POSITION_CLOSE)


@pytest.mark.parametrize('symbol,side,size,oid', [
    ('par:BTC','BUY','.0001',62391880965), ('par:BTC','SELL','.0001',62228843959),
    ('par:ETH','BUY','.0001',61841673908), ('par:HYPE','BUY','.01',61878767079),
    ('par:BRENT','SELL','.01',61912483832), ('par:EWJ','BUY','.001',61956380536)])
def test_only_original_observed_shapes_have_audit_proof(symbol,side,size,oid):
    asset, decimals, _ = SCOPES[symbol]
    scope = observed_scope(MarketSpec(symbol,decimals,20,asset),side,D(size))
    assert scope['historical_oid'] == oid and len(scope['evidence_sha256']) == 64


@pytest.mark.parametrize('symbol,side,size', [
    ('par:ETH','SELL','.0001'), ('par:HYPE','SELL','.01'), ('par:BRENT','BUY','.01'),
    ('par:BTC','SELL','.0002'), ('par:GOLD','SELL','.001')])
def test_close_observations_do_not_extrapolate(symbol,side,size):
    asset, decimals = SCOPES.get(symbol,(2670007,3))[:2]
    with pytest.raises(ExchangeError, match='SCOPE_NOT_VERIFIED'):
        observed_scope(MarketSpec(symbol,decimals,20,asset),side,D(size))


def test_full_close_minimum_is_explicit_not_global(scoped):
    req = request(); ctx = scoped.provider.load(req); token = permission(req, reason='REDUCE_ONLY_EXIT')
    assert scoped.validator.validate(req,ctx,token,NOW).code == 'MIN_ORDER_NOTIONAL'
    with pytest.raises(ExchangeError, match='ORDER_BELOW_MINIMUM_NOTIONAL'):
        ctx.spec.normalize_order('SELL','.0001','100',reduce_only=True,tif='Ioc')
    result = allowed(scoped)
    assert result.allowed and result.normalized.quantity == D('.0001')
    assert result.audit['closing_exception_applied'] is True


@pytest.mark.parametrize('damage,code', [
    ('entry','EXACT_FULL_CLOSE_OPERATION_REQUIRED'), ('gtc','EXACT_FULL_CLOSE_OPERATION_REQUIRED'),
    ('tag','EXACT_FULL_CLOSE_OPERATION_REQUIRED'), ('wrong_side','EXACT_FULL_CLOSE_POSITION_MISMATCH'),
    ('partial','EXACT_FULL_CLOSE_POSITION_MISMATCH'), ('oversize','EXACT_FULL_CLOSE_POSITION_MISMATCH'),
    ('stale','EXACT_FULL_CLOSE_FRESH_RECONCILIATION_REQUIRED'),
    ('unreconciled','EXACT_FULL_CLOSE_FRESH_RECONCILIATION_REQUIRED'),
    ('flat','EXACT_FULL_CLOSE_SOLE_POSITION_REQUIRED'), ('multi','EXACT_FULL_CLOSE_SOLE_POSITION_REQUIRED'),
    ('mapping','SUBMINIMUM_FULL_CLOSE_SCOPE_NOT_VERIFIED'), ('precision','EXACT_FULL_CLOSE_PRECISION_MISMATCH')])
def test_explicit_path_keeps_exact_account_guards(scoped,damage,code):
    req = request(); changes = {}
    if damage=='entry': req=replace(req,reduce_only=False)
    if damage=='gtc': req=replace(req,tif='Gtc')
    if damage=='tag': req=replace(req,strategy_id='TRIGGER_STOP')
    if damage=='wrong_side': req=replace(req,side='BUY')
    if damage=='partial': scoped.fixture.position('.0002')
    if damage=='oversize': req=replace(req,quantity=D('.0002'))
    if damage=='stale': changes['account_ms']=NOW-5001
    if damage=='unreconciled': changes['reconciled']=False
    if damage=='flat': scoped.fixture.position('0')
    if damage=='multi':
        ctx = scoped.provider.load(req)
        changes['positions']=dict(ctx.positions,other=replace(ctx.positions['par:BTC'],symbol='par:ETH'))
    if damage=='mapping':
        # Runtime metadata mapping change is rejected even before the validator.
        spec=replace(scoped.client.market('par:BTC'),asset_id=110000)
        with pytest.raises(ExchangeError,match='SCOPE_NOT_VERIFIED'):
            observed_scope(spec,'SELL',D('.0001'))
        return
    if damage=='precision': req=replace(req,price=D('100.00001'))
    result = allowed(scoped,req,**changes)
    assert not result.allowed and result.code==code, result
    assert not scoped.transport.signed_payloads


@pytest.mark.parametrize('damage,code', [('quote','STALE_MARKET_DATA'),('mark','STALE_MARKET_DATA'),
    ('permission','RISK_PERMISSION_DENIED'),('reference','PRICE_BAND_VIOLATION')])
def test_scoped_close_still_checks_market_and_risk(scoped,damage,code):
    req = request(); ctx = scoped.provider.load(req); token = permission(req,reason='REDUCE_ONLY_EXIT')
    if damage=='quote': ctx=replace(ctx,quote=replace(ctx.quote,timestamp_ms=NOW-5001))
    if damage=='mark': ctx=replace(ctx,quote=replace(ctx.quote,mark_timestamp_ms=NOW-60001))
    if damage=='permission': token=replace(token,maximum_quantity=D('.00001'))
    if damage=='reference': ctx=replace(ctx,quote=replace(ctx.quote,mark=D('10')))
    result = scoped.validator.validate(req,ctx,token,NOW,operation=FULL_POSITION_CLOSE)
    assert result.code==code and not result.allowed


def test_scoped_sizing_cannot_exempt_stops_or_invalid_dust(scoped):
    spec=scoped.client.market('par:BTC'); held=scoped.account.get_position('par:BTC')
    assert scoped_exact_full_close_size(spec,held,side='SELL',maximum_quantity='.2',limit_price='100')==D('.0001')
    with pytest.raises(ExchangeError,match='SUB_MINIMUM_RESIDUAL_CLOSE_NOT_VERIFIED'):
        exact_full_close_size(spec,held,side='SELL',maximum_quantity='.2',limit_price='100')
    with pytest.raises(ExchangeError,match='PRECISION_UNREPRESENTABLE'):
        scoped_exact_full_close_size(spec,replace(held,quantity=D('.00011')),side='SELL',
                                    maximum_quantity='.2',limit_price='100')


def test_small_entry_and_trigger_still_blocked_before_sdk(scoped):
    req=replace(request(),side='BUY',reduce_only=False,strategy_id='VWAP',client_order_id='small-entry')
    scoped.fixture.position('0')
    with pytest.raises(ExchangeError,match='MIN_ORDER_NOTIONAL'):
        scoped.executor.submit(req,permission=permission(req))
    scoped.fixture.position('.0001')
    req=request()
    with pytest.raises(ExchangeError,match='MIN_ORDER_NOTIONAL'):
        scoped.executor._validated(req,permission(req,reason='REDUCE_ONLY_EXIT'),critical=True,trigger=True)
    with pytest.raises(ExchangeError,match='CANNOT_BE_TRIGGER_OR_REPLACEMENT'):
        scoped.executor._validated(req,permission(req,reason='REDUCE_ONLY_EXIT'),critical=True,
                                   trigger=True,full_position_close=True)
    assert not scoped.transport.signed_payloads


def test_scoped_sdk_wire_closes_exact_quantity_and_deduplicates(scoped):
    req=request(client_order_id='bounded-close'); token=permission(req,reason='REDUCE_ONLY_EXIT')
    scoped.transport.responses=[response({'filled':{'oid':11,'totalSz':'.0001','avgPx':'100'}})]
    a=scoped.executor.close_full_position(req,permission=token)
    b=scoped.executor.close_full_position(req,permission=token)
    assert a.intent_key==b.intent_key and len(scoped.transport.signed_payloads)==1
    wire=scoped.transport.signed_payloads[0]['action']['orders'][0]
    assert wire['r'] is True and wire['b'] is False and D(wire['s'])==D('.0001')
    assert wire['a']==2670000 and wire['t']=={'limit':{'tif':'Ioc'}}


def test_position_change_at_permit_boundary_never_signs(scoped,monkeypatch):
    req=request(client_order_id='position-race'); original=scoped.executor._permit
    def race(*args,**kwargs):
        permit=original(*args,**kwargs)
        scoped.fixture.position('.0002')
        return permit
    monkeypatch.setattr(scoped.executor,'_permit',race)
    outcome=scoped.executor.close_full_position(req,permission=permission(req,reason='REDUCE_ONLY_EXIT'))
    assert outcome.state==OrderState.UNKNOWN and scoped.executor.entries_paused
    assert not scoped.transport.signed_payloads
    assert scoped.journal.control('global_position_lock')['state'] != 'FLAT'


@pytest.mark.parametrize('kind',['rejected','uncertain'])
def test_subminimum_close_failure_stays_exposed_no_blind_retry(scoped,kind):
    req=request(client_order_id='failure-close'); token=permission(req,reason='REDUCE_ONLY_EXIT')
    scoped.transport.responses=[response({'error':'Order must have minimum value of $10.'})] if kind=='rejected' else []
    first=scoped.executor.close_full_position(req,permission=token)
    again=scoped.executor.close_full_position(req,permission=token)
    assert first.state==again.state and first.state in {OrderState.REJECTED,OrderState.UNKNOWN}
    assert scoped.account.get_position('par:BTC').quantity==D('.0001')
    assert len(scoped.transport.signed_payloads)==1


def test_one_lot_partial_entry_can_close_but_cannot_pass_protection_certification(scoped_cert):
    c=scoped_cert; c.venue.partial_entry=D('.0001')/D(c.proposal.quantity)
    r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert r['final_flat'] and r['certification_passed'] is False
    assert r['protection_accepted'] is False and r['certification_blocker']=='ACTUAL_POSITION_PROTECTION_NOT_VERIFIED'
    assert len(c.venue.calls)==2 and all('trigger' not in a['orders'][0]['t'] for a in c.venue.calls)
    assert D(c.venue.calls[1]['orders'][0]['s'])==D('.0001')
    with pytest.raises(ExchangeError,match='SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED'):
        require_safe_partial_path(c.live.client.market('par:BTC'),c.proposal)


def test_unverified_two_lot_partial_remains_blocked(scoped_cert):
    c=scoped_cert; c.venue.partial_entry=D('.0002')/D(c.proposal.quantity)
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and r['operator_action_required'],r
    assert len(c.venue.calls)==1 and c.live.account.get_position('par:BTC').quantity==D('.0002')
    assert r['error']=='SUBMINIMUM_FULL_CLOSE_SCOPE_NOT_VERIFIED'


def test_partial_exit_one_lot_residual_uses_actual_quantity(scoped_cert):
    c=scoped_cert; original=c.venue.transmit; exit_calls=[]
    def transmit(payload):
        w=payload['action'].get('orders',[{}])[0]
        if w.get('r') and 'trigger' not in w.get('t',{}):
            exit_calls.append(w['s'])
            c.venue.partial_exit=(D(w['s'])-D('.0001'))/D(w['s']) if len(exit_calls)==1 else D(1)
        return original(payload)
    c.live.transport.transmit=transmit
    r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED' and r['certification_passed'],r
    assert len(exit_calls)==2 and D(exit_calls[1])==D('.0001') and r['final_flat']


def test_stop_rejection_does_not_award_long_certificate(scoped_cert):
    c=scoped_cert; c.venue.fail='protection_rejected'
    runtime=CertificationRuntime(c.sequence,None,None,None,c.live.journal)
    r=runtime.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED' and r['final_flat']
    assert r['certification_passed'] is False and not c.live.journal.control('long_certification_complete')


def test_offline_stop_success_never_certifies_actual_account(scoped_cert):
    c=scoped_cert
    r=CertificationRuntime(c.sequence,None,None,None,c.live.journal).run()
    assert r['certification_passed'] is True and r['evidence_scope']=='OFFLINE_SIGNED_FIXTURE'
    assert not c.live.journal.control('long_certification_complete')


def test_restart_does_not_repeat_consumed_small_entry(scoped_cert):
    c=scoped_cert; c.venue.partial_entry=D('.0001')/D(c.proposal.quantity)
    r=c.sequence.run(); assert r['final_flat']
    previous=len(c.venue.calls)
    c.auth.revoked=False
    restarted=CertificationSequence(c.live.executor,c.proposal,c.auth,verified_full_position_closes=True)
    result=restarted.run()
    assert len(c.venue.calls)==previous and not result['certification_passed']
    assert result['status']=='PREFLIGHT_BLOCKED'


def test_restart_uncertain_close_preserves_original_cloid(scoped,tmp_path):
    req=request(client_order_id='restart-unknown'); token=permission(req,reason='REDUCE_ONLY_EXIT')
    first=scoped.executor.close_full_position(req,permission=token)
    assert first.state==OrderState.UNKNOWN
    path=scoped.journal.path if hasattr(scoped.journal,'path') else tmp_path/'journal.sqlite'
    row=dict(scoped.journal.intent(req.client_order_id))
    # Reopen the durable journal independently; observation cannot resubmit an order.
    reopened=ExecutionJournal(path,session_id='offline:test',team_address=scoped.journal.team_address)
    try:
        recovered=reopened.intent(req.client_order_id)
        assert recovered['cloid']==row['cloid'] and recovered['state']=='UNKNOWN'
        assert reopened.control('global_position_lock')['state']!='FLAT'
    finally: reopened.close()
    second=scoped.executor.close_full_position(req,permission=token)
    assert second.cloid==first.cloid and len(scoped.transport.signed_payloads)==1


def test_paper_default_cannot_reach_scoped_order_path(scoped):
    from exchange.hyperliquid_execution import HyperliquidExecution
    from order_guard import OrderRoutingBlocked
    executor=HyperliquidExecution(scoped.client)
    with pytest.raises(OrderRoutingBlocked):
        executor.close_full_position(request(),permission=permission(request(),reason='REDUCE_ONLY_EXIT'))
    assert not scoped.transport.signed_payloads


def protection_classifier():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'docs/certification_v8_6_2026-10-12/protection_evidence.py'
    spec=importlib.util.spec_from_file_location('v86_stop_evidence',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.assess_open_stop


def public_stop_fixture():
    row=dict(coin='par:BTC',oid=42,side='A',sz='.0001',origSz='.0001',limitPx='80000',
             triggerPx='81000',reduceOnly=True,isTrigger=True,orderType='Stop Limit',isPositionTpsl=True)
    detail=dict(status='order',order=dict(status='open',order=dict(row)))
    state=dict(assetPositions=[dict(position=dict(coin='par:BTC',szi='.0001'))])
    return detail,row,state


def test_even_exact_open_stop_evidence_does_not_prove_residual_execution():
    detail,row,state=public_stop_fixture()
    r=protection_classifier()(detail,row,state,state,symbol='par:BTC',lot='.0001')
    assert r['one_lot_stop_acceptance'] and r['exact_position_coverage']
    assert r['position_attached_grouping_verified']
    assert not r['residual_behavior_verified'] and not r['capability_validated']


@pytest.mark.parametrize('damage',['no_position','wrong_size','wrong_side','not_stop','not_reduce',
    'not_trigger','larger_original','wrong_readback','terminal','changed_position','not_one_lot'])
def test_public_stop_evidence_rejects_false_proofs(damage):
    from copy import deepcopy
    detail,row,state=public_stop_fixture();after=deepcopy(state)
    if damage=='no_position': state['assetPositions']=[];after=deepcopy(state)
    if damage=='changed_position': after['assetPositions'][0]['position']['szi']='.0002'
    if damage=='wrong_size': state['assetPositions'][0]['position']['szi']='.0002';after=deepcopy(state)
    if damage=='wrong_side': row['side']='B'
    if damage=='not_stop': row['orderType']='Take Profit Limit'
    if damage=='not_reduce': row['reduceOnly']=False
    if damage=='not_trigger': row['isTrigger']=False
    if damage=='larger_original': row['origSz']='.001'
    if damage=='wrong_readback': detail['order']['order']['limitPx']='79900'
    if damage=='terminal': detail['order']['status']='rejected'
    if damage=='not_one_lot': row['sz']=row['origSz']='.0002'
    if damage!='wrong_readback':detail['order']['order']=dict(row)
    r=protection_classifier()(detail,row,state,after,symbol='par:BTC',lot='.0001')
    assert not r['one_lot_stop_acceptance'] and not r['exact_position_coverage'] and not r['capability_validated']


def test_scope_manifest_matches_preserved_original_close_proof():
    import hashlib
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    path=root/'docs/certification_v8_5_2026-10-12/independent_close_readback/one_lot_readback.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764'
    text=path.read_text()
    for symbol,(asset,decimals,rows) in SCOPES.items():
        for side,size,oid in rows:
            assert str(oid) in text
            assert observed_scope(MarketSpec(symbol,decimals,20,asset),side,size)['historical_oid']==oid


def test_restart_with_unverified_residual_is_read_only_and_escalates(scoped_cert):
    c=scoped_cert;c.venue.partial_entry=D('.0002')/D(c.proposal.quantity)
    r=c.sequence.run();assert r['operator_action_required']
    count=len(c.venue.calls);c.live.executor.recovery.recover()
    assert c.live.journal.control('certification_residual:'+c.proposal.identity)['signed_quantity']=='0.0002'
    c.auth.revoked=False
    result=CertificationSequence(c.live.executor,c.proposal,c.auth,verified_full_position_closes=True).run()
    assert len(c.venue.calls)==count and not result['certification_passed']
    assert c.live.account.get_position('par:BTC').quantity==D('.0002')
