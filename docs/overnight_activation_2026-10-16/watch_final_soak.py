"""Report-only sampling of the launched CLI; cannot start, signal or trade."""
import json,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
state=HERE/'final_soak';out=HERE/'final_soak_resource_samples.jsonl'
with out.open('x') as f:
 for _ in range(70):
  try:
   c=json.loads((state/'current.json').read_text());d=Path(c['output']);r=json.loads((d/'status.json').read_text())
   sample={k:r.get(k) for k in ('updated_ms','session_id','pid','status','source_hash','rss_high_watermark_mb',
    'stream_connected','stream_reconciled','account_stream_connected','account_stream_healthy','account_subscriptions',
    'public_receipt_count','actual_errors','account_age_ms','status_age_ms','journal_integrity','execution_intents','terminal_flat')}
   sample.update(sampled_ms=time.time_ns()//1000000,total_bytes=sum(p.stat().st_size for p in d.rglob('*') if p.is_file()),
    event_bytes=(d/'events.jsonl').stat().st_size if (d/'events.jsonl').exists() else 0,
    receipt_bytes=(d/'info_receipts.jsonl').stat().st_size if (d/'info_receipts.jsonl').exists() else 0)
   f.write(json.dumps(sample)+'\n');f.flush()
   if r['status'] in {'STOPPED','HALTED'}:break
  except (OSError,ValueError):pass
  time.sleep(15)
