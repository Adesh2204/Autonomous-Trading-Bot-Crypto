"""
execution_engine.py — Paper-Trading Execution Layer (Pyramiding Enabled)
========================================================================
Simulates trade execution with strict, mathematical risk management
and Scale-In (Pyramiding / Multi-Tranche Entry) support on consecutive
valid VWAP Pullback buy signals.

No real orders are placed; every trade is logged as a simulated ticket.

Scale-In (Pyramiding) Architecture
──────────────────────────────────
• Maximum 3 tranches (entries) per trading session on the same symbol.
• Total combined exposure ≤ Working Capital (50% of Total Capital).
• Total combined risk ≤ Daily Loss Limit (₹200) and per-trade cap (₹100).
• On each scale-in fill:
    – Volume Weighted Average Entry Price is recalculated (Σ(Pᵢ×Qᵢ) / ΣQᵢ)
    – Global Stop Loss updates (−0.5% from new average entry price)
    – Global Take Profit updates (1:2 R:R from new average entry price)
• Friction Gate runs on every incoming tranche to ensure positive net expectancy.
• Unified exit on SL / Target / 15:20 IST EOD — entire Q_total sold in single tx.

Risk Management Model
─────────────────────
• Total Capital       : ₹10,000
• Working Capital     : 50% of Total  (₹5,000)  — the other 50% is backup
• Daily Loss Limit    : 2%  of Total  (₹200)    — halt trading if breached
• Risk Per Trade      : 1%  of Total  (₹100)    — max loss on any single trade
• Quantity Formula    : Risk_Per_Trade / (Entry - Stop_Loss)
• Stop Loss           : Avg Entry − 0.5%
• Target              : Avg Entry + 2 × (Avg Entry − Stop Loss)  [1:2 R:R]
"""

import logging
import threading
from datetime import date, datetime
from typing import Optional


