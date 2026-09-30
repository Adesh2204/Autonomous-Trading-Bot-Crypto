"""
test_phase5_multisymbol.py — Comprehensive Test Suite for Phase 5 Multi-Symbol Infrastructure
=============================================================================================
Mandatory Verification Suite for:
1. test_screener_top_n_selection: Top-N watchlist selection with preserved ranking.
2. test_screener_zero_qualification_sit_out: Fail-safe zero-qualification sit-out rule.
3. test_symbol_state_tick_demultiplexing_isolation: Strict per-symbol tick and state isolation.
4. test_dynamic_standby_swapping: ATR collapse moves Symbol 1 to STANDBY while Symbol 2 executes.
5. test_global_position_limit_enforced: Global MAX_OPEN_POSITIONS = 1 blocks subsequent symbols.
6. test_signal_brain_diff_is_empty: Cryptographic verification of signal_brain.py immutability.
7. Additional regression tests:
   - Hysteresis recovery from STANDBY to ACTIVE
   - Failure containment (error on Symbol A does not crash B & C)
   - Multi-token WebSocket subscription & reconnect restoration
   - One-cycle execution precedence rule
"""

from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from candle_builder import CandleBuilder
from config import (
    MAX_OPEN_POSITIONS,
    SCREEN_TOP_N,
    STANDBY_ATR_THRESHOLD,
    STANDBY_CONFIRMATION_COUNT,
    STANDBY_RECOVERY_CONFIRMATION_COUNT,
    STANDBY_RECOVERY_THRESHOLD,
)
from feed_integrity import FeedHealthMonitor, FeedHealthState, RawTick, ThreadSafeTickIngestionQueue
from live_stream import AngelOneLiveStream
from market_schedule import NSEMarketSchedule, to_ist
from premarket_screener import (
    CandidateDiagnostic,
    PremarketScreenResult,
    run_premarket_screener,
)
from symbol_state import (
    SymbolExecutionState,
    SymbolState,
    create_isolated_symbol_state,
)


@pytest.fixture(autouse=True)
def isolated_execution_environment(monkeypatch):
    import config
    monkeypatch.setattr(config,'LIVE_MODE',False)
    monkeypatch.setattr(config,'EXECUTION_ENVIRONMENT','TEST')


def _verified_test_stream(candidates):
    from instrument_registry import InstrumentRegistry
    now=to_ist()
    records=[{'exch_seg':'NSE','symbol':c.trading_symbol,'token':c.token,'tick_size':'5','lotsize':'1'} for c in candidates]
    registry=InstrumentRegistry(records,now,[c.symbol for c in candidates])
    return AngelOneLiveStream(watchlist=candidates,registry=registry)


# ─────────────────────────────────────────────────────────────────────────────
# Helper Fixtures & Synthetic Generators
# ─────────────────────────────────────────────────────────────────────────────

def _make_candidate_diagnostic(
    symbol: str,
    token: str,
    atr_pct: float,
    ltp: float = 200.0,
    qualified: bool = True,
    rank: int = 1,
) -> CandidateDiagnostic:
    atr = (atr_pct / 100.0) * ltp
    return CandidateDiagnostic(
        symbol=symbol,
        trading_symbol=f"{symbol}-EQ",
        token=token,
        exchange="NSE",
        ltp=ltp,
        atr=atr,
        atr_pct=atr_pct,
        spread_pct=0.05,
        depth_status="AVAILABLE",
        ema_fast=ltp + 1.0,
        ema_slow=ltp - 1.0,
        trend="UPTREND",
        total_volume=10_000_000,
        candle_count=375,
        price_ok=True,
        atr_ok=qualified,
        spread_ok=True,
        depth_ok=True,
        ema_ok=True,
        volume_ok=True,
        exclusion_ok=True,
        data_ok=True,
        qualified=qualified,
        rejection_reasons=[] if qualified else ["ATR_BELOW_MIN"],
    )


