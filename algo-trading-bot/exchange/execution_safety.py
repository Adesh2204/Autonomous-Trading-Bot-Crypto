"""Explicit human authorization, durable nonces, clock and request budgets."""
from dataclasses import dataclass
from decimal import Decimal
import fcntl
import os
from pathlib import Path
import sqlite3
import threading
import time
import tempfile
import json

from .base_exchange import ExchangeError


class NonceManager:
    """One signer lease per process, with a durable high-water mark across restart."""
    def __init__(self, path, signer_address, *, clock_ms=None):
        from .live_readiness import valid_address
        if not valid_address(signer_address):
            raise ExchangeError('API_WALLET_ADDRESS_REQUIRED')
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.pid = os.getpid()
        self.lock = threading.Lock()
        self.closed = False
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.signer_address = signer_address.lower()
        lease_root=Path(tempfile.gettempdir())/('anchorium-signer-leases-'+str(os.getuid()))
        lease_root.mkdir(mode=0o700,exist_ok=True)
        self.lease = open(lease_root/(self.signer_address+'.lease'), 'a+b')
        os.chmod(self.lease.name, 0o600)
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            raise ExchangeError('API_WALLET_ALREADY_LEASED') from None
        try:
            self.lease.seek(0)
            binding=self.lease.read()
            if binding:
                previous=json.loads(binding)
                if previous['nonce_database']!=str(self.path.resolve()):
                    raise ExchangeError('API_WALLET_NONCE_STORE_CHANGED_FRESH_KEY_REQUIRED')
                if not self.path.exists():
                    raise ExchangeError('API_WALLET_NONCE_HISTORY_MISSING_FRESH_KEY_REQUIRED')
            self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            os.chmod(self.path, 0o600)
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS nonces (signer TEXT PRIMARY KEY,last INTEGER NOT NULL)')
            if not binding:
                self.lease.seek(0)
                self.lease.write(json.dumps({'nonce_database':str(self.path.resolve())}).encode())
                self.lease.flush()
                os.fsync(self.lease.fileno())
        except Exception:
            if hasattr(self,'db'):
                self.db.close()
            self.lease.close()
            raise

    def next(self):
        if self.closed or os.getpid() != self.pid:
            raise ExchangeError('NONCE_SIGNER_PROCESS_MISMATCH')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                row = self.db.execute('SELECT last FROM nonces WHERE signer=?', (self.signer_address,)).fetchone()
                now = self.clock_ms()
                if type(now) is not int or now < 0:
                    raise ExchangeError('INVALID_NONCE_CLOCK')
                nonce = max(now, row[0] + 1 if row else now)
                if nonce - now > 5000:
                    raise ExchangeError('NONCE_CLOCK_DRIFT')
                self.db.execute('INSERT OR REPLACE INTO nonces VALUES (?,?)', (self.signer_address, nonce))
                self.db.execute('COMMIT')
                return nonce
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()
                self.lease.close()


class ClockHealthMonitor:
    def __init__(self, *, clock_ms=None, monotonic_ms=None, max_skew_ms=2000, max_age_ms=30000):
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.max_skew_ms = max_skew_ms
        self.max_age_ms = max_age_ms
        self.observed_ms = None
        self.wall_base = self.clock_ms()
        self.monotonic_base = self.monotonic_ms()
        self.offset_ms = None
        self.reason = 'CLOCK_REFERENCE_REQUIRED'

    def observe(self, server_ms, sent_ms, received_ms):
        if any(type(x) is not int for x in (server_ms, sent_ms, received_ms)) or not 0 <= received_ms-sent_ms <= 2000:
            self.reason = 'CLOCK_REFERENCE_UNRELIABLE'
            self.observed_ms = None
            return False
        self.offset_ms = server_ms - (sent_ms + received_ms) // 2
        self.observed_ms = received_ms
        self.wall_base = self.clock_ms()
        self.monotonic_base = self.monotonic_ms()
        self.reason = None if abs(self.offset_ms) <= self.max_skew_ms else 'CLOCK_SKEW'
        return self.healthy

    @property
    def healthy(self):
        now = self.clock_ms()
        jump = abs((now-self.wall_base) - (self.monotonic_ms()-self.monotonic_base))
        return (self.reason is None and self.observed_ms is not None and
                0 <= now-self.observed_ms <= self.max_age_ms and jump <= self.max_skew_ms)

    def require(self):
        if not self.healthy:
            raise ExchangeError('CLOCK_HEALTH_REQUIRED')


