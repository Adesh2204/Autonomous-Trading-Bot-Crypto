"""Offline simulated venue for the carry basket runtime: the dry run and the tests.

Never signs, never sends an order and has no exchange transport. Books come from a
callable (live public L2 books in the dry run, fixed books in tests); positions, open
orders, fills and stops live in memory. The runtime, slicer, fill and funding ledgers,
protection planning (CarryBasketProtection, including the bug #12 keep-valid rule) and
leg verification that run against it are the production classes.
"""
from dataclasses import asdict
from decimal import ROUND_DOWN, Decimal as D
from types import SimpleNamespace
import json, random, threading

from .base_exchange import ExchangeError, Fill, Position
from .hyperliquid_execution import LiveOrder
from .order_lifecycle import OrderRequest, OrderState

FEE_TAKER, FEE_MAKER = D('0.00090'), D('0.00030')


class SimVenue:
    def __init__(self, books, clock_ms, *, collateral=D('100000'), maker_fill_chance=0.0, seed=7):
        self.books, self.clock_ms = books, clock_ms
        self.collateral = D(collateral)
        self.positions = {}         # symbol -> [signed qty, avg entry]
        self.orders = {}            # oid -> order row (frontendOpenOrders shape) + bookkeeping
        self.status = {}            # oid and cloid -> terminal status
        self.fills = []
        self.oid, self.tid = 9000, 1
        self.maker_fill_chance = maker_fill_chance
        self.random = random.Random(seed)
        self.fail_next_protection = None
        self.leverage = {}          # symbol -> leverage dict; default 1x CROSS
        self.lock = threading.RLock()

    # ---------- matching ----------
    def _fill(self, order, quantity, price, maker):
        symbol = order['coin']
        signed = quantity if order['side'] == 'B' else -quantity
        qty, entry = self.positions.get(symbol, [D(0), None])
        start = qty
        closed = D(0)
        if qty == 0 or (qty > 0) == (signed > 0):
            entry = (abs(qty) * (entry or 0) + quantity * price) / (abs(qty) + quantity)
            qty += signed
        else:
            closing = min(abs(qty), quantity)
            closed = closing * (price - entry) * (1 if qty > 0 else -1)
            qty += signed
            if qty == 0:
                entry = None
        if qty:
            self.positions[symbol] = [qty, entry]
        else:
            self.positions.pop(symbol, None)
        fee = quantity * price * (FEE_MAKER if maker else FEE_TAKER)
        self.collateral += closed - fee
        self.fills.append(Fill(symbol, self.clock_ms(), str(self.tid), str(order['oid']), 'BUY' if signed > 0 else 'SELL',
                               quantity, price, fee, 'USDP', closed, start, 'SIMULATED_FILL'))
        self.tid += 1
        order['filled'] = order.get('filled', D(0)) + quantity
        order['sz'] = str(D(order['origSz']) - order['filled'])

    def tick(self):
        """Resting maker children fill when the opposite touch trades through them (or, in the
        dry run, with a small chance per tick, half the size: a labelled simulation of flow)."""
        with self.lock:
            for oid, o in list(self.orders.items()):
                if o['isTrigger']:
                    continue
                book = self.books(o['coin'])
                px = D(o['limitPx'])
                through = (o['side'] == 'B' and book.asks and book.asks[0].price <= px or
                           o['side'] == 'A' and book.bids and book.bids[0].price >= px)
                left = D(o['sz'])
                if through:
                    self._fill(o, left, px, True)
                elif self.maker_fill_chance and self.random.random() < self.maker_fill_chance:
                    lot = D(1).scaleb(D(o['origSz']).as_tuple().exponent)
                    part = (left / 2).quantize(lot, rounding=ROUND_DOWN)
                    self._fill(o, part if part > 0 else left, px, True)
                if D(o['sz']) <= 0:
                    self._close(oid, 'filled')

    def _close(self, oid, status):
        o = self.orders.pop(str(oid))
        self.status[str(oid)] = self.status[o['cloid']] = (status, o)

    def place(self, request, cloid, *, trigger=None):
        with self.lock:
            self.oid += 1
            oid = str(self.oid)
            o = dict(coin=request.symbol, oid=int(oid), side='B' if request.side == 'BUY' else 'A',
                     sz=str(request.quantity), origSz=str(request.quantity), limitPx=str(request.price),
                     isTrigger=trigger is not None, reduceOnly=request.reduce_only, cloid=cloid,
                     triggerPx=str(trigger) if trigger is not None else '0.0', isPositionTpsl=False,
                     orderType='Stop Market' if trigger is not None else 'Limit', tif=request.tif)
            if trigger is not None:
                self.orders[oid] = o
                return oid, D(0), None
            book = self.books(request.symbol)
            buy = request.side == 'BUY'
            touch = (book.asks if buy else book.bids)[0]
            crosses = touch.price <= request.price if buy else touch.price >= request.price
            if request.tif == 'Alo':
                if crosses:
                    return None, D(0), 'POST_ONLY_WOULD_CROSS'
                self.orders[oid] = o
                return oid, D(0), None
            if request.reduce_only:
                held = abs(self.positions.get(request.symbol, [D(0)])[0])
                o['origSz'] = o['sz'] = str(min(request.quantity, held))
            filled = min(D(o['sz']), touch.quantity) if crosses else D(0)
            if filled:
                self._fill(o, filled, touch.price, False)
            self.status[oid] = self.status[cloid] = ('filled' if filled == request.quantity else 'canceled', o)
            return oid, filled, None if filled else 'IOC_NO_LIQUIDITY'

    def cancel(self, oid):
        with self.lock:
            if str(oid) not in self.orders:
                raise ExchangeError('TEAM_OPEN_ORDER_REQUIRED')
            self._close(oid, 'canceled')


