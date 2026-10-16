"""Synthetic transport/recovery evidence, never funded-account certification."""
import json
import queue
import threading
import time
from copy import deepcopy

import pytest

from exchange.base_exchange import ExchangeError
from exchange.feed_transport import FeedTransportHealth
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData, ParMarketDataEngine
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.reliability_policy import RequestPriority
from exchange.feed_certification import FeedCertificationReport
from test_exchange_migration import PublicInfoFixture, NOW, candle_row


def engine():
    source=PublicInfoFixture()
    client=HyperliquidClient(source,clock_ms=lambda:source.now)
    client.startup()
    return source,ParMarketDataEngine(HyperliquidMarketData(client),['par:BTC'],history_bars=300)


def test_open_bar_does_not_evict_completed_history():
    source,e=engine()
    e.ingest(dict(channel='candle',data=[candle_row(NOW-i*60000) for i in range(300,0,-1)]))
    e.ingest(dict(channel='candle',data=candle_row(NOW)))
    assert len(e.get_completed_candles('par:BTC'))==300
    assert len(e.candles['par:BTC'])==301


def test_old_generation_callbacks_cannot_mutate_current_book():
    source,e=engine()
    e.transport_health.begin(e.subscriptions())
    old=e.transport_health.generation
    e.transport_health.begin(e.subscriptions())
    assert e.ingest(dict(channel='l2Book',data=source.book),generation=old) is False
    assert not e.books


def test_single_reconnect_owner():
    _,e=engine()
    e._run_owner.acquire()
    try:
        with pytest.raises(ExchangeError,match='OWNER_ALREADY_RUNNING'):
            e.run(threading.Event())
    finally:e._run_owner.release()


def test_quiet_market_does_not_kill_transport_with_pongs():
    clock=[0.]
    h=FeedTransportHealth(monotonic=lambda:clock[0],wall_ms=lambda:int(clock[0]*1000))
    h.begin([])
    for n in range(1,151):
        clock[0]=n
        if h.poll():h.ping_sent();h.receive({'channel':'pong'},h.generation)
    assert h.current['pong_at_ms']==150000
    assert h.current['last_trade_message_at_ms'] is None


def test_missing_pong_is_not_hidden_by_book_messages():
    clock=[0.];h=FeedTransportHealth(monotonic=lambda:clock[0],wall_ms=lambda:int(clock[0]*1000))
    h.begin([])
    for n in range(1,41):
        clock[0]=n;h.receive({'channel':'l2Book'},h.generation)
        if n==30:h.ping_sent()
        if n<40:h.poll()
    with pytest.raises(ExchangeError,match='HEARTBEAT_STALE'):h.poll()


def test_host_pause_has_distinct_attribution():
    clock=[0.];h=FeedTransportHealth(monotonic=lambda:clock[0],wall_ms=lambda:int(clock[0]*1000))
    h.begin([]);clock[0]=46
    with pytest.raises(ExchangeError,match='HOST_PROCESSING_GAP'):h.poll()


def test_backoff_is_bounded_and_jittered():
    low=FeedTransportHealth(jitter=lambda:0);high=FeedTransportHealth(jitter=lambda:1)
    assert low.backoff(1)==.8 and high.backoff(1)==1
    assert high.backoff(99)==30 and low.backoff(99)==24


def test_subscription_set_is_reset_and_idempotent():
    _,e=engine();h=e.transport_health;subs=e.subscriptions()
    for _ in range(3):
        h.begin(subs)
        for s in subs:
            assert h.subscription_sent(s['subscription'])
            assert not h.subscription_sent(s['subscription'])
            h.receive({'channel':'subscriptionResponse','data':s},h.generation)
        assert len(h.sent)==len(h.confirmed)==len(h.desired)==3
    assert h.duplicates_prevented==9


def test_actual_venue_acknowledgement_defaults_match_requested_book():
    _,e=engine();h=e.transport_health;h.begin(e.subscriptions())
    ack={'channel':'subscriptionResponse','data':{'method':'subscribe','subscription':
        {'type':'l2Book','coin':'par:BTC','nSigFigs':None,'mantissa':None,'fast':False}}}
    h.receive(ack,h.generation)
    assert h.key({'type':'l2Book','coin':'par:BTC'}) in h.confirmed
    ack['data']['subscription']['nSigFigs']=5
    with pytest.raises(ExchangeError,match='UNEXPECTED_SUBSCRIPTION_ACK'):h.receive(ack,h.generation)


