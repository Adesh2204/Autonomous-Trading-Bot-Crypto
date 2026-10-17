"""Bounded unsigned account/metadata read; no observer, signer or exchange writes."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal as D
import json,sys,threading,time
P=Path(__file__).resolve().parent;ROOT=P.parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.public_quant_operator import ReadOnlyReceipts
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM
from exchange.capital_allocation import depth_capacity,floor_quantity
from venue_config import require_paper_migration
require_paper_migration()
out=P/'morning_account_2026-10-17';out.mkdir(exist_ok=False)
j=ExecutionJournal(out/'public.sqlite',session_id='public:morning-native-audit',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
previous=json.loads((P/'subminimum_readback_2026-10-17/audit.json').read_text());rates.weights.append((previous['finished_ms'],previous['rate_report']['ip_weight']))
transport=ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl');client=HyperliquidClient(transport,rate_limits=rates)
cancel=threading.Event();timer=threading.Timer(180,cancel.set);timer.start();client.read_cancel_event=cancel
r=dict(started_ms=client.clock_ms(),source_hash=active_source_hash(ROOT),orders_submitted=0,signatures=0,markets=[],readbacks=[],errors=[])
try:
 client.startup();a=HyperliquidAccount(client,TEAM);m=HyperliquidMarketData(client);truth=ExchangeTruthState();reconcile=HyperliquidReconciliation(a)
 reconcile.recover(truth,start_ms=0);r.update(account=truth.report(),account_mode=a._query('userAbstraction'),agents=a._query('extraAgents'),fees=a._query('userFees'),account_rate=a._query('userRateLimit'),metadata=client.metadata)
 contexts=m.get_asset_contexts();r['context_observed_ms']=client.clock_ms()
 for symbol in sorted(client.markets):
  spec=client.market(symbol);book=m.get_orderbook(symbol);active=a._query('activeAssetData',coin=symbol);ctx=contexts[symbol];mark=D(ctx['markPx']);step=spec.size_step
  buy=depth_capacity(book,'BUY');sell=depth_capacity(book,'SELL');fee=D(r['fees']['userCrossRate'])*6
  q=floor_quantity(spec,min(buy['best_quantity']*D('.1'),sell['best_quantity']*D('.1'),buy['raw_l2_quantity']*D('.1'),sell['raw_l2_quantity']*D('.1'),D(active['maxTradeSzs'][0]),min(D(x) for x in active['availableToTrade'])/(book.asks[0].price*(1+2*fee)),D(1000)/book.asks[0].price))
  r['markets'].append(dict(symbol=symbol,observed_ms=client.clock_ms(),spec=asdict(spec),active_asset=active,context=ctx,book=asdict(book),one_lot_mark_notional=str(step*mark),minimum_qualifying_mark_exclusive=str(D(10)/step),all_correct_long_stop_limits_below_ordinary_minimum=step*mark<=10,liquidity_only_quantity=str(q),liquidity_only_notional=str(q*book.asks[0].price),qualified_unattended_notional='0'))
  atomic_json(out/'audit.json',r)
 for _ in range(2):
  reconcile.recover(truth,start_ms=max(0,truth.last_window[1]-60000));before=a.get_positions();orders=a.get_frontend_open_orders();after=a.get_positions()
  if before!=after:raise RuntimeError('FINAL_POSITION_CHANGED')
  r['readbacks'].append(dict(observed_ms=client.clock_ms(),team=TEAM,source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',positions=[asdict(x) for x in after.values()],orders=orders,ready=not truth.reasons))
 r.update(account_final=truth.report(),status='BOUNDED_ACCOUNT_READ_COMPLETE',terminal_flat=len(r['readbacks'])==2 and r['readbacks'][0]['observed_ms']<r['readbacks'][1]['observed_ms'] and all(x['ready'] and not x['positions'] and not x['orders'] for x in r['readbacks']))
except Exception as e:
 from exchange.terminal_recovery import exception_evidence
 r.update(status='INCOMPLETE',error=exception_evidence(e));r['errors'].append(str(e))
finally:
 timer.cancel();r.update(finished_ms=client.clock_ms(),source_hash_after=active_source_hash(ROOT),rate_report=rates.report(),sqlite_integrity=j.db.execute('PRAGMA integrity_check').fetchone()[0]);atomic_json(out/'audit.json',r);client.close();j.close()
print(json.dumps({k:r.get(k) for k in ('status','terminal_flat','errors','readbacks')},indent=2));raise SystemExit(0 if r.get('status')=='BOUNDED_ACCOUNT_READ_COMPLETE' else 1)
