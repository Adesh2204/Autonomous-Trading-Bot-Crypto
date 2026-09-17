"""
==============================================================================
PRODUCTION-SAFE CAPITAL SYNC VERIFICATION TEST SUITE (§33)
==============================================================================
Tests the complete capital lifecycle and invariants:
1. Broker availablecash is strictly a pre-flight sufficiency gate, NEVER an allocation authority.
2. Bot WORKING_CAPITAL == config.WORKING_CAPITAL at all times.
3. Insufficient / missing / malformed broker cash triggers HALT + alert_human().
4. Tranche sizing (33%, 33%, 34%) and position sizing derive exclusively from config.WORKING_CAPITAL.
5. EOD summary displays raw broker balance separately with no fabricated Virtual Equity.
==============================================================================
"""

import math
import logging
from unittest.mock import MagicMock, patch
import pytest

import config
from execution_engine import (
    PaperTrader,
    get_live_capital,
    validate_broker_capital,
    alert_human,
)
from live_stream import AngelOneLiveStream


def test_scenario_1_broker_cash_equals_working_capital():
    """TEST 1: Broker Cash Exactly Equals Working Capital (₹10,000)."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "10000.00"},
    }
    engine = PaperTrader()
    assert engine.working_capital == config.WORKING_CAPITAL  # ₹10,000.00

    is_sufficient, broker_cash = validate_broker_capital(
        smart_api=mock_api,
        required_capital=config.WORKING_CAPITAL,
        engine=engine,
    )

    assert is_sufficient is True
    assert broker_cash == 10000.00
    assert engine.is_halted is False
    assert engine.working_capital == config.WORKING_CAPITAL  # Must NOT change!


def test_scenario_2_broker_cash_slightly_above_working_capital():
    """TEST 2: Broker Cash Slightly Above Working Capital (₹10,001)."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "10001.00"},
    }
    engine = PaperTrader()

    is_sufficient, broker_cash = validate_broker_capital(
        smart_api=mock_api,
        required_capital=config.WORKING_CAPITAL,
        engine=engine,
    )

    assert is_sufficient is True
    assert broker_cash == 10001.00
    assert engine.is_halted is False
    assert engine.working_capital == config.WORKING_CAPITAL  # Still ₹10,000.00


def test_scenario_3_broker_cash_far_above_working_capital():
    """TEST 3: Broker Cash Far Above Working Capital (₹50,000) — Catches Overwrite Bug."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "50000.00"},
    }
    engine = PaperTrader()
    assert engine.working_capital == 10000.00

    is_sufficient, broker_cash = validate_broker_capital(
        smart_api=mock_api,
        required_capital=config.WORKING_CAPITAL,
        engine=engine,
    )

    assert is_sufficient is True
    assert broker_cash == 50000.00
    assert engine.is_halted is False
    # CRITICAL: working_capital MUST remain ₹10,000.00, NOT ₹50,000.00!
    assert engine.working_capital == config.WORKING_CAPITAL
    assert engine.working_capital != 50000.00


def test_scenario_4_broker_cash_below_working_capital():
    """TEST 4: Broker Cash Below Working Capital (₹9,999) -> HALT + alert_human(), NO ORDER."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "9999.00"},
    }
    engine = PaperTrader()
    assert engine.is_halted is False

    with patch("execution_engine.alert_human") as mock_alert:
        is_sufficient, broker_cash = validate_broker_capital(
            smart_api=mock_api,
            required_capital=config.WORKING_CAPITAL,
            engine=engine,
        )

        assert is_sufficient is False
        assert broker_cash == 9999.00
        assert engine.is_halted is True  # Engine MUST be halted!
        assert engine.working_capital == config.WORKING_CAPITAL  # MUST NOT downsize to 9999!
        mock_alert.assert_called_once()
        alert_msg = mock_alert.call_args[0][0]
        assert "CRITICAL INSUFFICIENT FUNDS" in alert_msg
        assert "9,999.00" in alert_msg


def test_scenario_5_broker_cash_dramatically_below_working_capital():
    """TEST 5: Broker Cash Dramatically Below Working Capital (₹1,000) -> HALT + alert_human()."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "1000.00"},
    }
    engine = PaperTrader()

    with patch("execution_engine.alert_human") as mock_alert:
        is_sufficient, broker_cash = validate_broker_capital(
            smart_api=mock_api,
            required_capital=config.WORKING_CAPITAL,
            engine=engine,
        )

        assert is_sufficient is False
        assert broker_cash == 1000.00
        assert engine.is_halted is True
        assert engine.working_capital == config.WORKING_CAPITAL  # Never downsized!
        mock_alert.assert_called_once()
        assert "1,000.00" in mock_alert.call_args[0][0]


def test_scenario_6_broker_cash_extremely_high():
    """TEST 6: Broker Cash Extremely High (₹1,000,000) -> Position sizing not inflated."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "1000000.00"},
    }
    engine = PaperTrader()

    is_sufficient, broker_cash = validate_broker_capital(
        smart_api=mock_api,
        required_capital=config.WORKING_CAPITAL,
        engine=engine,
    )

    assert is_sufficient is True
    assert broker_cash == 1000000.00
    assert engine.working_capital == config.WORKING_CAPITAL  # Stays ₹10,000.00!
    assert engine.tranche_capitals == [3300.00, 3300.00, 3400.00]