class HyperliquidRateLimitManager:
    """Shared by every client in the signing process; conservative on exhaustion."""
    SMALL_INFO = {'l2Book', 'allMids', 'clearinghouseState', 'orderStatus',
                  'spotClearinghouseState', 'exchangeStatus'}
    def __init__(self, journal, *, clock_ms=None, ip_weight_limit=1200, daily_limit=50000):
        self.journal = journal
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.ip_weight_limit = ip_weight_limit
        self.daily_limit = daily_limit
        self.lock = threading.RLock()
        self.weights = []
        self.budget = None
        self.budget_observed_ms = None
        self.reserved_since_snapshot = 0
        self.open_orders = None
        self.recent_errors = 0
        self.backoff_until = 0

    def _weight(self, weight):
        now = self.clock_ms()
        self.weights = [(t,w) for t,w in self.weights if t > now-60000]
        if now < self.backoff_until or sum(w for _,w in self.weights)+weight > self.ip_weight_limit:
            raise ExchangeError('RATE_LIMITED')
        self.weights.append((now, weight))

    def reserve_info(self, query):
        with self.lock:
            self._weight(2 if query in self.SMALL_INFO else 60 if query == 'userRole' else 20)

    def observe_info(self, query, response):
        with self.lock:
            if query == 'userRateLimit':
                try:
                    used, cap = response['nRequestsUsed'], response['nRequestsCap']
                    if type(used) is not int or type(cap) is not int or used < 0 or cap < 0:
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    raise ExchangeError('INVALID_ACCOUNT_REQUEST_BUDGET') from None
                self.budget = max(0, cap-used)
                self.budget_observed_ms = self.clock_ms()
                self.reserved_since_snapshot = 0
            if query == 'openOrders' and isinstance(response, list):
                self.open_orders = len(response)
            if isinstance(response, list) and query in {'recentTrades','userFills','userFillsByTime',
                    'fundingHistory','userFunding','candleSnapshot'}:
                self._weight(len(response)//(60 if query == 'candleSnapshot' else 20))

    @property
    def healthy(self):
        return (self.budget is not None and self.budget > self.reserved_since_snapshot and
                self.budget_observed_ms is not None and 0 <= self.clock_ms()-self.budget_observed_ms <= 60000 and
                self.clock_ms() >= self.backoff_until and self.open_orders is not None)

    def reserve_action(self, *, operations=1, creates_order=False):
        with self.lock:
            if type(operations) is not int or operations < 1 or not self.healthy:
                raise ExchangeError('RATE_LIMITED')
            if self.budget-self.reserved_since_snapshot < operations or (
                    creates_order and self.open_orders+operations > 1000):
                raise ExchangeError('RATE_LIMITED')
            day = self.clock_ms()//86400000
            key = 'daily_actions:' + str(day)
            with self.journal.transaction():
                row = self.journal.db.execute('SELECT value FROM controls WHERE name=?', (key,)).fetchone()
                used = int(row[0]) if row else 0
                if used+operations > self.daily_limit:
                    raise ExchangeError('DAILY_ACTION_LIMIT')
                self._weight(1+operations//40)
                self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)', (key,str(used+operations)))
            self.reserved_since_snapshot += operations
            if creates_order:
                self.open_orders += operations

    def error(self):
        with self.lock:
            self.recent_errors += 1
            self.backoff_until = self.clock_ms()+min(30000,1000*2**min(self.recent_errors-1,5))

    def success(self):
        self.recent_errors = 0


@dataclass(frozen=True)
class HumanLiveApproval:
    """Supplied only after separate human authorization and manual account review."""
    approval_id: str
    team_address: str
    signer_address: str
    expires_ms: int
    manually_verified: bool = False


class LiveAuthorization:
    def __init__(self, approval=None, *, clock_ms=None):
        self.approval = approval
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.revoked = False

    def require(self, team_address, signer_address):
        import venue_config
        from order_guard import OrderRoutingBlocked
        p = self.approval
        if (self.revoked or not isinstance(p, HumanLiveApproval) or not p.approval_id or
                p.manually_verified is not True or type(p.expires_ms) is not int or
                self.clock_ms() >= p.expires_ms or p.team_address.lower()!=team_address.lower() or
                p.signer_address.lower()!=signer_address.lower()):
            raise OrderRoutingBlocked('EXPLICIT_MANUAL_LIVE_AUTHORIZATION_REQUIRED')
        if (venue_config.TRADING_VENUE!='HYPERLIQUID_TESTNET' or
                venue_config.EXECUTION_MODE!='HYPERLIQUID_TESTNET_LIVE' or
                venue_config.ALLOW_LIVE_ORDERS is not True or
                os.environ.get('EXECUTION_MODE','')!='HYPERLIQUID_TESTNET_LIVE' or
                os.environ.get('ALLOW_LIVE_ORDERS','').lower()!='true' or
                os.environ.get('HL_NETWORK','testnet')!='testnet' or os.environ.get('HL_DEX','par')!='par' or
                os.environ.get('TRADING_VENUE','HYPERLIQUID_TESTNET')!='HYPERLIQUID_TESTNET'):
            raise OrderRoutingBlocked('LIVE_RUNTIME_CONFIGURATION_REQUIRED')

    def revoke(self):
        self.revoked = True
