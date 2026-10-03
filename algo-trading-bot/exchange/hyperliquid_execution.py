"""Validated official-SDK execution. Default construction remains locked."""
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
import json
import threading

import order_guard
from .base_exchange import ExchangeError, decimal
from .exchange_rules import RiskPermission
from .order_lifecycle import OrderRequest, OrderState, parse_exchange_action_result
from .sdk_transport import OfflineSDKTransport, sdk_number
from .reliability_policy import RequestPriority


@dataclass(frozen=True)
class LiveOrder:
    cloid: str
    intent_key: str
    candidate_id: str
    request: OrderRequest
    state: OrderState
    exchange_order_id: str | None = None
    filled_quantity: Decimal = Decimal(0)
    average_price: Decimal | None = None
    remaining_quantity: Decimal = Decimal(0)
    remainder_cancelled: bool = False
    code: str | None = None
    reason: str | None = None
    execution_mode: str = 'LIVE_TESTNET'
    source: str = 'EXCHANGE_RESPONSE_SUMMARY_NOT_ACCOUNTING_FILL'


class HyperliquidExecution:
    is_live = True
    venue = 'HYPERLIQUID_TESTNET'

    def __init__(self, client, *, transport=None, account=None, journal=None,
                 context_provider=None, validator=None, recovery=None,
                 clock_health=None, rate_limits=None):
        self.client = client
        self.transport = transport
        self.account = account
        self.journal = journal
        self.context_provider = context_provider
        self.validator = validator
        self.recovery = recovery
        self.clock_health = clock_health
        self.rate_limits = rate_limits
        self.entries_paused = True
        self.exit_intents = {}
        self.lock = threading.RLock()
        self.protection=None

    def _require(self):
        if self.transport is None:
            order_guard.require_exchange_orders(self.venue)
        elif type(self.transport) is not OfflineSDKTransport:
            self.transport.authorization.require(self.transport.team_address,
                                                 self.transport.signer_address)

    def _dependencies(self):
        if any(x is None for x in (self.transport, self.account, self.journal,
                self.context_provider, self.validator, self.recovery,
                self.clock_health, self.rate_limits)):
            raise ExchangeError('LIVE_INFRASTRUCTURE_REQUIRED')
        if not (self.account.team_address.lower() == self.transport.team_address.lower() ==
                self.journal.team_address):
            raise ExchangeError('TEAM_ACCOUNT_IDENTITY_MISMATCH')

    def _guard(self, context, checked_ms, *, critical=False, entry=False):
        self._require()
        self.clock_health.require()
        if not self.transport.nonces.healthy:
            raise ExchangeError('NONCE_SIGNING_DEGRADED')
        if entry and (self.entries_paused or not self.rate_limits.entries_allowed or
                self.protection is not None and not self.protection.entries_allowed):
            raise ExchangeError('ENTRY_RELIABILITY_GATE_REQUIRED')
        startup=getattr(self.recovery,'startup_coordinator',None)
        if entry and startup is not None and not startup.entry_ready:
            raise ExchangeError('STARTUP_ENTRY_LOCK_REQUIRED')
        now = self.client.clock_ms()
        if (not self.client.ready or not 0 <= now-checked_ms <= 5000 or
                not context.readiness.account_ready or
                context.readiness.agent_expiry_ms is None or
                context.readiness.agent_expiry_ms <= now or
                (not critical and (not self.context_provider.feed_ready() or now < self.rate_limits.backoff_until))):
            raise ExchangeError('SIGNING_READINESS_REVOKED')

    def preview_order(self, symbol, side, quantity, price, *, reduce_only=False, tif='Gtc'):
        return self.client.market(symbol).normalize_order(side, quantity, price,
                                                        reduce_only=reduce_only, tif=tif)

    def preview_request(self, request):
        return self.preview_order(request.symbol, request.side, request.quantity, request.price,
                                  reduce_only=request.reduce_only, tif=request.tif)

    def _restore_order(self, row):
        data = json.loads(row['request'])
        request = OrderRequest(**data)
        outcome = json.loads(row['outcome']) if row['outcome'] else {}
        try:
            state = OrderState(row['state'])
        except ValueError:
            state = OrderState.UNKNOWN
        return LiveOrder(row['cloid'], row['intent_key'], row['candidate'], request, state,
            row['oid'], decimal(outcome.get('filled_quantity','0'), nonnegative=True),
            decimal(outcome['average_price'], positive=True) if outcome.get('average_price') else None,
            decimal(outcome.get('remaining_quantity', request.quantity), nonnegative=True),
            bool(outcome.get('remainder_cancelled',False)), outcome.get('code'), outcome.get('reason'),
            'OFFLINE_SIGNED_FIXTURE' if type(self.transport) is OfflineSDKTransport else 'LIVE_TESTNET')

    def _after_action(self):
        try:
            report = self.recovery.recover()
            self.entries_paused = not report.ready or not self.context_provider.feed_ready()
            self.entries_paused |= (not self.transport.nonces.healthy or not self.rate_limits.entries_allowed or
                any(r['state']=='UNKNOWN' for r in self.journal.management_actions()))
            startup=getattr(self.recovery,'startup_coordinator',None)
            self.entries_paused |= startup is not None and startup.state.value!='READY'
            if self.protection is not None and not self.protection.running:
                self.protection.ensure_all(allow_actions=report.ready)
                self.entries_paused |= not self.protection.entries_allowed
            self.journal.event('POST_ACTION_RECONCILIATION', self.client.clock_ms(),
                               ready=report.ready, reasons=report.reasons)
        except Exception as exc:
            self.entries_paused = True
            self.journal.event('RECONCILIATION_FAILED', self.client.clock_ms(),
                               error_type=type(exc).__name__)

    def _validated(self, request, permission, *, critical=False):
        try:
            context = self.context_provider.load(request,critical=True) if critical else self.context_provider.load(request)
        except Exception as exc:
            self.entries_paused = True
            self.journal.event('EXCHANGE_CONTEXT_UNAVAILABLE',self.client.clock_ms(),
                               error_type=type(exc).__name__)
            raise ExchangeError('EXCHANGE_CONTEXT_UNAVAILABLE') from None
        result = self.validator.validate(request, context, permission, self.client.clock_ms())
        if result.allowed and not request.reduce_only and self.protection is not None:
            for symbol,position in context.positions.items():
                state=self.protection.states.get(symbol,{})
                managed=self.protection.managers.get(symbol)
                held=managed._open_position if managed else None
                if (state.get('status')!='ACTIVE' or decimal(state.get('actual_quantity','0'))!=abs(position.quantity) or
                    state.get('position_side')!=('LONG' if position.quantity>0 else 'SHORT') or held is None or
                    held['quantity']!=abs(position.quantity) or (held['side']=='BUY')!=(position.quantity>0)):
                    self.entries_paused=True
                    self.journal.event('ENTRY_ACTUAL_PROTECTION_MISMATCH',self.client.clock_ms(),symbol=symbol,
                                       actual_quantity=str(position.quantity))
                    raise ExchangeError('ACTUAL_POSITION_PROTECTION_REQUIRED')
            if any(getattr(m,'has_open_position',False) and s not in context.positions
                   for s,m in self.protection.managers.items()):
                self.entries_paused=True
                raise ExchangeError('ACTUAL_POSITION_MANAGEMENT_RECONCILIATION_REQUIRED')
        self.journal.event('EXCHANGE_VALIDATION', self.client.clock_ms(),
                           candidate_id=getattr(permission,'candidate_id',None),
                           request=asdict(request), validation=asdict(result))
        if not result.allowed:
            if result.code in {'STALE_METADATA','MARKET_METADATA_CHANGED','ACCOUNT_NOT_READY',
                               'STALE_ACCOUNT_STATE','STALE_MARKET_DATA','DATA_NOT_READY'}:
                self.entries_paused = True
            raise ExchangeError(result.code)
        request = replace(request, quantity=result.normalized.quantity, price=result.normalized.price)
        return request, context, result

    def submit(self, request, *, permission=None):
        self._require()
        self._dependencies()
        with self.lock:
            if not isinstance(permission, RiskPermission):
                raise ExchangeError('RISK_PERMISSION_REQUIRED')
            key = request.client_order_id or ':'.join((permission.candidate_id, request.strategy_id,
                                                       request.side, 'exit' if request.reduce_only else 'entry'))
            prior = self.journal.intent(key)
            if prior:
                # Never re-sign any durable attempt, including an ambiguous one.
                if (prior['candidate'] != permission.candidate_id or
                        OrderRequest(**json.loads(prior['request'])) != replace(request,
                            quantity=self.client.market(request.symbol).normalize_size(request.quantity),
                            price=self.client.market(request.symbol).normalize_price(request.price,request.side))):
                    raise ExchangeError('CLOID_INTENT_CONFLICT')
                return self._restore_order(prior)
            if self.entries_paused and not request.reduce_only:
                raise ExchangeError('ENTRY_PAUSED')
            startup=getattr(self.recovery,'startup_coordinator',None)
            if not request.reduce_only and startup is not None and not startup.entry_ready:
                self.entries_paused=True
                raise ExchangeError('STARTUP_ENTRY_LOCK_REQUIRED')
            request, context, result = self._validated(request, permission,critical=request.reduce_only)
            if not request.reduce_only and (not self.rate_limits.entries_allowed or
                    self.protection is not None and not self.protection.entries_allowed):
                self.entries_paused=True
                raise ExchangeError('ENTRY_RELIABILITY_GATE_REQUIRED')
            row, fresh = self.journal.reserve(key, asdict(request), permission.candidate_id,
                                              self.client.clock_ms())
            if not fresh:
                return self._restore_order(row)
            wire, action = self.transport.order_action(request, row['cloid'])
            self._reserve_intent_action(key,creates_order=True,
                priority=RequestPriority.SAFETY if request.reduce_only else RequestPriority.EXECUTION,
                kind='strategy_exit' if request.reduce_only else 'entry')
            self.journal.update(key, 'SUBMITTED', self.client.clock_ms())
            self.journal.event('SIGNED_ATTEMPT', self.client.clock_ms(), intent_key=key,
                               cloid=row['cloid'], candidate_id=permission.candidate_id,
                               risk_permission=asdict(permission), validation=result.audit)
            from hyperliquid.utils.types import Cloid
            try:
                response = self.transport.perform('order',
                    (request.symbol, wire['is_buy'], wire['sz'], wire['limit_px'], wire['order_type']),
                    dict(reduce_only=request.reduce_only, cloid=Cloid.from_str(row['cloid'])),
                    action, lambda: self._guard(context,result.checked_ms,critical=request.reduce_only,
                                                entry=not request.reduce_only))
                outcome = parse_exchange_action_result(response, [request])[0]
                self.journal.update(key, outcome.state.value, self.client.clock_ms(),
                                    oid=outcome.exchange_order_id, outcome=asdict(outcome))
                self.journal.event('EXCHANGE_ORDER_RESULT',self.client.clock_ms(),
                    intent_key=key,cloid=row['cloid'],candidate_id=permission.candidate_id,
                    request_timestamp_ms=row['created_ms'],response_timestamp_ms=self.client.clock_ms(),
                    outcome=asdict(outcome),request_status=response.get('status'))
                if outcome.code=='RATE_LIMITED':
                    self.rate_limits.error()
                elif outcome.code=='NONCE_ERROR':
                    self.transport.nonces.degrade()
                else:
                    self.rate_limits.success()
            except Exception as exc:
                self.journal.update(key, 'UNKNOWN', self.client.clock_ms(),
                                    outcome=dict(code='TRANSMISSION_UNCERTAIN',reason=type(exc).__name__))
                self.entries_paused = True
                self.rate_limits.error(status=getattr(exc,'status_code',None))
                self.journal.event('EXCHANGE_ORDER_RESULT',self.client.clock_ms(),
                    intent_key=key,cloid=row['cloid'],candidate_id=permission.candidate_id,
                    state='UNKNOWN',code='TRANSMISSION_UNCERTAIN',error_type=type(exc).__name__)
                self.journal.event('AMBIGUOUS_ORDER_RESULT',self.client.clock_ms(),intent_key=key,
                                   blind_retry=False,cloid=row['cloid'])
            self._after_action()
            outcome_code=json.loads(self.journal.intent(key)['outcome'] or '{}').get('code')
            if self.journal.intent(key)['state']=='UNKNOWN' or outcome_code in {'RATE_LIMITED','NONCE_ERROR','API_WALLET_NOT_APPROVED'}:
                self.entries_paused = True
            return self._restore_order(self.journal.intent(key))

    submit_order = submit

    def _reserve_intent_action(self,key,**parameters):
        try:
            self.rate_limits.reserve_action(**parameters)
        except ExchangeError:
            # Durable proof that the attempt stopped before SDK/signing/sending.
            self.journal.update(key,'REJECTED',self.client.clock_ms(),
                                outcome=dict(code='LOCAL_API_CAPACITY_DENIED',transmitted=False))
            self.entries_paused=True
            raise

    def place_order(self, symbol, side=None, quantity=None, price=None, *, reduce_only=False,
                    tif='Gtc', permission=None, client_order_id=None, strategy_id='VWAP_BASELINE'):
        self._require()
        request = symbol if isinstance(symbol,OrderRequest) else OrderRequest(
            symbol,side,quantity,price,reduce_only=reduce_only,tif=tif,
            client_order_id=client_order_id,strategy_id=strategy_id)
        return self.submit(request,permission=permission)

    def recover_uncertain(self, intent_key):
        """Read only; unknownOid is not sufficient proof of absence for resubmission."""
        self._dependencies()
        with self.lock:
            self.entries_paused = True
            row = self.journal.intent(intent_key)
            if row is None:
                raise ExchangeError('UNKNOWN_DURABLE_INTENT')
            request = OrderRequest(**json.loads(row['request']))
            status = self.account._query('orderStatus', oid=row['cloid'])
            orders = self.account.get_open_orders()
            fills = self.account.get_fills(start_ms=row['created_ms'],end_ms=self.client.clock_ms())
            if isinstance(status,dict) and status.get('status')=='order':
                record = status['order']
                detail = record['order']
                if detail.get('coin')!=request.symbol or detail.get('cloid')!=row['cloid']:
                    raise ExchangeError('RECOVERY_IDENTITY_MISMATCH')
                oid = detail['oid']
                if type(oid) is not int or oid<0:
                    raise ExchangeError('INVALID_ORDER_ID')
                matched = [f for f in fills if f.symbol==request.symbol and f.order_id==str(oid)]
                quantity = sum((f.quantity for f in matched),Decimal(0))
                if quantity>request.quantity or any(f.side!=request.side for f in matched):
                    raise ExchangeError('RECOVERY_FILL_CONFLICT')
                average = sum((f.quantity*f.price for f in matched),Decimal(0))/quantity if quantity else None
                open_now = any(o['coin']==request.symbol and str(o['oid'])==str(oid) for o in orders)
                terminal = record.get('status')
                state = (OrderState.FILLED if quantity==request.quantity else
                         OrderState.PARTIALLY_FILLED if quantity else OrderState.OPEN if open_now else
                         OrderState.CANCELLED if terminal in {'canceled','cancelled'} else
                         OrderState.REJECTED if terminal=='rejected' else OrderState.UNKNOWN)
                if terminal=='filled' and not quantity:
                    state=OrderState.UNKNOWN
                self.journal.update(intent_key,state.value,self.client.clock_ms(),oid=str(oid),
                    outcome=dict(filled_quantity=quantity,average_price=average,
                                 remaining_quantity=request.quantity-quantity,
                                 remainder_cancelled=not open_now and quantity<request.quantity,
                                 code='ACCOUNT_EVIDENCE_RECOVERY'))
            self.journal.event('CLOID_RECOVERY',self.client.clock_ms(),intent_key=intent_key,
                               status=status,blind_retry=False)
            self._after_action()
            if self.journal.intent(intent_key)['state'] in {'UNKNOWN','SUBMITTED','PREPARED'}:
                self.entries_paused=True
            return self._restore_order(self.journal.intent(intent_key))

    def _own_order(self, symbol, order_id):
        self.client.market(symbol)
        rows = [o for o in self.account.get_open_orders() if o['coin']==symbol and str(o['oid'])==str(order_id)]
        if len(rows)!=1:
            raise ExchangeError('TEAM_OPEN_ORDER_REQUIRED')
        return rows[0]

    def _management_action(self, method, args, action, context, *, kwargs=None, critical=False):
        checked_ms = self.client.clock_ms()
        if self.journal.pending_management(action):
            raise ExchangeError('MANAGEMENT_UNCERTAINTY_RECOVERY_REQUIRED')
        if not context.readiness.account_ready:
            raise ExchangeError('ACCOUNT_NOT_READY')
        action_id=self.journal.reserve_management(action,checked_ms)
        try:
            self.rate_limits.reserve_action(priority=RequestPriority.SAFETY if critical else RequestPriority.EXECUTION,
                                            kind=action['type'])
        except ExchangeError:
            self.journal.update_management(action_id,'REJECTED_BEFORE_TRANSMISSION',self.client.clock_ms())
            raise
        self.journal.event('MANAGEMENT_ATTEMPT',checked_ms,action=action,action_id=action_id)
        try:
            response=self.transport.perform(method,args,kwargs or {},action,
                                             lambda:self._guard(context,checked_ms,critical=critical))
            outcome=parse_exchange_action_result(response,[None],action=action['type'])[0]
            if outcome.code=='NONCE_ERROR':
                self.transport.nonces.degrade()
            self.journal.update_management(action_id,outcome.state.value,self.client.clock_ms())
            self.rate_limits.success()
        except Exception as exc:
            self.entries_paused=True
            self.rate_limits.error()
            self.journal.event('MANAGEMENT_UNCERTAIN',self.client.clock_ms(),
                               action=action,action_id=action_id,error_type=type(exc).__name__,blind_retry=False)
            raise ExchangeError('MANAGEMENT_ACTION_UNCERTAIN') from None
        finally:
            self._after_action()
        self.journal.event('MANAGEMENT_RESULT',self.client.clock_ms(),action=action,outcome=asdict(outcome))
        return outcome

    def recover_management_action(self,action_id):
        """Read-only authoritative verification; unknownOid never clears ambiguity."""
        self._dependencies()
        with self.lock:
            row=next((r for r in self.journal.management_actions() if r['id']==action_id),None)
            if row is None:
                raise ExchangeError('UNKNOWN_MANAGEMENT_ACTION')
            if row['state']!='UNKNOWN':
                return row['state']
            action=json.loads(row['action'])
            confirmed=False
            if action['type'] in {'cancel','cancelByCloid'}:
                item=action['cancels'][0]
                identity=item.get('o',item.get('cloid'))
                status=self.account._query('orderStatus',oid=identity)
                orders=self.account.get_open_orders()
                if isinstance(status,dict) and status.get('status')=='order':
                    record=status['order']
                    detail=record['order']
                    asset=item.get('a',item.get('asset'))
                    if self.client.market(detail['coin']).asset_id!=asset or (
                            'o' in item and str(detail['oid'])!=str(identity) or
                            'cloid' in item and detail.get('cloid')!=identity):
                        raise ExchangeError('MANAGEMENT_RECOVERY_IDENTITY_CONFLICT')
                    terminal=record.get('status','')
                    confirmed=(terminal in {'canceled','cancelled','filled'} or terminal.endswith('Canceled')) and not any(
                        str(o['oid'])==str(detail['oid']) for o in orders)
            elif action['type']=='updateLeverage':
                symbol=next((s for s,p in self.client.markets.items() if p.asset_id==action['asset']),None)
                active=self.account._query('activeAssetData',coin=symbol,priority=RequestPriority.SAFETY)
                confirmed=(active.get('user','').lower()==self.account.team_address.lower() and
                    active.get('coin')==symbol and active.get('leverage')==dict(type='cross',value=action['leverage']))
            self.account.get_positions()
            if confirmed:
                self.journal.update_management(action_id,'CONFIRMED_BY_ACCOUNT',self.client.clock_ms())
            self.journal.event('MANAGEMENT_RECOVERY',self.client.clock_ms(),action_id=action_id,
                               confirmed=confirmed,blind_retry=False)
            self._after_action()
            return 'CONFIRMED_BY_ACCOUNT' if confirmed else 'UNKNOWN'

    def cancel_order(self, symbol, order_id):
        self._require()
        self._dependencies()
        with self.lock:
            own=self._own_order(symbol,order_id)
            request=OrderRequest(symbol,'BUY' if own['side']=='B' else 'SELL',own['sz'],own['limitPx'])
            context=self.context_provider.load(request)
            action=dict(type='cancel',cancels=[dict(a=self.client.market(symbol).asset_id,o=int(own['oid']))])
            return self._management_action('cancel',(symbol,int(own['oid'])),action,context)

    def cancel_by_cloid(self, symbol, cloid):
        self._require()
        self._dependencies()
        from hyperliquid.utils.types import Cloid
        with self.lock:
            parsed=Cloid.from_str(cloid)
            status=self.account._query('orderStatus',oid=cloid)
            if not isinstance(status,dict) or status.get('status')!='order':
                raise ExchangeError('TEAM_OPEN_ORDER_REQUIRED')
            own=status['order']['order']
            if own.get('coin')!=symbol or own.get('cloid')!=cloid or status['order'].get('status')!='open':
                raise ExchangeError('TEAM_OPEN_ORDER_REQUIRED')
            self._own_order(symbol,own['oid'])
            request=OrderRequest(symbol,'BUY' if own['side']=='B' else 'SELL',own['sz'],own['limitPx'])
            context=self.context_provider.load(request)
            action=dict(type='cancelByCloid',cancels=[dict(asset=self.client.market(symbol).asset_id,cloid=cloid)])
            return self._management_action('cancel_by_cloid',(symbol,parsed),action,context)

    def modify_order(self, symbol, order_id, *, request=None, permission=None, **parameters):
        self._require()
        self._dependencies()
        with self.lock:
            self._own_order(symbol,order_id)
            if not isinstance(request,OrderRequest) or request.symbol!=symbol:
                raise ExchangeError('REPLACEMENT_REQUEST_REQUIRED')
            if self.entries_paused and not request.reduce_only:
                raise ExchangeError('ENTRY_PAUSED')
            normalized,context,result=self._validated(request,permission,critical=request.reduce_only)
            key='modify:'+str(order_id)+':'+permission.candidate_id
            row,fresh=self.journal.reserve(key,asdict(normalized),permission.candidate_id,self.client.clock_ms())
            if not fresh:
                return self._restore_order(row)
            wire,action=self.transport.order_action(normalized,row['cloid'])
            action=dict(type='batchModify',modifies=[dict(oid=int(order_id),order=action['orders'][0])])
            self._reserve_intent_action(key,kind='modify',priority=RequestPriority.SAFETY if normalized.reduce_only
                                        else RequestPriority.EXECUTION)
            self.journal.update(key,'SUBMITTED',self.client.clock_ms())
            from hyperliquid.utils.types import Cloid
            try:
                response=self.transport.perform('modify_order',
                    (int(order_id),symbol,wire['is_buy'],wire['sz'],wire['limit_px'],wire['order_type']),
                    dict(reduce_only=normalized.reduce_only,cloid=Cloid.from_str(row['cloid'])),action,
                    lambda:self._guard(context,result.checked_ms,critical=normalized.reduce_only,
                                       entry=not normalized.reduce_only))
                outcome=parse_exchange_action_result(response,[normalized],action='batchModify')[0]
                if outcome.code=='NONCE_ERROR':
                    self.transport.nonces.degrade()
                self.journal.update(key,outcome.state.value,self.client.clock_ms(),
                                    oid=outcome.exchange_order_id,outcome=asdict(outcome))
                self.rate_limits.success()
            except Exception as exc:
                self.journal.update(key,'UNKNOWN',self.client.clock_ms(),
                                    outcome=dict(code='TRANSMISSION_UNCERTAIN',reason=type(exc).__name__))
                self.entries_paused=True
                self.rate_limits.error()
            self._after_action()
            if self.journal.intent(key)['state']=='UNKNOWN':
                self.entries_paused=True
            return self._restore_order(self.journal.intent(key))

    def submit_protection(self, plan, intent_key, *, modify_oid=None):
        """Official SDK trigger path; every attempt shares auth, validation and nonce gates."""
        self._require()
        self._dependencies()
        from .position_protection import ProtectionPlan
        from hyperliquid.utils.types import Cloid
        if not isinstance(plan,ProtectionPlan) or self.protection is None:
            raise ExchangeError('APPROVED_PROTECTION_MANAGER_REQUIRED')
        with self.lock:
            prior=self.journal.intent(intent_key)
            if prior is not None:
                return self._restore_order(prior)
            if not 0<=self.client.clock_ms()-plan.position_observed_ms<=5000:
                raise ExchangeError('STALE_PROTECTION_POSITION')
            request=OrderRequest(plan.symbol,plan.side,plan.quantity,plan.limit_price,
                reduce_only=True,strategy_id='CATASTROPHIC_STOP',client_order_id=intent_key)
            permission=RiskPermission(intent_key,plan.symbol,plan.side,plan.quantity,self.client.clock_ms(),
                True,'CATASTROPHIC_STOP',plan.limit_price)
            normalized,context,result=self._validated(request,permission,critical=True)
            position=context.positions.get(plan.symbol)
            if position is None:
                raise ExchangeError('PROTECTION_FLAT_POSITION')
            expected=self.protection._plan(plan.symbol,position,self.protection.managers.get(plan.symbol),
                                           plan.position_observed_ms)
            if expected!=plan or (plan.side=='SELL' and plan.trigger_price>=context.quote.mark or
                                 plan.side=='BUY' and plan.trigger_price<=context.quote.mark):
                raise ExchangeError('PROTECTION_GEOMETRY_OR_POSITION_CHANGED')
            if modify_oid is not None:
                self._own_order(plan.symbol,modify_oid)
            row,_=self.journal.reserve(intent_key,asdict(normalized),intent_key,self.client.clock_ms())
            order_type={'trigger':{'triggerPx':sdk_number(plan.trigger_price),'isMarket':True,'tpsl':'sl'}}
            wire,action=self.transport.order_action(normalized,row['cloid'],order_type=order_type)
            method='order'
            args=(plan.symbol,wire['is_buy'],wire['sz'],wire['limit_px'],wire['order_type'])
            if modify_oid is not None:
                method='modify_order'
                args=(int(modify_oid),*args)
                action=dict(type='batchModify',modifies=[dict(oid=int(modify_oid),order=action['orders'][0])])
            self._reserve_intent_action(intent_key,creates_order=modify_oid is None,priority=RequestPriority.SAFETY,
                                        kind='protection_modify' if modify_oid is not None else 'protection_create')
            self.journal.update(intent_key,'SUBMITTED',self.client.clock_ms())
            self.journal.event('PROTECTION_SUBMITTED',self.client.clock_ms(),intent_key=intent_key,
                               cloid=row['cloid'],plan=asdict(plan),modify_oid=modify_oid)
            try:
                response=self.transport.perform(method,args,dict(reduce_only=True,cloid=Cloid.from_str(row['cloid'])),
                    action,lambda:self._guard(context,result.checked_ms,critical=True))
                outcome=parse_exchange_action_result(response,[normalized],action=action['type'])[0]
                self.journal.update(intent_key,outcome.state.value,self.client.clock_ms(),
                                    oid=outcome.exchange_order_id,outcome=asdict(outcome))
                if outcome.code=='NONCE_ERROR':
                    self.transport.nonces.degrade()
                elif outcome.code=='RATE_LIMITED':
                    self.rate_limits.error()
                else:
                    self.rate_limits.success()
            except Exception as exc:
                self.journal.update(intent_key,'UNKNOWN',self.client.clock_ms(),
                                    outcome=dict(code='TRANSMISSION_UNCERTAIN',reason=type(exc).__name__))
                self.rate_limits.error(status=getattr(exc,'status_code',None))
                self.entries_paused=True
                self.journal.event('PROTECTION_UNCERTAIN',self.client.clock_ms(),intent_key=intent_key,
                                   blind_retry=False,error_type=type(exc).__name__)
                self.journal.event('AMBIGUOUS_ORDER_RESULT',self.client.clock_ms(),intent_key=intent_key,
                                   classification='CATASTROPHIC_STOP',blind_retry=False)
            self._after_action()
            return self._restore_order(self.journal.intent(intent_key))

    def cancel_protection(self,symbol,order_id,intent_key):
        self._require()
        self._dependencies()
        with self.lock:
            row=self.journal.intent(intent_key)
            if row is None or row['state']=='UNKNOWN':
                raise ExchangeError('PROTECTION_CANCEL_RECOVERY_REQUIRED')
            own=self._own_order(symbol,order_id)
            request=OrderRequest(symbol,'BUY' if own['side']=='B' else 'SELL',own['sz'],own['limitPx'])
            context=self.context_provider.load(request,critical=True)
            action=dict(type='cancel',cancels=[dict(a=self.client.market(symbol).asset_id,o=int(order_id))])
            # Persist ambiguity before cancellation so a restart cannot resubmit.
            self.journal.update(intent_key,'UNKNOWN',self.client.clock_ms(),oid=str(order_id),
                                outcome=dict(code='PROTECTION_CANCEL_PENDING'))
            return self._management_action('cancel',(symbol,int(order_id)),action,context,critical=True)

    def close_position(self, symbol, *, permission=None, price=None, **parameters):
        self._require()
        self._dependencies()
        with self.lock:
            position=self.account.get_position(symbol)
            if position is None or position.quantity==0:
                return None
            if not isinstance(permission,RiskPermission) or not permission.reduce_only or not permission.reason or price is None:
                raise ExchangeError('EXPLICIT_EXIT_PERMISSION_REQUIRED')
            self.exit_intents[symbol]=dict(reason=permission.reason,candidate_id=permission.candidate_id)
            request=OrderRequest(symbol,'SELL' if position.quantity>0 else 'BUY',abs(position.quantity),price,
                                 reduce_only=True,tif='Ioc',strategy_id='VWAP_BASELINE_EXIT',
                                 client_order_id=parameters.get('client_order_id'))
            result=self.submit(request,permission=permission)
            remaining=self.account.get_position(symbol)
            if remaining is None or remaining.quantity==0:
                self.exit_intents.pop(symbol,None)
            self.journal.event('CLOSE_VERIFICATION',self.client.clock_ms(),symbol=symbol,
                               remaining_quantity=str(remaining.quantity if remaining else 0),
                               exit_intent=self.exit_intents.get(symbol))
            return result

    def set_leverage(self, symbol, leverage, *, is_cross=True, **parameters):
        self._require()
        self._dependencies()
        with self.lock:
            spec=self.client.market(symbol)
            if (type(leverage) is not int or leverage<1 or leverage>spec.max_leverage or
                    leverage!=self.validator.policy_leverage or is_cross is not True):
                raise ExchangeError('INVALID_LEVERAGE')
            quote=self.context_provider.market.get_quote(symbol)
            quantity=spec.normalize_size(Decimal(11)/quote.mid+spec.size_step)
            context=self.context_provider.load(OrderRequest(symbol,'BUY',quantity,quote.mid))
            position=context.positions.get(symbol)
            notional=abs(position.quantity)*context.quote.mark if position else Decimal(0)
            if leverage>spec.maximum_leverage_at(notional):
                raise ExchangeError('INVALID_LEVERAGE')
            action=dict(type='updateLeverage',asset=spec.asset_id,isCross=True,leverage=leverage)
            return self._management_action('update_leverage',(leverage,symbol,True),action,context)


HyperliquidExecutor = HyperliquidExecution
LiveTradingDisabled = order_guard.OrderRoutingBlocked
