"""Execution compatibility API and unchanged candle-close management base.

Public PaperTrader/ExecutionEngine use SafeTrader for a single position, confirmed
fills, central fees and durable risk/accounting. Legacy entry, scaling and closing
paths are retired. Strategy math and one-minute signals remain frozen.
"""

import csv
from dataclasses import dataclass
from enum import Enum
import logging
import math
import os
import queue
import threading
import time
from datetime import date, datetime
from typing import Any, Optional, Tuple, Union

from market_schedule import BaseMarketSchedule, NSEMarketSchedule, get_market_schedule
import config


try:
    from config import (
        TOTAL_CAPITAL,
        WORKING_CAPITAL,
        BACKUP_CAPITAL,
        RISK_PER_TRADE,
        DAILY_LOSS_LIMIT,
        TRANCHE_FRACTIONS,
        MAX_TRANCHES,
        SL_ATR_MULT,
        TP_ATR_MULT,
        BE_ATR_MULT,
        TRAIL_ATR_MULT,
        REENTRY_COOLDOWN_CANDLES,
        MIN_NET_RR,
        MIN_NET_PROFIT,
        PYRAMID_TRIGGER_ATR_MULT,
        MIN_NET_RR_NORMAL,
        MIN_NET_RR_LOW_VOL,
        LOW_VOL_ATR_PCT,
        MIN_NET_PROFIT_RS,
        BROKERAGE_PCT,
        BROKERAGE_CAP,
        BROKERAGE_MIN,
        SLIPPAGE_HAIRCUT_PCT,
        RECONCILIATION_TOLERANCE_INTRADAY,
        RECONCILIATION_TOLERANCE_EOD,
        RECONCILIATION_MAX_RETRIES,
        RECONCILIATION_RETRY_INTERVAL,
    )
except ImportError:
    TOTAL_CAPITAL = 10000.00
    WORKING_CAPITAL = 5000.00   # 50% active allocation for 3-tranche pyramiding
    BACKUP_CAPITAL = 5000.00    # Capital reserve
    RISK_PER_TRADE = 100.00     # Standard 1% account risk
    DAILY_LOSS_LIMIT = 200.00   # 2% max daily drawdown limit
    TRANCHE_FRACTIONS = [0.33, 0.33, 0.34]
    MAX_TRANCHES = 3
    SL_ATR_MULT = 2.00
    TP_ATR_MULT = 4.00
    BE_ATR_MULT = 1.00
    TRAIL_ATR_MULT = 2.00
    REENTRY_COOLDOWN_CANDLES = 10
    MIN_NET_RR = 1.2
    MIN_NET_PROFIT = 5.0
    PYRAMID_TRIGGER_ATR_MULT = 2.00
    MIN_NET_RR_NORMAL = 1.2
    MIN_NET_RR_LOW_VOL = 0.8
    LOW_VOL_ATR_PCT = 0.0010
    MIN_NET_PROFIT_RS = 5.0
    BROKERAGE_PCT = 0.001
    BROKERAGE_CAP = 20.0
    BROKERAGE_MIN = 5.0
    SLIPPAGE_HAIRCUT_PCT = 0.0005
    RECONCILIATION_TOLERANCE_INTRADAY = 0.50
    RECONCILIATION_TOLERANCE_EOD = 1.00
    RECONCILIATION_MAX_RETRIES = 3
    RECONCILIATION_RETRY_INTERVAL = 0.5

# Strategy legacy defaults
DEFAULT_STOP_LOSS_PCT = 0.0050   # 0.50% initial risk distance
DEFAULT_PROFIT_TARGET_PCT = 0.0100  # 1.00% target (1:2 R:R)
TRANCHE2_TRIGGER_PCT = 0.0030       # +0.30% unrealized gain required to unlock Tranche 2
SCALE_IN_GAIN_TRIGGER_PCT = 0.0030  # +0.30% unrealized gain required to unlock next tranche

# ── Persistent Trade Ledger Schema (13 Columns) ──────────────────────────
CSV_HEADERS = [
    "timestamp",
    "trade_id",
    "symbol",
    "tranches_filled",
    "avg_entry_price",
    "exit_price",
    "total_quantity",
    "exit_reason",
    "gross_pnl",
    "statutory_charges",
    "net_pnl",
    "net_roi_pct",
    "ending_working_capital",
]

logger = logging.getLogger(__name__)

# ── Startup Validation: SLIPPAGE_HAIRCUT_PCT ──────────────────────────────
if (not isinstance(SLIPPAGE_HAIRCUT_PCT, (int, float))
        or math.isnan(SLIPPAGE_HAIRCUT_PCT)
        or math.isinf(SLIPPAGE_HAIRCUT_PCT)
        or SLIPPAGE_HAIRCUT_PCT < 0):
    raise ValueError(
        f"SLIPPAGE_HAIRCUT_PCT must be a finite number >= 0, got: {SLIPPAGE_HAIRCUT_PCT!r}"
    )


# ---------------------------------------------------------
# PHYSICAL API ISOLATION & VISUAL TRUTH INVARIANT
# ---------------------------------------------------------
class ReadOnlySmartConnectWrapper:
    """
    Defensive proxy wrapping an Angel One SmartConnect instance in Paper Mode.
    Permits market data streaming / reads, but mechanically blocks placing,
    modifying, or cancelling orders with an immediate AssertionError.
    """
    def __init__(self, target: Any):
        self._target = target

    def placeOrder(self, *args, **kwargs):
        raise AssertionError("FATAL: placeOrder invoked while LIVE_MODE is False!")

    def modifyOrder(self, *args, **kwargs):
        raise AssertionError("FATAL: modifyOrder invoked while LIVE_MODE is False!")

    def cancelOrder(self, *args, **kwargs):
        raise AssertionError("FATAL: cancelOrder invoked while LIVE_MODE is False!")

    def __getattr__(self, name: str):
        return getattr(self._target, name)


def log_execution_mode_banner(
    live_mode: bool,
    client_id: str = "N/A",
    capital: float = TOTAL_CAPITAL,
    working_tranche: float = 3300.0,
) -> None:
    """
    Authoritative, centralized execution mode banner logger.
    Enforces 100% physical reality with zero split-brain contradiction.
    """
    if not live_mode:
        banner = (
            "\n"
            "============================================================\n"
            "📄 EXECUTION MODE : SIMULATION / PAPER TRADING ONLY\n"
            "🔒 BROKER STATUS  : READ-ONLY MARKET DATA STREAM\n"
            "🛡️ CAPITAL RISK  : ₹0.00 (ZERO REAL MONEY AT RISK)\n"
            "🚫 ORDER ROUTING  : PHYSICALLY LOCKED & DISCONNECTED\n"
            "============================================================"
        )
        logger.info(banner)
    else:
        banner = (
            "\n"
            "================================================================================\n"
            "⚠️ CRITICAL WARNING: LIVE TRADING ACTIVE — REAL MONEY AT RISK ⚠️\n"
            f"Client ID     : {client_id}\n"
            f"Live Capital  : ₹{capital:,.2f}\n"
            f"Working Tranche: ₹{working_tranche:,.2f}\n"
            "Order Routing : DIRECT CONNECTION TO ANGEL ONE PRODUCTION EXCHANGE\n"
            "================================================================================"
        )
        logger.warning(banner)



# ---------------------------------------------------------
# BROKER ORDER RECOVERY PROTOCOL & DEFENSIVE PARSER
# ---------------------------------------------------------
class RecoveryStatus(str, Enum):
    CONFIRMED_ORDER = "CONFIRMED_ORDER"
    CONFIRMED_REJECTION = "CONFIRMED_REJECTION"
    CONFIRMED_NO_ORDER = "CONFIRMED_NO_ORDER"
    STATE_UNKNOWN = "STATE_UNKNOWN"


@dataclass
class OrderRecoveryResult:
    status: RecoveryStatus
    order_id: Optional[str] = None
    filled_qty: int = 0
    average_price: float = 0.0
    message: str = ""
    order_data: Optional[dict] = None


LAST_ORDER_RECOVERY: Optional[OrderRecoveryResult] = None


def get_last_order_recovery() -> Optional[OrderRecoveryResult]:
    """Returns the most recent order recovery result."""
    return LAST_ORDER_RECOVERY


def _is_order_within_window(
    order: dict,
    attempt_time: float,
    window_sec: float = 120.0,
) -> bool:
    """
    Validates whether an orderBook record falls within a bounded window
    around attempt_time (default: 120s), rejecting stale historical orders.
    """
    raw_time = (
        order.get("ordertime")
        or order.get("updatetime")
        or order.get("exchtime")
        or order.get("order_time")
        or order.get("timestamp")
    )
    if raw_time is None or raw_time == "":
        return True

    if isinstance(raw_time, (int, float)):
        return abs(float(raw_time) - attempt_time) <= window_sec

    if isinstance(raw_time, str):
        raw_str = raw_time.strip()
        try:
            num = float(raw_str)
            return abs(num - attempt_time) <= window_sec
        except ValueError:
            pass

        dt_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d-%b-%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
        ]
        clean_str = raw_str.split(".")[0]
        for fmt in dt_formats:
            try:
                parsed_dt = datetime.strptime(clean_str, fmt)
                attempt_dt = datetime.fromtimestamp(attempt_time)
                diff = abs((parsed_dt - attempt_dt).total_seconds())
                return diff <= window_sec
            except Exception:
                pass

        time_formats = ["%H:%M:%S", "%H:%M"]
        for fmt in time_formats:
            try:
                parsed_t = datetime.strptime(clean_str, fmt).time()
                attempt_dt = datetime.fromtimestamp(attempt_time)
                order_dt = datetime.combine(attempt_dt.date(), parsed_t)
                diff = abs((order_dt - attempt_dt).total_seconds())
                return diff <= window_sec
            except Exception:
                pass

    return True


def check_broker_position_netqty(
    smart_api: Any,
    symbol: str,
    token: str = "",
    exchange: str = "NSE",
    producttype: str = "INTRADAY",
) -> tuple[Optional[float], bool]:
    """
    Queries smart_api.position() and extracts the net quantity for symbol/token.
    Returns (netqty, is_success).
    - If API call succeeds and symbol found: returns (net_qty, True).
    - If API call succeeds but symbol not present in positions list: returns (0.0, True) (flat).
    - If API call fails or raises exception: returns (None, False).
    """
    if smart_api is None or not hasattr(smart_api, "position"):
        return None, False
    try:
        resp = smart_api.position()
        if not isinstance(resp, dict):
            return None, False
        if resp.get("status") is False:
            return None, False
        data = resp.get("data")
        if data is None:
            return None, False
        if not isinstance(data, list):
            return None, False

        token_clean = str(token).strip()
        sym_clean = str(symbol).strip().upper()
        ex_clean = str(exchange).strip().upper()
        prod_clean = str(producttype).strip().upper()

        matched_rows = []
        if token_clean:
            matched_rows = [
                r for r in data
                if isinstance(r, dict)
                and str(r.get("symboltoken", "")).strip() == token_clean
                and str(r.get("exchange", "")).strip().upper() == ex_clean
                and str(r.get("producttype", "")).strip().upper() == prod_clean
            ]
        if not matched_rows:
            matched_rows = [
                r for r in data
                if isinstance(r, dict)
                and str(r.get("tradingsymbol", "")).strip().upper() == sym_clean
                and str(r.get("exchange", "")).strip().upper() == ex_clean
                and str(r.get("producttype", "")).strip().upper() == prod_clean
            ]
        if not matched_rows:
            matched_rows = [
                r for r in data
                if isinstance(r, dict)
                and str(r.get("tradingsymbol", "")).strip().upper() == sym_clean
            ]

        if not matched_rows:
            return 0.0, True

        target_row = matched_rows[0]
        net_qty = safe_float(
            target_row.get("netqty") if target_row.get("netqty") is not None else target_row.get("netquantity", 0)
        )
        return net_qty, True
    except Exception as exc:
        logger.error(f"[CHECK POSITION NETQTY ERROR] Failed to query position: {exc}")
        return None, False


