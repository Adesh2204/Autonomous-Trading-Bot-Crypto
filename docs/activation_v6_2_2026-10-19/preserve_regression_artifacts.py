"""Preserve only this regression's generated paper artifacts, not execution state."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.terminal_app import locked
from exchange.paper_operations import atomic_json
archive=O/'regression_runtime_artifacts';archive.mkdir(exist_ok=True);r=dict(moved=[],restored=[])
for name in ('20261019T191902-regular-4032b994','20261019T191917-regular-c052731a','20261019T192727-regular-872c02f6','20261019T192734-regular-a4748cfd'):
 src=R/'algo-trading-bot/data/paper/runs'/name
 if src.exists():
  target=archive/name
  if target.exists():raise RuntimeError('PRESERVE_EXISTING_TEST_ARTIFACT')
  hashes={str(p.relative_to(src)):hashlib.sha256(p.read_bytes()).hexdigest() for p in src.rglob('*') if p.is_file()}
  shutil.move(str(src),str(target));r['moved'].append(dict(source=str(src.relative_to(R)),target=str(target.relative_to(R)),sha256=hashes))
for rel in ('algo-trading-bot/data/paper/regular-runtime.lock','docs/activation_v5_2_2026-10-19/preservation_receipt.json'):
 path=R/rel
 if path.suffix=='.lock' and locked(path):raise RuntimeError('PRESERVE_ACTIVE_LOCK')
 original=subprocess.check_output(['git','show','HEAD:'+rel],cwd=R)
 if original.startswith(b'version https://git-lfs'):raise RuntimeError('NO_LFS_POINTER_AS_CONTENT')
 if path.read_bytes()!=original:
  target=archive/(path.name+'.after_tests');target.write_bytes(path.read_bytes());path.write_bytes(original)
  r['restored'].append(dict(path=rel,retained=str(target.relative_to(R)),restored_sha256=hashlib.sha256(original).hexdigest()))
atomic_json(O/'runtime_artifact_preservation.json',r)
print(json.dumps(dict(moved=len(r['moved']),restored=len(r['restored']))))
