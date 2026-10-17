"""Bounded unsigned terminal account proof after the approved worker stopped."""
from pathlib import Path
from dataclasses import asdict
import json,sys,time,threading
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from exchange.public_quant_operator import ReadOnlyReceipts
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.paper_operations import atomic_json,active_source_hash
from exchange.testnet_certification import TEAM
from venue_config import require_paper_migration
require_paper_migration()
run=OUT/'authorized_native_qualification';out=run/'terminal_reconciliation';out.mkdir(exist_ok=False)
old=[json.loads(x) for x in (run/'info_receipts.jsonl').read_text().splitlines()]
last=max(x['received_ms'] for x in old)
while time.time_ns()//1000000<last+65000:time.sleep(.25)
j=ExecutionJournal(out/'public.sqlite',session_id='public:post-native-preflight',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
c=HyperliquidClient(ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl'),rate_limits=rates)
cancel=threading.Event();timer=threading.Timer(180,cancel.set);timer.start();c.read_cancel_event=cancel
r=dict(started_ms=c.clock_ms(),source_hash=active_source_hash(ROOT),orders_submitted=0,signatures=0,readbacks=[])
try:
 c.startup();a=HyperliquidAccount(c,TEAM);truth=ExchangeTruthState();reconcile=HyperliquidReconciliation(a)
 reconcile.recover(truth,start_ms=0)
 for _ in range(2):
  reconcile.recover(truth,start_ms=max(0,truth.last_window[1]-60000))
  before=a.get_positions();orders=a.get_frontend_open_orders();after=a.get_positions()
  r['readbacks'].append(dict(observed_ms=c.clock_ms(),source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',positions=[asdict(x) for x in after.values()],orders=orders,ready=not truth.reasons and before==after))
 r.update(account=truth.report(),status='TERMINAL_ACCOUNT_READ_COMPLETE',terminal_flat=len(r['readbacks'])==2 and r['readbacks'][0]['observed_ms']<r['readbacks'][1]['observed_ms'] and all(x['ready'] and not x['positions'] and not x['orders'] for x in r['readbacks']))
except Exception as e:r.update(status='UNKNOWN',error=str(e),terminal_flat=False)
finally:
 timer.cancel();r.update(finished_ms=c.clock_ms(),source_hash_after=active_source_hash(ROOT),rate_report=rates.report(),sqlite_integrity=j.db.execute('PRAGMA integrity_check').fetchone()[0]);atomic_json(out/'audit.json',r);c.close();j.close()
print(json.dumps({k:r.get(k) for k in ['status','terminal_flat','readbacks','error']},indent=2));raise SystemExit(0 if r.get('terminal_flat') else 1)
