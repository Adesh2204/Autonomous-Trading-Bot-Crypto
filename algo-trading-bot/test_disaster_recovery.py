"""
test_disaster_recovery.py

Offline Disaster-Recovery & Broker-State Synchronization Test Suite
for Angel One SmartAPI Intraday Trading Bot.

STRICT VERIFICATION FOR:
  Scenario A: Ghost Entry Recovery (BUY timeout -> order recovered -> position opened)
  Scenario B: Unrecoverable Entry + Human Alert (BUY timeout -> recovery failed -> STATE_UNKNOWN + alert)
  Scenario C: Ghost Exit Prevention (SELL timeout -> broker netqty=0 -> position closed, no 2nd SELL)
  Scenario D: Stranded Inventory Alert (SELL timeout -> broker netqty!=0 -> position preserved + alert)
  Scenario E: Duplicate Entry Protection (Quarantined STATE_UNKNOWN -> blocked 2nd BUY)
  Scenario F: Duplicate Exit Protection (In-flight exit -> blocked 2nd SELL)
  Scenario G: Partial Entry Fill (Preserves actual filled quantity)
  Scenario H: Partial Exit Fill (Preserves remaining open exposure + STATE_UNKNOWN)
  Scenario I: Recovery Ambiguity / Multiple Matches (Blocks arbitrary selection -> STATE_UNKNOWN)
  Scenario J: Recovery API Failure (All queries fail -> STATE_UNKNOWN + alert)
  Scenario K: Explicit Broker Rejection (Confirmed rejection distinguished from UNKNOWN)
  Scenario L: Normal Success Regression (Normal execution without false alerts)
"""

import math
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, call
import pytest
import requests.exceptions

import config
from execution_engine import (
    PaperTrader,
    PyramidingState,
    RecoveryStatus,
    OrderRecoveryResult,
    place_live_order,
    recover_broker_order,
    check_broker_position_netqty,
    alert_human,
    get_last_order_recovery,
)


@pytest.fixture(autouse=True)
def live_mode_enabler(monkeypatch):
    """Ensure LIVE_MODE is set to True for all disaster recovery tests."""
    monkeypatch.setattr(config, "LIVE_MODE", True)


def _build_dummy_position(qty: int = 50, avg_price: float = 100.0, side: str = "BUY", symbol: str = "SJVN-EQ", token: str = "18883"):
    """Helper to construct a valid production snapshot dictionary for PaperTrader._open_position."""
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    return {
        "position_id": 1,
        "symbol": symbol,
        "token": token,
        "exchange": "NSE",
        "producttype": "INTRADAY",
        "side": side,
        "quantity": qty,
        "initial_entry_price": avg_price,
        "average_entry_price": avg_price,
        "avg_entry_price": avg_price,
        "entry_notional": qty * avg_price,
        "entry_friction_total": 10.0,
        "total_cost": qty * avg_price,
        "current_tranches": 1,
        "tranches": [{"tranche_num": 1, "trade_id": 1, "quantity": qty, "entry_price": avg_price, "entry_turnover": qty * avg_price, "entry_friction": 10.0, "timestamp": t0}],
        "max_tranches": 3,
        "atr_14": 1.0,
        "entry_atr": 1.0,
        "stop_loss_distance": 2.0,
        "stop_loss_price": avg_price - 2.0 if side == "BUY" else avg_price + 2.0,
        "target_price": avg_price + 4.0 if side == "BUY" else avg_price - 4.0,
        "initial_target_price": avg_price + 4.0 if side == "BUY" else avg_price - 4.0,
        "risk_distance": 2.0,
        "projected_net_loss_at_stop": 110.0,
        "projected_net_profit_at_target": 190.0,
        "stop_exit_charges": 10.0,
        "target_exit_charges": 10.0,
        "timestamp": t0,
        "breakeven_armed": False,
        "exit_in_flight": False,
    }


