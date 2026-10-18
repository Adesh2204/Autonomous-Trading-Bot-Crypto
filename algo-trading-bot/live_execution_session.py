"""Future live owner loop using the existing scanner, risk and frozen managers."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from crypto_strategy_state import CryptoStrategyState
from exchange.base_exchange import ExchangeError
from exchange.exchange_rules import RiskPermission
from exchange.live_portfolio import ExchangePortfolioView
from exchange.order_lifecycle import OrderRequest, OrderState
from risk.circuit_breakers import CircuitBreakers
from strategy_freeze import verify_strategy_freeze


class LiveExecutionSession:
    def __init__(self, market, scanner, execution, risk):
        verify_strategy_freeze()
        execution._dependencies()
        self.market=market
        self.scanner=scanner
        self.execution=execution
        self.risk=risk
        self.recovery=execution.recovery
        self.recovery.position_guard=execution.position_guard
        self.journal=execution.journal
        self.clock_ms=market.client.clock_ms
        self.managers=self.recovery.managers
        self.quotes={}
        self.breakers=CircuitBreakers(risk.policy)
        self.account_stream=None
        self.pending_entries={}
        self.exit_reasons={}
        self.position_candidates={}
        self.direction_flip_intents={}
        self.processed_fill_ids=set()
        self.latest_scan=None
        self.portfolio=None
        self.starting_equity=None
        self.daily_setups=0
        self.day=None
        self.day_start_equity=None
        self.peak_equity=None
        self.max_drawdown=Decimal(0)
        self._restore_controls()
        from opportunity_funnel import OpportunityFunnel
        from exchange.sdk_transport import OfflineSDKTransport
        self.funnel=OpportunityFunnel(journal=self.journal,source='OFFLINE_SIGNED_FIXTURE' if type(execution.transport) is OfflineSDKTransport else 'EXCHANGE_REPORTED_RUNTIME')
        self.scanner.diagnostic_sink=self.funnel
        self.recovery.owner=self
        for symbol,record in self.recovery.saved_management.items():
            manager=self._manager(symbol)
            try:
                self.recovery.restore_manager(manager)
            except Exception:
                self.recovery.checkpoint_error='INVALID_MANAGEMENT_HISTORY'
                self.managers.pop(symbol,None)
                continue
            if record.get('pending_entry'):
                self.pending_entries[symbol]=record['pending_entry']
            if record.get('exit_reason'):
                self.exit_reasons[symbol]=record['exit_reason']
            if record.get('candidate_id'):
                self.position_candidates[symbol]=record['candidate_id']
            if record.get('direction_flip_intent'):
                self.direction_flip_intents[symbol]=record['direction_flip_intent']
            self.processed_fill_ids.update(tuple(x) for x in record.get('processed_fill_ids',[]))
        self.recovery.on_truth=self._consume_actual_fills
        from exchange.startup_recovery import StartupRecovery
        self.startup_recovery=StartupRecovery(self)

    def _restore_controls(self):
        import json
        snapshot=self.recovery.saved_snapshot
        data=snapshot.get('risk_state') if snapshot else None
        data=data or self.journal.control('live_risk_state')
        if data:
            self.daily_setups=data['daily_setups']
            self.day=data['day']
            self.day_start_equity=Decimal(data['day_start_equity'])
            self.peak_equity=Decimal(data['peak_equity'])
            self.max_drawdown=Decimal(data['max_drawdown'])
            self.starting_equity=Decimal(data.get('starting_equity',data['day_start_equity']))

    def risk_checkpoint_data(self):
        if self.day is None or self.day_start_equity is None:
            return None
        return dict(day=self.day,daily_setups=self.daily_setups,
            day_start_equity=self.day_start_equity,peak_equity=self.peak_equity,
            max_drawdown=self.max_drawdown,starting_equity=self.starting_equity)

    def _save_controls(self):
        from exchange.execution_journal import canonical
        if self.day is not None:
            with self.journal.transaction():
                self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                    ('live_risk_state',canonical(dict(day=self.day,daily_setups=self.daily_setups,
                        day_start_equity=self.day_start_equity,peak_equity=self.peak_equity,
                        max_drawdown=self.max_drawdown,starting_equity=self.starting_equity))))

    def _manager(self, symbol):
        if symbol not in self.managers:
            self.managers[symbol]=CryptoStrategyState(symbol,self._close,clock_ms=self.clock_ms)
        return self.managers[symbol]

    def _persist(self, symbol):
        self.recovery.persist_manager(self._manager(symbol),pending_entry=self.pending_entries.get(symbol),
            exit_reason=self.exit_reasons.get(symbol),candidate_id=self.position_candidates.get(symbol),
            direction_flip_intent=self.direction_flip_intents.get(symbol),
            processed_fill_ids=[list(x) for x in self.processed_fill_ids if x[0]==symbol])

    def _consume_actual_fills(self, state):
        intents={str(row['oid']):row for row in self.journal.intents() if row['oid'] is not None}
        import json
        intents.update((str(oid),row) for row in self.journal.intents()
                       for oid in json.loads(row['outcome'] or '{}').get('child_order_ids',[]))
        for fill in sorted(state.fills.values(),key=lambda f:f.identity):
            if fill.identity in self.processed_fill_ids:
                continue
            intent=intents.get(fill.order_id)
            if intent is None:
                # Unknown/manual fills remain account truth; never attribute them
                # to a strategy setup or invent its management geometry.
                continue
            import json
            request=OrderRequest(**json.loads(intent['request']))
            if request.symbol!=fill.symbol or request.side!=fill.side:
                raise ExchangeError('STRATEGY_FILL_LINK_CONFLICT')
            manager=self._manager(fill.symbol)
            if request.reduce_only:
                reason=('Catastrophic Protection' if request.strategy_id=='CATASTROPHIC_STOP'
                        else self.exit_reasons.get(fill.symbol))
                if not reason or not manager.has_open_position:
                    raise ExchangeError('EXIT_MANAGEMENT_EVIDENCE_MISSING')
                manager.confirm_exit(fill,reason)
                if not manager.has_open_position:
                    self.exit_reasons.pop(fill.symbol,None)
                    self.position_candidates.pop(fill.symbol,None)
            else:
                entry=self.pending_entries.get(fill.symbol)
                if entry is None or entry['candidate_id']!=intent['candidate']:
                    raise ExchangeError('ENTRY_MANAGEMENT_EVIDENCE_MISSING')
                decision=SimpleNamespace(stop=Decimal(entry['stop']),target=Decimal(entry['target']))
                if not manager.has_open_position:
                    manager.confirm_entry(fill,decision)
                    self.daily_setups+=1
                else:
                    # Multiple exchange executions belonging to the SAME entry
                    # are one baseline tranche, not additional strategy entries.
                    if self.position_candidates.get(fill.symbol)!=intent['candidate'] or manager._open_position['side']!=fill.side:
                        raise ExchangeError('UNEXPECTED_ADDITIONAL_ENTRY')
                    position=manager._open_position
                    total=position['quantity']+fill.quantity
                    average=(Decimal(str(position['average_entry_price']))*position['quantity']+fill.price*fill.quantity)/total
                    position['quantity']=total
                    position['average_entry_price']=float(average)
                    position['tranches']=[dict(entry_price=float(average))]
                self.position_candidates[fill.symbol]=intent['candidate']
                self.direction_flip_intents.pop(fill.symbol,None)
            self.processed_fill_ids.add(fill.identity)
            self.funnel.event('TRADE_PNL' if request.reduce_only and not manager.has_open_position else
                'ENTRY_FILL' if not request.reduce_only else 'PARTIAL_EXIT',intent['candidate'],{},self.clock_ms())
            from exchange.sdk_transport import OfflineSDKTransport
            synthetic=type(self.execution.transport) is OfflineSDKTransport
            self.journal.event('STRATEGY_ACTUAL_FILL',self.clock_ms(),candidate_id=intent['candidate'],
                symbol=fill.symbol,fill=asdict(fill),
                execution_mode='OFFLINE_SIGNED_FIXTURE' if synthetic else 'LIVE_TESTNET',
                source='SYNTHETIC_SIGNED_FIXTURE' if synthetic else 'EXCHANGE_REPORTED')
            self._persist(fill.symbol)
        self._save_controls()

    def startup(self):
        self.execution.entries_paused=True
        if self.execution.protection is not None:
            self.execution.protection.managers=self.managers
            self.execution.protection.ensure_all(allow_actions=False)
        report=self.startup_recovery.reconcile()
        eq=self.recovery.state.equity
        if eq is not None:
            if self.starting_equity is None:
                self.starting_equity=eq.reported_account_value
            if self.day_start_equity is None:
                self.day_start_equity=eq.reported_account_value
                self.day=datetime.fromtimestamp(self.clock_ms()/1000,timezone.utc).date().isoformat()
                self.peak_equity=eq.reported_account_value
            self.portfolio=ExchangePortfolioView(self.recovery,self.market.client.markets,self.starting_equity)
            self._save_controls()
        # Stream acknowledgment + reconciliation is also required before entry.
        # Fixture streams have no subscribe protocol. Production streams must
        # use after_stream only after real acknowledgements.
        if self.account_stream is not None and self.account_stream.healthy and not hasattr(self.account_stream,'generation'):
            self.startup_recovery.after_stream(0)
        self.execution.entries_paused=self.startup_recovery.state.value!='READY'
        self._protection_barrier(allow_actions=report.ready)
        return report

    def _protection_barrier(self,*,allow_actions=True):
        if allow_actions and (not self.execution.clock_health.healthy or not self.execution.rate_limits.healthy):
            from exchange.live_readiness import verify_live_account_readiness
            sent=self.clock_ms()
            # A fresh REST book supplies an exchange timestamp; cached market
            # timestamps are never presented as a new clock observation.
            from exchange.hyperliquid_market_data import HyperliquidMarketData
            book=HyperliquidMarketData(self.market.client).get_orderbook(self.market.client.api_market)
            self.execution.clock_health.observe(book.timestamp_ms,sent,self.clock_ms())
            readiness=verify_live_account_readiness(self.recovery.account,self.execution.transport.signer_address,
                clock_health=self.execution.clock_health,rate_limits=self.execution.rate_limits,
                reconciliation_ready=self.recovery.last_report.ready)
            if not readiness.account_ready:
                self.execution.entries_paused=True
        protection=self.execution.protection
        if protection is not None:
            protection.managers=self.managers
            if not protection.healthy:
                protection.ensure_all(allow_actions=allow_actions)
            self.execution.entries_paused |= not protection.entries_allowed
        self.breakers.update_reliability(self.execution)

    def attach_account_stream(self, stream):
        if stream.executor is not self.execution:
            raise ExchangeError('ACCOUNT_STREAM_EXECUTOR_MISMATCH')
        self.account_stream=stream

    def _account_barrier(self):
        if self.startup_recovery.state.value=='RECOVERY_REQUIRED':
            self.startup()
        if self.account_stream is None or not self.account_stream.healthy:
            self.execution.entries_paused=True
            raise ExchangeError('ACCOUNT_STREAM_NOT_READY')
        now=self.clock_ms()
        window=self.recovery.state.last_window
        # Trusted acknowledged account stream with a recent stable checkpoint
        # avoids downloading the same fills/history for every scanned symbol.
        report=(self.recovery.last_report if self.recovery.last_report.ready and window is not None and
                0<=now-window[1]<=self.execution.rate_limits.policy.budget_max_age_ms else self.recovery.recover())
        self.execution.entries_paused=not report.ready
        self.execution.entries_paused |= self.startup_recovery.state.value!='READY'
        self._protection_barrier(allow_actions=report.ready)
        if not report.ready:
            raise ExchangeError('ACCOUNT_RECONCILIATION_NOT_READY')
        if self.startup_recovery.state.value!='READY':
            raise ExchangeError('STARTUP_ENTRY_LOCK_REQUIRED')

    def _performance(self, snapshot):
        day=datetime.fromtimestamp(self.clock_ms()/1000,timezone.utc).date().isoformat()
        if day!=self.day:
            self.day=day
            self.daily_setups=0
            self.day_start_equity=snapshot.equity
        self.peak_equity=max(self.peak_equity,snapshot.equity)
        self.max_drawdown=max(self.max_drawdown,(self.peak_equity-snapshot.equity)/self.peak_equity)
        self.breakers.evaluate(snapshot,daily_loss=max(Decimal(0),self.day_start_equity-snapshot.equity),
            drawdown=self.max_drawdown,daily_loss_limit=self.portfolio.starting_collateral*self.risk.policy.max_daily_loss_fraction)
        self._save_controls()

    def _close(self, symbol, reason):
        held=self.recovery.account.get_position(symbol)
        if held is None:
            return None
        manager=self._manager(symbol)
        if not manager.has_open_position:
            raise ExchangeError('MANUAL_REVIEW_REQUIRED:MISSING_MANAGEMENT_HISTORY')
        quote=self.market.get_quote(symbol)
        side='SELL' if held.quantity>0 else 'BUY'
        price=quote.bid if side=='SELL' else quote.ask
        candidate=self.position_candidates.get(symbol)
        if not candidate:
            raise ExchangeError('EXIT_CANDIDATE_LINK_REQUIRED')
        self.exit_reasons[symbol]=reason
        self._persist(symbol)
        permission=RiskPermission(candidate,symbol,side,abs(held.quantity),self.clock_ms(),
                                  True,reason,price)
        from exchange.compliance_guard import OrderProvenance
        permission=replace(permission,provenance=OrderProvenance(candidate,'VWAP_BASELINE_EXIT',
            'POSITION_MANAGEMENT',self.clock_ms(),symbol,side,reason,
            dict(allowed=True,reduce_only=True,actual_quantity=str(held.quantity)),
            dict(allowed=True,price=str(price),quantity=str(abs(held.quantity))),
            classification='STRATEGY_EXIT',source_position_id=candidate))
        # A fresh close attempt is permitted only after the prior attempt is
        # terminal and remaining exposure has been authoritatively reconciled.
        prior=[r for r in self.journal.intents() if r['candidate']==candidate and
               OrderRequest(**__import__('json').loads(r['request'])).reduce_only and
               OrderRequest(**__import__('json').loads(r['request'])).strategy_id!='CATASTROPHIC_STOP']
        if prior and prior[-1]['state'] in {'UNKNOWN','SUBMITTED','PREPARED','OPEN'}:
            self.execution.entries_paused=True
            raise ExchangeError('EXIT_ORDER_RECOVERY_REQUIRED')
        key=candidate+':exit:'+str(len(prior))
        result=self.execution.close_position(symbol,permission=permission,price=price,client_order_id=key)
        self._persist(symbol)
        self._protection_barrier(allow_actions=self.recovery.last_report.ready)
        return result

    def observe(self, quotes):
        verify_strategy_freeze()
        self.quotes.update(quotes)
        # Management remains possible while entries are paused, but its signed
        # actions still require the full execution authorization/readiness gate.
        for symbol in list(self.recovery.state.positions):
            manager=self._manager(symbol)
            if not manager.has_open_position:
                continue
            quote=self.quotes.get(symbol)
            if quote is None or not 0<=self.clock_ms()-quote.timestamp_ms<=5000:
                self.execution.entries_paused=True
                continue
            manager._check_day_reset(datetime.fromtimestamp(self.clock_ms()/1000,timezone.utc))
            if symbol in self.exit_reasons:
                self._close(symbol,self.exit_reasons[symbol])
            else:
                held=self.recovery.state.positions[symbol]
                manager.check_exit(float(quote.bid if held.quantity>0 else quote.ask))
            self._persist(symbol)

    def observe_completed_candles(self, histories):
        verify_strategy_freeze()
        for symbol,candles in histories.items():
            manager=self._manager(symbol)
            bars=[c for c in candles if manager.last_candle_ms is None or c.timestamp_ms>manager.last_candle_ms]
            if manager.last_candle_ms is None:
                bars=bars[-1:]
            for candle in bars:
                try:
                    manager.completed_candle(candle)
                except ExchangeError as exc:
                    if str(exc)=='STRATEGY_STATE_CANDLE_GAP' and not manager.has_open_position:
                        manager.recover_idle_cursor(candle)
                    else:
                        self.execution.entries_paused=True
                        self.breakers.pause('management_history','MANUAL_REVIEW_REQUIRED:CANDLE_GAP')
                        raise
                self._persist(symbol)

    def consume_scan(self, scan):
        verify_strategy_freeze()
        self.latest_scan=scan
        self.funnel.observe_scan(scan,getattr(self.scanner,'policy',None))
        try:
            self._account_barrier()
        except ExchangeError as exc:
            for d in scan.diagnostics:
                self.funnel.event('ENTRY_REJECTED',f'{d.symbol}:{scan.observed_at_ms}',dict(reason=str(exc)),self.clock_ms())
            raise
        self.observe({s:self.market.get_quote(s) for s in self.recovery.state.positions})
        for diagnostic in scan.diagnostics:
            self.journal.event('LIVE_SIGNAL',self.clock_ms(),candidate_id=f'{diagnostic.symbol}:{scan.observed_at_ms}',
                symbol=diagnostic.symbol,signal=diagnostic.signal,reasons=diagnostic.reasons,metrics=diagnostic.metrics)
            self.observe_completed_candles({diagnostic.symbol:diagnostic.candles})
            if diagnostic.signal:
                self._manager(diagnostic.symbol).update_daily_bias(diagnostic.signal['bias'])
                self._persist(diagnostic.symbol)
        for symbol in scan.watchlist:
            diagnostic=next(d for d in scan.diagnostics if d.symbol==symbol)
            signal=diagnostic.signal
            if not signal or not (signal['long'] or signal['short']):
                continue
            candidate=f'{symbol}:{scan.observed_at_ms}'
            key=symbol+':'+str(signal['timestamp_ms'])
            if self.journal.intent(key):
                self.funnel.event('ENTRY_REJECTED',candidate,dict(reason='DUPLICATE_SIGNAL_ALREADY_PROCESSED'),self.clock_ms())
                continue
            if signal['long'] and signal['short'] or not 60000<=self.clock_ms()-signal['timestamp_ms']<=60000+self.risk.policy.max_candle_age_ms:
                self.journal.event('ENTRY_REJECTED',self.clock_ms(),candidate_id=candidate,reason='AMBIGUOUS_OR_STALE_SIGNAL')
                self.funnel.event('ENTRY_REJECTED',candidate,dict(reason='AMBIGUOUS_OR_STALE_SIGNAL'),self.clock_ms())
                continue
            side='BUY' if signal['long'] else 'SELL'
            manager=self._manager(symbol)
            self.funnel.permission_observation(candidate,manager,side)
            if not manager.permits(side):
                continue
            if manager.has_open_position and manager._open_position['side']!=side:
                self.direction_flip_intents[symbol]=dict(candidate_id=candidate,from_side=manager._open_position['side'],
                    to_side=side,actual_flat_required=True)
                self._persist(symbol)
                self._close(symbol,'Direction Flip')
                if manager.has_open_position:
                    continue
                if self.execution.protection is not None and not self.execution.protection.flat_clear(symbol):
                    continue
            if self.exit_reasons or self.breakers.entry_reasons(symbol):
                reasons=self.breakers.entry_reasons(symbol)
                self.funnel.event('ENTRY_REJECTED',candidate,dict(reason=reasons[0] if reasons else 'EXIT_RECONCILIATION_PENDING'),self.clock_ms())
                continue
            self._account_barrier()
            quote=self.market.get_quote(symbol)
            self.quotes[symbol]=quote
            active=self.recovery.account._query('activeAssetData',coin=symbol)
            self.portfolio.observe_buying_power(active,self.clock_ms())
            snapshot=self.portfolio.snapshot(self.quotes,self.clock_ms())
            self._performance(snapshot)
            if self.breakers.entry_reasons(symbol):
                continue
            decision=self.risk.assess(self.market.client.market(symbol),side,signal['reference'],signal['atr'],
                quote,self.portfolio,self.quotes,self.clock_ms(),
                daily_loss=max(Decimal(0),self.day_start_equity-snapshot.equity),daily_setups=self.daily_setups)
            self.journal.event('LIVE_RISK_DECISION',self.clock_ms(),candidate_id=candidate,decision=asdict(decision))
            self.funnel.event('LIVE_RISK_DECISION',candidate,dict(decision=asdict(decision),audit=getattr(self.risk,'last_audit',{})),self.clock_ms())
            if not decision.allowed:
                continue
            request=OrderRequest(symbol,side,decision.quantity,quote.ask if side=='BUY' else quote.bid,
                tif='Ioc',strategy_id=str(signal.get('signal_type') or 'VWAP_BASELINE'),client_order_id=key)
            permission=RiskPermission.from_decision(decision,request,candidate,self.clock_ms(),
                signal_timestamp_ms=signal['timestamp_ms'],setup_type=signal.get('signal_type'))
            self.pending_entries[symbol]=dict(candidate_id=candidate,stop=str(decision.stop),target=str(decision.target),
                setup_type=str(signal.get('signal_type') or 'VWAP_BASELINE'),reference_vwap=str(signal['reference']),
                atr=str(signal['atr']),signal_timestamp_ms=signal['timestamp_ms'])
            self._persist(symbol)
            try:
                self.funnel.event('EXECUTION_DECISION',candidate,{},self.clock_ms())
                self.funnel.event('ENTRY_ORDER_ATTEMPTED',candidate,{},self.clock_ms())
                result=self.execution.submit(request,permission=permission)
                self.breakers.order_result(result.state not in {OrderState.UNKNOWN,OrderState.REJECTED})
            except ExchangeError as exc:
                self.breakers.order_result(False)
                self.journal.event('ENTRY_REJECTED',self.clock_ms(),candidate_id=candidate,reason=str(exc))
                self.funnel.event('ENTRY_REJECTED',candidate,dict(reason=str(exc)),self.clock_ms())
            self._persist(symbol)

    def cycle(self, *, scan=True):
        if self.account_stream is not None:
            if getattr(self.account_stream,'background_receiving',False):
                if self.account_stream.receiver_fatal:
                    raise ExchangeError('ACCOUNT_RECEIVER_FATAL_REQUIRES_OPERATOR')
            else:
                if not self.account_stream.connected:
                    self.account_stream.connect()
                self.account_stream.poll()
            if self.account_stream.pending:
                self.account_stream.reconcile()
        if scan:
            return self.consume_scan(self.scanner.scan())
        self._account_barrier()
        self.observe({s:self.market.get_quote(s) for s in self.recovery.state.positions})
        engine=getattr(self.market,'engine',None)
        if engine is not None and engine.connected and engine.reconciled:
            histories={s:engine.get_completed_candles(s) for s in self.managers}
            now=self.clock_ms()
            self.observe_completed_candles({s:bars for s,bars in histories.items()
                if bars and 0<=now-(bars[-1].timestamp_ms+60000)<=self.risk.policy.max_candle_age_ms})
        if self.portfolio is not None:
            now=self.clock_ms()
            if self.portfolio.account_observed_ms is None or now-self.portfolio.account_observed_ms>=3000:
                symbol=next(iter(self.recovery.state.positions),'par:BTC')
                from exchange.reliability_policy import RequestPriority
                active=self.recovery.account._query('activeAssetData',coin=symbol,priority=RequestPriority.SAFETY)
                self.portfolio.observe_buying_power(active,self.clock_ms())
            self._performance(self.portfolio.snapshot(self.quotes,self.clock_ms()))
