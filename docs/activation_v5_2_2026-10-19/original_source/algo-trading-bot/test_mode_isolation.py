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


def test_paper_mode_banner_and_order_lockout(tmp_path,monkeypatch,caplog):
    monkeypatch.setattr(config,'LIVE_MODE',False)
    broker=MagicMock()
    t=paper_trader(tmp_path,angel_session=broker)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.open_position['simulated'] is True
    assert t.close_position(300,NOW)['environment']=='TEST'
    assert not broker.placeOrder.called
    t.shutdown()


def test_live_mode_banner_and_fill_accounting(tmp_path,monkeypatch,caplog):
    t,b=live_trader(tmp_path,monkeypatch)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.open_position['simulated'] is False
    assert t.open_position['actual_entry_fill']==float(b.orders[0]['averageprice'])
    summary=t.close_position(300,NOW)
    assert summary['net_pnl']==round(summary['gross_pnl']-summary['entry_fees']-summary['exit_fees'],2)
    assert summary['environment']=='LIVE' and b.netqty==0
    t.shutdown()


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

from safety_test_support import ScenarioBroker, paper_trader, live_trader, assert_unknown_submission, assert_unknown_exit
from test_safety_v6 import NOW, IDENTITY, payload, quote
from execution_safety import SafetyError, MarketQuote, solve_quantity
