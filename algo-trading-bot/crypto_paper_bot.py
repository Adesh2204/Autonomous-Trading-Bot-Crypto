"""Generic scanner -> frozen brain/state -> perpetual risk -> local executor."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal

from crypto_strategy_state import CryptoStrategyState
from exchange.base_exchange import ExchangeError
from exchange.event_timing import timing
from exchange.readiness import readiness
from exchange.order_lifecycle import OrderRequest
from exchange.paper_portfolio import FundingSettlement
from exchange.paper_reconciliation import PaperReconciliation
from risk.circuit_breakers import CircuitBreakers
from risk.exposure_manager import ExposureManager
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


class CryptoPaperBot:
    def __init__(self, market, scanner, execution, risk):
        require_paper_migration()
        if execution.is_live or execution.portfolio is None:
            raise ExchangeError('ACCOUNTED_PAPER_EXECUTOR_REQUIRED')
        self.market=market
        self.scanner=scanner
        self.execution=execution
        self.risk=risk
        self.clock_ms=market.client.clock_ms
        self.managers={}
        self.decisions=[]
        self.last_signals={}
        self.latest_scan=None
        self.quotes={}
        self._day=None
        self._day_start_equity=execution.portfolio.starting_collateral
        self._daily_setups=0
        self._funding_hour=self.clock_ms()//3600000
        self.accounting_halt=None
        self.reserved_setup_risk={}
        self.pending_exit_reasons={}
        self.setup_baseline_cash={}
        self.closed_trades=[]
        self.peak_equity=execution.portfolio.starting_collateral
        self.max_drawdown_fraction=Decimal(0)
        self.breakers=CircuitBreakers(risk.policy)
        self.reconciler=PaperReconciliation(execution)
        self.feed_health={}
        self.stream_report=None
        self.exchange_account_report=None
        self.market_snapshots={}
        self.team_address=None
        self.candidate_ids={}
        self.position_candidates={}
        self._audited_scan=None
        from opportunity_funnel import OpportunityFunnel
        self.funnel=OpportunityFunnel(source='LOCAL_'+execution.execution_mode+'_OBSERVATION')
        self.scanner.diagnostic_sink=self.funnel

    def _performance(self,snapshot):
        self.peak_equity=max(self.peak_equity,snapshot.equity)
        self.max_drawdown_fraction=max(self.max_drawdown_fraction,
                                      (self.peak_equity-snapshot.equity)/self.peak_equity)
        self.breakers.evaluate(snapshot,daily_loss=max(Decimal(0),self._day_start_equity-snapshot.equity),
                               drawdown=self.max_drawdown_fraction,
                               daily_loss_limit=self.execution.portfolio.starting_collateral*self.risk.policy.max_daily_loss_fraction)
        return snapshot

    def reconcile_paper_state(self):
        self._fresh_marks()
        self.execution.quotes.update(self.quotes)
        report=self.reconciler.recover(self.managers)
        self._record('PAPER_ACCOUNT_RECONCILED',report=report)
        return report

    def _manager(self,symbol):
        if symbol not in self.managers:
            self.managers[symbol]=CryptoStrategyState(symbol,self._close,clock_ms=self.clock_ms)
        return self.managers[symbol]

    def _record(self,kind,**details):
        symbol=details.get('symbol')
        details.setdefault('candidate_id',self.candidate_ids.get(symbol))
        clocks=details.pop('_timing',None) or timing(self.clock_ms())
        self.decisions.append(dict(kind=kind,timestamp_ms=self.clock_ms(),**clocks,**details))
        self.funnel.event(kind,details.get('candidate_id'),details,self.decisions[-1]['timestamp_ms'])

    def audit_scan(self,scan):
        """Record every candidate, including unavailable data and no-signal bars."""
        if self._audited_scan==scan.observed_at_ms:
            return
        self._audited_scan=scan.observed_at_ms
        self.funnel.observe_scan(scan,getattr(self.scanner,'policy',None))
        for d in scan.diagnostics:
            cid=f'{d.symbol}:{scan.observed_at_ms}'
            self.candidate_ids[d.symbol]=cid
            signal=d.signal or {}
            selected=d.symbol in scan.watchlist
            has_signal=bool(signal.get('long') or signal.get('short'))
            self._record('MARKET_DATA',symbol=d.symbol,candidate_id=cid,metrics=d.metrics,
                _timing={k:getattr(d.snapshot,k) for k in ('exchange_ts','received_ts','processed_ts')} if d.snapshot else None,
                market_snapshot=asdict(d.snapshot) if d.snapshot else None,
                candle_timestamp_ms=signal.get('timestamp_ms'),data_status='PASS' if d.signal else 'UNAVAILABLE',
                reasons=d.reasons)
            # Indicator values are copied from the frozen brain, never recalculated here.
            self._record('SIGNAL',symbol=d.symbol,candidate_id=cid,signal=signal,metrics=d.metrics,_timing=d.timing or None,
                scan_selected=selected,signal_status='PASS' if has_signal else 'NO_SIGNAL',
                scanner_status='PASS' if d.qualified else 'REJECTED',
                input_timing=d.timing,input_candle_close_ms=d.candles[-1].close_timestamp_ms if d.candles else None)
            if not selected or not has_signal:
                self._record('ENTRY_REJECTED',symbol=d.symbol,candidate_id=cid,
                    reason=d.reasons[0] if d.reasons else 'NOT_SELECTED' if not selected else 'NO_SIGNAL',
                    stage='SCANNER' if not selected else 'SIGNAL',risk_status='NOT_REACHED',
                    execution_status='NOT_REACHED')

    def _fresh_marks(self):
        for symbol in self.execution.portfolio.positions:
            quote=self.quotes.get(symbol)
            now=self.clock_ms()
            if (quote is None or not 0<=now-quote.timestamp_ms<=4000 or quote.mark_timestamp_ms is None or
                    not 0<=now-quote.mark_timestamp_ms<=self.risk.policy.max_mark_age_ms):
                self.quotes[symbol]=self.market.get_quote(symbol)

    def _close(self,symbol,reason):
        manager=self._manager(symbol)
        held=self.execution.positions.get(symbol,Decimal(0))
        if not held:
            return None
        self.pending_exit_reasons[symbol]=reason
        quote=self.quotes[symbol]
        cid=self.position_candidates.get(symbol)
        self.execution.candidate_id=cid
        self._record('EXECUTION_DECISION',symbol=symbol,candidate_id=cid,intent='REDUCE_ONLY_EXIT',reason=reason)
        side='SELL' if held>0 else 'BUY'
        price=quote.bid if side=='SELL' else quote.ask
        try:
            request=OrderRequest(symbol,side,abs(held),price,reduce_only=True,tif='Ioc',
                                 strategy_id='VWAP_BASELINE_EXIT')
            order=self.execution.submit(request)
            fill=self.execution.simulate_fill(order.order_id,quote)
            self.breakers.order_result(True)
            if fill:
                manager.confirm_exit(fill,reason)
                self._record('EXIT_FILL',symbol=symbol,candidate_id=cid,reason=reason,fill=asdict(fill))
                if not manager.has_open_position:
                    self.closed_trades.append(dict(symbol=symbol,reason=reason,candidate_id=cid,
                        completed_at_ms=self.clock_ms(),net_pnl=self.execution.portfolio.cash-
                        self.setup_baseline_cash.pop(symbol),collateral='USDPR',simulated=True,
                        **timing(self.clock_ms())))
                    self._record('TRADE_PNL',symbol=symbol,candidate_id=cid,trade=self.closed_trades[-1])
                    self.position_candidates.pop(symbol,None)
                    self.reserved_setup_risk.pop(symbol,None)
                    self.pending_exit_reasons.pop(symbol,None)
                return dict(reason=reason,quantity=fill.quantity,partial=manager.has_open_position)
            self._record('EXIT_UNFILLED',symbol=symbol,candidate_id=cid,reason=reason)
        except ExchangeError as exc:
            self.breakers.order_result(False)
            self._record('EXIT_REJECTED',symbol=symbol,candidate_id=cid,reason=str(exc),trigger=reason)
        return None

    def _funding(self,quotes,now):
        hour=now//3600000
        if hour<=self._funding_hour:
            return
        held=list(self.execution.portfolio.positions)
        if held and (hour!=self._funding_hour+1 or now-hour*3600000>5000):
            self.accounting_halt='MISSED_PAPER_FUNDING_BOUNDARY_REQUIRES_REPLAY'
            self.breakers.pause('accounting',self.accounting_halt)
            return
        for symbol in held:
            quote=quotes.get(symbol)
            if quote is None:
                raise ExchangeError('FUNDING_OBSERVATION_MISSING')
            self.execution.portfolio.settle_funding(FundingSettlement(symbol,hour*3600000,
                quote.oracle,quote.hourly_funding,'PAPER_SNAPSHOT_ESTIMATE'),now)
        self._funding_hour=hour

    def observe(self,quotes):
        """Single-thread ledger owner; feed ticks may call this between scans."""
        require_paper_migration()
        verify_strategy_freeze()
        now=self.clock_ms()
        self.quotes.update(quotes)
        self.execution.quotes.update(quotes)
        active={s:q for s,q in self.quotes.items() if s in self.execution.portfolio.positions}
        # A missing/stale portfolio mark forbids accounting or new entry.
        snapshot=self.execution.portfolio.snapshot(active,now)
        self._performance(snapshot)
        self._funding(active,now)
        day=datetime.fromtimestamp(now/1000,timezone.utc).date()
        if day!=self._day:
            self._day=day
            self._daily_setups=0
            self._day_start_equity=snapshot.equity
        for symbol in list(self.execution.portfolio.positions):
            quote=self.quotes[symbol]
            manager=self._manager(symbol)
            manager._check_day_reset(datetime.fromtimestamp(now/1000,timezone.utc))
            held=self.execution.portfolio.positions[symbol]
            if symbol in self.pending_exit_reasons:
                self._close(symbol,self.pending_exit_reasons[symbol])
                if not manager.has_open_position:
                    continue
                # An exit intent persists after a partial fill, even if a future
                # price no longer crosses the original stop or target trigger.
                continue
            trigger=quote.bid if held.quantity>0 else quote.ask
            manager.check_exit(float(trigger))
            if manager.has_open_position:
                held=self.execution.portfolio.positions[symbol]
                closing_fee=self.execution.fees.fee(abs(held.quantity),trigger)
                setup_loss=max(Decimal(0),self.setup_baseline_cash[symbol]-self.execution.portfolio.cash-
                               held.quantity*(trigger-held.entry_price)+closing_fee)
                limit=self.reserved_setup_risk.get(symbol)
                current=self.execution.portfolio.snapshot(active,now)
                if current.equity<=current.maintenance_margin_estimate*self.risk.policy.maintenance_buffer_multiple:
                    self._close(symbol,'Paper Margin Emergency')
                elif limit is not None and setup_loss>=limit:
                    self._close(symbol,'Capital Protection Emergency')
        return self._performance(self.execution.portfolio.snapshot(self.quotes,now))

    def consume_scan(self,scan):
        require_paper_migration()
        verify_strategy_freeze()
        self.market.client.startup()
        self.execution.refresh_specs(self.market.client.markets)
        self.latest_scan=scan
        self.audit_scan(scan)
        held=list(self.execution.portfolio.positions)
        self.observe({s:self.market.get_quote(s) for s in held})
        for d in scan.diagnostics:
            self.observe_completed_candles({d.symbol:d.candles})
            manager=self._manager(d.symbol)
            if d.signal:
                manager.update_daily_bias(d.signal['bias'])
        for symbol in scan.watchlist:
            d=next(d for d in scan.diagnostics if d.symbol==symbol)
            signal=d.signal
            if not signal or not (signal['long'] or signal['short']):
                continue
            signal_key=(symbol,signal['timestamp_ms'])
            if signal_key in self.last_signals:
                self._record('ENTRY_REJECTED',symbol=symbol,reason='DUPLICATE_SIGNAL_ALREADY_PROCESSED')
                continue
            self.last_signals[signal_key]=True
            now=self.clock_ms()
            if not 60000<=now-signal['timestamp_ms']<=60000+self.risk.policy.max_candle_age_ms:
                self._record('ENTRY_REJECTED',symbol=symbol,reason='SIGNAL_STALE_OR_OPEN')
                continue
            if signal['long'] and signal['short']:
                self._record('ENTRY_REJECTED',symbol=symbol,reason='AMBIGUOUS_DIRECTION')
                continue
            side='BUY' if signal['long'] else 'SELL'
            manager=self._manager(symbol)
            self.funnel.permission_observation(self.candidate_ids.get(symbol),manager,side)
            if not manager.permits(side):
                self._record('ENTRY_REJECTED',symbol=symbol,reason='BASELINE_BIAS_OR_COOLDOWN')
                continue
            if self.accounting_halt:
                self.breakers.pause('accounting',self.accounting_halt)
            blocked=self.breakers.entry_reasons(symbol)
            if blocked:
                self._record('ENTRY_REJECTED',symbol=symbol,reason=blocked[0],reasons=blocked)
                continue
            if manager.has_open_position and manager._open_position['side']!=side:
                quote=self.market.get_quote(symbol)
                self.quotes[symbol]=quote
                self._close(symbol,'Direction Flip')
                if manager.has_open_position:
                    self._record('ENTRY_REJECTED',symbol=symbol,reason='DIRECTION_FLIP_EXIT_INCOMPLETE')
                    continue
            if self.accounting_halt:
                self._record('ENTRY_REJECTED',symbol=symbol,reason=self.accounting_halt)
                continue
            if self.pending_exit_reasons:
                self._record('ENTRY_REJECTED',symbol=symbol,reason='EXIT_RECONCILIATION_PENDING')
                continue
            quote=self.market.get_quote(symbol)
            self.quotes[symbol]=quote
            self._fresh_marks()
            self.execution.quotes.update(self.quotes)
            snapshot=self.execution.portfolio.snapshot(self.quotes,self.clock_ms())
            decision=self.risk.assess(self.market.client.market(symbol),side,signal['reference'],
                signal['atr'],quote,self.execution.portfolio,self.quotes,self.clock_ms(),
                daily_loss=max(Decimal(0),self._day_start_equity-snapshot.equity),
                daily_setups=self._daily_setups)
            self._record('RISK_DECISION',symbol=symbol,side=side,decision=asdict(decision),audit=getattr(self.risk,'last_audit',{}))
            if not decision.allowed:
                continue
            self.execution.candidate_id=self.candidate_ids.get(symbol)
            self._record('EXECUTION_DECISION',symbol=symbol,execution_status='LOCAL_PAPER_SUBMIT',
                exchange_submission=False,quote=asdict(quote),quantity=decision.quantity)
            request=OrderRequest(symbol,side,decision.quantity,quote.ask if side=='BUY' else quote.bid,
                tif='Ioc',strategy_id=str(signal.get('signal_type') or 'VWAP_BASELINE'),
                client_order_id=symbol+':'+str(signal['timestamp_ms']))
            order=None
            setup_cash=self.execution.portfolio.cash
            try:
                self.funnel.event('ENTRY_ORDER_ATTEMPTED',self.candidate_ids.get(symbol),{},now)
                order=self.execution.submit(request)
                fill=self.execution.simulate_fill(order.order_id,quote)
                self.breakers.order_result(True)
                if fill:
                    self.position_candidates[symbol]=self.candidate_ids.get(symbol)
                    manager.confirm_entry(fill,decision)
                    self.reserved_setup_risk[symbol]=decision.economics.stop_risk*fill.quantity/decision.quantity
                    self.setup_baseline_cash[symbol]=setup_cash
                    self._daily_setups+=1
                    self._record('ENTRY_FILL',symbol=symbol,fill=asdict(fill))
                else:
                    self._record('ENTRY_UNFILLED',symbol=symbol,order_id=order.order_id,status=self.execution.orders[order.order_id].status)
            except ExchangeError as exc:
                self.breakers.order_result(False)
                if order is not None:
                    self.execution.cancel_order(symbol,order.order_id)
                self._record('ENTRY_REJECTED',symbol=symbol,reason=str(exc))
        self._fresh_marks()
        return self._performance(self.execution.portfolio.snapshot(self.quotes,self.clock_ms()))

    def cycle(self):
        return self.consume_scan(self.scanner.scan())

    def observe_completed_candles(self,histories):
        """Advance frozen close-stop/cooldown state between periodic scans.

        The caller supplies healthy feed history and refreshes held quotes first.
        Completed bars trigger management; fills still use the current BBO.
        """
        require_paper_migration()
        verify_strategy_freeze()
        for symbol,candles in histories.items():
            manager=self._manager(symbol)
            bars=[c for c in candles if manager.last_candle_ms is None or c.timestamp_ms>manager.last_candle_ms]
            if manager.last_candle_ms is None:
                bars=bars[-1:]
            for bar in bars:
                try:
                    manager.completed_candle(bar)
                except ExchangeError as exc:
                    if str(exc)=='STRATEGY_STATE_CANDLE_GAP' and not manager.has_open_position:
                        manager.recover_idle_cursor(bar)
                        self._record('IDLE_FEED_CURSOR_RECOVERED',symbol=symbol,reason=str(exc))
                    else:
                        self.accounting_halt=str(exc)
                        self.breakers.pause('accounting',self.accounting_halt)
                        self._record('STATE_DATA_HALT',symbol=symbol,reason=str(exc))
                        break

    def report(self):
        self._fresh_marks()
        snapshot=self.execution.portfolio.snapshot(self.quotes,self.clock_ms())
        self._performance(snapshot)
        scan=self.latest_scan
        return dict(execution_mode=self.execution.execution_mode,readiness=readiness(self.team_address,market_ready=self.market.client.ready),allow_live_orders=False,exchange_orders_submitted=0,
            balance_origin='HYPOTHETICAL_LOCAL_USDPR',starting_collateral=self.execution.portfolio.starting_collateral,
            portfolio=asdict(snapshot),positions=[asdict(p) for p in self.execution.portfolio.positions.values()],
            scan_status=scan.status if scan else 'NOT_SCANNED',watchlist=scan.watchlist if scan else [],
            scanned_markets=len(scan.diagnostics) if scan else 0,
            diagnostics=[dict(symbol=d.symbol,qualified=d.qualified,reasons=d.reasons,metrics=d.metrics,
                              score=d.score,signal=d.signal,market_snapshot=asdict(d.snapshot) if d.snapshot else None)
                         for d in scan.diagnostics] if scan else [],
            local_orders=len(self.execution.orders),local_fills=len(self.execution.fills),
            decisions=self.decisions,accounting_halt=self.accounting_halt,
            pending_exits=self.pending_exit_reasons,
            closed_trades=self.closed_trades,
            performance=dict(return_fraction=(snapshot.equity-self.execution.portfolio.starting_collateral)/
                self.execution.portfolio.starting_collateral,max_drawdown_fraction=self.max_drawdown_fraction,
                closed_trade_count=len(self.closed_trades),win_rate=(Decimal(sum(t['net_pnl']>0 for t in self.closed_trades))/
                    len(self.closed_trades) if self.closed_trades else None)),
            strategy_freeze=verify_strategy_freeze(),fees=asdict(self.execution.fees),
            risk_policy=asdict(self.risk.policy),scanner_policy=asdict(self.scanner.policy),
            market_specs=[asdict(s) for s in self.execution.specs.values()],
            exposure=ExposureManager.metrics(snapshot,self.execution.portfolio,self.quotes),
            risk_state=self.breakers.report(self.clock_ms()),feed_health=self.feed_health,
            public_stream=self.stream_report,paper_account_recovery=self.reconciler.last_report,
            market_snapshots={s:asdict(value) for s,value in self.market_snapshots.items()},
            exchange_account_observer=self.exchange_account_report,
            strategy_state={s:dict(position=m._open_position,daily_bias=m.daily_bias,
                candles_held=m.candles_held,candles_since_last_sl=m.candles_since_last_sl,
                last_completed_candle_ms=m.last_candle_ms) for s,m in self.managers.items()})
