"""Read-only verification of the new recovery context; no signer or nonce allocation."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from dataclasses import asdict
from decimal import Decimal
from exchange.exit_recovery import Environment,profit_floor,QUANTITY,ENTRY_MS
from exchange.paper_operations import atomic_json
out=Path(__file__).resolve().parent/'recovery_context_read_only.json'
if out.exists():raise RuntimeError('PRESERVE_EXISTING_EVIDENCE')
env=None
r=dict(started_ms=time.time_ns()//1000000,signed_actions=0,scope='READ_ONLY_NO_SIGNER_NO_NONCE')
try:
 env=Environment(ROOT);c,e=env.context()
 fee=env.provider.conservative_fee(c)
 funding=sum((f.cashflow for f in env.recovery.state.funding.values() if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS),Decimal(0))
 be,floor=profit_floor(c.spec,QUANTITY,e.quantity*e.price,e.fee,fee,funding)
 r.update(source_hash=env.source,observed_ms=env.client.clock_ms(),positions=[asdict(p) for p in c.positions.values()],orders=list(c.open_orders),quote=asdict(c.quote),entry=asdict(e),readiness=asdict(c.readiness),conservative_fee=str(fee),fee_scale=env.provider.current_fee_scale,funding=str(funding),break_even=str(be),profit_floor=str(floor),account_truth_ready=env.recovery.account_truth_ready,rate_health=env.rates.health(),status='READ_ONLY_CONTEXT_VERIFIED')
except Exception as exc:
 r.update(status='READ_ONLY_CONTEXT_FAILED',error=str(exc),error_type=type(exc).__name__)
finally:
 if env:env.close()
 atomic_json(out,r)
print(json.dumps(r,default=str,indent=2))
raise SystemExit(0 if r['status']=='READ_ONLY_CONTEXT_VERIFIED' else 1)
