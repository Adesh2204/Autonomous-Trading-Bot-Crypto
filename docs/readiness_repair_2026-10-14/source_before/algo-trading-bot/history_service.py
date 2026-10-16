"""Validated disk cache + cross-process priority/pacing budget for read-only history.

SQLite arbitration is shared by premarket_check and the regular runner. Lower
priority numbers win among queued requests; in-flight HTTP cannot be preempted.
No trading methods are exposed. Cache content is revalidated on EVERY read.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from collections import Counter
import fcntl
import hashlib
import json
import logging
import os
import random
import sqlite3
import time
import uuid
import pandas as pd
import config
from historical_data import HistoryContext, OHLCV, SCHEMA_VERSION, bounds, ist_timestamp, normalized_history, validate_history

PROTECTION, BOOTSTRAP, QUALIFICATION, MINIMUM_RVOL, OPTIONAL_RVOL = range(5)
logger=logging.getLogger(__name__)


def unavailable(reason):
    from premarket_screener import HistoricalDataUnavailable
    return HistoricalDataUnavailable(reason)


class SharedHistoryBudget:
    def __init__(self, path, *, clock=None, sleep=None, interval=None, per_minute=None, per_hour=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.sleep = clock or time.time, sleep or time.sleep
        self.interval = config.HISTORY_REQUEST_INTERVAL_SECONDS if interval is None else interval
        self.per_minute = config.HISTORY_REQUESTS_PER_MINUTE if per_minute is None else per_minute
        self.per_hour = config.HISTORY_REQUESTS_PER_HOUR if per_hour is None else per_hour
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS requests(ts REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS queue(id TEXT PRIMARY KEY, priority INTEGER, created REAL, expires REAL);
                CREATE TABLE IF NOT EXISTS limits(id INTEGER PRIMARY KEY, next_allowed REAL);
                INSERT OR IGNORE INTO limits VALUES(1,0);''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path, timeout=5.)
        try:
            with db:
                yield db
        finally:
            db.close()

    def acquire(self, priority, timeout=60.):
        ticket = str(uuid.uuid4())
        deadline = self.clock() + max(0., timeout)
        with self.connect() as db:
            db.execute('INSERT INTO queue VALUES(?,?,?,?)', (ticket, priority, self.clock(), deadline))
        try:
            while self.clock() < deadline:
                now = self.clock()
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('DELETE FROM queue WHERE expires<=?', (now,))
                    db.execute('DELETE FROM requests WHERE ts<=?', (now-3600,))
                    head = db.execute('SELECT id FROM queue ORDER BY priority, created, id LIMIT 1').fetchone()
                    next_allowed = db.execute('SELECT next_allowed FROM limits WHERE id=1').fetchone()[0]
                    recent = [r[0] for r in db.execute('SELECT ts FROM requests ORDER BY ts')]
                    minute = [t for t in recent if t > now-60]
                    if len(minute) >= self.per_minute:
                        next_allowed = max(next_allowed, minute[-self.per_minute]+60)
                    if len(recent) >= self.per_hour:
                        next_allowed = max(next_allowed, recent[-self.per_hour]+3600)
                    if head and head[0] == ticket and now >= next_allowed:
                        db.execute('INSERT INTO requests VALUES(?)', (now,))
                        db.execute('UPDATE limits SET next_allowed=? WHERE id=1', (now+self.interval,))
                        db.execute('DELETE FROM queue WHERE id=?', (ticket,))
                        return now
                wait = max(.01, min(.25, next_allowed-now))
                self.sleep(min(wait, max(0., deadline-self.clock())))
            raise unavailable('HISTORY_TIME_BUDGET_EXHAUSTED')
        finally:
            with self.connect() as db:
                db.execute('DELETE FROM queue WHERE id=?', (ticket,))

    def cooldown(self, seconds):
        with self.connect() as db:
            db.execute('UPDATE limits SET next_allowed=MAX(next_allowed,?) WHERE id=1', (self.clock()+seconds,))


class HistoryService:
    def __init__(self, broker, root=None, *, budget=None, clock=None):
        self.broker = broker
        self.root = Path(root or config.HISTORY_CACHE_DIR or Path(__file__).parent/'data'/'cache'/'history')
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        self.budget = budget or SharedHistoryBudget(self.root/'budget.sqlite3')
        self.metrics = Counter()
        self.calls = self.rate_limit_count = 0
        self.priority = QUALIFICATION
        self.deadline = self.clock()+config.DISCOVERY_HISTORY_MAX_RUNTIME_SECONDS

    def begin_optional_history(self):
        self.deadline = min(self.deadline, self.clock()+config.DISCOVERY_RVOL_MAX_RUNTIME_SECONDS)
        self.priority = MINIMUM_RVOL

    def cache_path(self, context):
        key = f'{context.exchange}:{context.token}:{context.timeframe}:{context.session_date}:v{SCHEMA_VERSION}'
        return self.root/(hashlib.sha256(key.encode()).hexdigest()+'.json')

    def _cached(self, context):
        path = self.cache_path(context)
        try:
            payload = json.loads(path.read_text())
            identity = [context.exchange, context.token, context.timeframe, str(context.session_date), SCHEMA_VERSION]
            if payload['identity'] != identity:
                return None
            frame = pd.DataFrame(payload['bars'])
            base = replace(context, start=None, end=None, require_complete=False)
            if not validate_history(frame, base).valid:
                return None
            frame = normalized_history(frame)
            start, end = bounds(context)
            # A provider's incomplete completed-session response is cached as such,
            # but an intraday partial cache must not masquerade as a full-day fetch.
            if ist_timestamp(payload['requested_start']) > start or ist_timestamp(payload['requested_end']) < end:
                return None
            sample = frame.loc[(frame.Timestamp >= start) & (frame.Timestamp <= end)].copy()
            validation = validate_history(sample, context)
            if not validation.valid:
                return None
            sample.attrs['validation'] = validation.report()
            return sample
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            return None

    def _store(self, frame, context, validation):
        path = self.cache_path(context)
        start, end = bounds(context)
        # Called under the per-session lock. Merge validated existing bars without
        # duplicating volume; preserve gaps and the exact requested coverage.
        try:
            old = json.loads(path.read_text())
            existing = pd.DataFrame(old['bars'])
            base = replace(context, start=None, end=None, require_complete=False)
            if validate_history(existing, base).valid:
                frame = pd.concat([normalized_history(existing), frame]).drop_duplicates('Timestamp',keep='last').sort_values('Timestamp')
                start, end = min(start,ist_timestamp(old['requested_start'])), max(end,ist_timestamp(old['requested_end']))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        payload = {'identity':[context.exchange,context.token,context.timeframe,str(context.session_date),SCHEMA_VERSION],
                   'provider':'ANGEL_ONE_SMARTAPI','fetched_at':ist_timestamp().isoformat(),
                   'requested_start':start.isoformat(),'requested_end':end.isoformat(),
                   'validation':validation.report(), 'row_count':len(frame),
                   'first_timestamp':str(frame.Timestamp.iloc[0]),'last_timestamp':str(frame.Timestamp.iloc[-1]),
                   'bars':json.loads(frame[OHLCV].to_json(orient='records',date_format='iso'))}
        temp = path.with_suffix(f'.{os.getpid()}.{uuid.uuid4().hex}.tmp')
        temp.write_text(json.dumps(payload,allow_nan=False))
        temp.replace(path)

    def fetch(self, context, *, priority=None, timeout=None):
        priority = self.priority if priority is None else priority
        timeout = max(0., self.deadline-self.clock()) if timeout is None else timeout
        deadline = self.clock()+timeout
        path = self.cache_path(context).with_suffix('.lock')
        with path.open('a') as lock:
            # Bounded single-flight per token/day; a crashed process releases flock.
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self.clock() >= deadline:
                        raise unavailable('HISTORY_TIME_BUDGET_EXHAUSTED')
                    self.budget.sleep(.05)
            cached = self._cached(context)
            if cached is not None:
                self.metrics['cache_hits'] += 1
                return cached
            self.metrics['cache_misses'] += 1
            consecutive_limits = 0
            for attempt in range(config.SCREEN_API_MAX_RETRIES):
                self.budget.acquire(priority, timeout=max(0.,deadline-self.clock()))
                start, end = bounds(context)
                params = {'exchange':context.exchange,'symboltoken':context.token,'interval':context.timeframe,
                          'fromdate':start.strftime('%Y-%m-%d %H:%M'),'todate':end.strftime('%Y-%m-%d %H:%M')}
                self.calls += 1
                self.metrics['requests'] += 1
                try:
                    response = self.broker.getCandleData(params)
                except Exception as exc:
                    response = {'status':False,'message':str(exc)}
                limited = any(t in str(response).lower() for t in ('exceeding access rate','rate limit','too many requests','ab1021'))
                if limited:
                    self.rate_limit_count += 1
                    consecutive_limits += 1
                    self.metrics['rate_limits'] += 1
                    delay = min(config.DISCOVERY_HISTORY_RATE_BACKOFF_MAX_SECONDS,
                                config.DISCOVERY_HISTORY_RATE_BACKOFF_SECONDS*2**(consecutive_limits-1))
                    self.budget.cooldown(delay+random.uniform(.1,.3))
                    if consecutive_limits >= config.DISCOVERY_HISTORY_MAX_CONSECUTIVE_RATE_LIMITS:
                        raise unavailable('HISTORY_RATE_LIMIT: consecutive rejection budget exhausted')
                elif isinstance(response,dict) and response.get('status') and response.get('data'):
                    try:
                        frame = pd.DataFrame(response['data'],columns=OHLCV)
                        validation = validate_history(frame,context)
                    except (ValueError, TypeError):
                        self.metrics['validation_failures'] += 1
                        return None
                    if not validation.valid:
                        self.metrics['validation_failures'] += 1
                        logger.warning('[HISTORY VALIDATION] %s %s reason=%s received=%s expected=%s',
                            context.symbol,context.session_date,validation.reason,validation.received_count,validation.expected_count)
                        return None
                    frame = normalized_history(frame)
                    self._store(frame,context,validation)
                    frame.attrs['validation'] = validation.report()
                    return frame
                elif isinstance(response,dict) and response.get('status') and response.get('data') == []:
                    self.metrics['empty_sessions'] += 1
                    return None  # completed empty session is not a transient transport failure
                else:
                    self.metrics['provider_failures'] += 1
                    code=response.get('errorcode') if isinstance(response,dict) else None
                    if isinstance(code,str) and code.isalnum():
                        self.metrics['provider_error_'+code] += 1
                    self.budget.cooldown(config.SCREEN_API_BACKOFF_BASE*2**attempt+random.uniform(.1,.3))
                self.metrics['retries'] += int(attempt+1 < config.SCREEN_API_MAX_RETRIES)
            if consecutive_limits:
                raise unavailable('HISTORY_RATE_LIMIT: request retry budget exhausted')
            return None
