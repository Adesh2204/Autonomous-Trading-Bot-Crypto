"""Unattended overnight momentum scalper inside the committed scored limits.

Committed scope enforced by the mandate and the central guards: the mandate's
markets and directions, up to `max_positions` concurrent positions (at most one
per market, at most 3), <= $1,000 per entry, <= 2 entries per clock hour, 1x
cross, and `participation` of top-of-book (10% default BBO rule; above 10% the
compliance guard applies the higher share to the same top-of-book snapshot, at most 25%).
Every entry gets an exchange-side reduce-only stop (trigger) and a resting
reduce-only take-profit limit, so the position stays protected if the bot dies.
"""
from dataclasses import dataclass, asdict, replace
from decimal import Decimal as D
from datetime import datetime, timezone
from pathlib import Path
import json, logging, time

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .exchange_rules import RiskPermission
from .compliance_guard import OrderProvenance
from .order_lifecycle import OrderRequest
from .position_protection import ExchangeProtectionManager, ProtectionPlan, ProtectionStatus
from .fill_ledger import entry_fills, missing_trades
from .carry_runtime import (BasketPositionGuard, CarryAccountRecovery, CarryAuthorization, CarryExecution, sha)

STRATEGY = 'MOMENTUM_SCALPER_OVERNIGHT_V1'
MIN_MS = 60000
log = logging.getLogger('overnight')

# Rolling Hyperliquid IP weight (reads cost 2 or 20) that must be free before an
# order's permission is issued. One guarded order: shared barrier ~66 + context
# load ~252 + post-action reconciliation ~132. An entry also covers the exchange
# stop that _after_action places inside the entry's own submit.
ORDER_WEIGHT = 450
ENTRY_WEIGHT = 880
ENTRY_WAIT_MS = 25000        # the signal must still sign inside its 60-180 s window
ENTRY_SIGN_BY_AGE_MS = 130000  # with a signal time, wait until this age: 50 s before the 180 s limit
PROTECT_WAIT_MS = 65000      # protective actions wait for budget, then try anyway
FLAT_POLL_MS = 15000         # account polling while flat; keeps budget for the next entry
# Rejections that only mean a snapshot aged inside the 5 s window; a flatten retries these.
STALE_CODES = frozenset({'STALE_PRICE_CONTEXT', 'STALE_MARKET_DATA', 'STALE_ACCOUNT_STATE', 'ACCOUNT_NOT_READY',
                         'RISK_PERMISSION_DENIED', 'EXCHANGE_CONTEXT_UNAVAILABLE', 'STALE_PROTECTION_POSITION',
                         'ACCOUNT_CHANGED_DURING_PREFLIGHT', 'PROTECTION_POSITION_CHANGED_OR_STALE'})
EXIT_ATTEMPTS = 4
FILL_RECONCILE_MS = 30000    # exchange fills vs journal (bug #11)
STOP_REPAIR_READS = 2        # fresh-read retries before a missing stop forces an exit (bug #12)


@dataclass(frozen=True)
class OvernightMandate:
    team_wallet: str
    api_wallet: str
    markets: tuple
    starts_ms: int
    flatten_ms: int
    exit_ms: int
    expires_ms: int
    starting_equity: str
    source_hash: str
    release_sha256: str
    venue_identity: str
    approval_reference: str
    t1_pct: str
    t2_pct: str
    t3_pct: str
    target_notes: str
    directions: tuple = ('LONG',)
    max_positions: int = 1
    leverage: int = 1
    max_notional: str = '1000'
    max_entries_per_hour: int = 2
    risk_fraction: str = '0.004'
    participation: str = '0.1'
    max_slippage_bps: str = '10'
    loss_cap_pct: str = '-2.0'
    stop_slippage: str = '0.01'
    exit_slippage: str = '0.005'
    max_order_errors: int = 3
    max_disconnect_ms: int = 180000
    strategy: str = STRATEGY
    network: str = 'testnet'
    dex: str = 'pas'

    def __post_init__(self):
        object.__setattr__(self, 'markets', tuple(self.markets))
        object.__setattr__(self, 'directions', tuple(self.directions))

    def require(self):
        import re
        from .competition_windows import SCORED_START_MS, SCORED_END_MS
        from .venue_profiles import venue_profile
        from .entry_scope import PAS_ENTRY_MARKETS
        wallet = lambda x: isinstance(x, str) and re.fullmatch('0x[0-9a-fA-F]{40}', x) and int(x[2:], 16)
        t1, t2, t3 = (decimal(x) for x in (self.t1_pct, self.t2_pct, self.t3_pct))
        if (self.strategy != STRATEGY or self.network != 'testnet' or self.dex != 'pas'
                or not wallet(self.team_wallet) or not wallet(self.api_wallet)
                or self.team_wallet.lower() == self.api_wallet.lower()
                or not self.markets or len(set(self.markets)) != len(self.markets)
                or not set(self.markets) <= PAS_ENTRY_MARKETS
                or not self.directions or len(set(self.directions)) != len(self.directions)
                or not set(self.directions) <= {'LONG', 'SHORT'}
                or not 1 <= self.max_positions <= min(3, len(self.markets)) or self.leverage != 1
                or not D(10) < decimal(self.max_notional) <= D(1000)
                or not 1 <= self.max_entries_per_hour <= 2
                or not D(0) < decimal(self.risk_fraction) <= D('0.005')
                or not D(0) < decimal(self.participation) <= D('0.25')
                or not D('-2.0') <= decimal(self.loss_cap_pct) < 0
                or not 0 < t1 < t2 < t3
                or not SCORED_START_MS <= self.starts_ms < self.flatten_ms < self.exit_ms < self.expires_ms <= SCORED_END_MS
                or not re.fullmatch('[0-9a-f]{64}', self.source_hash)
                or not re.fullmatch('[0-9a-f]{64}', self.release_sha256)
                or self.venue_identity != venue_profile('pas').identity
                or not self.approval_reference.strip()):
            raise ExchangeError('INVALID_OVERNIGHT_MANDATE')
        return self

    @property
    def identity(self):
        return fingerprint(asdict(self))

    @classmethod
    def read(cls, path):
        return cls(**json.loads(Path(path).read_text())).require()


class ScalpLeg:
    """Mirror of the exchange position plus the planned stop for its protection."""
    DEFAULT_ADOPTED_STOP = D('0.005')

    def __init__(self, symbol):
        self.symbol = symbol
        self.plan_stop = None
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
        stop = self.plan_stop if self.plan_stop is not None else (
            entry * (1 - self.DEFAULT_ADOPTED_STOP) if side == 'BUY' else entry * (1 + self.DEFAULT_ADOPTED_STOP))
        self._open_position = dict(quantity=abs(position.quantity), side=side, average_entry_price=entry,
                                   stop_loss_price=stop, atr_14=abs(entry - stop))


