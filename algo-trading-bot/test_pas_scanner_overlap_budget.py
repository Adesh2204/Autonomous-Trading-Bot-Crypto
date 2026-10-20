"""Synthetic offline fixtures only; never runtime candles or market evidence."""
import sqlite3
from contextlib import contextmanager

import pytest

from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData, ParMarketDataEngine
from exchange.rate_limits import HyperliquidRateLimitManager, PasCandleBudget
from exchange.stream_first import StreamFirstMarketData
from test_pas_stream_warmup import MINUTE, NOW, SYMBOLS, candle, raw_candle


class OfflineJournal:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.execute('CREATE TABLE controls (name TEXT PRIMARY KEY, value TEXT)')
        self.session_id = 'offline-scanner-overlap-regression'

    @contextmanager
    def transaction(self):
        yield

    def event(self, *args, **kwargs):
        pass


def scanner(symbol, *, seeded=(), rest_rows=None):
    """A connected/reconciled engine and testnet-client path, with no HTTP transport."""
    budget = PasCandleBudget(clock_ms=lambda: NOW)
    for slots, charged_symbol in seeded:
        budget.reserve(slots, **({'symbol': charged_symbol} if charged_symbol else {}))
    requests = []

    def transport(payload):
        req = payload['req']
        requests.append(dict(req))
        if rest_rows is not None:
            return rest_rows(req)
        return [raw_candle(req['coin'], minute) for minute in range(
            req['startTime'] // MINUTE, req['endTime'] // MINUTE + 1)]

    manager = HyperliquidRateLimitManager(OfflineJournal(), clock_ms=lambda: NOW,
        jitter=lambda: 0, wait=lambda milliseconds: None)
    client = HyperliquidClient(transport=transport, clock_ms=lambda: NOW,
                               rate_limits=manager)
    client.candle_budget = budget
    client.fair_candle_scheduling = True
    client.ready = True
    client.api_markets = {market: market for market in SYMBOLS}
    client.markets = {market: object() for market in SYMBOLS}
    # Skip identity discovery only; all scanner, reservation, parsing and rate
    # manager code below is the production implementation.
    client._validate_coin = lambda coin: None
    data = HyperliquidMarketData(client)
    engine = ParMarketDataEngine(data, symbols=SYMBOLS, history_bars=300,
                                 connect=lambda: None)
    engine.connected = engine.reconciled = True

    # More than 300 completed source observations. The latest 300 are contiguous,
    # received post-close, and fresh; the requested older minute is intentionally
    # absent while its immediate successor is retained for optional verification.
    target = NOW // MINUTE - 302
    for minute in range(target + 1, NOW // MINUTE):
        engine.candles[symbol][minute * MINUTE] = candle(
            symbol, minute, received=(minute + 1) * MINUTE)
    market = StreamFirstMarketData(client, engine, require_warmup=True)
    return budget, requests, engine, market, target


@pytest.mark.parametrize('symbol', SYMBOLS)
@pytest.mark.parametrize('quota_mode', ['market-share', 'global'])
def test_quota_refusal_of_optional_overlap_retries_exact_missing_minute(symbol, quota_mode):
    if quota_mode == 'market-share':
        seeded = [(149, symbol)]
    else:
        # Mixed/legacy unassigned slots can exhaust the shared budget while the
        # selected market still has room for an exact one-slot repair.
        seeded = [(148, symbol), (151, None)]
    budget, requests, engine, market, target = scanner(symbol, seeded=seeded)
    assert engine.connected and engine.reconciled
    assert len(engine.get_completed_candles(symbol)) >= 300

    rows = market.get_candles(symbol, target * MINUTE,
                              NOW - 1, now_ms=NOW)
    assert [row.timestamp_ms for row in rows] == list(range(target * MINUTE, NOW, MINUTE))
    # The 2-slot request was refused before transport; only the 1-slot retry is sent.
    assert len(requests) == 1
    assert requests[0]['startTime'] == target * MINUTE
    assert requests[0]['endTime'] == (target + 1) * MINUTE - 1
    assert budget.report()['used'] == (150 if quota_mode == 'market-share' else 300)


def test_no_remaining_quota_still_fails_without_http_or_additional_charge():
    symbol = SYMBOLS[0]
    budget, requests, _, market, target = scanner(
        symbol, seeded=[(150, symbol), (150, None)])
    with pytest.raises(ExchangeError, match='PAS_CANDLE_MARKET_SHARE_EXHAUSTED'):
        market.get_candles(symbol, target * MINUTE, NOW - 1,
                           now_ms=NOW)
    assert requests == []
    assert budget.report()['used'] == 300


def test_available_overlap_capacity_still_checks_conflicting_completed_bar():
    symbol = SYMBOLS[0]

    def conflicting_rows(req):
        return [raw_candle(symbol, minute, close=101 if minute == req['endTime'] // MINUTE else 100)
                for minute in range(req['startTime'] // MINUTE,
                                    req['endTime'] // MINUTE + 1)]

    budget, requests, engine, market, target = scanner(symbol, rest_rows=conflicting_rows)
    with pytest.raises(ExchangeError, match='CONFLICTING_COMPLETED_CANDLES'):
        market.get_candles(symbol, target * MINUTE, NOW - 1,
                           now_ms=NOW)
    assert len(requests) == 1
    assert (requests[0]['endTime'] - requests[0]['startTime']) // MINUTE + 1 == 2
    assert engine.scanner_errors[symbol] == 'CONFLICTING_COMPLETED_CANDLES'
    assert budget.report()['used'] == 2


def test_incomplete_rest_response_does_not_fabricate_the_missing_minute():
    symbol = SYMBOLS[0]
    budget, requests, engine, market, target = scanner(symbol, rest_rows=lambda req: [])
    with pytest.raises(ExchangeError, match='PAS_SCANNER_WINDOW_INCOMPLETE'):
        market.get_candles(symbol, target * MINUTE, NOW - 1,
                           now_ms=NOW)
    assert len(requests) == 1
    assert target * MINUTE not in engine.candles[symbol]
    assert budget.report()['used'] == 2
