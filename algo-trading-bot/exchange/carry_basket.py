"""Carry basket runtime (user directive 25 Oct 2026, "YES, CARRY").

Half size: LONG BTC, ETH, HYPE, SP500 and SHORT USDJPY, at most $9,500 per leg at 1x,
held until the 6 Nov unwind. There is no basket stop: every leg keeps the existing 8%
exchange-side reduce-only stop, and the -5% account-loss halt stays as a catastrophe
guard. Nobody trades around the basket: no funding-signal exits, no re-entry after a
stop-out.

Legs are built and unwound with sliced children (exchange/carry_slicer.py): post-only
at the touch for up to 2 h with a 10-minute re-price, then IOC children limited to the
touch, each at most 25% of the touch quantity. One child per leg at a time.

Every order still goes through the executor, the compliance guard, the validator and
the exact-action permits. Only this runtime selects the carry entry scope and the
carry position guard; every other runtime keeps its committed limits.
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import json, logging, time

from .base_exchange import ExchangeError, decimal
from .carry_runtime import (CARRY_CHILD_STRATEGIES, STRATEGY, CarryAuthorization, CarryAccountRecovery,
                            CarryExecution, CarryLeg, CarryMandate, CarryProtection, CarryRuntime)
from .carry_slicer import MAKER, TAKER, SliceParams, child, phase, remaining, stale, taker_ready, top
from .compliance_guard import OrderProvenance
from .exchange_rules import RiskPermission
from .multi_position_guard import MultiPositionGuard
from .order_lifecycle import OrderRequest
from .single_position_guard import PortfolioState, PositionDecision, SinglePositionGuard, unresolved

log = logging.getLogger('carry')
MIN_MS = 60000
TERMINAL = {'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED'}
# Refusals before anything is signed, and races with our own resting children: a skip, not an
# order error. Everything else (exchange rejections, ambiguous results, guard conflicts) counts.
SKIP_CODES = frozenset({
    'POST_ONLY_WOULD_CROSS', 'BOOK_MANIPULATION_RISK', 'ENTRY_PAUSED', 'ENTRY_RELIABILITY_GATE_REQUIRED',
    'ENTRY_READ_BUDGET_HEADROOM_UNAVAILABLE', 'EXCHANGE_CONTEXT_UNAVAILABLE', 'STALE_PRICE_CONTEXT',
    'STALE_MARKET_DATA', 'RATE_LIMITED', 'IOC_NO_LIQUIDITY', 'ACCOUNT_CHANGED_BEFORE_SIGNING',
    'GLOBAL_POSITION_LEASE_REVOKED', 'ACCOUNT_PREFLIGHT_INVALIDATED', 'INVALID_LEVERAGE', 'DATA_NOT_READY',
    'ACCOUNT_NOT_READY', 'SIGNING_READINESS_REVOKED', 'UNKNOWN_ACCOUNT_STATE', 'PRE_DISPATCH_REFUSED',
    'INSUFFICIENT_MARGIN', 'MARGIN_UNAVAILABLE'})
LEVERAGE_RECHECK_MS = 300000


def request_of(row):
    return json.loads(row['request'])


def settled(row):
    return row is None or row['state'] in TERMINAL or not unresolved(row)


# ---------- position guard ----------
class CarryPositionGuard(MultiPositionGuard):
    """Carry profile only: up to five legs on fixed sides, one unresolved child per leg.

    Keeps the account-wide durable lock of SinglePositionGuard (startup UNKNOWN, fresh
    reconciled exchange truth only, reservation inside the intent transaction, flat needs
    actual-fill evidence). Differences: an entry may add to a held leg on its own side,
    and our resting children on other legs do not close the entry slot.
    """
    def __init__(self, journal, *, clock_ms, sides, max_positions=5):
        sides = dict(sides)
        if (type(max_positions) is not int or not 1 <= max_positions <= 5 or not sides
                or any(v not in {'LONG', 'SHORT'} for v in sides.values())):
            raise ExchangeError('INVALID_CARRY_POSITION_GUARD')
        self.sides = sides
        self.max_positions = max_positions
        self.held = frozenset()
        self.pending = frozenset()
        self.slot_open = False
        SinglePositionGuard.__init__(self, journal, clock_ms=clock_ms)

    def _store(self, state, reason, *, entry_key=None, observed_ms=None, in_transaction=False):
        prior = self.journal.control(self.CONTROL) or {}
        value = dict(state=PortfolioState(state).value, reason=reason, entry_key=entry_key, observed_ms=observed_ms,
                     generation=prior.get('generation', 0) + 1, max_global_positions=self.max_positions,
                     held=sorted(self.held), pending=sorted(self.pending), entry_slot_open=self.slot_open,
                     profile='CARRY', team_address=self.journal.team_address)
        if in_transaction:
            from .execution_journal import canonical
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)', (self.CONTROL, canonical(value)))
        else:
            self.journal.control(self.CONTROL, value)
        self.state = PortfolioState(state)
        self.reason = reason
        return value

    def revoke(self, reason):
        self.pending = frozenset()
        super().revoke(reason)

    def _side_ok(self, symbol, quantity):
        return symbol in self.sides and (quantity > 0) == (self.sides[symbol] == 'LONG')

    def _reconcile(self, context, now_ms):
        positions = {s: p for s, p in context.positions.items() if decimal(p.quantity)}
        fresh = (context.readiness.account_ready and context.reconciled and
                 0 <= now_ms - context.account_ms <= 5000)
        pending_rows = [r for r in self.intent_rows() if unresolved(r)]
        entries = [request_of(r) for r in pending_rows if not request_of(r)['reduce_only']]
        self.held, self.pending, self.slot_open = frozenset(), frozenset(), False
        if (not fresh or any(r['state'] == 'UNKNOWN' for r in self.journal.management_actions())
                or not positions and not pending_rows and not context.open_orders):
            # Stale, an unknown management action, or flat: the single-position rules
            # decide (UNKNOWN / RECOVERING / FLAT with actual-fill evidence).
            report = SinglePositionGuard._reconcile(self, context, now_ms)
            if self.state == PortfolioState.FLAT:
                self.slot_open = True
                self._store(self.state, self.reason, observed_ms=context.account_ms, in_transaction=True)
            return report
        self.held = frozenset(positions)
        self.pending = frozenset(e['symbol'] for e in entries)
        known = {str(r['oid']): request_of(r) for r in self.journal.intents() if r['oid'] is not None}
        own = lambda o: (o.get('coin') in self.sides and (
            o.get('isTrigger') is True and o.get('reduceOnly') is True and o.get('coin') in positions
            or o.get('isTrigger') is not True and known.get(str(o.get('oid')), {}).get('strategy_id') in CARRY_CHILD_STRATEGIES))
        reason = None
        if len(positions) > self.max_positions or len(self.held | self.pending) > self.max_positions:
            reason = 'UNEXPECTED_CONCURRENT_EXPOSURE'
        elif any(not self._side_ok(s, p.quantity) for s, p in positions.items()):
            reason = 'UNEXPECTED_CARRY_EXPOSURE'
        elif any(e['symbol'] not in self.sides or (e['side'] == 'BUY') != (self.sides[e['symbol']] == 'LONG')
                 for e in entries) or len(entries) != len(self.pending):
            reason = 'UNEXPECTED_CARRY_ENTRY_INTENT'
        elif not all(own(o) for o in context.open_orders):
            reason = 'UNEXPLAINED_OPEN_ORDER'
        if reason:
            return self._held_state(context, now_ms, positions, PortfolioState.RECOVERING, reason)
        self.slot_open = True
        if entries:
            state = PortfolioState.ENTRY_PENDING
        elif positions:
            first = next(iter(positions.values()))
            state = PortfolioState.LONG if first.quantity > 0 else PortfolioState.SHORT
        else:
            state = PortfolioState.EXIT_PENDING
        return self._held_state(context, now_ms, positions, state, 'ACTUAL_EXCHANGE_EXPOSURE')

    def _entry_room(self, symbol, side, held, pending):
        return (symbol in self.sides and (side == 'BUY') == (self.sides[symbol] == 'LONG')
                and symbol not in pending and (symbol in held or len(set(held) | set(pending)) < self.max_positions))

    def evaluate(self, request, context, now_ms, *, expected_generation=None):
        self.reconcile(context, now_ms, expected_generation=expected_generation)
        if request.reduce_only:
            held = context.positions.get(request.symbol)
            allowed = bool(held and decimal(held.quantity) and
                           (held.quantity > 0) != (request.side == 'BUY') and request.quantity <= abs(held.quantity))
            return PositionDecision(allowed, 'SINGLE_POSITION_PASS' if allowed else 'REDUCE_ONLY_VIOLATION',
                                    self.state.value, self.reason, now_ms)
        held = context.positions.get(request.symbol)
        adds = held is not None and decimal(held.quantity) and not self._side_ok(request.symbol, held.quantity)
        allowed = (self.state not in {PortfolioState.UNKNOWN, PortfolioState.RECOVERING} and self.slot_open
                   and not adds and self._entry_room(request.symbol, request.side, self.held, self.pending))
        if allowed:
            return PositionDecision(True, 'CARRY_LEG_SLOT_PASS', self.state.value, self.reason, now_ms)
        code = ('UNKNOWN_ACCOUNT_STATE' if self.state in {PortfolioState.UNKNOWN, PortfolioState.RECOVERING}
                else 'POSITION_LIMIT')
        return PositionDecision(False, code, self.state.value, self.reason, now_ms)

    def reserve_in_transaction(self, key, request, now_ms, *, expected_generation=None):
        prior = self.journal.control(self.CONTROL) or {}
        if expected_generation is not None and prior.get('generation') != expected_generation:
            raise ExchangeError('ACCOUNT_PREFLIGHT_INVALIDATED')
        pending = {request_of(r)['symbol'] for r in self.intent_rows()
                   if unresolved(r) and not request_of(r)['reduce_only']}
        held = set(prior.get('held', []))
        if (prior.get('state') not in {'FLAT', 'LONG', 'SHORT', 'ENTRY_PENDING', 'EXIT_PENDING'}
                or not prior.get('entry_slot_open') or prior.get('observed_ms') is None
                or not 0 <= now_ms - prior['observed_ms'] <= 5000
                or not self._entry_room(request['symbol'], request['side'], held, pending)):
            raise ExchangeError('POSITION_LIMIT')
        self.held, self.pending = frozenset(held), frozenset(pending | {request['symbol']})
        self._store(PortfolioState.ENTRY_PENDING, 'DURABLE_ENTRY_RESERVED', entry_key=key,
                    observed_ms=prior['observed_ms'], in_transaction=True)

    def report(self):
        value = self.journal.control(self.CONTROL) or {}
        return dict(value, runtime_state=self.state.value, runtime_reason=self.reason,
                    entry_permission=self.slot_open and self.state not in {PortfolioState.UNKNOWN, PortfolioState.RECOVERING})


# ---------- protection ----------
class CarryBasketProtection(CarryProtection):
    """Per-leg 8% stop sized to the actual filled quantity, plus the bug #12 rule.

    The legs are re-synced from the same fresh position read before planning, so a child
    that filled since the runtime's last read re-sizes the stop instead of erroring. A
    failed stop update keeps an existing full-size valid stop (keep_valid_existing_stops).
    """
    before_action = None    # build_carry_basket_runtime installs the FreshReadGate

    def _needs_action(self):
        for symbol, leg in self.managers.items():
            state = self.states.get(symbol, {})
            active = state.get('status') == 'ACTIVE'
            if leg.has_open_position != active or (active and leg.has_open_position and
                                                    str(state.get('quantity')) != str(leg._open_position['quantity'])):
                return True
        return False

    def ensure_all(self, *, allow_actions=True):
        if not self.running:
            positions = self.account.get_positions()
            for symbol, leg in self.managers.items():
                leg.sync(positions.get(symbol))
            # As in ScalpProtection: a stop about to be placed or re-sized takes the fresh read
            # (budget, clock, barrier) first, outside the 5 s signing window. 26 Oct 12:28 IST the
            # HYPE stop re-size failed ACCOUNT_NOT_READY / STALE_PRICE_CONTEXT without it.
            if allow_actions and self.before_action is not None and self._needs_action():
                try:
                    self.before_action()
                except ExchangeError as exc:
                    log.warning('PROTECTION_FRESH_READ_FAILED %s', exc)
        super().ensure_all(allow_actions=allow_actions)
        if allow_actions:
            self.keep_valid_existing_stops()
        return self.report()

    @staticmethod
    def valid_stop(order, position):
        from .overnight_runtime import ScalpProtection
        return ScalpProtection.valid_stop(order, position)

    def keep_valid_existing_stops(self):
        from .overnight_runtime import ScalpProtection
        return ScalpProtection.keep_valid_existing_stops(self)


# ---------- runtime ----------
def _new_leg(side):
    return dict(side=side, mode='BUILD', target=None, started_ms=None, child=None, n=0, last_taker_ms=None,
                last_qty='0', protected_qty='0', verified=None, unwind=None, closed_reason=None,
                protection_errors=0, skips=0)


class CarryBasketRuntime(CarryRuntime):
    CYCLE_S = 10
    HEARTBEAT_MS = 900000
    STOP_CHECK_MS = 60000
    FILL_RECONCILE_MS = 30000
    FUNDING_RECONCILE_MS = 300000
    PROTECTION_RETRIES = 2
    CANCEL_ATTEMPTS = 3               # bug #13: a failed cancel is retried after a fresh account read
    SHUTDOWN_DEADLINE_MS = 600000     # shutdown keeps cancelling resting children for up to 10 min
    SHUTDOWN_RETRY_S = 15
    ENTRY_SIGN_BY_AGE_MS = 130000     # entry signal is the previous minute; sign well inside 60-180 s
    REPORT_UTC = (4, 30)              # 10:00 IST status

    def __init__(self, *, legs, preflight=None, leverage_reader=None, **kwargs):
        super().__init__(strategy=None, **kwargs)
        self.legs = legs
        self.preflight = preflight or (lambda **k: None)
        # A leg starts only once its market reads 1x CROSS on the exchange (the compliance
        # guard refuses anything else); until then it waits without counting as an error.
        self.leverage_reader = leverage_reader or (lambda symbol: self.client.post_info(
            'activeAssetData', user=self.m.team_wallet, coin=symbol).get('leverage'))
        self.leverage_ok = {}
        self.leverage_checked = {}
        m = self.m
        self.params = SliceParams(book_share=decimal(m.book_share, positive=True), maker_window_ms=m.maker_window_ms,
                                  reprice_ms=m.reprice_ms, taker_gap_ms=m.taker_gap_ms,
                                  taker_depth_bps=m.taker_depth_bps)
        s = self.state
        s.setdefault('legs', {sym: _new_leg(side) for sym, side in m.sides})
        s.setdefault('fills', {})
        s.setdefault('fill_cursor_ms', m.starts_ms)
        s.setdefault('funding', {})
        s.setdefault('funding_seen', {})
        s.setdefault('funding_cursor_ms', m.starts_ms)
        s.setdefault('final_unwind_ms', None)
        s.setdefault('basket_started_ms', None)
        s.setdefault('last_status_day', None)
        s.setdefault('rotation', 0)
        self.last_stop_check = 0
        self.last_fill_reconcile = 0
        self.last_funding_reconcile = 0
        self.stop_flag = self.state_dir / 'stop.flag'

    # ---------- small helpers ----------
    def _leg(self, symbol):
        return self.state['legs'][symbol]

    def _book(self, symbol):
        return top(self.market.get_orderbook(symbol))

    def _book_and_top(self, symbol):
        book = self.market.get_orderbook(symbol)
        return book, top(book)

    def _signal_ms(self):
        return (self.clock_ms() // MIN_MS - 1) * MIN_MS

    def _qty(self, positions, symbol):
        p = positions.get(symbol)
        return abs(p.quantity) if p is not None and p.quantity else D(0)

    def equity(self, positions=None):
        """Account equity = the unified USDP balance, which already includes unrealized P&L.

        27 Oct 01:45 IST, checked against exchange data: USDP total 99,456.74 = cash (start 99,998.34
        - fees 80.56 + funding 27.69) + uPnL -488.73. marked_equity (collateral + uPnL) counted uPnL
        twice, which skewed every heartbeat and made the -5% halt fire on a smaller real loss.
        """
        return self.account.get_equity().collateral_balance

    def _stream_health(self):
        # As in the scalper: a receiver thread connects, pings and polls continuously; the owner
        # thread only reconciles. (Polling once per cycle let the stream go stale: DATA_NOT_READY.)
        stream = self.stream
        if not getattr(stream, 'background_receiving', True):
            return super()._stream_health()
        try:
            if getattr(stream, 'receiver_fatal', None):
                self._event('STREAM_ERROR', error='RECEIVER_FATAL:' + str(stream.receiver_fatal))
            elif stream.pending or (stream.connected and not getattr(stream, 'ready', True)):
                stream.reconcile()
        except ExchangeError as exc:
            self._event('STREAM_ERROR', error=str(exc))
        now = self.clock_ms()
        if stream.healthy:
            self.disconnected_since = None
        elif self.disconnected_since is None:
            self.disconnected_since = now
        elif now - self.disconnected_since > self.m.max_disconnect_ms:
            self.halt('API_DISCONNECT_OVER_LIMIT', flatten=False)
        return stream.healthy

    def _note_order_error(self, exc, where):
        # Carry profile: 3 consecutive order errors halt AND flatten (sliced, touch-limited).
        self.order_errors += 1
        self._event('ORDER_ERROR', where=where, error=f'{type(exc).__name__}:{exc}' if isinstance(exc, Exception) else str(exc),
                    consecutive=self.order_errors)
        if self.order_errors >= self.m.max_order_errors:
            self.halt('CONSECUTIVE_ORDER_ERRORS', flatten=True)

    def _ok(self):
        self.order_errors = 0

    def flatten_all(self, reason):
        """Emergency unwind of every held leg with taker children at the touch; never a sweep."""
        for symbol in self.legs:
            self._start_unwind(symbol, 'EMERGENCY', reason)

    def _start_unwind(self, symbol, kind, reason):
        leg = self._leg(symbol)
        if leg['mode'] == 'CLOSED' or leg['unwind'] and leg['unwind']['kind'] == 'EMERGENCY':
            return
        leg['mode'] = 'UNWIND'
        leg['unwind'] = dict(kind=kind, reason=reason, started_ms=self.clock_ms())
        self._save_state()
        self._event('LEG_UNWIND_STARTED', symbol=symbol, unwind_kind=kind, reason=reason)

    # ---------- ledgers (exchange truth) ----------
    def reconcile_fills(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_fill_reconcile < self.FILL_RECONCILE_MS:
            return
        self.last_fill_reconcile = now
        from .fill_ledger import normalize
        start = max(self.m.starts_ms, int(self.state['fill_cursor_ms']) - MIN_MS)
        new = 0
        for f in self.account.get_fills(start_ms=start):
            r = normalize(f)
            if r['symbol'] not in self.legs or r['ms'] < self.m.starts_ms or r['tid'] in self.state['fills']:
                continue
            self.state['fills'][r['tid']] = dict(symbol=r['symbol'], ms=r['ms'], oid=r['oid'], signed=str(r['signed']),
                                                 px=str(r['px']), fee=str(r['fee']), closed_pnl=str(r['closed_pnl']))
            self.state['fill_cursor_ms'] = max(int(self.state['fill_cursor_ms']), r['ms'])
            new += 1
        if new:
            self._save_state()
            self._event('FILL_LEDGER_NEW_FILLS', new=new, total=len(self.state['fills']))
        log.info('FILL_LEDGER_RECONCILED new=%d total=%d', new, len(self.state['fills']))

    def reconcile_funding(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_funding_reconcile < self.FUNDING_RECONCILE_MS:
            return
        self.last_funding_reconcile = now
        seen = self.state['funding_seen']
        start = int(self.state['funding_cursor_ms'])
        while start < now:
            end = min(now, start + 24 * 3600000)     # 5 legs x 24 h stays far under the 500-row page
            for f in self.account.get_funding(start, end):
                key = '|'.join(map(str, f.identity))
                if f.symbol in self.legs and key not in seen:
                    seen[key] = int(f.timestamp_ms)
                    total = D(self.state['funding'].get(f.symbol, '0')) + decimal(f.cashflow)
                    self.state['funding'][f.symbol] = str(total)
            start = end
        # Re-read the last 2 h each time for late rows; remember only what that window can return.
        cursor = max(self.m.starts_ms, now - 2 * 3600000)
        self.state['funding_seen'] = {k: v for k, v in seen.items() if v >= cursor - 3600000}
        self.state['funding_cursor_ms'] = cursor
        self._save_state()

    def ledger(self):
        """Per-leg exchange-fill totals since the mandate start."""
        out = {s: dict(bought=D(0), sold=D(0), fees=D(0), closed_pnl=D(0)) for s in self.legs}
        for r in self.state['fills'].values():
            o = out[r['symbol']]
            q = D(r['signed'])
            o['bought' if q > 0 else 'sold'] += abs(q)
            o['fees'] += D(r['fee'])
            o['closed_pnl'] += D(r['closed_pnl'])
        return out

    # ---------- orders ----------
    def _provenance(self, key, request, *, entry, emergency, reason, signal_ms):
        if entry:
            classification, action = 'STRATEGY_ENTRY', 'STRATEGY'
        elif emergency:
            classification, action = 'PROTECTIVE_EXIT', 'RISK_PROTECTION'
        else:
            classification, action = 'STRATEGY_EXIT', 'STRATEGY'
        return OrderProvenance(key, request.strategy_id, request.strategy_id, signal_ms, request.symbol, request.side,
                               reason, dict(allowed=True, quantity=str(request.quantity), strategy=STRATEGY,
                                            profile=self.m.profile),
                               dict(allowed=True, quantity=str(request.quantity), price=str(request.price),
                                    order_type=request.order_type, tif=request.tif),
                               classification=classification, action_type=action,
                               source_position_id=None if entry else request.symbol, signal_interval_ms=MIN_MS)

    def _place(self, symbol, *, entry, trim=False):
        """Fresh read, then one child for this leg. Returns True when an order was sent.

        trim: a reduce-only IOC child selling a leg down to a lowered target (reallocation)."""
        leg = self._leg(symbol)
        emergency = bool(leg['unwind'] and leg['unwind']['kind'] == 'EMERGENCY')
        now = self.clock_ms()
        if entry:
            kind = phase(leg['started_ms'] or leg.get('resume_started_ms') or now, now, self.params)
        elif trim:
            kind = TAKER
        else:
            kind = phase(leg['unwind']['started_ms'], now, self.params,
                         maker=leg['unwind']['kind'] == 'FINAL' and now < self.m.flatten_ms)
        if kind == TAKER and not taker_ready(leg['last_taker_ms'], now, self.params):
            return False
        signal_ms = self._signal_ms()
        try:
            self.preflight(entry=entry, sign_by_ms=signal_ms + self.ENTRY_SIGN_BY_AGE_MS if entry else None)
        except ExchangeError as exc:
            if str(exc) in SKIP_CODES:
                self._skip(symbol, str(exc))
                return False
            raise
        book, quote = self._book_and_top(symbol)
        if quote is None:
            self._skip(symbol, 'EMPTY_BOOK_SIDE')
            return False
        spec = self.client.market(symbol)
        positions = self.positions()
        held = self._qty(positions, symbol)
        now = self.clock_ms()
        if entry:
            if symbol in self.m.close_legs:
                raise ExchangeError('CLOSE_LEG_IS_NEVER_BOUGHT:' + symbol)
            if leg['target'] is None:
                leg['target'] = str(self._target_for(symbol, quote.mid, positions))
                leg['started_ms'] = leg.get('resume_started_ms') or now
                self._event('LEG_BUILD_STARTED', symbol=symbol, side=leg['side'], target=leg['target'],
                            notional=self.m.notional_for(symbol), mid=quote.mid,
                            maker_phase=phase(leg['started_ms'], now, self.params) == MAKER)
            left = remaining(D(leg['target']), held)
            order_side = 'BUY' if leg['side'] == 'LONG' else 'SELL'
            reason = 'CARRY_BASKET_LEG_BUILD_STEP'
        elif trim:
            left = max(held - D(leg['target']), D(0))
            order_side = 'SELL' if leg['side'] == 'LONG' else 'BUY'
            reason = 'CARRY_REALLOCATION_TRIM'
        else:
            left = held
            order_side = 'SELL' if leg['side'] == 'LONG' else 'BUY'
            reason = leg['unwind']['reason']
        plan, why = child(order_side, left, quote, spec, kind, self.params, book=book)
        if plan is None:
            if why == 'TOUCH_TOO_THIN' or why == 'REMAINDER_BELOW_MINIMUM' and not entry:
                self._skip(symbol, why)
            return False
        leg['n'] += 1
        key = f"carry-{'in' if entry else 'trim' if trim else 'out'}:{symbol}:{self.m.identity[:12]}:{leg['n']}"
        strategy_id = ('CARRY_LONG' if leg['side'] == 'LONG' else 'CARRY_SHORT') if entry else 'CARRY_EXIT'
        request = OrderRequest(symbol, plan['side'], plan['quantity'], plan['price'], reduce_only=not entry,
                               tif=plan['tif'], strategy_id=strategy_id, client_order_id=key)
        provenance = self._provenance(key, request, entry=entry, emergency=emergency, reason=reason, signal_ms=signal_ms)
        permission = RiskPermission(key, symbol, plan['side'], plan['quantity'], now, reduce_only=not entry,
                                    reason=None if entry else reason, limit_price=plan['price'], provenance=provenance)
        # Durable before signing: a crash after this line is settled from the journal at restart.
        leg['child'] = dict(key=key, side=plan['side'], price=str(plan['price']), quantity=str(plan['quantity']),
                            tif=plan['tif'], kind=kind, entry=entry, trim=trim, placed_ms=now, oid=None,
                            state='PREPARED')
        if kind == TAKER:
            leg['last_taker_ms'] = now
        self._save_state()
        self._event('CHILD_ATTEMPT', symbol=symbol, key=key, entry=entry, child_kind=kind, side=plan['side'],
                    quantity=plan['quantity'], price=plan['price'], tif=plan['tif'], left=left,
                    touch_quantity=plan['touch_quantity'], bid=quote.bid, ask=quote.ask)
        try:
            result = self.executor.submit(request, permission=permission)
        except ExchangeError as exc:
            self._settle(symbol)
            if str(exc) in SKIP_CODES:
                self._skip(symbol, str(exc))
                return False
            raise
        leg['child'].update(oid=result.exchange_order_id, state=result.state.value)
        self._save_state()
        self._event('CHILD_RESULT', symbol=symbol, key=key, state=result.state.value, filled=result.filled_quantity,
                    average_price=result.average_price, code=result.code)
        if result.state.value == 'REJECTED' and result.code not in SKIP_CODES:
            self._settle(symbol)
            raise ExchangeError('CHILD_REJECTED:' + str(result.code))
        if result.state.value == 'UNKNOWN':
            raise ExchangeError('CHILD_OUTCOME_UNKNOWN')
        if result.state.value != 'OPEN':
            self._settle(symbol)
        leg['skips'] = 0
        self._ok()
        return True

    def one_x(self, symbol):
        """True once the market reads 1x CROSS; re-read every 5 minutes while it does not."""
        if self.leverage_ok.get(symbol):
            return True
        now = self.clock_ms()
        if now - self.leverage_checked.get(symbol, -LEVERAGE_RECHECK_MS) < LEVERAGE_RECHECK_MS:
            return False
        self.leverage_checked[symbol] = now
        try:
            value = self.leverage_reader(symbol)
        except ExchangeError as exc:
            value = 'READ_FAILED:' + str(exc)
        self.leverage_ok[symbol] = value == dict(type='cross', value=self.m.leverage)
        self._event('LEG_LEVERAGE_READY' if self.leverage_ok[symbol] else 'LEG_WAITING_FOR_1X', symbol=symbol,
                    leverage=value)
        return self.leverage_ok[symbol]

    def _skip(self, symbol, code):
        if code == 'INVALID_LEVERAGE':
            self.leverage_ok[symbol] = False
            self.leverage_checked[symbol] = self.clock_ms()
        leg = self._leg(symbol)
        leg['skips'] = leg.get('skips', 0) + 1
        if leg['skips'] in (1, 10, 100) or leg['skips'] % 500 == 0:
            self._event('CHILD_SKIPPED', symbol=symbol, code=code, consecutive=leg['skips'])

    def _settle(self, symbol):
        """Resolve this leg's child from the journal and, if needed, a read-only order-status query."""
        leg = self._leg(symbol)
        c = leg['child']
        if not c:
            return None
        row = self.executor.journal.intent(c['key'])
        if row is not None and row['state'] == 'PREPARED':
            self._not_transmitted(row)
            row = self.executor.journal.intent(c['key'])
        if row is not None and not settled(row):
            self.executor.recover_uncertain(c['key'])
            row = self.executor.journal.intent(c['key'])
        if row is None or settled(row):
            outcome = json.loads(row['outcome'] or '{}') if row is not None else {}
            self._event('CHILD_SETTLED', symbol=symbol, key=c['key'], state=row['state'] if row else 'NOT_RESERVED',
                        filled=outcome.get('filled_quantity'), average_price=outcome.get('average_price'))
            leg['child'] = None
            self._save_state()
            return row['state'] if row else None
        c.update(state=row['state'], oid=row['oid'] or c.get('oid'))
        self._save_state()
        return row['state']

    def _not_transmitted(self, row):
        # SUBMITTED is persisted before any SDK/signing call, so a PREPARED row was never sent
        # (the same proof ExchangeProtectionManager uses for its own PREPARED stops).
        self.executor.journal.update(row['intent_key'], 'REJECTED', self.clock_ms(),
                                     outcome=dict(code='PREPARED_NOT_TRANSMITTED', transmitted=False))

    def _cancel(self, symbol, why):
        leg = self._leg(symbol)
        c = leg['child']
        self._event('CHILD_CANCEL', symbol=symbol, key=c['key'], reason=why, price=c['price'])
        # Bug #13 (25 Oct 19:50 UTC): the shutdown cancel of two resting entry children failed once
        # with ACCOUNT_NOT_READY, the process exited, and both filled minutes later with no bot
        # running and no stop. A cancel only removes exposure: retry it after re-reading account
        # truth (stream reconcile + fresh-read gate), and give it the safety priority.
        for attempt in range(1, self.CANCEL_ATTEMPTS + 1):
            try:
                if attempt > 1:
                    self._stream_health()
                    self.preflight()
                self.executor.cancel_order(symbol, c['oid'], critical=True)
                self._ok()
                break
            except ExchangeError as exc:
                # It may have filled or been cancelled meanwhile; the settle below decides.
                self._event('CHILD_CANCEL_ERROR', symbol=symbol, key=c['key'], error=str(exc), attempt=attempt)
                if self._child_gone(c):
                    break
        state = self._settle(symbol)
        if leg['child'] is not None and state not in {'OPEN', 'PARTIALLY_FILLED'}:
            raise ExchangeError('CHILD_CANCEL_UNSETTLED:' + str(state))
        if leg['child'] is not None:
            raise ExchangeError('CHILD_STILL_RESTING_AFTER_CANCEL')

    def _child_gone(self, c):
        try:
            return str(c.get('oid')) not in {str(o['oid']) for o in self.account.get_frontend_open_orders()}
        except ExchangeError:
            return False

    def manage_children(self, positions, orders):
        """Settle finished children; cancel resting ones that must change. Returns legs touched."""
        open_oids = {str(o['oid']): o for o in orders}
        touched = set()
        for symbol, leg in self.state['legs'].items():
            c = leg['child']
            if not c:
                continue
            try:
                if c['state'] in {'PREPARED', 'SUBMITTED', 'UNKNOWN'} or not c.get('oid') or str(c['oid']) not in open_oids:
                    self._settle(symbol)
                    touched.add(symbol)
                    continue
                now = self.clock_ms()
                qty = self._qty(positions, symbol)
                why = None
                if c['entry'] and (leg['mode'] != 'BUILD' or self.state['halted'] or now >= self.m.unwind_starts_ms):
                    why = 'LEG_NO_LONGER_BUILDING'
                elif not c['entry'] and not c.get('trim') and leg['mode'] != 'UNWIND':
                    why = 'LEG_NO_LONGER_UNWINDING'
                elif c['entry'] and qty != D(leg['protected_qty']):
                    # Re-size the stop first; it would self-cross our own resting entry child.
                    why = 'PARTIAL_FILL_RESIZE_STOP'
                elif c['kind'] == MAKER:
                    started = leg['started_ms'] if c['entry'] else leg['unwind']['started_ms']
                    maker_allowed = c['entry'] or (leg['unwind']['kind'] == 'FINAL' and now < self.m.flatten_ms)
                    if phase(started, now, self.params, maker=maker_allowed) == TAKER:
                        why = 'MAKER_WINDOW_ENDED'
                    elif now - c['placed_ms'] >= self.params.reprice_ms:
                        quote = self._book(symbol)
                        if quote is not None and stale(c, quote, now, self.params):
                            why = 'REPRICE_AT_TOUCH'
                if why:
                    self._cancel(symbol, why)
                    touched.add(symbol)
            except ExchangeError as exc:
                self._note_order_error(exc, 'child:' + symbol)
        return touched

    # ---------- legs ----------
    def detect_closures(self, positions):
        for symbol, leg in self.state['legs'].items():
            qty = self._qty(positions, symbol)
            last = D(leg['last_qty'])
            if leg['mode'] in {'BUILD', 'HOLD'} and last > 0 and qty == 0 and not (leg['child'] and leg['child']['entry'] is False):
                leg['mode'], leg['closed_reason'] = 'CLOSED', 'CLOSED_BY_EXCHANGE_STOP'
                self.state['stopped_at'][symbol] = self.clock_ms()
                self._event('LEG_CLOSED_BY_EXCHANGE', symbol=symbol, last_quantity=last)
            elif leg['mode'] == 'UNWIND' and qty == 0 and not leg['child']:
                leg['mode'], leg['closed_reason'] = 'CLOSED', leg['unwind']['reason']
                self._event('LEG_UNWOUND', symbol=symbol, unwind_kind=leg['unwind']['kind'], reason=leg['unwind']['reason'])
            leg['last_qty'] = str(qty)
        self._save_state()

    def verify_leg(self, symbol):
        """Exchange check after a leg completes: side and size, and its exchange-side stop."""
        leg = self._leg(symbol)
        position = self.account.get_position(symbol)
        fills = [r for r in self.state['fills'].values() if r['symbol'] == symbol]
        net = sum((D(r['signed']) for r in fills), D(0))
        orders = [o for o in self.account.get_frontend_open_orders() if o.get('coin') == symbol]
        problems = []
        if position is None or not position.quantity:
            problems.append('NO_POSITION')
        else:
            long = position.quantity > 0
            if long != (leg['side'] == 'LONG'):
                problems.append('WRONG_SIDE')
            if (abs(position.quantity) - D(leg['target'])) * position.entry_price >= self.params.min_notional:
                problems.append('ABOVE_TARGET')        # a residual below the $11 minimum cannot be trimmed
            if net != position.quantity:
                problems.append(f'FILL_LEDGER_{net}_VS_POSITION_{position.quantity}')
            plan = self.protection._plan(symbol, position, self.legs[symbol], self.clock_ms())
            stops = [o for o in orders if self.protection._matches(o, plan)]
            if len(stops) != 1:
                problems.append('EXCHANGE_STOP_MISSING_OR_MISMATCHED')
            if any(o.get('isTrigger') is not True for o in orders):
                problems.append('RESTING_CHILD_LEFT')
        record = dict(symbol=symbol, side=leg['side'], quantity=position.quantity if position else None,
                      entry=position.entry_price if position else None, target=leg['target'],
                      ledger_net=net, stops=[dict(oid=o['oid'], trigger=o.get('triggerPx'), size=o.get('sz'))
                                             for o in orders if o.get('isTrigger')], problems=problems)
        self._event('LEG_VERIFIED' if not problems else 'LEG_VERIFICATION_FAILED', **record)
        return not problems, record

    def complete_legs(self, positions):
        for symbol, leg in self.state['legs'].items():
            if leg['mode'] != 'BUILD' or leg['target'] is None or leg['child']:
                continue
            quote = self._book(symbol)
            if quote is None:
                continue
            held = self._qty(positions, symbol)
            left = remaining(D(leg['target']), held)
            if (left * quote.mid >= self.params.min_notional or
                    (held - D(leg['target'])) * quote.mid >= self.params.min_notional):
                continue
            for attempt in range(3):
                if attempt:
                    time.sleep(2)
                self.reconcile_fills(force=True)
                self.protection.ensure_all()
                ok, record = self.verify_leg(symbol)
                if ok:
                    break
            leg['verified'] = record
            if ok:
                leg['mode'] = 'HOLD'
                self._save_state()
                continue
            # Any mismatch: flatten that leg, halt, report.
            self._start_unwind(symbol, 'EMERGENCY', 'LEG_VERIFICATION_FAILED')
            self.halt('LEG_VERIFICATION_FAILED:' + symbol, flatten=False)

    def excess(self, symbol, positions):
        """Quantity a leg holds above its target (0 when none or below the $11 minimum)."""
        leg = self._leg(symbol)
        if leg['target'] is None or leg['mode'] not in {'BUILD', 'HOLD'}:
            return D(0)
        over = self._qty(positions, symbol) - D(leg['target'])
        price = self.m.notional_for(symbol) / D(leg['target'])
        return over if over * price >= self.params.min_notional else D(0)

    def _target_for(self, symbol, mid, positions):
        """Target quantity: the leg's notional at the mid, or for a hold leg exactly what it holds."""
        if symbol in self.m.hold_legs:
            return self._qty(positions, symbol)
        return self.client.market(symbol).normalize_size(self.m.notional_for(symbol) / mid)

    def _ensure_targets(self):
        """Every building leg gets its target before anything is placed, so over-target legs are seen."""
        for symbol, leg in self.state['legs'].items():
            if leg['mode'] != 'BUILD' or leg['target'] is not None or symbol in self.m.close_legs:
                continue
            quote = self._book(symbol)
            if quote is None:
                continue
            now = self.clock_ms()
            positions = self.positions() if symbol in self.m.hold_legs else {}
            if symbol in self.m.hold_legs and not self._qty(positions, symbol):
                # A hold leg is never bought: with nothing held there is nothing to hold.
                leg['mode'], leg['closed_reason'] = 'CLOSED', 'HOLD_LEG_FLAT'
                self._event('HOLD_LEG_FLAT', symbol=symbol)
                continue
            leg['target'] = str(self._target_for(symbol, quote.mid, positions))
            leg['started_ms'] = leg.get('resume_started_ms') or now
            self._event('LEG_BUILD_STARTED', symbol=symbol, side=leg['side'], target=leg['target'],
                        notional=self.m.notional_for(symbol), mid=quote.mid,
                        maker_phase=phase(leg['started_ms'], now, self.params) == MAKER)
        self._save_state()

    def _place_children(self, positions):
        """At most one new child per cycle, rotating over the legs that need one.

        Reallocation (27 Oct): legs above a lowered target are trimmed first, with reduce-only IOC
        children; no entry is placed until every trim is done, so the freed margin funds the buys.
        Close legs (31 Oct) likewise: no entry until every close leg is flat."""
        now = self.clock_ms()
        building = (not self.state['halted'] and now < self.m.unwind_starts_ms)
        if building:
            self._ensure_targets()
        trims = [s for s in self.state['legs'] if building and self.excess(s, positions) > 0]
        closing = [s for s in self.m.close_legs if self._leg(s)['mode'] == 'UNWIND']
        # Protection first: no new entry while any leg holds more or less than its stop covers.
        unprotected = sorted(s for s, l in self.state['legs'].items()
                             if self._qty(positions, s) != D(l['protected_qty']))
        order = list(self.state['legs'])
        start = self.state['rotation'] % len(order)
        for symbol in order[start:] + order[:start]:
            leg = self._leg(symbol)
            if leg['child']:
                continue
            trim = symbol in trims
            entry = leg['mode'] == 'BUILD' and building and not trims and not closing
            unwind = leg['mode'] == 'UNWIND' and self._qty(positions, symbol) > 0
            if trims and not trim and not unwind:
                continue
            if not entry and not unwind and not trim:
                continue
            if trim:
                try:
                    sent = self._place(symbol, entry=False, trim=True)
                except ExchangeError as exc:
                    self._note_order_error(exc, 'trim:' + symbol)
                    sent = True
                if sent:
                    self.state['rotation'] = order.index(symbol) + 1
                    self._save_state()
                    return
                continue
            if entry and unprotected:
                self._skip(symbol, 'STOP_RESIZE_PENDING:' + ','.join(unprotected))
                continue
            if entry and not self.one_x(symbol):
                continue
            if entry and not self.stream.healthy:
                self._skip(symbol, 'STREAM_NOT_HEALTHY')
                continue
            if entry:
                if self.executor.entries_paused:
                    self.executor._after_action()       # re-derive from fresh account truth
                if self.executor.entries_paused or not self.stops_ok():
                    self._skip(symbol, 'ENTRY_GATE')
                    continue
            try:
                sent = self._place(symbol, entry=entry)
            except ExchangeError as exc:
                self._note_order_error(exc, ('entry:' if entry else 'exit:') + symbol)
                sent = True
            if sent:
                self.state['rotation'] = order.index(symbol) + 1
                self._save_state()
                return

    def check_stops(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_stop_check < self.STOP_CHECK_MS:
            return
        self.last_stop_check = now
        self.protection.ensure_all()
        for symbol, leg in self.state['legs'].items():
            c = leg['child']
            status = self.protection.states.get(symbol, {}).get('status')
            if status not in {'ACTIVE', 'NOT_REQUIRED'} and c and c['entry'] and c.get('oid'):
                # The stop would self-cross our own resting entry child: cancel it, then repair.
                try:
                    self._cancel(symbol, 'UNPROTECTED_LEG_REPAIR_STOP')
                except ExchangeError as exc:
                    self._event('CHILD_CANCEL_ERROR', symbol=symbol, error=str(exc))
                self.protection.ensure_all()
        healthy = True
        for symbol, leg in self.state['legs'].items():
            state = self.protection.states.get(symbol, {})
            status = state.get('status')
            if status == 'ACTIVE':
                leg['protected_qty'] = state.get('quantity') or state.get('actual_quantity') or leg['protected_qty']
            elif status == 'NOT_REQUIRED':
                leg['protected_qty'] = '0'
            if status == 'ERROR':
                healthy = False
                leg['protection_errors'] = leg.get('protection_errors', 0) + 1
                self._event('STOP_CHECK_ERROR', symbol=symbol, reason=self.protection.states[symbol].get('reason'),
                            attempt=leg['protection_errors'])
                if leg['protection_errors'] > self.PROTECTION_RETRIES:
                    leg['protection_errors'] = 0
                    self._note_order_error(ExchangeError('PROTECTION_' + str(self.protection.states[symbol].get('reason'))),
                                           'stop:' + symbol)
            else:
                leg['protection_errors'] = 0
        if healthy and self.protection.healthy:
            self.state['last_stop_ok_ms'] = now
        self._save_state()

    def stops_ok(self):
        return all(v.get('status') in {'ACTIVE', 'NOT_REQUIRED'}
                   for k, v in self.protection.states.items() if k != '__account__')

    # ---------- reporting ----------
    def snapshot(self, positions=None):
        positions = self.positions() if positions is None else positions
        equity = self.equity(positions)
        ledger = self.ledger()
        funding = {s: D(self.state['funding'].get(s, '0')) for s in self.legs}
        fees = sum((v['fees'] for v in ledger.values()), D(0))
        funding_total = sum(funding.values(), D(0))
        change = equity - self.start_equity
        legs = []
        for symbol, leg in self.state['legs'].items():
            p = positions.get(symbol)
            st = self.protection.states.get(symbol, {})
            legs.append(dict(symbol=symbol, side=leg['side'], mode=leg['mode'],
                             size=str(abs(p.quantity)) if p is not None and p.quantity else '0',
                             target=leg['target'], entry=str(p.entry_price) if p is not None and p.quantity else None,
                             upnl=str(p.unrealized_pnl) if p is not None and p.quantity else '0',
                             funding=str(funding[symbol]), fees=str(ledger[symbol]['fees']),
                             closed_pnl=str(ledger[symbol]['closed_pnl']),
                             stop=st.get('status'), stop_trigger=st.get('trigger_price'),
                             child=(leg['child'] or {}).get('kind'), closed_reason=leg['closed_reason']))
        return dict(utc=datetime.now(timezone.utc).isoformat(), equity=str(equity), start_equity=str(self.start_equity),
                    change=str(change), change_pct=str(change / self.start_equity * 100),
                    funding=str(funding_total), fees=str(fees), price_pnl=str(change - funding_total + fees),
                    legs=legs, halted=self.state['halted'], order_errors=self.order_errors,
                    stream_healthy=self.stream.healthy, fills=len(self.state['fills']))

    def heartbeat(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_heartbeat < self.HEARTBEAT_MS:
            return
        self.last_heartbeat = now
        record = self.snapshot()
        with (self.state_dir / 'heartbeat.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        from .paper_operations import atomic_json
        atomic_json(self.state_dir / 'status.json', record)
        legs = ' '.join(f"{l['symbol'][4:]}:{l['side'][0]}{l['size']}/{l['target']} upnl={D(l['upnl']):+.2f} "
                        f"fund={D(l['funding']):+.2f} stop={l['stop']}" for l in record['legs'])
        log.info('HEARTBEAT equity=%.2f change=%+.4f%% funding=%+.2f fees=%.2f price=%+.2f halted=%s | %s',
                 float(D(record['equity'])), float(D(record['change_pct'])), float(D(record['funding'])),
                 float(D(record['fees'])), float(D(record['price_pnl'])), bool(record['halted']), legs)

    def status_report(self, force=False):
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        if not force and ((now.hour, now.minute) < self.REPORT_UTC or self.state['last_status_day'] == day):
            return None
        from .carry_report import basket_status
        text = basket_status(self.snapshot(), self.m, self._events_since(self.clock_ms() - 24 * 3600000))
        path = self.state_dir / f'status_{day}.md'
        path.write_text(text)
        self.state['last_status_day'] = day
        self._save_state()
        self._event('STATUS_REPORT', path=str(path))
        return path

    def _events_since(self, ms):
        path = self.state_dir / 'carry_events.jsonl'
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('ms', 0) >= ms:
                out.append(e)
        return out

    # ---------- lifecycle ----------
    def reconcile_children(self):
        """Restart: every resting carry child is cancelled and settled before anything else."""
        rows = [r for r in self.executor.journal.intents() if r['created_ms'] >= self.m.starts_ms
                and request_of(r).get('strategy_id') in CARRY_CHILD_STRATEGIES and not settled(r)]
        open_oids = {str(o['oid']) for o in self.account.get_frontend_open_orders()}
        for row in rows:
            symbol = request_of(row)['symbol']
            if row['state'] == 'PREPARED':
                self._not_transmitted(row)
            else:
                self.executor.recover_uncertain(row['intent_key'])
            row = self.executor.journal.intent(row['intent_key'])
            if row['oid'] is not None and str(row['oid']) in open_oids and not settled(row):
                self.executor.cancel_order(symbol, row['oid'], critical=True)
                self.executor.recover_uncertain(row['intent_key'])
            self._event('RESTART_CHILD_RECONCILED', symbol=symbol, key=row['intent_key'],
                        state=self.executor.journal.intent(row['intent_key'])['state'])
        for symbol, leg in self.state['legs'].items():
            if leg['child']:
                row = self.executor.journal.intent(leg['child']['key'])
                if row is None or settled(row):
                    leg['child'] = None
                else:
                    raise ExchangeError('RESTART_CHILD_UNSETTLED:' + symbol)
        self._save_state()

    def startup(self):
        self.auth.require(self.m.team_wallet, self.m.api_wallet)
        self.recovery.recover()
        if hasattr(self.stream, 'start_receiver') and not self.stream.background_receiving:
            self.stream.start_receiver()
        for _ in range(30):
            if self._stream_health():
                break
            time.sleep(1)
        positions = self.positions()
        foreign = sorted(s for s, p in positions.items() if s not in self.legs or
                         (p.quantity > 0) != (self._leg(s)['side'] == 'LONG'))
        if foreign:
            # Never trade a foreign or wrong-side position; stop entries and report it.
            self.halt('FOREIGN_OR_WRONG_SIDE_EXPOSURE:' + ','.join(foreign), flatten=False)
        self.reconcile_children()
        for symbol, leg in self.state['legs'].items():
            leg['last_qty'] = str(self._qty(positions, symbol))
            leg['protected_qty'] = '-1'          # unknown until the first stop check
            if leg['started_ms'] is None and self._qty(positions, symbol) > 0:
                # A leg already partly built under an earlier mandate has had its maker window:
                # a restart continues with IOC children instead of opening another 2 h window.
                leg['resume_started_ms'] = self.clock_ms() - self.params.maker_window_ms
        if self.state['basket_started_ms'] is None:
            self.state['basket_started_ms'] = self.clock_ms()
        self._start_close_legs(positions)
        self._save_state()
        self.reconcile_fills(force=True)
        self.reconcile_funding(force=True)
        self.check_stops(force=True)
        self._event('STARTUP', profile=self.m.profile, positions=sorted(positions), equity=self.equity(positions),
                    halted=self.state['halted'], legs={s: (l['mode'], l['target'], l['last_qty'])
                                                       for s, l in self.state['legs'].items()},
                    protection=self.protection.report().get('positions'), funding_24h=self._funding_check())
        self.heartbeat(force=True)

    def _start_close_legs(self, positions):
        """31 Oct reallocation: a held close leg is sold to flat with reduce-only touch IOC children
        (CLOSE unwind, no maker window); a flat one is CLOSED. Neither is ever bought."""
        for symbol in self.m.close_legs:
            leg = self._leg(symbol)
            if leg['mode'] in {'UNWIND', 'CLOSED'}:
                continue
            if self._qty(positions, symbol) > 0:
                self._start_unwind(symbol, 'CLOSE', 'CARRY_REALLOCATION_CLOSE')
            else:
                leg['mode'], leg['closed_reason'] = 'CLOSED', 'CLOSE_LEG_FLAT'
                self._event('CLOSE_LEG_FLAT', symbol=symbol)

    def _funding_check(self):
        try:
            from strategies.funding_carry import trailing_mean
            rates = self.funding()
            now = self.clock_ms()
            return {s: str(trailing_mean(rates.get(s, {}), now, 24)) for s in self.legs}
        except ExchangeError as exc:
            return dict(error=str(exc))

    def cycle(self):
        now = self.clock_ms()
        self.auth.require(self.m.team_wallet, self.m.api_wallet)
        self._stream_health()
        positions = self.positions()
        self.detect_closures(positions)
        self.reconcile_fills()
        self.reconcile_funding()
        from strategies.funding_carry import loss_halt
        equity = self.equity(positions)
        if not self.state['halted'] and loss_halt(self.start_equity, equity, decimal(self.m.account_loss_halt)):
            self.halt(f'ACCOUNT_LOSS_HALT:{equity}', flatten=True)
        if now >= self.m.unwind_starts_ms and self.state['final_unwind_ms'] is None:
            self.state['final_unwind_ms'] = now
            self._event('FINAL_UNWIND_STARTED', flatten_ms=self.m.flatten_ms)
            for symbol in self.legs:
                self._start_unwind(symbol, 'FINAL', 'END_OF_COMPETITION_UNWIND')
        touched = self.manage_children(positions, self.account.get_frontend_open_orders())
        if touched:
            positions = self.positions()
            self.detect_closures(positions)
        changed = any(self._qty(positions, s) != D(l['protected_qty']) for s, l in self.state['legs'].items())
        self.check_stops(force=bool(touched) or changed)
        self._place_children(positions)
        self.complete_legs(self.positions())
        self.heartbeat()
        self.status_report()

    def shutdown(self, reason):
        """Clean stop: no resting child is left unattended; stops stay; final heartbeat."""
        ours = {s: leg['child']['oid'] for s, leg in self.state['legs'].items()
                if leg['child'] and leg['child'].get('oid')}
        for symbol, leg in self.state['legs'].items():
            if leg['child']:
                try:
                    if leg['child'].get('oid') and leg['child']['state'] == 'OPEN':
                        self._cancel(symbol, 'SHUTDOWN')
                    else:
                        self._settle(symbol)
                except ExchangeError as exc:
                    self._event('SHUTDOWN_CHILD_ERROR', symbol=symbol, error=str(exc))
        complete = self._shutdown_until_no_child_rests(ours)
        try:
            self.check_stops(force=True)
        except ExchangeError as exc:
            self._event('SHUTDOWN_STOP_CHECK_ERROR', error=str(exc))
        self.heartbeat(force=True)
        if hasattr(self.stream, 'stop_receiver') and getattr(self.stream, 'background_receiving', False):
            self.stream.stop_receiver()
        self._event('STOPPED', reason=reason, halted=self.state['halted'], complete=complete)
        return complete

    def _shutdown_until_no_child_rests(self, ours):
        """Never exit while one of our orders still rests on the exchange (bug #13).

        `ours` is every child order id known when shutdown began, so a child the journal already
        calls settled is still checked against the exchange's own open orders."""
        rounds = max(1, self.SHUTDOWN_DEADLINE_MS // (self.SHUTDOWN_RETRY_S * 1000))
        resting = None
        for attempt in range(rounds + 1):
            try:
                open_oids = {str(o['oid']) for o in self.account.get_frontend_open_orders()}
                resting = {s: oid for s, oid in ours.items() if str(oid) in open_oids}
            except ExchangeError as exc:
                self._event('SHUTDOWN_ORDER_READ_ERROR', error=str(exc))
                resting = None
            if resting == {}:
                return True
            if attempt == rounds:
                break
            for symbol, oid in (resting or {}).items():
                try:
                    leg = self._leg(symbol)
                    if leg['child'] and str(leg['child'].get('oid')) == str(oid):
                        self._cancel(symbol, 'SHUTDOWN_RETRY')
                    else:                                  # journal settled it, the exchange did not
                        self._stream_health()
                        self.preflight()
                        self.executor.cancel_order(symbol, oid, critical=True)
                except ExchangeError as exc:
                    self._event('SHUTDOWN_CHILD_ERROR', symbol=symbol, error=str(exc), round=attempt + 1)
            time.sleep(self.SHUTDOWN_RETRY_S)
        self.state['shutdown_incomplete'] = dict(ms=self.clock_ms(), resting=resting)
        self._save_state()
        self._event('SHUTDOWN_INCOMPLETE_RESTING_ORDERS', resting=resting)
        (self.state_dir / 'SHUTDOWN_INCOMPLETE').write_text(json.dumps(dict(resting=resting), default=str))
        return False

    def run(self, stop):
        self.startup()
        reason = 'SIGNAL'
        while not stop.is_set():
            if self.stop_flag.exists():
                reason = 'STOP_FLAG'
                break
            if self.clock_ms() >= self.m.expires_ms:
                reason = 'MANDATE_EXPIRED'
                break
            try:
                self.cycle()
            except ExchangeError as exc:
                self._event('CYCLE_ERROR', error=str(exc))
            stop.wait(self.CYCLE_S)
        return self.shutdown(reason)


def carry_entry_capacity(book, request, share):
    """Compliance size cap for a carry child: IOC = share of depth inside its limit, else share of the touch."""
    from .carry_slicer import depth_within
    if request.tif == 'Ioc':
        return depth_within(book, request.side, request.price) * share
    levels = book.asks if request.side == 'BUY' else book.bids
    return levels[0].quantity * share if levels else D(0)


def build_carry_basket_runtime(root, mandate_path, release_path, *, state_dir, runtime_cls=None, **extra):
    """Only construction gate for the carry basket. Evidence is checked before the key is read."""
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
    from .entry_scope import CARRY_SCOPE
    from .overnight_runtime import FreshReadGate, SharedAccountBarrier
    from .practice_preflight import read_api_key, api_signer
    from .testnet_certification import TEAM, API

    root = Path(root)
    m = CarryMandate.read(mandate_path)
    if not m.profile:
        raise ExchangeError('CARRY_PROFILE_MANDATE_REQUIRED')
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
    rate, clock_config, base_policy = load_reliability_policy(root / 'configs/reliability_policy.json')
    rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=API)
    rates.read_budget_wait_seconds = 65
    client = HyperliquidClient(rate_limits=rates, venue=profile)
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    owned = lambda: {r['intent_key'] for r in journal.intents() if r['created_ms'] >= m.starts_ms}
    barrier = SharedAccountBarrier(root, account, client, owned)
    barrier.require()
    from .pas_readiness import require_pas_market_status
    require_pas_market_status(client)
    # All evidence and barriers pass before the key is touched.
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
        feed_ready=lambda: bool(holder.get('stream') and holder['stream'].healthy), policy_leverage=m.leverage)
    original_load = provider.load

    def guarded_load(request, *, critical=False):
        # The runtime runs the full barrier right before issuing each permission;
        # the 5 s permission must survive the ~4 s context load that follows.
        barrier.require(fresh_within_ms=10000)
        return original_load(request, critical=critical)
    provider.load = guarded_load
    transport = OfficialSDKTransport(client, signer, TEAM, nonces, auth, rate_limits=rates)
    # The final pre-HTTP check carries the same carry scope as the validator (26 Oct: an SP500
    # child passed the validator and was refused here, before sending, as V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY).
    transport.entry_scope = CARRY_SCOPE
    validator = HyperliquidOrderValidator(client, policy_leverage=m.leverage)
    validator.entry_scope = CARRY_SCOPE
    executor = CarryExecution(client, transport=transport, account=account, journal=journal,
        context_provider=provider, validator=validator, recovery=recovery, clock_health=clock, rate_limits=rates)
    executor.max_positions = m.max_positions
    executor.allowed_markets = frozenset(m.markets)
    executor.sliced_legs = True
    # 26 Oct 16:30 IST an ETH child refused at the transport's final permit check (before any HTTP
    # request) was journalled UNKNOWN and froze the account; for the carry it is a not-sent rejection.
    executor.pre_dispatch_is_rejection = True
    executor.position_guard = CarryPositionGuard(journal, clock_ms=client.clock_ms, sides=m.sides,
                                                 max_positions=m.max_positions)
    executor.compliance_guard.position_guard = executor.position_guard
    executor.compliance_guard.extra_setup_types = frozenset({'CARRY_LONG', 'CARRY_SHORT'})
    # The mandate's leverage SETTING (1, or 2 for the 1.5x-exposure profile); exposure itself is
    # bounded by the per-leg targets in the mandate.
    executor.compliance_guard.entry_leverage = m.leverage
    # Book-impact rule: a child is at most this share of the same top-of-book snapshot the
    # price checks read (the L2-depth-within-limit hook would score a post-only child zero).
    executor.compliance_guard.entry_depth_participation = decimal(m.book_share, positive=True)
    if m.taker_depth_bps:
        # 26 Oct (user): an IOC child may take up to book_share of the depth inside its own limit
        # (at most 5 bps past the touch); a post-only child keeps book_share of the opposite touch.
        executor.compliance_guard.l2_entry_capacity = lambda request: carry_entry_capacity(
            public.get_orderbook(request.symbol), request, decimal(m.book_share, positive=True))
    policy = replace(base_policy, enabled=True, approval_reference=m.approval_reference,
                     execution_slippage_fraction=decimal(m.stop_slippage, positive=True))
    protection = CarryBasketProtection(executor, policy=policy, managers=legs, stop_fraction=m.position_stop)
    stream = LiveAccountStream(TEAM, recovery, executor, clock_ms=client.clock_ms)
    holder['stream'] = stream
    runtime = (runtime_cls or CarryBasketRuntime)(mandate=m, executor=executor, protection=protection, recovery=recovery,
                                                  account=account, client=client, market=public, public=public,
                                                  stream=stream, auth=auth, state_dir=state_dir, legs=legs, **extra)
    gate = FreshReadGate(barrier=barrier, recovery=recovery, rates=rates, clock=clock, client=client, market=public,
                         symbol=m.markets[0], event=runtime._event)
    runtime.preflight = gate
    protection.before_action = gate
    return runtime
