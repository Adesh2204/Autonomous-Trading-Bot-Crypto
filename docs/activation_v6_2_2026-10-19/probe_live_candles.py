"""Bounded independent public wire comparison. No signer or /exchange transport."""
from pathlib import Path
import json,ssl,sys,threading,time,sqlite3
import requests,websocket
R=Path(__file__).resolve().parents[2];O=Path(__file__).with_name('independent_candle_probe_final');O.mkdir(exist_ok=False)
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
from exchange.hyperliquid_client import RequestsInfoTransport,TESTNET_WS_URL
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.hyperliquid_market_data import parse_candle
j=ExecutionJournal(O/'public.sqlite',session_id='public:v6.2-candle-probe',team_address='0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C');rates=HyperliquidRateLimitManager(j)
rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
c=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),O/'info_receipts.jsonl'),rate_limits=rates,venue='pas')
stop=threading.Event();timer=threading.Timer(240,stop.set);timer.start();c.read_cancel_event=stop
result=dict(mode='ACTUAL_PUBLIC_INFO_AND_RAW_WS',source_hash=active_source_hash(R),signatures_created=0,exchange_writes=0,rounds=[],sockets=[])
def local():
 p=R/'runtime/pas-btc-ewy-v6-public/history.sqlite'
 with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
  return {s:dict(count=n,latest_open_ms=t) for s,n,t in db.execute('select symbol,count(*),max(t) from bars group by symbol')}
def rest():
 now=c.clock_ms();end=now//60000*60000-1;rows={}
 for s in sorted(c.markets):
  raw=c.post_info('candleSnapshot',req=dict(coin=s,interval='1m',startTime=end+1-30*60000,endTime=end))
  parsed=[parse_candle(x,s,'1m') for x in raw]
  rows[s]=dict(request_end_ms=end,received_ms=c.clock_ms(),count=len(raw),timestamps=[b.timestamp_ms for b in parsed],latest_open_ms=max((b.timestamp_ms for b in parsed),default=None))
 result['rounds'].append(dict(observed_ms=c.clock_ms(),rest=rows,local=local()))
try:
 c.startup();rest()
 with (O/'raw_ws.jsonl').open('x') as log:
  for generation in (1,2):
   ws=websocket.create_connection(TESTNET_WS_URL,timeout=1,sslopt=dict(ca_certs=requests.certs.where(),cert_reqs=ssl.CERT_REQUIRED,check_hostname=True))
   record=dict(generation=generation,started_ms=c.clock_ms(),acks=[],events={},pongs=0);result['sockets'].append(record)
   try:
    for s in sorted(c.markets):ws.send(json.dumps(dict(method='subscribe',subscription=dict(type='candle',coin=s,interval='1m'))))
    start=time.monotonic();ping=start
    while not stop.is_set() and time.monotonic()-start<62:
     if time.monotonic()-ping>=25:ws.send(json.dumps(dict(method='ping')));ping=time.monotonic()
     try:raw=ws.recv()
     except websocket.WebSocketTimeoutException:continue
     if not raw:raise RuntimeError('RAW_SOCKET_CLOSED')
     m=json.loads(raw);now=c.clock_ms();log.write(json.dumps(dict(received_ms=now,generation=generation,message=m))+'\n');log.flush()
     if m.get('channel')=='subscriptionResponse':record['acks'].append(m['data'])
     if m.get('channel')=='pong':record['pongs']+=1
     if m.get('channel')=='candle':
      for row in m['data'] if isinstance(m['data'],list) else [m['data']]:
       s=row.get('s');parse_candle(row,s,'1m');r=record['events'].setdefault(s,dict(count=0,latest_open_ms=None));r['count']+=1;r['latest_open_ms']=max(row['t'],r['latest_open_ms'] or 0)
   finally:record['closed_ms']=c.clock_ms();ws.close()
   rest()
 result['status']='COMPLETE'
except Exception as exc:result.update(status='INCOMPLETE',error=type(exc).__name__+':'+str(exc))
finally:
 result['finished_ms']=c.clock_ms();atomic_json(O/'probe.json',result);timer.cancel();c.close();j.close()
print(json.dumps(dict(status=result['status'],rounds=len(result['rounds']),sockets=result['sockets']),indent=2))
