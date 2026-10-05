"""Account-wide one-position barrier; only verified exchange truth unlocks it."""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import json
import fcntl
import os
from pathlib import Path

from .base_exchange import ExchangeError, decimal
from .execution_journal import canonical


MAX_GLOBAL_POSITIONS = 1
UNRESOLVED = {'PREPARED', 'SUBMITTED', 'UNKNOWN', 'OPEN', 'CANCEL_PENDING'}


class AccountExecutionLease:
    """One production execution owner per team account on this host/user.

    It does not coordinate another computer or manually operated wallets. The
    funded-account certification must verify the dedicated account deployment.
    """
    def __init__(self, team_address):
        from .live_readiness import valid_address
        if not valid_address(team_address):
            raise ExchangeError('TEAM_ACCOUNT_IDENTITY_REQUIRED')
        root=Path('/tmp').resolve()/('anchorium-account-leases-'+str(os.getuid()))
        root.mkdir(mode=0o700,exist_ok=True)
        self.file=open(root/(team_address.lower()+'.lease'),'a+b')
        os.chmod(self.file.name,0o600)
        self.pid=os.getpid()
        try:
            fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ExchangeError('TEAM_ACCOUNT_ALREADY_LEASED') from None

    def require(self):
        if self.file.closed or os.getpid()!=self.pid:
            raise ExchangeError('TEAM_ACCOUNT_LEASE_REQUIRED')

    def close(self):
        if not self.file.closed:
            self.file.close()


class PortfolioState(str, Enum):
    FLAT = 'FLAT'
    ENTRY_PENDING = 'ENTRY_PENDING'
    LONG = 'LONG'
    SHORT = 'SHORT'
    EXIT_PENDING = 'EXIT_PENDING'
    RECOVERING = 'RECOVERING'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class PositionDecision:
    allowed: bool
    code: str
    state: str
    reason: str
    timestamp: int


def unresolved(row):
    if row['state'] in UNRESOLVED:
        return True
    if row['state'] == 'PARTIALLY_FILLED':
        return not json.loads(row['outcome'] or '{}').get('remainder_cancelled', False)
    return False


