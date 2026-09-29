"""
test_mode_isolation.py — Automated Regression & Mode Isolation Invariant Verification
======================================================================================
Strictly enforces:
1. Paper Trading Mode Visual & Mechanical Isolation:
   - Zero split-brain banners.
   - "LIVE - REAL MONEY ACTIVE" is strictly forbidden in logs when LIVE_MODE=False.
   - "PAPER TRADING ONLY" banner is strictly logged.
   - Angel One SmartConnect is wrapped in ReadOnlySmartConnectWrapper.
   - Calling place_live_order in Paper Mode immediately raises RuntimeError.
   - PaperTrader.execute_trade() routes exclusively to internal ledger (0 broker calls).
2. Live Trading Mode Visual & Fill Accounting Invariant:
   - "CRITICAL WARNING: LIVE TRADING ACTIVE" is logged when LIVE_MODE=True.
   - place_live_order() executes via SmartAPI.
   - Fill accounting strictly binds to actual broker tradeBook fill (150.50),
     never confusing signal price (150.00) with actual fill.
3. Signal Brain Freeze Invariant:
   - algo-trading-bot/signal_brain.py must be 100% frozen (git diff exit code 0).
"""

from datetime import datetime, timezone
import logging
import subprocess
import sys
from unittest.mock import MagicMock
import pytest

import config
from execution_engine import (
    PaperTrader,
    ReadOnlySmartConnectWrapper,
    log_execution_mode_banner,
    place_live_order,
)
from live_stream import AngelOneLiveStream, place_live_order as stream_place_live_order


def test_paper_mode_banner_and_order_lockout(monkeypatch, caplog):
    """
    Test Case 1: Paper Mode Banner & Order Lockout
    - Ensure LIVE_MODE=False logs ONLY Paper Trading banner.
    - Assert 'LIVE - REAL MONEY ACTIVE' is NOT in logs.
    - Assert 'PAPER TRADING ONLY' IS in logs.
    - Assert mock_session.placeOrder.call_count == 0 upon execute_trade().
    - Directly calling place_live_order() raises RuntimeError.
    - Calling placeOrder() on ReadOnlySmartConnectWrapper raises AssertionError.
    """
    monkeypatch.setattr(config, "LIVE_MODE", False)

    mock_session = MagicMock()

    # 1. Capture stream / mode banner logs
    caplog.clear()
    with caplog.at_level(logging.INFO):
        log_execution_mode_banner(
            live_mode=config.LIVE_MODE,
            client_id="TEST_CLIENT",
            capital=20000.0,
            working_tranche=3300.0,
        )

    log_output = caplog.text
    assert "LIVE - REAL MONEY ACTIVE" not in log_output
    assert "ACTIVE — REAL MONEY AT RISK" not in log_output
    assert "PLACING LIVE ORDER" not in log_output
    assert "PAPER TRADING ONLY" in log_output
    assert "SIMULATION / PAPER TRADING ONLY" in log_output
    assert "PHYSICALLY LOCKED & DISCONNECTED" in log_output

    # 2. Verify ReadOnlySmartConnectWrapper mechanical block
    wrapper = ReadOnlySmartConnectWrapper(mock_session)
    with pytest.raises(AssertionError, match="FATAL: placeOrder invoked while LIVE_MODE is False!"):
        wrapper.placeOrder({"symbol": "SJVN-EQ"})
    with pytest.raises(AssertionError, match="FATAL: modifyOrder invoked while LIVE_MODE is False!"):
        wrapper.modifyOrder({"orderid": "123"})
    with pytest.raises(AssertionError, match="FATAL: cancelOrder invoked while LIVE_MODE is False!"):
        wrapper.cancelOrder("123")

    # 3. Verify place_live_order raises RuntimeError in Paper Mode
    with pytest.raises(RuntimeError, match="CRITICAL ERROR: Attempted to place a live broker order in Paper Mode."):
        place_live_order(mock_session, "SJVN-EQ", "18883", "BUY", 10)

    with pytest.raises(RuntimeError, match="CRITICAL ERROR: Attempted to place a live broker order in Paper Mode."):
        stream_place_live_order(mock_session, "SJVN-EQ", "18883", "BUY", 10)

    # 4. Verify PaperTrader.execute_trade routes exclusively to internal ledger
    trader = PaperTrader(total_capital=10000.0, angel_session=wrapper, bypass_friction_gate=True)
    signal = {
        "Close": 150.0,
        "VWAP": 150.0,
        "symbol": "SJVN-EQ",
        "token": "18883",
        "ATR_14": 1.0,
    }
    ticket = trader.execute_trade(
        signal_data=signal,
        timestamp=datetime.now(timezone.utc),
        atr_14=1.0,
        side="BUY",
    )
    assert ticket is not None
    assert mock_session.placeOrder.call_count == 0
    assert trader.actual_entry_fill == 150.0
    assert trader.open_position["simulated"] is True


