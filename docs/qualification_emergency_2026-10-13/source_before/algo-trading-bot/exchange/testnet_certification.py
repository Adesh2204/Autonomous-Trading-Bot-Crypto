"""One operator-approved execution experiment. No scanner or strategy imports.

PAPER configuration stays locked. Only this capability-bound SDK transport can
write for certification; it cannot approve autonomous practice or administration.
All prices are limits, and the exchange account supplies every accounting event.
"""
from dataclasses import asdict, dataclass, replace
from decimal import Decimal as D
from enum import Enum
import json

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .exchange_rules import RiskPermission
from .compliance_guard import OrderProvenance
from .order_lifecycle import OrderRequest, OrderState
from .position_protection import ProtectionPlan
from .sdk_transport import OfficialSDKTransport
from .partial_fill_safety import (partial_path_assessment, exact_full_close_size,
                                residual_observation)

TEAM = '0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C'
API = '0x46c9BED595770150752E7fA3806449F81E0Ec6f9'


def require_safe_partial_path(spec, proposal):
    """Protective orders still require the ordinary $10 minimum.

Do not open exposure which a one-lot IOC fill could strand. An authoritative
closing path alone does not verify stop acceptance. Both capabilities are
needed before changing this gate; approval cannot override missing evidence.
"""
    assessment = partial_path_assessment(spec, proposal)
    if not assessment['entry_admissible_under_documented_minimum']:
        raise ExchangeError(assessment['blocker'])


class ExecutionMode(str, Enum):
    PAPER = 'PAPER'
    TESTNET_CERTIFICATION = 'TESTNET_CERTIFICATION'
    TESTNET_PRACTICE = 'TESTNET_PRACTICE'


@dataclass(frozen=True)
class CertificationProposal:
    symbol: str
    asset_id: int
    quantity: str
    entry_side: str
    entry_limit: str
    exit_bound: str
    stop_trigger: str
    stop_limit: str
    reference_bid: str
    reference_ask: str
    reference_mark: str
    reference_oracle: str
    observed_ms: int
    source_hash: str
    reliability_policy_hash: str = ''
    max_notional: str = '25'
    session_loss_budget: str = '10'
    entry_slippage_bps: str = '5'
    exit_slippage_bps: str = '20'
    taker_fee_rate: str = '.0009'
    max_exit_attempts: int = 2
    max_signed_actions: int = 6
    team_wallet: str = TEAM
    api_wallet: str = API
    network: str = 'testnet'
    dex: str = 'par'
    mode: str = 'TESTNET_CERTIFICATION'

    def require(self):
        nums = {k: decimal(getattr(self, k), positive=True) for k in
                ('quantity', 'entry_limit', 'exit_bound', 'stop_trigger', 'stop_limit',
                 'reference_bid', 'reference_ask', 'reference_mark', 'reference_oracle',
                 'max_notional', 'session_loss_budget', 'entry_slippage_bps',
                 'exit_slippage_bps', 'taker_fee_rate')}
        if (self.network != 'testnet' or self.dex != 'par' or self.mode != 'TESTNET_CERTIFICATION'
                or self.symbol not in {'par:BTC', 'par:ETH', 'par:HYPE'}
                or self.team_wallet.lower() != TEAM.lower() or self.api_wallet.lower() != API.lower()
                or self.entry_side not in {'BUY', 'SELL'} or not self.source_hash or not self.reliability_policy_hash
                or type(self.asset_id) is not int or self.asset_id < 100000
                or type(self.observed_ms) is not int or self.observed_ms < 0
                or nums['max_notional'] > 25 or nums['session_loss_budget'] > 10
                or nums['entry_slippage_bps'] > 5 or nums['exit_slippage_bps'] > 20
                or type(self.max_exit_attempts) is not int or self.max_exit_attempts != 2
                or type(self.max_signed_actions) is not int or self.max_signed_actions != 6
                or nums['quantity']*nums['entry_limit'] > nums['max_notional']
                or nums['quantity']*min(nums['entry_limit'], nums['stop_limit']) < 10):
            raise ExchangeError('INVALID_CERTIFICATION_PROPOSAL')
        if self.entry_side == 'BUY':
            if not nums['stop_limit'] <= nums['exit_bound'] < nums['stop_trigger'] < nums['entry_limit']:
                raise ExchangeError('INVALID_CERTIFICATION_GEOMETRY')
        elif not nums['entry_limit'] < nums['stop_trigger'] < nums['exit_bound'] <= nums['stop_limit']:
            raise ExchangeError('INVALID_CERTIFICATION_GEOMETRY')
        planned_loss = nums['quantity']*abs(nums['entry_limit']-nums['exit_bound'])
        planned_loss += nums['quantity']*(nums['entry_limit']+nums['exit_bound'])*nums['taker_fee_rate']
        if planned_loss > nums['session_loss_budget']:
            raise ExchangeError('CERTIFICATION_LOSS_BUDGET_EXCEEDED')
        return self

    @property
    def identity(self):
        self.require()
        return fingerprint(asdict(self))


