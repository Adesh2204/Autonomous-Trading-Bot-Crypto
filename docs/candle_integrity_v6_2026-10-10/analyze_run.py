"""Read-only same-window candle audit, using recorded public inputs only."""
from collections import Counter,defaultdict
from decimal import Decimal
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.hyperliquid_market_data import parse_candle
from exchange.base_exchange import Candle,decimal

def metrics(rows,symbol,start,end,now,raw=False):
    normalized=[];invalid=[]
    for row in rows:
        try:
            c=(parse_candle(row,symbol,'1m') if raw else Candle(**{k:(decimal(v) if k in
                {'open','high','low','close','volume'} else v) for k,v in row.items() if k in Candle.__dataclass_fields__}))
            if start<=c.timestamp_ms<=end and c.timestamp_ms+60000<=now:normalized.append(c)
        except Exception as exc:invalid.append(type(exc).__name__+':'+str(exc))
    times=[c.timestamp_ms for c in normalized];unique=sorted(set(times));expected=list(range(start,end+1,60000))
    missing=[t for t in expected if t not in set(unique)];tail=0
    for t in reversed(expected):
        if t not in set(unique):break
        tail+=1
    values=defaultdict(set)
    for c in normalized:values[c.timestamp_ms].add(tuple(str(getattr(c,k)) for k in ('open','high','low','close','volume')))
    return dict(count=len(normalized),unique_count=len(unique),first_ms=min(unique,default=None),last_ms=max(unique,default=None),
        missing_timestamps_ms=missing,duplicates=len(times)-len(unique),conflicting_duplicates=sum(len(v)>1 for v in values.values()),
        invalid_ohlcv_count=len(invalid),invalid_reasons=invalid,contiguous_completed_tail=tail,
        close_age_ms=now-max(unique)-60000 if unique else None,interval_ms=60000)

def analyze(receipt_path):
    receipt=json.loads(Path(receipt_path).read_text());segment=Path(receipt['final_health']['segment'])
    traces=[json.loads(l) for l in (segment/'results/opportunity_traces.jsonl').open()]
    last_trace={t['symbol']:t for t in traces}
    def target(symbol):
        t=last_trace[symbol];end=t['data_evidence']['expected_last_completed_candle_ms'];start=min(end-299*60000,end//86400000*86400000-14*60000)
        return start,end+59999,t['decision_ms']
    wire=defaultdict(list);latest_raw={};latest_normalized={};latest_cache={};rejects=Counter();request_audits=defaultdict(list)
    path=segment/'public_candle_audit.jsonl'
    for line in path.open():
        r=json.loads(line);stage=r['stage']
        if stage=='RAW_REST':
            q=r['request']['req'];symbol=q['coin'];start,end,decision=target(symbol)
            request_audits[symbol].append(dict(request=q,received_ms=r['received_ms'],
                metrics=metrics(r['response'],symbol,q['startTime'],q['endTime'],r['received_ms'],True)))
            if q['startTime']==start and q['endTime']==end and r['received_ms']<=decision:latest_raw[symbol]=r
        if stage=='NORMALIZED_REST':
            start,end,decision=target(r['symbol'])
            if r['start_ms']==start and r['end_ms']==end and r['observed_ms']<=decision:latest_normalized[r['symbol']]=r
        if stage=='CACHE' and r['observed_ms']<=target(r['symbol'])[2]:latest_cache[r['symbol']]=r
        if stage=='CANDLE_REJECTED':rejects[(r['symbol'],r['reason'])]+=1
        if stage=='RAW_WS':
            message=r['message'];message=json.loads(message) if isinstance(message,str) else message
            data=message['data']
            for row in data if isinstance(data,list) else [data]:
                if isinstance(row,dict) and row.get('s') in last_trace and r['received_ms']<=target(row['s'])[2]:wire[row['s']].append(row)
    scanner={}
    for l in (segment/'candles.jsonl').open():
        r=json.loads(l);scanner[r['symbol']]=r
    result={}
    for symbol,t in last_trace.items():
        end=t['data_evidence']['expected_last_completed_candle_ms'];start=end-299*60000;now=t['decision_ms']
        raw=latest_raw.get(symbol);norm=latest_normalized.get(symbol);cache=latest_cache.get(symbol)
        # Use the exact last scanner request window and only facts observed by
        # that decision. A short tail repair is never a full-window response.
        stages={}
        for name,rows,israw in [('A_REST',raw['response'] if raw else [],True),('B_WS',wire[symbol],True),
                ('C_NORMALIZED',norm['candles'] if norm else [],False),('C_CACHE',cache['candles'] if cache else [],False),
                ('D_SCANNER',scanner.get(symbol,{}).get('candles',[]),False)]:
            stages[name]=metrics(rows,symbol,start,end,now,israw)
        absent=stages['D_SCANNER']['missing_timestamps_ms'];trace=[]
        raw_times={r['t'] for r in raw['response']} if raw else set()
        ws_times={r['t'] for r in wire[symbol] if 't' in r}
        for missing in absent:
            trace.append(dict(timestamp_ms=missing,raw_rest_returned=missing in raw_times,raw_ws_returned=(True if missing in ws_times else False if missing>=int(receipt['started_unix']*1000)//60000*60000 else 'UNKNOWN_NOT_OBSERVED'),
                normalized_received=missing not in stages['C_NORMALIZED']['missing_timestamps_ms'],
                cache_retained=missing not in stages['C_CACHE']['missing_timestamps_ms'],scanner_received=False,
                classification='EXCHANGE_DATA_UNAVAILABLE' if raw and missing not in raw_times and missing not in ws_times else 'CAUSE_UNDETERMINED',
                scope='This bounded run and recorded request only. Absence does not prove permanent venue unavailability.',
                responsible_function='HyperliquidMarketData.get_candles -> MarketRegimeScanner.scan',
                rejection=t['raw_reasons'],fix_possible='NO_FABRICATION_PERMITTED' if raw and missing not in raw_times else 'UNDETERMINED'))
        result[symbol]=dict(window_start_ms=start,window_end_ms=end+59999,reference_decision_ms=now,stages=stages,
            raw_request=raw['request'] if raw else None,raw_received_ms=raw['received_ms'] if raw else None,
            cache_observed_ms=cache['observed_ms'] if cache else None,
            comparison_limit='All sources filtered to the same 300-bar interval and facts received by this scanner decision. A_REST/C_NORMALIZED match the exact full UTC scanner request; C_CACHE is its bounded stream cache. WS only covers the run observation period; older WS bars are NOT_OBSERVED. Full-history validation may require more than this comparison window.',
            full_strategy_input_count=len(scanner.get(symbol,{}).get('candles',[])),
            missing_trace=trace,final_health=receipt['final_health']['market_health'][symbol])
    output=Path(receipt_path).parent/'candle_stage_audit.json'
    output.write_text(json.dumps(dict(markets=result,raw_audit_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        all_rest_request_integrity=request_audits,
        rejection_counts={str(k):v for k,v in rejects.items()},numeric_errors=[t for t in traces if any('INVALID_DECIMAL' in r or 'SCANNER_NUMERIC_INVALID' in r for r in t['raw_reasons'])]),indent=2))
    print(json.dumps({s:{stage:v['count'] for stage,v in a['stages'].items()} for s,a in result.items()}))
    return output

if __name__=='__main__':analyze(sys.argv[1])
