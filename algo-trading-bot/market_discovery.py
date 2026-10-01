"""Cheap direction-neutral Stage 1. Never imports or calls strategy signals."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
import logging
import math
import time

import config
from execution_safety import InstrumentIdentity, SafetyError
from market_universe import MarketUniverse, normalize_symbol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketSnapshot:
    session_date: date
    source: str
    source_timestamp: datetime
    available_at: datetime
    records: list[dict]
    checksum: str = ''
    cache_hit: bool = False
    schema_version: str = 'NSE_CM_UDIFF_V1'


@dataclass
class DiscoveryCandidate:
    instrument: InstrumentIdentity
    previous_close: float
    previous_high: float
    previous_low: float
    total_volume: int
    turnover: float
    daily_range_pct: float
    discovery_score: float = 0.
    discovery_rank: int = 0

    @property
    def symbol(self):
        return self.instrument.symbol

    def screening_record(self, session, source):
        identity = self.instrument
        return {'symbol': identity.symbol, 'trading_symbol': identity.trading_symbol,
            'token': identity.token, 'exchange': identity.exchange, 'instrument': identity,
            'discovery_lineage': {'instrument_source': source, 'instrument_token': identity.token,
                'discovery_session': session.isoformat(), 'discovery_rank': self.discovery_rank,
                'discovery_score': self.discovery_score}}


@dataclass(frozen=True)
class DiscoveryRejection:
    symbol: str
    reason: str


@dataclass
class MarketDiscoveryResult:
    session_date: date
    raw_instrument_count: int = 0
    eligible_equity_count: int | None = None
    snapshot_record_count: int = 0
    coarse_qualified_count: int = 0
    ranked_candidates: list[DiscoveryCandidate] = field(default_factory=list)
    selected_candidates: list[DiscoveryCandidate] = field(default_factory=list)
    rejected_candidates: list[DiscoveryRejection] = field(default_factory=list)
    universe_source: str = 'DYNAMIC_NSE_DISCOVERY'
    success: bool = False
    failure_reason: str | None = None
    data_source: str = ''
    data_checksum: str = ''
    available_at: str = ''
    cache_hit: bool = False
    elapsed_seconds: float = 0.
    request_counts: dict = field(default_factory=dict)
    instrument_source: str = ''
    resolved_intraday_eq_count: int = 0
    equity_classification_verified: bool = False
    missing_snapshot_count: int = 0
    snapshot_coverage_pct: float = 0.
    datasets: dict = field(default_factory=dict)

    def screening_universe(self):
        return [c.screening_record(self.session_date, self.instrument_source)
                for c in self.selected_candidates]

    def report(self):
        data = asdict(self)
        data['session_date'] = self.session_date.isoformat()
        return data


def discover_nse_candidates(universe: MarketUniverse, snapshot: MarketSnapshot,
                            target_session: date, decision_time: datetime):
    started = time.perf_counter()
    result = MarketDiscoveryResult(target_session, universe.raw_instrument_count,
        universe.eligible_equity_count, len(snapshot.records), data_source=snapshot.source,
        data_checksum=snapshot.checksum, available_at=snapshot.available_at.isoformat(),
        cache_hit=snapshot.cache_hit, instrument_source=';'.join(universe.sources) or 'BROKER_MASTER')
    result.resolved_intraday_eq_count = universe.eligible_equity_count
    result.equity_classification_verified = universe.equity_classification_verified
    try:
        if not universe.equity_classification_verified:
            raise SafetyError('EQUITY_CLASSIFICATION_UNVERIFIED')
        if snapshot.session_date != target_session:
            raise SafetyError('CACHE_SESSION_MISMATCH')
        from market_schedule import get_market_schedule
        schedule = get_market_schedule('NSE')
        close = datetime.combine(target_session, schedule.market_close_time, tzinfo=schedule.timezone)
        if (target_session >= schedule.localize(decision_time).date() or not snapshot.source or
                any(t.tzinfo is None for t in (snapshot.source_timestamp, snapshot.available_at, decision_time)) or
                not close <= snapshot.source_timestamp <= snapshot.available_at <= decision_time):
            raise SafetyError('LOOKAHEAD_OR_INVALID_AVAILABILITY')
        by_symbol = {}
        duplicates = set()
        for row in snapshot.records:
            if not isinstance(row, dict):
                result.rejected_candidates.append(DiscoveryRejection('', 'SCHEMA_VALIDATION_FAILED'))
                continue
            symbol = normalize_symbol(row.get('symbol'))
            if str(row.get('series', '')).strip().upper() != 'EQ':
                result.rejected_candidates.append(DiscoveryRejection(symbol, 'INVALID_SERIES'))
                continue
            if symbol in by_symbol:
                duplicates.add(symbol)
            by_symbol[symbol] = row
        excluded = {normalize_symbol(s) for s in config.EXCLUSION_LIST}
        for identity in universe.instruments:
            symbol = identity.symbol
            reasons = []
            row = by_symbol.get(symbol)
            if symbol in duplicates:
                reasons.append('DUPLICATE_MARKET_RECORD')
            if symbol in excluded:
                reasons.append('EXCLUDED_SYMBOL')
            if row is None:
                result.missing_snapshot_count += 1
                reasons.append('DATA_SOURCE_ERROR: missing snapshot row')
            if not reasons:
                try:
                    identity.validate(symbol, now=decision_time)
                    if row.get('market_date') != target_session.isoformat():
                        raise SafetyError('CACHE_SESSION_MISMATCH')
                    close, high, low = (float(row[k]) for k in ('close', 'high', 'low'))
                    if any(isinstance(row[k], bool) for k in ('close', 'high', 'low')) or not all(
                            math.isfinite(v) and v > 0 for v in (close, high, low)):
                        raise SafetyError('INVALID_CLOSE_OR_OHLC')
                    if not low <= close <= high:
                        raise SafetyError('INVALID_OHLC')
                    volume_value = row.get('volume')
                    if isinstance(volume_value, bool) or volume_value is None:
                        raise SafetyError('MISSING_VOLUME')
                    volume = float(volume_value)
                    if not math.isfinite(volume) or volume < 0 or not volume.is_integer():
                        raise SafetyError('INVALID_VOLUME')
                    turnover = float(row['turnover'])
                    if isinstance(row['turnover'], bool) or not math.isfinite(turnover) or turnover <= 0:
                        raise SafetyError('INVALID_TURNOVER')
                    if close < config.SCREEN_MIN_LTP:
                        reasons.append('PRICE_BELOW_DISCOVERY_MIN')
                    if close > config.SCREEN_MAX_LTP:
                        reasons.append('PRICE_ABOVE_DISCOVERY_MAX')
                    if volume < config.SCREEN_MIN_DAILY_VOLUME:
                        reasons.append('VOLUME_BELOW_DISCOVERY_MIN')
                    if not reasons:
                        result.ranked_candidates.append(DiscoveryCandidate(identity, close, high, low,
                            int(volume), turnover, (high - low) / close))
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    reasons.append(str(exc) if isinstance(exc, SafetyError) else 'SCHEMA_VALIDATION_FAILED')
            for reason in reasons:
                result.rejected_candidates.append(DiscoveryRejection(symbol, reason))
                logger.debug('[DISCOVERY FILTER] %s | %s', symbol, reason)
        ranked = result.ranked_candidates
        if ranked:
            max_range = max(c.daily_range_pct for c in ranked) or 1.
            max_volume = max(c.total_volume for c in ranked) or 1
            max_turnover = max(c.turnover for c in ranked) or 1.
            for candidate in ranked:
                candidate.discovery_score = (candidate.daily_range_pct / max_range +
                    candidate.total_volume / max_volume + candidate.turnover / max_turnover) / 3.
            ranked.sort(key=lambda c: (-c.discovery_score, -c.daily_range_pct, -c.total_volume, c.symbol))
            for rank, candidate in enumerate(ranked, 1):
                candidate.discovery_rank = rank
        result.coarse_qualified_count = len(ranked)
        result.snapshot_coverage_pct = ((universe.eligible_equity_count - result.missing_snapshot_count) /
            universe.eligible_equity_count * 100. if universe.eligible_equity_count else 0.)
        result.selected_candidates = ranked[:config.MAX_DISCOVERY_CANDIDATES]
        result.success = True  # A valid empty scan is not an infrastructure failure.
    except (SafetyError, TypeError, ValueError) as exc:
        result.failure_reason = str(exc)
        logger.warning('[DISCOVERY] DYNAMIC_DISCOVERY_FAILED | %s', exc)
    result.elapsed_seconds = time.perf_counter() - started
    logger.info('[DISCOVERY] session=%s raw=%s eligible=%s coarse=%s top=%s success=%s elapsed=%.4fs',
        target_session, result.raw_instrument_count, result.eligible_equity_count,
        result.coarse_qualified_count, len(result.selected_candidates), result.success, result.elapsed_seconds)
    for candidate in result.selected_candidates:
        logger.info('[DISCOVERY RANK] %02d | %s | range=%.4f | volume=%s | score=%.6f',
            candidate.discovery_rank, candidate.symbol, candidate.daily_range_pct,
            candidate.total_volume, candidate.discovery_score)
    return result
