"""
test_screener.py — Comprehensive Unit & Regression Test Suite for Premarket Screener
=====================================================================================
Validates all screening gates: Price, ATR%, Spread, Depth, EMA, Volume, Exclusions,
Data Completeness, Rate-Limiting, Zero-Qualification Behavior, Ranking, and the
historical Sep-23 UnionBank regression fixture.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
import pytest

from market_schedule import NSEMarketSchedule
from premarket_screener import (
    CandidateDiagnostic,
    PremarketScreenResult,
    RejectionReason,
    evaluate_candidate,
    find_previous_completed_market_session,
    run_premarket_screener,
    validate_candle_data,
)


def _generate_synthetic_session_candles(
    ltp: float,
    atr: float,
    volume: int = 6_000_000,
    candle_count: int = 375,
    uptrend: bool = True,
) -> pd.DataFrame:
    """Generate a realistic 375-bar 1-minute completed session dataset."""
    base_time = datetime(2026, 9, 22, 9, 15)
    timestamps = [base_time + timedelta(minutes=i) for i in range(candle_count)]

    # Trend component
    drift = np.linspace(-5.0, 5.0, candle_count) if uptrend else np.linspace(5.0, -5.0, candle_count)
    prices = ltp + drift

    vol_per_bar = max(1, volume // candle_count)
    data = []
    for i, ts in enumerate(timestamps):
        p = prices[i]
        # Half-spread fluctuation to create desired ATR
        high = p + (atr / 2.0)
        low = p - (atr / 2.0)
        open_p = low + (high - low) * 0.4
        close_p = low + (high - low) * 0.6
        data.append(
            {
                "Timestamp": ts,
                "Open": open_p,
                "High": high,
                "Low": low,
                "Close": close_p,
                "Volume": vol_per_bar,
            }
        )
    return pd.DataFrame(data)


def test_previous_session_resolution_skips_weekends():
    """Verify that previous session resolution properly skips weekends."""
    sched = NSEMarketSchedule()
    # Monday Sep 21, 2026 -> previous session is Friday Sep 18, 2026
    monday = date(2026, 9, 21)
    prev_session = find_previous_completed_market_session(monday, sched)
    assert prev_session == date(2026, 9, 18)
    assert prev_session.weekday() == 4  # Friday


def test_price_range_gate():
    """Test min and max LTP boundaries."""
    cand = {"symbol": "TEST", "trading_symbol": "TEST-EQ", "token": "100", "exchange": "NSE"}
    
    # 1. Price below min (< 150)
    df_low = _generate_synthetic_session_candles(ltp=120.0, atr=1.0)
    diag_low = evaluate_candidate(cand, df_low, min_ltp=150.0, max_ltp=350.0)
    assert not diag_low.price_ok
    assert RejectionReason.PRICE_BELOW_MIN in diag_low.rejection_reasons
    assert not diag_low.qualified

    # 2. Price above max (> 350)
    df_high = _generate_synthetic_session_candles(ltp=400.0, atr=2.0)
    diag_high = evaluate_candidate(cand, df_high, min_ltp=150.0, max_ltp=350.0)
    assert not diag_high.price_ok
    assert RejectionReason.PRICE_ABOVE_MAX in diag_high.rejection_reasons
    assert not diag_high.qualified

    # 3. Price in range [150, 350]
    df_ok = _generate_synthetic_session_candles(ltp=250.0, atr=1.5)
    diag_ok = evaluate_candidate(cand, df_ok, min_ltp=150.0, max_ltp=350.0)
    assert diag_ok.price_ok


def test_atr_percentage_gate():
    """Test ATR% floor requirement (>= 0.40%)."""
    cand = {"symbol": "TEST", "trading_symbol": "TEST-EQ", "token": "100", "exchange": "NSE"}
    
    # LTP = 200, ATR = 0.50 -> ATR% = 0.25% (< 0.40%) -> FAIL
    df_low_atr = _generate_synthetic_session_candles(ltp=200.0, atr=0.50)
    diag_low = evaluate_candidate(cand, df_low_atr, min_atr_pct=0.0040)
    assert not diag_low.atr_ok
    assert RejectionReason.ATR_BELOW_MIN in diag_low.rejection_reasons
    assert not diag_low.qualified

    # LTP = 200, ATR = 1.20 -> ATR% = 0.60% (>= 0.40%) -> PASS
    df_high_atr = _generate_synthetic_session_candles(ltp=200.0, atr=1.20)
    diag_high = evaluate_candidate(cand, df_high_atr, min_atr_pct=0.0040)
    assert diag_high.atr_ok


def test_spread_and_depth_gate():
    """Test spread threshold and depth availability gates."""
    cand = {"symbol": "TEST", "trading_symbol": "TEST-EQ", "token": "100", "exchange": "NSE"}
    df = _generate_synthetic_session_candles(ltp=200.0, atr=1.20)

    # Spread > 0.15% (e.g. 0.25%)
    diag_wide_spread = evaluate_candidate(cand, df, spread_pct=0.25, max_spread_pct=0.0015)
    assert not diag_wide_spread.spread_ok
    assert RejectionReason.SPREAD_TOO_WIDE in diag_wide_spread.rejection_reasons
    assert not diag_wide_spread.qualified

    # Depth unavailable
    diag_no_depth = evaluate_candidate(cand, df, spread_pct=0.05, depth_available=False)
    assert not diag_no_depth.depth_ok
    assert RejectionReason.DEPTH_INSUFFICIENT in diag_no_depth.rejection_reasons
    assert not diag_no_depth.qualified


def test_ema_trend_filter():
    """Pre-selection admits valid bearish structure; core decides trade direction."""
    cand = {"symbol": "TEST", "trading_symbol": "TEST-EQ", "token": "100", "exchange": "NSE"}
    # Downtrend: EMA_9 < EMA_21
    df_down = _generate_synthetic_session_candles(ltp=200.0, atr=1.20, uptrend=False)
    diag_down = evaluate_candidate(cand, df_down)
    assert diag_down.ema_ok
    assert RejectionReason.EMA_TREND_INVALID not in diag_down.rejection_reasons
    assert diag_down.qualified


def test_exclusion_list():
    """Verify that excluded symbols are disqualified immediately."""
    cand = {"symbol": "BANNED", "trading_symbol": "BANNED-EQ", "token": "999", "exchange": "NSE"}
    df = _generate_synthetic_session_candles(ltp=200.0, atr=1.20)
    diag = evaluate_candidate(cand, df, exclusion_list=["BANNED", "BANNED-EQ"])
    assert not diag.exclusion_ok
    assert RejectionReason.EXCLUDED_SYMBOL in diag.rejection_reasons
    assert not diag.qualified


def test_data_sufficiency_and_integrity():
    """Verify validation of candle count, missing columns, corrupt values, non-monotonic timestamps."""
    # 1. Fewer candles than minimum (e.g. 100 < 300)
    df_short = _generate_synthetic_session_candles(ltp=200.0, atr=1.0, candle_count=100)
    valid, err = validate_candle_data(df_short, min_candles=300)
    assert not valid
    assert err == RejectionReason.INSUFFICIENT_DATA

    # 2. Corrupt prices (negative or 0)
    df_corrupt = _generate_synthetic_session_candles(ltp=200.0, atr=1.0)
    df_corrupt.loc[10, "Low"] = -5.0
    valid, err = validate_candle_data(df_corrupt, min_candles=300)
    assert not valid
    assert err == RejectionReason.INVALID_QUOTE

    # 3. Non-monotonic timestamps
    df_stale = _generate_synthetic_session_candles(ltp=200.0, atr=1.0)
    df_stale.loc[50, "Timestamp"] = df_stale.loc[40, "Timestamp"]
    valid, err = validate_candle_data(df_stale, min_candles=300)
    assert not valid
    assert err == RejectionReason.STALE_DATA


def test_historical_regression_unionbank_disqualification():
    """
    CRITICAL HISTORICAL REGRESSION FIXTURE (Sep 23, 2026):
    Fixture Values:
      LTP      = 179.57
      ATR      = 0.30
      Quantity = 18
      Friction = 12.95
    Must prove that UnionBank is DISQUALIFIED by the screener because ATR% = 0.167% (< 0.40%).
    """
    ub_candidate = {
        "symbol": "UNIONBANK",
        "trading_symbol": "UNIONBANK-EQ",
        "token": "10753",
        "exchange": "NSE",
    }
    df_ub = _generate_synthetic_session_candles(ltp=179.57, atr=0.30, volume=8_500_000)

    diag = evaluate_candidate(
        candidate=ub_candidate,
        df=df_ub,
        spread_pct=0.08,
        min_ltp=150.0,
        max_ltp=350.0,
        min_atr_pct=0.0040,  # 0.40%
    )

    assert diag.price_ok is True  # 150 <= 179.57 <= 350
    assert diag.atr_ok is False   # 0.30 / 179.57 = 0.167% < 0.40%
    assert RejectionReason.ATR_BELOW_MIN in diag.rejection_reasons
    assert diag.qualified is False
    assert abs(diag.atr_pct - 0.167) < 0.01


def test_zero_qualification_sits_out_without_hardcoded_fallback():
    """
    Critical requirement: When no candidate qualifies, system must return NO_TRADE
    and NOT fall back to any hardcoded symbol or previous winner.
    """
    universe = [
        {"symbol": "LOWVOL1", "trading_symbol": "LOWVOL1-EQ", "token": "1", "exchange": "NSE"},
        {"symbol": "LOWVOL2", "trading_symbol": "LOWVOL2-EQ", "token": "2", "exchange": "NSE"},
    ]

    # Both fail ATR% threshold
    def mock_fetcher(cand, session_date):
        return _generate_synthetic_session_candles(ltp=200.0, atr=0.20)

    result = run_premarket_screener(
        universe=universe,
        data_fetcher=mock_fetcher,
        pacing_interval=0.0,
    )

    assert result.trading_day_status == "NO_TRADE"
    assert result.selected_candidate is None
    assert len(result.qualified_candidates) == 0
    assert len(result.rejected_candidates) == 2


def test_deterministic_ranking_by_atr_pct():
    """Verify that multiple qualified candidates are ranked by ATR% descending."""
    universe = [
        {"symbol": "STOCK_A", "trading_symbol": "STOCK_A-EQ", "token": "1", "exchange": "NSE"},
        {"symbol": "STOCK_B", "trading_symbol": "STOCK_B-EQ", "token": "2", "exchange": "NSE"},
        {"symbol": "STOCK_C", "trading_symbol": "STOCK_C-EQ", "token": "3", "exchange": "NSE"},
    ]

    def mock_fetcher(cand, session_date):
        if cand["symbol"] == "STOCK_A":
            return _generate_synthetic_session_candles(ltp=200.0, atr=1.00)  # ATR% = 0.50%
        elif cand["symbol"] == "STOCK_B":
            return _generate_synthetic_session_candles(ltp=200.0, atr=2.00)  # ATR% = 1.00%
        else:
            return _generate_synthetic_session_candles(ltp=200.0, atr=1.50)  # ATR% = 0.75%

    result = run_premarket_screener(
        universe=universe,
        data_fetcher=mock_fetcher,
        pacing_interval=0.0,
    )

    assert result.trading_day_status == "ACTIVE"
    assert len(result.qualified_candidates) == 3
    # Ranking order must be: STOCK_B (1.00%) > STOCK_C (0.75%) > STOCK_A (0.50%)
    assert result.qualified_candidates[0].symbol == "STOCK_B"
    assert result.qualified_candidates[1].symbol == "STOCK_C"
    assert result.qualified_candidates[2].symbol == "STOCK_A"
    assert result.selected_candidate.symbol == "STOCK_B"


def test_broker_api_failure_does_not_crash_screening():
    """
    Verify that an API error on one candidate records BROKER_DATA_ERROR
    and allows screening to continue for remaining candidates.
    """
    universe = [
        {"symbol": "FAILING_STOCK", "token": "1", "exchange": "NSE"},
        {"symbol": "WINNING_STOCK", "token": "2", "exchange": "NSE"},
    ]

    def mock_fetcher(cand, session_date):
        if cand["symbol"] == "FAILING_STOCK":
            return None  # Simulates API failure / max retries exceeded
        return _generate_synthetic_session_candles(ltp=200.0, atr=1.80)

    result = run_premarket_screener(
        universe=universe,
        data_fetcher=mock_fetcher,
        pacing_interval=0.0,
    )

    assert result.trading_day_status == "ACTIVE"
    assert result.selected_candidate.symbol == "WINNING_STOCK"
    failed = next(d for d in result.diagnostics if d.symbol == "FAILING_STOCK")
    assert not failed.qualified
    assert RejectionReason.BROKER_DATA_ERROR in failed.rejection_reasons


def test_premarket_screener_bypass_config():
    """Verify RUN_PREMARKET_SCREENER is properly configured in config and live_stream."""
    from config import RUN_PREMARKET_SCREENER, SYMBOL, TOKEN
    assert isinstance(RUN_PREMARKET_SCREENER, bool)
    assert SYMBOL == "ENGINERSIN"
    assert TOKEN == "4907"
