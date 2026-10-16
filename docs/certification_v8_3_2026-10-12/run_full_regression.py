"""Offline full regression with immutable source receipt. No HTTP or actual-wallet signer."""
import hashlib,json,subprocess,time,sys,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
out=Path(__file__).resolve().parent/'regression_release'
out.mkdir(exist_ok=False)
receipt=out/'test_receipt.json'
if receipt.exists():raise RuntimeError('PRESERVE_EXISTING_TEST_RECEIPT')
r={'started_unix':time.time(),'source_hash':active_source_hash(ROOT),'scope':'Full offline repository regression; V8.3 all-ten one-lot price, depth, size, capacity, read-only composition and unchanged partial-close/production safeguards; prior baseline 1487; no exchange submissions'}
atomic_json(receipt,r)
checks={}
for name,script in [('strategy_freeze','scripts/check_strategy_freeze.py'),('phase0','scripts/phase0_check.py')]:
 p=subprocess.run([sys.executable,script],cwd=ROOT,capture_output=True,text=True)
 checks[name]={'exit_code':p.returncode,'result':json.loads(p.stdout) if p.returncode==0 else p.stderr}
r['checks_before']=checks
xml=out/'regression.xml'
command=[sys.executable,'-m','pytest',*[str(p.relative_to(ROOT)) for p in sorted((ROOT/'algo-trading-bot').glob('test_*.py'))],'-q','--tb=short','-o','junit_family=xunit1','--junitxml='+str(xml)]
with (out/'regression.log').open('w') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
totals={k:0 for k in ('tests','failures','errors','skipped')}
for suite in ET.parse(xml).getroot().iter('testsuite'):
 for k in totals:totals[k]+=int(suite.attrib.get(k,0))
r.update(finished_unix=time.time(),exit_code=p.returncode,source_hash_after=active_source_hash(ROOT),totals=totals,xml_sha256=hashlib.sha256(xml.read_bytes()).hexdigest())
r['passed']=p.returncode==0 and r['source_hash']==r['source_hash_after'] and all(x['exit_code']==0 for x in checks.values())
atomic_json(receipt,r);print(json.dumps(r,indent=2))
raise SystemExit(p.returncode)
