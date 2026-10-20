"""Read current frozen public-reader status without modifying its state."""
from pathlib import Path
import json,sys,time
O=Path(__file__).resolve().parent;R=O.parents[1];S=O/'public_reader_source'
sys.path.insert(0,str(S/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.operator_status import current_status
from exchange.terminal_app import locked
state=R/'runtime/pas-btc-ewy-v6-public';samples=[]
for _ in range(6):
 now=time.time_ns()//1000000;current=json.loads((state/'current.json').read_text())
 raw=json.loads((Path(current['output'])/'status.json').read_text())
 v=current_status(raw,current,running=locked(state/'owner.lock'),now_ms=now,source_hash=active_source_hash(S))
 samples.append(dict(observed_ms=now,status=v.get('status'),status_age_ms=v.get('status_age_ms'),
  worker_running=locked(state/'owner.lock'),public_source_matches=v.get('current_source_matches'),
  market_stream=v.get('stream_connected'),account_stream=v.get('account_stream_healthy'),
  history=v.get('market_history'),signals=v.get('signals'),liquidity=v.get('liquidity'),funding=v.get('funding'),
  account=v.get('account'),account_observed_ms=v.get('account_observed_ms'),
  TRADING_AUTHORIZED=v.get('TRADING_AUTHORIZED'),AUTO_TRADING_ACTIVE=v.get('AUTO_TRADING_ACTIVE')))
 if len(samples)<6:time.sleep(10)
atomic_json(O/'public_reader_samples.json',dict(source_root=str(S),source_hash=active_source_hash(S),samples=samples))
print(json.dumps({k:samples[-1].get(k) for k in ('status','status_age_ms','worker_running','public_source_matches','market_stream','account_stream','TRADING_AUTHORIZED','AUTO_TRADING_ACTIVE')},indent=2))
