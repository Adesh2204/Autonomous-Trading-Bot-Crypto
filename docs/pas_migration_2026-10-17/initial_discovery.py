from pathlib import Path
import json,sys,time,threading
P=Path(__file__).resolve().parent;ROOT=P.parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import RequestsInfoTransport
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.testnet_certification import TEAM
transport=RequestsInfoTransport();journal=ExecutionJournal(P/'initial_public.sqlite',session_id='public:pas-discovery',team_address=TEAM);rates=HyperliquidRateLimitManager(journal);rates.read_budget_wait_seconds=65
stop=threading.Event();timer=threading.Timer(150,stop.set);timer.start();result={}
queries=[dict(type='meta',dex='pas'),dict(type='metaAndAssetCtxs',dex='pas'),dict(type='spotMeta'),dict(type='perpDexLimits',dex='pas'),dict(type='perpDexStatus',dex='pas'),dict(type='exchangeStatus'),dict(type='userAbstraction',user=TEAM),dict(type='spotClearinghouseState',user=TEAM),dict(type='clearinghouseState',user=TEAM,dex='pas'),dict(type='openOrders',user=TEAM,dex='pas'),dict(type='userFees',user=TEAM),dict(type='extraAgents',user=TEAM),dict(type='userRateLimit',user=TEAM)]
try:
 for q in queries:
  record=dict(request=q,sent_ms=time.time_ns()//1000000)
  try:
   record['response']=rates.read(q['type'],lambda:transport(q,cancel_event=stop),request_key=json.dumps(q,sort_keys=True),cancel_event=stop)
   result[q['type']]=record['response']
  except Exception as exc:record.update(error=str(exc),status_code=getattr(exc,'status_code',None));result[q['type']]=record
  record['received_ms']=time.time_ns()//1000000
  with (P/'initial_info_receipts.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
  (P/'initial_discovery.json').write_text(json.dumps(result,indent=2)+'\n')
finally:timer.cancel();transport.close();journal.close()
meta=result.get('meta',{});token=meta.get('collateralToken');tokens=result.get('spotMeta',{}).get('tokens',[])
print(json.dumps(dict(markets=meta.get('universe'),collateral=[x for x in tokens if x.get('index')==token],mode=result.get('userAbstraction'),account=result.get('clearinghouseState'),status=result.get('perpDexStatus'),exchange_status=result.get('exchangeStatus'),limits=result.get('perpDexLimits')),indent=2))
