"""Re-read two existing public HYPE closes. No signer and no /exchange."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal as D
import json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.paper_operations import atomic_json, active_source_hash
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze

USER='0x6c0eb3c0b539d637c1d507e6a2a68bdfd2fb3b3c'
RECORDS=((61997055149,1791301091928),(61745948135,1791036693873))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-directory',type=Path,required=True);a=p.parse_args()
    a.output_directory.mkdir(exist_ok=False)
    r={'started_utc':datetime.now(timezone.utc).isoformat(),'source_hash':active_source_hash(ROOT),
       'network':'testnet','dex':'par','coin':'par:HYPE','public_user':USER,
       'general_market_scan':False,'exchange_submissions':0,'signature_created':False,
       'records':[],'protection_exception_established':False,
       'scope':'Historical accepted full closes, not present-day blanket acceptance or protection certification'}
    client=HyperliquidClient()
    try:
        r['safety']=require_paper_migration();r['freeze']=verify_strategy_freeze();client.startup()
        for oid,timestamp in RECORDS:
            detail=client.post_info('orderStatus',user=USER,oid=oid)
            raw=client.post_info('userFillsByTime',user=USER,startTime=timestamp-1000,
                                endTime=timestamp+1000,aggregateByTime=False)
            fills=[f for f in raw if f.get('oid')==oid and f.get('coin')=='par:HYPE']
            order=detail.get('order',{}).get('order',{})
            orig=D(order['origSz']);limit=D(order['limitPx'])
            signed_start=D(fills[0]['startPosition']) if len(fills)==1 else None
            exact=(detail.get('status')=='order' and detail['order']['status']=='filled'
                and order.get('coin')=='par:HYPE' and order.get('reduceOnly') is True
                and order.get('isTrigger') is False and order.get('tif')=='Ioc'
                and 0<orig*limit<10 and len(fills)==1 and abs(signed_start)==orig
                and D(fills[0]['sz'])==orig and fills[0]['side']==order['side']
                and fills[0]['feeToken']=='USDPR' and fills[0]['time']==timestamp
                and ((signed_start>0 and order['side']=='A' and fills[0]['dir']=='Close Long')
                    or (signed_start<0 and order['side']=='B' and fills[0]['dir']=='Close Short')))
            r['records'].append({'oid':oid,'original_limit_notional':str(orig*limit),
                'order_status':detail,'raw_window_fills':raw,'matching_fills':fills,
                'verified_exact_full_close':exact,'filled_notional':str(D(fills[0]['sz'])*D(fills[0]['px'])) if fills else None,
                'post_fill_quantity':str(signed_start+(orig if order.get('side')=='B' else -orig)) if signed_start is not None else None})
        r['both_historical_full_closes_verified']=all(x['verified_exact_full_close'] for x in r['records']) and len(r['records'])==2
        r['status']='READ_ONLY_VERIFIED' if r['both_historical_full_closes_verified'] else 'EVIDENCE_NOT_VERIFIED'
    except Exception as exc:r.update(status='READ_ONLY_FAILED',error=str(exc))
    finally:client.close()
    r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT))
    atomic_json(a.output_directory/'full_close_evidence.json',r)
    print(json.dumps({k:r.get(k) for k in ('status','error','both_historical_full_closes_verified','exchange_submissions')},indent=2))
    return 0 if r['status']=='READ_ONLY_VERIFIED' else 1


if __name__=='__main__':raise SystemExit(main())
