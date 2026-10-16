"""Real composition under fake public/exchange state; no network or lasting keys."""
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import venue_config
from exchange.base_exchange import ExchangeError
from exchange.execution_safety import LiveAuthorization,HumanLiveApproval
from exchange.runtime_schedule import RuntimeSchedule
from exchange.paper_checkpoint import PaperCheckpoint
from exchange.paper_operations import PaperOwner,PaperHealth
from market_regime_scanner import MarketRegimeScanner
from test_exchange_migration import NOW,TEAM
from test_crypto_paper_infrastructure import universe,make_bot,signal_scan,POLICY
from test_live_exchange_execution import live

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def blocked(*args,**kwargs):raise AssertionError('NO_NETWORK_IN_PRACTICE_TESTS')
    import requests,websocket
    monkeypatch.setattr(requests.Session,'post',blocked)
    monkeypatch.setattr(websocket,'create_connection',blocked)


def future_mode(monkeypatch):
    monkeypatch.setattr(venue_config,'EXECUTION_MODE','HYPERLIQUID_TESTNET_LIVE')
    monkeypatch.setattr(venue_config,'ALLOW_LIVE_ORDERS',True)
    monkeypatch.setenv('EXECUTION_MODE','HYPERLIQUID_TESTNET_LIVE')
    monkeypatch.setenv('ALLOW_LIVE_ORDERS','true')


def test_default_scanner_rejects_future_mode_before_public_reads(universe,monkeypatch):
    fixture,market,scanner=universe
    count=len(fixture.calls)
    future_mode(monkeypatch)
    with pytest.raises(ValueError,match='MIGRATION_PAPER_MODE_REQUIRED'):scanner.scan()
    assert len(fixture.calls)==count


@pytest.mark.parametrize('fault',[None,'revoked','expired','wrong_team','wrong_signer','mainnet'])
def test_authorized_real_scanner_and_revocation(universe,monkeypatch,fault):
    fixture,market,old=universe
    future_mode(monkeypatch)
    signer='0x'+'2'*40
    approval=HumanLiveApproval('synthetic-offline',TEAM,signer,NOW+60000,True)
    if fault=='expired':approval=replace(approval,expires_ms=NOW)
    auth=LiveAuthorization(approval,clock_ms=lambda:NOW)
    if fault=='revoked':auth.revoke()
    if fault=='mainnet':monkeypatch.setenv('HL_NETWORK','mainnet')
    scanner=MarketRegimeScanner(market,old.policy,live_authorization=auth,
        team_address='0x'+'3'*40 if fault=='wrong_team' else TEAM,
        signer_address='0x'+'4'*40 if fault=='wrong_signer' else signer)
    count=len(fixture.calls)
    if fault:
        with pytest.raises(ValueError):scanner.scan()
        assert len(fixture.calls)==count
    else:
        result=scanner.scan()
        assert len(result.diagnostics)==11
        assert all(not d.reasons for d in result.diagnostics)


