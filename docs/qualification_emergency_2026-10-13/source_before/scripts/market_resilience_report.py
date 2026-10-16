"""Completed per-market PAPER evidence report; no client, signer or activation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.market_resilience_certification import evaluate_resilience
from exchange.paper_operations import atomic_json
from feed_certification_report import generate as generate_base
from check_practice_health import describe,assess_value


def generate(receipt_path,output,*,regression_passed=False):
    output=Path(output)
    base=generate_base(receipt_path,output.with_name(output.name+'_legacy_criteria'),regression_passed=regression_passed)
    receipt=json.loads(Path(receipt_path).read_text());health=receipt['final_health']
    samples=[json.loads(x) for x in Path(receipt['health_samples_path']).read_text().splitlines() if x.strip()]
    samples=[s for s in samples if receipt['started_unix']*1000<=s['timestamp_ms']<=receipt['finished_unix']*1000]
    report=dict(base,**evaluate_resilience(base,samples,health))
    report['legacy_three_scan_certificate']=base['feed_certified']
    report['legacy_three_scan_blockers']=base['blockers']
    events=health['public_stream'].get('events',[])
    report['successful_reconnect_account_barriers']=max(0,sum(e['phase']=='PAPER_ACCOUNT_RECONCILED' for e in events)-1)
    report['rest_reconciliations_including_initial']=base['successful_recoveries']
    report['maximum_receiver_gap_seconds']=health['public_stream']['transport']['max_receiver_gap_seconds']
    report['maximum_sampled_local_ip_weight']=max((s.get('public_stream',{}).get('public_rate_budget',{}).get('ip_weight',0) for s in samples),default=None)
    report['close_records']=[{k:c.get(k) for k in ('connection_id','close_code','close_reason','connection_age_seconds','client_exception')} for c in health['public_stream']['transport']['connections']]
    report['last_market_health']=health.get('market_health',{})
    report['market_recovery']=health['public_stream'].get('market_health',{})
    report['running_feed_ready_samples']=report['ready_samples']
    atomic_json(output.with_suffix('.json'),report)
    lines=[f'# Anchorium — {report["verdict"]}', '', report['note'], '',
           f'Runtime: {report["duration_seconds"]:.3f}s. Actual orders: {report["actual_exchange_orders"]}. PAPER fills: {report["local_fills"]}.',
           f'Usable-feed observations: {report["ready_samples"]}; partial-health observations: {report["partial_healthy_samples"]}.',
           'Quarantined: '+(', '.join(report['quarantine_observed']) or 'None observed')+'.',
           'Restored after quarantine: '+(', '.join(report['restored_after_quarantine']) or 'None observed')+'.',
           'Final usable markets: '+(', '.join(report['final_usable_markets']) or 'None')+'.',
           'Blockers: '+(', '.join(report['blockers']) or 'None')+'.', '',
           '| Check | Passed |','|---|---|']
    lines += [f'| {k} | {v} |' for k,v in report['checks'].items()]
    lines+=['','Independent checks and sequential admissions:','','| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted/evaluated |','|---|---:|---:|---:|---:|---:|']
    for v in report['funnel']['session']['stages']:
        pct=f'{v["pass_percent"]:.2f}%' if v['pass_percent'] is not None else 'Not evaluated'
        lines.append(f'| {v["stage"]} | {v["evaluated"]} | {v["passed"]} | {v["failed"]} | {pct} | {v["admission_passed"]}/{v["admission_evaluated"]} |')
    if samples:
        sample=next((s for s in reversed(samples) if s['status']=='RUNNING'),samples[-1])
        code,reason=assess_value(sample,now_ms=sample['timestamp_ms'])
        lines+=['','Actual saved operating sample (historical, not a live check):','','```text',describe(sample,code,reason),'```']
    lines+=['','The funded wallet is separate from this hypothetical ledger. Protection, funded LONG/SHORT and funded recovery remain untested. PAPER/false and protection disabled remain enforced.']
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--regression-passed',action='store_true')
    a=p.parse_args();r=generate(a.receipt,a.output,regression_passed=a.regression_passed)
    print(json.dumps({k:r[k] for k in ('verdict','feed_certified','blockers','partial_healthy_samples','restored_after_quarantine')}))
