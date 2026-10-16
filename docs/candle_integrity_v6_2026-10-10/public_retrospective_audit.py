"""LIVE_PUBLIC_READ_ONLY: same historical windows, queried now, not old wire proof."""
from pathlib import Path
import hashlib,json,sys,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
OUT=Path(__file__).resolve().parent
audit=json.loads((OUT/'historical_candle_audit.json').read_text())
wire=RequestsInfoTransport();requests=[]
def transport(payload):
    sent=time.time_ns()//1000000
    response=wire(payload)
    received=time.time_ns()//1000000
    requests.append(dict(request=payload,response=response,sent_ms=sent,received_ms=received))
    return response
journal=ExecutionJournal(OUT/'retrospective_public_budget.sqlite',session_id='v6-read-only',team_address='0x'+'0'*40)
rates=HyperliquidRateLimitManager(journal)
client=HyperliquidClient(transport,rate_limits=rates);client.startup();market=HyperliquidMarketData(client)
result={}
try:
    for symbol,a in audit.items():
        start,end=a['requested_start_ms'],a['requested_end_ms']
        try:
            candles=market.get_candles(symbol,start,end)
            response=requests[-1]['response'];raw={x['t'] for x in response}
            normalized={c.timestamp_ms for c in candles}
            result[symbol]=dict(raw_count=len(response),normalized_count=len(candles),
                request_start_ms=start,request_end_ms=end,queried_now_ms=client.last_received_ms,
                raw_timestamp_ms=sorted(raw),normalized_timestamp_ms=sorted(normalized),
                missing_in_response=[t for t in range(start,end+1,60000) if t not in raw],
                original_missing_now_present=[t for t in a['missing_timestamps_ms'] if t in raw],
                note='Current retrospective response cannot prove what the original run received.')
        except Exception as exc:result[symbol]=dict(error=type(exc).__name__+':'+str(exc))
        time.sleep(1)
finally:
    (OUT/'retrospective_raw_rest.json').write_text(json.dumps(requests))
    (OUT/'retrospective_audit.json').write_text(json.dumps(result,indent=2))
    wire.close();journal.close()
print(json.dumps({s:{k:v for k,v in r.items() if k not in ('raw_timestamp_ms','normalized_timestamp_ms','missing_in_response','original_missing_now_present')} for s,r in result.items()},indent=2))
