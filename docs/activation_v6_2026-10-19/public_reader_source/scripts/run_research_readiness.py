"""Structured capture replay -> status -> prespecified seal -> future holdout."""
import argparse
from copy import deepcopy
from pathlib import Path
import json
import sys
import time
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from research_intelligence.common import ResearchError, digest, immutable_json, HoldoutLedger
from research_lab.forward_lab import run_forward_lab
from research_intelligence.campaign import seal_campaign, load_campaign, verified_json
from research_intelligence.splits import ChronologicalSplit
from research_intelligence.readiness import assess_readiness, save_readiness


def timestamp_value(value):
    if isinstance(value,str):
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None: raise ResearchError('AWARE_ISO_DATE_REQUIRED')
        return int(dt.timestamp()*1000)
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    replay=sub.add_parser('replay',help='Four independent portfolios from one complete public capture')
    replay.add_argument('--capture',required=True); replay.add_argument('--output',required=True)
    status=sub.add_parser('status',help='Evidence-based flags and exact remaining data')
    status.add_argument('--lab',action='append',required=True); status.add_argument('--output',required=True)
    seal=sub.add_parser('seal',help='Fit/seal before a FUTURE holdout; refuses insufficient or already-observed data')
    seal.add_argument('--lab',action='append',required=True); seal.add_argument('--split-config',required=True); seal.add_argument('--output',required=True)
    held=sub.add_parser('holdout',help='Evaluate only a sealed future window; no tuning or activation')
    held.add_argument('--campaign',required=True); held.add_argument('--capture',required=True); held.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.command=='replay':
            result=run_forward_lab(a.capture,a.output)
            result=dict(frames=result['frames'],quality=result['quality'],portfolios=result['portfolios'])
        elif a.command=='status':
            result=assess_readiness(a.lab); save_readiness(result,a.output)
        elif a.command=='seal':
            config=json.loads(Path(a.split_config).read_text())
            for key in ('validation_start_ms','validation_tune_start_ms','holdout_start_ms','holdout_end_ms'):
                config[key]=timestamp_value(config[key])
            end=config.pop('holdout_end_ms')
            result=seal_campaign(a.lab,a.output,split=ChronologicalSplit(**config),holdout_end_ms=end)
        else:
            campaign,controllers=load_campaign(a.campaign)
            start=campaign['split']['holdout_start_ms']; end=campaign['holdout_end_ms']
            capture=verified_json(Path(a.capture)/'capture_manifest.json')
            if capture['created_ms']<campaign['created_ms']: raise ResearchError('HOLDOUT_CAPTURE_MUST_FOLLOW_MODEL_SEAL')
            if time.time_ns()//1000000<end: raise ResearchError('FUTURE_HOLDOUT_WINDOW_NOT_COMPLETE')
            # Seal the complete capture and model set before portfolio evaluation.
            completion=json.loads((Path(a.capture)/'capture_completion.json').read_text())
            HoldoutLedger(Path(a.campaign)/'holdout_evaluation_seals').claim(
                dict(campaign=campaign['sha256'],start=start,end=end),
                dict(capture_root=completion['root_hash'],models=campaign['models']))
            output=Path(a.output); output.mkdir(parents=True,exist_ok=False)
            lab=output/'portfolios'
            run_forward_lab(a.capture,lab,sealed_models=controllers,evaluation_start_ms=start,evaluation_end_ms=end)
            result=assess_readiness([lab],campaign_directory=a.campaign)
            save_readiness(result,output/'evaluation')
        print(json.dumps(dict(output=str(Path(a.output).resolve()),status=result.get('status',result.get('recommendation')),
            exchange_orders_submitted=0,production_changed=False),default=str))
        return 0
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
        print('Research stopped: '+type(exc).__name__+':'+str(exc),file=sys.stderr); return 1


if __name__=='__main__': raise SystemExit(main())