def recover_broker_order(
    smart_api: Any,
    symbol: str,
    token: str,
    side: str,
    qty: int,
    exchange: str = "NSE",
    producttype: str = "INTRADAY",
    attempt_time: Optional[float] = None,
    max_attempts: int = 3,
    retry_delay: float = 0.5,
    window_sec: float = 120.0,
) -> OrderRecoveryResult:
    """
    Authoritative Broker Order Recovery Protocol.
    Searches orderBook() using strong multi-attribute identity matching:
      (tradingsymbol/symboltoken, transactiontype, exchange, producttype, quantity, time window).
    Falls back to position() verification to determine if exposure exists at the broker.
    """
    if attempt_time is None:
        attempt_time = time.time()

    if smart_api is None:
        return OrderRecoveryResult(
            status=RecoveryStatus.STATE_UNKNOWN,
            message="No active broker session provided for recovery",
        )

    order_candidates: list[dict] = []
    sym_clean = str(symbol).strip().upper()
    tok_clean = str(token).strip()
    side_clean = str(side).strip().upper()
    ex_clean = str(exchange).strip().upper()
    prod_clean = str(producttype).strip().upper()
    qty_int = int(qty)

    for attempt in range(1, max_attempts + 1):
        if not hasattr(smart_api, "orderBook"):
            break
        try:
            resp = smart_api.orderBook()
            if isinstance(resp, dict) and resp.get("status") is not False:
                data = resp.get("data")
                if isinstance(data, list):
                    order_candidates.clear()
                    for o in data:
                        if not isinstance(o, dict):
                            continue

                        # 1. Match symbol or token
                        o_sym = str(o.get("tradingsymbol", "")).strip().upper()
                        o_tok = str(o.get("symboltoken", "")).strip()
                        sym_match = (o_sym == sym_clean) or (tok_clean and o_tok == tok_clean)
                        if not sym_match:
                            continue

                        # 2. Match transactiontype (side)
                        o_side = str(o.get("transactiontype", "")).strip().upper()
                        if o_side != side_clean:
                            continue

                        # 3. Match exchange
                        o_ex = str(o.get("exchange", "")).strip().upper()
                        if ex_clean and o_ex and o_ex != ex_clean:
                            continue

                        # 4. Match producttype
                        o_prod = str(o.get("producttype", "")).strip().upper()
                        if prod_clean and o_prod and o_prod != prod_clean:
                            continue

                        # 5. Match quantity
                        o_qty = int(safe_float(o.get("quantity", 0)))
                        if o_qty > 0 and o_qty != qty_int:
                            continue

                        # 6. Check time window
                        if not _is_order_within_window(o, attempt_time, window_sec):
                            continue

                        order_candidates.append(o)

                    if order_candidates:
                        break
        except Exception as exc:
            logger.warning(f"[RECOVERY QUERY ERROR] orderBook attempt {attempt}/{max_attempts} failed: {exc}")

        if attempt < max_attempts:
            time.sleep(retry_delay)

    # Inspect results from orderBook
    if len(order_candidates) == 1:
        cand = order_candidates[0]
        rec_oid = str(cand.get("orderid", "")).strip()
        status = str(cand.get("status", "")).strip().lower()
        avg_px = safe_float(cand.get("averageprice", 0.0))
        filled_shares = int(safe_float(cand.get("filledshares", qty_int)))

        if status in ("complete", "open", "pending", "trigger pending"):
            logger.info(
                f"[RECOVERY SUCCESS] Found matching broker order {rec_oid} "
                f"with status '{status}', filled={filled_shares} @ ₹{avg_px:.2f}."
            )
            return OrderRecoveryResult(
                status=RecoveryStatus.CONFIRMED_ORDER,
                order_id=rec_oid,
                filled_qty=filled_shares,
                average_price=avg_px,
                message=f"Order {rec_oid} found in orderBook with status '{status}'",
                order_data=cand,
            )
        elif status in ("rejected", "cancelled", "canceled"):
            rej_reason = str(cand.get("text", "") or cand.get("rejectionreason", "") or status)
            logger.warning(
                f"[RECOVERY REJECTION] Found matching order {rec_oid} confirmed {status}: {rej_reason}"
            )
            return OrderRecoveryResult(
                status=RecoveryStatus.CONFIRMED_REJECTION,
                order_id=rec_oid,
                message=f"Order {rec_oid} confirmed {status}: {rej_reason}",
                order_data=cand,
            )
        else:
            logger.error(f"[RECOVERY UNEXPECTED STATUS] Order {rec_oid} has status '{status}'")
            return OrderRecoveryResult(
                status=RecoveryStatus.STATE_UNKNOWN,
                order_id=rec_oid,
                message=f"Order {rec_oid} has unhandled status '{status}'",
                order_data=cand,
            )

    elif len(order_candidates) > 1:
        oids = [str(c.get("orderid", "")) for c in order_candidates]
        logger.error(
            f"[RECOVERY AMBIGUOUS] Multiple ({len(order_candidates)}) matching orders found in orderBook: {oids}"
        )
        return OrderRecoveryResult(
            status=RecoveryStatus.STATE_UNKNOWN,
            message=f"Ambiguous matches: found {len(order_candidates)} candidates ({', '.join(oids)})",
        )

    # Cross-check broker position netqty
    broker_net_qty, pos_ok = check_broker_position_netqty(
        smart_api=smart_api,
        symbol=symbol,
        token=token,
        exchange=exchange,
        producttype=producttype,
    )

    if pos_ok:
        if broker_net_qty == 0.0:
            logger.info(
                "[RECOVERY CONFIRMED NO ORDER] No order found in orderBook and broker position netqty is 0."
            )
            return OrderRecoveryResult(
                status=RecoveryStatus.CONFIRMED_NO_ORDER,
                message="No order found in orderBook and broker position is flat (netqty=0)",
            )
        else:
            logger.critical(
                f"[RECOVERY POSITION MISMATCH] No order found in orderBook but broker netqty is {broker_net_qty}!"
            )
            return OrderRecoveryResult(
                status=RecoveryStatus.STATE_UNKNOWN,
                message=f"No order found in orderBook but broker position netqty is {broker_net_qty}",
            )

    logger.critical("[RECOVERY FAILED] Broker state unreachable or unparseable. Unknown state.")
    return OrderRecoveryResult(
        status=RecoveryStatus.STATE_UNKNOWN,
        message="Broker orderBook and position() queries failed or returned inconclusive data",
    )


def place_live_order(angel, symbol, token, side, qty, *, instrument=None, quote=None, adapter=None):
    """Legacy public entry point: require the verified execution adapter; no MARKET bypass."""
    if not config.LIVE_MODE:
        raise RuntimeError('CRITICAL ERROR: Attempted to place a live broker order in Paper Mode.')
    from execution_safety import SafetyError
    if not config.LIVE_VALIDATION_APPROVED or instrument is None or quote is None or adapter is None:
        raise SafetyError('LIVE_EXECUTION_BLOCKED')
    # A direct order lacks the engine's durable reservation and complete signal economics.
    # Keep the old import/signature for a clear failure instead of a bypass around SafeTrader.
    raise SafetyError('DIRECT_ORDER_SUBMISSION_FORBIDDEN_USE_EXECUTION_ENGINE')


def get_actual_fill_price(
    smart_api: Any,
    order_id: str,
    expected_qty: int,
    timeout_sec: float = 5.0,
    poll_interval: float = 0.5,
    max_interval: float = 2.0,
) -> tuple[Optional[float], int]:
    """
    Polls Angel One's trade book or order book until the given order is confirmed
    complete, then returns (weighted_average_price, filled_qty).

    Supports multi-fill execution:
      weighted_fill_price = sum(quantity_i * price_i) / sum(quantity_i)

    Uses increasing backoff between polls to avoid hitting Angel One's rate limits.
    Returns (None, 0) and logs a warning if not confirmed within timeout.
    Callers must NOT silently fall back to the planned price if this returns None.
    """
    if smart_api is None or not order_id:
        return None, 0

    waited = 0.0
    interval = poll_interval
    while waited < timeout_sec:
        # Check 1: Query tradeBook for multi-fill executions
        try:
            if hasattr(smart_api, "tradeBook"):
                tb_resp = smart_api.tradeBook()
                tb_data = tb_resp.get("data", []) if isinstance(tb_resp, dict) else []
                if isinstance(tb_data, list):
                    order_trades = [
                        t for t in tb_data
                        if isinstance(t, dict) and str(t.get("orderid", "")).strip() == str(order_id).strip()
                    ]
                    if order_trades:
                        total_shares = sum(
                            int(t.get("fillsize") or t.get("shares") or t.get("quantity") or 0)
                            for t in order_trades
                        )
                        if total_shares > 0:
                            total_val = sum(
                                float(t.get("fillprice") or t.get("price") or 0.0)
                                * int(t.get("fillsize") or t.get("shares") or t.get("quantity") or 0)
                                for t in order_trades
                            )
                            weighted_price = round(total_val / total_shares, 4)
                            if total_shares == expected_qty:
                                logger.info(
                                    f"[TRADE BOOK MULTI-FILL] Order {order_id} filled {total_shares} shares "
                                    f"across {len(order_trades)} fills @ weighted average ₹{weighted_price:.2f}"
                                )
                                return weighted_price, total_shares
        except Exception as e:
            logger.debug(f"[TRADE BOOK QUERY] Exception checking tradeBook: {e}")

        # Check 2: Query orderBook
        try:
            if hasattr(smart_api, "orderBook"):
                order_book_resp = smart_api.orderBook()
                order_data = order_book_resp.get("data", []) if isinstance(order_book_resp, dict) else []
                if isinstance(order_data, list):
                    for order in order_data:
                        if isinstance(order, dict):
                            oid = str(order.get("orderid", "")).strip()
                            status = str(order.get("status", "")).strip().lower()
                            if oid == str(order_id).strip() and status == "complete":
                                filled_qty = int(order.get("filledshares", expected_qty))
                                if filled_qty != expected_qty:
                                    logger.warning(
                                        f"[PARTIAL FILL] Order {order_id} filled {filled_qty}/"
                                        f"{expected_qty} shares -- P&L math must use {filled_qty}, not the requested qty."
                                    )
                                avg_price = float(order.get("averageprice", 0.0))
                                return avg_price, filled_qty
        except Exception as e:
            logger.warning(f"[ORDER BOOK POLL ERROR] Error querying order book for {order_id}: {e}")

        time.sleep(interval)
        waited += interval
        interval = min(interval * 1.5, max_interval)

    logger.warning(
        f"[FILL CHECK TIMEOUT] Order {order_id} not confirmed "
        f"complete after {timeout_sec}s -- do not assume a price."
    )
    return None, 0


