"""Inspect local durable records after completion; never reset or sign anything."""
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_checkpoint import unpack
from exchange.paper_operations import active_source_hash

receipt=json.loads((OUT/'post_configuration_paper_receipt.json').read_text())
assert receipt['exit_code']==0 and receipt['final_health']['status']=='STOPPED'
state=Path(receipt['state_directory'])
f=(state/'owner.lock').open('a+')
fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
fcntl.flock(f.fileno(),fcntl.LOCK_UN)
f.close()
checks={}
for rel in ['paper.sqlite','backups/paper-latest.sqlite']:
 with sqlite3.connect((state/rel).resolve().as_uri()+'?mode=ro',uri=True) as c:
  integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
  raw,sha=c.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
  value=unpack(json.loads(raw))
  checks[rel]=dict(integrity=integrity,checksum_matches=hashlib.sha256(raw.encode()).hexdigest()==sha,
    clean_shutdown=value['clean'],source_hash=value['identity']['active_source_hash'])
counts={}
for label,path in [('configuration',ROOT/'runtime/testnet/anchorium-bot-1/configuration.sqlite'),('public_paper',state/'public_requests.sqlite')]:
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as c:
  counts[label]={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ['intents','signed_management','api_actions']}
  if label=='configuration':
   counts[label]['management_states']=c.execute('SELECT state,count(*) FROM signed_management GROUP BY state').fetchall()
   counts[label]['configuration_nonces']=c.execute("SELECT count(*) FROM events WHERE kind='NONCE_GENERATED'").fetchone()[0]
   counts[label]['configuration_action_kinds']=c.execute('SELECT kind,count(*) FROM api_actions GROUP BY kind').fetchall()
with sqlite3.connect((ROOT/'runtime/testnet/anchorium-bot-1/nonces.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as c:
 nonce_health=c.execute('SELECT count(*) FROM nonce_health').fetchone()[0]
 highwater=c.execute('SELECT signer,last FROM nonces').fetchall()
result=dict(scope='LOCAL_COMPLETION_AND_DURABLE_RECORDS',active_source_hash=active_source_hash(ROOT),
 paper_owner_lease_released=True,checkpoint_integrity_ok=all(v['integrity']=='ok' and v['checksum_matches'] and v['clean_shutdown'] for v in checks.values()),
 checkpoints=checks,counters=counts,nonce_error_latches=nonce_health,nonce_highwater_public=highwater,
 actual_orders_submitted=0,actual_configuration_submissions=json.loads((OUT/'leverage_applied_paced.json').read_text())['configuration_actions_submitted'],
 action_reservations_explanation='Local api_actions includes the first pre-transmission reservation. Count actual submissions from the immutable transport receipt, not reservations.')
with (OUT/'operating_checks_after.json').open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
