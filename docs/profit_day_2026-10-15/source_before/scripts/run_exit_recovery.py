"""Prepare read-only, or run one explicitly approved SELL-only BTC recovery."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.exit_recovery import RecoveryMandate,RecoveryApproval,prepare,execute

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-directory',required=True);p.add_argument('--test-receipt',required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--mandate');p.add_argument('--approval')
    p.add_argument('--immediate-loss',action='store_true',help='Prepare a separate explicit bounded-loss close mandate.')
    a=p.parse_args()
    if a.execute:
        if a.immediate_loss:p.error('Execution mode comes only from the exact accepted mandate.')
        if not a.mandate or not a.approval:p.error('Exact mandate and genuine new human approval required.')
        m=RecoveryMandate(**json.loads(Path(a.mandate).read_text()));approval=RecoveryApproval(**json.loads(Path(a.approval).read_text()))
        r=execute(ROOT,a.output_directory,m,approval,a.approval,a.test_receipt)
    else:
        if a.mandate or a.approval:p.error('Read-only preparation never consumes approval.')
        r=prepare(ROOT,a.output_directory,a.test_receipt,immediate_loss=a.immediate_loss)
    print(json.dumps(r,indent=2,default=str))
    return 0 if r['status'] in {'AWAITING_EXACT_RECOVERY_APPROVAL','CLOSED_EXCHANGE_VERIFIED','PROFIT_WINDOW_EXPIRED_NO_SELL'} else 1

if __name__=='__main__':raise SystemExit(main())
