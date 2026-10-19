"""Explicit human authorization, durable nonces, clock and request budgets."""
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import sqlite3
import threading
import time
import json
import socket

from .base_exchange import ExchangeError
from .reliability_policy import ClockState


class NonceManager:
    """One signer lease per process, with a durable high-water mark across restart."""
    def __init__(self, path, signer_address, *, clock_ms=None, journal=None, max_future_ms=5000):
        from .live_readiness import valid_address
        if not valid_address(signer_address):
            raise ExchangeError('API_WALLET_ADDRESS_REQUIRED')
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.pid = os.getpid()
        self.lock = threading.Lock()
        self.closed = False
        self.journal = journal
        self.max_future_ms=max_future_ms
        if type(max_future_ms) is not int or max_future_ms<1:
            raise ExchangeError('INVALID_NONCE_DRIFT_POLICY')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.signer_address = signer_address.lower()
        # A caller's TMPDIR must not create a second lock namespace for one key.
        lease_root=Path('/tmp').resolve()/('anchorium-signer-leases-'+str(os.getuid()))
        lease_root.mkdir(mode=0o700,exist_ok=True)
        lease_path=lease_root/(self.signer_address+'.lease')
        previously_bound=lease_path.exists()
        self.lease = open(lease_path, 'a+b')
        os.chmod(self.lease.name, 0o600)
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            if self.journal is not None:
                self.journal.event('API_WALLET_LOCK_CONFLICT',self.clock_ms(),api_wallet=self.signer_address,
                                   attempted_pid=self.pid)
            raise ExchangeError('API_WALLET_ALREADY_LEASED') from None
        try:
            self.lease.seek(0)
            binding=self.lease.read()
            if binding:
                try:
                    previous=json.loads(binding)
                except (ValueError,TypeError):
                    raise ExchangeError('NONCE_LEASE_BINDING_CORRUPT_FRESH_KEY_REQUIRED') from None
                if previous['nonce_database']!=str(self.path.resolve()):
                    raise ExchangeError('API_WALLET_NONCE_STORE_CHANGED_FRESH_KEY_REQUIRED')
                if not self.path.exists():
                    raise ExchangeError('API_WALLET_NONCE_HISTORY_MISSING_FRESH_KEY_REQUIRED')
            elif previously_bound:
                raise ExchangeError('NONCE_LEASE_BINDING_MISSING_FRESH_KEY_REQUIRED')
            self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            os.chmod(self.path, 0o600)
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS nonces (signer TEXT PRIMARY KEY,last INTEGER NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS nonce_health (signer TEXT PRIMARY KEY,reason TEXT NOT NULL)')
            self.owner = dict(nonce_database=str(self.path.resolve()),pid=self.pid,
                              hostname=socket.gethostname(),started_ms=self.clock_ms(),
                              api_wallet=self.signer_address)
            if not binding:
                self.lease.write(json.dumps({'nonce_database':str(self.path.resolve())}).encode())
                self.lease.flush()
                os.fsync(self.lease.fileno())
            owner_path=lease_root/(self.signer_address+'.owner.json')
            temporary=owner_path.with_suffix('.tmp')
            with open(temporary,'w') as owner_file:
                os.chmod(temporary,0o600)
                owner_file.write(json.dumps(self.owner))
                owner_file.flush()
                os.fsync(owner_file.fileno())
            os.replace(temporary,owner_path)
        except Exception:
            if hasattr(self,'db'):
                self.db.close()
            self.lease.close()
            raise

    def next(self):
        if self.closed or os.getpid() != self.pid:
            raise ExchangeError('NONCE_SIGNER_PROCESS_MISMATCH')
        with self.lock:
            if not self.healthy:
                raise ExchangeError('NONCE_SIGNING_DEGRADED')
            self.db.execute('BEGIN IMMEDIATE')
            try:
                row = self.db.execute('SELECT last FROM nonces WHERE signer=?', (self.signer_address,)).fetchone()
                now = self.clock_ms()
                if type(now) is not int or now < 0:
                    raise ExchangeError('INVALID_NONCE_CLOCK')
                nonce = max(now, row[0] + 1 if row else now)
                if nonce - now > self.max_future_ms:
                    raise ExchangeError('NONCE_CLOCK_DRIFT')
                self.db.execute('INSERT OR REPLACE INTO nonces VALUES (?,?)', (self.signer_address, nonce))
                self.db.execute('COMMIT')
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                raise
            if self.journal is not None:
                self.journal.event('NONCE_GENERATED',now,nonce=nonce,api_wallet=self.signer_address,pid=self.pid)
            return nonce

    @property
    def healthy(self):
        return (not self.closed and not self.lease.closed and os.getpid()==self.pid and self.db.execute(
            'SELECT reason FROM nonce_health WHERE signer=?',(self.signer_address,)).fetchone() is None)

    def degrade(self, reason='NONCE_ERROR'):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO nonce_health VALUES (?,?)',(self.signer_address,'NONCE_ERROR'))
            if self.journal is not None:
                self.journal.event('NONCE_ERROR',self.clock_ms(),api_wallet=self.signer_address,pid=self.pid)

    def recover(self, clock_health, *, manually_verified=False):
        """An error latch survives restart; only explicit reviewed recovery clears it."""
        with self.lock:
            if not manually_verified or self.closed or os.getpid()!=self.pid or not clock_health.healthy:
                raise ExchangeError('NONCE_MANUAL_RECOVERY_REQUIRED')
            row=self.db.execute('SELECT last FROM nonces WHERE signer=?',(self.signer_address,)).fetchone()
            if row and row[0]-self.clock_ms()>self.max_future_ms:
                raise ExchangeError('NONCE_CLOCK_DRIFT')
            self.db.execute('DELETE FROM nonce_health WHERE signer=?',(self.signer_address,))
            if self.journal is not None:
                self.journal.event('NONCE_RECOVERED',self.clock_ms(),api_wallet=self.signer_address)

    def report(self):
        return dict(state='HEALTHY' if self.healthy else 'DEGRADED',owner=self.owner,closed=self.closed)

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()
                self.lease.close()


class ClockHealthMonitor:
    def __init__(self, *, clock_ms=None, monotonic_ms=None, max_skew_ms=2000, max_age_ms=30000, journal=None):
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.max_skew_ms = max_skew_ms
        self.max_age_ms = max_age_ms
        self.observed_ms = None
        self.wall_base = self.clock_ms()
        self.monotonic_base = self.monotonic_ms()
        self.offset_ms = None
        self.reason = 'CLOCK_REFERENCE_REQUIRED'
        self.journal=journal
        self._state=ClockState.WARNING
        self._confirmed=0
        self._last_reference=None
        self._recovery_required=False

    def _set(self,state,reason):
        if (state,reason)!=(self._state,self.reason) and self.journal is not None:
            self.journal.event('CLOCK_UNSAFE' if state==ClockState.UNSAFE else
                               'CLOCK_WARNING' if state==ClockState.WARNING else 'CLOCK_STATE_CHANGE',
                               self.clock_ms(),state=state.value,reason=reason,offset_ms=self.offset_ms)
        self._state,self.reason=state,reason

    def observe(self, server_ms, sent_ms, received_ms):
        self.state  # detect a wall jump before accepting a new baseline
        if any(type(x) is not int for x in (server_ms, sent_ms, received_ms)) or not 0 <= received_ms-sent_ms <= 2000:
            self._set(ClockState.WARNING,'CLOCK_REFERENCE_UNRELIABLE')
            self._recovery_required=True
            self._confirmed=0
            self.observed_ms = None
            return False
        self.offset_ms = server_ms - (sent_ms + received_ms) // 2
        self.observed_ms = received_ms
        self.wall_base = self.clock_ms()
        self.monotonic_base = self.monotonic_ms()
        if abs(self.offset_ms)>self.max_skew_ms:
            self._set(ClockState.UNSAFE,'CLOCK_SKEW')
            self._recovery_required=True
            self._confirmed=0
        else:
            if self._last_reference is None or server_ms>self._last_reference:
                self._confirmed+=1
            required=2 if self._recovery_required else 1
            if self._confirmed>=required:
                self._set(ClockState.HEALTHY,None)
                self._recovery_required=False
            else:
                self._set(ClockState.WARNING,'CLOCK_RECOVERY_CONFIRMATION_REQUIRED')
        self._last_reference=server_ms
        return self.healthy

    @property
    def state(self):
        now = self.clock_ms()
        jump=(now-self.wall_base)-(self.monotonic_ms()-self.monotonic_base)
        if abs(jump)>self.max_skew_ms:
            self._set(ClockState.UNSAFE,'CLOCK_BACKWARD_JUMP' if jump<0 else 'CLOCK_FORWARD_JUMP')
            self._recovery_required=True
            self._confirmed=0
            self._last_reference=None
        elif self.observed_ms is not None and not 0<=now-self.observed_ms<=self.max_age_ms:
            self._set(ClockState.WARNING,'CLOCK_REFERENCE_STALE')
            self._recovery_required=True
            self._confirmed=0
        return self._state

    @property
    def healthy(self):
        return self.state==ClockState.HEALTHY

    def report(self):
        return dict(state=self.state.value,reason=self.reason,offset_ms=self.offset_ms,
                    last_reference_ms=self.observed_ms,fresh_confirmations=self._confirmed)

    def require(self):
        if not self.healthy:
            raise ExchangeError('CLOCK_HEALTH_REQUIRED')


from .rate_limits import HyperliquidRateLimitManager


@dataclass(frozen=True)
class HumanLiveApproval:
    """Supplied only after separate human authorization and manual account review."""
    approval_id: str
    team_address: str
    signer_address: str
    expires_ms: int
    manually_verified: bool = False
    competition_market: str | None = None
    active_base_assets: tuple = ()
    network: str | None = None


class LiveAuthorization:
    def __init__(self, approval=None, *, clock_ms=None):
        self.approval = approval
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.revoked = False

    @property
    def venue_identity(self):
        from .venue_profiles import SCORED
        p = self.approval
        if (isinstance(p, HumanLiveApproval) and p.competition_market == 'pas' and
                p.active_base_assets == ('BTC', 'EWY') and p.network == 'testnet'):
            return SCORED.identity
        return None

    def require(self, team_address, signer_address):
        import venue_config
        from order_guard import OrderRoutingBlocked
        p = self.approval
        if (self.revoked or self.venue_identity is None or not isinstance(p, HumanLiveApproval) or not p.approval_id or
                p.manually_verified is not True or type(p.expires_ms) is not int or
                self.clock_ms() >= p.expires_ms or p.team_address.lower()!=team_address.lower() or
                p.signer_address.lower()!=signer_address.lower()):
            raise OrderRoutingBlocked('EXPLICIT_MANUAL_LIVE_AUTHORIZATION_REQUIRED')
        if (venue_config.TRADING_VENUE!='HYPERLIQUID_TESTNET' or
                venue_config.EXECUTION_MODE!='HYPERLIQUID_TESTNET_LIVE' or
                venue_config.ALLOW_LIVE_ORDERS is not True or
                os.environ.get('EXECUTION_MODE','')!='HYPERLIQUID_TESTNET_LIVE' or
                os.environ.get('ALLOW_LIVE_ORDERS','').lower()!='true' or
                os.environ.get('HL_NETWORK','testnet')!='testnet' or os.environ.get('HL_DEX','pas')!='pas' or os.environ.get('HL_COMPETITION_MARKET','pas').lower()!='pas' or
                os.environ.get('TRADING_VENUE','HYPERLIQUID_TESTNET')!='HYPERLIQUID_TESTNET'):
            raise OrderRoutingBlocked('LIVE_RUNTIME_CONFIGURATION_REQUIRED')

    def revoke(self):
        self.revoked = True
