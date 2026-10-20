"""Create a fresh blocked/ready scored proposal after the new offline release passes."""
from pathlib import Path
import json,os,subprocess,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
release=O/'regression_release_final/test_receipt.json'
for _ in range(600):
 r=json.loads(release.read_text()) if release.exists() else {}
 if r.get('finished_unix'):
  if not r.get('passed'):raise SystemExit('REGRESSION_FAILED_NO_PROPOSAL')
  break
 time.sleep(2)
else:raise SystemExit('REGRESSION_PENDING_NO_PROPOSAL')
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE') if k in os.environ}
env.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY',PYTHONUNBUFFERED='1')
command=[str(R/'.venv/bin/python'),str(R/'scripts/anchorium_cli.py'),'prepare','--venue','pas',
 '--markets','pas:BTC','pas:EWY','--minutes','60','--maximum-notional','1000','--release',str(release),
 '--operator-confirmation',str(R/'docs/activation_v6_2026-10-19/operator_identity/operator_confirmation.json'),
 '--output',str(O/'scored_review_final')]
with (O/'scored_prepare.log').open('x') as log:
 p=subprocess.run(command,cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=240)
print(json.dumps(dict(returncode=p.returncode,mandate_created=(O/'scored_review_final/mandate.json').exists(),signing_authority='NONE')))
raise SystemExit(p.returncode)