def test_read_cancellation_is_cleared_before_next_connection_startup(tmp_path):
    source,e=engine();j=ExecutionJournal(tmp_path/'reads.sqlite',session_id='fixture',team_address='0x'+'0'*40)
    e.client.rate_limits=e.rates=HyperliquidRateLimitManager(j)
    class ImmediateStop(threading.Event):
        def wait(self,timeout=None):return self.is_set()
    stop=ImmediateStop();sockets=[]
    class Socket:
        def __init__(self,fail):self.fail=fail;self.inbox=queue.Queue()
        def send(self,value):
            data=json.loads(value)
            if data['method']=='subscribe':self.inbox.put({'channel':'subscriptionResponse','data':data})
        def recv(self):
            if self.fail:raise OSError('fixture network loss')
            if e.reconciled:stop.set();return json.dumps({'channel':'pong'})
            try:return json.dumps(self.inbox.get(timeout=.01))
            except queue.Empty:raise TimeoutError()
        def close(self):pass
    def connect():
        s=Socket(not sockets);sockets.append(s);return s
    e.connect=connect
    e.run(stop,max_reconnects=1)
    assert len(sockets)==2 and e.reconnections==1
    assert len(e.transport_health.confirmed)==3
    j.close()


def test_receiver_stays_responsive_during_slow_rest_repair():
    source,e=engine();waiting=threading.Event();release=threading.Event();stop=threading.Event()
    original=e.market.get_candles
    def slow(*args,**kwargs):
        waiting.set();assert release.wait(3)
        return original(*args,**kwargs)
    e.market.get_candles=slow
    inbox=queue.Queue()
    class Socket:
        closed=False
        def send(self,value):
            data=json.loads(value)
            if data['method']=='subscribe':inbox.put({'channel':'subscriptionResponse','data':data})
        def recv(self):
            try:return json.dumps(inbox.get(timeout=.01))
            except queue.Empty:raise TimeoutError()
        def close(self):self.closed=True
    socket=Socket();e.connect=lambda:socket
    failures=[]
    def run():
        try:e.run(stop)
        except Exception as exc:failures.append(exc)
    thread=threading.Thread(target=run);thread.start()
    try:
        assert waiting.wait(2)
        inbox.put({'channel':'pong'})
        deadline=time.monotonic()+2
        while e.transport_health.current.get('pong_at_ms') is None and time.monotonic()<deadline:time.sleep(.005)
        assert e.transport_health.current['pong_at_ms'] is not None
        assert not e.reconciled
        release.set()
        deadline=time.monotonic()+2
        while not e.reconciled and time.monotonic()<deadline:time.sleep(.005)
        assert e.reconciled and len(e.transport_health.confirmed)==3
    finally:release.set();stop.set();thread.join(3)
    assert not thread.is_alive() and socket.closed and not failures


