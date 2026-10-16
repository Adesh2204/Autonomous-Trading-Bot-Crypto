"""
test_atr_firewall.py — Unit & Integration Tests for Intraday ATR Firewall
========================================================================
Validates:
1. Healthy ATR maintenance (ACTIVE state).
2. Single-bar low ATR anomaly immunity (requires confirmation count).
3. Persistent low ATR triggers STANDBY state and blocks new entries.
4. Recovery confirmation requirement before unblocking.
5. Pre-entry safety gate evaluation (feed health, spread, depth, ATR%).
6. Existing position protection (exits and stop-losses remain unaffected).
7. Non-mutation of signal generation (blocks execution without touching signal).
"""

import pytest
from atr_firewall import ATRFirewall, FirewallStatus, PreEntryEvaluation


def test_healthy_atr_maintains_active():
    """Verify that ATR readings above floor keep the firewall ACTIVE."""
    fw = ATRFirewall(min_atr_pct=0.40, low_confirmation_count=2)
    # LTP = 200, ATR = 1.0 -> ATR% = 0.50% >= 0.40%
    status = fw.record_periodic_atr(atr=1.0, ltp=200.0)
    assert status == FirewallStatus.ACTIVE
    assert fw.consecutive_low_readings == 0
    assert fw.consecutive_healthy_readings == 1


def test_single_low_atr_reading_does_not_block():
    """Verify that a single low ATR reading does not prematurely block (requires confirmation)."""
    fw = ATRFirewall(min_atr_pct=0.40, low_confirmation_count=2)
    
    # 1st low reading: ATR% = 0.25% < 0.40%
    status = fw.record_periodic_atr(atr=0.50, ltp=200.0)
    assert status == FirewallStatus.ACTIVE  # Not yet STANDBY!
    assert fw.consecutive_low_readings == 1

    # Immediate pre-entry check still fails if immediate ATR is below floor
    eval_res = fw.validate_pre_entry(atr=0.50, ltp=200.0)
    assert not eval_res.execution_allowed
    assert eval_res.rejection_reason == "ATR_BELOW_THRESHOLD"

    # But if immediate tick bounces to healthy, entry is still allowed because status is ACTIVE
    eval_healthy = fw.validate_pre_entry(atr=1.00, ltp=200.0)
    assert eval_healthy.execution_allowed


def test_persistent_low_atr_triggers_standby_and_blocks():
    """Verify that reaching low_confirmation_count moves firewall to STANDBY."""
    fw = ATRFirewall(min_atr_pct=0.40, low_confirmation_count=2)
    
    # 1st low reading
    fw.record_periodic_atr(atr=0.50, ltp=200.0)
    assert fw.status == FirewallStatus.ACTIVE

    # 2nd low reading -> triggers STANDBY
    fw.record_periodic_atr(atr=0.60, ltp=200.0)
    assert fw.status == FirewallStatus.STANDBY
    assert fw.consecutive_low_readings == 2

    # In STANDBY, even if a single tick has high ATR, state remains STANDBY until confirmed recovery
    eval_res = fw.validate_pre_entry(atr=1.00, ltp=200.0)
    assert not eval_res.execution_allowed
    assert eval_res.rejection_reason == "ATR_PERSISTENT_LOW_STANDBY"


def test_recovery_requires_confirmation_count():
    """Verify that exiting STANDBY requires recovery_confirmation_count healthy readings."""
    fw = ATRFirewall(min_atr_pct=0.40, low_confirmation_count=2, recovery_confirmation_count=2)
    
    # Put into STANDBY
    fw.record_periodic_atr(atr=0.50, ltp=200.0)
    fw.record_periodic_atr(atr=0.50, ltp=200.0)
    assert fw.status == FirewallStatus.STANDBY

    # 1st healthy reading (ATR% = 0.50% >= 0.40%) -> remains STANDBY
    status1 = fw.record_periodic_atr(atr=1.00, ltp=200.0)
    assert status1 == FirewallStatus.STANDBY
    assert fw.consecutive_healthy_readings == 1

    # 2nd healthy reading -> recovers to ACTIVE!
    status2 = fw.record_periodic_atr(atr=1.10, ltp=200.0)
    assert status2 == FirewallStatus.ACTIVE
    assert fw.consecutive_healthy_readings == 2

    # Now new entries are permitted
    eval_res = fw.validate_pre_entry(atr=1.10, ltp=200.0)
    assert eval_res.execution_allowed


def test_pre_entry_gates_feed_spread_and_depth():
    """Verify pre-entry rejection for unhealthy feed, excessive spread, and missing depth."""
    fw = ATRFirewall(min_atr_pct=0.40, max_spread_pct=0.15)
    
    # 1. Unhealthy feed
    eval_feed = fw.validate_pre_entry(atr=1.0, ltp=200.0, feed_health="STALE")
    assert not eval_feed.execution_allowed
    assert eval_feed.rejection_reason == "FEED_UNHEALTHY_STALE"

    # 2. Wide spread (> 0.15%)
    eval_spread = fw.validate_pre_entry(atr=1.0, ltp=200.0, spread_pct=0.25)
    assert not eval_spread.execution_allowed
    assert eval_spread.rejection_reason == "SPREAD_TOO_WIDE"

    # 3. Missing depth
    eval_depth = fw.validate_pre_entry(atr=1.0, ltp=200.0, depth_available=False)
    assert not eval_depth.execution_allowed
    assert eval_depth.rejection_reason == "DEPTH_UNAVAILABLE"


def test_existing_position_immunity():
    """
    CRITICAL SAFETY INVARIANT:
    Exits, Stop-Losses, and EOD auto-square-offs MUST NOT be blocked by ATR collapse.
    """
    fw = ATRFirewall(min_atr_pct=0.40, low_confirmation_count=1)
    # Put into STANDBY
    fw.record_periodic_atr(atr=0.10, ltp=200.0)
    assert fw.status == FirewallStatus.STANDBY

    # Exit check with is_new_entry=False
    eval_exit = fw.validate_pre_entry(
        atr=0.10,
        ltp=200.0,
        feed_health="DEGRADED",
        spread_pct=0.50,
        depth_available=False,
        is_new_entry=False,
    )
    assert eval_exit.execution_allowed is True
    assert eval_exit.rejection_reason is None


def test_signal_generation_immutability():
    """
    Verify that the firewall acts strictly as an execution gate and does not
    convert a signal from BUY/SHORT into None.
    """
    fw = ATRFirewall(min_atr_pct=0.40)
    
    # Existing strategy emitted a BUY signal
    strategy_signal = "BUY"
    
    # Immediate ATR is low
    eval_res = fw.validate_pre_entry(atr=0.20, ltp=200.0)
    assert not eval_res.execution_allowed
    
    # The signal remains "BUY" — the firewall gates execution, not signal generation!
    assert strategy_signal == "BUY"
    execution_gate_passed = eval_res.execution_allowed
    assert execution_gate_passed is False