def propose(context, client, source_hash, *, reliability_policy_hash, side='BUY', max_notional=D(25)):
    """Conservative current-book proposal, never a strategy signal or permission."""
    q, spec, now = context.quote, context.spec, client.clock_ms()
    if (side not in {'BUY', 'SELL'} or max_notional <= 0 or max_notional > 25
            or not context.readiness.account_ready or not context.reconciled
            or context.positions or context.open_orders or not context.feed_ready
            or not 0 <= now-q.timestamp_ms <= 5000
            or q.mark_timestamp_ms is None or not 0 <= now-q.mark_timestamp_ms <= 5000
            or q.bid <= 0 or q.ask <= q.bid or (q.ask-q.bid)/q.mid*10000 > 15
            or abs(q.mark-q.oracle)/q.oracle*10000 > 50
            or abs(q.mid-q.oracle)/q.oracle*10000 > 100):
        raise ExchangeError('CERTIFICATION_FRESH_ACCOUNT_BOOK_REQUIRED')
    lev = context.active_asset.get('leverage')
    if lev != dict(type='cross', value=1):
        raise ExchangeError('CERTIFICATION_ONE_X_CROSS_REQUIRED')
    entry = spec.normalize_price(q.ask*D('1.0005') if side == 'BUY' else q.bid*D('.9995'), side)
    qty = spec.normalize_size(max_notional/max(entry, q.mark))
    close_side = 'SELL' if side == 'BUY' else 'BUY'
    trigger = spec.normalize_price(q.bid*D('.99') if side == 'BUY' else q.ask*D('1.01'), close_side)
    bound = spec.normalize_price(trigger*D('.995') if side == 'BUY' else trigger*D('1.005'), close_side)
    depth = q.ask_quantity if side == 'BUY' else q.bid_quantity
    exit_depth = q.bid_quantity if side == 'BUY' else q.ask_quantity
    idx = 0 if side == 'BUY' else 1
    fee = decimal(context.readiness.fees['userCrossRate'], positive=True)*2
    if (qty > min(depth, exit_depth)*D('.1') or qty*entry < 10
            or qty > decimal(context.active_asset['maxTradeSzs'][idx], nonnegative=True)
            or qty*entry*(1+fee*4) > decimal(context.active_asset['availableToTrade'][idx], nonnegative=True)
            or qty*entry/1 < spec.maintenance_margin(qty*entry)):
        raise ExchangeError('CERTIFICATION_LIQUIDITY_MARGIN_MINIMUM_REQUIRED')
    return CertificationProposal(spec.symbol, spec.asset_id, str(qty), side, str(entry), str(bound),
        str(trigger), str(bound), str(q.bid), str(q.ask), str(q.mark), str(q.oracle), now, source_hash,
        max_notional=str(max_notional), taker_fee_rate=str(fee), reliability_policy_hash=reliability_policy_hash,
        team_wallet=context.readiness.team_address, api_wallet=context.readiness.signer_address).require()


@dataclass(frozen=True)
class CertificationApproval:
    proposal_hash: str
    operator_approval: str
    approved_ms: int
    expires_ms: int
    manually_verified_wallets: bool = False
    sole_signer_host_confirmed: bool = False
    maximum_one_entry: bool = False


