"""Approved bounded PAPER sequence. No signing or order transport."""
import hashlib,json,pathlib,subprocess,sys,time,traceback
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'algo-trading-bot'),str(pathlib.Path(__file__).parent)]
from exchange.paper_operations import atomic_json,active_source_hash,PaperOwner
from write_final_report import write_report
OUT=pathlib.Path(__file__).resolve().parent
owner=PaperOwner(ROOT/'runtime/paper/market-resilience-sequence-owner.lock')
try:
 tests=json.loads((OUT/'test_receipt.json').read_text())
 if not tests.get('passed') or tests['source_hash']!=tests['source_hash_after'] or tests['source_hash']!=active_source_hash(ROOT):raise RuntimeError('SOURCE_BOUND_FULL_REGRESSION_REQUIRED')
 if hashlib.sha256((OUT/'regression.xml').read_bytes()).hexdigest()!=tests['xml_sha256']:raise RuntimeError('TEST_XML_CHECKSUM_REQUIRED')
 if (OUT/'sequence.json').exists():raise RuntimeError('PRESERVE_EXISTING_SEQUENCE')
 sequence=dict(started_unix=time.time(),source_hash=tests['source_hash'],phase='STARTING',execution_mode='PAPER',allow_live_orders=False,protection_enabled=False,exchange_orders_submitted=0)
 atomic_json(OUT/'sequence.json',sequence)
 try:
  for label,seconds,folder,state_suffix in [('short_30m',1800,'short_soak','short'),('long_3h',10800,'long_soak','long')]:
   state=ROOT/('runtime/paper/market-resilience-2026-10-08-'+state_suffix+'-v2')
   output=OUT/folder
   sequence.update(phase='RUNNING_'+label.upper(),current_label=label,current_started_unix=time.time(),current_expected_finish_unix=time.time()+seconds,current_state_directory=str(state),current_output_root=str(output))
   atomic_json(OUT/'sequence.json',sequence)
   command=[sys.executable,str(ROOT/'scripts/run_feed_soak.py'),'--seconds',str(seconds),'--name',label,'--state-directory',str(state),'--output-root',str(output),'--test-receipt',str(OUT/'test_receipt.json'),'--report-kind','market-resilience']
   with (OUT/(label+'_process.log')).open('w') as log:result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
   sequence[label+'_exit_code']=result.returncode
   cert_path=output/(label+'_certification.json')
   cert=json.loads(cert_path.read_text()) if cert_path.exists() else None
   sequence[label+'_feed_certified']=bool(cert and cert['feed_certified'])
   sequence[label+'_blockers']=cert['blockers'] if cert else ['CERTIFICATION_UNAVAILABLE']
   atomic_json(OUT/'sequence.json',sequence)
   if result.returncode!=0:
    sequence['phase']='FAILED';break
   if not cert or not cert['feed_certified']:
    sequence['phase']='SHORT_GATE_FAILED' if label=='short_30m' else 'COMPLETED_FEED_NOT_READY';break
   if active_source_hash(ROOT)!=tests['source_hash']:
    sequence['phase']='SOURCE_CHANGED';break
   if label=='long_3h':sequence['phase']='COMPLETED_FEED_READY'
  sequence['finished_unix']=time.time();atomic_json(OUT/'sequence.json',sequence);write_report(OUT)
 except Exception as exc:
  sequence.update(phase='FAILED',reason=type(exc).__name__+':'+str(exc),finished_unix=time.time());atomic_json(OUT/'sequence.json',sequence)
  traceback.print_exc();write_report(OUT)
finally:owner.close()
