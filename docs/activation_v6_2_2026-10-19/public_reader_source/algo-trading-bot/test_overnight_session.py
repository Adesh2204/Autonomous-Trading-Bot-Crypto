"""Finite overnight authority, durable midnight accounting and bounded shutdown."""
from dataclasses import asdict,replace
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json,socket,threading,time
import pytest
from exchange.base_exchange import ExchangeError,Position
from exchange.overnight_session import OvernightLimits,OvernightLongMandate,OVERNIGHT_ACKS,OVERNIGHT_MAX_EXPIRY_MS
from exchange.long_session import LongAuthorization,LongMandate,ACKS,read_mandate
from exchange.bounded_daily_session import DailyMandate,DailyLifecycle,TradeState
from exchange.execution_journal import ExecutionJournal
from exchange.testnet_certification import TEAM,API
from exchange.terminal_recovery import terminal_reconcile,exception_evidence

IST=ZoneInfo('Asia/Calcutta')
def ms(value):return int(datetime.fromisoformat(value).replace(tzinfo=IST).timestamp()*1000)
START=ms('2026-10-16T22:00:00')
MIDNIGHT=ms('2026-10-17T00:00:00')


def limits(**changes):
    d=OvernightLimits('offline:overnight',TEAM,API,('par:BTC',),('LONG',),START,OVERNIGHT_MAX_EXPIRY_MS,
        'a'*64,socket.gethostname(),'20000','1000','1000','2000')
    return replace(d,**changes)


def contract(**changes):
    return replace(OvernightLongMandate(limits(),START,START+300000,*(['b'*64]*4)),**changes)


def test_original_daily_scope_still_rejects_midnight():
    d=limits();data=asdict(d);data.pop('session_loss_fraction');data.pop('midnight_policy')
    with pytest.raises(ExchangeError,match='CROSS_IST_DAY'):DailyMandate(**data).require()
    with pytest.raises(ExchangeError):LongMandate(d,START,START+300000,*(['b'*64]*4)).require()


@pytest.mark.parametrize('change',[
    {'expires_ms':OVERNIGHT_MAX_EXPIRY_MS+1},{'starts_ms':ms('2026-10-17T00:01:00')},
    {'starts_ms':ms('2026-10-16T12:00:00')},{'expires_ms':ms('2026-10-16T23:59:00')},
    {'bankroll':'20001'},{'maximum_entry_attempts':3},{'maximum_concurrent_positions':2},
    {'leverage':2},{'directions':('SHORT',)},{'daily_loss_fraction':'.02'},
    {'session_loss_fraction':'.02'},{'session_loss_fraction':'.005'},{'midnight_policy':'RESET'},
    {'maximum_notional':'10001'},{'risk_fraction':'.006'},
])
def test_overnight_scope_never_broadens_baseline(change):
    with pytest.raises(ExchangeError):limits(**change).require()


@pytest.mark.parametrize('change',[
    {'mode':'EXACT_APPROVED_STRATEGY_LONG_TESTNET_V1'},{'entry_cutoff_buffer_ms':120000},
    {'risk_close_buffer_ms':60000},{'risk_close_buffer_ms':True},{'created_ms':'now'},
    {'maximum_signed_actions':13},{'allow_loss_making_risk_exits':False},
])
def test_overnight_contract_requires_exact_separate_windows(change):
    with pytest.raises(ExchangeError):contract(**change).require()


def test_overnight_roundtrip_parser_preserves_hash_and_type(tmp_path):
    m=contract().require();p=tmp_path/'mandate.json';p.write_text(json.dumps(asdict(m)))
    parsed=read_mandate(p)
    assert type(parsed) is OvernightLongMandate and type(parsed.daily) is OvernightLimits
    assert parsed.identity==m.identity
    assert parsed.daily.expires_ms-parsed.entry_cutoff_buffer_ms==ms('2026-10-17T11:45:00')
    assert parsed.daily.expires_ms-parsed.risk_close_buffer_ms==ms('2026-10-17T11:55:00')


