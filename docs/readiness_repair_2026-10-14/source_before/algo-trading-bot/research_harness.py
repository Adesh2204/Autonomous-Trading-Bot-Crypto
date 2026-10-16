"""Offline named-policy evaluation with explicit development/held-out manifests.

Usage: python research_harness.py manifest.json --output data/research
No authentication or networking. Each case is an independent single-symbol replay,
not a shared-capital portfolio. No automatic parameter selection or promotion.
"""
import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
import json
import config
import pandas as pd
from historical_data import ist_timestamp
from execution_safety import InstrumentIdentity
from replay_engine import ResearchVariant, replay, research_metrics
from research_policy import VolatilityPolicy


def evaluate_manifest(manifest,output):
    if config.LIVE_MODE:
        raise ValueError('PAPER_RESEARCH_ONLY')
    cases=manifest['sessions']
    if not cases or any(c['split'] not in {'DEVELOPMENT','HELD_OUT'} for c in cases):
        raise ValueError('EXPLICIT_RESEARCH_SPLITS_REQUIRED')
    dates={split:{c['date'] for c in cases if c['split']==split} for split in ('DEVELOPMENT','HELD_OUT')}
    if dates['DEVELOPMENT'] & dates['HELD_OUT']:
        raise ValueError('DEVELOPMENT_HELD_OUT_DATE_OVERLAP')
    if not dates['DEVELOPMENT'] or not dates['HELD_OUT']:
        raise ValueError('BOTH_RESEARCH_SPLITS_REQUIRED')
    policies=[VolatilityPolicy(**p) for p in manifest.get('policies',[{}])]
    if len({p.name for p in policies})!=len(policies):
        raise ValueError('DUPLICATE_POLICY_NAME')
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    results=[]
    for policy in policies:
        for split in ('DEVELOPMENT','HELD_OUT'):
            trades=[]; details=[]
            for case in sorted((c for c in cases if c['split']==split),key=lambda c:(c['date'],c['symbol'])):
                frame=pd.read_csv(case['path'])
                if any(ist_timestamp(t).date().isoformat()!=case['date'] for t in frame.Timestamp):
                    raise ValueError('CASE_SESSION_DATE_MISMATCH')
                if not str(case.get('regime','')).strip():
                    raise ValueError('CASE_REGIME_LABEL_REQUIRED')
                identity=InstrumentIdentity(case['symbol'],'NSE',str(case['token']),case['symbol']+'-EQ',
                    'EQ',float(case['tick_size']),int(case.get('lot_size',1)),'CASH',ist_timestamp(case['date']+' 09:00'))
                closed,_,meta=replay(frame,identity,case['provenance'],output/policy.name/split,
                                      variant=ResearchVariant(policy.name,volatility_policy=policy))
                trades.extend(closed)
                details.append(meta|{'date':case['date'],'symbol':case['symbol'],'regime':case['regime']})
            gates=Counter()
            for detail in details:gates.update(detail['blocked_by_gate'])
            metrics=research_metrics(trades)|{'opportunities_observed':sum(d['opportunities_observed'] for d in details),
                'entries_attempted':sum(d['entries_attempted'] for d in details),
                'fills':sum(d['fill_events'] for d in details),'blocked_by_gate':dict(gates)}
            results.append({'policy':policy.report(),'split':split,'case_count':len(details),
                            'metrics':metrics,'cases':details,
                            'warning':'POOLED INDEPENDENT SYMBOL CASES, NOT A SHARED-CAPITAL PORTFOLIO'})
    report={'research_only':True,'live_eligible':False,'automatic_policy_promotion':False,
            'regimes_supplied':sorted({c['regime'] for c in cases}),'results':results}
    (output/'comparison.json').write_text(json.dumps(report,indent=2,default=str))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'data'/'research')
    args=parser.parse_args()
    report=evaluate_manifest(json.loads(args.manifest.read_text()),args.output)
    print(json.dumps({'report':str(args.output/'comparison.json'),'comparisons':len(report['results'])}))


if __name__=='__main__':
    main()
