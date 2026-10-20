"""Refresh a qualification action's evidence, never its immutable signed order.

Only the existing exact-action permit can request renewal. A renewal reruns real
account recovery, readiness, risk and compliance; no observation is retimestamped.
"""
from dataclasses import asdict, replace
import json

from .base_exchange import ExchangeError
from .execution_journal import fingerprint
from .single_position_guard import PositionDecision, unresolved
from .hyperliquid_market_data import make_quote


def context_ages(context, now):
    return {name: now-value if type(value) is int else None for name,value in dict(
        readiness=context.readiness.observed_ms, account=context.account_ms,
        quote=context.quote.timestamp_ms, mark=context.quote.mark_timestamp_ms).items()}


def fresh(context, now):
    return all(age is not None and 0 <= age <= 5000 for age in context_ages(context,now).values())


class QualificationSigningBoundary:
    def __init__(self, execution):
        self.e=execution;self.frames={};self.current=None

    def bind(self, request, risk, context, decision, *, full_close=False):
        self.frames[fingerprint(asdict(request))]=dict(request=request,risk=risk,context=context,
            checked_ms=decision.timestamp,full_close=full_close)

    def refresh_permit(self, permit, action):
        e=self.e;now=e.client.clock_ms()
        if action.get('type')!='order':return  # Existing cancellation gates remain unchanged.
        if (permit.guard is not e.compliance_guard or fingerprint(action)!=permit.action_hash
                or action.get('type')!='order' or len(action.get('orders',[]))!=1):
            raise ExchangeError('QUALIFICATION_BOUNDARY_EXACT_ACTION_REQUIRED')
        wire=action['orders'][0]
        from .native_qualification import NativeQualificationExecution
        native = type(e) is NativeQualificationExecution
        if native and 'trigger' in wire.get('t', {}):
            return  # Native stop placement retains its existing exact trigger gates.
        row=e.journal.db.execute('SELECT * FROM intents WHERE cloid=?',(wire.get('c'),)).fetchone()
        if row is None:raise ExchangeError('QUALIFICATION_BOUNDARY_DURABLE_INTENT_REQUIRED')
        frame=self.frames.get(row['fingerprint'])
        if (frame is None or fingerprint(json.loads(row['request']))!=row['fingerprint']
                or row['state'] not in {'PREPARED','SUBMITTED'}):
            raise ExchangeError('QUALIFICATION_BOUNDARY_UNCERTAIN_INTENT')
        request=frame['request']
        if (wire['b']!=(request.side=='BUY') or wire['r']!=request.reduce_only
                or e.client.market(request.symbol).asset_id!=wire['a']):
            raise ExchangeError('QUALIFICATION_BOUNDARY_WIRE_CHANGED')
        from .base_exchange import decimal
        if decimal(wire['s'])!=request.quantity or decimal(wire['p'])!=request.price:
            raise ExchangeError('QUALIFICATION_BOUNDARY_WIRE_CHANGED')
        started=now;reacquired=False
        context=frame['context']
        for attempt in range(2):
            if not fresh(context,e.client.clock_ms()):
                context=e.context_provider.refresh_for_signing(request,e.recovery,row['intent_key'])
                reacquired=True
            mark_ms=context.quote.mark_timestamp_ms
            if native:
                # Keep the native route's actual account read at every SDK
                # callback, even while the rest of the evidence is <5s old.
                # These timestamps describe new network observations only.
                from .certification_runtime import same_position_exposure
                before=e.account.get_positions()
                orders=tuple(e.account.get_frontend_open_orders())
                after=e.account.get_positions()
                if not same_position_exposure(before,after):
                    raise ExchangeError('ACCOUNT_CHANGED_BEFORE_SIGNING')
                if not request.reduce_only and (before or after or orders):
                    e.entries_paused=True;e.position_guard.revoke('ACCOUNT_CHANGED_BEFORE_SIGNING')
                    raise ExchangeError('ACCOUNT_CHANGED_BEFORE_SIGNING')
                context=replace(context,positions=after,open_orders=orders,account_ms=e.client.clock_ms())
                metadata,values=e.client.post_info('metaAndAssetCtxs')
                e.client.validate_metadata(metadata)
                if fingerprint(metadata)!=context.metadata_hash or len(values)!=len(metadata['universe']):
                    raise ExchangeError('MARKET_METADATA_CHANGED')
                contexts={row['name']:value for row,value in zip(metadata['universe'],values)
                    if not row.get('isDelisted')}
                mark_ms=e.client.clock_ms()
                context=replace(context,contexts=contexts,metadata_ms=mark_ms,oracle_ms=mark_ms)
            # One current public book, independent of the retained readiness.
            sent=e.client.clock_ms();book=e.context_provider.market.get_orderbook(request.symbol)
            e.clock_health.observe(book.timestamp_ms,sent,e.client.clock_ms())
            quote=make_quote(book,context.contexts[request.symbol],e.client.clock_ms(),
                mark_timestamp_ms=mark_ms)
            context=replace(context,quote=quote)
            e.context_provider.books[request.symbol]=book
            if fresh(context,e.client.clock_ms()):break
        else:raise ExchangeError('QUALIFICATION_FRESH_BOUNDARY_UNAVAILABLE')
        e._require();e.clock_health.require()
        if not e.transport.nonces.healthy:raise ExchangeError('NONCE_SIGNING_DEGRADED')
        if not context.readiness.account_ready or not context.reconciled:
            raise ExchangeError('QUALIFICATION_FRESH_ACCOUNT_RECONCILIATION_REQUIRED')
        if not request.reduce_only:
            if context.positions or context.open_orders:
                e.entries_paused=True;e.position_guard.revoke('ACCOUNT_CHANGED_BEFORE_SIGNING')
                raise ExchangeError('ACCOUNT_CHANGED_BEFORE_SIGNING')
            e.position_guard.require_entry_lease(row['intent_key'],permit.generation)
            if any(unresolved(r) and r['intent_key']!=row['intent_key'] for r in e.position_guard.intent_rows()):
                raise ExchangeError('QUALIFICATION_OTHER_UNRESOLVED_INTENT')
            position=PositionDecision(True,'SINGLE_POSITION_PASS','ENTRY_PENDING',
                'OWN_RESERVED_ENTRY_AND_FRESH_FLAT_ACCOUNT',e.client.clock_ms())
        else:
            held=context.positions.get(request.symbol)
            allowed=held is not None and (held.quantity>0)!=(request.side=='BUY') and request.quantity==abs(held.quantity)
            if not allowed:raise ExchangeError('EXACT_FULL_CLOSE_POSITION_CHANGED_BEFORE_SIGNING')
            position=PositionDecision(True,'SINGLE_POSITION_PASS','EXIT_PENDING',
                'FRESH_EXACT_ACTUAL_POSITION',e.client.clock_ms())
        if native:
            from .testnet_certification import test_permission
            risk=test_permission(request,e.proposal,e.client.clock_ms(),
                reason=frame['risk'].reason if request.reduce_only else None)
        else:
            from .emergency_qualification import permission
            risk=permission(request,e.proposal,e.client.clock_ms(),
                reason=frame['risk'].reason if request.reduce_only else None)
        decision=e.compliance_guard.evaluate(request,context,risk,position,
            full_position_close=frame['full_close'],renewal=(permit,action))
        operation='EXACT_FULL_POSITION_CLOSE' if frame['full_close'] else 'ORDER'
        if frame['full_close']:
            from .full_position_close import FULL_POSITION_CLOSE
            operation=FULL_POSITION_CLOSE
        checked=e.validator.validate(request,context,risk,e.client.clock_ms(),operation=operation)
        if not decision.allowed or not checked.allowed:
            e.compliance_guard._approved.pop(id(decision),None)
            raise ExchangeError(decision.code if not decision.allowed else checked.code)
        if not request.reduce_only:
            if native:
                from .native_qualification import check_entry
                check_entry(context,e.proposal,e.client.clock_ms(),request=request)
            else:
                from .emergency_qualification import check_entry
                check_entry(context,request,e.proposal,e.client.clock_ms(),book,journal=e.journal,
                    stage='FRESH_SIGNING_BOUNDARY')
        e.compliance_guard._approved.pop(id(decision),None)
        old_issued=permit.issued_ms
        # Renew a capability only AFTER complete genuine revalidation of the
        # same action/intent. Evidence timestamps themselves never change.
        permit.issued_ms=e.client.clock_ms()
        frame.update(context=context,risk=risk,checked_ms=permit.issued_ms)
        self.current=frame
        e.journal.event('QUALIFICATION_SIGNING_BOUNDARY',e.client.clock_ms(),cloid=wire['c'],
            stage=getattr(e.transport,'boundary_phase','EXACT_ACTION_CALLBACK'),
            readiness_reacquired=reacquired,started_ms=started,old_permit_issued_ms=old_issued,
            new_validation_ms=permit.issued_ms,readiness_ms=context.readiness.observed_ms,
            account_ms=context.account_ms,quote_ms=context.quote.timestamp_ms,
            mark_ms=context.quote.mark_timestamp_ms,ages_ms=context_ages(context,e.client.clock_ms()),
            immutable_request=asdict(request),elapsed_ms=e.client.clock_ms()-started)

    def context_for(self, request):
        if self.current is None or self.current['request']!=request:
            raise ExchangeError('QUALIFICATION_FRESH_ACTION_FRAME_REQUIRED')
        return self.current['context'],self.current['checked_ms']
