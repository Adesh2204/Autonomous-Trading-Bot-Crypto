"""Fresh public-address account check only; no proposal, SDK or signer."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import sys
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
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


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-directory',type=Path,required=True);a=p.parse_args()
    a.output_directory.mkdir(exist_ok=False)
    r={'source_hash':active_source_hash(ROOT),'started_utc':datetime.now(timezone.utc).isoformat(),
       'network':'testnet','dex':'par','team_wallet':TEAM,'api_wallet':API,'general_market_scan':False,
       'execution_mode':'PAPER','allow_live_orders':False,'signature_created':False,
       'exchange_submissions':0,'order_authorized':False,'durable_certification_barrier_tested':False,
       'scope':'Timestamped read-only account observations, not execution certification'}
    client=journal=None
    try:
        r['safety']=require_paper_migration();r['strategy_freeze']=verify_strategy_freeze()
        policy,clock_policy,protection=load_reliability_policy(ROOT/'configs/reliability_policy.json')
        r['protection_enabled']=protection.enabled
        if protection.enabled:raise ExchangeError('MIGRATION_PROTECTION_MUST_REMAIN_DISABLED')
        journal=ExecutionJournal(a.output_directory/'read_only.sqlite',session_id='v8.4-read-only-account',team_address=TEAM)
        rates=HyperliquidRateLimitManager(journal,policy=policy,signer_address=API)
        client=HyperliquidClient(rate_limits=rates);client.startup()
        account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**clock_policy)
        r['runtime_metadata']=[asdict(client.market(s)) for s in sorted(EXPECTED_MARKETS)]
        r['initial_positions']=[asdict(v) for v in account.get_positions().values()]
        r['initial_frontend_open_orders']=account.get_frontend_open_orders()
        # Exactly two focused ETH reference reads establish fresh clock checks.
        # No candles, market-ranking loop, one-lot scan or trading signal runs.
        r['clock_reference_observations']=[]
        for _ in range(2):
            sent=client.clock_ms();raw_book=client.post_info('l2Book',coin='par:ETH');received=client.clock_ms()
            # Clock evidence only: an empty book can still report server time.
            # Never fabricate a quote or treat these timestamps as liquidity.
            clock.observe(raw_book.get('time'),sent,received)
            r['clock_reference_observations'].append(dict(coin='par:ETH',sent_ms=sent,
                received_ms=received,exchange_ms=raw_book.get('time'),raw_book=raw_book,
                executable_market_certified=False))
        r['account_readiness']=asdict(verify_live_account_readiness(account,API,
            clock_health=clock,rate_limits=rates,reconciliation_ready=False))
        r['clock_at_account_read']=clock.report()
        r['active_asset_by_market']={s:dict(value=account._query('activeAssetData',coin=s),
            observed_ms=client.clock_ms()) for s in sorted(EXPECTED_MARKETS)}
        r['all_ten_one_x_cross']=all(x['value'].get('leverage')==dict(type='cross',value=1)
            and x['value'].get('user','').lower()==TEAM.lower() and x['value'].get('coin')==s
            for s,x in r['active_asset_by_market'].items())
        r['reported_equity']=asdict(account.get_equity())
        r['actual_par_fills']=[asdict(v) for v in account.get_fills()]
        r['final_positions']=[asdict(v) for v in account.get_positions().values()]
        r['final_frontend_open_orders']=account.get_frontend_open_orders()
        r['account_observed_final_ms']=client.clock_ms()
        r['clock_final']=clock.report();r['rates']=rates.report()
        r['observed_flat']=not any(r[k] for k in ('initial_positions','initial_frontend_open_orders',
            'final_positions','final_frontend_open_orders'))
        r['account_observation_checks_passed']=(r['observed_flat'] and r['all_ten_one_x_cross']
            and r['account_readiness']['reasons']==('ACCOUNT_RECONCILIATION_REQUIRED',)
            and r['account_readiness']['clock_healthy'] and r['account_readiness']['rate_limits_healthy'])
        r['status']='READ_ONLY_COMPLETE'
    except Exception as exc:r.update(status='READ_ONLY_FAILED',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        if client:client.close()
        if journal:
            r['sqlite_integrity']=journal.db.execute('PRAGMA integrity_check').fetchone()[0]
            r['actual_action_rows']={table:journal.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('intents','api_actions','signed_management')}
            journal.close()
    r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT))
    if r['source_hash_after']!=r['source_hash']:r.update(status='READ_ONLY_FAILED',error='SOURCE_CHANGED_DURING_ACCOUNT_CHECK')
    atomic_json(a.output_directory/'account_check.json',r)
    print(json.dumps({k:r.get(k) for k in ('status','error','account_observation_checks_passed','observed_flat',
        'all_ten_one_x_cross','sqlite_integrity','actual_action_rows','exchange_submissions')},indent=2))
    return 0 if r['status']=='READ_ONLY_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
