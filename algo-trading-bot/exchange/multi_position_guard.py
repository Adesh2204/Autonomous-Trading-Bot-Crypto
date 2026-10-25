"""Account-wide barrier for up to `max_positions` concurrent positions, one per market.

User directive 2026-10-25 (continuous scalper): up to 3 concurrent positions.
The durable lock stays the single account-wide control record of
SinglePositionGuard and keeps every one of its properties: startup is UNKNOWN,
only fresh reconciled exchange truth opens it, a reservation is made inside the
transaction that persists the intent, and going flat still needs actual-fill
evidence. The only difference: while 1..max-1 positions are held, a new entry
slot is open for a market that is not held, provided no other entry is
unresolved and every resting order belongs to a held market.
"""
import json

from .base_exchange import ExchangeError, decimal
from .carry_runtime import BasketPositionGuard
from .single_position_guard import PortfolioState, PositionDecision, unresolved

MAX_CONCURRENT_POSITIONS = 3
HELD = {PortfolioState.LONG, PortfolioState.SHORT}


class MultiPositionGuard(BasketPositionGuard):
    def __init__(self, journal, *, clock_ms, max_positions):
        if type(max_positions) is not int or not 1 <= max_positions <= MAX_CONCURRENT_POSITIONS:
            raise ExchangeError('INVALID_MAX_CONCURRENT_POSITIONS')
        self.max_positions = max_positions
        self.held = frozenset()
        self.slot_open = False
        super().__init__(journal, clock_ms=clock_ms)

    def _store(self, state, reason, *, entry_key=None, observed_ms=None, in_transaction=False):
        prior = self.journal.control(self.CONTROL) or {}
        value = dict(state=PortfolioState(state).value, reason=reason, entry_key=entry_key, observed_ms=observed_ms,
                     generation=prior.get('generation', 0) + 1, max_global_positions=self.max_positions,
                     held=sorted(self.held), entry_slot_open=self.slot_open,
                     team_address=self.journal.team_address)
        if in_transaction:
            from .execution_journal import canonical
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)', (self.CONTROL, canonical(value)))
        else:
            self.journal.control(self.CONTROL, value)
        self.state = PortfolioState(state)
        self.reason = reason
        return value

    def revoke(self, reason):
        self.held, self.slot_open = frozenset(), False
        super().revoke(reason)

    def _reconcile(self, context, now_ms):
        positions = {s: p for s, p in context.positions.items() if decimal(p.quantity)}
        fresh = (context.readiness.account_ready and context.reconciled and
                 0 <= now_ms - context.account_ms <= 5000)
        if not fresh or not positions or len(positions) > self.max_positions or any(
                r['state'] == 'UNKNOWN' for r in self.journal.management_actions()):
            # Flat, stale, over the limit or an unknown management action: the
            # single-position rules decide (UNKNOWN / RECOVERING / FLAT evidence).
            self.held, self.slot_open = frozenset(positions) if fresh else frozenset(), False
            if fresh and len(positions) > self.max_positions:
                return self._held_state(context, now_ms, positions, PortfolioState.RECOVERING,
                                        'UNEXPECTED_CONCURRENT_EXPOSURE')
            if fresh and positions:
                return self._held_state(context, now_ms, positions, PortfolioState.RECOVERING,
                                        'UNKNOWN_MANAGEMENT_ACTION')
            return super()._reconcile(context, now_ms)
        pending = [r for r in self.intent_rows() if unresolved(r)]
        entry_pending = any(not json.loads(r['request'])['reduce_only'] for r in pending)
        self.held = frozenset(positions)
        self.slot_open = (len(positions) < self.max_positions and not entry_pending
                          and all(o.get('coin') in positions and o.get('reduceOnly') is True
                                  for o in context.open_orders))
        first = next(iter(positions.values()))
        state = (PortfolioState.ENTRY_PENDING if entry_pending else
                 PortfolioState.LONG if first.quantity > 0 else PortfolioState.SHORT)
        return self._held_state(context, now_ms, positions, state, 'ACTUAL_EXCHANGE_EXPOSURE')

    def _held_state(self, context, now_ms, positions, state, reason):
        prior = self.journal.control(self.CONTROL) or {}
        self._store(state, reason, entry_key=prior.get('entry_key'), observed_ms=context.account_ms,
                    in_transaction=True)
        from .execution_journal import canonical, safe_data
        from .event_timing import timing
        self.journal.db.execute('INSERT INTO events(timestamp_ms,kind,data) VALUES (?,?,?)',
            (now_ms, 'GLOBAL_POSITION_RECONCILED', canonical(safe_data(dict(**timing(now_ms), state=state.value,
             session_id=self.journal.session_id, event_type='GLOBAL_POSITION_RECONCILED', candidate_id=None,
             symbol=None, reason=reason, actual_position_count=len(positions),
             open_order_count=len(context.open_orders), max_global_positions=self.max_positions,
             entry_slot_open=self.slot_open)))))
        return self.report()

    def evaluate(self, request, context, now_ms, *, expected_generation=None):
        decision = super().evaluate(request, context, now_ms, expected_generation=expected_generation)
        if request.reduce_only or decision.allowed:
            return decision
        allowed = self.state in HELD and self.slot_open and request.symbol not in self.held
        if not allowed:
            return decision
        return PositionDecision(True, 'MULTI_POSITION_SLOT_PASS', self.state.value, self.reason, now_ms)

    def reserve_in_transaction(self, key, request, now_ms, *, expected_generation=None):
        prior = self.journal.control(self.CONTROL) or {}
        if prior.get('state') == 'FLAT':
            return super().reserve_in_transaction(key, request, now_ms, expected_generation=expected_generation)
        if expected_generation is not None and prior.get('generation') != expected_generation:
            raise ExchangeError('ACCOUNT_PREFLIGHT_INVALIDATED')
        if (prior.get('state') not in {'LONG', 'SHORT'} or not prior.get('entry_slot_open')
                or request['symbol'] in prior.get('held', []) or len(prior.get('held', [])) >= self.max_positions
                or prior.get('observed_ms') is None or not 0 <= now_ms - prior['observed_ms'] <= 5000
                or any(unresolved(r) and not json.loads(r['request'])['reduce_only'] for r in self.intent_rows())):
            raise ExchangeError('POSITION_LIMIT')
        self.slot_open = False
        self.held = frozenset(prior.get('held', []))
        self._store(PortfolioState.ENTRY_PENDING, 'DURABLE_ENTRY_RESERVED', entry_key=key,
                    observed_ms=prior['observed_ms'], in_transaction=True)

    def report(self):
        value = self.journal.control(self.CONTROL) or {}
        return dict(value, runtime_state=self.state.value, runtime_reason=self.reason,
                    entry_permission=self.state == PortfolioState.FLAT or (self.state in HELD and self.slot_open))
