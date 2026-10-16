"""Bounded testnet /info-only inspection of existing public stops; never submit one."""
import argparse, hashlib, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import RequestsInfoTransport, HyperliquidClient
from exchange.paper_operations import atomic_json, active_source_hash
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze
from protection_evidence import assess_open_stop

class Read:
    def __init__(self,path):
        self.transport=RequestsInfoTransport();self.path=path;self.records=[];self.weights=[];self.started=time.monotonic()
    def __call__(self,p):
        schemas={'perpDexs':{'type'},'meta':{'type','dex'},'recentTrades':{'type','coin'},
            'frontendOpenOrders':{'type','user','dex'},'clearinghouseState':{'type','user','dex'},
            'historicalOrders':{'type','user'},'orderStatus':{'type','user','oid'}}
        kind=p.get('type')
        if kind not in schemas or set(p)!=schemas[kind]:raise RuntimeError('READ_ONLY_SCHEMA_REJECTED')
        if 'dex' in p and p['dex']!='par':raise RuntimeError('PAR_REQUIRED')
        if 'coin' in p and p['coin'] not in {'par:BRENT','par:EWJ','par:USDEUR','par:USDJPY'}:raise RuntimeError('BOUNDED_SOURCE_REQUIRED')
        if 'user' in p and not re.fullmatch('0x[0-9a-fA-F]{40}',p['user']):raise RuntimeError('PUBLIC_USER_REQUIRED')
        if len(self.records)>=64 or time.monotonic()-self.started>180:raise RuntimeError('PUBLIC_SEARCH_BOUND')
        now=time.monotonic();self.weights=[w for w in self.weights if w[0]>now-60]
        reserve=120 if kind in {'historicalOrders','recentTrades'} else 20
        if sum(w[1] for w in self.weights)+reserve>1000:raise RuntimeError('PUBLIC_BUDGET_BOUND')
        charge=[now,reserve];self.weights.append(charge)
        r=dict(request=p,started_utc=datetime.now(timezone.utc).isoformat(),reserved_weight=reserve)
        self.records.append(r)
        try:
            v=self.transport(p);r['response']=v
            if kind=='recentTrades' and isinstance(v,list) and len(v)<=2000:charge[1]=20+len(v)//20
            r['charged_weight']=charge[1];return v
        except Exception as exc:r['error']=str(exc);raise
        finally:
            r['finished_utc']=datetime.now(timezone.utc).isoformat();atomic_json(self.path/'raw_info.json',self.records)
    def close(self):self.transport.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-directory',type=Path,required=True);a=p.parse_args()
    a.output_directory.mkdir(exist_ok=False);read=Read(a.output_directory)
    result=dict(source_hash=active_source_hash(ROOT),started_utc=datetime.now(timezone.utc).isoformat(),
        execution_mode='PAPER',allow_live_orders=False,protection_enabled=False,actual_orders=0,actual_signatures=0,
        scope='Existing public-order evidence only; no entry, general strategy scanning or minimum changes',
        limits=dict(max_users=12,max_new_histories=2,max_requests=64,max_seconds=180,max_rolling_weight=1000),
        users=[],histories=[],stop_candidates=[],accepted_stop_readbacks=[],
        protection_capability_validated=False,limitations=['Bounded/truncated histories are not a census',
            'Readback acceptance is not trigger execution or partial-residual proof',
            'Closing evidence does not establish stop support'])
    try:
        result['safety']=require_paper_migration();result['strategy_freeze']=verify_strategy_freeze()
        client=HyperliquidClient(read);client.startup()
        lots={s:client.market(s).size_step for s in client.markets}
        result['runtime_markets']={s:dict(lot=str(lots[s]),asset_id=client.market(s).asset_id) for s in lots}
        old=[]
        for name in ('public_search_verified','protection_search_verified'):
            old+=json.loads((ROOT/'docs/certification_v8_5_2026-10-12'/name/'observations.json').read_text())['public_users']
        old=list(dict.fromkeys(u.lower() for u in old));new=[]
        for coin in ('par:BRENT','par:EWJ','par:USDEUR','par:USDJPY'):
            trades=client.post_info('recentTrades',coin=coin)
            for t in sorted(trades,key=lambda t:t['time'],reverse=True):
                for u in t.get('users',[]):
                    if u.lower() not in old+new:new.append(u.lower())
        users=(new[:4]+old)[:12];result['users']=users;result['new_counterparties']=new[:4]
        for user in users:
            state=client.post_info('clearinghouseState',user=user)
            orders=client.post_info('frontendOpenOrders',user=user)
            for row in orders:
                coin=row.get('coin')
                if coin not in lots or row.get('isTrigger') is not True:continue
                result['stop_candidates'].append(dict(user=user,order=row,source='CURRENT_OPEN_ORDERS'))
                if row.get('orderType') not in {'Stop Limit','Stop Market'}:continue
                detail=client.post_info('orderStatus',user=user,oid=row['oid'])
                after=client.post_info('clearinghouseState',user=user)
                result['accepted_stop_readbacks'].append(dict(user=user,detail=detail,positions_before=state,
                    positions_after=after,assessment=assess_open_stop(detail,row,state,after,symbol=coin,lot=lots[coin])))
        for user in new[:2]:
            rows=read(dict(type='historicalOrders',user=user))
            par=[h for h in rows if h.get('order',{}).get('coin') in lots]
            triggers=[h for h in par if h['order'].get('isTrigger') is True]
            result['histories'].append(dict(user=user,total_rows=len(rows),par_rows=len(par),
                unique_par_orders=len({h['order']['oid'] for h in par}),trigger_rows=len(triggers),
                possible_truncation=len(rows)>=2000))
            for h in triggers:
                result['stop_candidates'].append(dict(user=user,historical=h,source='HISTORICAL_ORDERS',
                    capability_validated=False,reason='INDEPENDENT_ORIGINAL_ORDER_AND_POSITION_COVERAGE_REQUIRED'))
        result['status']='BOUNDED_READ_COMPLETE'
    except Exception as exc:result.update(status='BOUNDED_READ_INCOMPLETE',error=str(exc))
    finally:read.close()
    result.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT),
        requests=len(read.records),charged_weight=sum(r.get('charged_weight',r['reserved_weight']) for r in read.records),
        one_lot_stop_acceptance_count=sum(v['assessment']['one_lot_stop_acceptance'] for v in result['accepted_stop_readbacks']))
    result['source_stable']=result['source_hash']==result['source_hash_after']
    result['classifier_sha256']=hashlib.sha256((Path(__file__).parent/'protection_evidence.py').read_bytes()).hexdigest()
    atomic_json(a.output_directory/'observations.json',result)
    print(json.dumps({k:result.get(k) for k in ('status','error','requests','charged_weight','histories',
        'one_lot_stop_acceptance_count','protection_capability_validated','source_stable')},indent=2))
    return 0 if result['status']=='BOUNDED_READ_COMPLETE' and result['source_stable'] else 1
if __name__=='__main__':raise SystemExit(main())
