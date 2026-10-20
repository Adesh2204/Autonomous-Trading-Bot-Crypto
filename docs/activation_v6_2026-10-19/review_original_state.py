"""Read-only targeted consumed-attempt and original-UNKNOWN disposition."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.configuration_isolation import local_evidence,CLOID,INVOCATION,INTENT,NONCE
from exchange.execution_journal import fingerprint
from exchange.paper_operations import active_source_hash,atomic_json
history=json.loads((O/'public_audit_final/audit.json').read_text())
with sqlite3.connect((R/'runtime/testnet/anchorium-bot-1/qualification.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
 db.row_factory=sqlite3.Row
 row=dict(db.execute('select * from intents where cloid=?',(CLOID,)).fetchone())
 invocation=json.loads(db.execute('select value from controls where name=?',(INVOCATION,)).fetchone()[0])
 marker=json.loads(db.execute('select value from controls where name=?',('native_qualification_attempted',)).fetchone()[0])
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(R),original_cloid=CLOID,intent_key=INTENT,
 original_nonce=NONCE,original_row_hash=fingerprint(row),original_state=row['state'],original_oid=row.get('oid'),
 local=local_evidence(R),invocation=invocation,consumed_marker_record_status='REDACTED_LITERAL_PRESERVED' if marker=='[REDACTED]' else 'PRESENT_PRESERVED',
 consumed_marker_hash=fingerprint(marker),fresh_readbacks=history['final_readbacks'],
 bounded_history=dict(rows=history['own_historical_orders']['row_count'],possibly_truncated=history['own_historical_orders']['possibly_truncated'],matches=history['own_historical_orders']['matched_original_cloid']),
 status='HISTORICAL_OUTCOME_UNKNOWN_PRESERVED',non_transmission_proved=False,original_wire_failure_proof_available=False,
 native_attempt_reset=False,qualification_granted=False,order_authority=False,signatures_created=0,exchange_writes=0,
 disposition='No terminal status or matching historical order was returned. Two fresh flat readbacks prove current observed flatness only. The consumed attempt and UNKNOWN remain. Exact accepted configuration-only isolation is available; trading/qualification barriers are unchanged.',
 source_reconstruction='Prior forensic recovery is partial; no new complete historical source or causal wire proof was supplied.',
 proof_refs=['public_audit_final/audit.json','configuration_review_final/configuration_isolation/configuration_isolation.json','../activation_v5_2_2026-10-19/targeted_forensic.json'])
atomic_json(O/'original_state_review.json',r)
print(json.dumps({k:r[k] for k in ('status','original_state','original_oid','non_transmission_proved','native_attempt_reset','order_authority')},indent=2))
