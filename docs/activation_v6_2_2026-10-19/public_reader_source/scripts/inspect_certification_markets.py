"""Bounded read-only review of all ten official par markets. No execution mode."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D
import json, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.certification_market_review import review_one_lot_long
from exchange.hyperliquid_client import HyperliquidClient, EXPECTED_MARKETS
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager
from exchange.live_readiness import verify_live_account_readiness
from exchange.paper_operations import active_source_hash, atomic_json
from exchange.reliability_policy import load_reliability_policy
from exchange.testnet_certification import TEAM, API
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


def inspect_markets(directory):
    directory=Path(directory);directory.mkdir(exist_ok=False,parents=True)
    report=dict(status='READ_ONLY_IN_PROGRESS',source_hash=active_source_hash(ROOT),
        started_utc=datetime.now(timezone.utc).isoformat(),production_mode='PAPER',allow_live_orders=False,
        network='testnet',dex='par',team_wallet=TEAM,api_wallet=API,markets=[],
        exchange_submissions=0,signature_created=False,order_authorized=False,
        PARTIAL_FILL_EXIT_READY=False,ACTUAL_PROTECTION_READY=False,CONTROLLED_EXECUTION_READY=False)
    journal=client=None
    try:
        report['safety']=require_paper_migration();report['freeze']=verify_strategy_freeze()
        policy,clock_policy,protection=load_reliability_policy(ROOT/'configs/reliability_policy.json')
        report['global_protection_enabled']=protection.enabled
        if protection.enabled:raise ExchangeError('MIGRATION_PROTECTION_MUST_REMAIN_DISABLED')
        journal=ExecutionJournal(directory/'read_only.sqlite',session_id='v8.3-one-lot-review',team_address=TEAM)
        rates=HyperliquidRateLimitManager(journal,policy=policy,signer_address=API)
        client=HyperliquidClient(rate_limits=rates);client.startup()
        account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**clock_policy)
        report['metadata']=[asdict(client.market(s)) for s in sorted(EXPECTED_MARKETS)]
        report['initial_positions']=[asdict(v) for v in account.get_positions().values()]
        report['initial_orders']=account.get_frontend_open_orders()
        report['active_asset_by_market']={}
        for symbol in sorted(EXPECTED_MARKETS):
            value=account._query('activeAssetData',coin=symbol)
            report['active_asset_by_market'][symbol]=dict(observed_ms=client.clock_ms(),value=value)
        # Fresh reference observations precede the account check; do not relabel
        # a later healthy clock as proof of an earlier unsafe check.
        for _ in range(2):
            sent=client.clock_ms();book=market.get_orderbook('par:ETH')
            clock.observe(book.timestamp_ms,sent,client.clock_ms())
        report['account_readiness']=asdict(verify_live_account_readiness(account,API,
            clock_health=clock,rate_limits=rates,reconciliation_ready=False))
        report['clock_at_account_read']=clock.report()
        fee=D(report['account_readiness']['fees']['userCrossRate'])*2
        report['fee_scope']='Current userCrossRate doubled by documented par deployerFeeScale=1; estimate only'
        report['taker_fee_rate']=str(fee)
        for symbol in sorted(EXPECTED_MARKETS):
            row=dict(symbol=symbol,eligible_under_reviewed_bounds=False,blockers=[])
            try:
                deadline=time.monotonic()+65
                while rates._usage()+100>rates.policy.ip_weight_per_minute-rates.policy.ip_safety_reserve:
                    if time.monotonic()>=deadline:raise ExchangeError('CERTIFICATION_PUBLIC_READ_BUDGET')
                    time.sleep(.5)
                spec=client.market(symbol);context=market.get_asset_contexts()[symbol]
                context_ms=client.clock_ms();sent=client.clock_ms()
                raw_book=client.post_info('l2Book',coin=symbol);received=client.clock_ms()
                clock.observe(raw_book.get('time'),sent,received)
                active=account._query('activeAssetData',coin=symbol)
                row=review_one_lot_long(spec,raw_book,context,active,now_ms=client.clock_ms(),
                    context_observed_ms=context_ms,taker_fee_rate=fee)
                row.update(raw_book=raw_book,asset_context=context,active_asset=active,
                    active_asset_observed_ms=client.clock_ms(),clock=clock.report())
            except Exception as exc:
                row['blockers'].append(str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
            report['markets'].append(row)
            atomic_json(directory/'review.json',report)
        report['final_positions']=[asdict(v) for v in account.get_positions().values()]
        report['final_orders']=account.get_frontend_open_orders()
        report['account_observed_final_ms']=client.clock_ms()
        report['rates']=rates.report();report['clock_final']=clock.report()
        flat=not any(report[k] for k in ('initial_positions','initial_orders','final_positions','final_orders'))
        report['account_observed_flat']=flat
        report['eligible_markets']=[x['symbol'] for x in report['markets'] if x['eligible_under_reviewed_bounds']]
        report['status']='REVIEW_CANDIDATE_REQUIRES_FRESH_PREFLIGHT' if report['eligible_markets'] and flat else 'PREFLIGHT_BLOCKED'
        report['blocker']='NO_ELIGIBLE_ONE_LOT_MARKET' if not report['eligible_markets'] else None
        if not flat:report['blocker']='CERTIFICATION_FLAT_ACCOUNT_REQUIRED'
        # This report is never serialized as a proposal or used as authorization.
    except Exception as exc:
        report.update(status='PREFLIGHT_BLOCKED',blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        if client:client.transport.close()
        if journal:journal.close()
    report.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT))
    if report['source_hash']!=report['source_hash_after']:
        report.update(status='PREFLIGHT_BLOCKED',blocker='SOURCE_CHANGED_DURING_OBSERVATION')
    atomic_json(directory/'review.json',report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-directory',type=Path,required=True)
    args=p.parse_args(argv);r=inspect_markets(args.output_directory)
    print(json.dumps(dict(status=r['status'],blocker=r.get('blocker'),markets_reviewed=len(r['markets']),
        eligible_markets=r.get('eligible_markets',[]),exchange_submissions=0)))
    return 0 if r.get('eligible_markets') else 1


if __name__=='__main__':raise SystemExit(main())
