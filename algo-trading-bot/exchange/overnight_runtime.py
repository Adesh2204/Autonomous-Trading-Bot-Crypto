"""Unattended overnight momentum scalper inside the committed scored limits.

Committed scope enforced by the mandate and the unchanged central guards:
BTC/EWY only, LONG only, one position, <= $1,000 per entry, <= 2 entries per
clock hour, 1x cross, 10% of top-of-book (default compliance BBO rule).
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
from .position_protection import ExchangeProtectionManager, ProtectionPlan
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
                or self.max_positions != 1 or self.leverage != 1
                or not D(10) < decimal(self.max_notional) <= D(1000)
                or not 1 <= self.max_entries_per_hour <= 2
                or not D(0) < decimal(self.risk_fraction) <= D('0.005')
                or not D(0) < decimal(self.participation) <= D('0.1')
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
        return super().ensure_all(allow_actions=allow_actions)

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
        self.bars = {}
        self.preflight = lambda **k: None     # build_overnight_runtime installs the FreshReadGate

    # ---------- durable state ----------
    def _load_state(self):
        path = self.state_dir / 'overnight_state.json'
        if path.exists():
            value = json.loads(path.read_text())
            if value.get('mandate') == self.m.identity:
                return value
        return dict(mandate=self.m.identity, halted=None, finished=None, trade=None, trades=[], entries=[],
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
        result = self.executor.submit(request, permission=permission)
        position = self.positions().get(symbol)
        self._event('ENTRY_RESULT', symbol=symbol, state=result.state.value,
                    filled=position.quantity if position else 0, entry=position.entry_price if position else None)
        if position is None:
            self.legs[symbol].plan_stop = None
            return result
        # Keep the planned 1.5:1 geometry relative to the actual fill.
        actual = decimal(position.entry_price, positive=True)
        held = 'LONG' if position.quantity > 0 else 'SHORT'
        stop, target = levels(actual, decision['atr'], held, self.p)
        self.legs[symbol].plan_stop = stop
        self.legs[symbol].sync(position)
        self.state['trade'] = dict(symbol=symbol, side=held, entry_ms=self.clock_ms(), entry=str(actual), stop=str(stop),
                                   target=str(target), quantity=str(position.quantity), reason=decision['reason'],
                                   tp_key=None, half=half)
        self._save()
        # Re-plans the stop at the actual fill; the protection hook reads fresh before any change.
        self.protection.ensure_all()
        self._event('STOP_CHECKED', symbol=symbol, elapsed_ms=self.clock_ms() - self.state['trade']['entry_ms'],
                    status=self.protection.states.get(symbol, {}).get('status'))
        self.place_take_profit()
        return result

    def place_take_profit(self):
        trade = self.state['trade']
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

    def cancel_take_profit(self):
        trade = self.state['trade']
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
        if self.state['trade'] and self.state['trade']['symbol'] == symbol:
            self.cancel_take_profit()
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
        trade = self.state['trade']
        if trade and trade.get('tp_key') and trade['symbol'] not in held:
            try:
                self.executor.recover_uncertain(trade['tp_key'])
            except Exception as exc:
                self._event('TP_RECOVERY_ERROR', error=f'{type(exc).__name__}:{exc}')

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
        for f in self.account.get_fills(start_ms=trade['entry_ms'] - MIN_MS):
            if f.symbol == trade['symbol']:
                net += (f.closed_pnl or D(0)) - f.fee
        trade = dict(trade, exit_ms=self.clock_ms(), net=str(net))
        self.state['trades'].append(trade)
        self.state['trade'] = None
        self.legs[trade['symbol']].plan_stop = None
        self.guard.trade_closed(net, self.clock_ms())
        self._save()
        self._event('TRADE_CLOSED', symbol=trade['symbol'], net=net, reason=trade.get('reason'),
                    streak=self.guard.losing_streak, half_size=self.guard.half_size)

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
        if self.positions() or self.state['halted'] or now >= self.m.flatten_ms:
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
        if not found and now - last >= self.p.guarantee_ms:
            symbol = self.most_liquid()
            decision = guaranteed(self._bars(symbol, '5m', 40), self._bars(symbol, '15m', 60), self.p)
            if decision:
                decision['signal_ms'] = bar_close - MIN_MS
            self._event('TRADE_GUARANTEE_CHECK', symbol=symbol, decision=decision)
            if decision and decision['side']:
                found.append((symbol, decision))
                half = True
        for symbol, decision in found[:1]:
            try:
                self._stream_health()
                self.protection.ensure_all()
                self.cleanup_orders()
                if self.executor.entries_paused:
                    # A compliance block pauses entries until account truth is re-read.
                    self.executor._after_action()
                if self.executor.entries_paused or not self.protection.entries_allowed:
                    self._event('ENTRY_SKIPPED', symbol=symbol, reason='ENTRY_GATE',
                                entries_paused=self.executor.entries_paused)
                    return
                self.enter(symbol, decision, half=half)
                self.order_errors = 0
            except Exception as exc:
                self._note_order_error(exc, 'entry:' + symbol)

    def most_liquid(self):
        depth = {}
        for symbol in self.m.markets:
            book = self.market.get_orderbook(symbol)
            mid = (book.bids[0].price + book.asks[0].price) / 2
            depth[symbol] = sum((l.price * l.quantity for l in book.asks if l.price <= mid * D('1.0025')), D(0))
        return max(depth, key=depth.get)

    def manage(self):
        """Time stop, protection repair, flat detection for the tracked trade."""
        trade = self.state['trade']
        positions = self.positions()
        if trade and trade['symbol'] not in positions:
            self.cleanup_orders()
            self._closed_trade(trade)
            self.protection.ensure_all()      # cancels the now-obsolete exchange stop
            return
        for symbol, position in positions.items():
            if symbol not in self.m.markets or ('LONG' if position.quantity > 0 else 'SHORT') not in self.m.directions:
                self.exit(symbol, 'OUTSIDE_COMMITTED_SCOPE')
                continue
            status = self.protection.states.get(symbol, {}).get('status')
            if status != 'ACTIVE':
                self.protection.ensure_all()          # the protection hook reads fresh before signing
                if self.protection.states.get(symbol, {}).get('status') != 'ACTIVE':
                    self.exit(symbol, 'EXCHANGE_STOP_NOT_ACTIVE')
                    continue
            if trade and trade['symbol'] == symbol:
                if not trade.get('tp_key'):
                    self.place_take_profit()
                if self.clock_ms() - trade['entry_ms'] >= self.p.time_stop_ms:
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
        trade = self.state['trade']
        if trade:
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
        if positions and not trade:
            # Restart without a durable plan: adopt with the default stop, never re-enter.
            symbol, position = next(iter(positions.items()))
            self.legs[symbol].sync(position)
            self.state['trade'] = dict(symbol=symbol, side='LONG' if position.quantity > 0 else 'SHORT',
                                       entry_ms=self.clock_ms(), entry=str(position.entry_price),
                                       stop=str(self.legs[symbol]._open_position['stop_loss_price']),
                                       target=str(decimal(position.entry_price) *
                                                  (D('1.0075') if position.quantity > 0 else D('0.9925'))),
                                       quantity=str(position.quantity), reason='ADOPTED_ON_RESTART', tp_key=None)
            self._save()
        self.cleanup_orders()
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
                        if self.state['trade'] and not self.positions():
                            self._closed_trade(self.state['trade'])
                    self.heartbeat()
                    stop.wait(5)
                    continue
                self._stream_health()
                # Flat and untracked: poll the account every 15 s, not every cycle, so the
                # rolling read budget has room for the next entry and its stop.
                if self.state['trade'] or now - self.last_account_ms >= FLAT_POLL_MS:
                    self.last_account_ms = now
                    self.manage()
                    equity = self.equity()
                    self._apply_verdict(self.guard.check(self.guard_return(equity)))
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
                                    markets=m.markets, max_positions=1)
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
    executor.max_positions = 1
    executor.allowed_markets = frozenset(m.markets)
    executor.position_guard = BasketPositionGuard(journal, clock_ms=client.clock_ms, max_positions=1)
    executor.compliance_guard.position_guard = executor.position_guard
    executor.compliance_guard.extra_setup_types = frozenset('MOMENTUM_' + d for d in m.directions)
    # No L2 hook: the default 10%-of-top-of-book compliance rule stays in force.
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
