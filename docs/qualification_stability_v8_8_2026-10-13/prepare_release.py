from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
out=Path(__file__).resolve().parent
before=json.loads((out/'source_before.json').read_text())
changed=[name for name,value in before['files'].items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value]
expected={'algo-trading-bot/exchange/hyperliquid_client.py','algo-trading-bot/exchange/rate_limits.py','algo-trading-bot/exchange/testnet_qualification.py','scripts/run_testnet_qualification.py'}
if set(changed)!=expected:raise RuntimeError('UNEXPECTED_SOURCE_CHANGE:'+str(changed))
snapshot={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in before['files']}
new='algo-trading-bot/test_qualification_stability_v8_8.py'
snapshot[new]=hashlib.sha256((ROOT/new).read_bytes()).hexdigest()
atomic_json(out/'source_after.json',dict(source_hash=active_source_hash(ROOT),files=snapshot,modified_files=changed,new_files=[new],strategy_brain_unchanged=True,policy_unchanged=True))
original=(ROOT/'docs/qualification_recovery_v8_7_2026-10-13/run_full_regression.py').read_text()
runner=original.replace('prior baseline 1682 plus V8.7 dynamic sizing, ordered-clock and lifecycle regressions','prior baseline 1760 plus V8.8 bounded public HTTP, rate, cancellation and recovery regressions').replace('1682','1760')
(out/'run_full_regression.py').write_text(runner)
print(json.dumps(dict(source_hash=active_source_hash(ROOT),modified=changed,new=new)))
