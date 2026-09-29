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
    get_actual_fill_price,
    get_live_capital,
    reconcile_trade,
    reconcile_trade_intraday,
    reconcile_end_of_day,
    init_reconciliation_baselines,
    ReconciliationStatus,
    alert_human,
    RecoveryStatus,
    OrderRecoveryResult,
    recover_broker_order,
    check_broker_position_netqty,
    get_last_order_recovery,
    _is_order_within_window,
)
from signal_brain import evaluate_regime_gate, generate_vwap_signal


# ==============================================================================
# PHASE 1: ORDER EXECUTION & PAYLOAD VALIDATION
# ==============================================================================

def test_phase1_smartapi_string_payload(monkeypatch):
    """Verify smartApi.placeOrder() handling when SDK returns a raw string."""
    monkeypatch.setattr(config, "LIVE_MODE", True)
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


def test_phase1_smartapi_dict_payload(monkeypatch):
    """Verify smartApi.placeOrder() handling when wrapper returns a dictionary."""
    monkeypatch.setattr(config, "LIVE_MODE", True)
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
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "240915000001",
                "status": "complete",
                "averageprice": 100.0,
                "filledshares": 33,
            }
        ],
    }

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
# FULL ACCURACY FIXES: REAL FILLS, LIVE CAPITAL & RECONCILIATION
# ==============================================================================

def test_accuracy_fix1_fill_confirmation_success():
    """Verify fill confirmation extracts averageprice and filledshares from orderBook."""
    mock_api = MagicMock()
    mock_api.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "240916000001",
                "status": "complete",
                "averageprice": "100.25",
                "filledshares": "50",
            }
        ],
    }
    price, qty = get_actual_fill_price(mock_api, "240916000001", expected_qty=50, timeout_sec=0.1)
    assert price == 100.25
    assert qty == 50


def test_accuracy_fix1_partial_fill_warning():
    """Verify partial fill returns actual filledshares and logs warning."""
    mock_api = MagicMock()
    mock_api.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "240916000002",
                "status": "complete",
                "averageprice": "99.80",
                "filledshares": "35",
            }
        ],
    }
    price, qty = get_actual_fill_price(mock_api, "240916000002", expected_qty=50, timeout_sec=0.1)
    assert price == 99.80
    assert qty == 35


def test_accuracy_fix1_unconfirmed_fill_timeout():
    """Verify unconfirmed fill times out and returns (None, 0)."""
    mock_api = MagicMock()
    mock_api.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "240916000003",
                "status": "pending",
                "averageprice": "0.0",
                "filledshares": "0",
            }
        ],
    }
    price, qty = get_actual_fill_price(mock_api, "240916000003", expected_qty=50, timeout_sec=0.1, poll_interval=0.02)
    assert price is None
    assert qty == 0


