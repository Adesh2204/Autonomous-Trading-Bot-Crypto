"""Verify scope and original evidence using read-only SQLite connections."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
b=json.loads((OUT/'baseline.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
allowed={'algo-trading-bot/exchange/native_qualification.py','algo-trading-bot/exchange/native_qualification_runtime.py',
'algo-trading-bot/exchange/qualification_protection.py','algo-trading-bot/exchange/native_qualification_permissions.py',
'scripts/run_native_qualification.py','algo-trading-bot/test_par_native_workflow_repair.py',
'algo-trading-bot/test_native_qualification.py','algo-trading-bot/test_native_price_corridor.py'}
files=list((ROOT/'scripts').glob('*.py'))+[p for p in (ROOT/'algo-trading-bot').rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)]
current={str(p.relative_to(ROOT)):sha(p) for p in files}
changes=[dict(path=p,previous_sha256=b['files'].get(p),sha256=v) for p,v in current.items() if b['files'].get(p)!=v]
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),baseline_source=b['source_hash'],changes=changes,
 scope_violations=[x['path'] for x in changes if x['path'] not in allowed],protected={},databases={})
for p,v in b['protected'].items():r['protected'][p]=dict(matching=sha(ROOT/p)==v,sha256=sha(ROOT/p))
for name,baseline in b['databases'].items():
 path=ROOT/'runtime/testnet/anchorium-bot-1'/(name+'.sqlite')
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
  digest=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
  record=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],dump_sha256=digest,unchanged=digest==baseline['dump_sha256'])
  if name=='qualification':
   record['original_unknown']=[list(x) for x in db.execute("SELECT cloid,state,oid,request FROM intents WHERE cloid='0xac0eea156fcec80986dd67c9057b6ded'")]
   record['certificate_checksums']=[list(x) for x in db.execute('SELECT intent_key,checksum FROM nontransmission_resolutions')]
   record['checkpoint_integrity']=all(fingerprint(json.loads(data))==check for data,check in db.execute('SELECT data,checksum FROM recovery_snapshots'))
  if name=='nonces':record['nonce_rows']=[list(x) for x in db.execute('SELECT * FROM nonces')]
  r['databases'][name]=record
r['passed']=not r['scope_violations'] and all(x['matching'] for x in r['protected'].values()) and all(x['unchanged'] and x['integrity']=='ok' for x in r['databases'].values()) and r['databases']['qualification']['checkpoint_integrity']
r['pas_strategy_capital_authorization_limits_unchanged']=not r['scope_violations'] and all(current.get(p)==v for p,v in b['files'].items() if p not in allowed)
atomic_json(OUT/'preservation_receipt.json',r)
print(json.dumps(dict(passed=r['passed'],source_hash=r['source_hash'],scope_violations=r['scope_violations'],source_files_changed=len(changes))))
raise SystemExit(0 if r['passed'] else 1)
