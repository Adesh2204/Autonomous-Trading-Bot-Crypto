"""Independent catastrophic protection, driven solely by fresh account truth.

No strategy callbacks, stop tuning, synthetic fills or automatic policy activation.
An uncertain signed attempt is a durable barrier, never a reason to create another.
"""
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from enum import Enum
import json
import threading

from .base_exchange import ExchangeError, decimal
from .execution_journal import canonical, safe_data, safe_reason


class ProtectionStatus(str,Enum):
    NOT_REQUIRED='NOT_REQUIRED'
    PENDING='PENDING'
    ACTIVE='ACTIVE'
    PARTIAL='PARTIAL'
    MISSING='MISSING'
    ERROR='ERROR'
    OBSOLETE='OBSOLETE'


@dataclass(frozen=True)
class ProtectionPolicy:
    enabled: bool=False
    approval_reference: str | None=None
    atr_distance_multiple: Decimal | None=None
    execution_slippage_fraction: Decimal | None=None

    def require(self):
        if (self.enabled is not True or not isinstance(self.approval_reference,str) or not self.approval_reference.strip() or
                self.atr_distance_multiple is None or self.execution_slippage_fraction is None):
            raise ExchangeError('EXPLICIT_PROTECTION_DISTANCE_POLICY_REQUIRED')
        if decimal(self.atr_distance_multiple,positive=True)<=0 or not (
                Decimal(0)<decimal(self.execution_slippage_fraction)<Decimal('.8')):
            raise ExchangeError('INVALID_PROTECTION_POLICY')


@dataclass(frozen=True)
class ProtectionPlan:
    symbol: str
    side: str
    quantity: Decimal
    trigger_price: Decimal
    limit_price: Decimal
    normal_strategy_stop: Decimal
    approval_reference: str
    position_observed_ms: int
    actual_entry_price: Decimal | None=None
    classification: str='CATASTROPHIC_STOP'
    is_market: bool=True


