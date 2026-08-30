"""
execution_engine.py — Institutional Multi-Tranche Pyramiding Execution Engine
=============================================================================
Simulates trade execution for liquid NSE Cash Equities (nse_cm) with strict,
mathematical risk management and a 3-Stage Pyramiding (Scale-In on Strength)
state machine.

Core Architectural Features
────────────────────────────
1. Capital Allocation:
   • Total Capital    : ₹10,017.00
   • Working Capital  : ₹5,008.50 (50% intraday active deployment)
   • Backup Capital   : ₹5,008.50 (50% reserve buffer)
   • Risk Per Setup   : ≤ ₹100.00
   • Daily Loss Limit : ₹200.00 (Hard circuit breaker)

2. 3-Stage Multi-Tranche Pyramiding:
   • Tranche 1 (Base)   : 33% of Working Capital (≈ ₹1,652.80)
   • Tranche 2 (Scale 1): 33% of Working Capital (≈ ₹1,652.80)
   • Tranche 3 (Scale 2): 34% of Working Capital (≈ ₹1,702.90)
   • Quantity: Q_i = floor(Tranche_Capital_i / P_entry_i) where Q_i ≥ 1.

3. Scale-In on Strength & Zero-Risk Locks:
   • State 0 (IDLE)              → Fills Tranche 1, SL = Entry1 × (1 - 0.005), TP = Entry1 × (1 + 0.010).
   • State 1 (HOLDING_TRANCHE_1) → Trigger: Price ≥ Entry1 × 1.005 (+0.50%) & VWAP Signal.
                                   Trails SL to Entry1 (Breakeven), fills Tranche 2,
                                   recalculates VWAP Avg Entry & 1:2 TP.
   • State 2 (HOLDING_TRANCHE_2) → Trigger: Price ≥ Entry2 × 1.005 (+0.50%) & VWAP Signal.
                                   Trails SL to ≥ Entry2, fills Tranche 3,
                                   recalculates VWAP Avg Entry & 1:2 TP.
   • State 3 (MAX_TRANCHES_HELD) → Fully scaled position holding to TP / SL / EOD.

4. Exit Priority & Purged Time Stop:
   • All 40-candle / 40-minute time-stop exits are PERMANENTLY REMOVED.
   • Priority 1: Dynamic Stop Loss Hit (Low_t ≤ Global Stop Loss)
   • Priority 2: 1:2 Profit Target Hit (High_t ≥ Global Target Price)
   • Priority 3: 15:20:00 IST EOD Auto-Square-Off

5. Statutory Net-Profit Friction Gate & CSV Persistence:
   • NSE Intraday charges: Brokerage, STT (Sell), Exchange Fee (0.00345%), GST (18%), Stamp Duty (0.003%), SEBI.
   • Pre-order validation verifies net trade expectancy > 0.
   • Persistent ledger appended to `trades.csv` on position close.
"""

import csv
from enum import Enum
import logging
import math
import os
import queue
import threading
from datetime import date, datetime
from typing import Any, Optional, Union

from market_schedule import BaseMarketSchedule, NSEMarketSchedule, get_market_schedule


# ── Global Capital Partitioning & Risk Constants ────────────────────────
TOTAL_CAPITAL = 10010.06
WORKING_CAPITAL = 5005.03   # 50% intraday deployment limit
BACKUP_CAPITAL = 5005.03    # 50% reserve buffer
RISK_PER_TRADE = 100.00     # Max initial risk per setup
DAILY_LOSS_LIMIT = 200.00   # Hard daily loss circuit breaker

# Tranche fractions of Working Capital
TRANCHE_FRACTIONS = [0.33, 0.33, 0.34]
MAX_TRANCHES = 3

# Strategy parameters
DEFAULT_STOP_LOSS_PCT = 0.0050   # 0.50% initial risk distance
DEFAULT_PROFIT_TARGET_PCT = 0.0100  # 1.00% target (1:2 R:R)
TRANCHE2_TRIGGER_PCT = 0.0030       # +0.30% unrealized gain required to unlock Tranche 2
SCALE_IN_GAIN_TRIGGER_PCT = 0.0030  # +0.30% unrealized gain required to unlock next tranche
REENTRY_COOLDOWN_CANDLES = 10       # Minimum completed candles before re-entering after an exit
MIN_NET_RR = 1.5                    # Minimum Net Risk-to-Reward ratio after all statutory friction
MIN_NET_PROFIT = 3.0                # Absolute floor in rupees to prevent microscopic wins
MIN_NET_PROFIT_MULTIPLIER = 2.0     # Profit must be at least 2x the cost of doing business

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


