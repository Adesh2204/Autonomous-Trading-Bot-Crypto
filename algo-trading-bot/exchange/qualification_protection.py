"""Isolated fixed-size qualification stops, never production strategy geometry.

Uses the existing native trigger transport and its exact-action authorization.
It grants no signing authority. The current no-stop emergency proposal cannot
authorize this path. Ordinary $10 stop validation remains; historical IOC close
evidence is NOT a stop exemption. No observation here certifies venue capability.
"""
from dataclasses import asdict
from decimal import Decimal as D
import json
import threading

from .base_exchange import ExchangeError, decimal
from .execution_journal import safe_reason
from .order_lifecycle import OrderState
from .partial_fill_safety import (MIN_NOTIONAL, TERMINAL_CANCELLATIONS,
                                  TERMINAL_REJECTIONS, exact_full_close_size)
from .position_protection import ProtectionPlan
from .qualification_intent_recovery import verified_qualification_view
from .certification_runtime import same_position_exposure


def require_settled_exit_orders(executor, *, current_intent=None):
    """Exchange-read-only IOC barrier; only verified nontransmission is excluded."""
    if executor.account.get_frontend_open_orders():
        raise ExchangeError('QUALIFICATION_EXIT_OPEN_ORDER_RECONCILIATION_REQUIRED')
    if any(r['state']=='UNKNOWN' for r in executor.journal.management_actions()):
        raise ExchangeError('QUALIFICATION_EXIT_UNCERTAIN_MANAGEMENT_ACTION')
    view = verified_qualification_view(executor.journal.db)
    for resolution in view['resolutions']:
        executor.journal.event('QUALIFICATION_EXIT_HISTORICAL_NONTRANSMISSION_VERIFIED',
            executor.client.clock_ms(), **resolution, current_intent=current_intent,
            settlement_scope='HISTORICAL_INTENT_ONLY')
    for row in view['intents']:
        if row['intent_key'] == current_intent:
            continue  # The exact permitted close being checked before signing.
        request = json.loads(row['request'])
        outcome = json.loads(row['outcome'] or '{}')
        if row['state'] in {'PREPARED', 'SUBMITTED', 'UNKNOWN', 'OPEN', 'CANCEL_PENDING'}:
            raise ExchangeError('QUALIFICATION_EXIT_UNRESOLVED_ORDER')
        if row['state'] == 'PARTIALLY_FILLED' and not outcome.get('remainder_cancelled'):
            raise ExchangeError('QUALIFICATION_EXIT_UNSETTLED_REMAINDER')
        if request.get('strategy_id') == 'CATASTROPHIC_STOP':
            # Generic recovery cannot certify trigger children. Require the
            # isolated manager's explicit terminal readback even if journal says
            # FILLED/CANCELLED. Do not trust a saved ACTIVE flag after restart.
            proof = executor.journal.control('qualification_stop_settled:'+row['intent_key'])
            if not proof or proof.get('cloid') != row['cloid']:
                raise ExchangeError('QUALIFICATION_EXIT_STOP_LIFECYCLE_UNRESOLVED')


