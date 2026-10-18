"""One startup/reconnect barrier over the existing authoritative reconciler.

Historical candles explain management transitions; they never manufacture fills.
"""
from copy import deepcopy
from dataclasses import asdict
from enum import Enum
import json
from pathlib import Path
import uuid

from .base_exchange import ExchangeError
from .execution_journal import safe_data,fingerprint
from .base_exchange import decimal


class StartupState(str, Enum):
    BOOTING='BOOTING'
    ACCOUNT_NOT_CONFIGURED='ACCOUNT_NOT_CONFIGURED'
    READ_ONLY_READY='READ_ONLY_READY'
    RECOVERY_REQUIRED='RECOVERY_REQUIRED'
    RECOVERING='RECOVERING'
    RECONCILING='RECONCILING'
    POSITION_REVIEW='POSITION_REVIEW'
    ENTRY_PAUSED='ENTRY_PAUSED'
    READY='READY'
    FAILED_SAFE='FAILED_SAFE'


class StartupRecovery:
    def __init__(self, session):
        self.session=session
        self.recovery=session.recovery
        self.journal=session.journal
        self.clock=session.clock_ms
        prior=self.journal.control('recovery_lifecycle')
        self.previous_shutdown=('CLEAN' if prior['clean'] else 'UNCLEAN') if prior else 'UNKNOWN'
        self.run_id=uuid.uuid4().hex
        self.state=StartupState.BOOTING
        self.before_stream_verified=False
        self.post_stream_verified=False
        self.stream_generation=None
        self.downtime={}
        self.reasons=['STARTUP_RECOVERY_REQUIRED']
        self.local_positions={s:r['position'] for s,r in self.recovery.saved_management.items() if r.get('position')}
        self.fill_count=len(self.recovery.state.fills)
        self.funding_count=len(self.recovery.state.funding)
        self.transition(StartupState.RECOVERY_REQUIRED,'PREVIOUS_'+self.previous_shutdown+'_SHUTDOWN')
        self.recovery.startup_coordinator=self

    def transition(self, state, *reasons):
        self.state=StartupState(state)
        self.reasons=list(dict.fromkeys(reasons))
        if self.state!=StartupState.READY:
            self.session.execution.entries_paused=True
        lifecycle=dict(run_id=self.run_id,session_id=self.journal.session_id,state=self.state.value,
            clean=False,started_ms=getattr(self,'started_ms',self.clock()),updated_ms=self.clock(),
            previous_shutdown=self.previous_shutdown,reasons=self.reasons)
        self.started_ms=lifecycle['started_ms']
        self.journal.control('recovery_lifecycle',lifecycle)
        self.journal.event('STARTUP_STATE',self.clock(),**lifecycle)

    def _account_verification(self):
        from .live_readiness import verify_live_account_readiness
        from .hyperliquid_market_data import HyperliquidMarketData
        ex=self.session.execution
        sent=self.clock()
        book=HyperliquidMarketData(self.session.market.client).get_orderbook(self.session.market.client.api_market)
        ex.clock_health.observe(book.timestamp_ms,sent,self.clock())
        result=verify_live_account_readiness(self.recovery.account,ex.transport.signer_address,
            clock_health=ex.clock_health,rate_limits=ex.rate_limits,
            reconciliation_ready=self.recovery.last_report.ready)
        self.account_verified=result.account_ready
        return list(result.reasons) if not result.account_ready else []

    def _review_downtime(self):
        from crypto_strategy_state import CryptoStrategyState
        expected=self.clock()//60000*60000-60000
        reasons=[]
        for symbol in self.recovery.state.positions:
            manager=self.session.managers.get(symbol)
            if manager is None or not manager.has_open_position:
                reasons.append('MISSING_MANAGEMENT_HISTORY:'+symbol)
                continue
            cursor=manager.last_candle_ms
            if cursor is None:
                reasons.append('HELD_CANDLE_CURSOR_UNKNOWN:'+symbol)
                self.downtime[symbol]=dict(status='REVIEW',reason='CURSOR_UNKNOWN')
                continue
            if cursor>expected:
                reasons.append('HELD_CANDLE_CURSOR_IN_FUTURE:'+symbol)
                continue
            if cursor==expected:
                self.downtime[symbol]=dict(status='VERIFIED',missing_bars=0)
                continue
            try:
                bars=self.session.market.get_candles(symbol,cursor+60000,expected+59999,now_ms=self.clock())
                wanted=list(range(cursor+60000,expected+1,60000))
                if [b.timestamp_ms for b in bars]!=wanted or any(b.timestamp_ms+60000>self.clock() for b in bars):
                    raise ExchangeError('EXPOSED_CANDLE_HISTORY_INCOMPLETE')
                exits=[]
                shadow=CryptoStrategyState(symbol,lambda s,r:exits.append(r),clock_ms=self.clock)
                # Read-only copy of verified state, executing the SAME frozen
                # management methods with an inert exit observer.
                for name in ('_open_position','_state','daily_bias','candles_held',
                             'candles_since_last_sl','entry_atr','last_candle_ms','_day'):
                    setattr(shadow,name,deepcopy(getattr(manager,name)))
                target=shadow._open_position['target_price']
                side=shadow._open_position['side']
                target_touch=False
                for bar in bars:
                    target_touch |= (float(bar.high)>=target if side=='BUY' else float(bar.low)<=target)
                    shadow.completed_candle(bar)
                findings=[]
                if exits: findings.append('NORMAL_STOP_CONDITION_DURING_DOWNTIME')
                if target_touch: findings.append('TARGET_TOUCH_REQUIRES_EXECUTABLE_PRICE_REVIEW')
                self.downtime[symbol]=dict(status='REVIEW' if findings else 'VERIFIED',
                    first_bar_ms=bars[0].timestamp_ms,last_bar_ms=bars[-1].timestamp_ms,
                    missing_bars=len(bars),findings=findings,exchange_fill_invented=False)
                if findings:
                    reasons.extend(r+':'+symbol for r in findings)
                else:
                    for name in ('_open_position','_state','daily_bias','candles_held',
                                 'candles_since_last_sl','entry_atr','last_candle_ms','_day'):
                        setattr(manager,name,deepcopy(getattr(shadow,name)))
                    self.session._persist(symbol)
            except Exception as exc:
                reason='EXPOSED_DOWNTIME_REVIEW_REQUIRED:'+symbol+':'+type(exc).__name__
                reasons.append(reason)
                self.downtime[symbol]=dict(status='REVIEW',reason=reason)
        return reasons

    def reconcile(self, *, post_stream=False, generation=None):
        self.transition(StartupState.RECOVERING,'AUTHORITATIVE_REST_REQUIRED')
        try:
            client=self.session.market.client
            client.startup()
            snapshot=self.recovery.saved_snapshot
            if snapshot and snapshot.get('metadata_hash') and snapshot['metadata_hash']!=fingerprint(client.metadata):
                raise ExchangeError('RECOVERY_MARKET_METADATA_CHANGED')
            self.transition(StartupState.RECONCILING,'REST_ACCOUNT_AND_MANAGEMENT')
            report=self.recovery.recover()
            reasons=list(report.reasons)
            reasons+=self._account_verification()
            reasons+=self._review_downtime()
            protection=self.session.execution.protection
            if protection is not None:
                protection.managers=self.session.managers
                protection.ensure_all(allow_actions=not reasons)
                if not protection.entries_allowed: reasons.append('PROTECTION_NOT_VERIFIED')
            else:
                from .sdk_transport import OfflineSDKTransport
                if type(self.session.execution.transport) is not OfflineSDKTransport:
                    reasons.append('PROTECTION_INFRASTRUCTURE_REQUIRED')
            if not post_stream:
                self.before_stream_verified=not reasons
            else:
                self.post_stream_verified=not reasons
                self.stream_generation=generation
            stream=self.session.account_stream
            feed=bool(stream and (stream.healthy or post_stream and getattr(stream,'connected',False) and
                                  getattr(stream,'subscribed',set())==set(stream.CHANNELS)))
            if reasons:
                review=bool(self.recovery.state.positions or self.local_positions)
                self.transition(StartupState.POSITION_REVIEW if review else StartupState.ENTRY_PAUSED,*reasons)
            elif not (self.before_stream_verified and self.post_stream_verified and feed):
                self.transition(StartupState.ENTRY_PAUSED,'POST_STREAM_RECONCILIATION_REQUIRED')
            else:
                self.transition(StartupState.READY)
                self.session.execution.entries_paused=False
            self.recovery.checkpoint()
            return report
        except Exception as exc:
            self.transition(StartupState.FAILED_SAFE,'STARTUP_RECOVERY_FAILED:'+type(exc).__name__)
            raise ExchangeError('STARTUP_RECOVERY_FAILED:'+type(exc).__name__) from None

    def after_stream(self, generation):
        if not self.before_stream_verified:
            self.reconcile()
        self.reconcile(post_stream=True,generation=generation)
        return self.state==StartupState.READY

    @property
    def entry_ready(self):
        stream=self.session.account_stream
        if self.state!=StartupState.READY or not stream or not stream.healthy:
            return False
        engine=getattr(self.session.market,'engine',None)
        if engine is not None:
            return bool(engine.connected and engine.reconciled and engine.last_receive_ms is not None and
                        0<=self.clock()-engine.last_receive_ms<=45000)
        return True

    def clean_shutdown(self):
        self.session.execution.entries_paused=True
        lifecycle=self.journal.control('recovery_lifecycle')
        lifecycle.update(clean=True,state=StartupState.ENTRY_PAUSED.value,updated_ms=self.clock())
        if self.recovery.state.initialized and self.recovery.state.last_window is not None:
            self.recovery.checkpoint(lifecycle=lifecycle,clean=True)
        else:
            self.journal.control('recovery_lifecycle',lifecycle)
        self.journal.event('CLEAN_SHUTDOWN',self.clock(),run_id=self.run_id)

    def report(self):
        state=self.recovery.state
        known=state.equity is not None and state.last_window is not None
        tracked=state.tracked_order_ids
        orders=state.orders if known else {}
        unknown=set(orders)-tracked
        try:
            local={s:(decimal(p['quantity']),p['side']) for s,p in self.local_positions.items()}
            local_valid=True
        except Exception:
            local={};local_valid=False
        actual={s:(abs(p.quantity),'BUY' if p.quantity>0 else 'SELL') for s,p in state.positions.items()}
        protection=self.session.execution.protection
        return safe_data(dict(state=self.state.value,previous_shutdown=self.previous_shutdown,
            account='VERIFIED' if getattr(self,'account_verified',False) else 'NOT_READY',
            exchange_positions=len(actual) if known else None,local_positions=len(local),
            position_match=local==actual if known and local_valid else None,actual_positions=[asdict(p) for p in state.positions.values()],
            open_orders=len(orders) if known else None,tracked_orders=len(set(orders)&tracked) if known else None,unknown_orders=len(unknown) if known else None,
            order_classifications={oid:self._order_kind(oid) for oid in orders},
            new_fills_recovered=max(0,len(state.fills)-self.fill_count),
            funding_events_recovered=max(0,len(state.funding)-self.funding_count),
            strategy_state='RESTORED' if not self.reasons and known else 'PARTIAL' if self.session.managers else 'UNKNOWN',
            protection=protection.report() if protection else 'NOT_CONFIGURED',
            feed='HEALTHY' if self.session.account_stream and self.session.account_stream.healthy else 'DEGRADED',
            before_stream_verified=self.before_stream_verified,post_stream_verified=self.post_stream_verified,
            stream_generation=self.stream_generation,downtime_review=self.downtime,reasons=self.reasons,
            reconciliation='PASS' if self.state==StartupState.READY else 'FAIL',
            entry_status='READY' if self.entry_ready else 'ENTRY_PAUSED'))

    def _order_kind(self, oid):
        row=next((r for r in self.journal.intents() if str(r['oid'])==oid),None)
        if row is None:return 'UNKNOWN'
        request=json.loads(row['request'])
        if request['strategy_id']=='CATASTROPHIC_STOP':return 'CATASTROPHIC_STOP'
        if request.get('reduce_only'):return 'STRATEGY_EXIT'
        return 'ENTRY'


def read_only_startup_report(*,account_configured=False,market_ready=False):
    return dict(state='READ_ONLY_READY' if account_configured and market_ready else
                'ACCOUNT_NOT_CONFIGURED' if not account_configured else 'BOOTING',
        previous_shutdown='UNKNOWN',account='NOT_VERIFIED',exchange_positions=None,
        position_match=None,strategy_state='UNKNOWN',protection='NOT_VERIFIED',
        entry_status='ENTRY_PAUSED',live_ready=False,
        reason='READ_ONLY_OBSERVER_HAS_NO_AUTHORIZED_EXECUTOR_OR_RESTORED_MANAGEMENT')


def write_startup_report(directory, report):
    path=Path(directory)
    path.mkdir(parents=True,exist_ok=True)
    (path/'startup_recovery.json').write_text(json.dumps(safe_data(report),indent=2,default=str)+'\n')
    rows=['TEAM ANCHORIUM — STARTUP RECOVERY']+[str(k)+': '+str(v) for k,v in report.items() if k not in {'actual_positions','protection'}]
    (path/'startup_recovery.txt').write_text('\n'.join(rows)+'\n')
