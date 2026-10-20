"""OFFLINE_FIXTURE: measured native observations, not exchange certification."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest
from exchange.base_exchange import ExchangeError
from exchange.candle_availability import CandleAvailabilityMonitor
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine,parse_candle
from test_market_resilience import engine, ready
from test_exchange_migration import NOW, PublicInfoFixture, candle_row

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_practice_health import describe


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests, websocket
    def reject(*a,**kw):raise AssertionError('V7_OFFLINE_NETWORK_FORBIDDEN')
    monkeypatch.setattr(requests.Session,'post',reject)
    monkeypatch.setattr(websocket,'create_connection',reject)


def monitor():
    time=[NOW]
    m=CandleAvailabilityMonitor(('par:BTC','par:ETH'),clock_ms=lambda:time[0])
    return m,time


def response(m,time,rows,start=NOW,end=None,role=None):
    m.observe_rest('par:BTC',start,time[0]-1 if end is None else end,rows,
        parse_candle,time[0],time[0],role=role)


@pytest.mark.parametrize('delay',[0,1000,180000])
def test_exact_completed_reception_delay_and_left_censoring(delay):
    m,time=monitor();time[0]=NOW+60000+delay
    response(m,time,[candle_row(NOW)])
    s=m.snapshot(include_records=True)['markets']['par:BTC']
    assert s['latency']['REST']['median_ms']==delay
    assert s['interval_observations'][NOW]['exchange_publication_timestamp_ms'] is None
    assert s['latency']['REST']['observation_count']==1
    response(m,time,[candle_row(NOW-60000)],start=NOW-60000)
    assert m.snapshot()['markets']['par:BTC']['latency']['REST']['observation_count']==1


def test_empty_response_later_supplies_missing_genuine_candle():
    m,time=monitor();time[0]=NOW+60000
    response(m,time,[])
    s=m.snapshot()['markets']['par:BTC']
    assert s['latency']['right_censored_live_intervals']==1
    assert 'CANDLE_ABSENT_IN_COVERED_REST_RESPONSE' in s['missing_classifications'][str(NOW)]
    time[0]+=30000;response(m,time,[candle_row(NOW)])
    s=m.snapshot()['markets']['par:BTC']
    assert s['delayed_intervals']==1 and s['recovery']['recovered_missing']==1
    assert s['latency']['REST']['median_ms']==30000
    # A source observation alone does not populate the native cache or admit a scanner.
    assert s['present']==0 and not s['eligible_for_scanner_evaluation']


def test_never_observed_interval_is_censored_not_zero_delay():
    m,time=monitor();time[0]=NOW+180000;response(m,time,[])
    stats=m.snapshot()['markets']['par:BTC']['latency']
    assert stats['REST']['median_ms'] is None
    assert stats['REST']['never_observed_intervals']==3
    assert stats['right_censored_live_intervals']==3


def test_unfinished_ws_candle_is_observed_but_not_completed_sample():
    m,time=monitor();c=parse_candle(candle_row(NOW),'par:BTC','1m')
    m.observe_candle(c,'WS',NOW+1000)
    time[0]=NOW+60000
    stats=m.snapshot()['markets']['par:BTC']['latency']['WS']
    assert stats['observation_count']==0 and stats['never_observed_intervals']==1
    m.observe_candle(c,'WS',time[0]+500)
    assert m.snapshot()['markets']['par:BTC']['latency']['WS']['median_ms']==500


def test_rest_ws_duplicates_and_conflicts_keep_source_identity():
    m,time=monitor();time[0]=NOW+60000
    c=parse_candle(candle_row(NOW),'par:BTC','1m')
    m.observe_candle(c,'WS',time[0]);response(m,time,[candle_row(NOW)]*2)
    s=m.snapshot()['markets']['par:BTC']
    assert s['duplicates']==1 and s['conflicting_intervals']==0
    m.observe_candle(replace(c,volume=c.volume+1),'WS',time[0]+1)
    assert m.snapshot()['markets']['par:BTC']['conflicting_intervals']==1


def test_equivalent_decimal_encodings_are_duplicates_not_conflicts():
    m,time=monitor();time[0]=NOW+60000
    response(m,time,[dict(candle_row(NOW),v='1.2500'),candle_row(NOW)])
    assert m.snapshot()['markets']['par:BTC']['conflicting_intervals']==0


@pytest.mark.parametrize('fault',['ohlc','volume','future','identity'])
def test_validator_failures_captured_and_not_accepted(fault):
    m,time=monitor();time[0]=NOW+60000;r=candle_row(NOW)
    if fault=='ohlc':r['h']='1'
    if fault=='volume':r['v']='NaN'
    if fault=='future':r=candle_row(NOW+120000)
    if fault=='identity':r['s']='BTC'
    response(m,time,[r],end=NOW+180000)
    s=m.snapshot()['markets']['par:BTC']
    assert sum(s['malformed_candles'].values())==1
    assert s['latency']['REST']['observation_count']==0


@pytest.mark.parametrize('count',[299,300])
def test_cache_300_gate_separate_from_full_utc(count):
    m,time=monitor();bars=[parse_candle(candle_row(NOW-i*60000),'par:BTC','1m') for i in range(count,0,-1)]
    m.update_cache('par:BTC',bars,NOW,dict(healthy=count==300,state='HEALTHY' if count==300 else 'QUARANTINED'))
    s=m.snapshot()['markets']['par:BTC']
    assert s['present']==count and s['missing']==300-count
    assert s['contiguous_valid_tail']==count
    assert s['strategy_history']=={} and not s['eligible_for_scanner_evaluation']


def test_scanner_history_gap_remains_separate_from_complete_cache():
    m,time=monitor();time[0]+=60000
    bars=[candle_row(NOW-i*60000) for i in range(400,-1,-1)]
    bars=[r for r in bars if r['t']!=NOW-350*60000]
    response(m,time,bars,start=NOW-400*60000,role='SCANNER')
    cache=[parse_candle(r,'par:BTC','1m') for r in bars[-300:]]
    m.update_cache('par:BTC',cache,time[0],dict(healthy=True,state='HEALTHY'))
    s=m.snapshot()['markets']['par:BTC']
    assert s['present']==300 and not s['strategy_history']['history_gate_passed']
    assert not s['eligible_for_scanner_evaluation']


def test_freshness_allowance_does_not_require_latest_expected_minute():
    m,time=monitor();time[0]+=60000
    bars=[candle_row(NOW-i*60000) for i in range(300,0,-1)]
    response(m,time,bars,start=NOW-300*60000,role='SCANNER')
    m.update_cache('par:BTC',[parse_candle(r,'par:BTC','1m') for r in bars],time[0],dict(healthy=True,state='HEALTHY'))
    s=m.snapshot()['markets']['par:BTC']
    assert s['missing']==1 and s['strategy_history_current']
    assert s['eligible_for_scanner_evaluation']
    time[0]+=120001
    assert not m.snapshot()['markets']['par:BTC']['strategy_history_current']


def test_out_of_order_wire_rows_are_normalized_without_inventing_rows():
    m,time=monitor();time[0]+=180000
    response(m,time,[candle_row(NOW+120000),candle_row(NOW),candle_row(NOW+60000)])
    assert m.snapshot()['markets']['par:BTC']['latency']['REST']['observation_count']==3
    assert m.snapshot()['markets']['par:BTC']['rest_observation_history'][-1]['missing_count']==0


def test_rate_deferral_and_insufficient_samples_preserve_backoff():
    m,time=monitor();m.recovery_begin('par:BTC',NOW)
    m.recovery_finish('par:BTC',NOW+100,'PUBLIC_RATE_BUDGET_DEADLINE')
    s=m.snapshot()['markets']['par:BTC']
    assert s['recovery']['deferred_reason']=='RATE_BUDGET_RECOVERY_DEFERRED'
    assert m.retry_hint_ms('par:BTC') is None


def test_adaptive_hint_is_bounded_and_requires_twenty_live_intervals():
    m,time=monitor()
    for i in range(20):
        t=NOW+i*60000;time[0]=t+60000+40000
        m.observe_candle(parse_candle(candle_row(t),'par:BTC','1m'),'REST',time[0])
    assert m.retry_hint_ms('par:BTC')==40000
    _,e=engine();e.health_manager.begin_recovery(['par:BTC'],NOW)
    e.health_manager.finish_recovery(['par:BTC'],NOW,delay_hints={'par:BTC':999999})
    assert e.health_manager.records['par:BTC']['next_retry_at_ms']==NOW+300000


def test_quota_retry_deadline_is_honored_without_exponential_padding_or_fabrication():
    source=PublicInfoFixture()
    client=HyperliquidClient(source,clock_ms=lambda:source.now,venue='par');client.startup()
    e=ParMarketDataEngine(HyperliquidMarketData(client),history_bars=300,include_trades=True)
    ready(e)
    hole=sorted(e.candles['par:BTC'])[30]
    del e.candles['par:BTC'][hole]
    e.market_health()
    genuine_before=dict(e.candles['par:BTC'])
    original=source.__class__.__call__
    retry_after=[60000]

    def quota_limited(payload):
        if payload['type']=='candleSnapshot':
            error=ExchangeError('PAS_CANDLE_BUDGET_EXHAUSTED')
            error.retry_after_ms=retry_after[0]
            error.retryable=False
            raise error
        return original(source,payload)

    e.client.transport=quota_limited
    e.reconcile_history(symbols=['par:BTC'])
    first_deadline=source.now+60000
    assert e.health_manager.records['par:BTC']['next_retry_at_ms']==first_deadline
    assert not e.health_manager.due(first_deadline-1)
    assert 'par:BTC' in e.health_manager.due(first_deadline)
    assert e.candles['par:BTC']==genuine_before
    assert hole not in e.candles['par:BTC']

    # A second, shorter explicit quota wait replaces—not gets padded by—the
    # generic 60-second exponential delay from the prior failed recovery.
    source.now=first_deadline
    retry_after[0]=10000
    e.reconcile_history(symbols=['par:BTC'])
    assert e.health_manager.records['par:BTC']['next_retry_at_ms']==source.now+10000
    assert e.candles['par:BTC']==genuine_before
    assert hole not in e.candles['par:BTC']


def test_healthy_symbol_independent_and_genuine_gap_recovery_recorded():
    source,e=engine();ready(e)
    hole=sorted(e.candles['par:BTC'])[30];del e.candles['par:BTC'][hole]
    assert not e.market_health()['par:BTC']['healthy'] and e.market_health()['par:ETH']['healthy']
    e.reconcile_history(symbols=['par:BTC'])
    assert e.market_health()['par:BTC']['healthy']
    s=e.availability.snapshot()['markets']['par:BTC']
    assert s['recovery']['last_success_ms']==NOW and not s['recovery']['pending']
    assert hole in e.candles['par:BTC']


def test_near_ready_prioritization_never_excludes_old_due_symbol():
    m,time=monitor();m.cache['par:BTC']=list(range(299));m.cache['par:ETH']=[]
    h={'par:BTC':dict(next_retry_at_ms=NOW),'par:ETH':dict(next_retry_at_ms=NOW-60000)}
    assert m.prioritize(('par:BTC','par:ETH'),h)==('par:ETH','par:BTC')


def test_dashboard_has_exact_candle_reasons_and_independent_transport():
    _,e=engine();ready(e);availability=e.availability.snapshot()
    text=describe(dict(status='RUNNING',transport_ready=True,subscriptions_ready=True,
        public_stream=dict(connected=True,reconciled=True,candle_availability=availability),
        market_health=e.market_health()),2,'PAPER_DATA_OR_OPERATIONS_DEGRADED')
    for fragment in ('CANDLE AVAILABILITY','missing timestamps','full UTC scanner input','p95=',
                     'TRADE_READY: NO','TRANSPORT_READY: True'):
        assert fragment in text


def test_observation_history_is_bounded_and_does_not_become_execution_interface():
    m,time=monitor();time[0]+=60000
    for i in range(50):response(m,time,[])
    assert len(m.snapshot()['markets']['par:BTC']['rest_observation_history'])==40
    assert not hasattr(m,'place_order') and not hasattr(m,'cancel_order')
    with pytest.raises(ExchangeError):m.observe_candle(parse_candle(candle_row(NOW),'par:BTC','1m'),'EXTERNAL',time[0])


def test_recovery_cache_repair_is_distinct_from_first_source_observation():
    _,e=engine();ready(e);hole=sorted(e.candles['par:BTC'])[30]
    del e.candles['par:BTC'][hole];e.market_health()
    e.reconcile_history(symbols=['par:BTC'])
    event=e.availability.snapshot()['markets']['par:BTC']['recovery']['events'][-1]
    assert event['cache_holes_filled']==1 and event['recovered_missing']==0


def test_future_malformed_intervals_cannot_escape_retention_bound():
    m,time=monitor()
    for i in range(20):m.reject('par:BTC','FUTURE',timestamp_ms=NOW+(i+1)*60000,source='REST')
    assert len(m.rows['par:BTC'])==0 and m.errors['par:BTC']['FUTURE']==20
