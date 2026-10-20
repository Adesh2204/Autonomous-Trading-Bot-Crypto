"""Read-only opportunity observation for the existing bounded qualification rule.

No order transport, approval or nonce allocation exists here. L2 aggregation and
new directions are research only; eligibility retains 10% of BOTH best levels.
"""
from dataclasses import asdict, replace
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

from .base_exchange import ExchangeError
from .feed_transport import FeedTransportHealth
from .full_position_close import observed_scope
from .hyperliquid_market_data import parse_book, HyperliquidMarketData
from .hyperliquid_client import TESTNET_WS_URL

EXECUTION_MARKETS = frozenset({'par:BTC', 'par:ETH', 'par:HYPE'})
MAX_AGE_MS = 5000


def sweep(levels, quantity, limit, side):
    """Snapshot cost, not a prediction or actual fill. Never used for eligibility."""
    remaining, cost = quantity, D(0)
    available = D(0)
    for level in levels:
        if (side == 'BUY' and level.price > limit) or (side == 'SELL' and level.price < limit):
            break
        available += level.quantity
        taken = min(remaining, level.quantity)
        cost += taken * level.price
        remaining -= taken
    filled = quantity - remaining
    return dict(available_quantity=str(available), requested_quantity=str(quantity),
                covered_quantity=str(filled), shortfall=str(remaining), cost=str(cost),
                vwap=str(cost / filled) if filled else None, limit=str(limit),
                evidence='OBSERVED_BOOK_ESTIMATE_NOT_EXECUTION_OR_FILL')


def research_residuals(spec, quantity, close_price, close_side):
    """Evaluate each shape, not only the one-lot historical example."""
    count = int(quantity / spec.size_step)
    if count > 10000:
        return dict(ready=False, blocker='QUALIFICATION_RESIDUAL_ANALYSIS_BOUND')
    proofs = []
    for n in range(1, count + 1):
        size = spec.size_step * n
        if size * close_price < 10:
            try:
                proof = observed_scope(spec, close_side, size)
            except ExchangeError:
                return dict(ready=False, blocker='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL',
                            first_unverified_quantity=str(size), close_side=close_side,
                            notional=str(size * close_price))
            proofs.append(proof)
    return dict(ready=count > 0, possible_residual_count=count, close_side=close_side,
                historical_shapes=proofs, future_acceptance_guaranteed=False,
                protective_stop_verified=False)


