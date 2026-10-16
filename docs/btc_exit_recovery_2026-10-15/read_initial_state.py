"""Fresh read-only account and executable-book snapshot; no signer or orders."""
from pathlib import Path
from dataclasses import asdict
import json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.execution_journal import ExecutionJournal
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.reliability_policy import load_reliability_policy
from exchange.testnet_certification import TEAM
from exchange.paper_operations import atomic_json,active_source_hash
OUT=Path(__file__).resolve().parent/'initial_read_only';OUT.mkdir(exist_ok=False)
j=ExecutionJournal(OUT/'account.sqlite',session_id='exit-only-initial-read',team_address=TEAM)
policy,_,_=load_reliability_policy(ROOT/'configs/reliability_policy.json');rates=HyperliquidRateLimitManager(j,policy=policy);rates.read_budget_wait_seconds=65
c=HyperliquidClient(rate_limits=rates);r=dict(scope='READ_ONLY',signatures=0,orders_submitted=0,source_hash=active_source_hash(ROOT))
try:
 c.startup();a=HyperliquidAccount(c,TEAM);market=HyperliquidMarketData(c)
 before=a.get_positions();orders=a.get_frontend_open_orders();end=c.clock_ms()
 fills=a.get_fills(start_ms=1792039502353,end_ms=end);funding=a.get_funding(1792039590641,end)
 fees=a._query('userFees');active=a._query('activeAssetData',coin='par:BTC');status=a._query('orderStatus',oid='0x8e73fd40fceb5abb949215079466cb0b')
 contexts=market.get_asset_contexts();book=market.get_orderbook('par:BTC');after=a.get_positions()
 r.update(observed_ms=c.clock_ms(),positions_before=[asdict(p) for p in before.values()],positions_after=[asdict(p) for p in after.values()],orders=orders,fills=[asdict(f) for f in fills],funding=[asdict(f) for f in funding],funding_through_ms=end,fees=fees,active=active,entry_status=status,book=asdict(book),asset_context=contexts['par:BTC'],spec=asdict(c.market('par:BTC')),rates=rates.report())
finally:c.close();j.close();atomic_json(OUT/'report.json',r)
print(json.dumps({k:r.get(k) for k in ['observed_ms','positions_after','orders','funding','book']},indent=2)[:2500])