def test_actual_future_builder_runs_shared_scanner_without_network(live,monkeypatch,tmp_path):
    import exchange.live_runtime as module
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.execution_safety import NonceManager,ClockHealthMonitor
    from exchange.sdk_transport import OfflineSDKTransport
    from exchange.position_protection import ProtectionPolicy
    from market_regime_scanner import ScannerPolicy
    future_mode(monkeypatch)
    # A new process/state store uses a fresh ephemeral agent, as venue policy requires.
    from eth_account import Account
    fresh=Account.create()
    live.fixture.agents=[dict(address=fresh.address,validUntil=NOW+86400000)]
    monkeypatch.setattr(live.fixture,'close',lambda:None,raising=False)
    monkeypatch.setenv('API_WALLET_PRIVATE_KEY',fresh.key.hex())
    monkeypatch.setattr(module,'HyperliquidClient',lambda **kw:HyperliquidClient(live.fixture,clock_ms=lambda:live.fixture.now,**kw))
    monkeypatch.setattr(module,'NonceManager',lambda path,signer,**kw:NonceManager(path,signer,clock_ms=lambda:live.fixture.now,**kw))
    monkeypatch.setattr(module,'ClockHealthMonitor',lambda **kw:ClockHealthMonitor(clock_ms=lambda:live.fixture.now,monotonic_ms=lambda:live.fixture.now,**kw))
    monkeypatch.setattr(module,'OfficialSDKTransport',lambda c,s,t,n,a,**kw:OfflineSDKTransport(c,s,t,n,[]))
    class Stream:
        def __init__(self,team,recovery,execution,**kw):
            self.executor=execution;self.healthy=True;self.connected=True;self.pending=False
        def connect(self):pass
        def poll(self):pass
        def disconnect(self,*args):self.healthy=False
    monkeypatch.setattr(module,'LiveAccountStream',Stream)
    monkeypatch.setattr(module.LiveRuntime,'start_market_stream',lambda self:None)
    # Use the real scanner, account recovery, risk, manager and runtime builder.
    approval=HumanLiveApproval('synthetic-composition',TEAM,fresh.address,NOW+86400000,True)
    # LiveAuthorization's real wall clock must use the same test-only timeline.
    monkeypatch.setattr(module,'LiveAuthorization',lambda a:LiveAuthorization(a,clock_ms=lambda:live.fixture.now))
    try:
        runtime=module.build_live_runtime(team_address=TEAM,approval=approval,session_id='offline:composition',
            initial_start_ms=NOW-60000,risk_policy=POLICY,scanner_policy=ScannerPolicy('.004',15,0,10,history_bars=30),
            state_directory=tmp_path/'composed',fee_scale_verified=1,
            protection_policy=ProtectionPolicy(True,'synthetic-only',D('1'),D('.005')))
    except ExchangeError as exc:
        # All data here is a public/synthetic fixture; production stays redacted.
        raise AssertionError(str(exc.__context__)) from exc
    try:
        runtime.session.cycle()
        assert len(runtime.session.latest_scan.diagnostics)==10
        assert runtime.session.scanner.live_authorization is runtime.authorization
        assert not runtime.transport.signed_payloads
        previous=runtime.session.latest_scan
        runtime.session.cycle(scan=False)
        assert runtime.session.latest_scan is previous
        runtime.authorization.revoke()
        with pytest.raises(ValueError,match='EXPLICIT_MANUAL_LIVE_AUTHORIZATION_REQUIRED'):runtime.session.scanner.scan()
    finally:runtime.close()


def test_runtime_spaces_scans_and_keeps_management_cycles():
    from exchange.live_runtime import LiveRuntime
    clock=[0];calls=[];closed=[]
    class Stop:
        def is_set(self):return clock[0]>=8
        def wait(self,seconds):clock[0]+=seconds
    session=SimpleNamespace(cycle=lambda **kw:calls.append(kw.get('scan',True)))
    runtime=LiveRuntime(session,None,None,None,None,None,schedule=RuntimeSchedule(4,1,30),monotonic=lambda:clock[0])
    runtime.close=lambda **kw:closed.append(kw['clean'])
    runtime.run(Stop())
    assert calls==[True,False,False,False,True,False,False,False]
    assert closed==[True]


@pytest.mark.parametrize('values',[(float('nan'),1,30),(300,0,30),(0,1,30),(300,1,301),(300,True,30)])
def test_invalid_schedule_fails(values):
    with pytest.raises(ExchangeError):RuntimeSchedule(*values)