def _generate_synthetic_candle_df(
    symbol: str,
    base_price: float = 100.0,
    atr: float = 3.0,
    n_candles: int = 15,
    trigger_signal: str = "PULLBACK_LONG",
) -> pd.DataFrame:
    """Generate a 15-candle DataFrame that triggers a verified VWAP Pullback BUY signal."""
    dates = [to_ist(datetime(2026, 9, 23, 10, i)) for i in range(15)]
    open_prices = [base_price + i * 2.0 for i in range(15)]
    high_prices = [p + 2.0 for p in open_prices]
    low_prices = [p - 0.5 for p in open_prices]
    close_prices = [p + 1.5 for p in open_prices]

    if trigger_signal == "PULLBACK_LONG":
        open_prices[14] = base_price + 18.0
        high_prices[14] = base_price + 19.0
        low_prices[14] = base_price + 14.0   # Dips below / tests VWAP (~114.15)
        close_prices[14] = base_price + 16.0 # Rebounds and closes above VWAP

    df = pd.DataFrame({
        "Timestamp": dates,
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": [1000] * 15,
    })
    return df



# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Test 1: Top-N Screener Selection
# ─────────────────────────────────────────────────────────────────────────────

def test_screener_top_n_selection():
    """
    Test 1: Verify pre-market screener selects top-3 ranked candidates.
    Ranking order must be strictly preserved: Rank 1 -> Rank 2 -> Rank 3.
    selected_candidate must equal watchlist[0] for backward compatibility.
    """
    # 15 synthetic candidates with distinct ATR%
    mock_universe = []
    for i in range(15):
        sym = f"SYM{i+1}"
        tok = str(1000 + i)
        mock_universe.append(
            {"symbol": sym, "trading_symbol": f"{sym}-EQ", "token": tok, "exchange": "NSE"}
        )

    # Return valid candles with descending ATR% for each candidate
    def _mock_fetcher(cand: dict, session_date: date) -> pd.DataFrame:
        idx = int(cand["token"]) - 1000
        # ATR% ranges from 0.80% down to 0.45% (all qualified)
        atr_pct = 0.80 - (idx * 0.02)
        base_time = datetime(2026, 9, 22, 9, 15)
        n_bars = 350
        rows = []
        ltp = 200.0
        atr = (atr_pct / 100.0) * ltp
        for b in range(n_bars):
            rows.append(
                {
                    "Timestamp": base_time + timedelta(minutes=b),
                    "Open": ltp,
                    "High": ltp + (atr / 2.0),
                    "Low": ltp - (atr / 2.0),
                    "Close": ltp + 0.1,
                    "Volume": 20000,
                }
            )
        return pd.DataFrame(rows)

    result = run_premarket_screener(
        universe=mock_universe,
        session_date=date(2026, 9, 22),
        top_n=3,
        data_fetcher=_mock_fetcher,
        pacing_interval=0.0,
    )

    assert result.trading_day_status == "ACTIVE"
    assert len(result.qualified_candidates) == 15
    assert len(result.watchlist) == 3
    assert result.selected_candidate == result.watchlist[0]

    # Verify ranking order: strictly descending by ATR%
    assert result.watchlist[0].atr_pct > result.watchlist[1].atr_pct
    assert result.watchlist[1].atr_pct > result.watchlist[2].atr_pct
    assert result.watchlist[0].symbol == "SYM1"
    assert result.watchlist[1].symbol == "SYM2"
    assert result.watchlist[2].symbol == "SYM3"


# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Test 2: Zero Qualification Sit-Out
# ─────────────────────────────────────────────────────────────────────────────

def test_screener_zero_qualification_sit_out():
    """
    Test 2: When 0 candidates qualify, screener must return:
    watchlist == [], selected_candidate is None, trading_day_status == 'NO_TRADE'.
    Zero fallback to arbitrary symbols.
    """
    mock_universe = [
        {"symbol": "SYM1", "trading_symbol": "SYM1-EQ", "token": "1001", "exchange": "NSE"},
        {"symbol": "SYM2", "trading_symbol": "SYM2-EQ", "token": "1002", "exchange": "NSE"},
    ]

    # All candidates return compressed volatility (0.10% ATR% << 0.40% minimum)
    def _mock_compressed_fetcher(cand: dict, session_date: date) -> pd.DataFrame:
        base_time = datetime(2026, 9, 22, 9, 15)
        n_bars = 350
        ltp = 200.0
        atr = 0.20  # 0.10% of 200
        rows = [
            {
                "Timestamp": base_time + timedelta(minutes=b),
                "Open": ltp,
                "High": ltp + (atr / 2.0),
                "Low": ltp - (atr / 2.0),
                "Close": ltp,
                "Volume": 20000,
            }
            for b in range(n_bars)
        ]
        return pd.DataFrame(rows)

    result = run_premarket_screener(
        universe=mock_universe,
        session_date=date(2026, 9, 22),
        top_n=3,
        data_fetcher=_mock_compressed_fetcher,
        pacing_interval=0.0,
    )

    assert result.trading_day_status == "NO_TRADE"
    assert len(result.qualified_candidates) == 0
    assert result.watchlist == []
    assert result.selected_candidate is None


# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Test 3: Tick Demultiplexing & State Isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_symbol_state_tick_demultiplexing_isolation():
    """
    Test 3: Inject interleaved ticks for TATASTEEL, ONGC, and BANKBARODA.
    Verify each symbol's CandleBuilder and FeedHealthMonitor receive ONLY its own ticks.
    Zero cross-contamination of price, volume, timestamp, or feed state.
    """
    c1 = _make_candidate_diagnostic("TATASTEEL", "3499", atr_pct=0.60, rank=1)
    c2 = _make_candidate_diagnostic("ONGC", "2475", atr_pct=0.55, rank=2)
    c3 = _make_candidate_diagnostic("BANKBARODA", "4668", atr_pct=0.50, rank=3)

    received_candles = {"3499": [], "2475": [], "4668": []}

    def _on_close_cb(sym: str, tok: str, df: pd.DataFrame):
        received_candles[tok].append((sym, len(df), float(df.iloc[-1]["Close"])))

    s1 = create_isolated_symbol_state("TATASTEEL", "3499", "TATASTEEL-EQ", rank=1, candle_close_callback=_on_close_cb)
    s2 = create_isolated_symbol_state("ONGC", "2475", "ONGC-EQ", rank=2, candle_close_callback=_on_close_cb)
    s3 = create_isolated_symbol_state("BANKBARODA", "4668", "BANKBARODA-EQ", rank=3, candle_close_callback=_on_close_cb)

    active_symbols = {"3499": s1, "2475": s2, "4668": s3}

    # Interleaved ticks
    now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    tick_sequence = [
        ("3499", 150.0, 100, now),
        ("2475", 250.0, 200, now),
        ("4668", 220.0, 300, now),
        ("3499", 151.0, 150, now + timedelta(seconds=1)),
        ("4668", 221.0, 250, now + timedelta(seconds=1)),
        ("2475", 252.0, 180, now + timedelta(seconds=1)),
    ]

    for tok, price, vol, ts in tick_sequence:
        st = active_symbols[tok]
        tick = RawTick(
            sequence_id=1,
            symbol=st.symbol,
            token=tok,
            exchange_type=1,
            price=price,
            volume=vol,
            timestamp=ts,
            receipt_time=1.0,
        )
        is_gen, health, _ = st.feed_monitor.evaluate_tick(tick)
        assert is_gen is True
        st.builder.on_tick(price=price, volume=vol, timestamp=ts)

    # Assert builders have completely isolated volumes and prices
    assert s1.builder.current_candle["Volume"] == 250  # 100 + 150
    assert s1.builder.current_candle["Close"] == 151.0

    assert s2.builder.current_candle["Volume"] == 380  # 200 + 180
    assert s2.builder.current_candle["Close"] == 252.0

    assert s3.builder.current_candle["Volume"] == 550  # 300 + 250
    assert s3.builder.current_candle["Close"] == 221.0


    # Assert feed health monitors tracked their own isolated last price & volume
    assert s1.feed_monitor.last_price == 151.0
    assert s2.feed_monitor.last_price == 252.0
    assert s3.feed_monitor.last_price == 221.0


# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Test 4: Dynamic Standby Swapping
# ─────────────────────────────────────────────────────────────────────────────

