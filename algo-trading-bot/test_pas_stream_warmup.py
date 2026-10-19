"""PAS stream warmup regressions: genuine source facts only, no fabricated bars."""
from decimal import Decimal

import pytest

from exchange.base_exchange import Candle, ExchangeError
from exchange.hyperliquid_market_data import ParMarketDataEngine
from exchange.market_health import MarketHealthManager, validate_history
from exchange.stream_first import StreamFirstMarketData

MINUTE = 60_000
NOW = 2_000_000 * MINUTE
SYMBOLS = ('pas:BTC', 'pas:EWY')


class FakeClient:
    competition_mode = True
    rate_limits = None
    candle_audit = None
    last_received_ms = NOW

    def __init__(self, *, now=NOW, rows=None):
        self.now = now
        self.rows = rows or []
        self.requests = []
        self.markets = {symbol: object() for symbol in SYMBOLS}
        self.availability_monitor = None

    def clock_ms(self):
        return self.now

    def market(self, symbol):
        if symbol not in self.markets:
            raise ExchangeError('UNKNOWN_MARKET')
        return self.markets[symbol]

    def post_info(self, endpoint, **kwargs):
        assert endpoint == 'candleSnapshot'
        self.requests.append(kwargs['req'])
        return self.rows


class FakeMarket:
    def __init__(self, client):
        self.client = client


def candle(symbol, minute, *, received=None, close=100):
    t = minute * MINUTE
    value = Decimal(str(close))
    return Candle(symbol, '1m', t, t + MINUTE - 1, value, value, value, value,
                  Decimal('1'), received, received)


def raw_candle(symbol, minute, *, close=100):
    t = minute * MINUTE
    value = str(close)
    return dict(s=symbol, i='1m', t=t, T=t + MINUTE - 1, o=value, h=value,
                l=value, c=value, v='1')


def setup_engine(*, history_bars=300, now=NOW, rest_rows=None):
    client = FakeClient(now=now, rows=rest_rows)
    market = FakeMarket(client)
    engine = ParMarketDataEngine(market, symbols=SYMBOLS, history_bars=history_bars,
                                 connect=lambda: None)
    return client, engine, StreamFirstMarketData(client, engine)


@pytest.mark.parametrize('symbol', SYMBOLS)
@pytest.mark.parametrize('count,ready', [(299, False), (300, True)])
def test_both_pas_assets_require_300_real_contiguous_completed_bars(symbol, count, ready):
    bars = [candle(symbol, 1000 + i, received=(1001 + i) * MINUTE)
            for i in range(count)]
    assert len(bars) == count
    if ready:
        validate_history(symbol, bars, NOW, 300)
    else:
        with pytest.raises(ExchangeError, match='INSUFFICIENT_COMPLETED_HISTORY'):
            validate_history(symbol, bars, NOW, 300)


def test_pas_does_not_promote_open_or_unknown_receive_observations_after_clock_passage():
    client, engine, _ = setup_engine(now=NOW)
    symbol = SYMBOLS[0]
    open_seen_at = NOW - MINUTE + 10
    engine.candles[symbol][NOW - MINUTE] = candle(symbol, NOW // MINUTE - 1,
                                                   received=open_seen_at)
    engine.candles[symbol][NOW - 2 * MINUTE] = candle(symbol, NOW // MINUTE - 2,
                                                       received=None)
    # The clock has advanced well past both source timestamps; that is not a
    # substitute for an actual post-close source observation.
    client.now = NOW + 10 * MINUTE
    assert engine.get_completed_candles(symbol) == []


