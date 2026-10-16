"""Launch only the exact approved full-day session; no restart or signing in this wrapper."""
import json,sys,time,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.profit_only_session import LongSessionMandate
from exchange.exit_recovery import RecoveryApproval,require_recovery_regression
from exchange.paper_operations import active_source_hash,atomic_json

def main():
 proposal=BASE/'fresh_proposal';out=BASE/'authorized_session';receipt=BASE/'regression_release/test_receipt.json'
 m=LongSessionMandate(**json.loads((proposal/'mandate.json').read_text()))
 a=RecoveryApproval(**json.loads((proposal/'recovery_approval.json').read_text()))
 m.require();a.require(m,time.time_ns()//1000000)
 require_recovery_regression(ROOT,receipt)
 if active_source_hash(ROOT)!=m.source_hash:raise RuntimeError('SOURCE_CHANGED')
 if out.exists() or (BASE/'launch_receipt.json').exists():raise RuntimeError('NO_DUPLICATE_OR_RESTART')
 args=[sys.executable,str(ROOT/'scripts/run_exit_recovery.py'),'--execute','--output-directory',str(out),
       '--mandate',str(proposal/'mandate.json'),'--approval',str(proposal/'recovery_approval.json'),'--test-receipt',str(receipt)]
 with (BASE/'session_process.log').open('xb') as log:
  child=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(child.pid)],stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 r=dict(status='LAUNCHED_AWAITING_HEALTH',pid=child.pid,awake_helper_pid=awake.pid,launched_ms=time.time_ns()//1000000,
   mandate_id=m.identity,source_hash=m.source_hash,expires_ms=a.expires_ms,closing_cutoff_ms=a.expires_ms-m.reconciliation_reserve_ms,
   approved_quantity=m.quantity,minimum_sell=m.minimum_sell,state_directory=str(out),auto_restart=False,auto_renewal=False,
   wrapper_signed_actions=0,command=args)
 atomic_json(BASE/'launch_receipt.json',r);print(json.dumps(r,indent=2))

if __name__=='__main__':main()