def test_dynamic_standby_swapping():
    """
    Test 4: When Symbol 1's ATR collapses (e.g. 0.15% < STANDBY_ATR_THRESHOLD),
    it transitions to STANDBY.
    Symbol 2 (ATR 0.50%) remains ACTIVE and is eligible to execute trades.
    Symbol 1 in STANDBY does NOT block Symbol 2.
    """
    c1 = _make_candidate_diagnostic("SYM1", "1001", atr_pct=0.60, rank=1)
    c2 = _make_candidate_diagnostic("SYM2", "1002", atr_pct=0.50, rank=2)

    with patch.dict(
        "os.environ",
        {
            "BROKER_API_KEY": "dummy",
            "BROKER_CLIENT_ID": "dummy",
            "BROKER_PIN": "1234",
            "BROKER_TOTP_SECRET": "dummy",
        },
    ):
        stream = _verified_test_stream([c1, c2])

    s1 = stream.active_symbols["1001"]
    s2 = stream.active_symbols["1002"]

    assert s1.execution_state == SymbolExecutionState.ACTIVE
    assert s2.execution_state == SymbolExecutionState.ACTIVE

    now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)

    # Feed compressed ATR to Symbol 1 twice (STANDBY_CONFIRMATION_COUNT = 2)
    collapsed_atr = 0.30  # On LTP 200 -> 0.15% < 0.35% threshold
    s1.record_periodic_atr(atr=collapsed_atr, ltp=200.0, timestamp=now)
    assert s1.execution_state == SymbolExecutionState.ACTIVE  # 1st reading: pending confirmation
    s1.record_periodic_atr(atr=collapsed_atr, ltp=200.0, timestamp=now + timedelta(minutes=1))
    assert s1.execution_state == SymbolExecutionState.STANDBY  # 2nd reading: transitioned to STANDBY

    # Feed healthy ATR to Symbol 2 (0.50% > threshold)
    healthy_atr = 1.00  # On LTP 200 -> 0.50%
    s2.record_periodic_atr(atr=healthy_atr, ltp=200.0, timestamp=now)
    s2.record_periodic_atr(atr=healthy_atr, ltp=200.0, timestamp=now + timedelta(minutes=1))
    assert s2.execution_state == SymbolExecutionState.ACTIVE  # Symbol 2 remains fully ACTIVE

    # Provide synthetic candle DF with BUY signal for both symbols
    df1 = _generate_synthetic_candle_df("SYM1", base_price=200.0, atr=collapsed_atr)
    df2 = _generate_synthetic_candle_df("SYM2", base_price=200.0, atr=healthy_atr)
    s1.current_candle_df = df1
    s2.current_candle_df = df2
    s2.feed_monitor.state=FeedHealthState.HEALTHY
    from execution_safety import MarketQuote
    from signal_brain import generate_vwap_signal
    evaluation=to_ist(datetime(2026,9,23,10,15))
    observed=float(generate_vwap_signal(df2)['VWAP'].iloc[-1])+.1
    s2.quote=MarketQuote(observed-.05,observed+.05,10000,10000,evaluation,observed)
    s2.last_spread_pct=.05; s2.last_depth_available=True

    # Run orchestrator
    with patch.object(stream.paper_trader, "execute_trade") as mock_exec:
        eval_time = to_ist(datetime(2026, 9, 23, 10, 15))
        stream._evaluate_watchlist_orchestrator(evaluation_time=eval_time)
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0]['symbol']=='SYM2'

        # Symbol 1 was in STANDBY, so it was skipped.
        # If any trade was executed, it MUST be Symbol 2, NOT Symbol 1!
        for call in mock_exec.call_args_list:
            trade_payload = call[0][0]
            assert trade_payload["symbol"] != "SYM1", "Symbol 1 executed while in STANDBY!"


# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Test 5: Global Position Limit Enforced
# ─────────────────────────────────────────────────────────────────────────────

