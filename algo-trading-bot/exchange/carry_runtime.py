"""Unattended funding-carry basket on the existing signed execution stack.

One owner, one journal, the official SDK transport, the central validator, the
compliance guard with exact-action permits, and an exchange-side reduce-only
stop for every leg. This module only produces CARRY_LONG/CARRY_SHORT entries
and reduce-only exits. It never transfers, changes account mode or leverage.

Differences from the 1-hour VWAP session, all opt-in through owner hooks:
  * up to `max_positions` concurrent legs (basket entry/recovery/position guards)
  * our own resting stops do not count as pending exits
  * entry liquidity is checked against L2 depth inside the order's own limit
  * a multi-day mandate bounded by the published scored window
"""
from dataclasses import dataclass, asdict, replace
from decimal import Decimal as D
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, logging, threading, time

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .exchange_rules import RiskPermission
from .compliance_guard import OrderProvenance
from .hyperliquid_execution import HyperliquidExecution
from .order_lifecycle import OrderRequest
from .position_protection import ExchangeProtectionManager, ProtectionPlan, ProtectionPolicy
from .qualification_intent_recovery import QualificationPositionGuard

STRATEGY = 'FUNDING_CARRY_V1'
HOUR_MS = 3600000
log = logging.getLogger('carry')

# Carry profile (user directive 25 Oct 2026, "YES, CARRY"; full size chosen 26 Oct 11:55 IST): a fixed basket held to
# the 6 Nov flatten, built and unwound with sliced child orders. These limits apply only to a
# mandate that names this profile, i.e. only to the carry runtime; every other runtime keeps
# its committed limits.
CARRY_PROFILE = 'HALF_SIZE_FIXED_BASKET_2026_10_25'
CARRY_BASKET = (('pas:BTC', 'LONG'), ('pas:ETH', 'LONG'), ('pas:HYPE', 'LONG'), ('pas:SP500', 'LONG'),
                ('pas:USDJPY', 'SHORT'))
