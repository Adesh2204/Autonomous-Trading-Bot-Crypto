"""Native public candle observations. Measures availability, never creates bars.

Reception minus close is an observation-delay estimate, not an exchange-side
publication timestamp. Startup history is left-censored; absent live intervals
are right-censored. Scanner decisions and the existing health gates remain truth.
"""
from collections import Counter
from copy import deepcopy
import math
import threading

from .base_exchange import ExchangeError
from .market_health import validate_history

MINUTE = 60000


def sequence_lengths(timestamps):
    longest = tail = 0
    previous = None
    for t in sorted(set(timestamps)):
        tail = tail + 1 if previous is not None and t - previous == MINUTE else 1
        longest = max(longest, tail)
        previous = t
    return longest, tail


def distribution(values):
    values = sorted(values)
    def percentile(p):
        if not values:
            return None
        index = (len(values) - 1) * p
        lo, hi = math.floor(index), math.ceil(index)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return dict(observation_count=len(values), median_ms=percentile(.5),
        p90_ms=percentile(.9), p95_ms=percentile(.95), p99_ms=percentile(.99),
        max_ms=max(values) if values else None,
        sufficient_for_adaptive_retry=len(values) >= 20,
        basis='LOCAL_FIRST_COMPLETED_RECEPTION_MINUS_LOGICAL_CLOSE; NETWORK_AND_POLLING_NOT_SEPARABLE')