class PyramidingState(str, Enum):
    """Explicit multi-tranche pyramiding state machine."""
    IDLE = "IDLE"
    HOLDING_TRANCHE_1 = "HOLDING_TRANCHE_1"
    HOLDING_TRANCHE_2 = "HOLDING_TRANCHE_2"
    MAX_TRANCHES_HELD = "MAX_TRANCHES_HELD"
    CLOSED = "CLOSED"


class PaperTrader:
    """
    Production-grade Quantitative Paper-Trading Engine with Multi-Tranche
    Pyramiding (Scale-In on Strength) state machine and statutory friction validation.
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

        logging.info("=" * 60)
        logging.info("  PAPER TRADER INITIALIZED (Multi-Tranche Pyramiding v3)")
        logging.info(f"  Total Capital     : ₹{self.total_capital:,.2f}")
        logging.info(f"  Working Capital   : ₹{self.working_capital:,.2f}")
        logging.info(f"  Backup Capital    : ₹{self.backup_capital:,.2f}")
        logging.info(f"  Daily Loss Limit  : ₹{self.daily_loss_limit:,.2f}")
        logging.info(f"  Risk Per Setup    : ≤ ₹{self.risk_per_trade:,.2f}")
        logging.info(f"  Tranche 1 (Base)  : ₹{self.tranche_capitals[0]:,.2f} (33%)")
        logging.info(f"  Tranche 2 (Scale1): ₹{self.tranche_capitals[1]:,.2f} (33%)")
        logging.info(f"  Tranche 3 (Scale2): ₹{self.tranche_capitals[2]:,.2f} (34%)")
        logging.info("  Time Stop         : PERMANENTLY DISABLED (MOC Removed)")
        logging.info(f"  Trade Log (CSV)   : {self._csv_log_path}")
        logging.info("=" * 60)

    # ────────────────────────────────────────────────────────────────────
    #  STATUTORY CHARGES & FRICTION CALCULATIONS (NSE CASH INTRADAY)
    # ────────────────────────────────────────────────────────────────────

    def calculate_entry_leg_charges(self, quantity: int, price: float) -> dict:
        """
        Compute statutory transaction costs on BUY leg:
          • Brokerage: min(₹20, 0.03% × Turnover)
          • Exchange Turnover Fee: 0.00345% × Turnover
          • Stamp Duty: 0.003% × Turnover (Buy only)
          • SEBI Charges: 0.000001 × Turnover (₹10/Crore)
          • GST: 18% on (Brokerage + Exchange Fee)
        """
        turnover = quantity * price
        brokerage = min(20.0, turnover * 0.0003)
        exchange_fee = turnover * 0.0000345
        stamp_duty = turnover * 0.00003
        sebi_fee = turnover * 0.000001
        gst = (brokerage + exchange_fee) * 0.18
        total_charges = brokerage + exchange_fee + stamp_duty + sebi_fee + gst

        return {
            "turnover": turnover,
            "brokerage": brokerage,
            "exchange_fee": exchange_fee,
            "stamp_duty": stamp_duty,
            "sebi_fee": sebi_fee,
            "gst": gst,
            "total_charges": total_charges,
        }

    def calculate_exit_leg_charges(self, quantity: int, price: float) -> dict:
        """
        Compute statutory transaction costs on SELL leg:
          • Brokerage: min(₹20, 0.03% × Turnover)
          • STT: 0.025% × Turnover (Sell only)
          • Exchange Turnover Fee: 0.00345% × Turnover
          • SEBI Charges: 0.000001 × Turnover (₹10/Crore)
          • GST: 18% on (Brokerage + Exchange Fee)
        """
        turnover = quantity * price
        brokerage = min(20.0, turnover * 0.0003)
        stt = turnover * 0.00025
        exchange_fee = turnover * 0.0000345
        sebi_fee = turnover * 0.000001
        gst = (brokerage + exchange_fee) * 0.18
        total_charges = brokerage + stt + exchange_fee + sebi_fee + gst

        return {
            "turnover": turnover,
            "brokerage": brokerage,
            "stt": stt,
            "exchange_fee": exchange_fee,
            "sebi_fee": sebi_fee,
            "gst": gst,
            "total_charges": total_charges,
        }

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

    # ────────────────────────────────────────────────────────────────────
    #  PYRAMIDING STATE MACHINE & EXECUTION
    # ────────────────────────────────────────────────────────────────────

    def execute_trade(
        self,
        signal_data: dict,
        timestamp: Optional[datetime] = None,
        atr_14: Optional[float] = None,
        atr: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Process a confirmed VWAP_PULLBACK_BUY signal and advance the
        Pyramiding State Machine (State 0 -> State 1 -> State 2 -> State 3).
        Ingests dynamic ATR_14 for volatility-based risk-to-reward calculation.
        """
        with self.lock:
            trade_timestamp = self._resolve_timestamp(timestamp, signal_data)
            self._check_day_reset(trade_timestamp)

            if self._halted:
                logging.warning(
                    "⛔  TRADE BLOCKED — Daily loss limit "
                    f"(₹{self.daily_loss_limit:,.2f}) reached. All trading halted."
                )
                return None

            entry_price = float(signal_data.get("VWAP", 0))
            symbol = signal_data.get("symbol", "M&M")
            close_price = signal_data.get("Close")
            if close_price is not None:
                self._set_latest_price(float(close_price), trade_timestamp)

            if entry_price <= 0:
                logging.error("Invalid entry price for execution. Skipping.")
                return None

            # Ingest and validate dynamic ATR (14-period)
            raw_atr = atr_14 if atr_14 is not None else atr
            if raw_atr is None:
                raw_atr = signal_data.get("ATR_14", signal_data.get("atr", signal_data.get("atr_14")))

            pos = self._open_position

            # ── Guard: Symbol Mismatch ──────────────────────────────────
            if pos is not None and pos["symbol"] != symbol:
                logging.info(
                    f"⏳ Skipping signal — already holding open position in {pos['symbol']} "
                    f"({pos['current_tranches']}/{self.max_tranches} tranches)."
                )
                return None

            # ── STATE 0: IDLE → TRANCHE 1 (Base Entry) ──────────────────
            if pos is None:
                # ── Post-Stop-Loss Cooldown Firewall ────────────────────
                if self.candles_since_last_sl < self.reentry_cooldown_candles:
                    logging.info(
                        f"[COOLDOWN] Signal ignored. Waiting {self.reentry_cooldown_candles - self.candles_since_last_sl} "
                        "more candles after previous stop-out."
                    )
                    return None

                # Type & Value Failsafe: ATR validation for Tranche 1 dynamic volatility distance
                if raw_atr is None:
                    logging.error(
                        f"[ATR GATE] Rejected trade entry in {symbol}: missing atr_14 parameter. "
                        "Engine remains in IDLE."
                    )
                    return None
                try:
                    current_atr = float(raw_atr)
                    if current_atr <= 0.0 or not math.isfinite(current_atr):
                        logging.error(
                            f"[ATR GATE] Rejected trade entry in {symbol}: invalid atr_14 value ({raw_atr}). "
                            "Engine remains in IDLE."
                        )
                        return None
                except (ValueError, TypeError):
                    logging.error(
                        f"[ATR GATE] Rejected trade entry in {symbol}: non-numeric atr_14 ({raw_atr}). "
                        "Engine remains in IDLE."
                    )
                    return None

                return self._execute_tranche_1(
                    symbol=symbol,
                    entry_price=entry_price,
                    timestamp=trade_timestamp,
                    current_atr=current_atr,
                )

            # ── Scale-In Evaluation (State 1 or State 2) ────────────────
            current_tranches = pos["current_tranches"]
            if current_tranches >= self.max_tranches:
                logging.info(
                    f"⏳ Max pyramiding tranches reached ({current_tranches}/{self.max_tranches}) "
                    f"— holding full position in {symbol}."
                )
                return None

            current_price = self._latest_price if self._latest_price is not None else entry_price

            # ── STATE 1: HOLDING_TRANCHE_1 → TRANCHE 2 (Scale 1) ────────
            if current_tranches == 1:
                entry_atr = float(pos.get("atr_14") or self.entry_atr or 1.0)
                avg_entry = float(pos["average_entry_price"])
                # Scale-in requires a confirmed move of 2.0x the current ATR
                tranche2_trigger_distance = round(2.0 * entry_atr, 2)
                tranche2_trigger_price = round(avg_entry + tranche2_trigger_distance, 2)

                if current_price < tranche2_trigger_price:
                    logging.info(
                        f"[SCALE-IN CHECK] Tranche 2 gate: Price ₹{current_price:,.2f} < "
                        f"₹{tranche2_trigger_price:,.2f} trigger (2.0x ATR: ₹{tranche2_trigger_distance:.2f}). "
                        "Holding Tranche 1."
                    )
                    return None

                return self._execute_tranche_2(entry_price, trade_timestamp)

            # ── STATE 2: HOLDING_TRANCHE_2 → TRANCHE 3 (Scale 2) ────────
            if current_tranches == 2:
                entry_atr = float(pos.get("atr_14") or self.entry_atr or 1.0)
                p2 = float(pos["tranches"][1]["entry_price"])
                tranche3_trigger_distance = round(2.0 * entry_atr, 2)
                tranche3_trigger_price = round(p2 + tranche3_trigger_distance, 2)

                if current_price < tranche3_trigger_price:
                    logging.info(
                        f"[SCALE-IN CHECK] Tranche 3 gate: Price ₹{current_price:,.2f} < "
                        f"₹{tranche3_trigger_price:,.2f} trigger (2.0x ATR: ₹{tranche3_trigger_distance:.2f}). "
                        "Holding Tranche 2."
                    )
                    return None

                return self._execute_tranche_3(entry_price, trade_timestamp)

            return None

    def _execute_tranche_1(
        self,
        symbol: str,
        entry_price: float,
        timestamp: datetime,
        current_atr: float,
    ) -> Optional[dict]:
        """Execute Base Entry (Tranche 1: 33% of Working Capital) with dynamic ATR volatility model."""
        tranche_idx = 0
        allocated_capital = self.tranche_capitals[tranche_idx]
        qty = math.floor(allocated_capital / entry_price)
        if qty < 1:
            qty = 1  # Minimum 1 share for liquid lower denomination stocks

        entry_costs = self.calculate_entry_leg_charges(qty, entry_price)
        turnover = entry_costs["turnover"]
        friction = entry_costs["total_charges"]

        # ── Dynamic Volatility (ATR) Model ──────────────────────────────
        # Volatility unit: 2.0 * current_atr (Wick-Immune buffer)
        stop_loss_distance = round(2.0 * current_atr, 2)
        initial_stop_loss = round(entry_price - stop_loss_distance, 2)

        # Anchored Take-Profit: strictly 1:2 R:R (reward = 2.0 * risk)
        initial_target_price = round(entry_price + (2.0 * stop_loss_distance), 2)

        stop_loss_price = initial_stop_loss
        target_price = initial_target_price

        # ── True Net-R:R Friction Gate Validation ─────────────────────────
        exit_costs_target = self.calculate_exit_leg_charges(qty, target_price)
        total_friction = friction + exit_costs_target["total_charges"]

        # Calculate Absolute True Math
        gross_profit = (target_price - entry_price) * qty
        net_profit = gross_profit - total_friction

        gross_loss = (entry_price - stop_loss_price) * qty
        net_loss = gross_loss + total_friction  # Costs amplify the total loss

        actual_net_rr = net_profit / net_loss if net_loss > 0 else 0.0

        if actual_net_rr < MIN_NET_RR:
            logging.warning(
                f"[FRICTION GATE FAILED] Net R:R is 1:{actual_net_rr:.2f} (Requires minimum 1:{MIN_NET_RR:.1f}). "
                "Costs eating too much margin."
            )
            return None

        if net_profit < MIN_NET_PROFIT:
            logging.warning(
                f"[FRICTION GATE FAILED] Net Profit (₹{net_profit:.2f}) is below absolute floor (₹{MIN_NET_PROFIT:.2f})."
            )
            return None

        if net_profit < (MIN_NET_PROFIT_MULTIPLIER * total_friction):
            logging.warning(
                f"[FRICTION GATE FAILED] Net Profit (₹{net_profit:,.2f}) is too small compared to estimated costs (₹{total_friction:,.2f})."
            )
            return None

        projected_net_profit = net_profit

        # Check working capital budget
        total_cost = turnover + friction
        if total_cost > self.working_capital:
            logging.warning(
                f"[CAPITAL GATE] Tranche 1 cost (₹{total_cost:,.2f}) exceeds "
                f"Working Capital (₹{self.working_capital:,.2f}). Order blocked."
            )
            return None

        self._trade_count += 1
        trade_id = self._trade_count
        position_id = trade_id

        tranche_record = {
            "tranche_num": 1,
            "trade_id": trade_id,
            "quantity": qty,
            "entry_price": entry_price,
            "entry_turnover": turnover,
            "entry_friction": friction,
            "timestamp": timestamp,
        }

        exit_costs_stop = self.calculate_exit_leg_charges(qty, stop_loss_price)
        gross_loss_stop = qty * (entry_price - stop_loss_price)
        net_loss_at_stop = gross_loss_stop + friction + exit_costs_stop["total_charges"]

        snapshot = {
            "position_id": position_id,
            "symbol": symbol,
            "side": "BUY",
            "quantity": qty,
            "initial_entry_price": entry_price,
            "average_entry_price": entry_price,
            "entry_notional": turnover,
            "entry_friction_total": friction,
            "total_cost": total_cost,
            "current_tranches": 1,
            "max_tranches": self.max_tranches,
            "atr_14": current_atr,
            "entry_atr": current_atr,
            "stop_loss_distance": stop_loss_distance,
            "stop_loss_price": stop_loss_price,
            "target_price": target_price,
            "initial_target_price": target_price,
            "risk_distance": stop_loss_distance,
            "projected_net_loss_at_stop": net_loss_at_stop,
            "projected_net_profit_at_target": projected_net_profit,
            "stop_exit_charges": exit_costs_stop["total_charges"],
            "target_exit_charges": exit_costs_target["total_charges"],
            "tranches": [tranche_record],
            "timestamp": timestamp,
            "breakeven_armed": False,
        }

        self._open_position = snapshot
        self._state = PyramidingState.HOLDING_TRANCHE_1
        self._entry_timestamp = timestamp
        self.entry_atr = current_atr
        self.candles_held = 0

        ticket = self._build_ticket(snapshot, 1, qty, entry_price, trade_id)
        self._trade_log.append(ticket)
        self._print_trade_ticket(ticket)

        logging.info(
            f"✅ [ENTRY TRANCHE 1/{self.max_tranches}] Base position established in {symbol}. "
            f"ATR_14: {current_atr:.2f} | SL Distance: ₹{stop_loss_distance:.2f} | "
            f"SL: ₹{stop_loss_price:,.2f} | Target: ₹{target_price:,.2f} | "
            f"State: {self._state.value}"
        )
        return ticket

    def _execute_tranche_2(
        self,
        entry_price: float,
        timestamp: datetime,
    ) -> Optional[dict]:
        """Execute Scale 1 (Tranche 2: 33% of Working Capital) + Zero-Risk Lock."""
        pos = self._open_position
        tranche_idx = 1
        allocated_capital = self.tranche_capitals[tranche_idx]
        qty2 = math.floor(allocated_capital / entry_price)
        if qty2 < 1:
            qty2 = 1

        entry_costs2 = self.calculate_entry_leg_charges(qty2, entry_price)
        new_total_cost = pos["total_cost"] + entry_costs2["turnover"] + entry_costs2["total_charges"]

        if new_total_cost > self.working_capital:
            logging.warning(
                f"[CAPITAL GATE] Scale-In Tranche 2 would exceed Working Capital "
                f"(₹{new_total_cost:,.2f} > ₹{self.working_capital:,.2f}). Scale-in skipped."
            )
            return None

        # Record Tranche 2
        self._trade_count += 1
        trade_id = self._trade_count
        t1 = pos["tranches"][0]
        q1 = t1["quantity"]
        p1 = t1["entry_price"]

        t2_record = {
            "tranche_num": 2,
            "trade_id": trade_id,
            "quantity": qty2,
            "entry_price": entry_price,
            "entry_turnover": entry_costs2["turnover"],
            "entry_friction": entry_costs2["total_charges"],
            "timestamp": timestamp,
        }

        total_qty = q1 + qty2
        vwap_avg_entry = round(((p1 * q1) + (entry_price * qty2)) / total_qty, 2)

        # Zero-Risk Lock: Trail SL to max(P_entry_1, Avg_Entry × 0.995)
        new_stop_loss = round(max(p1, vwap_avg_entry * (1.0 - self.stop_loss_pct)), 2)

        # ANCHORED TAKE-PROFIT TARGET: Target is permanently anchored to Tranche 1 setup (P1 * 1.010)
        anchored_target_price = pos.get("initial_target_price", pos["target_price"])

        # Friction validation on combined position using anchored target
        total_entry_friction = pos["entry_friction_total"] + entry_costs2["total_charges"]
        exit_costs_target = self.calculate_exit_leg_charges(total_qty, anchored_target_price)
        total_friction = total_entry_friction + exit_costs_target["total_charges"]
        projected_net_profit = (total_qty * (anchored_target_price - vwap_avg_entry)) - total_friction

        if projected_net_profit <= 0:
            logging.warning(
                "[FRICTION GATE] Scale-In Tranche 2 Expectancy Negative — Scale-in Blocked."
            )
            return None

        exit_costs_stop = self.calculate_exit_leg_charges(total_qty, new_stop_loss)
        net_loss_at_stop = (total_qty * max(0.0, vwap_avg_entry - new_stop_loss)) + total_entry_friction + exit_costs_stop["total_charges"]

        # Update position snapshot
        pos["quantity"] = total_qty
        pos["average_entry_price"] = vwap_avg_entry
        pos["entry_notional"] = (p1 * q1) + entry_costs2["turnover"]
        pos["entry_friction_total"] = total_entry_friction
        pos["total_cost"] = new_total_cost
        pos["current_tranches"] = 2
        pos["stop_loss_price"] = new_stop_loss
        pos["target_price"] = anchored_target_price
        pos["initial_target_price"] = anchored_target_price
        pos["risk_distance"] = vwap_avg_entry - new_stop_loss
        pos["projected_net_loss_at_stop"] = net_loss_at_stop
        pos["projected_net_profit_at_target"] = projected_net_profit
        pos["stop_exit_charges"] = exit_costs_stop["total_charges"]
        pos["target_exit_charges"] = exit_costs_target["total_charges"]
        pos["tranches"].append(t2_record)
        pos["breakeven_armed"] = True

        self._state = PyramidingState.HOLDING_TRANCHE_2

        ticket = self._build_ticket(pos, 2, qty2, entry_price, trade_id)
        self._trade_log.append(ticket)
        self._print_trade_ticket(ticket)

        logging.info(
            f"🛡️  [ZERO-RISK LOCK ARMED] Tranche 1 protected at breakeven floor (SL: ₹{new_stop_loss:,.2f})."
        )
        logging.info(
            f"🔄 [POSITION RECALCULATED] Tranches: 2/{self.max_tranches} | "
            f"New VWAP Avg Entry: ₹{vwap_avg_entry:,.2f} | Anchored Target: ₹{anchored_target_price:,.2f} | "
            f"State: {self._state.value}"
        )
        return ticket

    def _execute_tranche_3(
        self,
        entry_price: float,
        timestamp: datetime,
    ) -> Optional[dict]:
        """Execute Scale 2 (Tranche 3: 34% of Working Capital) + Full Zero-Risk Lock."""
        pos = self._open_position
        tranche_idx = 2
        allocated_capital = self.tranche_capitals[tranche_idx]
        qty3 = math.floor(allocated_capital / entry_price)
        if qty3 < 1:
            qty3 = 1

        entry_costs3 = self.calculate_entry_leg_charges(qty3, entry_price)
        new_total_cost = pos["total_cost"] + entry_costs3["turnover"] + entry_costs3["total_charges"]

        if new_total_cost > self.working_capital:
            logging.warning(
                f"[CAPITAL GATE] Scale-In Tranche 3 would exceed Working Capital "
                f"(₹{new_total_cost:,.2f} > ₹{self.working_capital:,.2f}). Scale-in skipped."
            )
            return None

        # Record Tranche 3
        self._trade_count += 1
        trade_id = self._trade_count
        t1, t2 = pos["tranches"][0], pos["tranches"][1]
        p1, q1 = t1["entry_price"], t1["quantity"]
        p2, q2 = t2["entry_price"], t2["quantity"]

        t3_record = {
            "tranche_num": 3,
            "trade_id": trade_id,
            "quantity": qty3,
            "entry_price": entry_price,
            "entry_turnover": entry_costs3["turnover"],
            "entry_friction": entry_costs3["total_charges"],
            "timestamp": timestamp,
        }

        total_qty = q1 + q2 + qty3
        total_notional = (p1 * q1) + (p2 * q2) + (entry_price * qty3)
        vwap_avg_entry = round(total_notional / total_qty, 2)

        # Zero-Risk Lock: Trail SL to ≥ P_entry_2 (Locking profit on T1, breakeven on T2)
        new_stop_loss = round(max(p2, vwap_avg_entry * (1.0 - self.stop_loss_pct)), 2)

        # ANCHORED TAKE-PROFIT TARGET: Target is permanently anchored to Tranche 1 setup (P1 * 1.010)
        anchored_target_price = pos.get("initial_target_price", pos["target_price"])

        total_entry_friction = pos["entry_friction_total"] + entry_costs3["total_charges"]
        exit_costs_target = self.calculate_exit_leg_charges(total_qty, anchored_target_price)
        total_friction = total_entry_friction + exit_costs_target["total_charges"]
        projected_net_profit = (total_qty * (anchored_target_price - vwap_avg_entry)) - total_friction

        if projected_net_profit <= 0:
            logging.warning(
                "[FRICTION GATE] Scale-In Tranche 3 Expectancy Negative — Scale-in Blocked."
            )
            return None

        exit_costs_stop = self.calculate_exit_leg_charges(total_qty, new_stop_loss)
        net_loss_at_stop = (total_qty * max(0.0, vwap_avg_entry - new_stop_loss)) + total_entry_friction + exit_costs_stop["total_charges"]

        # Update position snapshot
        pos["quantity"] = total_qty
        pos["average_entry_price"] = vwap_avg_entry
        pos["entry_notional"] = total_notional
        pos["entry_friction_total"] = total_entry_friction
        pos["total_cost"] = new_total_cost
        pos["current_tranches"] = 3
        pos["stop_loss_price"] = new_stop_loss
        pos["target_price"] = anchored_target_price
        pos["initial_target_price"] = anchored_target_price
        pos["risk_distance"] = vwap_avg_entry - new_stop_loss
        pos["projected_net_loss_at_stop"] = net_loss_at_stop
        pos["projected_net_profit_at_target"] = projected_net_profit
        pos["stop_exit_charges"] = exit_costs_stop["total_charges"]
        pos["target_exit_charges"] = exit_costs_target["total_charges"]
        pos["tranches"].append(t3_record)
        pos["breakeven_armed"] = True

        self._state = PyramidingState.MAX_TRANCHES_HELD

        ticket = self._build_ticket(pos, 3, qty3, entry_price, trade_id)
        self._trade_log.append(ticket)
        self._print_trade_ticket(ticket)

        logging.info(
            f"🛡️  [PROFIT LOCK ARMED] SL ratcheted to ₹{new_stop_loss:,.2f} (Locking T1 profit & T2 breakeven)."
        )
        logging.info(
            f"🔄 [POSITION FULLY SCALED] Tranches: 3/{self.max_tranches} | "
            f"Final VWAP Avg Entry: ₹{vwap_avg_entry:,.2f} | Anchored Target: ₹{anchored_target_price:,.2f} | "
            f"State: {self._state.value}"
        )
        return ticket

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
            "side": "BUY",
            "tranche_number": tranche_num,
            "max_tranches": self.max_tranches,
            "entry_price": round(entry_price, 2),
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
            if live_price >= pos["target_price"]:
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

    def close_position(
        self,
        exit_price: float,
        timestamp: Optional[datetime] = None,
        reason: str = "Signal Exit",
    ) -> Optional[dict]:
        """
        Close full position, calculate net P&L, update working capital,
        and append a structured record to `trades.csv`.
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
            tranches_filled = pos["current_tranches"]

            gross_pnl = (exit_price - avg_entry_price) * total_qty
            exit_leg_costs = self.calculate_exit_leg_charges(total_qty, exit_price)
            total_charges = pos["entry_friction_total"] + exit_leg_costs["total_charges"]
            net_pnl = gross_pnl - total_charges
            net_roi_pct = (net_pnl / pos["total_cost"]) * 100.0 if pos["total_cost"] > 0 else 0.0

            # Hold duration
            entry_ts = pos.get("timestamp") or self._entry_timestamp
            if entry_ts is not None and exit_timestamp is not None:
                hold_mins = round((exit_timestamp - entry_ts).total_seconds() / 60.0, 2)
            else:
                hold_mins = 0.0

            result = "PROFIT ✅" if net_pnl >= 0 else "LOSS ❌"

            # Update working capital & daily PnL
            self._daily_pnl += net_pnl
            self.working_capital += net_pnl
            final_balance = self.working_capital + self.backup_capital

            summary = {
                "trade_id": pos["position_id"],
                "symbol": pos["symbol"],
                "side": pos.get("side", "BUY"),
                "tranches_filled": tranches_filled,
                "avg_entry_price": round(avg_entry_price, 2),
                "exit_price": round(exit_price, 2),
                "total_quantity": total_qty,
                "quantity": total_qty,
                "exit_reason": reason,
                "reason": reason,
                "gross_pnl": round(gross_pnl, 2),
                "statutory_charges": round(total_charges, 2),
                "charges": round(total_charges, 2),
                "net_pnl": round(net_pnl, 2),
                "pnl": round(net_pnl, 2),
                "net_roi_pct": round(net_roi_pct, 2),
                "pnl_pct": round(net_roi_pct, 2),
                "ending_working_capital": round(self.working_capital, 2),
                "final_balance": round(final_balance, 2),
                "hold_duration_mins": hold_mins,
                "timestamp": exit_timestamp,
                "result": result,
            }

            # Persistent CSV ledger write
            try:
                self._append_trade_csv(summary)
            except Exception as exc:
                logging.error(f"Failed to append to trades.csv: {exc!s}")

            # Terminal ticket
            self._print_closed_ticket(
                pos,
                exit_price,
                gross_pnl,
                total_charges,
                net_pnl,
                net_roi_pct,
                result,
                reason,
            )

            # Reset position & state
            self._open_position = None
            self._entry_timestamp = None
            self._state = PyramidingState.CLOSED
            self.entry_atr = None
            if "Stop Loss" in reason:
                self.candles_since_last_sl = 0
            self.candles_held = 0

            # Daily Circuit Breaker Check
            if self._daily_pnl <= -self.daily_loss_limit:
                self._halted = True
                logging.warning("⛔ ══════════════════════════════════════════════════════")
                logging.warning(
                    f"⛔  DAILY LOSS LIMIT CIRCUIT BREAKER HIT | P&L: ₹{self._daily_pnl:,.2f}"
                )
                logging.warning("⛔  ALL INTRADAY TRADING HALTED FOR TODAY")
                logging.warning("⛔ ══════════════════════════════════════════════════════")

            return summary

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

                # ── Theta-Decay Defense (Time-Based Breakeven) ───────────
                # If we have held the trade for 15+ candles and it is in profit, lock risk to zero.
                if self._state == PyramidingState.HOLDING_TRANCHE_1 and self.candles_held >= 15:
                    if close_val > avg_entry:
                        current_sl = float(pos["stop_loss_price"])
                        if current_sl < avg_entry:
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
                    tranche2_trigger_price = round(avg_entry + tranche2_trigger_distance, 2)
                    distance_to_trigger = round(tranche2_trigger_price - close_val, 2)
                    logging.debug(
                        f"[SCALE-IN TELEMETRY] Current: ₹{close_val:.2f} | "
                        f"T2 Gate: ₹{tranche2_trigger_price:.2f} (2x ATR) | Distance: ₹{distance_to_trigger:.2f}"
                    )

            # ── Wick-Immune Stop-Loss Evaluation (Confirmed Candle Close) ──
            if self._open_position is not None and px is not None:
                pos = self._open_position
                close_val = float(px)
                sl_price = float(pos["stop_loss_price"])

                if close_val <= sl_price:
                    exit_reason = (
                        "Breakeven Stop (Close-Based)"
                        if pos.get("breakeven_armed") and sl_price >= pos["tranches"][0]["entry_price"]
                        else "Stop Loss (Close-Based)"
                    )
                    logging.warning(
                        f"[STOP LOSS TRIGGERED] Candle closed at ₹{close_val:,.2f} below SL ₹{sl_price:,.2f}. "
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

    @property
    def has_open_position(self) -> bool:
        return self._open_position is not None

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def latest_price(self) -> Optional[float]:
        return self._latest_price

    @property
    def avg_entry_price(self) -> Optional[float]:
        if self._open_position is not None:
            return float(self._open_position["average_entry_price"])
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
        logging.info("║           SIMULATED TRADE TICKET                        ║")
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
ExecutionEngine = PaperTrader
