"""Durable, exchange-truth-driven BTC position lifecycle state machine."""
from enum import Enum

from .base_exchange import ExchangeError


class PositionState(str, Enum):
    UNKNOWN = "UNKNOWN"
    FLAT = "FLAT"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PROTECTION_PENDING = "PROTECTION_PENDING"
    PROTECTED = "PROTECTED"
    MANAGING = "MANAGING"
    EXIT_REQUESTED = "EXIT_REQUESTED"
    EXIT_PARTIAL = "EXIT_PARTIAL"
    FLAT_RECONCILED = "FLAT_RECONCILED"


# This state machine is evidence-only: transitions never submit exchange actions.
_ALLOWED = {
    PositionState.UNKNOWN: {PositionState.FLAT, PositionState.PROTECTED, PositionState.MANAGING,
                            PositionState.PROTECTION_PENDING, PositionState.FLAT_RECONCILED},
    PositionState.FLAT: {PositionState.SIGNAL_DETECTED, PositionState.FLAT_RECONCILED},
    PositionState.FLAT_RECONCILED: {PositionState.FLAT, PositionState.SIGNAL_DETECTED,
                                     PositionState.PROTECTION_PENDING, PositionState.MANAGING},
    PositionState.SIGNAL_DETECTED: {PositionState.ORDER_SUBMITTED, PositionState.FLAT,
                                    PositionState.FLAT_RECONCILED},
    PositionState.ORDER_SUBMITTED: {PositionState.PARTIALLY_FILLED, PositionState.FILLED,
                                    PositionState.FLAT_RECONCILED, PositionState.EXIT_REQUESTED},
    PositionState.PARTIALLY_FILLED: {PositionState.PARTIALLY_FILLED, PositionState.FILLED,
                                     PositionState.PROTECTION_PENDING, PositionState.EXIT_REQUESTED,
                                     PositionState.EXIT_PARTIAL, PositionState.FLAT_RECONCILED},
    PositionState.FILLED: {PositionState.PROTECTION_PENDING, PositionState.PROTECTED,
                           PositionState.MANAGING, PositionState.EXIT_REQUESTED},
    PositionState.PROTECTION_PENDING: {PositionState.PROTECTED, PositionState.EXIT_REQUESTED,
                                        PositionState.EXIT_PARTIAL, PositionState.FLAT_RECONCILED},
    PositionState.PROTECTED: {PositionState.MANAGING, PositionState.EXIT_REQUESTED,
                              PositionState.PROTECTION_PENDING},
    PositionState.MANAGING: {PositionState.EXIT_REQUESTED, PositionState.PROTECTION_PENDING,
                             PositionState.FLAT_RECONCILED},
    PositionState.EXIT_REQUESTED: {PositionState.EXIT_PARTIAL, PositionState.FLAT_RECONCILED,
                                   PositionState.EXIT_REQUESTED, PositionState.PROTECTION_PENDING},
    PositionState.EXIT_PARTIAL: {PositionState.EXIT_PARTIAL, PositionState.EXIT_REQUESTED,
                                 PositionState.FLAT_RECONCILED, PositionState.PROTECTION_PENDING},
}


class PositionStateJournal:
    """Single-session transition log; restart begins UNKNOWN until REST reconciliation.

    Previous journal state is retained for audit, but never treated as current
    exchange truth after a restart.
    """
    PREFIX = "btc_position_state:"

    def __init__(self, journal, clock_ms, *, market):
        if not isinstance(market, str) or market.count(":") != 1 or not market.endswith(":BTC"):
            raise ExchangeError("PAS_BTC_POSITION_STATE_REQUIRED")
        self.journal = journal
        self.clock_ms = clock_ms
        self.market = market
        self.state = PositionState.UNKNOWN
        self.reason = "RESTART_AUTHORITATIVE_RECONCILIATION_REQUIRED"
        self.sequence = 0

    def _control_key(self):
        return self.PREFIX + self.market

    def transition(self, target, reason, *, evidence=None, reconciled=False):
        try:
            target = PositionState(target)
        except ValueError as exc:
            raise ExchangeError("INVALID_POSITION_STATE") from exc
        prior = self.state
        if prior == target:
            self.reason = str(reason)
            return self.report()
        if target == PositionState.UNKNOWN:
            raise ExchangeError("POSITION_STATE_CANNOT_REENTER_UNKNOWN")
        if prior == PositionState.UNKNOWN:
            if not reconciled or target not in {
                PositionState.FLAT, PositionState.PROTECTED, PositionState.MANAGING,
                PositionState.PROTECTION_PENDING, PositionState.FLAT_RECONCILED,
            }:
                raise ExchangeError("POSITION_STATE_RECONCILIATION_REQUIRED")
        elif target not in _ALLOWED.get(prior, set()):
            raise ExchangeError("INVALID_POSITION_STATE_TRANSITION:" + prior.value + "->" + target.value)
        self.sequence += 1
        now = self.clock_ms()
        record = {
            "market": self.market,
            "state": target.value,
            "previous_state": prior.value,
            "reason": str(reason),
            "observed_at_ms": now,
            "sequence": self.sequence,
            "evidence": evidence or {},
        }
        self.journal.control(self._control_key(), record)
        self.journal.event("BTC_POSITION_STATE", now, **record)
        self.state = target
        self.reason = str(reason)
        return self.report()

    def report(self):
        return {
            "market": self.market,
            "state": self.state.value,
            "reason": self.reason,
            "sequence": self.sequence,
        }