def generate_trade_reconciliation_report(
    symbol: str,
    order_id: str,
    bot_record: dict,
    broker_record: dict,
    tolerance: float = RECONCILIATION_TOLERANCE_INTRADAY,
) -> dict:
    """
    Produces structured reconciliation record comparing bot internal fill records
    against Angel One's broker-confirmed trade data (Section 44 audit spec).
    """
    if broker_record.get("status") == "SIMULATED_PAPER_DISCONNECT":
        status_str = "SIMULATED_PAPER_DISCONNECT"
        report_text = f"""
TRADE RECONCILIATION
────────────────────────────────────────
Symbol:           {symbol}
Status:           SIMULATED_PAPER_DISCONNECT
Broker Real P&L:  ₹0.00
Orders Placed:    0 | Filled Shares: 0
────────────────────────────────────────"""
        logger.info(report_text)
        return {
            "status": status_str,
            "matched": True,
            "orders_placed": 0,
            "filled_shares": 0,
            "broker_real_pnl": 0.0,
            "differences": {
                "entry_price": 0.0,
                "exit_price": 0.0,
                "quantity": 0,
                "gross_pnl": 0.0,
                "charges": 0.0,
                "net_pnl": 0.0,
            },
            "report_text": report_text,
        }

    bot_entry = safe_float(bot_record.get("actual_entry_fill_price") or bot_record.get("avg_entry_price"))
    broker_entry = safe_float(broker_record.get("entry_fill") or broker_record.get("averageprice") or bot_entry)

    bot_exit = safe_float(bot_record.get("actual_exit_fill_price") or bot_record.get("exit_price"))
    broker_exit = safe_float(broker_record.get("exit_fill") or broker_record.get("averageprice") or bot_exit)

    bot_qty = int(bot_record.get("quantity") or bot_record.get("total_quantity") or 0)
    broker_qty = int(broker_record.get("quantity") or broker_record.get("filledshares") or bot_qty)

    bot_gross = safe_float(bot_record.get("gross_pnl"))
    broker_gross = safe_float(broker_record.get("gross_pnl") or broker_record.get("realised") or bot_gross)

    bot_charges = safe_float(bot_record.get("charges") or bot_record.get("statutory_charges") or 0.0)
    broker_charges = safe_float(broker_record.get("charges") or bot_charges)

    bot_net = safe_float(bot_record.get("net_pnl"))
    broker_net = safe_float(broker_record.get("net_pnl") or (broker_gross - broker_charges))

    diff_entry = round(abs(bot_entry - broker_entry), 4) if (bot_entry and broker_entry) else 0.0
    diff_exit = round(abs(bot_exit - broker_exit), 4) if (bot_exit and broker_exit) else 0.0
    diff_qty = abs(bot_qty - broker_qty)
    diff_gross = round(abs(bot_gross - broker_gross), 4) if (bot_gross is not None and broker_gross is not None) else 0.0
    diff_charges = round(abs(bot_charges - broker_charges), 4)
    diff_net = round(abs(bot_net - broker_net), 4) if (bot_net is not None and broker_net is not None) else 0.0

    matched = (diff_qty == 0) and (diff_gross <= tolerance) and (diff_entry <= tolerance)
    status_str = "MATCHED" if matched else "MISMATCH"

    report_text = f"""
TRADE RECONCILIATION
────────────────────────────────────────
Symbol:           {symbol}
Order ID:         {order_id}
Trade IDs:        {broker_record.get("trade_ids", "N/A")}

BOT RECORD
  Entry time:     {bot_record.get("entry_time", bot_record.get("timestamp", "N/A"))}
  Entry quantity: {bot_qty}
  Entry fill:     ₹{bot_entry:.2f}
  Exit time:      {bot_record.get("exit_time", bot_record.get("timestamp", "N/A"))}
  Exit quantity:  {bot_qty}
  Exit fill:      ₹{bot_exit:.2f}
  Gross P&L:      ₹{bot_gross:.2f}
  Charges:        ₹{bot_charges:.2f}
  Net P&L:        ₹{bot_net:.2f}

BROKER RECORD
  Entry:          ₹{broker_entry:.2f}
  Exit:           ₹{broker_exit:.2f}
  Quantity:       {broker_qty}
  Charges:        ₹{broker_charges:.2f}
  Net P&L:        ₹{broker_net:.2f}

DIFFERENCES
  Entry price:    ₹{diff_entry:.2f}
  Exit price:     ₹{diff_exit:.2f}
  Quantity:       {diff_qty}
  Gross P&L:      ₹{diff_gross:.2f}
  Charges:        ₹{diff_charges:.2f}
  Net P&L:        ₹{diff_net:.2f}

STATUS:           {status_str}
────────────────────────────────────────"""

    if matched:
        logger.info(report_text)
    else:
        logger.error(report_text)

    return {
        "status": status_str,
        "matched": matched,
        "differences": {
            "entry_price": diff_entry,
            "exit_price": diff_exit,
            "quantity": diff_qty,
            "gross_pnl": diff_gross,
            "charges": diff_charges,
            "net_pnl": diff_net,
        },
        "report_text": report_text,
    }



def alert_human(message: str) -> None:
    """
    Alerts human operator when unconfirmed or ambiguous order states arise.
    Logs as CRITICAL and serves as dispatch hook for notification channels.
    """
    logger.critical(f"🚨 [HUMAN INTERVENTION REQUIRED] {message}")


def get_live_capital(smart_api: Any) -> Optional[float]:
    """
    Returns real available trading cash from Angel One RMS.
    Used strictly for funds sufficiency validation and raw broker cash reporting.
    NEVER overwrites the bot's configured WORKING_CAPITAL.
    """
    if smart_api is None:
        return None
    try:
        if hasattr(smart_api, "rmsLimit"):
            funds = smart_api.rmsLimit()
            if isinstance(funds, dict) and funds.get("status") is not False:
                data = funds.get("data", {}) or {}
                raw_val = None
                if "availablecash" in data:
                    raw_val = data["availablecash"]
                elif "net" in data:
                    raw_val = data["net"]
                if raw_val is not None:
                    if isinstance(raw_val, bool):
                        logger.error(f"[RMS LIMIT] Invalid boolean availablecash: {raw_val}")
                        return None
                    try:
                        val = float(raw_val)
                        if math.isfinite(val):
                            return val
                        logger.error(f"[RMS LIMIT] Non-finite availablecash: {val}")
                        return None
                    except (ValueError, TypeError):
                        logger.error(f"[RMS LIMIT] Malformed non-numeric availablecash: {raw_val}")
                        return None
            logger.warning(f"[RMS LIMIT] Unexpected rmsLimit response: {funds}")
    except Exception as e:
        logger.error(f"[RMS LIMIT ERROR] Failed to fetch live capital: {e}")
    return None


def validate_broker_capital(
    smart_api: Any,
    required_capital: float = WORKING_CAPITAL,
    engine: Optional[Any] = None,
) -> Tuple[bool, Optional[float]]:
    """
    Validates that Angel One availablecash is sufficient to support WORKING_CAPITAL.
    Broker availablecash is used EXCLUSIVELY for pre-flight fund sufficiency validation.
    It NEVER overwrites the bot's internal WORKING_CAPITAL or active position sizing.

    Returns:
        (is_sufficient: bool, broker_available_cash: Optional[float])
    """
    broker_available_cash = get_live_capital(smart_api)

    # ── Step 1: Validate Broker Response / Numeric Normalization ────────
    if broker_available_cash is None:
        logger.critical(
            "🚨 [CAPITAL SYNC ERROR] Failed to retrieve or parse broker availablecash from Angel One RMS. "
            "Cannot verify fund sufficiency."
        )
        alert_human(
            "[CRITICAL CAPITAL SYNC FAILURE] Angel One availablecash could not be verified. Trading halted."
        )
        if engine is not None and hasattr(engine, "_halted"):
            engine._halted = True
        return False, None

    # ── Step 2: Pre-Flight Funds Sufficiency Check ──────────────────────
    if broker_available_cash >= required_capital:
        logger.info(
            f"[CAPITAL SYNC ✅] Broker balance (₹{broker_available_cash:,.2f}) covers Working Capital (₹{required_capital:,.2f})."
        )
        return True, broker_available_cash
    else:
        logger.critical(
            f"⛔ [CRITICAL INSUFFICIENT FUNDS] Broker available cash: ₹{broker_available_cash:,.2f} < "
            f"Required Working Capital: ₹{required_capital:,.2f}. Trading halted."
        )
        alert_human(
            f"[CRITICAL INSUFFICIENT FUNDS] Broker available cash: ₹{broker_available_cash:,.2f} < "
            f"Required Working Capital: ₹{required_capital:,.2f}. Trading halted."
        )
        if engine is not None and hasattr(engine, "_halted"):
            engine._halted = True
        return False, broker_available_cash


class ReconciliationStatus(str, Enum):
    RECONCILED = "RECONCILED"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"
    API_ERROR = "API_ERROR"
    DATA_ERROR = "DATA_ERROR"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely converts input to float, guarding against None, invalid strings, and binary float issues."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


_GLOBAL_RECONCILIATION_BASELINES: dict[str, float] = {}


def init_reconciliation_baselines(
    smart_api: Any,
    baselines: Optional[dict] = None,
) -> dict:
    """
    Initializes reconciliation baselines from live broker position() state.
    Essential for restart safety: captures any pre-existing realized P&L from earlier
    trades so that subsequent trades are evaluated strictly against the delta.
    """
    if baselines is None:
        baselines = _GLOBAL_RECONCILIATION_BASELINES
    if smart_api is None:
        return baselines
    try:
        if hasattr(smart_api, "position"):
            resp = smart_api.position()
            if isinstance(resp, dict) and resp.get("status") is not False:
                data = resp.get("data")
                if isinstance(data, list):
                    for row in data:
                        token = str(row.get("symboltoken", "")).strip()
                        sym = str(row.get("tradingsymbol", "")).strip().upper()
                        ex = str(row.get("exchange", "NSE")).strip().upper()
                        prod = str(row.get("producttype", "INTRADAY")).strip().upper()
                        realised = safe_float(row.get("realised") if "realised" in row else row.get("realized", 0.0))
                        if token:
                            baselines[f"{ex}:{token}:{prod}"] = realised
                        if sym:
                            baselines[f"{ex}:{sym}:{prod}"] = realised
                    logger.info(f"[RECONCILIATION BASELINE INITIALIZED] Baselines snapshot captured from broker.")
    except Exception as exc:
        logger.warning(f"[RECONCILIATION BASELINE ERROR] Failed to fetch position baseline: {exc}")
    return baselines


