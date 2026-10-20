"""Verified unsigned public reader on frozen source; no account controller or signer."""
from pathlib import Path
import json,os,subprocess,time,sys
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent;S=O/'public_reader_source'
sys.path.insert(0,str(S/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.terminal_app import locked
state=R/'runtime/pas-btc-ewy-v6-public'
if locked(state/'owner.lock'):raise RuntimeError('PUBLIC_READER_ALREADY_RUNNING')
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE') if k in os.environ}
env.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY',PYTHONUNBUFFERED='1')
command=[str(R/'.venv/bin/python'),str(S/'scripts/anchorium_cli.py'),'start','--venue','pas','--state',str(state),'--markets','pas:BTC','pas:EWY','--scan-seconds','60','--readiness-release',str(R/'docs/opening_v5_3_2026-10-19/regression_release_final/test_receipt.json')]
with (O/'public_reader.log').open('x') as log:
 p=subprocess.Popen(command,cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 keep=subprocess.Popen(['/usr/bin/caffeinate','-w',str(p.pid)],cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
value=dict(pid=p.pid,caffeinate_pid=keep.pid,created_ms=time.time_ns()//1000000,source_hash=active_source_hash(S),source_root=str(S),state=str(state),command=command,signing_authority='NONE',exchange_writes=0,actual_wallet_signatures=0)
(O/'public_reader_launch.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2))