def test_overnight_approval_extra_acknowledgments_and_expiry(tmp_path):
    m=contract();clock=[START+1];p=tmp_path/'acceptance.json'
    data=dict(mandate_hash=m.identity,accepted_ms=clock[0],expires_ms=m.daily.expires_ms,
        operator_acceptance='Explicit OFFLINE synthetic fixture',**{k:True for k in ACKS})
    p.write_text(json.dumps(data));j=ExecutionJournal(tmp_path/'auth.sqlite',session_id='offline:authority',team_address=TEAM)
    try:
        with pytest.raises(ExchangeError,match='OVERNIGHT'):LongAuthorization(m,p,j,clock_ms=lambda:clock[0],source_hash=lambda:'a'*64,policy_hash=lambda:'b'*64)
        data.update({k:True for k in OVERNIGHT_ACKS});p.write_text(json.dumps(data))
        a=LongAuthorization(m,p,j,clock_ms=lambda:clock[0],source_hash=lambda:'a'*64,policy_hash=lambda:'b'*64)
        clock[0]=MIDNIGHT+1;a.require(TEAM,API)
        clock[0]=OVERNIGHT_MAX_EXPIRY_MS
        with pytest.raises(ExchangeError):a.require(TEAM,API)
    finally:j.close()


def test_counters_allocation_drawdown_never_reset_at_midnight(tmp_path):
    clock=[MIDNIGHT-1000];j=ExecutionJournal(tmp_path/'day.sqlite',session_id='offline:overnight',team_address=TEAM)
    d=DailyLifecycle(j,limits(),clock_ms=lambda:clock[0],source_hash=lambda:'a'*64,mode='OFFLINE_FIXTURE')
    try:
        d.data.update(state='FLAT_VERIFIED',attempts=2,allocation='1900',realized_net='-50',equity='19950',peak_equity='20100',drawdown='150')
        d._save('SYNTHETIC_PRE_MIDNIGHT')
        before=dict(d.data);clock[0]=MIDNIGHT+1000;d.require_window()
        assert d.data==before
        d.candidate('new','par:BTC','LONG')
        plan=dict(symbol='par:BTC',side='BUY',quantity='1',notional='100',observed_ms=clock[0],intended_loss='1',collateral_reserved='100',free_collateral_observed='1000')
        with pytest.raises(ExchangeError,match='RISK_ATTEMPT'):d.reserve_entry(1,100,allocation=plan,protection_fixture=True)
    finally:j.close()


def test_session_loss_latch_carries_into_new_day(tmp_path):
    clock=[MIDNIGHT-1000];j=ExecutionJournal(tmp_path/'day.sqlite',session_id='offline:loss',team_address=TEAM)
    d=DailyLifecycle(j,limits(),clock_ms=lambda:clock[0],source_hash=lambda:'a'*64,mode='OFFLINE_FIXTURE')
    try:
        d.data.update(state='FLAT_VERIFIED',equity='19800',realized_net='-200',drawdown='200')
        clock[0]=MIDNIGHT+1000;d.candidate('fresh','par:BTC','LONG')
        plan=dict(symbol='par:BTC',side='BUY',quantity='1',notional='100',observed_ms=clock[0],intended_loss='1',collateral_reserved='100',free_collateral_observed='1000')
        with pytest.raises(ExchangeError):d.reserve_entry(1,100,allocation=plan,protection_fixture=True)
    finally:j.close()