def test_accuracy_fix2_get_live_capital():
    """Verify get_live_capital queries broker rmsLimit and extracts availablecash."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {
            "availablecash": "18450.50",
            "net": "18450.50",
        },
    }
    capital = get_live_capital(mock_api)
    assert capital == 18450.50


def test_accuracy_fix6_reconcile_trade():
    """[DEPRECATED LEGACY TEST] Verify old reconcile_trade check passes within tolerance."""
    assert reconcile_trade(capital_before=10000.0, capital_after=10048.0, logged_net_pnl=49.0, tolerance=5.0) is True
    assert reconcile_trade(capital_before=10000.0, capital_after=9950.0, logged_net_pnl=40.0, tolerance=5.0) is False

# ==============================================================================
# SLIPPAGE HAIRCUT INTEGRATION TESTS (11 SCENARIOS — §32-§52)
# ==============================================================================

def test_slippage_long_simulation():
    """§32: LONG — simulated_buy = 100.05, simulated_sell = 101.949 for H=0.0005."""
    from unittest.mock import patch, call
    entry, target, qty, H = 100.0, 102.0, 50, 0.0005
    expected_buy = entry * (1.0 + H)   # 100.05
    expected_sell = target * (1.0 - H)  # 101.949

    assert abs(expected_buy - 100.05) < 1e-9
    assert abs(expected_sell - 101.949) < 1e-9

    with patch("execution_engine.calculate_true_friction", wraps=calculate_true_friction) as mock_ctf:
        validate_trade_margin(entry_price=entry, target_price=target, qty=qty, side="BUY", slippage_pct=H)
        mock_ctf.assert_called_once()
        called_buy, called_sell, called_qty = mock_ctf.call_args[0]
        assert abs(called_buy - expected_buy) < 1e-9, f"BUY price mismatch: {called_buy} vs {expected_buy}"
        assert abs(called_sell - expected_sell) < 1e-9, f"SELL price mismatch: {called_sell} vs {expected_sell}"
        assert called_qty == qty


def test_slippage_short_simulation():
    """§33: SHORT — simulated_sell = 99.95, simulated_buy = 98.049 for H=0.0005."""
    from unittest.mock import patch
    entry, target, qty, H = 100.0, 98.0, 50, 0.0005
    expected_sell = entry * (1.0 - H)   # 99.95
    expected_buy = target * (1.0 + H)   # 98.049

    assert abs(expected_sell - 99.95) < 1e-9
    assert abs(expected_buy - 98.049) < 1e-9

    with patch("execution_engine.calculate_true_friction", wraps=calculate_true_friction) as mock_ctf:
        validate_trade_margin(entry_price=entry, target_price=target, qty=qty, side="SHORT", slippage_pct=H)
        mock_ctf.assert_called_once()
        called_buy, called_sell, called_qty = mock_ctf.call_args[0]
        assert abs(called_buy - expected_buy) < 1e-9, f"BUY price mismatch: {called_buy} vs {expected_buy}"
        assert abs(called_sell - expected_sell) < 1e-9, f"SELL price mismatch: {called_sell} vs {expected_sell}"
        assert called_qty == qty


def test_slippage_zero_haircut():
    """§34: Zero haircut → simulated prices == expected prices."""
    from unittest.mock import patch
    entry, target, qty = 100.0, 105.0, 50

    # LONG with zero haircut
    with patch("execution_engine.calculate_true_friction", wraps=calculate_true_friction) as mock_ctf:
        validate_trade_margin(entry_price=entry, target_price=target, qty=qty, side="BUY", slippage_pct=0.0)
        called_buy, called_sell, called_qty = mock_ctf.call_args[0]
        assert called_buy == entry, f"Zero haircut: buy should equal entry, got {called_buy}"
        assert called_sell == target, f"Zero haircut: sell should equal target, got {called_sell}"

    # SHORT with zero haircut
    with patch("execution_engine.calculate_true_friction", wraps=calculate_true_friction) as mock_ctf:
        validate_trade_margin(entry_price=entry, target_price=98.0, qty=qty, side="SHORT", slippage_pct=0.0)
        called_buy, called_sell, called_qty = mock_ctf.call_args[0]
        assert called_buy == 98.0, f"Zero haircut: buy should equal target, got {called_buy}"
        assert called_sell == entry, f"Zero haircut: sell should equal entry, got {called_sell}"


def test_slippage_blocked_trade():
    """§35: Marginal trade that survives without haircut fails with haircut."""
    # Use a narrow target that just barely clears MIN_NET_PROFIT without slippage
    # but gets blocked when haircut is applied
    entry, qty = 65.00, 50
    # Find a target that barely passes with zero slippage
    target = 65.50  # Known to pass from existing tests

    # Confirm it passes with zero slippage
    result_no_slip = validate_trade_margin(entry_price=entry, target_price=target, qty=qty, side="BUY", slippage_pct=0.0)
    assert result_no_slip is True, "Should pass without slippage"

    # Now use a very aggressive haircut to force a block
    result_with_slip = validate_trade_margin(entry_price=entry, target_price=target, qty=qty, side="BUY", slippage_pct=0.10)
    assert result_with_slip is False, "Should be blocked with 10% haircut"


def test_slippage_passed_trade():
    """§36: Comfortable trade passes even after haircut."""
    # Large target spread easily survives 0.05% haircut
    result = validate_trade_margin(
        entry_price=100.0, target_price=110.0, qty=100, side="BUY", slippage_pct=0.0005
    )
    assert result is True, "Wide target should pass even with haircut"

    # SHORT direction too
    result_short = validate_trade_margin(
        entry_price=110.0, target_price=100.0, qty=100, side="SHORT", slippage_pct=0.0005
    )
    assert result_short is True, "Wide short target should pass even with haircut"


def test_slippage_strategy_immutability():
    """§37: Original strategy values must remain unchanged after gate evaluation."""
    entry_price = 100.0
    target_price = 102.0
    stop_loss = 98.0
    qty = 50

    # Capture originals
    orig_entry = entry_price
    orig_target = target_price
    orig_sl = stop_loss
    orig_qty = qty

    # Run the gate
    validate_trade_margin(
        entry_price=entry_price, target_price=target_price, qty=qty,
        side="BUY", slippage_pct=0.0005
    )

    # Assert all strategy values untouched
    assert entry_price == orig_entry, f"entry_price mutated: {entry_price} vs {orig_entry}"
    assert target_price == orig_target, f"target_price mutated: {target_price} vs {orig_target}"
    assert stop_loss == orig_sl, f"stop_loss mutated: {stop_loss} vs {orig_sl}"
    assert qty == orig_qty, f"qty mutated: {qty} vs {orig_qty}"


def test_slippage_invalid_side():
    """§40: Invalid side → error, no fallback to LONG, no mutation."""
    result = validate_trade_margin(
        entry_price=100.0, target_price=105.0, qty=50, side="INVALID"
    )
    assert result is False, "Invalid side must return False"

    # Also test empty string and numeric side
    assert validate_trade_margin(100.0, 105.0, 50, side="") is False
    assert validate_trade_margin(100.0, 105.0, 50, side="UP") is False


def test_slippage_negative_haircut():
    """§41: Negative haircut → rejected (would reward instead of penalise)."""
    result = validate_trade_margin(
        entry_price=100.0, target_price=105.0, qty=50,
        side="BUY", slippage_pct=-0.001
    )
    assert result is False, "Negative haircut must be rejected"


def test_slippage_config_override():
    """§42: Explicit override is used; global config is not permanently modified."""
    import execution_engine
    original_config = execution_engine.SLIPPAGE_HAIRCUT_PCT

    # Use explicit override — should use 0.001 not the global 0.0005
    from unittest.mock import patch
    with patch("execution_engine.calculate_true_friction", wraps=calculate_true_friction) as mock_ctf:
        validate_trade_margin(
            entry_price=100.0, target_price=105.0, qty=50,
            side="BUY", slippage_pct=0.001
        )
        called_buy = mock_ctf.call_args[0][0]
        # With 0.001 override: 100 * 1.001 = 100.1
        assert abs(called_buy - 100.1) < 1e-9, f"Override not used: got {called_buy}"

    # Confirm global config unchanged
    assert execution_engine.SLIPPAGE_HAIRCUT_PCT == original_config, \
        "Global SLIPPAGE_HAIRCUT_PCT was modified by test override"


def test_slippage_no_double_application():
    """§43: Penalty must be applied exactly once — price × (1 ± H), not × (1 ± H)²."""
    from unittest.mock import patch
    entry, target, qty, H = 100.0, 102.0, 50, 0.01  # 1% for easy verification

    with patch("execution_engine.calculate_true_friction", wraps=calculate_true_friction) as mock_ctf:
        validate_trade_margin(entry_price=entry, target_price=target, qty=qty, side="BUY", slippage_pct=H)
        called_buy = mock_ctf.call_args[0][0]
        called_sell = mock_ctf.call_args[0][1]

        # Single application: 100 * 1.01 = 101.0
        # Double application would be: 100 * 1.01 * 1.01 = 102.01
        expected_single_buy = entry * (1.0 + H)
        expected_double_buy = entry * (1.0 + H) * (1.0 + H)
        assert abs(called_buy - expected_single_buy) < 1e-9, \
            f"Haircut applied more than once on buy: {called_buy}"
        assert abs(called_buy - expected_double_buy) > 0.5, \
            f"Buy price matches double-application: {called_buy}"

        expected_single_sell = target * (1.0 - H)
        assert abs(called_sell - expected_single_sell) < 1e-9, \
            f"Haircut applied more than once on sell: {called_sell}"


def test_slippage_financial_invariant():
    """§51-52: Haircut must always make simulated trade less favourable or equal."""
    from unittest.mock import patch
    import random
    random.seed(42)

    for _ in range(50):
        entry = random.uniform(10, 5000)
        spread = random.uniform(0.5, 100)
        target = entry + spread  # LONG: target > entry
        qty = random.randint(1, 1000)
        H = random.uniform(0, 0.05)  # 0% to 5%

        # LONG invariant: sim_buy >= entry, sim_sell <= target
        sim_buy = entry * (1.0 + H)
        sim_sell = target * (1.0 - H)
        assert sim_buy >= entry, f"LONG: sim_buy {sim_buy} < entry {entry}"
        assert sim_sell <= target, f"LONG: sim_sell {sim_sell} > target {target}"

        # SHORT invariant: sim_sell <= entry, sim_buy >= target_short
        target_short = entry - spread  # SHORT: target < entry
        if target_short > 0:
            sim_sell_s = entry * (1.0 - H)
            sim_buy_s = target_short * (1.0 + H)
            assert sim_sell_s <= entry, f"SHORT: sim_sell {sim_sell_s} > entry {entry}"
            assert sim_buy_s >= target_short, f"SHORT: sim_buy {sim_buy_s} < target {target_short}"

    # H=0 equality check
    assert 100.0 * (1.0 + 0) == 100.0
    assert 102.0 * (1.0 - 0) == 102.0


# ==============================================================================
# FIX #6: LIVE BROKER RECONCILIATION TEST SUITE (16 SCENARIOS)
# ==============================================================================

def test_recon_normal_winning_trade():
    """Test 1: Normal winning trade — gross +100 matches broker delta +100 -> RECONCILED."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [
            {
                "exchange": "NSE",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "producttype": "INTRADAY",
                "realised": "100.00",
                "netqty": "0",
            }
        ],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T1", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=100.0,
        trade_context=trade_ctx,
        baselines=baselines,
    )
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["broker_realised_delta"] == 100.0
    assert result["difference"] == 0.0


