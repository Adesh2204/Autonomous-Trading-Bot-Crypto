"""Bounded public /info investigation; no signer or exchange transport."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D
import inspect, json, sys, time
from pathlib import Path

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
    'exchange_submissions':0,'signature_created':False,'production_mode':'PAPER','allow_live_orders':False,
    'network':'testnet','dex':'par','team_wallet':TEAM,'api_wallet':API,'markets':[]}
 journal=client=None
 try:
  r['safety']=require_paper_migration();r['freeze']=verify_strategy_freeze()
  policy,clock_policy,_=load_reliability_policy(ROOT/'configs/reliability_policy.json')
  journal=ExecutionJournal(a.output_directory/'read_only.sqlite',session_id='v8.3-all-market-probe',team_address=TEAM)
  rates=HyperliquidRateLimitManager(journal,policy=policy,signer_address=API)
  client=HyperliquidClient(rate_limits=rates);client.startup()
  account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
  clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**clock_policy)
  r['metadata']=[asdict(client.market(s)) for s in sorted(EXPECTED_MARKETS)]
  r['initial_positions']=[asdict(v) for v in account.get_positions().values()]
  r['initial_orders']=account.get_frontend_open_orders()
  r['active_asset_by_market']={s:dict(observed_ms=client.clock_ms(),value=account._query('activeAssetData',coin=s)) for s in sorted(EXPECTED_MARKETS)}
  for _ in range(2):
   sent=client.clock_ms();book=market.get_orderbook('par:ETH');clock.observe(book.timestamp_ms,sent,client.clock_ms())
  r['account_readiness']=asdict(verify_live_account_readiness(account,API,clock_health=clock,rate_limits=rates,reconciliation_ready=False))
  # A public flat snapshot is not the durable certification account barrier.
  r['clock_at_account_read']=clock.report()
  for symbol in sorted(EXPECTED_MARKETS):
   row={'symbol':symbol};r['markets'].append(row)
   try:
    deadline=time.monotonic()+65
    while rates._usage()+100>rates.policy.ip_weight_per_minute-rates.policy.ip_safety_reserve:
     if time.monotonic()>deadline:raise ExchangeError('PUBLIC_READ_BUDGET_WAIT_EXHAUSTED')
     time.sleep(.5)
    spec=client.market(symbol)
    context=market.get_asset_contexts()[symbol];row['context_observed_ms']=client.clock_ms()
    sent=client.clock_ms();raw=client.post_info('l2Book',coin=symbol);received=client.clock_ms()
    clock.observe(raw['time'],sent,received)
    row.update(observed_ms=received,book=raw,asset_context=context,lot_size=str(spec.size_step))
    bid=D(raw['levels'][0][0]['px']);ask=D(raw['levels'][1][0]['px'])
    entry=spec.normalize_price(ask*D('1.0005'),'BUY')
    trigger=spec.normalize_price(bid*D('.99'),'SELL');bound=spec.normalize_price(trigger*D('.995'),'SELL')
    row.update(reviewed_long_prices={'entry_limit':str(entry),'stop_trigger':str(trigger),'stop_limit':str(bound),'exit_bound':str(bound)},
      one_lot_notionals={'bid':str(spec.size_step*bid),'ask':str(spec.size_step*ask),'mark':str(spec.size_step*D(context['markPx'])),
        'entry_limit':str(spec.size_step*entry),'stop_limit':str(spec.size_step*bound),'exit_bound':str(spec.size_step*bound)})
    row['one_lot_at_least_ten_at_all_limits']=min(spec.size_step*entry,spec.size_step*bound)>=10
   except Exception as exc:row['error']=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__
   atomic_json(a.output_directory/'observations.json',r)
  r['final_positions']=[asdict(v) for v in account.get_positions().values()]
  r['final_orders']=account.get_frontend_open_orders();r['clock_final']=clock.report();r['rates']=rates.report()
  r['status']='READ_ONLY_COMPLETE'
 except Exception as exc:r.update(status='READ_ONLY_FAILED',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
 finally:
  if client:client.transport.close()
  if journal:journal.close()
 r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT))
 atomic_json(a.output_directory/'observations.json',r)
 print(json.dumps({'status':r['status'],'markets':[dict(symbol=x['symbol'],lot=x.get('lot_size'),notionals=x.get('one_lot_notionals'),error=x.get('error')) for x in r['markets']]}))
 return 0 if r['status']=='READ_ONLY_COMPLETE' else 1

if __name__=='__main__':raise SystemExit(main())