def inspect_book(spec, book, now_ms, side='BUY'):
    """Stage A: no account reads, margin assumptions, signing, or rule expansion."""
    if side not in {'BUY', 'SELL'}:
        raise ExchangeError('INVALID_RESEARCH_DIRECTION')
    row = dict(symbol=spec.symbol, entry_side=side, potential=False, stage='PUBLIC_BOOK_ONLY',
               asset_id=spec.asset_id, size_step=str(spec.size_step), observed_ms=now_ms,
               exchange_ms=book.timestamp_ms, received_ms=book.received_timestamp_ms,
               execution_scope_permitted=spec.symbol in EXECUTION_MARKETS and side == 'BUY',
               account_checks_performed=False, normal_minimum='10', maximum_notional='25',
               depth_policy='STRICT_10_PERCENT_OF_EACH_BEST_LEVEL', protection_verified=False)
    if book.symbol != spec.symbol or not 0 <= now_ms - book.timestamp_ms <= MAX_AGE_MS:
        return dict(row, blocker='WRONG_OR_STALE_BOOK')
    if (not book.bids or not book.asks or book.asks[0].price <= book.bids[0].price
            or any(x.price <= 0 or x.quantity <= 0 for x in (*book.bids, *book.asks))):
        return dict(row, blocker='QUALIFICATION_TWO_SIDED_BOOK_REQUIRED')
    if (any(a.price <= b.price for a, b in zip(book.bids, book.bids[1:]))
            or any(a.price >= b.price for a, b in zip(book.asks, book.asks[1:]))):
        return dict(row, blocker='DUPLICATE_OR_UNSORTED_BOOK_LEVELS')
    bid, ask = book.bids[0], book.asks[0]
    spread = (ask.price - bid.price) / ((ask.price + bid.price) / 2) * 10000
    if side == 'BUY':
        entry = spec.normalize_price(ask.price * D('1.0005'), 'BUY')
        reference = spec.normalize_price(bid.price * D('.99'), 'SELL')
        bound = spec.normalize_price(reference * D('.995'), 'SELL')
        immediate = spec.normalize_price(bid.price * D('.998'), 'SELL')
        entry_levels, exit_levels, close_side = book.asks, book.bids, 'SELL'
        # For a SHORT research candidate, subminimum BUY evidence is evaluated
        # at the lower reviewed price, not just the high adverse exit ceiling.
        residual_price = bound
    else:
        entry = spec.normalize_price(bid.price * D('.9995'), 'SELL')
        reference = spec.normalize_price(ask.price * D('1.01'), 'BUY')
        bound = spec.normalize_price(reference * D('1.005'), 'BUY')
        immediate = spec.normalize_price(ask.price * D('1.002'), 'BUY')
        entry_levels, exit_levels, close_side = book.bids, book.asks, 'BUY'
        residual_price = spec.normalize_price(bid.price * D('.98505'), 'SELL')
    lot = spec.size_step
    minimum = (D(10) / entry / lot).to_integral_value(rounding=ROUND_CEILING) * lot
    bounds = dict(notional=D(25) / entry, bid_depth=bid.quantity * D('.1'), ask_depth=ask.quantity * D('.1'))
    capacity = min(bounds.values())
    maximum = (capacity / lot).to_integral_value(rounding=ROUND_FLOOR) * lot
    # Evaluate a legal minimum even when strict BBO depth fails, to show why
    # multi-level research cannot silently substitute for the current policy.
    residuals = research_residuals(spec, max(minimum, maximum), residual_price, close_side)
    entry_sweep = sweep(entry_levels, minimum, entry, side)
    exit_sweep = sweep(exit_levels, minimum, bound, close_side)
    aggregate_cap = min(D(25) / entry, D(entry_sweep['available_quantity']) * D('.1'),
                        D(exit_sweep['available_quantity']) * D('.1'))
    aggregate_qty = (aggregate_cap / lot).to_integral_value(rounding=ROUND_FLOOR) * lot
    row.update(bid=str(bid.price), ask=str(ask.price), spread_bps=str(spread),
        bid_quantity=str(bid.quantity), ask_quantity=str(ask.quantity),
        bid_depth_limit=str(bid.quantity * D('.1')), ask_depth_limit=str(ask.quantity * D('.1')),
        entry_limit=str(entry), exit_bound=str(bound), reviewed_immediate_exit_limit=str(immediate),
        minimum_valid_entry_quantity=str(minimum), minimum_entry_notional=str(minimum * entry),
        maximum_book_quantity=str(maximum), maximum_book_notional=str(maximum * entry),
        quantity_bounds={k: str(v) for k, v in bounds.items()},
        binding_capacity_constraints=[k for k, v in bounds.items() if v == capacity],
        minimum_lot_notional=str(lot * entry), residuals=residuals,
        l2_research=dict(entry=entry_sweep, exit=exit_sweep,
            levels=dict(bids=len(book.bids), asks=len(book.asks)),
            hypothetical_aggregate_depth_quantity=str(aggregate_qty),
            aggregate_can_meet_minimum=aggregate_qty >= minimum,
            affects_eligibility=False, separate_policy_approval_required=True),
        raw_book=asdict(book))
    if maximum < minimum:
        row['blocker'] = 'QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS'
    elif spread > 50:
        row['blocker'] = 'QUALIFICATION_SPREAD_EXCEEDED'
    elif not residuals['ready']:
        row['blocker'] = residuals['blocker']
    elif not row['execution_scope_permitted']:
        row['blocker'] = 'SEPARATE_DIRECTION_OR_MARKET_APPROVAL_REQUIRED'
    else:
        row.update(potential=True, blocker=None)
    return row