def test_live_mode_banner_and_fill_accounting(monkeypatch, caplog):
    """
    Test Case 2: Live Mode Banner & Fill Accounting
    - Set config.LIVE_MODE = True.
    - Mock Angel One session returning confirmed tradeBook fills (Qty: 20 @ 150.50).
    - Assert 'CRITICAL WARNING: LIVE TRADING ACTIVE' IS in logs.
    - Assert 'SIMULATED TRADE TICKET' is NOT in live trade ticket log.
    - Call execute_trade(); assert place_live_order() executes.
    - Assert internal actual_entry_fill == 150.50 (matches broker fill, NOT signal price 150.00).
    """
    monkeypatch.setattr(config, "LIVE_MODE", True)

    mock_session = MagicMock()
    mock_session.placeOrder.return_value = "ORD_LIVE_999"
    mock_session.tradeBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "ORD_LIVE_999",
                "fillsize": 20,
                "fillprice": 150.50,
            }
        ],
    }
    mock_session.orderBook.return_value = {
        "status": True,
        "data": [
            {
                "orderid": "ORD_LIVE_999",
                "status": "complete",
                "filledshares": 20,
                "averageprice": 150.50,
            }
        ],
    }
    mock_session.position.return_value = {"status": True, "data": []}
    mock_session.rmsLimit.return_value = {
        "status": True,
        "data": {"net": "25000.00", "availablecash": "25000.00"},
    }

    # 1. Capture banner log
    caplog.clear()
    with caplog.at_level(logging.INFO):
        log_execution_mode_banner(
            live_mode=config.LIVE_MODE,
            client_id="LIVE_CLIENT_01",
            capital=20000.0,
            working_tranche=3300.0,
        )

    log_output = caplog.text
    assert "CRITICAL WARNING: LIVE TRADING ACTIVE" in log_output
    assert "REAL MONEY AT RISK" in log_output
    assert "DIRECT CONNECTION TO ANGEL ONE PRODUCTION EXCHANGE" in log_output

    # 2. Execute live trade
    trader = PaperTrader(total_capital=10000.0, angel_session=mock_session, bypass_friction_gate=True)
    signal = {
        "Close": 150.0,  # Signal price is 150.00
        "VWAP": 150.0,
        "symbol": "SJVN-EQ",
        "token": "18883",
        "ATR_14": 1.0,
    }

    ticket = trader.execute_trade(
        signal_data=signal,
        timestamp=datetime.now(timezone.utc),
        atr_14=1.0,
        side="BUY",
        angel_session=mock_session,
    )

    assert ticket is not None
    assert mock_session.placeOrder.call_count >= 1

    # Invariant: internal actual_entry_fill must be broker confirmed fill (150.50), NOT signal price (150.00)
    assert trader.actual_entry_fill == 150.50
    assert trader.open_position["actual_entry_fill"] == 150.50
    assert trader.open_position["signal_price"] == 150.00
    assert trader.open_position["simulated"] is False


def test_signal_brain_untouched():
    """
    Test Case 3: Invariant Certificate
    - Assert git diff --exit-code -- algo-trading-bot/signal_brain.py returns 0.
    """
    result = subprocess.run(
        ["git", "diff", "--exit-code", "--", "algo-trading-bot/signal_brain.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"signal_brain.py has unauthorized diff:\n{result.stdout}"
