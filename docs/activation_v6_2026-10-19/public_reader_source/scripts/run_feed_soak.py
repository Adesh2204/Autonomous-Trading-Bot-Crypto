"""One bounded public PAPER evidence run with immutable source/test binding."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import PaperOwner,atomic_json,active_source_hash
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration
from feed_certification_report import generate


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=int,required=True);p.add_argument('--name',required=True)
    p.add_argument('--state-directory',type=Path,required=True);p.add_argument('--output-root',type=Path,required=True)
    p.add_argument('--test-receipt',type=Path,required=True)
    p.add_argument('--report-kind',choices=['feed','market-resilience'],default='feed')
    a=p.parse_args()
    if a.seconds<1 or not a.name.replace('_','').isalnum():p.error('Bounded duration and simple evidence name required')
    require_paper_migration();freeze=verify_strategy_freeze()
    if json.loads((ROOT/'configs/reliability_policy.json').read_text())['protection']['enabled']:raise RuntimeError('PROTECTION_MUST_REMAIN_DISABLED')
    source=active_source_hash(ROOT);tests=json.loads(a.test_receipt.read_text())
    if not (tests['passed'] and tests['source_hash']==source):raise RuntimeError('SOURCE_BOUND_REGRESSION_REQUIRED')
    a.output_root.mkdir(parents=True,exist_ok=True)
    receipt_path=a.output_root/(a.name+'_paper_receipt.json');samples_path=a.output_root/(a.name+'_health_samples.jsonl')
    if receipt_path.exists() or samples_path.exists() or (a.state_directory/'paper.sqlite').exists():raise RuntimeError('NEW_STATE_AND_EVIDENCE_REQUIRED')
    owner=PaperOwner(ROOT/'runtime/paper/feed-soak-owner.lock')
    receipt=dict(started_unix=time.time(),requested_duration_seconds=a.seconds,source_hash_before=source,
        state_directory=str(a.state_directory.resolve()),health_samples_path=str(samples_path.resolve()),
        execution_mode='PAPER',allow_live_orders=False,exchange_orders_submitted=0,strategy_freeze=freeze,
        test_receipt=str(a.test_receipt.resolve()))
    receipt['report_kind']=a.report_kind
    atomic_json(receipt_path,receipt)
    process=None
    try:
        command=[sys.executable,str(ROOT/'scripts/run_practice.py'),'--duration-seconds',str(a.seconds),
            '--state-directory',str(a.state_directory),'--output-root',str(a.output_root/'paper_segments')]
        process=subprocess.Popen(command,cwd=ROOT)
        seen=None;last_health=None
        with samples_path.open('w') as stream:
            while process.poll() is None:
                path=a.state_directory/'health.json'
                if path.exists():
                    try:health=json.loads(path.read_text())
                    except json.JSONDecodeError:time.sleep(.1);continue
                    if health['timestamp_ms']>=receipt['started_unix']*1000 and health['timestamp_ms']!=seen:
                        if health['execution_mode']!='PAPER' or health['allow_live_orders'] is not False or health['exchange_orders_submitted']!=0:
                            process.terminate();raise RuntimeError('PAPER_SAFETY_VIOLATION')
                        stream.write(json.dumps(health)+'\n');stream.flush();seen=health['timestamp_ms'];last_health=health
                time.sleep(1)
            if (a.state_directory/'health.json').exists():
                last_health=json.loads((a.state_directory/'health.json').read_text())
                stream.write(json.dumps(last_health)+'\n')
        receipt.update(finished_unix=time.time(),exit_code=process.returncode,final_health=last_health,
            source_hash_after=active_source_hash(ROOT),health_samples_sha256=hashlib.sha256(samples_path.read_bytes()).hexdigest())
        receipt['source_unchanged']=receipt['source_hash_before']==receipt['source_hash_after']
        atomic_json(receipt_path,receipt)
        if last_health and (Path(last_health['segment'])/'report.json').exists():
            if a.report_kind=='market-resilience':
                from market_resilience_report import generate as certify
            else:certify=generate
            certify(receipt_path,a.output_root/(a.name+'_certification'),regression_passed=tests['passed'])
        print(json.dumps(dict(receipt=str(receipt_path),exit_code=process.returncode)))
        return process.returncode
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=30)
        owner.close()


if __name__=='__main__':raise SystemExit(main())