CARRY_MAX_LEG_NOTIONAL = D('19000')
# 26 Oct 22:35 IST (user): HYPE is the priority leg. Per-leg targets may then differ, each at most
# $50,000 (27 Oct 01:35 IST: HYPE $50k within 1x), with the basket total still at most the starting equity.
CARRY_MAX_TILTED_LEG = D('50000')
CARRY_TAKER_DEPTH_BPS = (0, 5)    # IOC children: the touch only, or up to 5 bps past it
# 27 Oct 01:05 IST (user: "take more risk, invest heavily on HYPE"): the carry profile may use a 2x
# cross leverage SETTING with total exposure capped at 1.5x equity and each leg at most $60,000.
# 29 Oct 13:45 IST (user: "start buying with the remaining balance, most into HYPE, then SP500, BTC, ETH,
# then the others"): exposure up to 1.85x equity, each leg at most $65,000. At 1.85x the margin left free
# at the 2x setting stays above the loss that trips the -5% halt, so no build child runs out of margin first.
CARRY_LEVERAGE_SETTINGS = (1, 2)
CARRY_MAX_EXPOSURE_2X = D('1.85')
CARRY_MAX_LEG_2X = D('65000')
# 31 Oct 22:40 IST (user: "square off USDJPY and S&P500 and put the balance into HYPE, leverage 1.5x"; answered
# question: total exposure 1.5x equity, BTC and ETH kept as held, HYPE gets the rest): close legs are sold to flat
# with reduce-only IOC children and never bought; with close legs one leg may reach $90,000.
# 1 Nov 12:05 IST (user: "invest the remaining $26k strictly all into HYPE ... leverage still 1.5x"; answered
# question "keep 1.5x: move BTC/ETH into HYPE"): $26k of BTC/ETH is trimmed into HYPE, so HYPE may reach $120,000.
# 1 Nov 22:30 IST (user: "atleast 10k dollars" more of BTC/ETH into HYPE, leverage 1.5x): HYPE may reach $130,000.
# 1 Nov 23:10 IST (user: "increase the leverage for 1.85x"; answered question "$185k: bot's 1.85x cap"): HYPE gets the
# room up to 1.85x the starting equity (about $148k with BTC/ETH held), so it may reach $155,000.
CARRY_MAX_LEG_2X_CLOSE = D('155000')
# 27 Oct 09:05 IST (user: "let the funds be where it is, don't sell or trim"): a hold leg keeps exactly the
# size it holds when the mandate starts; it is never bought, trimmed or topped up, only protected and unwound.
CARRY_CHILD_STRATEGIES = frozenset({'CARRY_LONG', 'CARRY_SHORT', 'CARRY_EXIT'})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class CarryMandate:
    team_wallet: str
    api_wallet: str
    markets: tuple
    starts_ms: int
    flatten_ms: int
    expires_ms: int
    starting_equity: str
    leg_notional: str
    source_hash: str
    release_sha256: str
    venue_identity: str
    approval_reference: str
    max_positions: int = 5
    leverage: int = 1
    account_loss_halt: str = '0.05'
    position_stop: str = '0.08'
    stop_slippage: str = '0.01'
    entry_slippage: str = '0.003'
    exit_slippage: str = '0.005'
    l2_participation: str = '0.25'
    fill_deviation_halt: str = '0.005'
    max_order_errors: int = 3
    max_disconnect_ms: int = 300000
    funding_threshold: str = '0.00002'
    lookback_hours: int = 24
    cooldown_hours: int = 24
    strategy: str = STRATEGY
    network: str = 'testnet'
    dex: str = 'pas'
    # Carry profile only (empty profile = the original funding-signal runtime).
    profile: str = ''
    sides: tuple = ()
    unwind_starts_ms: int = 0
    maker_window_ms: int = 7200000
    reprice_ms: int = 600000
    taker_gap_ms: int = 30000
    book_share: str = '0.25'
    leg_notionals: tuple = ()        # ((symbol, notional), ...); empty = leg_notional for every leg
    taker_depth_bps: int = 0
    hold_legs: tuple = ()            # symbols held at their current size (no entry or trim children)
    close_legs: tuple = ()           # symbols sold to flat (reduce-only IOC children) and never bought

    def __post_init__(self):
        object.__setattr__(self, 'markets', tuple(self.markets))
        object.__setattr__(self, 'sides', tuple(tuple(x) for x in self.sides))
        object.__setattr__(self, 'leg_notionals', tuple(tuple(x) for x in self.leg_notionals))
        object.__setattr__(self, 'hold_legs', tuple(self.hold_legs))
        object.__setattr__(self, 'close_legs', tuple(self.close_legs))

    def notional_for(self, symbol):
        return decimal(dict(self.leg_notionals).get(symbol, self.leg_notional), positive=True)

    def require(self):
        import re
        from .competition_windows import SCORED_START_MS, SCORED_END_MS
        from .venue_profiles import venue_profile
        wallet = lambda x: isinstance(x, str) and re.fullmatch('0x[0-9a-fA-F]{40}', x) and int(x[2:], 16)
        equity, leg = decimal(self.starting_equity, positive=True), decimal(self.leg_notional, positive=True)
        if (self.strategy != STRATEGY or self.network != 'testnet' or self.dex != 'pas'
                or not wallet(self.team_wallet) or not wallet(self.api_wallet)
                or self.team_wallet.lower() == self.api_wallet.lower()
                or not self.markets or len(set(self.markets)) != len(self.markets)
                or any(not m.startswith('pas:') for m in self.markets)
                or not (self.leverage == 1 or self.profile and self.leverage in CARRY_LEVERAGE_SETTINGS)
                or not 1 <= self.max_positions <= 5
                or leg * self.max_positions > equity
                or not SCORED_START_MS <= self.starts_ms < self.flatten_ms < self.expires_ms <= SCORED_END_MS
                or not D(0) < decimal(self.account_loss_halt) <= D('0.05')
                or not D(0) < decimal(self.position_stop) <= D('0.08')
                or not D(0) < decimal(self.l2_participation) <= D('0.5')
                or not D(0) < decimal(self.fill_deviation_halt) <= D('0.01')
                or not re.fullmatch('[0-9a-f]{64}', self.source_hash)
                or not re.fullmatch('[0-9a-f]{64}', self.release_sha256)
                or self.venue_identity != venue_profile('pas').identity
                or not self.approval_reference.strip()):
            raise ExchangeError('INVALID_CARRY_MANDATE')
        if self.profile or self.sides or self.unwind_starts_ms:
            self._require_profile(leg)
        return self

    def _require_profile(self, leg):
        if (self.profile != CARRY_PROFILE or self.sides != CARRY_BASKET
                or self.markets != tuple(s for s, _ in CARRY_BASKET)
                or leg > CARRY_MAX_LEG_NOTIONAL or self.max_positions != len(CARRY_BASKET)
                or not self.starts_ms < self.unwind_starts_ms < self.flatten_ms
                or self.maker_window_ms != 7200000 or self.reprice_ms != 600000
                or not 0 < self.taker_gap_ms <= 300000
                or not D(0) < decimal(self.book_share) <= D('0.25')
                or decimal(self.position_stop) != D('0.08')
                or decimal(self.account_loss_halt) != D('0.05')
                or self.taker_depth_bps not in CARRY_TAKER_DEPTH_BPS):
            raise ExchangeError('INVALID_CARRY_MANDATE')
        if self.leverage == 2 and not self.leg_notionals:
            raise ExchangeError('INVALID_CARRY_MANDATE')
        if (len(set(self.hold_legs)) != len(self.hold_legs) or not set(self.hold_legs) <= set(self.markets)
                or self.hold_legs and not self.leg_notionals):
            raise ExchangeError('INVALID_CARRY_MANDATE')
        if self.close_legs and (len(set(self.close_legs)) != len(self.close_legs)
                                or not set(self.close_legs) <= set(self.markets)
                                or set(self.close_legs) & set(self.hold_legs)
                                or len(self.close_legs) >= len(self.markets)
                                or self.leverage != 2 or not self.leg_notionals):
            raise ExchangeError('INVALID_CARRY_MANDATE')
        if self.leg_notionals:
            tilted = dict(self.leg_notionals)
            amounts = [decimal(v, positive=True) for v in tilted.values()]
            leg_cap, exposure = ((CARRY_MAX_LEG_2X_CLOSE if self.close_legs else CARRY_MAX_LEG_2X,
                                  CARRY_MAX_EXPOSURE_2X) if self.leverage == 2 else (CARRY_MAX_TILTED_LEG, D(1)))
            # A close leg has no budget: it is only ever sold to flat.
            if (len(tilted) != len(self.leg_notionals) or set(tilted) != set(self.markets) - set(self.close_legs)
                    or any(a > leg_cap for a in amounts)
                    or sum(amounts, D(0)) > decimal(self.starting_equity, positive=True) * exposure):
                raise ExchangeError('INVALID_CARRY_MANDATE')

    @property
    def basket(self):
        return dict(self.sides)

    @property
    def identity(self):
        return fingerprint(asdict(self))

    @classmethod
    def read(cls, path):
        return cls(**json.loads(Path(path).read_text())).require()