class SinglePositionGuard:
    """Durable lock scoped to the journal's team account, never to a symbol.

    Initialization is UNKNOWN even when a previous checkpoint says FLAT.
    SQLite BEGIN IMMEDIATE serializes reservation across connections/processes
    sharing this account journal. Separate journals are not a coordination bus;
    deployment must use one journal and one owner for the entire team account.
    """
    CONTROL = 'global_position_lock'

    def __init__(self, journal, *, clock_ms, max_positions=1):
        if type(max_positions) is not int or max_positions != MAX_GLOBAL_POSITIONS:
            raise ExchangeError('ONE_GLOBAL_POSITION_REQUIRED')
        self.journal = journal
        self.clock_ms = clock_ms
        self.state = PortfolioState.UNKNOWN
        self.reason = 'STARTUP_AUTHORITATIVE_ACCOUNT_REQUIRED'
        if journal.control(self.CONTROL) is None:
            self._store(self.state, self.reason)

    def _store(self, state, reason, *, entry_key=None, observed_ms=None, in_transaction=False):
        prior = self.journal.control(self.CONTROL) or {}
        value = dict(state=PortfolioState(state).value, reason=reason,
            entry_key=entry_key, observed_ms=observed_ms,
            generation=prior.get('generation', 0) + 1, max_global_positions=1,
            team_address=self.journal.team_address)
        if in_transaction:
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                                   (self.CONTROL, canonical(value)))
        else:
            self.journal.control(self.CONTROL, value)
        self.state = PortfolioState(state)
        self.reason = reason
        return value

    def revoke(self, reason):
        previous = self.journal.control(self.CONTROL) or {}
        self._store(PortfolioState.UNKNOWN, reason, entry_key=previous.get('entry_key'))
        self.journal.event('GLOBAL_POSITION_REVOKED', self.clock_ms(), reason=reason)

    def reconcile(self, context, now_ms, *, expected_generation=None):
        with self.journal.transaction():
            current=self.journal.control(self.CONTROL) or {}
            if expected_generation is not None and current.get('generation') != expected_generation:
                raise ExchangeError('ACCOUNT_PREFLIGHT_INVALIDATED')
            return self._reconcile(context, now_ms)

    def _reconcile(self, context, now_ms):
        prior = self.journal.control(self.CONTROL) or {}
        key = prior.get('entry_key')
        positions = {s: p for s, p in context.positions.items() if decimal(p.quantity)}
        orders = context.open_orders
        rows = self.journal.intents()
        pending = [r for r in rows if unresolved(r)]
        state, reason = PortfolioState.UNKNOWN, 'UNKNOWN_ACCOUNT_STATE'
        if (context.readiness.account_ready and context.reconciled and
                0 <= now_ms-context.account_ms <= 5000):
            if len(positions) > 1:
                state, reason = PortfolioState.RECOVERING, 'UNEXPECTED_CONCURRENT_EXPOSURE'
            elif any(r['state'] == 'UNKNOWN' for r in self.journal.management_actions()):
                state, reason = PortfolioState.RECOVERING, 'UNKNOWN_MANAGEMENT_ACTION'
            elif positions:
                p = next(iter(positions.values()))
                exits = any(json.loads(r['request'])['reduce_only'] for r in pending)
                state = PortfolioState.EXIT_PENDING if exits else (
                    PortfolioState.LONG if p.quantity > 0 else PortfolioState.SHORT)
                reason = 'ACTUAL_EXCHANGE_EXPOSURE'
            elif pending or orders:
                entries = any(not json.loads(r['request'])['reduce_only'] for r in pending)
                state = PortfolioState.ENTRY_PENDING if entries else PortfolioState.EXIT_PENDING
                reason = 'UNRESOLVED_OR_OPEN_ORDER'
            else:
                # A filled response without userFills is NOT proof of a completed
                # exposure lifecycle. Keep the lock even if a snapshot says zero.
                row = self.journal.intent(key) if key else None
                outcome = json.loads(row['outcome'] or '{}') if row else {}
                expected = decimal(outcome.get('filled_quantity', 0), nonnegative=True)
                if row and expected:
                    matching = [f for f in context.fills if str(f.order_id) in
                        {str(row['oid']), *map(str, outcome.get('child_order_ids', []))}]
                    observed = sum((f.quantity for f in matching), Decimal(0))
                    request = json.loads(row['request'])
                    evidence = observed >= expected and all(f.symbol == request['symbol'] and
                        f.side == request['side'] and f.source == 'EXCHANGE_REPORTED_FILL' for f in matching)
                    # Confirm the zero position from actual net fills since this
                    # reserved entry, rather than from an exchange response.
                    net = sum((f.quantity if f.side == 'BUY' else -f.quantity
                        for f in context.fills if f.symbol == request['symbol'] and
                        f.timestamp_ms >= row['created_ms']), Decimal(0))
                    if not evidence or net:
                        state, reason = PortfolioState.RECOVERING, 'ACTUAL_FILL_FLAT_EVIDENCE_REQUIRED'
                    else:
                        state, reason, key = PortfolioState.FLAT, 'AUTHORITATIVE_FLAT_RECONCILED', None
                else:
                    state, reason, key = PortfolioState.FLAT, 'AUTHORITATIVE_FLAT_RECONCILED', None
        self._store(state, reason, entry_key=key, observed_ms=context.account_ms,in_transaction=True)
        from .execution_journal import safe_data
        from .event_timing import timing
        self.journal.db.execute('INSERT INTO events(timestamp_ms,kind,data) VALUES (?,?,?)',
            (now_ms,'GLOBAL_POSITION_RECONCILED',canonical(safe_data(dict(**timing(now_ms),state=state.value,
             session_id=self.journal.session_id,event_type='GLOBAL_POSITION_RECONCILED',candidate_id=None,symbol=None,
             reason=reason,actual_position_count=len(positions),open_order_count=len(orders),
             max_global_positions=1)))))
        return self.report()

    def evaluate(self, request, context, now_ms, *, expected_generation=None):
        self.reconcile(context, now_ms, expected_generation=expected_generation)
        if request.reduce_only:
            held = context.positions.get(request.symbol)
            allowed = bool(held and decimal(held.quantity) and
                (held.quantity > 0) != (request.side == 'BUY') and request.quantity <= abs(held.quantity))
            code = 'SINGLE_POSITION_PASS' if allowed else 'REDUCE_ONLY_VIOLATION'
        else:
            allowed = self.state == PortfolioState.FLAT
            code = 'SINGLE_POSITION_PASS' if allowed else (
                'UNKNOWN_ACCOUNT_STATE' if self.state in {PortfolioState.UNKNOWN, PortfolioState.RECOVERING}
                else 'POSITION_LIMIT')
        return PositionDecision(allowed, code, self.state.value, self.reason, now_ms)

    def reserve_in_transaction(self, key, request, now_ms, *, expected_generation=None):
        """Called INSIDE the same transaction that persists the order intent."""
        prior = self.journal.control(self.CONTROL) or {}
        if expected_generation is not None and prior.get('generation') != expected_generation:
            raise ExchangeError('ACCOUNT_PREFLIGHT_INVALIDATED')
        if (prior.get('state') != 'FLAT' or prior.get('entry_key') is not None or
                prior.get('observed_ms') is None or not 0 <= now_ms-prior['observed_ms'] <= 5000 or
                any(unresolved(r) for r in self.journal.intents())):
            raise ExchangeError('POSITION_LIMIT')
        self._store(PortfolioState.ENTRY_PENDING, 'DURABLE_ENTRY_RESERVED',
                    entry_key=key, observed_ms=prior['observed_ms'], in_transaction=True)

    def require_entry_lease(self, key, generation):
        value = self.journal.control(self.CONTROL) or {}
        if (value.get('state') != 'ENTRY_PENDING' or value.get('entry_key') != key or
                value.get('generation') != generation):
            raise ExchangeError('GLOBAL_POSITION_LEASE_REVOKED')

    def report(self):
        value = self.journal.control(self.CONTROL) or {}
        return dict(value, runtime_state=self.state.value, runtime_reason=self.reason,
                    entry_permission=self.state == PortfolioState.FLAT)


GlobalPositionLock = SinglePositionGuard
