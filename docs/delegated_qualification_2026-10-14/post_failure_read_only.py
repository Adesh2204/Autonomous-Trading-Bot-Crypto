"""Read-only account observations after halt; no key, nonce or SDK construction."""
import json,sys,time,sqlite3
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.certification_runtime import CertificationRecovery
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.reliability_policy import load_reliability_policy
from exchange.paper_operations import atomic_json,active_source_hash
from exchange.testnet_certification import TEAM
OUT=Path(__file__).resolve().parent/'post_failure_read_only'
OUT.mkdir(exist_ok=False)
journal=ExecutionJournal(OUT/'account.sqlite',session_id='anchorium-delegated-post-halt-read-only',team_address=TEAM)
rate,_,_=load_reliability_policy(ROOT/'configs/reliability_policy.json')
rates=HyperliquidRateLimitManager(journal,policy=rate)
rates.read_budget_wait_seconds=65
client=HyperliquidClient(rate_limits=rates)
result=dict(scope='READ_ONLY_POST_HALT_ACCOUNT_OBSERVATION',exchange_actions_submitted=0,
    signatures_created=0,source_hash=active_source_hash(ROOT),snapshots=[])
try:
 client.startup();account=HyperliquidAccount(client,TEAM)
 with sqlite3.connect((ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite').as_uri()+'?mode=ro',uri=True) as db:
  row=db.execute('SELECT intent_key,cloid,oid FROM intents').fetchone()
 assert row is not None
 result['original_intent']=dict(intent_key=row[0],cloid=row[1],oid=row[2])
 recovery=CertificationRecovery(account,journal,initial_start_ms=0)
 for index in range(2):
  report=recovery.recover()
  before=account.get_positions();orders=account.get_frontend_open_orders()
  status=account._query('orderStatus',oid=row[1])
  fills=account._query('userFillsByTime',startTime=1791964441387,endTime=client.clock_ms(),aggregateByTime=False)
  after=account.get_positions()
  snap=dict(observed_ms=client.clock_ms(),positions_before=[asdict(x) for x in before.values()],
      positions_after=[asdict(x) for x in after.values()],orders=orders,original_order_status=status,
      fills_since_acceptance=fills,account_reconciliation=asdict(report),
      flat_observed=before==after and not after and not orders and report.ready)
  result['snapshots'].append(snap);atomic_json(OUT/'report.json',result)
  if index==0:time.sleep(2)
 result.update(final_flat_observed=all(s['flat_observed'] for s in result['snapshots']),
   actual_fill_verified=False,original_order_unknown_to_exchange=all(s['original_order_status'].get('status')=='unknownOid' for s in result['snapshots']),
   no_local_uncertainty_cleared=True,no_entry_retry=True,completed_ms=client.clock_ms())
 recovery.checkpoint(clean=True)
finally:
 client.close();journal.close();atomic_json(OUT/'report.json',result)
print(json.dumps({k:result.get(k) for k in ('final_flat_observed','actual_fill_verified','original_order_unknown_to_exchange','exchange_actions_submitted','signatures_created','completed_ms')},indent=2))