def recovery_fixture(*,fail=None,exposed=False):
    at=[100000];starts=[]
    def clock():at[0]+=1;return at[0]
    truth=SimpleNamespace(initialized=True,last_window=(0,90000),reasons=(),entries_paused=True,positions={},orders={},
        report=lambda:dict(positions=[],open_orders=[]))
    class Reconciler:
        def recover(self,state,*,start_ms):
            starts.append(start_ms)
            if fail:raise ExchangeError(fail)
            state.last_window=(start_ms,clock())
    position=Position('par:BTC',D('.0002'),D(81512),D(0),D(1),None)
    account=SimpleNamespace(team_address=TEAM,get_positions=lambda:{'par:BTC':position} if exposed else {},get_frontend_open_orders=lambda:[])
    client=SimpleNamespace(read_cancel_event=threading.Event(),request_lock=threading.RLock())
    rates=SimpleNamespace(read_budget_wait_seconds=5,read_deadline_seconds=45,read_progress=None,report=lambda:{'ip_limit':1200,'reserve':120})
    return account,Reconciler(),truth,client,rates,clock,starts


def test_shutdown_uses_overlap_after_stream_revokes_entries():
    a,r,t,c,rates,clock,starts=recovery_fixture()
    result=terminal_reconcile(a,r,t,c,rates,clock)
    assert starts[0]==30000 and starts[1]>0
    assert result['account_status']=='FLAT_VERIFIED' and len(result['terminal_readbacks'])==2
    assert rates.read_budget_wait_seconds==5 and rates.read_deadline_seconds==45
    assert result['rate_report']=={'ip_limit':1200,'reserve':120}


@pytest.mark.parametrize('reason',['PUBLIC_RATE_BUDGET_EXHAUSTED','ACCOUNT_HISTORY_WINDOW_GAP','UNKNOWN_ORDER','INFO_READ_CANCELLED'])
def test_shutdown_preserves_error_stack_and_unknown(reason):
    a,r,t,c,rates,clock,starts=recovery_fixture(fail=reason)
    result=terminal_reconcile(a,r,t,c,rates,clock)
    assert not result['terminal_flat'] and result['account_status']=='UNKNOWN'
    assert result['terminal_reconciliation_error']['reason']==reason
    assert 'ExchangeError' in result['terminal_reconciliation_error']['traceback']
    assert result['terminal_reconciliation_failed_phase']=='ACCOUNT_HISTORY_1'


def test_exposure_cannot_be_reported_flat():
    a,r,t,c,rates,clock,starts=recovery_fixture(exposed=True)
    result=terminal_reconcile(a,r,t,c,rates,clock)
    assert result['account_status']=='EXPOSED' and not result['terminal_flat']


def test_uncertain_history_is_not_cleared_by_overlap():
    a,r,t,c,rates,clock,starts=recovery_fixture();t.reasons=('UNRESOLVED_HISTORY',)
    result=terminal_reconcile(a,r,t,c,rates,clock)
    assert starts[0]==0 and not result['terminal_flat']


def test_error_diagnostics_redact_key_shaped_values():
    try:raise ExchangeError('private_key=0x'+'a'*64)
    except ExchangeError as exc:r=exception_evidence(exc)
    assert 'a'*64 not in json.dumps(r) and '[REDACTED]' in r['reason']


def test_account_notifications_during_rest_do_not_clear_pending(monkeypatch):
    from exchange.live_account_stream import LiveAccountStream
    events=[]
    recovery=SimpleNamespace(account=SimpleNamespace(team_address=TEAM),journal=SimpleNamespace(event=lambda *a,**k:events.append(a)),revoke=lambda _:None)
    stream=LiveAccountStream(TEAM,recovery,SimpleNamespace(entries_paused=True),clock_ms=lambda:10000)
    stream.connected=True;stream.generation=1;stream.subscribed=set(stream.CHANNELS)
    def recover():
        done=threading.Event()
        def note():stream.handle(dict(channel='userFills',data={'user':TEAM}));done.set()
        t=threading.Thread(target=note);t.start();assert done.wait(1),'RECEIVER_LOCK_HELD_ACROSS_REST';t.join()
        return SimpleNamespace(ready=True)
    recovery.recover=recover
    assert not stream.reconcile() and stream.pending and not stream.healthy


