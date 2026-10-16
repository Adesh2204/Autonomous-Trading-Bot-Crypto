"""Read saved PAPER completion, checkpoint and backup; never relabel its source."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from exchange.paper_checkpoint import unpack

receipt = json.loads((OUT/'followup_paper_receipt.json').read_text())
if 'finished_unix' not in receipt:
    raise RuntimeError('PAPER_SEGMENT_STILL_RUNNING')
state = Path(receipt['state_directory'])
segment = Path(receipt['final_health']['segment'])
paper = json.loads((segment/'report.json').read_text())
samples = [json.loads(row) for row in (OUT/'followup_health_samples.jsonl').read_text().splitlines()]
running = list({s['timestamp_ms']:s for s in samples if s['status']=='RUNNING' and s.get('segment')==str(segment)}.values())
checks = {}
for relative in ('paper.sqlite','backups/paper-latest.sqlite'):
    with sqlite3.connect((state/relative).resolve().as_uri()+'?mode=ro', uri=True) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        raw, checksum = db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
        value = unpack(json.loads(raw))
        checks[relative] = dict(integrity=integrity, checksum_matches=hashlib.sha256(raw.encode()).hexdigest()==checksum,
            clean_shutdown=value['clean'], saved_source_hash=value['identity']['active_source_hash'])
scan_ids = {json.loads(row)['scan_observed_at_ms'] for row in (segment/'candles.jsonl').read_text().splitlines()}
funnel = json.loads((segment/'results/funnel_summary.json').read_text())
scanner = next(s for s in funnel['session']['stages'] if s['stage']=='SCANNER_QUALIFIED')
result = dict(scope='COMPLETED_PUBLIC_PAPER_EVIDENCE_ONLY', elapsed_seconds=receipt['finished_unix']-receipt['started_unix'],
    requested_seconds=receipt['requested_duration_seconds'], exit_code=receipt['exit_code'], source_unchanged=receipt['source_unchanged'],
    source_hash=receipt['source_hash_before'], final_status=receipt['final_health']['status'], heartbeat_samples=len(running),
    any_healthy_samples=sum(bool(s['data_healthy']) for s in running), healthy_counts=dict(Counter(m for s in running for m in s['healthy_markets'])),
    scanner_cycles=len(scan_ids), scanner_qualified=scanner['passed'], scanner_rejection_reasons=scanner['rejection_reasons'],
    local_fills=receipt['final_health']['local_fills'], local_positions=receipt['final_health']['local_positions'],
    exchange_orders_submitted=0, signer_constructed=False, reconnections=receipt['final_health']['public_stream']['reconnections'],
    paper_accounting_halt=paper['accounting_halt'], checkpoints=checks, segment=str(segment),
    observed_at_utc=datetime.now(timezone.utc).isoformat())
with (OUT/'paper_completion.json').open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
