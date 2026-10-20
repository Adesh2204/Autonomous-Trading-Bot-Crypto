"""Deploy only a verified credential-free PUBLIC observer. No signed controller."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent;S=O/'public_reader_source'
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.long_session import require_release,sha
from exchange.terminal_app import locked
release=O/'regression_release_final/test_receipt.json';source=active_source_hash(R)
require_release(R,release,source,sha(release))
state=R/'runtime/pas-btc-ewy-v6_2-public'
if locked(state/'owner.lock'):raise RuntimeError('V6_2_PUBLIC_READER_ALREADY_RUNNING')
S.mkdir(exist_ok=False)
paths=list((R/'scripts').glob('*.py'))+[p for p in (R/'algo-trading-bot').rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)]
paths+=[R/'algo-trading-bot/requirements.txt',R/'docs/strategy_freeze.json',*list((R/'configs').glob('*.json'))]
copied={}
for p in paths:
 target=S/p.relative_to(R);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
 copied[str(p.relative_to(R))]=sha(target)
(S/'runtime').mkdir();(S/'runtime/testnet').symlink_to(R/'runtime/testnet',target_is_directory=True)
if active_source_hash(S)!=source or any(p.name.startswith('.env') for p in S.rglob('*')):raise RuntimeError('PUBLIC_SNAPSHOT_SOURCE_OR_CREDENTIAL_BOUNDARY_FAILED')
require_release(S,release,source,sha(release))
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE') if k in os.environ}
env.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY',PYTHONUNBUFFERED='1')
old=R/'runtime/pas-btc-ewy-v6-public'
if locked(old/'owner.lock'):
 p=subprocess.run([str(R/'.venv/bin/python'),str(R/'docs/activation_v6_2026-10-19/public_reader_source/scripts/anchorium_cli.py'),'stop','--state',str(old)],cwd=R,env=env,capture_output=True,text=True,timeout=30)
 atomic_json(O/'old_public_reader_stop_request.json',dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
 for _ in range(60):
  if not locked(old/'owner.lock'):break
  time.sleep(1)
 else:raise RuntimeError('OLD_PUBLIC_READER_NOT_STOPPED_NO_DUPLICATE_DEPLOYMENT')
 current=json.loads((old/'current.json').read_text());terminal=json.loads((Path(current['output'])/'terminal_result.json').read_text())
 atomic_json(O/'old_public_reader_terminal_result.json',terminal)
 if terminal.get('terminal_flat') is not True:raise RuntimeError('OLD_PUBLIC_READER_TERMINAL_RECONCILIATION_REQUIRED')
command=[str(R/'.venv/bin/python'),str(S/'scripts/anchorium_cli.py'),'start','--venue','pas','--state',str(state),'--markets','pas:BTC','pas:EWY','--scan-seconds','60','--readiness-release',str(release)]
with (O/'public_reader.log').open('x') as log:
 p=subprocess.Popen(command,cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 keep=subprocess.Popen(['/usr/bin/caffeinate','-w',str(p.pid)],cwd=R,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
receipt=dict(mode='PUBLIC_ONLY_UNSIGNED',source_hash=source,release_sha256=sha(release),files=copied,
 pid=p.pid,caffeinate_pid=keep.pid,source_root=str(S),state=str(state),command=command,signing_authority='NONE',actual_wallet_signatures=0,exchange_writes=0,created_ms=time.time_ns()//1000000)
atomic_json(O/'public_reader_launch.json',receipt)
print(json.dumps({k:receipt[k] for k in ('mode','source_hash','pid','source_root','state','signing_authority')},indent=2))
