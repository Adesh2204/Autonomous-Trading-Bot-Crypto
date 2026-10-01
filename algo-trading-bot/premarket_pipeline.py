"""One startup path: market discovery -> unchanged deep screener -> Phase 5."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path

import config
from discovery_data import DiscoveryDataSource, atomic_json
from execution_safety import SafetyError
from market_discovery import MarketDiscoveryResult, discover_nse_candidates
from market_schedule import get_market_schedule
from market_universe import build_market_universe, configured_fallback, load_master_envelope
from premarket_screener import (PremarketScreenResult, find_previous_completed_market_session,
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

    def report(self):
        from dataclasses import asdict
        return {'discovery': self.discovery.report(), 'readiness': self.readiness,
            'deep_screen': {'session_date': self.screen.session_date.isoformat(),
                'analysed': self.screen.total_candidates, 'qualified': len(self.screen.qualified_candidates),
                'rejected': len(self.screen.rejected_candidates), 'watchlist_count': len(self.screen.watchlist),
                'status': self.screen.trading_day_status, 'historical_requests': self.deep_historical_requests,
                'rejections': [{'symbol': c.symbol, 'reasons': c.rejection_reasons}
                               for c in self.screen.rejected_candidates]},
            'lineage': self.lineage, 'universe_rejections': [asdict(r) for r in self.universe_rejections],
            'fallback_rejections': [asdict(r) for r in self.fallback_rejections]}


def load_startup_universe(smart_api, source, now, master_path=None):
    """Use a fresh cache first; reuse existing read-only refresh on failure."""
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
    """Only wraps Stage 2's read-only historical method, never execution."""
    def __init__(self, broker):
        self.broker = broker
        self.calls = 0

    def getCandleData(self, params):
        self.calls += 1
        return self.broker.getCandleData(params)


def run_premarket_pipeline(smart_api=None, *, now=None, schedule=None, data_source=None,
                           market_universe=None, data_fetcher=None, pacing_interval=None,
                           report_path=None):
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
        base = market_universe or load_startup_universe(smart_api, source, current)
        registry = base.registry
        universe_rejections = base.rejected_records
        discovery.raw_instrument_count = base.raw_instrument_count
        discovery.resolved_intraday_eq_count = base.eligible_equity_count
        if config.AUTO_DISCOVER_UNIVERSE:
            equities = source.equity_symbols(target_session, current)
            stocks = base.equity_only(equities)
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
        manual = not config.AUTO_DISCOVER_UNIVERSE
        if registry is not None and (manual or config.DISCOVERY_ALLOW_CONFIG_FALLBACK):
            screening_universe, fallback_rejections = configured_fallback(registry, current)
            discovery.universe_source = 'CONFIG_FALLBACK'
            logger.warning('[MARKET DISCOVERY WARNING] Dynamic NSE universe unavailable. '
                           'Using configured fallback universe. Reason: %s', discovery.failure_reason)
        else:
            discovery.universe_source = 'UNAVAILABLE'
            logger.error('[FALLBACK] unavailable: fresh authoritative identity required; NO_TRADE')
    discovery.request_counts = source.accounting.report()
    counted_broker = _HistoricalRequestCounter(smart_api) if smart_api is not None else None
    kwargs = {'smart_api': counted_broker, 'schedule': schedule, 'universe': screening_universe,
              'session_date': target_session, 'top_n': config.SCREEN_TOP_N, 'data_fetcher': data_fetcher}
    if pacing_interval is not None:
        kwargs['pacing_interval'] = pacing_interval
    logger.info('[PREMARKET DEEP SCREEN] source=%s candidates=%s session=%s',
                discovery.universe_source, len(screening_universe), target_session)
    screen = run_premarket_screener(**kwargs)
    selected_ranks = {c.symbol: rank for rank, c in enumerate(screen.watchlist, 1)}
    deep_ranks = {c.symbol: rank for rank, c in enumerate(screen.qualified_candidates, 1)}
    records = {c['symbol']: c for c in screening_universe}
    lineage = []
    for diagnostic in screen.diagnostics:
        record = records[diagnostic.symbol]
        trace = dict(record.get('discovery_lineage', {}))
        trace.update({'symbol': diagnostic.symbol, 'trading_symbol': diagnostic.trading_symbol,
            'token': diagnostic.token, 'exchange': diagnostic.exchange,
            'instrument_source': trace.get('instrument_source', 'BROKER_MASTER_CONFIG_FALLBACK'),
            'universe_source': discovery.universe_source, 'session_date': target_session.isoformat(),
            'deep_screen_rank': deep_ranks.get(diagnostic.symbol), 'opportunity_score': diagnostic.opportunity_score,
            'qualified': diagnostic.qualified, 'qualification_result': 'QUALIFIED' if diagnostic.qualified else 'REJECTED',
            'rejection_reasons': diagnostic.rejection_reasons, 'final_rank': selected_ranks.get(diagnostic.symbol)})
        diagnostic.discovery_lineage = trace
        lineage.append(trace)
    if discovery.success:
        readiness = 'DYNAMIC_DISCOVERY_READY'
    elif discovery.universe_source == 'CONFIG_FALLBACK' and screening_universe:
        readiness = 'CONFIG_FALLBACK_READY'
    else:
        readiness = 'BLOCKED'
    result = PremarketPipelineResult(discovery, screen, registry, readiness, lineage,
        universe_rejections, fallback_rejections, counted_broker.calls if counted_broker else 0)
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