class CertificationAuthorization:
    def __init__(self, proposal, approval, journal, *, clock_ms, source_hash, policy_hash):
        self.proposal, self.approval, self.journal = proposal, approval, journal
        self.clock_ms, self.source_hash = clock_ms, source_hash
        self.policy_hash = policy_hash
        self.revoked = False

    def require(self, team, signer):
        from venue_config import require_paper_migration
        require_paper_migration()  # Never set global LIVE flags for this experiment.
        p, a, now = self.proposal.require(), self.approval, self.clock_ms()
        if (self.revoked or not isinstance(a, CertificationApproval)
                or a.proposal_hash != p.identity or not a.operator_approval.strip()
                or a.manually_verified_wallets is not True or a.sole_signer_host_confirmed is not True
                or a.maximum_one_entry is not True
                or type(a.approved_ms) is not int or type(a.expires_ms) is not int
                or not a.approved_ms <= now < a.expires_ms <= a.approved_ms+300000
                or a.approved_ms < p.observed_ms or a.approved_ms-p.observed_ms > 300000
                or team.lower() != p.team_wallet.lower() or signer.lower() != p.api_wallet.lower()
                or self.source_hash() != p.source_hash
                or self.policy_hash() != p.reliability_policy_hash
                or self.journal.team_address != p.team_wallet.lower()):
            raise ExchangeError('EXACT_HUMAN_CERTIFICATION_APPROVAL_REQUIRED')
        if (self.journal.control('certification_completed:'+p.identity) or
                self.journal.control('certification_halted:'+p.identity)):
            raise ExchangeError('CERTIFICATION_ALREADY_FINISHED')

    def check_action(self, action):
        p = self.proposal
        self.require(p.team_wallet, p.api_wallet)
        if action.get('type') == 'cancel':
            rows = action.get('cancels', [])
            if len(rows) != 1 or rows[0].get('a') != p.asset_id:
                raise ExchangeError('CERTIFICATION_ACTION_OUTSIDE_SCOPE')
            own = [r for r in self.journal.intents() if str(r['oid']) == str(rows[0].get('o'))
                   and r['intent_key'].startswith('certification:'+p.identity+':')]
            if len(own) != 1:
                raise ExchangeError('CERTIFICATION_OWN_ORDER_REQUIRED')
            return
        if action.get('type') != 'order' or len(action.get('orders', [])) != 1:
            raise ExchangeError('CERTIFICATION_ACTION_OUTSIDE_SCOPE')
        w = action['orders'][0]
        row = self.journal.db.execute('SELECT * FROM intents WHERE cloid=?', (w.get('c'),)).fetchone()
        prefix = 'certification:'+p.identity+':'
        if (row is None or not row['intent_key'].startswith(prefix) or w.get('a') != p.asset_id
                or type(w.get('b')) is not bool or type(w.get('r')) is not bool
                or decimal(w.get('s'), positive=True) > decimal(p.quantity)):
            raise ExchangeError('CERTIFICATION_ACTION_OUTSIDE_SCOPE')
        px, qty = decimal(w.get('p'), positive=True), decimal(w['s'], positive=True)
        if not w['r']:
            if (row['intent_key'] != prefix+'entry' or w['b'] != (p.entry_side == 'BUY')
                    or qty != decimal(p.quantity) or px != decimal(p.entry_limit)
                    or qty*px > decimal(p.max_notional) or w['t'] != {'limit': {'tif': 'Ioc'}}):
                raise ExchangeError('CERTIFICATION_ENTRY_OUTSIDE_SCOPE')
        else:
            if w['b'] == (p.entry_side == 'BUY'):
                raise ExchangeError('CERTIFICATION_EXIT_DIRECTION')
            if (p.entry_side == 'BUY' and px < decimal(p.exit_bound) or
                    p.entry_side == 'SELL' and px > decimal(p.exit_bound)):
                raise ExchangeError('CERTIFICATION_EXIT_PRICE_BOUND')
            if 'trigger' in w.get('t', {}):
                if (row['intent_key'] != prefix+'protection' or px != decimal(p.stop_limit)
                        or w['t'] != {'trigger': {'triggerPx': p.stop_trigger.rstrip('0').rstrip('.')
                            if '.' in p.stop_trigger else p.stop_trigger, 'isMarket': False, 'tpsl': 'sl'}}):
                    raise ExchangeError('CERTIFICATION_PROTECTION_OUTSIDE_SCOPE')
            elif (row['intent_key'] not in {prefix+'exit:0', prefix+'exit:1'}
                    or w['t'] != {'limit': {'tif': 'Ioc'}}):
                raise ExchangeError('CERTIFICATION_EXIT_OUTSIDE_SCOPE')

    def claim_transmission(self, action):
        """Persist before HTTP; failed/uncertain writes consume the attempt forever."""
        self.check_action(action)
        p, key = self.proposal, 'certification_transmissions:'+self.proposal.identity
        digest = fingerprint(action)
        with self.journal.transaction():
            raw = self.journal.db.execute('SELECT value FROM controls WHERE name=?', (key,)).fetchone()
            history = json.loads(raw[0]) if raw else []
            entry = action['type'] == 'order' and action['orders'][0]['r'] is False
            if (len(history) >= p.max_signed_actions or any(h['hash'] == digest for h in history)
                    or entry and any(h['entry'] for h in history)):
                raise ExchangeError('CERTIFICATION_ATTEMPT_ALREADY_CONSUMED')
            history.append(dict(hash=digest, entry=entry, timestamp_ms=self.clock_ms()))
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                                    (key, json.dumps(history)))

    def revoke(self):
        self.revoked = True


