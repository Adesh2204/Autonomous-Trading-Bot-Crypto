"""After the offline release passes, create one unsigned fresh scored proposal."""
from pathlib import Path
import json,os,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
release=O/'regression_release_final/test_receipt.json'
for _ in range(300):
 data=json.loads(release.read_text()) if release.is_file() else {}
 if data.get('finished_unix'):
  if data.get('passed') is not True:raise SystemExit('FAILED_REGRESSION_NO_PROPOSAL')
  break
 time.sleep(2)
else:raise SystemExit('REGRESSION_STILL_PENDING_NO_PROPOSAL')
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE') if k in os.environ}
env.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY',PYTHONUNBUFFERED='1')
cmd=[str(R/'.venv/bin/python'),str(R/'scripts/anchorium_cli.py'),'prepare','--venue','pas',
 '--markets','pas:BTC','pas:EWY','--minutes','720','--maximum-notional','1000',
 '--release',str(release),'--operator-confirmation',str(O/'operator_identity/operator_confirmation.json'),
 '--output',str(O/'scored_review_final')]
with (O/'scored_prepare.log').open('x') as log:
 result=subprocess.run(cmd,cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=240)
print(json.dumps(dict(returncode=result.returncode,proposal=str(O/'scored_review_final/proposal.json'),
 mandate_created=(O/'scored_review_final/mandate.json').exists(),signing_authority='NONE')))
raise SystemExit(result.returncode)
