"""Offline real public-feed composition; no funded-account certification."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import queue
import sys
import threading
import time

import pytest

from exchange.base_exchange import ExchangeError,VenueMismatch
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine,parse_candle
from exchange.market_health import MarketHealthManager,validate_history
from exchange.paper_operations import PaperHealth
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy,ScanResult
from market_stream import MarketStream
from test_exchange_migration import PublicInfoFixture,NOW,candle_row
from test_crypto_paper_infrastructure import universe,make_bot,POLICY,signal_scan

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_practice_health import assess,describe


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests,websocket
    def reject(*args,**kwargs):raise AssertionError('NO_NETWORK_OR_SIGNED_ACTION')
    monkeypatch.setattr(requests.Session,'post',reject)
    monkeypatch.setattr(websocket,'create_connection',reject)


def engine():
    source=PublicInfoFixture();client=HyperliquidClient(source,clock_ms=lambda:source.now);client.startup()
    e=ParMarketDataEngine(HyperliquidMarketData(client),history_bars=300,include_trades=True)
    return source,e


def ready(e):
    e.connected=True;e.transport_health.begin(e.subscriptions())
    for s in e.subscriptions():
        e.transport_health.subscription_sent(s['subscription'])
        e.transport_health.receive({'channel':'subscriptionResponse','data':s},e.transport_health.generation)
    e.reconcile_history()


def test_stale_btc_does_not_quarantine_healthy_eth_and_restores():
    source,e=engine();ready(e)
    e.candles['par:BTC']={k:c for k,c in e.candles['par:BTC'].items() if k<NOW-600000}
    h=e.market_health()
    assert h['par:BTC']['state']=='QUARANTINED' and h['par:ETH']['healthy']
    assert h['par:BTC']['data_state']=='INSUFFICIENT_HISTORY'
    source.now+=30000;source.book['time']=source.now
    assert 'par:BTC' in e.health_manager.due(source.now)
    e.reconcile_history(symbols=['par:BTC'])
    assert e.market_health()['par:BTC']['healthy']
    assert e.health_manager.records['par:BTC']['restorations']>=1
    requests=[x['req'] for x in source.calls if x['type']=='candleSnapshot']
    assert all(x['coin'].startswith('par:') for x in requests)
    assert requests[-1]['endTime']-requests[-1]['startTime']<300*60000


@pytest.mark.parametrize('fault',['gap','duplicate','future','ohlc','volume','identity'])
def test_all_completed_input_integrity_checked_before_brain(fault):
    bars=[parse_candle(candle_row(NOW-i*60000),'par:BTC','1m') for i in range(300,0,-1)]
    if fault=='gap':bars[40]=replace(bars[40],timestamp_ms=bars[40].timestamp_ms+60000,close_timestamp_ms=bars[40].close_timestamp_ms+60000)
    if fault=='duplicate':bars[40]=bars[39]
    if fault=='future':bars[-1]=replace(bars[-1],timestamp_ms=NOW+60000,close_timestamp_ms=NOW+119999)
    if fault=='ohlc':bars[-1]=replace(bars[-1],high=Decimal('1'))
    if fault=='volume':bars[-1]=replace(bars[-1],volume=Decimal('NaN'))
    if fault=='identity':bars[-1]=replace(bars[-1],symbol='BTC')
    with pytest.raises(ExchangeError):validate_history('par:BTC',bars,NOW,300)


def test_tail_repair_backfills_older_gap_without_fabrication():
    _,e=engine();ready(e)
    hole=sorted(e.candles['par:BTC'])[30];del e.candles['par:BTC'][hole]
    assert not e.market_health()['par:BTC']['healthy']
    e.reconcile_history(symbols=['par:BTC'])
    bars=e.get_completed_candles('par:BTC');validate_history('par:BTC',bars,NOW,300)
    assert len(bars)==300 and hole in e.candles['par:BTC']


@pytest.mark.parametrize('response',['empty','csv','invalid','error'])
def test_unavailable_rest_never_creates_candles_or_restores_market(response):
    source,e=engine()
    original=source.__class__.__call__
    def info(payload):
        if payload['type']=='candleSnapshot':
            if response=='empty':return []
            if response=='csv':return 'Timestamp,Open,High,Low,Close,Volume\n2026-10-02,1,2,1,2,10'
            if response=='invalid':return [dict(candle_row(NOW-60000,payload['req']['coin']),h='1')]
            raise ExchangeError('FIXTURE_REST_OFFLINE')
        return original(source,payload)
    e.client.transport=info
    # Transport call is the real client boundary; no research path is consulted.
    e.reconcile_history()
    assert not any(e.candles.values())
    assert all(not h['healthy'] and h['state']=='QUARANTINED' for h in e.market_health().values())


def test_future_rest_timestamp_rejected_and_identical_duplicates_deduplicated():
    source,e=engine();source.history=[candle_row(NOW+60000)]
    with pytest.raises(ExchangeError,match='FUTURE_REST_CANDLE'):
        e.market.get_candles('par:BTC',NOW,NOW+120000,now_ms=NOW)
    source.history=[candle_row(NOW-60000)]*2
    rows=e.market.get_candles('par:BTC',NOW-60000,NOW-1,now_ms=NOW)
    assert len(rows)==1


def test_invalid_known_stream_symbol_is_local_but_wrong_venue_still_fatal():
    _,e=engine();ready(e)
    bad=dict(candle_row(NOW-60000),h='1')
    assert e.ingest({'channel':'candle','data':bad}) is False
    assert e.connected and e.reconciled
    assert not e.market_health()['par:BTC']['healthy'] and e.market_health()['par:ETH']['healthy']
    with pytest.raises(VenueMismatch):e.ingest({'channel':'candle','data':candle_row(NOW-60000,'BTC')})
    assert not e.connected


def test_mixed_stream_batch_keeps_other_real_bars():
    _,e=engine();ready(e)
    e.ingest({'channel':'candle','data':[dict(candle_row(NOW-60000),v='bad'),candle_row(NOW-60000,'par:ETH')]})
    assert e.market_health()['par:ETH']['healthy'] and not e.market_health()['par:BTC']['healthy']


def test_malformed_context_is_symbol_local():
    _,e=engine();ready(e);e.contexts['par:BTC']=[]
    h=e.market_health()
    assert h['par:BTC']['context_health']=='INVALID_DATA' and not h['par:BTC']['healthy']
    assert h['par:ETH']['healthy'] and e.connected


def test_unknown_protocol_channel_still_fails_connection_closed():
    _,e=engine();ready(e)
    with pytest.raises(ExchangeError,match='UNEXPECTED_PUBLIC_STREAM_CHANNEL'):
        e.ingest({'channel':'unrecognized','data':{'coin':'par:BTC'}})
    assert not e.connected and not e.reconciled


@pytest.mark.parametrize('source_kind',['REST','WS'])
def test_future_book_cannot_poison_cache(source_kind):
    source,e=engine();ready(e);before=e.books['par:BTC'];bad=dict(deepcopy(source.book),time=NOW+600000)
    if source_kind=='REST':
        source.book=bad
        with pytest.raises(ExchangeError,match='FUTURE_ORDERBOOK'):e.market.get_orderbook('par:BTC')
    else:
        assert e.ingest({'channel':'l2Book','data':bad}) is False
        assert e.connected and e.market_health()['par:ETH']['healthy']
    assert e.books['par:BTC']==before


def test_quarantine_blocks_scanner_brain_signal_and_paper_order(monkeypatch):
    source,e=engine();original=e.market.get_candles
    def stale(symbol,*a,**kw):return [] if symbol=='par:BTC' else original(symbol,*a,**kw)
    monkeypatch.setattr(e.market,'get_candles',stale)
    s=MarketRegimeScanner(e.market,ScannerPolicy('.004',15,0,10))
    calls=[];brain=s.brain.evaluate_candles
    monkeypatch.setattr(s.brain,'evaluate_candles',lambda bars:(calls.append(bars[0].symbol),brain(bars))[1])
    scan=s.scan();btc=next(d for d in scan.diagnostics if d.symbol=='par:BTC')
    assert btc.signal is None and not btc.qualified and 'par:BTC' not in calls and 'par:BTC' not in scan.watchlist
    assert len(calls)==9


def composition(universe):
    source,bot=make_bot(universe)
    e=ParMarketDataEngine(bot.market,history_bars=30,include_trades=True);stream=MarketStream(e,POLICY)
    ready(e);stream.poll(bot)
    bot.latest_scan=ScanResult(NOW,[],[],'NO_TRADE')
    return source,bot,e,stream


def test_partial_health_exit_success_with_stale_symbol_and_no_signal(universe,tmp_path):
    _,bot,e,stream=composition(universe)
    e.candles['par:BTC'].clear();stream.poll(bot)
    value=PaperHealth(tmp_path,session_id='offline',segment='offline').write(bot)
    code,reason=assess(tmp_path/'health.json',now_ms=NOW)
    assert code==0 and value['overall']=='PARTIAL_HEALTHY' and value['feed_ready'] and not value['trade_ready']
    assert value['usable_markets']==10 and not value['global_blockers']
    text=describe(value,code,reason)
    for word in ['par:BTC: QUARANTINED','INSUFFICIENT_COMPLETED_HISTORY','TRANSPORT: CONNECTED','44 / 44',
                 'USABLE MARKETS: 10 / 11','FEED_READY: YES','TRADE_READY: NO','GLOBAL BLOCKER: NONE']:
        assert word in text


@pytest.mark.parametrize('fault',['all_markets','transport','account','budget','accounting','worker','subscription'])
def test_genuine_global_problem_remains_degraded(universe,tmp_path,fault):
    _,bot,e,stream=composition(universe)
    if fault=='all_markets':
        for s in e.symbols:e.candles[s].clear()
        stream.poll(bot)
    if fault=='transport':bot.stream_report['connected']=False
    if fault=='account':bot.stream_report['account_recovery']['entries_paused']=True
    if fault=='budget':bot.stream_report['public_rate_budget']={'public_read_blocked':True,'state':'UNKNOWN'}
    if fault=='accounting':bot.accounting_halt='FIXTURE_CHECKSUM_BAD'
    if fault=='worker':bot.breakers.pause('worker','FIXTURE_WORKER_FAILED')
    if fault=='subscription':bot.stream_report['transport']['confirmed_count']-=1
    value=PaperHealth(tmp_path,session_id='offline',segment='offline').write(bot)
    assert assess(tmp_path/'health.json',now_ms=NOW)[0]==2
    assert value['overall']=='DEGRADED' and not value['feed_ready'] and value['global_blockers']


def test_pending_repair_pauses_only_selected_symbol_and_finishes_without_account_restart():
    _,e=engine();ready(e);gen=e.recovery_generation
    e.health_manager.begin_recovery(['par:BTC'],NOW)
    h=e.market_health();assert not h['par:BTC']['healthy'] and h['par:ETH']['healthy']
    e.health_manager.finish_recovery(['par:BTC'],NOW);e.market_health()
    e.reconcile_history(e.transport_health.generation,['par:BTC'])
    assert e.market_health()['par:BTC']['healthy'] and e.recovery_generation==gen


def test_automatic_retry_worker_recovers_empty_history_on_existing_socket():
    source,e=engine();e.health_manager.retry_ms=1;original=e.market.get_candles;calls=[]
    def get(symbol,*a,**kw):
        if symbol=='par:BTC':
            calls.append(symbol)
            if len(calls)==1:return []
        return original(symbol,*a,**kw)
    e.market.get_candles=get;stop=threading.Event();inbox=queue.Queue();advanced=False;connections=[]
    class Socket:
        def send(self,value):
            data=json.loads(value)
            if data['method']=='subscribe':inbox.put({'channel':'subscriptionResponse','data':data})
        def recv(self):
            nonlocal advanced
            if e.reconciled and not advanced:source.now+=10;advanced=True
            if len(calls)>=2 and e.health_manager.records['par:BTC']['healthy']:stop.set()
            try:return json.dumps(inbox.get(timeout=.01))
            except queue.Empty:raise TimeoutError()
        def close(self):pass
    def connect():connections.append(1);return Socket()
    e.connect=connect;errors=[]
    def run():
        try:e.run(stop)
        except Exception as exc:errors.append(exc)
    t=threading.Thread(target=run);t.start();t.join(4)
    if t.is_alive():stop.set();t.join(2)
    assert not t.is_alive() and not errors and len(calls)>=2
    assert len(connections)==1 and e.reconnections==0 and e.health_manager.records['par:BTC']['restorations']>=1


def test_expiry_reconnect_restores_40_subscriptions_while_bad_symbol_stays_quarantined():
    source,e=engine();stop=threading.Event();sockets=[];original=e.market.get_candles
    e.market.get_candles=lambda symbol,*a,**kw: [] if symbol=='par:BTC' else original(symbol,*a,**kw)
    class Stop(threading.Event):
        def wait(self,timeout=None):return self.is_set()
    stop=Stop()
    class Socket:
        def __init__(self):self.inbox=queue.Queue()
        def send(self,value):
            d=json.loads(value)
            if d['method']=='subscribe':self.inbox.put({'channel':'subscriptionResponse','data':d})
        def recv(self):
            if e.reconciled:
                if len(sockets)==1:
                    e.transport_health.current.update(close_code=1000,close_reason='Expired');return ''
                stop.set();return json.dumps({'channel':'pong'})
            try:return json.dumps(self.inbox.get(timeout=.01))
            except queue.Empty:raise TimeoutError()
        def close(self):pass
    def connect():s=Socket();sockets.append(s);return s
    e.connect=connect;e.run(stop,max_reconnects=1)
    assert len(sockets)==2 and e.reconnections==1
    assert e.transport_health.report()['confirmed_count']==40 and e.transport_health.report()['duplicate_subscriptions']==0
    h=e.market_health();assert not h['par:BTC']['healthy'] and h['par:ETH']['healthy']
    assert e.last_error is None


@pytest.mark.parametrize('fault',[None,'no_market','one_sample','sample_digest','workers','scanner','unsafe'])
def test_feed_certificate_uses_usable_data_not_forced_strategy_signal(fault):
    from exchange.market_resilience_certification import evaluate_resilience
    base=dict(checks={'paper_lock':True,'no_exchange_orders':True,'sustained_valid_market':False,
                    'final_valid_market':False},health_samples_checksum_matches=True,
              per_market={'par:ETH':{'healthy':1}},local_fills=0)
    health=dict(healthy_markets=['par:ETH'],last_operating_feed_ready=True,
        public_stream={'workers_stopped_cleanly':True,'market_health':{'transitions':[
            {'symbol':'par:ETH','state':'QUARANTINED'},{'symbol':'par:ETH','state':'RECOVERING'},
            {'symbol':'par:ETH','state':'HEALTHY'}]}})
    samples=[dict(status='RUNNING',feed_ready=True,usable_markets=1,total_markets=10,
                  global_blockers=[],timestamp_ms=NOW+i*30000) for i in range(2)]
    if fault=='no_market':health['healthy_markets']=[]
    if fault=='one_sample':samples=samples[:1]
    if fault=='sample_digest':base['health_samples_checksum_matches']=False
    if fault=='workers':health['public_stream']['workers_stopped_cleanly']=False
    if fault=='scanner':base['per_market']['par:ETH']['healthy']=0
    if fault=='unsafe':base['checks']['paper_lock']=False
    result=evaluate_resilience(base,samples,health)
    assert result['feed_certified']==(fault is None)
    assert not result['controlled_execution_ready'] and not result['practice_ready'] and not result['live_ready']
    if fault is None:assert result['partial_healthy_samples']==2 and result['restored_after_quarantine']==['par:ETH']
