"""Bounded public observation/report process. No SDK signer or exchange writes."""
from dataclasses import asdict
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime
from zoneinfo import ZoneInfo
import json,threading,time,os,signal
from .base_exchange import ExchangeError
from .hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from .hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine
from .hyperliquid_account import HyperliquidAccount
from .hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from .execution_journal import ExecutionJournal,safe_reason
from .rate_limits import HyperliquidRateLimitManager
from .reliability_policy import load_reliability_policy
from .paper_operations import PaperOwner,active_source_hash,atomic_json
from .stream_first import StreamFirstMarketData
from .quant_observation import explain_market,rank_reports
from .capital_allocation import floor_quantity,depth_capacity

READ_QUERIES=frozenset({'perpDexs','meta','metaAndAssetCtxs','l2Book','candleSnapshot',
    'clearinghouseState','spotClearinghouseState','frontendOpenOrders','openOrders',
    'userFillsByTime','userFunding','userFees','activeAssetData','userAbstraction','extraAgents',
    'orderStatus','perpDexLimits','userRateLimit'})


class SerializedPublicClient(HyperliquidClient):
    def __init__(self,*args,**kwargs):
        self.request_lock=threading.RLock();super().__init__(*args,**kwargs)
    def startup(self):
        with self.request_lock:return super().startup()
    def post_info(self,*args,**kwargs):
        with self.request_lock:return super().post_info(*args,**kwargs)
    def market(self,symbol):
        with self.request_lock:return super().market(symbol)


class SerializedPublicMarket(HyperliquidMarketData):
    def __init__(self,client,*a,**k):
        with client.request_lock:super().__init__(client,*a,**k)
    def get_candles(self,*a,**k):
        with self.client.request_lock:return super().get_candles(*a,**k)
    def get_asset_contexts(self):
        with self.client.request_lock:return super().get_asset_contexts()
    def get_orderbook(self,symbol):
        with self.client.request_lock:return super().get_orderbook(symbol)


class SerializedStreamMarket(StreamFirstMarketData,SerializedPublicMarket):
    def get_candles(self,*a,**k):
        with self.client.request_lock:return super().get_candles(*a,**k)
    def get_asset_contexts(self):
        with self.client.request_lock:return super().get_asset_contexts()
    def get_orderbook(self,symbol):
        with self.client.request_lock:return super().get_orderbook(symbol)


