"""V8.8 public HTTP and qualification regressions. Network and real signing forbidden."""
from decimal import Decimal as D
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json,threading,time,socket
import pytest,requests
from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import RequestsInfoTransport,HyperliquidClient
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.reliability_policy import RequestPriority as P
from test_qualification_recovery_v8_7 import launcher
from test_testnet_qualification import qualification
from test_live_exchange_execution import live
from test_exchange_migration import NOW


def test_read_timeout_is_distinct_from_unknown_http_failure(monkeypatch):
    def fail(*args,**kwargs):raise requests.ReadTimeout('OFFLINE_HUNG_RESPONSE')
    monkeypatch.setattr(requests.Session,'post',fail)
    t=RequestsInfoTransport()
    try:
        with pytest.raises(ExchangeError,match='^INFO_READ_TIMEOUT$'):t({'type':'userAbstraction'})
    finally:t.close()


def test_transport_has_separate_timeouts_and_an_absolute_read_deadline(monkeypatch):
    entered=threading.Event();release=threading.Event()
    def hung(*args,**kwargs):entered.set();release.wait(2);raise requests.ReadTimeout('OFFLINE_HUNG_RESPONSE')
    monkeypatch.setattr(requests.Session,'post',hung)
    t=RequestsInfoTransport(connect_timeout=.02,read_timeout=.02,total_timeout=.05)
    start=time.monotonic()
    try:
        with pytest.raises(ExchangeError,match='^INFO_TOTAL_TIMEOUT$'):t({'type':'userAbstraction'})
        assert entered.is_set() and time.monotonic()-start<.5
    finally:release.set();t.close()


def test_server_retry_after_is_not_silently_shortened(live):
    duration=live.rate.error(status=429,retry_after_ms=90000)
    assert duration>=90000 and live.rate.backoff_until>=NOW+90000


def test_interrupted_read_is_not_reported_as_success_to_coalesced_waiter(live):
    started=threading.Event();release=threading.Event();values=[]
    def operation():started.set();assert release.wait(2);raise KeyboardInterrupt()
    def leader():
        try:live.rate.read('meta',operation,request_key='same')
        except KeyboardInterrupt:pass
    def follower():
        try:values.append(live.rate.read('meta',operation,request_key='same'))
        except ExchangeError as exc:values.append(str(exc))
    a=threading.Thread(target=leader);b=threading.Thread(target=follower)
    a.start();assert started.wait(1);b.start()
    deadline=time.monotonic()+1
    while live.rate.coalesced_reads<1 and time.monotonic()<deadline:time.sleep(.001)
    release.set();a.join(2);b.join(2)
    assert values==['INFO_READ_INTERRUPTED']


def test_interrupt_preparation_saves_diagnostic_json_and_closes_sqlite(tmp_path,monkeypatch):
    mod=launcher();closed=[]
    class InterruptedClient:
        def __init__(self,**kwargs):pass
        def startup(self):raise KeyboardInterrupt()
        def close(self):closed.append(True)
    monkeypatch.setattr(mod,'current_test_receipt',lambda *args:tmp_path/'OFFLINE_RECEIPT')
    monkeypatch.setattr(mod,'HyperliquidClient',InterruptedClient)
    out=tmp_path/'interrupted'
    try:r=mod.prepare(out)
    except KeyboardInterrupt:pytest.fail('Interrupted preparation lost final diagnostics')
    assert r['status']=='QUALIFICATION_LOCKED' and r['blocker']=='PREPARATION_INTERRUPTED'
    assert closed==[True] and r['sqlite_integrity']=='ok'
    assert not mod.preflight_flat_proven(r)
    assert json.loads((out/'readiness.json').read_text())['interrupted']
    assert not json.loads((out/'WHITELIST_TRADE_PROOF.json').read_text())['preflight_flat_observed']


class Response:
    def __init__(self,status=200,body=b'{"ok":true}',headers=None):
        self.status_code=status;self.body=body;self.headers=headers or {};self.closed=False
    def iter_content(self,**kwargs):yield self.body
    def close(self):self.closed=True


