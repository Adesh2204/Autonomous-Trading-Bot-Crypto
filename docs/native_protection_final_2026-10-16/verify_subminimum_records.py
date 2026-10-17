"""Independently read exact public subminimum trigger IDs; never submits orders."""
from pathlib import Path
from decimal import Decimal as D
import json,sys,time,threading
P=Path(__file__).resolve().parent;ROOT=P.parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.public_quant_operator import ReadOnlyReceipts
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.execution_journal import ExecutionJournal
from exchange.testnet_certification import TEAM
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.paper_operations import atomic_json,active_source_hash
from venue_config import require_paper_migration
require_paper_migration()
out=P/'subminimum_readback_2026-10-17';out.mkdir(exist_ok=False)
j=ExecutionJournal(out/'public.sqlite',session_id='public:subminimum-native-readback',team_address=TEAM)
rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
previous=json.loads((P/'public_evidence/audit.json').read_text())
# Carry the entire last observed rolling usage forward conservatively so a
# separate read-only diagnostic cannot evade the IP reserve through a restart.
rates.weights.append((previous['finished_ms'],previous['rate_report']['ip_weight']))
transport=ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl');client=HyperliquidClient(transport,rate_limits=rates)
cancel=threading.Event();timer=threading.Timer(180,cancel.set);client.read_cancel_event=cancel;timer.start()
r=dict(started_ms=client.clock_ms(),source_hash=active_source_hash(ROOT),signatures=0,exchange_writes=0,records=[],errors=[],scope='EXACT_PUBLIC_ORDER_STATUS_ONLY_NOT_TEAM_QUALIFICATION')
try:
 client.startup()
 for candidate in json.loads((P/'subminimum_candidates.json').read_text()):
  a=HyperliquidAccount(client,candidate['user']);reply=a._query('orderStatus',oid=candidate['oid']);record=dict(candidate=candidate,order_status=reply,observed_ms=client.clock_ms(),closing_qualification=False)
  if reply.get('status')=='order':
   state=reply['order'];o=state['order'];spec=client.market(o['coin']);quantity=D(o['origSz']);notional=quantity*D(o['limitPx'])
   record.update(native_type=o['orderType'],position_tpsl=o.get('isPositionTpsl'),quantity=str(quantity),lot_count=str(quantity/spec.size_step),original_limit_notional=str(notional),direct_status=state['status'],identity_matching=o['oid']==candidate['oid'] and o['coin']==candidate['symbol'] and quantity==D(candidate['quantity']),historical_open_observed='open' in candidate['statuses'],reduce_only=o.get('reduceOnly'),is_trigger=o.get('isTrigger'),children=state.get('children',o.get('children',[])))
   record['acceptance_evidence']=record['identity_matching'] and record['historical_open_observed'] and o.get('reduceOnly') is True and o.get('isTrigger') is True and notional<10 and state['status'] in {'canceled','reduceOnlyCanceled','open','triggered','filled'}
   if state['status'] in {'triggered','filled'}:record['requires_full_linked_fill_audit']=True
  r['records'].append(record);atomic_json(out/'audit.json',r)
 r['status']='EXACT_READBACK_COMPLETE'
except Exception as e:
 from exchange.terminal_recovery import exception_evidence
 r.update(status='INCOMPLETE',error=exception_evidence(e));r['errors'].append(str(e))
finally:
 timer.cancel();r.update(finished_ms=client.clock_ms(),source_hash_after=active_source_hash(ROOT),rate_report=rates.report(),sqlite_integrity=j.db.execute('PRAGMA integrity_check').fetchone()[0]);atomic_json(out/'audit.json',r);client.close();j.close()
print(json.dumps(dict(status=r['status'],errors=r['errors'],records=[{k:v.get(k) for k in ('quantity','lot_count','native_type','original_limit_notional','direct_status','identity_matching','acceptance_evidence','closing_qualification')} for v in r['records']]),indent=2))
raise SystemExit(0 if r['status']=='EXACT_READBACK_COMPLETE' else 1)
