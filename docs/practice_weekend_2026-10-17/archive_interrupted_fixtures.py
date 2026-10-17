"""Archive only the two completed PAPER fixtures produced by this regression."""
from pathlib import Path
import fcntl,hashlib,json,subprocess
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
r=json.loads((P/'freshness_repair/interrupted_regression/test_receipt.json').read_text())
if r.get('intentionally_interrupted') is not True or r.get('passed') is not False:raise RuntimeError('MATCHED_INTERRUPTED_OFFLINE_RUN_REQUIRED')
names=tuple(f.parent.name for f in (ROOT/'algo-trading-bot/data/paper/runs').glob('*/identity.json') if json.loads(f.read_text()).get('process_id')==21897)
if len(names)!=2:raise RuntimeError('EXACT_TWO_OWN_OFFLINE_FIXTURES_REQUIRED')
parent=ROOT/'algo-trading-bot/data/paper';rows=[]
for name in names:
    path=parent/'runs'/name;identity=json.loads((path/'identity.json').read_text())
    if (identity['run_id']!=name or identity['process_id']!=21897 or identity['mode']!='PAPER'
            or identity['error']!='SystemExit' or not identity.get('completed_at')):
        raise RuntimeError('OFFLINE_FIXTURE_IDENTITY_REQUIRED')
    rows.append(dict(path=path,identity=identity))
target=P/'freshness_repair/interrupted_regression/offline_fixture_artifacts';target.mkdir(exist_ok=False)
lock=parent/'regular-runtime.lock'
with lock.open('r+b') as stream:
    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    prior=stream.read();identity=json.loads(prior)
    if identity.get('pid')!=21897:raise RuntimeError('UNRELATED_RUNTIME_LOCK_PRESERVE')
    original=subprocess.run(['git','show','HEAD:algo-trading-bot/data/paper/regular-runtime.lock'],
        cwd=ROOT,capture_output=True,check=True).stdout
    for row in rows:row['path'].rename(target/row['path'].name)
    stream.seek(0);stream.truncate();stream.write(original);stream.flush()
    fcntl.flock(stream,fcntl.LOCK_UN)
receipt=dict(scope='Only completed offline fixtures from this exact full regression',
    pytest_process=21897,regression_passed=False,intentionally_interrupted=True,fixtures=[x['identity'] for x in rows],
    released_lock_restored_from_HEAD=True,lock_sha256=hashlib.sha256(original).hexdigest(),
    actual_exchange_runtime_or_history_modified=False)
(P/'freshness_repair/interrupted_regression/offline_fixture_archive_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(dict(archived=[x['run_id'] for x in receipt['fixtures']],restored_released_fixture_lock=True)))
