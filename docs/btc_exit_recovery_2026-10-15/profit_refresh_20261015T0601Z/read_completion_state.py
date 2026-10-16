"""One read-only end-of-window account/fee/funding/book snapshot. No authority renewal."""
import json,sys,time
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.exit_recovery import Environment,QUANTITY,ENTRY_MS,ENTRY_OID,profit_floor
from exchange.order_lifecycle import OrderRequest
from exchange.paper_operations import atomic_json
OUT=Path(__file__).resolve().parent/'completion_read_only.json'
if OUT.exists():raise RuntimeError('PRESERVE_COMPLETION_EVIDENCE')
env=None;r=dict(scope='ACTUAL_TESTNET_READ_ONLY_AFTER_BOUNDED_WINDOW',started_ms=time.time_ns()//1000000,signatures_created=0,orders_submitted=0,authorization_renewed=False)
try:
 env=Environment(ROOT)
 draft=OrderRequest('par:BTC','SELL',QUANTITY,'81812',reduce_only=True,strategy_id='TESTNET_CERTIFICATION_EXIT',tif='Ioc')
 c=env.provider.load(draft,critical=True)
 fills=list(env.recovery.state.fills.values());funds=list(env.recovery.state.funding.values())
 fee=env.provider.conservative_fee(c)
 funding=sum((f.cashflow for f in funds if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS),D(0))
 entry=[f for f in fills if f.order_id==ENTRY_OID]
 if len(entry)!=1:raise RuntimeError('ORIGINAL_ENTRY_HISTORY_CHANGED_REVIEW_REQUIRED')
 e=entry[0];be,floor=profit_floor(c.spec,e.quantity,e.quantity*e.price,e.fee,fee,funding)
 after=env.account.get_positions();orders=env.account.get_frontend_open_orders()
 r.update(status='READ_ONLY_COMPLETION_VERIFIED',source_hash=env.source,observed_ms=env.client.clock_ms(),
   context_positions=[asdict(v) for v in c.positions.values()],positions_after=[asdict(v) for v in after.values()],
   orders=list(c.open_orders),orders_after=orders,quote=asdict(c.quote),readiness=asdict(c.readiness),
   reconciliation=asdict(env.recovery.last_report),fills=[asdict(f) for f in fills],funding_records=[asdict(f) for f in funds],
   funding_cashflow=str(funding),conservative_exit_fee=str(fee),fee_scale=env.provider.current_fee_scale,
   break_even=str(be),positive_buffer_floor=str(floor),
   conditional_net_at_observed_bid=str(e.quantity*c.quote.bid*(1-fee)-e.quantity*e.price-e.fee+funding),
   rate_report=env.rates.report(),protection_verified=False,organizer_whitelisting_confirmed=False)
except Exception as exc:r.update(status='READ_ONLY_COMPLETION_UNCERTAIN',error=str(exc),error_type=type(exc).__name__)
finally:
 if env:env.close()
 r['finished_ms']=time.time_ns()//1000000;atomic_json(OUT,r)
print(json.dumps({k:r.get(k) for k in ('status','error','observed_ms','positions_after','orders_after','quote','funding_cashflow','break_even','positive_buffer_floor','conditional_net_at_observed_bid')},indent=2,default=str))
raise SystemExit(0 if r['status']=='READ_ONLY_COMPLETION_VERIFIED' else 1)
