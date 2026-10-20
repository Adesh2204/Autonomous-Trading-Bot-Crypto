"""Bounded public PAS order/fill observation; third-party evidence, no team certification."""
from pathlib import Path
import json,sys,time,threading
from decimal import Decimal as D
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
from exchange.hyperliquid_client import RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.reliability_policy import RequestPriority
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM
out=O/'public_route_probe_retry';out.mkdir(exist_ok=False)
j=ExecutionJournal(out/'public.sqlite',session_id='public:pas-routes',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
class HistoryReceipts(ReadOnlyReceipts):
 def __call__(self,payload,*,cancel_event=None,progress=None):
  if payload.get('type')!='historicalOrders':return super().__call__(payload,cancel_event=cancel_event,progress=progress)
  if set(payload)!={'type','user'} or payload['user'] not in allowed_history_users:raise RuntimeError('EXACT_SELECTED_PUBLIC_HISTORY_USER_REQUIRED')
  record=dict(request=payload,sent_ms=time.time_ns()//1000000)
  try:record['response']=self.transport(payload,cancel_event=cancel_event,progress=progress);return record['response']
  except Exception as e:record['error']=str(e);raise
  finally:
   record['received_ms']=time.time_ns()//1000000
   with self.lock:self.file.write(json.dumps(record)+'\n');self.file.flush()
allowed_history_users=set()
transport=HistoryReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl')
c=SerializedPublicClient(transport,rate_limits=rates,venue='pas');stop=threading.Event();timer=threading.Timer(180,stop.set);c.read_cancel_event=stop;timer.start()
r=dict(source_hash=active_source_hash(R),started_ms=c.clock_ms(),scope='PUBLIC_THIRD_PARTY_VENUE_BEHAVIOR_ONLY_NOT_TEAM_QUALIFICATION',users=[],markets={},team_certified=False,signatures_created=0,exchange_writes=0)
try:
 c.startup();users=[]
 for s in ('pas:BTC','pas:EWY'):
  trades=c.post_info('recentTrades',coin=s);r['markets'][s]=dict(recent_trades=trades)
  for row in reversed(trades):
   for user in row.get('users',[]):
    if user.lower()!=TEAM.lower() and user not in users:users.append(user)
 allowed_history_users.update(users[:2])
 for user in users[:2]:
  # The documented historicalOrders schema has user only. This isolated
  # /info read reserves its maximum 2000-row charge before transmission.
  rates.wait_for_read_budget(120,max_wait_seconds=75)
  rates.reserve_info('historicalOrders',priority=RequestPriority.DECISION,response_weight=100)
  history=transport(dict(type='historicalOrders',user=user),cancel_event=stop)
  if not isinstance(history,list) or len(history)>2000:raise RuntimeError('BOUNDED_HISTORY_REQUIRED')
  a=HyperliquidAccount(c,user);now=c.clock_ms();fills=a._query('userFillsByTime',startTime=now-86400000,endTime=now)
  pas_orders=[v for v in history if v.get('order',{}).get('coin','').startswith('pas:')]
  pas_fills=[v for v in fills if v.get('coin','').startswith('pas:')]
  r['users'].append(dict(public_user=user,history_rows=len(history),history_may_be_truncated=len(history)==2000,
   pas_orders=pas_orders,pas_fills=pas_fills,observed_ms=c.clock_ms(),
   trigger_records=[v for v in pas_orders if v.get('order',{}).get('isTrigger') is True],
   subminimum_reduce_only_records=[v for v in pas_orders if v.get('order',{}).get('reduceOnly') is True
    and D(v['order'].get('origSz','0'))*D(v['order'].get('limitPx','0'))<10]))
 r['status']='BOUNDED_PUBLIC_ROUTE_REVIEW_COMPLETE'
except Exception as e:r.update(status='INCOMPLETE',error=str(e))
finally:
 r.update(finished_ms=c.clock_ms(),source_hash_after=active_source_hash(R),journal_integrity=j.db.execute('pragma integrity_check').fetchone()[0])
 c.close();j.close();timer.cancel();atomic_json(out/'probe.json',r)
print(json.dumps(dict(status=r['status'],users=len(r['users']),trigger_records=sum(len(v['trigger_records']) for v in r['users']),subminimum_records=sum(len(v['subminimum_reduce_only_records']) for v in r['users']),team_certified=False),indent=2))