def test_paper_checkpoint_restores_same_closed_ledger_and_cooldown(universe,tmp_path):
    fixture,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    bot._close('par:BTC','Stop Loss')
    assert not bot.execution.portfolio.positions
    bot.managers['par:BTC'].candles_since_last_sl=3
    identity={'session':'fixture','configuration':'same'}
    state=PaperCheckpoint(tmp_path/'paper.sqlite',identity)
    state.save(bot,clean=False)
    _,again=make_bot(universe)
    report=state.load(again)
    assert report['restored'] and not report['previous_clean_shutdown']
    assert again.execution.portfolio.cash==bot.execution.portfolio.cash
    assert again.execution.fills==bot.execution.fills
    assert again._daily_setups==bot._daily_setups==1
    assert again.managers['par:BTC'].candles_since_last_sl==3
    state.backup(tmp_path/'backup.sqlite')
    copied=PaperCheckpoint(tmp_path/'backup.sqlite',identity)
    _,third=make_bot(universe)
    assert copied.load(third)['restored']
    copied.close();state.close()


def test_open_paper_exposure_blocks_restart_without_erasing_evidence(universe,tmp_path):
    _,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    state=PaperCheckpoint(tmp_path/'paper.sqlite',{'session':'fixture'})
    state.save(bot)
    before=state.db.execute('SELECT data,sha256 FROM paper_state').fetchone()
    _,again=make_bot(universe)
    with pytest.raises(ExchangeError,match='DOWNTIME_WITH_EXPOSURE'):state.load(again)
    assert state.db.execute('SELECT data,sha256 FROM paper_state').fetchone()==before
    state.close()


@pytest.mark.parametrize('fault',['checksum','identity'])
def test_checkpoint_corruption_or_wrong_configuration_blocks(universe,tmp_path,fault):
    _,bot=make_bot(universe)
    state=PaperCheckpoint(tmp_path/'paper.sqlite',{'session':'fixture'})
    state.save(bot)
    if fault=='checksum':
        with state.db:state.db.execute("UPDATE paper_state SET sha256='wrong'")
    else:state.identity={'session':'other'}
    _,again=make_bot(universe)
    with pytest.raises(ExchangeError):state.load(again)
    state.close()


def test_second_paper_owner_is_rejected_and_lock_is_released(tmp_path):
    first=PaperOwner(tmp_path/'owner.lock')
    with pytest.raises(ExchangeError,match='ALREADY_RUNNING'):PaperOwner(tmp_path/'owner.lock')
    first.close()
    PaperOwner(tmp_path/'owner.lock').close()


def test_health_warns_on_stale_data_and_detects_stopped_heartbeat(universe,tmp_path):
    from check_practice_health import assess
    _,bot=make_bot(universe)
    health=PaperHealth(tmp_path,session_id='fixture',segment='fixture')
    health.write(bot)
    path=tmp_path/'health.json'
    assert assess(path,now_ms=NOW)[0]==2
    assert assess(path,now_ms=NOW+91000)[0]==1
    health.write(bot,status='STOPPED')
    assert assess(path,now_ms=NOW)[0]==3


def test_proposed_policy_cannot_activate_protection():
    from exchange.position_protection import ProtectionPolicy
    p=ProtectionPolicy(**json.loads((ROOT/'configs/protection_policy.proposed.json').read_text()))
    with pytest.raises(ExchangeError,match='EXPLICIT_PROTECTION'):p.require()


def test_raw_stale_candle_timestamps_are_not_repaired_or_invented():
    from diagnose_par_freshness import candle_evidence
    from test_exchange_migration import candle_row
    rows=[candle_row(NOW-600000),candle_row(NOW-480000)]
    report=candle_evidence(rows,'par:BTC',NOW)
    assert report['adapter_matches_raw'] and not report['completed_fresh']
    assert report['missing_minutes_between_returned_bars']==1
    assert report['raw_latest']['t']==NOW-480000


def test_practice_launcher_configuration_rejects_activation(tmp_path):
    from run_practice import load_ops
    ops=json.loads((ROOT/'configs/practice_ops.json').read_text())
    ops['allow_live_orders']=True
    path=tmp_path/'ops.json';path.write_text(json.dumps(ops))
    with pytest.raises(ExchangeError):load_ops(path)