def test_global_position_limit_enforced():
    """
    Test 5: When Symbol 2 executes an order, the global position limit
    (MAX_OPEN_POSITIONS = 1) is occupied. Subsequent signal on Symbol 3 is blocked.
    """
    c1 = _make_candidate_diagnostic("SYM1", "1001", atr_pct=0.60, rank=1)
    c2 = _make_candidate_diagnostic("SYM2", "1002", atr_pct=0.55, rank=2)
    c3 = _make_candidate_diagnostic("SYM3", "1003", atr_pct=0.50, rank=3)

    with patch.dict(
        "os.environ",
        {
            "BROKER_API_KEY": "dummy",
            "BROKER_CLIENT_ID": "dummy",
            "BROKER_PIN": "1234",
            "BROKER_TOTP_SECRET": "dummy",
        },
    ):
        stream = _verified_test_stream([c1, c2, c3])

    s1 = stream.active_symbols["1001"]
    s2 = stream.active_symbols["1002"]
    s3 = stream.active_symbols["1003"]

    # Put Symbol 1 in STANDBY so orchestrator proceeds to Symbol 2
    s1.execution_state = SymbolExecutionState.STANDBY

    # Set feed monitors to HEALTHY
    s2.feed_monitor.state = FeedHealthState.HEALTHY
    s3.feed_monitor.state = FeedHealthState.HEALTHY

    now = to_ist(datetime(2026, 9, 23, 10, 0))
    s2.atr_firewall.record_periodic_atr(atr=3.0, ltp=116.0, timestamp=now)
    s3.atr_firewall.record_periodic_atr(atr=3.0, ltp=116.0, timestamp=now)

    # Both s2 and s3 have candle data that produces buy signals
    s2.current_candle_df = _generate_synthetic_candle_df("SYM2", base_price=100.0, atr=3.0)
    s3.current_candle_df = _generate_synthetic_candle_df("SYM3", base_price=100.0, atr=3.0)

    executed_trades = []

    def _mock_execute_trade(signal_data, **kwargs):
        executed_trades.append(signal_data["symbol"])
        # Simulate position becoming occupied
        stream.paper_trader._open_position = {
            "symbol": signal_data["symbol"],
            "token": signal_data['token'],
            "side": kwargs.get("side", "BUY"),
            "target_price": 210.0,
            "stop_loss_price": 195.0,
        }
        return {'quantity':1}

    eval_time = to_ist(datetime(2026, 9, 23, 10, 15))
    from execution_safety import MarketQuote
    from signal_brain import generate_vwap_signal
    for state in (s2,s3):
        observed=float(generate_vwap_signal(state.current_candle_df)['VWAP'].iloc[-1])+.1
        state.quote=MarketQuote(observed-.05,observed+.05,10000,10000,eval_time,observed)
        state.last_spread_pct=.09
        state.last_depth_available=True
    with patch.object(stream.paper_trader, "execute_trade", side_effect=_mock_execute_trade):
        stream._evaluate_watchlist_orchestrator(evaluation_time=eval_time)


        # Exactly 1 trade should execute across the entire watchlist
        assert len(executed_trades) == 1
        assert executed_trades[0] == "SYM2"
        assert stream.paper_trader.has_open_position is True

        # Now trigger orchestrator again: since position is occupied, Symbol 3 MUST be blocked!
        stream._evaluate_watchlist_orchestrator(evaluation_time=eval_time)
        assert len(executed_trades) == 1  # Still exactly 1 trade!



# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Test 6: Signal Brain Immutability
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_brain_diff_is_empty():
    """
    Test 6: Cryptographic / Git diff verification that signal_brain.py has 0 changes.
    git diff --exit-code -- algo-trading-bot/signal_brain.py must return exit code 0.
    """
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", "algo-trading-bot/signal_brain.py"],
        capture_output=True,
        text=True,
    )
    assert (
        result.returncode == 0
    ), f"CRITICAL: signal_brain.py was modified! Diff output:\n{result.stdout}"


# ─────────────────────────────────────────────────────────────────────────────
# Additional Regression Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_standby_hysteresis_recovery():
    """Verify hysteresis recovery from STANDBY back to ACTIVE requires confirmed healthy readings."""
    state = create_isolated_symbol_state("TEST", "9999", "TEST-EQ", rank=1)
    state.execution_state = SymbolExecutionState.STANDBY

    now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)

    # 1st healthy reading (ATR% 0.50% >= 0.40% threshold): still in STANDBY
    state.record_periodic_atr(atr=1.0, ltp=200.0, timestamp=now)
    assert state.execution_state == SymbolExecutionState.STANDBY
    assert state.standby_recovery_count == 1

    # 2nd healthy reading: recovers to ACTIVE
    state.record_periodic_atr(atr=1.0, ltp=200.0, timestamp=now + timedelta(minutes=1))
    assert state.execution_state == SymbolExecutionState.ACTIVE
    assert state.standby_recovery_count == 2


