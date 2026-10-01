"""
atr_firewall.py — Intraday ATR Volatility Firewall & Safety Gating
===================================================================
Continuously monitors intraday ATR% to prevent entering new trades when market
volatility collapses post-market-open.

Key Architectural Invariants:
1. Signal Immutability: Gating never converts BUY/SHORT into None inside the strategy.
   The signal is preserved in logs, while execution is marked blocked (EXECUTION_ALLOWED = False).
2. Existing Position Protection: Only gates NEW entries. Existing open positions continue
   to be actively managed by stop-loss, targets, trailing stops, and EOD auto-square-off.
3. Multi-Check Persistence: Gating requires configurable consecutive failure counts before
   transitioning to STANDBY, preventing whipsaws on single anomalous bars.
4. Recovery Confirmation: Reactivation requires consecutive healthy readings before restoring ACTIVE.
5. Pre-Entry Gatekeeper: Immediately evaluates latest ATR, feed health, spread, and depth
   prior to every new order placement.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from config import (
    ATR_LOW_CONFIRMATION_COUNT,
    ATR_RECHECK_INTERVAL_SECONDS,
    ATR_RECOVERY_CONFIRMATION_COUNT,
    INTRADAY_ATR_MIN_PCT,
    SCREEN_MAX_SPREAD_PCT,
)

logger = logging.getLogger(__name__)


class FirewallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"


@dataclass
class PreEntryEvaluation:
    execution_allowed: bool
    rejection_reason: Optional[str] = None
    atr: float = 0.0
    atr_pct: float = 0.0
    feed_health: str = "HEALTHY"
    spread_pct: float = 0.0
    status: FirewallStatus = FirewallStatus.ACTIVE


class ATRFirewall:
    """
    Intraday ATR volatility monitoring firewall and pre-entry execution eligibility gate.
    """

    def __init__(
        self,
        min_atr_pct: float = INTRADAY_ATR_MIN_PCT,
        recheck_interval_seconds: float = ATR_RECHECK_INTERVAL_SECONDS,
        low_confirmation_count: int = ATR_LOW_CONFIRMATION_COUNT,
        recovery_confirmation_count: int = ATR_RECOVERY_CONFIRMATION_COUNT,
        max_spread_pct: float = SCREEN_MAX_SPREAD_PCT,
    ) -> None:
        self.min_atr_pct = min_atr_pct * 100.0 if min_atr_pct < 0.1 else min_atr_pct
        self.recheck_interval_seconds = recheck_interval_seconds
        self.low_confirmation_count = low_confirmation_count
        self.recovery_confirmation_count = recovery_confirmation_count
        self.max_spread_pct = max_spread_pct * 100.0 if max_spread_pct < 0.1 else max_spread_pct

        self.status: FirewallStatus = FirewallStatus.ACTIVE
        self.consecutive_low_readings: int = 0
        self.consecutive_healthy_readings: int = 0
        self.last_recheck_time: Optional[datetime] = None
        self.latest_atr: float = 0.0
        self.latest_atr_pct: float = 0.0

    def record_periodic_atr(
        self,
        atr: float,
        ltp: float,
        timestamp: Optional[datetime] = None,
    ) -> FirewallStatus:
        """
        Records a periodic or candle-close ATR reading and updates firewall state.
        """
        if atr is None or not math.isfinite(atr) or not math.isfinite(ltp) or atr < 0 or ltp <= 0:
            return self.status
        self.latest_atr = float(atr)
        self.latest_atr_pct = (self.latest_atr / ltp) * 100.0 if ltp and ltp > 0 else 0.0
        self.last_recheck_time = timestamp or datetime.now()

        if self.latest_atr_pct < self.min_atr_pct:
            self.consecutive_low_readings += 1
            self.consecutive_healthy_readings = 0

            logger.debug(
                f"[ATR FIREWALL EVAL] Reading: {self.latest_atr_pct:.3f}% < {self.min_atr_pct:.3f}% "
                f"| Low Count: {self.consecutive_low_readings}/{self.low_confirmation_count} "
                f"| Current State: {self.status.value}"
            )

            if (
                self.status == FirewallStatus.ACTIVE
                and self.consecutive_low_readings >= self.low_confirmation_count
            ):
                self.status = FirewallStatus.STANDBY
                logger.warning(
                    f"⚠️ [ATR FIREWALL BLOCK] Volatility collapsed ({self.latest_atr_pct:.3f}% < {self.min_atr_pct:.3f}%). "
                    f"Confirmed {self.consecutive_low_readings} times. State -> STANDBY. New entries BLOCKED."
                )
        else:
            self.consecutive_healthy_readings += 1
            self.consecutive_low_readings = 0

            if (
                self.status == FirewallStatus.STANDBY
                and self.consecutive_healthy_readings >= self.recovery_confirmation_count
            ):
                self.status = FirewallStatus.ACTIVE
                logger.info(
                    f"✅ [ATR FIREWALL CLEAR] Volatility recovered ({self.latest_atr_pct:.3f}% >= {self.min_atr_pct:.3f}%). "
                    f"Confirmed {self.consecutive_healthy_readings} times. State -> ACTIVE. New entries RESTORED."
                )

        return self.status

    def validate_pre_entry(
        self,
        atr: float,
        ltp: float,
        feed_health: str = "HEALTHY",
        spread_pct: Optional[float] = None,
        depth_available: bool = True,
        is_new_entry: bool = True,
    ) -> PreEntryEvaluation:
        """
        Validates all safety conditions immediately prior to placing a NEW order.
        If is_new_entry is False (i.e. closing an existing position or stop loss),
        execution is always allowed.
        """
        calc_atr = float(atr) if atr is not None else self.latest_atr
        calc_atr_pct = (calc_atr / ltp) * 100.0 if ltp and ltp > 0 else self.latest_atr_pct
        actual_spread = spread_pct if spread_pct is not None else 0.05

        # Invariant 2: Existing positions remain protected — never block an exit!
        if not is_new_entry:
            return PreEntryEvaluation(
                execution_allowed=True,
                rejection_reason=None,
                atr=calc_atr,
                atr_pct=calc_atr_pct,
                feed_health=feed_health,
                spread_pct=actual_spread,
                status=self.status,
            )

        if not math.isfinite(calc_atr) or not math.isfinite(ltp) or ltp <= 0 or calc_atr < 0:
            return PreEntryEvaluation(False, "INVALID_ATR_DATA", status=self.status)

        # Gate 1: Feed Health must be HEALTHY
        if feed_health != "HEALTHY":
            logger.warning(
                f"[FIREWALL GATE BLOCKED] Unhealthy market data feed: {feed_health}. Entry rejected."
            )
            return PreEntryEvaluation(
                execution_allowed=False,
                rejection_reason=f"FEED_UNHEALTHY_{feed_health}",
                atr=calc_atr,
                atr_pct=calc_atr_pct,
                feed_health=feed_health,
                spread_pct=actual_spread,
                status=self.status,
            )

        # Gate 2: Depth must be available
        if not depth_available:
            logger.warning("[FIREWALL GATE BLOCKED] Market depth unavailable. Entry rejected.")
            return PreEntryEvaluation(
                execution_allowed=False,
                rejection_reason="DEPTH_UNAVAILABLE",
                atr=calc_atr,
                atr_pct=calc_atr_pct,
                feed_health=feed_health,
                spread_pct=actual_spread,
                status=self.status,
            )

        # Gate 3: Spread must be within limit
        if actual_spread > self.max_spread_pct:
            logger.warning(
                f"[FIREWALL GATE BLOCKED] Spread too wide ({actual_spread:.3f}% > {self.max_spread_pct:.3f}%). Entry rejected."
            )
            return PreEntryEvaluation(
                execution_allowed=False,
                rejection_reason="SPREAD_TOO_WIDE",
                atr=calc_atr,
                atr_pct=calc_atr_pct,
                feed_health=feed_health,
                spread_pct=actual_spread,
                status=self.status,
            )

        # Gate 4: Persistent STANDBY status blocks new entries
        if self.status == FirewallStatus.STANDBY:
            logger.warning(
                f"[FIREWALL GATE BLOCKED] Symbol is in STANDBY state due to persistent low ATR ({calc_atr_pct:.3f}%). Entry rejected."
            )
            return PreEntryEvaluation(
                execution_allowed=False,
                rejection_reason="ATR_PERSISTENT_LOW_STANDBY",
                atr=calc_atr,
                atr_pct=calc_atr_pct,
                feed_health=feed_health,
                spread_pct=actual_spread,
                status=self.status,
            )

        # Gate 5: Immediate ATR% floor check
        if calc_atr_pct < self.min_atr_pct:
            logger.warning(
                f"[FIREWALL GATE BLOCKED] Immediate ATR% ({calc_atr_pct:.3f}%) below floor ({self.min_atr_pct:.3f}%). Entry rejected."
            )
            return PreEntryEvaluation(
                execution_allowed=False,
                rejection_reason="ATR_BELOW_THRESHOLD",
                atr=calc_atr,
                atr_pct=calc_atr_pct,
                feed_health=feed_health,
                spread_pct=actual_spread,
                status=self.status,
            )

        return PreEntryEvaluation(
            execution_allowed=True,
            rejection_reason=None,
            atr=calc_atr,
            atr_pct=calc_atr_pct,
            feed_health=feed_health,
            spread_pct=actual_spread,
            status=self.status,
        )
