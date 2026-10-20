"""Bounded unsigned BTC/EWY upstream/stream diagnostic; never synthesizes bars."""
from pathlib import Path
import threading,time
from .entry_scope import PAS_ENTRY_MARKETS
from .paper_operations import active_source_hash,atomic_json


def review_history(root,output):
    from .public_quant_operator import SerializedPublicClient,ReadOnlyReceipts,SerializedPublicMarket
    from .hyperliquid_client import RequestsInfoTransport
    from .hyperliquid_market_data import ParMarketDataEngine
    from .execution_journal import ExecutionJournal
    from .rate_limits import HyperliquidRateLimitManager
    from .durable_history import DurableHistory
    from .candle_audit import PublicCandleAudit
    from .testnet_certification import TEAM
    p=Path(output);p.mkdir(parents=True,exist_ok=False)
    source=active_source_hash(Path(root));stop=threading.Event()
    timer=threading.Timer(180,stop.set);timer.start()
    journal=ExecutionJournal(p/'public.sqlite',session_id='pas-history-review',team_address=TEAM)
    rates=HyperliquidRateLimitManager(journal);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
    client=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),p/'info_receipts.jsonl'),rate_limits=rates,venue='pas')
    client.read_cancel_event=stop
    history=engine=thread=None
    result=dict(source_hash=source,signing_authority='NONE',exchange_writes=0,signatures_created=0,markets={})
    try:
        client.startup();history=DurableHistory(p/'history.sqlite',client,p/'info_receipts.jsonl')
        raw_audit=PublicCandleAudit(p/'candle_wire.jsonl')
        class Audit:
            def record(self,stage,**values):
                raw_audit.record(stage,**values);history.record(stage,**values)
        client.candle_audit=Audit()
        market=SerializedPublicMarket(client)
        for symbol in sorted(PAS_ENTRY_MARKETS):
            now=client.clock_ms();end=now//60000*60000-1;start=end+1-5000*60000
            row=dict(symbol=symbol,asset_id=client.market(symbol).asset_id,requested_start_ms=start,requested_end_ms=end)
            try:
                bars=market.get_candles(symbol,start,end)
                trades=client.post_info('recentTrades',coin=symbol)
                times=[x['time'] for x in trades if x.get('coin')==symbol and type(x.get('time')) is int]
                row.update(history=history.report(symbol,client.clock_ms()),recent_trade_count=len(trades),
                    first_recent_trade_ms=min(times) if times else None,last_recent_trade_ms=max(times) if times else None,
                    first_ever_trade_ms=None,trade_history_scope='recentTrades is bounded; first-ever trade is UNKNOWN',
                    funding_history=client.post_info('fundingHistory',coin=symbol,startTime=now-86400000),
                    asset_context=market.get_asset_contexts()[symbol])
            except Exception as exc:row['error']=str(exc)
            result['markets'][symbol]=row
        for row in result['markets'].values():row['initial_history']=row.get('history')
        engine=ParMarketDataEngine(market,symbols=sorted(PAS_ENTRY_MARKETS),include_trades=True)
        def receive():
            try:engine.run(stop,max_reconnects=2)
            except Exception as exc:result['stream_error']=str(exc)
        thread=threading.Thread(target=receive,daemon=True);thread.start()
        # Read-only stream sample, bounded independently of the total read budget.
        stop.wait(30)
        result['stream_transport']=engine.transport_health.report()
        result['candle_availability']=engine.availability.snapshot(include_records=True)
        result['completion_policy']='ACTUAL_POST_CLOSE_OBSERVATION; open updates are not finalized by local clock passage'
        result['wire_receipts_file']='candle_wire.jsonl'
        for symbol,row in result['markets'].items():
            row['history']=history.report(symbol,client.clock_ms())
            row['strategy_signal']='UNKNOWN'
            row['signal_reason']='Use the frozen scanner after full authentic warmup and freshness checks'
            row['last_stream_trade']=engine.last_trades.get(symbol)
        result.update(status='UNSIGNED_HISTORY_REVIEW_COMPLETE',observed_ms=client.clock_ms(),
            source_hash_after=active_source_hash(Path(root)))
    except Exception as exc:result.update(status='HISTORY_REVIEW_INCOMPLETE',error=str(exc))
    finally:
        stop.set()
        if engine:engine._recovery_cancel.set()
        if thread:thread.join(timeout=15)
        result['stream_stopped']=thread is None or not thread.is_alive()
        if history:
            result['history_integrity']=history.db.execute('pragma integrity_check').fetchone()[0]
            history.close()
        result['journal_integrity']=journal.db.execute('pragma integrity_check').fetchone()[0]
        client.close();journal.close();timer.cancel()
        atomic_json(p/'history_review.json',result)
    return result
