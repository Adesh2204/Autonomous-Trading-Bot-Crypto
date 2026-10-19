"""Conditional activation adversarial tests. All authority/account data are fixtures."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace as NS
import json
import socket
import threading
import pytest

from exchange.base_exchange import ExchangeError
from exchange.pas_controller import assess
from exchange.conditional_activation import WaitingAuthority,readiness_to_dispatch,wait_for_readiness
from exchange.long_session import require_long_acceptance,ACKS
from exchange.scored_session import SCORED_ACKS
from test_pas_migration import isolated_pas_environment,scored
from test_activation_v3 import funding,NOW


def ready_report():
    return dict(status='OBSERVING',markets=['pas:BTC','pas:EWY'],source_hash='a'*64,
        funding=funding(),account_observed_ms=NOW,
        account=dict(positions=[],open_orders=[],reasons=[]),
        local_execution_state=dict(status='NO_LOCAL_UNRESOLVED_INTENT'),
        stream_connected=True,stream_reconciled=True,account_stream_healthy=True,
        release_verification=dict(verified=True,source_hash='a'*64),
        native_proof_verification=dict(verified=True,markets=['pas:BTC','pas:EWY'],residual_scope_verified=True),
        market_history={s:dict(strategy_history_ready=True,latest_completed_ms=NOW) for s in ('pas:BTC','pas:EWY')},
        signals=[dict(symbol='pas:BTC',decision='LONG',observed_ms=NOW)],
        liquidity={s:dict(active_asset=dict(leverage=dict(type='cross',value=20)),active_asset_ms=NOW,
            evidence_evaluation=dict(observed_ms=NOW,economically_viable_notional='10')) for s in ('pas:BTC','pas:EWY')})


def fake_authority():
    # Dispatch tests use no signer or builder; actual approval validation has
    # separate adversarial tests below and the existing full contract suites.
    return NS(require=lambda:None,consume_wait=lambda:None,clock_ms=lambda:NOW,
        m=NS(identity='fixture-only',daily=NS(markets=('pas:BTC','pas:EWY'),source_hash='a'*64,expires_ms=NOW+3600000),entry_cutoff_buffer_ms=120000))


def test_no_cross_market_native_history_signal_composition():
    r=ready_report();r['native_proof_verification']['markets']=['pas:BTC']
    r['signals']=[dict(symbol='pas:EWY',decision='LONG',observed_ms=NOW)]
    a=assess(r,NOW)
    assert a['gates']['NATIVE_PROTECTION_QUALIFIED'] and a['gates']['MARKET_HISTORY_READY']
    assert not a['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE'] and a['eligible_markets']==['pas:BTC']
    r['signals'][0]['symbol']='pas:BTC'
    assert assess(r,NOW)['opportunity_markets']==['pas:BTC']


def test_residual_scope_is_matched_to_the_same_market():
    r=ready_report();r['native_proof_verification']['residual_markets']=['pas:EWY']
    assert not assess(r,NOW)['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE']
    r['signals'][0]['symbol']='pas:EWY'
    assert assess(r,NOW)['opportunity_markets']==['pas:EWY']


@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity','bad',None,{},'-1','0'])
def test_malformed_or_unbounded_capacity_is_blocked_without_crashing(value):
    r=ready_report();r['liquidity']['pas:BTC']['evidence_evaluation']['economically_viable_notional']=value
    assert not assess(r,NOW)['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE']


@pytest.mark.parametrize('field',['observed_ms','capacity_ms'])
@pytest.mark.parametrize('at',[None,True,NOW+1,NOW-5001])
def test_signal_and_capacity_have_independent_freshness(field,at):
    r=ready_report()
    if field=='observed_ms':r['signals'][0]['observed_ms']=at
    else:r['liquidity']['pas:BTC']['evidence_evaluation']['observed_ms']=at
    assert not assess(r,NOW)['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE']


@pytest.mark.parametrize('fault',['funding','unknown','leverage','history','native','source','account',
    'orders','positions','stream','account_stream','scope','cutoff'])
def test_conditional_dispatch_requires_every_gate_and_no_exposure(fault):
    r=ready_report();a=fake_authority();assert readiness_to_dispatch(r,a,NOW)
    if fault=='funding':r['funding']['status']='USDP_ZERO'
    elif fault=='unknown':r['local_execution_state']['status']='BLOCKED_UNRESOLVED_INTENT'
    elif fault=='leverage':r['liquidity']['pas:BTC']['active_asset']['leverage']['value']=1
    elif fault=='history':r['market_history']={}
    elif fault=='native':r['native_proof_verification']={}
    elif fault=='source':r['release_verification']['source_hash']='b'*64
    elif fault=='account':r['account_observed_ms']=NOW-360001
    elif fault=='orders':r['account']['open_orders']=[{}]
    elif fault=='positions':r['account']['positions']=[{}]
    elif fault=='stream':r['stream_reconciled']=False
    elif fault=='account_stream':r['account_stream_healthy']=False
    elif fault=='scope':r['markets']=['pas:BTC']
    else:a.m.daily.expires_ms=NOW+120000
    assert not readiness_to_dispatch(r,a,NOW)


def test_approval_validation_is_read_only_and_cannot_accept_before_start(tmp_path):
    m=scored();a=dict(mandate_hash=m.identity,operator_acceptance='OFFLINE_FIXTURE_ONLY',
        accepted_ms=m.created_ms+1,expires_ms=m.daily.expires_ms,**{k:True for k in ACKS+SCORED_ACKS})
    p=tmp_path/'acceptance.json';p.write_text(json.dumps(a));original=p.read_bytes()
    kw=dict(team=m.daily.team_wallet,signer=m.daily.api_wallet,source_hash=lambda:m.daily.source_hash,
        policy_hash=lambda:m.reliability_sha256,host=socket.gethostname())
    assert require_long_acceptance(m,p,now_ms=m.created_ms+1,**kw)==a
    with pytest.raises(ExchangeError):require_long_acceptance(m,p,now_ms=m.daily.starts_ms-1,**kw)
    assert p.read_bytes()==original and list(tmp_path.iterdir())==[p]


@pytest.mark.parametrize('fault',['expiry','ack','tamper','revocation','source','evidence'])
def test_wait_uses_the_same_exact_acceptance_rules(tmp_path,fault):
    m=scored();p=tmp_path/'acceptance.json';p.write_text(json.dumps(dict(mandate_hash=m.identity,
        operator_acceptance='OFFLINE_FIXTURE_ONLY',accepted_ms=m.created_ms+1,
        expires_ms=m.daily.expires_ms,**{k:True for k in ACKS+SCORED_ACKS})))
    evidence=tmp_path/'raw';evidence.write_text('original')
    from exchange.long_session import sha
    expected={str(evidence):sha(evidence)};before=json.loads(p.read_text());now=m.created_ms+1
    if fault=='expiry':now=m.daily.expires_ms
    elif fault=='ack':v=deepcopy(before);v[SCORED_ACKS[0]]=False;p.write_text(json.dumps(v));before=v
    elif fault=='tamper':p.write_text('{}')
    elif fault=='revocation':p.with_name('session_revocation.json').write_text('{}')
    elif fault=='evidence':evidence.write_text('changed')
    with pytest.raises(ExchangeError):require_long_acceptance(m,p,now_ms=now,
        team=m.daily.team_wallet,signer=m.daily.api_wallet,source_hash=lambda:'bad' if fault=='source' else m.daily.source_hash,
        policy_hash=lambda:m.reliability_sha256,host=socket.gethostname(),bound_evidence=expected,expected_acceptance=before)


def test_duplicate_wait_is_consumed_once_across_output_directories(tmp_path):
    a=WaitingAuthority.__new__(WaitingAuthority);a.args=NS(mandate=tmp_path/'mandate.json');a.m=scored();a.clock_ms=lambda:NOW
    a.consume_wait()
    with pytest.raises(ExchangeError,match='ALREADY_CONSUMED'):a.consume_wait()
    r=json.loads((tmp_path/'activation_wait_started.json').read_text())
    assert r['signing_authority']=='NONE' and not r['restart_permitted']
    assert not (tmp_path/'acceptance.json').exists()


@pytest.mark.parametrize('fault',['none','outer_stop','no_signal','thread','flat','database','halt'])
def test_wait_closes_public_observer_before_single_runtime_handoff(tmp_path,fault):
    a=fake_authority();stop=threading.Event();events=[]
    def observe(root,out,cancel,publish,**kw):
        assert kw['venue']=='pas' and kw['markets']==a.m.daily.markets
        r=ready_report()
        if fault=='no_signal':r['signals']=[]
        publish(r);events.append(('public_stopped',cancel.is_set()))
        if fault=='outer_stop':stop.set()
        return dict(status='HALTED' if fault=='halt' else 'STOPPED',threads_stopped=fault!='thread',
            terminal_flat=fault!='flat',journal_integrity='bad' if fault=='database' else 'ok',history_integrity='ok')
    args=NS(scan_seconds=60)
    if fault=='none':
        assert wait_for_readiness(tmp_path,args,stop,lambda v:v,tmp_path,observe=observe,authority=a)['terminal_flat']
        assert events==[('public_stopped',True)]
    else:
        with pytest.raises(ExchangeError,match='WITHOUT_DISPATCH'):
            wait_for_readiness(tmp_path,args,stop,lambda v:v,tmp_path,observe=observe,authority=a)
    assert (tmp_path/'activation_observation_result.json').exists()


def test_actual_activity_requires_owned_transmitted_fill_and_current_authority():
    from exchange.trading_status import authorized_status
    limits=NS(team_wallet='t',api_wallet='a',markets=('pas:BTC',),starts_ms=NOW,expires_ms=NOW+3600000)
    auth=NS(m=NS(daily=limits),require=lambda *a:None,data=dict(owned={'k':{}},transmissions=[]))
    fills={'fill':NS(order_id='1',symbol='pas:BTC',timestamp_ms=NOW)}
    r=NS(authorization=auth,journal=NS(intents=lambda:[dict(intent_key='k',oid=1)]),
        session=NS(recovery=NS(state=NS(fills=fills)),account_stream=NS(healthy=True),
            execution=NS(daily=NS(state=NS(value='FLAT')),entries_paused=False)),market_stream=NS(connected=True,reconciled=True))
    assert authorized_status(r,NOW)['TRADING_AUTHORIZED'] and not authorized_status(r,NOW)['AUTO_TRADING_ACTIVE']
    auth.data['transmissions']=[dict(key='k',kind='entry')]
    assert authorized_status(r,NOW)['AUTO_TRADING_ACTIVE']
    fills['fill'].order_id='other';assert not authorized_status(r,NOW)['AUTO_TRADING_ACTIVE']
    fills['fill'].order_id='1';r.session.execution.entries_paused=True
    assert not authorized_status(r,NOW)['AUTO_TRADING_ACTIVE']


def test_cli_rejects_wait_without_real_authorized_files_before_state_creation(tmp_path):
    from test_terminal_app import command
    p=command('start','--venue','pas','--wait-for-readiness','--state',tmp_path/'state')
    assert p.returncode==1 and 'CONDITIONAL_WAIT_REQUIRES_EXACT_AUTHORIZED_PAS_MODE' in p.stdout+p.stderr
    assert not (tmp_path/'state').exists()


def test_retired_authorized_wait_rejects_before_state_or_signer_creation(tmp_path):
    from test_terminal_app import command
    state=tmp_path/'state'
    p=command('start','--venue','pas','--authorized','--wait-for-readiness','--state',state)
    assert p.returncode==1
    failure=json.loads(p.stderr)
    assert failure['error']=='RETIRED_AUTHORIZED_TERMINAL_ROUTE'
    assert failure['signing_authority']=='NONE_CREATED_BY_THIS_COMMAND'
    assert not state.exists()


@pytest.mark.parametrize('at',[None,True,'bad',{},NOW+1,NOW-360001])
def test_corrupt_cached_funding_clock_cannot_crash_or_qualify(at):
    from exchange.pas_funding import current_funding
    f=funding();f['observed_ms']=at
    assert current_funding(f,NOW)['status'] in {'USDP_STALE','USDP_UNAVAILABLE'}