def test_failure_containment_isolated_error():
    """Verify that an exception in Symbol A does not disrupt Symbol B or crash the stream."""
    c1 = _make_candidate_diagnostic("SYM1", "1001", atr_pct=0.60, rank=1)
    c2 = _make_candidate_diagnostic("SYM2", "1002", atr_pct=0.55, rank=2)

    with patch.dict(
        "os.environ",
        {
            "BROKER_API_KEY": "dummy",
            "BROKER_CLIENT_ID": "dummy",
            "BROKER_PIN": "1234",
            "BROKER_TOTP_SECRET": "dummy",
        },
    ):
        stream = _verified_test_stream([c1, c2])

    s1 = stream.active_symbols["1001"]
    s2 = stream.active_symbols["1002"]

    s1.feed_monitor.state = FeedHealthState.HEALTHY
    s2.feed_monitor.state = FeedHealthState.HEALTHY

    # Invalidate Symbol 1 by setting a corrupted dataframe (missing required columns) that raises error during signal evaluation
    s1.current_candle_df = pd.DataFrame({"corrupt_column": range(20)})
    s2.current_candle_df = _generate_synthetic_candle_df("SYM2", base_price=100.0, atr=3.0)


    # Orchestrator should catch Symbol 1 exception, mark s1 ERROR, and continue to evaluate s2
    eval_time = to_ist(datetime(2026, 9, 23, 10, 15))
    stream._evaluate_watchlist_orchestrator(evaluation_time=eval_time)

    assert s1.execution_state == SymbolExecutionState.ERROR
    assert s2.execution_state == SymbolExecutionState.ACTIVE




def test_websocket_reconnect_restores_all_watchlist_tokens():
    """Verify that when WebSocket reconnects, subscription payload includes all watchlist tokens."""
    c1 = _make_candidate_diagnostic("TATASTEEL", "3499", atr_pct=0.60, rank=1)
    c2 = _make_candidate_diagnostic("ONGC", "2475", atr_pct=0.55, rank=2)
    c3 = _make_candidate_diagnostic("BANKBARODA", "4668", atr_pct=0.50, rank=3)

    with patch.dict(
        "os.environ",
        {
            "BROKER_API_KEY": "dummy",
            "BROKER_CLIENT_ID": "dummy",
            "BROKER_PIN": "1234",
            "BROKER_TOTP_SECRET": "dummy",
        },
    ):
        stream = _verified_test_stream([c1, c2, c3])

    mock_ws = MagicMock()
    stream.websocket = mock_ws

    # Trigger _on_open (reconnect simulation)
    stream._on_open(mock_ws)

    # Verify subscribe was called
    assert mock_ws.subscribe.called
    call_args = mock_ws.subscribe.call_args[0]
    token_list = call_args[2]

    # Extract all subscribed tokens
    subscribed_tokens = []
    for entry in token_list:
        subscribed_tokens.extend(entry["tokens"])

    assert "3499" in subscribed_tokens
    assert "2475" in subscribed_tokens
    assert "4668" in subscribed_tokens
    assert len(subscribed_tokens) == 3


def test_unknown_token_safely_ignored():
    """Verify that ticks with unregistered tokens are safely discarded without altering state."""
    c1 = _make_candidate_diagnostic("TATASTEEL", "3499", atr_pct=0.60, rank=1)

    with patch.dict(
        "os.environ",
        {
            "BROKER_API_KEY": "dummy",
            "BROKER_CLIENT_ID": "dummy",
            "BROKER_PIN": "1234",
            "BROKER_TOTP_SECRET": "dummy",
        },
    ):
        stream = _verified_test_stream([c1])

    # Tick for unknown token "99999"
    now_ts = int(datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc).timestamp())
    raw_payload = {
        "token": "99999",
        "last_traded_price": 50000,
        "last_traded_quantity": 100,
        "exchange_timestamp": now_ts,
    }

    initial_qsize = stream.ingestion_queue.qsize()
    stream._on_data(None, raw_payload)
    # Queue size should be unchanged
    assert stream.ingestion_queue.qsize() == initial_qsize