def reconcile_trade_intraday(
    smart_api: Any,
    symbol: str,
    logged_gross_pnl: float,
    trade_context: Optional[dict] = None,
    tolerance: float = RECONCILIATION_TOLERANCE_INTRADAY,
    max_retries: int = RECONCILIATION_MAX_RETRIES,
    retry_interval: float = RECONCILIATION_RETRY_INTERVAL,
    baselines: Optional[dict] = None,
) -> dict:
    """
    Layer A — Intraday Trade Reconciliation (Fix #6)
    Executed immediately after each completed trade.
    Compares logged_gross_pnl against broker realised P&L delta from smart_api.position().
    Strictly decouples trade-level gross P&L from account-level RMS availablecash.
    """
    if baselines is None:
        baselines = _GLOBAL_RECONCILIATION_BASELINES

    ctx = trade_context or {}
    trade_id = ctx.get("trade_id", "N/A")
    token = str(ctx.get("token", "")).strip()
    exchange = str(ctx.get("exchange", "NSE")).strip().upper()
    producttype = str(ctx.get("producttype", "INTRADAY")).strip().upper()
    sym_clean = symbol.strip().upper()

    pos_key = f"{exchange}:{token}:{producttype}" if token else f"{exchange}:{sym_clean}:{producttype}"
    alias_key = f"{exchange}:{sym_clean}:{producttype}" if token else None

    if smart_api is None:
        logger.warning("[RECONCILIATION SKIPPED] No SmartAPI broker session provided.")
        return {
            "status": ReconciliationStatus.SKIPPED,
            "trade_id": trade_id,
            "symbol": symbol,
            "logged_gross_pnl": logged_gross_pnl,
            "broker_realised_before": 0.0,
            "broker_realised_after": 0.0,
            "broker_realised_delta": 0.0,
            "difference": 0.0,
            "tolerance": tolerance,
        }

    for attempt in range(1, max_retries + 1):
        try:
            if not hasattr(smart_api, "position"):
                logger.warning("[RECONCILIATION SKIPPED] SmartAPI client does not implement position().")
                return {
                    "status": ReconciliationStatus.SKIPPED,
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "logged_gross_pnl": logged_gross_pnl,
                    "difference": 0.0,
                    "tolerance": tolerance,
                }

            resp = smart_api.position()
        except Exception as exc:
            logger.error(f"[RECONCILIATION API ERROR] position() request failed: {exc}. Trade remains unverified.")
            return {
                "status": ReconciliationStatus.API_ERROR,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "error": str(exc),
                "tolerance": tolerance,
            }

        if not isinstance(resp, dict):
            logger.warning(f"[RECONCILIATION SKIPPED] position() returned non-dict response: {type(resp)}")
            return {
                "status": ReconciliationStatus.SKIPPED,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "tolerance": tolerance,
            }

        if resp.get("status") is False:
            err_msg = resp.get("message", "Unknown error")
            if attempt < max_retries:
                time.sleep(retry_interval)
                continue
            logger.error(f"[RECONCILIATION API ERROR] position() returned status False: {err_msg}")
            return {
                "status": ReconciliationStatus.API_ERROR,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "error": err_msg,
                "tolerance": tolerance,
            }

        data = resp.get("data")
        if data is None:
            if attempt < max_retries:
                time.sleep(retry_interval)
                continue
            logger.warning("[RECONCILIATION SKIPPED] No data field in position response.")
            return {
                "status": ReconciliationStatus.SKIPPED,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "tolerance": tolerance,
            }

        if not isinstance(data, list):
            logger.error(f"[RECONCILIATION DATA_ERROR] Expected list in position data, got {type(data)}")
            return {
                "status": ReconciliationStatus.DATA_ERROR,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "tolerance": tolerance,
            }

        if len(data) == 0:
            if attempt < max_retries:
                time.sleep(retry_interval)
                continue
            logger.warning("[RECONCILIATION SKIPPED] No positions returned in broker response.")
            return {
                "status": ReconciliationStatus.SKIPPED,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "tolerance": tolerance,
            }

        # Hierarchy Matching (Section 8)
        matched_rows = []
        if token:
            matched_rows = [
                r for r in data
                if str(r.get("symboltoken", "")).strip() == token
                and str(r.get("exchange", "")).strip().upper() == exchange
                and str(r.get("producttype", "")).strip().upper() == producttype
            ]
        if not matched_rows:
            matched_rows = [
                r for r in data
                if str(r.get("tradingsymbol", "")).strip().upper() == sym_clean
                and str(r.get("exchange", "")).strip().upper() == exchange
                and str(r.get("producttype", "")).strip().upper() == producttype
            ]
        if not matched_rows:
            matched_rows = [
                r for r in data
                if str(r.get("tradingsymbol", "")).strip().upper() == sym_clean
            ]

        if not matched_rows:
            if attempt < max_retries:
                time.sleep(retry_interval)
                continue
            logger.warning(
                f"[RECONCILIATION SKIPPED] No matching broker position found for {sym_clean} "
                f"(token={token}, exchange={exchange}, product={producttype})."
            )
            return {
                "status": ReconciliationStatus.SKIPPED,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "tolerance": tolerance,
            }

        target_row = matched_rows[0]

        # Guard: Check if position is still open (Section 39)
        net_qty = safe_float(target_row.get("netqty") or target_row.get("netquantity", 0))
        if net_qty != 0:
            if attempt < max_retries:
                logger.info(
                    f"[RECONCILIATION PENDING] Position netqty={net_qty} != 0. "
                    f"Waiting for square-off to settle. Retry {attempt}/{max_retries}."
                )
                time.sleep(retry_interval)
                continue
            logger.warning(
                f"[RECONCILIATION UNVERIFIED] Position netqty={net_qty} != 0 (open position). "
                f"Trade remains unverified as closed."
            )
            return {
                "status": ReconciliationStatus.UNVERIFIED,
                "trade_id": trade_id,
                "symbol": symbol,
                "logged_gross_pnl": logged_gross_pnl,
                "net_qty": net_qty,
                "tolerance": tolerance,
            }

        # Extract realized P&L from broker
        realised_str = target_row.get("realised") if "realised" in target_row else target_row.get("realized", 0.0)
        current_broker_realised = safe_float(realised_str)
        previous_broker_realised = baselines.get(pos_key, baselines.get(alias_key, 0.0))
        broker_trade_realised_delta = round(current_broker_realised - previous_broker_realised, 4)

        # Freshness Check (Section 13, 40, 41):
        # If broker realized delta is 0 but logged gross PnL is non-zero, broker position may not have updated yet
        if abs(broker_trade_realised_delta) < 1e-6 and abs(logged_gross_pnl) > tolerance:
            if attempt < max_retries:
                logger.info(
                    f"[RECONCILIATION PENDING]\n"
                    f"Broker position state has not yet reflected the completed trade.\n"
                    f"Retry attempt: {attempt}/{max_retries}"
                )
                time.sleep(retry_interval * (1.5 ** (attempt - 1)))
                continue
            else:
                logger.warning(
                    f"[RECONCILIATION UNVERIFIED]\n"
                    f"Trade ID: {trade_id}\n"
                    f"Symbol: {symbol}\n"
                    f"Broker position state did not update after {max_retries} attempts.\n"
                    f"Trade remains unverified."
                )
                return {
                    "status": ReconciliationStatus.UNVERIFIED,
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "logged_gross_pnl": logged_gross_pnl,
                    "broker_realised_before": previous_broker_realised,
                    "broker_realised_after": current_broker_realised,
                    "broker_realised_delta": broker_trade_realised_delta,
                    "difference": round(abs(broker_trade_realised_delta - logged_gross_pnl), 4),
                    "tolerance": tolerance,
                }

        diff = round(abs(broker_trade_realised_delta - logged_gross_pnl), 4)

        if diff <= tolerance:
            status = ReconciliationStatus.RECONCILED
            baselines[pos_key] = current_broker_realised
            if alias_key:
                baselines[alias_key] = current_broker_realised
            logger.info(
                f"[RECONCILIATION]\n"
                f"Trade ID: {trade_id}\n"
                f"Symbol: {symbol}\n"
                f"Logged Gross P&L: ₹{logged_gross_pnl:.2f}\n"
                f"Broker Realised Before: ₹{previous_broker_realised:.2f}\n"
                f"Broker Realised After: ₹{current_broker_realised:.2f}\n"
                f"Broker Realised Delta: ₹{broker_trade_realised_delta:.2f}\n"
                f"Difference: ₹{diff:.2f}\n"
                f"Status: RECONCILED"
            )
        else:
            status = ReconciliationStatus.MISMATCH
            logger.error(
                f"[RECONCILIATION MISMATCH]\n"
                f"Trade ID: {trade_id}\n"
                f"Symbol: {symbol}\n"
                f"Logged Gross P&L: ₹{logged_gross_pnl:.2f}\n"
                f"Broker Realised Before: ₹{previous_broker_realised:.2f}\n"
                f"Broker Realised After: ₹{current_broker_realised:.2f}\n"
                f"Broker Realised Delta: ₹{broker_trade_realised_delta:.2f}\n"
                f"Difference: ₹{diff:.2f}\n"
                f"Tolerance: ₹{tolerance:.2f}"
            )

        return {
            "status": status,
            "trade_id": trade_id,
            "symbol": symbol,
            "logged_gross_pnl": logged_gross_pnl,
            "broker_realised_before": previous_broker_realised,
            "broker_realised_after": current_broker_realised,
            "broker_realised_delta": broker_trade_realised_delta,
            "difference": diff,
            "tolerance": tolerance,
        }

    return {
        "status": ReconciliationStatus.UNVERIFIED,
        "trade_id": trade_id,
        "symbol": symbol,
        "logged_gross_pnl": logged_gross_pnl,
        "tolerance": tolerance,
    }


def reconcile_end_of_day(
    smart_api: Any,
    opening_capital: float,
    logged_daily_net_pnl: float,
    closing_snapshot: Optional[float] = None,
    tolerance: float = RECONCILIATION_TOLERANCE_EOD,
) -> dict:
    """
    Layer B — End-of-Day Account Reconciliation (Fix #6)
    Executed once after all trading and square-offs are complete.
    Compares account-level capital movement against cumulative session net P&L.
    """
    closing_capital = None
    if closing_snapshot is not None:
        closing_capital = safe_float(closing_snapshot)
    elif smart_api is not None:
        try:
            if hasattr(smart_api, "rmsLimit"):
                funds = smart_api.rmsLimit()
                if isinstance(funds, dict) and funds.get("status") is not False:
                    data = funds.get("data", {}) or {}
                    if "availablecash" in data:
                        closing_capital = safe_float(data["availablecash"])
                    elif "net" in data:
                        closing_capital = safe_float(data["net"])
                else:
                    closing_capital = None
            else:
                closing_capital = None
        except Exception as exc:
            logger.error(f"[EOD RECONCILIATION ERROR] Failed to fetch closing capital: {exc}")
            closing_capital = None

    if closing_capital is None:
        logger.warning("[EOD RECONCILIATION UNVERIFIED] Closing capital unavailable from broker.")
        return {
            "status": ReconciliationStatus.UNVERIFIED,
            "opening_capital": opening_capital,
            "closing_capital": None,
            "broker_capital_change": None,
            "logged_daily_net_pnl": logged_daily_net_pnl,
            "difference": None,
            "tolerance": tolerance,
        }

    broker_capital_change = round(closing_capital - opening_capital, 4)
    diff = round(abs(broker_capital_change - logged_daily_net_pnl), 4)
    is_reconciled = diff <= tolerance
    status = ReconciliationStatus.RECONCILED if is_reconciled else ReconciliationStatus.MISMATCH

    logger.info("════════════════════════════════════════════════════════════")
    logger.info("  📊 END-OF-DAY RECONCILIATION SUMMARY")
    logger.info(f"  Opening Capital: ₹{opening_capital:,.2f}")
    logger.info(f"  Closing Capital: ₹{closing_capital:,.2f}")
    logger.info(f"  Broker Day P&L : ₹{broker_capital_change:,.2f}")
    logger.info(f"  Bot Logged P&L : ₹{logged_daily_net_pnl:,.2f}")
    logger.info(f"  Difference     : ₹{diff:,.2f}")
    if is_reconciled:
        logger.info(f"  Status         : RECONCILED ✅ (within ₹{tolerance:.2f} tolerance)")
    else:
        logger.error(f"  Status         : MISMATCH ❌ (diff ₹{diff:.2f} > ₹{tolerance:.2f})")
    logger.info("════════════════════════════════════════════════════════════")

    return {
        "status": status,
        "opening_capital": opening_capital,
        "closing_capital": closing_capital,
        "broker_capital_change": broker_capital_change,
        "logged_daily_net_pnl": logged_daily_net_pnl,
        "difference": diff,
        "tolerance": tolerance,
    }


