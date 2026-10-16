"""Bounded PAPER sequence: short soak, reviewed engineering gates, then three hours."""
import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import atomic_json,active_source_hash
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze
OUT=Path(__file__).resolve().parent
sequence_path=OUT/'sequence.json'
if sequence_path.exists():raise RuntimeError('PRESERVE_EXISTING_SEQUENCE')
require_paper_migration();verify_strategy_freeze()
tests=json.loads((OUT/'test_receipt.json').read_text())
if not tests.get('passed') or tests['source_hash']!=active_source_hash(ROOT):raise RuntimeError('CURRENT_SOURCE_FULL_REGRESSION_REQUIRED')
sequence={'started_unix':time.time(),'source_hash':tests['source_hash'],'phase':'STARTING','execution_mode':'PAPER','allow_live_orders':False,'protection_enabled':False,'orders_submitted':0}
atomic_json(sequence_path,sequence)
for label,seconds,state_name,folder in [('short_15m_v2',900,'feed-certification-2026-10-07-short-v2','short_soak_v2'),('long_3h',10800,'feed-certification-2026-10-07-long','long_soak')]:
 sequence.update(phase='RUNNING_'+label.upper(),current_started_unix=time.time(),current_expected_finish_unix=time.time()+seconds,current_state_directory=str(ROOT/'runtime/paper'/state_name),current_output_root=str(OUT/folder),current_label=label)
 atomic_json(sequence_path,sequence)
 command=[sys.executable,'-u',str(ROOT/'scripts/run_feed_soak.py'),'--seconds',str(seconds),'--name',label,'--state-directory',str(ROOT/'runtime/paper'/state_name),'--output-root',str(OUT/folder),'--test-receipt',str(OUT/'test_receipt.json')]
 result=subprocess.run(command,cwd=ROOT)
 sequence[label+'_exit_code']=result.returncode
 if result.returncode!=0:
  sequence.update(phase='FAILED_'+label.upper(),finished_unix=time.time(),long_run_blocked=True)
  atomic_json(sequence_path,sequence);raise SystemExit(result.returncode)
 certificate_path=OUT/folder/(label+'_certification.json')
 certificate=json.loads(certificate_path.read_text())
 if label=='short_15m_v2':
  # Short soak is a regression gate. Legitimate sparse/stale venue windows are
  # still reported as feed-certification failures, but may be observed longer.
  engineering={k:v for k,v in certificate['checks'].items() if k not in {'sustained_valid_market','final_valid_market'}}
  sequence['short_engineering_checks']=engineering
  sequence['short_feed_certified']=certificate['feed_certified']
  sequence['short_feed_blockers']=certificate['blockers']
  if not all(engineering.values()):
   sequence.update(phase='SHORT_ENGINEERING_GATE_FAILED',finished_unix=time.time(),long_run_blocked=True)
   atomic_json(sequence_path,sequence);raise SystemExit(2)
  if active_source_hash(ROOT)!=tests['source_hash']:raise RuntimeError('SOURCE_CHANGED_BEFORE_LONG_RUN')
sequence.update(phase='COMPLETED',finished_unix=time.time())
atomic_json(sequence_path,sequence)
