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
from datetime import date
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
    """

    def __init__(
        self,
        total_capital: float = 10_000.0,
        working_capital_pct: float = 0.50,
        daily_loss_limit_pct: float = 0.02,
        risk_per_trade_pct: float = 0.01,
        stop_loss_pct: float = 0.005,
        reward_to_risk: float = 2.0,
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

        # ── Daily State (resets each trading day) ───────────────────
        self._current_date: Optional[date] = None
        self._daily_pnl: float             = 0.0
        self._trade_count: int             = 0
        self._halted: bool                 = False

        # ── Session Tracking ────────────────────────────────────────
        self._open_position: Optional[dict] = None
        self._trade_log: list               = []

        logging.info("=" * 60)
        logging.info("  PAPER TRADER INITIALIZED")
        logging.info(f"  Total Capital     : ₹{self.total_capital:,.2f}")
        logging.info(f"  Working Capital   : ₹{self.working_capital:,.2f}")
        logging.info(f"  Backup Capital    : ₹{self.backup_capital:,.2f}")
        logging.info(f"  Daily Loss Limit  : ₹{self.daily_loss_limit:,.2f}")
        logging.info(f"  Risk Per Trade    : ₹{self.risk_per_trade:,.2f}")
        logging.info("=" * 60)

    # ────────────────────────────────────────────────────────────────
    #  PUBLIC API
    # ────────────────────────────────────────────────────────────────

    def execute_trade(self, signal_data: dict) -> Optional[dict]:
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
        self._check_day_reset()

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

        # ── 4. Capital adequacy check ───────────────────────────────
        total_cost = quantity * entry_price
        if total_cost > self.working_capital:
            # Scale down to what working capital allows
            quantity   = int(self.working_capital / entry_price)
            total_cost = quantity * entry_price
            if quantity <= 0:
                logging.warning(
                    "Insufficient working capital for even 1 share. Skipping."
                )
                return None

        # ── 5. Build the Trade Ticket ───────────────────────────────
        potential_loss   = quantity * risk_distance
        potential_profit = quantity * (target_price - entry_price)

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
            "risk_reward":     f"1:{self.reward_to_risk:.0f}",
        }

        # ── 6. Record the position ─────────────────────────────────
        self._open_position = ticket
        self._trade_count  += 1
        self._trade_log.append(ticket)

        # ── 7. Print the Simulated Trade Ticket ─────────────────────
        self._print_trade_ticket(ticket)

        return ticket

    def close_position(self, exit_price: float) -> Optional[dict]:
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
        if self._open_position is None:
            logging.info("No open position to close.")
            return None

        pos       = self._open_position
        pnl       = (exit_price - pos["entry_price"]) * pos["quantity"]
        pnl_pct   = (pnl / pos["total_cost"]) * 100 if pos["total_cost"] else 0

        result = "PROFIT ✅" if pnl >= 0 else "LOSS ❌"

        summary = {
            "trade_id":    pos["trade_id"],
            "symbol":      pos["symbol"],
            "entry_price": pos["entry_price"],
            "exit_price":  round(exit_price, 2),
            "quantity":    pos["quantity"],
            "pnl":         round(pnl, 2),
            "pnl_pct":     round(pnl_pct, 2),
            "result":      result,
        }

        # Update daily P&L
        self._daily_pnl += pnl
        self.working_capital += pnl

        logging.info("=" * 60)
        logging.info(f"  📋  POSITION CLOSED — {result}")
        logging.info(f"  Entry : ₹{pos['entry_price']:,.2f}")
        logging.info(f"  Exit  : ₹{exit_price:,.2f}")
        logging.info(f"  Qty   : {pos['quantity']}")
        logging.info(f"  P&L   : ₹{pnl:,.2f}  ({pnl_pct:+.2f}%)")
        logging.info(f"  Daily P&L  : ₹{self._daily_pnl:,.2f}")
        logging.info(f"  Working Cap: ₹{self.working_capital:,.2f}")
        logging.info("=" * 60)

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

    def check_exit(self, live_price: float) -> Optional[dict]:
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
            return self.close_position(exit_price=pos["stop_loss_price"])

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
            return self.close_position(exit_price=pos["target_price"])

        # ── Neither threshold breached — position stays open ────────
        return None

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

    # ────────────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ────────────────────────────────────────────────────────────────

    def _check_day_reset(self) -> None:
        """
        Reset daily counters when a new trading day begins.
        This ensures the daily loss limit and trade count refresh
        automatically without manual intervention.
        """
        today = date.today()
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
        logging.info(f"║  Risk : Reward:  {ticket['risk_reward']:<40}║")
        logging.info("╚══════════════════════════════════════════════════════════╝")
        logging.info("")