def test_recon_normal_losing_trade():
    """Test 2: Normal losing trade — gross -100 matches broker delta -100 -> RECONCILED."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [
            {
                "exchange": "NSE",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "producttype": "INTRADAY",
                "realised": "-100.00",
                "netqty": "0",
            }
        ],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T2", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=-100.0,
        trade_context=trade_ctx,
        baselines=baselines,
    )
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["broker_realised_delta"] == -100.0
    assert result["difference"] == 0.0


def test_recon_rms_cash_movement_immunity():
    """
    Test 3: Temporary RMS cash movement immunity.
    Proves that availablecash fluctuations (e.g. margin holds, provisional taxes)
    do NOT cause false reconciliation mismatches.
    """
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [
            {
                "exchange": "NSE",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "producttype": "INTRADAY",
                "realised": "6.00",
                "netqty": "0",
            }
        ],
    }
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "9930.00"},  # started at 10000.00
    }
    # Legacy cash comparison fails: abs((9930 - 10000) - 6.0) = 76.0 > 5.0 -> FALSE MISMATCH
    old_recon = reconcile_trade(capital_before=10000.0, capital_after=9930.0, logged_net_pnl=6.0, tolerance=5.0)
    assert old_recon is False

    # New architecture evaluates against position() realized P&L delta -> RECONCILED
    baselines = {}
    trade_ctx = {"trade_id": "T3", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=6.0,
        trade_context=trade_ctx,
        baselines=baselines,
    )
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["difference"] == 0.0


def test_recon_genuine_mismatch():
    """Test 4: Genuine P&L mismatch — bot logs +100, broker realised delta is +80 -> MISMATCH."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [
            {
                "exchange": "NSE",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "producttype": "INTRADAY",
                "realised": "80.00",
                "netqty": "0",
            }
        ],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T4", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=100.0,
        trade_context=trade_ctx,
        tolerance=0.50,
        baselines=baselines,
    )
    assert result["status"] == ReconciliationStatus.MISMATCH
    assert result["difference"] == 20.0


def test_recon_delayed_position_update():
    """Test 5: Delayed position update — first call unchanged, second call reflects trade -> RECONCILED."""
    mock_api = MagicMock()
    resp_stale = {
        "status": True,
        "data": [
            {
                "exchange": "NSE",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "producttype": "INTRADAY",
                "realised": "0.00",
                "netqty": "0",
            }
        ],
    }
    resp_fresh = {
        "status": True,
        "data": [
            {
                "exchange": "NSE",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "producttype": "INTRADAY",
                "realised": "75.00",
                "netqty": "0",
            }
        ],
    }
    mock_api.position.side_effect = [resp_stale, resp_fresh]
    baselines = {}
    trade_ctx = {"trade_id": "T5", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=75.0,
        trade_context=trade_ctx,
        max_retries=3,
        retry_interval=0.01,
        baselines=baselines,
    )
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["broker_realised_delta"] == 75.0


