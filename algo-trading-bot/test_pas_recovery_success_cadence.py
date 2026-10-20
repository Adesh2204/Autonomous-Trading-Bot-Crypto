"""Offline PAS scheduling regressions; no synthetic runtime candles or signing."""
from decimal import Decimal

import pytest

from exchange.base_exchange import BookLevel, ExchangeError, OrderBook
from test_pas_stream_warmup import MINUTE, NOW, SYMBOLS, candle, setup_engine


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests
    import websocket
    def reject(*args, **kwargs):
        raise AssertionError('PAS_RECOVERY_TEST_NETWORK_FORBIDDEN')
    monkeypatch.setattr(requests.Session, 'request', reject)
    monkeypatch.setattr(websocket, 'create_connection', reject)


def recovery_engine(symbol, *, complete=True):
    # A genuine-source fixture tail is already 115 seconds old. A successful
    # repair must not retain a prior 120-second failure delay.
    client, engine, _ = setup_engine(now=NOW + 55_000)
    engine.market.get_asset_contexts = lambda: {
        s: dict(markPx='100', oraclePx='100', funding='0') for s in SYMBOLS}
    engine.market.get_orderbook = lambda s: OrderBook(
        s, client.now, (BookLevel(Decimal('99.99'), Decimal('5')),),
        (BookLevel(Decimal('100.01'), Decimal('5')),))
    engine.market.get_candles = lambda *args, **kwargs: []
    if complete:
        for minute in range(NOW // MINUTE - 301, NOW // MINUTE - 1):
            bar = candle(symbol, minute, received=(minute + 1) * MINUTE)
            engine.candles[symbol][bar.timestamp_ms] = bar
    engine.health_manager.records[symbol]['consecutive_recovery_attempts'] = 2
    return client, engine


@pytest.mark.parametrize('symbol', SYMBOLS)
@pytest.mark.parametrize('hint,expected_delay', [(None, 30_000), (45_000, 45_000)])
def test_success_rebases_failure_backoff_but_preserves_adaptive_floor(symbol, hint, expected_delay):
    client, engine = recovery_engine(symbol)
    engine.availability.retry_hint_ms = lambda _: hint
    original = dict(engine.candles[symbol])
    engine.reconcile_history(symbols=[symbol])
    record = engine.health_manager.records[symbol]
    assert record['healthy']
    assert record['consecutive_recovery_attempts'] == 0
    assert record['next_retry_at_ms'] == client.now + expected_delay
    assert engine.candles[symbol] == original  # Empty REST cannot create a bar.
    # Only the 120s freshness gate changes health; books/context remain fresh.
    client.now += expected_delay
    engine.books[symbol] = engine.market.get_orderbook(symbol)
    engine.context_times[symbol] = client.now
    health = engine.market_health()[symbol]
    assert not health['healthy']
    assert 'LAST_CANDLE_TIME_STALE' in health['reasons']
    assert symbol in engine.health_manager.due(client.now)
    assert len(engine.get_completed_candles(symbol)) == 300
    assert engine.candles[symbol] == original


@pytest.mark.parametrize('symbol', SYMBOLS)
def test_failed_quota_deadline_remains_authoritative_without_fabrication(symbol):
    client, engine = recovery_engine(symbol, complete=False)
    def quota(*args, **kwargs):
        error = ExchangeError('PAS_CANDLE_MARKET_SHARE_EXHAUSTED')
        error.retry_after_ms = 50_000
        raise error
    engine.market.get_candles = quota
    engine.reconcile_history(symbols=[symbol])
    record = engine.health_manager.records[symbol]
    assert not record['healthy']
    assert record['next_retry_at_ms'] == client.now + 50_000
    assert symbol not in engine.health_manager.due(client.now + 49_999)
    assert symbol in engine.health_manager.due(client.now + 50_000)
    assert not engine.get_completed_candles(symbol)


@pytest.mark.parametrize('symbol', SYMBOLS)
def test_incomplete_history_retains_failure_backoff_and_300_bar_gate(symbol):
    client, engine = recovery_engine(symbol, complete=False)
    engine.reconcile_history(symbols=[symbol])
    record = engine.health_manager.records[symbol]
    assert not record['healthy']
    assert 'INSUFFICIENT_COMPLETED_HISTORY' in record['reasons']
    assert record['next_retry_at_ms'] == client.now + 120_000
    assert not engine.get_completed_candles(symbol)
