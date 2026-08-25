"""
execution_engine.py — Paper-Trading Execution Layer
====================================================
Simulates trade execution with strict, mathematical risk management.
No real orders are placed; every trade is logged as a simulated ticket.

Risk Management Model
─────────────────────
• Total Capital       : ₹10,000
• Working Capital     : 50% of Total  (₹5,000)  — the other 50% is backup
• Daily Loss Limit    : 2%  of Total  (₹200)    — halt trading if breached
• Risk Per Trade      : 1%  of Total  (₹100)    — max loss on any single trade
• Quantity Formula    : Risk_Per_Trade / (Entry - Stop_Loss)
• Stop Loss           : VWAP - 0.5%
• Target              : Entry + 2 × (Entry - Stop_Loss)   [1:2 R:R]
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

        # ── Day-reset check ─────────────────────────────────────────
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

            # ── Guard: already in an open position ──────────────────────
            if self._open_position is not None:
                logging.info(
                    "⏳  Skipping signal — already holding an open position "
                    f"(Entry: ₹{self._open_position['entry_price']:,.2f})"
                )
                return None

            # ── Extract data ────────────────────────────────────────────
            entry_price = float(signal_data.get("VWAP", 0))
            symbol      = signal_data.get("symbol", "RELIANCE")
            close_price = signal_data.get("Close")
            if close_price is not None:
                self._set_latest_price(float(close_price), trade_timestamp)

            if entry_price <= 0:
                logging.error("Invalid VWAP value for trade entry. Skipping.")
                return None

            # ── 1. Calculate Stop-Loss (VWAP - 0.5%) ───────────────────
            stop_loss_price = entry_price * (1 - self.stop_loss_pct)

            # ── 2. Calculate Target (1:2 Risk-to-Reward) ────────────────
            risk_distance   = entry_price - stop_loss_price
            target_price    = entry_price + (self.reward_to_risk * risk_distance)

            # ── 3. Quantity Sizing ──────────────────────────────────────
            #    Quantity = Risk_Per_Trade / (Entry - Stop_Loss)
            if risk_distance <= 0:
                logging.error("Risk distance is zero or negative. Skipping.")
                return None

            raw_quantity = self.risk_per_trade / risk_distance
            quantity     = int(raw_quantity)  # Floor to whole shares

            if quantity <= 0:
                logging.warning(
                    "Calculated quantity is 0 (price too high for current "
                    "risk budget). Skipping."
                )
                return None

            # ── 4. Capital and net-risk adequacy checks ─────────────────
            while quantity > 0:
                costs_at_stop = self._estimate_round_trip_costs(
                    quantity=quantity,
                    entry_price=entry_price,
                    exit_price=stop_loss_price,
                )
                gross_stop_loss = quantity * risk_distance
                net_stop_loss = gross_stop_loss + costs_at_stop["total_charges"]
                total_cost = costs_at_stop["buy_turnover"] + costs_at_stop["entry_charges"]

                if total_cost <= self.working_capital and net_stop_loss <= self.risk_per_trade:
                    break
                quantity -= 1

            if quantity <= 0:
                logging.warning(
                    "Insufficient working capital or net risk budget after "
                    "statutory charges. Skipping."
                )
                return None

            # ── 5. Net-Profit Gate (target-side projection) ───────────
            gross_expected_reward = quantity * (target_price - entry_price)
            projected_friction = self.calculate_friction(
                qty=quantity,
                entry_price=entry_price,
                exit_price=target_price,
            )
            expected_net_pnl = gross_expected_reward - projected_friction

            if expected_net_pnl <= 0:
                logging.warning(
                    "[TRADE REJECTED] Gross Target Profit "
                    f"(₹{gross_expected_reward:,.2f}) is fully consumed by "
                    f"Transaction Friction (₹{projected_friction:,.2f}). "
                    f"Net Expected PnL: ₹{expected_net_pnl:,.2f}."
                )
                return None

            # ── 6. Build the Trade Ticket ───────────────────────────────
            costs_at_stop = self._estimate_round_trip_costs(
                quantity=quantity,
                entry_price=entry_price,
                exit_price=stop_loss_price,
            )
            costs_at_target = self._estimate_round_trip_costs(
                quantity=quantity,
                entry_price=entry_price,
                exit_price=target_price,
            )
            potential_loss = quantity * risk_distance
            potential_profit = quantity * (target_price - entry_price)
            estimated_net_loss = potential_loss + costs_at_stop["total_charges"]
            estimated_net_profit = potential_profit - costs_at_target["total_charges"]
            total_cost = costs_at_stop["buy_turnover"] + costs_at_stop["entry_charges"]

            ticket = {
                "trade_id":        self._trade_count + 1,
                "symbol":          symbol,
                "side":            "BUY",
                "entry_price":     round(entry_price, 2),
                "stop_loss_price": round(stop_loss_price, 2),
                "target_price":    round(target_price, 2),
                "quantity":        quantity,
                "total_cost":      round(total_cost, 2),
                "risk_distance":   round(risk_distance, 2),
                "potential_loss":  round(potential_loss, 2),
                "potential_profit": round(potential_profit, 2),
                "estimated_charges_at_stop": round(costs_at_stop["total_charges"], 2),
                "estimated_charges_at_target": round(costs_at_target["total_charges"], 2),
                "estimated_net_loss": round(estimated_net_loss, 2),
                "estimated_net_profit": round(estimated_net_profit, 2),
                "risk_reward":     f"1:{self.reward_to_risk:.0f}",
                "timestamp":       trade_timestamp,
            }

            # ── 7. Record the position ─────────────────────────────────
            self._open_position = ticket
            self._trade_count  += 1
            self._trade_log.append(ticket)

            # ── 8. Print the Simulated Trade Ticket ─────────────────────
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

            pos       = self._open_position
            gross_pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
            cost_breakdown = self._estimate_round_trip_costs(
                quantity=pos["quantity"],
                entry_price=pos["entry_price"],
                exit_price=exit_price,
            )
            net_pnl = gross_pnl - cost_breakdown["total_charges"]
            pnl_pct = (net_pnl / pos["total_cost"]) * 100 if pos["total_cost"] else 0

            result = "PROFIT ✅" if net_pnl >= 0 else "LOSS ❌"

            summary = {
                "trade_id":    pos["trade_id"],
                "symbol":      pos["symbol"],
                "entry_price": pos["entry_price"],
                "exit_price":  round(exit_price, 2),
                "quantity":    pos["quantity"],
                "gross_pnl":   round(gross_pnl, 2),
                "charges":     round(cost_breakdown["total_charges"], 2),
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
                cost_breakdown["total_charges"],
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
                    f"(SL was ₹{pos['stop_loss_price']:,.2f})"
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
                    f"(Target was ₹{pos['target_price']:,.2f})"
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
                    f"₹{summary['net_pnl']:,.2f} | Reason: {reason}"
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

    def _estimate_round_trip_costs(
        self,
        quantity: int,
        entry_price: float,
        exit_price: float,
    ) -> dict:
        """Estimate NSE intraday equity round-trip friction components."""
        buy_turnover = quantity * entry_price
        sell_turnover = quantity * exit_price
        total_turnover = buy_turnover + sell_turnover

        buy_brokerage = min(20.0, buy_turnover * 0.0003)
        sell_brokerage = min(20.0, sell_turnover * 0.0003)
        brokerage = buy_brokerage + sell_brokerage
        stt = sell_turnover * 0.00025
        exchange_txn = total_turnover * 0.0000325
        stamp_duty = buy_turnover * 0.00003
        gst = (brokerage + exchange_txn) * 0.18
        total_charges = brokerage + stt + exchange_txn + stamp_duty + gst

        entry_charges = buy_brokerage + stamp_duty + (buy_turnover * 0.0000325) + ((buy_brokerage + (buy_turnover * 0.0000325)) * 0.18)
        exit_charges = sell_brokerage + stt + (sell_turnover * 0.0000325) + ((sell_brokerage + (sell_turnover * 0.0000325)) * 0.18)

        return {
            "buy_turnover": buy_turnover,
            "sell_turnover": sell_turnover,
            "brokerage": brokerage,
            "buy_brokerage": buy_brokerage,
            "sell_brokerage": sell_brokerage,
            "stt": stt,
            "exchange_txn": exchange_txn,
            "stamp_duty": stamp_duty,
            "gst": gst,
            "entry_charges": entry_charges,
            "exit_charges": exit_charges,
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

        buy_turnover = qty * entry_price
        sell_turnover = qty * exit_price
        total_turnover = buy_turnover + sell_turnover

        buy_brokerage = min(20.0, buy_turnover * 0.0003)
        sell_brokerage = min(20.0, sell_turnover * 0.0003)
        brokerage = buy_brokerage + sell_brokerage
        stt = sell_turnover * 0.00025
        exchange_txn = total_turnover * 0.0000325
        stamp_duty = buy_turnover * 0.00003
        gst = (brokerage + exchange_txn) * 0.18

        return brokerage + stt + exchange_txn + stamp_duty + gst

    def _print_trade_ticket(self, ticket: dict) -> None:
        """Print a clear, structured simulated trade ticket."""
        logging.info("")
        logging.info("╔══════════════════════════════════════════════════════════╗")
        logging.info("║           📝  SIMULATED TRADE TICKET                   ║")
        logging.info("╠══════════════════════════════════════════════════════════╣")
        logging.info(f"║  Trade ID     :  #{ticket['trade_id']:<39}║")
        logging.info(f"║  Symbol       :  {ticket['symbol']:<40}║")
        logging.info(f"║  Side         :  {ticket['side']:<40}║")
        logging.info(f"║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Entry Price  :  ₹{ticket['entry_price']:>10,.2f}{'':<28}║")
        logging.info(f"║  Stop Loss    :  ₹{ticket['stop_loss_price']:>10,.2f}  (−{self.stop_loss_pct*100:.1f}%){'':<18}║")
        logging.info(f"║  Target Price :  ₹{ticket['target_price']:>10,.2f}  ({ticket['risk_reward']}){'':<19}║")
        logging.info(f"║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Quantity     :  {ticket['quantity']:<40}║")
        logging.info(f"║  Total Cost   :  ₹{ticket['total_cost']:>10,.2f}{'':<28}║")
        logging.info(f"║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Max Loss     :  ₹{ticket['potential_loss']:>10,.2f}{'':<28}║")
        logging.info(f"║  Max Profit   :  ₹{ticket['potential_profit']:>10,.2f}{'':<28}║")
        logging.info(f"║  Est. Charges :  ₹{ticket['estimated_charges_at_target']:>10,.2f}{'':<28}║")
        logging.info(f"║  Net Loss Est.:  ₹{ticket['estimated_net_loss']:>10,.2f}{'':<28}║")
        logging.info(f"║  Net Prof Est.:  ₹{ticket['estimated_net_profit']:>10,.2f}{'':<28}║")
        logging.info(f"║  Risk : Reward:  {ticket['risk_reward']:<40}║")
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

        logging.info("")
        logging.info("╔══════════════════════════════════════════════════════════╗")
        logging.info(f"║  {pnl_icon}  TRADE CLOSED  ──  {result:<35}║")
        logging.info("╠══════════════════════════════════════════════════════════╣")
        logging.info(f"║  Trade ID     :  #{pos['trade_id']:<39}║")
        logging.info(f"║  Symbol       :  {pos['symbol']:<40}║")
        logging.info("║──────────────────────────────────────────────────────────║")
        logging.info(f"║  Entry Price  :  ₹{pos['entry_price']:>10,.2f}{'':<28}║")
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