def test_frozen_long_sdk_cycles_across_ist_midnight(tmp_path,monkeypatch):
    """Real frozen-brain/SDK plumbing with an explicitly synthetic unit-lot venue."""
    import test_exchange_migration as public
    import test_live_exchange_execution as actual
    import test_production_reliability as protection
    import test_long_session as long_tests
    start=ms('2026-10-16T23:59:00')
    for module in (public,actual,protection,long_tests):monkeypatch.setattr(module,'NOW',start)
    def overnight_fixture(*args,**kwargs):return OvernightLimits(*args,**kwargs)
    monkeypatch.setattr(long_tests,'DailyMandate',overnight_fixture)
    generator=actual.live.__wrapped__(tmp_path,monkeypatch);live=next(generator)
    try:
        b=long_tests.bridge.__wrapped__(live,monkeypatch)
        nets=[]
        for cycle in range(2):
            long_tests.enter(b)
            assert live.account.get_positions(),b.daily.data
            old=D(b.daily.data['realized_net'])
            price=D(105) if cycle==0 else D(97)
            live.fixture.book.update(time=live.fixture.now,levels=[[dict(px=str(price),sz='100')],[dict(px=str(price+D('.02')),sz='100')]])
            live.fixture.contexts=[dict(markPx=str(price),oraclePx=str(price),funding='.0001',openInterest='10') for _ in live.fixture.contexts]
            b.session._close('par:BTC','Target Hit' if cycle==0 else 'Stop Loss Hit')
            assert b.daily.state==TradeState.FLAT_VERIFIED
            assert not live.account.get_positions() and not live.account.get_frontend_open_orders()
            nets.append(D(b.daily.data['realized_net'])-old)
            if cycle==0:live.fixture.now=ms('2026-10-17T00:00:00')
        assert nets[0]>0 and nets[1]<0
        assert b.daily.data['attempts']==2 and b.daily.data['cycles']==2
        before=len(live.transport.signed_payloads);long_tests.enter(b)
        assert len(live.transport.signed_payloads)==before
        assert before<=12
    finally:
        try:next(generator)
        except StopIteration:pass


def test_old_short_rate_wait_fails_new_shutdown_waits_without_raising_limits(tmp_path):
    from exchange.rate_limits import HyperliquidRateLimitManager
    from exchange.reliability_policy import RequestPriority
    from dataclasses import asdict
    tick=[100000]
    def now():tick[0]+=1;return tick[0]
    j=ExecutionJournal(tmp_path/'rates.sqlite',session_id='offline:pressure',team_address=TEAM)
    rates=HyperliquidRateLimitManager(j,clock_ms=now,wait=lambda delay:tick.__setitem__(0,tick[0]+delay))
    try:
        policy=asdict(rates.policy)
        for _ in range(54):rates.reserve_info('meta',priority=RequestPriority.DECISION)
        rates.read_budget_wait_seconds=5
        with pytest.raises(ExchangeError,match='INFO_PUBLIC_READ_BUDGET_DEADLINE'):
            rates.read('userFees',lambda:{})
        a,r,t,c,_,clock,starts=recovery_fixture()
        t.last_window=(0,tick[0]-1000)
        def recover(state,*,start_ms):
            rates.read('userFees',lambda:{})
            state.last_window=(start_ms,now())
        r.recover=recover
        result=terminal_reconcile(a,r,t,c,rates,now)
        assert result['terminal_flat'] and asdict(rates.policy)==policy
        assert any(x.get('event')=='WAITING_FOR_RATE_BUDGET' for x in result['terminal_recovery_steps'])
        assert tick[0]>=160000 and result['terminal_recovery_order_actions']==0
    finally:j.close()


