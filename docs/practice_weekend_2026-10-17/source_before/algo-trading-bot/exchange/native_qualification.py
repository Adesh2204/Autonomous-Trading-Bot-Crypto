"""One separately approved two-lot BTC Stop Limit experiment.

This is not an unattended-entry exception. A one-lot entry is aborted using the
already observed exact full-position IOC scope; it is never given an unverified
small stop. Ordinary certification and strategy entry guards remain unchanged.
Native qualification requires actual trigger-linked fills, not acceptance.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import time

from .base_exchange import ExchangeError, decimal
from .testnet_certification import (CertificationProposal, CertificationApproval,
    CertificationAuthorization, CertificationSequence, test_permission)
from .full_position_close import observed_scope
from .order_lifecycle import OrderRequest, OrderState
from .sdk_transport import OfficialSDKTransport, OfflineSDKTransport
from .partial_fill_safety import scoped_exact_full_close_size
from .qualification_protection import QualificationStopManager, require_settled_exit_orders
from .certification_runtime import CertificationRecovery, same_position_exposure
from .hyperliquid_execution import HyperliquidExecution

PURPOSE = 'TWO_LOT_BTC_NATIVE_STOP_WITH_ONE_LOT_ABORT_V1'
CLOSE_PROOF = 'docs/certification_v8_5_2026-10-12/independent_close_readback/one_lot_readback.json'
CLOSE_SHA = 'c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764'


@dataclass(frozen=True)
class NativeQualificationProposal(CertificationProposal):
    purpose: str = PURPOSE
    close_evidence_sha256: str = CLOSE_SHA
    trigger_wait_seconds: int = 120

    def require(self):
        super().require()
        if (self.purpose != PURPOSE or self.close_evidence_sha256 != CLOSE_SHA
                or self.symbol != 'par:BTC' or self.asset_id != 2670000
                or self.entry_side != 'BUY' or decimal(self.quantity) != D('.0002')
                or type(self.trigger_wait_seconds) is not int or self.trigger_wait_seconds != 120):
            raise ExchangeError('EXACT_TWO_LOT_NATIVE_QUALIFICATION_REQUIRED')
        return self


def require_partial_abort_path(spec, proposal):
    """Only two representable lots: full >=$10 stop or exact one-lot IOC abort."""
    if type(proposal) is not NativeQualificationProposal:
        raise ExchangeError('NATIVE_QUALIFICATION_PROPOSAL_TYPE_REQUIRED')
    p = proposal.require()
    if (spec.symbol != p.symbol or spec.asset_id != p.asset_id or spec.size_decimals != 4
            or spec.size_step != D('.0001') or decimal(p.quantity) != 2*spec.size_step
            or spec.normalize_size(decimal(p.quantity)) != decimal(p.quantity)):
        raise ExchangeError('NATIVE_QUALIFICATION_RUNTIME_MAPPING_CHANGED')
    for name in ('entry_limit', 'stop_limit', 'exit_bound'):
        px = decimal(getattr(p, name), positive=True)
        if (spec.normalize_price(px, 'BUY' if name == 'entry_limit' else 'SELL') != px
                or 2*spec.size_step*px < 10):
            raise ExchangeError('FULL_NATIVE_STOP_ORDINARY_MINIMUM_REQUIRED')
    trigger = spec.normalize_price(decimal(p.reference_bid)*D('.99'), 'SELL')
    if (decimal(p.entry_limit) != spec.normalize_price(decimal(p.reference_ask)*D('1.0005'), 'BUY')
            or decimal(p.stop_trigger) != trigger
            or decimal(p.stop_limit) != spec.normalize_price(trigger*D('.995'), 'SELL')
            or decimal(p.exit_bound) != decimal(p.stop_limit)):
        raise ExchangeError('NATIVE_QUALIFICATION_FIXED_TEST_GEOMETRY_REQUIRED')
    return dict(full_quantity=p.quantity, partial_abort_quantity=str(spec.size_step),
        partial_abort_scope=observed_scope(spec, 'SELL', spec.size_step),
        small_native_stop_verified=False, unattended_entry_authorized=False)


def check_entry(context, proposal, now):
    p = proposal.require(); q = context.quote
    require_partial_abort_path(context.spec, p)
    if (not context.readiness.account_ready or not context.reconciled or not context.feed_ready
            or context.positions or context.open_orders
            or context.readiness.team_address.lower() != p.team_wallet.lower()
            or context.readiness.signer_address.lower() != p.api_wallet.lower()
            or any(type(x) is not int or not 0 <= now-x <= 5000 for x in
                (context.readiness.observed_ms, context.account_ms, q.timestamp_ms, q.mark_timestamp_ms))
            or q.bid <= 0 or q.ask <= q.bid or (q.ask-q.bid)/q.mid*10000 > 15
            or abs(q.mark-q.oracle)/q.oracle*10000 > 50
            or abs(q.mid-q.oracle)/q.oracle*10000 > 100):
        raise ExchangeError('NATIVE_QUALIFICATION_FRESH_FLAT_ACCOUNT_BOOK_REQUIRED')
    if context.active_asset.get('leverage') != dict(type='cross', value=1):
        raise ExchangeError('NATIVE_QUALIFICATION_ONE_X_CROSS_REQUIRED')
    qty, px = decimal(p.quantity), decimal(p.entry_limit)
    fee = decimal(context.readiness.fees['userCrossRate'], positive=True)*2
    if (fee > decimal(p.taker_fee_rate) or px < q.ask or px > q.ask*D('1.0005')
            or decimal(p.stop_trigger) >= min(q.bid, q.mark)
            or qty > min(q.bid_quantity, q.ask_quantity)*D('.1')
            or qty*max(px, q.mark) > decimal(p.max_notional)
            or qty > decimal(context.active_asset['maxTradeSzs'][0], nonnegative=True)
            or qty*px*(1+fee*4) > min(decimal(x, nonnegative=True)
                for x in context.active_asset['availableToTrade'])):
        raise ExchangeError('NATIVE_QUALIFICATION_PRICE_DEPTH_FEE_MARGIN_REQUIRED')


def propose(context, client, source_hash, policy_hash):
    """Current-book fixed two-lot proposal; no increase to satisfy a minimum."""
    q, spec = context.quote, context.spec
    trigger = spec.normalize_price(q.bid*D('.99'), 'SELL')
    floor = spec.normalize_price(trigger*D('.995'), 'SELL')
    p = NativeQualificationProposal(spec.symbol, spec.asset_id, '0.0002', 'BUY',
        str(spec.normalize_price(q.ask*D('1.0005'), 'BUY')), str(floor), str(trigger), str(floor),
        str(q.bid), str(q.ask), str(q.mark), str(q.oracle), client.clock_ms(), source_hash,
        reliability_policy_hash=policy_hash,
        taker_fee_rate=str(decimal(context.readiness.fees['userCrossRate'], positive=True)*2),
        team_wallet=context.readiness.team_address, api_wallet=context.readiness.signer_address).require()
    check_entry(context, p, client.clock_ms())
    return p


@dataclass(frozen=True)
class NativeQualificationApproval(CertificationApproval):
    partial_entry_immediate_ioc_abort_accepted: bool = False
    unprotected_interval_and_residual_risk_accepted: bool = False
    loss_making_cleanup_accepted: bool = False
    acceptance_without_trigger_is_incomplete_accepted: bool = False
    mac_power_app_internet_dependency_accepted: bool = False


class NativeQualificationAuthorization(CertificationAuthorization):
    def __init__(self, *args, root, **kwargs):
        self.root = Path(root)
        super().__init__(*args, **kwargs)

    def require(self, team, signer):
        super().require(team, signer)
        a = self.approval
        if (type(self.proposal) is not NativeQualificationProposal
                or type(a) is not NativeQualificationApproval
                or any(getattr(a, k) is not True for k in (
                    'partial_entry_immediate_ioc_abort_accepted',
                    'unprotected_interval_and_residual_risk_accepted', 'loss_making_cleanup_accepted',
                    'acceptance_without_trigger_is_incomplete_accepted',
                    'mac_power_app_internet_dependency_accepted'))):
            raise ExchangeError('EXACT_NATIVE_QUALIFICATION_RISK_APPROVAL_REQUIRED')
        try:
            valid = hashlib.sha256((self.root/CLOSE_PROOF).read_bytes()).hexdigest() == CLOSE_SHA
        except OSError:
            valid = False
        if not valid:
            raise ExchangeError('ORIGINAL_EXACT_IOC_CLOSE_PROOF_REQUIRED')

    def check_action(self, action):
        self.require(self.proposal.team_wallet, self.proposal.api_wallet)
        if action.get('type') == 'cancel':
            # Parent ownership is checked by the existing authorization. A
            # child can only come from this manager's exact-ID REST readback.
            rows = action.get('cancels', [])
            key = 'qualification_stop:'+self.proposal.identity+':observation'
            observation = self.journal.control(key) or {}
            saved = self.journal.control('qualification_stop:'+self.proposal.identity) or {}
            parent = self.journal.intent('certification:'+self.proposal.identity+':protection')
            if (len(rows) == 1 and rows[0].get('a') == self.proposal.asset_id
                    and type(rows[0].get('o')) is int and parent
                    and observation.get('cloid') == parent['cloid']
                    and saved.get('configuration_hash') == self.proposal.identity
                    and observation.get('status') == 'TRIGGERED_UNSETTLED'
                    and str(rows[0]['o']) in observation.get('child_order_ids', [])
                    and str(rows[0]['o']) in observation.get('remaining_order_quantities', {})
                    and 0 <= self.clock_ms()-observation.get('observed_ms', -1) <= 5000):
                return
        super().check_action(action)
        if action.get('type') == 'order' and action.get('grouping', 'na') != 'na':
            raise ExchangeError('NATIVE_QUALIFICATION_FIXED_STOP_GROUPING_REQUIRED')


class NativeQualificationTransport(OfficialSDKTransport):
    def __init__(self, *args, **kwargs):
        auth = args[4] if len(args) > 4 else kwargs.get('authorization')
        if type(auth) is not NativeQualificationAuthorization:
            raise ExchangeError('NATIVE_QUALIFICATION_CAPABILITY_REQUIRED')
        auth.require(auth.proposal.team_wallet, auth.proposal.api_wallet)
        self.action_expiry_ms = auth.approval.expires_ms
        super().__init__(*args, **kwargs)

    def check(self, action):
        super().check(action)
        self.authorization.check_action(action)
        if action.get('type') == 'order' and action['orders'][0]['r'] is False:
            require_partial_abort_path(self.client.market(self.authorization.proposal.symbol),
                                      self.authorization.proposal)

    def transmit(self, payload):
        self.check(payload['action'])
        if payload.get('expiresAfter') != self.action_expiry_ms:
            raise ExchangeError('NATIVE_QUALIFICATION_SIGNED_EXPIRY_REQUIRED')
        self.authorization.claim_transmission(payload['action'])
        return super().transmit(payload)


class NativeQualificationRecovery(CertificationRecovery):
    def intent_rows(self):
        from .qualification_intent_recovery import qualification_intents
        return qualification_intents(self.journal)

    def recover(self):
        manager = getattr(self, 'native_stop_manager', None)
        if manager is not None and self.journal.control(manager.key):
            # Re-read the original parent and every reported child before
            # including those IDs in account recovery. No synthetic intents.
            observation = manager.reconcile()
            if observation['status'] == 'UNKNOWN':
                raise ExchangeError('NATIVE_CHILD_IDENTITY_RECONCILIATION_REQUIRED')
        return super().recover()

    def known_order_ids(self):
        known = super().known_order_ids()
        manager = getattr(self, 'native_stop_manager', None)
        if manager is None or not self.journal.control(manager.key):
            return known
        observation = manager.states.get(manager.proposal.symbol, {})
        parent = self.journal.intent(manager.intent_key)
        if (not parent or observation.get('cloid') != parent['cloid']
                or observation.get('status') in {'UNKNOWN','NOT_SUBMITTED','SUBMISSION_PENDING'}
                or not 0 <= self.account.client.clock_ms()-observation.get('observed_ms', -1) <= 5000):
            raise ExchangeError('NATIVE_CHILD_IDENTITY_RECONCILIATION_REQUIRED')
        return known | set(observation.get('child_order_ids', []))


class NativeQualificationExecution(HyperliquidExecution):
    def __init__(self, *args, proposal, **kwargs):
        self.proposal = proposal.require()
        super().__init__(*args, **kwargs)
        from .qualification_intent_recovery import QualificationPositionGuard
        self.position_guard = QualificationPositionGuard(self.journal, clock_ms=self.client.clock_ms)
        self.compliance_guard.position_guard = self.position_guard

    def _prepare_context_request(self, request, permission, context):
        if not request.reduce_only:
            if (request.symbol != self.proposal.symbol or request.side != 'BUY'
                    or request.quantity != decimal(self.proposal.quantity)
                    or request.price != decimal(self.proposal.entry_limit)
                    or request.tif != 'Ioc' or request.order_type != 'LIMIT'):
                raise ExchangeError('NATIVE_QUALIFICATION_EXACT_ENTRY_REQUIRED')
            check_entry(context, self.proposal, self.client.clock_ms())
        elif request.strategy_id == 'TESTNET_CERTIFICATION_EXIT':
            require_settled_exit_orders(self, current_intent=request.client_order_id)
        return request, permission

    def _guard(self, context, checked_ms, **kwargs):
        if kwargs.get('exact_full_close') is not None:
            require_settled_exit_orders(self,
                current_intent=kwargs['exact_full_close'].client_order_id)
        super()._guard(context, checked_ms, **kwargs)
        if kwargs.get('entry'):
            from dataclasses import replace
            from .hyperliquid_market_data import make_quote
            contexts = self.context_provider.market.get_asset_contexts()
            mark_ms = self.client.clock_ms()
            sent = mark_ms
            book = self.context_provider.market.get_orderbook(self.proposal.symbol)
            self.clock_health.observe(book.timestamp_ms, sent, self.client.clock_ms())
            quote = make_quote(book, contexts[self.proposal.symbol], self.client.clock_ms(),
                               mark_timestamp_ms=mark_ms)
            # Account timestamps are retained. This is fresh evidence for the
            # same immutable order, never a permit/time/price renewal.
            check_entry(replace(context, quote=quote), self.proposal, self.client.clock_ms())
            if self.transport.authorization.approval.expires_ms-self.client.clock_ms() < 150000:
                raise ExchangeError('NATIVE_QUALIFICATION_CLEANUP_TIME_REQUIRED')


class NativeQualificationSequence(CertificationSequence):
    """Reuse entry/accounting orchestration; manage the isolated native test."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, verified_full_position_closes=True, **kwargs)
        self.manager = QualificationStopManager(self.e, self.p)
        self.manager.entries_allowed = True  # Exact one-entry capability only.
        self.e.recovery.native_stop_manager = self.manager
        self.stop_observation = None
        self.native_fill_complete = False

    def completion_passed(self):
        return False  # Raw trigger/closing proof is checked independently.

    def owned_order_ids(self):
        return super().owned_order_ids() | set((self.stop_observation or {}).get('child_order_ids', []))

    def observe(self):
        self.e.recovery.recover()
        started = self.e.client.clock_ms()
        before = self.e.account.get_positions()
        orders = self.e.account.get_frontend_open_orders()
        after = self.e.account.get_positions()
        if (not same_position_exposure(before, after) or len(after) > 1
                or any(s != self.p.symbol for s in after)
                or not 0 <= self.e.client.clock_ms()-started <= 5000):
            raise ExchangeError('CERTIFICATION_ACCOUNT_RECONCILIATION_MISMATCH')
        self.report['actual_exchange_proof'].append(dict(timestamp_ms=self.e.client.clock_ms(),
            positions=[asdict(x) for x in after.values()], orders=orders,
            accounting=self.e.recovery.state.report()))
        return after, orders

    def manage_position(self, positions):
        held = positions[self.p.symbol]
        if abs(held.quantity) != decimal(self.p.quantity):
            if held.quantity != D('.0001'):
                raise ExchangeError('NATIVE_QUALIFICATION_UNEXPECTED_ENTRY_RESIDUAL')
            self.report['partial_entry_aborted_without_native_stop'] = True
            return
        observation = self.manager.submit(self.prefix+'protection')
        self.report['protection_accepted'] = observation['status'] == 'READBACK_ACCEPTED'
        self.report['native_stop_observations'] = [observation]
        deadline = min(self.e.client.clock_ms()+self.p.trigger_wait_seconds*1000,
                       self.auth.approval.expires_ms-120000)
        while observation['status'] == 'READBACK_ACCEPTED' and self.e.client.clock_ms() < deadline:
            self.wait()
            self.auth.require(self.p.team_wallet, self.p.api_wallet)
            observation = self.manager.reconcile()
            self.report['native_stop_observations'].append(observation)
        if observation['status'] in {'UNKNOWN', 'SUBMISSION_PENDING', 'STALE_COVERAGE'}:
            raise ExchangeError('NATIVE_STOP_UNCERTAIN_READ_ONLY_REVIEW_REQUIRED')
        if observation.get('remaining_order_quantities'):
            self.e.recovery.recover()  # Adopt a resolved original lost-ACK ID.
            observation = self.manager.cancel()
            self.report['native_stop_observations'].append(observation)
        if not observation.get('remainder_settled'):
            raise ExchangeError('NATIVE_STOP_UNSETTLED_NO_COMPETING_IOC')
        self.stop_observation = observation
        self.native_fill_complete = (observation['status'] == 'FILLED'
            and decimal(observation.get('filled_quantity', '0')) == decimal(self.p.quantity)
            and observation.get('flat_observed') is True)

    def close(self):
        for attempt in range(self.p.max_exit_attempts):
            positions, _ = self.observe()
            if not positions:
                return
            require_settled_exit_orders(self.e)
            held = positions[self.p.symbol]
            if held.quantity <= 0:
                raise ExchangeError('NATIVE_QUALIFICATION_LONG_EXPOSURE_REQUIRED')
            q = self.e.context_provider.market.get_quote(self.p.symbol)
            now = self.e.client.clock_ms()
            if not 0 <= now-q.timestamp_ms <= 5000:
                raise ExchangeError('CERTIFICATION_EXIT_STALE_BOOK')
            spec = self.e.client.market(self.p.symbol)
            px = spec.normalize_price(q.bid*D('.998'), 'SELL')
            if px < decimal(self.p.exit_bound):
                raise ExchangeError('CERTIFICATION_EXIT_PRICE_BOUND')
            qty = scoped_exact_full_close_size(spec, held, side='SELL',
                maximum_quantity=self.p.quantity, limit_price=px)
            request = OrderRequest(self.p.symbol, 'SELL', qty, px, reduce_only=True,
                strategy_id='TESTNET_CERTIFICATION_EXIT', tif='Ioc',
                client_order_id=self.prefix+'exit:'+str(attempt))
            result = self.resolved(self.e.close_full_position(request,
                permission=test_permission(request, self.p, now, reason='CERTIFICATION_REDUCE_ONLY_EXIT')))
            self.report.setdefault('exit_attempts', []).append(asdict(result))
            require_settled_exit_orders(self.e)
        positions, _ = self.observe()
        if positions:
            raise ExchangeError('CERTIFICATION_EXIT_PARTIAL_URGENT_REVIEW')

    def run(self):
        result = super().run()
        result['small_native_stop_verified'] = False
        result['native_trigger_closing_observed'] = self.native_fill_complete
        result['certification_passed'] = False
        result['native_protection_qualified'] = False
        result['practice_ready'] = result['live_ready'] = False
        # Export raw proof separately. Never promote by this summary flag.
        if (result.get('status') == 'TRADE_CLOSED_RECONCILED'
                and result.get('final_flat') and self.native_fill_complete):
            result['native_qualification_status'] = 'TRIGGER_CLOSING_RECORDED_REQUIRES_RAW_PROOF_VALIDATION'
        else:
            result['native_qualification_status'] = 'INCOMPLETE'
        return result
