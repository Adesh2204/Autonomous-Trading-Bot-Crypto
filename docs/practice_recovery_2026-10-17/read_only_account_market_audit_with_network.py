"""Bounded public /info evidence audit. No keys, signer, worker or exchange writes."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal as D
import hashlib,json,sys,threading,time
P=Path(__file__).resolve().parent;ROOT=P.parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.execution_journal import ExecutionJournal
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.reliability_policy import RequestPriority
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM,API
from exchange.capital_allocation import depth_capacity,floor_quantity
from exchange.base_exchange import ExchangeError
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze

out=P/'public_audit_with_network';out.mkdir(exist_ok=False)
stop=threading.Event();timer=threading.Timer(180,stop.set);timer.start()
class StrictReceipts(RequestsInfoTransport):
 def __init__(self):self.inner=RequestsInfoTransport();self.records=[]
 def __call__(self,payload,*,cancel_event=None,progress=None):
  allowed={'perpDexs','meta','metaAndAssetCtxs','l2Book','recentTrades','activeAssetData','clearinghouseState','openOrders','frontendOpenOrders','userFillsByTime','userFunding','userAbstraction','spotClearinghouseState','userFees','extraAgents','userRateLimit','orderStatus','historicalOrders'}
  if payload.get('type') not in allowed or any(k in payload for k in ('action','signature','private_key','nonce')):raise ExchangeError('STRICT_INFO_ONLY')
  if payload['type']=='historicalOrders' and set(payload)!={'type','user'}:raise ExchangeError('HISTORY_SCHEMA_REQUIRED')
  r=dict(request=payload,sent_ms=time.time_ns()//1000000);self.records.append(r)
  try:r['response']=self.inner(payload,cancel_event=cancel_event,progress=progress);return r['response']
  except Exception as e:r.update(error=str(e),status_code=getattr(e,'status_code',None));raise
  finally:
   r['received_ms']=time.time_ns()//1000000
   with (out/'info_receipts.jsonl').open('a') as f:f.write(json.dumps(r,default=str)+'\n')
 def close(self):self.inner.close()
require_paper_migration();verify_strategy_freeze()
j=ExecutionJournal(out/'public.sqlite',session_id='public:practice-weekend-position-stops',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
transport=StrictReceipts();client=HyperliquidClient(transport,rate_limits=rates);client.read_cancel_event=stop
result=dict(started_ms=client.clock_ms(),source_hash=active_source_hash(ROOT),scope='POST_ATTEMPT_CAPACITY_AND_ACCOUNT_READS_ONLY_NO_SIGNER',orders_submitted=0,signatures=0,private_keys_accessed=False,markets=[],public_users=[],histories=[],native_records=[],errors=[],limits=dict(max_public_users=0,max_histories=1,max_native_statuses=0,timeout_seconds=180))
def save():atomic_json(out/'audit.json',result)
def history(user):
 # HistoricalOrders is not in the production query allowlist. This isolated
 # /info-only research read reserves 120 weight before one bounded request,
 # enough for the documented maximum 2000 rows; no order API is reachable.
 began=time.monotonic()
 while True:
  if stop.is_set() or time.monotonic()-began>=65:raise ExchangeError('BOUNDED_HISTORY_RATE_WAIT_EXCEEDED')
  try:rates.reserve_info('historicalOrders',priority=RequestPriority.DECISION,response_weight=100);break
  except ExchangeError as e:
   if str(e)!='RATE_LIMITED':raise
   stop.wait(.25)
 rows=transport(dict(type='historicalOrders',user=user),cancel_event=stop)
 if not isinstance(rows,list) or len(rows)>2000:raise ExchangeError('BOUNDED_HISTORY_RESPONSE_INVALID')
 return rows
try:
 client.startup();account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client);truth=ExchangeTruthState();reconciler=HyperliquidReconciliation(account)
 reconciler.recover(truth,start_ms=0)
 result.update(metadata=client.metadata,account_initial=truth.report(),fees=account._query('userFees'),agents=account._query('extraAgents'),account_mode=account._query('userAbstraction'),account_rate=account._query('userRateLimit'))
 own_history=history(TEAM)
 result['own_historical_orders']=dict(rows=own_history,row_count=len(own_history),possibly_truncated=len(own_history)==2000,matched_original_cloid=[x for x in own_history if '0xac0eea156fcec80986dd67c9057b6ded' in json.dumps(x)])
 contexts=market.get_asset_contexts();result['context_observed_ms']=client.clock_ms()
 for symbol in sorted(client.markets):
  spec=client.market(symbol);book=market.get_orderbook(symbol);active=account._query('activeAssetData',coin=symbol);ctx=contexts[symbol]
  mark=D(ctx['markPx']);step=spec.size_step;bid=book.bids[0];ask=book.asks[0];a=depth_capacity(book,'BUY');b=depth_capacity(book,'SELL')
  q=floor_quantity(spec,min(a['best_quantity']*D('.1'),b['best_quantity']*D('.1'),a['raw_l2_quantity']*D('.1'),b['raw_l2_quantity']*D('.1'),D(active['maxTradeSzs'][0]),D(10000)/ask.price))
  result['markets'].append(dict(symbol=symbol,spec=asdict(spec),observed_ms=client.clock_ms(),book=asdict(book),active_asset=active,context=ctx,one_lot_mark_notional=str(step*mark),minimum_eligible_mark_exclusive=str(D(10)/step),all_correct_long_stop_limits_below_minimum=step*mark<=10,reason='SELL stop trigger below current mark and execution limit below trigger implies one-lot stop value strictly below one-lot mark value',liquidity_only_quantity=str(q),liquidity_only_notional=str(q*ask.price),qualified_unattended_notional='0'))
  save()
 result['final_readbacks']=[]
 for _ in range(2):
  start=max(0,truth.last_window[1]-60000);reconciler.recover(truth,start_ms=start)
  original_status=account._query('orderStatus',oid='0xac0eea156fcec80986dd67c9057b6ded');before=account.get_positions();orders=account.get_frontend_open_orders();after=account.get_positions()
  if before!=after:raise ExchangeError('FINAL_POSITION_CHANGED')
  result['final_readbacks'].append(dict(observed_ms=client.clock_ms(),source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',team=TEAM,original_order_status=original_status,positions=[asdict(x) for x in after.values()],orders=orders,ready=not truth.reasons));save()
 result.update(account_final=truth.report(),status='BOUNDED_AUDIT_COMPLETE',terminal_flat=len(result['final_readbacks'])==2 and all(r['ready'] and not r['positions'] and not r['orders'] for r in result['final_readbacks']))
except Exception as exc:
 from exchange.terminal_recovery import exception_evidence
 result.update(status='INCOMPLETE_REQUIRES_REVIEW',error=exception_evidence(exc));result['errors'].append(str(exc))
finally:
 timer.cancel();result.update(finished_ms=client.clock_ms(),source_hash_after=active_source_hash(ROOT),requests=len(transport.records),rate_report=rates.report(),sqlite_integrity=j.db.execute('PRAGMA integrity_check').fetchone()[0]);save();client.close();j.close()
print(json.dumps({k:result.get(k) for k in ('status','error','requests','candidate_stop_count','native_records','terminal_flat')},default=str,indent=2))
raise SystemExit(0 if result.get('status')=='BOUNDED_AUDIT_COMPLETE' else 1)
