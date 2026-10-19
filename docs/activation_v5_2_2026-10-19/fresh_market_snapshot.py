"""Bounded unsigned final two-market snapshot. No signing imports or action endpoint."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal as D
import sys,json,time,threading
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent/'final_market_read';O.mkdir(exist_ok=False)
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
from exchange.hyperliquid_client import RequestsInfoTransport
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.capital_allocation import depth_capacity,floor_quantity
from exchange.pas_economics import fee_scenarios
from exchange.testnet_certification import TEAM,API
from exchange.entry_scope import PAS_ENTRY_MARKETS
j=ExecutionJournal(O/'public.sqlite',session_id='public:v5-2-final-market',team_address=TEAM);rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
c=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),O/'info_receipts.jsonl'),rate_limits=rates,venue='pas');stop=threading.Event();timer=threading.Timer(120,stop.set);c.read_cancel_event=stop;timer.start()
v=dict(source_hash=active_source_hash(R),started_ms=c.clock_ms(),team_wallet=TEAM,api_wallet=API,signatures_created=0,exchange_writes=0,signing_authority='NONE',markets={},flat_readbacks=[])
try:
 c.startup();a=HyperliquidAccount(c,TEAM);market=HyperliquidMarketData(c)
 fees=a._query('userFees');v['fee_observed_ms']=c.clock_ms();v['fees']=fees;v['agents']=a._query('extraAgents');v['account_mode']=a._query('userAbstraction');v['spot']=c.post_info('spotClearinghouseState',user=TEAM)
 for s in sorted(PAS_ENTRY_MARKETS):
  context=market.get_asset_contexts()[s];context_ms=c.clock_ms();active=a._query('activeAssetData',coin=s);active_ms=c.clock_ms();book=market.get_orderbook(s);spec=c.market(s);now=c.clock_ms()
  buy,sell=depth_capacity(book,'BUY'),depth_capacity(book,'SELL')
  q=floor_quantity(spec,min(buy['best_quantity']*D('.1'),sell['best_quantity']*D('.1'),buy['raw_l2_quantity']*D('.1'),sell['raw_l2_quantity']*D('.1')))
  v['markets'][s]=dict(spec=asdict(spec),context=context,context_ms=context_ms,active_asset=active,active_ms=active_ms,book=asdict(book),observed_ms=now,
   displayed_book_only_quantity=str(q),displayed_book_only_notional=str(q*book.asks[0].price),account_constrained_quantity='0' if min(D(x) for x in active['maxTradeSzs'])==0 else 'NOT_QUALIFIED',authorized_executable_notional='0',signal='UNKNOWN_NO_FRESH_COMPLETED_HISTORY',
   fee_scenarios=fee_scenarios(book,context,{},quantity=q,base_taker_rate=fees['userCrossRate'],base_maker_rate=fees['userAddRate'],now_ms=now,context_ms=context_ms))
 for _ in range(2):
  before=a.get_positions();orders=a.get_frontend_open_orders();after=a.get_positions()
  v['flat_readbacks'].append(dict(observed_ms=c.clock_ms(),positions=[asdict(x) for x in after.values()],orders=orders,stable=before==after))
 v['terminal_flat']=all(not x['positions'] and not x['orders'] and x['stable'] for x in v['flat_readbacks']) and v['flat_readbacks'][0]['observed_ms']<v['flat_readbacks'][1]['observed_ms']
 v['status']='UNSIGNED_FINAL_MARKET_READ_COMPLETE'
except Exception as exc:v.update(status='READ_INCOMPLETE',error=str(exc))
finally:
 v.update(observed_ms=c.clock_ms(),source_hash_after=active_source_hash(R),journal_integrity=j.db.execute('pragma integrity_check').fetchone()[0]);timer.cancel();c.close();j.close();atomic_json(O/'snapshot.json',v)
print(json.dumps(v,default=str,indent=2))