class ReadOnlyReceipts(RequestsInfoTransport):
    """Decorator retaining the client's cancellable Requests transport contract."""
    def __init__(self,transport,path):
        self.transport=transport;self.file=Path(path).open('x');self.lock=threading.RLock()

    def __call__(self,payload,*,cancel_event=None,progress=None):
        if (not isinstance(payload,dict) or payload.get('type') not in READ_QUERIES
                or any(x in payload for x in ('action','signature','private_key','nonce'))):
            raise ExchangeError('QUANT_OBSERVER_READ_ONLY_QUERY_REQUIRED')
        sent=time.time_ns()//1000000;record=dict(request=payload,sent_ms=sent)
        try:
            response=self.transport(payload,cancel_event=cancel_event,progress=progress) if isinstance(
                self.transport,RequestsInfoTransport) else self.transport(payload)
            record['response']=response
        except Exception as exc:
            record.update(error=safe_reason(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
                status_code=getattr(exc,'status_code',None),retry_after_ms=getattr(exc,'retry_after_ms',None))
            self._record(record);raise
        self._record(record)
        return response

    def _record(self,record):
        record['received_ms']=time.time_ns()//1000000
        with self.lock:
            if self.file.tell()>500000000:raise ExchangeError('QUANT_RECEIPT_STORAGE_BOUND_EXCEEDED')
            self.file.write(json.dumps(record,default=str)+'\n');self.file.flush()

    def close(self):
        self.transport.close();self.file.close()


def operator_report(path,value):
    atomic_json(path/'operator_report.json',value)
    account=value.get('account',{});realized=account.get('realized',{})
    lines=['# Anchorium daily operator — PUBLIC OBSERVATION ONLY','',
        f"Status: **{value['status']}**. Updated ms: {value['updated_ms']}. Signing authority: **NONE**. Deadline ms: {value['expires_ms']}.",'',
        f"Actual account positions: {len(account.get('positions',[]))}; open orders: {len(account.get('open_orders',[]))}. Account observation ms: {value.get('account_observed_ms')}.",
        f"Actual observed account-event net: {realized.get('net_after_fees_and_funding')} TEST USDPR. This is separate from all synthetic stress results.",
        'Approved capital: **none**; approved risk budget: **none**; qualified unattended notional: **0**. Native protection and SHORT exchange qualification remain unverified.','',
        '| Market | Decision | Bias | Reasons | LONG/SHORT liquidity cap (TEST USDPR) |','|---|---|---|---|---:|']
    for r in value.get('signals',[]):
        caps=value.get('liquidity',{}).get(r['symbol'],{})
        lines.append(f"| {r['symbol']} | {r['decision']} | {r.get('metrics',{}).get('trend')} | {', '.join(r['reasons'])} | {caps.get('long')} / {caps.get('short')} |")
    lines+=['','Ranking scores, when present, are descriptive ranks rather than calibrated confidence. All signals use the unchanged frozen brain; higher-timeframe confirmation is an isolated observation veto. Candle gaps and stale data yield NO_TRADE, never forward-filled bars.','',
        'Worker source changes, deadline, operator interruption or account exposure/order surprises terminate observation. Mac, application, power and internet availability are required. A heartbeat is not signing authorization.']
    equity=account.get('reported_account_equity',{})
    lines+=['','## Account and execution evidence','',
        f"Reported account equity: {equity.get('reported_account_value')}; reported collateral: {equity.get('collateral_balance')}; margin used: {equity.get('margin_used')}. This collateral is not an approved bankroll.",
        f"Gross observed closed P&L: {realized.get('gross_closed_pnl')}; actual fees: {realized.get('actual_fill_fees')}; actual funding: {realized.get('actual_funding_cashflow')} TEST USDPR.",
        f"Observation-session equity change: {value.get('observed_equity_change')}; sampled equity drawdown: {value.get('sampled_equity_drawdown')}. Sampling does not establish intraperiod maximum drawdown.",
        'Current allocation and risk budget: none. Active strategy stop, take profit and liquidation price: unavailable while flat. Native stop verification: absent. No trade cycle is inferred from submitted orders or simulated scenarios.','',
        '| Exchange time ms | Symbol | Side | Quantity | Price | Order ID | Fill ID | Actual fee |',
        '|---:|---|---|---:|---:|---|---|---:|']
    for f in account.get('fills',[]):
        lines.append(f"| {f['timestamp_ms']} | {f['symbol']} | {f['side']} | {f['quantity']} | {f['price']} | {f['order_id']} | {f['trade_id']} | {f['fee']} |")
    original_ids={'800659111758533','260274449763192'}
    known_close=original_ids.issubset({str(f['trade_id']) for f in account.get('fills',[])})
    lines+=['',f'Original BTC entry/exit fill pair present in these reads: {known_close}; current session orders: zero. Actual SHORT performance and larger size-tier returns: not yet tested. Win-rate, profit factor and annualized ratios are not statistically established by one trade. Session percentage return and sampled equity changes are not organizer scores.']
    (path/'operator_report.md').write_text('\n'.join(lines)+'\n')


def observe(root,output,*,team_wallet,markets,expires_ms,source_hash,scan_seconds=300,
            heartbeat_seconds=30,clock_ms=None,stop_event=None):
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    require_paper_migration();verify_strategy_freeze()
    root=Path(root);path=Path(output);path.mkdir(parents=True,exist_ok=False)
    clock=clock_ms or (lambda:time.time_ns()//1000000);now=clock()
    end=datetime.fromtimestamp(expires_ms/1000,ZoneInfo('Asia/Calcutta'))
    start=datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta'))
    if (type(expires_ms) is not int or not now<expires_ms<=now+86400000
            or start.date()!=end.date() or start.date().isoformat()!='2026-10-16'
            or not 60<=scan_seconds<=3600 or not 1<=heartbeat_seconds<=60):
        raise ExchangeError('EXACT_BOUNDED_OCT16_PUBLIC_SESSION_REQUIRED')
    if active_source_hash(root)!=source_hash:raise ExchangeError('PUBLIC_OPERATOR_SOURCE_MISMATCH')
    owner=PaperOwner(path/'owner.lock');journal=None;client=None;stream=None;thread=None
    stop=stop_event or threading.Event();previous={};clean=False;guard_done=threading.Event()
    report=dict(status='STARTING',updated_ms=now,expires_ms=expires_ms,source_hash=source_hash,
        pid=os.getpid(),network='testnet',dex='par',team_wallet=team_wallet,
        execution_mode='PAPER',allow_live_orders=False,signatures_created=0,exchange_writes=0,
        signing_authority='NONE',signals=[],liquidity={})
    def guard():
        # Independent of a rate-budget wait or candle recovery. No order path.
        while not guard_done.wait(heartbeat_seconds):
            reason=None
            if clock()>=expires_ms:reason='PUBLIC_SESSION_EXPIRED'
            elif active_source_hash(root)!=source_hash:reason='PUBLIC_OPERATOR_SOURCE_CHANGED'
            if reason:
                report['guard_stop_reason']=reason;stop.set()
                if stream:stream._recovery_cancel.set()
                return
    guard_thread=threading.Thread(target=guard,name='quant-public-deadline',daemon=True)
    guard_thread.start()
    try:
        journal=ExecutionJournal(path/'public_observer.sqlite',session_id='public-quant-oct16',team_address=team_wallet)
        rate_policy,_,_=load_reliability_policy(root/'configs/reliability_policy.json')
        rates=HyperliquidRateLimitManager(journal,policy=rate_policy,clock_ms=clock)
        rates.read_budget_wait_seconds=65
        transport=ReadOnlyReceipts(RequestsInfoTransport(),path/'info_receipts.jsonl')
        client=SerializedPublicClient(transport,rate_limits=rates,clock_ms=clock);client.read_cancel_event=stop;client.startup()
        selected=tuple(markets)
        if not selected or len(selected)>10 or len(set(selected))!=len(selected) or any(s not in client.markets for s in selected):
            raise ExchangeError('BOUNDED_RUNTIME_PAR_MARKETS_REQUIRED')
        report['markets']=selected;public=SerializedPublicMarket(client)
        stream=ParMarketDataEngine(public,symbols=selected,history_bars=900,include_trades=False)
        def receive():
            try:stream.run(stop,max_reconnects=5)
            except Exception as exc:report['stream_error']=type(exc).__name__
        thread=threading.Thread(target=receive,name='quant-public-stream',daemon=True);thread.start()
        market=SerializedStreamMarket(client,stream)
        account=HyperliquidAccount(client,team_wallet);truth=ExchangeTruthState();reconciler=HyperliquidReconciliation(account)
        next_scan=next_heartbeat=0
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,lambda *_:stop.set())
        while not stop.is_set() and clock()<expires_ms:
            now=clock()
            if now>=next_scan:
                if active_source_hash(root)!=source_hash:raise ExchangeError('PUBLIC_OPERATOR_SOURCE_CHANGED')
                next_scan=now+int(scan_seconds*1000)
                with client.request_lock:reconciler.recover_incremental(truth,initial_start_ms=0)
                report['account']=truth.report();report['account_observed_ms']=clock()
                equity=D(report['account']['reported_account_equity']['reported_account_value'])
                initial=D(report.setdefault('initial_observed_equity',str(equity)))
                peak=max(D(report.get('peak_observed_equity',str(equity))),equity)
                report.update(peak_observed_equity=str(peak),observed_equity_change=str(equity-initial),
                    sampled_equity_drawdown=str(max(D(report.get('sampled_equity_drawdown','0')),peak-equity)))
                if truth.positions or truth.orders:raise ExchangeError('UNEXPECTED_ACCOUNT_EXPOSURE_REQUIRES_HUMAN_REVIEW')
                if not truth.initialized or truth.reasons:raise ExchangeError('AUTHORITATIVE_ACCOUNT_RECONCILIATION_UNAVAILABLE')
                with client.request_lock:fees=account._query('userFees')
                fee=D(fees['userCrossRate'])*6
                report['fee_bound']=str(fee);signals=[];liquidity={};snapshots=[]
                for symbol in selected:
                    if stop.is_set() or clock()>=expires_ms:break
                    row=dict(symbol=symbol,decision='NO_TRADE',reasons=[])
                    try:
                        end_ms=clock()//60000*60000-1
                        # Full UTC-anchor support plus sufficient HTF history.
                        utc_day=end_ms//86400000*86400000
                        begin=min(end_ms+1-900*60000,utc_day-14*60000)
                        candles=market.get_candles(symbol,begin,end_ms,now_ms=clock())
                        contexts=market.get_asset_contexts();context_ms=clock()
                        book=market.get_orderbook(symbol);observed=clock();spec=client.market(symbol)
                        row=explain_market(spec,book,candles,contexts[symbol],now_ms=observed,
                            context_ms=context_ms,fee_rate=fee)
                        cap=floor_quantity(spec,min(book.bids[0].quantity,book.asks[0].quantity,
                            depth_capacity(book,'BUY')['raw_l2_quantity'],depth_capacity(book,'SELL')['raw_l2_quantity'])*D('.1'))
                        liquidity[symbol]=dict(long=str(cap*book.asks[0].price),short=str(cap*book.bids[0].price),observed_ms=observed)
                        snapshots.append(dict(observed_ms=observed,spec=asdict(spec),book=asdict(book),
                            context=contexts[symbol],candles=[asdict(c) for c in candles],signal=row))
                    except (ExchangeError,ValueError) as exc:row['reasons'].append(str(exc))
                    signals.append(row)
                report.update(status='OBSERVING_NO_ORDER_AUTHORITY',signals=rank_reports(signals),liquidity=liquidity,
                    latest_scan_ms=clock(),watchlist=[r['symbol'] for r in signals if r['decision']!='NO_TRADE'][:3])
                with (path/'market_snapshots.jsonl').open('a') as f:
                    for s in snapshots:f.write(json.dumps(s,default=str)+'\n')
            if now>=next_heartbeat:
                if active_source_hash(root)!=source_hash:raise ExchangeError('PUBLIC_OPERATOR_SOURCE_CHANGED')
                next_heartbeat=now+int(heartbeat_seconds*1000)
                report.update(updated_ms=clock(),stream_connected=stream.connected,
                    stream_reconciled=stream.reconciled,account_age_ms=clock()-report.get('account_observed_ms',clock()),
                    stream_last_error=stream.last_error,stream_reconnections=stream.reconnections,
                    stream_transport=stream.transport_health.report(),
                    feed_mode='WEBSOCKET_WITH_RATE_CONTROLLED_REST_FALLBACK' if stream.connected else 'RATE_CONTROLLED_REST_FALLBACK',
                    rate_report=rates.report())
                operator_report(path,report)
            stop.wait(min(1,max(0,(expires_ms-clock())/1000)))
        clean=True;report['status']=report.get('guard_stop_reason') or ('PUBLIC_SESSION_EXPIRED' if clock()>=expires_ms else 'PUBLIC_SESSION_STOPPED')
    except Exception as exc:
        report.update(status='PUBLIC_SESSION_HALTED',error_type=type(exc).__name__,
            reason=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        stop.set()
        if stream:stream._recovery_cancel.set()
        if thread:thread.join(12)
        if thread and thread.is_alive():report.update(status='PUBLIC_SHUTDOWN_INCOMPLETE',clean=False)
        else:report['clean']=clean
        report['fresh_terminal_reconciliation']=False
        if client and journal and not (thread and thread.is_alive()) and 'reconciler' in locals():
            # Bounded public reads after collection stops; no signing authority
            # is created by terminal reconciliation or by a flat account.
            final_cancel=threading.Event();timer=threading.Timer(30,final_cancel.set)
            client.read_cancel_event=final_cancel;rates.read_budget_wait_seconds=5;timer.start()
            readbacks=[]
            try:
                for _ in range(2):
                    with client.request_lock:reconciler.recover_incremental(truth,initial_start_ms=0)
                    report['account']=truth.report();report['account_observed_ms']=clock()
                    readbacks.append(dict(observed_ms=clock(),positions=truth.report()['positions'],
                        orders=truth.report()['open_orders'],ready=truth.initialized and not truth.reasons,
                        source='EXCHANGE_DIRECT_TESTNET_PAR_INFO'))
                report['terminal_readbacks']=readbacks
                report['fresh_terminal_reconciliation']=all(r['ready'] for r in readbacks)
                if truth.positions or truth.orders:report['status']='EXPOSURE_REQUIRES_HUMAN_REVIEW'
            except Exception as exc:report['terminal_reconciliation_error']=type(exc).__name__
            finally:timer.cancel()
        guard_done.set();guard_thread.join(1)
        if client:client.close()
        if journal:
            report['journal_integrity']=journal.db.execute('PRAGMA integrity_check').fetchone()[0];journal.close()
        owner.close()
        for sig,handler in previous.items():signal.signal(sig,handler)
        report.update(updated_ms=clock(),final_positions=report.get('account',{}).get('positions'),
            final_orders=report.get('account',{}).get('open_orders'),signing_revoked=True)
        operator_report(path,report);atomic_json(path/'terminal_result.json',report)
    return report
