"""Archive only this assignment's known offline regression fixtures."""
import fcntl,hashlib,json,shutil,subprocess
from pathlib import Path
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
r=json.loads((P/'regression_release_final/test_receipt.json').read_text())
assert r['passed'] is True
out=P/'offline_regression_artifacts';out.mkdir(exist_ok=False)
known=['20261016T220429-regular-28716d92','20261016T220434-regular-2fd228f2','20261016T221424-regular-0d80083c','20261016T221430-regular-a1014dde']
manifest=[]
for name in known:
 src=ROOT/'algo-trading-bot/data/paper/runs'/name
 if not src.is_dir():raise RuntimeError('MISSING_KNOWN_OFFLINE_FIXTURE:'+name)
 manifest.append(dict(original=str(src.relative_to(ROOT)),files={str(f.relative_to(src)):hashlib.sha256(f.read_bytes()).hexdigest() for f in src.rglob('*') if f.is_file()}))
 shutil.move(str(src),str(out/name))
lock=ROOT/'algo-trading-bot/data/paper/regular-runtime.lock'
with lock.open('r+b') as f:
 fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 current=f.read();identity=json.loads(current)
 if identity['pid']!=89432:raise RuntimeError('LEGACY_FIXTURE_LOCK_OWNER_CHANGED')
 before=subprocess.check_output(['git','show','HEAD:algo-trading-bot/data/paper/regular-runtime.lock'],cwd=ROOT)
 f.seek(0);f.truncate();f.write(before);f.flush()
 fcntl.flock(f,fcntl.LOCK_UN)
(P/'offline_artifact_archive_receipt.json').write_text(json.dumps(dict(offline_only=True,archive=manifest,fixture_lock_before_restore=current.decode(),restored_head_lock_sha256=hashlib.sha256(before).hexdigest()),indent=2)+'\n')
print('Archived four known offline regression directories and restored only their released legacy lock.')
