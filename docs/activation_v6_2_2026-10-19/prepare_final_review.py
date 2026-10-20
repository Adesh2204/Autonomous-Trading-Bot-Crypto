"""Fresh unsigned final evidence, only after the complete offline release passes."""
from pathlib import Path
import json,os,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.long_session import require_release,sha
from exchange.paper_operations import active_source_hash
release=O/'regression_release_final/test_receipt.json';require_release(R,release,active_source_hash(R),sha(release))
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE') if k in os.environ}
env.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY',PYTHONUNBUFFERED='1')
commands=[
 ['native-prepare','--market','pas:BTC','--output',str(O/'native_btc_final')],
 ['native-prepare','--market','pas:EWY','--output',str(O/'native_ewy_final')],
 ['pas-ranking','--output',str(O/'ranking_final')],
 ['trading-isolation-prepare','--minutes','60','--output',str(O/'isolation_final')],
 ['prepare','--venue','pas','--markets','pas:BTC','pas:EWY','--minutes','60','--maximum-notional','1000',
  '--release',str(release),'--operator-confirmation',str(R/'docs/activation_v6_2026-10-19/operator_identity/operator_confirmation.json'),
  '--trading-isolation-policy',str(O/'isolation_final/policy.json'),'--output',str(O/'session_final')]]
for i,args in enumerate(commands):
 if i==4:time.sleep(30)
 if 0<i<4:time.sleep(60)  # Leave room for the existing public reader's IP budget.
 with (O/('final_read_'+str(i)+'.log')).open('x') as log:
  p=subprocess.run([str(R/'.venv/bin/python'),str(R/'scripts/anchorium_cli.py'),*args],cwd=R,env=env,
   stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=300)
 if p.returncode:raise SystemExit('UNSIGNED_FINAL_READ_FAILED:'+str(i))
print(json.dumps(dict(status='UNSIGNED_FINAL_REVIEWS_COMPLETE',mandate_created=(O/'session_final/mandate.json').exists(),accepted=False,signing_authority='NONE')))
