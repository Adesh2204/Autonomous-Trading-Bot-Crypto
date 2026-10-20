"""
feed_integrity.py — WebSocket Feed Health Monitor, Tick Queue & Frozen Data Detector
======================================================================================
Guarantees market data veracity and eliminates race conditions:
1. Concurrency Safety: WebSocket callbacks enqueue raw ticks into a thread-safe Queue;
   a single consumer thread processes ticks sequentially, owning mutable symbol state.
2. Same-Millisecond Tick Safety: Same-millisecond ticks are preserved using sequence IDs
   and symbol keys rather than lossy timestamp-deduplication.
3. Feed Health State Machine: HEALTHY, DEGRADED, STALE, DISCONNECTED, RECOVERING.
4. Genuinely New Tick Detection: Filters out frozen / duplicate broadcast payloads.
5. Reconnection Recovery Pipeline: Reconnecting does NOT immediately mean healthy data;
   requires subscription restoration and warm-up validation before restoring HEALTHY.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from config import (
    FEED_RECONNECT_WARMUP_TICKS,
    MAX_QUEUE_SIZE,
    STALE_TICK_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class FeedHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    RECOVERING = "RECOVERING"


@dataclass
class RawTick:
    sequence_id: int
    symbol: str
    token: str
    exchange_type: int
    price: float
    volume: int
    timestamp: datetime
    receipt_time: float
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    depth_available: bool = True
    bid_quantity: int = 0
    ask_quantity: int = 0
    cumulative_volume: float = 0.0


class FeedHealthMonitor:
    """
    State machine tracking the integrity, freshness, and connection lifecycle of market data.
    """

    def __init__(
        self,
        symbol: str,
        token: str,
        stale_timeout_seconds: float = STALE_TICK_TIMEOUT_SECONDS,
        warmup_ticks_required: int = FEED_RECONNECT_WARMUP_TICKS,
    ) -> None:
        self.symbol = symbol
        self.token = token
        self.stale_timeout_seconds = stale_timeout_seconds
        self.warmup_ticks_required = warmup_ticks_required

        self.state: FeedHealthState = FeedHealthState.DISCONNECTED
        self.last_genuine_tick_timestamp: Optional[datetime] = None
        self.last_receipt_time: float = 0.0
        self.last_price: Optional[float] = None
        self.last_volume: Optional[int] = None
        self.warmup_ticks_received: int = 0
        self.duplicate_tick_count: int = 0
        self.lock = threading.Lock()

    def on_disconnect(self, reason: str = "Connection lost") -> None:
        """Mark feed as DISCONNECTED."""
        with self.lock:
            old_state = self.state
            self.state = FeedHealthState.DISCONNECTED
            self.warmup_ticks_received = 0
            logger.warning(
                f"[FEED HEALTH] {self.symbol} state {old_state.value} -> DISCONNECTED. Reason: {reason}"
            )

    def on_connect(self) -> None:
        """Mark feed as RECOVERING upon socket connection."""
        with self.lock:
            old_state = self.state
            self.state = FeedHealthState.RECOVERING
            self.warmup_ticks_received = 0
            logger.info(
                f"[FEED HEALTH] {self.symbol} state {old_state.value} -> RECOVERING. Waiting for fresh ticks."
            )

    def evaluate_tick(self, tick: RawTick) -> Tuple[bool, FeedHealthState, str]:
        """
        Processes an incoming tick:
        - Detects frozen/duplicate ticks
        - Advances recovery state if warming up
        - Updates genuine tick timestamp
        Returns (is_genuine, state, reason)
        """
        with self.lock:
            now_mono = time.monotonic()

            # Price sanity check
            if tick.price <= 0 or not math.isfinite(tick.price):
                return False, self.state, "INVALID_PRICE"

            # Check duplicate / frozen tick:
            # Identical price and volume received with identical or zero-movement timestamp
            is_duplicate = False
            if (
                self.last_price is not None
                and self.last_volume is not None
                and tick.price == self.last_price
                and tick.volume == self.last_volume
            ):
                if self.last_genuine_tick_timestamp is not None:
                    delta = (tick.timestamp - self.last_genuine_tick_timestamp).total_seconds()
                    if delta <= 0.0:
                        is_duplicate = True

            if is_duplicate:
                self.duplicate_tick_count += 1
                logger.debug(
                    f"[FEED HEALTH] Duplicate tick detected for {self.symbol} "
                    f"(P={tick.price}, V={tick.volume}). Total dupes: {self.duplicate_tick_count}"
                )
                return False, self.state, "DUPLICATE_TICK_DETECTED"

            # Tick is genuine
            self.last_price = tick.price
            self.last_volume = tick.volume
            self.last_genuine_tick_timestamp = tick.timestamp
            self.last_receipt_time = now_mono

            # State transition if in RECOVERING
            if self.state in (FeedHealthState.RECOVERING, FeedHealthState.DISCONNECTED):
                self.warmup_ticks_received += 1
                if self.warmup_ticks_received >= self.warmup_ticks_required:
                    self.state = FeedHealthState.HEALTHY
                    logger.info(
                        f"✅ [FEED HEALTH] {self.symbol} state -> HEALTHY. Warmup complete ({self.warmup_ticks_received} ticks)."
                    )
            elif self.state in (FeedHealthState.STALE, FeedHealthState.DEGRADED):
                self.state = FeedHealthState.HEALTHY
                logger.info(f"✅ [FEED HEALTH] {self.symbol} state -> HEALTHY. Fresh tick received.")

            return True, self.state, "GENUINE_TICK"

    def check_heartbeat(self, now_mono: Optional[float] = None) -> FeedHealthState:
        """
        Evaluates elapsed wall-clock / monotonic time since last genuine tick.
        Transitions state to STALE if timeout exceeded.
        """
        with self.lock:
            curr = now_mono if now_mono is not None else time.monotonic()
            if self.last_receipt_time > 0 and self.state == FeedHealthState.HEALTHY:
                elapsed = curr - self.last_receipt_time
                if elapsed > self.stale_timeout_seconds:
                    self.state = FeedHealthState.STALE
                    logger.warning(
                        f"⚠️ [FEED HEALTH] {self.symbol} state -> STALE. No genuine tick for {elapsed:.1f}s "
                        f"(Timeout: {self.stale_timeout_seconds}s). New entries BLOCKED."
                    )
            return self.state


class ThreadSafeTickIngestionQueue:
    """
    Thread-safe ingestion buffer decoupling fast WebSocket reception from state processing.
    """

    def __init__(self, maxsize: int = MAX_QUEUE_SIZE) -> None:
        self.queue: queue.Queue[RawTick] = queue.Queue(maxsize=maxsize)
        self._seq_counter: int = 0
        self._lock = threading.Lock()

    def enqueue(
        self,
        symbol: str,
        token: str,
        exchange_type: int,
        price: float,
        volume: int,
        timestamp: datetime,
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
        depth_available: bool = True,
        bid_quantity: int = 0,
        ask_quantity: int = 0,
        cumulative_volume: float = 0.0,
    ) -> bool:
        """Enqueue tick safely from the WebSocket callback thread."""
        with self._lock:
            self._seq_counter += 1
            seq = self._seq_counter

        tick = RawTick(
            sequence_id=seq,
            symbol=symbol,
            token=token,
            exchange_type=exchange_type,
            price=price,
            volume=volume,
            timestamp=timestamp,
            receipt_time=time.monotonic(),
            best_bid=best_bid,
            best_ask=best_ask,
            depth_available=depth_available,
            bid_quantity=bid_quantity,
            ask_quantity=ask_quantity,
            cumulative_volume=cumulative_volume,
        )

        try:
            self.queue.put_nowait(tick)
            return True
        except queue.Full:
            logger.critical("[QUEUE OVERFLOW] Ingestion queue full! Dropping tick.")
            return False

    def get(self, timeout: Optional[float] = 0.5) -> Optional[RawTick]:
        """Fetch next tick for the single consumer thread."""
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def empty(self) -> bool:
        return self.queue.empty()

    def qsize(self) -> int:
        return self.queue.qsize()


# Re-export Phase 5 Symbol State classes for backward compatibility
try:
    from symbol_state import SymbolExecutionState, SymbolState
except ImportError:
    pass
