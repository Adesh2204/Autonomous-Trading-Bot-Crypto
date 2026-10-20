"""Freeze the last verified public reader before development; never copy credentials."""
from pathlib import Path
import hashlib,json,shutil,sqlite3,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
source=active_source_hash(ROOT);snapshot=OUT/'public_reader_source';snapshot.mkdir(exist_ok=False)
for d in ('scripts','algo-trading-bot'):
 for p in (ROOT/d).rglob('*.py'):
  if {'venv','.venv','__pycache__'}&set(p.parts):continue
  target=snapshot/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for relative in ('algo-trading-bot/requirements.txt','docs/strategy_freeze.json'):
 target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
shutil.copytree(ROOT/'configs',snapshot/'configs')
(snapshot/'runtime').mkdir();(snapshot/'runtime/testnet').symlink_to(ROOT/'runtime/testnet',target_is_directory=True)
assert active_source_hash(snapshot)==source
state=ROOT/'runtime/pas-btc-ewy-v6-public';state.mkdir(exist_ok=False)
original=ROOT/'runtime/pas-btc-ewy-v5-2/history.sqlite'
with sqlite3.connect(original.resolve().as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(state/'history.sqlite') as dst:src.backup(dst)
result=dict(source_hash=source,snapshot=str(snapshot),public_state=str(state),history_copy='SQLite read-only backup; original unchanged',credentials_copied=False,signer_available=False,execution_state_link='Original journals are read by the public diagnostic only; no execution client is constructed')
(OUT/'public_reader_source_receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