@pytest.mark.parametrize('kind,code,retryable',[
    ('connect','INFO_CONNECT_TIMEOUT',True),('read','INFO_READ_TIMEOUT',True),
    ('reset','INFO_CONNECTION_FAILED',True),('dns','INFO_DNS_FAILED',True),
    ('tls','INFO_TLS_FAILED',False),('stream_read','INFO_READ_TIMEOUT',True)])
def test_specific_transport_failures(monkeypatch,kind,code,retryable):
    from urllib3.exceptions import ReadTimeoutError
    errors=dict(connect=requests.ConnectTimeout(),read=requests.ReadTimeout(),
        reset=requests.ConnectionError(ConnectionResetError()),
        dns=requests.ConnectionError(socket.gaierror()),tls=requests.exceptions.SSLError(),
        stream_read=requests.ConnectionError(ReadTimeoutError(None,None,'OFFLINE_TIMEOUT')))
    def fail(*args,**kwargs):raise errors[kind]
    monkeypatch.setattr(requests.Session,'post',fail);t=RequestsInfoTransport()
    try:
        with pytest.raises(ExchangeError,match='^'+code+'$') as caught:t({'type':'userAbstraction'})
        assert caught.value.retryable is retryable
        assert t.last_diagnostic['result']==code
    finally:t.close()


@pytest.mark.parametrize('status,retryable',[(429,True),(500,True),(503,True),(400,False),(403,False),(302,False)])
def test_http_status_retry_guidance_and_cleanup(monkeypatch,status,retryable):
    r=Response(status,headers={'Retry-After':'90'});calls=[]
    monkeypatch.setattr(requests.Session,'post',lambda *a,**kw:calls.append(kw) or r)
    t=RequestsInfoTransport()
    try:
        with pytest.raises(ExchangeError,match='^INFO_HTTP_'+str(status)+'$') as e:t({'type':'meta','dex':'par'})
        assert e.value.status_code==status and e.value.retry_after_ms==90000
        assert e.value.retryable is retryable and len(calls)==1 and r.closed
        assert calls[0]['allow_redirects'] is False
    finally:t.close()


@pytest.mark.parametrize('body,limit,code',[(b'not JSON',100,'INFO_INVALID_JSON'),(b'x'*9,8,'INFO_RESPONSE_TOO_LARGE')])
def test_bad_response_never_becomes_account_truth(monkeypatch,body,limit,code):
    r=Response(body=body);monkeypatch.setattr(requests.Session,'post',lambda *a,**kw:r)
    t=RequestsInfoTransport(max_response_bytes=limit)
    try:
        with pytest.raises(ExchangeError,match=code) as e:t({'type':'userAbstraction'})
        assert not e.value.retryable and r.closed
    finally:t.close()


def test_public_transport_exact_endpoint_socket_limits_and_no_adapter_retries(monkeypatch):
    calls=[];r=Response()
    def post(*args,**kwargs):calls.append((args,kwargs));return r
    monkeypatch.setattr(requests.Session,'post',post)
    t=RequestsInfoTransport(connect_timeout=.7,read_timeout=1.2,total_timeout=2)
    try:
        assert t({'type':'userAbstraction','user':'0x'+'11'*20})=={'ok':True}
        args,kw=calls[0]
        assert args[-1]=='https://api.hyperliquid-testnet.xyz/info'
        assert kw['timeout']==(.7,1.2) and kw['stream'] is True
        assert t.session.get_adapter(args[-1]).max_retries.total==0 and r.closed
    finally:t.close()


@pytest.mark.parametrize('field,value',[('connect_timeout',0),('read_timeout',float('inf')),('total_timeout',True),('read_timeout',-1)])
def test_invalid_timeout_policy_is_rejected_before_http(field,value):
    with pytest.raises(ExchangeError,match='INFO_TIMEOUT_POLICY_INVALID'):RequestsInfoTransport(**{field:value})


def test_hung_worker_cannot_spawn_duplicate_workers_or_block_close(monkeypatch):
    release=threading.Event();calls=[]
    def hung(*a,**kw):calls.append(kw);release.wait(2);return Response()
    monkeypatch.setattr(requests.Session,'post',hung)
    t=RequestsInfoTransport(total_timeout=.05);events=[]
    try:
        for _ in range(2):
            with pytest.raises(ExchangeError,match='INFO_TOTAL_TIMEOUT'):
                t({'type':'meta'},progress=lambda event,**kw:events.append(event))
        assert len(calls)==1 and 'WAITING_FOR_HTTP_SLOT' in events
        start=time.monotonic();t.close();assert time.monotonic()-start<.2
    finally:release.set();t.close()


