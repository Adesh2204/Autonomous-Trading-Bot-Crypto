"""Feed supervision and a main-thread account barrier after every reconnect."""
import queue
from exchange.event_timing import timing

from exchange.base_exchange import ExchangeError


class MarketStream:
    def __init__(self,engine,policy,*,account_recovery=None):
        self.engine=engine
        self.policy=policy
        self.accepted_generation=None
        self.recovery=None
        self.events=[]
        self.account_recovery=account_recovery
        self.next_recovery_ms=0
        self.last_account_recovery_ms=None
        self._pending=queue.Queue()
        engine.on_lifecycle=self._pending.put

    def run(self,stop):
        return self.engine.run(stop,max_reconnects=self.policy.max_reconnect_failures-1)

    def health(self,now_ms):
        if hasattr(self.engine,'market_health'):
            return self.engine.market_health()
        result={}
        limits={'last_tick_time':self.policy.max_data_age_ms,
                'last_orderbook_time':self.policy.max_data_age_ms,
                'last_candle_time':self.policy.max_candle_age_ms,
                'last_mark_time':self.policy.max_mark_age_ms}
        for symbol in self.engine.symbols:
            clocks=self.engine.get_observations(symbol)
            reasons=[]
            ages={}
            for name,limit in limits.items():
                value=clocks[name]
                age=None if value is None else now_ms-value
                ages[name]=age
                if age is None or not 0<=age<=limit:
                    reasons.append(name.upper()+'_STALE')
            history=self.engine.get_completed_candles(symbol)
            if len(history)<self.engine.history_bars:reasons.append('INSUFFICIENT_HISTORY')
            repair_error=getattr(self.engine,'recovery_errors',{}).get(symbol)
            if repair_error:reasons.append('MARKET_REPAIR_FAILED:'+repair_error)
            result[symbol]=dict(healthy=not reasons,reasons=tuple(reasons),clocks=clocks,ages_ms=ages,
                data_state='HEALTHY' if not reasons else 'INSUFFICIENT_HISTORY' if 'INSUFFICIENT_HISTORY' in reasons else 'STALE_CANDLE' if 'LAST_CANDLE_TIME_STALE' in reasons else 'STALE_BOOK' if 'LAST_ORDERBOOK_TIME_STALE' in reasons else 'STALE_CONTEXT' if 'LAST_MARK_TIME_STALE' in reasons else 'UNKNOWN')
        return result

    def poll(self,bot):
        """Called only by the ledger owner. Worker callbacks enqueue facts."""
        while not self._pending.empty():
            event=self._pending.get_nowait()
            self.events.append(event)
            if event['phase'] in {'CONNECTING','SUBSCRIBED','DISCONNECTED'}:
                bot.breakers.pause('stream','STREAM_RECOVERY_REQUIRED')
        bot.breakers.update_reconnects(self.engine.consecutive_failures)
        if not self.engine.connected or not self.engine.reconciled:
            bot.breakers.pause('stream','STREAM_NOT_HEALTHY')
        elif self.accepted_generation!=self.engine.recovery_generation or self.account_recovery is not None and (
                self.last_account_recovery_ms is None or bot.clock_ms()-self.last_account_recovery_ms>=60000):
            generation=self.engine.recovery_generation
            bot.breakers.pause('account','REST_ACCOUNT_RECONCILIATION_REQUIRED')
            if bot.clock_ms()<self.next_recovery_ms:
                return False
            try:
                self.recovery=bot.reconcile_paper_state()
                if self.recovery['entries_paused']:
                    raise ExchangeError('PAPER_ACCOUNT_RECONCILIATION_FAILED')
                if self.account_recovery is not None:
                    bot.exchange_account_report=self.account_recovery()
                    if bot.exchange_account_report['entries_paused']:
                        raise ExchangeError('EXCHANGE_ACCOUNT_RECONCILIATION_FAILED')
                self.engine.acknowledge_recovery(generation)
                self.accepted_generation=generation
                self.last_account_recovery_ms=bot.clock_ms()
                bot.breakers.clear('account')
                bot.breakers.clear('stream')
                self.events.append(dict(phase='PAPER_ACCOUNT_RECONCILED',generation=generation,
                                        timestamp_ms=bot.clock_ms(),source=self.recovery['source'],**timing(bot.clock_ms())))
            except ExchangeError as exc:
                bot.breakers.pause('account',str(exc))
                self.next_recovery_ms=bot.clock_ms()+5000
        health=self.health(bot.clock_ms())
        snapshots={}
        for symbol,status in health.items():
            if status['healthy'] and self.engine.connected and self.engine.reconciled:
                try:
                    snapshots[symbol]=self.engine.get_snapshot(symbol)
                except ExchangeError as exc:
                    status['healthy']=False
                    status['reasons']+= (str(exc),)
        bot.market_snapshots=snapshots
        bot.breakers.update_symbols(health)
        bot.feed_health=health
        bot.stream_report=dict(connected=self.engine.connected,reconciled=self.engine.reconciled,
            generation=self.engine.recovery_generation,accepted_generation=self.accepted_generation,
            messages=self.engine.messages,reconnections=self.engine.reconnections,
            last_receive_ms=self.engine.last_receive_ms,last_error=self.engine.last_error,
            account_recovery=self.recovery,last_account_recovery_ms=self.last_account_recovery_ms,events=self.events,
            transport=self.engine.transport_health.report(),recovery_status=self.engine.recovery_status,
            public_rate_budget=self.engine.rates.report() if self.engine.rates is not None else None,
            market_health=self.engine.health_manager.report() if hasattr(self.engine,'health_manager') else None,
            feed_ready=bool(self.accepted_generation==self.engine.recovery_generation and
                self.recovery and not self.recovery['entries_paused'] and
                self.engine.connected and self.engine.reconciled and any(s['healthy'] for s in health.values())),
            trade_ready=False)
        return self.accepted_generation==self.engine.recovery_generation and self.engine.connected and self.engine.reconciled