def test_scenario_7_missing_broker_cash():
    """TEST 7: Missing Broker Cash (availablecash is None) -> Fail safe, HALT + alert."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": None},
    }
    engine = PaperTrader()

    with patch("execution_engine.alert_human") as mock_alert:
        is_sufficient, broker_cash = validate_broker_capital(
            smart_api=mock_api,
            required_capital=config.WORKING_CAPITAL,
            engine=engine,
        )

        assert is_sufficient is False
        assert broker_cash is None
        assert engine.is_halted is True
        assert engine.working_capital == config.WORKING_CAPITAL  # No fabricated capital
        mock_alert.assert_called_once()
        assert "CRITICAL CAPITAL SYNC FAILURE" in mock_alert.call_args[0][0]


def test_scenario_8_malformed_broker_cash():
    """TEST 8: Malformed Broker Cash (non-numeric / bool) -> Fail safe, HALT + alert."""
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "INVALID_NUMBER_XYZ"},
    }
    engine = PaperTrader()

    with patch("execution_engine.alert_human") as mock_alert:
        is_sufficient, broker_cash = validate_broker_capital(
            smart_api=mock_api,
            required_capital=config.WORKING_CAPITAL,
            engine=engine,
        )

        assert is_sufficient is False
        assert broker_cash is None
        assert engine.is_halted is True
        mock_alert.assert_called_once()


def test_scenario_9_rms_api_failure():
    """TEST 9: RMS/API Failure (Network error / Exception) -> Fail safe, HALT + alert."""
    mock_api = MagicMock()
    mock_api.rmsLimit.side_effect = Exception("504 Gateway Timeout")
    engine = PaperTrader()

    with patch("execution_engine.alert_human") as mock_alert:
        is_sufficient, broker_cash = validate_broker_capital(
            smart_api=mock_api,
            required_capital=config.WORKING_CAPITAL,
            engine=engine,
        )

        assert is_sufficient is False
        assert broker_cash is None
        assert engine.is_halted is True
        mock_alert.assert_called_once()


def test_scenario_10_position_sizing_integration():
    """
    TEST 10: Position Sizing Integration.
    With Broker = ₹50,000 and Working Capital = ₹10,000,
    verify that position sizing and tranche 1 execution strictly uses ₹3,300.00, not ₹50,000.
    """
    mock_api = MagicMock()
    mock_api.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "50000.00"},
    }
    engine = PaperTrader(total_capital=config.TOTAL_CAPITAL, working_capital_pct=0.50)
    assert engine.working_capital == 10000.00

    # Tranche 1 capital nominal fraction: 33% of ₹10,000 = ₹3,300
    assert engine.tranche_capitals[0] == 3300.00
    assert engine.tranche_capitals[1] == 3300.00
    assert engine.tranche_capitals[2] == 3400.00

    # Assume entry price = 20.00 (Yes Bank approx)
    entry_price = 20.00
    expected_qty = math.floor(3300.00 / entry_price)  # 165 shares
    # If it erroneously used broker cash (50,000), 33% would be ₹16,500 / 20 = 825 shares!

    allocated_capital = engine.tranche_capitals[0]
    calculated_qty = math.floor(allocated_capital / entry_price)
    assert calculated_qty == expected_qty == 165
    assert calculated_qty != 825


def test_scenario_11_tranche_allocation_percentages():
    """
    TEST 11: Tranche Allocation Invariant.
    Verify 33%, 33%, 34% is unchanged and calculated against config.WORKING_CAPITAL base.
    """
    engine = PaperTrader()
    assert config.TRANCHE_FRACTIONS == [0.33, 0.33, 0.34]
    assert engine.tranche_capitals[0] == 3300.00
    assert engine.tranche_capitals[1] == 3300.00
    assert engine.tranche_capitals[2] == 3400.00
    assert sum(engine.tranche_capitals) == config.WORKING_CAPITAL == 10000.00


def test_scenario_12_eod_summary_no_fabricated_virtual_equity(caplog):
    """
    TEST 12: EOD Summary Integrity.
    Verify raw broker balance is displayed separately and NO fabricated Virtual Equity exists.
    """
    mock_stream = MagicMock()
    mock_stream.paper_trader = PaperTrader()
    mock_stream.paper_trader._daily_pnl = 150.25
    mock_stream.paper_trader.working_capital = 10150.25
    mock_stream.angel_session = MagicMock()
    mock_stream.angel_session.rmsLimit.return_value = {
        "status": True,
        "data": {"availablecash": "18450.50"},
    }

    with patch("live_stream.LIVE_MODE", True):
        with caplog.at_level(logging.INFO):
            # Call the unbound method passing mock_stream as self
            AngelOneLiveStream.log_daily_summary(mock_stream, prefix="Final Daily P&L")

    log_output = caplog.text
    # 1. Must NOT contain "Virtual Equity"
    assert "Virtual Equity" not in log_output
    # 2. Must contain raw broker cash
    assert "Broker Available Cash: ₹18,450.50" in log_output
    # 3. Must contain bot working capital
    assert "Working Capital: ₹10,150.25" in log_output
    # 4. Must contain Daily P&L
    assert "Daily P&L: ₹150.25" in log_output