def test_slow_stream_deadline_and_cancellation(monkeypatch):
    release=threading.Event();entered=threading.Event()
    class Slow(Response):
        def iter_content(self,**kwargs):entered.set();release.wait(2);yield b'{}'
    r=Slow();monkeypatch.setattr(requests.Session,'post',lambda *a,**kw:r)
    t=RequestsInfoTransport(total_timeout=.3);cancel=threading.Event()
    def cancel_after_read():assert entered.wait(1);cancel.set()
    timer=threading.Thread(target=cancel_after_read);timer.start()
    try:
        with pytest.raises(ExchangeError,match='INFO_READ_CANCELLED'):t({'type':'userAbstraction'},cancel_event=cancel)
        assert not t.last_diagnostic['result']=='OK'
    finally:release.set();timer.join(1);t.close()


def test_retry_after_http_date_and_invalid_values():
    from datetime import datetime,timezone,timedelta
    from email.utils import format_datetime
    future=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=90),usegmt=True)
    assert 88000<=RequestsInfoTransport._retry_after(future)<=90000
    for value in (None,'nan','inf','bad'):assert RequestsInfoTransport._retry_after(value) is None


def rate_fixture(live):
    live.rate.jitter=lambda:1
    live.rate.wait=lambda ms:setattr(live.fixture,'now',live.fixture.now+int(ms))
    return live.rate


def test_three_read_attempts_are_charged_with_distinct_failure_details(live):
    rate=rate_fixture(live);calls=[]
    def operation():calls.append(1);raise RequestsInfoTransport._failure('INFO_READ_TIMEOUT',retryable=True)
    with pytest.raises(ExchangeError,match='INFO_RETRY_BUDGET_EXHAUSTED'):rate.read('meta',operation)
    assert len(calls)==3 and rate.read_counts=={'meta':3}
    assert rate._usage()==60 and len(rate.read_failure_details)==3
    assert [x['attempt'] for x in rate.read_failure_details]==[1,2,3]
    assert rate.daily_used()==0


def test_retry_after_beyond_deadline_stops_without_early_retry(live):
    rate=rate_fixture(live);calls=[]
    def operation():calls.append(1);raise RequestsInfoTransport._failure('INFO_HTTP_429',status_code=429,retryable=True,retry_after_ms=90000)
    with pytest.raises(ExchangeError,match='INFO_READ_WAIT_DEADLINE'):rate.read('openOrders',operation,priority=P.SAFETY)
    assert len(calls)==1 and rate.backoff_until>=NOW+90000 and rate._usage()==20
    assert rate.read_failure_details[-1]['retry_after_ms']==90000


def test_non_retryable_total_timeout_is_not_repeated(live):
    rate=rate_fixture(live);calls=[]
    def operation():calls.append(1);raise RequestsInfoTransport._failure('INFO_TOTAL_TIMEOUT')
    with pytest.raises(ExchangeError,match='INFO_TOTAL_TIMEOUT'):rate.read('meta',operation)
    assert len(calls)==1 and rate._usage()==20


def test_cancellable_retry_backoff_never_issues_second_read(live):
    rate=rate_fixture(live);cancel=threading.Event();calls=[]
    def operation():calls.append(1);cancel.set();raise RequestsInfoTransport._failure('INFO_CONNECTION_FAILED',retryable=True)
    with pytest.raises(ExchangeError,match='INFO_READ_CANCELLED'):rate.read('meta',operation,cancel_event=cancel)
    assert len(calls)==1


@pytest.mark.parametrize('query',['order','cancel','updateLeverage','userSetAbstraction'])
def test_signed_actions_cannot_enter_public_retry_api(live,query):
    calls=[]
    with pytest.raises(ExchangeError,match='PUBLIC_INFO_QUERY_NOT_ALLOWED'):live.rate.read(query,lambda:calls.append('SIGNED_ACTION'))
    assert not calls and live.rate.daily_used()==0 and not live.transport.signed_payloads