class ScalpProtection(ExchangeProtectionManager):
    """Stop-market at the trade's planned stop (1.0 ATR, 0.15% floor)."""
    before_action = None

    def ensure_all(self, *, allow_actions=True):
        # A held leg without an active stop (or an active stop on a flat leg) is
        # about to be signed: take the fresh read first, before the position is
        # observed and the stop's permission is issued.
        if (allow_actions and self.before_action is not None and not self.running and
                any(m.has_open_position != (self.states.get(s, {}).get('status') == 'ACTIVE')
                    for s, m in self.managers.items())):
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
        """A resting reduce-only stop-market that closes the whole position on the loss side."""
        try:
            long = position.quantity > 0
            trigger = decimal(order['triggerPx'], positive=True)
            liquidation = position.liquidation_price
            return (order.get('isTrigger') is True and order.get('reduceOnly') is True and
                    order.get('orderType') in {'Stop Market', 'StopMarket'} and
                    order.get('side') == ('A' if long else 'B') and decimal(order['sz']) == abs(position.quantity) and
                    (liquidation is None or (trigger > liquidation if long else trigger < liquidation)))
        except (KeyError, TypeError, ExchangeError):
            return False

    def keep_valid_existing_stops(self):
        """Bug #12: a failed stop update (any error, e.g. DUPLICATE_ORDER) is not a missing stop.

        Re-read the position and the open orders; if exactly one owned stop already protects the full
        position, keep the position (status ACTIVE, warning logged) instead of reporting ERROR, which
        the runtime used to answer with a flatten."""
        for symbol, state in list(self.states.items()):
            if symbol == '__account__' or state.get('status') != 'ERROR':
                continue
            try:
                position = self.account.get_position(symbol)
                if position is None or not position.quantity:
                    continue
                owned, _ = self._discover(self.account.get_frontend_open_orders())
                stops = [o for o in owned.get(symbol, []) if self.valid_stop(o, position)]
            except Exception as exc:
                log.warning('STOP_KEEP_CHECK_FAILED %s %s', symbol, exc)
                continue
            if len(stops) != 1:
                continue
            stop = stops[0]
            log.warning('STOP_UPDATE_FAILED_EXISTING_STOP_KEPT %s %s (update error: %s)', symbol, stop['oid'],
                        state.get('reason'))
            self._status(symbol, ProtectionStatus.ACTIVE, 'KEPT_EXISTING_STOP_AFTER_UPDATE_ERROR',
                         order_id=str(stop['oid']), cloid=stop.get('cloid'), trigger_price=str(stop['triggerPx']),
                         quantity=str(abs(position.quantity)), update_error=state.get('reason'))

    def _plan(self, symbol, position, manager, observed_ms):
        self.policy.require()
        managed = manager._open_position if manager else None
        if (managed is None or managed['quantity'] != abs(position.quantity) or
                (managed['side'] == 'BUY') != (position.quantity > 0)):
            raise ExchangeError('PROTECTION_MANAGEMENT_EVIDENCE_REQUIRED')
        spec = self.executor.client.market(symbol)
        side = 'SELL' if position.quantity > 0 else 'BUY'
        trigger = spec.normalize_price(decimal(managed['stop_loss_price'], positive=True), side)
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


def to_bars(candles):
    return [dict(t=c.timestamp_ms, o=c.open, h=c.high, l=c.low, c=c.close, v=c.volume) for c in candles]


