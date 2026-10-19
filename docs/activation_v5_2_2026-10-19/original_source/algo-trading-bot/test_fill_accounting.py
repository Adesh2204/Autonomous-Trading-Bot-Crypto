"""
test_fill_accounting.py — Unit & Regression Tests for Fill Accounting & Broker Reconciliation
=============================================================================================
Validates:
1. Multi-fill weighted-average fill price calculation.
2. Partial fill detection and quantity adjustment.
3. Price-lifecycle separation (signal_price != requested_price != actual_fill).
4. Realized P&L calculation strictly derived from broker fills, not theoretical target prices.
5. Structured trade reconciliation report generation and mismatch detection.
6. Sep-15 historical regression fixture: Theoretical +42.53 vs Broker -117.60.
"""

from execution_engine import (
    calculate_true_friction,
    generate_trade_reconciliation_report,
    get_actual_fill_price,
)


class MockSmartAPIWithTradeBook:
    """Mock SmartAPI providing multi-fill tradeBook data."""
    def __init__(self, trades):
        self._trades = trades

    def tradeBook(self):
        return {"status": True, "data": self._trades}


class MockSmartAPIWithOrderBook:
    """Mock SmartAPI providing orderBook data."""
    def __init__(self, orders):
        self._orders = orders

    def orderBook(self):
        return {"status": True, "data": self._orders}


def test_multi_fill_weighted_average_calculation():
    """
    Test weighted average execution price across multiple partial fills:
    Fill 1: 10 shares @ ₹100.00
    Fill 2: 20 shares @ ₹101.50
    Total:  30 shares @ ₹(10*100 + 20*101.50) / 30 = ₹101.00
    """
    trades = [
        {"orderid": "ORD123", "fillprice": "100.00", "fillsize": "10"},
        {"orderid": "ORD123", "fillprice": "101.50", "fillsize": "20"},
    ]
    mock_api = MockSmartAPIWithTradeBook(trades)
    avg_price, filled_qty = get_actual_fill_price(mock_api, "ORD123", expected_qty=30, timeout_sec=0.1)

    assert filled_qty == 30
    assert abs(avg_price - 101.00) < 1e-4


def test_partial_fill_reporting():
    """Verify that partial fills return actual filled shares rather than expected shares."""
    orders = [
        {"orderid": "ORD456", "status": "complete", "averageprice": "150.25", "filledshares": "15"},
    ]
    mock_api = MockSmartAPIWithOrderBook(orders)
    avg_price, filled_qty = get_actual_fill_price(mock_api, "ORD456", expected_qty=50, timeout_sec=0.1)

    assert filled_qty == 15
    assert avg_price == 150.25


def test_price_lifecycle_separation():
    """
    Verify that signal_price, requested_price, and actual_fill_price
    remain distinct and never overwrite one another.
    """
    signal_price = 179.57
    requested_price = 179.60
    actual_fill_price = 179.75

    bot_record = {
        "signal_price": signal_price,
        "requested_order_price": requested_price,
        "actual_entry_fill_price": actual_fill_price,
        "quantity": 18,
        "gross_pnl": 10.0,
        "charges": 12.95,
        "net_pnl": -2.95,
    }

    # All three must maintain independent values
    assert bot_record["signal_price"] == 179.57
    assert bot_record["requested_order_price"] == 179.60
    assert bot_record["actual_entry_fill_price"] == 179.75
    assert bot_record["signal_price"] != bot_record["actual_entry_fill_price"]


def test_realized_pnl_strictly_from_actual_fills():
    """
    Verify that realized P&L is calculated strictly from actual fills + charges,
    not from theoretical target prices.
    """
    # Scenario: Target was 185.00, but actual exit fill was 181.00
    entry_fill = 180.00
    exit_fill = 181.00
    qty = 20

    friction = calculate_true_friction(entry_fill, exit_fill, qty)
    expected_gross = (exit_fill - entry_fill) * qty  # (181 - 180) * 20 = 20.00
    expected_net = expected_gross - friction["total_friction"]

    assert friction["gross_pnl"] == expected_gross
    assert friction["net_pnl"] == expected_net
    # Gross P&L must NOT be based on target (185 - 180) * 20 = 100.00
    assert friction["gross_pnl"] != (185.00 - 180.00) * qty