@pytest.mark.parametrize('query,expected',[
    ('l2Book',2),('clearinghouseState',2),('orderStatus',2),('spotClearinghouseState',2),
    ('userRole',60),('userAbstraction',20),('extraAgents',20),('userFees',20)])
def test_official_public_weights(live,query,expected):
    live.rate.reserve_info(query)
    assert live.rate._usage()==expected


def test_history_response_weights_and_reserved_candles_are_not_double_charged(live):
    rate=live.rate;rate.reserve_info('userFillsByTime');rate.observe_info('userFillsByTime',[{}]*60)
    assert rate._usage()==23
    rate.reserve_info('candleSnapshot',response_weight=5)
    rate.observe_info('candleSnapshot',[{}]*300,reserved_response_weight=5)
    assert rate._usage()==48


def test_rate_expiry_estimate_and_safety_reserve_are_grounded(live):
    rate=rate_fixture(live);rate.weights=[(NOW-59000,1080)]
    assert rate.read_budget_delay_ms(20)==1000
    assert rate.read_budget_delay_ms(20,P.SAFETY)==0
    events=[];rate.wait_for_read_budget(20,progress=lambda event,**kw:events.append((event,kw)))
    assert rate._usage()==0 and live.fixture.now==NOW+1000
    assert events[0][0]=='WAITING_FOR_RATE_BUDGET' and events[0][1]['next_retry_ms']==NOW+1000
    assert rate.policy.ip_safety_reserve==120


def test_rate_budget_deadline_exits_cleanly_without_upstream_call(live):
    rate=rate_fixture(live);rate.weights=[(NOW,1080)];events=[]
    with pytest.raises(ExchangeError,match='INFO_PUBLIC_READ_BUDGET_DEADLINE'):
        rate.wait_for_read_budget(20,max_wait_seconds=1,progress=lambda event,**kw:events.append(event))
    assert events==['WAITING_FOR_RATE_BUDGET'] and rate._usage()==1080


def test_cancelling_budget_wait_does_not_reserve_weight(live):
    rate=rate_fixture(live);rate.weights=[(NOW,1080)];cancel=threading.Event()
    with pytest.raises(ExchangeError,match='INFO_READ_CANCELLED'):
        rate.wait_for_read_budget(20,cancel_event=cancel,progress=lambda *a,**kw:cancel.set())
    assert rate._usage()==1080 and rate.daily_used()==0


@pytest.mark.parametrize('query',['userAbstraction','extraAgents','userFees'])
def test_scoped_snapshots_preserve_original_time_and_are_copied(query):
    stamp=[NOW];calls=[]
    def read(payload):calls.append(payload);return {'mode':['original']}
    client=HyperliquidClient(read,clock_ms=lambda:stamp[0])
    with client.read_snapshot_scope():
        first=client.post_info(query,user='0x'+'11'*20);first['mode'].append('mutated')
        stamp[0]+=500
        second=client.post_info(query,user='0x'+'11'*20)
        assert second=={'mode':['original']} and client.last_received_ms==NOW
        assert len(calls)==1
        stamp[0]+=501;client.post_info(query,user='0x'+'11'*20)
        assert len(calls)==2
    client.post_info(query,user='0x'+'11'*20);assert len(calls)==3


@pytest.mark.parametrize('query',['clearinghouseState','openOrders','frontendOpenOrders','userFillsByTime','userFunding','orderStatus'])
def test_account_truth_and_histories_are_never_snapshot_cached(query):
    calls=[];client=HyperliquidClient(lambda p:calls.append(p) or [],clock_ms=lambda:NOW)
    with client.read_snapshot_scope():
        for _ in range(2):client.post_info(query,user='0x'+'11'*20)
    assert len(calls)==2 and client.snapshot_hits==0


def test_market_quotes_are_never_reused_as_fresh(live):
    calls=[];original=live.client.transport
    live.client.transport=lambda p:calls.append(p) or original(p)
    with live.client.read_snapshot_scope():
        for _ in range(2):live.client.post_info('l2Book',coin='par:BTC')
    assert len(calls)==2 and live.client.snapshot_hits==0