class PublicBookStream:
    """One receiver; public subscriptions only. SQLite/account reads stay on owner.

    Exactly acknowledged subscriptions plus two distinct exchange timestamps
    establish actual channel operation. Disconnect clears all candidate caches.
    Three connections maximum per bounded watcher; REST is the fallback.
    """
    def __init__(self, symbols, rates, *, clock_ms, connect=None):
        self.symbols = tuple(symbols)
        if not self.symbols or any(not s.startswith('par:') for s in self.symbols):
            raise ExchangeError('PAR_PUBLIC_SUBSCRIPTIONS_REQUIRED')
        self.rates, self.clock_ms = rates, clock_ms
        self.connect = connect or self._connect
        self.health = FeedTransportHealth(wall_ms=clock_ms)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.books, self.updates, self.support_seen = {}, {}, {}
        self.socket = self.thread = None
        self.connected = False
        self.failures = []
        self.market_errors = {}
        self.attempts = 0

    @staticmethod
    def _connect():
        import certifi
        import websocket
        return websocket.create_connection(TESTNET_WS_URL, timeout=3,
                                            sslopt={'ca_certs': certifi.where()})

    def begin(self):
        with self.lock:
            self.books.clear(); self.updates.clear()
            subscriptions = [dict(method='subscribe', subscription=dict(type='l2Book', coin=s))
                             for s in self.symbols]
            generation = self.health.begin(subscriptions)
            self.connected = True
            return generation, subscriptions

    def ingest(self, message, generation):
        with self.lock:
            if not self.health.receive(message, generation):
                return
            if message.get('channel') != 'l2Book':
                return
            data = message.get('data', {})
            symbol = data.get('coin')
            if symbol not in self.symbols:
                raise ExchangeError('UNEXPECTED_BOOK_SYMBOL')
            key = self.health.key(dict(type='l2Book', coin=symbol))
            if key not in self.health.confirmed:
                return
            try:
                book = parse_book(data, symbol)
            except ExchangeError as exc:
                self.books.pop(symbol, None)
                self.updates.pop(symbol, None)
                self.market_errors[symbol] = dict(at_ms=self.clock_ms(), reason=str(exc))
                return
            if not 0 <= self.clock_ms() - book.timestamp_ms <= MAX_AGE_MS:
                return
            previous = self.books.get(symbol)
            if previous and book.timestamp_ms <= previous.timestamp_ms:
                return
            book = replace(book, received_timestamp_ms=self.clock_ms(), processed_timestamp_ms=self.clock_ms())
            self.books[symbol] = book
            self.market_errors.pop(symbol, None)
            self.updates[symbol] = self.updates.get(symbol, 0) + 1
            if self.updates[symbol] >= 2:
                self.support_seen[symbol] = dict(generation=generation, updates=self.updates[symbol],
                                               last_exchange_ms=book.timestamp_ms)

    def disconnect(self, reason):
        with self.lock:
            self.connected = False
            self.books.clear(); self.updates.clear()
            self.health.disconnect(reason)

    def snapshot(self, symbol):
        with self.lock:
            book = self.books.get(symbol)
            if (not self.connected or self.updates.get(symbol, 0) < 2 or book is None
                    or not 0 <= self.clock_ms() - book.timestamp_ms <= MAX_AGE_MS):
                return None
            return book

    def start(self):
        if self.thread is not None:
            raise ExchangeError('PUBLIC_WATCHER_ALREADY_STARTED')
        self.thread = threading.Thread(target=self._run, name='qualification-public-books', daemon=True)
        self.thread.start()

    def _run(self):
        import websocket
        for attempt in range(3):
            if self.stop_event.is_set():
                break
            identity = 'qualification-watch-' + str(attempt)
            self.attempts += 1
            try:
                self.rates.ws_open(identity)
                socket = self.connect()
                self.socket = socket
                socket.settimeout(1)
                generation, subscriptions = self.begin()
                for message in subscriptions:
                    sub = message['subscription']
                    with self.lock:
                        allowed = self.health.subscription_sent(sub) and self.rates.ws_send(identity, sub)
                    if allowed:
                        socket.send(json.dumps(message))
                while not self.stop_event.is_set():
                    with self.lock:
                        ping = self.health.poll()
                    if ping and self.rates.ws_send(identity, heartbeat=True):
                        socket.send(json.dumps(dict(method='ping')))
                        with self.lock:
                            self.health.ping_sent()
                    try:
                        raw = socket.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw:
                        raise ExchangeError('PUBLIC_SOCKET_CLOSED_WITHOUT_CODE')
                    if len(raw) > 2 * 1024 * 1024:
                        raise ExchangeError('PUBLIC_WS_MESSAGE_TOO_LARGE')
                    self.ingest(json.loads(raw), generation)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
                with self.lock:
                    self.failures.append(dict(at_ms=self.clock_ms(), reason=reason))
                self.disconnect(reason)
            finally:
                if self.socket:
                    self.socket.close(); self.socket = None
                self.rates.ws_close(identity)
                self.disconnect('OPERATOR_OR_BOUNDED_WATCH_STOP' if self.stop_event.is_set() else 'RECONNECT')
            if self.stop_event.wait(self.health.backoff(attempt + 1)):
                break

    def report(self):
        with self.lock:
            return dict(self.health.report(), connected=self.connected, attempts=self.attempts,
                        verified_public_channel_observations=dict(self.support_seen),
                        errors=list(self.failures), current_market_errors=dict(self.market_errors), exchange_actions=0)

    def close(self):
        self.stop_event.set()
        socket = self.socket
        if socket:
            socket.close()
        if self.thread:
            self.thread.join(4)
            if self.thread.is_alive():
                raise ExchangeError('PUBLIC_RECEIVER_SHUTDOWN_UNCONFIRMED')


