"""Opening diagnostics regressions; no network, key, acceptance or order."""
from copy import deepcopy
import json
import time

import pytest
from exchange.operator_status import current_status
from exchange.paper_operations import atomic_json
from test_terminal_app import command
from test_activation_v3 import NOW, funding


def active_snapshot():
    return dict(mode='AUTHORIZED TESTNET TRADING',status='POSITION_OPEN', trading_status='TRADING_ACTIVE',
        source_hash='a'*64, session_id='session', pid=123, updated_ms=NOW,
        expires_ms=NOW+60000, TRADING_AUTHORIZED=True, AUTO_TRADING_ACTIVE=True,
        authorization_valid=True, signing_authority='EXACT_BOUNDED_LONG_MANDATE',
        exchange_activity_confirmed=True)


@pytest.mark.parametrize('fault', ['dead', 'stale', 'future', 'source', 'session', 'pid', 'expired', 'paused', 'no_expiry', 'public', 'invalid'])
def test_cached_authority_never_survives_lost_current_evidence(fault):
    value=active_snapshot();current=dict(session_id='session',pid=123)
    now=NOW;source='a'*64
    if fault=='stale':value['updated_ms']=NOW-180001
    if fault=='future':value['updated_ms']=NOW+1
    if fault=='source':source='b'*64
    if fault=='session':current['session_id']='other'
    if fault=='pid':current['pid']=456
    if fault=='expired':now=value['expires_ms']
    if fault=='paused':value['trading_status']='TRADING_PAUSED'
    if fault=='no_expiry':value.pop('expires_ms')
    if fault=='public':value['mode']='TESTNET OBSERVATION'
    if fault=='invalid':value['authorization_valid']=False
    before=deepcopy(value)
    result=current_status(value,current,running=fault!='dead',now_ms=now,source_hash=source)
    assert not result['TRADING_AUTHORIZED'] and not result['AUTO_TRADING_ACTIVE']
    assert not result['authorization_valid'] and not result['authority_observation_current']
    assert result['signing_authority']=='REVOKED_OR_UNAVAILABLE'
    assert result['exchange_activity_confirmed']  # retain historical fill evidence
    assert value==before


def test_current_authorized_snapshot_uses_trading_health_not_position_state():
    value=active_snapshot()
    result=current_status(value,dict(session_id='session',pid=123),running=True,now_ms=NOW,source_hash='a'*64)
    assert result['TRADING_AUTHORIZED'] and result['AUTO_TRADING_ACTIVE']
    assert result['status']=='POSITION_OPEN'


@pytest.mark.parametrize('name', ['status', 'report', 'dashboard'])
def test_all_cli_views_reject_cached_authority_and_preserve_source_file(tmp_path,name):
    value=active_snapshot();value['updated_ms']=time.time_ns()//1000000
    atomic_json(tmp_path/'current.json',dict(session_id='session',output=str(tmp_path),pid=123))
    atomic_json(tmp_path/'status.json',value);before=(tmp_path/'status.json').read_bytes()
    args=('dashboard','--state',tmp_path,'--once') if name=='dashboard' else (name,'--state',tmp_path)
    p=command(*args);assert p.returncode==0,p.stderr
    if name=='status':
        r=json.loads(p.stdout)
        assert not r['TRADING_AUTHORIZED'] and not r['AUTO_TRADING_ACTIVE']
        assert r['status']=='INTERRUPTED_UNCLEAN'
    else:assert 'EXACT_BOUNDED_LONG_MANDATE' not in p.stdout
    assert (tmp_path/'status.json').read_bytes()==before


def test_read_clock_expires_public_funding_history_and_release_without_writing():
    value=dict(mode='TESTNET OBSERVATION',dex='pas',status='OBSERVING',source_hash='a'*64,
        updated_ms=NOW,session_id='session',pid=123,funding=funding(),account_observed_ms=NOW,
        fees_observed_ms=NOW,release_verification=dict(verified=True,source_hash='a'*64),
        market_history={'pas:BTC':dict(strategy_history_ready=True,latest_completed_ms=NOW)})
    before=deepcopy(value)
    r=current_status(value,dict(session_id='session',pid=123),running=True,now_ms=NOW+360001,source_hash='b'*64)
    assert r['funding']['status']=='USDP_STALE' and r['account_age_ms']==360001
    assert r['fee_age_ms']==360001 and r['market_history']['pas:BTC']['cache_age_ms']==360001
    assert not r['readiness']['gates']['MARKET_HISTORY_READY']
    assert not r['readiness']['gates']['SOURCE_RELEASE_VERIFIED']
    assert value==before


