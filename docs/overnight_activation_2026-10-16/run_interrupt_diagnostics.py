"""Bounded unsigned public CLI SIGINT/SIGTERM diagnostics; never uses a signer."""
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
source=active_source_hash(ROOT)
def read(p):
 for _ in range(4):
  try:return json.loads(p.read_text())
  except (ValueError,FileNotFoundError):time.sleep(.05)
 return {}
results=[]
for label,sig in [('ctrl_c',signal.SIGINT),('sigterm',signal.SIGTERM)]:
 state=P/label
 cmd=[sys.executable,str(ROOT/'scripts/anchorium_cli.py'),'start','--state',str(state),'--duration','150','--scan-seconds','60','--markets','par:BTC']
 with (P/(label+'_console.log')).open('x') as log:
  proc=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
  began=time.monotonic();triggered=False;out=None;record=dict(test=label,pid=proc.pid,source_hash=source,command=cmd)
  while proc.poll() is None and time.monotonic()-began<145:
   current=read(state/'current.json')
   if current.get('pid')==proc.pid:
    out=Path(current['output']);s=read(out/'status.json')
    if s.get('source_hash')!=source:raise RuntimeError('DIAGNOSTIC_SOURCE_CHANGED')
    if s.get('account_stream_healthy') and s.get('stream_connected') and s.get('latest_scan_ms'):
     command=subprocess.check_output(['/bin/ps','-p',str(proc.pid),'-o','command='],text=True).strip()
     if 'anchorium_cli.py start' not in command or str(state) not in command:raise RuntimeError('DIAGNOSTIC_PID_IDENTITY_CHANGED')
     record.update(signal_sent_ms=time.time_ns()//1000000,matched_command=command,healthy_before_signal=True)
     proc.send_signal(sig);triggered=True;break
   time.sleep(.5)
  record['signal_sent']=triggered
  try:record['exit_code']=proc.wait(timeout=240)
  except subprocess.TimeoutExpired:
   record.update(status='DIAGNOSTIC_DID_NOT_TERMINATE_REQUIRES_REVIEW');results.append(record)
   (P/'interrupt_diagnostics.json').write_text(json.dumps(results,indent=2)+'\n')
   raise SystemExit(1)
  if out:
   terminal=read(out/'terminal_result.json');record.update(output=str(out),status=terminal.get('status'),account_status=terminal.get('account_status'),terminal_flat=terminal.get('terminal_flat'),terminal_readbacks=terminal.get('terminal_readbacks'),threads_stopped=terminal.get('threads_stopped'),execution_intents=terminal.get('execution_intents'),exchange_writes=terminal.get('exchange_writes'),signatures=terminal.get('signatures_created'),errors=terminal.get('actual_errors'),terminal_reconciliation_error=terminal.get('terminal_reconciliation_error'),journal_integrity=terminal.get('journal_integrity'))
  record['elapsed_seconds']=round(time.monotonic()-began,3)
  results.append(record);(P/'interrupt_diagnostics.json').write_text(json.dumps(results,indent=2)+'\n')
  if not triggered or not record.get('terminal_flat') or not record.get('threads_stopped'):raise SystemExit(1)
print(json.dumps(results,indent=2))
