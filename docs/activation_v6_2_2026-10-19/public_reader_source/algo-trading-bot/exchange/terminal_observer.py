"""Persistent public observer for the standalone terminal. No signing imports."""
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json
import os
import threading
import time

from .base_exchange import ExchangeError
from .public_quant_operator import (SerializedPublicClient, SerializedPublicMarket,
    SerializedStreamMarket, ReadOnlyReceipts)
from .hyperliquid_client import RequestsInfoTransport
from .hyperliquid_market_data import ParMarketDataEngine
from .hyperliquid_account import HyperliquidAccount
from .hyperliquid_reconciliation import ExchangeTruthState, HyperliquidReconciliation
from .execution_journal import ExecutionJournal
from .rate_limits import HyperliquidRateLimitManager
from .reliability_policy import load_reliability_policy
from .paper_operations import active_source_hash
from .live_account_stream import LiveAccountStream
from .capital_allocation import floor_quantity, depth_capacity
from .quant_observation import explain_market, rank_reports
from .testnet_certification import TEAM
from .partial_fill_safety import partial_path_assessment
from .terminal_evidence import local_execution_state, opportunity_capacity, complete_scan_frame, SessionPerformance


class RotatingReceipts(ReadOnlyReceipts):
    """Bounded local retention; rotation is explicit, never a full-history proof."""
    def __init__(self, transport, path, *, limit=16_000_000, backups=8):
        super().__init__(transport, path)
        self.path = Path(path)
        self.limit, self.backups, self.rotations, self.records = limit, backups, 0, 0
        self.error_counts = {}

    def _record(self, record):
        with self.lock:
            if self.file.tell() >= self.limit:
                self.file.close()
                self.path.with_name(self.path.name + f'.{self.backups}').unlink(missing_ok=True)
                for i in range(self.backups - 1, 0, -1):
                    p = self.path.with_name(self.path.name + f'.{i}')
                    if p.exists():p.replace(self.path.with_name(self.path.name + f'.{i+1}'))
                self.path.replace(self.path.with_name(self.path.name + '.1'))
                self.file = self.path.open('x')
                self.rotations += 1
            self.records += 1
            if 'error' in record:
                key = f"{record.get('status_code')}:{record['error']}"
                self.error_counts[key] = self.error_counts.get(key, 0) + 1
            super()._record(record)