class OvernightRuntime:
    def __init__(self, *, mandate, executor, protection, recovery, account, client, market, stream, auth,
                 legs, state_dir, clock_ms=None):
        from strategies.momentum_scalper import NightGuard, ScalpParams
        self.m = mandate
        self.p = ScalpParams(markets=mandate.markets, directions=mandate.directions,
                             risk_fraction=decimal(mandate.risk_fraction))
        self.executor, self.protection, self.recovery = executor, protection, recovery
        self.account, self.client, self.market, self.stream, self.auth = account, client, market, stream, auth
        self.legs = legs
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock_ms = clock_ms or client.clock_ms
        self.start_equity = decimal(mandate.starting_equity, positive=True)
        self.state = self._load_state()
        g = self.state['guard']
        self.guard = NightGuard(decimal(mandate.t1_pct), decimal(mandate.t2_pct), decimal(mandate.t3_pct),
                                loss_cap=decimal(mandate.loss_cap_pct), hit_t1=g['hit_t1'], hit_t2=g['hit_t2'],
                                losing_streak=g['losing_streak'], paused_until_ms=g['paused_until_ms'],
                                half_size=g['half_size'])
        self.order_errors = 0
        self.disconnected_since = None
        self.last_heartbeat = 0
        self.last_account_ms = 0
        self.last_fill_reconcile_ms = 0
        self.bars = {}
        self.preflight = lambda **k: None     # build_overnight_runtime installs the FreshReadGate

    # ---------- durable state ----------
    def _load_state(self):
        path = self.state_dir / 'overnight_state.json'
        if path.exists():
            value = json.loads(path.read_text())
            if value.get('mandate') == self.m.identity:
                return value
        return dict(mandate=self.m.identity, halted=None, finished=None, open={}, trades=[], entries=[],
                    last_entry_ms=None, guard=dict(hit_t1=False, hit_t2=False, losing_streak=0,
                                                   paused_until_ms=0, half_size=False))

    def _save(self):
        from .paper_operations import atomic_json
        g = self.guard
        self.state['guard'] = dict(hit_t1=g.hit_t1, hit_t2=g.hit_t2, losing_streak=g.losing_streak,
                                   paused_until_ms=g.paused_until_ms, half_size=g.half_size)
        atomic_json(self.state_dir / 'overnight_state.json', self.state)

    def _event(self, kind, **data):
        record = dict(kind=kind, ms=self.clock_ms(), utc=datetime.now(timezone.utc).isoformat(), **data)
        with (self.state_dir / 'overnight_events.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        log.info('%s %s', kind, json.dumps(data, default=str))
        try:
            self.executor.journal.event('OVERNIGHT_' + kind, self.clock_ms(), **{k: str(v) for k, v in data.items()})
        except Exception:
            pass

    # ---------- account truth ----------
    def positions(self):
        return {s: p for s, p in self.account.get_positions().items() if p.quantity}

    def own_orders(self):
        return [o for o in self.account.get_frontend_open_orders() if o['coin'] in self.m.markets]

    def equity(self, positions=None):
        from strategies.funding_carry import marked_equity
        positions = self.positions() if positions is None else positions
        return marked_equity(self.account.get_equity().collateral_balance, positions)

    def pnl_pct(self, equity):
        return (equity / self.start_equity - 1) * 100

    def guard_return(self, equity):
        """The return the guard's locks and loss cap are measured on."""
        return self.pnl_pct(equity)

    # ---------- orders ----------
    def _provenance(self, key, request, *, setup, signal_ms, classification='STRATEGY_ENTRY', action='STRATEGY',
                    reason='MOMENTUM_BREAKOUT_15M_TREND', source=None):
        return OrderProvenance(key, request.strategy_id, setup, signal_ms, request.symbol, request.side, reason,
                               dict(allowed=True, quantity=str(request.quantity), strategy=STRATEGY),
                               dict(allowed=True, quantity=str(request.quantity), price=str(request.price),
                                    order_type=request.order_type, tif=request.tif),
                               classification=classification, action_type=action, source_position_id=source)

    def _entries_last_hour(self):
        now = self.clock_ms()
        return sum(1 for ms in self.state['entries'] if now - ms < 60 * MIN_MS)

    def enter(self, symbol, decision, *, half):
        from strategies.momentum_scalper import levels, size
        # Fresh read first (budget for the entry and its stop, clock, barrier); the
        # quote and sizing below then come from the same fresh moment.
        try:
            self.preflight(entry=True, sign_by_ms=decision['signal_ms'] + ENTRY_SIGN_BY_AGE_MS)
        except ExchangeError as exc:
            if str(exc) != 'ENTRY_READ_BUDGET_HEADROOM_UNAVAILABLE':
                raise
            self._event('ENTRY_SKIPPED', symbol=symbol, side=decision['side'], reason=str(exc))
            return None
        quote = self.market.get_quote(symbol)
        spec = self.client.market(symbol)
        side = decision['side']
        order_side = 'BUY' if side == 'LONG' else 'SELL'
        # Take the touch: ask for a long, bid for a short; size against that side's top level.
        entry_ref, top = (quote.ask, quote.ask_quantity) if side == 'LONG' else (quote.bid, quote.bid_quantity)
        stop, target = levels(entry_ref, decision['atr'], side, self.p)
        equity = self.equity()
        quantity = size(equity=equity, risk_fraction=self.p.risk_fraction, stop_distance=abs(entry_ref - stop),
                        price=entry_ref, max_notional=decimal(self.m.max_notional),
                        top_quantity=top, participation=decimal(self.m.participation), half=half)
        quantity = spec.normalize_size(quantity) if quantity * entry_ref >= 11 else D(0)
        slip_bps = abs(entry_ref - quote.mid) / quote.mid * 10000
        if quantity * entry_ref < 11 or slip_bps > decimal(self.m.max_slippage_bps):
            self._event('ENTRY_SKIPPED', symbol=symbol, side=side, reason='SIZE_OR_SLIPPAGE', quantity=quantity,
                        top_qty=top, slippage_bps=slip_bps)
            return None
        limit = spec.normalize_price(entry_ref, order_side)
        # Signal time: the last completed 1m bar before the decision (set by decide()).
        signal_ms = decision['signal_ms']
        key = f'scalp:{symbol}:{signal_ms}'
        setup = 'MOMENTUM_' + side
        request = OrderRequest(symbol, order_side, quantity, limit, tif='Ioc', strategy_id=setup,
                               client_order_id=key)
        permission = RiskPermission(key, symbol, order_side, quantity, self.clock_ms(), limit_price=limit,
            provenance=self._provenance(key, request, setup=setup, signal_ms=signal_ms,
                                        reason=decision['reason']))
        self.legs[symbol].plan_stop = stop
        self._event('ENTRY_ATTEMPT', symbol=symbol, side=side, reason=decision['reason'], quantity=quantity, limit=limit,
                    notional=quantity * limit, stop=stop, target=target, half=half, mid=quote.mid)
        self.state['entries'].append(self.clock_ms())
        self.state['last_entry_ms'] = self.clock_ms()
        self._save()
        # The executor's post-action reconciliation already re-read account truth
        # and, through the protection hook, placed the exchange stop.
        attempt_ms = self.state['last_entry_ms']
        result = self.executor.submit(request, permission=permission)
        position = self.positions().get(symbol)
        # Bug #11: the exchange's fills decide whether the entry filled, never the placement
        # response or one position snapshot (the HYPE short filled and was stopped out before
        # the first read, and was logged "filled 0").
        fills = self._entry_fills(symbol, result, attempt_ms)
        filled = sum((f['signed'] for f in fills if (f['signed'] > 0) == (order_side == 'BUY')), D(0))
        self._event('ENTRY_RESULT', symbol=symbol, state=result.state.value, filled=filled,
                    position=position.quantity if position else 0, entry=position.entry_price if position else None,
                    fills=len(fills))
        if position is None:
            if fills:
                # Filled and already closed (exchange stop) before the read: book it from the fills now.
                self._event('ENTRY_FILLED_AND_CLOSED_BEFORE_READ', symbol=symbol, fills=len(fills))
                self.reconcile_fills(force=True)
            else:
                self.legs[symbol].plan_stop = None
            return result
        # Keep the planned 1.5:1 geometry relative to the actual fill.
        actual = decimal(position.entry_price, positive=True)
        held = 'LONG' if position.quantity > 0 else 'SHORT'
        stop, target = levels(actual, decision['atr'], held, self.p)
        self.legs[symbol].plan_stop = stop
        self.legs[symbol].sync(position)
        self.state['open'][symbol] = dict(symbol=symbol, side=held, entry_ms=self.clock_ms(), entry=str(actual),
                                          stop=str(stop), target=str(target), quantity=str(position.quantity),
                                          reason=decision['reason'], tp_key=None, half=half)
        self._save()
        # Re-plans the stop at the actual fill; the protection hook reads fresh before any change.
        self.protection.ensure_all()
        self._event('STOP_CHECKED', symbol=symbol, elapsed_ms=self.clock_ms() - self.state['open'][symbol]['entry_ms'],
                    status=self.protection.states.get(symbol, {}).get('status'))
        self.place_take_profit(symbol)
        return result

    def _exchange_fills(self, start_ms):
        """Exchange-reported fills since start_ms; an account adapter without fill history (some
        offline doubles) reports FILL_READ_UNAVAILABLE instead of inventing anything."""
        getter = getattr(self.account, 'get_fills', None)
        if getter is None:
            raise ExchangeError('FILL_READ_UNAVAILABLE')
        return getter(start_ms=start_ms)

    def _entry_fills(self, symbol, result, attempt_ms):
        try:
            fills = self._exchange_fills(max(0, attempt_ms - 5000))
        except ExchangeError as exc:
            self._event('ENTRY_FILL_READ_FAILED', symbol=symbol, error=str(exc))
            return []
        oid = getattr(result, 'exchange_order_id', None)
        return entry_fills(fills, oid=oid, symbol=symbol, since_ms=attempt_ms - 5000) if oid else \
            entry_fills(fills, symbol=symbol, since_ms=attempt_ms - 5000)

    # ---------- fills: exchange truth vs journal (bug #11) ----------
    def _recorded_tids(self, fills):
        """Fill ids already attributed to a journal trade (older trades have only a time window)."""
        from .fill_ledger import normalize
        tids = {t for trade in self.state['trades'] for t in trade.get('fill_tids', ())}
        windows = [(t['symbol'], t['entry_ms'] - MIN_MS, t.get('exit_ms', t['entry_ms']) + 5000)
                   for t in self.state['trades'] if not t.get('fill_tids')]
        for f in map(normalize, fills):
            if any(f['symbol'] == s and a <= f['ms'] <= b for s, a, b in windows):
                tids.add(f['tid'])
        return tids

    def reconcile_fills(self, force=False):
        """Every 30 s: any round trip the exchange reports but the journal lacks is inserted, and
        its net P&L goes to the losing streak (the loss cap already reads exchange equity)."""
        now = self.clock_ms()
        if not force and now - getattr(self, 'last_fill_reconcile_ms', 0) < FILL_RECONCILE_MS:
            return []
        self.last_fill_reconcile_ms = now
        start = self.state.get('session_start_ms') or self.m.starts_ms
        try:
            fills = self._exchange_fills(start)
        except ExchangeError as exc:
            if str(exc) == 'FILL_READ_UNAVAILABLE':
                return []
            raise
        missing, conflicts, _open = missing_trades(fills, self._recorded_tids(fills))
        for c in conflicts:
            self._event('FILL_JOURNAL_CONFLICT', symbol=c['symbol'], tids=c['tids'], recorded=c['recorded'])
        booked = []
        for trip in missing:
            tracked = self.state['open'].get(trip['symbol'])
            if tracked and trip['entry_ms'] >= tracked['entry_ms'] - MIN_MS:
                continue                      # closes through manage() -> _closed_trade
            trade = dict(symbol=trip['symbol'], side=trip['side'], entry_ms=trip['entry_ms'],
                         exit_ms=trip['exit_ms'], entry=str(trip['entry']), exit=str(trip['exit']),
                         quantity=str(trip['quantity']), net=str(trip['net']), fees=str(trip['fees']),
                         reason='RECONCILED_FROM_EXCHANGE_FILLS', fill_tids=trip['tids'], oids=trip['oids'])
            self.state['trades'].append(trade)
            self.guard.trade_closed(trip['net'], now)
            booked.append(trade)
            self._event('FILL_RECONCILED', symbol=trip['symbol'], side=trip['side'], net=trip['net'],
                        fills=len(trip['tids']), streak=self.guard.losing_streak)
        if booked:
            self._save()
        return booked

    def adopt_untracked(self, positions):
        """A position the exchange holds but the journal does not track (a fill the first read
        missed) is adopted so it gets an exchange stop and a take-profit; never re-entered."""
        untracked = {s: p for s, p in positions.items() if s not in self.state['open'] and s in self.legs}
        opened = {}
        if untracked:
            from .fill_ledger import round_trips
            try:
                _, opened = round_trips(self._exchange_fills(self.state.get('session_start_ms') or self.m.starts_ms))
            except ExchangeError as exc:
                self._event('ADOPTION_FILL_READ_FAILED', error=str(exc))
        for symbol, position in untracked.items():
            self.legs[symbol].sync(position)
            entry_ms = opened[symbol]['entry_ms'] if symbol in opened else self.clock_ms()
            stop = self.legs[symbol]._open_position['stop_loss_price']
            long = position.quantity > 0
            entry = decimal(position.entry_price)
            target = entry + (entry - stop) * D('1.5') if long else entry - (stop - entry) * D('1.5')
            self.state['open'][symbol] = dict(symbol=symbol, side='LONG' if long else 'SHORT',
                                              entry_ms=entry_ms, entry=str(entry), stop=str(stop),
                                              target=str(target), quantity=str(position.quantity),
                                              reason='ADOPTED_FROM_EXCHANGE_FILL', tp_key=None)
            self._save()
            self._event('POSITION_ADOPTED', symbol=symbol, size=position.quantity, entry=entry, stop=stop)

    def place_take_profit(self, symbol):
        trade = self.state['open'].get(symbol)
        if not trade or trade.get('tp_key'):
            return
        self.preflight()
        position = self.positions().get(trade['symbol'])
        if position is None:
            return
        spec = self.client.market(trade['symbol'])
        tp_side = 'SELL' if position.quantity > 0 else 'BUY'
        target = spec.normalize_price(decimal(trade['target'], positive=True), tp_side)
        key = f'scalp-tp:{trade["symbol"]}:{trade["entry_ms"]}'
        request = OrderRequest(trade['symbol'], tp_side, abs(position.quantity), target, reduce_only=True,
                               tif='Gtc', strategy_id='MOMENTUM_TP', client_order_id=key)
        permission = RiskPermission(key, trade['symbol'], tp_side, abs(position.quantity), self.clock_ms(),
            reduce_only=True, reason='TAKE_PROFIT_1_5_ATR', limit_price=target,
            provenance=self._provenance(key, request, setup='MOMENTUM_TP', signal_ms=self.clock_ms() - MIN_MS,
                classification='STRATEGY_EXIT', reason='TAKE_PROFIT_1_5_ATR', source=trade['symbol']))
        result = self.executor.submit(request, permission=permission)
        trade['tp_key'] = key
        trade['tp_oid'] = result.exchange_order_id
        self._save()
        self._event('TAKE_PROFIT_PLACED', symbol=trade['symbol'], price=target, state=result.state.value,
                    oid=result.exchange_order_id, elapsed_ms=self.clock_ms() - trade['entry_ms'])

    def cancel_take_profit(self, symbol):
        trade = self.state['open'].get(symbol)
        if not trade or not trade.get('tp_key'):
            return
        open_ids = {str(o['oid']) for o in self.own_orders() if not o.get('isTrigger')}
        if trade.get('tp_oid') and str(trade['tp_oid']) in open_ids:
            self.preflight()
            self.executor.cancel_order(trade['symbol'], trade['tp_oid'], critical=True)
            self._event('TAKE_PROFIT_CANCELLED', symbol=trade['symbol'], oid=trade['tp_oid'])
        self.executor.recover_uncertain(trade['tp_key'])

    def exit(self, symbol, reason):
        """Flatten fast path: a fresh read before every attempt, retried only when a snapshot went stale."""
        for attempt in range(1, EXIT_ATTEMPTS + 1):
            try:
                return self._exit_once(symbol, reason)
            except ExchangeError as exc:
                if str(exc) not in STALE_CODES or attempt == EXIT_ATTEMPTS:
                    raise
                self._event('EXIT_RETRY_AFTER_STALE_SNAPSHOT', symbol=symbol, reason=reason, attempt=attempt,
                            error=str(exc))

    def _exit_once(self, symbol, reason):
        if symbol in self.state['open']:
            self.cancel_take_profit(symbol)
        position = self.positions().get(symbol)
        if position is None:
            return None
        self.preflight()
        quote = self.market.get_quote(symbol)
        spec = self.client.market(symbol)
        side = 'SELL' if position.quantity > 0 else 'BUY'
        slip = decimal(self.m.exit_slippage)
        limit = spec.normalize_price(quote.bid * (1 - slip) if side == 'SELL' else quote.ask * (1 + slip), side)
        key = f'scalp-exit:{symbol}:{self.clock_ms()}'
        request = OrderRequest(symbol, side, abs(position.quantity), limit, reduce_only=True, tif='Ioc',
                               strategy_id='MOMENTUM_EXIT', client_order_id=key)
        permission = RiskPermission(key, symbol, side, abs(position.quantity), self.clock_ms(), reduce_only=True,
            reason=reason, limit_price=limit,
            provenance=self._provenance(key, request, setup='MOMENTUM_EXIT', signal_ms=self.clock_ms() - MIN_MS,
                classification='PROTECTIVE_EXIT', action='RISK_PROTECTION', reason=reason, source=symbol))
        self._event('EXIT_ATTEMPT', symbol=symbol, reason=reason, quantity=abs(position.quantity), limit=limit)
        result = self.executor.submit(request, permission=permission)
        self.protection.ensure_all()
        self._event('EXIT_RESULT', symbol=symbol, state=result.state.value,
                    remaining=(self.positions().get(symbol).quantity if self.positions().get(symbol) else 0))
        return result

    def flatten_all(self, reason):
        for symbol in list(self.positions()):
            try:
                self.exit(symbol, reason)
            except Exception as exc:
                self._event('FLATTEN_ERROR', symbol=symbol, error=f'{type(exc).__name__}:{exc}')
        self.cleanup_orders()
        self.protection.ensure_all()

    def cleanup_orders(self):
        """Cancel our resting non-trigger orders on markets that are flat."""
        held = set(self.positions())
        for o in self.own_orders():
            if not o.get('isTrigger') and o['coin'] not in held:
                try:
                    self.preflight()
                    self.executor.cancel_order(o['coin'], o['oid'], critical=True)
                    self._event('ORPHAN_ORDER_CANCELLED', symbol=o['coin'], oid=o['oid'])
                except Exception as exc:
                    self._event('CANCEL_ERROR', symbol=o['coin'], error=f'{type(exc).__name__}:{exc}')
        for trade in list(self.state['open'].values()):
            if trade.get('tp_key') and trade['symbol'] not in held:
                try:
                    self.executor.recover_uncertain(trade['tp_key'])
                except Exception as exc:
                    self._event('TP_RECOVERY_ERROR', symbol=trade['symbol'], error=f'{type(exc).__name__}:{exc}')

    # ---------- guardrails ----------
    def halt(self, reason):
        if self.state['halted'] is None:
            self.state['halted'] = dict(reason=reason, ms=self.clock_ms())
            self._save()
            self._event('HALT', reason=reason)
        self.executor.entries_paused = True
        self.flatten_all(reason)

    def _note_order_error(self, exc, where):
        self.order_errors += 1
        self._event('ORDER_ERROR', where=where, error=f'{type(exc).__name__}:{exc}', consecutive=self.order_errors)
        if self.order_errors >= self.m.max_order_errors:
            self.halt('CONSECUTIVE_ORDER_ERRORS')

    def _stream_health(self):
        # The receiver thread connects, pings and polls continuously; the owner
        # thread only reconciles after events or reconnects.
        stream = self.stream
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
            self.halt('API_DISCONNECT_OVER_3_MIN')
        return stream.healthy

    def _closed_trade(self, trade):
        """A tracked trade went flat: book its net P&L from exchange fills."""
        net = D(0)
        fills = self.account.get_fills(start_ms=trade['entry_ms'] - MIN_MS)
        recorded = {t for done in self.state['trades'] for t in done.get('fill_tids', ())}
        tids = []
        for f in fills:
            tid = getattr(f, 'trade_id', None)
            if f.symbol == trade['symbol'] and (tid is None or str(tid) not in recorded):
                net += (f.closed_pnl or D(0)) - f.fee
                if tid is not None:
                    tids.append(str(tid))
        trade = dict(trade, exit_ms=self.clock_ms(), net=str(net), fill_tids=tids)
        trade.update(self._stop_fill_record(trade, [f for f in fills if f.symbol == trade['symbol']]))
        self.state['trades'].append(trade)
        self.state['open'].pop(trade['symbol'], None)
        self.legs[trade['symbol']].plan_stop = None
        self.guard.trade_closed(net, self.clock_ms())
        self._save()
        self._event('TRADE_CLOSED', symbol=trade['symbol'], net=net, reason=trade.get('reason'),
                    streak=self.guard.losing_streak, half_size=self.guard.half_size)

    def _stop_fill_record(self, trade, fills):
        """Phase 1.4: expected (trigger) vs actual stop-fill price, measured, never assumed."""
        from .fill_ledger import stop_slippage_bps
        state = self.protection.states.get(trade['symbol'], {}) if hasattr(self.protection, 'states') else {}
        oid, trigger = state.get('order_id'), state.get('trigger_price')
        if not oid or not trigger:
            return {}
        stop_fills = [f for f in fills if str(getattr(f, 'order_id', '')) == str(oid)]
        qty = sum((f.quantity for f in stop_fills), D(0))
        if not qty:
            return {}
        px = sum((f.quantity * f.price for f in stop_fills), D(0)) / qty
        bps = stop_slippage_bps(px, trigger, trade.get('side') or ('LONG' if decimal(trade['quantity']) > 0 else 'SHORT'))
        samples = self.state.setdefault('stop_slippage_bps', [])
        samples.append(str(round(bps, 3)))
        mean = sum(D(x) for x in samples) / len(samples)
        self._event('STOP_FILL_MEASURED', symbol=trade['symbol'], trigger=trigger, fill=px, slippage_bps=round(bps, 3),
                    samples=len(samples), mean_bps=round(mean, 3))
        return dict(stop_trigger=str(trigger), stop_fill=str(px), stop_slippage_bps=str(round(bps, 3)))

    # ---------- decisions ----------
    def _bars(self, symbol, interval, count):
        step = {'5m': 5 * MIN_MS, '15m': 15 * MIN_MS}[interval]
        now = self.clock_ms()
        end = now // step * step - 1
        cached = self.bars.get((symbol, interval))
        if cached and cached[0] == end:
            return cached[1]
        bars = to_bars(self.market.get_candles(symbol, end + 1 - count * step, end, interval=interval, now_ms=now))
        if bars and bars[-1]['t'] + step == end + 1:
            self.bars[(symbol, interval)] = (end, bars)
        return bars

    def decide(self):
        from strategies.momentum_scalper import guaranteed, setup
        now = self.clock_ms()
        bar_close = now // (5 * MIN_MS) * (5 * MIN_MS)
        # The signal is stamped at the last 1m bar (close - 60 s); compliance accepts
        # 60-180 s of age. Decide 5-40 s after the 5m close: a slow context load
        # (~40 s observed) still signs well inside the window.
        if not 5000 <= now - bar_close <= 40000 or self.state.get('decided_bar') == bar_close:
            return
        self.state['decided_bar'] = bar_close
        held = self.positions()
        if len(held) >= self.m.max_positions or self.state['halted'] or now >= self.m.flatten_ms:
            return
        if self.guard.paused(now):
            self._event('PAUSED_AFTER_LOSS_STREAK', until_ms=self.guard.paused_until_ms)
            return
        if self._entries_last_hour() >= self.m.max_entries_per_hour:
            self._event('ENTRY_SKIPPED', reason='COMMITTED_TWO_ENTRIES_PER_HOUR')
            return
        half = self.guard.size_factor_half()
        found = []
        for symbol in self.m.markets:
            if symbol in held or symbol in self.state['open']:
                continue                      # at most one position per market
            bars5 = self._bars(symbol, '5m', 40)
            # pas markets skip empty 5m candles; only the bar that just closed may signal.
            if not bars5 or bars5[-1]['t'] != bar_close - 5 * MIN_MS:
                continue
            decision = setup(bars5, self._bars(symbol, '15m', 60), self.p)
            if decision:
                decision['signal_ms'] = bar_close - MIN_MS
                self._event('SIGNAL', symbol=symbol, **decision)
                if decision['side']:
                    found.append((symbol, decision))
        last = self.state['last_entry_ms'] or self.m.starts_ms
        if not found and self.p.guarantee_ms is not None and now - last >= self.p.guarantee_ms:
            symbol = self.most_liquid()
            decision = guaranteed(self._bars(symbol, '5m', 40), self._bars(symbol, '15m', 60), self.p)
            if decision:
                decision['signal_ms'] = bar_close - MIN_MS
            self._event('TRADE_GUARANTEE_CHECK', symbol=symbol, decision=decision)
            if decision and decision['side']:
                found.append((symbol, decision))
                half = True
        slots = min(self.m.max_positions - len(held), self.m.max_entries_per_hour - self._entries_last_hour())
        for symbol, decision in found[:slots]:
            try:
                self._stream_health()
                self.protection.ensure_all()
                self.cleanup_orders()
                if self.executor.entries_paused:
                    # A compliance block pauses entries until account truth is re-read.
                    self._refresh_account_budget()
                    self.executor._after_action()
                if self.executor.entries_paused or not self.protection.entries_allowed:
                    self._event('ENTRY_SKIPPED', symbol=symbol, reason='ENTRY_GATE',
                                entries_paused=self.executor.entries_paused)
                    return
                before = self._weight_mark()
                self.enter(symbol, decision, half=half)
                self._event('ENTRY_CYCLE_WEIGHT', symbol=symbol, **self._weight_since(before))
                self.order_errors = 0
            except Exception as exc:
                if str(exc) == 'ENTRY_PAUSED':
                    # The executor refused before signing (a stream reconnect revoked
                    # entries): nothing was sent, so it is a skip, not an order error.
                    self._event('ENTRY_SKIPPED', symbol=symbol, reason='ENTRY_PAUSED_BEFORE_SIGNING')
                    continue
                self._note_order_error(exc, 'entry:' + symbol)

    # ---------- request budget measurement (Phase 1.3) ----------
    def _weight_mark(self):
        rates = getattr(self.executor, 'rate_limits', None)
        return (getattr(rates, 'total_weight', None), dict(getattr(rates, 'weight_by_query', {}) or {}))

    def _weight_since(self, mark):
        rates = getattr(self.executor, 'rate_limits', None)
        total, by_query = mark
        if rates is None or total is None:
            return dict(weight=None)
        now = dict(getattr(rates, 'weight_by_query', {}) or {})
        delta = {q: w - by_query.get(q, 0) for q, w in now.items() if w != by_query.get(q, 0)}
        return dict(weight=rates.total_weight - total, by_query=delta)

    def _refresh_account_budget(self):
        """The account-budget snapshot reads UNKNOWN 60 s after the last order, so after a
        trade entries stayed paused until a stream reconnect re-read it. Re-read it here;
        a failed read only leaves entries paused."""
        rates = getattr(self.executor, 'rate_limits', None)
        if rates is None:
            return
        try:
            rates.observe_info('userRateLimit', self.account._query('userRateLimit'))
        except ExchangeError as exc:
            self._event('BUDGET_REFRESH_SKIPPED', error=str(exc))

    def most_liquid(self):
        depth = {}
        for symbol in self.m.markets:
            book = self.market.get_orderbook(symbol)
            mid = (book.bids[0].price + book.asks[0].price) / 2
            depth[symbol] = sum((l.price * l.quantity for l in book.asks if l.price <= mid * D('1.0025')), D(0))
        return max(depth, key=depth.get)

    def manage(self):
        """Optional time stop, protection repair, flat detection for every tracked trade."""
        positions = self.positions()
        closed = [t for s, t in self.state['open'].items() if s not in positions]
        if closed:
            self.cleanup_orders()
            for trade in closed:
                self._closed_trade(trade)
            self.protection.ensure_all()      # cancels the now-obsolete exchange stops
            positions = self.positions()
        self.adopt_untracked({s: p for s, p in positions.items()
                              if s in self.m.markets and ('LONG' if p.quantity > 0 else 'SHORT') in self.m.directions})
        for symbol, position in positions.items():
            if symbol not in self.m.markets or ('LONG' if position.quantity > 0 else 'SHORT') not in self.m.directions:
                self.exit(symbol, 'OUTSIDE_COMMITTED_SCOPE')
                continue
            status = self.protection.states.get(symbol, {}).get('status')
            if status != 'ACTIVE':
                # Bug #12: a stop-update error is not a missing stop. Each ensure_all re-reads the
                # position and open orders (and keeps a valid existing stop); flatten only when no
                # valid stop exists after STOP_REPAIR_READS fresh reads.
                for attempt in range(1, STOP_REPAIR_READS + 1):
                    self.protection.ensure_all()      # the protection hook reads fresh before signing
                    if self.protection.states.get(symbol, {}).get('status') == 'ACTIVE':
                        break
                    self._event('STOP_REPAIR_RETRY', symbol=symbol, attempt=attempt,
                                status=self.protection.states.get(symbol, {}).get('status'),
                                reason=self.protection.states.get(symbol, {}).get('reason'))
                if self.protection.states.get(symbol, {}).get('status') != 'ACTIVE':
                    self.exit(symbol, 'EXCHANGE_STOP_NOT_ACTIVE')
                    continue
            trade = self.state['open'].get(symbol)
            if trade:
                if not trade.get('tp_key'):
                    self.place_take_profit(symbol)
                if self.p.time_stop_ms is not None and self.clock_ms() - trade['entry_ms'] >= self.p.time_stop_ms:
                    self.exit(symbol, 'TIME_STOP_60_MIN')

    # ---------- reporting ----------
    def heartbeat(self, force=False):
        now = self.clock_ms()
        if not force and now - self.last_heartbeat < 15 * MIN_MS:
            return
        self.last_heartbeat = now
        positions = self.positions()
        equity = self.equity(positions)
        pnl = self.pnl_pct(equity)
        record = dict(utc=datetime.now(timezone.utc).isoformat(), equity=str(equity), pnl_pct=f'{pnl:.5f}',
                      positions=[dict(symbol=s, size=str(p.quantity), entry=str(p.entry_price), upnl=str(p.unrealized_pnl))
                                 for s, p in positions.items()],
                      trades=len(self.state['trades']), entries=len(self.state['entries']),
                      t1=dict(target=self.m.t1_pct, hit=self.guard.hit_t1),
                      t2=dict(target=self.m.t2_pct, hit=self.guard.hit_t2), t3=dict(target=self.m.t3_pct),
                      halted=self.state['halted'], paused_until_ms=self.guard.paused_until_ms,
                      half_size=self.guard.size_factor_half(), stream_healthy=self.stream.healthy,
                      protection={s: v.get('status') for s, v in self.protection.states.items()})
        with (self.state_dir / 'heartbeat.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        from .paper_operations import atomic_json
        atomic_json(self.state_dir / 'status.json', record)
        log.info('HEARTBEAT pnl=%s%% equity=%s position=%s trades=%d T1=%s/%s T2=%s/%s T3=%s halted=%s',
                 record['pnl_pct'], equity, record['positions'] or 'flat', record['trades'], self.m.t1_pct,
                 self.guard.hit_t1, self.m.t2_pct, self.guard.hit_t2, self.m.t3_pct, self.state['halted'])

    def verify_flat(self):
        readings = []
        for _ in range(2):
            positions = self.positions()
            orders = self.account.get_frontend_open_orders()
            readings.append(dict(ms=self.clock_ms(), positions=len(positions), orders=len(orders)))
            time.sleep(2)
        flat = all(r['positions'] == 0 and r['orders'] == 0 for r in readings)
        self._event('FINAL_FLAT_VERIFICATION', flat=flat, readings=readings)
        return flat, readings

    # ---------- lifecycle ----------
    def startup(self):
        self.auth.require(self.m.team_wallet, self.m.api_wallet)
        self._event('TARGETS', t1_pct=self.m.t1_pct, t2_pct=self.m.t2_pct, t3_pct=self.m.t3_pct,
                    notes=self.m.target_notes, start_equity=self.m.starting_equity)
        for trade in self.state['open'].values():
            self.legs[trade['symbol']].plan_stop = decimal(trade['stop'], positive=True)
        self.recovery.recover()
        if not getattr(self.stream, 'background_receiving', True):
            self.stream.start_receiver()
        for _ in range(30):
            if self._stream_health():
                break
            time.sleep(1)
        self.protection.ensure_all()
        positions = self.positions()
        for symbol, position in positions.items():
            if symbol in self.state['open'] or symbol not in self.legs:
                continue
            # Restart without a durable plan: adopt with the default stop, never re-enter.
            self.legs[symbol].sync(position)
            self.state['open'][symbol] = dict(symbol=symbol, side='LONG' if position.quantity > 0 else 'SHORT',
                                              entry_ms=self.clock_ms(), entry=str(position.entry_price),
                                              stop=str(self.legs[symbol]._open_position['stop_loss_price']),
                                              target=str(decimal(position.entry_price) *
                                                         (D('1.0075') if position.quantity > 0 else D('0.9925'))),
                                              quantity=str(position.quantity), reason='ADOPTED_ON_RESTART', tp_key=None)
            self._save()
        self.cleanup_orders()
        try:
            self.reconcile_fills(force=True)          # exchange fills vs journal on every boot
        except ExchangeError as exc:
            self._event('FILL_RECONCILE_FAILED', error=str(exc))
        self._event('STARTUP', positions=sorted(positions), equity=self.equity(), halted=self.state['halted'],
                    protection={s: v.get('status') for s, v in self.protection.states.items()})
        self.heartbeat(force=True)

    def run(self, stop):
        self.startup()
        while not stop.is_set():
            now = self.clock_ms()
            try:
                self.auth.require(self.m.team_wallet, self.m.api_wallet)
                if now >= self.m.exit_ms:
                    break
                if now >= self.m.flatten_ms:
                    if self.positions() or self.own_orders():
                        self._event('SCHEDULED_FLATTEN_0845_IST')
                        self.flatten_all('SCHEDULED_FLATTEN_0845_IST')
                        held = self.positions()
                        for trade in [t for s, t in self.state['open'].items() if s not in held]:
                            self._closed_trade(trade)
                    self.heartbeat()
                    stop.wait(5)
                    continue
                self._stream_health()
                # Flat and untracked: poll the account every 15 s, not every cycle, so the
                # rolling read budget has room for the next entry and its stop.
                if self.state['open'] or now - self.last_account_ms >= FLAT_POLL_MS:
                    self.last_account_ms = now
                    self.manage()
                    equity = self.equity()
                    self._apply_verdict(self.guard.check(self.guard_return(equity)))
                self.reconcile_fills()
                if not self.state['halted']:
                    self.decide()
                self._save()
                self.heartbeat()
            except ExchangeError as exc:
                self._event('CYCLE_ERROR', error=str(exc))
            except Exception as exc:
                self._event('CYCLE_EXCEPTION', error=f'{type(exc).__name__}:{exc}')
            stop.wait(5)
        # 08:50 IST: final verification, report, and a clean exit (no restart).
        if self.positions() or self.own_orders():
            self.flatten_all('FINAL_EXIT_FLATTEN')
        flat, readings = self.verify_flat()
        self.heartbeat(force=True)
        self.state['finished'] = dict(ms=self.clock_ms(), flat=flat, readings=readings)
        self._save()
        path = self._write_report()
        self._event('FINISHED', flat=flat, report=str(path))
        return flat

    def _apply_verdict(self, verdict):
        if verdict and not self.state['halted']:
            self.halt(verdict[1])

    def _write_report(self):
        from .overnight_report import write_report
        return write_report(self.state_dir, self.m, self.account)


class SharedAccountBarrier:
    """The shared-account barrier, with one exact historical exemption.

    Every unresolved intent in any local journal blocks signing, except our own
    and the single qualification certification intent that earlier human-approved
    isolation exempted, and only while the exchange reports that cloid unknown.
    Any par exposure or par order also blocks.
    """
    def __init__(self, root, account, client, owned, *, recheck_ms=600000):
        self.root, self.account, self.client, self.owned = Path(root), account, client, owned
        self.recheck_ms = recheck_ms
        self.historical_checked_ms = None
        self.passed_ms = None

    def require(self, *, fresh_within_ms=0):
        """Full check; inside a context load, reuse a pass at most `fresh_within_ms` old."""
        if (fresh_within_ms and self.passed_ms is not None and
                0 <= self.client.clock_ms() - self.passed_ms <= fresh_within_ms):
            return
        from .terminal_evidence import local_execution_state
        from .configuration_isolation import CLOID, INTENT
        from .hyperliquid_client import RequestsInfoTransport
        from .testnet_certification import TEAM
        local = local_execution_state(self.root)
        historical = dict(journal='qualification', cloid=CLOID, state='UNKNOWN', intent_key=INTENT)
        owned = self.owned()
        foreign = [r for r in local['unresolved'] if r != historical and
                   not (r.get('journal') == 'pas' and r.get('intent_key') in owned)]
        if local['status'] not in {'NO_LOCAL_UNRESOLVED_INTENT', 'BLOCKED_UNRESOLVED_INTENT'} or foreign:
            raise ExchangeError('SHARED_ACCOUNT_UNRESOLVED_INTENT_BLOCKS_SIGNING')
        now = self.client.clock_ms()
        if historical in local['unresolved'] and (self.historical_checked_ms is None or
                                                  now - self.historical_checked_ms > self.recheck_ms):
            status = self.account._query('orderStatus', oid=CLOID)
            if not isinstance(status, dict) or status.get('status') != 'unknownOid':
                raise ExchangeError('HISTORICAL_QUALIFICATION_INTENT_STATE_CHANGED')
            self.historical_checked_ms = now
        for kind in ('clearinghouseState', 'openOrders', 'frontendOpenOrders'):
            payload = dict(type=kind, user=TEAM, dex='par')
            client = self.client
            operation = ((lambda: client.transport(payload, cancel_event=client.read_cancel_event, progress=client.progress))
                         if isinstance(client.transport, RequestsInfoTransport) else (lambda: client.transport(payload)))
            value = client.rate_limits.read(kind, operation, request_key='shared:' + json.dumps(payload, sort_keys=True),
                                            cancel_event=client.read_cancel_event)
            if kind == 'clearinghouseState':
                if not isinstance(value, dict) or not isinstance(value.get('assetPositions'), list):
                    raise ExchangeError('SHARED_ACCOUNT_POSITION_READ_REQUIRED')
                occupied = any(decimal(r['position']['szi']) for r in value['assetPositions'])
            else:
                if not isinstance(value, list):
                    raise ExchangeError('SHARED_ACCOUNT_ORDER_READ_REQUIRED')
                occupied = bool(value)
            if occupied:
                raise ExchangeError('OTHER_DEX_EXPOSURE_OR_ORDERS_BLOCK_PAS_SIGNING')
        from .pas_readiness import require_pas_market_status
        require_pas_market_status(self.client)
        self.passed_ms = self.client.clock_ms()


class FreshReadGate:
    """Fresh exchange read immediately before every order, outside the 5 s signing window.

    The permission is issued just before the guarded context load, and the
    compliance and validator rules allow 5 s for the book, the account state,
    the readiness and the permission. On 2026-10-24 the stop and the flatten
    waited inside that window (rolling read budget, a clock needing two fresh
    confirmations, a revoked reconciliation) and failed STALE_PRICE_CONTEXT /
    ACCOUNT_NOT_READY. Every such wait now happens here, before the permission
    exists. The rules themselves are unchanged.
    """
    CLOCK_FRESH_MS = 2000

    def __init__(self, *, barrier, recovery, rates, clock, client, market, symbol, sleep=time.sleep, event=None):
        self.barrier, self.recovery, self.rates, self.clock = barrier, recovery, rates, clock
        self.client, self.market, self.symbol, self.sleep = client, market, symbol, sleep
        self.event = event or (lambda kind, **data: None)

    def __call__(self, *, entry=False, sign_by_ms=None):
        started = self.client.clock_ms()
        if not self.recovery.last_report.ready:
            self.recovery.recover()
        weight, limit_ms = (ENTRY_WEIGHT, ENTRY_WAIT_MS) if entry else (ORDER_WEIGHT, PROTECT_WAIT_MS)
        if entry and sign_by_ms is not None:
            # Wait for budget only while the signal can still sign well inside its window.
            limit_ms = max(0, sign_by_ms - started)
        waited = 0
        while True:
            delay = self.rates.read_budget_delay_ms(weight)
            if not delay:
                break
            if waited + delay > limit_ms:
                self.event('FRESH_READ_BUDGET_SHORT', entry=entry, weight=weight, delay_ms=delay, waited_ms=waited)
                if entry:
                    raise ExchangeError('ENTRY_READ_BUDGET_HEADROOM_UNAVAILABLE')
                break
            step = min(delay, 1000)
            self.sleep(step / 1000)
            waited += step
        for _ in range(3):
            observed = self.clock.observed_ms
            if self.clock.healthy and observed is not None and 0 <= self.client.clock_ms() - observed <= self.CLOCK_FRESH_MS:
                break
            sent = self.client.clock_ms()
            book = self.market.get_orderbook(self.symbol)
            self.clock.observe(book.timestamp_ms, sent, self.client.clock_ms())
        self.barrier.require()
        self.event('FRESH_READ', entry=entry, budget_wait_ms=waited, elapsed_ms=self.client.clock_ms() - started,
                   clock=self.clock.state.value)


def build_overnight_runtime(root, mandate_path, release_path, *, state_dir, runtime_cls=None, **extra):
    """Construction gate: evidence before key; the committed guards stay in force."""
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
    from .practice_preflight import read_api_key, api_signer
    from .testnet_certification import TEAM, API

    root = Path(root)
    m = OvernightMandate.read(mandate_path)
    if m.team_wallet.lower() != TEAM.lower() or m.api_wallet.lower() != API.lower():
        raise ExchangeError('OVERNIGHT_WALLET_IDENTITY_MISMATCH')
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
    from .pas_readiness import require_pas_market_status
    owned = lambda: {r['intent_key'] for r in journal.intents() if r['created_ms'] >= m.starts_ms}
    barrier = SharedAccountBarrier(root, account, client, owned)
    barrier.require()
    # All evidence and barriers pass before the key is touched.
    key, _ = read_api_key(root)
    try:
        signer = api_signer(key, API, TEAM)
    finally:
        key = None
    if signer.address.lower() != API.lower():
        raise ExchangeError('OVERNIGHT_SIGNER_IDENTITY_MISMATCH')
    nonces = NonceManager(state / 'nonces.sqlite', signer.address, journal=journal)
    public = HyperliquidMarketData(client)
    clock = ClockHealthMonitor(journal=journal, **clock_config)
    legs = {s: ScalpLeg(s) for s in m.markets}
    recovery = CarryAccountRecovery(account, journal, initial_start_ms=0, managers=legs,
                                    markets=m.markets, max_positions=m.max_positions)
    holder = {}
    provider = LiveContextProvider(public, account, API, clock, rates,
        reconciliation_ready=lambda: recovery.last_report.ready,
        feed_ready=lambda: bool(holder.get('stream') and holder['stream'].healthy), policy_leverage=1)
    original_load = provider.load

    def guarded_load(request, *, critical=False):
        # The runtime runs the full barrier right before issuing each permission;
        # the 5 s permission must survive the ~4 s context load that follows.
        barrier.require(fresh_within_ms=10000)
        return original_load(request, critical=critical)
    provider.load = guarded_load
    transport = OfficialSDKTransport(client, signer, TEAM, nonces, auth, rate_limits=rates)
    executor = CarryExecution(client, transport=transport, account=account, journal=journal,
        context_provider=provider, validator=HyperliquidOrderValidator(client, policy_leverage=1),
        recovery=recovery, clock_health=clock, rate_limits=rates)
    executor.max_positions = m.max_positions
    executor.allowed_markets = frozenset(m.markets)
    if m.max_positions > 1:
        from .multi_position_guard import MultiPositionGuard
        executor.position_guard = MultiPositionGuard(journal, clock_ms=client.clock_ms, max_positions=m.max_positions)
        executor.resting_take_profits = True
    else:
        executor.position_guard = BasketPositionGuard(journal, clock_ms=client.clock_ms)
    executor.compliance_guard.position_guard = executor.position_guard
    executor.compliance_guard.extra_setup_types = frozenset('MOMENTUM_' + d for d in m.directions)
    participation = decimal(m.participation, positive=True)
    if participation > D('0.1'):
        # Above the default 10% BBO rule, entries may take the mandate's share of the
        # same top-of-book snapshot the price checks use. A separately fetched L2 book
        # raced the context quote: on 25 Oct a one-tick move left 0 depth at the limit.
        executor.compliance_guard.entry_depth_participation = participation
    policy = replace(base_policy, enabled=True, approval_reference=m.approval_reference,
                     execution_slippage_fraction=decimal(m.stop_slippage, positive=True))
    protection = ScalpProtection(executor, policy=policy, managers=legs)
    stream = LiveAccountStream(TEAM, recovery, executor, clock_ms=client.clock_ms)
    holder['stream'] = stream
    runtime = (runtime_cls or OvernightRuntime)(mandate=m, executor=executor, protection=protection,
                               recovery=recovery, account=account, client=client, market=public, stream=stream,
                               auth=auth, legs=legs, state_dir=state_dir, **extra)
    gate = FreshReadGate(barrier=barrier, recovery=recovery, rates=rates, clock=clock, client=client, market=public,
                         symbol=m.markets[0], event=runtime._event)
    runtime.preflight = gate
    protection.before_action = gate
    return runtime
