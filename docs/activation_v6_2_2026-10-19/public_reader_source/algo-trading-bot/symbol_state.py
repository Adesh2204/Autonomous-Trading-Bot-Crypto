"""
symbol_state.py — Isolated Symbol Execution State Container
===========================================================
Defines the per-symbol isolated runtime state container for Phase 5 multi-symbol execution:
- SymbolExecutionState: Lifecycle enum (SELECTED, ACTIVE, STANDBY, BLOCKED, ERROR)
- SymbolState: Dedicated container owning independent CandleBuilder, FeedHealthMonitor,
  ATRFirewall, rolling candle DataFrame, latest tick telemetry, and execution state.

Architectural Invariants:
1. Strict Isolation: Zero cross-symbol state contamination.
   Every watchlist symbol possesses its own dedicated CandleBuilder, FeedHealthMonitor,
   and ATRFirewall instances.
2. Dynamic STANDBY: If a symbol's volatility collapses below STANDBY_ATR_THRESHOLD for
   STANDBY_CONFIRMATION_COUNT consecutive readings, it transitions to STANDBY without
   affecting other active symbols.
3. Hysteresis Recovery: A symbol in STANDBY recovers to ACTIVE only after
   STANDBY_RECOVERY_CONFIRMATION_COUNT consecutive healthy ATR readings.
"""

from __future__ import annotations

import logging
import math
import config
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

import pandas as pd

from atr_firewall import ATRFirewall
from candle_builder import CandleBuilder
from config import (
    STANDBY_ATR_THRESHOLD,
    STANDBY_CONFIRMATION_COUNT,
    STANDBY_RECOVERY_CONFIRMATION_COUNT,
    STANDBY_RECOVERY_THRESHOLD,
)
from feed_integrity import FeedHealthMonitor

logger = logging.getLogger(__name__)


