"""Bounded public REST/WS evidence. No wallet, signer, fabricated bars or orders."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine,parse_candle
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


def candle_evidence(rows,symbol,now_ms):
    expected=(now_ms//60000-1)*60000
    raw=sorted((r for r in rows if r['t']+60000<=now_ms),key=lambda r:r['t'])
    parsed=sorted((parse_candle(r,symbol,'1m') for r in rows if r['t']+60000<=now_ms),key=lambda r:r.timestamp_ms)
    latest=raw[-1] if raw else None
    starts=[r['t'] for r in raw]
    return dict(expected_completed_start_ms=expected,raw_completed_count=len(raw),
        raw_latest=latest,parsed_latest=asdict(parsed[-1]) if parsed else None,
        adapter_matches_raw=([c.timestamp_ms for c in parsed]==starts),
        missing_minutes_between_returned_bars=sum(max(0,(b-a)//60000-1) for a,b in zip(starts,starts[1:])),
        completed_age_ms=now_ms-(latest['t']+60000) if latest else None,
        completed_fresh=bool(latest and 0<=now_ms-(latest['t']+60000)<=120000))


class EvidenceEngine(ParMarketDataEngine):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.channels={}
        self.ws_candles={}
    def ingest(self,message):
        decoded=json.loads(message) if isinstance(message,str) else message
        super().ingest(decoded)
        channel=decoded.get('channel')
        self.channels[channel]=self.channels.get(channel,0)+1
        if channel=='candle':
            data=decoded['data']
            for row in data if isinstance(data,list) else [data]:
                self.ws_candles[row['s']]=row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stream-seconds',type=float,default=45)
    args=parser.parse_args()
    if not 0<=args.stream_seconds<=120:parser.error('stream-seconds must be 0–120')
    require_paper_migration()
    verify_strategy_freeze()
    if args.output.exists():parser.error('output must be new')
    client=HyperliquidClient()
    report=dict(execution_mode='PAPER',network='testnet',dex='par',read_only=True,
        exchange_orders_submitted=0,provenance='LIVE_PUBLIC_PAR_FRESHNESS_OBSERVATION',markets={})
    try:
        client.startup()
        market=HyperliquidMarketData(client)
        report['dex_index']=client.dex_index
        report['contexts']=market.get_asset_contexts()
        for symbol in sorted(client.markets):
            now=client.clock_ms()
            end=now//60000*60000-1
            rows=client.post_info('candleSnapshot',req=dict(coin=symbol,interval='1m',startTime=end+1-300*60000,endTime=end))
            item=candle_evidence(rows,symbol,now)
            try:
                book=market.get_orderbook(symbol)
                item['book']=asdict(book)
                item['book_age_ms']=client.clock_ms()-book.timestamp_ms
            except ExchangeError as exc:item['book_error']=str(exc)
            trades=client.post_info('recentTrades',coin=symbol)
            last=max(trades,key=lambda r:r['time']) if trades else None
            item['latest_public_trade']=last
            item['latest_public_trade_age_ms']=client.clock_ms()-last['time'] if last else None
            report['markets'][symbol]=item
        if args.stream_seconds:
            stop=threading.Event()
            engine=EvidenceEngine(market,history_bars=300,include_trades=True)
            timer=threading.Timer(args.stream_seconds,stop.set)
            timer.start()
            try:engine.run(stop)
            finally:stop.set();timer.cancel()
            now=client.clock_ms()
            report['websocket']=dict(duration_seconds=args.stream_seconds,messages=engine.messages,
                channels=engine.channels,last_error=engine.last_error,reconnections=engine.reconnections)
            for symbol,item in report['markets'].items():
                bars=engine.get_completed_candles(symbol)
                item['stream_cache_latest_completed']=asdict(bars[-1]) if bars else None
                item['websocket_candle_message']=engine.ws_candles.get(symbol)
                item['stream_last_public_trade']=engine.last_trades.get(symbol)
                item['stream_observations']=engine.get_observations(symbol)
                rest=item['raw_latest']
                ws=item['websocket_candle_message']
                item['newer_completed_ws_bar']=bool(ws and ws['t']+60000<=now and (not rest or ws['t']>rest['t']))
        for item in report['markets'].values():
            item['finding']=('RAW_COMPLETED_HISTORY_FRESH' if item['completed_fresh'] else
                'NEW_COMPLETED_WS_BAR_AFTER_REST_OBSERVATION' if item.get('newer_completed_ws_bar') else
                'RAW_HISTORY_STALE_ADAPTER_MATCHES')
        report['status']='OBSERVED'
    except Exception as exc:
        report.update(status='OBSERVATION_FAILED',error_type=type(exc).__name__,reason=str(exc))
    finally:
        report['observed_at_utc']=datetime.now(timezone.utc).isoformat()
        client.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,default=str,allow_nan=False)+'\n')
    print(json.dumps(dict(path=str(args.output),status=report['status'],
        findings={s:v.get('finding') for s,v in report['markets'].items()},websocket=report.get('websocket'))))
    return 0 if report['status']=='OBSERVED' else 1


if __name__=='__main__':raise SystemExit(main())