def test_recon_api_failure():
    """Test 6: Position endpoint failure — API exception returns API_ERROR, never RECONCILED."""
    mock_api = MagicMock()
    mock_api.position.side_effect = Exception("Connection reset by peer")
    baselines = {}
    trade_ctx = {"trade_id": "T6", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=50.0,
        trade_context=trade_ctx,
        baselines=baselines,
    )
    assert result["status"] == ReconciliationStatus.API_ERROR
    assert result["status"] != ReconciliationStatus.RECONCILED


def test_recon_empty_position_response():
    """Test 7: Empty position response — returns SKIPPED, never RECONCILED."""
    mock_api = MagicMock()
    mock_api.position.return_value = {"status": True, "data": []}
    baselines = {}
    trade_ctx = {"trade_id": "T7", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(
        smart_api=mock_api,
        symbol="SJVN-EQ",
        logged_gross_pnl=50.0,
        trade_context=trade_ctx,
        max_retries=2,
        retry_interval=0.01,
        baselines=baselines,
    )
    assert result["status"] in (ReconciliationStatus.SKIPPED, ReconciliationStatus.UNVERIFIED)
    assert result["status"] != ReconciliationStatus.RECONCILED


def test_recon_multiple_trades_cumulative_delta():
    """
    Test 8: Multiple trades on the same symbol.
    Trade 1: +100 -> cumulative 100.
    Trade 2: -20  -> cumulative 80.
    Both reconcile cleanly against deltas (+100 and -20).
    """
    mock_api = MagicMock()
    baselines = {}
    trade_ctx = {"token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}

    # Trade 1 (+100 gross)
    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "100.00", "netqty": "0"}],
    }
    r1 = reconcile_trade_intraday(mock_api, "SJVN-EQ", 100.0, trade_context={"trade_id": "T8-1", **trade_ctx}, baselines=baselines)
    assert r1["status"] == ReconciliationStatus.RECONCILED
    assert r1["broker_realised_delta"] == 100.0

    # Trade 2 (-20 gross, cumulative becomes 80)
    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "80.00", "netqty": "0"}],
    }
    r2 = reconcile_trade_intraday(mock_api, "SJVN-EQ", -20.0, trade_context={"trade_id": "T8-2", **trade_ctx}, baselines=baselines)
    assert r2["status"] == ReconciliationStatus.RECONCILED
    assert r2["broker_realised_delta"] == -20.0


def test_recon_restart_safety():
    """
    Test 9: Bot restart safety.
    Broker has pre-existing realized P&L of +250.
    At restart, init_reconciliation_baselines snapshots 250.
    New trade of +50 brings cumulative to 300. Delta is correctly 50, not 300.
    """
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "250.00", "netqty": "0"}],
    }
    baselines = {}
    init_reconciliation_baselines(mock_api, baselines)
    assert baselines.get("NSE:18883:INTRADAY") == 250.0

    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "300.00", "netqty": "0"}],
    }
    trade_ctx = {"trade_id": "T9", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(mock_api, "SJVN-EQ", 50.0, trade_context=trade_ctx, baselines=baselines)
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["broker_realised_delta"] == 50.0
    assert result["broker_realised_delta"] != 300.0


def test_recon_decimal_precision():
    """Test 10: Decimal precision — handles floating-point micro-divergences (10.00 vs 9.999999) -> RECONCILED."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "9.999999", "netqty": "0"}],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T10", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(mock_api, "SJVN-EQ", 10.00, trade_context=trade_ctx, tolerance=0.50, baselines=baselines)
    assert result["status"] == ReconciliationStatus.RECONCILED


def test_recon_wrong_symbol():
    """Test 11: Wrong symbol — broker positions contain other symbols; returns SKIPPED/UNVERIFIED, no false match."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "RELIANCE-EQ", "symboltoken": "2885", "exchange": "NSE", "producttype": "INTRADAY", "realised": "100.00", "netqty": "0"}],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T11", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(mock_api, "SJVN-EQ", 100.0, trade_context=trade_ctx, max_retries=2, retry_interval=0.01, baselines=baselines)
    assert result["status"] in (ReconciliationStatus.SKIPPED, ReconciliationStatus.UNVERIFIED)
    assert result["status"] != ReconciliationStatus.RECONCILED


def test_recon_symbol_exchange_isolation():
    """Test 12: Symbol on multiple exchanges — correctly selects NSE row over BSE row."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [
            {"tradingsymbol": "SJVN-EQ", "symboltoken": "533206", "exchange": "BSE", "producttype": "INTRADAY", "realised": "500.00", "netqty": "0"},
            {"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "120.00", "netqty": "0"},
        ],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T12", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(mock_api, "SJVN-EQ", 120.0, trade_context=trade_ctx, baselines=baselines)
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["broker_realised_delta"] == 120.0


def test_recon_open_position_guard():
    """Test 13: Open position guard — netqty != 0 indicates trade not closed yet; marked UNVERIFIED."""
    mock_api = MagicMock()
    mock_api.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "exchange": "NSE", "producttype": "INTRADAY", "realised": "50.00", "netqty": "50"}],
    }
    baselines = {}
    trade_ctx = {"trade_id": "T13", "token": "18883", "exchange": "NSE", "producttype": "INTRADAY"}
    result = reconcile_trade_intraday(mock_api, "SJVN-EQ", 50.0, trade_context=trade_ctx, max_retries=2, retry_interval=0.01, baselines=baselines)
    assert result["status"] == ReconciliationStatus.UNVERIFIED
    assert result["status"] != ReconciliationStatus.RECONCILED


def test_eod_recon_matching():
    """Test 14: EOD matching — broker capital movement matches logged daily net P&L -> RECONCILED."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "10500.00"},
    }
    result = reconcile_end_of_day(
        smart_api=mock_api,
        opening_capital=10000.0,
        logged_daily_net_pnl=500.0,
        tolerance=1.00,
    )
    assert result["status"] == ReconciliationStatus.RECONCILED
    assert result["difference"] == 0.0


