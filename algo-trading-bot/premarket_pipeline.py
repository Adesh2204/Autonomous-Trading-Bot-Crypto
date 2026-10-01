"""One startup path: market discovery -> unchanged deep screener -> Phase 5."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import logging
from pathlib import Path
import time

import config
from discovery_data import DiscoveryDataSource, atomic_json
from execution_safety import SafetyError
from market_discovery import MarketDiscoveryResult, discover_nse_candidates
from market_schedule import get_market_schedule
from market_universe import build_market_universe, load_master_envelope
from premarket_screener import (HistoricalDataUnavailable, PremarketScreenResult, find_previous_completed_market_session,
                                run_premarket_screener)

logger = logging.getLogger(__name__)


@dataclass
class PremarketPipelineResult:
    discovery: MarketDiscoveryResult
    screen: PremarketScreenResult
    registry: object | None
    readiness: str
    lineage: list[dict] = field(default_factory=list)
    universe_rejections: list = field(default_factory=list)
    fallback_rejections: list = field(default_factory=list)
    deep_historical_requests: int = 0
    deep_rate_limit_responses: int = 0
    screen_failure_reason: str | None = None

    def report(self):
        from dataclasses import asdict
        eligible = len(self.registry.by_symbol) if self.registry is not None else 0
        return {'discovery': self.discovery.report(), 'readiness': self.readiness,
            'screen_failure_reason': self.screen_failure_reason,
            'universe_audit': {'scope': 'NSE_INTRADAY_EQUITY_SHARES',
                'raw_records_examined': self.discovery.raw_instrument_count,
                'eligible_instruments': eligible, 'excluded_records': len(self.universe_rejections),
                'exclusion_reasons': dict(Counter(r.reason for r in self.universe_rejections)),
                'record_accounting_complete': (self.registry is not None and
                    eligible + len(self.universe_rejections) == self.discovery.raw_instrument_count),
                'configured_stock_list_used': False},
            'deep_screen': {'session_date': self.screen.session_date.isoformat(),
                'planned_candidates': len(self.discovery.selected_candidates),
                'analysed': self.screen.total_candidates, 'qualified': len(self.screen.qualified_candidates),
                'rejected': len(self.screen.rejected_candidates), 'watchlist_count': len(self.screen.watchlist),
                'status': self.screen.trading_day_status, 'historical_requests': self.deep_historical_requests,
                'rate_limit_responses': self.deep_rate_limit_responses,
                'candidates_with_valid_data': sum(c.data_ok for c in self.screen.diagnostics),
                'history_warning': self.screen.history_warning,
                'rejections': [{'symbol': c.symbol, 'reasons': c.rejection_reasons}
                               for c in self.screen.rejected_candidates]},
            'lineage': self.lineage, 'universe_rejections': [asdict(r) for r in self.universe_rejections],
            'fallback_rejections': [asdict(r) for r in self.fallback_rejections]}


def load_startup_universe(smart_api, source, now, master_path=None):
    """Use a fresh full instrument cache; refresh it read-only when required."""
    path = master_path or config.INSTRUMENT_MASTER_FILE or str(Path(__file__).parent / 'data' / 'instruments.json')
    try:
        envelope = load_master_envelope(path, now)
        return build_market_universe(envelope, now)
    except (SafetyError, OSError, ValueError, TypeError) as exc:
        logger.warning('[UNIVERSE] cache unavailable | %s', exc)
    from refresh_instruments import refresh_registry
    refresh_registry(smart_api, path, now, get=source.instrument_get)
    return build_market_universe(load_master_envelope(path, now), now)


class _HistoricalRequestCounter:
    """Pace all historical requests, including retries, and respect rate-limit backoff."""
    def __init__(self, broker, *, clock=None, sleep=None):
        self.broker = broker
        self.calls = 0
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.next_allowed = 0.
        self.rate_limit_count = 0
        self.consecutive_rate_limits = 0
        self.deadline = self.clock() + config.DISCOVERY_HISTORY_MAX_RUNTIME_SECONDS

    def _rate_limited(self, response):
        if not any(marker in str(response).lower() for marker in
                   ('exceeding access rate', 'rate limit', 'too many requests', 'ab1021')):
            return False
        self.rate_limit_count += 1
        self.consecutive_rate_limits += 1
        delay = min(config.DISCOVERY_HISTORY_RATE_BACKOFF_MAX_SECONDS,
                    config.DISCOVERY_HISTORY_RATE_BACKOFF_SECONDS * 2 ** (self.consecutive_rate_limits - 1))
        self.next_allowed = max(self.next_allowed, self.clock() + delay)
        logger.warning('[HISTORY RATE LIMIT] cooling down for %.1fs before the next request', delay)
        if self.consecutive_rate_limits >= config.DISCOVERY_HISTORY_MAX_CONSECUTIVE_RATE_LIMITS:
            raise HistoricalDataUnavailable('HISTORY_RATE_LIMIT: consecutive rejection budget exhausted')
        return True

    def getCandleData(self, params):
        if max(self.clock(), self.next_allowed) >= self.deadline:
            raise HistoricalDataUnavailable('HISTORY_TIME_BUDGET_EXHAUSTED')
        self.sleep(max(0., self.next_allowed - self.clock()))
        self.next_allowed = self.clock() + config.DISCOVERY_HISTORY_INTERVAL_SECONDS
        self.calls += 1
        try:
            response = self.broker.getCandleData(params)
        except Exception as exc:
            self._rate_limited(exc)
            raise
        if not self._rate_limited(response):
            self.consecutive_rate_limits = 0
        return response

    def begin_optional_history(self):
        self.deadline = min(self.deadline, self.clock() + config.DISCOVERY_RVOL_MAX_RUNTIME_SECONDS)


def run_premarket_pipeline(smart_api=None, *, now=None, schedule=None, data_source=None,
                           market_universe=None, data_fetcher=None, pacing_interval=None,
                           report_path=None, master_path=None):
    schedule = schedule or get_market_schedule('NSE')
    current = schedule.localize(now)
    target_session = find_previous_completed_market_session(current.date(), schedule)
    source = data_source or DiscoveryDataSource()
    registry = None
    universe_rejections = []
    fallback_rejections = []
    screening_universe = []
    discovery = MarketDiscoveryResult(target_session)
    try:
        base = market_universe or load_startup_universe(smart_api, source, current, master_path)
        registry = base.registry
        universe_rejections = base.rejected_records
        discovery.raw_instrument_count = base.raw_instrument_count
        discovery.resolved_intraday_eq_count = base.eligible_equity_count
        if config.AUTO_DISCOVER_UNIVERSE:
            equities = source.equity_symbols(target_session, current)
            stocks = base.equity_only(equities)
            registry = stocks.registry
            discovery.eligible_equity_count = stocks.eligible_equity_count
            discovery.equity_classification_verified = True
            universe_rejections = stocks.rejected_records
            snapshot = source.snapshot(target_session, current)
            decision_time = schedule.localize() if now is None else current
            discovery = discover_nse_candidates(stocks, snapshot, target_session, decision_time)
            discovery.resolved_intraday_eq_count = base.eligible_equity_count
            if not discovery.success:
                raise SafetyError(discovery.failure_reason)
            registry = stocks.registry
            screening_universe = discovery.screening_universe()
        else:
            discovery.failure_reason = 'AUTO_DISCOVER_UNIVERSE_DISABLED'
    except (OSError, ValueError, TypeError, KeyError) as exc:
        discovery.success = False
        discovery.failure_reason = str(exc) if isinstance(exc, SafetyError) else type(exc).__name__
        logger.warning('[DISCOVERY] DYNAMIC_DISCOVERY_FAILED | %s', discovery.failure_reason)

    if not discovery.success:
        screening_universe = []
        discovery.universe_source = 'UNAVAILABLE'
        logger.error('[DISCOVERY BLOCKED] %s | full market data required; configured stock lists are disabled',
                     discovery.failure_reason)
    discovery.request_counts = source.accounting.report()
    discovery.datasets = getattr(source, 'datasets', {})
    counted_broker = _HistoricalRequestCounter(smart_api) if smart_api is not None else None
    kwargs = {'smart_api': counted_broker, 'schedule': schedule, 'universe': screening_universe,
              'session_date': target_session, 'top_n': config.SCREEN_TOP_N, 'data_fetcher': data_fetcher}
    if pacing_interval is not None:
        kwargs['pacing_interval'] = pacing_interval
    logger.info('[PREMARKET DEEP SCREEN] source=%s candidates=%s session=%s',
                discovery.universe_source, len(screening_universe), target_session)
    screen_failure_reason = None
    try:
        screen = run_premarket_screener(**kwargs)
    except HistoricalDataUnavailable as exc:
        screen_failure_reason = str(exc)
        diagnostics = list(exc.diagnostics)
        screen = PremarketScreenResult(target_session, len(diagnostics),
            [c for c in diagnostics if c.qualified], [c for c in diagnostics if not c.qualified],
            None, 'NO_TRADE', diagnostics, [])
        logger.error('[PREMARKET BLOCKED] %s | completed=%s planned=%s; no trading watchlist released',
                     screen_failure_reason, len(diagnostics), len(screening_universe))
    selected_ranks = {c.symbol: rank for rank, c in enumerate(screen.watchlist, 1)}
    deep_ranks = {c.symbol: rank for rank, c in enumerate(screen.qualified_candidates, 1)}
    records = {c['symbol']: c for c in screening_universe}
    lineage = []
    for diagnostic in screen.diagnostics:
        record = records[diagnostic.symbol]
        trace = dict(record.get('discovery_lineage', {}))
        trace.update({'symbol': diagnostic.symbol, 'trading_symbol': diagnostic.trading_symbol,
            'token': diagnostic.token, 'exchange': diagnostic.exchange,
            'instrument_source': trace.get('instrument_source', 'BROKER_MASTER'),
            'universe_source': discovery.universe_source, 'session_date': target_session.isoformat(),
            'deep_screen_rank': deep_ranks.get(diagnostic.symbol), 'opportunity_score': diagnostic.opportunity_score,
            'screened_price': diagnostic.ltp, 'atr_pct': diagnostic.atr_pct,
            'total_volume': diagnostic.total_volume, 'candle_count': diagnostic.candle_count,
            'rvol_history_sessions': len(diagnostic.volume_profiles),
            'spread_depth_basis': 'PREMARKET_ASSUMPTION_REQUIRES_LIVE_QUOTE_VALIDATION',
            'qualified': diagnostic.qualified, 'qualification_result': 'QUALIFIED' if diagnostic.qualified else 'REJECTED',
            'rejection_reasons': diagnostic.rejection_reasons, 'final_rank': selected_ranks.get(diagnostic.symbol)})
        diagnostic.discovery_lineage = trace
        lineage.append(trace)
    if discovery.success and screen_failure_reason is None:
        readiness = 'DYNAMIC_DISCOVERY_READY'
    else:
        readiness = 'BLOCKED'
    result = PremarketPipelineResult(discovery, screen, registry, readiness, lineage,
        universe_rejections, fallback_rejections, counted_broker.calls if counted_broker else 0,
        counted_broker.rate_limit_count if counted_broker else 0, screen_failure_reason)
    logger.info('[DISCOVERY API] %s', discovery.request_counts)
    logger.info('[PREMARKET DEEP SCREEN] analysed=%s qualified=%s rejected=%s',
                screen.total_candidates, len(screen.qualified_candidates), len(screen.rejected_candidates))
    logger.info('[FINAL TOP-3 WATCHLIST] %s', [c.trading_symbol for c in screen.watchlist])
    logger.info('[CORE STRATEGY STATUS] version=%s watchlist=%s max_open_positions=%s mode=%s',
        config.STRATEGY_VERSION, config.WATCHLIST_MODE, config.MAX_OPEN_POSITIONS,
        'LIVE (separately gated)' if config.LIVE_MODE else 'PAPER')
    if report_path:
        try:
            atomic_json(report_path, result.report())
        except OSError as exc:
            logger.error('[DISCOVERY REPORT] write failed | %s', type(exc).__name__)
    return result