def reconcile_trade(
    capital_before: float,
    capital_after: float,
    logged_net_pnl: float,
    tolerance: float = 5.00,
) -> bool:
    """
    [DEPRECATED] Legacy per-trade cash comparison.
    Do NOT use in live intraday execution -- replaced by reconcile_trade_intraday()
    which uses broker position() realized P&L delta, and reconcile_end_of_day()
    which reconciles account-level capital.
    Retained solely for backward compatibility with legacy unit tests.
    """
    real_pnl = capital_after - capital_before
    diff = abs(real_pnl - logged_net_pnl)

    if diff > tolerance:
        logger.error(
            f"[RECONCILIATION MISMATCH] Bot logged ₹{logged_net_pnl:.2f}, "
            f"real balance moved by ₹{real_pnl:.2f} (diff ₹{diff:.2f}). "
            f"Trust the broker figure, not the bot's own log."
        )
    else:
        logger.info(f"[RECONCILED ✅] Bot ₹{logged_net_pnl:.2f} ≈ Real ₹{real_pnl:.2f}")
    return diff <= tolerance


# ---------------------------------------------------------
# ACCURATE ANGEL ONE NSE EQUITY INTRADAY COST MODEL
# Rates verified against angelone.in/exchange-transaction-charges
# on 2026-09-16. Reconciled against actual ₹116.60 bill.
# ---------------------------------------------------------
def calculate_true_friction(buy_price: float, sell_price: float, qty: int) -> dict:
    """Compatibility API backed by the single per-order fee implementation."""
    from execution_safety import FeeModel
    if qty <= 0:
        return {k: 0.0 for k in ('gross_pnl','brokerage','stt','exchange_txn_charge','stamp_duty','sebi_fee','ipft','gst','total_friction','net_pnl')}
    fees=FeeModel(); buy=fees.leg('BUY',buy_price,qty); sell=fees.leg('SELL',sell_price,qty)
    gross=(sell_price-buy_price)*qty
    total=buy['total_charges']+sell['total_charges']
    result={k:round(buy[k]+sell[k],6 if k=='ipft' else 2) for k in ('brokerage','stt','stamp_duty','sebi_fee','ipft','gst')}
    result.update(gross_pnl=round(gross,2),exchange_txn_charge=round(buy['exchange_fee']+sell['exchange_fee'],2),
                  total_friction=round(total,2),net_pnl=round(gross-total,2))
    return result


def validate_trade_margin(
    entry_price: float,
    target_price: float,
    qty: int,
    side: str = "SHORT",
    slippage_pct: Optional[float] = None,
) -> bool:
    """
    Pre-trade Friction Gate with Slippage Haircut Simulation.

    Applies a configured adverse execution haircut to BOTH entry and exit
    prices, then passes the penalised simulated prices into
    calculate_true_friction() to determine whether the projected net P&L
    clears MIN_NET_PROFIT.

    The haircut is a simulation-only financial penalty — it never reaches
    live order payloads or alters strategy state.

    Args:
        entry_price: Strategy's expected entry price (never modified).
        target_price: Strategy's expected exit/target price (never modified).
        qty: Number of shares.
        side: "LONG"/"BUY" or "SHORT"/"SELL".
        slippage_pct: Override haircut. None → use SLIPPAGE_HAIRCUT_PCT from config.

    Returns:
        True if projected net P&L >= MIN_NET_PROFIT, False otherwise.
    """
    # ── Step 1: Validate inputs ──────────────────────────────────────────
    if not isinstance(entry_price, (int, float)) or entry_price <= 0:
        logger.error(
            f"[FRICTION GATE ERROR] Invalid entry_price: {entry_price}"
        )
        return False
    if not isinstance(target_price, (int, float)) or target_price <= 0:
        logger.error(
            f"[FRICTION GATE ERROR] Invalid target_price: {target_price}"
        )
        return False
    if not isinstance(qty, (int, float)) or qty <= 0:
        logger.error(f"[FRICTION GATE ERROR] Invalid qty: {qty}")
        return False

    side_upper = side.upper() if isinstance(side, str) else ""
    if side_upper not in {"LONG", "SHORT", "BUY", "SELL"}:
        logger.error(f"[FRICTION GATE ERROR] Invalid trade side: {side}")
        return False

    # ── Step 2: Resolve configured haircut ────────────────────────────────
    if slippage_pct is None:
        slippage_pct = SLIPPAGE_HAIRCUT_PCT

    if (not isinstance(slippage_pct, (int, float))
            or math.isnan(slippage_pct)
            or math.isinf(slippage_pct)):
        logger.error(
            f"[FRICTION GATE ERROR] Invalid slippage_pct: {slippage_pct}"
        )
        return False
    if slippage_pct < 0:
        logger.error(
            f"[FRICTION GATE ERROR] Negative slippage_pct ({slippage_pct}) "
            f"rejected — haircut must be >= 0"
        )
        return False

    # ── Step 3: Preserve original prices (never mutated) ──────────────────
    expected_entry_price = entry_price
    expected_exit_price = target_price

    # ── Step 4: Compute adverse simulated prices ──────────────────────────
    if side_upper in {"LONG", "BUY"}:
        # LONG: Buy more expensively, sell more cheaply
        simulated_buy_price = expected_entry_price * (1.0 + slippage_pct)
        simulated_sell_price = expected_exit_price * (1.0 - slippage_pct)
        buy_price = simulated_buy_price
        sell_price = simulated_sell_price
    else:
        # SHORT: Sell at lower price (entry), buy back at higher price (exit)
        simulated_sell_price = expected_entry_price * (1.0 - slippage_pct)
        simulated_buy_price = expected_exit_price * (1.0 + slippage_pct)
        buy_price = simulated_buy_price
        sell_price = simulated_sell_price

    # ── Step 5: Call existing friction engine (unchanged) ─────────────────
    costs = calculate_true_friction(buy_price, sell_price, qty)

    # ── Step 6: Decision against MIN_NET_PROFIT threshold ─────────────────
    haircut_display = f"{slippage_pct * 100:.4f}%"

    if costs["net_pnl"] >= MIN_NET_PROFIT:
        if side_upper in {"LONG", "BUY"}:
            logger.info(
                f"[FRICTION GATE PASSED] Slippage Haircut: {haircut_display} | "
                f"Expected Entry: ₹{expected_entry_price:.2f}, "
                f"Simulated BUY Entry: ₹{simulated_buy_price:.4f} | "
                f"Expected Exit: ₹{expected_exit_price:.2f}, "
                f"Simulated SELL Exit: ₹{simulated_sell_price:.4f} | "
                f"Qty: {qty} | "
                f"Gross P&L: ₹{costs['gross_pnl']}, "
                f"Friction: ₹{costs['total_friction']}, "
                f"Net P&L: ₹{costs['net_pnl']} | "
                f"Min Required: ₹{MIN_NET_PROFIT:.2f}"
            )
        else:
            logger.info(
                f"[FRICTION GATE PASSED] Slippage Haircut: {haircut_display} | "
                f"Expected Short Entry: ₹{expected_entry_price:.2f}, "
                f"Simulated SELL Entry: ₹{simulated_sell_price:.4f} | "
                f"Expected Buyback: ₹{expected_exit_price:.2f}, "
                f"Simulated BUY Exit: ₹{simulated_buy_price:.4f} | "
                f"Qty: {qty} | "
                f"Gross P&L: ₹{costs['gross_pnl']}, "
                f"Friction: ₹{costs['total_friction']}, "
                f"Net P&L: ₹{costs['net_pnl']} | "
                f"Min Required: ₹{MIN_NET_PROFIT:.2f}"
            )
        return True

    # ── BLOCKED — projected net P&L below threshold ───────────────────────
    if side_upper in {"LONG", "BUY"}:
        logger.warning(
            f"[FRICTION GATE BLOCKED] Slippage Haircut: {haircut_display} | "
            f"Expected Entry: ₹{expected_entry_price:.2f}, "
            f"Simulated BUY Entry: ₹{simulated_buy_price:.4f} | "
            f"Expected Exit: ₹{expected_exit_price:.2f}, "
            f"Simulated SELL Exit: ₹{simulated_sell_price:.4f} | "
            f"Qty: {qty} | "
            f"Projected Net P&L: ₹{costs['net_pnl']}, "
            f"Required Min: ₹{MIN_NET_PROFIT:.2f}, "
            f"Friction: ₹{costs['total_friction']} | "
            f"Reason: projected net P&L does not survive the configured "
            f"slippage haircut and existing transaction costs."
        )
    else:
        logger.warning(
            f"[FRICTION GATE BLOCKED] Slippage Haircut: {haircut_display} | "
            f"Expected Short Entry: ₹{expected_entry_price:.2f}, "
            f"Simulated SELL Entry: ₹{simulated_sell_price:.4f} | "
            f"Expected Buyback: ₹{expected_exit_price:.2f}, "
            f"Simulated BUY Exit: ₹{simulated_buy_price:.4f} | "
            f"Qty: {qty} | "
            f"Projected Net P&L: ₹{costs['net_pnl']}, "
            f"Required Min: ₹{MIN_NET_PROFIT:.2f}, "
            f"Friction: ₹{costs['total_friction']} | "
            f"Reason: projected net P&L does not survive the configured "
            f"slippage haircut and existing transaction costs."
        )
    return False


class PyramidingState(str, Enum):
    """Explicit multi-tranche pyramiding state machine."""
    IDLE = "IDLE"
    HOLDING_TRANCHE_1 = "HOLDING_TRANCHE_1"
    HOLDING_TRANCHE_2 = "HOLDING_TRANCHE_2"
    MAX_TRANCHES_HELD = "MAX_TRANCHES_HELD"
    CLOSED = "CLOSED"
    STATE_UNKNOWN = "STATE_UNKNOWN"