class QualificationStopManager:
    """Explicit one-stop lifecycle; no automatic submit, rearm, modify or exit.

    Fixed stop prices come from a separately approved certification proposal.
    'coverage_observed' means matching current readbacks, not guaranteed fills or
    verified small-stop venue support. REST refresh is mandatory after WS loss.
    """
    running = True  # Existing executor must not invoke automatic ensure_all.
    entries_allowed = False

    def __init__(self, executor, proposal):
        self.executor, self.proposal = executor, proposal.require()
        self.account, self.journal = executor.account, executor.journal
        self.managers, self.states = {}, {}
        self.lock = threading.RLock()
        self.key = 'qualification_stop:'+proposal.identity
        self.intent_key = 'certification:'+proposal.identity+':protection'
        executor.protection = self

    def _save(self, status, **data):
        record = dict(status=status, observed_ms=self.executor.client.clock_ms(),
            coverage_observed=False, protection_verified=False,
            capability_status='UNVERIFIED_REQUIRES_INDEPENDENT_EXCHANGE_EVIDENCE',
            evidence_scope='READBACK_ONLY_NOT_CAPABILITY_CERTIFICATION')
        record.update(data)
        record['protection_verified'] = False
        if status not in {'FILLED','PARTIALLY_FILLED','CANCELLED','REJECTED'}:
            self.journal.control('qualification_stop_settled:'+self.intent_key, False)
        self.states[self.proposal.symbol] = record
        self.journal.control(self.key+':observation', record)
        self.journal.event('QUALIFICATION_STOP_OBSERVATION', record['observed_ms'], **record)
        self.executor.entries_paused = True
        return record

    def _plan(self, symbol, position, manager, observed_ms):
        p = self.proposal
        now = self.executor.client.clock_ms()
        if not 0 <= now-observed_ms <= 5000:
            raise ExchangeError('QUALIFICATION_STOP_STALE_POSITION')
        if (symbol != p.symbol or position.symbol != symbol or not position.quantity
                or (position.quantity > 0) != (p.entry_side == 'BUY')
                or abs(position.quantity) > decimal(p.quantity)):
            raise ExchangeError('QUALIFICATION_STOP_POSITION_CONFLICT')
        spec = self.executor.client.market(symbol)
        side = 'SELL' if position.quantity > 0 else 'BUY'
        if abs(position.quantity)*decimal(p.stop_limit, positive=True) < MIN_NOTIONAL:
            raise ExchangeError('SMALL_STOP_VENUE_SUPPORT_UNVERIFIED')
        quantity = exact_full_close_size(spec, position, side=side,
            maximum_quantity=p.quantity, limit_price=p.stop_limit)
        trigger = decimal(p.stop_trigger, positive=True)
        limit = decimal(p.stop_limit, positive=True)
        if (spec.normalize_price(trigger, side) != trigger or
                side == 'SELL' and limit >= trigger or side == 'BUY' and limit <= trigger):
            raise ExchangeError('QUALIFICATION_STOP_GEOMETRY_INVALID')
        return ProtectionPlan(symbol, side, quantity, trigger, limit, trigger,
            'CERTIFICATION_ONLY:'+p.identity, observed_ms, position.entry_price,
            'CATASTROPHIC_STOP', False)

    def prepare(self):
        """Read-only preparation for the exact current position, never entry size."""
        self.executor.recovery.recover()
        before = self.account.get_positions()
        orders = self.account.get_frontend_open_orders()
        after = self.account.get_positions()
        if not same_position_exposure(before,after) or len(after) != 1 or self.proposal.symbol not in after or orders:
            raise ExchangeError('QUALIFICATION_STOP_ACCOUNT_BARRIER')
        if not self.executor.recovery.last_report.ready:
            raise ExchangeError('QUALIFICATION_STOP_ACCOUNT_UNRECONCILED')
        return self._plan(self.proposal.symbol, after[self.proposal.symbol], None,
                          self.executor.client.clock_ms())

    def submit(self, intent_key):
        """Explicit dispatch through unchanged central gates; never blind retry."""
        with self.lock, self.executor.lock:
            prior = self.journal.control(self.key)
            if prior or self.journal.intent(intent_key):
                raise ExchangeError('QUALIFICATION_STOP_READ_ONLY_RECOVERY_REQUIRED')
            if intent_key != self.intent_key:
                raise ExchangeError('QUALIFICATION_STOP_EXACT_INTENT_REQUIRED')
            plan = self.prepare()
            # Persist BEFORE the SDK call. Crashes/unknown acknowledgements own
            # this attempt forever; observing it does not authorize replacement.
            self.journal.control(self.key, dict(plan=asdict(plan),
                working_source_hash=self.proposal.source_hash, configuration_hash=self.proposal.identity))
            self._save('SUBMISSION_PENDING', intent_key=intent_key)
            try:
                self.executor.submit_protection(plan, intent_key)
            except Exception as exc:
                self._save('UNKNOWN', error=safe_reason(str(exc)))
                raise
            # ACK/resting is insufficient. Separate orderStatus+frontend readback.
            return self.reconcile()

    def on_disconnect(self):
        """A WS reconnect is only a hint to refresh; no submit is performed."""
        with self.lock, self.executor.lock:
            return self._save('UNKNOWN', reason='DISCONNECT_REQUIRES_REST_RECONCILIATION')

    def recover(self):
        """Restart always ignores saved coverage and re-reads the original ID."""
        self._save('UNKNOWN', reason='RESTART_REQUIRES_REST_RECONCILIATION')
        cancel_oid = self.journal.control(self.key+':cancel_oid')
        for row in self.journal.management_actions():
            action = json.loads(row['action'])
            if (row['state']=='UNKNOWN' and action.get('type')=='cancel'
                    and action.get('cancels')==[dict(a=self.executor.client.market(self.proposal.symbol).asset_id,
                                                   o=cancel_oid)]):
                try:
                    self.executor.recover_management_action(row['id'])
                except Exception as exc:
                    return self._save('UNKNOWN', reason=safe_reason(str(exc)), operator_action_required=True)
        return self.reconcile()

    @staticmethod
    def _status(account, oid):
        result = account._query('orderStatus', oid=oid)
        if not isinstance(result, dict) or result.get('status') != 'order':
            raise ExchangeError('QUALIFICATION_STOP_ORDER_STATUS_UNKNOWN')
        record = result.get('order')
        if not isinstance(record, dict) or not isinstance(record.get('order'), dict):
            raise ExchangeError('QUALIFICATION_STOP_STATUS_SCHEMA')
        return record

    def reconcile(self):
        """Authoritative IDs, fills, live children and actual remaining position."""
        with self.lock, self.executor.lock:
            try:
                return self._reconcile()
            except Exception as exc:
                return self._save('UNKNOWN', reason=safe_reason(str(exc)),
                                  operator_action_required=True, blind_retry=False)

    def _reconcile(self):
        started_ms = self.executor.client.clock_ms()
        if any(r['state']=='UNKNOWN' for r in self.journal.management_actions()):
            raise ExchangeError('QUALIFICATION_STOP_CANCELLATION_UNCERTAIN')
        saved = self.journal.control(self.key)
        if not saved:
            return self._save('NOT_SUBMITTED', reason='NO_STOP_ATTEMPT_RECORDED')
        if (saved['working_source_hash'] != self.proposal.source_hash or
                saved['configuration_hash'] != self.proposal.identity):
            raise ExchangeError('QUALIFICATION_STOP_SOURCE_OR_PROPOSAL_CONFLICT')
        row = self.journal.intent(self.intent_key)
        if not row:
            # A crash before journal.reserve may prove no order only with an
            # explicit dispatch record. No automatic retry even in this case.
            raise ExchangeError('QUALIFICATION_STOP_DISPATCH_OUTCOME_UNKNOWN')
        plan = ProtectionPlan(**saved['plan'])
        plan = ProtectionPlan(**{**asdict(plan), **{k:decimal(getattr(plan,k),positive=True)
            for k in ('quantity','trigger_price','limit_price','normal_strategy_stop')}})
        before = self.account.get_positions()
        orders = self.account.get_frontend_open_orders()
        outcome = json.loads(row['outcome'] or '{}')
        if (row['state'] == 'REJECTED' and not row['oid']
                and outcome.get('result') in {'ORDER_REJECTED','REQUEST_FAILED'}):
            # A definite SDK error response is distinct from a lost response.
            # No accepted OID was returned. Never use missing openOrders alone.
            after = self.account.get_positions()
            if (not same_position_exposure(before,after) or orders or self.account.get_frontend_open_orders()
                    or not 0 <= self.executor.client.clock_ms()-started_ms <= 5000
                    or len(after)>1 or any(s!=plan.symbol for s in after)):
                raise ExchangeError('QUALIFICATION_STOP_REJECTION_ACCOUNT_CHANGED')
            held = after.get(plan.symbol)
            if held and ((held.quantity>0)!=(plan.side=='SELL') or abs(held.quantity)>plan.quantity):
                raise ExchangeError('QUALIFICATION_STOP_POSITION_CONFLICT')
            proof = dict(cloid=row['cloid'], observed_ms=self.executor.client.clock_ms(),
                placement_rejection_observed=True, rejection_code=outcome.get('code'), remainder_settled=True)
            self.journal.control('qualification_stop_settled:'+row['intent_key'], proof)
            return self._save('REJECTED', filled_quantity='0',
                remaining_position_quantity=str(abs(held.quantity) if held else D(0)),
                operator_action_required=bool(held), **{k:v for k,v in proof.items() if k!='observed_ms'})
        parent = self._status(self.account, row['cloid'])
        detail = parent['order']
        oid = detail.get('oid')
        if (type(oid) is not int or oid < 0 or detail.get('cloid') != row['cloid']
                or detail.get('coin') != plan.symbol or detail.get('reduceOnly') is not True
                or detail.get('side') != ('A' if plan.side == 'SELL' else 'B')
                or decimal(detail['origSz']) != plan.quantity
                or decimal(detail['limitPx']) != plan.limit_price
                or decimal(detail['triggerPx']) != plan.trigger_price
                or detail.get('isPositionTpsl') is True
                or detail.get('orderType') != 'Stop Limit'):
            raise ExchangeError('QUALIFICATION_STOP_READBACK_MISMATCH')
        children = detail.get('children', [])
        if not isinstance(children, list):
            raise ExchangeError('QUALIFICATION_STOP_CHILD_SCHEMA')
        records = {str(oid):parent}
        for child in children:
            child_id = child.get('oid') if isinstance(child, dict) else child
            if type(child_id) is not int or child_id < 0 or str(child_id) in records:
                raise ExchangeError('QUALIFICATION_STOP_CHILD_IDENTITY')
            record = self._status(self.account, child_id)
            c = record['order']
            if (c.get('oid') != child_id or c.get('coin') != plan.symbol
                    or c.get('reduceOnly') is not True or c.get('side') != detail['side']
                    or decimal(c['origSz'],positive=True) > plan.quantity
                    or decimal(c['limitPx']) != plan.limit_price):
                raise ExchangeError('QUALIFICATION_STOP_CHILD_IDENTITY')
            records[str(child_id)] = record
        fills = self.account.get_fills(start_ms=row['created_ms'], end_ms=self.executor.client.clock_ms())
        after = self.account.get_positions()
        orders_after = self.account.get_frontend_open_orders()
        if (not 0 <= self.executor.client.clock_ms()-started_ms <= 5000
                or not same_position_exposure(before,after) or orders != orders_after or len(after) > 1
                or any(s != plan.symbol for s in after)):
            raise ExchangeError('QUALIFICATION_STOP_SNAPSHOT_CHANGED')
        if any(str(o['oid']) not in records for o in orders):
            raise ExchangeError('QUALIFICATION_STOP_UNEXPECTED_ORDER')
        matched = {}
        for fill in fills:
            if fill.symbol != plan.symbol or str(fill.order_id) not in records:
                continue
            if fill.identity in matched and fill != matched[fill.identity]:
                raise ExchangeError('QUALIFICATION_STOP_FILL_CONFLICT')
            matched[fill.identity] = fill
        quantity = sum((f.quantity for f in matched.values()), D(0))
        if quantity > plan.quantity or any(f.side != plan.side for f in matched.values()):
            raise ExchangeError('QUALIFICATION_STOP_FILL_CONFLICT')
        if any(f.price<plan.limit_price if plan.side=='SELL' else f.price>plan.limit_price for f in matched.values()):
            raise ExchangeError('QUALIFICATION_STOP_FILL_PRICE_CONFLICT')
        held = after.get(plan.symbol)
        remaining = abs(held.quantity) if held else D(0)
        if held and ((held.quantity > 0) != (plan.side == 'SELL') or remaining > plan.quantity-quantity):
            raise ExchangeError('QUALIFICATION_STOP_POSITION_CONFLICT')
        terminal = {'filled'} | TERMINAL_CANCELLATIONS | TERMINAL_REJECTIONS
        parent_state = parent.get('status')
        live = [o for o in orders if str(o['oid']) in records]
        # 'triggered' is not terminal. With no explicit children, only complete
        # matching fills plus flat account can resolve a triggered parent.
        settled = not live and (parent_state in terminal or parent_state == 'triggered' and
            (len(records)>1 and all(r.get('status') in terminal for k,r in records.items() if k!=str(oid))
             or quantity == plan.quantity and not remaining))
        base = dict(intent_key=row['intent_key'], cloid=row['cloid'], order_id=str(oid),
            child_order_ids=[k for k in records if k != str(oid)], order_statuses={k:r.get('status') for k,r in records.items()},
            filled_quantity=str(quantity), remaining_position_quantity=str(remaining),
            remaining_order_quantities={str(o['oid']):str(o['sz']) for o in live},
            actual_fill_ids=[list(k) for k in matched], reduce_only=True,
            flat_observed=not after and not orders, remainder_settled=settled)
        if parent_state == 'open' and len(live) == 1 and str(live[0]['oid']) == str(oid) and not quantity:
            live_row = live[0]
            if (detail.get('isTrigger') is not True or live_row.get('isTrigger') is not True
                    or any(live_row.get(k) != detail.get(k) for k in
                        ('coin','side','oid','cloid','sz','limitPx','reduceOnly','triggerPx','orderType'))):
                raise ExchangeError('QUALIFICATION_STOP_READBACK_MISMATCH')
            if decimal(live_row['sz']) == plan.quantity == remaining:
                # A lost placement ACK may leave the original row UNKNOWN.
                # Matching fresh status+frontend+position evidence resolves
                # that same order, without signing or replacing anything.
                if row['state'] in {'UNKNOWN','SUBMITTED'}:
                    self.journal.update(row['intent_key'], 'OPEN', self.executor.client.clock_ms(),
                        oid=str(oid), outcome=dict(filled_quantity=D(0),
                            remaining_quantity=plan.quantity, remainder_cancelled=False,
                            code='ISOLATED_STOP_OPEN_EXACT_READBACK'))
                return self._save('READBACK_ACCEPTED', coverage_observed=True, **base)
            return self._save('STALE_COVERAGE', operator_action_required=True, **base)
        if parent_state == 'filled' and quantity != plan.quantity:
            raise ExchangeError('QUALIFICATION_STOP_FILL_EVIDENCE_REQUIRED')
        if settled:
            state = ('FILLED' if quantity == plan.quantity else 'PARTIALLY_FILLED' if quantity else
                     'REJECTED' if any(r.get('status') in TERMINAL_REJECTIONS for r in records.values())
                     else 'CANCELLED')
            proof = dict(base, observed_ms=self.executor.client.clock_ms())
            self.journal.control('qualification_stop_settled:'+row['intent_key'], proof)
            self.journal.update(row['intent_key'], state, self.executor.client.clock_ms(), oid=str(oid),
                outcome=dict(filled_quantity=quantity, remaining_quantity=plan.quantity-quantity,
                             remainder_cancelled=True, code='ISOLATED_STOP_TERMINAL_READBACK'))
            return self._save(state, operator_action_required=bool(remaining), **base)
        return self._save('TRIGGERED_UNSETTLED' if parent_state=='triggered' or quantity else 'UNKNOWN',
                          operator_action_required=True, **base)

    def cancel(self):
        """One explicit cancellation round; acknowledgment alone proves nothing."""
        with self.lock, self.executor.lock:
            if self.journal.control(self.key+':cancel_attempted'):
                raise ExchangeError('QUALIFICATION_STOP_CANCEL_ALREADY_ATTEMPTED')
            observation = self.reconcile()
            if observation['status'] == 'UNKNOWN':
                raise ExchangeError('QUALIFICATION_STOP_CANCEL_IDENTITY_UNCERTAIN')
            saved = self.journal.control(self.key)
            if not saved:
                raise ExchangeError('QUALIFICATION_STOP_NOT_SUBMITTED')
            ids = list(observation.get('remaining_order_quantities', {}))
            if not ids:
                return observation
            if len(ids) != 1:
                raise ExchangeError('QUALIFICATION_STOP_MULTIPLE_LIVE_ORDERS_REQUIRE_OPERATOR_REVIEW')
            self.journal.control(self.key+':cancel_attempted', True)
            self.journal.control(self.key+':cancel_oid', int(ids[0]))
            for oid in ids:
                try:
                    outcome = self.executor.cancel_order(self.proposal.symbol, oid, critical=True)
                except Exception as exc:
                    return self._save('UNKNOWN', reason=safe_reason(str(exc)), operator_action_required=True)
            result = self.reconcile()
            result.update(cancel_result=asdict(outcome), cancel_confirmed=bool(result.get('remainder_settled')))
            if not result['cancel_confirmed']:
                result['operator_action_required'] = True
            self.journal.control(self.key+':cancel_result', result)
            return result
