"""Read-only comparison of original identities, nonce, causal records and certificate."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.qualification_intent_recovery import verified_qualification_view,ORIGINAL_CLOID,ORIGINAL_SOURCE
from exchange.paper_operations import atomic_json,active_source_hash
from exchange.execution_journal import fingerprint
cloid='0xac0eea156fcec80986dd67c9057b6ded';mandate='59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea';nonce=1792217834069
old=json.loads((ROOT/'docs/practice_recovery_2026-10-17/original_local_evidence.json').read_text())
path=ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
 names=[x[1] for x in db.execute('PRAGMA table_info(intents)')]
 raw=dict(zip(names,db.execute('SELECT * FROM intents WHERE cloid=?',(cloid,)).fetchone()))
 view=verified_qualification_view(db)
 causal=[dict(seq=s,timestamp_ms=t,kind=k,data=json.loads(v)) for s,t,k,v in db.execute('SELECT seq,timestamp_ms,kind,data FROM events')
  if (cloid in v or mandate in v or raw['created_ms']-5000<=t<=raw['updated_ms']+1000)]
 claims=db.execute('SELECT value FROM controls WHERE name=?',('certification_transmissions:'+mandate,)).fetchone()
 boundary=[e for e in causal if e['kind']=='QUALIFICATION_TRANSPORT_BOUNDARY' and e['data'].get('cloid')==cloid]
 result=dict(verdict='BLOCKED_EXTERNAL_EVIDENCE',observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),
  original_cloid=cloid,original_nonce=nonce,original_mandate=mandate,original_signing_source='88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f',
  earlier_certified_cloid=ORIGINAL_CLOID,earlier_signing_source=ORIGINAL_SOURCE,earlier_certificate_applies_to_newer=False,
  raw_row_unchanged=raw==old['original_row'],raw_row=raw,effective_newer_unknown=[r for r in view['intents'] if r['cloid']==cloid],
  prior_verified_resolutions=view['resolutions'],recorded_transmission_claims=json.loads(claims[0]) if claims else [],
  original_boundary_records=boundary,causal_events=causal,reconstructed_age_ms=5526,
  reconstructed_age_is_original_causal_record=False,positive_terminal_order_record=None,
  new_certificate_applied=False,nonce_reset=False,original_row_changed=False,
  note='Current source logging fixes do not backfill original telemetry or prove rejection. unknownOid and empty current position/order snapshots are not conclusive non-transmission evidence.')
atomic_json(OUT/'unknown_forensic_verdict.json',result)
print(json.dumps({k:result[k] for k in ['verdict','raw_row_unchanged','earlier_certificate_applies_to_newer','original_boundary_records','recorded_transmission_claims']},indent=2))
