"""Interval-aware strategy bars: 1m behaviour unchanged, 1h accepted end to end."""
from decimal import Decimal as D

import pytest

from candle_normalizer import candles_to_frame
from crypto_strategy_state import CryptoStrategyState
from exchange.base_exchange import Candle, ExchangeError
from exchange.market_health import bar_step, validate_history
from market_regime_scanner import ScannerPolicy

H = 3600000
T0 = 1792800000000 // H * H


def bar(t, interval='1h', symbol='pas:BTC', price='100'):
    step = {'1m': 60000, '1h': H}[interval]
    return Candle(symbol, interval, t, t + step - 1, D(price), D(price), D(price), D(price), D(1))


def test_scanner_policy_defaults_to_one_minute_and_validates_hourly():
    assert ScannerPolicy(D('.004'), D(15), D(0), D(10)).bar_interval == '1m'
    ScannerPolicy(D('.004'), D(15), D(0), D(10), bar_interval='1h', strategy_history_bars=48)
    for bad in (dict(bar_interval='1h'), dict(bar_interval='5m', strategy_history_bars=48),
                dict(strategy_history_bars=48), dict(bar_interval='1h', strategy_history_bars=10)):
        with pytest.raises(ExchangeError, match='INVALID_SCANNER_POLICY'):
            ScannerPolicy(D('.004'), D(15), D(0), D(10), **bad)


def test_normalizer_and_history_accept_contiguous_hourly_bars():
    bars = [bar(T0 + i * H) for i in range(48)]
    assert len(candles_to_frame(bars)) == 48
    validate_history('pas:BTC', bars, T0 + 48 * H, 48)
    assert bar_step(bars) == H and bar_step([]) == 60000


@pytest.mark.parametrize('bars,code', [
    ([bar(T0), bar(T0 + 2 * H)], 'STRATEGY_CANDLE_GAP_OR_DUPLICATE'),
    ([bar(T0), bar(T0 + H, interval='1m')], 'STRATEGY_CANDLE_IDENTITY_MISMATCH'),
])
def test_hourly_gaps_and_mixed_intervals_rejected(bars, code):
    with pytest.raises(ExchangeError, match=code):
        candles_to_frame(bars)
    with pytest.raises(ExchangeError, match=code):
        validate_history('pas:BTC', bars, T0 + 10 * H, 1)


def test_open_hourly_bar_is_not_completed():
    with pytest.raises(ExchangeError, match='FUTURE_OR_OPEN_COMPLETED_CANDLE'):
        validate_history('pas:BTC', [bar(T0)], T0 + H - 1, 1)


def test_strategy_state_uses_hourly_step():
    state = CryptoStrategyState('pas:BTC', lambda *a: None, clock_ms=lambda: T0 + 10 * H)
    state.completed_candle(bar(T0))
    state.completed_candle(bar(T0 + H))
    with pytest.raises(ExchangeError, match='STRATEGY_STATE_CANDLE_GAP'):
        state.completed_candle(bar(T0 + 3 * H))
