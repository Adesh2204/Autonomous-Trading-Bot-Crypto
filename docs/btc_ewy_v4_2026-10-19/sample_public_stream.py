"""Bounded actual public WebSocket evidence. No account or signing capability."""
from pathlib import Path
import threading,time,json,sys
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent/'stream_sample';O.mkdir(exist_ok=False)
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.public_quant_operator import SerializedPublicClient,SerializedPublicMarket,ReadOnlyReceipts
from exchange.hyperliquid_client import RequestsInfoTransport
from exchange.hyperliquid_market_data import ParMarketDataEngine
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from exchange.testnet_certification import TEAM
from exchange.entry_scope import PAS_ENTRY_MARKETS
j=ExecutionJournal(O/'public.sqlite',session_id='v4-public-stream-sample',team_address=TEAM);rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
c=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),O/'info_receipts.jsonl'),rate_limits=rates,venue='pas');stop=threading.Event();c.read_cancel_event=stop
result=dict(source_hash=active_source_hash(R),started_ms=c.clock_ms(),per_market={s:{} for s in sorted(PAS_ENTRY_MARKETS)},signing_authority='NONE',exchange_writes=0,signatures_created=0)
raw=(O/'public_ws.jsonl').open('x')
class Sample(ParMarketDataEngine):
 def ingest(self,message,**kwargs):
  value=json.loads(message) if isinstance(message,str) else message
  answer=super().ingest(message,**kwargs)
  received=c.clock_ms();channel=value.get('channel');data=value.get('data',{})
  raw.write(json.dumps(dict(received_ms=received,message=value),default=str)+'\n');raw.flush()
  rows=data if isinstance(data,list) else [data]
  for row in rows:
   if not isinstance(row,dict):continue
   symbol=row.get('coin',row.get('s'))
   if symbol in PAS_ENTRY_MARKETS:
    result['per_market'][symbol][channel]=dict(received_ms=received,
     exchange_timestamp_ms=row.get('time'),candle_open_ms=row.get('t') if channel=='candle' else None,
     exchange_timestamp_status='REPORTED' if type(row.get('time')) is int else 'UNKNOWN_NOT_REPLACED_BY_LOCAL_RECEIVE_TIME')
  return answer
engine=thread=None;timer=threading.Timer(90,stop.set);timer.start()
try:
 c.startup();engine=Sample(SerializedPublicMarket(c),symbols=sorted(PAS_ENTRY_MARKETS),include_trades=True)
 def run():
  try:engine.run(stop,max_reconnects=2)
  except Exception as exc:result['stream_error']=str(exc)
 thread=threading.Thread(target=run,daemon=True);thread.start();stop.wait(20)
 result.update(transport=engine.transport_health.report(),observed_ms=c.clock_ms(),status='PUBLIC_STREAM_SAMPLE_COMPLETE')
 for s in PAS_ENTRY_MARKETS:
  result['per_market'][s].setdefault('candle',None)
  result['per_market'][s]['observations']=engine.get_observations(s)
except Exception as exc:result.update(status='PUBLIC_STREAM_SAMPLE_INCOMPLETE',error=str(exc))
finally:
 stop.set()
 if engine:engine._recovery_cancel.set()
 if thread:thread.join(15)
 result.update(receiver_stopped=thread is None or not thread.is_alive(),source_hash_after=active_source_hash(R),journal_integrity=j.db.execute('pragma integrity_check').fetchone()[0]);timer.cancel();raw.close();c.close();j.close();atomic_json(O/'stream_sample.json',result)
print(json.dumps(result,indent=2,default=str))
