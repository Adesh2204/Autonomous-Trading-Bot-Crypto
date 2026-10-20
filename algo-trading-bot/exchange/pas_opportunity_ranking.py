"""Read-only all-ten PAS ranking using the unchanged scanner and frozen brain.

The separate observation scanner can collect other PAS markets. Central entry
scope remains BTC/EWY. A rank is neither an order permission nor expected profit.
"""
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
import threading
from .base_exchange import ExchangeError
from .entry_scope import PAS_ENTRY_MARKETS
from .venue_profiles import SCORED
from .paper_operations import active_source_hash,atomic_json
from .public_quant_operator import SerializedPublicClient,ReadOnlyReceipts,SerializedPublicMarket
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy


class ReadOnlyPasRankingScanner(MarketRegimeScanner):
    def require_runtime(self):
        from venue_config import require_paper_migration
        if (type(self.client) is not SerializedPublicClient or self.client.dex!='pas'
                or type(self.client.transport) is not ReadOnlyReceipts
                or self.live_authorization is not None or self.team_address is not None
                or self.signer_address is not None):
            raise ExchangeError('READ_ONLY_PAS_RANKING_CLIENT_REQUIRED')
        require_paper_migration('pas')

    def selected_markets(self):
        self.require_runtime()
        if not self.client.ready or set(self.client.markets)!=SCORED.markets:
            raise ExchangeError('ALL_TEN_CANONICAL_PAS_MARKETS_REQUIRED')
        if self.candidate_symbols and set(self.candidate_symbols)!=SCORED.markets:
            raise ExchangeError('RANKING_SCOPE_MUST_BE_ALL_TEN_PAS_MARKETS')
        return tuple(sorted(self.client.markets))


def ranking_report(result,source,source_after):
    """Keep raw qualifications, signal eligibility and entry scope distinct."""
    if source!=source_after:raise ExchangeError('RANKING_SOURCE_CHANGED')
    if len(result.diagnostics)!=10 or {d.symbol for d in result.diagnostics}!=SCORED.markets:
        raise ExchangeError('COMPLETE_TEN_MARKET_RANKING_REQUIRED')
    qualified={d.symbol for d in result.diagnostics if d.qualified}
    if (len(result.watchlist)>3 or len(set(result.watchlist))!=len(result.watchlist)
            or not set(result.watchlist)<=qualified):
        raise ExchangeError('OBSERVATIONAL_TOP_THREE_MUST_BE_QUALIFIED_AND_UNIQUE')
    rows=[]
    for d in result.diagnostics:
        rows.append(dict(symbol=d.symbol,rank=d.evidence.get('scanner_rank'),score=str(d.score),
            scanner_qualified=d.qualified,reasons=d.reasons,metrics=d.metrics,signal=d.signal,
            evidence=d.evidence,timing=d.timing,
            production_entry_market=d.symbol in PAS_ENTRY_MARKETS,
            strategy_signal_present=bool(d.signal and (d.signal.get('long') or d.signal.get('short'))),
            signed_entry_authorized=False,expected_profit=None))
    rows.sort(key=lambda r:(r['rank'] is None,r['rank'] or 0,r['symbol']))
    return dict(status='READ_ONLY_PAS_RANKING_COMPLETE',observed_ms=result.observed_at_ms,
        source_hash=source,source_hash_after=source_after,network='testnet',dex='pas',collateral='USDP',
        strategy='UNCHANGED_FROZEN_BRAIN_AND_SCANNER_RANKING',
        policy=dict(atr_fraction='0.004',spread_bps='15',history_bars=300,top_n=3,
            percentile_factors=['atr_fraction','spread_bps_inverse','window_notional_approx','bbo_notional']),
        observational_top_three=result.watchlist,rows=rows,production_entry_markets=sorted(PAS_ENTRY_MARKETS),
        signing_authority='NONE',signatures_created=0,exchange_writes=0,
        note='All ten are observed only. Ranking never expands BTC/EWY entry policy, supplies a signal, qualifies protection, or creates mandate acceptance.')


def collect(root,output):
    from .hyperliquid_client import RequestsInfoTransport
    from .execution_journal import ExecutionJournal
    from .rate_limits import HyperliquidRateLimitManager
    from .durable_history import DurableHistory
    from .testnet_certification import TEAM
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    require_paper_migration('pas');verify_strategy_freeze()
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    source=active_source_hash(root)
    journal=ExecutionJournal(out/'public.sqlite',session_id='public:pas-ten-market-ranking',team_address=TEAM)
    rates=HyperliquidRateLimitManager(journal);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
    client=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl'),rate_limits=rates,venue='pas')
    history=None;stop=threading.Event();timer=threading.Timer(240,stop.set);timer.start();client.read_cancel_event=stop
    try:
        client.startup();history=DurableHistory(out/'history.sqlite',client,out/'info_receipts.jsonl');client.candle_audit=history
        scanner=ReadOnlyPasRankingScanner(SerializedPublicMarket(client),ScannerPolicy(D('.004'),D(15),D(0),D(0)))
        result=scanner.scan();report=ranking_report(result,source,active_source_hash(root))
        report.update(histories={s:history.report(s,client.clock_ms()) for s in sorted(client.markets)},
            journal_integrity=journal.db.execute('pragma integrity_check').fetchone()[0],
            history_integrity=history.db.execute('pragma integrity_check').fetchone()[0],rate_report=rates.report())
        atomic_json(out/'ranking.json',report);return report
    finally:
        stop.set();timer.cancel()
        if history:history.close()
        client.close();journal.close()
