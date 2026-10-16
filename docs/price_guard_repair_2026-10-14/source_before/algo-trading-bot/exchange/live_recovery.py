"""Durable account truth and frozen-management restart barriers; no order repair."""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
import json

from .account_events import AccountFunding
from .base_exchange import ExchangeError, Fill, decimal
from .execution_journal import fingerprint
from .hyperliquid_reconciliation import ExchangeTruthState, HyperliquidReconciliation
from strategy_contract import ManagementState
from strategy_freeze import verify_strategy_freeze


@dataclass(frozen=True)
class LiveRecoveryReport:
    ready: bool
    reasons: tuple
    accounting: dict


class LiveAccountRecovery:
    def __init__(self, account, journal, *, initial_start_ms, managers=None):
        self.account=account
        self.journal=journal
        self.initial_start_ms=initial_start_ms
        self.managers=managers if managers is not None else {}
        self.state=ExchangeTruthState()
        self.reconciler=HyperliquidReconciliation(account)
        self.on_truth=None
        self.protection=None
        self.startup_coordinator=None
        self.owner=None
        self.checkpoint_error=None
        self.source=self.source_identity()
        self.saved_management=journal.management()
        try:
            self.saved_snapshot=journal.recovery_snapshot()
            checkpoint=self.saved_snapshot['account'] if self.saved_snapshot else journal.checkpoint()
            if self.saved_snapshot:
                self.saved_management=self.saved_snapshot['management']
                self.checkpoint_error=self.saved_snapshot.get('checkpoint_error')
        except Exception:
            self.saved_snapshot=None
            checkpoint=None
            self.saved_management={}
            self.checkpoint_error='RECOVERY_CHECKPOINT_CORRUPT'
        if checkpoint:
            if checkpoint.get('initial_start_ms')!=initial_start_ms:
                raise ExchangeError('ACCOUNTING_ORIGIN_MISMATCH')
            try:
                self.state.initialized=True
                self.state.quantities={s:decimal(q) for s,q in checkpoint['quantities'].items()}
                self.state.quantity_evidence={s:decimal(q) for s,q in checkpoint['quantity_evidence'].items()}
                self.state.last_window=tuple(checkpoint['last_window'])
                self.state.accounting_origin_ms=initial_start_ms
                restored=[]
                for row in checkpoint['fills']:
                    values=dict(row)
                    for name in ('quantity','price','fee','closed_pnl','start_position'):
                        if values.get(name) is not None:
                            values[name]=decimal(values[name])
                    restored.append(Fill(**values))
                self.state.fills={f.identity:f for f in restored}
                self.state.funding={f.identity:f for f in (AccountFunding(**row) for row in checkpoint['funding'])}
            except Exception:
                self.state=ExchangeTruthState()
                self.saved_management={}
                self.checkpoint_error="RECOVERY_CHECKPOINT_CORRUPT"
        self.last_report=LiveRecoveryReport(False,('STARTUP_RECONCILIATION_REQUIRED',),{})

    def restore_manager(self, manager):
        value=self.saved_management.get(manager.symbol)
        if value is None:
            return False
        verify_strategy_freeze()
        if value.get('version')!=1:
            raise ExchangeError('UNKNOWN_MANAGEMENT_SCHEMA')
        if (any(type(value[k]) is not int or value[k]<0 for k in ('candles_held','candles_since_last_sl')) or
            value['last_candle_ms'] is not None and (type(value['last_candle_ms']) is not int or value['last_candle_ms']<0 or value['last_candle_ms']%60000)):
            raise ExchangeError('INVALID_MANAGEMENT_CANDLE_EVIDENCE')
        position=value.get('position')
        if position is not None:
            if position['side'] not in {'BUY','SELL'}:
                raise ExchangeError('INVALID_MANAGEMENT_SIDE')
            position=dict(position,quantity=decimal(position['quantity'],positive=True))
            for name in ('average_entry_price','stop_loss_price','target_price','atr_14'):
                decimal(position[name],positive=True)
            # Never rebuild a missing stop/target from current market prices.
        manager._open_position=position
        manager._state=ManagementState(value['state'])
        manager.daily_bias=value['daily_bias']
        manager.candles_held=value['candles_held']
        manager.candles_since_last_sl=value['candles_since_last_sl']
        manager.entry_atr=value['entry_atr']
        manager.last_candle_ms=value['last_candle_ms']
        manager._day=date.fromisoformat(value['utc_day']) if value.get('utc_day') else None
        return True

    def manager_data(self, manager, **links):
        return dict(version=1,position=manager._open_position,
            state=manager._state.value,daily_bias=manager.daily_bias,candles_held=manager.candles_held,
            candles_since_last_sl=manager.candles_since_last_sl,entry_atr=manager.entry_atr,
            last_candle_ms=manager.last_candle_ms,utc_day=manager._day.isoformat() if manager._day else None,
            **links)

    def persist_manager(self, manager, **links):
        data=self.manager_data(manager,**links)
        if self.state.initialized and self.state.last_window is not None:
            self.checkpoint(management=dict(self.journal.management(),**{manager.symbol:data}))
        else:
            self.journal.save_management(manager.symbol,data)

    def checkpoint(self, management=None, *, lifecycle=None, clean=False):
        account=dict(initial_start_ms=self.initial_start_ms,quantities=self.state.quantities,
            quantity_evidence=self.state.quantity_evidence,last_window=self.state.last_window,
            fills=[asdict(f) for f in self.state.fills.values()],funding=[asdict(f) for f in self.state.funding.values()])
        from .sdk_transport import OfflineSDKTransport
        mode=('OFFLINE_SIGNED_FIXTURE' if self.owner and type(self.owner.execution.transport) is OfflineSDKTransport else
              'LIVE_TESTNET' if self.owner else 'READ_ONLY_ACCOUNT_RECOVERY')
        evidence=dict(last_checkpoint_ts=self.account.client.clock_ms(),execution_mode=mode,
            last_clean_shutdown=clean,source_identity=self.source,
            metadata_hash=fingerprint(self.account.client.metadata),
            checkpoint_error=self.checkpoint_error,
            fill_identities=[list(f.identity) for f in self.state.fills.values()],
            funding_identities=[list(f.identity) for f in self.state.funding.values()],
            risk_state=self.owner.risk_checkpoint_data() if self.owner else self.journal.control('live_risk_state'),
            lifecycle=lifecycle if lifecycle is not None else self.journal.control('recovery_lifecycle'))
        return self.journal.save_recovery_snapshot(account,management if management is not None else self.journal.management(),evidence)

    @staticmethod
    def source_identity():
        from pathlib import Path
        import hashlib,subprocess
        root=Path(__file__).resolve().parents[2]
        brain=root/'algo-trading-bot/signal_brain.py'
        from session_results import source_version
        return dict(git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                    working_source_hash=source_version(list((root/'algo-trading-bot').rglob('*.py'))),
                    strategy_source_hash=hashlib.sha256(brain.read_bytes()).hexdigest())

    def revoke(self, reason):
        guard=getattr(self,'position_guard',None)
        if guard is not None:
            guard.revoke(reason)
        self.state.entries_paused=True
        self.state.reasons=(reason,)
        self.last_report=LiveRecoveryReport(False,(reason,),self.state.report())
        self.journal.event('ACCOUNT_ENTRY_REVOKED',self.account.client.clock_ms(),reason=reason)

    def recover(self):
        verify_strategy_freeze()
        self.revoke('REST_ACCOUNT_RECONCILIATION_REQUIRED')
        protection_reasons=[]
        if self.protection is not None:
            try:
                self.protection.recover_order_identities()
            except Exception as exc:
                protection_reasons.append('PROTECTION_IDENTITY_RECOVERY_REQUIRED')
                self.journal.event('PROTECTION_IDENTITY_RECOVERY_FAILED',self.account.client.clock_ms(),
                                   error_type=type(exc).__name__)
        self.state.tracked_order_ids={str(row['oid']) for row in self.journal.intents() if row['oid'] is not None}
        self.state.tracked_order_ids.update(str(oid) for row in self.journal.intents()
            for oid in json.loads(row['outcome'] or '{}').get('child_order_ids',[]))
        try:
            start=self.initial_start_ms
            if self.state.initialized and self.state.last_window is not None:
                start=max(start,self.state.last_window[1]-60000)
            report=self.reconciler.recover(self.state,start_ms=start)
            if start>self.initial_start_ms and 'POSITION_DELTA_NOT_EXPLAINED_BY_OBSERVED_FILLS' in report['reasons']:
                report=self.reconciler.recover(self.state,start_ms=self.initial_start_ms)
                self.journal.event('ACCOUNT_HISTORY_EXPANDED',self.account.client.clock_ms(),start_ms=self.initial_start_ms)
            if self.on_truth is not None:
                self.on_truth(self.state)
            reasons=list(report['reasons'])+protection_reasons
            if len(self.state.positions)>1:
                reasons.append('UNEXPECTED_CONCURRENT_EXPOSURE')
            if self.checkpoint_error:
                reasons.append(self.checkpoint_error)
            for symbol,position in self.state.positions.items():
                manager=self.managers.get(symbol)
                managed=manager._open_position if manager else None
                if managed is None:
                    reasons.append('MANUAL_REVIEW_REQUIRED:'+symbol+':MISSING_MANAGEMENT_HISTORY')
                elif (managed['quantity']!=abs(position.quantity) or
                      (managed['side']=='BUY')!=(position.quantity>0)):
                    reasons.append('MANUAL_REVIEW_REQUIRED:'+symbol+':MANAGEMENT_QUANTITY_MISMATCH')
                elif position.entry_price is None or float(managed['average_entry_price'])!=float(position.entry_price):
                    reasons.append('MANUAL_REVIEW_REQUIRED:'+symbol+':ENTRY_PRICE_MISMATCH')
            for symbol,manager in self.managers.items():
                if manager.has_open_position and symbol not in self.state.positions:
                    reasons.append('MANUAL_REVIEW_REQUIRED:'+symbol+':UNEXPLAINED_FLAT_POSITION')
            if any(row['state'] in {'UNKNOWN','SUBMITTED','PREPARED'} for row in self.journal.intents()):
                reasons.append('AMBIGUOUS_DURABLE_ORDER_REQUIRES_CLOID_RECOVERY')
            if any(row['state']=='UNKNOWN' for row in self.journal.management_actions()):
                reasons.append('AMBIGUOUS_MANAGEMENT_ACTION_REQUIRES_ACCOUNT_RECOVERY')
            self.state.reasons=tuple(dict.fromkeys(reasons))
            self.state.entries_paused=bool(reasons)
            for manager in self.managers.values():
                prior=self.journal.management().get(manager.symbol,{})
                links={k:v for k,v in prior.items() if k in {'pending_entry','exit_reason','candidate_id','processed_fill_ids','direction_flip_intent'}}
                self.persist_manager(manager,**links)
            self.checkpoint()
            self.last_report=LiveRecoveryReport(not reasons,self.state.reasons,self.state.report())
            if self.owner is not None:
                self.owner.execution._sync_position_truth()
            self.journal.event('LIVE_ACCOUNT_RECONCILED',self.account.client.clock_ms(),
                               ready=not reasons,reasons=self.state.reasons,
                               actual_fees=self.state.report()['realized']['actual_fill_fees'],
                               actual_funding=self.state.report()['realized']['actual_funding_cashflow'])
            return self.last_report
        except Exception as exc:
            self.revoke('ACCOUNT_RECOVERY_FAILED:'+type(exc).__name__)
            raise ExchangeError('ACCOUNT_RECOVERY_FAILED:'+type(exc).__name__) from None


# All restart, reconnect, ambiguous-action and verification callers reuse this
# service; there is no separate reconnect accounting implementation.
AccountReconciler=LiveAccountRecovery