class CertificationSDKTransport(OfficialSDKTransport):
    def __init__(self, *args, **kwargs):
        auth = args[4] if len(args) > 4 else kwargs.get('authorization')
        if type(auth) is not CertificationAuthorization:
            raise ExchangeError('CERTIFICATION_CAPABILITY_REQUIRED')
        auth.require(auth.proposal.team_wallet, auth.proposal.api_wallet)
        self.action_expiry_ms = auth.approval.expires_ms
        super().__init__(*args, **kwargs)

    def check(self, action):
        super().check(action)
        self.authorization.check_action(action)
        if action.get('type') == 'order' and action['orders'][0]['r'] is False:
            require_safe_partial_path(self.client.market(self.authorization.proposal.symbol),
                                      self.authorization.proposal)

    def transmit(self, payload):
        self.check(payload['action'])
        if payload.get('expiresAfter') != self.action_expiry_ms:
            raise ExchangeError('CERTIFICATION_SIGNED_EXPIRY_REQUIRED')
        self.authorization.claim_transmission(payload['action'])
        return super().transmit(payload)


class CertificationProtection:
    """Approved fixed test stop, deliberately independent of VWAP/ATR geometry."""
    def __init__(self, executor, proposal):
        self.executor, self.proposal = executor, proposal
        self.managers, self.states = {}, {}
        self.running = True  # The bounded sequence drives protection explicitly.
        self.entries_allowed = True
        executor.protection = self

    def _plan(self, symbol, position, manager, observed_ms):
        p = self.proposal
        if (symbol != p.symbol or not position.quantity
                or (position.quantity > 0) != (p.entry_side == 'BUY')
                or abs(position.quantity) > decimal(p.quantity)):
            raise ExchangeError('CERTIFICATION_PROTECTION_POSITION_CONFLICT')
        side = 'SELL' if position.quantity > 0 else 'BUY'
        quantity = exact_full_close_size(self.executor.client.market(symbol), position, side=side,
            maximum_quantity=p.quantity, limit_price=p.stop_limit)
        return ProtectionPlan(symbol, side, quantity, decimal(p.stop_trigger),
            decimal(p.stop_limit), decimal(p.stop_trigger), 'CERTIFICATION_ONLY:'+p.identity,
            observed_ms, position.entry_price, 'CATASTROPHIC_STOP', False)


