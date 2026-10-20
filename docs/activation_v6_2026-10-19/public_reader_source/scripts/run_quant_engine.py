"""Isolated capital/exit research or bounded PUBLIC observation; no execute mode."""
import argparse,json,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    research=sub.add_parser('research');research.add_argument('--snapshot',required=True)
    research.add_argument('--output',required=True);research.add_argument('--historical-tape');research.add_argument('--historical-sha256')
    observe=sub.add_parser('observe');observe.add_argument('--output',required=True)
    observe.add_argument('--team-wallet',required=True);observe.add_argument('--markets',nargs='+',required=True)
    observe.add_argument('--expires-ms',type=int,required=True);observe.add_argument('--source-hash',required=True)
    observe.add_argument('--scan-seconds',type=int,default=300)
    a=p.parse_args()
    if a.command=='research':
        from research_lab.quant_campaign import run_campaign
        r=run_campaign(a.snapshot,a.output,historical_tape=a.historical_tape,historical_sha=a.historical_sha256)
        print(json.dumps(dict(status='RESEARCH_COMPLETE_NOT_ACTIVATED',source_hash=r['source_hash'],
            synthetic_episodes=r['synthetic_episodes'],synthetic_fault_episodes=r['synthetic_fault_episodes'],
            qualified_genuine_notional=r['genuine_execution_qualified_notional'],exchange_orders_submitted=0)))
    else:
        os.environ['ANCHORIUM_PUBLIC_ONLY']='true'
        from exchange.public_quant_operator import observe
        r=observe(ROOT,a.output,team_wallet=a.team_wallet,markets=a.markets,
            expires_ms=a.expires_ms,source_hash=a.source_hash,scan_seconds=a.scan_seconds)
        print(json.dumps(dict(status=r['status'],exchange_writes=0)))
        return 0 if r.get('clean') else 1
    return 0

if __name__=='__main__':raise SystemExit(main())
