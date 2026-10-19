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
def test_scenario_a_ghost_entry_recovery(tmp_path,monkeypatch):
    assert_unknown_submission(tmp_path,monkeypatch,TimeoutError('mock lost acknowledgement'))


# ==============================================================================
# SCENARIO B: UNRECOVERABLE ENTRY + HUMAN ALERT
# ==============================================================================
def test_scenario_b_unrecoverable_entry_alert(tmp_path,monkeypatch):
    t,b=live_trader(tmp_path,monkeypatch)
    alerts=MagicMock(); monkeypatch.setattr('execution_engine.alert_human',alerts)
    original=b.placeOrder
    def failed(params):
        result=original(params); b.fail_snapshot=True; raise TimeoutError('mock timeout')
    b.placeOrder=failed
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.is_halted and alerts.called and t.journal.reservations()
    assert not t.reconcile_broker('RESTART')
    t.shutdown()


# ==============================================================================
# SCENARIO C: GHOST EXIT PREVENTION (BROKER FLAT)
# ==============================================================================
def test_scenario_c_ghost_exit_prevention(tmp_path,monkeypatch):
    assert_unknown_exit(tmp_path,monkeypatch)


# ==============================================================================
# SCENARIO D: STRANDED INVENTORY ALERT (BROKER REMAINS OPEN)
# ==============================================================================
def test_scenario_d_stranded_inventory_alert(tmp_path,monkeypatch):
    b=ScenarioBroker(partial_exit=2); t,b=live_trader(tmp_path,monkeypatch,b)
    assert t.execute_trade(payload(),timestamp=NOW)
    alerts=MagicMock(); monkeypatch.setattr('execution_engine.alert_human',alerts)
    b.fail_submit=TimeoutError('mock partial exit lost acknowledgement')
    assert t.close_position(300,NOW) is None
    assert t.has_open_position and b.netqty>0 and t.is_halted and alerts.called
    assert not t.journal.trades()
    t.shutdown()


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
def test_scenario_f_duplicate_exit_protection(tmp_path,monkeypatch):
    assert_unknown_exit(tmp_path,monkeypatch)


# ==============================================================================
# SCENARIO G: PARTIAL ENTRY FILL
# ==============================================================================
def test_scenario_g_partial_entry_fill(tmp_path,monkeypatch):
    b=ScenarioBroker(partial_entry=8); t,b=live_trader(tmp_path,monkeypatch,b)
    ticket=t.execute_trade(payload(atr=4),timestamp=NOW)
    assert ticket and ticket['quantity']==8 and t.open_position['quantity']==8
    assert b.requests[-1]['quantity']=='8' and b.requests[-1]['ordertype']=='STOPLOSS_LIMIT'
    assert t.close_position(300,NOW)['filled_quantity']==8
    t.shutdown()


# ==============================================================================
# SCENARIO H: PARTIAL EXIT FILL
# ==============================================================================
def test_scenario_h_partial_exit_fill(tmp_path,monkeypatch):
    b=ScenarioBroker(partial_exit=2); t,b=live_trader(tmp_path,monkeypatch,b)
    ticket=t.execute_trade(payload(),timestamp=NOW); qty=ticket['quantity']
    assert t.close_position(300,NOW) is None
    assert t.open_position['quantity']==qty-2 and b.netqty==qty-2
    assert t.execution_state=='PARTIALLY_EXITED' and t.open_position['protection_id']
    assert not t.journal.trades()
    for _ in range(qty):
        if t.has_open_position:t.close_position(300,NOW)
    assert b.netqty==0 and len(t.journal.trades())==1
    t.shutdown()


# ==============================================================================
# SCENARIO I: MULTIPLE MATCHES IN ORDERBOOK (AMBIGUOUS RECOVERY)
# ==============================================================================
def test_scenario_i_multiple_recovery_matches(tmp_path,monkeypatch):
    t,b=live_trader(tmp_path,monkeypatch)
    row={'orderid':'duplicate','symboltoken':IDENTITY.token,'tradingsymbol':IDENTITY.trading_symbol,
        'transactiontype':'BUY','status':'open','quantity':'8','exchange':'NSE'}
    b.orders=[row,dict(row)]
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.is_halted and not b.requests
    t.shutdown()


# ==============================================================================
# SCENARIO J: RECOVERY API FAILURE (BROKER UNREACHABLE)
# ==============================================================================
def test_scenario_j_recovery_api_failure(tmp_path,monkeypatch):
    t,b=live_trader(tmp_path,monkeypatch)
    b.fail_snapshot=True
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.is_halted and not b.requests and not t.journal.trades()
    t.shutdown()


# ==============================================================================
# SCENARIO K: EXPLICIT BROKER REJECTION
# ==============================================================================
def test_scenario_k_explicit_broker_rejection(tmp_path,monkeypatch):
    t,b=live_trader(tmp_path,monkeypatch)
    b.reject=True
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.last_rejection=='BROKER_ORDER_REJECTED'
    assert not t.has_open_position and not t.journal.reservations() and not t.journal.fills()
    t.shutdown()


# ==============================================================================
# SCENARIO L: NORMAL SUCCESS REGRESSION
# ==============================================================================
def test_scenario_l_normal_success_regression(tmp_path,monkeypatch):
    t,b=live_trader(tmp_path,monkeypatch)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.execution_state=='POSITION_OPEN'
    assert t.close_position(300,NOW)
    assert t.execution_state=='ACCOUNTED' and b.netqty==0
    assert t.journal.trades()[0]['reconciliation_status']=='BROKER_QUANTITY_MATCHED'
    assert all(p['ordertype'] in {'LIMIT','STOPLOSS_LIMIT'} for p in b.requests)
    t.shutdown()


if __name__ == "__main__":
    pytest.main(["-v", __file__])


from safety_test_support import ScenarioBroker, paper_trader, live_trader, assert_unknown_submission, assert_unknown_exit
from test_safety_v6 import NOW, IDENTITY, payload, quote
from execution_safety import SafetyError, MarketQuote, solve_quantity