class SimAccount:
    """The HyperliquidAccount surface the carry runtime and protection read."""
    def __init__(self, venue, *, real=None):
        self.venue, self.real = venue, real
        self.client = SimpleNamespace(clock_ms=venue.clock_ms)

    def get_positions(self):
        with self.venue.lock:
            out = {}
            for s, (q, e) in self.venue.positions.items():
                book = self.venue.books(s)
                mid = (book.bids[0].price + book.asks[0].price) / 2
                out[s] = Position(s, q, e, (mid - e) * q, abs(q) * e, None)
            return out

    def get_position(self, symbol):
        return self.get_positions().get(symbol)

    def get_frontend_open_orders(self):
        with self.venue.lock:
            return [{k: v for k, v in o.items() if k not in {'filled', 'tif'}} for o in self.venue.orders.values()]

    get_open_orders = get_frontend_open_orders

    def _query(self, kind, **kw):
        if kind != 'orderStatus':
            raise ExchangeError('SIM_QUERY_UNSUPPORTED:' + kind)
        key = str(kw['oid'])
        with self.venue.lock:
            for o in self.venue.orders.values():
                if str(o['oid']) == key or o['cloid'] == key:
                    return dict(status='order', order=dict(order=dict(o), status='open'))
            if key in self.venue.status:
                status, o = self.venue.status[key]
                return dict(status='order', order=dict(order=dict(o), status=status))
        return dict(status='unknownOid')

    def get_fills(self, *, start_ms=None, end_ms=None):
        return [f for f in self.venue.fills if start_ms is None or f.timestamp_ms >= start_ms]

    def get_funding(self, start_ms, end_ms=None):
        return []

    def get_equity(self):
        return SimpleNamespace(collateral_balance=self.venue.collateral)


