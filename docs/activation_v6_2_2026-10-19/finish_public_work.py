"""After a passing release, run only unsigned reads and replace the public reader."""
from pathlib import Path
import json,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
receipt=O/'regression_release_final/test_receipt.json'
for _ in range(900):
 r=json.loads(receipt.read_text()) if receipt.exists() else {}
 if r.get('finished_unix'):
  if not r.get('passed'):raise SystemExit('FAILED_REGRESSION_NO_FURTHER_ACTION')
  break
 time.sleep(2)
else:raise SystemExit('REGRESSION_WAIT_EXPIRED_NO_FURTHER_ACTION')
for name in ('prepare_final_review.py','launch_verified_public_reader.py'):
 with (O/(name+'.log')).open('x') as f:
  p=subprocess.run([sys.executable,str(O/name)],cwd=R,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,timeout=900)
 if p.returncode:raise SystemExit('PUBLIC_ONLY_HANDOFF_STEP_FAILED:'+name)
launch=json.loads((O/'public_reader_launch.json').read_text());state=Path(launch['state'])
for _ in range(120):
 if (state/'current.json').exists():
  current=json.loads((state/'current.json').read_text());path=Path(current['output'])/'status.json'
  if path.exists():
   status=json.loads(path.read_text())
   if (status.get('source_hash')==launch['source_hash'] and status.get('latest_scan_ms') is not None
      and len(status.get('signals',[]))==2 and status.get('stream_connected') is True
      and status.get('account_stream_healthy') is True):
    (O/'public_reader_initial_verified_snapshot.json').write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps(dict(status='UNSIGNED_HANDOFF_COMPLETE',source_hash=launch['source_hash'],automatic_trading=False)));break
 time.sleep(1)
else:raise SystemExit('PUBLIC_READER_WARMUP_UNCONFIRMED_READ_STATUS')