@pytest.mark.parametrize('name,status', [('history-review','HISTORY_REVIEW_INCOMPLETE'),
    ('configuration-review','DISCOVERY_INCOMPLETE')])
def test_incomplete_read_diagnostic_exits_nonzero(monkeypatch,tmp_path,name,status,capsys):
    import sys
    from exchange import pas_operations
    from exchange.terminal_app import main
    monkeypatch.setattr(pas_operations,'dispatch',lambda *a:dict(status=status,signing_authority='NONE'))
    monkeypatch.setattr(sys,'argv',['anchorium_cli.py',name,'--output',str(tmp_path/'unused')])
    assert main(tmp_path)==1
    assert json.loads(capsys.readouterr().out)['status']==status


def test_missing_fill_evidence_cannot_show_active_trading():
    value=active_snapshot();value['exchange_activity_confirmed']=False
    result=current_status(value,dict(session_id='session',pid=123),running=True,now_ms=NOW,source_hash='a'*64)
    assert result['TRADING_AUTHORIZED'] and not result['AUTO_TRADING_ACTIVE']


def test_opening_check_independent_states_and_no_cached_claims(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from exchange import opening_audit,terminal_app
    from test_activation_v5_2 import ready_report
    from exchange.testnet_certification import TEAM
    value=ready_report();value.update(mode='TESTNET OBSERVATION',dex='pas',collateral='USDP',
        updated_ms=NOW,session_id='session',pid=123,team_wallet=TEAM,
        TRADING_AUTHORIZED=True,AUTO_TRADING_ACTIVE=True,authorization_valid=True)
    value['account'].update(source='EXCHANGE_REPORTED_ACCOUNT_OBSERVER',entries_paused=False)
    value['market_history']['pas:HYPE']=dict(strategy_history_ready=True,latest_completed_ms=NOW)
    atomic_json(tmp_path/'current.json',dict(session_id='session',output=str(tmp_path),pid=123))
    atomic_json(tmp_path/'status.json',value);before=(tmp_path/'status.json').read_bytes()
    monkeypatch.setattr(opening_audit.time,'time_ns',lambda:NOW*1000000)
    monkeypatch.setattr(opening_audit,'active_source_hash',lambda _:'a'*64)
    monkeypatch.setattr(terminal_app,'locked',lambda _:True)
    result=opening_audit.opening_check(tmp_path,SimpleNamespace(state=tmp_path))
    s=result['statuses'];assert len(s)==14
    assert s['OBSERVER_HEALTHY'] and s['FUNDING_VERIFIED'] and s['BTC_1X_VERIFIED'] and s['EWY_1X_VERIFIED']
    assert s['MARKET_DATA_FRESH'] and s['HISTORICAL_ORDER_SAFE']
    assert not s['RELEASE_VERIFIED'] and not s['ACCOUNT_IDENTITY_VERIFIED']
    assert not s['BTC_NATIVE_AND_RESIDUAL_QUALIFIED'] and not s['EWY_NATIVE_AND_RESIDUAL_QUALIFIED']
    assert not s['EXACT_SESSION_ACCEPTED'] and not s['TRADING_AUTHORIZED'] and not s['AUTO_TRADING_ACTIVE']
    assert result['verdict']=='NO_GO' and result['signatures_created']==result['exchange_writes']==0
    assert (tmp_path/'status.json').read_bytes()==before


def test_opening_help_and_absent_evidence_do_not_create_state(tmp_path):
    assert command('opening-check','--help').returncode==0
    result=command('opening-check','--state',tmp_path/'absent')
    assert result.returncode==1 and not (tmp_path/'absent').exists()
