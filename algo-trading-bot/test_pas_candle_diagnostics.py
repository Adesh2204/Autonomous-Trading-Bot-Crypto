"""Data readiness is not trading authorization; all inputs are offline fixtures."""
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_pas_candles import candle_status, REQUIRED_BARS
from exchange.base_exchange import Candle

NOW = 1800000000000
START = NOW - 300 * 60000


def bars(symbol='pas:BTC', count=300):
    return [Candle(symbol, '1m', t, t + 59999,
                   Decimal(100), Decimal(101), Decimal(99), Decimal(100), Decimal(1),
                   received_timestamp_ms=t + 60000)
            for t in range(START, START + count * 60000, 60000)]


@pytest.mark.parametrize('symbol', ['pas:BTC', 'pas:EWY'])
def test_exact_300_real_completed_bars_pass_only_data_gate(symbol):
    result = candle_status(symbol, bars(symbol), NOW, START, NOW - 1)
    assert REQUIRED_BARS == 300
    assert result['data_gate_passed']
    assert result['completed_bars'] == result['consecutive_tail_bars'] == 300
    assert result['missing_bars'] == 0
    assert result['last_close_age_ms'] == 0


@pytest.mark.parametrize('count', [0, 1, 53, 299])
def test_short_history_is_never_ready(count):
    result = candle_status('pas:BTC', bars(count=count), NOW, START, NOW - 1)
    assert not result['data_gate_passed']
    assert 'INSUFFICIENT_COMPLETED_HISTORY' in result['reasons']
    assert result['missing_bars'] == 300 - count
    if count == 0:
        assert result['last_start_ms'] is None
        assert result['consecutive'] is False


def test_300_nonconsecutive_bars_fail_closed():
    rows = bars()
    rows[140] = rows[139]
    result = candle_status('pas:BTC', rows, NOW, START, NOW - 1)
    assert not result['data_gate_passed']
    assert 'STRATEGY_CANDLE_GAP_OR_DUPLICATE' in result['reasons']
    assert result['consecutive_tail_bars'] == len(rows[141:])


def test_stale_complete_history_does_not_pass():
    result = candle_status('pas:BTC', bars(), NOW + 120001, START, NOW - 1)
    assert not result['data_gate_passed']
    assert result['last_close_age_ms'] == 120001


def test_open_bar_is_not_completed_history():
    result = candle_status('pas:BTC', bars(), NOW - 1, START, NOW - 1)
    assert not result['data_gate_passed']
    assert 'FUTURE_OR_OPEN_COMPLETED_CANDLE' in result['reasons']


def test_other_asset_candles_cannot_satisfy_btc_warmup():
    result = candle_status('pas:BTC', bars('pas:EWY'), NOW, START, NOW - 1)
    assert not result['data_gate_passed']
    assert 'STRATEGY_CANDLE_IDENTITY_MISMATCH' in result['reasons']


def test_data_only_check_waits_for_shared_budget_but_never_certifies_live(monkeypatch):
    import check_pas_candles as diagnostic
    from types import SimpleNamespace
    from exchange.base_exchange import ExchangeError
    clock = [NOW]
    calls = []
    waits = []
    client = SimpleNamespace(startup=lambda: None, competition_mode=True, api_dex='pas',
        api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'}, collateral_token_name='USDP',
        market_mapping={'verification': 'OFFLINE_FIXTURE'}, clock_ms=lambda: clock[0])
    class Market:
        def __init__(self, _client): pass
        def get_candles(self, symbol, start, end, **_kwargs):
            calls.append(symbol)
            if symbol == 'pas:EWY' and calls.count(symbol) == 1:
                error = ExchangeError('PAS_CANDLE_BUDGET_EXHAUSTED')
                error.retry_after_ms = 60000
                raise error
            return [Candle(symbol, '1m', t, t + 59999, Decimal(100), Decimal(101),
                           Decimal(99), Decimal(100), Decimal(1), received_timestamp_ms=t+60000)
                    for t in range(start, end+1, 60000)]
    def wait(seconds):
        waits.append(seconds)
        clock[0] += round(seconds * 1000)
    monkeypatch.setattr(diagnostic, 'HyperliquidMarketData', Market)
    result = diagnostic.check(client, sleep=wait)
    assert calls == ['pas:BTC', 'pas:EWY', 'pas:EWY']
    assert len(waits) == 1 and waits[0] <= 61
    assert result['data_gate_passed']
    assert result['status'] == 'DATA_ONLY_PASS_NOT_LIVE_CERTIFIED'
    assert result['live_ready'] is False
    assert result['funding_verified'] is False
    assert result['wallet_or_signer_certified'] is False
    assert result['orders_submitted'] == 0


def test_budget_failure_reports_both_assets_without_claiming_missing_bars_ready(monkeypatch):
    import check_pas_candles as diagnostic
    from types import SimpleNamespace
    from exchange.base_exchange import ExchangeError
    client = SimpleNamespace(startup=lambda: None, competition_mode=True, api_dex='pas',
        api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'}, collateral_token_name='USDP',
        market_mapping={}, clock_ms=lambda: NOW)
    class Market:
        def __init__(self, _client): pass
        def get_candles(self, *_args, **_kwargs):
            raise ExchangeError('PAS_CANDLE_BUDGET_EXHAUSTED')
    monkeypatch.setattr(diagnostic, 'HyperliquidMarketData', Market)
    result = diagnostic.check(client, wait_for_budget=False)
    assert set(result['markets']) == {'pas:BTC', 'pas:EWY'}
    assert result['data_gate_passed'] is False and result['live_ready'] is False
    assert all(v['completed_bars'] is None for v in result['markets'].values())
