"""Delegated authorization over real execution composition, no actual exchange.

Ephemeral fixtures and simulated fills never certify team trading or protection.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal as D
from datetime import datetime, timezone, timedelta
import importlib.util, json
from pathlib import Path
from types import SimpleNamespace
import pytest
from exchange.base_exchange import ExchangeError
from exchange.delegated_qualification import (SessionMandate, SessionAcceptance, Delegation,
    DelegatedAuthorization, SESSION_SCOPE, ACKNOWLEDGMENTS, validate_proposal, revoke_session)
from exchange.emergency_qualification import (EmergencySequence, EmergencyComplianceScope,
    permission, build_runtime)
from test_qualification_price_guard import bounded, moved, move_venue, draft
from test_emergency_qualification import emergency
from test_live_exchange_execution import live, response
from test_exchange_migration import NOW


@pytest.fixture
def delegated(bounded, monkeypatch, tmp_path):
    import exchange.delegated_qualification as module
    monkeypatch.setattr(module, 'START_MS', NOW-3600000)
    monkeypatch.setattr(module, 'END_MS', NOW+8*3600000)
    c = bounded
    m = SessionMandate('ab'*16, NOW, 'fixture-source', 'fixture-policy',
        team_wallet=c.p.team_wallet, api_wallet=c.p.api_wallet, expires_ms=module.END_MS).require()
    a = SessionAcceptance(m.identity, 'SYNTHETIC_EXPLICIT_SESSION_ACCEPTANCE', NOW, m.expires_ms,
        **{k:True for k in ACKNOWLEDGMENTS})
    path=tmp_path/'session_acceptance.json';path.write_text(json.dumps(asdict(a)))
    delegation=Delegation(m,a,str(path))
    auth=DelegatedAuthorization(c.p,delegation,c.live.journal,clock_ms=lambda:c.live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    auth.register_runtime()
    c.m,c.a,c.delegation,c.auth,c.acceptance_path=m,a,delegation,auth,path
    c.venue.auth=auth;c.live.transport.authorization=auth
    c.sequence=EmergencySequence(c.live.executor,c.p,auth)
    return c


def replace_acceptance(c, **values):
    a=replace(c.a,**values);c.acceptance_path.write_text(json.dumps(asdict(a)))
    c.auth.delegation=replace(c.delegation,acceptance=a);c.auth.approval=a


def test_real_calendar_end_is_october_14_2359_ist():
    import exchange.delegated_qualification as module
    ist=timezone(timedelta(hours=5,minutes=30))
    assert datetime.fromtimestamp(module.END_MS/1000,ist).isoformat()=='2026-10-14T23:59:00+05:30'
    assert SESSION_SCOPE['maximum_opening_notional']=='20'
    assert SESSION_SCOPE['quantity']=='0.0002' and SESSION_SCOPE['maximum_buy_price']=='100000'


@pytest.mark.parametrize('key,value',[('network','mainnet'),('dex','pa'),('symbol','par:ETH'),
    ('quantity','0.0003'),('maximum_opening_notional','1000'),('maximum_buy_price','100001'),
    ('leverage',2),('margin_mode','isolated'),('side','SELL'),('tif','Gtc'),
    ('entry_attempts',2),('exit_attempts',3),('signed_actions',5),('l2_participation','1'),
    ('qualification_spread_bps','51'),('protection','VERIFIED')])
def test_mandate_cannot_enlarge_or_change_scope(delegated,key,value):
    scope=dict(delegated.m.scope,**{key:value})
    with pytest.raises(ExchangeError):replace(delegated.m,scope=scope).require()
    assert not delegated.venue.calls


@pytest.mark.parametrize('field', ACKNOWLEDGMENTS)
def test_every_genuine_session_risk_acknowledgment_required(delegated,field):
    c=delegated;replace_acceptance(c,**{field:False})
    result=c.sequence.run()
    assert result['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls and not c.live.transport.signed_payloads


@pytest.mark.parametrize('field,value',[('session_hash','wrong-session'),('operator_acceptance',''),
    ('accepted_ms',NOW+1),('accepted_ms',NOW-1),('expires_ms',NOW),('expires_ms',NOW+8*3600000+1)])
def test_session_acceptance_is_not_synthesized_or_backdated(delegated,field,value):
    c=delegated;replace_acceptance(c,**{field:value})
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


@pytest.mark.parametrize('how',['file','durable','missing','changed'])
def test_revocation_or_acceptance_file_change_blocks_signing(delegated,how):
    c=delegated
    if how=='file':c.acceptance_path.with_name('session_revocation.json').write_text('{}')
    if how=='durable':revoke_session(c.live.journal,c.m,NOW,reason='SYNTHETIC_REVOKE')
    if how=='missing':c.acceptance_path.unlink()
    if how=='changed':c.acceptance_path.write_text(json.dumps(dict(asdict(c.a),operator_acceptance='other')))
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.live.transport.signed_payloads


@pytest.mark.parametrize('what',['source','policy','signer','team','expiry'])
def test_identity_source_and_expiry_are_session_bound(delegated,what):
    c=delegated
    if what=='source':c.auth.source_hash=lambda:'changed-source'
    if what=='policy':c.auth.policy_hash=lambda:'changed-policy'
    if what=='expiry':c.live.fixture.now=c.m.expires_ms
    if what in {'signer','team'}:
        with pytest.raises(ExchangeError):
            c.auth.require('0x'+'3'*40 if what=='team' else c.m.team_wallet,
                '0x'+'4'*40 if what=='signer' else c.m.api_wallet)
    else:assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls


@pytest.mark.parametrize('bid,ask',[('83380','83420'),('83440','83470'),('83560','83600')])
def test_session_uses_existing_fresh_price_rule_in_real_composition(delegated,bid,ask):
    c=delegated;move_venue(c,bid,ask)
    result=c.sequence.run()
    assert result['status']=='TRADE_CLOSED_RECONCILED',result
    entry=c.venue.calls[0]['orders'][0]
    assert D(entry['s'])==D('.0002') and D(entry['p'])*D(entry['s'])<=20
    assert D(entry['p'])==min(c.context.spec.normalize_price(D(ask)*D('1.001'),'BUY'),D(c.p.max_buy_price))
    assert result['final_flat'] and not result['protection_accepted']
    assert not result['certification_passed'] and not result['live_ready']


@pytest.mark.parametrize('field,value',[('symbol','par:ETH'),('quantity','.0003'),('max_buy_price','110000'),
    ('source_hash','other'),('reliability_policy_hash','other'),('price_authorization_mode','FIXED_LIMIT_V1')])
def test_generated_proposal_must_fit_session_not_outer_thousand_cap(delegated,field,value):
    c=delegated;values={field:value}
    if field=='quantity':values.update(quantity_ceiling=value,entry_notional_ceiling=str(D(value)*D(c.p.entry_limit)))
    if field=='max_buy_price':values.update(entry_limit=value,entry_notional_ceiling=str(D(value)*D(c.p.quantity)))
    with pytest.raises(ExchangeError):validate_proposal(c.m,replace(c.p,**values))


def test_current_mark_exposure_cannot_exceed_twenty(delegated):
    c=delegated;ctx,book=moved(c,'83400','83440',mark='100001',oracle='100001')
    with pytest.raises(ExchangeError,match='TWENTY'):
        c.auth.require_context(ctx,draft(c))
    assert not c.live.transport.signed_payloads


def test_floor_is_derived_from_reviewed_bid_not_discretionary(delegated):
    c=delegated;p=replace(c.p,exit_bound='82000',stop_limit='82000').require()
    with pytest.raises(ExchangeError,match='ALGORITHMIC'):
        validate_proposal(c.m,p,c.context.spec)


def test_stale_quote_preserves_existing_entry_guard(delegated):
    c=delegated;c.live.fixture.book['time']=NOW-5001
    assert c.sequence.run()['status'] in {'PREFLIGHT_BLOCKED','EMERGENCY_EXIT_REQUIRED'}
    assert not c.venue.calls


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_actual_quantity_zero_partial_full_is_reconciled_without_repeat(delegated,fraction):
    c=delegated;c.venue.partial_entry=D(fraction);result=c.sequence.run()
    assert result['status']==('NO_FILL_VERIFIED' if fraction=='0' else 'TRADE_CLOSED_RECONCILED'),result
    assert len([a for a in c.venue.calls if not a['orders'][0]['r']])==1
    assert result['final_flat']
    if fraction!='0':assert D(c.venue.calls[-1]['orders'][0]['s'])==D('.0002')*D(fraction)
    with pytest.raises(ExchangeError):c.auth.require(c.m.team_wallet,c.m.api_wallet)


@pytest.mark.parametrize('fail',['entry_rejected','timeout_before','timeout_after_fill','disconnect_after_fill'])
def test_uncertain_or_rejected_entry_never_refreshes_into_second_entry(delegated,fail):
    c=delegated;c.venue.fail=fail;result=c.sequence.run()
    assert len([a for a in c.venue.calls if not a['orders'][0]['r']])==1
    assert result['status']=={'entry_rejected':'NO_FILL_VERIFIED','timeout_after_fill':'TRADE_CLOSED_RECONCILED'}.get(fail,'EMERGENCY_EXIT_REQUIRED')


def test_partial_exit_handles_one_lot_exact_residual(delegated):
    c=delegated;c.venue.partial_exit=D('.6');result=c.sequence.run()
    assert result['status']=='TRADE_CLOSED_RECONCILED',result
    assert [D(a['orders'][0]['s']) for a in c.venue.calls]==[D('.0002'),D('.0002'),D('.0001')]


def test_rejected_exits_halt_and_preserve_unprotected_residual(delegated,monkeypatch):
    c=delegated;original=c.venue.transmit
    def rejected(payload):
        if payload['action']['orders'][0]['r']:
            c.auth.claim_transmission(payload['action']);c.venue.calls.append(deepcopy(payload['action']))
            return response({'error':'Order must have minimum value of $10.'})
        return original(payload)
    monkeypatch.setattr(c.live.transport,'transmit',rejected)
    result=c.sequence.run()
    assert result['status']=='EMERGENCY_EXIT_REQUIRED' and not result.get('final_flat')
    assert len(c.venue.calls)==3 and c.live.account.get_position('par:BTC')


def test_restart_cannot_resume_a_registered_runtime_even_without_order(delegated):
    c=delegated
    fresh=DelegatedAuthorization(c.p,c.delegation,c.live.journal,clock_ms=lambda:NOW,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    with pytest.raises(ExchangeError,match='RESTART_READ_ONLY'):fresh.require(c.m.team_wallet,c.m.api_wallet)
    assert not c.venue.calls


def test_duplicate_submit_returns_original_intent_and_price(delegated):
    c=delegated;c.live.executor.entries_paused=False;req=draft(c)
    first=c.live.executor.submit(req,permission=permission(req,c.p,NOW))
    move_venue(c,'83380','83420')
    second=c.live.executor.submit(req,permission=permission(req,c.p,NOW))
    assert first.cloid==second.cloid and first.request.price==second.request.price
    assert len(c.venue.calls)==1


def test_future_envelope_needs_no_fabricated_human_price_approval(delegated):
    c=delegated;p=replace(c.p,observed_ms=NOW+1000,candidate_evidence_hash='new-book-hash')
    validate_proposal(c.m,p,c.context.spec)
    assert p.identity!=c.p.identity and c.a.session_hash==c.m.identity
    assert not hasattr(c.a,'proposal_hash') and not hasattr(c.a,'approved_ms')


def test_revocation_after_filling_prevents_further_writes_and_escalates(delegated,monkeypatch):
    c=delegated;original=c.venue.transmit
    def transmit(payload):
        result=original(payload)
        if not payload['action']['orders'][0]['r']:
            revoke_session(c.live.journal,c.m,NOW,reason='SYNTHETIC_POST_FILL_REVOCATION')
        return result
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    result=c.sequence.run()
    assert result['status']=='EMERGENCY_EXIT_REQUIRED' and c.live.account.get_position('par:BTC')
    assert len(c.venue.calls)==1 and not result.get('final_flat')


def launcher(monkeypatch):
    root=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('delegated_fixture_launcher',root/'scripts/run_delegated_qualification.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_missing_acceptance_cannot_even_start_readiness_or_sdk(delegated,monkeypatch,tmp_path):
    c=delegated;module=launcher(monkeypatch);c.acceptance_path.unlink()
    def forbidden(*a,**k):raise AssertionError('ACTUAL_PREPARATION_OR_SIGNER_PROHIBITED')
    monkeypatch.setattr(module,'prepare',forbidden);monkeypatch.setattr(module,'build_runtime',forbidden)
    result=module.execute_session(tmp_path/'never_signed',c.delegation,tmp_path/'receipt.json')
    assert result['status']=='SESSION_HALTED' and not result['authorized_entry_attempted']


def test_legacy_exact_proposal_route_does_not_accept_session_object(delegated):
    from exchange.emergency_qualification import EmergencyAuthorization
    c=delegated;auth=EmergencyAuthorization(c.p,c.a,c.live.journal,clock_ms=lambda:NOW,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    with pytest.raises(ExchangeError):auth.require(c.m.team_wallet,c.m.api_wallet)


def test_session_acceptance_template_stays_blank(delegated):
    c=delegated;template=asdict(SessionAcceptance(c.m.identity,'',None,None))
    assert template['operator_acceptance']=='' and template['accepted_ms'] is None
    assert all(template[k] is False for k in ACKNOWLEDGMENTS)


def test_per_envelope_expiry_still_applies_during_long_session(delegated):
    c=delegated;c.live.fixture.now=NOW+300000
    assert c.live.fixture.now<c.m.expires_ms
    with pytest.raises(ExchangeError):c.auth.require(c.m.team_wallet,c.m.api_wallet)
    assert not c.venue.calls


def runner_fixture(c,monkeypatch,tmp_path):
    module=launcher(monkeypatch);monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'require_release',lambda receipt:receipt)
    monkeypatch.setattr(module,'source_unchanged',lambda *a:None)
    monkeypatch.setattr(module,'require_unused_runtime',lambda *a:None)
    monkeypatch.setattr(module,'prior_execution_check',lambda *a:None)
    monkeypatch.setattr(module,'persist_price_diagnostics',lambda *a:None)
    monkeypatch.setattr(module,'PaperOwner',lambda *a:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(module.time,'sleep',lambda seconds:None)
    clock=[NOW];monkeypatch.setattr(module,'now_ms',lambda:clock[0])
    return module,clock


def observed(c,**kwargs):
    return dict(status='AWAITING_EXACT_HUMAN_RISK_APPROVAL',source_hash_after='fixture-source',
        proposal=asdict(c.p),**kwargs)


def test_read_only_observation_can_wait_until_cutoff_without_any_runtime(delegated,monkeypatch,tmp_path):
    c=delegated;module,clock=runner_fixture(c,monkeypatch,tmp_path)
    def prepare(*a,**k):
        clock[0]=c.m.expires_ms-60000
        return dict(status='NO_CURRENT_QUALIFICATION_PROPOSAL',source_hash_after='fixture-source')
    monkeypatch.setattr(module,'prepare',prepare)
    def forbidden(*a,**k):raise AssertionError('NO_ELIGIBLE_MARKET_MUST_NOT_CONSTRUCT_SIGNER')
    monkeypatch.setattr(module,'build_runtime',forbidden)
    result=module.execute_session(tmp_path/'observation_only',c.delegation,tmp_path/'receipt')
    assert result['status']=='SESSION_ENTRY_WINDOW_CLOSED_NO_SUBMISSION'
    assert not result['authorized_entry_attempted'] and len(result['observations'])==1


def test_revocation_after_read_only_refresh_prevents_runtime_construction(delegated,monkeypatch,tmp_path):
    c=delegated;module,clock=runner_fixture(c,monkeypatch,tmp_path)
    def prepare(*a,**k):
        c.acceptance_path.with_name('session_revocation.json').write_text('{}');return observed(c)
    monkeypatch.setattr(module,'prepare',prepare)
    def forbidden(*a,**k):raise AssertionError('REVOKED_SESSION_MUST_NOT_CONSTRUCT_SIGNER')
    monkeypatch.setattr(module,'build_runtime',forbidden)
    result=module.execute_session(tmp_path/'revoked_during_reads',c.delegation,tmp_path/'receipt')
    assert result['status']=='SESSION_HALTED' and not result['authorized_entry_attempted']


@pytest.mark.parametrize('blocker',['ACCOUNT_NOT_READY','API_WALLET_EXPIRED','EXCHANGE_CONTEXT_UNAVAILABLE'])
def test_account_or_signing_failure_is_never_read_only_retry_permission(delegated,monkeypatch,tmp_path,blocker):
    c=delegated;module,clock=runner_fixture(c,monkeypatch,tmp_path)
    monkeypatch.setattr(module,'prepare',lambda *a,**k:dict(status='QUALIFICATION_LOCKED',blocker=blocker,
        source_hash_after='fixture-source'))
    def forbidden(*a,**k):raise AssertionError('UNHEALTHY_ACCOUNT_MUST_NOT_CONSTRUCT_SIGNER')
    monkeypatch.setattr(module,'build_runtime',forbidden)
    result=module.execute_session(tmp_path/'unhealthy',c.delegation,tmp_path/'receipt')
    assert result['status']=='SESSION_HALTED' and not result['authorized_entry_attempted']
    assert len(result['observations'])==1


def test_pre_transmission_price_rejection_allows_only_new_reads_then_one_workflow(delegated,monkeypatch,tmp_path):
    c=delegated;module,clock=runner_fixture(c,monkeypatch,tmp_path);builds=[];runs=[]
    monkeypatch.setattr(module,'prepare',lambda *a,**k:observed(c))
    def run():
        runs.append(1);return dict(status='NO_FILL_VERIFIED',final_flat=True,
            whitelist_trade_proof=dict(fill_verified=False,final_flat_verified=True))
    runtime=SimpleNamespace(run=run,close=lambda:None)
    def build(*a,**k):
        builds.append(k)
        if len(builds)==1:raise ExchangeError('P0_CURRENT_PRICE_OR_CAP_REQUIRED')
        return runtime
    monkeypatch.setattr(module,'build_runtime',build)
    result=module.execute_session(tmp_path/'bounded',c.delegation,tmp_path/'receipt')
    assert result['status']=='NO_FILL_VERIFIED' and len(builds)==2 and len(runs)==1
    assert all(k['delegation'] is c.delegation for k in builds)
    assert (tmp_path/'bounded/NO_FILL_VERIFICATION.json').exists()
    assert not (tmp_path/'bounded/WHITELIST_TRADE_PROOF.json').exists()


def test_runtime_result_uncertain_ends_session_instead_of_observing_another_entry(delegated,monkeypatch,tmp_path):
    c=delegated;module,clock=runner_fixture(c,monkeypatch,tmp_path);reads=[]
    def prepare(*a,**k):reads.append(1);return observed(c)
    monkeypatch.setattr(module,'prepare',prepare)
    runtime=SimpleNamespace(run=lambda:dict(status='EMERGENCY_EXIT_REQUIRED',operator_action_required=True,
        whitelist_trade_proof=dict(fill_verified=False,final_flat_verified=False)),close=lambda:None)
    monkeypatch.setattr(module,'build_runtime',lambda *a,**k:runtime)
    result=module.execute_session(tmp_path/'uncertain',c.delegation,tmp_path/'receipt')
    assert result['status']=='EMERGENCY_EXIT_REQUIRED' and len(reads)==1
    assert not result['final_flat_verified']


def test_actual_transport_expiry_is_short_envelope_not_whole_session(delegated,monkeypatch):
    from exchange.emergency_qualification import EmergencySDKTransport
    from exchange.sdk_transport import OfficialSDKTransport
    c=delegated;called=[]
    def initialized(*a,**k):called.append(1)
    monkeypatch.setattr(OfficialSDKTransport,'__init__',initialized)
    transport=EmergencySDKTransport(c.live.client,c.live.signer,c.m.team_wallet,c.live.nonces,c.auth,
        rate_limits=c.live.rate)
    assert called==[1] and transport.action_expiry_ms==NOW+300000
    assert transport.action_expiry_ms<c.m.expires_ms


def test_price_guard_new_final_read_rejects_abrupt_move_even_with_session(delegated):
    c=delegated;ctx,book=moved(c,'83400','83440')
    from exchange.emergency_qualification import calculate_bounded_entry
    req=calculate_bounded_entry(ctx,c.p,NOW,book);c.live.executor.entries_paused=False
    move_venue(c,'83270','83300')
    with pytest.raises(ExchangeError,match='P0_CURRENT_PRICE_OR_CAP_REQUIRED'):
        c.live.executor._guard(ctx,NOW,entry=True,entry_request=req)
    assert not c.live.transport.signed_payloads
