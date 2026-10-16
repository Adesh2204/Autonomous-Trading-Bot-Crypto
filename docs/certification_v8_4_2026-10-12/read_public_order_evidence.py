"""Bounded /info-only historical evidence inspection. Never an execution route.

Inspect only par:ETH trades, then at most four already public counterparties.
Small fill notional is NOT evidence of a small submitted order. Raw original
order fields and actual reducing fills must be reviewed separately. This file
is outside production source and does not expand its query allowlist.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal as D
import json, re, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient, RequestsInfoTransport
from exchange.paper_operations import active_source_hash, atomic_json
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


class BoundedPublicInfo:
    """Reserve worst-case documented response weight before each HTTP read."""
    def __init__(self, directory):
        self.transport=RequestsInfoTransport();self.directory=directory
        self.weights=[];self.records=[]

    def __call__(self, payload):
        kind=payload.get('type');keys=set(payload)
        schemas={'perpDexs':{'type'},'meta':{'type','dex'},
                 'recentTrades':{'type','coin'},'historicalOrders':{'type','user'},
                 'userFills':{'type','user'},'orderStatus':{'type','user','oid'}}
        if kind not in schemas or keys!=schemas[kind]:raise RuntimeError('READ_SCHEMA_REJECTED')
        if kind=='meta' and payload['dex']!='par':raise RuntimeError('PAR_REQUIRED')
        if kind=='recentTrades' and payload['coin']!='par:ETH':raise RuntimeError('FOCUSED_COIN_REQUIRED')
        if 'user' in payload and not re.fullmatch(r'0x[0-9a-fA-F]{40}',payload['user']):
            raise RuntimeError('PUBLIC_ADDRESS_REQUIRED')
        now=time.monotonic();self.weights=[x for x in self.weights if x[0]>now-60]
        # These history endpoints return at most 2000 records: 20 + 2000/20.
        weight=120 if kind in {'historicalOrders','userFills','recentTrades'} else 2 if kind=='orderStatus' else 20
        if sum(x[1] for x in self.weights)+weight>1000:raise RuntimeError('BOUNDED_PUBLIC_READ_BUDGET')
        self.weights.append((now,weight))
        row={'request':payload,'started_utc':datetime.now(timezone.utc).isoformat(),
             'reserved_worst_case_weight':weight}
        self.records.append(row)
        try:row['response']=self.transport(payload);return row['response']
        except Exception as exc:row['error']=str(exc);raise
        finally:
            row['finished_utc']=datetime.now(timezone.utc).isoformat()
            atomic_json(self.directory/'raw_info.json',self.records)

    def close(self):self.transport.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-directory',type=Path,required=True);args=p.parse_args()
    directory=args.output_directory;directory.mkdir(exist_ok=False)
    r={'source_hash':active_source_hash(ROOT),'started_utc':datetime.now(timezone.utc).isoformat(),
       'network':'testnet','dex':'par','focused_trade_coin':'par:ETH','general_market_scan':False,
       'exchange_submissions':0,'signature_created':False,'execution_mode':'PAPER',
       'allow_live_orders':False,'candidates':[],
       'limitations':['Bounded observational sample, not a general acceptance guarantee',
          'Historical orders/fills may be truncated; grouping and submission-position truth can be missing',
          'Tiny matched fills of larger original orders do not establish a minimum exception',
          'This report creates no permit, proposal, signed order or readiness flag']}
    transport=BoundedPublicInfo(directory)
    try:
        r['safety']=require_paper_migration();r['freeze']=verify_strategy_freeze()
        client=HyperliquidClient(transport);client.startup()
        trades=client.post_info('recentTrades',coin='par:ETH')
        if not isinstance(trades,list):raise RuntimeError('INVALID_PUBLIC_TRADES')
        r['recent_trade_count']=len(trades)
        users=[]
        for trade in sorted(trades,key=lambda x:x.get('time',0),reverse=True):
            for user in trade.get('users',[]):
                if isinstance(user,str) and user.lower() not in [u.lower() for u in users]:users.append(user)
            if len(users)>=4:break
        r['public_counterparties_sampled']=users[:4]
        for user in users[:4]:
            orders=transport({'type':'historicalOrders','user':user})
            fills=client.post_info('userFills',user=user)
            if not isinstance(orders,list) or not isinstance(fills,list):raise RuntimeError('INVALID_PUBLIC_HISTORY')
            for historical in orders:
                order=historical.get('order',{})
                if order.get('coin')!='par:ETH' or order.get('reduceOnly') is not True:continue
                try:notional=D(order['origSz'])*D(order['limitPx'])
                except (KeyError,ValueError,ArithmeticError):continue
                if notional<=0 or notional>=10:continue
                matched=[f for f in fills if f.get('coin')=='par:ETH' and f.get('oid')==order.get('oid')]
                r['candidates'].append({'public_user':user,'original_limit_notional':str(notional),
                    'historical_order':historical,'matching_fills':matched,
                    'proof_classification':'REQUIRES_ORIGINAL_POSITION_AND_PROTECTION_REVIEW'})
        # Re-read candidate identity, capped at eight; an open/current order is
        # not automatically a full-position stop or an actual completed close.
        for candidate in r['candidates'][:8]:
            candidate['order_status_readback']=client.post_info('orderStatus',
                user=candidate['public_user'],oid=candidate['historical_order']['order']['oid'])
        r['status']='READ_ONLY_COMPLETE'
    except Exception as exc:r.update(status='READ_ONLY_INCOMPLETE',error=str(exc))
    finally:transport.close()
    r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT),
             requests=len(transport.records),reserved_worst_case_weight=sum(x['reserved_worst_case_weight'] for x in transport.records))
    atomic_json(directory/'observations.json',r)
    print(json.dumps({k:r.get(k) for k in ('status','error','recent_trade_count','requests','reserved_worst_case_weight')},indent=2))
    print(json.dumps({'subminimum_original_reduce_only_candidates':len(r['candidates']),
                      'exchange_submissions':0,'signature_created':False}))
    return 0 if r['status']=='READ_ONLY_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