# ==============================================================================
# SCENARIO A: GHOST ENTRY RECOVERY
# ==============================================================================
def test_scenario_a_ghost_entry_recovery(monkeypatch):
    """
    Test A: Ghost Entry Recovery
    Trigger: placeOrder() raises Timeout
    Broker State: BUY order exists and is complete in orderBook
    Expected: Order ID recovered, position established in HOLDING_TRANCHE_1, fill price preserved, no duplicate BUY.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("HTTPSConnectionPool Read timed out")
    
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "RECOVERED-ORDER-001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "exchange": "NSE",
                "quantity": 33,
                "status": "complete",
                "averageprice": 100.10,
                "filledshares": 33,
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }
    mock_angel.position.return_value = {
        "status": True,
        "data": [
            {
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "netqty": "33",
                "producttype": "INTRADAY",
                "exchange": "NSE",
            }
        ],
    }

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}

    # State before
    assert trader.state == PyramidingState.IDLE
    assert trader._open_position is None

    # Execute trade
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)

    # State after & Invariant Verification
    assert ticket is not None, "Trade ticket should be generated on successful order recovery"
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1, f"Expected HOLDING_TRANCHE_1, got {trader.state}"
    assert trader._pending_order_id == "RECOVERED-ORDER-001"
    assert trader._open_position is not None
    assert trader._open_position["average_entry_price"] == 100.10
    assert trader._open_position["quantity"] == 33

    # Broker Call Assertions
    assert mock_angel.placeOrder.call_count == 1, "Must call placeOrder exactly once (no duplicate BUY)"
    assert mock_angel.orderBook.call_count >= 1, "orderBook must be queried for state recovery"
    assert mock_alert.call_count == 0, "No emergency human alert should fire on clean recovery"


# ==============================================================================
# SCENARIO B: UNRECOVERABLE ENTRY + HUMAN ALERT
# ==============================================================================
def test_scenario_b_unrecoverable_entry_alert(monkeypatch):
    """
    Test B: Unrecoverable Entry + Human Alert
    Trigger: placeOrder() raises Timeout, broker queries fail / inconclusive
    Expected: Engine quarantined in STATE_UNKNOWN, alert_human called, no duplicate BUY, no ghost position.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("Connection timed out waiting for gateway")
    mock_angel.orderBook.side_effect = requests.exceptions.Timeout("OrderBook API unavailable")
    mock_angel.position.side_effect = requests.exceptions.Timeout("Position API unavailable")

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}

    # State before
    assert trader.state == PyramidingState.IDLE
    assert trader._open_position is None

    # Execute trade
    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)

    # State after & Invariants
    assert ticket is None, "Ticket must not be issued for unresolved order"
    assert trader._open_position is None, "Local position must not be opened for unresolved order"
    assert trader.state == PyramidingState.STATE_UNKNOWN, "Engine must be quarantined in STATE_UNKNOWN"
    assert mock_angel.placeOrder.call_count == 1, "Duplicate order placement must be blocked"
    assert mock_alert.call_count >= 1, "alert_human must be dispatched"

    # Verify alert context
    alert_args = [call[0][0] for call in mock_alert.call_args_list]
    assert any("CRITICAL STATE UNKNOWN" in msg for msg in alert_args)


