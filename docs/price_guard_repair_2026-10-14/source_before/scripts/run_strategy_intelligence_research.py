"""Saved-evidence-only research. No exchange client, secret or order capability."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from research_intelligence.experiment import run_research
from research_intelligence.splits import ChronologicalSplit
from research_intelligence.dataset import feature_evidence_from_events
from research_intelligence.common import record_attempt


def lines(path):return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()] if path else []
def value(path):return json.loads(Path(path).read_text()) if path else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--traces');p.add_argument('--candidates',help='Explicit candidate rows with timestamped feature_evidence')
    p.add_argument('--feature-observations');p.add_argument('--outcomes');p.add_argument('--candles')
    p.add_argument('--candidate-events',help='Existing candidate_traces.jsonl with timestamped MARKET_DATA snapshots')
    p.add_argument('--anchor-config',default=str(ROOT/'research/configurations/anchor_policies.json'))
    p.add_argument('--assumptions',help='Unchanged recorded fee/risk/execution assumptions JSON')
    p.add_argument('--split-config',help='Explicit ChronologicalSplit boundaries JSON')
    p.add_argument('--output',required=True)
    p.add_argument('--registry',default=str(ROOT/'research/experiment_registry.jsonl'))
    a=p.parse_args()
    try:
        manifest=run_research(output=a.output,registry=a.registry,traces=lines(a.traces),
            candidate_observations=lines(a.candidates) if a.candidates else None,
            feature_observations=value(a.feature_observations) if a.feature_observations else feature_evidence_from_events(lines(a.candidate_events)),
            outcomes=value(a.outcomes),candle_observations=lines(a.candles),anchor_config=value(a.anchor_config),
            assumptions=value(a.assumptions),split=ChronologicalSplit(**value(a.split_config)) if a.split_config else None)
    except (ValueError,TypeError,KeyError,OSError) as exc:
        record_attempt(a.registry,dict(result='INPUT_OR_RUN_FAILED',conclusion=type(exc).__name__+': '+str(exc),
            inputs=dict(traces=a.traces,candidates=a.candidates,outcomes=a.outcomes,candles=a.candles),output=a.output))
        print('Research stopped: '+str(exc),file=sys.stderr);return 1
    print(json.dumps(dict(experiment_id=manifest['experiment_id'],recommendation=manifest['recommendation'],status=manifest['status'],exchange_orders_submitted=0)))
    return 0


if __name__=='__main__':raise SystemExit(main())