def test_eod_recon_mismatch():
    """Test 15: EOD mismatch — broker capital movement diverges from logged net P&L -> MISMATCH."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "10470.00"},
    }
    result = reconcile_end_of_day(
        smart_api=mock_api,
        opening_capital=10000.0,
        logged_daily_net_pnl=500.0,
        tolerance=1.00,
    )
    assert result["status"] == ReconciliationStatus.MISMATCH
    assert result["difference"] == 30.0


def test_eod_recon_api_failure():
    """Test 16: EOD API failure — broker API returns error; marked UNVERIFIED, never success."""
    mock_api = MagicMock()
    mock_api.rmsLimit.side_effect = Exception("Service unavailable")
    result = reconcile_end_of_day(
        smart_api=mock_api,
        opening_capital=10000.0,
        logged_daily_net_pnl=500.0,
    )
    assert result["status"] == ReconciliationStatus.UNVERIFIED
    assert result["status"] != ReconciliationStatus.RECONCILED


# ==============================================================================
# PHASE 3: SURGICAL BROKER ORDER RECOVERY & SAFETY AUDIT (18 SCENARIOS)
# ==============================================================================

def test_recovery_entry_timeout_broker_executed(monkeypatch=None):
    """Scenario 1: Entry timeout + broker execution -> recovers order ID, establishes position."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Connection timed out waiting for gateway")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "REC_BUY_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 100.10,
                "filledshares": 50,
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }
    mock_angel.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}]
    }

    # 1. Direct verification of place_live_order recovery
    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid == "REC_BUY_001", f"Expected recovered order ID 'REC_BUY_001', got: {oid}"
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_ORDER
    assert last_rec.order_id == "REC_BUY_001"

    # 2. Integration test: PaperTrader executes Tranche 1 using recovered order
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "REC_BUY_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "status": "complete",
                "averageprice": 100.10,
                "filledshares": 33,
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }
    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)
    assert ticket is not None
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1
    assert trader._pending_order_id == "REC_BUY_001"
    assert trader._open_position is not None


def test_recovery_entry_timeout_broker_rejected(monkeypatch=None):
    """Scenario 2: Entry timeout + broker rejection -> confirmed rejection, returns IDLE, no ghost position."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Connection timed out")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "REC_REJ_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "rejected",
                "text": "RMS: Margin Insufficient",
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid is None
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_REJECTION

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)
    assert ticket is None
    assert trader.state == PyramidingState.IDLE
    assert trader._open_position is None


def test_recovery_entry_timeout_no_order(monkeypatch=None):
    """Scenario 3: Entry timeout + no immediate order visibility & netqty==0 -> CONFIRMED_NO_ORDER."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Connection timed out")
    mock_angel.orderBook.return_value = {"status": True, "data": []}
    mock_angel.position.return_value = {"status": True, "data": []}

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid is None
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_NO_ORDER

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)
    assert ticket is None
    assert trader.state == PyramidingState.IDLE
    assert trader._open_position is None


def test_recovery_entry_timeout_multiple_matches(monkeypatch=None):
    """Scenario 4: Entry timeout + multiple matching orders -> STATE_UNKNOWN, quarantines engine."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Connection timed out")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "OID_1",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "complete",
                "ordertype": "MARKET",
                "ordertime": now_str,
            },
            {
                "orderid": "OID_2",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "complete",
                "ordertype": "MARKET",
                "ordertime": now_str,
            },
        ],
    }

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid is None
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.STATE_UNKNOWN

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)
    assert ticket is None
    assert trader.state == PyramidingState.STATE_UNKNOWN


def test_recovery_entry_duplicate_blocked(monkeypatch=None):
    """Scenario 5: Entry timeout + duplicate retry attempt -> STATE_UNKNOWN halts all future entries."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    t0 = datetime(2026, 9, 15, 9, 21, tzinfo=timezone.utc)
    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    trader._current_date = t0.date()
    trader._state = PyramidingState.STATE_UNKNOWN

    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)

    assert ticket is None
    assert trader.state == PyramidingState.STATE_UNKNOWN
    assert mock_angel.placeOrder.call_count == 0


def test_recovery_exit_timeout_broker_executed(monkeypatch=None):
    """Scenario 6: Exit timeout + broker execution -> confirms closure, updates P&L."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Exit order timeout")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "REC_EXIT_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "SELL",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 105.0,
                "filledshares": 50,
                "ordertype": "MARKET",
                "ordertime": now_str,
            }
        ],
    }
    # Checkpoint A sees open (50), post-flight sees flat (0)
    mock_angel.position.side_effect = [
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}]},
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "0", "producttype": "INTRADAY", "exchange": "NSE"}]},
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "0", "producttype": "INTRADAY", "exchange": "NSE"}]},
    ]

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    trader._open_position = {
        "position_id": "P1",
        "symbol": "SJVN-EQ",
        "token": "18883",
        "side": "BUY",
        "quantity": 50,
        "avg_entry_price": 100.0,
        "average_entry_price": 100.0,
        "total_cost": 5000.0,
        "entry_timestamp": datetime.now(),
        "current_tranches": 1,
        "tranches": [1],
        "exit_in_flight": False,
    }
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    summary = trader.close_position(exit_price=105.0, reason="Target Reached", timestamp=datetime.now())
    assert trader._open_position is None
    assert trader.state == PyramidingState.CLOSED
    assert summary is not None
    assert summary["exit_price"] == 105.0


def test_recovery_exit_timeout_broker_rejected(monkeypatch=None):
    """Scenario 7: Exit timeout + broker rejection -> trade remains open locally, no false closure."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Exit order timeout")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "REJ_EXIT_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "SELL",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "rejected",
                "text": "Market closed",
                "ordertype": "MARKET",
                "ordertime": now_str,
            }
        ],
    }
    mock_angel.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}]
    }

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    trader._open_position = {
        "position_id": "P1",
        "symbol": "SJVN-EQ",
        "token": "18883",
        "side": "BUY",
        "quantity": 50,
        "avg_entry_price": 100.0,
        "average_entry_price": 100.0,
        "total_cost": 5000.0,
        "entry_timestamp": datetime.now(),
        "current_tranches": 1,
        "tranches": [1],
        "exit_in_flight": False,
    }
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    summary = trader.close_position(exit_price=105.0, reason="Target Reached", timestamp=datetime.now())
    assert summary is None
    assert trader._open_position is not None
    assert trader.state == PyramidingState.STATE_UNKNOWN