def observe(root, output, stop, publish, *, markets=(), scan_seconds=60, account_seconds=300, once=False, venue='par'):
    """Reuse stream, rate and account reconciliation infrastructure indefinitely.

    STOP/deadline belongs to the outer local application. No mandate is renewed.
    An exposed account remains visible and never obtains write authority here.
    """
    root, output = Path(root), Path(output)
    from .venue_profiles import venue_profile
    profile = venue_profile(venue)
    source = active_source_hash(root)
    clock = lambda: time.time_ns() // 1_000_000
    journal = ExecutionJournal(output/'public.sqlite', session_id='public:terminal', team_address=TEAM)
    policy, _, _ = load_reliability_policy(root/'configs/reliability_policy.json')
    rates = HyperliquidRateLimitManager(journal, policy=policy, clock_ms=clock)
    rates.read_budget_wait_seconds = 65
    rates.read_deadline_seconds = 75
    transport = RotatingReceipts(RequestsInfoTransport(), output/'info_receipts.jsonl')
    client = SerializedPublicClient(transport, rate_limits=rates, clock_ms=clock, venue=profile)
    client.read_cancel_event = stop
    stream = account_stream = thread = account_thread = history = None
    result = dict(mode='TESTNET OBSERVATION', status='CONNECTING', source_hash=source,
        team_wallet=TEAM, network='testnet', dex=profile.dex, collateral=profile.collateral,
        venue_identity=profile.identity, phase=profile.phase, approved_bankroll=None,
        approved_maximum_notional=None, proposed_bankroll='20000', signing_authority='NONE',
        exchange_writes=0, signatures_created=0, exchange_time_ms=None, signals=[], liquidity={})
    started_ms=clock()
    performance=SessionPerformance(started_ms)
    try:
        publish(result)
        client.startup()
        from .durable_history import DurableHistory
        cache_path=(output.parent.parent/'history.sqlite') if output.parent.name=='sessions' else output/'history.sqlite'
        history=DurableHistory(cache_path,client,output/'info_receipts.jsonl')
        client.candle_audit=history
        result['market_history']={}
        from .entry_scope import signal_markets
        selected = signal_markets(client,markets)
        if not selected or len(set(selected)) != len(selected) or any(s not in client.markets for s in selected):
            raise ExchangeError('RUNTIME_PAR_MARKETS_REQUIRED')
        result.update(markets=selected, metadata=client.metadata)
        stream = ParMarketDataEngine(SerializedPublicMarket(client), symbols=selected, history_bars=900, include_trades=True)
        def receive():
            try:stream.run(stop, max_reconnects=5)
            except Exception as exc:result['market_thread_error'] = type(exc).__name__
        thread = threading.Thread(target=receive, name='terminal-market', daemon=True)
        thread.start()
        market = SerializedStreamMarket(client, stream)
        account = HyperliquidAccount(client, TEAM)
        truth = ExchangeTruthState()
        reconciler = HyperliquidReconciliation(account)
        class PublicRecovery:
            def __init__(self):self.account, self.journal = account, journal
            def revoke(self, reason):truth.entries_paused = True
        # This executor has no submit/sign/key capability. Stream events only
        # invalidate cached account truth until the owner thread refreshes it.
        executor = SimpleNamespace(entries_paused=True, rate_limits=rates)
        account_stream = LiveAccountStream(TEAM, PublicRecovery(), executor, clock_ms=clock)
        account_stream.start_receiver();account_thread=account_stream.receiver_thread
        next_scan = next_account = next_health = 0
        account_failures = 0
        last_complete_scan=None
        while not stop.is_set():
            now = clock()
            if active_source_hash(root) != source:raise ExchangeError('TERMINAL_SOURCE_CHANGED')
            if account_stream.receiver_fatal:raise ExchangeError(account_stream.receiver_fatal)
            if now >= next_account or account_stream.pending and now >= next_account - account_seconds*1000 + 30000:
                next_account = now + account_seconds*1000
                try:
                    generation=account_stream.generation;sequence=account_stream.event_sequence
                    with client.request_lock:
                        client.startup()
                        reconciler.recover_incremental(truth, initial_start_ms=0)
                    result.update(account=truth.report(), account_observed_ms=clock(), account_error=None)
                    result.update(local_execution_state=local_execution_state(root),
                        session_performance=performance.observe(result['account'],result['account_observed_ms']))
                    truth.events.clear()  # Account state lives in the report, not an unbounded event list.
                    fees = account._query('userFees')
                    result.update(base_taker_fee_rate=str(D(fees['userCrossRate'])),base_maker_fee_rate=str(D(fees['userAddRate'])),
                        documented_pas_taker_fee_estimate=str(D(fees['userCrossRate'])*2) if profile.dex=='pas' else None,
                        fee_rate_bound=str(D(fees['userCrossRate'])*6),
                        maker_fee_rate_bound=str(D(fees['userAddRate'])*6),fees_observed_ms=clock(),
                        fee_estimation_basis='Existing conservative 6x base-rate bound; actual fills determine charged fees')
                    if profile.dex=='pas':
                        from .pas_funding import read_funding
                        prior_funding=result.get('funding',{})
                        result['funding']=read_funding(client,account,provenance=str(output/'info_receipts.jsonl'))
                        if prior_funding.get('balance')!=result['funding'].get('balance') or prior_funding.get('status')!=result['funding'].get('status'):
                            result['funding_event']=dict(before=prior_funding.get('status'),after=result['funding']['status'],
                                balance=result['funding']['balance'],observed_ms=clock(),signing_triggered=False)
                            with (output/'funding_events.jsonl').open('a') as f:
                                f.write(json.dumps(result['funding_event'])+'\n');f.flush();os.fsync(f.fileno())
                            next_scan=0
                        from .paper_operations import atomic_json
                        atomic_json(output/'funding_evidence.json',result['funding'])
                    account_failures = 0
                    with account_stream.lock:
                        if (account_stream.connected and account_stream.generation==generation
                                and account_stream.event_sequence==sequence and account_stream.subscribed == set(account_stream.CHANNELS)):
                            account_stream.pending = False
                            account_stream.ready = not truth.reasons
                            account_stream.reconciled_generation = account_stream.generation
                except Exception as exc:
                    account_failures += 1
                    result['account_error'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
                    if account_failures >= 3:raise ExchangeError('REPEATED_AUTHORITATIVE_ACCOUNT_FAILURE')
            if now >= next_scan:
                next_scan = now + scan_seconds*1000
                signals, capacity, opportunities = [], {}, []
                for symbol in selected:
                    if stop.is_set():break
                    row = dict(symbol=symbol, decision='NO_TRADE', reasons=[])
                    try:
                        end = clock()//60000*60000-1
                        begin = min(end+1-900*60000, end//86400000*86400000-14*60000)
                        spec = client.market(symbol)
                        try:
                            # Persist every normalized real REST response, including
                            # sparse snapshots which cannot yet satisfy the strategy.
                            cached=history.read(symbol,clock())
                            full=history.report(symbol,clock())
                            request_begin=max(begin,cached[-1].timestamp_ms-60000) if cached and cached[0].timestamp_ms<=begin and full['contiguous_tail_bars']>=300 else begin
                            try:
                                returned=market.get_candles(symbol,request_begin,end,now_ms=clock())
                                history.ingest(symbol,returned,now_ms=clock())
                            except (ExchangeError,ValueError) as exc:
                                row['history_recovery_reason']=str(exc)
                            bars=[b for b in history.read(symbol,clock()) if begin<=b.timestamp_ms<=end]
                            h=history.report(symbol,clock());result['market_history'][symbol]=h
                            # Slow history calls must not age quotes used for signal
                            # explanations; each observation has its own clock.
                            context=market.get_asset_contexts()[symbol];context_ms=clock()
                            book=market.get_orderbook(symbol);at=clock()
                            active=account._query('activeAssetData',coin=symbol);active_ms=clock()
                            row=explain_market(spec,book,bars,context,now_ms=clock(),context_ms=context_ms,fee_rate=D(result.get('fee_rate_bound','.003')))
                            row['history']=h
                        except (ExchangeError,ValueError) as exc:
                            row['reasons'].append(str(exc))
                            raise
                        fee=D(result.get('fee_rate_bound','.003'))
                        opportunity=opportunity_capacity(spec,book,active,row,now_ms=clock(),active_ms=active_ms,
                            fee_rate=fee,fee_ms=result.get('fees_observed_ms'),maker_fee_rate=result.get('maker_fee_rate_bound'))
                        opportunities.append(opportunity)
                        # A stale candle blocks signals independently; it does
                        # not erase a separately observed current bid/ask.
                        a, b = depth_capacity(book, 'BUY'), depth_capacity(book, 'SELL')
                        q = floor_quantity(spec, min(a['best_quantity']*D('.1'), b['best_quantity']*D('.1'),
                            a['raw_l2_quantity']*D('.1'), b['raw_l2_quantity']*D('.1'),
                            D(active['maxTradeSzs'][0]), min(D(x) for x in active['availableToTrade'])/(a['best_price']*(1+2*fee)),
                            D('10000')/a['best_price']))
                        # This is a capacity observation; strategy/protection/approval are independent.
                        partial=dict(entry_admissible_under_documented_minimum=False,blocker='FROZEN_STOP_PLAN_UNAVAILABLE')
                        if row.get('baseline_stop') is not None and row.get('metrics',{}).get('atr') is not None:
                            proposed=SimpleNamespace(symbol=symbol,asset_id=spec.asset_id,quantity=q,
                                entry_limit=spec.normalize_price(a['best_price']*D('1.0005'),'BUY'),
                                stop_limit=spec.normalize_price((row['baseline_stop']-row['metrics']['atr'])*D('.995'),'SELL'),
                                exit_bound=spec.normalize_price(b['best_price']*D('.9995'),'SELL'))
                            if q>0:partial=partial_path_assessment(spec,proposed)
                        capacity[symbol] = dict(quantity=str(q), notional=str(q*a['best_price']),
                            bid=str(book.bids[0].price), ask=str(book.asks[0].price), book_ms=book.timestamp_ms,
                            observed_ms=at, active_asset_ms=active_ms, context_ms=context_ms,
                            market_context=context,size_step=str(spec.size_step), one_lot_bid_notional=str(spec.size_step*book.bids[0].price),
                            partial_minimum_admissible=partial['entry_admissible_under_documented_minimum'],
                            partial_protection_qualified=partial['entry_admissible_under_documented_minimum'] if profile.dex=='par' else False,
                            native_protection_qualified=False,partial_path=partial,
                            targets={str(t):q*a['best_price']>=t for t in (1000,2500,5000,10000,25000,50000)},
                            qualified_unattended_notional='0', active_asset=active)
                        capacity[symbol]['evidence_evaluation']=opportunity
                        if profile.dex=='pas' and result.get('base_taker_fee_rate') is not None:
                            from .pas_economics import fee_scenarios
                            capacity[symbol]['fee_scenarios']=fee_scenarios(book,context,row,quantity=q,
                                base_taker_rate=result['base_taker_fee_rate'],base_maker_rate=result['base_maker_fee_rate'],now_ms=clock(),context_ms=context_ms)
                        if any(x in opportunity['reasons'] for x in ('CAPITAL_FRESH_PAR_BOOK_REQUIRED','ACTIVE_ACCOUNT_LIMITS_STALE','FEE_OBSERVATION_STALE')):
                            capacity[symbol].update(quantity='0',notional='0',stale_capacity_withheld=True)
                        row.update(approved_quantity=None, execution_preflight='NOT_AUTHORIZED',
                            protection='ACTUAL_NATIVE_TRIGGER_QUALIFICATION_REQUIRED')
                    except (ExchangeError, ValueError, KeyError, IndexError) as exc:
                        row['reasons'].append(str(exc))
                    if not any(r['symbol']==symbol for r in opportunities):
                        opportunities.append(dict(symbol=symbol,liquidity_only_quantity='0',liquidity_only_notional='0',
                            economically_viable_notional='0',authorized_executable_notional='0',
                            expected_net_pnl=None,reasons=list(row['reasons']) or ['DATA_UNAVAILABLE']))
                    signals.append(row)
                    result.update(signals=list(signals),liquidity=dict(capacity),status='SCANNING_NO_ORDER_AUTHORITY',scan_in_progress=True)
                    publish(result)
                frame=complete_scan_frame(rank_reports(signals),capacity,opportunities,
                    market_count=len(selected),at=clock(),cancelled=stop.is_set())
                if frame is not None:
                    last_complete_scan=frame;result.update(frame)
                else:
                    result['interrupted_scan']=dict(observed_ms=clock(),signals=signals,liquidity=capacity,
                        completed_markets=len(signals),expected_markets=len(selected))
                    if last_complete_scan:result.update(last_complete_scan)
                    else:result.update(signals=[],liquidity={},capacity_ranking=[],latest_scan_ms=None,scan_in_progress=False)
                if once:break
            if now >= next_health:
                next_health = now+5000
                result.update(status='EXPOSED_REQUIRES_OPERATOR' if truth.positions or truth.orders else 'OBSERVING',
                    stream_connected=stream.connected, stream_reconciled=stream.reconciled,
                    stream_transport=stream.transport_health.report(), stream_last_error=stream.last_error,
                    stream_reconnections=stream.reconnections, account_stream_connected=account_stream.connected,
                    account_stream_error=account_stream.last_error,account_stream_generation=account_stream.generation,
                    account_stream_healthy=account_stream.healthy, account_subscriptions=sorted(account_stream.subscribed),
                    account_age_ms=clock()-result['account_observed_ms'] if result.get('account_observed_ms') else None,
                    fee_age_ms=clock()-result['fees_observed_ms'] if result.get('fees_observed_ms') else None,
                    rate_report=rates.report(), public_receipt_count=transport.records,
                    receipt_rotations=transport.rotations, actual_errors=transport.error_counts,
                    feed_mode='WEBSOCKET_WITH_RATE_CONTROLLED_REST_FALLBACK' if stream.connected else 'RATE_CONTROLLED_REST_FALLBACK')
                result['session_account_events']=dict(fills=[asdict(f) for f in truth.fills.values() if f.timestamp_ms>=started_ms],
                    funding=[asdict(e) for e in truth.funding.values() if e.timestamp_ms>=started_ms],start_ms=started_ms)
                publish(result)
                if thread and not thread.is_alive():raise ExchangeError('MARKET_COLLECTOR_STOPPED')
            stop.wait(.25)
    except Exception as exc:
        from .terminal_recovery import exception_evidence
        result.update(status='HALTED', error=str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__,
            error_details=exception_evidence(exc))
    finally:
        stop.set()
        if stream:stream._recovery_cancel.set()
        if account_stream:
            try:account_stream.stop_receiver()
            except Exception as exc:
                from .terminal_recovery import exception_evidence
                result['account_thread_shutdown_error']=exception_evidence(exc)
        if thread:thread.join(12)
        if account_thread:account_thread.join(12)
        result['threads_stopped'] = not any(t and t.is_alive() for t in (thread,account_thread))
        if result.get('account_thread_fatal'):result.update(status='HALTED',error=result['account_thread_fatal'])
        result['terminal_readbacks'] = []
        if result['threads_stopped'] and 'reconciler' in locals():
            from .terminal_recovery import terminal_reconcile
            result.update(terminal_reconcile(account,reconciler,truth,client,rates,clock))
        if result.get('account_observed_ms') is not None and result.get('account'):
            result['session_performance']=performance.observe(result['account'],result['account_observed_ms'])
        r = result['terminal_readbacks']
        result['terminal_flat'] = len(r)==2 and r[0]['observed_ms']<r[1]['observed_ms'] and all(x['ready'] and not x['positions'] and not x['orders'] for x in r)
        result.setdefault('account_status','FLAT_VERIFIED' if result['terminal_flat'] else 'UNKNOWN')
        result.setdefault('residual_status','FLAT_VERIFIED' if result['terminal_flat'] else 'UNKNOWN_REQUIRES_OPERATOR')
        result['journal_integrity'] = journal.db.execute('PRAGMA integrity_check').fetchone()[0]
        result['execution_intents'] = len(journal.intents())
        if history:
            result['history_integrity']=history.db.execute('PRAGMA integrity_check').fetchone()[0]
            history.close()
        client.close();journal.close()
        if result['status'] != 'HALTED':result['status'] = 'STOPPED'
        result['source_hash_after']=active_source_hash(root)
        if result['source_hash_after']!=source:result.update(status='HALTED',error='TERMINAL_SOURCE_CHANGED')
        result.update(public_receipt_count=transport.records, receipt_rotations=transport.rotations, actual_errors=transport.error_counts)
        publish(result)
    return result
