"""Bounded complete PAPER launcher plus local heartbeat evidence. No signer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.paper_operations import active_source_hash, atomic_json
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds', type=int, default=3600)
parser.add_argument('--segment', default='continuous')
args = parser.parse_args()
OUT = Path(__file__).resolve().parent
STATE = ROOT / 'runtime/paper/readiness-2026-10-07-paced-source'
receipt_path = OUT / (args.segment + '_paper_receipt.json')
samples_path = OUT / (args.segment + '_health_samples.jsonl')
if receipt_path.exists() or samples_path.exists() or args.seconds < 1:
    raise RuntimeError('NEW_BOUNDED_PAPER_EVIDENCE_REQUIRED')
require_paper_migration()
verify_strategy_freeze()
receipt = dict(started_unix=time.time(), source_hash_before=active_source_hash(ROOT),
               requested_duration_seconds=args.seconds, state_directory=str(STATE),
               host='CURRENT_LOCAL_MAC', execution_mode='PAPER', allow_live_orders=False,
               exchange_orders_submitted=0, account_actions_submitted=0)
atomic_json(receipt_path, receipt)
command = [sys.executable, str(ROOT / 'scripts/run_practice.py'),
           '--duration-seconds', str(args.seconds), '--state-directory', str(STATE),
           '--output-root', str(OUT / 'paper_segments')]
process = subprocess.Popen(command, cwd=ROOT)
seen = None
with samples_path.open('a') as samples:
    while process.poll() is None:
        health_path = STATE / 'health.json'
        if health_path.exists():
            health = json.loads(health_path.read_text())
            if health.get('timestamp_ms') != seen:
                samples.write(json.dumps(health) + '\n')
                samples.flush()
                seen = health.get('timestamp_ms')
        time.sleep(2)
    if (STATE / 'health.json').exists():
        health = json.loads((STATE / 'health.json').read_text())
        samples.write(json.dumps(health) + '\n')
        receipt['final_health'] = health
receipt.update(finished_unix=time.time(), exit_code=process.returncode,
               source_hash_after=active_source_hash(ROOT))
receipt['source_unchanged'] = receipt['source_hash_before'] == receipt['source_hash_after']
receipt['health_samples_sha256'] = hashlib.sha256(samples_path.read_bytes()).hexdigest()
atomic_json(receipt_path, receipt)
print(json.dumps(dict(receipt=str(receipt_path), exit_code=process.returncode,
                     source_unchanged=receipt['source_unchanged'])))
raise SystemExit(process.returncode)
