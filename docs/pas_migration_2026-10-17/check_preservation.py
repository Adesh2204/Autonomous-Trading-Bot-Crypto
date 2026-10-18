"""Read-only baseline, proof, SQLite checkpoint and nonce preservation audit."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time,subprocess
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
b=json.loads((OUT/'baseline.json').read_text())
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),protected={},databases={})
for name,expected in b['protected'].items():
 digest=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
 r['protected'][name]=dict(sha256=digest,matching=digest==expected)
for name,old in b['databases'].items():
 p=ROOT/'runtime/testnet/anchorium-bot-1'/(name+'.sqlite')
 with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
  dump=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
  record=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],dump_sha256=dump,unchanged=dump==old['dump_sha256'])
  if name=='qualification':
   rows=[dict(zip([d[0] for d in cur.description],row)) for cur in [db.execute('SELECT * FROM intents WHERE cloid=?',('0xac0eea156fcec80986dd67c9057b6ded',))] for row in cur]
   record['original_unknown']=rows
   record['checkpoint_integrity']=all(fingerprint(json.loads(data))==checksum for data,checksum in db.execute('SELECT data,checksum FROM recovery_snapshots'))
   record['unknown_preserved']=len(rows)==1 and rows[0]['state']=='UNKNOWN' and rows[0]['oid'] is None
  if name=='nonces':record['nonce_rows']=[list(x) for x in db.execute('SELECT * FROM nonces')]
  r['databases'][name]=record
r['passed']=all(x['matching'] for x in r['protected'].values()) and all(x['integrity']=='ok' and x['unchanged'] for x in r['databases'].values()) and r['databases']['qualification']['unknown_preserved'] and r['databases']['qualification']['checkpoint_integrity']
atomic_json(OUT/'preservation_receipt.json',r)
current={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['algo-trading-bot','scripts'] for p in (ROOT/folder).rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)}
changes=[dict(path=name,previous_sha256=b['files'].get(name),sha256=digest,kind='MODIFIED' if name in b['files'] else 'NEW') for name,digest in current.items() if b['files'].get(name)!=digest]
atomic_json(OUT/'source_change_manifest.json',dict(baseline_head=b['head'],baseline_source=b['source_hash'],final_source=r['source_hash'],changes=changes,signal_brain_unchanged=current['algo-trading-bot/signal_brain.py']==b['files']['algo-trading-bot/signal_brain.py']))
print(json.dumps(dict(passed=r['passed'],source_hash=r['source_hash'],changed_source_files=len(changes))))
raise SystemExit(0 if r['passed'] else 1)
