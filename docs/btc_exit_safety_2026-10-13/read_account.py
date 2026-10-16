"""One public TESTNET /info observation. No order client or actual signatures."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib, json, sys, threading
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash, atomic_json
from exchange.qualification_watcher import ReadOnlyQualificationSession, source_unchanged
from exchange.emergency_qualification import EmergencyContextProvider
from exchange.order_lifecycle import OrderRequest
from exchange.full_position_close import observed_scope
from exchange.partial_fill_safety import MIN_NOTIONAL
from exchange.base_exchange import decimal
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze

require_paper_migration(); verify_strategy_freeze()
out=Path(__file__).resolve().parent/(sys.argv[1] if len(sys.argv)>1 else 'read_only_account');out.mkdir(exist_ok=False)
source=active_source_hash(ROOT)
policy=hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest()
http=requests.Session.post;calls=[]
def info_only(session,url,**kwargs):
    if url!='https://api.hyperliquid-testnet.xyz/info':
        raise RuntimeError('ALL_NON_INFO_HTTP_BLOCKED')
    body=kwargs.get('json',{})
    if 'signature' in body or body.get('type')=='order':
        raise RuntimeError('SIGNED_PAYLOAD_BLOCKED')
    calls.append(dict(type=body.get('type'),dex=body.get('dex'),coin=body.get('coin')))
    return http(session,url,**kwargs)
requests.Session.post=info_only
def progress(event, **fields):
    with (out/'progress.jsonl').open('a') as stream:
        stream.write(json.dumps(dict(event=event,**fields),default=str)+'\n')
s=ReadOnlyQualificationSession(ROOT,out,source,policy,progress=progress,cancel_event=threading.Event())
s._provider_class=EmergencyContextProvider
r=dict(status='READ_ONLY_IN_PROGRESS',observed_utc=datetime.now(timezone.utc).isoformat(),
    source_hash=source,execution_mode='PAPER',allow_live_orders=False,
    actual_wallet_signatures=0,exchange_submissions=0,protection_verified=False,
    actual_fill_verified=False,actual_trading_authorized=False)
try:
    s.start();r['signer']=s.verify_signer()
    context=s.provider.load(OrderRequest('par:BTC','BUY','.0002','1',tif='Ioc'))
    now=s.client.clock_ms();spec=context.spec;q=context.quote
    floor=spec.normalize_price(q.bid*decimal('.98505'),'SELL')
    r.update(status='READ_ONLY_ACCOUNT_OBSERVED',completed_ms=now,account_ms=context.account_ms,
        team_wallet=s.team,api_wallet=s.api,metadata=asdict(spec),quote=asdict(q),book=asdict(s.provider.last_book),
        account_readiness=asdict(context.readiness),active_asset=context.active_asset,
        positions=[asdict(p) for p in context.positions.values()],orders=list(context.open_orders),
        reported_fills=[asdict(f) for f in context.fills],account_reconciliation=s.recovery.state.report(),
        account_reconciliation_ready=s.recovery.last_report.ready,
        clock_health=s.clock.report(),
        illustrative_exit_floor=str(floor),
        one_lot_notional_at_illustrative_floor=str(spec.size_step*floor),
        two_lot_notional_at_illustrative_floor=str(2*spec.size_step*floor),
        exact_one_lot_sell_close_scope=observed_scope(spec,'SELL',spec.size_step),
        small_stop_support='UNVERIFIED; no signed stop test or accepted team stop exists in this observation',
        protection_requirement_ordinary_minimum=str(MIN_NOTIONAL),
        price_scope='READ_ONLY_OBSERVATION_NOT_APPROVED_ORDER_OR_STOP_GEOMETRY')
except Exception as exc:
    r.update(status='READ_ONLY_CHECK_FAILED',error_type=type(exc).__name__,error=str(exc))
finally:
    s.close();r['durable_cleanup']=getattr(s,'cleanup',None)
    r['public_http_requests']=calls;r['reconciliation_calls']=s.reconciliation_calls
    r['source_hash_after']=active_source_hash(ROOT)
    source_unchanged(ROOT,source,policy)
    atomic_json(out/'account_report.json',r)
print(json.dumps(dict(status=r['status'],source_stable=r['source_hash']==r['source_hash_after'],
    public_requests=len(calls),error=r.get('error'),exchange_submissions=0,actual_signatures=0)))
raise SystemExit(0 if r['status']=='READ_ONLY_ACCOUNT_OBSERVED' else 1)
