"""Read local PAPER evidence only; no network or wallet access."""
from collections import Counter
import json
from pathlib import Path
import time

OUT = Path(__file__).resolve().parent
receipt = json.loads((OUT / 'continuous_paper_receipt.json').read_text())
health = json.loads((Path(receipt['state_directory']) / 'health.json').read_text())
samples = [json.loads(line) for line in (OUT / 'continuous_health_samples.jsonl').read_text().splitlines()]
running = {s['timestamp_ms']: s for s in samples if s['status'] == 'RUNNING'}
counts = Counter(m for s in running.values() for m in s['healthy_markets'])
print(json.dumps(dict(elapsed_minutes=round((time.time() - receipt['started_unix']) / 60, 1),
    remaining_minutes=round(max(0, receipt['started_unix'] + receipt['requested_duration_seconds'] - time.time()) / 60, 1),
    status=health['status'], running_heartbeat_samples=len(running),
    healthy_market_heartbeats=dict(sorted(counts.items())),
    any_healthy_heartbeats=sum(bool(s['healthy_markets']) for s in running.values()),
    all_ten_healthy_heartbeats=sum(len(s['healthy_markets']) == 10 for s in running.values()),
    scan=health['scan_status'], current_healthy_markets=health['healthy_markets'],
    local_fills=health['local_fills'], local_positions=health['local_positions'],
    exchange_orders_submitted=health['exchange_orders_submitted'],
    reconnections=health['public_stream'].get('reconnections'),
    messages=health['public_stream'].get('messages'),
    current_issues=health['issues'], memory_mb=round(health['rss_high_watermark_mb'], 1))))
