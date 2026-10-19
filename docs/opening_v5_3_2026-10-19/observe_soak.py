"""Three-minute local observation of the genuine unsigned worker. No network/actions."""
from pathlib import Path
import json,os,sqlite3,sys,time
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.terminal_app import read_json,locked
from exchange.operator_status import current_status
from exchange.paper_operations import active_source_hash,atomic_json
state=ROOT/'runtime/pas-btc-ewy-v5-2';source=active_source_hash(ROOT)
samples=[];started=time.time_ns()//1000000
for index in range(7):
 now=time.time_ns()//1000000;current=read_json(state/'current.json')
 raw=read_json(Path(current['output'])/'status.json')
 v=current_status(raw,current,running=locked(state/'owner.lock'),now_ms=now,source_hash=source)
 try:os.kill(current['pid'],0);alive=True
 except PermissionError:alive=None
 except (OSError,KeyError):alive=False
 transport=v.get('stream_transport',{}).get('current',{})
 samples.append(dict(observed_ms=now,pid=current['pid'],session=current['session_id'],alive=alive,
  status=v.get('status'),status_age_ms=v.get('status_age_ms'),source_matches=v.get('current_source_matches'),
  owner_lock=v['process_lock_held'],stream_connected=v.get('stream_connected'),stream_reconciled=v.get('stream_reconciled'),
  stream_reconnections=v.get('stream_reconnections'),account_stream_healthy=v.get('account_stream_healthy'),
  account_age_ms=v.get('account_age_ms'),account_error=v.get('account_error'),
  funding=v.get('readiness',{}).get('funding'),
  candle_ages_ms={s:h.get('cache_age_ms') for s,h in v.get('market_history',{}).items()},
  candle_ready={s:h.get('strategy_history_ready') for s,h in v.get('market_history',{}).items()},
  latest_scan_ms=v.get('latest_scan_ms'),book_cache_ages_ms={s:now-c['book_ms'] for s,c in v.get('liquidity',{}).items() if type(c.get('book_ms')) is int},
  last_stream_book_message_ms=transport.get('last_book_message_at_ms'),
  public_reads=v.get('rate_report',{}).get('public_reads'),actual_errors=v.get('actual_errors'),
  signing_authority=v.get('signing_authority'),exchange_writes=v.get('exchange_writes'),signatures_created=v.get('signatures_created')))
 atomic_json(OUT/'soak_progress.json',dict(started_ms=started,samples=samples))
 if index<6:time.sleep(30)
current=read_json(state/'current.json');integrity={}
for path in (Path(current['output'])/'public.sqlite',state/'history.sqlite'):
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
  integrity[str(path.relative_to(ROOT))]=db.execute('pragma integrity_check').fetchone()[0]
result=dict(kind='ACTUAL_BOUNDED_PUBLIC_OBSERVATION',source_hash=source,source_hash_after=active_source_hash(ROOT),
 started_ms=started,finished_ms=time.time_ns()//1000000,samples=samples,integrity=integrity,
 local_events_persisted=(Path(current['output'])/'events.jsonl').stat().st_size>0,
 external_alert_delivery='NOT_CONFIGURED_OR_TESTED; no messages sent',
 no_overnight_uptime_claim=True,no_crash_injection_on_live_worker=True,
 exchange_writes=0,signatures_created=0)
atomic_json(OUT/'soak_result.json',result)
print(json.dumps(dict(samples=len(samples),duration_ms=result['finished_ms']-started,integrity=integrity)))