def test_gaps_future_and_staleness_remain_blocking():
    symbol = SYMBOLS[0]
    gap = [candle(symbol, 10 + i + (i >= 150), received=(12 + i) * MINUTE)
           for i in range(300)]
    with pytest.raises(ExchangeError, match='STRATEGY_CANDLE_GAP_OR_DUPLICATE'):
        validate_history(symbol, gap, NOW, 300)
    future = [candle(symbol, 10 + i, received=(12 + i) * MINUTE) for i in range(299)]
    future.append(candle(symbol, NOW // MINUTE, received=NOW + MINUTE))
    with pytest.raises(ExchangeError, match='FUTURE_OR_OPEN_COMPLETED_CANDLE'):
        validate_history(symbol, future, NOW, 300)
    stale = [candle(symbol, 10 + i, received=(12 + i) * MINUTE) for i in range(300)]
    health = MarketHealthManager([symbol], history_bars=300, max_candle_age_ms=2 * MINUTE)
    record = health.evaluate(symbol, stale, None, None, None, NOW)
    assert record['healthy'] is False
    assert 'LAST_CANDLE_TIME_STALE' in record['reasons']


def test_stream_rows_accumulate_with_partial_rest_without_replacing_them():
    # Requested range is four completed minutes; cache has genuine 1,2 and REST repairs 3,4.
    now = 20 * MINUTE + 1
    rows = [raw_candle(SYMBOLS[0], 3), raw_candle(SYMBOLS[0], 4)]
    client, engine, market = setup_engine(now=now, rest_rows=rows)
    engine.connected = engine.reconciled = True
    for minute in (1, 2, 5):
        engine.candles[SYMBOLS[0]][minute * MINUTE] = candle(
            SYMBOLS[0], minute, received=(minute + 1) * MINUTE)
    result = market.get_candles(SYMBOLS[0], MINUTE, 5 * MINUTE - 1, now_ms=now)
    assert [c.timestamp_ms // MINUTE for c in result] == [1, 2, 3, 4]
    assert result[0].close == Decimal('100') and result[-1].close == Decimal('100')


def test_conflicting_finalized_stream_and_rest_bar_quarantines_only_market():
    now = 20 * MINUTE + 1
    client, engine, market = setup_engine(now=now,
        rest_rows=[raw_candle(SYMBOLS[0], 2, close=101)])
    engine.connected = engine.reconciled = True
    engine.candles[SYMBOLS[0]][2 * MINUTE] = candle(
        SYMBOLS[0], 2, received=3 * MINUTE, close=100)
    with pytest.raises(ExchangeError, match='CONFLICTING_COMPLETED_CANDLES'):
        market.get_candles(SYMBOLS[0], MINUTE, 2 * MINUTE, now_ms=now)
    assert engine.scanner_errors[SYMBOLS[0]] == 'CONFLICTING_COMPLETED_CANDLES'
    assert SYMBOLS[1] not in engine.scanner_errors


def test_pas_retention_covers_full_utc_window_beyond_300_bars_and_is_bounded():
    _, engine, _ = setup_engine(history_bars=300)
    assert engine.history_bars == 300
    assert engine.retention_capacity == 5001  # <=5000 completed + one mutable bar
    symbol = SYMBOLS[0]
    for minute in range(600):
        engine.candles[symbol][minute * MINUTE] = candle(
            symbol, minute, received=(minute + 1) * MINUTE)
    assert len(engine.get_completed_candles(symbol)) == 600
    assert min(engine.get_completed_candles(symbol), key=lambda c: c.timestamp_ms).timestamp_ms == 0


def test_disconnected_cache_is_not_a_stream_readiness_source():
    now = 20 * MINUTE + 1
    # Deliberately incomplete REST result; a full but disconnected cache must
    # not be used to satisfy the requested scanner window.
    client, engine, market = setup_engine(now=now, rest_rows=[raw_candle(SYMBOLS[0], 1)])
    for minute in range(1, 6):
        engine.candles[SYMBOLS[0]][minute * MINUTE] = candle(
            SYMBOLS[0], minute, received=(minute + 1) * MINUTE)
    with pytest.raises(ExchangeError, match='PAS_SCANNER_WINDOW_INCOMPLETE'):
        market.get_candles(SYMBOLS[0], MINUTE, 5 * MINUTE, now_ms=now)


def test_full_utc_rest_repair_uses_bounded_chunks_and_requires_all_rows():
    now = 1000 * MINUTE + 1
    client, engine, market = setup_engine(now=now)
    # The fake public endpoint returns only real minute observations within
    # each requested segment and records the exact read bounds.
    def post_info(endpoint, **kwargs):
        assert endpoint == 'candleSnapshot'
        req = kwargs['req']
        client.requests.append(req)
        return [raw_candle(req['coin'], minute) for minute in range(
            (req['startTime'] + MINUTE - 1) // MINUTE,
            req['endTime'] // MINUTE + 1)]
    client.post_info = post_info
    result = market.get_candles(SYMBOLS[0], MINUTE, 651 * MINUTE - 1, now_ms=now)
    assert len(result) == 650
    assert len(client.requests) == 3
    assert max((req['endTime'] - req['startTime']) // MINUTE + 1
               for req in client.requests) <= 300
    validate_history(SYMBOLS[0], result, now, 300)


def test_real_budget_deferral_retains_chunks_and_resumes_at_missing_history():
    from exchange.rate_limits import PasCandleBudget
    clock = [0]
    budget = PasCandleBudget(clock_ms=lambda: clock[0])
    now = 1000 * MINUTE
    client, engine, market = setup_engine(now=now)
    engine.connected = engine.reconciled = True
    def post_info(endpoint, **kwargs):
        assert endpoint == 'candleSnapshot'
        req = kwargs['req']
        budget.reserve((req['endTime'] - req['startTime']) // MINUTE + 1)
        client.requests.append(req)
        return [raw_candle(req['coin'], minute) for minute in range(
            req['startTime'] // MINUTE, req['endTime'] // MINUTE + 1)]
    client.post_info = post_info
    symbol = SYMBOLS[0]
    for expected_retained in (300, 600):
        with pytest.raises(ExchangeError, match='PAS_CANDLE_BUDGET_EXHAUSTED'):
            market.get_candles(symbol, 0, 650 * MINUTE - 1, now_ms=now)
        assert len(engine.get_completed_candles(symbol)) == expected_retained
        assert budget.report()['used'] == 300
        clock[0] += MINUTE
    result = market.get_candles(symbol, 0, 650 * MINUTE - 1, now_ms=now)
    assert len(result) == 650
    assert [r['startTime'] // MINUTE for r in client.requests] == [0, 300, 599]
    assert budget.report()['used'] == 51  # one real retained bar rechecked in overlap
    validate_history(symbol, result, now, 300)


def test_cached_complete_window_cannot_clear_a_completed_fact_conflict():
    now = 20 * MINUTE
    client, engine, market = setup_engine(now=now)
    engine.connected = engine.reconciled = True
    symbol = SYMBOLS[0]
    for minute in range(1, 6):
        engine.candles[symbol][minute * MINUTE] = candle(
            symbol, minute, received=(minute + 1) * MINUTE)
    engine.note_scanner_failure(symbol, 'CONFLICTING_COMPLETED_CANDLES')
    with pytest.raises(ExchangeError, match='CONFLICTING_COMPLETED_CANDLES'):
        market.get_candles(symbol, MINUTE, 6 * MINUTE - 1, now_ms=now)
    assert not client.requests


def test_trailing_300_bars_cannot_hide_a_missing_utc_anchor_prefix():
    now = 400 * MINUTE
    client, engine, market = setup_engine(now=now)
    engine.connected = engine.reconciled = True
    symbol = SYMBOLS[0]
    for minute in range(100, 400):
        engine.candles[symbol][minute * MINUTE] = candle(
            symbol, minute, received=(minute + 1) * MINUTE)
    # Endpoint supplies no missing UTC-anchor bars; fresh trailing bars alone
    # must not silently change the frozen brain's requested input range.
    with pytest.raises(ExchangeError, match='PAS_SCANNER_WINDOW_INCOMPLETE'):
        market.get_candles(symbol, 0, 400 * MINUTE - 1, now_ms=now)
