"""Exactly one bounded V7 PAPER run. No automatic long run or recurring monitor."""
from pathlib import Path
import fcntl,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
os.environ.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',
 TRADING_VENUE='HYPERLIQUID_TESTNET',HL_NETWORK='testnet',HL_DEX='par',
 SIGNAL_DATA_MODE='PAR_NATIVE_ONLY',EXTERNAL_RESEARCH_ENABLED='false',EXTERNAL_SIGNAL_LIVE_APPROVED='false')
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json,PaperOwner
TESTS=BASE/'regression_release/test_receipt.json';tests=json.loads(TESTS.read_text())
if not tests['passed'] or tests['source_hash']!=tests['source_hash_after'] or tests['source_hash']!=active_source_hash(ROOT):raise RuntimeError('SOURCE_BOUND_FULL_REGRESSION_REQUIRED')
if hashlib.sha256(TESTS.with_name('regression.xml').read_bytes()).hexdigest()!=tests['xml_sha256']:raise RuntimeError('TEST_XML_CHECKSUM_REQUIRED')
if json.loads((ROOT/'configs/reliability_policy.json').read_text())['protection']['enabled']:raise RuntimeError('PROTECTION_MUST_STAY_DISABLED')
for lock in (ROOT/'runtime/paper').rglob('*owner.lock'):
 with lock.open('r') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
  except BlockingIOError:raise RuntimeError('ACTIVE_PAPER_OWNER:'+str(lock))
processes=subprocess.check_output(['ps','-axo','pid,ppid,etime,command'],text=True)
active=[r for r in processes.splitlines() if 'python' in r.lower() and any(s in r for s in ('scripts/run_practice.py','scripts/run_crypto_paper.py','scripts/run_feed_soak.py'))]
if active:raise RuntimeError('CONFLICTING_PAPER_PROCESS')
OUT=BASE/'short_15m';STATE=ROOT/'runtime/paper/availability-v7-2026-10-10-short'
if OUT.exists() or STATE.exists():raise RuntimeError('FRESH_STATE_AND_OUTPUT_REQUIRED')
owner=PaperOwner(ROOT/'runtime/paper/v7-validation-owner.lock')
sequence=dict(started_ms=time.time_ns()//1000000,state_directory=str(STATE),output=str(OUT),
 source_hash=tests['source_hash'],execution_mode='PAPER',allow_live_orders=False,protection_enabled=False,
 requested_seconds=900,actual_exchange_orders=0,long_run_started=False,phase='RUNNING')
atomic_json(BASE/'validation_sequence.json',sequence)
try:
 command=[sys.executable,str(ROOT/'scripts/run_feed_soak.py'),'--seconds','900','--name','short_15m',
  '--state-directory',str(STATE),'--output-root',str(OUT),'--test-receipt',str(TESTS),'--report-kind','market-resilience']
 with (BASE/'short_15m_process.log').open('w') as log:
  result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 certpath=OUT/'short_15m_certification.json'
 cert=json.loads(certpath.read_text()) if certpath.exists() else {}
 sequence.update(finished_ms=time.time_ns()//1000000,exit_code=result.returncode,
  source_hash_after=active_source_hash(ROOT),source_unchanged=active_source_hash(ROOT)==tests['source_hash'],
  feed_certified=cert.get('feed_certified',False),blockers=cert.get('blockers',['CERTIFICATION_UNAVAILABLE']),
  phase='COMPLETED' if result.returncode==0 else 'FAILED')
 atomic_json(BASE/'validation_sequence.json',sequence)
 print(json.dumps(sequence,indent=2))
finally:owner.close()
