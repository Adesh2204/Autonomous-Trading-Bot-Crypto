from pathlib import Path
import hashlib,json,sqlite3,sys,time
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
b=json.loads((O/'baseline.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
expected=set(json.loads((O/'source_changes.json').read_text())['changes'][i]['path'] for i in range(14))
files=list((R/'scripts').glob('*.py'))+[p for p in (R/'algo-trading-bot').rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)]
c={str(p.relative_to(R)):sha(p) for p in files};changed={p for p,v in c.items() if b['files'].get(p)!=v}
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(R),starting_source=b['source_hash'],
 source_changes=sorted(changed),unexpected_source_changes=sorted(changed-expected),protected={},databases={},native_repairs={})
for p,v in b['protected'].items():r['protected'][p]=dict(matching=sha(R/p)==v,sha256=sha(R/p))
for p,v in b['databases'].items():
 with sqlite3.connect((R/p).resolve().as_uri()+'?mode=ro',uri=True) as d:
  digest=hashlib.sha256('\n'.join(d.iterdump()).encode()).hexdigest()
  r['databases'][p]=dict(integrity=d.execute('PRAGMA integrity_check').fetchone()[0],unchanged=digest==v['dump_sha256'],dump_sha256=digest)
  if p.endswith('anchorium-bot-1/qualification.sqlite'):
   r['original_unknown']=[list(x) for x in d.execute("SELECT cloid,state,oid,outcome FROM intents WHERE cloid='0xac0eea156fcec80986dd67c9057b6ded'")]
   r['native_invocation_controls']=[list(x) for x in d.execute("SELECT name,value FROM controls WHERE name='native_qualification_attempted' OR name LIKE 'native_qualification_invocation:%'")]
   r['certificate_checksums']=[list(x) for x in d.execute('SELECT intent_key,checksum FROM nontransmission_resolutions')]
for p in ['algo-trading-bot/exchange/native_qualification.py','algo-trading-bot/exchange/native_qualification_runtime.py','algo-trading-bot/exchange/qualification_protection.py','algo-trading-bot/exchange/native_qualification_permissions.py','scripts/run_native_qualification.py']:
 r['native_repairs'][p]=c[p]==b['files'][p]
r['all_original_journals_unchanged']=all(x['unchanged'] and x['integrity']=='ok' for x in r['databases'].values())
r['strategy_capital_nonce_policy_unchanged']=all(c.get(p)==v for p,v in b['files'].items() if p not in expected)
r['passed']=not r['unexpected_source_changes'] and all(x['matching'] for x in r['protected'].values()) and r['all_original_journals_unchanged'] and all(r['native_repairs'].values()) and r['strategy_capital_nonce_policy_unchanged']
(O/'preservation_receipt.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({k:r[k] for k in ('passed','source_hash','all_original_journals_unchanged','unexpected_source_changes')}))
raise SystemExit(0 if r['passed'] else 1)