def test_interrupt_during_account_reconciliation_preserves_checkpoint_and_unknown_truth(qualification,tmp_path,monkeypatch):
    from exchange.certification_runtime import CertificationRecovery
    c=qualification;mod=launcher();closed=[];original=c.live.client.transport
    def read(payload):
        if payload['type']=='userAbstraction':raise KeyboardInterrupt()
        return original(payload)
    c.live.client.transport=read
    monkeypatch.setattr(c.live.client,'close',lambda:closed.append(True))
    def client(**kw):c.live.client.rate_limits=kw['rate_limits'];return c.live.client
    monkeypatch.setattr(mod,'HyperliquidClient',client)
    monkeypatch.setattr(mod,'current_test_receipt',lambda *a:tmp_path/'OFFLINE_RECEIPT')
    out=tmp_path/'interrupted_account';r=mod.prepare(out)
    assert r['blocker']=='PREPARATION_INTERRUPTED' and not mod.preflight_flat_proven(r)
    assert r['actual_action_rows']==dict(intents=0,api_actions=0,signed_management=0) and closed==[True]
    journal=ExecutionJournal(out/'read_only.sqlite',session_id='qualification-proposal',team_address=mod.TEAM)
    try:
        assert journal.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        account=SimpleNamespace(client=c.live.client,team_address=mod.TEAM)
        recovered=CertificationRecovery(account,journal,initial_start_ms=0)
        assert recovered.saved_snapshot and recovered.saved_snapshot['last_clean_shutdown'] is True
        assert not recovered.last_report.ready
    finally:journal.close()
    proof=json.loads((out/'WHITELIST_TRADE_PROOF.json').read_text())
    assert not proof['fill_verified'] and not proof['preflight_flat_observed']


@pytest.mark.parametrize('code',['INFO_READ_TIMEOUT','INFO_DNS_FAILED','INFO_HTTP_429'])
def test_failed_initial_reconciliation_never_infers_flat(qualification,tmp_path,monkeypatch,code):
    c=qualification;mod=launcher();original=c.live.client.transport
    def read(payload):
        if payload['type']=='userAbstraction':raise RequestsInfoTransport._failure(code)
        return original(payload)
    c.live.client.transport=read
    def client(**kw):c.live.client.rate_limits=kw['rate_limits'];return c.live.client
    monkeypatch.setattr(mod,'HyperliquidClient',client)
    monkeypatch.setattr(mod,'current_test_receipt',lambda *a:tmp_path/'OFFLINE_RECEIPT')
    out=tmp_path/code;r=mod.prepare(out)
    assert r['status']=='QUALIFICATION_LOCKED' and not mod.preflight_flat_proven(r)
    assert r['exchange_submissions']==r['actual_wallet_signatures']==0
    assert not json.loads((out/'WHITELIST_TRADE_PROOF.json').read_text())['preflight_flat_observed']
    assert r['sqlite_integrity']=='ok' and not (out/'proposal.json').exists()


def test_saved_v87_real_thin_books_cannot_be_relabelled_ready(qualification):
    import exchange.testnet_qualification as q
    from test_qualification_recovery_v8_7 import context
    root=Path(__file__).resolve().parents[1]
    saved=json.loads((root/'docs/qualification_recovery_v8_7_2026-10-13/read_only_preflight/readiness.json').read_text())
    ctx=context(qualification)
    for row in saved['candidates']:
        symbol=row['symbol'];quote=row['quote'];spec=qualification.live.client.market(symbol)
        translated=replace(ctx,quote=replace(ctx.quote,symbol=symbol,
            bid=D(quote['bid']),ask=D(quote['ask']),mid=D(quote['mid']),mark=D(quote['mark']),oracle=D(quote['oracle']),
            bid_quantity=D(quote['bid_quantity']),ask_quantity=D(quote['ask_quantity'])),
            spec=spec,active_asset=dict(ctx.active_asset,coin=symbol))
        result=q.find_largest_safe_qualification_quantity(translated,qualification.live.client,'fixture-source','fixture-policy')
        assert not result['ready'] and result['rejection']=='QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS'
    assert not qualification.venue.calls and not qualification.live.transport.signed_payloads