class CarryAuthorization:
    """Signing authority for the carry owner. Exits stay possible until expiry."""
    def __init__(self, mandate, journal, *, root, release_path, clock_ms):
        self.m = mandate
        self.journal = journal
        self.root = Path(root)
        self.release_path = Path(release_path)
        self.clock_ms = clock_ms
        self.venue_identity = mandate.venue_identity
        self.revoked = False
        self._source_checked_ms = None

    def require(self, team, signer):
        from .paper_operations import active_source_hash
        now = self.clock_ms()
        if (self.revoked or team.lower() != self.m.team_wallet.lower() or signer.lower() != self.m.api_wallet.lower()
                or not self.m.starts_ms <= now < self.m.expires_ms):
            raise ExchangeError('CARRY_AUTHORITY_REQUIRED')
        # Hashing every source file per action is slow; re-verify each minute.
        if self._source_checked_ms is None or now - self._source_checked_ms > 60000:
            if active_source_hash(self.root) != self.m.source_hash or sha(self.release_path) != self.m.release_sha256:
                self.revoked = True
                raise ExchangeError('CARRY_SOURCE_OR_RELEASE_CHANGED')
            self._source_checked_ms = now

    def revoke(self):
        self.revoked = True


def resting_protection(row):
    return row['state'] == 'OPEN' and json.loads(row['request']).get('strategy_id') == 'CATASTROPHIC_STOP'


class BasketPositionGuard(QualificationPositionGuard):
    """Our own resting stops on held legs are protection, not pending exits."""
    def intent_rows(self):
        return [r for r in super().intent_rows() if not resting_protection(r)]


def _recovery_base():
    from .long_session import LongAccountRecovery
    return LongAccountRecovery


class CarryAccountRecovery(_recovery_base()):
    def __init__(self, account, journal, *, initial_start_ms, managers, markets, max_positions):
        super().__init__(account, journal, initial_start_ms=initial_start_ms, managers=managers)
        self.markets = set(markets)
        self.max_positions = max_positions
        self.on_truth = self._adopt

    def _adopt(self, state):
        # Exchange truth is the only position source; legs mirror it exactly.
        for symbol, leg in self.managers.items():
            leg.sync(state.positions.get(symbol))

    def concurrent_exposure_reasons(self):
        reasons = []
        if len(self.state.positions) > self.max_positions:
            reasons.append('UNEXPECTED_CONCURRENT_EXPOSURE')
        reasons += ['UNEXPECTED_MARKET_EXPOSURE:' + s for s in self.state.positions if s not in self.markets]
        return reasons

    def manager_data(self, manager, **links):
        position = manager._open_position
        return dict(version=1, strategy=STRATEGY,
                    position={k: str(v) for k, v in position.items()} if position else None, **links)


class CarryLeg:
    """Per-market mirror of the exchange position, as the protection layer expects."""
    def __init__(self, symbol, stop_fraction):
        self.symbol = symbol
        self.stop_fraction = decimal(stop_fraction, positive=True)
        self._open_position = None

    @property
    def has_open_position(self):
        return self._open_position is not None

    def sync(self, position):
        if position is None or not position.quantity or position.entry_price is None:
            self._open_position = None
            return
        entry = decimal(position.entry_price, positive=True)
        side = 'BUY' if position.quantity > 0 else 'SELL'
        stop = entry * (1 - self.stop_fraction) if side == 'BUY' else entry * (1 + self.stop_fraction)
        self._open_position = dict(quantity=abs(position.quantity), side=side, average_entry_price=entry,
                                   stop_loss_price=stop, atr_14=entry * self.stop_fraction)