class PaperTrader:
    """
    Paper-trading engine with built-in risk management.

    Instantiate once at bot startup. Call `execute_trade()` every time
    the Signal Brain emits a Buy_Signal.

    Parameters
    ----------
    total_capital       : float — Starting paper capital (default ₹10,000).
    working_capital_pct : float — Fraction of capital deployable (default 0.50).
    daily_loss_limit_pct: float — Max daily loss as fraction of total (default 0.02).
    risk_per_trade_pct  : float — Risk per trade as fraction of total (default 0.01).
    stop_loss_pct       : float — Stop-loss distance below entry (default 0.005 = 0.5%).
    reward_to_risk      : float — Reward-to-risk ratio for target (default 2.0).
    slippage_pct        : float — Per-side estimated slippage (default 0.05%).
    brokerage_per_order : float — Flat brokerage per order leg.
    """

    def __init__(
        self,
        total_capital: float = 10_000.0,
        working_capital_pct: float = 0.50,
        daily_loss_limit_pct: float = 0.02,
        risk_per_trade_pct: float = 0.01,
        stop_loss_pct: float = 0.005,
        reward_to_risk: float = 2.0,
        slippage_pct: float = 0.0005,
        brokerage_per_order: float = 20.0,
        max_tranches: int = 3,
        stt_sell_pct: float = 0.00025,
        exchange_txn_pct: float = 0.0000322,
        sebi_turnover_pct: float = 0.000001,
        stamp_duty_buy_pct: float = 0.00003,
        gst_pct: float = 0.18,
    ):
        # ── Capital Configuration ───────────────────────────────────
        self.total_capital       = total_capital
        self.working_capital     = total_capital * working_capital_pct
        self.backup_capital      = total_capital * (1 - working_capital_pct)

        # ── Risk Limits ─────────────────────────────────────────────
        self.daily_loss_limit    = total_capital * daily_loss_limit_pct
        self.risk_per_trade      = total_capital * risk_per_trade_pct
        self.stop_loss_pct       = stop_loss_pct
        self.reward_to_risk      = reward_to_risk
        self.slippage_pct        = slippage_pct
        self.brokerage_per_order = brokerage_per_order
        self.max_tranches        = max_tranches
        self.stt_sell_pct        = stt_sell_pct
        self.exchange_txn_pct    = exchange_txn_pct
        self.sebi_turnover_pct   = sebi_turnover_pct
        self.stamp_duty_buy_pct  = stamp_duty_buy_pct
        self.gst_pct             = gst_pct

        # ── Daily State (resets each trading day) ───────────────────
        self._current_date: Optional[date] = None
        self._daily_pnl: float             = 0.0
        self._trade_count: int             = 0
        self._halted: bool                 = False

        # ── Session Tracking ────────────────────────────────────────
        self._open_position: Optional[dict] = None
        self._trade_log: list               = []
        self._pending_orders: list          = []
        self._latest_price: Optional[float] = None
        self._latest_timestamp: Optional[datetime] = None
        self.lock = threading.RLock()
        self._state_lock = self.lock

        logging.info("=" * 60)
        logging.info("  PAPER TRADER INITIALIZED")
        logging.info(f"  Total Capital     : ₹{self.total_capital:,.2f}")
        logging.info(f"  Working Capital   : ₹{self.working_capital:,.2f}")
        logging.info(f"  Backup Capital    : ₹{self.backup_capital:,.2f}")
        logging.info(f"  Daily Loss Limit  : ₹{self.daily_loss_limit:,.2f}")
        logging.info(f"  Risk Per Trade    : ₹{self.risk_per_trade:,.2f}")
        logging.info(f"  Slippage / Side   : {self.slippage_pct * 100:.3f}%")
        logging.info(f"  Brokerage / Order : ₹{self.brokerage_per_order:,.2f}")
        logging.info("=" * 60)

    # ────────────────────────────────────────────────────────────────
    #  PUBLIC API
    # ────────────────────────────────────────────────────────────────

    def execute_trade(
        self,
        signal_data: dict,
        timestamp: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Process a buy signal and simulate a trade entry.

        Parameters
        ----------
        signal_data : dict
            Must contain at minimum:
            • "VWAP"  (float) — the current VWAP value used as entry price.

            Optional keys:
            • "Close" (float) — latest close, for informational logging.
            • "symbol" (str)  — instrument name (default "UNKNOWN").

        Returns
        -------
        dict or None
            The trade ticket dict if a trade was placed, else None
            (e.g. when halted or position already open).
        """

        with self.lock:
            trade_timestamp = self._resolve_timestamp(timestamp, signal_data)
            self._check_day_reset(trade_timestamp)

            # ── Guard: daily loss limit breached ────────────────────────
            if self._halted:
                logging.warning(
                    "⛔  TRADE BLOCKED — Daily loss limit "
                    f"(₹{self.daily_loss_limit:,.2f}) has been reached. "
                    "Trading is halted for today."
                )
                return None

            entry_price = float(signal_data.get("VWAP", 0))
            symbol      = signal_data.get("symbol", "RELIANCE")
            close_price = signal_data.get("Close")
            if close_price is not None:
                self._set_latest_price(float(close_price), trade_timestamp)

            if entry_price <= 0:
                logging.error("Invalid VWAP value for trade entry. Skipping.")
                return None

            current_position = self._open_position

            if current_position is not None and current_position["symbol"] != symbol:
                logging.info(
                    "⏳  Skipping signal — already holding an open position "
                    f"in {current_position['symbol']} "
                    f"(Tranches: {current_position['current_tranches']}/{current_position['max_tranches']}, "
                    f"Avg Entry: ₹{current_position['average_entry_price']:,.2f})"
                )
                return None

            if current_position is not None:
                ct = current_position["current_tranches"]
                mt = current_position["max_tranches"]
                total_invested = current_position["total_cost"]
                logging.info(
                    f"[SCALE-IN CHECK] Detected open position in {symbol} | "
                    f"Tranches: {ct}/{mt} | "
                    f"Total Invested: ₹{total_invested:,.2f} / ₹{self.working_capital:,.2f} Working Cap | "
                    f"Evaluating scale-in eligibility..."
                )
                if ct >= mt:
                    logging.info(
                        "⏳ Max scale-in limit reached — holding full position "
                        f"({ct}/{mt} tranches deployed)."
                    )
                    return None
            else:
                logging.info(
                    f"[SCALE-IN CHECK] No open position in {symbol} | "
                    f"Evaluating ENTRY TRANCHE 1/{self.max_tranches}..."
                )

            trade_id = self._trade_count + 1
            snapshot, ticket, rejection_reason = self._find_valid_scale_in(
                current_position=current_position,
                symbol=symbol,
                entry_price=entry_price,
                trade_id=trade_id,
                timestamp=trade_timestamp,
            )

            if snapshot is None or ticket is None:
                if current_position is not None and rejection_reason in {"max_tranches", "capital_or_risk"}:
                    if rejection_reason == "capital_or_risk":
                        logging.info(
                            "⏳ Max scale-in limit reached — holding full position "
                            "(capital or risk budget exhausted)."
                        )
                    else:
                        logging.info(
                            "⏳ Max scale-in limit reached — holding full position "
                            f"({current_position['current_tranches']}/{self.max_tranches} tranches)."
                        )
                elif rejection_reason == "symbol_mismatch":
                    logging.info(
                        "⏳  Skipping signal — already holding an open position "
                        f"in {current_position['symbol']}"
                    )
                elif rejection_reason == "friction":
                    logging.warning(
                        "[FRICTION GATE FAILED] Incoming tranche rejected — "
                        "transaction costs (STT + Stamp Duty + Brokerage + Exchange Turnover) "
                        "would make net trade expectancy negative."
                    )
                elif rejection_reason in {"capital", "risk"}:
                    constraint = "Working Capital" if rejection_reason == "capital" else "Risk Budget"
                    logging.warning(
                        f"[TRADE REJECTED] {constraint} constraint violated — "
                        "added tranche would exceed allowable exposure."
                    )
                else:
                    logging.warning(
                        "[TRADE REJECTED] Added tranche would violate capital, risk, or net expectancy constraints."
                    )
                return None

            tranche_number = snapshot["current_tranches"]
            if current_position is None:
                logging.info(
                    f"✅ [ENTRY TRANCHE {tranche_number}/{self.max_tranches}] "
                    f"Initial VWAP buy signal accepted. All gates passed."
                )
            else:
                new_avg = snapshot["average_entry_price"]
                new_sl = snapshot["stop_loss_price"]
                new_tp = snapshot["target_price"]
                logging.info(
                    f"✅ [SCALE-IN TRANCHE {tranche_number}/{self.max_tranches}] "
                    f"Adding qty {ticket['tranche_quantity']} at ₹{entry_price:,.2f}. "
                    f"All gates passed."
                )
                logging.info(
                    f"🔄 [POSITION RECALCULATED] New Avg Entry: ₹{new_avg:,.2f} | "
                    f"Updated SL: ₹{new_sl:,.2f} (−{self.stop_loss_pct*100:.1f}%) | "
                    f"Updated TP: ₹{new_tp:,.2f} (1:{self.reward_to_risk:.0f} R:R)"
                )

            self._open_position = snapshot
            self._trade_count += 1
            self._trade_log.append(ticket)

            self._print_trade_ticket(ticket)
            return ticket

    def close_position(
        self,
        exit_price: float,
        timestamp: Optional[datetime] = None,
        reason: str = "Signal Exit",
    ) -> Optional[dict]:
        """
        Close the current open position at the given exit price
        and update the daily P&L.

        Parameters
        ----------
        exit_price : float — The price at which the position is exited.

        Returns
        -------
        dict or None — Summary of the closed trade, or None if no position.
        """
        with self.lock:
            if self._open_position is None:
                logging.info("No open position to close.")
                return None

            exit_timestamp = self._resolve_timestamp(timestamp)
            self._check_day_reset(exit_timestamp)
            self._set_latest_price(exit_price, exit_timestamp)

            pos = self._open_position
            total_qty = pos["quantity"]
            avg_entry_price = pos["average_entry_price"]
            gross_pnl = (exit_price - avg_entry_price) * total_qty
            exit_leg_costs = self._calculate_exit_leg_charges(total_qty, exit_price)
            total_charges = pos["entry_friction_total"] + exit_leg_costs["total_charges"]
            net_pnl = gross_pnl - total_charges
            pnl_pct = (net_pnl / pos["total_cost"]) * 100 if pos["total_cost"] else 0

            result = "PROFIT ✅" if net_pnl >= 0 else "LOSS ❌"

            summary = {
                "trade_id":    pos["position_id"],
                "symbol":      pos["symbol"],
                "entry_price": round(avg_entry_price, 2),
                "exit_price":  round(exit_price, 2),
                "quantity":    total_qty,
                "avg_entry_price": round(avg_entry_price, 2),
                "tranches":    pos["current_tranches"],
                "gross_pnl":   round(gross_pnl, 2),
                "charges":     round(total_charges, 2),
                "net_pnl":     round(net_pnl, 2),
                "pnl":         round(net_pnl, 2),
                "pnl_pct":     round(pnl_pct, 2),
                "result":      result,
                "reason":      reason,
                "timestamp":   exit_timestamp,
            }

            # Update daily P&L
            self._daily_pnl += net_pnl
            self.working_capital += net_pnl

            # Print the structured TRADE CLOSED ticket to the terminal
            self._print_closed_ticket(
                pos,
                exit_price,
                gross_pnl,
                total_charges,
                net_pnl,
                pnl_pct,
                result,
            )

            # Clear the open position
            self._open_position = None

            # Check if daily loss limit is now breached
            if self._daily_pnl <= -self.daily_loss_limit:
                self._halted = True
                logging.warning(
                    "⛔ ══════════════════════════════════════════════════════"
                )
                logging.warning(
                    f"⛔  DAILY LOSS LIMIT HIT  |  P&L: ₹{self._daily_pnl:,.2f}"
                )
                logging.warning(
                    "⛔  ALL TRADING IS HALTED FOR THE REST OF THE DAY"
                )
                logging.warning(
                    "⛔ ══════════════════════════════════════════════════════"
                )

            return summary

    def check_exit(
        self,
        live_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Check every incoming tick against the open position's
        Stop-Loss and Target thresholds.  If either is breached,
        automatically close the position.

        Call this on EVERY raw tick inside the WebSocket on_message
        callback.  The method is O(1) — two float comparisons and
        an early return — so it adds negligible overhead.

        Parameters
        ----------
        live_price : float — The latest traded price from the tick.

        Returns
        -------
        dict or None
            The closed-trade summary if an exit was triggered,
            otherwise None (position still open or no position).
        """
        with self.lock:
            tick_timestamp = self._resolve_timestamp(timestamp)
            self._check_day_reset(tick_timestamp)
            self._set_latest_price(live_price, tick_timestamp)

            # ── Fast exit: nothing to monitor ───────────────────────────
            if self._open_position is None:
                return None

            pos = self._open_position

            # ── Stop-Loss Hit ───────────────────────────────────────────
            # Price dropped to or below the stop-loss level.
            if live_price <= pos["stop_loss_price"]:
                logging.info("")
                logging.info(
                    "🔴 ════════════════════════════════════════════════════════"
                )
                logging.info(
                    f"🔴  STOP-LOSS TRIGGERED  @  ₹{live_price:,.2f}  "
                    f"(SL was ₹{pos['stop_loss_price']:,.2f}) | Tranches: {pos['current_tranches']}/{pos['max_tranches']}"
                )
                logging.info(
                    "🔴 ════════════════════════════════════════════════════════"
                )
                return self.close_position(
                    exit_price=pos["stop_loss_price"],
                    timestamp=tick_timestamp,
                    reason="Stop Loss",
                )

            # ── Target Hit ──────────────────────────────────────────────
            # Price rose to or above the target level.
            if live_price >= pos["target_price"]:
                logging.info("")
                logging.info(
                    "🟢 ════════════════════════════════════════════════════════"
                )
                logging.info(
                    f"🟢  TARGET HIT  @  ₹{live_price:,.2f}  "
                    f"(Target was ₹{pos['target_price']:,.2f}) | Tranches: {pos['current_tranches']}/{pos['max_tranches']}"
                )
                logging.info(
                    "🟢 ════════════════════════════════════════════════════════"
                )
                return self.close_position(
                    exit_price=pos["target_price"],
                    timestamp=tick_timestamp,
                    reason="Target Hit",
                )

            # ── Neither threshold breached — position stays open ────────
            return None

    def square_off_all_positions(
        self,
        reason: str,
        latest_price: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Force-close any open intraday position at the latest market price.

        Parameters
        ----------
        reason       : str   — Operational reason for forced exit.
        latest_price : float — Optional explicit market price. If omitted,
                               the most recent tick seen by check_exit() is used.
        timestamp    : datetime, optional — Event time for live/test injection.
        """
        with self.lock:
            square_off_timestamp = self._resolve_timestamp(timestamp)
            self._check_day_reset(square_off_timestamp)

            if latest_price is not None:
                self._set_latest_price(latest_price, square_off_timestamp)

            if self._open_position is None:
                logging.info(
                    f"[AUTO-SQUARE-OFF] No open position to close. Reason: {reason}"
                )
                return None

            if self._latest_price is None:
                logging.warning(
                    "[AUTO-SQUARE-OFF] Cannot close position because no latest "
                    f"market price is available. Reason: {reason}"
                )
                return None

            summary = self.close_position(
                exit_price=self._latest_price,
                timestamp=square_off_timestamp,
                reason=reason,
            )

            if summary is not None:
                logging.info(
                    "[AUTO-SQUARE-OFF] Closed position at "
                    f"₹{summary['exit_price']:,.2f}. Realized Net P&L: "
                    f"₹{summary['net_pnl']:,.2f} | Tranches: {summary.get('tranches', 1)} | Reason: {reason}"
                )

            return summary

    def cancel_pending_orders(self, reason: str = "Lifecycle shutdown") -> int:
        """
        Cancel tracked paper orders.

        The current paper engine has no broker-side pending orders, but keeping
        this method makes the live lifecycle path explicit and future-proof.
        """
        cancelled_count = len(self._pending_orders)
        self._pending_orders.clear()
        logging.info(
            f"Cancelled {cancelled_count} pending paper orders. Reason: {reason}"
        )
        return cancelled_count

    @property
    def is_halted(self) -> bool:
        """Whether trading has been halted due to daily loss limit."""
        return self._halted

    @property
    def has_open_position(self) -> bool:
        """Whether there is currently an open paper position."""
        return self._open_position is not None

    @property
    def daily_pnl(self) -> float:
        """Running daily P&L in rupees."""
        return self._daily_pnl

    @property
    def latest_price(self) -> Optional[float]:
        """Most recent market price observed by the trader."""
        return self._latest_price

    # ────────────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ────────────────────────────────────────────────────────────────

    def _check_day_reset(self, current_dt: Optional[datetime] = None) -> None:
        """
        Reset daily counters when a new trading day begins.
        This ensures the daily loss limit and trade count refresh
        automatically without manual intervention.
        """
        today = current_dt.date() if current_dt is not None else date.today()
        if self._current_date != today:
            if self._current_date is not None:
                logging.info(
                    f"📅  New trading day detected ({today}). "
                    "Resetting daily counters."
                )
            self._current_date = today
            self._daily_pnl    = 0.0
            self._trade_count  = 0
            self._halted       = False

    def _resolve_timestamp(
        self,
        timestamp: Optional[datetime],
        data: Optional[dict] = None,
    ) -> datetime:
        """Resolve timestamp from an explicit value, signal payload, or clock."""
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
        """Track the last market price for lifecycle exits."""
        self._latest_price = float(price)
        self._latest_timestamp = timestamp

    def _calculate_entry_leg_charges(self, quantity: int, price: float) -> dict:
        """Calculate buy-leg turnover and statutory charges for one tranche."""
        turnover = quantity * price
        brokerage = min(20.0, turnover * 0.0003)
        exchange_txn = turnover * 0.0000325
        stamp_duty = turnover * 0.00003
        gst = (brokerage + exchange_txn) * 0.18
        total_charges = brokerage + exchange_txn + stamp_duty + gst
        return {
            "turnover": turnover,
            "brokerage": brokerage,
            "exchange_txn": exchange_txn,
            "stamp_duty": stamp_duty,
            "gst": gst,
            "total_charges": total_charges,
        }

    def _calculate_exit_leg_charges(self, quantity: int, price: float) -> dict:
        """Calculate sell-leg turnover and statutory charges for one exit."""
        turnover = quantity * price
        brokerage = min(20.0, turnover * 0.0003)
        stt = turnover * 0.00025
        exchange_txn = turnover * 0.0000325
        gst = (brokerage + exchange_txn) * 0.18
        total_charges = brokerage + stt + exchange_txn + gst
        return {
            "turnover": turnover,
            "brokerage": brokerage,
            "stt": stt,
            "exchange_txn": exchange_txn,
            "gst": gst,
            "total_charges": total_charges,
        }

    def _estimate_round_trip_costs(
        self,
        quantity: int,
        entry_price: float,
        exit_price: float,
    ) -> dict:
        """Estimate NSE intraday equity round-trip friction components."""
        entry_leg = self._calculate_entry_leg_charges(quantity, entry_price)
        exit_leg = self._calculate_exit_leg_charges(quantity, exit_price)
        buy_turnover = entry_leg["turnover"]
        sell_turnover = exit_leg["turnover"]
        brokerage = entry_leg["brokerage"] + exit_leg["brokerage"]
        stt = exit_leg["stt"]
        exchange_txn = entry_leg["exchange_txn"] + exit_leg["exchange_txn"]
        stamp_duty = entry_leg["stamp_duty"]
        gst = entry_leg["gst"] + exit_leg["gst"]
        total_charges = entry_leg["total_charges"] + exit_leg["total_charges"]

        return {
            "buy_turnover": buy_turnover,
            "sell_turnover": sell_turnover,
            "brokerage": brokerage,
            "buy_brokerage": entry_leg["brokerage"],
            "sell_brokerage": exit_leg["brokerage"],
            "stt": stt,
            "exchange_txn": exchange_txn,
            "stamp_duty": stamp_duty,
            "gst": gst,
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
        """Return total NSE intraday equity transaction friction for a round trip."""
        if qty <= 0 or entry_price <= 0 or exit_price <= 0:
            return 0.0

        return self._estimate_round_trip_costs(
            quantity=qty,
            entry_price=entry_price,
            exit_price=exit_price,
        )["total_charges"]

    def _build_position_snapshot(
        self,
        *,
        symbol: str,
        tranches: list,
        position_id: int,
        timestamp: Optional[datetime],
    ) -> dict:
        """
        Create an aggregated open-position snapshot from tranche fills.

        Dynamic Position Recalculation (per tranche fill):
        ──────────────────────────────────────────────────
        Volume Weighted Average Entry Price:
            Avg Entry = Σ (Pᵢ × Qᵢ) / Σ Qᵢ

        Global Stop Loss  : −0.5% from the NEW average entry price.
        Global Take Profit: 1:2 R:R from the NEW average entry price.
        """
        num_tranches = len(tranches)

        total_quantity = sum(tranche["quantity"] for tranche in tranches)
        entry_notional = sum(tranche["entry_turnover"] for tranche in tranches)
        entry_friction = sum(tranche["entry_friction"] for tranche in tranches)

        average_entry_price = entry_notional / total_quantity
        stop_loss_price = average_entry_price * (1 - self.stop_loss_pct)
        risk_distance = average_entry_price - stop_loss_price
        target_price = average_entry_price + (self.reward_to_risk * risk_distance)

        stop_exit_costs = self._calculate_exit_leg_charges(total_quantity, stop_loss_price)
        target_exit_costs = self._calculate_exit_leg_charges(total_quantity, target_price)
        gross_stop_loss = total_quantity * risk_distance
        gross_target_profit = total_quantity * (target_price - average_entry_price)

        projected_net_loss_at_stop = gross_stop_loss + entry_friction + stop_exit_costs["total_charges"]
        projected_net_profit_at_target = gross_target_profit - entry_friction - target_exit_costs["total_charges"]
        total_cost = entry_notional + entry_friction

        if num_tranches > 1:
            tranche_detail = " | ".join(
                f"T{i+1}:₹{t['entry_price']:,.2f}×{t['quantity']}"
                for i, t in enumerate(tranches)
            )
            logging.debug(
                f"[VWAP RECALC] Tranches[{num_tranches}]: {tranche_detail} "
                f"→ Weighted Avg: ₹{average_entry_price:,.2f} | "
                f"Σ(Q): {total_quantity} | Σ(P×Q): ₹{entry_notional:,.2f}"
            )

        return {
            "position_id": position_id,
            "symbol": symbol,
            "side": "BUY",
            "quantity": total_quantity,
            "average_entry_price": average_entry_price,
            "entry_notional": entry_notional,
            "entry_friction_total": entry_friction,
            "total_cost": total_cost,
            "current_tranches": num_tranches,
            "max_tranches": self.max_tranches,
            "stop_loss_price": stop_loss_price,
            "target_price": target_price,
            "risk_distance": risk_distance,
            "projected_net_loss_at_stop": projected_net_loss_at_stop,
            "projected_net_profit_at_target": projected_net_profit_at_target,
            "stop_exit_charges": stop_exit_costs["total_charges"],
            "target_exit_charges": target_exit_costs["total_charges"],
            "tranches": tranches,
            "timestamp": timestamp,
        }

    def _project_position_after_tranche(
        self,
        current_position: Optional[dict],
        symbol: str,
        entry_price: float,
        quantity: int,
        trade_id: int,
        timestamp: Optional[datetime],
    ) -> tuple[dict, dict]:
        """Return a new position snapshot and tranche ticket for the candidate fill."""
        tranche_entry_charges = self._calculate_entry_leg_charges(quantity, entry_price)
        tranche = {
            "trade_id": trade_id,
            "quantity": quantity,
            "entry_price": entry_price,
            "entry_turnover": tranche_entry_charges["turnover"],
            "entry_friction": tranche_entry_charges["total_charges"],
            "timestamp": timestamp,
        }

        if current_position is None:
            position_id = trade_id
            tranches = [tranche]
        else:
            position_id = current_position["position_id"]
            tranches = [*current_position["tranches"], tranche]

        snapshot = self._build_position_snapshot(
            symbol=symbol,
            tranches=tranches,
            position_id=position_id,
            timestamp=timestamp,
        )

        rr_ratio = f"1:{self.reward_to_risk:.1f}"
        ticket = {
            "trade_id": trade_id,
            "position_id": position_id,
            "symbol": symbol,
            "side": "BUY",
            "tranche_number": snapshot["current_tranches"],
            "max_tranches": snapshot["max_tranches"],
            "entry_price": round(entry_price, 2),
            "quantity": quantity,
            "tranche_quantity": quantity,
            "avg_entry_price": round(snapshot["average_entry_price"], 2),
            "stop_loss_price": round(snapshot["stop_loss_price"], 2),
            "target_price": round(snapshot["target_price"], 2),
            "total_quantity": snapshot["quantity"],
            "total_cost": round(snapshot["total_cost"], 2),
            "risk_distance": round(snapshot["risk_distance"], 2),
            "risk_reward": rr_ratio,
            "potential_loss": round(snapshot["projected_net_loss_at_stop"], 2),
            "potential_profit": round(snapshot["projected_net_profit_at_target"], 2),
            "estimated_charges_at_stop": round(snapshot["stop_exit_charges"] + snapshot["entry_friction_total"], 2),
            "estimated_charges_at_target": round(snapshot["target_exit_charges"] + snapshot["entry_friction_total"], 2),
            "estimated_net_loss": round(snapshot["projected_net_loss_at_stop"], 2),
            "estimated_net_profit": round(snapshot["projected_net_profit_at_target"], 2),
            "entry_friction_total": round(snapshot["entry_friction_total"], 2),
            "current_tranches": snapshot["current_tranches"],
            "timestamp": timestamp,
            "tranches": tranches,
        }

        return snapshot, ticket

    def _can_accept_position_snapshot(
        self,
        snapshot: dict,
    ) -> tuple[bool, Optional[str]]:
        """
        Friction Gate + Risk + Capital Validator per tranche.

        Runs the Net-Profit Gate check on the incoming tranche to ensure
        added transaction costs (STT + Stamp Duty + Brokerage + Exchange
        Turnover) do not make the net trade expectancy negative.

        Also enforces:
        • Total combined exposure ≤ Working Capital (50% of Total Capital)
        • Total combined risk     ≤ Daily Loss Limit (₹200) ∩ Per-trade cap (₹100)
        • Projected net profit at target  >  0  (Friction Gate)
        """
        risk_cap = min(self.risk_per_trade, self.daily_loss_limit)
        nt = snapshot["current_tranches"]

        if snapshot["total_cost"] > self.working_capital:
            logging.debug(
                f"[GATE FAIL] Tranche {nt}: Capital breach — "
                f"₹{snapshot['total_cost']:,.2f} > ₹{self.working_capital:,.2f} Working Cap"
            )
            return False, "capital"

        if snapshot["projected_net_loss_at_stop"] > risk_cap:
            logging.debug(
                f"[GATE FAIL] Tranche {nt}: Risk breach — "
                f"₹{snapshot['projected_net_loss_at_stop']:,.2f} > ₹{risk_cap:,.2f} Risk Cap"
            )
            return False, "risk"

        if snapshot["projected_net_profit_at_target"] <= 0:
            friction_total = (
                snapshot["entry_friction_total"]
                + snapshot["target_exit_charges"]
            )
            logging.debug(
                f"[GATE FAIL] Tranche {nt}: Friction Gate failed — "
                f"Net Profit at Target ₹{snapshot['projected_net_profit_at_target']:,.2f} ≤ 0 | "
                f"Total Charges ₹{friction_total:,.2f}"
            )
            return False, "friction"

        return True, None

    def _find_valid_scale_in(
        self,
        current_position: Optional[dict],
        symbol: str,
        entry_price: float,
        trade_id: int,
        timestamp: Optional[datetime],
    ) -> tuple[Optional[dict], Optional[dict], Optional[str]]:
        """Search for the largest valid tranche size under the current constraints."""
        risk_cap = min(self.risk_per_trade, self.daily_loss_limit)

        if current_position is not None and current_position["current_tranches"] >= self.max_tranches:
            return None, None, "max_tranches"

        if current_position is not None and current_position["symbol"] != symbol:
            return None, None, "symbol_mismatch"

        if current_position is None:
            committed_cost = 0.0
            current_net_risk = 0.0
        else:
            committed_cost = current_position["total_cost"]
            current_net_risk = current_position["projected_net_loss_at_stop"]

        remaining_risk_budget = risk_cap - current_net_risk
        remaining_capital = self.working_capital - committed_cost

        if remaining_risk_budget <= 0 or remaining_capital <= 0:
            return None, None, "capital_or_risk"

        raw_risk_distance = entry_price * self.stop_loss_pct
        if raw_risk_distance <= 0:
            return None, None, "risk"

        max_by_risk = int(remaining_risk_budget // raw_risk_distance)
        max_by_capital = int(remaining_capital // entry_price)
        candidate_max = min(max_by_risk, max_by_capital)

        if candidate_max <= 0:
            return None, None, "capital_or_risk"

        for quantity in range(candidate_max, 0, -1):
            snapshot, ticket = self._project_position_after_tranche(
                current_position=current_position,
                symbol=symbol,
                entry_price=entry_price,
                quantity=quantity,
                trade_id=trade_id,
                timestamp=timestamp,
            )
            is_valid, reason = self._can_accept_position_snapshot(snapshot)
            if is_valid:
                return snapshot, ticket, None

            if reason == "capital" and current_position is not None and current_position["current_tranches"] >= self.max_tranches:
                return None, None, "max_tranches"

        return None, None, "friction"

    def _print_trade_ticket(self, ticket: dict) -> None:
        """Print a clear, structured simulated trade ticket with tranche info."""
        tranche_label = f"[TRANCHE {ticket['tranche_number']}/{ticket['max_tranches']}]"
        if ticket['tranche_number'] == 1:
            ticket_type = "📝  INITIAL ENTRY"
        else:
            ticket_type = "📐  SCALE-IN (PYRAMID)"
        logging.info("")
        logging.info("╔══════════════════════════════════════════════════════════╗")
        logging.info(f"║  {ticket_type:<45} {tranche_label}║")
        logging.info(f"║           SIMULATED TRADE TICKET                        ║")
        logging.info("╠══════════════════════════════════════════════════════════╣")
        logging.info(f"║  Trade ID     :  #{ticket['trade_id']:<39}║")
        logging.info(f"║  Position ID  :  #{ticket['position_id']:<39}║")
        logging.info(f"║  Symbol       :  {ticket['symbol']:<40}║")
        logging.info(f"║  Side         :  {ticket['side']:<40}║")
        logging.info(f"║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Entry Price  :  ₹{ticket['entry_price']:>10,.2f}{'':<28}║")
        logging.info(f"║  Avg Entry    :  ₹{ticket['avg_entry_price']:>10,.2f}  (VWAP Weighted){'':<10}║")
        logging.info(f"║  Stop Loss    :  ₹{ticket['stop_loss_price']:>10,.2f}  (−{self.stop_loss_pct*100:.1f}%){'':<18}║")
        logging.info(f"║  Target Price :  ₹{ticket['target_price']:>10,.2f}  ({ticket['risk_reward']}){'':<19}║")
        logging.info(f"║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Tranche Qty  :  {ticket['tranche_quantity']:<40}║")
        logging.info(f"║  Total Qty    :  {ticket['total_quantity']:<40}║")
        logging.info(f"║  Total Cost   :  ₹{ticket['total_cost']:>10,.2f}{'':<28}║")
        logging.info(f"║──────────────────────────────────────────────────────────║")
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
    ) -> None:
        """
        Print a structured TRADE CLOSED ticket to the terminal.
        Called by close_position() on every SL hit or target hit.
        Mirrors the entry ticket's box-drawing style for consistency.
        """
        pnl_icon    = "🟢" if pnl >= 0 else "🔴"
        pnl_sign    = "+" if pnl >= 0 else ""
        exit_label  = f"₹{exit_price:,.2f}"
        pnl_label   = f"{pnl_sign}₹{pnl:,.2f}  ({pnl_sign}{pnl_pct:.2f}%)"
        gross_label = f"₹{gross_pnl:,.2f}"
        charges_label = f"₹{charges:,.2f}"
        daily_label = f"₹{self._daily_pnl:,.2f}"
        wcap_label  = f"₹{self.working_capital:,.2f}"

        tranche_label = f"{pos['current_tranches']}/{pos['max_tranches']}"
        logging.info("")
        logging.info("╔══════════════════════════════════════════════════════════╗")
        logging.info(f"║  {pnl_icon}  TRADE CLOSED  ──  {result:<35}║")
        logging.info("╠══════════════════════════════════════════════════════════╣")
        logging.info(f"║  Position ID  :  #{pos['position_id']:<39}║")
        logging.info(f"║  Symbol       :  {pos['symbol']:<40}║")
        logging.info(f"║  Tranches     :  {tranche_label:<40}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Avg Entry    :  ₹{pos['average_entry_price']:>10,.2f}{'':<28}║")
        logging.info(f"║  Exit  Price  :  {exit_label:<42}║")
        logging.info(f"║  Quantity     :  {pos['quantity']:<40}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Gross P&L    :  {gross_label:<42}║")
        logging.info(f"║  Costs        :  {charges_label:<42}║")
        logging.info(f"║  Net P&L      :  {pnl_label:<42}║")
        logging.info(f"║  Daily P&L    :  {daily_label:<42}║")
        logging.info(f"║  Working Cap  :  {wcap_label:<42}║")
        logging.info("╚══════════════════════════════════════════════════════════╝")
        logging.info("")