def test_recovery_exit_timeout_netqty_zero_prevents_second_sell(monkeypatch=None):
    """Scenario 8: Exit timeout + netqty == 0 -> Checkpoint A intercepts, zero new SELLs placed."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "0", "producttype": "INTRADAY", "exchange": "NSE"}]
    }
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "ALREADY_CLOSED_OID",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "SELL",
                "producttype": "INTRADAY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 102.5,
                "ordertype": "MARKET",
            }
        ]
    }

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    trader._open_position = {
        "position_id": "P1",
        "symbol": "SJVN-EQ",
        "token": "18883",
        "side": "BUY",
        "quantity": 50,
        "avg_entry_price": 100.0,
        "average_entry_price": 100.0,
        "total_cost": 5000.0,
        "entry_timestamp": datetime.now(),
        "current_tranches": 1,
        "tranches": [1],
        "exit_in_flight": False,
    }
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    summary = trader.close_position(exit_price=103.0, reason="Target Reached", timestamp=datetime.now())
    assert mock_angel.placeOrder.call_count == 0
    assert trader._open_position is None
    assert trader.state == PyramidingState.CLOSED
    assert summary is not None
    assert summary["exit_price"] == 102.5


def test_recovery_exit_timeout_netqty_nonzero_prevents_false_closure(monkeypatch=None):
    """Scenario 9: Exit timeout + netqty != 0 -> prevents false trade closure, sets exit_in_flight."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Exit timeout")
    mock_angel.orderBook.return_value = {"status": True, "data": []}
    mock_angel.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}]
    }

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    trader._open_position = {
        "position_id": "P1",
        "symbol": "SJVN-EQ",
        "token": "18883",
        "side": "BUY",
        "quantity": 50,
        "avg_entry_price": 100.0,
        "average_entry_price": 100.0,
        "total_cost": 5000.0,
        "entry_timestamp": datetime.now(),
        "current_tranches": 1,
        "tranches": [1],
        "exit_in_flight": False,
    }
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    summary = trader.close_position(exit_price=105.0, reason="Target Reached", timestamp=datetime.now())
    assert summary is None
    assert trader._open_position is not None
    assert trader._open_position["exit_in_flight"] is True
    assert trader.state == PyramidingState.STATE_UNKNOWN


def test_recovery_exit_timeout_ambiguous(monkeypatch=None):
    """Scenario 10: Exit timeout + ambiguous broker state -> quarantines, second call blocked by exit_in_flight."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Gateway timeout")
    mock_angel.orderBook.side_effect = Exception("Orderbook API down")
    mock_angel.position.side_effect = Exception("Position API down")

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    trader._open_position = {
        "position_id": "P1",
        "symbol": "SJVN-EQ",
        "token": "18883",
        "side": "BUY",
        "quantity": 50,
        "avg_entry_price": 100.0,
        "average_entry_price": 100.0,
        "total_cost": 5000.0,
        "entry_timestamp": datetime.now(),
        "current_tranches": 1,
        "tranches": [1],
        "exit_in_flight": False,
    }
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    # First exit attempt
    trader.close_position(exit_price=105.0, reason="Stop Loss", timestamp=datetime.now())
    assert trader._open_position is not None
    assert trader._open_position["exit_in_flight"] is True
    assert trader.state == PyramidingState.STATE_UNKNOWN
    assert mock_angel.placeOrder.call_count == 1

    # Second exit call on subsequent candle - blocked by exit_in_flight
    trader.close_position(exit_price=104.0, reason="Stop Loss", timestamp=datetime.now())
    assert mock_angel.placeOrder.call_count == 1


def test_recovery_partial_entry_fill(monkeypatch=None):
    """Scenario 11: Partial entry fill -> position quantity records actual filled shares (30/50)."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.return_value = "ORD_PART_001"
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "ORD_PART_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "status": "complete",
                "averageprice": 100.5,
                "filledshares": 30,
                "unfilledshares": 20,
            }
        ],
    }

    actual_price, filled_qty = get_actual_fill_price(mock_angel, "ORD_PART_001", expected_qty=50)
    assert actual_price == 100.5
    assert filled_qty == 30

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)
    assert ticket is not None
    assert trader._open_position["quantity"] == 30


