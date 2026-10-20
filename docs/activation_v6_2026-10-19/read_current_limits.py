"""Bounded public PAS OI, fee, margin and two-sided book evidence; no signer."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal as D
import json,sys,threading
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
from exchange.hyperliquid_client import RequestsInfoTransport
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM
from exchange.capital_allocation import validate_book,depth_capacity
from exchange.long_session import sha
name=sys.argv[1] if len(sys.argv)>1 else 'current_limits'
if name not in {'current_limits','current_limits_final'}:raise SystemExit('FIXED_LOCAL_OUTPUT_NAME_REQUIRED')
out=O/name;out.mkdir(exist_ok=False)
j=ExecutionJournal(out/'public.sqlite',session_id='public:pas-v6-limits',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
c=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl'),rate_limits=rates,venue='pas')
stop=threading.Event();timer=threading.Timer(180,stop.set);c.read_cancel_event=stop;timer.start()
r=dict(status='READING',source_hash=active_source_hash(R),started_ms=c.clock_ms(),markets={},signing_authority='NONE',signatures_created=0,exchange_writes=0)
try:
 c.startup();a=HyperliquidAccount(c,TEAM);m=HyperliquidMarketData(c)
 r['limits']=c.post_info('perpDexLimits',dex='pas');r['limits_observed_ms']=c.clock_ms()
 r['contexts']=m.get_asset_contexts();r['contexts_observed_ms']=c.clock_ms()
 r['fees']=a._query('userFees');r['fees_observed_ms']=c.clock_ms()
 r['account_rate']=a._query('userRateLimit');r['account_rate_observed_ms']=c.clock_ms()
 r['total_oi_notional']=str(sum((D(x['openInterest'])*D(x['oraclePx']) for x in r['contexts'].values()),D(0)))
 r['effective_global_cap']=str(min(D('50000000'),D(r['limits']['totalOiCap'])))
 caps=dict(r['limits']['coinToOiCap'])
 for s in ('pas:BTC','pas:EWY'):
  book=m.get_orderbook(s);at=c.clock_ms();validate_book(book,at)
  active=a._query('activeAssetData',coin=s);active_ms=c.clock_ms()
  cap=D(caps.get(s,caps.get(s.split(':')[1])))
  r['markets'][s]=dict(spec=asdict(c.market(s)),book=asdict(book),book_observed_ms=at,active=active,active_observed_ms=active_ms,
   buy_depth=depth_capacity(book,'BUY'),sell_depth=depth_capacity(book,'SELL'),context=r['contexts'][s],
   effective_market_cap=str(min(cap,D('10000000'))),reported_market_cap=str(cap))
 r['status']='READ_ONLY_LIMITS_COMPLETE'
except Exception as e:r.update(status='INCOMPLETE',error=str(e))
finally:
 r.update(finished_ms=c.clock_ms(),source_hash_after=active_source_hash(R),journal_integrity=j.db.execute('pragma integrity_check').fetchone()[0])
 c.close();j.close();timer.cancel();r['receipt_sha256']=sha(out/'info_receipts.jsonl');atomic_json(out/'limits.json',r)
print(json.dumps({k:r.get(k) for k in ('status','error','total_oi_notional','effective_global_cap')},indent=2))
raise SystemExit(0 if r['status']=='READ_ONLY_LIMITS_COMPLETE' else 1)