class CandleAvailabilityMonitor:
    def __init__(self, symbols, *, clock_ms, history_bars=300, retained_intervals=5000):
        self.symbols = tuple(symbols)
        if (not self.symbols or len(set(self.symbols)) != len(self.symbols) or
                any(not s.startswith('par:') for s in self.symbols)):
            raise ExchangeError('AVAILABILITY_PAR_UNIVERSE_REQUIRED')
        self.clock_ms = clock_ms
        self.started_ms = clock_ms()
        self.history_bars = history_bars
        self.retained_intervals = retained_intervals
        if (type(history_bars) is not int or type(retained_intervals) is not int or
                not 1<=history_bars<=retained_intervals<=5000):
            raise ExchangeError('AVAILABILITY_RETENTION_INVALID')
        self.lock = threading.RLock()
        self.rows = {s: {} for s in self.symbols}
        self.requests = {s: [] for s in self.symbols}
        self.errors = {s: Counter() for s in self.symbols}
        self.recoveries = {s: dict(attempts=0, failures=0, consecutive_failures=0,
            recovered_missing=0, last_success_ms=None, pending=False, deferred_reason=None,
            events=[]) for s in self.symbols}
        self.strategy = {}
        self.cache = {}
        self.health = {}

    def _require(self, symbol):
        if symbol not in self.rows:
            raise ExchangeError('AVAILABILITY_MARKET_IDENTITY_MISMATCH')

    def _row(self, symbol, t):
        self._require(symbol)
        row = self.rows[symbol].setdefault(t, dict(timestamp_ms=t,
            expected_close_ms=t + MINUTE, exchange_publication_timestamp_ms=None,
            first_observed_at_ms=None, sources={}, rejected=[], conflict=False,
            missing_first_observed_ms=None, rest_absent_count=0))
        return row

    def _prune(self, symbol, now):
        cutoff = now // MINUTE * MINUTE - self.retained_intervals * MINUTE
        self.rows[symbol] = {t:r for t,r in self.rows[symbol].items()
            if cutoff <= t <= now // MINUTE * MINUTE}

    def observe_candle(self, candle, source, received_ms):
        if source not in {'REST', 'WS'}:
            raise ExchangeError('NATIVE_SOURCE_REQUIRED')
        with self.lock:
            r = self._row(candle.symbol, candle.timestamp_ms)
            if r['first_observed_at_ms'] is None:
                r['first_observed_at_ms'] = received_ms
            # Decimal equality preserves equivalent encodings such as 1/1.00.
            facts = tuple(getattr(candle, k) for k in ('open','high','low','close','volume'))
            complete = candle.timestamp_ms + MINUTE <= received_ms
            old = r['sources'].get(source)
            if old is None:
                old = r['sources'][source] = dict(first_observed_at_ms=received_ms,
                    first_completed_observed_at_ms=None, last_observed_at_ms=received_ms,
                    observations=0, duplicates=0, latest_facts=None, completed_facts=None)
            if old['latest_facts'] == facts:
                old['duplicates'] += 1
            if complete:
                for other in r['sources'].values():
                    if other['completed_facts'] is not None and other['completed_facts'] != facts:
                        r['conflict'] = True
                if old['first_completed_observed_at_ms'] is None:
                    old['first_completed_observed_at_ms'] = received_ms
                    old['completed_facts'] = facts
                    if source == 'REST' and r['missing_first_observed_ms'] is not None:
                        self.recoveries[candle.symbol]['recovered_missing'] += 1
                    if r['missing_first_observed_ms'] is not None and received_ms > r['missing_first_observed_ms']:
                        r['availability_classification']='CANDLE_PUBLICATION_DELAYED'
            old.update(last_observed_at_ms=received_ms, latest_facts=facts,
                observations=old['observations'] + 1)
            self._prune(candle.symbol, received_ms)

    def reject(self, symbol, reason, *, timestamp_ms=None, source=None):
        with self.lock:
            self._require(symbol)
            self.errors[symbol][reason] += 1
            if type(timestamp_ms) is int and timestamp_ms % MINUTE == 0:
                r = self._row(symbol, timestamp_ms)
                r['rejected'] = (r['rejected'] + [dict(reason=reason, source=source,
                    observed_at_ms=self.clock_ms())])[-10:]
                if 'CONFLICT' in reason:
                    r['conflict'] = True
                self._prune(symbol,self.clock_ms())

    def observe_rest(self, symbol, start_ms, end_ms, raw, parse, received_ms, as_of_ms, *, role=None):
        """Wire-derived observations are separate from cache/scanner acceptance."""
        self._require(symbol)
        valid = []; seen = set(); rejected = 0
        if not isinstance(raw, list):
            self.reject(symbol, 'INVALID_CANDLE_RESPONSE', source='REST')
            return
        for row in raw:
            try:
                c = parse(row, symbol, '1m')
                if not start_ms <= c.timestamp_ms <= end_ms:
                    raise ExchangeError('CANDLE_OUTSIDE_REQUESTED_RANGE')
                if c.timestamp_ms > as_of_ms:
                    raise ExchangeError('FUTURE_REST_CANDLE')
                self.observe_candle(c, 'REST', received_ms)
                if c.timestamp_ms + MINUTE <= as_of_ms:
                    valid.append(c); seen.add(c.timestamp_ms)
            except (ExchangeError, ValueError, TypeError) as exc:
                rejected += 1
                self.reject(symbol, str(exc), timestamp_ms=row.get('t') if isinstance(row,dict) else None, source='REST')
        with self.lock:
            expected = range((start_ms + MINUTE - 1) // MINUTE * MINUTE,
                min(end_ms // MINUTE * MINUTE, as_of_ms // MINUTE * MINUTE - MINUTE) + 1, MINUTE)
            for t in expected:
                if t not in seen:
                    r = self._row(symbol, t)
                    if r['missing_first_observed_ms'] is None:
                        r['missing_first_observed_ms'] = received_ms
                    r['rest_absent_count'] += 1
            self.requests[symbol] = (self.requests[symbol] + [dict(start_ms=start_ms,
                end_ms=end_ms, received_ms=received_ms, as_of_ms=as_of_ms,
                raw_count=len(raw), valid_completed_count=len(seen), rejected_count=rejected,
                expected_count=len(expected), missing_count=len(expected) - len(seen), role=role)])[-40:]
            if role == 'SCANNER':
                reason = None
                bars = sorted({c.timestamp_ms:c for c in valid}.values(), key=lambda c:c.timestamp_ms)
                try:
                    if rejected:
                        raise ExchangeError('CANDLE_REJECTED_BY_VALIDATOR')
                    if any(self.rows[symbol][c.timestamp_ms]['conflict'] for c in bars):
                        raise ExchangeError('CANDLE_MERGE_CONFLICT')
                    validate_history(symbol, bars, as_of_ms, self.history_bars)
                    if not 0 <= as_of_ms - (bars[-1].timestamp_ms + MINUTE) <= 120000:
                        raise ExchangeError('COMPLETED_CANDLE_STALE')
                except (ExchangeError, ValueError, TypeError) as exc:
                    reason = str(exc)
                self.strategy[symbol] = dict(observed_ms=received_ms, as_of_ms=as_of_ms,
                    requested_start_ms=start_ms, requested_end_ms=end_ms,
                    completed_count=len(bars), requested_interval_count=len(expected),
                    requested_window_missing_count=len(expected) - len(seen),
                    last_close_ms=bars[-1].timestamp_ms + MINUTE if bars else None,
                    history_gate_passed=reason is None, reason=reason,
                    scope='ACTUAL_SCANNER_REST_INPUT; FROZEN_VALIDATION; NOT_SIGNAL_OR_ADMISSION')
            self._prune(symbol, received_ms)

    def update_cache(self, symbol, candles, now_ms, health):
        with self.lock:
            self._require(symbol)
            self.cache[symbol] = sorted({c.timestamp_ms for c in candles if c.timestamp_ms + MINUTE <= now_ms})
            self.health[symbol] = deepcopy(health)

    def recovery_begin(self, symbol, now_ms):
        with self.lock:
            r = self.recoveries[symbol]
            r.update(pending=True, attempts=r['attempts'] + 1, started_ms=now_ms,
                recovered_before=r['recovered_missing'], deferred_reason=None)
            last=now_ms//MINUTE*MINUTE-MINUTE
            r['cache_missing_before']=sorted(set(range(last-(self.history_bars-1)*MINUTE,last+1,MINUTE))-
                set(self.cache.get(symbol,[])))

    def recovery_finish(self, symbol, now_ms, error=None):
        with self.lock:
            r = self.recoveries[symbol]
            health = self.health.get(symbol, {})
            success = not error and health.get('healthy') is True
            r.update(pending=False, consecutive_failures=0 if success else r['consecutive_failures'] + 1)
            if not success:
                r['failures'] += 1
            else:
                r['last_success_ms'] = now_ms
            if error and any(x in str(error).upper() for x in ('BUDGET','RATE','DEADLINE')):
                r['deferred_reason'] = 'RATE_BUDGET_RECOVERY_DEFERRED'
            event = dict(started_ms=r.get('started_ms'), finished_ms=now_ms, success=success,
                error=str(error) if error else None, health_reasons=health.get('reasons',[]),
                recovered_missing=r['recovered_missing'] - r.get('recovered_before',r['recovered_missing']))
            event['cache_holes_filled']=len(set(r.get('cache_missing_before',[]))&set(self.cache.get(symbol,[])))
            event['cache_holes_scope']='GENUINE_CACHE_ADMISSIONS_DURING_RECOVERY; REST_VS_WS_CAUSALITY_NOT_ASSUMED; INCLUDES_WARMUP'
            r['events'] = (r['events'] + [event])[-40:]
            return deepcopy(event)

    def _latency(self, symbol, now):
        rows = self.rows[symbol]
        live = [r for t,r in rows.items() if self.started_ms < t + MINUTE <= now]
        out = {}
        for source in ('REST','WS'):
            values = [r['sources'][source]['first_completed_observed_at_ms'] - r['expected_close_ms']
                for r in live if source in r['sources'] and
                r['sources'][source]['first_completed_observed_at_ms'] is not None]
            out[source] = distribution(values)
            out[source]['never_observed_intervals'] = len(live) - len(values)
        out['left_censored_startup_intervals'] = sum(t + MINUTE <= self.started_ms for t in rows)
        out['right_censored_live_intervals'] = sum(not any(v['first_completed_observed_at_ms'] is not None
            for v in r['sources'].values()) for r in live)
        out['first_observed_through_ws'] = sum(r['sources'].get('WS',{}).get('first_completed_observed_at_ms') is not None and
            (r['sources'].get('REST',{}).get('first_completed_observed_at_ms') is None or
             r['sources']['WS']['first_completed_observed_at_ms'] < r['sources']['REST']['first_completed_observed_at_ms']) for r in live)
        return out

    def retry_hint_ms(self, symbol):
        with self.lock:
            stats = self._latency(symbol, self.clock_ms())['REST']
            if not stats['sufficient_for_adaptive_retry']:
                return None
            return min(300000, max(30000, int(stats['p95_ms'])))

    def prioritize(self, symbols, health_records):
        # Old due deadlines lead: near-ready preference only within a 30s cohort.
        # Every selected symbol is still processed by the same single worker.
        with self.lock:
            return tuple(sorted(symbols, key=lambda s:(health_records[s]['next_retry_at_ms']//30000,
                self.history_bars - min(self.history_bars,len(self.cache.get(s,[]))),
                health_records[s]['next_retry_at_ms'],s)))

    def snapshot(self, *, now_ms=None, include_records=False):
        now = self.clock_ms() if now_ms is None else now_ms
        with self.lock:
            out = {}
            last = now // MINUTE * MINUTE - MINUTE
            expected = list(range(last - (self.history_bars - 1) * MINUTE, last + 1, MINUTE))
            for s in self.symbols:
                for t in expected:
                    r = self._row(s,t)
                    if not any(v['first_completed_observed_at_ms'] is not None for v in r['sources'].values()) and r['missing_first_observed_ms'] is None:
                        r['missing_first_observed_ms'] = now
                self._prune(s,now)
                cache = self.cache.get(s,[]); present = set(cache) & set(expected)
                missing = sorted(set(expected) - present)
                reasons = {}
                requests = self.requests[s]
                for t in missing:
                    r = self.rows[s][t]; classifications = []
                    if r['conflict']: classifications.append('CANDLE_MERGE_CONFLICT')
                    if r['rejected']: classifications.append('CANDLE_REJECTED_BY_VALIDATOR')
                    if any(v['first_completed_observed_at_ms'] is not None for v in r['sources'].values()):
                        classifications.append('CANDLE_CACHE_MISSING')
                    elif r['rest_absent_count']:
                        classifications.append('CANDLE_ABSENT_IN_COVERED_REST_RESPONSE')
                    elif requests:
                        classifications.append('REST_REQUEST_WINDOW_INCOMPLETE')
                    else: classifications.append('CANDLE_NOT_YET_OBSERVED')
                    if not r['sources']:classifications.append('CAUSE_UNDETERMINED')
                    if self.started_ms < t + MINUTE <= now and 'WS' not in r['sources']:
                        classifications.append('WEBSOCKET_EVENT_NOT_OBSERVED')
                    if self.recoveries[s]['deferred_reason']:
                        classifications.append(self.recoveries[s]['deferred_reason'])
                    reasons[str(t)] = classifications
                longest, tail = sequence_lengths(cache)
                h = self.health.get(s,{})
                strategy = deepcopy(self.strategy.get(s,{}))
                current_strategy = bool(strategy.get('history_gate_passed') and
                    strategy.get('last_close_ms') is not None and
                    0 <= now - strategy['last_close_ms'] <= 120000)
                out[s] = dict(trusted_local_timestamp_ms=now,
                    exchange_current_timestamp_ms=None, expected_last_completed_start_ms=last,
                    expected_last_completed_close_ms=last + MINUTE, expected_bars=self.history_bars,
                    present=len(present), missing=len(missing), missing_timestamps_ms=missing,
                    missing_classifications=reasons, longest_uninterrupted_sequence=longest,
                    contiguous_valid_tail=tail, valid_completed_held=len(cache),
                    history_classifications=[] if tail>=self.history_bars else ['INSUFFICIENT_CONTIGUOUS_HISTORY'],
                    latest_genuine_observed_start_ms=max((t for t,r in self.rows[s].items() if r['sources']),default=None),
                    last_completed_close_age_ms=now - (cache[-1]+MINUTE) if cache else None,
                    strategy_history=strategy, strategy_history_current=current_strategy,
                    eligible_for_scanner_evaluation=bool(h.get('healthy') and current_strategy),
                    authoritative_market_healthy=h.get('healthy',False),
                    quarantine_reason=h.get('reasons',['MARKET_HEALTH_UNKNOWN']),
                    status=h.get('state','UNKNOWN'), next_recovery_at_ms=h.get('next_retry_at_ms'),
                    latency=self._latency(s,now), recovery=deepcopy(self.recoveries[s]),
                    duplicates=sum(v['duplicates'] for r in self.rows[s].values() for v in r['sources'].values()),
                    conflicting_intervals=sum(r['conflict'] for r in self.rows[s].values()),
                    malformed_candles=dict(self.errors[s]), rest_observation_history=deepcopy(requests),
                    delayed_intervals=sum(r['missing_first_observed_ms'] is not None and any(
                        v['first_completed_observed_at_ms'] is not None and v['first_completed_observed_at_ms'] > r['missing_first_observed_ms']
                        for v in r['sources'].values()) for r in self.rows[s].values()))
                if include_records:
                    out[s]['interval_observations'] = deepcopy(self.rows[s])
            return dict(provenance='NATIVE_PAR_PUBLIC_OBSERVATIONS_ONLY', network='testnet',dex='par',
                observed_at_ms=now, observation_started_ms=self.started_ms,
                retention_intervals=self.retained_intervals, markets=out,
                publication_timestamp_scope='UNAVAILABLE; OBSERVATION_DELAYS_ONLY',
                readiness_scope='MONITOR DOES NOT AUTHORIZE ORDERS OR REPLACE SCANNER DECISIONS')