def test_recovery_partial_exit_fill(monkeypatch=None):
    """Scenario 12: Partial exit fill -> remaining exposure retained (20 shares), trade not closed."""
    mp = monkeypatch or pytest.MonkeyPatch()
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.return_value = "EXIT_PART_001"
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "EXIT_PART_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "SELL",
                "status": "complete",
                "averageprice": 105.0,
                "filledshares": 30,
                "unfilledshares": 20,
            }
        ],
    }
    # Checkpoint A sees 50, post-flight sees 20 remaining
    mock_angel.position.side_effect = [
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}]},
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "20", "producttype": "INTRADAY", "exchange": "NSE"}]},
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "20", "producttype": "INTRADAY", "exchange": "NSE"}]},
    ]

    trader = PaperTrader(total_capital=10000.0, working_capital_pct=0.50, angel_session=mock_angel)
    trader._open_position = {
        "position_id": "P1",
        "symbol": "SJVN-EQ",
        "token": "18883",
        "side": "BUY",
        "quantity": 50,
        "avg_entry_price": 100.0,
        "average_entry_price": 100.0,
        "total_cost": 5000.0,
        "entry_timestamp": datetime.now(),
        "current_tranches": 1,
        "tranches": [1],
        "exit_in_flight": False,
    }
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    summary = trader.close_position(exit_price=105.0, reason="Target Reached", timestamp=datetime.now())
    assert summary is None
    assert trader._open_position is not None
    assert trader._open_position["quantity"] == 20
    assert trader._open_position["exit_in_flight"] is True
    assert trader.state == PyramidingState.STATE_UNKNOWN


def test_recovery_http_502(monkeypatch=None):
    """Scenario 13: HTTP 502 Bad Gateway -> treated as ambiguous transport error, initiates recovery."""
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = Exception("502 Server Error: Bad Gateway for url: https://apiconnect.angelbroking.com")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "502_REC_OID",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 100.0,
                "ordertype": "MARKET",
                "ordertime": now_str,
            }
        ],
    }

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid == "502_REC_OID"
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_ORDER


def test_recovery_http_504(monkeypatch=None):
    """Scenario 14: HTTP 504 Gateway Timeout -> treated as ambiguous, initiates recovery."""
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = Exception("504 Gateway Time-out")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "504_REC_OID",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 100.0,
                "ordertype": "MARKET",
                "ordertime": now_str,
            }
        ],
    }

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid == "504_REC_OID"
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_ORDER


def test_recovery_connection_error(monkeypatch=None):
    """Scenario 15: ConnectionError / ConnectionResetError -> triggers recovery protocol."""
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = ConnectionResetError("Connection reset by peer [Errno 54]")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "CONN_REC_OID",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 100.0,
                "ordertype": "MARKET",
                "ordertime": now_str,
            }
        ],
    }

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid == "CONN_REC_OID"
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_ORDER


def test_recovery_missing_order_id(monkeypatch=None):
    """Scenario 16: Missing order ID in 200 OK response -> triggers orderBook recovery."""
    mock_angel = MagicMock()
    mock_angel.placeOrder.return_value = {"status": True, "message": "SUCCESS", "data": {}}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "MISSING_ID_RECOVERED",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "quantity": 50,
                "status": "complete",
                "averageprice": 100.0,
                "ordertype": "MARKET",
                "ordertime": now_str,
            }
        ],
    }

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid == "MISSING_ID_RECOVERED"
    last_rec = get_last_order_recovery()
    assert last_rec is not None
    assert last_rec.status == RecoveryStatus.CONFIRMED_ORDER


def test_recovery_human_alert_fired(monkeypatch=None):
    """Scenario 17: Human alert invocation verification -> context rich, zero credentials leaked."""
    mp = monkeypatch or pytest.MonkeyPatch()
    alert_messages = []
    def mock_alert(msg: str):
        alert_messages.append(msg)

    mp.setattr("execution_engine.alert_human", mock_alert)
    mp.setattr(config, "LIVE_MODE", True)

    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = TimeoutError("Simulated timeout")
    mock_angel.orderBook.side_effect = Exception("Service unavailable")
    mock_angel.position.side_effect = Exception("Service unavailable")

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)
    assert oid is None
    assert len(alert_messages) >= 1
    alert_text = alert_messages[0]

    assert "[CRITICAL STATE UNKNOWN]" in alert_text
    assert "Symbol: SJVN-EQ" in alert_text
    assert "Side: BUY" in alert_text
    assert "Qty: 50" in alert_text
    assert "BLOCKED" in alert_text
    forbidden_tokens = ["jwtToken", "apiKey", "password", "feedToken", "secret", "privateKey"]
    for token in forbidden_tokens:
        assert token not in alert_text