class SymbolExecutionState(str, Enum):
    SELECTED = "SELECTED"
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass
class SymbolState:
    symbol: str
    token: str
    trading_symbol: str
    exchange: str
    exchange_type: int
    builder: CandleBuilder
    feed_monitor: FeedHealthMonitor
    atr_firewall: ATRFirewall
    execution_state: SymbolExecutionState = SymbolExecutionState.SELECTED
    rank: int = 1
    last_signal: Optional[Dict[str, Any]] = None
    last_spread_pct: Optional[float] = None
    last_depth_available: bool = True
    current_candle_df: Optional[pd.DataFrame] = None
    last_tick_price: float = 0.0
    last_tick_volume: int = 0
    last_tick_time: Optional[datetime] = None
    standby_low_count: int = 0
    standby_recovery_count: int = 0
    error_message: Optional[str] = None
    instrument: Any = None
    quote: Any = None
    opportunity_score: float = 0.0
    volume_profiles: list = field(default_factory=list)
    cumulative_volume: float = 0.0
    data_status: str = "BOOTSTRAPPING"
    volatility_status: str = "UNKNOWN"
    history_validation: dict = field(default_factory=dict)
    watchlist_role: str = "PRIMARY"
    promotion_confirmations: int = 0
    last_promotion_time: Optional[datetime] = None
    last_volatility_candle: Any = None

    def refresh_maturity(self):
        count = 0 if self.current_candle_df is None else len(self.current_candle_df)
        if self.builder.recovery_required:
            self.data_status = "BOOTSTRAPPING"
        elif count < config.MIN_CANDLES_BEFORE_TRADE:
            self.data_status = "WARMING_UP"
        else:
            self.data_status = "READY"
        return self.data_status

    def record_periodic_atr(self, atr: float, ltp: float, timestamp: datetime,
                            completed_count: Optional[int] = None) -> None:
        """
        Records ATR in the symbol's isolated ATRFirewall and manages dynamic STANDBY
        transitions with hysteresis confirmation counts.
        """
        # Standalone callers may supply mature ATR telemetry; the runtime always
        # supplies its actual completed count and session-recovery status.
        if completed_count is not None and (completed_count < config.MIN_CANDLES_BEFORE_TRADE
                                            or self.builder.recovery_required):
            self.refresh_maturity()
            self.volatility_status = "UNKNOWN"
            self.standby_low_count = self.standby_recovery_count = 0
            return
        if not math.isfinite(atr) or not math.isfinite(ltp) or atr < 0 or ltp <= 0:
            self.volatility_status = "UNKNOWN"
            return
        if completed_count is not None and timestamp == self.last_volatility_candle:
            return  # polling/reconciliation is not a second independent ATR confirmation
        self.last_volatility_candle = timestamp
        self.atr_firewall.record_periodic_atr(atr=atr, ltp=ltp, timestamp=timestamp)

        atr_pct = atr / ltp

        if self.execution_state == SymbolExecutionState.ACTIVE:
            if atr_pct < STANDBY_ATR_THRESHOLD:
                self.standby_low_count += 1
                self.standby_recovery_count = 0
                logger.debug(
                    f"[STANDBY CHECK] {self.symbol} low ATR reading {self.standby_low_count}/"
                    f"{STANDBY_CONFIRMATION_COUNT} (ATR%: {atr_pct*100:.3f}% < {STANDBY_ATR_THRESHOLD*100:.3f}%)"
                )
                if self.standby_low_count >= STANDBY_CONFIRMATION_COUNT:
                    self.execution_state = SymbolExecutionState.STANDBY
                    logger.warning(
                        f"⚠️ [STATE TRANSITION] {self.symbol} ACTIVE -> STANDBY "
                        f"(ATR%: {atr_pct*100:.3f}% below threshold {STANDBY_ATR_THRESHOLD*100:.3f}% "
                        f"for {self.standby_low_count} consecutive readings)"
                    )
            else:
                self.standby_low_count = 0

        elif self.execution_state == SymbolExecutionState.STANDBY:
            if atr_pct >= STANDBY_RECOVERY_THRESHOLD:
                self.standby_recovery_count += 1
                self.standby_low_count = 0
                logger.debug(
                    f"[STANDBY RECOVERY CHECK] {self.symbol} healthy ATR reading {self.standby_recovery_count}/"
                    f"{STANDBY_RECOVERY_CONFIRMATION_COUNT} (ATR%: {atr_pct*100:.3f}% >= {STANDBY_RECOVERY_THRESHOLD*100:.3f}%)"
                )
                if self.standby_recovery_count >= STANDBY_RECOVERY_CONFIRMATION_COUNT:
                    self.execution_state = SymbolExecutionState.ACTIVE
                    logger.info(
                        f"✅ [STATE TRANSITION] {self.symbol} STANDBY -> ACTIVE "
                        f"(ATR%: {atr_pct*100:.3f}% recovered above {STANDBY_RECOVERY_THRESHOLD*100:.3f}% "
                        f"for {self.standby_recovery_count} consecutive readings)"
                    )
            else:
                self.standby_recovery_count = 0
        self.volatility_status = ("STANDBY" if self.execution_state == SymbolExecutionState.STANDBY
                                  or self.atr_firewall.status.value == "STANDBY" else "ACTIVE")

    def mark_error(self, message: str) -> None:
        """Transitions symbol to ERROR state with error message."""
        self.execution_state = SymbolExecutionState.ERROR
        self.error_message = message
        logger.error(f"❌ [SYMBOL ERROR] {self.symbol} (Token: {self.token}) marked ERROR: {message}")


def create_isolated_symbol_state(
    symbol: str,
    token: str,
    trading_symbol: str,
    exchange: str = "NSE",
    exchange_type: int = 1,
    rank: int = 1,
    candle_close_callback: Optional[Callable[[str, str, pd.DataFrame], None]] = None,
    candle_interval_seconds: int = 60,
    strict_session: bool = False,
) -> SymbolState:
    """
    Factory function instantiating a completely isolated SymbolState with its own
    CandleBuilder, FeedHealthMonitor, and ATRFirewall.
    """
    sym = symbol.upper()
    tok = str(token)

    feed_monitor = FeedHealthMonitor(symbol=sym, token=tok)
    atr_firewall = ATRFirewall()

    # Create symbol-bound candle close wrapper if a callback was provided
    def _bound_candle_close(df: pd.DataFrame) -> None:
        if candle_close_callback is not None:
            candle_close_callback(sym, tok, df)

    builder = CandleBuilder(
        interval_seconds=candle_interval_seconds,
        on_candle_close=_bound_candle_close,
        strict_session=strict_session,
    )

    state = SymbolState(
        symbol=sym,
        token=tok,
        trading_symbol=trading_symbol,
        exchange=exchange,
        exchange_type=exchange_type,
        builder=builder,
        feed_monitor=feed_monitor,
        atr_firewall=atr_firewall,
        execution_state=SymbolExecutionState.SELECTED,
        rank=rank,
    )
    return state
