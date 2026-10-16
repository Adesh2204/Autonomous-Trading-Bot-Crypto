"""Future explicitly authorized testnet launcher. PAPER defaults refuse activation."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.execution_safety import HumanLiveApproval,LiveAuthorization
from exchange.live_runtime import build_live_runtime
from exchange.reliability_policy import load_reliability_policy
from exchange.runtime_schedule import RuntimeSchedule
from run_crypto_paper import load_policy


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--approval-file',type=Path,required=True,help='Explicit future human approval; contains public identities only')
    p.add_argument('--state-directory',type=Path,required=True)
    p.add_argument('--session-id',required=True)
    p.add_argument('--account-history-start-ms',type=int,required=True)
    p.add_argument('--policy',type=Path,default=ROOT/'docs/paper_policy.example.json')
    p.add_argument('--reliability-policy',type=Path,default=ROOT/'configs/reliability_policy.json')
    p.add_argument('--verified-fee-scale',type=int,required=True)
    args=p.parse_args()
    try:
        approval=HumanLiveApproval(**json.loads(args.approval_file.read_text()))
        LiveAuthorization(approval).require(approval.team_address,approval.signer_address)
        if args.account_history_start_ms<0:raise ValueError('ACCOUNT_HISTORY_START_REQUIRED')
        _,_,scanner,risk=load_policy(args.policy)
        rate,clock,protection=load_reliability_policy(args.reliability_policy)
        protection.require()
        runtime=build_live_runtime(team_address=approval.team_address,approval=approval,
            session_id=args.session_id,initial_start_ms=args.account_history_start_ms,risk_policy=risk,
            scanner_policy=scanner,state_directory=args.state_directory,fee_scale_verified=args.verified_fee_scale,
            rate_policy=rate,clock_policy=clock,protection_policy=protection,schedule=RuntimeSchedule())
        runtime.run()
        return 0
    except (ValueError,TypeError,OSError,RuntimeError) as exc:
        from exchange.execution_journal import safe_reason
        print('Practice activation refused: '+safe_reason(exc),file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