class CarryProtection(ExchangeProtectionManager):
    """Stop-market at actual exchange entry -/+ the approved fraction."""
    def __init__(self, executor, *, policy, managers, stop_fraction):
        self.stop_fraction = decimal(stop_fraction, positive=True)
        super().__init__(executor, policy=policy, managers=managers)

    def _plan(self, symbol, position, manager, observed_ms):
        self.policy.require()
        managed = manager._open_position if manager else None
        if (managed is None or managed['quantity'] != abs(position.quantity) or
                (managed['side'] == 'BUY') != (position.quantity > 0)):
            raise ExchangeError('PROTECTION_MANAGEMENT_EVIDENCE_REQUIRED')
        spec = self.executor.client.market(symbol)
        entry = decimal(position.entry_price, positive=True)
        side = 'SELL' if position.quantity > 0 else 'BUY'
        trigger = spec.normalize_price(entry * (1 - self.stop_fraction) if side == 'SELL'
                                       else entry * (1 + self.stop_fraction), side)
        slip = decimal(self.policy.execution_slippage_fraction, positive=True)
        limit = spec.normalize_price(trigger * (1 - slip) if side == 'SELL' else trigger * (1 + slip), side)
        liquidation = position.liquidation_price
        if liquidation is not None and (side == 'SELL' and trigger <= liquidation or side == 'BUY' and trigger >= liquidation):
            raise ExchangeError('PROTECTION_TRIGGER_BEYOND_LIQUIDATION')
        quantity = spec.normalize_size(abs(position.quantity))
        if quantity != abs(position.quantity):
            raise ExchangeError('PROTECTION_POSITION_PRECISION_CONFLICT')
        return ProtectionPlan(symbol, side, quantity, trigger, limit, trigger,
                              self.policy.approval_reference, observed_ms, position.entry_price)


class CarryExecution(HyperliquidExecution):
    """Basket boundary check: this market empty, room left, only our stops resting."""
    max_positions = 1
    allowed_markets = frozenset()
    # The scalper's resting reduce-only take-profit on a held market is not a pending entry.
    resting_take_profits = False
    # Carry profile: a leg is built by several children, so an entry may add to a held leg
    # on its own side, and our own resting children on other legs are not foreign orders.
    sliced_legs = False

    def _fresh_protection(self):
        # Both entry reliability gates (after validation in _submit, and in _guard)
        # need protection verified within 5 s; the ~4 s context load ages it.
        # Re-verify read-only (no orders) when the last verification is over 3 s old.
        if self.protection is not None:
            last = self.protection.last_verified_ms
            if last is None or self.client.clock_ms() - last > 3000:
                self.protection.ensure_all(allow_actions=False)

    def _validated(self, request, permission, **kwargs):
        validated = super()._validated(request, permission, **kwargs)
        if not request.reduce_only:
            self._fresh_protection()
        return validated

    def _guard(self, context, checked_ms, *, critical=False, entry=False, exact_full_close=None, entry_request=None):
        if entry:
            self._fresh_protection()
        return super()._guard(context, checked_ms, critical=critical, entry=entry,
                              exact_full_close=exact_full_close, entry_request=entry_request)

    def _sliced_entry_ok(self, entry_request, held, orders):
        # Adding to a held leg needs the held leg on the request's side; a new leg needs room.
        symbol, long = entry_request.symbol, entry_request.side == 'BUY'
        if symbol in held:
            room = (held[symbol].quantity > 0) == long
        else:
            room = len(held) < self.max_positions
        known = {str(r['oid']): json.loads(r['request']).get('strategy_id')
                 for r in self.journal.intents() if r['oid'] is not None}
        own_child = lambda o: (o.get('isTrigger') is not True and o.get('coin') in self.allowed_markets
                               and o.get('coin') != symbol and known.get(str(o.get('oid'))) in CARRY_CHILD_STRATEGIES)
        stop = lambda o: o.get('isTrigger') is True and o.get('reduceOnly') is True and o.get('coin') in held
        return room and all(stop(o) or own_child(o) for o in orders)

    def _require_entry_account(self, now, entry_request):
        before = self.account.get_positions()
        orders = self.account.get_frontend_open_orders()
        after = self.account.get_positions()
        held = {s for s, p in after.items() if p.quantity}
        signature = lambda ps: {s: p.quantity for s, p in ps.items()}
        if self.sliced_legs:
            ok = (entry_request is not None and signature(before) == signature(after)
                  and held <= set(self.allowed_markets)
                  and self._sliced_entry_ok(entry_request, {s: after[s] for s in held}, orders))
        else:
            ok = (entry_request is not None and signature(before) == signature(after)
                  and entry_request.symbol not in held and len(held) < self.max_positions
                  and held <= set(self.allowed_markets)
                  and all((o.get('isTrigger') is True or self.resting_take_profits) and o.get('reduceOnly') is True
                          and o.get('coin') in held for o in orders))
        if not ok:
            self.entries_paused = True
            self.position_guard.revoke('BASKET_ACCOUNT_CHANGED_BEFORE_SIGNING')
            self.journal.event('COMPLIANCE_SIGNING_BLOCK', now, code='POSITION_LIMIT',
                               reason='BASKET_ACCOUNT_CHANGED_BEFORE_SIGNING',
                               actual_position_count=len(after), open_order_count=len(orders))
            raise ExchangeError('ACCOUNT_CHANGED_BEFORE_SIGNING')


