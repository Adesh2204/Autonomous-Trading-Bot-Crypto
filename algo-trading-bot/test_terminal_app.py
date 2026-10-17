"""Standalone terminal process contracts; no actual exchange transport."""
from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from exchange.base_exchange import ExchangeError
from exchange.paper_operations import PaperOwner, atomic_json
from exchange.terminal_app import read_json, locked, Reporter, main, run_authorized
from exchange.terminal_observer import RotatingReceipts
from test_long_session import mandate

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/anchorium_cli.py'


def command(*args):
    return subprocess.run([sys.executable,str(CLI),*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=60)


@pytest.mark.parametrize('name',['doctor','research','simulate','prepare','start','status','stop','report'])
def test_every_documented_command_has_help(name):
    assert command(name,'--help').returncode==0


def test_doctor_checks_pins_without_key_or_network():
    p=command('doctor');assert p.returncode==0,p.stderr
    r=json.loads(p.stdout)
    assert r['execution_mode']=='PAPER' and r['allow_live_orders'] is False
    assert r['llm_runtime_dependencies']==[] and r['signing_authority']=='NONE'
    assert all(x['matching'] for x in r['dependencies'].values())


def test_complete_cli_simulation(tmp_path):
    out=tmp_path/'simulation';p=command('simulate','--output',out)
    assert p.returncode==0,p.stdout+p.stderr
    result=read_json(out/'simulation_result.json')
    assert result['exchange_writes']==0 and result['actual_realized_pnl'] is None
    rows={r['scenario']:r for r in result['episodes']}
    assert rows['win_then_loss']['cycles']==2
    assert rows['uncertain_entry']['state']=='UNKNOWN'
    assert rows['partial_exit']['positions'] and rows['partial_exit']['state']=='RECOVERY_REQUIRED'
    events=[json.loads(l) for l in (out/'events.jsonl').read_text().splitlines()]
    assert all(r['mode']=='SIMULATION' for r in events)
    cycles=[r['daily']['realized_net'] for r in events if r['scenario']=='win_then_loss' and r['event']=='EXIT_RECONCILED']
    from decimal import Decimal as D
    assert D(cycles[0])>0 and D(cycles[1])<D(cycles[0])


def test_duplicate_process_lock_and_stop_identity(tmp_path):
    owner=PaperOwner(tmp_path/'owner.lock')
    try:
        assert locked(tmp_path/'owner.lock')
        with pytest.raises(ExchangeError):PaperOwner(tmp_path/'owner.lock')
    finally:owner.close()
    assert not locked(tmp_path/'owner.lock')


def test_stop_requests_only_the_published_session(tmp_path):
    atomic_json(tmp_path/'current.json',dict(session_id='exact-session',output=str(tmp_path),pid=123))
    owner=PaperOwner(tmp_path/'owner.lock')
    try:
        p=command('stop','--state',tmp_path);assert p.returncode==0
        assert read_json(tmp_path/'stop.json')['session_id']=='exact-session'
    finally:owner.close()
    p=command('stop','--state',tmp_path)
    assert json.loads(p.stdout)['status']=='ALREADY_STOPPED'


def test_dead_worker_never_shows_running_or_verified_flat(tmp_path):
    atomic_json(tmp_path/'current.json',dict(session_id='old',output=str(tmp_path),pid=1))
    atomic_json(tmp_path/'status.json',dict(status='OBSERVING',updated_ms=1,terminal_flat=True))
    p=command('status','--state',tmp_path);r=json.loads(p.stdout)
    assert r['status']=='INTERRUPTED_UNCLEAN' and r['terminal_flat'] is None


def test_authorized_start_without_exact_evidence_fails_before_key(tmp_path):
    p=command('start','--authorized','--state',tmp_path)
    assert p.returncode==1
    r=read_json(Path(read_json(tmp_path/'current.json')['output'])/'status.json')
    assert r['status']=='HALTED_BEFORE_OR_DURING_START' and r['signing_authority']=='NONE'
    assert not locked(tmp_path/'owner.lock')


def test_public_mode_cannot_sneak_in_approval_flags(tmp_path):
    # Supplying signing files without the explicit mode is an operator error.
    p=command('start','--mandate','ignored.json','--state',tmp_path,'--duration','1')
    assert p.returncode==1


def test_reporter_deduplicates_and_persists(tmp_path,capsys):
    output=tmp_path/'run';output.mkdir()
    r=Reporter(ROOT,tmp_path,output,'id')
    v=dict(mode='TESTNET OBSERVATION',status='OBSERVING',source_hash='a'*64)
    r(v);r(v)
    assert len((output/'events.jsonl').read_text().splitlines())==1
    assert capsys.readouterr().out.count('TEAM ANCHORIUM')==1
    assert read_json(output/'status.json')['session_id']=='id'


def test_midwrite_json_is_retried(tmp_path):
    path=tmp_path/'value.json';path.write_text('{')
    thread=threading.Thread(target=lambda:(time.sleep(.06),path.write_text('{"valid":true}')))
    thread.start()
    try:assert read_json(path)=={'valid':True}
    finally:thread.join()


def test_receipts_rotate_and_preserve_actual_error_labels(tmp_path):
    class Transport:
        def close(self):pass
    r=RotatingReceipts(Transport(),tmp_path/'receipts.jsonl',limit=1,backups=2)
    try:
        r._record(dict(response=[],request={'type':'l2Book'}))
        r._record(dict(error='NETWORK_TIMEOUT',status_code=None))
        r._record(dict(error='ACTUAL_LIMIT',status_code=429))
        assert r.rotations==2 and r.records==3
        assert r.error_counts=={'None:NETWORK_TIMEOUT':1,'429:ACTUAL_LIMIT':1}
        assert (tmp_path/'receipts.jsonl.2').exists()
    finally:r.close()


@pytest.mark.parametrize('payload',[{'type':'order'},{'type':'l2Book','signature':'x'},{'type':'clearinghouseState','nonce':1}])
def test_observer_receipt_transport_cannot_write(tmp_path,payload):
    class Transport:
        def __call__(self,*a,**k):raise AssertionError('MUST_NOT_CALL_TRANSPORT')
        def close(self):pass
    r=RotatingReceipts(Transport(),tmp_path/'receipts.jsonl')
    try:
        with pytest.raises(ExchangeError):r(payload)
    finally:r.close()


def test_future_exact_day_requires_its_own_finite_mandate():
    m=mandate();day=86400000
    d=replace(m.daily,starts_ms=m.daily.starts_ms+day,expires_ms=m.daily.expires_ms+day)
    assert replace(m,daily=d,created_ms=m.created_ms+day,approval_deadline_ms=m.approval_deadline_ms+day).require()
    with pytest.raises(ExchangeError):replace(m,daily=replace(d,expires_ms=d.expires_ms+60000)).require()


def test_signer_deadline_does_not_stop_outer_observer(monkeypatch,tmp_path):
    import exchange.long_session as module
    m=mandate();source=tmp_path/'mandate.json';source.write_text('{}')
    outer=threading.Event()
    class Runtime:
        def __init__(self):
            self.session=SimpleNamespace(cycle=lambda **k:None)
            self.authorization=SimpleNamespace()
        def run(self,stop):
            assert stop is not outer
            stop.set()
            atomic_json(tmp_path/'terminal_result.json',dict(status='STOPPED_FLAT_VERIFIED',terminal_flat=True))
    monkeypatch.setattr(module,'read_mandate',lambda *_:m)
    monkeypatch.setattr(module,'build_long_runtime',lambda *a,**k:Runtime())
    args=SimpleNamespace(mandate=source,acceptance='a',release='r',native_protection_evidence='p')
    result=run_authorized(ROOT,args,outer,lambda _:None)
    assert result['terminal_flat'] and not outer.is_set()


def test_stop_revokes_entry_at_signing_boundary_but_retains_exact_risk_exit(tmp_path):
    from test_long_session import authority
    from exchange.bounded_daily_session import TradeState
    auth,clock,journal=authority(tmp_path)
    auth.lifecycle=SimpleNamespace(data={'attempts':1},state=TradeState.ENTRY_SUBMITTED)
    auth.entry_stop_event=threading.Event()
    try:
        request=dict(symbol='par:BTC',side='BUY',quantity='1',price='100',reduce_only=False)
        row,_=journal.reserve('entry',request,'candidate',clock[0]);auth.bind('entry','entry','par:BTC',1)
        wire=dict(a=1,b=True,r=False,s='1',p='100',t={'limit':{'tif':'Ioc'}},c=row['cloid'])
        assert auth.check_action(dict(type='order',orders=[wire]))[0]=='entry'
        auth.entry_stop_event.set()
        with pytest.raises(ExchangeError,match='REVOKED_BY_OPERATOR_STOP'):
            auth.check_action(dict(type='order',orders=[wire]))
        request.update(side='SELL',reduce_only=True)
        row,_=journal.reserve('exit',request,'exit-candidate',clock[0]);auth.bind('exit','exit','par:BTC',1)
        wire.update(b=False,r=True,c=row['cloid'])
        assert auth.check_action(dict(type='order',orders=[wire]))[0]=='exit'
    finally:journal.close()


def test_interactive_approval_requires_exact_typed_identity(monkeypatch,tmp_path):
    import exchange.long_session as module
    from exchange.terminal_app import approve
    m=mandate();proof=tmp_path/'proof.json';proof.write_text('{}')
    import hashlib
    m=replace(m,protection_evidence_sha256=hashlib.sha256(proof.read_bytes()).hexdigest())
    monkeypatch.setattr(module,'read_mandate',lambda *_:m)
    monkeypatch.setattr(module,'require_release',lambda *a:None)
    monkeypatch.setattr(module,'require_native_evidence',lambda *a:None)
    monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(time,'time_ns',lambda:(m.created_ms+1)*1000000)
    args=SimpleNamespace(mandate=tmp_path/'mandate.json',release='receipt',native_protection_evidence=proof)
    monkeypatch.setattr('builtins.input',lambda _: 'APPROVE previous-id')
    with pytest.raises(ExchangeError,match='NOT_GIVEN'):approve(ROOT,args)
    assert not (tmp_path/'acceptance.json').exists()
    monkeypatch.setattr('builtins.input',lambda _: 'APPROVE '+m.identity)
    assert approve(ROOT,args)==0
    assert read_json(tmp_path/'acceptance.json')['mandate_hash']==m.identity
    with pytest.raises(FileExistsError):approve(ROOT,args)


def test_noninteractive_approval_cannot_mint_acceptance(monkeypatch,tmp_path):
    import exchange.long_session as module
    from exchange.terminal_app import approve
    m=mandate();proof=tmp_path/'proof.json';proof.write_text('{}')
    from exchange.terminal_app import sha
    m=replace(m,protection_evidence_sha256=sha(proof))
    monkeypatch.setattr(module,'read_mandate',lambda *_:m)
    monkeypatch.setattr(module,'require_release',lambda *a:None)
    monkeypatch.setattr(module,'require_native_evidence',lambda *a:None)
    monkeypatch.setattr(sys.stdin,'isatty',lambda:False)
    with pytest.raises(ExchangeError,match='INTERACTIVE_HUMAN'):
        approve(ROOT,SimpleNamespace(mandate=tmp_path/'mandate.json',release='x',native_protection_evidence=proof))
    assert not (tmp_path/'acceptance.json').exists()


def test_account_stream_default_uses_verified_ca_and_hostname(monkeypatch):
    import ssl,requests,websocket
    from exchange.live_account_stream import LiveAccountStream
    from exchange.testnet_certification import TEAM
    seen={}
    class Socket:
        def send(self,message):pass
        def close(self):pass
    def connect(url,**kwargs):seen.update(url=url,**kwargs);return Socket()
    monkeypatch.setattr(websocket,'create_connection',connect)
    recovery=SimpleNamespace(account=SimpleNamespace(team_address=TEAM),revoke=lambda _:None)
    stream=LiveAccountStream(TEAM,recovery,SimpleNamespace(entries_paused=True),clock_ms=lambda:10000)
    try:
        stream.connect()
        assert seen['sslopt']=={'ca_certs':requests.certs.where(),'cert_reqs':ssl.CERT_REQUIRED,'check_hostname':True}
        assert seen['timeout']==1 and stream.connected
    finally:stream.disconnect()


def test_closed_authorized_result_is_not_mislabeled_as_crashed(tmp_path):
    atomic_json(tmp_path/'current.json',dict(session_id='closed',output=str(tmp_path),pid=1))
    atomic_json(tmp_path/'status.json',dict(status='STOPPED_FLAT_VERIFIED',updated_ms=1,terminal_flat=True))
    r=json.loads(command('status','--state',tmp_path).stdout)
    assert r['status']=='STOPPED_FLAT_VERIFIED' and r['terminal_flat'] is True


def test_account_event_sequence_distinguishes_trade_events_from_pongs():
    from exchange.live_account_stream import LiveAccountStream
    from exchange.testnet_certification import TEAM
    events=[]
    recovery=SimpleNamespace(account=SimpleNamespace(team_address=TEAM),revoke=lambda _:None,
        journal=SimpleNamespace(event=lambda *a,**k:events.append((a,k))))
    stream=LiveAccountStream(TEAM,recovery,SimpleNamespace(entries_paused=True),clock_ms=lambda:10000)
    stream.handle(dict(channel='pong'))
    assert stream.event_sequence==0
    stream.handle(dict(channel='userFills',data={'user':TEAM,'fills':[]}))
    assert stream.event_sequence==1 and stream.pending
    stream.handle(dict(channel='pong'))
    assert stream.event_sequence==1 and len(events)==1
