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
r={'started_unix':time.time(),'source_hash':active_source_hash(ROOT),'scope':'Full final-source practice-native repair regression; 2850 preserved baseline plus 39 native proof-export, position/readback, causal logging, durable barrier, calendar/provenance and preparation tests; offline ephemeral signatures only, no actual-wallet signatures or exchange actions'}
dependency=ROOT/'docs/certification_v8_6_2026-10-12/protection_evidence.py'
r['evidence_classifier_sha256']=hashlib.sha256(dependency.read_bytes()).hexdigest()
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
r['evidence_classifier_sha256_after']=hashlib.sha256(dependency.read_bytes()).hexdigest()
r['previous_evidence_classifier_sha256']=hashlib.sha256((ROOT/'docs/certification_v8_5_2026-10-12/public_evidence.py').read_bytes()).hexdigest()
r['baseline_minimum']=2850
r['expected_minimum']=2889
checks_after={}
for name,script in [('strategy_freeze','scripts/check_strategy_freeze.py'),('phase0','scripts/phase0_check.py')]:
 check=subprocess.run([sys.executable,script],cwd=ROOT,capture_output=True,text=True)
 checks_after[name]={'exit_code':check.returncode,'result':json.loads(check.stdout) if check.returncode==0 else check.stderr}
r['checks_after']=checks_after
r['passed']=totals['tests']>=2889 and totals['failures']==0 and totals['errors']==0 and totals['skipped']==0 and r['previous_evidence_classifier_sha256']=='9c95b59054aed2adc38a41f5f65b0a65c314ac4cb3b29ea437a88d2b6dfcf8e0' and r['evidence_classifier_sha256']==r['evidence_classifier_sha256_after'] and p.returncode==0 and r['source_hash']==r['source_hash_after'] and all(x['exit_code']==0 and x['result'].get('passed') is True for x in [*checks.values(),*checks_after.values()])
import importlib.metadata
r['requirements_sha256']=hashlib.sha256((ROOT/'algo-trading-bot/requirements.txt').read_bytes()).hexdigest()
r['runtime_versions']={line.split('==')[0]:importlib.metadata.version(line.split('==')[0]) for line in (ROOT/'algo-trading-bot/requirements.txt').read_text().splitlines() if '==' in line}
atomic_json(receipt,r);print(json.dumps(r,indent=2))
raise SystemExit(0 if r['passed'] else 1)
