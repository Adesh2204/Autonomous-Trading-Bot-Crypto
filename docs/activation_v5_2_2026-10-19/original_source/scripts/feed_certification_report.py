"""Summarize a completed, source-bound PAPER run; no network or signer."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.feed_certification import FeedCertificationReport
from exchange.paper_checkpoint import unpack
from exchange.paper_operations import atomic_json
from opportunity_funnel import OpportunityFunnel


def checkpoint(path):
    db=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
    try:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        row=db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
        checksum=bool(row and hashlib.sha256(row[0].encode()).hexdigest()==row[1])
        data=unpack(json.loads(row[0])) if checksum else {}
        return dict(integrity=integrity,checksum_matches=checksum,clean_shutdown=data.get('clean'),
                    source_hash=data.get('identity',{}).get('active_source_hash'))
    finally:db.close()


def generate(receipt_path,output,*,regression_passed=False):
    receipt=json.loads(Path(receipt_path).read_text())
    if 'finished_unix' not in receipt:raise ValueError('RUN_NOT_COMPLETE')
    health=receipt['final_health'];segment=Path(health['segment'])
    start=int(receipt['started_unix']*1000);end=int(receipt['finished_unix']*1000)
    all_traces=[json.loads(line) for line in (segment/'results/opportunity_traces.jsonl').read_text().splitlines()]
    traces=[t for t in all_traces if start<=t['decision_ms']<=end]
    funnel=OpportunityFunnel();funnel.traces={t['candidate_id']:t for t in traces}
    state=Path(receipt['state_directory'])
    checks={name:checkpoint(state/name) for name in ('paper.sqlite','backups/paper-latest.sqlite')}
    intact=all(v['integrity']=='ok' and v['checksum_matches'] and v['source_hash']==receipt['source_hash_before'] for v in checks.values())
    clean=receipt['exit_code']==0 and health['status']=='STOPPED' and all(v['clean_shutdown'] for v in checks.values())
    report=FeedCertificationReport.evaluate(health=health,traces=traces,started_ms=start,finished_ms=end,
        source_unchanged=receipt['source_hash_before']==receipt['source_hash_after'],
        checkpoint_ok=intact,clean_shutdown=clean,regression_passed=regression_passed)
    samples_path=Path(receipt.get('health_samples_path',Path(receipt_path).with_name(Path(receipt_path).name.replace('_paper_receipt.json','_health_samples.jsonl'))))
    report.update(receipt=str(receipt_path),segment=str(segment),checkpoints=checks,
        source_hash=receipt['source_hash_before'],
        health_samples_checksum_matches=hashlib.sha256(samples_path.read_bytes()).hexdigest()==receipt['health_samples_sha256'],
        funnel=funnel.report(),cumulative_observations=len(all_traces),this_run_observations=len(traces),
        paper_results=json.loads((segment/'report.json').read_text())['portfolio'],
        actual_exchange_orders=health['exchange_orders_submitted'],
        local_fills=health['local_fills'],
        note='Only this run is counted in the comparison. Independent metric checks and sequential admissions have separate denominators. Local PAPER accounting is separate from the team wallet.')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(output.with_suffix('.json'),report)
    text=[f'Team Anchorium — {report["verdict"]}', '',
        f'Duration: {report["duration_seconds"]:.2f} seconds. Actual exchange orders: {report["actual_exchange_orders"]}.',
        f'PAPER fills: {report["local_fills"]}. Feed certified: {report["feed_certified"]}. Practice ready: false.',
        f'This session: {len(traces)} market observations; cumulative ledger: {len(all_traces)}.',
        '', 'Per-market valid scanner data windows:', '', '| Market | Evaluated | Healthy | Healthy % | Best consecutive windows |',
        '|---|---:|---:|---:|---:|']
    for symbol,v in report['per_market'].items():text.append(f'| {symbol} | {v["evaluated"]} | {v["healthy"]} | {v["healthy_percent"]:.2f} | {v["maximum_consecutive_healthy_windows"]} |')
    text+=['','Observed checks (independent; unobserved is excluded from evaluated):','',
        '| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted / evaluated |','|---|---:|---:|---:|---:|---:|']
    for v in report['funnel']['session']['stages']:
        percent=f'{v["pass_percent"]:.2f}' if v['pass_percent'] is not None else 'Not evaluated'
        text.append(f'| {v["stage"]} | {v["evaluated"]} | {v["passed"]} | {v["failed"]} | {percent} | {v["admission_passed"]} / {v["admission_evaluated"]} |')
    text+=['','First blocking reasons by category (each market-cycle counted once):','',
        json.dumps(report['funnel']['session']['first_rejection_categories'],indent=2),
        '',f'Disconnect reasons: {report["disconnect_reasons"]}.',
        f'Checkpoint and backup valid: {intact}. Clean shutdown: {clean}. Source unchanged during run: {receipt["source_unchanged"]}.',
        f'Certification blockers: {", ".join(report["blockers"]) or "None"}.',
        '', 'Close codes and transport timing absent in old runs remain unknown. A past error string alone cannot prove it was unresolved at shutdown. No strategy profitability or funded practice is certified.']
    output.with_suffix('.md').write_text('\n'.join(text)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--regression-passed',action='store_true')
    a=p.parse_args();r=generate(a.receipt,a.output,regression_passed=a.regression_passed)
    print(json.dumps({k:r[k] for k in ('verdict','duration_seconds','this_run_observations','actual_exchange_orders','feed_certified','blockers')}))


if __name__=='__main__':main()