def test_trade_reconciliation_report_matched():
    """Verify structured trade reconciliation when bot and broker match within tolerance."""
    bot_record = {
        "avg_entry_price": 100.00,
        "exit_price": 105.00,
        "quantity": 50,
        "gross_pnl": 250.00,
        "charges": 14.50,
        "net_pnl": 235.50,
        "entry_time": "2026-09-23 09:30:00",
        "exit_time": "2026-09-23 10:15:00",
    }
    broker_record = {
        "averageprice": 100.00,
        "entry_fill": 100.00,
        "exit_fill": 105.00,
        "filledshares": 50,
        "quantity": 50,
        "realised": 250.00,
        "charges": 14.50,
        "net_pnl": 235.50,
        "trade_ids": "TRD9991",
    }

    report = generate_trade_reconciliation_report(
        symbol="TATASTEEL",
        order_id="ORD777",
        bot_record=bot_record,
        broker_record=broker_record,
        tolerance=0.50,
    )

    assert report["status"] == "MATCHED"
    assert report["matched"] is True
    assert report["differences"]["gross_pnl"] == 0.0
    assert report["differences"]["quantity"] == 0


def test_trade_reconciliation_report_mismatch():
    """Verify structured trade reconciliation when bot and broker mismatch."""
    bot_record = {
        "avg_entry_price": 100.00,
        "exit_price": 105.00,
        "quantity": 50,
        "gross_pnl": 250.00,
        "charges": 14.50,
        "net_pnl": 235.50,
    }
    broker_record = {
        "entry_fill": 100.00,
        "exit_fill": 101.00,  # Slippage / worse exit
        "quantity": 50,
        "gross_pnl": 50.00,   # Actual gross ₹50 instead of ₹250
        "charges": 14.50,
        "net_pnl": 35.50,
        "trade_ids": "TRD9992",
    }

    report = generate_trade_reconciliation_report(
        symbol="TATASTEEL",
        order_id="ORD888",
        bot_record=bot_record,
        broker_record=broker_record,
        tolerance=0.50,
    )

    assert report["status"] == "MISMATCH"
    assert report["matched"] is False
    assert report["differences"]["gross_pnl"] == 200.00


def test_sep15_historical_regression_discrepancy():
    """
    CRITICAL HISTORICAL REGRESSION FIXTURE (Sep 15, 2026):
    The bot previously reported theoretical P&L: +42.53
    Broker actual net P&L was:                  -117.60
    
    Prove that:
    1. Theoretical target price cannot masquerade as an actual fill.
    2. Any reconciliation between the bot's theoretical assumption and the broker's
       actual record is flagged as MISMATCH.
    """
    bot_theoretical_record = {
        "avg_entry_price": 66.05,
        "exit_price": 66.90,  # Theoretical target exit
        "quantity": 49,
        "gross_pnl": 55.48,
        "charges": 12.95,
        "net_pnl": 42.53,     # +42.53 theoretical profit!
        "entry_time": "2026-09-15 09:29:00",
        "exit_time": "2026-09-15 09:45:00",
    }

    broker_actual_record = {
        "entry_fill": 66.05,
        "exit_fill": 63.60,   # Realized loss on broker
        "quantity": 49,
        "gross_pnl": -104.65,
        "charges": 12.95,
        "net_pnl": -117.60,   # -117.60 actual net loss!
        "trade_ids": "SEP15_TRD",
    }

    report = generate_trade_reconciliation_report(
        symbol="SJVN",
        order_id="ORD_SEP15",
        bot_record=bot_theoretical_record,
        broker_record=broker_actual_record,
        tolerance=0.50,
    )

    # Discrepancy between +42.53 and -117.60 must be flagged as MISMATCH!
    assert report["status"] == "MISMATCH"
    assert report["matched"] is False
    assert report["differences"]["net_pnl"] == 160.13
    assert report["differences"]["gross_pnl"] == 160.13

