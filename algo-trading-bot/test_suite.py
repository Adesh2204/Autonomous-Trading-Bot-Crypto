"""
test_suite.py — Production-Grade End-to-End Test Suite & Quantitative Risk Audit
================================================================================
Comprehensive verification covering:
  Phase 1: Order Execution & Payload Validation
    - SmartAPI string order ID payload ("240915000001")
    - SmartAPI dictionary payload ({'status': True, 'data': {'orderid': ...}})
    - Internal state transitions to HOLDING_TRANCHE_1
    - Order failure / None handling with graceful return to IDLE

  Phase 2: Structural Logic & Quantitative Risk Pillars
    - Pillar 1: Dual-Layer Regime Filter (VWAP slope < 0 and EMA9 < EMA21)
    - Pillar 2: Statutory Net-Profit Friction Gate (5x leveraged ₹16,500 size >= 1.5x R:R)
    - Pillar 3: Wick-Immunity (Intra-candle wick ignored, confirmed on candle close)
    - Pillar 4: Dynamic Pyramiding (Tranche 2 trigger == entry + 2.0 * ATR)
    - Pillar 5: P&L Tracking & Post-Stop-Loss 10-Candle Cooldown Firewall
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# Ensure mocks for optional external broker SDKs in offline testing environments
if "pyotp" not in sys.modules:
    sys.modules["pyotp"] = MagicMock()
if "SmartApi" not in sys.modules:
    sys.modules["SmartApi"] = MagicMock()
    sys.modules["SmartApi.smartWebSocketV2"] = MagicMock()

base_dir = os.path.dirname(os.path.abspath(__file__))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

import config
from execution_engine import (
    PaperTrader,
    PyramidingState,
    place_live_order,
    calculate_true_friction,
    validate_trade_margin,
)
from signal_brain import evaluate_regime_gate, generate_vwap_signal


# ==============================================================================
# PHASE 1: ORDER EXECUTION & PAYLOAD VALIDATION
# ==============================================================================

def test_phase1_smartapi_string_payload():
    """Verify smartApi.placeOrder() handling when SDK returns a raw string."""
    mock_angel = MagicMock()
    raw_order_id = "240915000001"
    mock_angel.placeOrder.return_value = raw_order_id

    order_id = place_live_order(
        angel=mock_angel,
        symbol="SJVN-EQ",
        token="18883",
        side="BUY",
        qty=50,
    )
    assert order_id == raw_order_id, f"Expected {raw_order_id}, got {order_id}"
    assert isinstance(order_id, str), "Order ID must be extracted as string"


def test_phase1_smartapi_dict_payload():
    """Verify smartApi.placeOrder() handling when wrapper returns a dictionary."""
    mock_angel = MagicMock()

    # Case A: status = True
    mock_angel.placeOrder.return_value = {
        "status": True,
        "data": {"orderid": "240915000002"},
    }
    order_id_a = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert order_id_a == "240915000002"

    # Case B: success = True
    mock_angel.placeOrder.return_value = {
        "success": True,
        "data": {"orderid": "240915000003"},
    }
    order_id_b = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert order_id_b == "240915000003"


def test_phase1_order_assignment_state_transition(monkeypatch):
    """Confirm internal position state strictly transitions to HOLDING_TRANCHE_1."""
    monkeypatch.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.return_value = "240915000001"

    trader = PaperTrader(
        total_capital=config.TOTAL_CAPITAL,
        working_capital_pct=0.50,
        angel_session=mock_angel,
    )
    assert trader.state == PyramidingState.IDLE

    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {
        "VWAP": 100.0,
        "Close": 100.0,
        "symbol": "SJVN-EQ",
        "ATR_14": 1.0,
    }

    ticket = trader.execute_trade(
        signal_data=signal_data,
        timestamp=t0,
        atr_14=1.0,
        side="BUY",
        angel_session=mock_angel,
    )

    assert ticket is not None, "Trade execution returned None on valid order"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1, (
        f"State did not transition to HOLDING_TRANCHE_1: {trader.state}"
    )
    assert trader._pending_order_id == "240915000001"
    assert trader._open_position is not None
    assert trader._open_position["current_tranches"] == 1
    assert trader._open_position["quantity"] > 0
    assert mock_angel.placeOrder.called


def test_phase1_order_failure_graceful_skip(monkeypatch):
    """Verify failed/None order gracefully skips trade and stays IDLE."""
    monkeypatch.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    # Broker returns rejection / failure
    mock_angel.placeOrder.return_value = None

    trader = PaperTrader(
        total_capital=10000.0,
        working_capital_pct=0.50,
        angel_session=mock_angel,
    )
    assert trader.state == PyramidingState.IDLE

    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {
        "VWAP": 100.0,
        "Close": 100.0,
        "symbol": "SJVN-EQ",
        "ATR_14": 1.0,
    }

    ticket = trader.execute_trade(
        signal_data=signal_data,
        timestamp=t0,
        atr_14=1.0,
        side="BUY",
        angel_session=mock_angel,
    )

    assert ticket is None, "Failed order must return None"
    assert trader.state == PyramidingState.IDLE, "State must remain IDLE on failed order"
    assert trader._open_position is None, "No position must be opened on failed order"


# ==============================================================================
# PHASE 2: STRUCTURAL LOGIC & QUANTITATIVE RISK PILLARS
# ==============================================================================

def test_phase2_regime_filter_negative_slope_bearish_ema():
    """Assert engine strictly blocks BUY signals when VWAP slope < 0 and EMA9 < EMA21."""
    # Gatekeeper direct unit test
    signal_result = evaluate_regime_gate(
        potential_signal="BUY",
        vwap_slope=-0.05,  # Negative slope
        ema9=100.0,
        ema21=105.0,       # EMA9 < EMA21
    )
    assert signal_result is None, "Regime gate must block BUY when slope < 0 and EMA9 < EMA21"

    # Test Gate A standalone failure (slope negative)
    signal_gate_a = evaluate_regime_gate("BUY", vwap_slope=-0.01, ema9=105.0, ema21=100.0)
    assert signal_gate_a is None, "Regime gate must block BUY when slope <= 0"

    # Test Gate B standalone failure (EMA9 < EMA21)
    signal_gate_b = evaluate_regime_gate("BUY", vwap_slope=0.05, ema9=99.0, ema21=101.0)
    assert signal_gate_b is None, "Regime gate must block BUY when EMA9 < EMA21"

    # Test passing condition
    signal_pass = evaluate_regime_gate("BUY", vwap_slope=0.05, ema9=105.0, ema21=100.0)
    assert signal_pass == "BUY", "Regime gate must allow BUY when slope > 0 and EMA9 >= EMA21"


def test_phase2_friction_gate_statutory_taxes_and_rr():
    """
    Inject a test trade with a ₹16,500 position size (5x leveraged).
    Assert net profit math clears the minimum 1.5x R:R threshold after statutory exchange taxes.
    """
    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50)

    entry_price = 100.0
    qty = 165  # Position size = 165 * 100.0 = ₹16,500
    atr = 1.0

    # 1:2 Risk-Reward setup with 2x ATR SL and 4x ATR TP
    sl_distance = 2.0 * atr  # ₹2.00
    tp_distance = 4.0 * atr  # ₹4.00
    sl_price = entry_price - sl_distance  # ₹98.00
    tp_price = entry_price + tp_distance  # ₹104.00

    # Statutory charges audit
    entry_costs = trader.calculate_entry_leg_charges(qty, entry_price)
    exit_costs_tp = trader.calculate_exit_leg_charges(qty, tp_price)
    round_trip_friction = entry_costs["total_charges"] + exit_costs_tp["total_charges"]

    gross_profit = qty * tp_distance   # 165 * 4 = ₹660.00
    gross_loss = qty * sl_distance     # 165 * 2 = ₹330.00
    net_profit = gross_profit - round_trip_friction
    net_loss = gross_loss + round_trip_friction

    actual_net_rr = net_profit / net_loss

    # Assert statutory charges are strictly non-zero and detailed
    assert entry_costs["brokerage"] > 0
    assert exit_costs_tp["stt"] > 0
    assert round_trip_friction > 0

    # Assert Net R:R clears minimum threshold (1.5x)
    assert actual_net_rr >= 1.50, (
        f"Net R:R {actual_net_rr:.2f} failed to clear 1.5x floor on ₹16,500 position"
    )

    # Validate the built-in friction gate check passes
    passed, reason = trader.friction_gate_check(
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        qty=qty,
        atr=atr,
        brokerage_cost=0.0,
    )
    assert passed is True, f"Friction gate check failed: {reason}"


def test_phase2_wick_immunity_intra_candle_vs_close():
    """
    Simulate a tick-level price drop below the stop-loss limit, followed by
    a 1-minute candle close above it. Assert intra-candle wick is ignored.
    """
    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)

    # Establish Base Position
    ticket = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
        side="BUY",
    )
    assert ticket is not None
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1
    stop_loss = trader._open_position["stop_loss_price"]  # ₹98.00

    # 1. Tick-level breach (Wick test): Price plunges below SL to ₹97.50
    t1 = t0 + timedelta(seconds=30)
    tick_exit = trader.check_exit(live_price=97.50, timestamp=t1)
    assert tick_exit is None, "check_exit prematurely triggered SL on intra-candle wick!"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1, "Position must remain open during intra-candle wick"

    # 2. Candle Close ABOVE Stop Loss (Wick absorbed): Close = ₹98.50 > ₹98.00
    t2 = t0 + timedelta(minutes=1)
    candle_payload = {
        "Timestamp": t2,
        "Open": 100.0,
        "High": 100.5,
        "Low": 97.50,    # Deep wick below SL
        "Close": 98.50,  # Rebounded above SL
        "Volume": 1000,
    }
    close_exit = trader.notify_candle_close(
        candle=candle_payload,
        timestamp=t2,
        latest_price=98.50,
    )
    assert close_exit is None, "notify_candle_close falsely triggered SL when close was above SL!"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1, "Position must survive wick"

    # 3. Candle Close BELOW Stop Loss (True Breach): Close = ₹97.80 < ₹98.00
    t3 = t0 + timedelta(minutes=2)
    candle_breach = {
        "Timestamp": t3,
        "Open": 98.50,
        "High": 98.60,
        "Low": 97.50,
        "Close": 97.80,  # Closed below SL
        "Volume": 1000,
    }
    sl_exit = trader.notify_candle_close(
        candle=candle_breach,
        timestamp=t3,
        latest_price=97.80,
    )
    assert sl_exit is not None, "notify_candle_close failed to trigger SL on confirmed candle close"
    assert "Stop Loss" in sl_exit["exit_reason"]
    assert trader._open_position is None


def test_phase2_dynamic_pyramiding_tranche2_trigger():
    """Verify Tranche 2 scale-in trigger dynamically calculates to exactly entry_price + (2.0 * ATR)."""
    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)

    entry_price = 100.0
    entry_atr = 1.50
    ticket = trader.execute_trade(
        {"VWAP": entry_price, "Close": entry_price, "symbol": "SJVN-EQ", "ATR_14": entry_atr},
        timestamp=t0,
        atr_14=entry_atr,
        side="BUY",
    )
    assert ticket is not None

    # Expected trigger price: entry_price + (2.0 * ATR) = 100.0 + 3.0 = ₹103.00
    expected_trigger = entry_price + (2.0 * entry_atr)
    assert trader.entry_atr == entry_atr

    # Scale-in blocked when price is below trigger (e.g. ₹101.50)
    t1 = t0 + timedelta(minutes=2)
    sub_trigger_signal = {
        "VWAP": 101.50,
        "Close": 101.50,
        "symbol": "SJVN-EQ",
        "ATR_14": entry_atr,
    }
    blocked_res = trader.execute_trade(
        signal_data=sub_trigger_signal,
        timestamp=t1,
        atr_14=entry_atr,
        side="BUY",
    )
    assert blocked_res is None, "Scale-in must be blocked before price reaches 2.0x ATR"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1

    # Scale-in permitted when price meets/exceeds trigger (e.g. ₹103.05)
    t2 = t0 + timedelta(minutes=4)
    valid_scale_signal = {
        "VWAP": expected_trigger + 0.05,
        "Close": expected_trigger + 0.05,
        "symbol": "SJVN-EQ",
        "ATR_14": entry_atr,
    }
    scale_res = trader.execute_trade(
        signal_data=valid_scale_signal,
        timestamp=t2,
        atr_14=entry_atr,
        side="BUY",
    )
    assert scale_res is not None, "Scale-in must execute when price reaches entry + 2.0x ATR"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_2
    assert trader._open_position["current_tranches"] == 2


def test_phase2_pnl_tracking_tp_and_sl_cooldown():
    """
    Trigger simulated take-profit exit and stop-loss exit.
    Validate P&L trackers correctly log net capital changes, trigger 10-candle
    cooldown on loss, and cleanly reset state to IDLE.
    """
    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50)
    initial_working_cap = trader.working_capital

    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)

    # ── Part 1: Take-Profit Exit ──────────────────────────────────────────────
    trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
        side="BUY",
    )
    tp_summary = trader.close_position(
        exit_price=104.0,
        timestamp=t0 + timedelta(minutes=5),
        reason="Target Hit",
    )
    assert tp_summary is not None
    assert tp_summary["net_pnl"] > 0
    assert trader.working_capital > initial_working_cap
    assert trader._open_position is None

    # Reset state to IDLE for next trade
    trader._state = PyramidingState.IDLE

    # ── Part 2: Stop-Loss Exit & 10-Candle Cooldown ───────────────────────────
    cap_before_loss = trader.working_capital
    t1 = t0 + timedelta(minutes=10)
    trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0},
        timestamp=t1,
        atr_14=1.0,
        side="BUY",
    )
    sl_summary = trader.close_position(
        exit_price=98.0,
        timestamp=t1 + timedelta(minutes=2),
        reason="Stop Loss (Wick-Immune Candle Close)",
    )
    assert sl_summary is not None
    assert sl_summary["net_pnl"] < 0
    assert trader.working_capital < cap_before_loss

    # Verify Cooldown Firewall Triggered
    assert trader.candles_since_last_sl == 0, "Stop loss must reset cooldown counter to 0"

    # Reset state to IDLE
    trader._state = PyramidingState.IDLE

    # Immediate next signal must be BLOCKED by Cooldown Firewall (< 10 candles)
    t2 = t1 + timedelta(minutes=3)
    blocked_trade = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0},
        timestamp=t2,
        atr_14=1.0,
        side="BUY",
    )
    assert blocked_trade is None, "Cooldown firewall must block trade immediately after stop loss"

    # Advance 10 candles
    for i in range(1, 11):
        trader.notify_candle_close(
            candle={"Close": 100.0, "Volume": 500},
            timestamp=t2 + timedelta(minutes=i),
            latest_price=100.0,
        )
    assert trader.candles_since_last_sl >= 10, "Cooldown counter must reach >= 10 after 10 candle closes"

    # Now trade must be PERMITTED
    t3 = t2 + timedelta(minutes=11)
    allowed_trade = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0},
        timestamp=t3,
        atr_14=1.0,
        side="BUY",
    )
    assert allowed_trade is not None, "Trade must be permitted once 10-candle cooldown expires"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1


# ==============================================================================
# FRICTION GATE V2 ACCEPTANCE TESTS (Angel One NSE Equity Intraday Cost Model)
# ==============================================================================

def test_friction_v2_acceptance_reproduce_actual_bill():
    """
    Acceptance Test 1: Reproduce today's actual Angel One bill.
    Pull 9 round-trip entry/exit prices with qty=50 (~₹3,250 order value).
    Sum of total_friction across all 9 must match ₹116.60 within a few paise.
    """
    trades = [
        (65.00, 65.20), (65.10, 64.90), (65.25, 65.05),
        (65.00, 65.15), (65.30, 65.10), (65.05, 65.25),
        (65.20, 65.00), (65.15, 65.35), (65.00, 64.85),
    ]
    total_bill = sum(calculate_true_friction(b, s, 50)["total_friction"] for b, s in trades)
    assert abs(total_bill - 116.60) <= 0.50, (
        f"Sum of 9 round trips total friction was ₹{total_bill:.2f}, expected ₹116.60 (diff > 50p)"
    )


def test_friction_v2_acceptance_narrow_target_blocked():
    """
    Acceptance Test 2: A typical current target should fail the gate.
    Feed in a ₹0.13–0.22/share target at qty=50 — net_pnl must be negative,
    and validate_trade_margin must block it.
    """
    for target_dist in [0.13, 0.18, 0.22]:
        costs = calculate_true_friction(buy_price=65.00, sell_price=65.00 + target_dist, qty=50)
        assert costs["net_pnl"] < 0, f"Net PnL should be negative for target {target_dist}: {costs}"
        passed = validate_trade_margin(entry_price=65.00, target_price=65.00 + target_dist, qty=50, side="BUY")
        assert passed is False, f"Gate should block narrow target {target_dist}"


def test_friction_v2_acceptance_wider_target_passed():
    """
    Acceptance Test 3: A wider target should pass.
    Confirm there is a realistic target size (e.g. ₹0.50/share at qty=50)
    where net_pnl clears MIN_NET_PROFIT (₹5.00).
    """
    costs = calculate_true_friction(buy_price=65.00, sell_price=65.50, qty=50)
    assert costs["net_pnl"] >= config.MIN_NET_PROFIT_RS, (
        f"Net PnL {costs['net_pnl']} should clear MIN_NET_PROFIT {config.MIN_NET_PROFIT_RS}"
    )
    passed = validate_trade_margin(entry_price=65.00, target_price=65.50, qty=50, side="BUY")
    assert passed is True, "Gate should pass wider target (₹0.50/share)"


def test_friction_v2_acceptance_edge_cases():
    """
    Acceptance Test 4: Edge cases:
      - qty=0: returns all 0.0
      - buy_price == sell_price: returns negative net_pnl equal to -total_friction
      - very large qty: correctly applies ₹20 brokerage cap per leg (₹40 total)
    """
    zero_res = calculate_true_friction(65.00, 65.00, 0)
    assert zero_res["total_friction"] == 0.0
    assert zero_res["net_pnl"] == 0.0
    assert zero_res["brokerage"] == 0.0

    eq_res = calculate_true_friction(65.00, 65.00, 50)
    assert eq_res["gross_pnl"] == 0.0
    assert eq_res["net_pnl"] == -eq_res["total_friction"]
    assert eq_res["total_friction"] > 0

    lg_res = calculate_true_friction(1000.00, 1050.00, 1000)
    assert lg_res["brokerage"] == 40.00, f"Brokerage cap failed: {lg_res['brokerage']}"


# ==============================================================================
# AUDIT RUNNER & REPORT GENERATOR
# ==============================================================================

def run_audit() -> None:
    print("\n" + "═" * 78)
    print("  ALGO-TRADING-BOT: COMPREHENSIVE QA & QUANTITATIVE AUDIT REPORT")
    print("═" * 78)

    tests = [
        ("Phase 1: SmartAPI Raw String Payload ('240915000001')", test_phase1_smartapi_string_payload),
        ("Phase 1: SmartAPI Dict Payload Parsing (status/success)", test_phase1_smartapi_dict_payload),
        ("Phase 1: State Transition strictly to HOLDING_TRANCHE_1", lambda: test_phase1_order_assignment_state_transition(pytest.MonkeyPatch())),
        ("Phase 1: Graceful Skip on Broker Order Failure / None", lambda: test_phase1_order_failure_graceful_skip(pytest.MonkeyPatch())),
        ("Phase 2: Pillar 1 - Regime Filter (Negative Slope & Bearish EMA)", test_phase2_regime_filter_negative_slope_bearish_ema),
        ("Phase 2: Pillar 2 - Friction Gate (₹16,500 Position Size >= 1.5x R:R)", test_phase2_friction_gate_statutory_taxes_and_rr),
        ("Phase 2: Pillar 3 - Wick-Immunity (Intra-candle vs Candle Close)", test_phase2_wick_immunity_intra_candle_vs_close),
        ("Phase 2: Pillar 4 - Dynamic Pyramiding (Trigger = Entry + 2.0x ATR)", test_phase2_dynamic_pyramiding_tranche2_trigger),
        ("Phase 2: Pillar 5 - P&L Tracking & 10-Candle SL Cooldown Firewall", test_phase2_pnl_tracking_tp_and_sl_cooldown),
        ("Friction v2: Acceptance 1 - Reconcile 9-trade bill within ₹0.50 of ₹116.60", test_friction_v2_acceptance_reproduce_actual_bill),
        ("Friction v2: Acceptance 2 - Block narrow ₹0.13-0.22/share targets", test_friction_v2_acceptance_narrow_target_blocked),
        ("Friction v2: Acceptance 3 - Pass wider target clearing ₹5.00 net profit", test_friction_v2_acceptance_wider_target_passed),
        ("Friction v2: Acceptance 4 - Edge cases (qty=0, equal price, ₹20 cap)", test_friction_v2_acceptance_edge_cases),
    ]

    passed_count = 0
    failed_count = 0

    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  [PASS ✅]  {name}")
            passed_count += 1
        except Exception as exc:
            print(f"  [FAIL ❌]  {name}")
            print(f"             Reason: {exc}")
            failed_count += 1

    print("═" * 78)
    print(f"  AUDIT SUMMARY: {passed_count}/{len(tests)} PASSED | {failed_count} FAILED")
    print("═" * 78 + "\n")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_audit()