def test_background_receiver_keeps_polling_and_stops_without_restarting():
    from exchange.live_account_stream import LiveAccountStream
    import queue
    q=queue.Queue();events=[]
    class Socket:
        def send(self,message):
            m=json.loads(message)
            if m['method']=='subscribe':q.put(json.dumps(dict(channel='subscriptionResponse',data={'subscription':m['subscription']})))
        def recv(self):
            try:return q.get(timeout=.02)
            except queue.Empty:raise TimeoutError()
        def close(self):pass
    recovery=SimpleNamespace(account=SimpleNamespace(team_address=TEAM),revoke=lambda _:None,
        recover=lambda:SimpleNamespace(ready=True),journal=SimpleNamespace(event=lambda *a,**k:events.append(a)))
    stream=LiveAccountStream(TEAM,recovery,SimpleNamespace(entries_paused=True),clock_ms=lambda:10000,connector=lambda *a,**k:Socket())
    stream.start_receiver()
    try:
        until=time.monotonic()+2
        while stream.subscribed!=set(stream.CHANNELS) and time.monotonic()<until:time.sleep(.01)
        assert stream.subscribed==set(stream.CHANNELS) and stream.reconcile() and stream.healthy
        with pytest.raises(ExchangeError,match='ALREADY_STARTED'):stream.start_receiver()
    finally:stream.stop_receiver()
    assert not stream.receiver_thread.is_alive() and not stream.healthy


def test_sleep_wake_gap_revokes_account_readiness():
    from exchange.live_account_stream import LiveAccountStream
    tick=[10000]
    recovery=SimpleNamespace(account=SimpleNamespace(team_address=TEAM),revoke=lambda _:None)
    executor=SimpleNamespace(entries_paused=False)
    stream=LiveAccountStream(TEAM,recovery,executor,clock_ms=lambda:tick[0])
    stream.connected=True;stream.ready=True;stream.pending=False;stream.generation=1;stream.reconciled_generation=1
    stream.last_received_ms=10000;stream.last_ping_ms=10000
    tick[0]+=60000
    with pytest.raises(ExchangeError,match='HEARTBEAT_EXPIRED'):stream.poll()
    assert executor.entries_paused and not stream.healthy and not stream.connected


def test_live_recovery_retains_original_cause_and_sanitized_trace(tmp_path):
    from exchange.live_recovery import LiveAccountRecovery
    j=ExecutionJournal(tmp_path/'cause.sqlite',session_id='offline:cause',team_address=TEAM)
    account=SimpleNamespace(client=SimpleNamespace(clock_ms=lambda:10000))
    recovery=LiveAccountRecovery(account,j,initial_start_ms=0)
    def fail(*args,**kwargs):raise ExchangeError('INFO_PUBLIC_READ_BUDGET_DEADLINE')
    recovery.reconciler.recover=fail
    try:
        with pytest.raises(ExchangeError,match='ACCOUNT_RECOVERY_FAILED') as caught:recovery.recover()
        assert str(caught.value.__cause__)=='INFO_PUBLIC_READ_BUDGET_DEADLINE'
        evidence=exception_evidence(caught.value)
        assert 'INFO_PUBLIC_READ_BUDGET_DEADLINE' in evidence['traceback']
        rows=j.db.execute("SELECT data FROM events WHERE kind='ACCOUNT_RECOVERY_EXCEPTION'").fetchall()
        assert len(rows)==1 and 'INFO_PUBLIC_READ_BUDGET_DEADLINE' in rows[0][0]
    finally:j.close()


@pytest.mark.parametrize('external_owner',[True,False])
def test_runtime_preserves_cli_signal_ownership(monkeypatch,external_owner):
    from exchange.live_runtime import LiveRuntime
    import signal
    calls=[]
    monkeypatch.setattr(signal,'signal',lambda *args:calls.append(args))
    runtime=object.__new__(LiveRuntime)
    runtime.external_signal_owner=external_owner
    runtime.save_results=lambda:None
    runtime.close=lambda **kwargs:None
    stop=threading.Event();stop.set()
    runtime.run(stop)
    assert len(calls)==(0 if external_owner else 2)
