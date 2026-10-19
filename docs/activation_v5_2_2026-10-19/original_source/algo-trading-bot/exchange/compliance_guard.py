"""Central explainable order checks and exact-action signing capabilities.

Local price/participation limits are conservative bot policy, not a verdict from
the competition committee. This guard cannot identify other teams behind public
book quotes or certify unrelated wallets/manual activity.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
import json

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint, safe_data
from .single_position_guard import unresolved


class OrderClassification(str, Enum):
    STRATEGY_ENTRY = 'STRATEGY_ENTRY'
    STRATEGY_EXIT = 'STRATEGY_EXIT'
    CATASTROPHIC_STOP = 'CATASTROPHIC_STOP'
    PROTECTIVE_EXIT = 'PROTECTIVE_EXIT'
    RECONCILIATION_ACTION = 'RECONCILIATION_ACTION'
    CONTROLLED_TEST_ORDER = 'CONTROLLED_TEST_ORDER'


@dataclass(frozen=True)
class OrderProvenance:
    candidate_id: str
    strategy_id: str
    setup_type: str
    signal_timestamp_ms: int
    source_market: str
    direction: str
    reason: str
    risk_decision: dict
    execution_decision: dict
    classification: str = 'STRATEGY_ENTRY'
    action_type: str = 'STRATEGY'
    source_position_id: str | None = None
    input_source: str = 'OWN_STRATEGY_PUBLIC_MARKET'
    test_authorization: dict | None = None


@dataclass(frozen=True)
class CompliancePolicy:
    max_order_book_bps: Decimal = Decimal('100')
    max_order_oracle_bps: Decimal = Decimal('150')
    max_mark_oracle_bps: Decimal = Decimal('50')
    depth_participation: Decimal = Decimal('0.1')
    max_book_age_ms: int = 5000
    max_reference_age_ms: int = 60000

    def __post_init__(self):
        for name in ('max_order_book_bps', 'max_order_oracle_bps', 'max_mark_oracle_bps', 'depth_participation'):
            object.__setattr__(self, name, decimal(getattr(self, name), positive=True))
        if (self.depth_participation > Decimal('0.1') or self.max_mark_oracle_bps > 50 or
                self.max_order_book_bps > 100 or self.max_order_oracle_bps > 150 or
                type(self.max_book_age_ms) is not int or not 1 <= self.max_book_age_ms <= 5000 or
                type(self.max_reference_age_ms) is not int or not 1 <= self.max_reference_age_ms <= 60000):
            raise ExchangeError('CONSERVATIVE_COMPLIANCE_POLICY_REQUIRED')


@dataclass(frozen=True)
class ComplianceDecision:
    allowed: bool
    code: str
    reason: str
    candidate_id: str | None
    checks: dict
    timestamp: int
    classification: str | None = None


class ActionPermit:
    """Internal exact-action capability; plain callbacks cannot sign orders."""
    def __init__(self, guard, action, callback, *, entry_key=None):
        self.guard = guard
        self.action_hash = fingerprint(action)
        self.callback = callback
        self.entry_key = entry_key
        self.generation = (guard.position_guard.journal.control('global_position_lock') or {}).get('generation')
        self.issued_ms = guard.clock_ms()
        self.active = True

    def require(self, transport, action):
        if (not self.active or self.guard._permits.get(id(self)) is not self or self.guard.transport is not transport or
                getattr(transport, '_compliance_guard', None) is not self.guard or
                fingerprint(action) != self.action_hash):
            raise ExchangeError('COMPLIANCE_ACTION_PERMIT_REQUIRED')
        # Only the isolated qualification owner installs this typed boundary.
        # Production retains its original fixed five-second permit behavior.
        boundary=getattr(self.guard.execution_owner,'signing_boundary',None)
        if boundary is not None:
            from .qualification_signing_boundary import QualificationSigningBoundary
            if type(boundary) is not QualificationSigningBoundary:
                raise ExchangeError('QUALIFICATION_SIGNING_BOUNDARY_REQUIRED')
            boundary.refresh_permit(self,action)
        if not 0 <= self.guard.clock_ms()-self.issued_ms <= 5000:
            raise ExchangeError('COMPLIANCE_ACTION_PERMIT_REQUIRED')
        if self.entry_key is not None:
            self.guard.position_guard.require_entry_lease(self.entry_key, self.generation)
        self.callback()

    def __call__(self):
        self.require(self.guard.transport, self.guard.transport._current_action)


class ComplianceGuard:
    def __init__(self, journal, position_guard, *, clock_ms, transport, policy=None, execution_owner=None,
                 qualification_scope=None):
        self.journal = journal
        self.position_guard = position_guard
        self.clock_ms = clock_ms
        self.transport = transport
        self.execution_owner = execution_owner
        self.policy = policy or CompliancePolicy()
        if qualification_scope is not None:
            from .emergency_qualification import EmergencyComplianceScope
            if type(qualification_scope) is not EmergencyComplianceScope:
                raise ExchangeError('P0_EXACT_COMPLIANCE_SCOPE_REQUIRED')
        self.qualification_scope = qualification_scope
        self._approved = {}
        self._permits = {}

    def _issue(self, action, callback, *, entry_key=None):
        for identity,old in list(self._permits.items()):
            if not old.active or not 0 <= self.clock_ms()-old.issued_ms <= 5000:
                old.active=False
                del self._permits[identity]
        if len(self._permits)>=16:
            raise ExchangeError('UNRESOLVED_COMPLIANCE_PERMITS')
        permit=ActionPermit(self, action, callback, entry_key=entry_key)
        self._permits[id(permit)]=permit
        return permit

    def record(self, decision, request=None, *, cloid=None, order_id=None, provenance=None):
        self.journal.event('COMPLIANCE_DECISION', decision.timestamp,
            candidate_id=decision.candidate_id, symbol=getattr(request, 'symbol', None),
            side=getattr(request, 'side', None), request=asdict(request) if request else None,
            order_classification=decision.classification, cloid=cloid, order_id=order_id,
            checks=decision.checks, outcome='PASS' if decision.allowed else 'BLOCK',
            code=decision.code, reason=decision.reason,
            execution_mode='OFFLINE_SIGNED_FIXTURE' if type(self.transport).__name__=='OfflineSDKTransport' else 'LIVE_TESTNET',
            provenance=asdict(provenance) if isinstance(provenance, OrderProvenance) else None)
        return decision

    def evaluate(self, request, context, permission, position, *, trigger=False, modify_oid=None,
                 full_position_close=False, renewal=None):
        now = self.clock_ms()
        candidate = getattr(permission, 'candidate_id', None)
        checks = dict(single_position=asdict(position), policy=asdict(self.policy),
                      trigger_order=trigger, modifies_order_id=modify_oid,
                      exact_full_position_close=full_position_close is True,
                      position_generation=(self.journal.control('global_position_lock') or {}).get('generation'))
        p = getattr(permission, 'provenance', None)
        classification = None
        def finish(allowed, code, reason=None):
            decision = ComplianceDecision(allowed, code, reason or code, candidate,
                                          safe_data(checks), now, classification)
            self.record(decision, request, order_id=modify_oid, provenance=p)
            if allowed:
                self._approved[id(decision)] = (decision, fingerprint(asdict(request)), modify_oid, trigger,
                                                full_position_close is True)
                if len(self._approved)>512:
                    del self._approved[next(iter(self._approved))]
            return decision
        try:
            if full_position_close:
                from .full_position_close import normalize_exact_full_close
                if trigger or modify_oid is not None:
                    return finish(False, 'EXACT_FULL_CLOSE_CANNOT_BE_TRIGGER_OR_REPLACEMENT')
                normalize_exact_full_close(context.spec, request, context, now)
            if not isinstance(p, OrderProvenance):
                return finish(False, 'MISSING_STRATEGY_PROVENANCE')
            try:
                classification = OrderClassification(p.classification).value
            except (ValueError, TypeError):
                return finish(False, 'UNEXPLAINED_ORDER')
            if not position.allowed:
                return finish(False, position.code, position.reason)
            if not request.reduce_only and (type(context.leverage) is not int or context.leverage!=1):
                return finish(False, 'INVALID_LEVERAGE')
            if (p.candidate_id != candidate or p.strategy_id != request.strategy_id or
                    p.source_market != request.symbol or p.direction != request.side or
                    not p.reason or not p.setup_type or type(p.signal_timestamp_ms) is not int or
                    not 0 <= p.signal_timestamp_ms <= now or
                    not isinstance(p.risk_decision, dict) or p.risk_decision.get('allowed') is not True or
                    not isinstance(p.execution_decision, dict) or p.execution_decision.get('allowed') is not True):
                return finish(False, 'MISSING_STRATEGY_PROVENANCE')
            if p.input_source != 'OWN_STRATEGY_PUBLIC_MARKET':
                return finish(False, 'COORDINATED_INPUT_BLOCK')
            held = context.positions.get(request.symbol)
            protective = classification in {'CATASTROPHIC_STOP', 'PROTECTIVE_EXIT', 'RECONCILIATION_ACTION'}
            if protective:
                if (p.action_type != 'RISK_PROTECTION' or not request.reduce_only or
                        not permission.reason or held is None):
                    return finish(False, 'UNEXPLAINED_ORDER')
                if (classification == 'CATASTROPHIC_STOP') != trigger:
                    return finish(False, 'UNEXPLAINED_ORDER')
            elif classification == 'STRATEGY_EXIT':
                if not request.reduce_only or not p.source_position_id or held is None:
                    return finish(False, 'MISSING_SOURCE_POSITION')
            elif classification == 'STRATEGY_ENTRY':
                if request.reduce_only or p.action_type != 'STRATEGY' or not 60000 <= now-p.signal_timestamp_ms <= 180000:
                    return finish(False, 'MISSING_STRATEGY_PROVENANCE')
                if p.setup_type not in {'PULLBACK_LONG','PULLBACK_SHORT','BREAKOUT_LONG','BREAKDOWN_SHORT'}:
                    return finish(False, 'UNEXPLAINED_ORDER')
            elif classification == 'CONTROLLED_TEST_ORDER':
                a = p.test_authorization or {}
                scoped = self.qualification_scope
                if scoped is not None:
                    checks['qualification_policy'] = scoped.validate(request, context, permission, now)
                checks['performance_statistics'] = 'EXCLUDE_CONTROLLED_TEST'
                if (p.action_type != 'CONTROLLED_TEST_ORDER' or not a.get('operator_authorization') or
                        not a.get('objective') or not a.get('exit_procedure') or
                        a.get('market') != request.symbol or decimal(a.get('expected_quantity', 0)) != request.quantity or
                        type(a.get('timestamp_ms')) is not int or type(a.get('expires_ms')) is not int or
                        not a['timestamp_ms'] <= now < a['expires_ms'] <= a['timestamp_ms']+300000 or
                        request.quantity*context.quote.mark > (1000 if scoped is not None else 50)):
                    return finish(False, 'UNAUTHORIZED_TEST_ORDER')
            if request.reduce_only and (not held or (held.quantity > 0) == (request.side == 'BUY') or
                    request.quantity > abs(held.quantity)):
                return finish(False, 'REDUCE_ONLY_VIOLATION')
            checks['provenance'] = 'PASS'
            renewal_key=None
            if renewal is not None:
                from .qualification_signing_boundary import QualificationSigningBoundary
                permit,action=renewal
                wire=action.get('orders',[{}])[0]
                own=self.journal.db.execute('SELECT * FROM intents WHERE cloid=?',(wire.get('c'),)).fetchone()
                if (type(permit) is not ActionPermit or self._permits.get(id(permit)) is not permit
                        or permit.guard is not self or not permit.active or fingerprint(action)!=permit.action_hash
                        or type(getattr(self.execution_owner,'signing_boundary',None)) is not QualificationSigningBoundary
                        or self.qualification_scope is None or own is None
                        or own['state'] not in {'PREPARED','SUBMITTED'}
                        or own['candidate']!=candidate or own['fingerprint']!=fingerprint(asdict(request))):
                    return finish(False,'INVALID_SAME_ACTION_REVALIDATION')
                renewal_key=own['intent_key']
            for row in self.position_guard.intent_rows():
                if row['intent_key']==renewal_key:continue
                old = json.loads(row['request'])
                if modify_oid is not None and str(row['oid']) == str(modify_oid):
                    # Only a tracked reduce-only replacement may be changed;
                    # exposure-increasing entry modifications are rejected.
                    if not request.reduce_only:
                        return finish(False, 'POSITION_LIMIT')
                    continue
                if not request.reduce_only and not old['reduce_only'] and row['candidate'] == candidate:
                    return finish(False, 'DUPLICATE_ORDER')
                if request.client_order_id and (row['intent_key'] == request.client_order_id or row['cloid'] == request.client_order_id):
                    return finish(False, 'DUPLICATE_ORDER')
                if unresolved(row) and old['symbol'] == request.symbol and old['side'] == request.side and bool(old['reduce_only']) == request.reduce_only:
                    dormant_protection = (old['strategy_id'] == 'CATASTROPHIC_STOP' and
                        request.strategy_id != 'CATASTROPHIC_STOP' and request.reduce_only and
                        any(str(o['oid']) == str(row['oid']) and o.get('isTrigger') is True and
                            o.get('reduceOnly') is True for o in context.open_orders))
                    if dormant_protection:
                        continue
                    return finish(False, 'DUPLICATE_ORDER')
            known = {str(r['oid']): r for r in self.journal.intents() if r['oid'] is not None}
            for own in context.open_orders:
                if modify_oid is not None and str(own['oid']) == str(modify_oid):
                    continue
                if own['coin'] != request.symbol:
                    continue
                if own['side'] not in {'B', 'A'}:
                    return finish(False, 'UNKNOWN_ACCOUNT_STATE')
                if own.get('isTrigger') is True:
                    row = known.get(str(own['oid']))
                    if (own.get('reduceOnly') is not True or row is None or
                            not json.loads(row['request'])['reduce_only']):
                        return finish(False, 'UNKNOWN_PROTECTION_ORDER')
                    continue
                opposite = own['side'] == ('A' if request.side == 'BUY' else 'B')
                px = decimal(own['limitPx'], positive=True)
                if opposite and (request.side == 'BUY' and request.price >= px or request.side == 'SELL' and request.price <= px):
                    return finish(False, 'SELF_CROSS_RISK')
                if not opposite and request.price == px and request.quantity == decimal(own['sz']):
                    return finish(False, 'DUPLICATE_ORDER')
            checks['self_cross'] = checks['duplicate_order'] = 'PASS'
            q = context.quote
            if (not 0 <= now-q.timestamp_ms <= self.policy.max_book_age_ms or
                    q.mark_timestamp_ms is None or not 0 <= now-q.mark_timestamp_ms <= self.policy.max_reference_age_ms or
                    context.oracle_ms is None or not 0 <= now-context.oracle_ms <= self.policy.max_reference_age_ms):
                return finish(False, 'STALE_PRICE_CONTEXT')
            references = dict(bid=q.bid, ask=q.ask, mid=q.mid, mark=q.mark, oracle=q.oracle)
            deviations = {name: abs(request.price-decimal(value, positive=True))/decimal(value, positive=True)*10000
                          for name, value in references.items()}
            checks.update(reference_prices=references, deviations_bps=deviations,
                          mark_oracle_bps=abs(q.mark-q.oracle)/q.oracle*10000)
            if not request.reduce_only and checks['mark_oracle_bps'] > self.policy.max_mark_oracle_bps:
                return finish(False, 'MARK_ORACLE_DIVERGENCE')
            if not trigger and (deviations['mid'] > self.policy.max_order_book_bps or
                                deviations['oracle'] > self.policy.max_order_oracle_bps):
                return finish(False, 'ABNORMAL_PRICE')
            if not request.reduce_only:
                depth = q.ask_quantity if request.side == 'BUY' else q.bid_quantity
                checks.update(executable_depth=str(depth), order_size=str(request.quantity),
                              participation=str(request.quantity/depth) if depth else None)
                separate_l2 = classification == 'CONTROLLED_TEST_ORDER' and self.qualification_scope is not None
                if not separate_l2 and (depth <= 0 or request.quantity > depth*self.policy.depth_participation):
                    return finish(False, 'BOOK_MANIPULATION_RISK')
                if separate_l2:
                    checks['liquidity_policy'] = 'P0_EXACT_SCOPE_L2_CHECK; NOT_OLD_BBO_RULE'
            checks['liquidity'] = 'PASS' if not request.reduce_only else 'REDUCE_ONLY_RISK_ACTION'
            checks['exchange_writes'] = 'SEPARATE_AUTHORIZATION_STILL_REQUIRED'
            return finish(True, 'COMPLIANCE_PASS')
        except (ExchangeError, KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError):
            return finish(False, 'COMPLIANCE_CONTEXT_INVALID')

    def authorize(self, action, decision, request, context, callback, *, entry_key=None):
        approved = self._approved.pop(id(decision), None)
        if approved is None or approved[0] is not decision or approved[1] != fingerprint(asdict(request)):
            raise ExchangeError('COMPLIANCE_ACTION_PERMIT_REQUIRED')
        modify_oid, trigger, full_position_close = approved[2:]
        kind = action.get('type')
        if kind == 'order' and modify_oid is None and len(action.get('orders', [])) == 1:
            wire = action['orders'][0]
        elif kind == 'batchModify' and len(action.get('modifies', [])) == 1 and str(action['modifies'][0]['oid']) == str(modify_oid):
            wire = action['modifies'][0]['order']
        else:
            raise ExchangeError('UNVALIDATED_SIGNED_ACTION')
        if (wire['a'] != context.spec.asset_id or wire['b'] != (request.side == 'BUY') or
                decimal(wire['s']) != request.quantity or decimal(wire['p']) != request.price or
                wire['r'] != request.reduce_only or not wire.get('c') or
                ('trigger' in wire['t']) != trigger or
                not trigger and wire['t'] != {'limit': {'tif': request.tif}}):
            raise ExchangeError('COMPLIANCE_ACTION_WIRE_MISMATCH')
        row=self.journal.db.execute('SELECT * FROM intents WHERE cloid=?',(wire['c'],)).fetchone()
        if (self.execution_owner is None or row is None or row['state']!='PREPARED' or
                row['candidate']!=decision.candidate_id or row['fingerprint']!=fingerprint(asdict(request)) or
                not request.reduce_only and (entry_key is None or row['intent_key']!=entry_key)):
            raise ExchangeError('DURABLE_COMPLIANCE_INTENT_REQUIRED')
        # The executor's fixed boundary supplies nonce/clock/account/health gates;
        # an alternate caller cannot replace them with a permissive callback.
        callback=lambda:self.execution_owner._guard(context,decision.timestamp,
            critical=request.reduce_only,entry=not request.reduce_only,
            entry_request=request if not request.reduce_only else None,
            exact_full_close=request if full_position_close else None)
        self.journal.event('COMPLIANCE_ACTION_AUTHORIZED', self.clock_ms(),
            candidate_id=decision.candidate_id, cloid=wire['c'], order_classification=decision.classification,
            action_type=kind, order=asdict(request), context_ms=context.account_ms,
            decision_timestamp=decision.timestamp,
            execution_mode='OFFLINE_SIGNED_FIXTURE' if type(self.transport).__name__=='OfflineSDKTransport' else 'LIVE_TESTNET')
        return self._issue(action, callback, entry_key=entry_key)

    def authorize_management(self, action, context, callback, *, critical=False):
        kind = action.get('type')
        checks = dict(account_ready=context.readiness.account_ready)
        allowed = kind in {'cancel', 'cancelByCloid', 'updateLeverage'} and context.readiness.account_ready
        if kind == 'updateLeverage':
            allowed &= (action.get('leverage') == 1 and action.get('isCross') is True and
                        action.get('asset') == context.spec.asset_id)
        elif kind in {'cancel', 'cancelByCloid'}:
            items = action.get('cancels', [])
            allowed &= len(items) == 1
            if allowed:
                item = items[0]
                asset = item.get('a', item.get('asset'))
                allowed &= any(self.transport.client.market(o['coin']).asset_id == asset and
                    (str(o['oid']) == str(item['o']) if 'o' in item else o.get('cloid') == item.get('cloid'))
                    for o in context.open_orders)
        self.record(ComplianceDecision(bool(allowed), 'COMPLIANCE_PASS' if allowed else
            'COLLATERAL_TRANSFER_BLOCK' if kind not in {'cancel', 'cancelByCloid', 'updateLeverage'} else
            'UNKNOWN_ACCOUNT_STATE', 'EXPLAINED_ACCOUNT_ORDER_MANAGEMENT', None,
            dict(checks, action_type=kind), self.clock_ms(), 'RECONCILIATION_ACTION'))
        if not allowed:
            raise ExchangeError('COMPLIANCE_MANAGEMENT_BLOCKED')
        if self.execution_owner is None:
            raise ExchangeError('CENTRAL_EXECUTION_OWNER_REQUIRED')
        checked_ms=self.clock_ms()
        callback=lambda:self.execution_owner._guard(context,checked_ms,critical=critical)
        return self._issue(action, callback)
