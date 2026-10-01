"""Safety wrapper around the unchanged candle-close management mathematics."""
import csv
import json
import logging
import math
import os
import tempfile
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from execution_engine import LegacyPaperTrader, PyramidingState
from execution_safety import InstrumentIdentity, MarketQuote, ExecutionQualityGate, SafetyError, FeeModel, solve_quantity, estimate_trade_economics, capital_protection_prices
from execution_adapters import PaperExecutionAdapter
from safety_journal import SafetyJournal

LOGGER=logging.getLogger(__name__)
STATES=('SIGNAL_CREATED','ECONOMICALLY_VALIDATED','RISK_APPROVED','ORDER_SUBMITTED','ORDER_ACKNOWLEDGED',
        'PARTIALLY_FILLED','FILLED','PROTECTION_CONFIRMED','POSITION_OPEN','EXIT_REQUESTED',
        'PARTIALLY_EXITED','POSITION_CLOSED','BROKER_RECONCILED','ACCOUNTED')
FAILURES={'REJECTED','CANCELLED','EXPIRED','BROKER_TIMEOUT','PARTIAL_FILL_STALLED','PROTECTION_FAILED',
          'RECONCILIATION_FAILED','UNKNOWN_BROKER_STATE','UNPROTECTED_POSITION_EMERGENCY'}