class LegacyPaperTrader:
    """
    Management compatibility base. Entry, scaling and accounting paths are retired.
    Public PaperTrader/ExecutionEngine resolve to the safety executor at module end.
    """

    def __init__(
        self,
        total_capital: float = TOTAL_CAPITAL,
        working_capital_pct: float = 0.50,
        daily_loss_limit: Optional[float] = None,
        daily_loss_limit_pct: float = 0.02,
        risk_per_trade: Optional[float] = None,
        risk_per_trade_pct: float = 0.01,
        stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        reward_to_risk: float = 2.0,
        slippage_pct: float = 0.0005,
        max_tranches: int = MAX_TRANCHES,
        csv_log_path: Optional[str] = None,
        schedule: Optional[BaseMarketSchedule] = None,
        angel_session: Any = None,
        **kwargs,
    ):
        # ── Market Schedule Strategy Provider ───────────────────────────
        self.schedule: BaseMarketSchedule = (
            schedule if schedule is not None else get_market_schedule("NSE")
        )

        # ── Capital Configuration ───────────────────────────────────────
        self.total_capital = total_capital
        self.working_capital = total_capital * working_capital_pct
        self.backup_capital = total_capital * (1.0 - working_capital_pct)

        # ── Risk Limits ─────────────────────────────────────────────────
        if daily_loss_limit is not None:
            self.daily_loss_limit = daily_loss_limit
        elif total_capital == TOTAL_CAPITAL:
            self.daily_loss_limit = DAILY_LOSS_LIMIT
        else:
            self.daily_loss_limit = total_capital * daily_loss_limit_pct

        if risk_per_trade is not None:
            self.risk_per_trade = risk_per_trade
        elif total_capital == TOTAL_CAPITAL:
            self.risk_per_trade = RISK_PER_TRADE
        else:
            self.risk_per_trade = total_capital * risk_per_trade_pct

        self.stop_loss_pct = stop_loss_pct
        self.reward_to_risk = reward_to_risk
        self.slippage_pct = slippage_pct
        self.max_tranches = max_tranches
        self.bypass_friction_gate = kwargs.get("bypass_friction_gate", False)

        # Compute per-tranche nominal capital partitions (33%, 33%, 34%)
        self.tranche_capitals = [
            round(self.working_capital * frac, 2)
            for frac in TRANCHE_FRACTIONS[:max_tranches]
        ]
        diff = round(self.working_capital - sum(self.tranche_capitals), 2)
        if self.tranche_capitals:
            self.tranche_capitals[-1] = round(self.tranche_capitals[-1] + diff, 2)

        # ── Persistent CSV Log ──────────────────────────────────────────
        if csv_log_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            csv_log_path = os.path.join(base_dir, "trades.csv")
        self._csv_log_path = csv_log_path
        self._init_csv_log(self._csv_log_path)

        # ── Asynchronous Background CSV Writer ──────────────────────────
        self._trade_log_queue: queue.Queue = queue.Queue()
        self._stop_writer = threading.Event()
        self._writer_thread = threading.Thread(
            target=self._csv_writer_worker,
            name="CSVWriterWorker",
            daemon=True,
        )
        self._writer_thread.start()

        # ── Daily State (resets each trading session) ───────────────────
        self._current_date: Optional[date] = None
        self._daily_pnl: float = 0.0
        self._trade_count: int = 0
        self._halted: bool = False

        # ── Position & Pyramiding State ─────────────────────────────────
        self._state: PyramidingState = PyramidingState.IDLE
        self._open_position: Optional[dict] = None
        self._trade_log: list = []
        self._pending_orders: list = []
        self._pending_order_id: Optional[str] = None
        self.angel_session: Any = angel_session
        self._latest_price: Optional[float] = None
        self._latest_timestamp: Optional[datetime] = None
        self._entry_timestamp: Optional[datetime] = None
        self.candles_held: int = 0
        self.candles_since_last_sl: int = 999
        self.reentry_cooldown_candles: int = REENTRY_COOLDOWN_CANDLES
        self.entry_atr: Optional[float] = None
        self.tranche2_trigger_pct: float = TRANCHE2_TRIGGER_PCT
        self.scale_in_gain_trigger_pct: float = SCALE_IN_GAIN_TRIGGER_PCT
        self.lock = threading.RLock()
        self.daily_bias: str = "NEUTRAL"  # Updated by live_stream on each candle close
        self._reconciliation_baselines: dict[str, float] = {}

        logging.info("=" * 60)
        logging.info("  EXECUTION MANAGEMENT INITIALIZED (single-position safety policy)")
        logging.info(f"  Total Capital     : ₹{self.total_capital:,.2f}")
        logging.info(f"  Working Capital   : ₹{self.working_capital:,.2f}")
        logging.info(f"  Backup Capital    : ₹{self.backup_capital:,.2f}")
        logging.info(f"  Daily Loss Limit  : ₹{self.daily_loss_limit:,.2f}")
        logging.info(f"  Risk Per Setup    : ≤ ₹{self.risk_per_trade:,.2f}")
        for index, capital in enumerate(self.tranche_capitals, 1):
            logging.info("  Tranche %s: ₹%.2f", index, capital)
        logging.info("  Time Stop         : PERMANENTLY DISABLED (MOC Removed)")
        logging.info(f"  Trade Log (CSV)   : {self._csv_log_path}")
        logging.info("=" * 60)

    def init_reconciliation_baselines(self, smart_api: Any = None) -> dict:
        """Query live broker positions to initialize or recover realized P&L baselines."""
        session = smart_api if smart_api is not None else self.angel_session
        return init_reconciliation_baselines(session, self._reconciliation_baselines)

    def update_daily_bias(self, bias: str) -> None:
        """Update the daily directional bias. Called from live_stream after each candle."""
        if bias != self.daily_bias:
            old = self.daily_bias
            self.daily_bias = bias
            logging.info(f"[BIAS] Daily bias changed: {old} → {bias}")

    # ────────────────────────────────────────────────────────────────────
    #  STATUTORY CHARGES & FRICTION CALCULATIONS (NSE CASH INTRADAY)
    # ────────────────────────────────────────────────────────────────────

    def calculate_entry_leg_charges(self, quantity: int, price: float) -> dict:
        from execution_safety import FeeModel
        return FeeModel().leg('BUY',price,quantity)

    def calculate_exit_leg_charges(self, quantity: int, price: float) -> dict:
        from execution_safety import FeeModel
        return FeeModel().leg('SELL',price,quantity)

    def estimate_round_trip_costs(
        self,
        quantity: int,
        entry_price: float,
        exit_price: float,
    ) -> dict:
        """Calculate complete round-trip statutory costs."""
        entry_leg = self.calculate_entry_leg_charges(quantity, entry_price)
        exit_leg = self.calculate_exit_leg_charges(quantity, exit_price)
        total_charges = entry_leg["total_charges"] + exit_leg["total_charges"]

        return {
            "buy_turnover": entry_leg["turnover"],
            "sell_turnover": exit_leg["turnover"],
            "brokerage": entry_leg["brokerage"] + exit_leg["brokerage"],
            "stt": exit_leg["stt"],
            "exchange_fee": entry_leg["exchange_fee"] + exit_leg["exchange_fee"],
            "stamp_duty": entry_leg["stamp_duty"],
            "sebi_fee": entry_leg["sebi_fee"] + exit_leg["sebi_fee"],
            "ipft": entry_leg["ipft"] + exit_leg["ipft"],
            "gst": entry_leg["gst"] + exit_leg["gst"],
            "entry_charges": entry_leg["total_charges"],
            "exit_charges": exit_leg["total_charges"],
            "total_charges": total_charges,
        }

    def calculate_friction(
        self,
        qty: int,
        entry_price: float,
        exit_price: float,
    ) -> float:
        """Public helper returning total estimated round-trip charges."""
        if qty <= 0 or entry_price <= 0 or exit_price <= 0:
            return 0.0
        return self.estimate_round_trip_costs(qty, entry_price, exit_price)["total_charges"]

    def friction_gate_check(
        self,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        qty: int,
        atr: float,
        brokerage_cost: float = 0.0,  # Legacy param — ignored, kept for call-site compat
    ) -> tuple[bool, str]:
        """
        Adaptive friction gate. Returns (passed: bool, reason: str).
        Always computes total friction dynamically from the corrected
        Angel One charge model. Relaxes R:R floor in low-volatility regimes.

        Low-vol regime: ATR / price < LOW_VOL_ATR_PCT (0.0010)
        Normal regime : ATR / price >= LOW_VOL_ATR_PCT
        """
        raw_sl_dist = abs(entry_price - sl_price)
        raw_tp_dist = abs(tp_price - entry_price)

        if raw_sl_dist <= 0:
            return False, "SL distance is zero — invalid trade"

        gross_profit = raw_tp_dist * qty
        gross_loss = raw_sl_dist * qty

        # Always compute friction dynamically — no hardcoded overrides
        entry_c = self.calculate_entry_leg_charges(qty, entry_price)["total_charges"]
        exit_c = self.calculate_exit_leg_charges(qty, tp_price)["total_charges"]
        total_friction = entry_c + exit_c

        net_profit = gross_profit - total_friction
        net_loss = gross_loss + total_friction
        actual_net_rr = net_profit / net_loss if net_loss > 0 else 0.0

        # Adaptive floor selection
        is_low_vol = (atr / entry_price) < LOW_VOL_ATR_PCT
        rr_floor = MIN_NET_RR_LOW_VOL if is_low_vol else MIN_NET_RR_NORMAL
        regime_tag = "low-vol" if is_low_vol else "normal"

        if actual_net_rr < rr_floor:
            return False, (
                f"Net R:R is 1:{actual_net_rr:.2f} "
                f"(Requires minimum 1:{rr_floor:.2f} in {regime_tag} regime)"
            )

        if net_profit < MIN_NET_PROFIT_RS:
            return False, (
                f"Net profit ₹{net_profit:.2f} < "
                f"floor ₹{MIN_NET_PROFIT_RS:.2f}"
            )

        return True, (
            f"PASSED — Net R:R 1:{actual_net_rr:.2f} "
            f"({regime_tag}), Net profit ₹{net_profit:.2f}"
        )

    # ────────────────────────────────────────────────────────────────────
    #  PYRAMIDING STATE MACHINE & EXECUTION
    # ────────────────────────────────────────────────────────────────────

    def execute_trade(self,*args,**kwargs):
        """Retired execution path; public PaperTrader resolves to SafeTrader."""
        from execution_safety import SafetyError
        raise SafetyError("LEGACY_ENTRY_PATH_DISABLED")

    def _execute_tranche_1(self,*args,**kwargs):
        """Retired execution path; public PaperTrader resolves to SafeTrader."""
        from execution_safety import SafetyError
        raise SafetyError("LEGACY_ENTRY_PATH_DISABLED")

    def _execute_tranche_2(self,*args,**kwargs):
        """Retired execution path; public PaperTrader resolves to SafeTrader."""
        from execution_safety import SafetyError
        raise SafetyError("SCALE_IN_DISABLED")

    def _execute_tranche_3(self,*args,**kwargs):
        """Retired execution path; public PaperTrader resolves to SafeTrader."""
        from execution_safety import SafetyError
        raise SafetyError("SCALE_IN_DISABLED")

    def _build_ticket(
        self,
        snapshot: dict,
        tranche_num: int,
        tranche_qty: int,
        entry_price: float,
        trade_id: int,
    ) -> dict:
        rr_ratio = f"1:{self.reward_to_risk:.1f}"
        return {
            "trade_id": trade_id,
            "position_id": snapshot["position_id"],
            "symbol": snapshot["symbol"],
            "side": snapshot.get("side", "BUY"),
            "tranche_number": tranche_num,
            "max_tranches": self.max_tranches,
            "entry_price": round(entry_price, 2),
            "signal_price": snapshot.get("signal_price", round(entry_price, 2)),
            "requested_order_price": snapshot.get("requested_order_price", round(entry_price, 2)),
            "actual_entry_fill": snapshot.get("actual_entry_fill", round(entry_price, 2)),
            "actual_fill_price": snapshot.get("actual_fill_price", round(entry_price, 2)),
            "simulated": snapshot.get("simulated", not getattr(config, "LIVE_MODE", False)),
            "quantity": tranche_qty,
            "tranche_quantity": tranche_qty,
            "avg_entry_price": round(snapshot["average_entry_price"], 2),
            "stop_loss_price": round(snapshot["stop_loss_price"], 2),
            "target_price": round(snapshot["target_price"], 2),
            "total_quantity": snapshot["quantity"],
            "total_cost": round(snapshot["total_cost"], 2),
            "risk_distance": round(snapshot["risk_distance"], 2),
            "atr_14": snapshot.get("atr_14"),
            "stop_loss_distance": snapshot.get("stop_loss_distance"),
            "risk_reward": rr_ratio,
            "potential_loss": round(snapshot["projected_net_loss_at_stop"], 2),
            "potential_profit": round(snapshot["projected_net_profit_at_target"], 2),
            "estimated_charges_at_target": round(
                snapshot["target_exit_charges"] + snapshot["entry_friction_total"], 2
            ),
            "estimated_net_loss": round(snapshot["projected_net_loss_at_stop"], 2),
            "estimated_net_profit": round(snapshot["projected_net_profit_at_target"], 2),
            "current_tranches": snapshot["current_tranches"],
            "timestamp": snapshot["timestamp"],
            "tranches": snapshot["tranches"],
        }

    # ────────────────────────────────────────────────────────────────────
    #  EXIT ENGINE & ORDER OF PRIORITY
    # ────────────────────────────────────────────────────────────────────

    def check_exit(
        self,
        live_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Evaluate exits on incoming tick in strict priority order:
          PRIORITY 1: 1:2 Profit Target Hit (live_price ≥ Global Target Price) [Instant Tick Execution]
          PRIORITY 2: Mandatory EOD Auto-Square-Off (15:20 IST)
          (Stop Loss is evaluated STRICTLY on confirmed 1-min Candle Close for Wick Immunity)
        """
        with self.lock:
            tick_timestamp = self._resolve_timestamp(timestamp)
            self._check_day_reset(tick_timestamp)
            self._set_latest_price(live_price, tick_timestamp)

            if self._open_position is None:
                return None

            pos = self._open_position

            # ── PRIORITY 1: 1:2 Profit Target Hit (Instant Tick Execution) ──
            side = pos.get("side", "BUY")
            target_hit = (
                live_price >= pos["target_price"] if side == "BUY"
                else live_price <= pos["target_price"]
            )
            if target_hit:
                logging.info("")
                logging.info("🟢 ════════════════════════════════════════════════════════")
                logging.info(
                    f"🟢  TARGET HIT  @  ₹{live_price:,.2f}  "
                    f"(Target was ₹{pos['target_price']:,.2f}) | Tranches: {pos['current_tranches']}/{self.max_tranches}"
                )
                logging.info("🟢 ════════════════════════════════════════════════════════")
                return self.close_position(
                    exit_price=pos["target_price"],
                    timestamp=tick_timestamp,
                    reason="Target Hit",
                )

            # ── PRIORITY 2: Mandatory EOD Auto-Square-Off ────────────────
            if tick_timestamp is not None and self.schedule.is_eod_square_off(tick_timestamp):
                logging.info(
                    f"⏰ [EOD AUTO-SQUARE-OFF] Mandatory cutoff reached ({tick_timestamp}). Closing position."
                )
                return self.square_off_all_positions(
                    reason="EOD Auto-Square-Off",
                    latest_price=live_price,
                    timestamp=tick_timestamp,
                )

            return None

    def update_tick(
        self,
        live_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Alias for check_exit: evaluates tick-level exits (Take-Profit hit & EOD square-off).
        Stop-Loss checks are strictly excluded here for Wick Immunity.
        """
        return self.check_exit(live_price=live_price, timestamp=timestamp)

    def close_position(self,*args,**kwargs):
        """Retired execution path; public PaperTrader resolves to SafeTrader."""
        from execution_safety import SafetyError
        raise SafetyError("LEGACY_ACCOUNTING_PATH_DISABLED")

    def notify_candle_close(
        self,
        candle: Optional[Union[dict, Any]] = None,
        timestamp: Optional[datetime] = None,
        latest_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Candle close notification called when a 1-minute candle completes.
        Evaluates Theta-Decay Defense, logs State Telemetry, evaluates Wick-Immune
        Candle-Close Stop Loss, updates price/timestamp, and increments cooldown counter.
        (Time stop is permanently eliminated; trades run to SL, TP, or 15:20 EOD).
        """
        with self.lock:
            self.candles_since_last_sl += 1
            ts = timestamp
            px = latest_price

            if candle is not None:
                if isinstance(candle, dict) or hasattr(candle, "get"):
                    ts = candle.get("Timestamp", candle.get("timestamp", ts))
                    px = candle.get("Close", candle.get("close", px))
                elif isinstance(candle, datetime):
                    ts = candle

            resolved_ts = self._resolve_timestamp(ts)
            if px is not None:
                self._set_latest_price(float(px), resolved_ts)

            # ── Active Position Management on Candle Close ───────────────
            if self._open_position is not None:
                self.candles_held += 1
                pos = self._open_position
                close_val = float(px) if px is not None else float(pos["average_entry_price"])
                avg_entry = float(pos["average_entry_price"])

                side = pos.get("side", "BUY")

                # ── Theta-Decay Defense (Time-Based Breakeven) ───────────
                # If we have held the trade for 15+ candles and it is in profit, lock risk to zero.
                if self._state == PyramidingState.HOLDING_TRANCHE_1 and self.candles_held >= 15:
                    in_profit = (close_val > avg_entry) if side == "BUY" else (close_val < avg_entry)
                    if in_profit:
                        current_sl = float(pos["stop_loss_price"])
                        should_trail_be = (current_sl < avg_entry) if side == "BUY" else (current_sl > avg_entry)
                        if should_trail_be:
                            pos["stop_loss_price"] = avg_entry
                            pos["breakeven_armed"] = True
                            logging.info(
                                f"[THETA DEFENSE] 15 candles elapsed in profit. "
                                f"Stop Loss aggressively trailed to Breakeven (₹{avg_entry:,.2f}). Risk is now Zero."
                            )

                # ── State Telemetry Tracking ─────────────────────────────
                if self._state == PyramidingState.HOLDING_TRANCHE_1:
                    entry_atr = float(pos.get("atr_14") or (self.entry_atr if self.entry_atr is not None else 1.0))
                    tranche2_trigger_distance = round(2.0 * entry_atr, 2)
                    if side == "BUY":
                        tranche2_trigger_price = round(avg_entry + tranche2_trigger_distance, 2)
                        distance_to_trigger = round(tranche2_trigger_price - close_val, 2)
                    else:
                        tranche2_trigger_price = round(avg_entry - tranche2_trigger_distance, 2)
                        distance_to_trigger = round(close_val - tranche2_trigger_price, 2)
                    logging.debug(
                        f"[SCALE-IN TELEMETRY] Current: ₹{close_val:.2f} | "
                        f"T2 Gate: ₹{tranche2_trigger_price:.2f} (2x ATR) | Distance: ₹{distance_to_trigger:.2f}"
                    )

            # ── Wick-Immune Stop-Loss Evaluation (Confirmed Candle Close) ──
            if self._open_position is not None and px is not None:
                pos = self._open_position
                close_val = float(px)
                sl_price = float(pos["stop_loss_price"])

                side = pos.get("side", "BUY")
                if side == "BUY":
                    sl_triggered = close_val <= sl_price
                else:  # SELL (short)
                    sl_triggered = close_val >= sl_price

                if sl_triggered:
                    is_be = (
                        (sl_price >= pos["tranches"][0]["entry_price"])
                        if side == "BUY"
                        else (sl_price <= pos["tranches"][0]["entry_price"])
                    )
                    exit_reason = (
                        "Breakeven Stop (Close-Based)"
                        if pos.get("breakeven_armed") and is_be
                        else "Stop Loss (Close-Based)"
                    )
                    dir_str = "below" if side == "BUY" else "above"
                    logging.warning(
                        f"[STOP LOSS TRIGGERED] Candle closed at ₹{close_val:,.2f} {dir_str} SL ₹{sl_price:,.2f}. "
                        "Wick immunity breached."
                    )
                    logging.info("")
                    logging.info("🔴 ════════════════════════════════════════════════════════")
                    logging.info(
                        f"🔴  {exit_reason.upper()} TRIGGERED  @  ₹{close_val:,.2f}  "
                        f"(SL was ₹{sl_price:,.2f}) | Tranches: {pos['current_tranches']}/{self.max_tranches}"
                    )
                    logging.info("🔴 ════════════════════════════════════════════════════════")
                    return self.close_position(
                        exit_price=sl_price,
                        timestamp=resolved_ts,
                        reason=exit_reason,
                    )

            return None

    def on_candle_close(
        self,
        candle: Optional[Union[dict, Any]] = None,
        timestamp: Optional[datetime] = None,
        latest_price: Optional[float] = None,
    ) -> Optional[dict]:
        """Alias for notify_candle_close for plug-and-play candle stream consumers."""
        return self.notify_candle_close(candle=candle, timestamp=timestamp, latest_price=latest_price)

    def manage_open_position(
        self,
        candle: Optional[Union[dict, Any]] = None,
        timestamp: Optional[datetime] = None,
        latest_price: Optional[float] = None,
        **kwargs,
    ) -> Optional[dict]:
        """Alias for notify_candle_close."""
        if latest_price is None and "current_price" in kwargs:
            latest_price = kwargs.pop("current_price")
        return self.notify_candle_close(candle=candle, timestamp=timestamp, latest_price=latest_price)

    def square_off_all_positions(
        self,
        reason: str = "EOD Auto-Square-Off",
        latest_price: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        PRIORITY 3: 15:20:00 IST EOD Auto-Square-Off.
        Forced market liquidation of any open intraday position.
        """
        with self.lock:
            sq_ts = self._resolve_timestamp(timestamp)
            self._check_day_reset(sq_ts)

            if latest_price is not None:
                self._set_latest_price(latest_price, sq_ts)

            if self._open_position is None:
                logging.info(f"[AUTO-SQUARE-OFF] No open position to close. Reason: {reason}")
                return None

            if self._latest_price is None:
                logging.warning(
                    f"[AUTO-SQUARE-OFF] Cannot close position: no market price available. Reason: {reason}"
                )
                return None

            summary = self.close_position(
                exit_price=self._latest_price,
                timestamp=sq_ts,
                reason=reason,
            )

            if summary is not None:
                logging.info(
                    f"[AUTO-SQUARE-OFF] Closed position at ₹{summary['exit_price']:,.2f}. "
                    f"Realized Net P&L: ₹{summary['net_pnl']:,.2f} | Tranches: {summary['tranches_filled']} | "
                    f"Reason: {reason}"
                )

            return summary

    def cancel_pending_orders(self, reason: str = "Lifecycle shutdown") -> int:
        """Cancel tracked paper orders."""
        cancelled = len(self._pending_orders)
        self._pending_orders.clear()
        logging.info(f"Cancelled {cancelled} pending paper orders. Reason: {reason}")
        return cancelled

    # ────────────────────────────────────────────────────────────────────
    #  PERSISTENT TRADE LEDGER (trades.csv)
    # ────────────────────────────────────────────────────────────────────

    def _init_csv_log(self, path: str) -> None:
        needs_header = False
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            needs_header = True
        else:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    first_line = fh.readline().strip()
                if first_line != ",".join(CSV_HEADERS):
                    needs_header = True
            except Exception:
                needs_header = True

        if needs_header:
            try:
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(CSV_HEADERS)
                logging.info(f"Initialized persistent trade log CSV: {path}")
            except Exception as exc:
                logging.error(f"Could not initialize trades.csv: {exc!s}")

    def _append_trade_csv(self, summary: dict) -> None:
        """
        Non-blocking enqueue of completed trade summary record.
        Offloads synchronous disk I/O to dedicated CSVWriterWorker thread.
        """
        self._trade_log_queue.put(summary)

    def _write_row_to_file(self, summary: dict) -> None:
        """
        Synchronous file append isolated strictly to background worker thread.
        Writes structured 13-field trade record to `trades.csv`.
        """
        ts = summary.get("timestamp")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)

        row = [
            ts_str,
            summary.get("trade_id", ""),
            summary.get("symbol", ""),
            summary.get("tranches_filled", 1),
            f"{summary.get('avg_entry_price', 0.0):.2f}",
            f"{summary.get('exit_price', 0.0):.2f}",
            summary.get("total_quantity", summary.get("quantity", 0)),
            summary.get("exit_reason", summary.get("reason", "")),
            f"{summary.get('gross_pnl', 0.0):.2f}",
            f"{summary.get('statutory_charges', summary.get('charges', 0.0)):.2f}",
            f"{summary.get('net_pnl', 0.0):.2f}",
            f"{summary.get('net_roi_pct', 0.0):.2f}",
            f"{summary.get('ending_working_capital', self.working_capital):.2f}",
        ]
        with open(self._csv_log_path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(row)
            fh.flush()

    def _csv_writer_worker(self) -> None:
        """
        Background daemon worker loop for non-blocking disk persistence.
        Consumes trade records from queue and flushes them to trades.csv.
        """
        while not self._stop_writer.is_set() or not self._trade_log_queue.empty():
            try:
                trade_record = self._trade_log_queue.get(timeout=0.5)
                if trade_record is None:
                    self._trade_log_queue.task_done()
                    break

                self._write_row_to_file(trade_record)
                self._trade_log_queue.task_done()
            except queue.Empty:
                continue
            except Exception as exc:
                logging.error(f"[CSV WRITER ERROR] Failed writing to trades.csv: {exc}", exc_info=True)

    def flush_logs(self, timeout: float = 2.0) -> None:
        """Wait for pending trade logs in the queue to be fully written to disk."""
        try:
            self._trade_log_queue.join()
        except Exception as exc:
            logging.warning(f"Error while flushing trade log queue: {exc}")

    def shutdown(self, timeout: float = 2.0) -> None:
        """
        Gracefully stop background CSV writer worker thread and flush pending records.
        """
        self._stop_writer.set()
        self._trade_log_queue.put(None)
        if hasattr(self, "_writer_thread") and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=timeout)

    # ────────────────────────────────────────────────────────────────────
    #  STATE PROPERTIES & TERMINAL TICKETS
    # ────────────────────────────────────────────────────────────────────

    @property
    def state(self) -> PyramidingState:
        return self._state

    @property
    def is_halted(self) -> bool:
        return self._halted

    def validate_preflight_capital(self, session: Optional[Any] = None) -> bool:
        """
        Pre-flight RMS validation gate.
        Validates broker available cash >= config.WORKING_CAPITAL.
        Halts engine and alerts operator if funds are insufficient or unverified.
        """
        from config import LIVE_MODE
        sess = session if session is not None else getattr(self, "angel_session", None)
        if not LIVE_MODE or sess is None:
            return True
        is_sufficient, _ = validate_broker_capital(
            smart_api=sess,
            required_capital=WORKING_CAPITAL,
            engine=self,
        )
        return is_sufficient

    @property
    def has_open_position(self) -> bool:
        return self._open_position is not None

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def trade_log(self) -> list:
        return list(self._trade_log)

    @property
    def latest_price(self) -> Optional[float]:
        return self._latest_price

    @property
    def avg_entry_price(self) -> Optional[float]:
        if self._open_position is not None:
            return float(self._open_position["average_entry_price"])
        return None

    @property
    def open_position(self) -> Optional[dict]:
        return self._open_position

    @property
    def actual_entry_fill(self) -> Optional[float]:
        if self._open_position and "actual_entry_fill" in self._open_position:
            return float(self._open_position["actual_entry_fill"])
        if self._trade_log:
            for item in reversed(self._trade_log):
                if "actual_entry_fill" in item:
                    return float(item["actual_entry_fill"])
                if "avg_entry_price" in item:
                    return float(item["avg_entry_price"])
        return None

    @property
    def actual_exit_fill(self) -> Optional[float]:
        if self._open_position and "actual_exit_fill" in self._open_position:
            return float(self._open_position["actual_exit_fill"])
        if self._trade_log:
            for item in reversed(self._trade_log):
                if "actual_exit_fill" in item:
                    return float(item["actual_exit_fill"])
                if "exit_price" in item:
                    return float(item["exit_price"])
        return None

    @property
    def candles_since_last_exit(self) -> int:
        return self.candles_since_last_sl

    @candles_since_last_exit.setter
    def candles_since_last_exit(self, val: int) -> None:
        self.candles_since_last_sl = val

    def check_day_reset(self, current_dt: Optional[datetime] = None) -> None:
        """Public method to reset intraday state if session date changes."""
        today = current_dt.date() if current_dt is not None else date.today()
        if self._current_date != today:
            if self._current_date is not None:
                logging.info(f"📅 New trading session ({today}). Resetting intraday state.")
            self._current_date = today
            self._daily_pnl = 0.0
            self._trade_count = 0
            self._halted = False
            self._state = PyramidingState.IDLE
            self.daily_bias = "NEUTRAL"

    # Backward compatibility alias
    _check_day_reset = check_day_reset

    def _resolve_timestamp(
        self,
        timestamp: Optional[datetime],
        data: Optional[dict] = None,
    ) -> datetime:
        if timestamp is not None:
            return timestamp
        if data is not None:
            value = data.get("timestamp", data.get("Timestamp"))
            if isinstance(value, datetime):
                return value
        return datetime.now()

    def _set_latest_price(
        self,
        price: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        self._latest_price = float(price)
        self._latest_timestamp = timestamp

    def _print_trade_ticket(self, ticket: dict) -> None:
        tranche_label = f"[TRANCHE {ticket['tranche_number']}/{ticket['max_tranches']}]"
        ticket_type = "📝  INITIAL ENTRY" if ticket['tranche_number'] == 1 else "📐  SCALE-IN (PYRAMID)"
        atr_val = ticket.get("atr_14")
        sl_dist = ticket.get("stop_loss_distance")
        sl_dist_display = f"  (−₹{sl_dist:,.2f})" if sl_dist is not None else f"  (−{self.stop_loss_pct*100:.1f}%)"

        logging.info("")
        logging.info("╔══════════════════════════════════════════════════════════╗")
        logging.info(f"║  {ticket_type:<45} {tranche_label}║")
        ticket_header = "LIVE TRADE TICKET" if getattr(config, "LIVE_MODE", False) else "SIMULATED TRADE TICKET"
        logging.info(f"║           {ticket_header:<46}║")
        logging.info("╠══════════════════════════════════════════════════════════╣")
        logging.info(f"║  Trade ID     :  #{ticket['trade_id']:<39}║")
        logging.info(f"║  Position ID  :  #{ticket['position_id']:<39}║")
        logging.info(f"║  Symbol       :  {ticket['symbol']:<40}║")
        logging.info(f"║  Side         :  {ticket['side']:<40}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Entry Price  :  ₹{ticket['entry_price']:>10,.2f}{'':<28}║")
        logging.info(f"║  Avg Entry    :  ₹{ticket['avg_entry_price']:>10,.2f}  (VWAP Weighted){'':<10}║")
        if atr_val is not None and sl_dist is not None:
            logging.info(f"║  ATR (14)     :  {atr_val:>10.2f}  (Volatility Proxy){'':<11}║")
            logging.info(f"║  SL Distance  :  ₹{sl_dist:>10.2f}  (2.00 × ATR_14){'':<13}║")
        logging.info(f"║  Stop Loss    :  ₹{ticket['stop_loss_price']:>10,.2f}{sl_dist_display:<28}║")
        logging.info(f"║  Target Price :  ₹{ticket['target_price']:>10,.2f}  ({ticket['risk_reward']}){'':<19}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Tranche Qty  :  {ticket['tranche_quantity']:<40}║")
        logging.info(f"║  Total Qty    :  {ticket['total_quantity']:<40}║")
        logging.info(f"║  Total Cost   :  ₹{ticket['total_cost']:>10,.2f}{'':<28}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Max Loss     :  ₹{ticket['potential_loss']:>10,.2f}{'':<28}║")
        logging.info(f"║  Max Profit   :  ₹{ticket['potential_profit']:>10,.2f}{'':<28}║")
        logging.info(f"║  Est. Charges :  ₹{ticket['estimated_charges_at_target']:>10,.2f}{'':<28}║")
        logging.info(f"║  Net Loss Est.:  ₹{ticket['estimated_net_loss']:>10,.2f}{'':<28}║")
        logging.info(f"║  Net Prof Est.:  ₹{ticket['estimated_net_profit']:>10,.2f}{'':<28}║")
        logging.info(f"║  Risk : Reward:  {ticket['risk_reward']:<40}║")
        logging.info(f"║  Friction Gate:  PASSED ✅{'':<32}║")
        logging.info("╚══════════════════════════════════════════════════════════╝")
        logging.info("")

    def _print_closed_ticket(
        self,
        pos: dict,
        exit_price: float,
        gross_pnl: float,
        charges: float,
        pnl: float,
        pnl_pct: float,
        result: str,
        reason: str,
    ) -> None:
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        pnl_sign = "+" if pnl >= 0 else ""
        exit_label = f"₹{exit_price:,.2f}"
        pnl_label = f"{pnl_sign}₹{pnl:,.2f}  ({pnl_sign}{pnl_pct:.2f}%)"
        gross_label = f"₹{gross_pnl:,.2f}"
        charges_label = f"₹{charges:,.2f}"
        daily_label = f"₹{self._daily_pnl:,.2f}"
        wcap_label = f"₹{self.working_capital:,.2f}"
        tranche_label = f"{pos['current_tranches']}/{self.max_tranches}"

        logging.info("")
        logging.info("╔══════════════════════════════════════════════════════════╗")
        logging.info(f"║  {pnl_icon}  TRADE CLOSED  ──  {result:<35}║")
        logging.info("╠══════════════════════════════════════════════════════════╣")
        logging.info(f"║  Position ID  :  #{pos['position_id']:<39}║")
        logging.info(f"║  Symbol       :  {pos['symbol']:<40}║")
        logging.info(f"║  Tranches     :  {tranche_label:<40}║")
        logging.info(f"║  Exit Reason  :  {reason:<40}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Avg Entry    :  ₹{pos['average_entry_price']:>10,.2f}{'':<28}║")
        logging.info(f"║  Exit Price   :  {exit_label:<42}║")
        logging.info(f"║  Quantity     :  {pos['quantity']:<40}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Gross P&L    :  {gross_label:<42}║")
        logging.info(f"║  Costs        :  {charges_label:<42}║")
        logging.info(f"║  Net P&L      :  {pnl_label:<42}║")
        logging.info(f"║  Daily P&L    :  {daily_label:<42}║")
        logging.info(f"║  Working Cap  :  {wcap_label:<42}║")
        logging.info("╚══════════════════════════════════════════════════════════╝")
        logging.info("")


# ── Execution Engine Alias ──────────────────────────────────────────────
def __getattr__(name):
    if name in {"PaperTrader", "ExecutionEngine"}:
        from safe_trader import SafeTrader
        return SafeTrader
    raise AttributeError(name)