class PublicBookReader:
    """No account queries. A missing/stale WS book admits at most one REST read
    per symbol per five seconds, also bounded globally by the shared limiter.
    """
    def __init__(self, market, stream=None, *, monotonic=None):
        self.market, self.stream = market, stream
        self.monotonic = monotonic or time.monotonic
        self.started = self.monotonic()
        self.last_rest, self.rest_books, self.errors = {}, {}, []

    def get(self, symbol):
        if self.stream:
            book = self.stream.snapshot(symbol)
            if book:
                return book, 'WS_ACKNOWLEDGED_REPEATED'
            if self.monotonic() - self.started < 10:
                return None, 'WS_STARTUP_GRACE'
        now = self.monotonic()
        if now - self.last_rest.get(symbol, -float('inf')) >= 5:
            self.last_rest[symbol] = now
            try:
                # Admission is immediate here: do not spend the public reserve
                # or wait 65s for an ordinary monitoring update.
                self.market.client.rate_limits.read_budget_wait_seconds = 0
                self.rest_books[symbol] = self.market.get_orderbook(symbol)
            except ExchangeError as exc:
                self.rest_books.pop(symbol, None)
                self.errors.append(dict(symbol=symbol, at_ms=self.market.client.clock_ms(), reason=str(exc)))
                self.errors[:] = self.errors[-100:]
        book = self.rest_books.get(symbol)
        if book and 0 <= self.market.client.clock_ms() - book.timestamp_ms <= MAX_AGE_MS:
            return book, 'RATE_LIMITED_REST'
        return None, 'NO_FRESH_BOOK'


class OpportunityGate:
    """Bounded full validations, with no expensive reads on ordinary updates."""
    def __init__(self, *, cooldown_seconds=60, maximum_attempts=2, monotonic=None):
        if cooldown_seconds < 60 or not 1 <= maximum_attempts <= 3:
            raise ExchangeError('INVALID_WATCH_PREFLIGHT_BOUNDS')
        self.cooldown = cooldown_seconds
        self.maximum_attempts = maximum_attempts
        self.monotonic = monotonic or time.monotonic
        self.attempts = 0
        self.last = -float('inf')
        self.consumed_books = set()

    def claim(self, row):
        identity = (row['symbol'], row['exchange_ms'])
        if (not row['potential'] or self.attempts >= self.maximum_attempts
                or self.monotonic() - self.last < self.cooldown or identity in self.consumed_books):
            return False
        self.last = self.monotonic(); self.attempts += 1
        self.consumed_books.add(identity)
        return True


def durable_readback(path, expected_source, *, clean=False):
    """Verify committed checkpoints through a separate read-only SQLite handle.
    No journal reopen, account history replay, or network call is necessary.
    """
    from .execution_journal import fingerprint
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        identity = dict(db.execute('SELECT name,value FROM identity'))
        rows = db.execute('SELECT data,checksum FROM recovery_snapshots ORDER BY seq DESC').fetchall()
        if integrity != 'ok' or not rows:
            raise ExchangeError('QUALIFICATION_DURABLE_CHECKPOINT_REQUIRED')
        values = []
        for data, checksum in rows:
            value = json.loads(data)
            if (fingerprint(value) != checksum or value['source_identity'] != expected_source
                    or value.get('checkpoint_error') or value['venue'] != 'testnet:par'
                    or value['schema_version'] != 1 or value['team_address'] != identity.get('team')
                    or value['session_id'] != identity.get('session') or identity.get('venue') != 'testnet:par'):
                raise ExchangeError('QUALIFICATION_CHECKPOINT_IDENTITY_OR_CHECKSUM_FAILED')
            values.append(value)
        account = db.execute('SELECT data FROM account_checkpoint WHERE id=1').fetchone()
        if not account or json.loads(account[0]) != values[0]['account']:
            raise ExchangeError('QUALIFICATION_CHECKPOINT_ACCOUNT_MISMATCH')
        if clean and not values[0]['last_clean_shutdown']:
            raise ExchangeError('QUALIFICATION_CLEAN_SHUTDOWN_REQUIRED')
        actions = {t: db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
                   for t in ('intents', 'api_actions', 'signed_management')}
        if any(actions.values()):
            raise ExchangeError('READ_ONLY_JOURNAL_CONTAINS_ACTIONS')
        return dict(integrity=integrity, snapshots_verified=len(rows), checksums_verified=True,
                    source_identity=expected_source, clean=values[0]['last_clean_shutdown'], actions=actions)


