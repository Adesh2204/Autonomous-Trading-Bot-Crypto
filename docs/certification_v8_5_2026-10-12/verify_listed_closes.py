"""Independent bounded re-read of discovered original OIDs and fill windows."""
import argparse, json, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import atomic_json,active_source_hash
from exchange.hyperliquid_client import HyperliquidClient
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration
from read_public_evidence import BoundedRead
from public_evidence import classify

p=argparse.ArgumentParser();p.add_argument('--output-directory',type=Path,required=True);a=p.parse_args()
a.output_directory.mkdir(exist_ok=False)
r=dict(started_utc=datetime.now(timezone.utc).isoformat(),source_hash=active_source_hash(ROOT),
       network='testnet',dex='par',exchange_submissions=0,signature_created=False,records=[])
transport=BoundedRead(a.output_directory)
try:
    r['safety']=require_paper_migration();r['freeze']=verify_strategy_freeze()
    client=HyperliquidClient(transport);client.startup()
    listed=[]
    for name in ('public_search_verified','protection_search_verified'):
        observations=json.loads((Path(__file__).resolve().parent/name/'observations.json').read_text())
        listed += [v for v in observations['verified'] if v['classification']['one_lot_full_close']]
    if len(listed)>8:raise RuntimeError('BOUNDED_CANDIDATE_COUNT_EXCEEDED')
    for observed in listed:
        original=observed['order_status']['order']['order'];user=observed['user'];coin=original['coin']
        timestamp=observed['order_status']['order']['statusTimestamp']
        detail=client.post_info('orderStatus',user=user,oid=original['oid'])
        fills=client.post_info('userFillsByTime',user=user,startTime=timestamp-1000,endTime=timestamp+1000,aggregateByTime=False)
        verification=classify(detail,fills,coin=coin,lot=client.market(coin).size_step)
        r['records'].append(dict(user=user,order_status=detail,raw_window_fills=fills,
            original_identity_unchanged=detail['order']['order']==original,classification=verification))
    r['all_six_historical_one_lot_closes_verified']=len(r['records'])==6 and all(
        v['original_identity_unchanged'] and v['classification']['one_lot_full_close'] for v in r['records'])
    r['status']='INDEPENDENT_READBACK_VERIFIED' if r['all_six_historical_one_lot_closes_verified'] else 'READBACK_NOT_VERIFIED'
except Exception as exc:r.update(status='READBACK_FAILED',error=str(exc))
finally:transport.close()
r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT),
         requests=len(transport.records))
atomic_json(a.output_directory/'one_lot_readback.json',r)
print(json.dumps({k:r.get(k) for k in ('status','error','all_six_historical_one_lot_closes_verified','requests')},indent=2))
raise SystemExit(0 if r['status']=='INDEPENDENT_READBACK_VERIFIED' else 1)
