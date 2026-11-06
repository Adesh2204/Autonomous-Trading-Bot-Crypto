"""Run an actual offline source-matched release; never synthesize pass evidence."""
from pathlib import Path
import hashlib,importlib.metadata,json,os,subprocess,sys,time,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
OUT=Path(__file__).resolve().parent/'regression_release'
OUT.mkdir(exist_ok=True)
env=dict(os.environ,ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',
 GIT_CONFIG_COUNT='3',GIT_CONFIG_KEY_0='filter.lfs.process',GIT_CONFIG_VALUE_0='',
 GIT_CONFIG_KEY_1='filter.lfs.clean',GIT_CONFIG_VALUE_1='cat',GIT_CONFIG_KEY_2='filter.lfs.required',GIT_CONFIG_VALUE_2='false')
receipt=dict(started_unix=time.time(),source_hash=active_source_hash(ROOT),scope='All root test_*.py offline; no actual signer or exchange write; never a PAS qualification')
paths=sorted((ROOT/'algo-trading-bot').glob('test_*.py'))
receipt['test_paths']=[str(p.relative_to(ROOT)) for p in paths]
receipt['minimum_previous_test_count']=3321
receipt['requirements_sha256']=hashlib.sha256((ROOT/'algo-trading-bot/requirements.txt').read_bytes()).hexdigest()
receipt['runtime_versions']={line.split('==')[0]:importlib.metadata.version(line.split('==')[0]) for line in (ROOT/'algo-trading-bot/requirements.txt').read_text().splitlines() if '==' in line}
def checks(stage):
 result={}
 for name,script in [('strategy_freeze','scripts/check_strategy_freeze.py'),('phase0','scripts/phase0_check.py')]:
  p=subprocess.run([sys.executable,script],cwd=ROOT,env=env,capture_output=True,text=True)
  (OUT/(stage+'_'+name+'.log')).write_text(p.stdout+p.stderr)
  try:value=json.loads(p.stdout)
  except ValueError:value={'passed':False,'error':'INVALID_CHECK_OUTPUT'}
  result[name]=dict(exit_code=p.returncode,result=value)
 return result
receipt['checks_before']=checks('before')
atomic_json(OUT/'test_receipt.json',receipt)
if not all(x['exit_code']==0 and x['result'].get('passed') is True for x in receipt['checks_before'].values()):raise SystemExit('Required prechecks failed')
xml=OUT/'regression.xml'
command=[sys.executable,'-m','pytest',*receipt['test_paths'],'-q','--tb=short','-o','junit_family=xunit1','--junitxml='+str(xml)]
receipt['command']=command
with (OUT/'regression.log').open('w') as log:run=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
receipt.update(exit_code=run.returncode,source_hash_after=active_source_hash(ROOT))
receipt['checks_after']=checks('after')
totals={k:0 for k in ('tests','failures','errors','skipped')}
if xml.is_file():
 for suite in ET.parse(xml).getroot().iter('testsuite'):
  for key in totals:totals[key]+=int(suite.get(key,0))
 receipt['xml_sha256']=hashlib.sha256(xml.read_bytes()).hexdigest()
receipt.update(totals=totals,finished_unix=time.time())
receipt['passed']=(run.returncode==0 and totals['tests']>=3321 and all(totals[k]==0 for k in ('failures','errors','skipped'))
 and receipt['source_hash']==receipt['source_hash_after'] and all(x['exit_code']==0 and x['result'].get('passed') is True
 for stage in ('checks_before','checks_after') for x in receipt[stage].values()))
atomic_json(OUT/'test_receipt.json',receipt)
print(json.dumps({k:receipt[k] for k in ('passed','source_hash','source_hash_after','totals','started_unix','finished_unix')}),flush=True)
raise SystemExit(0 if receipt['passed'] else 1)