def prior_execution_check(root):
    """Mirror the existing activation history blocks without mutating the ledger."""
    state = Path(root) / 'runtime/testnet/anchorium-bot-1'
    result = {}
    for name in ('certification.sqlite', 'qualification.sqlite'):
        path = state / name
        if not path.exists():
            result[name] = dict(exists=False)
            continue
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ExchangeError('PRIOR_EXECUTION_JOURNAL_CORRUPT')
            pending = db.execute("SELECT COUNT(*) FROM intents WHERE state IN "
                "('PREPARED','SUBMITTED','UNKNOWN','OPEN','PARTIALLY_FILLED')").fetchone()[0]
            total = db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]
            effective_total=total
            if name=='qualification.sqlite':
                from .qualification_intent_recovery import effective_rows
                effective_total=len(effective_rows(db))
            consumed = db.execute("SELECT value FROM controls WHERE name='qualification_entry_consumed'").fetchone()
            result[name] = dict(exists=True, pending=pending, intents=total, entry_consumed=bool(consumed),
                actionable_intents=effective_total,certified_nontransmission_records=total-effective_total)
            if name == 'certification.sqlite' and pending:
                raise ExchangeError('PRIOR_CERTIFICATION_UNRESOLVED_REVIEW_REQUIRED')
            if name == 'qualification.sqlite' and (effective_total or consumed):
                raise ExchangeError('QUALIFICATION_PRIOR_ATTEMPT_READ_ONLY_RECOVERY_REQUIRED')
    return result


