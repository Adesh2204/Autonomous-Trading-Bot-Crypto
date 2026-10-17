"""Finish only the matched bounded public diagnostics. No signing or trading."""
import fcntl,json,subprocess,sys,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
source=active_source_hash(ROOT);state=P/'final_soak'
def read(p):
 for _ in range(4):
  try:return json.loads(p.read_text())
  except (ValueError,FileNotFoundError):time.sleep(.05)
 raise RuntimeError('DIAGNOSTIC_JSON_UNREADABLE')
def owned():
 with (state/'owner.lock').open('a+') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return True
  fcntl.flock(f,fcntl.LOCK_UN);return False
current=read(state/'current.json');output=Path(current['output']);s=read(output/'status.json');start=s['started_ms']
if s['source_hash']!=source or current['pid']!=s['pid']:raise RuntimeError('DIAGNOSTIC_IDENTITY_MISMATCH')
while time.time_ns()//1000000-start<600000:
 if not owned():raise RuntimeError('DIAGNOSTIC_STOPPED_BEFORE_CONTROLLED_STOP')
 if active_source_hash(ROOT)!=source:raise RuntimeError('DIAGNOSTIC_SOURCE_CHANGED')
 time.sleep(.5)
command=[sys.executable,str(ROOT/'scripts/anchorium_cli.py'),'stop','--state',str(state)]
r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
(P/'controlled_stop_receipt.json').write_text(json.dumps(dict(requested_ms=time.time_ns()//1000000,identity=current,source_hash=source,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr),indent=2)+'\n')
if r.returncode:raise SystemExit(r.returncode)
deadline=time.monotonic()+220
while owned() and time.monotonic()<deadline:time.sleep(.5)
if owned():raise RuntimeError('DIAGNOSTIC_SHUTDOWN_EXCEEDED')
result=read(output/'terminal_result.json')
if result.get('source_hash')!=source or result.get('terminal_flat') is not True:raise RuntimeError('DIAGNOSTIC_TERMINAL_REQUIRES_REVIEW')
subprocess.run([sys.executable,str(P/'run_interrupt_diagnostics.py')],cwd=ROOT,check=True,timeout=900)
with (P/'prepare_final_console.log').open('x') as log:
 subprocess.run([sys.executable,str(ROOT/'scripts/anchorium_cli.py'),'prepare','--overnight','--output',str(P/'final_proposal'),'--maximum-notional','1000'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=360)
print('All bounded public diagnostics finished. No trading worker remains.')
