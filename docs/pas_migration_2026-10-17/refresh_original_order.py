"""Bounded unsigned original par identity check. It cannot resolve absence as rejection."""
from pathlib import Path
from dataclasses import asdict
import json,threading,sys,time
OUT=Path(__file__).resolve().parent/'original_order_readback';ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
from exchange.hyperliquid_client import RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM
OUT.mkdir(exist_ok=False)
j=ExecutionJournal(OUT/'public.sqlite',session_id='public:original-cloid-readback',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65
transport=ReadOnlyReceipts(RequestsInfoTransport(),OUT/'info_receipts.jsonl')
c=SerializedPublicClient(transport,rate_limits=rates);stop=threading.Event();timer=threading.Timer(120,stop.set);c.read_cancel_event=stop;timer.start()
r=dict(source_hash=active_source_hash(ROOT),signatures=0,exchange_writes=0,cloid='0xac0eea156fcec80986dd67c9057b6ded',nonce=1792217834069,original_dex='par',readbacks=[],resolution='UNKNOWN_PRESERVED')
try:
 c.startup();a=HyperliquidAccount(c,TEAM)
 for _ in range(2):
  status=a._query('orderStatus',oid=r['cloid']);before=a.get_positions();orders=a.get_frontend_open_orders();after=a.get_positions()
  r['readbacks'].append(dict(observed_ms=c.clock_ms(),source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',order_status=status,
   positions=[asdict(x) for x in after.values()],orders=orders,stable=before==after))
 r['status']='READBACK_COMPLETE'
except Exception as exc:r.update(status='READBACK_INCOMPLETE',error=str(exc))
finally:
 timer.cancel();r.update(observed_ms=c.clock_ms(),source_hash_after=active_source_hash(ROOT),journal_integrity=j.db.execute('PRAGMA integrity_check').fetchone()[0]);atomic_json(OUT/'readback.json',r);c.close();j.close()
print(json.dumps(r,indent=2,default=str))