# ==============================================================================
# SCENARIO C: GHOST EXIT PREVENTION (BROKER FLAT)
# ==============================================================================
def test_scenario_c_ghost_exit_prevention(monkeypatch):
    """
    Test C: Ghost Exit Prevention
    Trigger: Exit SELL raises Timeout, but broker position is flat (netqty=0).
    Expected: Broker-flat recognized, local position safely closed, no second SELL sent.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("Exit gateway timeout")
    
    # Checkpoint A sees netqty=50 (position open) -> proceeds with exit placeOrder -> Timeout
    # Checkpoint B sees netqty=0 (flat at broker) -> finalizes closure without 2nd SELL
    mock_angel.position.side_effect = [
        {
            "status": True,
            "data": [
                {
                    "tradingsymbol": "SJVN-EQ",
                    "symboltoken": "18883",
                    "netqty": "50",
                    "producttype": "INTRADAY",
                    "exchange": "NSE",
                }
            ],
        },
        {
            "status": True,
            "data": [
                {
                    "tradingsymbol": "SJVN-EQ",
                    "symboltoken": "18883",
                    "netqty": "0",
                    "producttype": "INTRADAY",
                    "exchange": "NSE",
                }
            ],
        },
    ]
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "EXIT_RECOVERED_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "SELL",
                "producttype": "INTRADAY",
                "status": "complete",
                "averageprice": 104.0,
                "filledshares": 50,
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    trader._open_position = _build_dummy_position(qty=50, avg_price=100.0)
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    # State before
    assert trader._open_position is not None
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1

    # Execute exit
    summary = trader.close_position(exit_price=104.0, timestamp=t0, reason="Target Hit", angel_session=mock_angel)

    # State after & Invariants
    assert summary is not None, "Position must be finalized when broker is confirmed flat"
    assert trader._open_position is None, "Local position must be cleared"
    assert trader.state == PyramidingState.CLOSED, "State must transition to CLOSED"
    assert mock_angel.placeOrder.call_count == 1, "Exactly one exit order attempted; duplicate SELL blocked"
    assert mock_angel.position.call_count >= 1, "Broker position must be verified"
    assert summary["total_quantity"] == 50
    assert summary["exit_price"] == 104.0


# ==============================================================================
# SCENARIO D: STRANDED INVENTORY ALERT (BROKER REMAINS OPEN)
# ==============================================================================
def test_scenario_d_stranded_inventory_alert(monkeypatch):
    """
    Test D: Stranded Inventory Alert
    Trigger: Exit SELL raises Timeout, and broker position remains open (netqty=50).
    Expected: Position NOT marked closed, exit_in_flight=True, engine in STATE_UNKNOWN, alert dispatched.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("Exit gateway timeout")
    # Checkpoint A sees 50 -> calls placeOrder -> Timeout -> Checkpoint B sees 50 (still open)
    mock_angel.position.return_value = {
        "status": True,
        "data": [
            {
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "netqty": "50",
                "producttype": "INTRADAY",
                "exchange": "NSE",
            }
        ],
    }
    mock_angel.orderBook.return_value = {"status": True, "data": []}

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    trader._open_position = _build_dummy_position(qty=50, avg_price=100.0)
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    # Execute exit
    summary = trader.close_position(exit_price=104.0, timestamp=t0, reason="Stop Loss", angel_session=mock_angel)

    # Invariants & Assertions
    assert summary is None, "Must NOT finalize closure while broker still reports open position"
    assert trader._open_position is not None, "Position must NOT be discarded from local tracking"
    assert trader._open_position["exit_in_flight"] is True, "exit_in_flight guard must be armed"
    assert trader.state == PyramidingState.STATE_UNKNOWN, "Engine must be quarantined in STATE_UNKNOWN"
    assert mock_angel.placeOrder.call_count == 1, "Must not blindly place second SELL"
    assert mock_alert.call_count >= 1, "Operator alert must be dispatched"

    alert_msgs = [call[0][0] for call in mock_alert.call_args_list]
    assert any("CRITICAL STATE UNKNOWN" in m and "EXIT" in m for m in alert_msgs)


# ==============================================================================
# SCENARIO E: DUPLICATE ENTRY PROTECTION
# ==============================================================================
def test_scenario_e_duplicate_entry_protection(monkeypatch):
    """
    Test E: Duplicate Entry Protection
    Simulate: Previous order unresolved -> Engine in STATE_UNKNOWN.
    Subsequent signal arrives.
    Expected: Immediately blocked without calling placeOrder.
    """
    mock_angel = MagicMock()
    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 25, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    trader._state = PyramidingState.STATE_UNKNOWN

    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}

    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)

    assert ticket is None, "Trade must be blocked in STATE_UNKNOWN"
    assert mock_angel.placeOrder.call_count == 0, "No order must be sent while quarantined"


# ==============================================================================
# SCENARIO F: DUPLICATE EXIT PROTECTION
# ==============================================================================
def test_scenario_f_duplicate_exit_protection(monkeypatch):
    """
    Test F: Duplicate Exit Protection
    Simulate: Open position has exit_in_flight=True from prior unconfirmed exit.
    Subsequent exit call occurs.
    Expected: Immediately blocked without calling placeOrder (prevents double-sell short exposure).
    """
    mock_angel = MagicMock()
    # Pre-flight position check returns netqty=50 (position open)
    mock_angel.position.return_value = {
        "status": True,
        "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}],
    }

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 30, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    trader._open_position = _build_dummy_position(qty=50, avg_price=100.0)
    trader._open_position["exit_in_flight"] = True
    trader._state = PyramidingState.STATE_UNKNOWN

    summary = trader.close_position(exit_price=104.0, timestamp=t0, reason="Stop Loss", angel_session=mock_angel)

    assert summary is None, "Close position must return None when exit is in flight"
    assert mock_angel.placeOrder.call_count == 0, "No duplicate SELL must be dispatched"


