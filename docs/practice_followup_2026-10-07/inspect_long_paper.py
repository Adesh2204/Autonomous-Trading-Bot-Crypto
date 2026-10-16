"""Read-only freshness observations for the bounded run; never changes entry rules."""
from collections import Counter
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import atomic_json,active_source_hash
from exchange.paper_checkpoint import unpack
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


def inspect():
 launch=json.loads((OUT/'long_3h_launch.json').read_text())
 receipt_path=Path(launch['completion_receipt'])
 receipt=json.loads(receipt_path.read_text())
 completed='finished_unix' in receipt
 health=receipt.get('final_health') or json.loads((Path(launch['state_directory'])/'health.json').read_text())
 assert health['timestamp_ms']>=int(launch['started_unix']*1000)
 segment=Path(health['segment'])
 monitor=json.loads((OUT/'long_3h_monitor_setup.json').read_text())
 assert segment.parent==Path(launch['output_root']) and segment==Path(monitor['segment'])
 source=active_source_hash(ROOT)
 lock=require_paper_migration();freeze=verify_strategy_freeze()
 assert source==launch['source_hash']==receipt['source_hash_before']
 assert freeze['passed']
 policy=json.loads((ROOT/'configs/reliability_policy.json').read_text())
 assert policy['protection']['enabled'] is False
 latest={};by_scan={};counts=Counter();max_streak=Counter();streak=Counter();last_scan={}
 with (segment/'candles.jsonl').open() as f:
  for line in f:
   row=json.loads(line);symbol=row['symbol'];scan=row['scan_observed_at_ms'];candles=row['candles']
   assert symbol.startswith('par:')
   last=candles[-1]['timestamp_ms'] if candles else None
   age=scan-(last+60000) if last is not None else None
   tail=[c['timestamp_ms'] for c in candles[-300:]]
   contiguous=len(tail)==300 and all(b-a==60000 for a,b in zip(tail,tail[1:]))
   # Observation as of scan export; scanner decision remains authoritative.
   fresh=len(candles)>=300 and age is not None and 0<=age<=120000
   obs=dict(scan_observed_at_ms=scan,completed_rows=len(candles),latest_open_ms=last,
     latest_close_age_seconds=age/1000 if age is not None else None,
     fresh_300_rows_as_of_scan_export=fresh,last_300_rows_contiguous=contiguous)
   latest[symbol]=obs
   if last_scan.get(symbol)==scan:continue
   last_scan[symbol]=scan
   counts[symbol]+=int(fresh);streak[symbol]=streak[symbol]+1 if fresh else 0
   max_streak[symbol]=max(max_streak[symbol],streak[symbol])
   by_scan.setdefault(scan,[])
   if fresh:by_scan[scan].append(symbol)
 report=json.loads((segment/'report.json').read_text())
 rows=[json.loads(s) for s in Path(launch['health_samples']).read_text().splitlines()]
 rows=list({s['timestamp_ms']:s for s in rows if s.get('segment')==str(segment) and s.get('status')=='RUNNING'}.values())
 baseline=next(s for s in launch['prior_funnel_baseline']['session']['stages'] if s['stage']=='SCANNER_QUALIFIED')
 funnel=json.loads((segment/'results/funnel_summary.json').read_text())
 scanner=next(s for s in funnel['session']['stages'] if s['stage']=='SCANNER_QUALIFIED')
 rejections={k:v-baseline['rejection_reasons'].get(k,0) for k,v in scanner['rejection_reasons'].items()}
 result=dict(scope='PUBLIC_PAPER_FRESHNESS_OBSERVATION_NOT_ENTRY_AUTHORIZATION',completed=completed,
   observed_at_utc=datetime.now(timezone.utc).isoformat(),safety=lock,strategy_freeze=freeze,
   source_hash=source,protection_enabled=False,segment=str(segment),health=health,
   latest_candle_observations=latest,fresh_300_observations=dict(counts),max_consecutive_fresh_300_scans=dict(max_streak),
   scans_with_any_fresh_300=sum(bool(v) for v in by_scan.values()),scanner_cycles=len(by_scan),
   scanner_qualified_this_run=scanner['passed']-baseline['passed'],scanner_rejections_this_run=rejections,
   running_heartbeat_samples=len(rows),heartbeats_with_any_healthy_market=sum(bool(r['data_healthy']) for r in rows),
   public_reconnects=health['public_stream']['reconnections'],hypothetical_local_fills=report['local_fills'],
   hypothetical_portfolio=report['portfolio'],accounting_halt=report['accounting_halt'],actual_orders_submitted=0,
   expected_finish_ist=launch['expected_finish_ist'],
   freshness_explanation='Actual completed rows and latest close age at scan export. Contiguity is reported separately as an observation. It is not a new admission gate or a change to scanner behavior.',
   sample_explanation='Health samples are observations, not proof of uninterrupted healthy feed. Local PAPER fills/portfolio are separate from actual account truth.')
 if completed:
  assert receipt['source_unchanged'] and receipt['source_hash_after']==source
  result['exit_code']=receipt['exit_code'];result['elapsed_seconds']=receipt['finished_unix']-receipt['started_unix']
  result['checkpoints']={}
  for rel in ['paper.sqlite','backups/paper-latest.sqlite']:
   with sqlite3.connect((Path(launch['state_directory'])/rel).resolve().as_uri()+'?mode=ro',uri=True) as db:
    raw,digest=db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
    value=unpack(json.loads(raw))
    result['checkpoints'][rel]=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
      checksum_matches=hashlib.sha256(raw.encode()).hexdigest()==digest,clean_shutdown=value['clean'])
 atomic_json(OUT/'long_3h_progress.json',result)
 return result


if __name__=='__main__':
 result=inspect()
 print(json.dumps({'completed':result['completed'],'status':result['health']['status'],
   'scan':result['health']['scan_status'],'scanner_cycles':result['scanner_cycles'],
   'fresh_300_rows':{s:o['fresh_300_rows_as_of_scan_export'] for s,o in result['latest_candle_observations'].items()},
   'real_orders':0,'progress':str(OUT/'long_3h_progress.json')},indent=2))