class ExchangeProtectionManager:
    def __init__(self,executor,*,policy=None,managers=None):
        self.executor=executor
        self.account=executor.account
        self.journal=executor.journal
        self.clock_ms=executor.client.clock_ms
        self.policy=policy or ProtectionPolicy()
        self.managers=managers if managers is not None else {}
        self.states={}
        self.lock=threading.RLock()
        self.running=False
        self.last_verified_ms=None
        with self.journal.transaction():
            self.journal.db.execute('CREATE TABLE IF NOT EXISTS protection_intents '
                                    '(intent_key TEXT PRIMARY KEY,data TEXT NOT NULL)')
        executor.protection=self
        executor.recovery.protection=self
        executor.context_provider.trigger_aware=True

    def records(self,symbol=None):
        result=[dict(intent_key=r['intent_key'],**json.loads(r['data'])) for r in
                self.journal.db.execute('SELECT * FROM protection_intents ORDER BY rowid')]
        return [r for r in result if symbol is None or r['symbol']==symbol]

    def _fixed_limit_price(self,intent_key):
        record=next((r for r in self.records() if r['intent_key']==intent_key),None)
        return decimal(record['limit_price'],positive=True) if record and record.get('is_market') is False else None

    def _status(self,symbol,status,reason=None,**values):
        record=dict(status=status.value,reason=safe_reason(reason) if reason else None,
                    observed_ms=self.clock_ms(),**values)
        self.states[symbol]=record
        self.journal.event('PROTECTION_'+status.value,self.clock_ms(),symbol=symbol,**record)
        if status not in {ProtectionStatus.ACTIVE,ProtectionStatus.NOT_REQUIRED}:
            self.executor.entries_paused=True
        return record

    def _plan(self,symbol,position,manager,observed_ms):
        self.policy.require()
        managed=manager._open_position if manager else None
        if (managed is None or managed['quantity']!=abs(position.quantity) or
                (managed['side']=='BUY')!=(position.quantity>0)):
            raise ExchangeError('PROTECTION_MANAGEMENT_EVIDENCE_REQUIRED')
        spec=self.executor.client.market(symbol)
        normal=decimal(managed['stop_loss_price'],positive=True)
        atr=decimal(managed['atr_14'],positive=True)
        distance=atr*decimal(self.policy.atr_distance_multiple,positive=True)
        side='SELL' if position.quantity>0 else 'BUY'
        trigger=spec.normalize_price(normal-distance if side=='SELL' else normal+distance,side)
        if side=='SELL' and trigger>=normal or side=='BUY' and trigger<=normal:
            raise ExchangeError('CATASTROPHIC_STOP_INTERFERES_WITH_STRATEGY')
        slip=decimal(self.policy.execution_slippage_fraction,positive=True)
        limit=spec.normalize_price(trigger*(1-slip if side=='SELL' else 1+slip),side)
        liquidation=position.liquidation_price
        if liquidation is not None and (side=='SELL' and trigger<=liquidation or side=='BUY' and trigger>=liquidation):
            raise ExchangeError('PROTECTION_TRIGGER_BEYOND_LIQUIDATION')
        quantity=spec.normalize_size(abs(position.quantity))
        if quantity!=abs(position.quantity):
            raise ExchangeError('PROTECTION_POSITION_PRECISION_CONFLICT')
        return ProtectionPlan(symbol,side,quantity,trigger,limit,normal,
                              self.policy.approval_reference,observed_ms,position.entry_price)

    def _active(self,symbol,plan,order):
        return self._status(symbol,ProtectionStatus.ACTIVE,quantity=str(plan.quantity),
            actual_quantity=str(plan.quantity),position_side='LONG' if plan.side=='SELL' else 'SHORT',
            actual_entry_price=str(plan.actual_entry_price) if plan.actual_entry_price is not None else None,
            normal_strategy_stop=str(plan.normal_strategy_stop),trigger_price=str(plan.trigger_price),
            limit_price=str(plan.limit_price),position_observed_ms=plan.position_observed_ms,
            order_id=str(order['oid']),cloid=order['cloid'],reduce_only=True,
            approval_reference=plan.approval_reference)

    def _discover(self,orders):
        """Reconstruct ownership from durable CLOIDs even if the lifecycle row was lost."""
        owned={}
        unknown=[]
        known={r['cloid']:r for r in self.journal.intents() if
               json.loads(r['request']).get('strategy_id')=='CATASTROPHIC_STOP'}
        for order in orders:
            if not order['isTrigger']:
                continue
            status=self.account._query('orderStatus',oid=order['oid'])
            if not isinstance(status,dict) or status.get('status')!='order':
                raise ExchangeError('PROTECTION_ORDER_IDENTITY_UNVERIFIED')
            detail=status['order']['order']
            if status['order'].get('status')!='open':
                raise ExchangeError('PROTECTION_FRONTEND_STATUS_CONFLICT')
            for field in ('coin','side','sz','limitPx','isTrigger','reduceOnly','triggerPx','orderType'):
                a,b=detail.get(field),order.get(field)
                equal=decimal(a)==decimal(b) if field in {'sz','limitPx','triggerPx'} else a==b
                if not equal:
                    raise ExchangeError('PROTECTION_SNAPSHOT_CONFLICT')
            intent=known.get(detail.get('cloid'))
            if intent is None:
                unknown.append(order)
                continue
            request=json.loads(intent['request'])
            if self._fixed_limit_price(intent['intent_key']) is not None and (
                    detail.get('isPositionTpsl') is True or order.get('isPositionTpsl') is True):
                raise ExchangeError('FIXED_STOP_POSITION_TPSL_CONFLICT')
            if detail.get('coin')!=order['coin'] or request['symbol']!=order['coin'] or str(detail.get('oid'))!=str(order['oid']):
                raise ExchangeError('PROTECTION_ORDER_IDENTITY_CONFLICT')
            owned.setdefault(order['coin'],[]).append(dict(order,intent_key=intent['intent_key'],cloid=intent['cloid']))
            self.journal.update(intent['intent_key'],'OPEN',self.clock_ms(),oid=str(order['oid']),
                                outcome=dict(code='PROTECTION_EXCHANGE_VERIFIED'))
        return owned,unknown

    def _resolve_absent(self,symbol,owned):
        """unknownOid is not absence proof. Never retry an ambiguous signature."""
        live_keys={o['intent_key'] for o in owned}
        for row in self.journal.intents():
            request=json.loads(row['request'])
            if request.get('strategy_id')!='CATASTROPHIC_STOP' or request['symbol']!=symbol or row['intent_key'] in live_keys:
                continue
            if row['state'] not in {'PREPARED','SUBMITTED','UNKNOWN','OPEN','PARTIALLY_FILLED'}:
                continue
            if row['state']=='PREPARED':
                # SUBMITTED is fsynced before any SDK/signing call. A crashed
                # PREPARED attempt therefore has durable non-transmission proof.
                self.journal.update(row['intent_key'],'REJECTED',self.clock_ms(),
                                    outcome=dict(code='PREPARED_NOT_TRANSMITTED',transmitted=False))
                continue
            if row['state']=='PARTIALLY_FILLED' and json.loads(row['outcome'] or '{}').get('remainder_cancelled'):
                continue
            status=self.account._query('orderStatus',oid=row['cloid'])
            if not isinstance(status,dict) or status.get('status')!='order':
                raise ExchangeError('PROTECTION_OUTCOME_UNKNOWN')
            record=status['order']
            detail=record['order']
            if detail.get('cloid')!=row['cloid'] or detail.get('coin')!=symbol:
                raise ExchangeError('PROTECTION_RECOVERY_IDENTITY_CONFLICT')
            terminal=record.get('status')
            if terminal in {'canceled','cancelled'} or isinstance(terminal,str) and terminal.endswith('Canceled'):
                self.journal.update(row['intent_key'],'CANCELLED',self.clock_ms(),oid=str(detail['oid']))
            elif terminal in {'filled','triggered'}:
                fills=self.account.get_fills(start_ms=row['created_ms'],end_ms=self.clock_ms())
                children=detail.get('children',[])
                if not isinstance(children,list):
                    raise ExchangeError('PROTECTION_CHILD_SCHEMA_UNVERIFIED')
                child_ids=[]
                for child in children:
                    oid=child.get('oid') if isinstance(child,dict) else child
                    if type(oid) is not int or oid<0:
                        raise ExchangeError('PROTECTION_CHILD_SCHEMA_UNVERIFIED')
                    child_status=self.account._query('orderStatus',oid=oid)
                    if not isinstance(child_status,dict) or child_status.get('status')!='order':
                        raise ExchangeError('PROTECTION_CHILD_OUTCOME_UNKNOWN')
                    child_record=child_status['order']
                    child_detail=child_record['order']
                    child_state=child_record.get('status','')
                    if (child_detail.get('coin')!=symbol or child_detail.get('oid')!=oid or
                        child_detail.get('side')!=('A' if request['side']=='SELL' else 'B') or
                        child_detail.get('reduceOnly') is not True or child_state not in {'filled','canceled','rejected'} and
                        not child_state.endswith(('Canceled','Rejected'))):
                        raise ExchangeError('PROTECTION_TRIGGER_REMAINDER_REQUIRES_RECONCILIATION')
                    child_ids.append(str(oid))
                identities={str(detail['oid']),*child_ids}
                if any(str(o['oid']) in identities for o in self.account.get_open_orders()):
                    raise ExchangeError('PROTECTION_TRIGGER_REMAINDER_STILL_OPEN')
                matched=[f for f in fills if f.symbol==symbol and f.order_id in identities]
                quantity=sum((f.quantity for f in matched),Decimal(0))
                requested=decimal(request['quantity'])
                if any(f.side!=request['side'] for f in matched) or quantity>requested:
                    raise ExchangeError('PROTECTION_FILL_EVIDENCE_CONFLICT')
                limit=self._fixed_limit_price(row['intent_key'])
                if limit is not None and any(f.price<limit if request['side']=='SELL' else f.price>limit for f in matched):
                    raise ExchangeError('PROTECTION_FIXED_LIMIT_FILL_CONFLICT')
                if quantity<requested and (terminal=='filled' or not child_ids):
                    raise ExchangeError('PROTECTION_FILL_EVIDENCE_REQUIRED')
                self.journal.update(row['intent_key'],'FILLED' if quantity==requested else 'PARTIALLY_FILLED',
                    self.clock_ms(),oid=str(detail['oid']),outcome=dict(filled_quantity=quantity,
                        remaining_quantity=requested-quantity,remainder_cancelled=True,child_order_ids=child_ids,
                        code='PROTECTION_TRIGGER_EXECUTION_VERIFIED'))
            elif terminal=='rejected' or isinstance(terminal,str) and terminal.endswith('Rejected'):
                self.journal.update(row['intent_key'],'REJECTED',self.clock_ms(),oid=str(detail['oid']))
            else:
                raise ExchangeError('PROTECTION_OUTCOME_UNKNOWN')

    @staticmethod
    def _matches(order,plan):
        return (order.get('isTrigger') is True and order.get('reduceOnly') is True and
            order.get('side')==('A' if plan.side=='SELL' else 'B') and
            decimal(order['sz'])==plan.quantity and decimal(order['triggerPx'])==plan.trigger_price and
            decimal(order['limitPx'])==plan.limit_price and
            order.get('orderType') in {'Stop Market','StopMarket'})

    def _cancel(self,symbol,orders):
        for order in orders:
            self._status(symbol,ProtectionStatus.OBSOLETE,order_id=str(order['oid']))
            result=self.executor.cancel_protection(symbol,order['oid'],order['intent_key'])
            if result.code not in {'CANCELLED','SUCCESS','ALLOWED'} and result.state.value not in {'CANCELLED'}:
                raise ExchangeError('PROTECTION_CANCEL_UNCERTAIN')
        remaining=self.account.get_frontend_open_orders()
        if any(str(o['oid']) in {str(r['oid']) for r in orders} for o in remaining):
            raise ExchangeError('OBSOLETE_PROTECTION_STILL_OPEN')
        for order in orders:
            self.journal.update(order['intent_key'],'CANCELLED',self.clock_ms(),oid=str(order['oid']))
        self.journal.event('PROTECTION_CANCELLED',self.clock_ms(),symbol=symbol,verified=True)

    def ensure_all(self,*,allow_actions=True):
        with self.executor.lock,self.lock:
            if self.running:
                return self.report()
            self.running=True
            try:
                positions=self.account.get_positions()
                observed=self.clock_ms()
                orders=self.account.get_frontend_open_orders()
                owned,unknown=self._discover(orders)
                self.states.pop('__account__',None)
                symbols=set(positions)|set(owned)|set(self.managers)|set(self.states)|{r['symbol'] for r in self.records()}|{
                    json.loads(r['request'])['symbol'] for r in self.journal.intents() if
                    json.loads(r['request']).get('strategy_id')=='CATASTROPHIC_STOP'}
                for symbol in sorted(symbols):
                    try:
                        current=owned.get(symbol,[])
                        self._resolve_absent(symbol,current)
                        if any(o['coin']==symbol for o in unknown):
                            raise ExchangeError('UNRECOGNIZED_TRIGGER_REQUIRES_MANUAL_REVIEW')
                        position=positions.get(symbol)
                        if position is None or not position.quantity:
                            if current:
                                if not allow_actions:
                                    self._status(symbol,ProtectionStatus.OBSOLETE,'FLAT_WITH_OPEN_PROTECTION')
                                    continue
                                self._cancel(symbol,current)
                            self._status(symbol,ProtectionStatus.NOT_REQUIRED)
                            continue
                        if len(current)>1:
                            raise ExchangeError('DUPLICATE_PROTECTION_REQUIRES_MANUAL_REVIEW')
                        plan=self._plan(symbol,position,self.managers.get(symbol),observed)
                        # The 5 s window runs from this symbol's own confirmation read, not from the
                        # shared snapshot: with five legs, every symbol after the first used to fail
                        # STALE on read latency alone (27 Oct), and each failure cost two re-check reads.
                        confirmed=self.clock_ms()
                        fresh_position=self.account.get_position(symbol)
                        if (fresh_position is None or fresh_position.quantity!=position.quantity or
                            fresh_position.entry_price!=position.entry_price or not 0<=self.clock_ms()-confirmed<=5000):
                            raise ExchangeError('PROTECTION_POSITION_CHANGED_OR_STALE')
                        plan=replace(plan,position_observed_ms=confirmed)
                        if current and self._matches(current[0],plan):
                            self._active(symbol,plan,current[0])
                            continue
                        if not allow_actions:
                            self._status(symbol,ProtectionStatus.PARTIAL if current else ProtectionStatus.MISSING,
                                         'PROTECTION_REPAIR_REQUIRED')
                            continue
                        old=current[0] if current else None
                        if old and (old['side']!=('A' if plan.side=='SELL' else 'B') or old['reduceOnly'] is not True):
                            self._cancel(symbol,current)
                            old=None
                        keys={r['intent_key'] for r in self.journal.intents()}|{
                            r['intent_key'] for r in self.records(symbol)}
                        generation=0
                        while 'protection:'+symbol+':'+str(generation) in keys:
                            generation+=1
                        key='protection:'+symbol+':'+str(generation)
                        with self.journal.transaction():
                            self.journal.db.execute('INSERT INTO protection_intents VALUES (?,?)',
                                (key,canonical(safe_data(asdict(plan)))))
                        self._status(symbol,ProtectionStatus.PENDING,intent_key=key,quantity=str(plan.quantity))
                        result=self.executor.submit_protection(plan,key,modify_oid=old['oid'] if old else None)
                        if result.state.value in {'UNKNOWN','SUBMITTED','PREPARED','REJECTED'}:
                            raise ExchangeError('PROTECTION_SUBMISSION_'+result.state.value)
                        verified=self.account.get_frontend_open_orders()
                        verified_owned,_=self._discover(verified)
                        actual=verified_owned.get(symbol,[])
                        fresh_position=self.account.get_position(symbol)
                        if (fresh_position is None or fresh_position.quantity!=position.quantity or len(actual)!=1 or
                                not self._matches(actual[0],plan)):
                            raise ExchangeError('PROTECTION_POST_ACTION_VERIFICATION_REQUIRED')
                        if old:
                            self.journal.update(old['intent_key'],'CANCELLED',self.clock_ms(),oid=str(old['oid']))
                        self._active(symbol,plan,actual[0])
                    except Exception as exc:
                        self._status(symbol,ProtectionStatus.ERROR,str(exc))
                self.last_verified_ms=self.clock_ms()
            except Exception as exc:
                for symbol in (set(self.managers)|set(self.states))-{'__account__'}:
                    previous=self.states.get(symbol,{})
                    self._status(symbol,ProtectionStatus.ERROR,'PROTECTION_DISCOVERY_FAILED:'+type(exc).__name__,
                        last_known_status=previous.get('status'),last_known_verified_ms=previous.get('observed_ms'))
                self._status('__account__',ProtectionStatus.ERROR,'PROTECTION_DISCOVERY_FAILED:'+type(exc).__name__)
            finally:
                self.running=False
            return self.report()

    def recover_order_identities(self):
        """Public reads before fill reconciliation, including trigger child IDs."""
        with self.executor.lock,self.lock:
            owned,_=self._discover(self.account.get_frontend_open_orders())
            symbols={json.loads(r['request'])['symbol'] for r in self.journal.intents()
                     if json.loads(r['request']).get('strategy_id')=='CATASTROPHIC_STOP'}
            for symbol in symbols:
                self._resolve_absent(symbol,owned.get(symbol,[]))

    @property
    def healthy(self):
        return (self.last_verified_ms is not None and 0<=self.clock_ms()-self.last_verified_ms<=5000 and
            all(r['status'] in {'ACTIVE','NOT_REQUIRED'} for r in self.states.values()))

    @property
    def entries_allowed(self):
        try:
            self.policy.require()
            return self.healthy
        except ExchangeError:
            return False

    def flat_clear(self,symbol):
        self.ensure_all()
        return self.states.get(symbol,{}).get('status')=='NOT_REQUIRED'

    def report(self):
        return dict(policy=asdict(self.policy),healthy=self.healthy,entries_allowed=self.entries_allowed,
                    last_verified_ms=self.last_verified_ms,positions=dict(self.states),
                    accounting_source='EXCHANGE_REPORTED',normal_strategy_stop_changed=False)
