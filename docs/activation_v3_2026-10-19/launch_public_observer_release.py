"""Launch only the standalone public observer. No signer or trading authority."""
from pathlib import Path
import json,os,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.terminal_app import locked
state=ROOT/'runtime/pas-v3-public'
if locked(state/'owner.lock'):raise SystemExit('PUBLIC_OWNER_ALREADY_RUNNING')
log=OUT/'public_observer_release.log'
if log.exists():raise SystemExit('PRESERVE_EXISTING_PUBLIC_LAUNCH')
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE') if k in os.environ}
env.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY',PYTHONUNBUFFERED='1')
command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/anchorium_cli.py'),'start','--venue','pas',
    '--state',str(state),'--scan-seconds','60','--readiness-release',str(OUT/'regression_release_final/test_receipt.json')]
with log.open('x') as stream:
 worker=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
 caffeinate=subprocess.Popen(['/usr/bin/caffeinate','-w',str(worker.pid)],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
receipt=dict(created_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),worker_pid=worker.pid,caffeinate_pid=caffeinate.pid,
    command=command,state=str(state),log=str(log),scope='PUBLIC_PAS_OBSERVATION_ONLY',signing_authority='NONE',
    continuous_observation=True,trading_authority_renewal=False,exchange_writes=0,signatures_created=0,
    dependency='Mac/Python/power/internet/exchange; independent of Codex/app; caffeinate is bound to this process')
(OUT/'public_observer_release_launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