# ==============================================================================
# SCENARIO G: PARTIAL ENTRY FILL
# ==============================================================================
def test_scenario_g_partial_entry_fill(monkeypatch):
    """
    Test G: Partial Entry Fill
    Requested quantity = 33, broker filled quantity = 20.
    Expected: Position recorded with actual filled quantity (20 shares), turnover/friction calculated for 20 shares.
    """
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
                "producttype": "INTRADAY",
                "status": "complete",
                "averageprice": 100.50,
                "filledshares": 20,
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}

    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)

    assert ticket is not None
    assert trader._open_position is not None
    assert trader._open_position["quantity"] == 20, f"Expected 20 shares, got {trader._open_position['quantity']}"
    assert trader._open_position["average_entry_price"] == 100.50
    assert trader._open_position["entry_notional"] == 20 * 100.50


# ==============================================================================
# SCENARIO H: PARTIAL EXIT FILL
# ==============================================================================
def test_scenario_h_partial_exit_fill(monkeypatch):
    """
    Test H: Partial Exit Fill
    Existing position = 50, exit filled = 30, remaining broker netqty = 20.
    Expected: Trade NOT marked closed, quantity updated to 20, exit_in_flight=True, STATE_UNKNOWN, alert dispatched.
    """
    mock_angel = MagicMock()
    # Pre-flight position check returns netqty=50
    mock_angel.position.side_effect = [
        # 1. Pre-flight check
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "50", "producttype": "INTRADAY", "exchange": "NSE"}]},
        # 2. Post-fill check after partial exit fill
        {"status": True, "data": [{"tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "netqty": "20", "producttype": "INTRADAY", "exchange": "NSE"}]},
    ]
    mock_angel.placeOrder.return_value = "EXIT_PART_001"
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "EXIT_PART_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "SELL",
                "producttype": "INTRADAY",
                "status": "complete",
                "averageprice": 105.0,
                "filledshares": 30,
                "ordertype": "MARKET",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    trader._open_position = _build_dummy_position(qty=50, avg_price=100.0)
    trader._state = PyramidingState.HOLDING_TRANCHE_1

    summary = trader.close_position(exit_price=105.0, timestamp=t0, reason="Target Hit", angel_session=mock_angel)

    assert summary is None, "Partial exit must not finalize closure"
    assert trader._open_position is not None, "Position must remain open locally"
    assert trader._open_position["quantity"] == 20, f"Remaining quantity must be updated to 20, got {trader._open_position['quantity']}"
    assert trader._open_position["exit_in_flight"] is True
    assert trader.state == PyramidingState.STATE_UNKNOWN
    assert mock_alert.call_count >= 1, "Alert must be fired for partial exit fill"


# ==============================================================================
# SCENARIO I: MULTIPLE MATCHES IN ORDERBOOK (AMBIGUOUS RECOVERY)
# ==============================================================================
def test_scenario_i_multiple_recovery_matches(monkeypatch):
    """
    Test I: Multiple Matching Orders in OrderBook
    Trigger: placeOrder raises Timeout, orderBook contains 2 candidates matching the order criteria.
    Expected: Engine rejects arbitrary choice, returns STATE_UNKNOWN, alerts operator, no order ID accepted.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("Read timeout")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {"orderid": "MATCH_001", "tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "transactiontype": "BUY", "producttype": "INTRADAY", "exchange": "NSE", "quantity": 50, "status": "complete", "averageprice": 100.0, "filledshares": 50, "ordertime": now_str},
            {"orderid": "MATCH_002", "tradingsymbol": "SJVN-EQ", "symboltoken": "18883", "transactiontype": "BUY", "producttype": "INTRADAY", "exchange": "NSE", "quantity": 50, "status": "complete", "averageprice": 100.1, "filledshares": 50, "ordertime": now_str},
        ],
    }

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)

    assert oid is None, "Ambiguous multiple orders must not return an order ID"
    rec = get_last_order_recovery()
    assert rec is not None
    assert rec.status == RecoveryStatus.STATE_UNKNOWN
    assert mock_alert.call_count >= 1, "Must alert human on ambiguous multiple matches"


# ==============================================================================
# SCENARIO J: RECOVERY API FAILURE (BROKER UNREACHABLE)
# ==============================================================================
def test_scenario_j_recovery_api_failure(monkeypatch):
    """
    Test J: Recovery API Failure
    Trigger: placeOrder raises Timeout, orderBook raises ConnectionError, position raises ConnectionError.
    Expected: Does not crash, returns STATE_UNKNOWN, fires human alert, returns None.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("Initial timeout")
    mock_angel.orderBook.side_effect = requests.exceptions.ConnectionError("OrderBook offline")
    mock_angel.position.side_effect = requests.exceptions.ConnectionError("Position offline")

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)

    assert oid is None
    rec = get_last_order_recovery()
    assert rec is not None
    assert rec.status == RecoveryStatus.STATE_UNKNOWN
    assert mock_alert.call_count >= 1


# ==============================================================================
# SCENARIO K: EXPLICIT BROKER REJECTION
# ==============================================================================
def test_scenario_k_explicit_broker_rejection(monkeypatch):
    """
    Test K: Explicit Broker Rejection
    Trigger: placeOrder raises Timeout, orderBook contains matched order with status='rejected'.
    Expected: Distinguishes from UNKNOWN, returns CONFIRMED_REJECTION, returns None, no false UNKNOWN alert.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.side_effect = requests.exceptions.Timeout("Gateway timeout")
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "REJ_001",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "exchange": "NSE",
                "quantity": 50,
                "status": "rejected",
                "text": "RMS: Margin Insufficient",
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    oid = place_live_order(mock_angel, "SJVN-EQ", "18883", "BUY", 50)

    assert oid is None
    rec = get_last_order_recovery()
    assert rec is not None
    assert rec.status == RecoveryStatus.CONFIRMED_REJECTION
    assert "rejected" in rec.message.lower()
    # Confirmed rejection should NOT fire critical unknown state alert
    assert mock_alert.call_count == 0


# ==============================================================================
# SCENARIO L: NORMAL SUCCESS REGRESSION
# ==============================================================================
def test_scenario_l_normal_success_regression(monkeypatch):
    """
    Test L: Normal Success Regression
    Trigger: Normal placeOrder response with orderid, normal complete fill.
    Expected: Normal order flow unchanged, no alert fired, ticket generated, state=HOLDING_TRANCHE_1.
    """
    mock_angel = MagicMock()
    mock_angel.placeOrder.return_value = {"status": True, "data": {"orderid": "ORD_NORMAL_100"}}
    mock_angel.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "ORD_NORMAL_100",
                "tradingsymbol": "SJVN-EQ",
                "symboltoken": "18883",
                "transactiontype": "BUY",
                "producttype": "INTRADAY",
                "exchange": "NSE",
                "status": "complete",
                "averageprice": 100.0,
                "filledshares": 33,
                "ordertime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
    }

    mock_alert = MagicMock()
    monkeypatch.setattr("execution_engine.alert_human", mock_alert)

    trader = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50, angel_session=mock_angel)
    t0 = datetime(2026, 9, 15, 9, 20, tzinfo=timezone.utc)
    trader._current_date = t0.date()
    signal_data = {"VWAP": 100.0, "Close": 100.0, "symbol": "SJVN-EQ", "ATR_14": 1.0}

    ticket = trader.execute_trade(signal_data=signal_data, timestamp=t0, atr_14=1.0, side="BUY", angel_session=mock_angel)

    assert ticket is not None
    assert trader.state == PyramidingState.HOLDING_TRANCHE_1
    assert trader._pending_order_id == "ORD_NORMAL_100"
    assert mock_angel.placeOrder.call_count == 1
    assert mock_alert.call_count == 0


if __name__ == "__main__":
    pytest.main(["-v", __file__])

