"""Offline saved-observation research; cannot load a trading runtime."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'algo-trading-bot'))
from counterfactual_research import CounterfactualResearch


def main():
    p=argparse.ArgumentParser(description='COUNTERFACTUAL — NOT LIVE POLICY')
    p.add_argument('--traces',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--holdout-start-ms',type=int)
    p.add_argument('--outcomes',help='Optional explicit recorded outcome and cost evidence JSON')
    a=p.parse_args()
    traces=[json.loads(line) for line in Path(a.traces).read_text().splitlines() if line.strip()]
    outcomes=json.loads(Path(a.outcomes).read_text()) if a.outcomes else None
    report=CounterfactualResearch().export(traces,a.output,holdout_start_ms=a.holdout_start_ms,outcomes=outcomes)
    print(json.dumps(dict(label=report['label'],research_status=report['research_status'],
                         observations=report['observation_count'],exchange_orders_submitted=0)))

if __name__=='__main__':main()
