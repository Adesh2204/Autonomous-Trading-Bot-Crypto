"""Archive only known generated test artifacts; retain preexisting user changes."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.terminal_app import locked
from exchange.paper_operations import atomic_json
archive=OUT/'regression_runtime_artifacts';archive.mkdir(exist_ok=True)
r=dict(moved=[],restored_known_clean_files=[],original_execution_journals_modified=False)
for name in ('20261019T162347-regular-83800f81','20261019T162352-regular-1476be31'):
 source=ROOT/'algo-trading-bot/data/paper/runs'/name
 if source.exists():
  target=archive/name
  if target.exists():raise RuntimeError('PRESERVE_EXISTING_ARTIFACT')
  files={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
  shutil.move(str(source),str(target));r['moved'].append(dict(source=str(source.relative_to(ROOT)),target=str(target.relative_to(ROOT)),file_hashes=files))
for relative in ('algo-trading-bot/data/paper/regular-runtime.lock','docs/activation_v5_2_2026-10-19/preservation_receipt.json'):
 path=ROOT/relative
 if path.suffix=='.lock' and locked(path):raise RuntimeError('ACTIVE_PAPER_LOCK_MUST_NOT_BE_REPLACED')
 # Both files were clean in the initial task status. Archive our generated
 # contents before restoring those exact original committed bytes.
 original=subprocess.check_output(['git','show','HEAD:'+relative],cwd=ROOT)
 if original.startswith(b'version https://git-lfs'):raise RuntimeError('DO_NOT_RESTORE_POINTER_AS_CONTENT')
 if path.read_bytes()!=original:
  saved=archive/(path.name+'.after_tests');saved.write_bytes(path.read_bytes());path.write_bytes(original)
  r['restored_known_clean_files'].append(dict(path=relative,retained_generated_copy=str(saved.relative_to(ROOT)),restored_sha256=hashlib.sha256(original).hexdigest()))
atomic_json(OUT/'runtime_artifact_preservation.json',r);print(json.dumps(dict(moved=len(r['moved']),restored=len(r['restored_known_clean_files']))))