class SafeTrader(LegacyPaperTrader):
    def __init__(self,*args,environment=None,adapter=None,clock=None,journal_path=None,**kwargs):
        self.environment=environment or ('TEST' if os.getenv('PYTEST_CURRENT_TEST') else config.EXECUTION_ENVIRONMENT)
        self.clock=clock or (lambda:datetime.now(ZoneInfo('Asia/Kolkata')))
        self.adapter=adapter or PaperExecutionAdapter()
        if self.environment=='LIVE':
            if not config.LIVE_MODE or not config.LIVE_VALIDATION_APPROVED or not self.adapter.is_live:
                raise SafetyError('LIVE_EXECUTION_BLOCKED')
            from activation_gate import validate_activation
            validate_activation(config.LIVE_ACTIVATION_EVIDENCE_FILE,self.clock())
            self.adapter.capabilities.validate(self.clock())
        elif self.adapter.is_live:
            raise SafetyError('ENVIRONMENT_MISMATCH')
        if kwargs.get('bypass_friction_gate'):
            raise SafetyError('FRICTION_BYPASS_FORBIDDEN')
        self.session_id=str(uuid.uuid4()); self.quotes={}; self.last_rejection=None
        self.execution_state=None; self._shutdown_complete=False
        path=kwargs.get('csv_log_path')
        if path is None:
            base=Path(tempfile.mkdtemp(prefix='bot-tests-')) if self.environment=='TEST' else Path(__file__).parent/'data'/self.environment.lower()
            path=str(base/'trades.csv'); kwargs['csv_log_path']=path
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        journal_location=journal_path or str(Path(path).with_suffix('.sqlite3'))
        self._journal_was_present=Path(journal_location).exists()
        self.journal=SafetyJournal(journal_location,self.environment)
        self.journal.start_day(self.clock().date())
        if self.adapter.is_live:self.adapter.on_order_acknowledged=self._record_acknowledgement
        # Force one position/tranche at the infrastructure boundary; strategy code stays frozen.
        kwargs['max_tranches']=1
        try:super().__init__(*args,**kwargs)
        except Exception:
            self.journal.close(); raise
        self._current_date=self.clock().date()
        self._daily_pnl=sum(t['net_pnl'] for t in self.journal.trades())
        self._trade_count=self.journal.budget()[1]
        self.working_capital=min(self.working_capital,config.WORKING_CAPITAL)
        self.risk_per_trade=min(self.risk_per_trade,config.RISK_PER_TRADE)
        self.daily_loss_limit=min(self.daily_loss_limit,config.DAILY_LOSS_LIMIT)
        self.tranche_capitals=[self.working_capital]
        self.reconciliation_status='SIMULATED' if not self.adapter.is_live else 'UNVERIFIED'
        recovered=self.journal.load_position()
        if recovered:
            self._open_position=recovered
            self._open_position['instrument']=InstrumentIdentity.from_dict(recovered['instrument'])
            self._open_position['timestamp']=datetime.fromisoformat(recovered['timestamp'])
            self._state=PyramidingState.HOLDING_TRANCHE_1
            self._halted=True
            self.execution_state='POSITION_OPEN'
        elif self.journal.reservations():
            self._halted=True; self._state=PyramidingState.STATE_UNKNOWN
            self.execution_state='UNKNOWN_BROKER_STATE'
        if self.journal.get_meta('quarantine'):self._halted=True
        management=self.journal.get_meta('management_state') or {}
        self.candles_since_last_sl=management.get('candles_since_last_sl',self.candles_since_last_sl)
        if recovered:self.candles_held=management.get('candles_held',0)
        if management.get('day')==self.journal.day:self.daily_bias=management.get('daily_bias','NEUTRAL')
        if self.adapter.is_live:self.reconcile_broker('STARTUP')

    def _event(self,kind,**payload):
        payload.setdefault('run_id',getattr(self,'run_id',self.session_id))
        self.journal.event(str(uuid.uuid4()),kind,payload)
        LOGGER.info('[%s] %s',kind,json.dumps(payload,default=str,sort_keys=True))

    def _quarantine(self,reason):
        self._halted=True
        from execution_engine import alert_human
        alert_human('CRITICAL STATE UNKNOWN / SAFETY HALT: '+reason)
        try:self.journal.set_meta('quarantine',{'reason':reason,'timestamp':self.clock().isoformat()})
        except sqlite3.Error:LOGGER.critical('Safety halt could not be persisted; broker/operator recovery required')

    def _storage_failure(self,operation,fill=None,instrument=None,side=None,risk_budget=None):
        self._quarantine('JOURNAL_UNAVAILABLE')
        self._state=PyramidingState.STATE_UNKNOWN; self.execution_state='UNKNOWN_BROKER_STATE'
        self.reconciliation_status='ACCOUNTING_UNAVAILABLE'
        LOGGER.critical('Journal failure during %s; no new order or fabricated accounting is permitted',operation)
        if operation=='ENTRY' and fill is not None and instrument is not None:
            exposure={'instrument':instrument.to_dict(),'side':side,'quantity':fill.quantity,
                'averageprice':fill.price,'entry_order_id':fill.order_id,'accounting':'UNCONFIRMED'}
            self.recovered_broker_positions=[exposure]
            try:
                if self.adapter.is_live:
                    positions,_=self.adapter.snapshot()
                    active=[p for p in positions if float(p.get('netqty',0))!=0]
                    if len(active)!=1 or str(active[0].get('symboltoken'))!=instrument.token or active[0].get('tradingsymbol')!=instrument.trading_symbol or float(active[0]['netqty'])!=fill.quantity*(1 if side=='BUY' else -1):
                        raise SafetyError('BROKER_LOCAL_POSITION_MISMATCH')
                trigger,limit=capital_protection_prices(instrument,side,fill.price,fill.quantity,fill.fees,risk_budget)
                self.adapter.protect(instrument,'SELL' if side=='BUY' else 'BUY',fill.quantity,trigger,self.clock(),limit=limit)
                exposure['protection']='BROKER_ACKNOWLEDGED' if self.adapter.is_live else 'SIMULATED'
            except Exception:
                LOGGER.critical('Known exposure could not be protected after journal failure; immediate operator action required')
        return None

    def _record_acknowledgement(self,order_id,params):
        operation=self.journal.get_meta('pending_operation') or {}
        operation.update(broker_order_id=order_id,submitted_params=params)
        self.journal.set_meta('pending_operation',operation)
        self._event('BROKER_ACKNOWLEDGED',order_id=order_id,params=params)

    def _mark_to_market(self,last_price):
        state=self.journal.get_meta('intraday_mark') or {}
        if state.get('day')!=self.journal.day:
            state={'day':self.journal.day,'peak_equity':self.total_capital,'drawdown':0.}
        equity=self.total_capital+sum(t['net_pnl'] for t in self.journal.trades())
        position=self._open_position
        if position:
            if not math.isfinite(last_price) or last_price<=0:return
            sign=1 if position['side']=='BUY' else -1
            equity+=sign*(last_price-position['average_entry_price'])*position['quantity']-position['entry_friction_total']
            equity+=sum(sign*(f['price']-position['average_entry_price'])*f['quantity']-f['fees'] for f in position['exit_fills'])
            if position['quantity']:
                equity-=FeeModel().leg('SELL' if sign==1 else 'BUY',last_price,position['quantity'])['total_charges']
        state['peak_equity']=max(state['peak_equity'],equity)
        state['drawdown']=max(state['drawdown'],state['peak_equity']-equity)
        state['last_equity']=equity
        state['basis']='OBSERVED_LAST_PRICE_WITH_ESTIMATED_UNREALIZED_EXIT_FEES'
        self.journal.set_meta('intraday_mark',state)

    def _transition(self,state,**payload):
        previous=self.execution_state
        allowed={
          None:{'SIGNAL_CREATED'},'ACCOUNTED':{'SIGNAL_CREATED'},'REJECTED':{'SIGNAL_CREATED'},
          'CANCELLED':{'SIGNAL_CREATED'},'EXPIRED':{'SIGNAL_CREATED'},
          'SIGNAL_CREATED':{'ECONOMICALLY_VALIDATED'},'ECONOMICALLY_VALIDATED':{'RISK_APPROVED'},
          'RISK_APPROVED':{'ORDER_SUBMITTED'},'ORDER_SUBMITTED':{'ORDER_ACKNOWLEDGED'},
          'ORDER_ACKNOWLEDGED':{'PARTIALLY_FILLED','FILLED'},'PARTIALLY_FILLED':{'FILLED','PROTECTION_CONFIRMED'},
          'FILLED':{'PROTECTION_CONFIRMED'},'PROTECTION_CONFIRMED':{'POSITION_OPEN'},
          'POSITION_OPEN':{'EXIT_REQUESTED'},'EXIT_REQUESTED':{'PARTIALLY_EXITED','POSITION_CLOSED'},
          'PARTIALLY_EXITED':{'EXIT_REQUESTED'},'POSITION_CLOSED':{'BROKER_RECONCILED'},
          'BROKER_RECONCILED':{'ACCOUNTED'},'UNPROTECTED_POSITION_EMERGENCY':{'EXIT_REQUESTED'},
        }
        if state not in FAILURES and state not in allowed.get(previous,set()):
            raise SafetyError('INVALID_EXECUTION_STATE_TRANSITION')
        self.execution_state=state; self._event(state,previous=previous,**payload)

    def _reject(self,reason,payload=None):
        self.last_rejection=reason
        self._event('REJECTED',reason=reason,signal=payload or {})
        if not self.has_open_position and self.execution_state not in FAILURES:self.execution_state='REJECTED'
        return None

    def set_quote(self,instrument,quote):
        self.quotes[instrument.token]=quote

    def check_day_reset(self,current_dt=None):
        dt=self.schedule.localize(current_dt or self.clock())
        if self._current_date==dt.date():return
        if self._open_position is not None and self._current_date is not None:
            self._halted=True; self._event('RECONCILIATION_FAILED',reason='OVERNIGHT_EXPOSURE')
            return
        self._current_date=dt.date(); self.journal.start_day(dt.date())
        self._daily_pnl=sum(t['net_pnl'] for t in self.journal.trades())
        self._trade_count=self.journal.budget()[1]
        self._halted=bool(self.journal.get_meta('quarantine') or self.journal.reservations())
        self.daily_bias='NEUTRAL'
        self._persist_management()
    _check_day_reset=check_day_reset

    def _persist_position(self):
        p=dict(self._open_position) if self._open_position else None
        if p:
            p['instrument']=p['instrument'].to_dict()
            self.journal.save_position(p)
        else:self.journal.save_position(None)
        self._persist_management()

    def _persist_management(self):
        self.journal.set_meta('management_state',{'day':self.journal.day,'candles_held':self.candles_held,
            'candles_since_last_sl':self.candles_since_last_sl,'daily_bias':self.daily_bias})

    def execute_trade(self,signal_data,timestamp=None,atr_14=None,atr=None,side='BUY',angel_session=None,**kwargs):
        with self.lock:
            ts=self.schedule.localize(timestamp or self.clock()); self.check_day_reset(ts)
            if self.has_open_position:
                requested_side='SELL' if side in {'SHORT','SELL'} else side
                existing=self._open_position
                if requested_side!=existing['side'] and signal_data.get('symbol') in {existing['symbol'],existing['trading_symbol']}:
                    candidate_identity=signal_data.get('instrument')
                    if candidate_identity!=existing['instrument']:return self._reject('INSTRUMENT_IDENTITY_MISMATCH')
                    candidate_quote=signal_data.get('quote')
                    if candidate_quote:self.set_quote(candidate_identity,candidate_quote)
                    if self.close_position(signal_data.get('Close',0),ts,f"Direction Flip ({existing['side']}→{requested_side})") is None:
                        return self._reject('UNKNOWN_BROKER_STATE')
                else:return self._reject('POSITION_ALREADY_OPEN')
            if self._halted or self._state==PyramidingState.STATE_UNKNOWN:return self._reject('UNKNOWN_BROKER_STATE')
            if not self.schedule.can_enter_new_positions(ts):return self._reject('ENTRY_CUTOFF_REACHED')
            if self.journal.budget()[1]>=config.MAX_NEW_SETUPS:return self._reject('MAX_NEW_SETUPS_REACHED')
            if self.candles_since_last_sl<self.reentry_cooldown_candles:return self._reject('COOLDOWN')
            if self.journal.remaining(self.daily_loss_limit)<=0:return self._reject('DAILY_RISK_EXHAUSTED')
            side='SELL' if side in {'SHORT','SELL'} else side
            if side not in {'BUY','SELL'}:return self._reject('INVALID_SIDE')
            try:
                identity=signal_data.get('instrument')
                if not isinstance(identity,InstrumentIdentity):raise SafetyError('INSTRUMENT_IDENTITY_MISMATCH')
                identity.validate(signal_data.get('symbol'),signal_data.get('token'),signal_data.get('exchange'),ts)
                if self.adapter.is_live and not self.reconcile_broker('PRE_ENTRY'):raise SafetyError('RECONCILIATION_FAILED')
                available_cash=self.working_capital
                if self.adapter.is_live:available_cash=min(available_cash,self.adapter.available_cash())
                self._transition('SIGNAL_CREATED',side=side,symbol=identity.symbol,signal=signal_data)
                ref=float(signal_data['VWAP']); current_atr=float(atr_14 if atr_14 is not None else atr if atr is not None else signal_data['ATR_14'])
                if not math.isfinite(current_atr) or current_atr<=0 or not math.isfinite(ref) or ref<=0:raise SafetyError('INVALID_ATR')
                # Preserve the original absolute stop and 1:2 geometry anchored to signal VWAP.
                distance=round(config.SL_ATR_MULT*current_atr,2); sign=1 if side=='BUY' else -1
                stop=round(ref-sign*distance,2); target=round(ref+sign*2.*distance,2)
                quote=signal_data.get('quote') or self.quotes.get(identity.token)
                expected=ExecutionQualityGate().validate(quote,side,ts)
                sizing_reference=expected
                self.set_quote(identity,quote)
                self._event('EXECUTION_CHECK',bid=quote.bid,ask=quote.ask,spread=quote.spread_pct,expected_entry=expected)
                # Preserve the existing normal/low-vol economic floors, without weakening either.
                rr=config.MIN_NET_RR_LOW_VOL if current_atr/ref<config.LOW_VOL_ATR_PCT else config.MIN_NET_RR_NORMAL
                remaining=self.journal.remaining(self.daily_loss_limit)
                depth=quote.ask_quantity if side=='BUY' else quote.bid_quantity
                e=solve_quantity(side,sizing_reference,stop,target,available_cash,self.risk_per_trade,remaining,rr,
                    config.SLIPPAGE_HAIRCUT_PCT,identity.lot_size,int(depth*config.BEST_LEVEL_MAX_PARTICIPATION),
                    exit_spread_pct=config.SCREEN_MAX_SPREAD_PCT/2,tick_size=identity.tick_size)
                if e is None:raise SafetyError('NO_ECONOMICALLY_VALID_QUANTITY')
                self._transition('ECONOMICALLY_VALIDATED',economics=e.__dict__)
                risk_budget=min(self.risk_per_trade,remaining)
                trade_id=str(uuid.uuid4()); self.journal.reserve(trade_id,risk_budget,self.daily_loss_limit)
                self._transition('RISK_APPROVED',trade_id=trade_id,remaining=remaining,risk=risk_budget,projected_strategy_stop_risk=e.net_stop_loss)
                limit=identity.price(expected*(1+sign*config.ORDER_LIMIT_ALLOWANCE_PCT),side)
                self._transition('ORDER_SUBMITTED',requested_quantity=e.quantity,limit=limit)
                self.journal.set_meta('pending_operation',{'kind':'ENTRY','trade_id':trade_id,
                    'instrument':identity.to_dict(),'side':side,'requested_quantity':e.quantity,'limit':limit})
                fill=self.adapter.execute(identity,side,e.quantity,quote,ts,limit=limit)
                self._transition('ORDER_ACKNOWLEDGED',order_id=fill.order_id)
                self._transition(fill.status,filled_quantity=fill.quantity)
                if not self.journal.record_fill(fill.to_dict()):raise SafetyError('DUPLICATE_ENTRY_FILL')
                self._event('FILL',**fill.to_dict())
                self._trade_count=self.journal.budget()[1]
                actual=estimate_trade_economics(side,fill.quantity,fill.price,stop,target,
                    config.SLIPPAGE_HAIRCUT_PCT,exit_spread_pct=config.SCREEN_MAX_SPREAD_PCT/2,
                    tick_size=identity.tick_size,entry_slippage_allowance=0.)
                self._open_position={
                    'position_id':trade_id,'trade_id':trade_id,'session_id':self.session_id,'instrument':identity,
                    'symbol':identity.symbol,'trading_symbol':identity.trading_symbol,'token':identity.token,'exchange':identity.exchange,
                    'side':side,'quantity':fill.quantity,'initial_quantity':fill.quantity,'requested_quantity':e.quantity,
                    'initial_entry_price':fill.price,'average_entry_price':fill.price,'signal_price':ref,
                    'signal_vwap':ref,'signal_timestamp':str(signal_data.get('signal_timestamp',ts.isoformat())),
                    'signal_type':signal_data.get('signal_type'),'signal_id':signal_data.get('signal_id',str(uuid.uuid4())),
                    'decision_price':quote.last,'expected_entry_price':expected,'requested_order_price':limit,
                    'submitted_limit_price':limit,'actual_entry_fill':fill.price,'actual_fill_price':fill.price,
                    'entry_order_id':fill.order_id,'entry_fill_id':fill.fill_id,'entry_fee_source':fill.fee_source,
                    'simulated':not self.adapter.is_live,'entry_notional':fill.price*fill.quantity,
                    'entry_friction_total':fill.fees,'total_cost':fill.price*fill.quantity+fill.fees,
                    'current_tranches':1,'max_tranches':1,'atr_14':current_atr,'entry_atr':current_atr,
                    'stop_loss_distance':distance,'stop_loss_price':stop,'target_price':target,'initial_target_price':target,
                    'risk_distance':distance,'projected_net_loss_at_stop':actual.net_stop_loss,
                    'projected_net_profit_at_target':actual.net_target_profit,'stop_exit_charges':actual.stop_exit_fees,
                    'target_exit_charges':actual.target_exit_fees,'tranches':[{'entry_price':fill.price,'quantity':fill.quantity}],
                    'timestamp':ts,'breakeven_armed':False,'exit_fills':[],'mae':0.,'mfe':0.,
                    'reserved_risk':risk_budget,'protection_id':None,'protection_basis':'CAPITAL_LOSS_LIMIT',
                }
                self._state=PyramidingState.HOLDING_TRANCHE_1; self.entry_atr=current_atr; self.candles_held=0
                self._persist_position() # Durable exposure exists before protection attempt.
                self._mark_to_market(fill.price)
                self.journal.set_meta('pending_operation',None)
                if actual.net_stop_loss+fill.fees-actual.entry_fees>min(self.risk_per_trade,e.net_stop_loss)+1e-8 or fill.quantity>e.quantity:
                    raise SafetyError('POST_FILL_RISK_EXCEEDED')
                if actual.net_rr<rr or actual.net_target_profit<config.MIN_NET_PROFIT_RS:
                    raise SafetyError('POST_FILL_ECONOMICS_FAILED')
                protection=self._install_capital_protection(ts)
                self._open_position['protection_id']=protection; self._persist_position()
                self.journal.set_meta('pending_operation',None)
                self._transition('PROTECTION_CONFIRMED',quantity=fill.quantity,protection_id=protection)
                self._transition('POSITION_OPEN',trade_id=trade_id)
                if self.adapter.is_live and not self.reconcile_broker('POST_ENTRY'):raise SafetyError('RECONCILIATION_FAILED')
                ticket=self._build_ticket(self._open_position,1,fill.quantity,fill.price,trade_id)
                self._trade_log.append(ticket); return ticket
            except Exception as exc:
                if isinstance(exc,sqlite3.Error):
                    return self._storage_failure('ENTRY',locals().get('fill'),locals().get('identity'),side,locals().get('risk_budget'))
                reason=str(exc)
                if self.has_open_position:
                    self._quarantine(reason); self._state=PyramidingState.STATE_UNKNOWN
                    self._transition('UNPROTECTED_POSITION_EMERGENCY',reason=reason)
                    # No new entry is possible; attempt the deterministic protected unwind.
                    self.close_position(self._latest_price or signal_data.get('Close',0),ts,'Protection/Risk Emergency')
                    self._halted=True
                elif self.execution_state in {'ORDER_SUBMITTED','ORDER_ACKNOWLEDGED','PARTIALLY_FILLED','FILLED'} and reason not in {'BROKER_ORDER_REJECTED','CANCELLED','EXPIRED'}:
                    self._quarantine(reason); self._state=PyramidingState.STATE_UNKNOWN
                    self._transition('UNKNOWN_BROKER_STATE',reason=reason)
                else:
                    if 'trade_id' in locals():self.journal.release(trade_id)
                    self.journal.set_meta('pending_operation',None)
                    if reason in {'CANCELLED','EXPIRED','BROKER_ORDER_REJECTED'}:
                        self._transition('REJECTED' if reason=='BROKER_ORDER_REJECTED' else reason,reason=reason)
                return self._reject(reason,signal_data)

    def check_exit(self,live_price,timestamp=None):
        with self.lock:
            if self._open_position:
                p=self._open_position; sign=1 if p['side']=='BUY' else -1
                move=sign*(live_price-p['average_entry_price'])*p['quantity']
                p['mae']=min(p.get('mae',0),move); p['mfe']=max(p.get('mfe',0),move)
                self._mark_to_market(live_price)
            result=super().check_exit(live_price,timestamp)
            if result or not self._open_position:return result
            position=self._open_position
            sign=1 if position['side']=='BUY' else -1
            realized=sum(max(0.,sign*(position['average_entry_price']-f['price'])*f['quantity']+f['fees']) for f in position['exit_fills'])
            loss=sign*(position['average_entry_price']-live_price)*position['quantity']+position['entry_friction_total']+realized
            loss+=FeeModel().leg('SELL' if sign==1 else 'BUY',live_price,position['quantity'])['total_charges']
            if loss>=position['reserved_risk']:
                self._quarantine('CAPITAL_PROTECTION_TRIGGER')
                return self.close_position(live_price,timestamp,'Capital Protection Emergency')
            return None

    def _install_capital_protection(self,when):
        position=self._open_position; sign=1 if position['side']=='BUY' else -1
        realized=sum(max(0.,sign*(position['average_entry_price']-f['price'])*f['quantity']+f['fees']) for f in position['exit_fills'])
        trigger,limit=capital_protection_prices(position['instrument'],position['side'],position['average_entry_price'],
            position['quantity'],position['entry_friction_total'],position['reserved_risk'],realized)
        position['emergency_trigger_price']=trigger; position['emergency_limit_price']=limit
        self._event('CAPITAL_PROTECTION',strategy_stop=position['stop_loss_price'],trigger=trigger,limit=limit,
            quantity=position['quantity'],risk_budget=position['reserved_risk'])
        return self.adapter.protect(position['instrument'],'SELL' if sign==1 else 'BUY',position['quantity'],trigger,when,limit=limit)

    def notify_candle_close(self,*args,**kwargs):
        with self.lock:
            result=super().notify_candle_close(*args,**kwargs)
            if self.has_open_position:self._persist_position()
            else:self._persist_management()
            return result
    on_candle_close=notify_candle_close

    def close_position(self,exit_price,timestamp=None,reason='Signal Exit',angel_session=None):
        with self.lock:
            if not self.has_open_position:return None
            p=self._open_position; ts=self.schedule.localize(timestamp or self.clock())
            if not isinstance(p.get('instrument'),InstrumentIdentity) or p.get('side') not in {'BUY','SELL'}:
                self._halted=True; self._state=PyramidingState.STATE_UNKNOWN
                self._event('UNKNOWN_BROKER_STATE',reason='INVALID_LOCAL_POSITION'); return None
            identity=p['instrument']; side='SELL' if p['side']=='BUY' else 'BUY'
            try:
                # Pre-submission quote failure is known to have sent no exit order. Keep the
                # current state/protection so a fresh observation can safely retry flattening.
                needs_quote=p['quantity']>0
                if self.adapter.is_live and p.get('protection_id'):
                    row=self.adapter._order(p['protection_id'])
                    terminal=str(row.get('status',row.get('orderstatus',''))).lower() in self.adapter.TERMINAL
                    needs_quote=not terminal or int(float(row.get('filledshares',0)))<p['quantity']
                if needs_quote:
                    try:ExecutionQualityGate().validate(self.quotes.get(identity.token),side,ts,p['quantity'])
                    except SafetyError as exc:
                        self._halted=True; self._event('REJECTED',operation='EXIT',reason=str(exc)); return None
                self._transition('EXIT_REQUESTED',reason=reason)
                quote=self.quotes.get(identity.token)
                if p.get('protection_id'):
                    self.adapter.cancel(p['protection_id']); p['protection_id']=None
                    if self.adapter.is_live:
                        protected_fill=self.adapter.read_fill(str(row['orderid']),identity,side,p['quantity'])
                        if protected_fill and self.journal.record_fill(protected_fill.to_dict()):
                            p['exit_fills'].append(protected_fill.to_dict()); p['quantity']-=protected_fill.quantity
                if self.adapter.is_live and not self.reconcile_broker('PRE_EXIT',allow_pending=True):
                    raise SafetyError('RECONCILIATION_FAILED')
                # A target/stop argument is a trigger only. Fill comes from an observable quote.
                if p['quantity']>0:
                    self.journal.set_meta('pending_operation',{'kind':'EXIT','trade_id':p['trade_id'],
                        'instrument':identity.to_dict(),'side':side,'requested_quantity':p['quantity']})
                    fill=self.adapter.execute(identity,side,p['quantity'],quote,ts,**({'is_exit':True} if self.adapter.is_live else {}))
                    if not self.journal.record_fill(fill.to_dict()):raise SafetyError('DUPLICATE_EXIT_FILL')
                    self._event('FILL',**fill.to_dict())
                    p['exit_fills'].append(fill.to_dict()); p['quantity']-=fill.quantity
                    self.journal.set_meta('pending_operation',None)
                if p['quantity']>0:
                    self._transition('PARTIALLY_EXITED',remaining=p['quantity'])
                    try:p['protection_id']=self._install_capital_protection(ts)
                    except SafetyError as exc:
                        self._quarantine(str(exc)); self._event('UNPROTECTED_POSITION_EMERGENCY',remaining=p['quantity'])
                    self._persist_position(); self._halted=True; return None
                self._transition('POSITION_CLOSED',trade_id=p['trade_id'])
                if self.adapter.is_live:
                    positions,orders=self.adapter.snapshot()
                    if any(float(x.get('netqty',0))!=0 for x in positions):raise SafetyError('RECONCILIATION_FAILED')
                    self.reconciliation_status='BROKER_QUANTITY_MATCHED'
                else:self.reconciliation_status='SIMULATED'
                self._transition('BROKER_RECONCILED',result=self.reconciliation_status)
                total=p['initial_quantity']; price=sum(f['quantity']*f['price'] for f in p['exit_fills'])/total
                exit_fees=sum(f['fees'] for f in p['exit_fills']); gross=(1 if p['side']=='BUY' else -1)*(price-p['average_entry_price'])*total
                entry_fees=p['entry_friction_total']; net=gross-entry_fees-exit_fees
                summary={
                    'environment':self.environment,'session_id':p['session_id'],'trade_id':p['trade_id'],
                    'strategy_version':config.STRATEGY_VERSION,'symbol':p['symbol'],'token':p['token'],'side':p['side'],
                    'signal_timestamp':p['signal_timestamp'],'signal_price':p['signal_price'],
                    'broker_order_id':p['entry_order_id'],'broker_fill_id':p['entry_fill_id'],
                    'exit_order_ids':[f['order_id'] for f in p['exit_fills']],
                    'requested_quantity':p['requested_quantity'],'filled_quantity':total,
                    'actual_entry_price':p['average_entry_price'],'actual_exit_price':price,
                    'gross_pnl':round(gross,2),'entry_fees':entry_fees,'exit_fees':exit_fees,'net_pnl':round(net,2),
                    'entry_fee_source':p['entry_fee_source'],'exit_fee_sources':[f['fee_source'] for f in p['exit_fills']],
                    'exit_reason':reason,'reconciliation_status':self.reconciliation_status,
                    'timestamp':ts.isoformat(),'avg_entry_price':p['average_entry_price'],'exit_price':price,
                    'total_quantity':total,'quantity':total,'tranches_filled':1,'statutory_charges':entry_fees+exit_fees,
                    'net_roi_pct':net/p['total_cost']*100,'ending_working_capital':self.working_capital,
                    'hold_duration_minutes':(ts-p['timestamp']).total_seconds()/60,'mae':p['mae'],'mfe':p['mfe'],
                    'entry_slippage':(1 if p['side']=='BUY' else -1)*(p['average_entry_price']-p['expected_entry_price']),
                    'signal_type':p['signal_type'],'reserved_risk':p['reserved_risk'],
                }
                if self.journal.finish(p['trade_id'],net,summary):
                    self._daily_pnl+=net; self._trade_log.append(summary)
                    try:self._export_csv()
                    except OSError as exc:self._event('CSV_EXPORT_FAILED',reason=type(exc).__name__)
                self._transition('ACCOUNTED',trade_id=p['trade_id'],net_pnl=net)
                self._open_position=None; self._state=PyramidingState.CLOSED
                self._mark_to_market(0.)
                self._entry_timestamp=None; self.entry_atr=None; self.candles_held=0
                if 'Stop Loss' in reason:self.candles_since_last_sl=0
                if -net>p['reserved_risk']+1e-8:self._quarantine('REALIZED_SETUP_RISK_BREACH')
                self._persist_management()
                self._halted=bool(self.journal.get_meta('quarantine')) or self.journal.remaining(self.daily_loss_limit)<=0
                return summary
            except Exception as exc:
                if isinstance(exc,sqlite3.Error):return self._storage_failure('EXIT')
                self._quarantine(str(exc)); self._state=PyramidingState.STATE_UNKNOWN
                self.execution_state='UNKNOWN_BROKER_STATE'
                self._event('UNKNOWN_BROKER_STATE',operation='EXIT',reason=str(exc))
                self._persist_position(); return None

    def reconcile_broker(self,reason,allow_pending=False):
        if not self.adapter.is_live:return True
        try:
            positions,orders=self.adapter.snapshot()
            active=[p for p in positions if float(p.get('netqty',0))!=0]
            pending=[o for o in orders if str(o.get('status',o.get('orderstatus',''))).lower() not in self.adapter.TERMINAL]
            local=self._open_position
            if local:
                match=[p for p in active if str(p.get('symboltoken'))==local['token'] and p.get('tradingsymbol')==local['trading_symbol']]
                expected_qty=local['quantity']*(1 if local['side']=='BUY' else -1)
                if local['quantity']==0 and not active:
                    self.reconciliation_status='PASS'; return True
                if (len(active)!=1 or len(match)!=1 or float(match[0]['netqty'])!=expected_qty or
                    match[0].get('exchange','NSE')!=local['exchange'] or
                    match[0].get('producttype','INTRADAY')!='INTRADAY'):
                    raise SafetyError('BROKER_LOCAL_POSITION_MISMATCH')
                if not allow_pending and any(str(o.get('orderid'))!=local.get('protection_id') for o in pending):raise SafetyError('UNKNOWN_OPEN_ORDER')
            elif active:
                # Preserve verified broker exposure for operator recovery; do not invent strategy stops.
                self._event('BROKER_POSITION_RECOVERED',positions=active,orders=pending)
                self.journal.event('recovery-'+str(uuid.uuid4()),'RECOVERED_EXPOSURE',{'positions':active,'orders':pending})
                self.journal.set_meta('recovered_exposure',{'positions':active,'orders':pending})
                self.recovered_broker_positions=active; raise SafetyError('UNMANAGED_BROKER_POSITION')
            elif pending:raise SafetyError('UNKNOWN_OPEN_ORDER')
            self.reconciliation_status='PASS'; self._event('RECONCILIATION',reason=reason,result='PASS'); return True
        except Exception as exc:
            self._quarantine(str(exc)); self._state=PyramidingState.STATE_UNKNOWN
            self.reconciliation_status='FAILED'; self._event('RECONCILIATION_FAILED',reason=reason,error=str(exc)); return False

    def _init_csv_log(self,path):
        # Preserve old files; SQLite is authoritative, CSV is an atomic projection.
        if Path(path).exists() and Path(path).stat().st_size:
            with open(path,newline='') as f:
                reader=csv.DictReader(f)
                if not {'environment','trade_id'}<=set(reader.fieldnames or []):raise SafetyError('LEGACY_LEDGER_REQUIRES_SEPARATE_PATH')
                rows=list(reader)
                if any(row.get('environment')!=self.environment for row in rows):raise SafetyError('ENVIRONMENT_MISMATCH')
                if rows and not self._journal_was_present:raise SafetyError('JOURNAL_MISSING_FOR_EXISTING_LEDGER')

    def _export_csv(self):
        rows=self.journal.trades()
        if not rows:return
        path=Path(self._csv_log_path); temp=path.with_suffix('.csv.tmp')
        with temp.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
            f.flush(); os.fsync(f.fileno())
        os.replace(temp,path)

    def cancel_pending_orders(self,reason='Lifecycle shutdown'):
        if not self.adapter.is_live:return 0
        try:
            _,orders=self.adapter.snapshot(); n=0
            acknowledged=self.journal.db.execute("SELECT payload FROM events WHERE kind='BROKER_ACKNOWLEDGED'").fetchall()
            owned={str(json.loads(row[0])['order_id']) for row in acknowledged}
            for o in orders:
                order_id=str(o.get('orderid'))
                if str(o.get('status',o.get('orderstatus',''))).lower() not in self.adapter.TERMINAL and order_id!=(self._open_position or {}).get('protection_id'):
                    if order_id not in owned:
                        self._quarantine('UNKNOWN_OPEN_ORDER'); continue
                    self.adapter.cancel(order_id); n+=1
            return n
        except Exception as exc:
            self._halted=True; self._event('UNKNOWN_BROKER_STATE',reason=str(exc)); return 0

    def _execute_tranche_1(self,*args,**kwargs):
        raise SafetyError('LEGACY_ENTRY_PATH_DISABLED')
    def _execute_tranche_2(self,*args,**kwargs):
        raise SafetyError('SCALE_IN_DISABLED')
    def _execute_tranche_3(self,*args,**kwargs):
        raise SafetyError('SCALE_IN_DISABLED')

    def session_report(self):
        report=self.journal.report(); report['reconciliation_status']=self.reconciliation_status
        path=Path(self._csv_log_path).with_suffix('.report.json')
        path.write_text(json.dumps(report,indent=2,default=str)); return report

    def shutdown(self,timeout=2.):
        if self._shutdown_complete:return
        self.session_report(); super().shutdown(timeout); self.journal.close(); self._shutdown_complete=True
