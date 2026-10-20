"""
test_feed_integrity.py — Unit Tests for Feed Integrity, Health States & Queue
=============================================================================
Validates:
1. Lifecycle transitions: DISCONNECTED -> RECOVERING -> HEALTHY.
2. Warmup ticks requirement on reconnect.
3. Stale tick heartbeat watchdog.
4. Frozen / duplicate tick detection.
5. ThreadSafeTickIngestionQueue order and same-millisecond collision protection.
"""

from datetime import datetime, timezone
import time
import pytest

from feed_integrity import FeedHealthMonitor, FeedHealthState, RawTick, ThreadSafeTickIngestionQueue


def test_feed_lifecycle_reconnect_and_warmup():
    """Verify that socket connection enters RECOVERING and requires warmup ticks before HEALTHY."""
    monitor = FeedHealthMonitor(symbol="TEST", token="100", stale_timeout_seconds=5.0, warmup_ticks_required=3)
    assert monitor.state == FeedHealthState.DISCONNECTED

    # On socket connect -> RECOVERING
    monitor.on_connect()
    assert monitor.state == FeedHealthState.RECOVERING

    ts = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
    
    # Tick 1 -> still RECOVERING
    t1 = RawTick(sequence_id=1, symbol="TEST", token="100", exchange_type=1, price=100.0, volume=10, timestamp=ts, receipt_time=time.monotonic())
    is_gen, state, _ = monitor.evaluate_tick(t1)
    assert is_gen is True
    assert state == FeedHealthState.RECOVERING

    # Tick 2 -> still RECOVERING
    t2 = RawTick(sequence_id=2, symbol="TEST", token="100", exchange_type=1, price=100.1, volume=15, timestamp=ts, receipt_time=time.monotonic())
    is_gen, state, _ = monitor.evaluate_tick(t2)
    assert is_gen is True
    assert state == FeedHealthState.RECOVERING

    # Tick 3 -> reaches warmup threshold (3) -> HEALTHY
    t3 = RawTick(sequence_id=3, symbol="TEST", token="100", exchange_type=1, price=100.2, volume=20, timestamp=ts, receipt_time=time.monotonic())
    is_gen, state, _ = monitor.evaluate_tick(t3)
    assert is_gen is True
    assert state == FeedHealthState.HEALTHY


def test_stale_tick_watchdog():
    """Verify that heartbeat watchdog detects stale feed after timeout."""
    monitor = FeedHealthMonitor(symbol="TEST", token="100", stale_timeout_seconds=0.1, warmup_ticks_required=1)
    monitor.on_connect()

    ts = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
    t1 = RawTick(sequence_id=1, symbol="TEST", token="100", exchange_type=1, price=100.0, volume=10, timestamp=ts, receipt_time=time.monotonic())
    monitor.evaluate_tick(t1)
    assert monitor.state == FeedHealthState.HEALTHY

    # Sleep past stale timeout
    time.sleep(0.15)
    state = monitor.check_heartbeat()
    assert state == FeedHealthState.STALE

    # When fresh tick arrives, state immediately recovers to HEALTHY
    t2 = RawTick(sequence_id=2, symbol="TEST", token="100", exchange_type=1, price=100.5, volume=25, timestamp=ts, receipt_time=time.monotonic())
    is_gen, state, _ = monitor.evaluate_tick(t2)
    assert is_gen is True
    assert state == FeedHealthState.HEALTHY


def test_duplicate_frozen_tick_filtering():
    """Verify that repeated broadcast ticks with identical price, volume, and timestamp are rejected as duplicates."""
    monitor = FeedHealthMonitor(symbol="TEST", token="100", warmup_ticks_required=1)
    monitor.on_connect()

    ts = datetime(2026, 9, 23, 15, 18, 0, tzinfo=timezone.utc)
    t1 = RawTick(sequence_id=1, symbol="TEST", token="100", exchange_type=1, price=179.45, volume=3000, timestamp=ts, receipt_time=time.monotonic())
    is_gen1, state1, reason1 = monitor.evaluate_tick(t1)
    assert is_gen1 is True
    assert state1 == FeedHealthState.HEALTHY

    # Duplicate tick (same price 179.45, same volume 3000, same timestamp)
    t2 = RawTick(sequence_id=2, symbol="TEST", token="100", exchange_type=1, price=179.45, volume=3000, timestamp=ts, receipt_time=time.monotonic())
    is_gen2, state2, reason2 = monitor.evaluate_tick(t2)
    assert is_gen2 is False
    assert reason2 == "DUPLICATE_TICK_DETECTED"
    assert monitor.duplicate_tick_count == 1


def test_thread_safe_queue_same_millisecond_ordering():
    """Verify that ticks arriving at the exact same millisecond preserve order and sequence IDs."""
    q = ThreadSafeTickIngestionQueue(maxsize=100)
    same_time = datetime(2026, 9, 23, 10, 0, 0, 123456, tzinfo=timezone.utc)

    # Enqueue multiple symbols at identical millisecond
    ok1 = q.enqueue(symbol="A", token="1", exchange_type=1, price=100.0, volume=10, timestamp=same_time)
    ok2 = q.enqueue(symbol="B", token="2", exchange_type=1, price=200.0, volume=20, timestamp=same_time)
    ok3 = q.enqueue(symbol="C", token="3", exchange_type=1, price=300.0, volume=30, timestamp=same_time)

    assert ok1 and ok2 and ok3
    assert q.qsize() == 3

    t1 = q.get(timeout=0.1)
    t2 = q.get(timeout=0.1)
    t3 = q.get(timeout=0.1)

    assert t1.symbol == "A" and t1.sequence_id == 1
    assert t2.symbol == "B" and t2.sequence_id == 2
    assert t3.symbol == "C" and t3.sequence_id == 3
    assert q.empty()

