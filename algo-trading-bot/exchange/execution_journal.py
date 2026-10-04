"""Durable intent and account evidence. No signer, signature or key is stored."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading

from .base_exchange import ExchangeError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def safe_reason(value):
    """Never echo credential-shaped values supplied in remote errors."""
    text = str(value)
    text = re.sub(r'0x[0-9a-fA-F]{64}\b', '[REDACTED]', text)
    text = re.sub(r'\b[0-9a-fA-F]{64}\b', '[REDACTED]', text)
    text = re.sub(r'(?i)(private[_ ]?key|seed|secret|signature|authorization)\s*[:=]\s*\S+',
                  r'\1=[REDACTED]', text)
    return text[:1000]


def safe_data(value):
    if isinstance(value, dict):
        forbidden = {'signature', 'private_key', 'api_wallet_private_key', 'seed',
                     'seed_phrase', 'signer', 'authorization', 'secret'}
        public_hash_fields={'metadata_hash','expected_metadata_hash','working_source_hash',
                            'configuration_hash','strategy_source_hash','event_hash'}
        return {k: v if k in public_hash_fields and isinstance(v,str) and re.fullmatch(r'(0x)?[0-9a-fA-F]{64}',v)
                else safe_data(v) for k, v in value.items() if k.lower() not in forbidden}
    if isinstance(value, (list, tuple)):
        return [safe_data(v) for v in value]
    return safe_reason(value) if isinstance(value, str) else value


class ExecutionJournal:
    def __init__(self, path, *, session_id, team_address):
        if not session_id or not re.fullmatch(r'0x[0-9a-fA-F]{40}', team_address):
            raise ExchangeError('JOURNAL_IDENTITY_REQUIRED')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.team_address = team_address.lower()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS identity (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intents (
          intent_key TEXT PRIMARY KEY, cloid TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
          request TEXT NOT NULL, candidate TEXT NOT NULL, state TEXT NOT NULL,
          oid TEXT, outcome TEXT, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp_ms INTEGER NOT NULL,
          kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS management (symbol TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS account_checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS controls (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signed_management (
          id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
          action TEXT NOT NULL, state TEXT NOT NULL, created_ms INTEGER NOT NULL,
          updated_ms INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS recovery_snapshots (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, checksum TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS opportunity_traces (candidate TEXT PRIMARY KEY,data TEXT NOT NULL);
        ''')
        with self.transaction():
            identity = dict(self.db.execute('SELECT name,value FROM identity'))
            expected = {'session': session_id, 'team': self.team_address, 'venue': 'testnet:par'}
            if identity and identity != expected:
                raise ExchangeError('JOURNAL_ACCOUNT_OR_SESSION_MISMATCH')
            self.db.executemany('INSERT OR IGNORE INTO identity VALUES (?,?)', expected.items())

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def reserve(self, intent_key, request, candidate, now_ms, *, position_guard=None, position_generation=None):
        if not isinstance(intent_key, str) or not intent_key or not candidate:
            raise ExchangeError('TRACEABLE_INTENT_REQUIRED')
        fp = fingerprint(request)
        cloid = '0x' + fingerprint([self.team_address, self.session_id, candidate,
                                  request.get('strategy_id'), intent_key])[:32]
        with self.transaction():
            prior = self.db.execute('SELECT * FROM intents WHERE intent_key=?', (intent_key,)).fetchone()
            if prior:
                if prior['fingerprint'] != fp or prior['candidate'] != candidate:
                    raise ExchangeError('CLOID_INTENT_CONFLICT')
                return dict(prior), False
            if position_guard is not None and not request.get('reduce_only'):
                position_guard.reserve_in_transaction(intent_key, request, now_ms,
                                                       expected_generation=position_generation)
            self.db.execute('INSERT INTO intents VALUES (?,?,?,?,?,?,?,?,?,?)',
                (intent_key, cloid, fp, canonical(request), candidate, 'PREPARED', None,
                 None, now_ms, now_ms))
        return self.intent(intent_key), True

    def intent(self, key):
        with self.lock:
            row = self.db.execute('SELECT * FROM intents WHERE intent_key=?', (key,)).fetchone()
            return dict(row) if row else None

    def intents(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM intents ORDER BY created_ms,intent_key')]

    def update(self, key, state, now_ms, *, oid=None, outcome=None):
        with self.transaction():
            if self.db.execute('UPDATE intents SET state=?,oid=COALESCE(?,oid),outcome=?,updated_ms=? '
                               'WHERE intent_key=?', (state, oid, canonical(safe_data(outcome)) if outcome else None,
                                                     now_ms, key)).rowcount != 1:
                raise ExchangeError('UNKNOWN_DURABLE_INTENT')

    def event(self, kind, now_ms, **data):
        from .event_timing import timing
        data=dict(timing(now_ms),**data)
        with self.transaction():
            self.db.execute('INSERT INTO events(timestamp_ms,kind,data) VALUES (?,?,?)',
                            (now_ms, kind, canonical(safe_data(data))))

    def save_management(self, symbol, data):
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO management VALUES (?,?)',
                            (symbol, canonical(safe_data(data))))

    def management(self):
        return {r['symbol']: json.loads(r['data']) for r in self.db.execute('SELECT * FROM management')}

    def checkpoint(self, data=None):
        if data is not None:
            with self.transaction():
                self.db.execute('INSERT OR REPLACE INTO account_checkpoint VALUES (1,?)', (canonical(safe_data(data)),))
        row = self.db.execute('SELECT data FROM account_checkpoint WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def recovery_snapshot(self):
        with self.lock:
            row=self.db.execute('SELECT * FROM recovery_snapshots ORDER BY seq DESC LIMIT 1').fetchone()
            if row is None:
                return None
            try:
                value=json.loads(row['data'])
                if fingerprint(value)!=row['checksum'] or value['schema_version']!=1:
                    raise ValueError()
                if value['team_address']!=self.team_address or value['venue']!='testnet:par':
                    raise ValueError()
                return value
            except (ValueError,KeyError,TypeError):
                raise ExchangeError('RECOVERY_CHECKPOINT_CORRUPT') from None

    def save_recovery_snapshot(self, account_data, management, evidence):
        value=safe_data(dict(schema_version=1,team_address=self.team_address,venue='testnet:par',
            session_id=self.session_id,account=account_data,management=management,
            orders=self.intents(),signed_management=self.management_actions(),**evidence))
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO account_checkpoint VALUES (1,?)',(canonical(safe_data(account_data)),))
            self.db.executemany('INSERT OR REPLACE INTO management VALUES (?,?)',
                               [(s,canonical(safe_data(m))) for s,m in management.items()])
            self.db.execute('INSERT INTO recovery_snapshots(data,checksum) VALUES (?,?)',(canonical(value),fingerprint(value)))
            if value.get('lifecycle') is not None:
                self.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                                ('recovery_lifecycle',canonical(value['lifecycle'])))
            # Retain the previous complete checkpoint; never silently adopt a
            # corrupt latest record as healthy, even when a previous one exists.
            self.db.execute('DELETE FROM recovery_snapshots WHERE seq NOT IN '
                            '(SELECT seq FROM recovery_snapshots ORDER BY seq DESC LIMIT 2)')
        return value

    def control(self, name, value=None):
        if value is not None:
            with self.transaction():
                self.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(name,canonical(safe_data(value))))
        row=self.db.execute('SELECT value FROM controls WHERE name=?',(name,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self):
        self.db.close()

    def reserve_management(self,action,now_ms):
        fp=fingerprint(action)
        with self.transaction():
            if self.db.execute("SELECT id FROM signed_management WHERE fingerprint=? AND state='UNKNOWN'",(fp,)).fetchone():
                raise ExchangeError('MANAGEMENT_UNCERTAINTY_RECOVERY_REQUIRED')
            cursor=self.db.execute('INSERT INTO signed_management(fingerprint,action,state,created_ms,updated_ms) '
                'VALUES (?,?,?,?,?)',(fp,canonical(safe_data(action)),'UNKNOWN',now_ms,now_ms))
            return cursor.lastrowid

    def pending_management(self,action):
        return self.db.execute("SELECT id FROM signed_management WHERE fingerprint=? AND state='UNKNOWN'",
                               (fingerprint(action),)).fetchone() is not None

    def update_management(self,action_id,state,now_ms):
        with self.transaction():
            if self.db.execute('UPDATE signed_management SET state=?,updated_ms=? WHERE id=?',
                               (state,now_ms,action_id)).rowcount!=1:
                raise ExchangeError('UNKNOWN_MANAGEMENT_ACTION')

    def management_actions(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM signed_management ORDER BY id')]
