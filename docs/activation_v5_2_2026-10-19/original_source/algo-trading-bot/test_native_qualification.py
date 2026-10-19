"""Offline real composition only; ephemeral fixtures never qualify the venue."""
from dataclasses import asdict, replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from exchange.base_exchange import ExchangeError
from exchange.certification_runtime import CertificationRecovery
from exchange.native_qualification import (NativeQualificationProposal, NativeQualificationApproval,
    NativeQualificationAuthorization, NativeQualificationSequence, NativeQualificationExecution,
    NativeQualificationRecovery, require_partial_abort_path, check_entry, propose, CLOSE_PROOF)
from exchange.testnet_certification import CertificationProposal, CertificationApproval, require_safe_partial_path
from exchange.order_lifecycle import OrderRequest
from exchange.native_qualification_runtime import require_prior_certification_settled
from test_live_exchange_execution import live
from test_exact_full_close_v8_6 import runtime_mapping
from test_testnet_certification_v8 import FakeCertificationVenue
from test_exchange_migration import NOW, TEAM

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native(live, monkeypatch):
    import exchange.testnet_certification as mod
    monkeypatch.setattr(mod, 'TEAM', TEAM); monkeypatch.setattr(mod, 'API', live.signer.address)
    runtime_mapping(live)
    live.fixture.book.update(levels=[[dict(px='83400', sz='.1')],[dict(px='83440', sz='.1')]])
    live.fixture.contexts=[dict(markPx='83500', oraclePx='83500', funding='.0001', openInterest='10')
        for _ in live.fixture.metadata['universe']]
    live.fixture.active.update(markPx='83500', availableToTrade=['1000','1000'])
    recovery=NativeQualificationRecovery(live.account, live.journal, initial_start_ms=NOW)
    live.executor.recovery=recovery
    live.provider.reconciliation_ready=lambda:recovery.account_truth_ready
    recovery.recover()
    context=live.provider.load(OrderRequest('par:BTC','BUY','.0002','83481',tif='Ioc'))
    p=propose(context, live.client, 'fixture-source', 'fixture-policy')
    a=NativeQualificationApproval(p.identity, 'SYNTHETIC_HUMAN_ONLY', NOW, NOW+300000,
        True, True, True, True, True, True, True, True)
    auth=NativeQualificationAuthorization(p,a,live.journal,root=ROOT,clock_ms=lambda:live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    live.transport.authorization=auth
    e=NativeQualificationExecution(live.client, proposal=p, transport=live.transport,
        account=live.account, journal=live.journal, context_provider=live.provider,
        validator=live.validator, recovery=recovery, clock_health=live.clock, rate_limits=live.rate)
    live.executor=e
    venue=FakeCertificationVenue(live, monkeypatch, auth)
    def wait():
        live.fixture.now+=10000; live.fixture.book['time']=live.fixture.now
        for _ in range(2): live.clock.observe(live.fixture.now, live.fixture.now, live.fixture.now)
    sequence=NativeQualificationSequence(e,p,auth,wait=wait)
    return SimpleNamespace(live=live,p=p,a=a,auth=auth,venue=venue,sequence=sequence,context=context)


def test_two_lot_path_has_only_exact_one_lot_abort_and_keeps_generic_gate(native):
    c=native;spec=c.live.client.market(c.p.symbol)
    path=require_partial_abort_path(spec,c.p)
    assert path['partial_abort_quantity']=='0.0001'
    assert path['partial_abort_scope']['historical_oid']==62228843959
    assert not path['small_native_stop_verified'] and not path['unattended_entry_authorized']
    with pytest.raises(ExchangeError,match='SUB_MINIMUM_PARTIAL_FILL'):
        require_safe_partial_path(spec,c.p)


@pytest.mark.parametrize('field,value', [('quantity','.0001'),('quantity','.0003'),
    ('entry_side','SELL'),('asset_id',2670001),('purpose','other'),
    ('close_evidence_sha256','other'),('trigger_wait_seconds',121),('trigger_wait_seconds',True)])
def test_scope_cannot_enlarge_or_generalize(native,field,value):
    with pytest.raises(ExchangeError):replace(native.p,**{field:value}).require()


def test_generic_proposal_cannot_select_abort_exception(native):
    p=CertificationProposal(**{k:v for k,v in asdict(native.p).items() if k not in
        {'purpose','close_evidence_sha256','trigger_wait_seconds'}})
    with pytest.raises(ExchangeError,match='PROPOSAL_TYPE'):
        require_partial_abort_path(native.live.client.market(p.symbol),p)


@pytest.mark.parametrize('field', ['partial_entry_immediate_ioc_abort_accepted',
    'unprotected_interval_and_residual_risk_accepted','loss_making_cleanup_accepted',
    'acceptance_without_trigger_is_incomplete_accepted','mac_power_app_internet_dependency_accepted',
    'manually_verified_wallets','sole_signer_host_confirmed','maximum_one_entry'])
def test_all_exact_human_acknowledgments_required(native,field):
    c=native;c.auth.approval=replace(c.a,**{field:False})
    r=c.sequence.run()
    assert r['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


def test_old_approval_type_is_not_native_authority(native):
    c=native;c.auth.approval=CertificationApproval(c.p.identity,'SYNTHETIC',NOW,NOW+300000,True,True,True)
    with pytest.raises(ExchangeError,match='RISK_APPROVAL'):
        c.auth.require(c.p.team_wallet,c.p.api_wallet)


@pytest.mark.parametrize('damage',['source','policy','proof','expired'])
def test_missing_or_changed_evidence_never_signs(native,tmp_path,damage):
    c=native
    if damage=='source':c.auth.source_hash=lambda:'changed'
    elif damage=='policy':c.auth.policy_hash=lambda:'changed'
    elif damage=='proof':c.auth.root=tmp_path
    else:c.live.fixture.now=NOW+300000
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls and not c.live.transport.signed_payloads


def test_accepted_untriggered_stop_is_incomplete_then_canceled_and_closed(native):
    c=native;r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',(r.get('error'),r.get('native_stop_observations'),r.get('exit_attempts'))
    assert r['protection_accepted'] and r['final_flat']
    assert not r['certification_passed'] and not r['native_protection_qualified']
    assert r['native_qualification_status']=='INCOMPLETE' and not r['small_native_stop_verified']
    assert [a['type'] for a in c.venue.calls]==['order','order','cancel','order']
    assert c.live.fixture.now>=NOW+120000
    assert D(r['realized_pnl']['net_realized_pnl'])<0


def test_one_lot_partial_is_immediately_aborted_without_small_stop(native):
    c=native;c.venue.partial_entry=D('.5');r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert r['partial_entry_aborted_without_native_stop'] and r['final_flat']
    assert [D(a['orders'][0]['s']) for a in c.venue.calls]==[D('.0002'),D('.0001')]
    assert all('trigger' not in a['orders'][0]['t'] for a in c.venue.calls)
    assert not r['native_protection_qualified'] and not r['protection_accepted']


@pytest.mark.parametrize('failure,status', [
    ('entry_rejected','NO_FILL_VERIFIED'),('timeout_before','EMERGENCY_EXIT_REQUIRED'),
    ('summary_without_fill','EMERGENCY_EXIT_REQUIRED'),
    ('disconnect_after_fill','EMERGENCY_EXIT_REQUIRED'),
    ('protection_rejected','TRADE_CLOSED_RECONCILED'),
    ('protection_timeout_before','EMERGENCY_EXIT_REQUIRED')])
def test_failures_never_duplicate_or_claim_protection(native,failure,status):
    c=native;c.venue.fail=failure;r=c.sequence.run()
    assert r['status']==status,r
    assert len([a for a in c.venue.calls if a['type']=='order' and not a['orders'][0]['r']])==1
    assert not r['native_protection_qualified'] and not r['certification_passed']
    if failure=='protection_timeout_before':assert len(c.venue.calls)==2


def test_uncertain_native_cancellation_does_not_submit_competing_ioc(native):
    c=native;c.venue.cancel_uncertain=True;r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and not r.get('final_flat',False),r
    assert len([a for a in c.venue.calls if a['type']=='order'])==2
    assert c.live.account.get_positions() and c.live.account.get_frontend_open_orders()


def test_known_partial_cleanup_uses_exact_residual_only(native):
    c=native;c.venue.partial_exit=D('.6');r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',(r.get('error'),r.get('exit_attempts'))
    assert not c.live.account.get_positions()
    assert all(D(a['orders'][0]['s'])<=D('.0002') for a in c.venue.calls if a['type']=='order')


def test_price_gap_halts_without_widening_floor(native,monkeypatch):
    c=native;c.venue.partial_entry=D('.5');original=c.venue.transmit
    def transmit(payload):
        result=original(payload)
        if not payload['action']['orders'][0]['r']:
            c.live.fixture.book['levels']=[[dict(px='75000',sz='.1')],[dict(px='75010',sz='.1')]]
        return result
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run();assert r['status']=='EMERGENCY_EXIT_REQUIRED',r
    assert len(c.venue.calls)==1 and c.live.account.get_positions()


@pytest.mark.parametrize('change', ['depth','stale','fee','leverage','account'])
def test_entry_gates_retain_original_participation_and_freshness(native,change):
    c=native;context=c.context
    if change=='depth':context=replace(context,quote=replace(context.quote,ask_quantity=D('.0012')))
    elif change=='stale':context=replace(context,account_ms=NOW-5001)
    elif change=='fee':context=replace(context,readiness=replace(context.readiness,fees={'userCrossRate':'.001'}))
    elif change=='leverage':context=replace(context,active_asset={**context.active_asset,'leverage':{'type':'cross','value':2}})
    else:context=replace(context,reconciled=False)
    with pytest.raises(ExchangeError):check_entry(context,c.p,NOW)


def test_prior_certification_table_schema_is_read_only(tmp_path):
    import sqlite3
    path=tmp_path/'certification.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE intents(state TEXT);CREATE TABLE signed_management(state TEXT);')
    require_prior_certification_settled(tmp_path)
    with sqlite3.connect(path) as db:db.execute("INSERT INTO intents VALUES ('UNKNOWN')")
    with pytest.raises(ExchangeError,match='PRIOR_CERTIFICATION_UNRESOLVED'):
        require_prior_certification_settled(tmp_path)


def synthetic_trigger(c, *, quantity, child_state='filled'):
    """Synthetic exchange fixture only; no network or real trigger is generated."""
    row=c.live.journal.intent(c.sequence.prefix+'protection')
    parent=c.venue.statuses[row['cloid']]
    detail=parent['order']['order'];parent['order']['status']='triggered'
    detail['children']=[dict(oid=999)]
    qty=D(quantity);remaining=D(c.p.quantity)-qty;px=D(c.p.stop_limit)
    child=dict(coin=c.p.symbol,side='A',oid=999,cloid=None,sz=str(remaining),
        origSz=c.p.quantity,limitPx=c.p.stop_limit,isTrigger=False,reduceOnly=True,
        orderType='Limit',timestamp=c.live.fixture.now)
    c.venue.statuses['999']=dict(status='order',order=dict(order=child,status=child_state))
    c.live.fixture.orders=[child] if child_state=='open' else []
    if qty:
        fee=qty*px*D(c.p.taker_fee_rate);pnl=qty*(px-D(c.p.entry_limit))
        c.live.fixture.position(remaining,c.p.entry_limit)
        c.live.fixture.fill(qty,side='A',price=str(px),oid=999,tid=999,closed=str(pnl),fee=str(fee))
        balance=c.live.fixture.spot['balances'][0]
        balance['total']=str(D(balance['total'])+pnl-fee)


@pytest.mark.parametrize('quantity,child_state', [('.0002','filled'),('.0001','canceled'),
    ('.0001','open'),('0','rejected')])
def test_trigger_child_actual_ids_reconciled_before_any_cleanup(native,quantity,child_state):
    c=native;done=False
    def wait():
        nonlocal done
        c.live.fixture.now+=1000;c.live.fixture.book['time']=c.live.fixture.now
        for _ in range(2):c.live.clock.observe(c.live.fixture.now,c.live.fixture.now,c.live.fixture.now)
        if not done:
            done=True;synthetic_trigger(c,quantity=quantity,child_state=child_state)
    c.sequence.wait=wait
    r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',(r.get('error'),r.get('native_stop_observations'))
    assert r['final_flat'] and not r['native_protection_qualified']
    assert r['native_trigger_closing_observed']==(quantity=='.0002')
    assert D(r['realized_pnl']['net_realized_pnl'])<0
    exits=[a for a in c.venue.calls if a['type']=='order' and a['orders'][0]['r'] and 'limit' in a['orders'][0]['t']]
    if quantity=='.0002':assert not exits
    else:assert D(exits[-1]['orders'][0]['s'])==D('.0002')-D(quantity)


def test_unknown_child_identity_blocks_ioc_and_false_flatness(native):
    c=native
    def wait():
        c.live.fixture.now+=1000;c.live.fixture.book['time']=c.live.fixture.now
        synthetic_trigger(c,quantity='.0001',child_state='canceled')
        del c.venue.statuses['999']
    c.sequence.wait=wait
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and not r.get('final_flat',False)
    assert len(c.venue.calls)==2 and not r['native_protection_qualified']


def test_expiry_after_entry_never_extends_authority(native):
    c=native
    def wait():
        c.live.fixture.now=NOW+300001;c.live.fixture.book['time']=c.live.fixture.now
    c.sequence.wait=wait
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and not r.get('final_flat',False)
    assert len(c.venue.calls)==2 and c.live.account.get_positions()
    assert c.auth.approval.expires_ms==NOW+300000 and c.auth.revoked


def test_lost_stop_ack_is_read_back_once_without_resubmission(native):
    c=native;c.venue.fail='protection_timeout_after';r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r.get('error')
    assert len([a for a in c.venue.calls if a['type']=='order' and 'trigger' in a['orders'][0]['t']])==1
    assert r['protection_accepted'] and not r['native_protection_qualified']


@pytest.mark.parametrize('field', ['manually_verified_wallets','maximum_one_entry',
    'partial_entry_immediate_ioc_abort_accepted','unprotected_interval_and_residual_risk_accepted',
    'loss_making_cleanup_accepted','acceptance_without_trigger_is_incomplete_accepted',
    'mac_power_app_internet_dependency_accepted'])
def test_runtime_rejects_inexact_approval_before_public_client_or_key(native,tmp_path,monkeypatch,field):
    import hashlib
    import exchange.native_qualification_runtime as rt
    c=native;config=tmp_path/'configs/reliability_policy.json';config.parent.mkdir()
    config.write_bytes((ROOT/'configs/reliability_policy.json').read_bytes())
    evidence=tmp_path/CLOSE_PROOF;evidence.parent.mkdir(parents=True)
    evidence.write_bytes((ROOT/CLOSE_PROOF).read_bytes())
    (tmp_path/'runtime/testnet/anchorium-bot-1').mkdir(parents=True)
    p=replace(c.p,reliability_policy_hash=hashlib.sha256(config.read_bytes()).hexdigest())
    a=replace(c.a,proposal_hash=p.identity,**{field:False})
    monkeypatch.setattr(rt,'active_source_hash',lambda _:p.source_hash)
    monkeypatch.setattr(rt,'require_qualification_regression',lambda *_:None)
    monkeypatch.setattr(rt,'time',SimpleNamespace(time_ns=lambda:NOW*1000000))
    def forbidden(*_,**__):raise AssertionError('NO_PUBLIC_CLIENT_OR_REAL_KEY_BEFORE_APPROVAL')
    monkeypatch.setattr(rt,'HyperliquidClient',forbidden)
    monkeypatch.setattr(rt,'read_api_key',forbidden)
    with pytest.raises(ExchangeError):
        rt.build_native_qualification(tmp_path,p,a,test_receipt=tmp_path/'unused',output=tmp_path)
    assert not (tmp_path/'runtime/testnet/anchorium-bot-1/nonces.sqlite').exists()


def test_runtime_wiring_reaches_mocked_key_only_after_fresh_preflight(native,tmp_path,monkeypatch):
    import hashlib
    import exchange.native_qualification_runtime as rt
    c=native;config=tmp_path/'configs/reliability_policy.json';config.parent.mkdir()
    config.write_bytes((ROOT/'configs/reliability_policy.json').read_bytes())
    evidence=tmp_path/CLOSE_PROOF;evidence.parent.mkdir(parents=True)
    evidence.write_bytes((ROOT/CLOSE_PROOF).read_bytes())
    (tmp_path/'runtime/testnet/anchorium-bot-1').mkdir(parents=True)
    p=replace(c.p,reliability_policy_hash=hashlib.sha256(config.read_bytes()).hexdigest())
    a=replace(c.a,proposal_hash=p.identity)
    monkeypatch.setattr(rt,'active_source_hash',lambda _:p.source_hash)
    monkeypatch.setattr(rt,'require_qualification_regression',lambda *_:None)
    monkeypatch.setattr(rt,'time',SimpleNamespace(time_ns=lambda:NOW*1000000))
    monkeypatch.setattr(rt,'ReadOnlyReceipts',lambda transport,path:transport)
    monkeypatch.setattr(rt,'HyperliquidClient',lambda *_,**__:c.live.client)
    reached=[]
    def end(_):reached.append(True);raise ExchangeError('MOCK_KEY_BOUNDARY_REACHED_WITHOUT_KEY')
    monkeypatch.setattr(rt,'read_api_key',end)
    with pytest.raises(ExchangeError,match='MOCK_KEY_BOUNDARY_REACHED'):
        rt.build_native_qualification(tmp_path,p,a,test_receipt=tmp_path/'unused',output=tmp_path)
    assert reached==[True]
    assert not (tmp_path/'runtime/testnet/anchorium-bot-1/nonces.sqlite').exists()


@pytest.mark.parametrize('interruption',[False,True])
def test_terminal_recovery_failure_still_reports_direct_actual_exposure(native,tmp_path,interruption):
    from exchange.native_qualification_runtime import NativeQualificationRuntime
    c=native;c.live.fixture.position('.0001',c.p.entry_limit)
    def failed_recovery():raise ExchangeError('SYNTHETIC_ORIGINAL_CHILD_UNKNOWN')
    def run():
        c.live.executor.recovery.recover=failed_recovery
        if interruption:raise KeyboardInterrupt()
        return dict(status='EMERGENCY_EXIT_REQUIRED',native_protection_qualified=False)
    c.sequence.run=run
    runtime=NativeQualificationRuntime(ROOT,tmp_path,c.sequence,c.live.client,
        c.live.transport,c.live.nonces,c.live.journal)
    r=runtime.run()
    assert len(r['terminal_readbacks'])==2
    assert all(D(x['positions'][0]['quantity'])==D('.0001') and not x['ready'] for x in r['terminal_readbacks'])
    assert not r['final_flat'] and r['operator_action_required'] and not r['native_protection_qualified']
    assert c.auth.revoked and not c.venue.calls


def test_direct_close_cannot_bypass_unresolved_original_stop(native):
    from exchange.testnet_certification import test_permission as permission
    c=native;c.venue.fail='protection_timeout_before'
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and len(c.venue.calls)==2
    request=OrderRequest(c.p.symbol,'SELL',c.p.quantity,c.p.entry_limit,reduce_only=True,
        strategy_id='TESTNET_CERTIFICATION_EXIT',tif='Ioc',client_order_id=c.sequence.prefix+'exit:0')
    with pytest.raises(ExchangeError,match='QUALIFICATION_EXIT_UNRESOLVED_ORDER'):
        c.live.executor._prepare_context_request(request,permission(request,c.p,NOW),c.context)
    assert len(c.venue.calls)==2