def l2_capacity(book, side, limit, participation):
    """Displayed quantity up to the order's own limit, times participation."""
    levels = book.asks if side == 'BUY' else book.bids
    within = sum((l.quantity for l in levels if (l.price <= limit if side == 'BUY' else l.price >= limit)), D(0))
    return within * participation


class CarryRuntime:
    """Decision loop and overnight guardrails. All orders go through `executor`."""
    def __init__(self, *, mandate, strategy, executor, protection, recovery, account, client, market,
                 public, stream, auth, state_dir, clock_ms=None):
        self.m = mandate
        self.strategy = strategy
        self.executor = executor
        self.protection = protection
        self.recovery = recovery
        self.account = account
        self.client = client
        self.market = market
        self.public = public
        self.stream = stream
        self.auth = auth
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock_ms = clock_ms or client.clock_ms
        self.start_equity = decimal(mandate.starting_equity, positive=True)
        self.state = self._load_state()
        self.order_errors = 0
        self.disconnected_since = None
        self.last_heartbeat = 0
        self.last_decision_hour = None

    # ---------- durable runtime state ----------
    def _state_path(self):
        return self.state_dir / 'carry_state.json'

    def _load_state(self):
        path = self._state_path()
        if path.exists():
            value = json.loads(path.read_text())
            if value.get('mandate') == self.m.identity:
                return value
        return dict(mandate=self.m.identity, halted=None, stopped_at={}, trades=[], breakers=[],
                    last_report_day=None)

    def _save_state(self):
        from .paper_operations import atomic_json
        atomic_json(self._state_path(), self.state)

    def _event(self, kind, **data):
        record = dict(kind=kind, ms=self.clock_ms(), utc=datetime.now(timezone.utc).isoformat(), **data)
        with (self.state_dir / 'carry_events.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        log.info('%s %s', kind, json.dumps(data, default=str))
        self.executor.journal.event('CARRY_' + kind, self.clock_ms(), **{k: str(v) for k, v in data.items()})

    def halt(self, reason, *, flatten):
        if self.state['halted'] is None:
            self.state['halted'] = dict(reason=reason, ms=self.clock_ms(), flatten=flatten)
            self.state['breakers'].append(dict(reason=reason, ms=self.clock_ms()))
            self._save_state()
            self._event('HALT', reason=reason, flatten=flatten)
        self.executor.entries_paused = True
        if flatten:
            self.flatten_all(reason)

    # ---------- account truth ----------
    def positions(self):
        return {s: p for s, p in self.account.get_positions().items() if p.quantity}

    def equity(self, positions=None):
        from strategies.funding_carry import marked_equity
        positions = self.positions() if positions is None else positions
        return marked_equity(self.account.get_equity().collateral_balance, positions)

    def funding(self):
        start = self.clock_ms() - (self.m.lookback_hours + 6) * HOUR_MS
        out = {}
        for symbol in self.m.markets:
            rows = self.client.post_info('fundingHistory', coin=symbol, startTime=start)
            out[symbol] = {int(r['time']) // HOUR_MS * HOUR_MS: decimal(r['fundingRate']) for r in rows}
        return out

    def owned_intents(self):
        return {r['intent_key'] for r in self.executor.journal.intents() if r['created_ms'] >= self.m.starts_ms}

    # ---------- orders ----------
    def _provenance(self, key, request, *, setup, signal_ms, classification='STRATEGY_ENTRY',
                    action='STRATEGY', reason='FUNDING_CARRY_SIGNAL_WITH_GUARDRAIL_SIZING', source=None):
        return OrderProvenance(key, request.strategy_id, setup, signal_ms, request.symbol, request.side, reason,
                               dict(allowed=True, quantity=str(request.quantity), strategy=STRATEGY),
                               dict(allowed=True, quantity=str(request.quantity), price=str(request.price),
                                    order_type=request.order_type, tif=request.tif),
                               classification=classification, action_type=action, source_position_id=source,
                               signal_interval_ms=HOUR_MS)

    def enter(self, symbol, side, signal_ms):
        quote = self.market.get_quote(symbol)
        spec = self.client.market(symbol)
        order_side = 'BUY' if side == 'LONG' else 'SELL'
        slip = decimal(self.m.entry_slippage)
        limit = spec.normalize_price(quote.ask * (1 + slip) if order_side == 'BUY' else quote.bid * (1 - slip), order_side)
        quantity = spec.normalize_size(decimal(self.m.leg_notional) / quote.mid)
        key = f'carry:{symbol}:{side}:{signal_ms}'
        setup = 'CARRY_' + side
        request = OrderRequest(symbol, order_side, quantity, limit, tif='Ioc', strategy_id=setup, client_order_id=key)
        permission = RiskPermission(key, symbol, order_side, quantity, self.clock_ms(), limit_price=limit,
                                    provenance=self._provenance(key, request, setup=setup, signal_ms=signal_ms))
        self._event('ENTRY_ATTEMPT', symbol=symbol, side=side, quantity=quantity, limit=limit, mid=quote.mid,
                    notional=quantity * quote.mid)
        result = self.executor.submit(request, permission=permission)
        self.recovery.recover()
        position = self.positions().get(symbol)
        filled = abs(position.quantity) if position else D(0)
        self._event('ENTRY_RESULT', symbol=symbol, state=result.state.value, filled=filled,
                    entry_price=position.entry_price if position else None)
        if position is not None:
            self.state['trades'].append(dict(symbol=symbol, side=side, open_ms=self.clock_ms(),
                                             entry=str(position.entry_price), quantity=str(filled)))
            self._save_state()
            from strategies.funding_carry import fill_deviation
            deviation = fill_deviation(quote.mid, decimal(position.entry_price, positive=True))
            if deviation > decimal(self.m.fill_deviation_halt):
                self.halt(f'FILL_DEVIATION:{symbol}:{deviation:.4%}', flatten=False)
        self.protection.ensure_all()
        return result

    def exit(self, symbol, reason, *, protective):
        position = self.positions().get(symbol)
        if position is None:
            return None
        quote = self.market.get_quote(symbol)
        spec = self.client.market(symbol)
        order_side = 'SELL' if position.quantity > 0 else 'BUY'
        slip = decimal(self.m.exit_slippage)
        limit = spec.normalize_price(quote.bid * (1 - slip) if order_side == 'SELL' else quote.ask * (1 + slip), order_side)
        key = f'carry-exit:{symbol}:{self.clock_ms()}'
        request = OrderRequest(symbol, order_side, abs(position.quantity), limit, reduce_only=True, tif='Ioc',
                               strategy_id='CARRY_EXIT', client_order_id=key)
        provenance = self._provenance(key, request, setup='CARRY_EXIT', signal_ms=self.clock_ms() - HOUR_MS,
            classification='PROTECTIVE_EXIT' if protective else 'STRATEGY_EXIT',
            action='RISK_PROTECTION' if protective else 'STRATEGY', reason=reason, source=symbol)
        permission = RiskPermission(key, symbol, order_side, abs(position.quantity), self.clock_ms(),
                                    reduce_only=True, reason=reason, limit_price=limit, provenance=provenance)
        self._event('EXIT_ATTEMPT', symbol=symbol, reason=reason, quantity=abs(position.quantity), limit=limit,
                    unrealized_pnl=position.unrealized_pnl)
        result = self.executor.submit(request, permission=permission)
        self.recovery.recover()
        remaining = self.positions().get(symbol)
        self._event('EXIT_RESULT', symbol=symbol, state=result.state.value,
                    remaining=remaining.quantity if remaining else 0)
        self.protection.ensure_all()
        return result

    def flatten_all(self, reason):
        for symbol in list(self.positions()):
            try:
                self.exit(symbol, reason, protective=True)
            except Exception as exc:
                self._event('FLATTEN_ERROR', symbol=symbol, error=f'{type(exc).__name__}:{exc}')
        self.protection.ensure_all()

    # ---------- guardrails ----------
    def _stream_health(self):
        stream = self.stream
        try:
            if not stream.connected:
                stream.connect()
            stream.poll()
            if stream.pending or (stream.connected and not getattr(stream, 'ready', True)):
                stream.reconcile()
        except ExchangeError as exc:
            self._event('STREAM_ERROR', error=str(exc))
        healthy = stream.healthy
        now = self.clock_ms()
        if healthy:
            self.disconnected_since = None
        elif self.disconnected_since is None:
            self.disconnected_since = now
        elif now - self.disconnected_since > self.m.max_disconnect_ms:
            self.halt('API_DISCONNECT_OVER_LIMIT', flatten=False)
        return healthy

    def _note_order_error(self, exc, where):
        self.order_errors += 1
        self._event('ORDER_ERROR', where=where, error=f'{type(exc).__name__}:{exc}', consecutive=self.order_errors)
        if self.order_errors >= self.m.max_order_errors:
            self.halt('CONSECUTIVE_ORDER_ERRORS', flatten=False)

    def _record_stops(self, before, after):
        # A leg that vanished while its stop rested was stopped out on the exchange.
        for symbol in set(before) - set(after):
            self.state['stopped_at'][symbol] = self.clock_ms()
            self._event('LEG_CLOSED_BY_EXCHANGE', symbol=symbol)
        self._save_state()

    def decide(self):
        now = self.clock_ms()
        hour = now // HOUR_MS * HOUR_MS
        # Signals are the just-settled hourly funding; the compliance window is
        # one interval plus five minutes, so act only in the first minutes.
        if self.last_decision_hour == hour or now - hour > 240000:
            return
        self.last_decision_hour = hour
        positions = self.positions()
        exits, entries = self.strategy.decide(self.funding(), {s: p.quantity for s, p in positions.items()},
                                              self.state['stopped_at'], now)
        self._event('DECISION', exits=exits, entries=entries, held=sorted(positions))
        for e in exits:
            try:
                self.exit(e['symbol'], e['reason'], protective=False)
                self.order_errors = 0
            except Exception as exc:
                self._note_order_error(exc, 'exit:' + e['symbol'])
        if self.state['halted'] or now >= self.m.flatten_ms:
            return
        for e in entries:
            if len(self.positions()) >= self.m.max_positions or self.state['halted']:
                break
            try:
                self.protection.ensure_all()
                if not self.protection.entries_allowed or self.executor.entries_paused:
                    self._event('ENTRY_SKIPPED', symbol=e['symbol'], reason='PROTECTION_OR_ENTRY_GATE',
                                protection=self.protection.report().get('positions'),
                                entries_paused=self.executor.entries_paused)
                    continue
                self.enter(e['symbol'], e['side'], hour - HOUR_MS)
                self.order_errors = 0
            except Exception as exc:
                self._note_order_error(exc, 'entry:' + e['symbol'])

    def heartbeat(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_heartbeat < 900000:
            return
        self.last_heartbeat = now
        positions = self.positions()
        equity = self.equity(positions)
        realized = self.recovery.state.report().get('realized', {})
        record = dict(utc=datetime.now(timezone.utc).isoformat(), equity=str(equity),
                      pnl=str(equity - self.start_equity),
                      pnl_pct=str((equity / self.start_equity - 1) * 100),
                      positions=[dict(symbol=s, side='LONG' if p.quantity > 0 else 'SHORT', size=str(abs(p.quantity)),
                                      entry=str(p.entry_price), upnl=str(p.unrealized_pnl)) for s, p in positions.items()],
                      realized=realized, trades=len(self.state['trades']), halted=self.state['halted'],
                      protection={s: v.get('status') for s, v in self.protection.states.items()},
                      stream_healthy=self.stream.healthy, order_errors=self.order_errors)
        with (self.state_dir / 'heartbeat.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        from .paper_operations import atomic_json
        atomic_json(self.state_dir / 'status.json', record)
        log.info('HEARTBEAT equity=%s pnl=%s%% positions=%d halted=%s', equity, record['pnl_pct'][:7],
                 len(positions), self.state['halted'])

    def morning_report(self, force=False):
        # 07:00 IST = 01:30 UTC
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        if not force and (now.hour, now.minute) < (1, 30) or not force and self.state['last_report_day'] == day:
            return
        from .carry_report import write_report
        write_report(self.state_dir, self.m, self.account)
        self.state['last_report_day'] = day
        self._save_state()

    # ---------- lifecycle ----------
    def startup(self):
        self.auth.require(self.m.team_wallet, self.m.api_wallet)
        self.recovery.recover()
        for _ in range(20):
            if self._stream_health():
                break
            time.sleep(1)
        self.protection.ensure_all()
        positions = self.positions()
        for symbol in [s for s in positions if s not in self.m.markets]:
            self.exit(symbol, 'ORPHAN_POSITION_OUTSIDE_BASKET', protective=True)
        self._event('STARTUP', positions=sorted(positions), equity=self.equity(), halted=self.state['halted'],
                    protection=self.protection.report().get('positions'))
        self.heartbeat(force=True)

    def run(self, stop):
        self.startup()
        last_positions = set(self.positions())
        while not stop.is_set():
            try:
                self.auth.require(self.m.team_wallet, self.m.api_wallet)
                self._stream_health()
                positions = self.positions()
                self._record_stops(last_positions, set(positions))
                if self.clock_ms() >= self.m.flatten_ms:
                    if positions:
                        self._event('END_OF_COMPETITION_FLATTEN')
                        self.flatten_all('END_OF_COMPETITION_FLATTEN')
                    self.heartbeat(force=True)
                    self.morning_report(force=True)
                    break
                from strategies.funding_carry import loss_halt
                equity = self.equity(positions)
                if not self.state['halted'] and loss_halt(self.start_equity, equity, decimal(self.m.account_loss_halt)):
                    self.halt(f'ACCOUNT_LOSS_HALT:{equity}', flatten=True)
                if not self.protection.healthy:
                    self.protection.ensure_all()
                if not self.state['halted']:
                    self.decide()
                last_positions = set(self.positions())
                self.heartbeat()
                self.morning_report()
            except ExchangeError as exc:
                self._event('CYCLE_ERROR', error=str(exc))
            stop.wait(15)
        self._event('STOPPED', halted=self.state['halted'])


def build_carry_runtime(root, mandate_path, release_path, *, state_dir):
    """Only construction gate for carry execution. Evidence is checked before the key is read."""
    from venue_config import require_paper_migration
    from .execution_journal import ExecutionJournal
    from .execution_safety import NonceManager, ClockHealthMonitor, HyperliquidRateLimitManager
    from .hyperliquid_client import HyperliquidClient
    from .hyperliquid_account import HyperliquidAccount
    from .hyperliquid_market_data import HyperliquidMarketData
    from .exchange_rules import LiveContextProvider, HyperliquidOrderValidator
    from .reliability_policy import load_reliability_policy
    from .live_account_stream import LiveAccountStream
    from .sdk_transport import OfficialSDKTransport
    from .venue_profiles import venue_profile
    from .long_session import require_release
    from .scored_session import require_shared_scope
    from .pas_readiness import require_pas_market_status
    from .practice_preflight import read_api_key, api_signer
    from .testnet_certification import TEAM, API
    from strategies import select
    from strategies.funding_carry import CarryParams

    root = Path(root)
    m = CarryMandate.read(mandate_path)
    if m.team_wallet.lower() != TEAM.lower() or m.api_wallet.lower() != API.lower():
        raise ExchangeError('CARRY_WALLET_IDENTITY_MISMATCH')
    profile = venue_profile('pas')
    require_paper_migration(profile)
    require_release(root, release_path, m.source_hash, m.release_sha256)
    state = root / 'runtime/testnet/anchorium-bot-1'
    journal = ExecutionJournal(state / 'pas.sqlite', session_id='anchorium-pas-v1', team_address=TEAM)
    auth = CarryAuthorization(m, journal, root=root, release_path=release_path,
                              clock_ms=lambda: time.time_ns() // 1000000)
    auth.require(TEAM, API)
    owned = lambda: {r['intent_key'] for r in journal.intents() if r['created_ms'] >= m.starts_ms}
    rate, clock_config, base_policy = load_reliability_policy(root / 'configs/reliability_policy.json')
    rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=API)
    rates.read_budget_wait_seconds = 65
    client = HyperliquidClient(rate_limits=rates, venue=profile)
    client.startup()
    require_shared_scope(root, client, owned_pas_intents=owned())
    require_pas_market_status(client)
    account = HyperliquidAccount(client, TEAM)
    # All evidence passes before the key is touched.
    key, _ = read_api_key(root)
    try:
        signer = api_signer(key, API, TEAM)
    finally:
        key = None
    if signer.address.lower() != API.lower():
        raise ExchangeError('CARRY_SIGNER_IDENTITY_MISMATCH')
    nonces = NonceManager(state / 'nonces.sqlite', signer.address, journal=journal)
    public = HyperliquidMarketData(client)
    clock = ClockHealthMonitor(journal=journal, **clock_config)
    legs = {s: CarryLeg(s, m.position_stop) for s in m.markets}
    recovery = CarryAccountRecovery(account, journal, initial_start_ms=0, managers=legs,
                                    markets=m.markets, max_positions=m.max_positions)
    holder = {}
    provider = LiveContextProvider(public, account, API, clock, rates,
        reconciliation_ready=lambda: recovery.last_report.ready,
        feed_ready=lambda: bool(holder.get('stream') and holder['stream'].healthy), policy_leverage=1)
    original_load = provider.load

    def pas_load(request, *, critical=False):
        require_shared_scope(root, client, owned_pas_intents=owned())
        require_pas_market_status(client)
        return original_load(request, critical=critical)
    provider.load = pas_load
    transport = OfficialSDKTransport(client, signer, TEAM, nonces, auth, rate_limits=rates)
    executor = CarryExecution(client, transport=transport, account=account, journal=journal,
        context_provider=provider, validator=HyperliquidOrderValidator(client, policy_leverage=1),
        recovery=recovery, clock_health=clock, rate_limits=rates)
    executor.max_positions = m.max_positions
    executor.allowed_markets = frozenset(m.markets)
    executor.position_guard = BasketPositionGuard(journal, clock_ms=client.clock_ms, max_positions=m.max_positions)
    executor.compliance_guard.position_guard = executor.position_guard
    executor.compliance_guard.extra_setup_types = frozenset({'CARRY_LONG', 'CARRY_SHORT'})
    participation = decimal(m.l2_participation, positive=True)
    executor.compliance_guard.l2_entry_capacity = lambda request: l2_capacity(
        public.get_orderbook(request.symbol), request.side, request.price, participation)
    policy = replace(base_policy, enabled=True, approval_reference=m.approval_reference,
                     execution_slippage_fraction=decimal(m.stop_slippage, positive=True))
    protection = CarryProtection(executor, policy=policy, managers=legs, stop_fraction=m.position_stop)
    stream = LiveAccountStream(TEAM, recovery, executor, clock_ms=client.clock_ms)
    holder['stream'] = stream
    strategy = select('funding_carry')(CarryParams(markets=m.markets, threshold=decimal(m.funding_threshold),
        lookback_hours=m.lookback_hours, cooldown_hours=m.cooldown_hours))
    return CarryRuntime(mandate=m, strategy=strategy, executor=executor, protection=protection, recovery=recovery,
                        account=account, client=client, market=public, public=public, stream=stream, auth=auth,
                        state_dir=state_dir)