def test_permission(request, proposal, now, *, reason=None):
    """Controlled-test provenance cannot masquerade as a frozen strategy signal."""
    key = 'certification:'+proposal.identity
    a = dict(operator_authorization=key, objective='ONE_EXECUTION_ROUND_TRIP_NOT_A_STRATEGY_SIGNAL',
             exit_procedure='BOUNDED_REDUCE_ONLY_IOC_AND_FLAT_RECONCILIATION', market=proposal.symbol,
             expected_quantity=str(request.quantity), timestamp_ms=now, expires_ms=now+300000)
    provenance = OrderProvenance(key, request.strategy_id, 'EXECUTION_CERTIFICATION', now,
        request.symbol, request.side, reason or 'OPERATOR_APPROVED_EXECUTION_TEST',
        dict(allowed=True, max_notional=proposal.max_notional, loss_budget=proposal.session_loss_budget),
        dict(allowed=True, price=str(request.price), tif=request.tif),
        classification='CONTROLLED_TEST_ORDER', action_type='CONTROLLED_TEST_ORDER',
        source_position_id=proposal.symbol if request.reduce_only else None, test_authorization=a)
    return RiskPermission(key, request.symbol, request.side, request.quantity, now,
        request.reduce_only, reason, request.price, provenance)


class CertificationSequence:
    """Bounded orchestration over the existing validator, journal and SDK executor."""
    def __init__(self, executor, proposal, authorization, *, wait=None,
                 verified_full_position_closes=False):
        self.e, self.p, self.auth = executor, proposal.require(), authorization
        self.wait = wait or (lambda: None)
        self.verified_full_position_closes = verified_full_position_closes is True
        self.prefix = 'certification:'+proposal.identity+':'
        self.report = dict(status='NO_ORDER_AUTHORIZED', execution_mode='TESTNET_CERTIFICATION',
            production_mode='PAPER', strategy_signal=False, exclude_from_strategy_statistics=True,
            proposal=asdict(proposal), actual_exchange_proof=[], realized_pnl=None,
            realized_pnl_status='REALIZED_PNL_NOT_CERTIFIED', practice_ready=False, live_ready=False,
            protection_accepted=False, certification_passed=False)

    def observe(self):
        self.e.recovery.recover()
        positions = self.e.account.get_positions()
        orders = self.e.account.get_frontend_open_orders()
        after = self.e.account.get_positions()
        if positions != after or len(after) > 1 or any(s != self.p.symbol for s in after):
            raise ExchangeError('CERTIFICATION_ACCOUNT_RECONCILIATION_MISMATCH')
        self.report['actual_exchange_proof'].append(dict(timestamp_ms=self.e.client.clock_ms(),
            positions=[asdict(x) for x in after.values()], orders=orders,
            accounting=self.e.recovery.state.report()))
        residual = (residual_observation(self.e.client.market(self.p.symbol), after[self.p.symbol],
                    self.p, self.e.client.clock_ms()) if after else None)
        self.report['residual_position'] = residual
        self.e.journal.control('certification_residual:'+self.p.identity,
                               residual if residual is not None else False)
        return after, orders

    def resolved(self, order):
        if order.state in {OrderState.UNKNOWN, OrderState.SUBMITTED}:
            for _ in range(3):
                self.wait()
                order = self.e.recover_uncertain(order.intent_key)
                if order.state not in {OrderState.UNKNOWN, OrderState.SUBMITTED}:
                    break
        if order.state in {OrderState.UNKNOWN, OrderState.SUBMITTED}:
            raise ExchangeError('CERTIFICATION_UNCERTAIN_ORDER_URGENT_REVIEW')
        return order

    def _verify_protection(self, plan, order, rows, position):
        quantity = exact_full_close_size(self.e.client.market(plan.symbol), position, side=plan.side,
            maximum_quantity=self.p.quantity, limit_price=plan.limit_price)
        if quantity != plan.quantity:
            raise ExchangeError('CERTIFICATION_PROTECTION_POSITION_CHANGED')
        matching = [o for o in rows if str(o['oid']) == str(order.exchange_order_id)]
        if len(matching) != 1:
            raise ExchangeError('CERTIFICATION_PROTECTION_NOT_CONFIRMED')
        row = matching[0]
        detail = self.e.account._query('orderStatus', oid=order.exchange_order_id)
        if (row.get('cloid') != order.cloid or row.get('isTrigger') is not True
                or row.get('reduceOnly') is not True or row['side'] != ('A' if plan.side == 'SELL' else 'B')
                or decimal(row['sz']) != plan.quantity or decimal(row['triggerPx']) != plan.trigger_price
                or decimal(row['limitPx']) != plan.limit_price or row.get('orderType') != 'Stop Limit'
                or detail.get('status') != 'order' or detail['order']['status'] != 'open'
                or any(detail['order']['order'].get(k) != row.get(k) for k in
                       ('coin','side','oid','sz','limitPx','isTrigger','reduceOnly','triggerPx','orderType'))):
            raise ExchangeError('CERTIFICATION_PROTECTION_READBACK_MISMATCH')
        self.report['protection_accepted'] = True
        self.report['protection_plan'] = asdict(plan)

    def close(self):
        for attempt in range(self.p.max_exit_attempts):
            positions, orders = self.observe()
            if not positions:
                return
            held = positions[self.p.symbol]
            q = self.e.context_provider.market.get_quote(self.p.symbol)
            now = self.e.client.clock_ms()
            if not 0 <= now-q.timestamp_ms <= 5000:
                raise ExchangeError('CERTIFICATION_EXIT_STALE_BOOK')
            side = 'SELL' if held.quantity > 0 else 'BUY'
            spec = self.e.client.market(self.p.symbol)
            px = spec.normalize_price(q.bid*D('.998') if side == 'SELL' else q.ask*D('1.002'), side)
            if (side == 'SELL' and px < decimal(self.p.exit_bound)
                    or side == 'BUY' and px > decimal(self.p.exit_bound)):
                raise ExchangeError('CERTIFICATION_EXIT_PRICE_BOUND')
            from .partial_fill_safety import scoped_exact_full_close_size
            sizing = scoped_exact_full_close_size if self.verified_full_position_closes else exact_full_close_size
            quantity = sizing(spec, held, side=side,
                maximum_quantity=self.p.quantity, limit_price=px)
            req = OrderRequest(self.p.symbol, side, quantity, px, reduce_only=True,
                strategy_id='TESTNET_CERTIFICATION_EXIT', tif='Ioc', client_order_id=self.prefix+'exit:'+str(attempt))
            submit = self.e.close_full_position if self.verified_full_position_closes else self.e.submit
            outcome = self.resolved(submit(req, permission=test_permission(req, self.p, now,
                                                                 reason='CERTIFICATION_REDUCE_ONLY_EXIT')))
            self.report.setdefault('exit_attempts', []).append(dict(attempt=attempt,
                requested_quantity=str(quantity), outcome=asdict(outcome)))
            if outcome.state == OrderState.OPEN:
                self.e.cancel_order(self.p.symbol, outcome.exchange_order_id, critical=True)
                self.resolved(self.e.recover_uncertain(outcome.intent_key))
            self.wait()
        positions, _ = self.observe()
        if positions:
            raise ExchangeError('CERTIFICATION_EXIT_PARTIAL_URGENT_REVIEW')

    def run(self):
        try:
            self.auth.require(self.p.team_wallet, self.p.api_wallet)
            if self.e.journal.control('certification_started:'+self.p.identity):
                raise ExchangeError('CERTIFICATION_RESTART_READ_ONLY_RECOVERY_REQUIRED')
            positions, orders = self.observe()
            if positions or orders or not self.e.recovery.last_report.ready:
                raise ExchangeError('CERTIFICATION_INITIAL_FLAT_ACCOUNT_REQUIRED')
            self.report['equity_before'] = str(self.e.recovery.state.equity.reported_account_value)
            before_fills = set(self.e.recovery.state.fills)
            before_funding = set(self.e.recovery.state.funding)
            self.e.journal.control('certification_started:'+self.p.identity, True)
            self.e.entries_paused = False
            req = OrderRequest(self.p.symbol, self.p.entry_side, self.p.quantity, self.p.entry_limit,
                strategy_id='TESTNET_CERTIFICATION_ENTRY', tif='Ioc', client_order_id=self.prefix+'entry')
            self.report['status'] = 'ENTRY_SUBMISSION_PENDING'
            order = self.resolved(self.e.submit(req, permission=test_permission(req, self.p, self.e.client.clock_ms())))
            self.report['entry'] = asdict(order)
            positions, orders = self.observe()
            entry_fills = [f for f in self.e.recovery.state.fills.values()
                           if f.order_id == str(order.exchange_order_id) and f.symbol == self.p.symbol]
            observed_qty = sum((f.quantity for f in entry_fills), D(0))
            if (observed_qty != order.filled_quantity or any(f.side != self.p.entry_side for f in entry_fills)
                    or positions and observed_qty != abs(positions[self.p.symbol].quantity)):
                raise ExchangeError('CERTIFICATION_ENTRY_FILL_POSITION_NOT_RECONCILED')
            if orders and order.exchange_order_id is not None:
                self.e.cancel_order(self.p.symbol, order.exchange_order_id, critical=True)
                self.resolved(self.e.recover_uncertain(order.intent_key))
                positions, orders = self.observe()
            if not positions:
                self.report['status'] = 'ORDER_REJECTED' if order.state == OrderState.REJECTED else 'NO_FILL_VERIFIED'
            else:
                self.report['status'] = 'PARTIAL_FILL' if order.state == OrderState.PARTIALLY_FILLED else 'FILLED_POSITION'
                try:
                    plan = self.e.protection._plan(self.p.symbol, positions[self.p.symbol], None, self.e.client.clock_ms())
                    protective = self.resolved(self.e.submit_protection(plan, self.prefix+'protection'))
                    positions, orders = self.observe()
                    if positions:
                        self._verify_protection(plan, protective, orders, positions[self.p.symbol])
                        self.report['status'] = 'OPEN_PROTECTED_POSITION'
                except Exception as exc:
                    self.report['protection_error'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
                    self.report['status'] = 'EMERGENCY_EXIT_REQUIRED'
                self.close()  # Never wait for a profit.
            positions, orders = self.observe()
            if positions:
                raise ExchangeError('CERTIFICATION_FINAL_POSITION_NOT_FLAT')
            for row in orders:
                own = [r for r in self.e.journal.intents() if str(r['oid']) == str(row['oid'])
                       and r['intent_key'].startswith(self.prefix)]
                if len(own) != 1:
                    raise ExchangeError('CERTIFICATION_UNEXPECTED_ORDER')
                self.e.cancel_order(self.p.symbol, row['oid'], critical=True)
            positions, orders = self.observe()
            if positions or orders or not self.e.recovery.last_report.ready:
                raise ExchangeError('CERTIFICATION_FINAL_RECONCILIATION_REQUIRED')
            fills = [f for k,f in self.e.recovery.state.fills.items() if k not in before_fills]
            known = {str(r['oid']) for r in self.e.journal.intents() if r['intent_key'].startswith(self.prefix) and r['oid']}
            if any(f.order_id not in known for f in fills):
                raise ExchangeError('CERTIFICATION_UNEXPECTED_FILL')
            entries = [f for f in fills if f.side == self.p.entry_side]
            exits = [f for f in fills if f.side != self.p.entry_side]
            self.report['final_flat'] = True
            if entries or exits:
                self.report.update(certify_realized(entries, exits,
                    [f for k,f in self.e.recovery.state.funding.items() if k not in before_funding], self.p))
                self.report['equity_after'] = str(self.e.recovery.state.equity.reported_account_value)
                delta = decimal(self.report['equity_after'])-decimal(self.report['equity_before'])
                self.report['equity_delta'] = str(delta)
                if abs(delta-decimal(self.report['realized_pnl']['net_realized_pnl'])) > D('.000001'):
                    raise ExchangeError('CERTIFICATION_EQUITY_ACCOUNTING_MISMATCH')
                self.report['status'] = 'TRADE_CLOSED_RECONCILED'
                self.report['certification_passed'] = self.report['protection_accepted'] is True
                if not self.report['certification_passed']:
                    self.report['certification_blocker'] = 'ACTUAL_POSITION_PROTECTION_NOT_VERIFIED'
            # This is a consumed-attempt marker, not a successful qualification.
            self.e.journal.control('certification_completed:'+self.p.identity, True)
        except Exception as exc:
            self.report['error'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
            if self.report['status'] not in {'NO_ORDER_AUTHORIZED', 'NO_FILL_VERIFIED', 'ORDER_REJECTED'}:
                self.report['status'] = 'EMERGENCY_EXIT_REQUIRED'
            else:
                self.report['status'] = 'PREFLIGHT_BLOCKED'
            self.report['realized_pnl_status'] = 'REALIZED_PNL_NOT_CERTIFIED'
            self.report['operator_action_required'] = self.report['status'] == 'EMERGENCY_EXIT_REQUIRED'
            self.e.journal.control('certification_halted:'+self.p.identity, True)
        finally:
            self.e.entries_paused = True
            self.auth.revoke()
            self.e.journal.event('CERTIFICATION_RESULT', self.e.client.clock_ms(), report=self.report)
        from .sdk_transport import OfflineSDKTransport
        self.report['evidence_scope'] = ('OFFLINE_SIGNED_FIXTURE' if type(self.e.transport) is OfflineSDKTransport
                                         else 'ACTUAL_TESTNET_ACCOUNT')
        return self.report


def certify_realized(entries, exits, funding, proposal):
    """Exchange closedPnl is distinct from independent fill-price arithmetic."""
    events = entries+exits
    if (not entries or not exits or any(f.source != 'EXCHANGE_REPORTED_FILL'
            or f.closed_pnl is None or f.fee_token != 'USDPR' or f.symbol != proposal.symbol for f in events)
            or len({f.identity for f in events}) != len(events)
            or any(f.source != 'EXCHANGE_REPORTED_USER_FUNDING' or f.symbol != proposal.symbol for f in funding)):
        raise ExchangeError('REALIZED_PNL_EXCHANGE_EVENTS_REQUIRED')
    quantity = sum((f.quantity for f in entries), D(0))
    if quantity != sum((f.quantity for f in exits), D(0)) or quantity > decimal(proposal.quantity):
        raise ExchangeError('REALIZED_PNL_FILL_SIZE_MISMATCH')
    entry_notional = sum((f.quantity*f.price for f in entries), D(0))
    exit_notional = sum((f.quantity*f.price for f in exits), D(0))
    arithmetic = (exit_notional-entry_notional)*(1 if proposal.entry_side == 'BUY' else -1)
    gross = sum((f.closed_pnl for f in events), D(0))
    if abs(arithmetic-gross) > D('.000001'):
        raise ExchangeError('REALIZED_PNL_CLOSED_FIELD_MISMATCH')
    entry_fee, exit_fee = sum((f.fee for f in entries), D(0)), sum((f.fee for f in exits), D(0))
    expected_fee = (entry_notional+exit_notional)*decimal(proposal.taker_fee_rate)
    if abs(entry_fee+exit_fee-expected_fee) > max(D('.000002'), expected_fee*D('.02')):
        raise ExchangeError('CERTIFICATION_FEE_MISMATCH')
    cash = sum((f.cashflow for f in funding), D(0))
    net = gross-entry_fee-exit_fee+cash
    if net < -decimal(proposal.session_loss_budget):
        raise ExchangeError('CERTIFICATION_OBSERVED_LOSS_BUDGET_EXCEEDED')
    return dict(realized_pnl_status='EXCHANGE_REALIZED_PNL_CERTIFIED', realized_pnl={k:str(v) for k,v in
        dict(quantity=quantity, entry_notional=entry_notional, actual_entry_price=entry_notional/quantity,
             actual_exit_price=exit_notional/quantity, gross_closed_pnl=gross, fill_price_gross=arithmetic,
             actual_entry_fee=entry_fee, actual_exit_fee=exit_fee, actual_funding=cash, net_realized_pnl=net).items()},
        fill_proof=[asdict(f) for f in events], funding_proof=[asdict(f) for f in funding])
