"""One bounded V6 PAPER job, not a recurring task. No signer or account calls."""
from pathlib import Path
import fcntl,hashlib,json,os,subprocess,sys,time,traceback
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
OUT=BASE/'validated_run';OUT.mkdir(exist_ok=False)
os.environ.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',
    TRADING_VENUE='HYPERLIQUID_TESTNET',HL_NETWORK='testnet',HL_DEX='par')
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import atomic_json,active_source_hash,PaperOwner
TESTS=BASE/'regression_final_v2/test_receipt.json'
tests=json.loads(TESTS.read_text())
if not tests['passed'] or tests['source_hash']!=tests['source_hash_after'] or tests['source_hash']!=active_source_hash(ROOT):raise RuntimeError('FINAL_SOURCE_BOUND_TESTS_REQUIRED')
if hashlib.sha256(TESTS.with_name('regression.xml').read_bytes()).hexdigest()!=tests['xml_sha256']:raise RuntimeError('TEST_XML_HASH_REQUIRED')
if (OUT/'validation_sequence.json').exists():raise RuntimeError('PRESERVE_PREVIOUS_VALIDATION')
for p in (ROOT/'runtime/paper').rglob('*owner.lock'):
    with p.open('r') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
        except BlockingIOError:raise RuntimeError('PAPER_ALREADY_RUNNING:'+str(p))
owner=PaperOwner(ROOT/'runtime/paper/v6-validation-owner.lock')
sequence=dict(started_unix=time.time(),source_hash=tests['source_hash'],execution_mode='PAPER',
    allow_live_orders=False,protection_enabled=False,actual_exchange_orders=0,phase='STARTING')
atomic_json(OUT/'validation_sequence.json',sequence)
try:
    for name,seconds in [('short_15m',900),('long_3h',10800)]:
        state=ROOT/('runtime/paper/candle-integrity-v6-2026-10-10-'+name+'-v2')
        output=OUT/name
        if state.exists():raise RuntimeError('FRESH_STATE_REQUIRED')
        sequence.update(phase='RUNNING_'+name.upper(),current_state=str(state),current_output=str(output),
            expected_finish_unix=time.time()+seconds)
        atomic_json(OUT/'validation_sequence.json',sequence)
        command=[sys.executable,str(ROOT/'scripts/run_feed_soak.py'),'--seconds',str(seconds),
            '--name',name,'--state-directory',str(state),'--output-root',str(output),
            '--test-receipt',str(TESTS),'--report-kind','market-resilience']
        with (OUT/(name+'_process.log')).open('w') as log:
            process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        sequence[name+'_exit_code']=process.returncode
        cert_path=output/(name+'_certification.json')
        cert=json.loads(cert_path.read_text()) if cert_path.exists() else {}
        sequence[name+'_feed_certified']=bool(cert.get('feed_certified'))
        sequence[name+'_blockers']=cert.get('blockers',['CERTIFICATION_UNAVAILABLE'])
        receipt=output/(name+'_paper_receipt.json')
        if receipt.exists() and cert:
            subprocess.run([sys.executable,str(BASE/'analyze_run.py'),str(receipt)],cwd=ROOT,check=True)
        numeric=json.loads((output/'candle_stage_audit.json').read_text()).get('numeric_errors',[]) if (output/'candle_stage_audit.json').exists() else []
        sequence[name+'_unresolved_numeric_count']=len(numeric)
        atomic_json(OUT/'validation_sequence.json',sequence)
        if process.returncode or not cert.get('feed_certified') or numeric:
            sequence['phase']='SHORT_GATE_FAILED' if name=='short_15m' else 'COMPLETED_FEED_NOT_READY';break
        if active_source_hash(ROOT)!=tests['source_hash']:raise RuntimeError('SOURCE_MUTATION_DURING_OBSERVATION')
        if name=='long_3h':sequence['phase']='COMPLETED_FEED_CERTIFIED'
    sequence['finished_unix']=time.time();atomic_json(OUT/'validation_sequence.json',sequence)
except Exception as exc:
    sequence.update(phase='FAILED',reason=type(exc).__name__+':'+str(exc),finished_unix=time.time())
    atomic_json(OUT/'validation_sequence.json',sequence);traceback.print_exc();raise
finally:owner.close()