class SimExecutor:
    """Order surface of CarryExecution, executed against SimVenue. Never signs."""
    def __init__(self, venue, account, client, journal):
        self.venue, self.account, self.client, self.journal = venue, account, client, journal
        self.entries_paused = False
        self.protection = None
        self.recovery = SimpleNamespace()
        self.context_provider = SimpleNamespace()
        self.lock = threading.RLock()

    def _after_action(self):
        self.entries_paused = False

    def _order(self, row, state, filled=D(0), code=None):
        request = OrderRequest(**json.loads(row['request']))
        return LiveOrder(row['cloid'], row['intent_key'], row['candidate'], request, OrderState(state), row['oid'],
                         filled, None, request.quantity - filled, state != 'OPEN', code, None, 'OFFLINE_SIMULATION')

    def submit(self, request, *, permission=None):
        if self.entries_paused and not request.reduce_only:
            raise ExchangeError('ENTRY_PAUSED')
        key = request.client_order_id
        row, _ = self.journal.reserve(key, asdict(request), permission.candidate_id, self.client.clock_ms())
        self.journal.update(key, 'SUBMITTED', self.client.clock_ms())
        oid, filled, code = self.venue.place(request, row['cloid'])
        if oid is None:
            self.journal.update(key, 'REJECTED', self.client.clock_ms(), outcome=dict(code=code))
            return self._order(self.journal.intent(key), 'REJECTED', code=code)
        if request.tif == 'Alo':
            self.journal.update(key, 'OPEN', self.client.clock_ms(), oid=oid, outcome=dict(code='ORDER_RESTING'))
            return self._order(self.journal.intent(key), 'OPEN')
        state = 'FILLED' if filled == request.quantity else 'PARTIALLY_FILLED' if filled else 'CANCELLED'
        self.journal.update(key, state, self.client.clock_ms(), oid=oid,
                            outcome=dict(filled_quantity=filled, remaining_quantity=request.quantity - filled,
                                         remainder_cancelled=state != 'FILLED', code=code or 'ORDER_FILLED'))
        return self._order(self.journal.intent(key), state, filled, code)

    def cancel_order(self, symbol, order_id, *, critical=False):
        self.venue.cancel(order_id)
        return SimpleNamespace(code='ORDER_CANCELLED', state=OrderState.CANCELLED)

    def recover_uncertain(self, intent_key):
        row = self.journal.intent(intent_key)
        status = self.account._query('orderStatus', oid=row['cloid'])
        if status['status'] == 'order':
            o, terminal = status['order']['order'], status['order']['status']
            filled = D(o['origSz']) - D(o['sz'])
            state = ('OPEN' if terminal == 'open' and not filled else 'PARTIALLY_FILLED' if terminal == 'open'
                     else 'FILLED' if filled == D(o['origSz']) else 'PARTIALLY_FILLED' if filled else 'CANCELLED')
            self.journal.update(intent_key, state, self.client.clock_ms(), oid=str(o['oid']),
                                outcome=dict(filled_quantity=filled, remaining_quantity=D(o['origSz']) - filled,
                                             remainder_cancelled=terminal != 'open', code='SIM_ACCOUNT_RECOVERY'))
        return self._order(self.journal.intent(intent_key), self.journal.intent(intent_key)['state'])

    # ---------- protection surface (ExchangeProtectionManager) ----------
    def submit_protection(self, plan, intent_key, *, modify_oid=None):
        if self.venue.fail_next_protection and modify_oid is not None:
            code, self.venue.fail_next_protection = self.venue.fail_next_protection, None
            raise ExchangeError(code)
        request = OrderRequest(plan.symbol, plan.side, plan.quantity, plan.limit_price, reduce_only=True,
                               strategy_id='CATASTROPHIC_STOP', client_order_id=intent_key)
        row, _ = self.journal.reserve(intent_key, asdict(request), intent_key, self.client.clock_ms())
        if modify_oid is not None:
            self.venue.cancel(modify_oid)
        oid, _, _ = self.venue.place(request, row['cloid'], trigger=plan.trigger_price)
        self.journal.update(intent_key, 'OPEN', self.client.clock_ms(), oid=oid)
        return self._order(self.journal.intent(intent_key), 'OPEN')

    def cancel_protection(self, symbol, order_id, intent_key):
        self.venue.cancel(order_id)
        return SimpleNamespace(code='CANCELLED', state=OrderState.CANCELLED)


class SimStream:
    connected = ready = healthy = True
    pending = False

    def connect(self):
        pass

    def poll(self):
        pass

    def reconcile(self):
        pass


def build_simulated_runtime(mandate, *, client, books, clock_ms, state_dir, journal_path, collateral=D('100000'),
                            maker_fill_chance=0.0, real_account=None, runtime_cls=None, venue=None):
    """The production CarryBasketRuntime and CarryBasketProtection on a SimVenue (pass `venue` to restart
    against the same simulated exchange state)."""
    from .carry_basket import CarryBasketProtection, CarryBasketRuntime
    from .carry_runtime import CarryLeg
    from .execution_journal import ExecutionJournal
    from .position_protection import ProtectionPolicy
    venue = venue or SimVenue(books, clock_ms, collateral=collateral, maker_fill_chance=maker_fill_chance)
    account = SimAccount(venue, real=real_account)
    journal = ExecutionJournal(journal_path, session_id='offline:carry-simulation', team_address=mandate.team_wallet)
    executor = SimExecutor(venue, account, client, journal)
    legs = {s: CarryLeg(s, mandate.position_stop) for s in mandate.markets}
    policy = ProtectionPolicy(True, mandate.approval_reference, D(1), D(mandate.stop_slippage))
    protection = CarryBasketProtection(executor, policy=policy, managers=legs, stop_fraction=mandate.position_stop)
    recovery = executor.recovery
    recovery.recover = lambda: SimpleNamespace(ready=True, reasons=())
    recovery.last_report = SimpleNamespace(ready=True, reasons=())
    runtime = (runtime_cls or CarryBasketRuntime)(
        mandate=mandate, executor=executor, protection=protection, recovery=recovery, account=account,
        client=client, market=SimpleNamespace(get_orderbook=books), public=None, stream=SimStream(),
        auth=SimpleNamespace(require=lambda *a: None), state_dir=state_dir, legs=legs, clock_ms=clock_ms,
        leverage_reader=lambda symbol: venue.leverage.get(symbol, dict(type='cross', value=1)))
    return runtime, venue
