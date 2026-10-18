"""Run the existing unsigned PAS prepare only after the final full release passes."""
from pathlib import Path
import json,os,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
p=O/'regression_release_final/test_receipt.json';deadline=time.monotonic()+900
while time.monotonic()<deadline:
 try:
  r=json.loads(p.read_text())
  if r.get('finished_unix'):
   if not r.get('passed'):raise SystemExit('FINAL_RELEASE_FAILED_NO_PREPARATION')
   break
 except (OSError,ValueError):pass
 time.sleep(1)
else:raise SystemExit('FINAL_RELEASE_WAIT_TIMEOUT')
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
assert active_source_hash(R)==r['source_hash']==r['source_hash_after']
os.environ.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY')
with (O/'final_preopening_proposal.log').open('x') as log:
 result=subprocess.run([sys.executable,'scripts/anchorium_cli.py','prepare','--venue','pas','--output',str(O/'final_preopening_proposal'),
  '--minutes','60','--maximum-notional','1000','--release',str(p)],cwd=R,stdout=log,stderr=subprocess.STDOUT)
print('UNSIGNED_PREPARATION_EXIT',result.returncode)
raise SystemExit(result.returncode)