class ReadOnlyQualificationSession:
    """One journal, limiter and recovery object for the bounded watcher session.
    Existing context/central validators remain authoritative. Every full attempt
    performs reconciliation once (twice only for the existing clock-pair retry).
    """
    def __init__(self, root, directory, source_hash, policy_hash, *, progress, cancel_event):
        from .execution_journal import ExecutionJournal
        from .execution_safety import HyperliquidRateLimitManager, ClockHealthMonitor
        from .hyperliquid_client import HyperliquidClient
        from .hyperliquid_account import HyperliquidAccount
        from .certification_runtime import CertificationRecovery
        from .reliability_policy import load_reliability_policy
        from .testnet_qualification import QualificationContextProvider
        from .testnet_certification import TEAM, API
        self.root, self.directory = Path(root), Path(directory)
        self.source_hash, self.policy_hash, self.progress = source_hash, policy_hash, progress
        rate_policy, clock_policy, protection = load_reliability_policy(root / 'configs/reliability_policy.json')
        if protection.enabled:
            raise ExchangeError('QUALIFICATION_GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        self.journal = ExecutionJournal(directory / 'read_only.sqlite', session_id='qualification-watch', team_address=TEAM)
        self.rates = HyperliquidRateLimitManager(self.journal, policy=rate_policy, signer_address=API)
        self.rates.read_progress = progress
        self.client = HyperliquidClient(rate_limits=self.rates, progress=progress)
        self.client.read_cancel_event = cancel_event
        self.recovery = None
        self.reconciliation_calls = 0
        self.identity = None
        self.attempt_reports = []
        self.closed = False
        self.clock_policy = clock_policy
        self._provider_class = QualificationContextProvider
        self._recovery_class = CertificationRecovery
        self._account_class = HyperliquidAccount
        self._clock_class = ClockHealthMonitor
        self.team, self.api = TEAM, API

    def start(self):
        self.client.startup()
        self.account = self._account_class(self.client, self.team)
        self.market = HyperliquidMarketData(self.client)
        self.recovery = self._recovery_class(self.account, self.journal, initial_start_ms=0)
        self.clock = self._clock_class(clock_ms=self.client.clock_ms, journal=self.journal, **self.clock_policy)
        self.provider = self._provider_class(self.market, self.account, self.api, self.clock, self.rates,
            reconcile_before_load=self._reconcile, progress=self.progress,
            reconciliation_ready=lambda: self.recovery.account_truth_ready, feed_ready=lambda: True)

    def _reconcile(self):
        self.reconciliation_calls += 1
        return self.recovery.recover()

    def verify_signer(self):
        from .practice_preflight import verify_private_identity, check_local_nonce_ownership
        identity = verify_private_identity(self.root, self.api, self.team)
        lease = check_local_nonce_ownership(self.root / 'runtime/testnet/anchorium-bot-1/nonces.sqlite',
                                          self.api, self.team, root=self.root)
        self.identity = dict(observed_ms=self.client.clock_ms(), identity=identity, local_lease=lease,
            sole_host_evidence='HUMAN_CONFIRMED_IN_CHAT; LOCAL_LEASE_CANNOT_CHECK_OTHER_MACHINES',
            signature_created=False)
        return self.identity

    def refresh_metadata(self):
        metadata = self.client.post_info('meta')
        self.client.validate_metadata(metadata)
        self.client.metadata_timestamp_ms = self.client.clock_ms()

    def validate(self, symbol, *, audit_only=False):
        from .testnet_qualification import find_largest_safe_qualification_quantity
        if symbol not in EXECUTION_MARKETS:
            raise ExchangeError('UNAPPROVED_QUALIFICATION_MARKET')
        started = time.monotonic()
        before = self.reconciliation_calls
        report = dict(symbol=symbol, eligible_for_risk_review=False, audit_only=audit_only)
        self.attempt_reports.append(report)
        try:
            self.progress('REFRESHING_ACCOUNT', symbol=symbol)
            report['prior_execution'] = prior_execution_check(self.root)
            self.verify_signer()
            self.rates.read_budget_wait_seconds = 65
            context = self.provider.load(SimpleNamespace(symbol=symbol, reduce_only=False))
            report.update(quote=asdict(context.quote), active_asset=context.active_asset,
                readiness=asdict(context.readiness), account_observed_ms=context.account_ms,
                final_positions=[asdict(p) for p in context.positions.values()],
                final_orders=list(context.open_orders), final_reconciliation=asdict(self.recovery.last_report),
                clock=self.clock.report(), signer=self.identity)
            if not context.readiness.account_ready or context.positions or context.open_orders or not context.reconciled:
                raise ExchangeError('QUALIFICATION_FRESH_FLAT_ACCOUNT_BOOK_REQUIRED')
            # A committed local readback proves durability; keep network truth
            # fresh without replaying the same account history after reopening.
            report['checkpoint'] = durable_readback(self.directory / 'read_only.sqlite', self.recovery.source)
            self.progress('CHECKING_RESIDUAL_EXITS', symbol=symbol)
            sizing = find_largest_safe_qualification_quantity(context, self.client, self.source_hash, self.policy_hash)
            report['sizing'] = sizing
            if not sizing['ready']:
                raise ExchangeError(sizing['rejection'])
            from .testnet_qualification import QualificationProposal
            proposal = QualificationProposal(**sizing['proposal'])
            now = self.client.clock_ms()
            if any(not 0 <= now - stamp <= MAX_AGE_MS for stamp in
                   (context.account_ms, context.readiness.observed_ms, context.quote.timestamp_ms,
                    context.quote.mark_timestamp_ms)):
                raise ExchangeError('QUALIFICATION_CLOCK_ACCOUNT_QUOTE_PAIR_NOT_READY')
            report.update(eligible_for_risk_review=not audit_only, proposal=asdict(proposal),
                proposal_hash=proposal.identity, central_validation=sizing['central_validation'],
                residual_close_scope=sizing['residual_close_scope'],
                spread_bps=str((context.quote.ask - context.quote.bid) / context.quote.mid * 10000))
            return report
        except ExchangeError as exc:
            report['blocker'] = str(exc)
            return report
        finally:
            report.update(elapsed_seconds=round(time.monotonic()-started, 3),
                          reconciliation_calls=self.reconciliation_calls-before)
            self.rates.read_budget_wait_seconds = 0

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.recovery is not None:
                self.recovery.checkpoint(clean=True)
                self.cleanup = durable_readback(self.directory / 'read_only.sqlite', self.recovery.source, clean=True)
        finally:
            self.client.close()
            self.journal.close()


def source_unchanged(root, source_hash, policy_hash):
    from .paper_operations import active_source_hash
    from venue_config import require_paper_migration
    require_paper_migration()
    if (active_source_hash(root) != source_hash or
            hashlib.sha256((root / 'configs/reliability_policy.json').read_bytes()).hexdigest() != policy_hash):
        raise ExchangeError('SOURCE_OR_POLICY_CHANGED_DURING_WATCH')