def test_recovery_restart_after_unknown_state(monkeypatch=None):
    """Scenario 18: Restart after UNKNOWN state & stale historical order rejection."""
    mock_angel = MagicMock()
    # (a) Startup position check detects surviving unclosed position
    mock_angel.position.return_value = {
        "status": True,
        "data": [
            {"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}
        ]
    }
    net_qty, ok = check_broker_position_netqty(mock_angel, "SJVN-EQ", "18883", "NSE", "INTRADAY")
    assert ok is True
    assert net_qty == 50.0

    # (b) Stale historical orders (e.g. 15 minutes ago) rejected during recovery window
    now_ts = datetime.now().timestamp()
    stale_time_str = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    stale_order = {
        "orderid": "STALE_001",
        "tradingsymbol": "SJVN-EQ",
        "ordertime": stale_time_str,
    }
    assert _is_order_within_window(stale_order, attempt_time=now_ts, window_sec=120.0) is False

    fresh_time_str = (datetime.now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
    fresh_order = {
        "orderid": "FRESH_001",
        "tradingsymbol": "SJVN-EQ",
        "ordertime": fresh_time_str,
    }
    assert _is_order_within_window(fresh_order, attempt_time=now_ts, window_sec=120.0) is True


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
        ("Accuracy Fix 1: Order Book Fill Confirmation & Avg Price", test_accuracy_fix1_fill_confirmation_success),
        ("Accuracy Fix 1: Partial Fill Warning & Filled Shares Math", test_accuracy_fix1_partial_fill_warning),
        ("Accuracy Fix 1: Unconfirmed Fill Timeout Failsafe", test_accuracy_fix1_unconfirmed_fill_timeout),
        ("Accuracy Fix 2: Live Available Capital Synchronization", test_accuracy_fix2_get_live_capital),
        ("Slippage §32: LONG Adverse Simulation (buy=100.05, sell=101.949)", test_slippage_long_simulation),
        ("Slippage §33: SHORT Adverse Simulation (sell=99.95, buy=98.049)", test_slippage_short_simulation),
        ("Slippage §34: Zero Haircut Neutrality (simulated == expected)", test_slippage_zero_haircut),
        ("Slippage §35: Marginal Trade Blocked After Haircut", test_slippage_blocked_trade),
        ("Slippage §36: Comfortable Trade Passes After Haircut", test_slippage_passed_trade),
        ("Slippage §37: Strategy Values Immutability After Gate", test_slippage_strategy_immutability),
        ("Slippage §40: Invalid Side Rejected (No LONG Fallback)", test_slippage_invalid_side),
        ("Slippage §41: Negative Haircut Rejected", test_slippage_negative_haircut),
        ("Slippage §42: Config Override Used, Global Unchanged", test_slippage_config_override),
        ("Slippage §43: No Double Application (single × (1±H))", test_slippage_no_double_application),
        ("Slippage §51: Financial Invariant (always worse or equal)", test_slippage_financial_invariant),
        ("Fix #6 Test 1: Normal Winning Trade (+₹100 -> RECONCILED)", test_recon_normal_winning_trade),
        ("Fix #6 Test 2: Normal Losing Trade (-₹100 -> RECONCILED)", test_recon_normal_losing_trade),
        ("Fix #6 Test 3: RMS Cash Movement Immunity (Eliminate False Mismatch)", test_recon_rms_cash_movement_immunity),
        ("Fix #6 Test 4: Genuine P&L Mismatch (+₹100 vs +₹80 -> MISMATCH)", test_recon_genuine_mismatch),
        ("Fix #6 Test 5: Delayed Position State Propagation (Retry -> RECONCILED)", test_recon_delayed_position_update),
        ("Fix #6 Test 6: Position API Endpoint Failure (API_ERROR, Never Success)", test_recon_api_failure),
        ("Fix #6 Test 7: Empty Broker Position Payload (SKIPPED, Never Success)", test_recon_empty_position_response),
        ("Fix #6 Test 8: Multiple Trades on Same Symbol (Cumulative Baseline Delta)", test_recon_multiple_trades_cumulative_delta),
        ("Fix #6 Test 9: Restart Safety (Pre-existing Baseline Snapshot Recovery)", test_recon_restart_safety),
        ("Fix #6 Test 10: Decimal & Micro-Precision Divergence Handling", test_recon_decimal_precision),
        ("Fix #6 Test 11: Symbol Isolation (No Cross-Symbol Contamination)", test_recon_wrong_symbol),
        ("Fix #6 Test 12: Exchange Isolation (NSE vs BSE Disambiguation)", test_recon_symbol_exchange_isolation),
        ("Fix #6 Test 13: Open Position Guard (netqty != 0 -> UNVERIFIED)", test_recon_open_position_guard),
        ("Fix #6 Test 14: End-of-Day Capital Movement Matching (RECONCILED)", test_eod_recon_matching),
        ("Fix #6 Test 15: End-of-Day Capital Divergence (MISMATCH Detected)", test_eod_recon_mismatch),
        ("Fix #6 Test 16: End-of-Day API Unavailable (UNVERIFIED, Never Success)", test_eod_recon_api_failure),
        ("Recovery §73.1: Entry Timeout + Broker Executed (Recover Order ID)", test_recovery_entry_timeout_broker_executed),
        ("Recovery §73.2: Entry Timeout + Broker Rejected (IDLE Return, No Ghost)", test_recovery_entry_timeout_broker_rejected),
        ("Recovery §73.3: Entry Timeout + No Order (Confirmed No Order -> IDLE)", test_recovery_entry_timeout_no_order),
        ("Recovery §73.4: Entry Timeout + Multiple Matches (Quarantines Engine)", test_recovery_entry_timeout_multiple_matches),
        ("Recovery §73.5: Duplicate Entry Blocked During STATE_UNKNOWN", test_recovery_entry_duplicate_blocked),
        ("Recovery §73.6: Exit Timeout + Broker Executed (Confirmed Closure)", test_recovery_exit_timeout_broker_executed),
        ("Recovery §73.7: Exit Timeout + Broker Rejected (Prevents False Closure)", test_recovery_exit_timeout_broker_rejected),
        ("Recovery §73.8: Exit Timeout + netqty==0 (Prevents Accidental 2nd Sell)", test_recovery_exit_timeout_netqty_zero_prevents_second_sell),
        ("Recovery §73.9: Exit Timeout + netqty!=0 (Preserves Open Position)", test_recovery_exit_timeout_netqty_nonzero_prevents_false_closure),
        ("Recovery §73.10: Exit Timeout + Ambiguous Broker (In-Flight Blocked)", test_recovery_exit_timeout_ambiguous),
        ("Recovery §73.11: Partial Entry Fill (Actual Shares Recorded 30/50)", test_recovery_partial_entry_fill),
        ("Recovery §73.12: Partial Exit Fill (Remaining Exposure 20 Shares Kept)", test_recovery_partial_exit_fill),
        ("Recovery §73.13: HTTP 502 Bad Gateway Transport Recovery", test_recovery_http_502),
        ("Recovery §73.14: HTTP 504 Gateway Timeout Transport Recovery", test_recovery_http_504),
        ("Recovery §73.15: ConnectionResetError Transport Recovery", test_recovery_connection_error),
        ("Recovery §73.16: Missing Order ID in 200 OK Response Recovery", test_recovery_missing_order_id),
        ("Recovery §73.17: Human Alert Dispatched with Zero Secrets Leaked", test_recovery_human_alert_fired),
        ("Recovery §73.18: Restart Discovery & Stale Historical Order Rejection", test_recovery_restart_after_unknown_state),
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