def test_rest_retry_exhaustion_does_not_reconnect_a_healthy_socket():
    _,e=engine();stop=threading.Event();inbox=queue.Queue();original=e.reconcile_history
    calls=[];events=[];connections=[];e.on_lifecycle=events.append
    e.transport_health.backoff=lambda failures:.01
    def repair(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise ExchangeError('INFO_RETRY_BUDGET_EXHAUSTED')
        return original(*args,**kwargs)
    e.reconcile_history=repair
    class Socket:
        def send(self,value):
            data=json.loads(value)
            if data['method']=='subscribe':inbox.put({'channel':'subscriptionResponse','data':data})
        def recv(self):
            if e.reconciled:stop.set();return json.dumps({'channel':'pong'})
            try:return json.dumps(inbox.get(timeout=.01))
            except queue.Empty:raise TimeoutError()
        def close(self):pass
    def connect():connections.append(1);return Socket()
    e.connect=connect;failures=[]
    def run():
        try:e.run(stop)
        except Exception as exc:failures.append(exc)
    t=threading.Thread(target=run);t.start();t.join(3)
    if t.is_alive():stop.set();t.join(2)
    assert not t.is_alive() and not failures
    assert len(calls)==2 and len(connections)==1 and e.reconnections==0
    assert sum(x['phase']=='REST_RECOVERY_DEFERRED' for x in events)==1


def test_identical_inflight_public_reads_are_coalesced(tmp_path):
    j=ExecutionJournal(tmp_path/'reads.sqlite',session_id='fixture',team_address='0x'+'0'*40)
    r=HyperliquidRateLimitManager(j);started=threading.Event();release=threading.Event();calls=[];values=[]
    def operation():calls.append(1);started.set();assert release.wait(3);return {'value':1}
    def run():values.append(r.read('meta',operation,request_key='same-resource'))
    first=threading.Thread(target=run);second=threading.Thread(target=run)
    first.start();assert started.wait(2);second.start()
    deadline=time.monotonic()+2
    while r.coalesced_reads<1 and time.monotonic()<deadline:time.sleep(.005)
    release.set();first.join(3);second.join(3)
    assert len(calls)==1 and values==[{'value':1}]*2 and r.coalesced_reads==1
    assert r.report()['public_reads']['upstream_by_operation']=={'meta':1}
    j.close()


def test_candle_response_weight_cannot_spend_safety_reserve(tmp_path):
    j=ExecutionJournal(tmp_path/'reads.sqlite',session_id='fixture',team_address='0x'+'0'*40)
    r=HyperliquidRateLimitManager(j)
    r.weights=[(r.clock_ms(),1056)];calls=[]
    with pytest.raises(ExchangeError,match='RATE_LIMITED'):
        r.read('candleSnapshot',lambda:calls.append(1),expected_items=300)
    assert not calls
    r.reserve_info('clearinghouseState',priority=RequestPriority.SAFETY)
    assert r._usage()==1058
    j.close()


def test_cancelled_recovery_read_never_contacts_upstream(tmp_path):
    j=ExecutionJournal(tmp_path/'reads.sqlite',session_id='fixture',team_address='0x'+'0'*40)
    r=HyperliquidRateLimitManager(j);cancel=threading.Event();cancel.set();calls=[]
    with pytest.raises(ExchangeError,match='READ_CANCELLED'):
        r.read('meta',lambda:calls.append(1),cancel_event=cancel)
    assert not calls
    j.close()


def test_history_repair_is_bounded_and_never_fills_a_missing_bar():
    source,e=engine();e.history_bars=2;e.reconcile_history()
    original=deepcopy(e.candles['par:BTC'])
    source.now+=60000
    source.history=[]
    e.reconcile_history()
    request=next(p['req'] for p in reversed(source.calls) if p['type']=='candleSnapshot')
    assert request['startTime']>=source.now//60000*60000-2*60000
    assert NOW not in e.candles['par:BTC']
    assert set(e.candles['par:BTC'])<=set(original)


def test_close_frame_retains_server_code_and_reason():
    import websocket
    from types import SimpleNamespace
    _,e=engine();e.transport_health.begin(e.subscriptions())
    class Socket:
        def recv_data_frame(self,**kwargs):
            return websocket.ABNF.OPCODE_CLOSE,SimpleNamespace(data=(1001).to_bytes(2,'big')+b'server restart')
    assert e._receive(Socket())==''
    assert e.transport_health.current['close_code']==1001
    assert e.transport_health.current['close_reason']=='server restart'


def certification_fixture():
    health=dict(execution_mode='PAPER',allow_live_orders=False,exchange_orders_submitted=0,
        issues=[],healthy_markets=['par:BTC'],public_stream=dict(connected=True,reconciled=True,last_error=None,
            transport=dict(current=dict(connection_started_at_ms=0),connections=[],desired_count=3,confirmed_count=3,duplicate_subscriptions=0),
            events=[],public_rate_budget=dict(public_reads=dict(pending=0)),
            account_recovery=dict(entries_paused=False)))
    rows=[dict(symbol='par:BTC',decision_ms=n*300000,
        stages={s:dict(status='PASS') for s in ('MARKET_DATA_HEALTHY','ENOUGH_HISTORY')}) for n in range(3)]
    return health,rows


def test_feed_certification_does_not_require_a_trade_or_signal():
    health,rows=certification_fixture()
    result=FeedCertificationReport.evaluate(health=health,traces=rows,started_ms=0,finished_ms=900000,
        source_unchanged=True,checkpoint_ok=True,clean_shutdown=True,regression_passed=True)
    assert result['feed_certified']
    assert not result['practice_ready'] and not result['controlled_execution_ready'] and not result['live_ready']


@pytest.mark.parametrize('damage',['missing_acks','stale_final','insufficient_windows','unresolved_transport','real_orders'])
def test_feed_certification_fails_closed_with_exact_blocker(damage):
    health,rows=certification_fixture()
    if damage=='missing_acks':health['public_stream']['transport']['confirmed_count']=2
    if damage=='stale_final':health['healthy_markets']=[]
    if damage=='insufficient_windows':rows=rows[:2]
    if damage=='unresolved_transport':health['public_stream']['last_error']='INFO_RETRY_BUDGET_EXHAUSTED'
    if damage=='real_orders':health['exchange_orders_submitted']=1
    result=FeedCertificationReport.evaluate(health=health,traces=rows,started_ms=0,finished_ms=900000,
        source_unchanged=True,checkpoint_ok=True,clean_shutdown=True,regression_passed=True)
    assert not result['feed_certified'] and result['blockers'] and not result['practice_ready']
