"""Offline safety smoke checks, not market evidence or live certification."""
from decimal import Decimal
import pytest
from exchange.base_exchange import ExchangeError, BookLevel, OrderBook
from exchange.rate_limits import PasCandleBudget
from exchange.hyperliquid_market_data import ParMarketDataEngine
from exchange.stream_first import StreamFirstMarketData
from test_pas_stream_warmup import FakeClient, candle, NOW, MINUTE, SYMBOLS


def test_market_shares_preserve_aggregate_and_do_not_starve_ewy():
    clock=[NOW]
    budget=PasCandleBudget(clock_ms=lambda:clock[0])
    budget.reserve(150,symbol=SYMBOLS[0])
    with pytest.raises(ExchangeError,match='PAS_CANDLE_MARKET_SHARE_EXHAUSTED'):
        budget.reserve(1,symbol=SYMBOLS[0])
    budget.reserve(150,symbol=SYMBOLS[1])
    assert budget.report()['used']==300
    clock[0]+=60000
    budget.reserve(150,symbol=SYMBOLS[1])
    budget.reserve(150,symbol=SYMBOLS[0])
    assert budget.report()['used']==300


def test_fair_recovery_commits_real_chunks_then_repairs_only_missing():
    client=FakeClient()
    client.fair_candle_scheduling=True
    client.candle_budget=PasCandleBudget(clock_ms=client.clock_ms)
    class Market:
        def __init__(self):self.client=client;self.requests=[]
        def get_asset_contexts(self):
            return {s:dict(markPx='100',oraclePx='100',funding='0') for s in SYMBOLS}
        def get_candles(self,symbol,start,end,**kwargs):
            count=(end-start)//MINUTE+1
            client.candle_budget.reserve(count,symbol=symbol)
            self.requests.append((symbol,count))
            return [candle(symbol,t//MINUTE,received=client.now)
                    for t in range(start,end+1,MINUTE)]
        def get_orderbook(self,symbol):
            return OrderBook(symbol,client.now,(BookLevel(Decimal('99'),Decimal('100')),),
                (BookLevel(Decimal('101'),Decimal('100')),))
    market=Market()
    engine=ParMarketDataEngine(market,symbols=SYMBOLS,connect=lambda:None)
    engine.reconcile_history()
    assert market.requests==[(s,150) for s in SYMBOLS]
    assert all(len(engine.get_completed_candles(s))==150 for s in SYMBOLS)
    client.now+=MINUTE
    engine.reconcile_history()
    assert all(len(engine.get_completed_candles(s))==300 for s in SYMBOLS)
    # The advancing current window still has a genuine missing minute: never
    # declare that old 300-row cache to be the complete latest window.
    assert all(engine.get_completed_candles(s)[-1].timestamp_ms==NOW-MINUTE for s in SYMBOLS)
    client.now+=MINUTE
    engine.reconcile_history()
    assert market.requests[-2:]==[(s,2) for s in SYMBOLS]
    assert all(engine.get_completed_candles(s)[-1].timestamp_ms==client.now-MINUTE for s in SYMBOLS)


def test_scanner_does_not_spend_slots_before_required_warmup():
    client=FakeClient()
    client.fair_candle_scheduling=True
    class Market:
        def __init__(self):self.client=client
    engine=ParMarketDataEngine(Market(),symbols=SYMBOLS,connect=lambda:None)
    market=StreamFirstMarketData(client,engine,require_warmup=True)
    with pytest.raises(ExchangeError,match='INSUFFICIENT_COMPLETED_HISTORY'):
        market.get_candles(SYMBOLS[0],NOW-300*MINUTE,NOW-1)
    assert client.requests==[]


def test_scanner_stale_completed_bars_cannot_spend_or_signal():
    client=FakeClient()
    client.fair_candle_scheduling=True
    class Market:
        def __init__(self):self.client=client
    engine=ParMarketDataEngine(Market(),symbols=SYMBOLS,connect=lambda:None)
    for i in range(300):
        t=NOW//MINUTE-310+i
        engine.candles[SYMBOLS[0]][t*MINUTE]=candle(SYMBOLS[0],t,received=NOW)
    market=StreamFirstMarketData(client,engine,require_warmup=True)
    with pytest.raises(ExchangeError,match='COMPLETED_CANDLE_STALE'):
        market.get_candles(SYMBOLS[0],NOW-300*MINUTE,NOW-1)
    assert client.requests==[]
