"""Retire only the proven stale, unsigned V5.3 public reader; preserve its state."""
from pathlib import Path
import json,os,signal,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.terminal_app import locked
from exchange.paper_operations import atomic_json
state=R/'runtime/pas-btc-ewy-v6-public'
launch=json.loads((R/'docs/activation_v6_2026-10-19/public_reader_launch.json').read_text())
current=json.loads((state/'current.json').read_text());status=json.loads((Path(current['output'])/'status.json').read_text())
pid=launch['pid'];command=launch['command'];now=time.time_ns()//1000000
if (pid!=current['pid'] or pid!=int((state/'owner.lock').read_text()) or launch['state']!=str(state)
        or launch['signing_authority']!='NONE' or launch['actual_wallet_signatures']!=0 or launch['exchange_writes']!=0
        or '--authorized' in command or '--mandate' in command or '--acceptance' in command
        or status.get('signing_authority')!='NONE' or now-status['updated_ms']<180000):
 raise RuntimeError('EXACT_STALLED_UNSIGNED_PUBLIC_WORKER_REQUIRED')
atomic_json(O/'stalled_public_reader_evidence.json',dict(launch=launch,current=current,last_status=status,
 observed_ms=now,stale_ms=now-status['updated_ms'],diagnosis='LOCAL_PUBLIC_COLLECTOR_STALLED; exact Python lock stack not sampled; cache/REST lock inversion was independently identified and corrected'))
def exact_process():
 p=subprocess.run(['ps','-p',str(pid),'-o','args='],capture_output=True,text=True)
 return p.returncode==0 and command[1] in p.stdout and str(state) in p.stdout and '--authorized' not in p.stdout
if locked(state/'owner.lock'):
 if not exact_process():raise RuntimeError('PUBLIC_PROCESS_IDENTITY_CHANGED')
 os.kill(pid,signal.SIGTERM)
 for _ in range(15):
  if not locked(state/'owner.lock'):break
  time.sleep(1)
 if locked(state/'owner.lock'):
  if not exact_process():raise RuntimeError('PUBLIC_PROCESS_IDENTITY_CHANGED_BEFORE_TERMINATION')
  os.kill(pid,signal.SIGKILL)
  method='FORCED_TERMINATION_AFTER_GRACEFUL_STOP_AND_SIGTERM'
 else:method='SIGTERM_GRACEFUL'
else:method='ALREADY_STOPPED'
for _ in range(10):
 if not locked(state/'owner.lock'):break
 time.sleep(.2)
if locked(state/'owner.lock'):raise RuntimeError('STALE_PUBLIC_OWNER_NOT_RELEASED')
atomic_json(O/'stalled_public_reader_retirement.json',dict(pid=pid,method=method,stopped_ms=time.time_ns()//1000000,
 original_files_preserved=True,old_terminal_flat='NOT_INFERRED_FROM_STALE_WORKER',exchange_writes=0,
 note='Fresh final-source PAS/PAR readbacks must establish current account truth; this process was public-only and never had order authority.'))
print(json.dumps(dict(pid=pid,method=method,public_owner_released=True)))
