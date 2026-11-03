"""Carry profile (user directive 25 Oct 2026, "YES, CARRY"): limits, scope, sliced entry with partial
fills, per-leg stops sized to the filled quantity, restart reconcile, halts and the final unwind.

The runtime, slicer, ledgers, protection and guards are the production classes; the venue is the
offline SimVenue (never signs, no exchange transport)."""
from dataclasses import asdict, replace
from decimal import Decimal as D
from types import SimpleNamespace
import json

import pytest

from exchange import carry_basket
from exchange.base_exchange import BookLevel, ExchangeError, MarketSpec, OrderBook, Position
from exchange.carry_basket import CarryPositionGuard
from exchange.carry_runtime import CARRY_BASKET, CARRY_BASKET_EWJ_BTC_SHORT, CARRY_PROFILE, CarryExecution, CarryMandate
from exchange.carry_simulation import build_simulated_runtime
from exchange.carry_slicer import MAKER, TAKER, SliceParams, child, remaining, stale
from exchange.entry_scope import CARRY_ENTRY_MARKETS, PAS_ENTRY_MARKETS, require_entry
from exchange.execution_journal import ExecutionJournal
from exchange.order_lifecycle import OrderRequest
from test_live_exchange_execution import live, permission
from test_single_position_compliance import evaluate

HOUR = 3600000
SPECS = {'pas:BTC': (5, 80000, '0.05'), 'pas:ETH': (4, 2350, '1.7'), 'pas:HYPE': (2, 77, '52'),
         'pas:SP500': (3, 7630, '0.52'), 'pas:USDJPY': (2, D('156.9'), '25')}


def basket_mandate(**changes):
    from exchange.competition_windows import SCORED_START_MS, SCORED_END_MS
    from exchange.venue_profiles import venue_profile
    base = dict(team_wallet='0x' + '1' * 40, api_wallet='0x' + '2' * 40, markets=tuple(s for s, _ in CARRY_BASKET),
                starts_ms=SCORED_START_MS + 1, flatten_ms=SCORED_END_MS - 1800000, expires_ms=SCORED_END_MS - 300000,
                starting_equity='100000', leg_notional='9500', source_hash='a' * 64, release_sha256='b' * 64,
                venue_identity=venue_profile('pas').identity, approval_reference='YES, CARRY (25 Oct 2026)',
                profile=CARRY_PROFILE, sides=CARRY_BASKET, unwind_starts_ms=SCORED_END_MS - 6 * HOUR - 1800000)
    return CarryMandate(**dict(base, **changes))


# ---------- carry profile limits ----------
def test_carry_profile_mandate_is_valid_and_survives_a_json_round_trip(tmp_path):
    m = basket_mandate().require()
    path = tmp_path / 'mandate.json'
    path.write_text(json.dumps(asdict(m)))
    assert CarryMandate.read(path) == m and m.basket['pas:USDJPY'] == 'SHORT' and m.max_positions == 5


@pytest.mark.parametrize('change', [
    dict(leg_notional='19001'), dict(max_positions=4), dict(sides=CARRY_BASKET[:4] + (('pas:USDJPY', 'LONG'),)),
    dict(markets=('pas:BTC', 'pas:ETH', 'pas:HYPE', 'pas:SP500', 'pas:EWY')), dict(profile='OTHER'),
    dict(book_share='0.26'), dict(reprice_ms=300000), dict(maker_window_ms=3 * HOUR), dict(position_stop='0.07'),
    dict(account_loss_halt='0.015'), dict(unwind_starts_ms=1), dict(taker_gap_ms=0), dict(leverage=2)])
def test_carry_profile_rejects_any_other_limit(change):
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(**change).require()


def test_original_funding_carry_mandate_is_unaffected_by_the_profile_fields():
    m = basket_mandate(profile='', sides=(), unwind_starts_ms=0, leg_notional='19000').require()
    assert m.profile == '' and m.leg_notional == '19000'


# ---------- profile scoped to the carry runtime only ----------
def test_entry_scope_widens_only_for_the_carry_scope():
    for symbol in ('pas:ETH', 'pas:SP500', 'pas:USDJPY'):
        with pytest.raises(ExchangeError, match='V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY'):
            require_entry(symbol)
        require_entry(symbol, 'CARRY')
    with pytest.raises(ExchangeError, match='CARRY_BASKET_NEW_ENTRIES_ONLY'):
        require_entry('pas:EWY', 'CARRY')
    with pytest.raises(ExchangeError, match='CARRY_BASKET_NEW_ENTRIES_ONLY'):
        require_entry('pas:BTC', 'SCALPER')
    assert PAS_ENTRY_MARKETS == {'pas:BTC', 'pas:EWY', 'pas:HYPE'} and len(CARRY_ENTRY_MARKETS) == 6
    assert 'pas:EWJ' in CARRY_ENTRY_MARKETS                                         # joined 2 Nov 22:05 IST


def test_other_runtimes_keep_their_committed_guards():
    from exchange.exchange_rules import HyperliquidOrderValidator
    from exchange.multi_position_guard import MAX_CONCURRENT_POSITIONS
    assert CarryExecution.sliced_legs is False and MAX_CONCURRENT_POSITIONS == 3
    assert getattr(HyperliquidOrderValidator, 'entry_scope', None) is None


def test_basket_builder_refuses_a_mandate_without_the_profile(tmp_path):
    path = tmp_path / 'mandate.json'
    path.write_text(json.dumps(asdict(basket_mandate(profile='', sides=(), unwind_starts_ms=0))))
    with pytest.raises(ExchangeError, match='CARRY_PROFILE_MANDATE_REQUIRED'):
        carry_basket.build_carry_basket_runtime(tmp_path, path, tmp_path / 'receipt.json', state_dir=tmp_path)


# ---------- slicer ----------
def quote(bid, ask, bq, aq):
    return SimpleNamespace(bid=D(bid), ask=D(ask), bid_quantity=D(bq), ask_quantity=D(aq))


def test_child_is_a_quarter_of_the_thinner_touch_at_the_right_price():
    spec, p = MarketSpec('pas:BTC', 5, 40, 1), SliceParams()
    q = quote('80000', '80010', '0.006', '0.04')
    maker, _ = child('BUY', D('0.118'), q, spec, MAKER, p)
    taker, _ = child('BUY', D('0.118'), q, spec, TAKER, p)
    short, _ = child('SELL', D('0.118'), q, spec, MAKER, p)
    assert (maker['price'], maker['tif'], maker['quantity']) == (D('80000'), 'Alo', D('0.0015'))
    assert (taker['price'], taker['tif']) == (D('80010'), 'Ioc') and short['price'] == D('80010')


def test_child_never_strands_dust_and_refuses_a_thin_touch():
    spec, p = MarketSpec('pas:BTC', 5, 40, 1), SliceParams()
    q = quote('80000', '80010', '0.006', '0.006')
    plan, _ = child('BUY', D('0.0016'), q, spec, TAKER, p)
    assert (D('0.0016') - plan['quantity']) * D('80010') >= 11
    assert child('BUY', D('0.0001'), q, spec, TAKER, p) == (None, 'REMAINDER_BELOW_MINIMUM')
    assert child('BUY', D('0.1'), quote('80000', '80010', '0.00001', '1'), spec, MAKER, p) == (None, 'TOUCH_TOO_THIN')
    assert remaining(D('0.1'), D('-0.04')) == D('0.06') and remaining(D('0.1'), D('0.2')) == 0


def test_reprice_only_after_ten_minutes_and_off_the_touch():
    p = SliceParams()
    row = dict(side='BUY', price='80000', placed_ms=0)
    assert not stale(row, quote('80001', '80010', 1, 1), p.reprice_ms - 1, p)
    assert stale(row, quote('80001', '80010', 1, 1), p.reprice_ms, p)
    assert not stale(row, quote('80000', '80010', 1, 1), p.reprice_ms, p)


# ---------- carry position guard (real journal) ----------
def ctx(now, positions=None, orders=()):
    return SimpleNamespace(positions=positions or {}, open_orders=tuple(orders), fills=(), account_ms=now,
                           readiness=SimpleNamespace(account_ready=True), reconciled=True)


def entry(symbol, side, key):
    return OrderRequest(symbol, side, D('1'), D('100'), tif='Alo', strategy_id='CARRY_LONG' if side == 'BUY' else
                        'CARRY_SHORT', client_order_id=key)


@pytest.fixture
def guard(tmp_path):
    journal = ExecutionJournal(tmp_path / 'j.sqlite', session_id='offline:carry', team_address='0x' + '1' * 40)
    clock = [10 ** 12]
    g = CarryPositionGuard(journal, clock_ms=lambda: clock[0], sides=CARRY_BASKET)
    yield SimpleNamespace(g=g, journal=journal, now=clock[0])
    journal.close()


def reserve(t, req, positions=None, orders=()):
    decision = t.g.evaluate(req, ctx(t.now, positions, orders), t.now)
    assert decision.allowed, decision
    gen = t.journal.control('global_position_lock')['generation']
    t.journal.reserve(req.client_order_id, asdict(req), req.client_order_id, t.now, position_guard=t.g,
                      position_generation=gen)


def test_one_unresolved_child_per_leg_and_sides_fixed(guard):
    t = guard
    reserve(t, entry('pas:BTC', 'BUY', 'c1'))
    c = ctx(t.now)
    assert t.g.evaluate(entry('pas:BTC', 'BUY', 'c2'), c, t.now).code == 'POSITION_LIMIT'      # one per leg
    assert t.g.evaluate(entry('pas:USDJPY', 'BUY', 'c3'), c, t.now).code == 'POSITION_LIMIT'   # wrong side
    assert t.g.evaluate(entry('pas:EWY', 'BUY', 'c4'), c, t.now).code == 'POSITION_LIMIT'      # not in basket
    reserve(t, entry('pas:ETH', 'BUY', 'c5'))
    reserve(t, entry('pas:USDJPY', 'SELL', 'c6'))


def test_adding_to_a_held_leg_next_to_resting_children_and_its_stop(guard):
    t = guard
    reserve(t, entry('pas:BTC', 'BUY', 'c1'))
    t.journal.update('c1', 'PARTIALLY_FILLED', t.now, oid='11',
                     outcome=dict(filled_quantity='0.01', remainder_cancelled=True))
    held = {'pas:BTC': Position('pas:BTC', D('0.01'), D('80000'), D(0), D(0), None)}
    stop = dict(coin='pas:BTC', oid=13, isTrigger=True, reduceOnly=True)
    # A fill with the account read as flat and no fill evidence is not trusted.
    assert t.g.evaluate(entry('pas:ETH', 'BUY', 'c2'), ctx(t.now), t.now).code == 'UNKNOWN_ACCOUNT_STATE'
    reserve(t, entry('pas:ETH', 'BUY', 'c2'), held, [stop])
    t.journal.update('c2', 'OPEN', t.now, oid='12')
    orders = [dict(coin='pas:ETH', oid=12, isTrigger=False, reduceOnly=False), stop]
    c = ctx(t.now, held, orders)
    assert t.g.evaluate(entry('pas:BTC', 'BUY', 'c3'), c, t.now).allowed                      # add to the leg
    assert t.g.evaluate(entry('pas:BTC', 'SELL', 'c4'), c, t.now).code == 'POSITION_LIMIT'    # never flip
    assert t.g.evaluate(entry('pas:ETH', 'BUY', 'c5'), c, t.now).code == 'POSITION_LIMIT'     # child resting
    reserve(t, entry('pas:BTC', 'BUY', 'c3'), held, orders)


@pytest.mark.parametrize('positions,orders,reason', [
    ({'pas:GOLD': Position('pas:GOLD', D('1'), D('10'), D(0), D(0), None)}, [], 'UNEXPECTED_CARRY_EXPOSURE'),
    ({'pas:USDJPY': Position('pas:USDJPY', D('5'), D('150'), D(0), D(0), None)}, [], 'UNEXPECTED_CARRY_EXPOSURE'),
    ({}, [dict(coin='pas:BTC', oid=99, isTrigger=False, reduceOnly=False)], 'UNEXPLAINED_OPEN_ORDER'),
])
def test_foreign_or_wrong_side_exposure_and_unknown_orders_block_entries(guard, positions, orders, reason):
    t = guard
    decision = t.g.evaluate(entry('pas:ETH', 'BUY', 'x'), ctx(t.now, positions, orders), t.now)
    assert decision.code == 'UNKNOWN_ACCOUNT_STATE' and t.g.reason == reason


def test_stale_account_truth_blocks_entries(guard):
    t = guard
    assert t.g.evaluate(entry('pas:ETH', 'BUY', 'x'), ctx(t.now - 6000), t.now).code == 'UNKNOWN_ACCOUNT_STATE'


def test_an_observation_gone_stale_before_the_reservation_is_a_skip_not_a_position_limit(guard):
    # 3 Nov: a slow read let the 5 s window lapse between evaluate and reserve; POSITION_LIMIT counted as an order error.
    t = guard
    req = entry('pas:ETH', 'BUY', 'x')
    assert t.g.evaluate(req, ctx(t.now), t.now).allowed
    gen = t.journal.control('global_position_lock')['generation']
    with pytest.raises(ExchangeError, match='ACCOUNT_PREFLIGHT_INVALIDATED'):
        t.journal.reserve('x', asdict(req), 'x', t.now + 10000, position_guard=t.g, position_generation=gen)
    assert 'ACCOUNT_PREFLIGHT_INVALIDATED' in carry_basket.SKIP_CODES and t.journal.intent('x') is None
    reserve(t, entry('pas:BTC', 'BUY', 'y'))                                         # fresh: reserved as before


# ---------- real compliance guard and validator ----------
def test_real_compliance_accepts_a_post_only_child_inside_the_book_share(live):
    g = live.executor.compliance_guard
    live.executor.position_guard = g.position_guard = CarryPositionGuard(
        live.journal, clock_ms=lambda: live.fixture.now, sides=(('par:BTC', 'LONG'),))
    g.extra_setup_types = frozenset({'CARRY_LONG'})
    g.entry_depth_participation = D('0.25')
    req = OrderRequest('par:BTC', 'BUY', D('25'), D('99.99'), tif='Alo', strategy_id='CARRY_LONG', client_order_id='c1')
    token = permission(req)
    token = replace(token, provenance=replace(token.provenance, setup_type='CARRY_LONG'))
    assert evaluate(live, req, token=token).allowed
    big = replace(req, quantity=D('25.01'))
    assert evaluate(live, big, token=replace(token, maximum_quantity=big.quantity)).code == 'BOOK_MANIPULATION_RISK'
    cross = replace(req, price=D('100.01'))
    context = live.provider.load(cross)
    assert live.validator.validate(cross, context, token, live.fixture.now).code == 'POST_ONLY_WOULD_CROSS'


# ---------- runtime on the simulated venue ----------
def start_legs(w):
    """Start every leg (its maker window opens at its first child), then let the window pass."""
    w.r.startup()
    for _ in range(5):
        w.step()
    w.clock[0] += 2 * HOUR


class World:
    def __init__(self, tmp_path, monkeypatch, *, venue=None, books=None, clock=None, maker_fill_chance=0.0, **mandate):
        monkeypatch.setattr(carry_basket.time, 'sleep', lambda s: None)
        self.m = basket_mandate(**mandate).require()
        self.clock = clock or [self.m.starts_ms + 1000]
        self.books = books or {s: self.book(s) for s in SPECS}
        specs = {s: MarketSpec(s, d, 20, i) for i, (s, (d, _, _)) in enumerate(SPECS.items())}
        client = SimpleNamespace(market=specs.__getitem__, clock_ms=lambda: self.clock[0],
                                 post_info=lambda *a, **k: [])
        self.r, self.venue = build_simulated_runtime(
            self.m, client=client, books=lambda s: self.books[s], clock_ms=lambda: self.clock[0],
            state_dir=tmp_path / 'state', journal_path=tmp_path / 'journal.sqlite', venue=venue,
            maker_fill_chance=maker_fill_chance)

    @staticmethod
    def book(symbol, shift=0):
        decimals, px, qty = SPECS[symbol]
        spec = MarketSpec(symbol, decimals, 20, 0)
        px = D(str(px)) + shift
        tick = px * D('0.0001')                         # real books sit on the exchange price grid
        bid, ask = spec.normalize_price(px - tick, 'BUY'), spec.normalize_price(px + tick, 'SELL')
        return OrderBook(symbol, 0, (BookLevel(bid, D(qty)),), (BookLevel(ask, D(qty)),))

    def step(self, ms=10000):
        self.clock[0] += ms
        self.venue.tick()
        self.r.cycle()

    def leg(self, symbol):
        return self.r.state['legs'][symbol]

    def position(self, symbol):
        p = self.venue.positions.get(symbol)
        return p[0] if p else D(0)

    def stops(self, symbol):
        return [o for o in self.venue.orders.values() if o['coin'] == symbol and o['isTrigger']]

    def children(self, symbol=None):
        return [o for o in self.venue.orders.values() if not o['isTrigger'] and (symbol is None or o['coin'] == symbol)]

    def events(self, kind):
        path = self.r.state_dir / 'carry_events.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines() if json.loads(l)['kind'] == kind]


def test_sliced_entry_with_a_partial_fill_resizes_the_stop_then_finishes_with_touch_ioc(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    for _ in range(5):
        w.step()
    resting = w.children()
    assert len(resting) == 5 and all(o['tif'] == 'Alo' for o in w.venue.orders.values() if not o['isTrigger'])
    btc = w.children('pas:BTC')[0]
    assert D(btc['limitPx']) == w.books['pas:BTC'].bids[0].price                    # maker at our side of the touch
    assert D(btc['sz']) <= D('0.05') * D('0.25')
    w.venue._fill(btc, D('0.004'), D(btc['limitPx']), True)                        # partial fill
    w.step()
    assert w.events('CHILD_CANCEL')[0]['reason'] == 'PARTIAL_FILL_RESIZE_STOP'
    stop = w.stops('pas:BTC')
    assert len(stop) == 1 and D(stop[0]['sz']) == w.position('pas:BTC') == D('0.004')    # sized to the fill
    assert D(stop[0]['triggerPx']) == MarketSpec('pas:BTC', 5, 20, 0).normalize_price(D(btc['limitPx']) * D('0.92'), 'SELL')
    w.clock[0] += 2 * HOUR                                                           # maker window over
    for _ in range(400):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in SPECS):
            break
    for symbol in SPECS:
        leg, qty = w.leg(symbol), w.position(symbol)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert (qty > 0) == (dict(CARRY_BASKET)[symbol] == 'LONG')
        assert abs(qty) * D(str(SPECS[symbol][1])) <= D('9500') * D('1.002')
        assert (D(leg['target']) - abs(qty)) * D(str(SPECS[symbol][1])) < 11
        assert [D(s['sz']) for s in w.stops(symbol)] == [abs(qty)]                  # one full-size stop per leg
    takers = [e for e in w.events('CHILD_ATTEMPT') if e['child_kind'] == TAKER]
    assert takers and all(D(e['quantity']) <= D(e['touch_quantity']) * D('0.25') for e in takers)
    assert all(D(e['price']) == (D(e['ask']) if e['side'] == 'BUY' else D(e['bid'])) for e in takers)
    assert w.r.order_errors == 0 and not w.r.state['halted'] and not w.children()


def test_unfilled_maker_child_is_repriced_at_the_touch_after_ten_minutes(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    for _ in range(5):
        w.step()
    first = w.children('pas:ETH')[0]['oid']
    w.books['pas:ETH'] = World.book('pas:ETH', shift=D('0.5'))                      # touch moved up
    w.step(600000)
    w.step()
    assert any(e['reason'] == 'REPRICE_AT_TOUCH' and e['symbol'] == 'pas:ETH' for e in w.events('CHILD_CANCEL'))
    for _ in range(5):
        w.step()
    again = w.children('pas:ETH')[0]
    assert again['oid'] != first and D(again['limitPx']) == w.books['pas:ETH'].bids[0].price


def test_restart_cancels_and_settles_resting_children_and_keeps_leg_progress(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    for _ in range(5):
        w.step()
    btc = w.children('pas:BTC')[0]
    w.venue._fill(btc, D('0.004'), D(btc['limitPx']), True)
    target, started = w.leg('pas:BTC')['target'], w.leg('pas:BTC')['started_ms']
    # Crash: a new process, same journal and state directory, same exchange.
    w2 = World(tmp_path, monkeypatch, venue=w.venue, books=w.books, clock=w.clock)
    w2.r.startup()
    assert not w2.children() and all(w2.leg(s)['child'] is None for s in SPECS)
    assert (w2.leg('pas:BTC')['target'], w2.leg('pas:BTC')['started_ms']) == (target, started)
    assert [D(s['sz']) for s in w2.stops('pas:BTC')] == [D('0.004')]                # stop for the fill
    rows = [r for r in w2.r.executor.journal.intents() if json.loads(r['request'])['strategy_id'] == 'CARRY_LONG']
    assert rows and all(r['state'] in {'CANCELLED', 'PARTIALLY_FILLED'} for r in rows)
    assert len(w2.events('RESTART_CHILD_RECONCILED')) == 5
    w2.step()
    assert len(w2.children()) == 1                                                  # building resumes, one child


def test_a_fresh_state_under_a_mandate_that_already_traded_never_reuses_a_journaled_child_key(tmp_path, monkeypatch):
    # 3 Nov: a rebind reproduced the same mandate identity into a fresh state directory, n restarted at 0 and every
    # new child hit CLOID_INTENT_CONFLICT on the prior run's journal rows, which counted toward the 3-error halt.
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    for _ in range(5):
        w.step()
    used = {r['intent_key'] for r in w.r.executor.journal.intents()}
    (tmp_path / 'state').rename(tmp_path / 'state_archived')                         # same mandate, fresh state
    w2 = World(tmp_path, monkeypatch, venue=w.venue, books=w.books, clock=w.clock)
    w2.r.startup()
    for _ in range(5):
        w2.step()
    new = {r['intent_key'] for r in w2.r.executor.journal.intents()} - used
    assert sorted(k.rsplit(':', 1)[1] for k in new if k.startswith('carry-in:')) == ['2'] * 5
    assert len(w2.children()) == 5 and w2.r.order_errors == 0 and not w2.r.state['halted']


def test_three_consecutive_order_errors_halt_and_unwind_everything_at_the_touch(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    start_legs(w)
    for _ in range(12):
        w.step(31000)
    assert w.position('pas:BTC') > 0
    place = w.venue.place
    w.venue.place = lambda request, cloid, **k: (None, D(0), 'MARGIN_REJECTED') if not request.reduce_only \
        else place(request, cloid, **k)
    for _ in range(3):
        w.step(31000)
    assert w.r.state['halted']['reason'] == 'CONSECUTIVE_ORDER_ERRORS'
    for _ in range(300):
        w.step(31000)
        if not w.venue.positions:
            break
    w.step()                                                                        # legs close on the next read
    assert not w.venue.positions and all(w.leg(s)['mode'] == 'CLOSED' for s in SPECS)
    exits = [e for e in w.events('CHILD_ATTEMPT') if not e['entry']]
    assert exits and all(e['tif'] == 'Ioc' and D(e['quantity']) <= D(e['touch_quantity']) * D('0.25') for e in exits)
    assert not w.stops('pas:BTC')                                                   # flat leg: stop removed


def test_leg_verification_mismatch_flattens_that_leg_and_halts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    start_legs(w)
    original = w.r.verify_leg

    def tamper(symbol):
        if symbol == 'pas:HYPE':                                                    # ledger disagrees with the position
            w.r.state['fills'] = {k: v for k, v in w.r.state['fills'].items() if v['symbol'] != 'pas:HYPE'}
        return original(symbol)
    monkeypatch.setattr(w.r, 'verify_leg', tamper)
    for _ in range(400):
        w.step(31000)
        if w.r.state['halted']:
            break
    assert w.r.state['halted']['reason'] == 'LEG_VERIFICATION_FAILED:pas:HYPE'
    assert w.leg('pas:HYPE')['unwind']['kind'] == 'EMERGENCY'
    for _ in range(100):
        w.step(31000)
    assert w.position('pas:HYPE') == 0 and w.leg('pas:HYPE')['mode'] == 'CLOSED'
    assert [l for s, l in w.r.state['legs'].items() if s != 'pas:HYPE' and l['mode'] == 'UNWIND'] == []


def test_final_unwind_is_maker_first_then_touch_ioc_and_ends_flat(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    start_legs(w)
    for _ in range(400):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in SPECS):
            break
    w.clock[0] = w.m.unwind_starts_ms
    for _ in range(5):
        w.step()
    exits = w.children()
    assert len(exits) == 5 and all(o['reduceOnly'] and o['tif'] == 'Alo' for o in w.venue.orders.values()
                                   if not o['isTrigger'])
    w.clock[0] += 2 * HOUR
    for _ in range(400):
        w.step(31000)
        if not w.venue.positions:
            break
    w.step()                                                                        # legs close on the next read
    assert not w.venue.positions and all(w.leg(s)['mode'] == 'CLOSED' for s in SPECS)
    assert not w.venue.orders                                                       # stops gone, nothing resting
    assert w.events('FINAL_UNWIND_STARTED')


def test_stop_update_error_keeps_a_valid_full_size_stop(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    start_legs(w)
    for _ in range(400):
        w.step(31000)
        if w.leg('pas:BTC')['mode'] == 'HOLD':
            break
    stop = w.stops('pas:BTC')[0]
    stop['triggerPx'] = str(D(stop['triggerPx']) - 1)                               # plan now differs: update
    w.venue.fail_next_protection = 'DUPLICATE_ORDER'
    w.r.protection.ensure_all()
    state = w.r.protection.states['pas:BTC']
    assert state['status'] == 'ACTIVE' and state['reason'] == 'KEPT_EXISTING_STOP_AFTER_UPDATE_ERROR'
    w.r.check_stops(force=True)                                                     # next check repairs it
    assert w.r.protection.states['pas:BTC']['reason'] is None and len(w.stops('pas:BTC')) == 1


def test_heartbeat_and_status_split_equity_into_price_funding_and_fees(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    start_legs(w)
    for _ in range(30):
        w.step(31000)
    w.r.state['funding'] = {'pas:BTC': '1.50'}
    snap = w.r.snapshot()
    assert D(snap['price_pnl']) == D(snap['change']) - D('1.50') + D(snap['fees']) and D(snap['fees']) > 0
    path = w.r.status_report(force=True)
    text = path.read_text()
    assert text.startswith('Equity ') and 'funding earned +1.50' in text and 'judge the carry on 6 Nov' in text
    w.r.heartbeat(force=True)
    beat = json.loads((w.r.state_dir / 'heartbeat.jsonl').read_text().splitlines()[-1])
    assert {l['symbol'] for l in beat['legs']} == set(SPECS) and 'stop' in beat['legs'][0]


def test_stop_flag_shuts_down_cleanly_without_leaving_children(tmp_path, monkeypatch):
    import threading
    w = World(tmp_path, monkeypatch)
    w.r.CYCLE_S = 0
    calls = []
    original = w.r.cycle

    def cycle():
        calls.append(1)
        w.clock[0] += 10000
        original()
        if len(calls) == 3:
            (w.r.state_dir / 'stop.flag').touch()
    monkeypatch.setattr(w.r, 'cycle', cycle)
    w.r.run(threading.Event())
    assert len(calls) == 3 and not w.children() and w.events('STOPPED')[-1]['reason'] == 'STOP_FLAG'


def test_a_leg_not_at_one_x_waits_without_errors_and_starts_once_configured(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    for symbol in ('pas:ETH', 'pas:SP500', 'pas:USDJPY'):
        w.venue.leverage[symbol] = dict(type='cross', value=20)
    w.r.startup()
    for _ in range(10):
        w.step()
    assert {o['coin'] for o in w.children()} == {'pas:BTC', 'pas:HYPE'}
    assert w.r.order_errors == 0 and not w.r.state['halted']
    assert {e['symbol'] for e in w.events('LEG_WAITING_FOR_1X')} == {'pas:ETH', 'pas:SP500', 'pas:USDJPY'}
    w.venue.leverage.clear()                                                        # the human 1x route ran
    w.step(300000)
    for _ in range(5):
        w.step()
    assert {o['coin'] for o in w.children()} == set(SPECS)
    assert {e['symbol'] for e in w.events('LEG_LEVERAGE_READY')} == set(SPECS)


def test_a_compliance_leverage_refusal_is_a_skip_and_rechecks_later(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    w.r._skip('pas:BTC', 'INVALID_LEVERAGE')
    assert w.r.leverage_ok['pas:BTC'] is False and w.r.order_errors == 0
    w.clock[0] += 300001
    assert w.r.one_x('pas:BTC')


def test_entries_wait_while_the_account_stream_is_unhealthy_and_data_not_ready_is_a_skip(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    w.r.stream.healthy = False
    for _ in range(5):
        w.step()
    assert not w.children() and w.r.order_errors == 0 and not w.r.state['halted']
    assert 'DATA_NOT_READY' in carry_basket.SKIP_CODES
    w.r.stream.healthy = True
    w.step()
    assert len(w.children()) == 1


class ReceiverStream:
    def __init__(self):
        self.receiver_thread, self.started, self.stopped = None, 0, 0
        self.healthy, self.pending, self.connected, self.ready, self.receiver_fatal = True, False, True, True, None

    @property
    def background_receiving(self):
        return self.receiver_thread is not None

    def start_receiver(self):
        self.receiver_thread, self.started = object(), self.started + 1

    def stop_receiver(self):
        self.stopped += 1

    def connect(self):
        raise AssertionError('the owner thread must not connect when a receiver runs')

    poll = connect


def test_runtime_uses_the_background_receiver_like_the_scalper(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.stream = ReceiverStream()
    w.r.startup()
    w.step()
    w.r.shutdown('TEST')
    assert w.r.stream.started == 1 and w.r.stream.stopped == 1


def test_final_sdk_boundary_scope_matches_the_validator_scope():
    from exchange.entry_scope import require_entry_action
    from exchange.sdk_transport import OfficialSDKTransport
    import inspect
    specs = {s: MarketSpec(s, 2, 20, i) for i, s in enumerate(('pas:BTC', 'pas:ETH', 'pas:SP500', 'pas:USDJPY', 'pas:EWY'))}
    client = SimpleNamespace(markets=specs, dex='pas')
    order = lambda s, reduce=False: dict(type='order', orders=[dict(a=specs[s].asset_id, r=reduce)])
    for symbol in ('pas:ETH', 'pas:SP500', 'pas:USDJPY'):
        with pytest.raises(ExchangeError, match='V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY'):
            require_entry_action(client, order(symbol))                             # every other runtime
        require_entry_action(client, order(symbol), 'CARRY')
        require_entry_action(client, order(symbol, reduce=True))                    # exits never blocked
    with pytest.raises(ExchangeError, match='CARRY_BASKET_NEW_ENTRIES_ONLY'):
        require_entry_action(client, order('pas:EWY'), 'CARRY')
    assert "getattr(self,'entry_scope',None)" in inspect.getsource(OfficialSDKTransport.check)
    assert 'transport.entry_scope = CARRY_SCOPE' in inspect.getsource(carry_basket.build_carry_basket_runtime)


def test_full_size_leg_is_the_limit_and_the_basket_fits_the_equity():
    assert basket_mandate(leg_notional='19000', starting_equity='99996').require()
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(leg_notional='19000', starting_equity='94999').require()       # 5 legs must fit equity at 1x


def test_a_stop_resize_takes_the_fresh_read_first_and_a_matching_stop_does_not(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    calls = []
    w.r.protection.before_action = lambda: calls.append(1)
    start_legs(w)
    for _ in range(30):
        w.step(31000)
    assert calls                                                                    # stops placed/re-sized
    w.r.protection.ensure_all()                                                     # settle any fill from the last cycle
    n = len(calls)
    w.r.protection.ensure_all()
    assert len(calls) == n                                                          # all stops already match
    btc = w.venue.positions['pas:BTC']
    btc[0] += D('0.001')                                                            # a fill grew the leg
    w.r.protection.ensure_all()
    assert len(calls) == n + 1 and [D(s['sz']) for s in w.stops('pas:BTC')] == [btc[0]]
    import inspect
    assert 'protection.before_action = gate' in inspect.getsource(carry_basket.build_carry_basket_runtime)


def test_no_new_entry_while_a_leg_exceeds_its_stop(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    w.step()
    w.venue.positions['pas:BTC'] = [D('0.002'), D('80000')]                        # filled, stop not yet sized
    before = len(w.events('CHILD_ATTEMPT'))
    w.r._place_children(w.r.positions())
    assert len(w.events('CHILD_ATTEMPT')) == before
    assert w.events('CHILD_SKIPPED')[-1]['code'] == 'STOP_RESIZE_PENDING:pas:BTC'


# ---------- refusals before dispatch (26 Oct 16:30 IST) ----------
def test_transport_refusal_before_http_is_a_pre_dispatch_refusal_and_never_posts():
    from exchange.sdk_transport import OfficialSDKTransport, PreDispatchRefusal
    t = OfficialSDKTransport.__new__(OfficialSDKTransport)
    posts = []
    t._sdk = SimpleNamespace(session=SimpleNamespace(post=lambda *a, **k: posts.append(1)))

    def refuse(action):
        raise ExchangeError('ENTRY_RELIABILITY_GATE_REQUIRED')
    t.check = refuse
    with pytest.raises(PreDispatchRefusal, match='ENTRY_RELIABILITY_GATE_REQUIRED'):
        t.transmit(dict(action=dict(type='order', orders=[])))
    assert posts == [] and issubclass(PreDispatchRefusal, ExchangeError)


@pytest.mark.parametrize('opt_in,state,code', [(False, 'UNKNOWN', 'TRANSMISSION_UNCERTAIN'),
                                               (True, 'REJECTED', 'PRE_DISPATCH_REFUSED')])
def test_pre_dispatch_refusal_is_rejected_only_for_the_carry_executor(live, monkeypatch, opt_in, state, code):
    from exchange.sdk_transport import PreDispatchRefusal
    from test_single_position_compliance import request

    def refuse(*a, **k):
        raise PreDispatchRefusal('ENTRY_RELIABILITY_GATE_REQUIRED')
    monkeypatch.setattr(live.transport, 'perform', refuse)
    live.executor.pre_dispatch_is_rejection = opt_in
    req = request(key='pre-dispatch-' + str(opt_in))
    order = live.executor.submit(req, permission=permission(req))
    row = live.journal.intent(req.client_order_id)
    assert order.state.value == row['state'] == state
    # UNKNOWN keeps entries paused; a clean not-sent rejection is re-derived from account truth.
    assert live.executor.entries_paused is (not opt_in)
    assert json.loads(row['outcome'])['code'] == code


def test_carry_builder_opts_in_and_counts_it_as_a_skip():
    import inspect
    from exchange.hyperliquid_execution import HyperliquidExecution
    assert HyperliquidExecution.pre_dispatch_is_rejection is False
    assert 'executor.pre_dispatch_is_rejection = True' in inspect.getsource(carry_basket.build_carry_basket_runtime)
    assert 'PRE_DISPATCH_REFUSED' in carry_basket.SKIP_CODES



# ---------- HYPE-first allocation and depth slices (26 Oct 22:35 IST) ----------
TILT = (('pas:BTC', '18000'), ('pas:ETH', '17000'), ('pas:HYPE', '35000'), ('pas:SP500', '20000'),
        ('pas:USDJPY', '5000'))


def test_tilted_legs_hype_first_within_one_x(tmp_path):
    m = basket_mandate(leg_notionals=TILT, taker_depth_bps=5).require()
    assert m.notional_for('pas:HYPE') == D('35000') and m.notional_for('pas:USDJPY') == D('5000')
    path = tmp_path / 'm.json'
    path.write_text(json.dumps(asdict(m)))
    assert CarryMandate.read(path) == m


@pytest.mark.parametrize('legs,bps', [
    (TILT[:2] + (('pas:HYPE', '50001'),) + TILT[3:], 5),                  # above the $50k leg cap
    (TILT[:4] + (('pas:USDJPY', '10001'),), 5),                            # basket above equity (1x)
    (TILT[:4], 5),                                                         # a market missing
    (TILT[:4] + (('pas:EWY', '5000'),), 5),                                # not a basket market
    (TILT, 7),                                                             # depth beyond 5 bps
])
def test_tilted_legs_reject_anything_else(legs, bps):
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(leg_notionals=legs, taker_depth_bps=bps).require()


def deep_book(symbol='pas:BTC'):
    asks = tuple(BookLevel(D(p), D(q)) for p, q in (('80000', '0.006'), ('80010', '0.05'), ('80030', '0.05'), ('80100', '5')))
    bids = tuple(BookLevel(D(p), D(q)) for p, q in (('79990', '0.006'), ('79980', '0.05'), ('79900', '5')))
    return OrderBook(symbol, 0, bids, asks)


def test_depth_child_takes_a_quarter_of_depth_within_five_bps_and_never_deeper():
    from exchange.carry_slicer import depth_within, top
    spec, book = MarketSpec('pas:BTC', 5, 40, 1), deep_book()
    p = SliceParams(taker_depth_bps=5)
    plan, _ = child('BUY', D('1'), top(book), spec, TAKER, p, book=book)
    assert plan['price'] == D('80040') and plan['tif'] == 'Ioc'                   # 80000 * 1.0005
    assert depth_within(book, 'BUY', plan['price']) == D('0.106')                 # the 80100 level is excluded
    assert plan['quantity'] == D('0.0265')                                        # 25% of 0.106
    short, _ = child('SELL', D('1'), top(book), spec, TAKER, p, book=book)
    assert short['price'] == D('79951') and short['quantity'] == D('0.0140')     # 25% of bids within 5 bps (0.056)
    touch_only, _ = child('BUY', D('1'), top(book), spec, TAKER, SliceParams(), book=book)
    assert touch_only['price'] == D('80000') and touch_only['quantity'] == D('0.0015')


def test_compliance_capacity_uses_depth_for_ioc_and_the_touch_for_post_only():
    book = deep_book()
    ioc = OrderRequest('pas:BTC', 'BUY', D('0.02'), D('80040'), tif='Ioc')
    alo = OrderRequest('pas:BTC', 'BUY', D('0.0015'), D('79990'), tif='Alo')
    assert carry_basket.carry_entry_capacity(book, ioc, D('0.25')) == D('0.0265')
    assert carry_basket.carry_entry_capacity(book, alo, D('0.25')) == D('0.0015')


def test_targets_follow_the_tilt_and_a_partly_built_leg_resumes_with_ioc(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, leg_notionals=TILT, taker_depth_bps=5)
    w.venue.positions['pas:HYPE'] = [D('10'), D('77')]                            # built under an earlier mandate
    w.r.startup()
    for _ in range(6):
        w.step(31000)
    targets = {s: D(l['target']) * D(str(SPECS[s][1])) for s, l in w.r.state['legs'].items() if l['target']}
    assert targets['pas:HYPE'] > D('34000') and targets['pas:USDJPY'] < D('5100')
    hype = [e for e in w.events('CHILD_ATTEMPT') if e['symbol'] == 'pas:HYPE']
    assert hype and hype[0]['child_kind'] == TAKER                               # no second 2 h maker window
    assert [e for e in w.events('CHILD_ATTEMPT') if e['symbol'] == 'pas:BTC'][0]['child_kind'] == MAKER


# ---------- 2x cross setting, exposure capped at 1.5x (27 Oct 01:05 IST) ----------
TILT_2X = (('pas:BTC', '25000'), ('pas:ETH', '22500'), ('pas:HYPE', '60000'), ('pas:SP500', '30000'),
           ('pas:USDJPY', '5000'))


def test_two_x_setting_allows_one_and_a_half_x_exposure_hype_first():
    m = basket_mandate(leverage=2, leg_notionals=TILT_2X, taker_depth_bps=5).require()
    assert m.notional_for('pas:HYPE') == D('60000') and sum(D(v) for _, v in TILT_2X) == D('142500')


@pytest.mark.parametrize('change', [
    dict(leverage=2, leg_notionals=TILT_2X[:2] + (('pas:HYPE', '65001'),) + TILT_2X[3:]),      # leg above $65k
    dict(leverage=2, leg_notionals=TILT_2X[:4] + (('pas:USDJPY', '62600'),)),                   # above 2x equity
    dict(leverage=2),                                                                           # 2x needs explicit legs
    dict(leverage=3, leg_notionals=TILT_2X),                                                    # never above 2x
    dict(leverage=1, leg_notionals=TILT_2X),                                                    # 1x keeps the 1x caps
])
def test_two_x_profile_rejects_anything_else(change):
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(**change).require()


def test_two_x_is_carry_profile_only():
    from test_funding_carry import mandate as funding_mandate
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        funding_mandate(leverage=2).require()
    from exchange.compliance_guard import ComplianceGuard
    assert ComplianceGuard.entry_leverage == 1


def test_compliance_entry_leverage_follows_the_guard_setting(live):
    from test_single_position_compliance import request
    req = request()
    assert evaluate(live, req).allowed                                              # fixture account is 1x
    live.executor.compliance_guard.entry_leverage = 2
    assert evaluate(live, req).code == 'INVALID_LEVERAGE'                          # a 2x guard refuses a 1x account


def test_carry_two_x_configuration_plan_targets_only_the_carry_markets():
    from exchange.pas_configuration_plan import configuration_plan
    from test_post_funding_v6 import observation
    o = observation()
    o['configuration_scope'] = 'CARRY_2X'
    plan = configuration_plan(o)
    assert plan['target_leverage'] == 2 and plan['configuration_scope'] == 'CARRY_2X'
    assert {c['symbol'] for c in plan['changes']} | set(plan['already_one_x_cross']) == set(CARRY_ENTRY_MARKETS)
    assert all(c['requested_action']['leverage'] == 2 and c['requested_action']['isCross'] is True for c in plan['changes'])
    o['configuration_scope'] = 'CARRY_3X'
    with pytest.raises(ExchangeError, match='UNKNOWN_PAS_CONFIGURATION_SCOPE'):
        configuration_plan(o)
    plain = configuration_plan(observation())
    assert 'target_leverage' not in plain and all(c['requested_action']['leverage'] == 1 for c in plain['changes'])


def test_two_x_runtime_waits_for_two_x_markets(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, leverage=2, leg_notionals=TILT_2X, taker_depth_bps=5)
    w.venue.leverage.update({s: dict(type='cross', value=1) for s in SPECS})           # still 1x on the exchange
    w.r.startup()
    for _ in range(3):
        w.step()
    assert not w.children() and {e['symbol'] for e in w.events('LEG_WAITING_FOR_1X')} == set(SPECS)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    w.step(300000)
    assert w.children() and w.r.order_errors == 0


# ---------- reallocation within 1x: HYPE $50k (27 Oct 01:35 IST) ----------
HYPE50 = (('pas:BTC', '13000'), ('pas:ETH', '12000'), ('pas:HYPE', '50000'), ('pas:SP500', '15000'),
          ('pas:USDJPY', '5000'))


def test_reallocation_trims_over_target_legs_first_then_buys_hype_and_verifies(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, leg_notionals=HYPE50, taker_depth_bps=5)
    held = {'pas:BTC': D('0.225'), 'pas:ETH': D('7.23'), 'pas:HYPE': D('454.5'), 'pas:SP500': D('2.62'),
            'pas:USDJPY': D('-31.9')}                                               # tonight's $95k basket
    for n, (s, q) in enumerate(held.items()):                                      # real (simulated) fills
        order = dict(coin=s, side='B' if q > 0 else 'A', oid=8000 + n, origSz=str(abs(q)), sz=str(abs(q)))
        w.venue._fill(order, abs(q), D(str(SPECS[s][1])), False)
    w.r.startup()
    for _ in range(600):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in SPECS):
            break
    attempts = w.events('CHILD_ATTEMPT')
    first_buy = next(i for i, e in enumerate(attempts) if e['entry'])
    trims = [e for e in attempts if e['key'].startswith('carry-trim:')]
    assert {e['symbol'] for e in trims} == {'pas:BTC', 'pas:ETH', 'pas:SP500'}
    assert all(not e['entry'] and e['tif'] == 'Ioc' for e in trims)
    assert max(i for i, e in enumerate(attempts) if e['key'].startswith('carry-trim:')) < first_buy   # trims first
    assert all(e['symbol'] == 'pas:HYPE' for e in attempts if e['entry'])
    for s in SPECS:
        leg, qty = w.leg(s), abs(w.position(s))
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert abs(qty - D(leg['target'])) * D(str(SPECS[s][1])) < 11
        assert [D(o['sz']) for o in w.stops(s)] == [qty]                           # stop sized to the new size
    assert w.r.order_errors == 0 and not w.r.state['halted']


def test_margin_refusal_before_signing_is_a_skip():
    assert {'INSUFFICIENT_MARGIN', 'MARGIN_UNAVAILABLE'} <= carry_basket.SKIP_CODES



def test_equity_is_the_unified_balance_without_adding_upnl_again(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.account.get_equity = lambda: SimpleNamespace(collateral_balance=D('99456.74'))
    w.venue.positions['pas:HYPE'] = [D('10'), D('80')]                             # uPnL is not added again
    assert w.r.equity() == D('99456.74') and w.r.equity(w.r.positions()) == D('99456.74')
    w.r.account.get_equity = lambda: SimpleNamespace(collateral_balance=D('94998'))
    from strategies.funding_carry import loss_halt
    assert loss_halt(w.r.start_equity, w.r.equity(), D('0.05'))                    # halt on the real -5%


# ---------- HYPE held as is, 2x setting, 1.5x exposure, raise-only leverage route (27 Oct 09:05 IST) ----------
def run_carry_module():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import run_carry
    return run_carry


def test_two_x_budgets_hold_hype_and_split_the_rest_equally():
    rc = run_carry_module()
    legs = dict(rc.two_x_notionals('99998.337076', {'pas:HYPE': D('647.66') * D('77.71')}))
    assert legs == {'pas:HYPE': '50400', 'pas:USDJPY': '5000', 'pas:BTC': '31500', 'pas:ETH': '31500',
                    'pas:SP500': '31500'}
    m = basket_mandate(starting_equity='99998.337076', leverage=2, leg_notionals=tuple(legs.items()),
                       taker_depth_bps=5, hold_legs=('pas:HYPE',)).require()
    assert sum(D(v) for v in legs.values()) <= D('99998.337076') * D('1.5') and m.hold_legs == ('pas:HYPE',)
    with pytest.raises(SystemExit):
        rc.two_x_notionals('99998', {})                                            # HYPE must be held


@pytest.mark.parametrize('hold', [('pas:EWY',), ('pas:HYPE', 'pas:HYPE')])
def test_hold_legs_must_be_distinct_basket_markets(hold):
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(leverage=2, leg_notionals=TILT_2X, taker_depth_bps=5, hold_legs=hold).require()
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(hold_legs=('pas:HYPE',)).require()                          # needs explicit leg budgets


def seed(w, held):
    for n, (s, q) in enumerate(held.items()):
        order = dict(coin=s, side='B' if q > 0 else 'A', oid=9000 + n, origSz=str(abs(q)), sz=str(abs(q)))
        w.venue._fill(order, abs(q), D(str(SPECS[s][1])), False)


def test_hold_leg_is_never_bought_or_trimmed_while_the_others_grow_and_verify(tmp_path, monkeypatch):
    rc = run_carry_module()
    legs = rc.two_x_notionals('100000', {'pas:HYPE': D('647.66') * 77})
    w = World(tmp_path, monkeypatch, leverage=2, leg_notionals=legs, taker_depth_bps=5, hold_legs=('pas:HYPE',))
    held = {'pas:BTC': D('0.16289'), 'pas:ETH': D('5.2127'), 'pas:HYPE': D('647.66'), 'pas:SP500': D('1.958'),
            'pas:USDJPY': D('-31.77')}                                              # this morning's basket
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})        # after the raise
    seed(w, held)
    w.r.startup()
    for _ in range(900):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in SPECS):
            break
    attempts = w.events('CHILD_ATTEMPT')
    assert not [e for e in attempts if e['symbol'] == 'pas:HYPE']                  # no buy, no trim
    assert not [e for e in attempts if e['key'].startswith('carry-trim:')]
    assert w.position('pas:HYPE') == D('647.66') and w.leg('pas:HYPE')['target'] == '647.66'
    for s in SPECS:
        leg, qty = w.leg(s), abs(w.position(s))
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [qty]
    for s in ('pas:BTC', 'pas:ETH', 'pas:SP500'):
        assert abs(w.position(s)) * D(str(SPECS[s][1])) > D('31000')               # grown to ~$31.7k
    assert w.r.order_errors == 0 and not w.r.state['halted']


def test_a_flat_hold_leg_closes_instead_of_being_bought(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, leverage=2, leg_notionals=TILT_2X, taker_depth_bps=5, hold_legs=('pas:HYPE',))
    w.r.startup()
    for _ in range(5):
        w.step(31000)
    assert w.leg('pas:HYPE')['mode'] == 'CLOSED' and w.leg('pas:HYPE')['closed_reason'] == 'HOLD_LEG_FLAT'
    assert not w.children('pas:HYPE') and w.position('pas:HYPE') == 0 and w.events('HOLD_LEG_FLAT')


# ---------- remaining balance in, ranked HYPE > SP500 > BTC > ETH > USDJPY, 1.85x (29 Oct 13:45 IST) ----------
HELD_29OCT = {'pas:BTC': D('31665.6656'), 'pas:ETH': D('31632.9717'), 'pas:HYPE': D('51191.0464'),
              'pas:SP500': D('31672.482'), 'pas:USDJPY': D('4994.9982')}


def test_ranked_budgets_top_up_every_leg_in_the_users_order():
    rc = run_carry_module()
    legs = {s: D(v) for s, v in rc.ranked_notionals('99998.337076', HELD_29OCT)}
    assert legs == {'pas:BTC': D('38400'), 'pas:ETH': D('36100'), 'pas:HYPE': D('62400'), 'pas:SP500': D('40600'),
                    'pas:USDJPY': D('7200')}
    assert all(legs[s] > HELD_29OCT[s] for s in legs)                             # nothing is sold or trimmed
    assert sum(legs.values()) <= D('99998.337076') * D('1.85')
    basket_mandate(starting_equity='99998.337076', leverage=2, leg_notionals=tuple((s, str(v)) for s, v in legs.items()),
                   taker_depth_bps=5).require()


@pytest.mark.parametrize('held', [
    dict(HELD_29OCT, **{'pas:ETH': D('39000')}),                                  # ETH would overtake BTC
    {s: v for s, v in HELD_29OCT.items() if s != 'pas:USDJPY'},                    # a leg is missing
    {s: v * 2 for s, v in HELD_29OCT.items()},                                     # already above 1.85x: would sell
])
def test_ranked_budgets_refuse_a_sale_or_a_broken_order(held):
    with pytest.raises(SystemExit):
        run_carry_module().ranked_notionals('99998.337076', held)


def test_ranked_top_up_buys_every_leg_hype_included_and_never_trims(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.3959'), 'pas:ETH': D('13.6614'), 'pas:HYPE': D('647.66'), 'pas:SP500': D('4.11'),
            'pas:USDJPY': D('-31.66')}                                              # the 29 Oct basket
    legs = rc.ranked_notionals('100000', {s: abs(q) * D(str(SPECS[s][1])) for s, q in held.items()})
    w = World(tmp_path, monkeypatch, leverage=2, leg_notionals=legs, taker_depth_bps=5)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(1500):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in SPECS):
            break
    attempts = w.events('CHILD_ATTEMPT')
    assert not [e for e in attempts if e['key'].startswith(('carry-trim:', 'carry-out:'))]
    for s, q in held.items():
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert abs(w.position(s)) > abs(q)                                         # every leg grew, HYPE too
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]
    values = [abs(w.position(s)) * D(str(SPECS[s][1])) for s, _ in rc.RANKED_SHARES]
    assert all(a > b for a, b in zip(values, values[1:]))                          # HYPE > SP500 > BTC > ETH > USDJPY
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- SP500 and USDJPY squared off, HYPE grows to 1.5x the current equity (31 Oct 22:40 IST) ----------
HELD_31OCT = {'pas:BTC': D('37223.30'), 'pas:ETH': D('35092.02'), 'pas:HYPE': D('69105.61'), 'pas:SP500': D('40008.82'),
              'pas:USDJPY': D('7166.29')}
CLOSE_31OCT = (('pas:BTC', '37300'), ('pas:ETH', '35100'), ('pas:HYPE', '85100'))
CLOSE_KW = dict(starting_equity='99998.337076', leverage=2, taker_depth_bps=5, hold_legs=('pas:BTC', 'pas:ETH'),
                close_legs=('pas:SP500', 'pas:USDJPY'))


def test_close_budgets_hold_btc_eth_and_give_hype_the_rest_of_one_and_a_half_x():
    legs = run_carry_module().close_notionals('105045.342709', HELD_31OCT)
    assert legs == CLOSE_31OCT                                                     # no budget for SP500/USDJPY
    assert sum(D(v) for _, v in legs) <= D('105045.342709') * D('1.5')
    assert basket_mandate(leg_notionals=legs, **CLOSE_KW).require().close_legs == ('pas:SP500', 'pas:USDJPY')


@pytest.mark.parametrize('held', [
    {s: v for s, v in HELD_31OCT.items() if s != 'pas:ETH'},                       # a hold leg is missing
    dict(HELD_31OCT, **{'pas:HYPE': D('90000')}),                                  # HYPE budget would sell
])
def test_close_budgets_refuse_a_missing_leg_or_a_hype_sale(held):
    with pytest.raises(SystemExit):
        run_carry_module().close_notionals('105045.342709', held)


@pytest.mark.parametrize('change', [
    dict(leg_notionals=CLOSE_31OCT + (('pas:SP500', '1000'),)),                    # a close leg with a budget
    dict(hold_legs=('pas:BTC', 'pas:ETH', 'pas:SP500')),                           # held and closed at once
    dict(close_legs=('pas:SP500', 'pas:SP500', 'pas:USDJPY')),
    dict(close_legs=('pas:SP500', 'pas:DOGE')),
    dict(leverage=1),
    dict(leg_notionals=(('pas:BTC', '10000'), ('pas:ETH', '10000'), ('pas:HYPE', '170100'))),  # leg above $170k
    dict(leg_notionals=(('pas:BTC', '70000'), ('pas:ETH', '70000'), ('pas:HYPE', '70000'))),   # above 2x
    dict(leg_notionals=(), close_legs=('pas:BTC', 'pas:ETH', 'pas:HYPE', 'pas:SP500', 'pas:USDJPY'), hold_legs=()),
])
def test_close_legs_reject_anything_else(change):
    with pytest.raises(ExchangeError):
        basket_mandate(**{**CLOSE_KW, 'leg_notionals': CLOSE_31OCT, **change}).require()


def test_without_close_legs_the_65k_leg_cap_still_holds():
    with pytest.raises(ExchangeError):
        basket_mandate(leverage=2, taker_depth_bps=5, leg_notionals=TILT_2X[:2] + (('pas:HYPE', '65100'),)
                       + TILT_2X[3:]).require()


def test_close_legs_sell_to_flat_with_touch_ioc_then_hype_grows_and_btc_eth_stay(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.48009'), 'pas:ETH': D('15.602'), 'pas:HYPE': D('789.12'), 'pas:SP500': D('5.278'),
            'pas:USDJPY': D('-45.59')}                                              # the 31 Oct basket
    marked = {s: abs(q) * D(str(SPECS[s][1])) for s, q in held.items()}
    equity = D('105045.342709')
    legs = rc.close_notionals(equity, marked)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, **CLOSE_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(1500):
        w.step(31000)
        if (all(w.leg(s)['mode'] == 'HOLD' for s in ('pas:BTC', 'pas:ETH', 'pas:HYPE'))
                and all(w.leg(s)['mode'] == 'CLOSED' for s in rc.CLOSE_LEGS)):
            break
    attempts = w.events('CHILD_ATTEMPT')
    closes = [e for e in attempts if e['symbol'] in rc.CLOSE_LEGS]
    buys = [i for i, e in enumerate(attempts) if e['entry']]
    assert closes and all(e['key'].startswith('carry-out:') and not e['entry'] and e['tif'] == 'Ioc' for e in closes)
    assert buys and all(attempts[i]['symbol'] == 'pas:HYPE' for i in buys)          # only HYPE is bought
    assert max(i for i, e in enumerate(attempts) if e['symbol'] in rc.CLOSE_LEGS) < min(buys)   # closes first
    assert not [e for e in attempts if e['symbol'] in rc.CLOSE_HOLD_LEGS]          # BTC and ETH untouched
    assert not [e for e in attempts if e['key'].startswith('carry-trim:')]
    for s in rc.CLOSE_LEGS:
        leg = w.leg(s)
        assert w.position(s) == 0 and leg['closed_reason'] == 'CARRY_REALLOCATION_CLOSE'
        assert not w.stops(s) and not w.children(s)                                # its stop is gone too
    for s in ('pas:BTC', 'pas:ETH', 'pas:HYPE'):
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]
    assert w.position('pas:BTC') == held['pas:BTC'] and w.position('pas:ETH') == held['pas:ETH']
    assert w.position('pas:HYPE') > held['pas:HYPE']
    exposure = sum(abs(w.position(s)) * D(str(SPECS[s][1])) for s in SPECS)
    assert exposure <= equity * D('1.5') and exposure > equity * D('1.49')
    assert w.r.order_errors == 0 and not w.r.state['halted']


def test_a_flat_close_leg_closes_at_startup_and_is_never_bought(tmp_path, monkeypatch):
    held = {'pas:BTC': D('0.48009'), 'pas:ETH': D('15.602'), 'pas:HYPE': D('789.12')}
    w = World(tmp_path, monkeypatch, leg_notionals=CLOSE_31OCT, **CLOSE_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(5):
        w.step(31000)
    for s in ('pas:SP500', 'pas:USDJPY'):
        assert w.leg(s)['mode'] == 'CLOSED' and w.leg(s)['closed_reason'] == 'CLOSE_LEG_FLAT'
        assert w.position(s) == 0 and not w.children(s)
    assert not [e for e in w.events('CHILD_ATTEMPT') if e['symbol'] in ('pas:SP500', 'pas:USDJPY')]


class RaiseAccount:
    """Fake account for the raise-only route: the basket, its stops, journal rows and exchange order states."""
    team_address = '0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C'

    def __init__(self):
        self.positions = {'pas:BTC': D('0.16289'), 'pas:HYPE': D('647.66'), 'pas:USDJPY': D('-31.77')}
        self.orders = [dict(coin=s, cloid=f'0xs{s}', sz=str(abs(q)), side='A' if q > 0 else 'B', isTrigger=True,
                            reduceOnly=True, triggerPx='1') for s, q in self.positions.items()]
        self.status = {'0xchild': {'status': 'order', 'order': {'status': 'filled'}}}
        self.leverage = {s: dict(type='cross', value=1) for s in CARRY_ENTRY_MARKETS}

    def get_positions(self):
        return {s: Position(s, q, D('1'), D(0), D(0), None) for s, q in self.positions.items()}

    def get_frontend_open_orders(self):
        return self.orders

    def get_open_orders(self):
        return list(self.orders)

    def _query(self, kind, **k):
        if kind == 'orderStatus':
            return self.status.get(k['oid'], {'status': 'unknownOid'})
        return dict(coin=k['coin'], user=self.team_address, leverage=self.leverage[k['coin']])


def raise_world(monkeypatch, account):
    from exchange import carry_leverage_raise, scored_session, terminal_evidence
    rows = [dict(journal='pas', cloid=o['cloid'], state='OPEN', intent_key=f"protection:{o['coin']}:7")
            for o in account.orders]
    rows.append(dict(journal='pas', cloid='0xchild', state='PARTIALLY_FILLED', intent_key='carry-in:pas:ETH:abc:8'))
    local = dict(status='BLOCKED_UNRESOLVED_INTENT', unresolved=rows)
    monkeypatch.setattr(terminal_evidence, 'local_execution_state', lambda root: local)
    monkeypatch.setattr(scored_session, 'require_no_par_exposure', lambda client: None)
    monkeypatch.setattr('exchange.pas_funding.read_funding', lambda c, a, provenance: dict(
        status='USDP_POSITIVE_VERIFIED', account_mode='unifiedAccount', balance='99275'))
    specs = {s: MarketSpec(s, 2, 20, i) for i, s in enumerate(sorted(CARRY_ENTRY_MARKETS))}
    client = SimpleNamespace(market=specs.__getitem__, clock_ms=lambda: 1000)
    return carry_leverage_raise, client, local


def test_raise_plan_accepts_the_open_basket_with_its_stops_and_raises_only_one_to_two(monkeypatch, tmp_path):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    account.leverage['pas:SP500'] = dict(type='cross', value=2)                    # already raised: skipped
    plan = mod.raise_plan(tmp_path, client, account, provenance='x')
    assert [c['symbol'] for c in plan['changes']] == ['pas:BTC', 'pas:ETH', 'pas:EWJ', 'pas:HYPE', 'pas:USDJPY']
    assert all(c['requested_action'] == dict(type='updateLeverage', asset=client.market(c['symbol']).asset_id,
                                             isCross=True, leverage=2) for c in plan['changes'])
    assert plan['already_two_x_cross'] == ['pas:SP500'] and plan['configuration_scope'] == 'CARRY_2X'
    assert plan['open_basket']['settled_local_rows'] == ['carry-in:pas:ETH:abc:8']
    assert plan['orders_permitted'] is False and plan['transfers_allowed'] is False
    monkeypatch.setattr(mod.time, 'time_ns', lambda: (plan['observed_ms'] + 1000) * 1000000)
    monkeypatch.setattr('exchange.paper_operations.active_source_hash', lambda root: plan['source_hash'])
    assert mod.require_plan(tmp_path, plan, plan['observed_ms'] + 1000) == plan
    with pytest.raises(ExchangeError, match='FRESH_EXACT_CARRY_LEVERAGE_PLAN_REQUIRED'):
        mod.require_plan(tmp_path, plan, plan['observed_ms'] + 300001)            # stale
    with pytest.raises(ExchangeError, match='FRESH_EXACT_CARRY_LEVERAGE_PLAN_REQUIRED'):
        mod.require_plan(tmp_path, dict(plan, target_leverage=3), plan['observed_ms'])


@pytest.mark.parametrize('before', [dict(type='cross', value=3), dict(type='isolated', value=1)])
def test_raise_route_never_lowers_or_switches_margin_mode(monkeypatch, tmp_path, before):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    account.leverage['pas:ETH'] = before
    with pytest.raises(ExchangeError, match='ONLY_A_RAISE_FROM_1X_CROSS'):
        mod.raise_plan(tmp_path, client, account, provenance='x')


def _foreign(a, local):
    a.positions['pas:EWY'] = D('1')

def _wrong_side(a, local):
    a.positions['pas:USDJPY'] = D('31.77')

def _resting_child(a, local):
    a.orders.append(dict(coin='pas:BTC', cloid='0xchild', sz='0.01', side='B', isTrigger=False, reduceOnly=False))

def _not_reduce_only(a, local):
    a.orders[0]['reduceOnly'] = False

def _partial_stop(a, local):
    a.orders[0]['sz'] = '0.1'

def _unjournaled_stop(a, local):
    a.orders[0]['cloid'] = '0xother'

def _child_still_open(a, local):
    a.status['0xchild'] = {'status': 'order', 'order': {'status': 'open'}}

def _unknown_row(a, local):
    local['unresolved'].append(dict(journal='pas', cloid='0xu', state='UNKNOWN', intent_key='carry-in:pas:BTC:a:1'))

def _configuration_unknown(a, local):
    local['unresolved'].append(dict(journal='pas-configuration', management_id=1, state='UNKNOWN'))

def _journal_unreadable(a, local):
    local['status'] = 'UNKNOWN_REQUIRES_REVIEW'


@pytest.mark.parametrize('fault,code', [
    (_foreign, 'CARRY_BASKET_POSITIONS_ONLY'), (_wrong_side, 'CARRY_BASKET_POSITIONS_ONLY'),
    (_resting_child, 'ONLY_FULL_SIZE_REDUCE_ONLY_BASKET_STOPS_MAY_REST'),
    (_not_reduce_only, 'ONLY_FULL_SIZE_REDUCE_ONLY_BASKET_STOPS_MAY_REST'),
    (_partial_stop, 'ONLY_FULL_SIZE_REDUCE_ONLY_BASKET_STOPS_MAY_REST'),
    (_unjournaled_stop, 'ONLY_FULL_SIZE_REDUCE_ONLY_BASKET_STOPS_MAY_REST'),
    (_child_still_open, 'UNRESOLVED_LOCAL_ACTION_BLOCKS_CONFIGURATION'),
    (_unknown_row, 'UNRESOLVED_LOCAL_ACTION_BLOCKS_CONFIGURATION'),
    (_configuration_unknown, 'UNRESOLVED_LOCAL_ACTION_BLOCKS_CONFIGURATION'),
    (_journal_unreadable, 'LOCAL_JOURNAL_STATE_REQUIRED'),
])
def test_raise_route_refuses_anything_but_the_basket_and_its_own_stops(monkeypatch, tmp_path, fault, code):
    account = RaiseAccount()
    mod, client, local = raise_world(monkeypatch, account)
    fault(account, local)
    with pytest.raises(ExchangeError, match=code):
        mod.basket_evidence(tmp_path, client, account)


def test_raise_route_still_requires_no_par_exposure(monkeypatch, tmp_path):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    from exchange import scored_session

    def occupied(client):
        raise ExchangeError('OTHER_DEX_EXPOSURE_OR_ORDERS_BLOCK_PAS_SIGNING')
    monkeypatch.setattr(scored_session, 'require_no_par_exposure', occupied)
    with pytest.raises(ExchangeError, match='OTHER_DEX_EXPOSURE'):
        mod.basket_evidence(tmp_path, client, account)


def test_raise_route_accepts_only_its_own_in_flight_action(monkeypatch, tmp_path):
    """27 Oct 10:37 IST: the route's own action is journaled UNKNOWN just before signing; it must not block itself."""
    account = RaiseAccount()
    mod, client, local = raise_world(monkeypatch, account)
    local['unresolved'].append(dict(journal='pas-configuration', management_id=1, state='UNKNOWN'))
    assert mod.basket_evidence(tmp_path, client, account, owned_actions=(1,))['positions']
    with pytest.raises(ExchangeError, match='UNRESOLVED_LOCAL_ACTION_BLOCKS_CONFIGURATION'):
        mod.basket_evidence(tmp_path, client, account, owned_actions=(2,))


def test_a_refusal_before_signing_is_a_pre_dispatch_refusal(live):
    """27 Oct 12:27 IST: the sink check before the nonce lease raised a plain error, journaled UNKNOWN."""
    from exchange.sdk_transport import PreDispatchRefusal, build_exchange
    from test_exact_full_close_v8_6 import runtime_mapping
    runtime_mapping(live)
    sdk = live.transport._sdk
    assert type(sdk).__name__ == 'GuardedExchange'

    def refuse(action):
        raise ExchangeError('SIGNING_READINESS_REVOKED')
    live.transport.check = refuse
    leased = []
    live.nonces.next = lambda: leased.append(1)
    with pytest.raises(PreDispatchRefusal, match='SIGNING_READINESS_REVOKED'):
        sdk._post_action(dict(type='order', orders=[]), None, 0)
    assert leased == []                                                            # no nonce, nothing signed


# ---------- $10k more of BTC/ETH moved into HYPE, exposure kept at 1.5x (1 Nov 22:30 IST) ----------
HELD_1NOV = {'pas:BTC': D('24142.32'), 'pas:ETH': D('22825.00'), 'pas:HYPE': D('111592.31')}
MOVE_KW = dict(starting_equity='99998.337076', leverage=2, taker_depth_bps=5, close_legs=('pas:SP500', 'pas:USDJPY'))


def test_move_budgets_take_at_least_10k_from_btc_eth_in_proportion_and_give_it_to_hype():
    legs = run_carry_module().move_notionals('105906.51', HELD_1NOV)
    assert legs == (('pas:BTC', '19000'), ('pas:ETH', '17900'), ('pas:HYPE', '121600'))
    budget = dict(legs)
    sold = HELD_1NOV['pas:BTC'] + HELD_1NOV['pas:ETH'] - D(budget['pas:BTC']) - D(budget['pas:ETH'])
    assert D('10000') <= sold <= D('10200')                                        # at least $10k, at most $10.2k
    assert D(budget['pas:HYPE']) - HELD_1NOV['pas:HYPE'] <= sold                   # HYPE gets only what was sold
    assert sum(D(v) for _, v in legs) <= D('105906.51') * D('1.5')                  # exposure stays 1.5x
    assert basket_mandate(leg_notionals=legs, **MOVE_KW).require().hold_legs == ()


def test_move_budgets_never_exceed_one_and_a_half_x_the_current_equity():
    legs = dict(run_carry_module().move_notionals('100000', HELD_1NOV))             # equity fell: the cap binds
    assert sum(D(v) for v in legs.values()) <= D('150000')
    assert legs['pas:BTC'] == '19000' and legs['pas:ETH'] == '17900'


@pytest.mark.parametrize('held', [
    {s: v for s, v in HELD_1NOV.items() if s != 'pas:ETH'},                         # a trimmed leg is missing
    {s: v for s, v in HELD_1NOV.items() if s != 'pas:HYPE'},                        # HYPE is missing
    dict(HELD_1NOV, **{'pas:BTC': D('5000'), 'pas:ETH': D('5000')}),                # less than $10k to move
    dict(HELD_1NOV, **{'pas:HYPE': D('160000')}),                                   # HYPE budget would sell
])
def test_move_budgets_refuse_a_missing_leg_too_little_to_move_or_a_hype_sale(held):
    with pytest.raises(SystemExit):
        run_carry_module().move_notionals('105906.51', held)


def test_move_trims_btc_eth_first_with_reduce_only_ioc_then_buys_only_hype(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.30939'), 'pas:ETH': D('10.0626'), 'pas:HYPE': D('1266.54')}  # the 1 Nov 22:30 basket
    marked = {s: q * D(str(SPECS[s][1])) for s, q in held.items()}
    equity = D('105906.51')
    legs = rc.move_notionals(equity, marked)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, **MOVE_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(1500):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in held):
            break
    attempts = w.events('CHILD_ATTEMPT')
    trims = [e for e in attempts if e['key'].startswith('carry-trim:')]
    buys = [i for i, e in enumerate(attempts) if e['entry']]
    assert {e['symbol'] for e in trims} == {'pas:BTC', 'pas:ETH'}
    assert all(not e['entry'] and e['tif'] == 'Ioc' for e in trims)
    assert buys and all(attempts[i]['symbol'] == 'pas:HYPE' for i in buys)          # only HYPE is bought
    assert max(i for i, e in enumerate(attempts) if e['key'].startswith('carry-trim:')) < min(buys)   # trims first
    assert not [e for e in attempts if e['symbol'] in rc.CLOSE_LEGS]                # SP500/USDJPY stay closed
    for s in rc.CLOSE_LEGS:
        assert w.leg(s)['mode'] == 'CLOSED' and w.position(s) == 0
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in held}
    sold = sum(marked[s] - value[s] for s in rc.MOVE_FROM_LEGS)
    assert D('10000') <= sold <= D('10300')                                        # at least $10k, never a sweep
    assert value['pas:HYPE'] - marked['pas:HYPE'] <= sold + 11                      # HYPE grew by what was sold
    assert value['pas:HYPE'] - marked['pas:HYPE'] > sold - 200
    for s in held:
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]            # stop sized to the new size
    assert sum(value.values()) <= equity * D('1.5')                                 # exposure stays 1.5x
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- exposure raised to 1.85x the starting equity, BTC/ETH held, HYPE gets the room (1 Nov 23:10 IST) ----------
HELD_RAISE = {'pas:BTC': D('18998.39'), 'pas:ETH': D('17900.56'), 'pas:HYPE': D('112018.75')}
RAISE_KW = dict(MOVE_KW, hold_legs=('pas:BTC', 'pas:ETH'))


def test_raise_budgets_hold_btc_eth_and_give_hype_the_room_up_to_1_85x_the_starting_equity():
    legs = run_carry_module().raise_notionals('99998.337076', HELD_RAISE)
    assert legs == (('pas:BTC', '19000'), ('pas:ETH', '18000'), ('pas:HYPE', '147900'))
    assert sum(D(v) for _, v in legs) <= D('99998.337076') * D('1.85')              # never above the 1.85x cap
    m = basket_mandate(leg_notionals=legs, **RAISE_KW).require()
    assert m.hold_legs == ('pas:BTC', 'pas:ETH') and m.close_legs == ('pas:SP500', 'pas:USDJPY')


@pytest.mark.parametrize('held', [
    {s: v for s, v in HELD_RAISE.items() if s != 'pas:BTC'},                        # a hold leg is missing
    {s: v for s, v in HELD_RAISE.items() if s != 'pas:HYPE'},                       # HYPE is missing
    dict(HELD_RAISE, **{'pas:HYPE': D('150000')}),                                  # HYPE budget would sell
])
def test_raise_budgets_refuse_a_missing_leg_or_a_hype_sale(held):
    with pytest.raises(SystemExit):
        run_carry_module().raise_notionals('99998.337076', held)


def test_raise_budgets_above_the_2x_close_leg_cap_are_refused_by_the_mandate():
    with pytest.raises(ExchangeError):
        basket_mandate(leg_notionals=(('pas:BTC', '19000'), ('pas:ETH', '18000'), ('pas:HYPE', '163000')),
                       **RAISE_KW).require()


def test_raise_buys_only_hype_and_leaves_btc_eth_untouched(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.24336'), 'pas:ETH': D('7.8955'), 'pas:HYPE': D('1266.54')}  # the 1 Nov 23:00 basket
    marked = {s: q * D(str(SPECS[s][1])) for s, q in held.items()}
    legs = rc.raise_notionals('99998.337076', marked)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, **RAISE_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(3000):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in held):
            break
    attempts = w.events('CHILD_ATTEMPT')
    assert attempts and all(e['symbol'] == 'pas:HYPE' and e['entry'] for e in attempts)   # only HYPE is bought
    assert all(e['tif'] == 'Ioc' for e in attempts)
    for s in rc.MOVE_FROM_LEGS:
        assert w.position(s) == held[s]                                             # BTC and ETH exactly as held
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in held}
    assert value['pas:HYPE'] > D(dict(legs)['pas:HYPE']) - 200
    assert sum(value.values()) <= D('99998.337076') * D('1.85')                    # exposure stays within 1.85x
    for s in held:
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- exposure raised to 2x the starting equity, all three legs scaled up in proportion (2 Nov 11:40 IST) ----------
HELD_2NOV = {'pas:BTC': D('19046.15'), 'pas:ETH': D('18062.53'), 'pas:HYPE': D('146794.97')}   # marked 2 Nov 11:00 IST


def test_scale_budgets_raise_btc_eth_hype_in_proportion_to_2x_the_starting_equity():
    legs = dict(run_carry_module().scale_notionals('99998.337076', HELD_2NOV))
    assert legs == {'pas:BTC': '20700', 'pas:ETH': '19600', 'pas:HYPE': '159600'}
    total = sum(D(v) for v in legs.values())
    assert D('99998.337076') * 2 - 300 < total <= D('99998.337076') * 2           # 2x, never above it
    assert all(D(legs[s]) > HELD_2NOV[s] for s in HELD_2NOV)                      # every leg grows, nothing is sold
    share = lambda d: {s: D(v) / sum(D(x) for x in d.values()) for s, v in d.items()}
    assert all(abs(share(legs)[s] - share(HELD_2NOV)[s]) < D('0.001') for s in HELD_2NOV)   # same mix
    m = basket_mandate(leg_notionals=tuple(legs.items()), **MOVE_KW).require()
    assert m.hold_legs == () and m.close_legs == ('pas:SP500', 'pas:USDJPY')


@pytest.mark.parametrize('held', [
    {s: v for s, v in HELD_2NOV.items() if s != 'pas:ETH'},                         # a leg is missing
    dict(HELD_2NOV, **{'pas:SP500': D('1000')}),                                    # a closed leg is held
    {s: v * 2 for s, v in HELD_2NOV.items()},                                       # already above 2x: would sell
])
def test_scale_budgets_refuse_a_missing_or_foreign_leg_or_a_sale(held):
    with pytest.raises(SystemExit):
        run_carry_module().scale_notionals('99998.337076', held)


def test_scale_budgets_above_2x_the_starting_equity_are_refused_by_the_mandate():
    with pytest.raises(ExchangeError):
        basket_mandate(leg_notionals=(('pas:BTC', '20800'), ('pas:ETH', '19700'), ('pas:HYPE', '159600')),
                       **MOVE_KW).require()


def test_scale_buys_all_three_legs_with_ioc_children_up_to_2x(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.24336'), 'pas:ETH': D('7.8955'), 'pas:HYPE': D('1676.39')}  # the 2 Nov 11:00 basket
    marked = {s: q * D(str(SPECS[s][1])) for s, q in held.items()}
    legs = rc.scale_notionals('99998.337076', marked)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, **MOVE_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(4000):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in held):
            break
    attempts = w.events('CHILD_ATTEMPT')
    assert {e['symbol'] for e in attempts} == set(held)                             # all three legs are bought
    assert all(e['entry'] and e['tif'] == 'Ioc' for e in attempts)                  # buys only, never a sale
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in held}
    for s in held:
        assert w.position(s) > held[s]
        assert value[s] > D(dict(legs)[s]) - 200
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]            # stop sized to the new size
    assert sum(value.values()) <= D('99998.337076') * 2                             # exposure stays within 2x
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- $50k of HYPE moved into SP500, BTC/ETH held, USDJPY closed, exposure kept at 2x (2 Nov 20:50 IST) ----------
HELD_SHIFT = {'pas:BTC': D('20634.73'), 'pas:ETH': D('19767.57'), 'pas:HYPE': D('158259.52')}   # marked 2 Nov 20:55 IST
SHIFT_KW = dict(starting_equity='99998.337076', leverage=2, taker_depth_bps=5, hold_legs=('pas:BTC', 'pas:ETH'),
                close_legs=('pas:USDJPY',))


def test_shift_budgets_take_at_most_50k_from_hype_into_sp500_and_hold_btc_eth():
    legs = run_carry_module().shift_notionals('99998.337076', HELD_SHIFT)
    assert legs == (('pas:BTC', '20700'), ('pas:ETH', '19800'), ('pas:HYPE', '108300'), ('pas:SP500', '49900'))
    budget = dict(legs)
    sold = HELD_SHIFT['pas:HYPE'] - D(budget['pas:HYPE'])
    assert D('49900') < sold <= D('50000')                                          # about $50k, never more
    assert D(budget['pas:SP500']) <= sold                                           # SP500 gets only what was sold
    assert sum(D(v) for v in budget.values()) <= D('99998.337076') * 2              # exposure stays within 2x
    m = basket_mandate(leg_notionals=legs, **SHIFT_KW).require()
    assert m.hold_legs == ('pas:BTC', 'pas:ETH') and m.close_legs == ('pas:USDJPY',)


def test_shift_budgets_keep_the_exposure_within_2x_when_hype_has_risen():
    held = dict(HELD_SHIFT, **{'pas:HYPE': D('165000')})                            # HYPE up ~4%: the 2x cap binds
    legs = dict(run_carry_module().shift_notionals('99998.337076', held))
    assert legs == {'pas:BTC': '20700', 'pas:ETH': '19800', 'pas:HYPE': '115000', 'pas:SP500': '44400'}
    assert sum(D(v) for v in legs.values()) <= D('99998.337076') * 2


@pytest.mark.parametrize('held', [
    {s: v for s, v in HELD_SHIFT.items() if s != 'pas:ETH'},                        # a hold leg is missing
    {s: v for s, v in HELD_SHIFT.items() if s != 'pas:HYPE'},                       # HYPE is missing
    dict(HELD_SHIFT, **{'pas:SP500': D('1000')}),                                   # SP500 is not flat
    dict(HELD_SHIFT, **{'pas:USDJPY': D('1000')}),                                  # a closed leg is held
    dict(HELD_SHIFT, **{'pas:HYPE': D('45000')}),                                   # less HYPE than the move
    dict(HELD_SHIFT, **{'pas:HYPE': D('175000')}),                                  # the 2x cap leaves SP500 < $40k
])
def test_shift_budgets_refuse_a_missing_or_foreign_leg_or_too_little_room(held):
    with pytest.raises(SystemExit):
        run_carry_module().shift_notionals('99998.337076', held)


def test_shift_budgets_above_2x_the_starting_equity_are_refused_by_the_mandate():
    with pytest.raises(ExchangeError):
        basket_mandate(leg_notionals=(('pas:BTC', '20700'), ('pas:ETH', '19800'), ('pas:HYPE', '108300'),
                                      ('pas:SP500', '51300')), **SHIFT_KW).require()


def test_shift_trims_hype_first_with_reduce_only_ioc_then_buys_only_sp500(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.26485'), 'pas:ETH': D('8.6261'), 'pas:HYPE': D('1834.17')}  # the 2 Nov 20:50 basket
    marked = {s: q * D(str(SPECS[s][1])) for s, q in held.items()}
    legs = rc.shift_notionals('99998.337076', marked)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, **SHIFT_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    built = (*held, 'pas:SP500')
    for _ in range(4000):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in built):
            break
    attempts = w.events('CHILD_ATTEMPT')
    trims = [i for i, e in enumerate(attempts) if e['key'].startswith('carry-trim:')]
    buys = [i for i, e in enumerate(attempts) if e['entry']]
    assert trims and {attempts[i]['symbol'] for i in trims} == {'pas:HYPE'}         # only HYPE is trimmed
    assert all(not attempts[i]['entry'] and attempts[i]['tif'] == 'Ioc' for i in trims)
    assert buys and {attempts[i]['symbol'] for i in buys} == {'pas:SP500'}          # only SP500 is bought
    assert max(trims) < min(buys)                                                   # every trim before any buy
    for s in rc.SHIFT_HOLD_LEGS:
        assert w.position(s) == held[s]                                             # BTC and ETH exactly as held
    assert w.leg('pas:USDJPY')['mode'] == 'CLOSED' and w.position('pas:USDJPY') == 0
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in SPECS}
    sold = marked['pas:HYPE'] - value['pas:HYPE']
    assert D('49800') < sold <= D('50000')                                          # about $50k, never a sweep
    assert D(dict(legs)['pas:SP500']) - 200 < value['pas:SP500'] <= sold            # SP500 bought with what was sold
    assert sum(value.values()) <= D('99998.337076') * 2                             # exposure stays within 2x
    for s in built:
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]            # one full-size stop per leg
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- $50k more of HYPE into SP500 + USDJPY (short), EWJ's $25k to follow (2 Nov 22:05 IST) ----------
HELD_DIV = {'pas:BTC': D('20634.73'), 'pas:ETH': D('19767.57'), 'pas:HYPE': D('107399.38')}   # marked 2 Nov 22:00 IST
PRIOR_DIV = (('pas:BTC', '20600'), ('pas:ETH', '19700'), ('pas:HYPE', '107400'), ('pas:SP500', '49900'))
DIV_KW = dict(starting_equity='99998.337076', leverage=2, taker_depth_bps=5, hold_legs=('pas:BTC', 'pas:ETH'))


@pytest.mark.parametrize('sp500_held', [None, D('3000')])                      # SP500 flat or partly built
def test_diversify_budgets_take_at_most_50k_more_from_hype_into_sp500_and_usdjpy(sp500_held):
    held = dict(HELD_DIV, **({'pas:SP500': sp500_held} if sp500_held else {}))
    legs = run_carry_module().diversify_notionals(held, PRIOR_DIV)
    assert legs == (('pas:BTC', '20700'), ('pas:ETH', '19800'), ('pas:HYPE', '57400'), ('pas:SP500', '59900'),
                    ('pas:USDJPY', '15000'))
    sold = HELD_DIV['pas:HYPE'] - D(dict(legs)['pas:HYPE'])
    assert D('49900') < sold <= D('50000')                                          # about $50k, never more
    assert D('10000') + D('15000') + D('25000') <= sold + 100                       # SP500 + USDJPY + EWJ's share
    assert sum(D(v) for _, v in legs) <= D('99998.337076') * D('1.85')              # below the no-close-leg cap
    m = basket_mandate(leg_notionals=legs, **DIV_KW).require()
    assert m.hold_legs == ('pas:BTC', 'pas:ETH') and m.close_legs == () and m.basket['pas:USDJPY'] == 'SHORT'


@pytest.mark.parametrize('held', [
    {s: v for s, v in HELD_DIV.items() if s != 'pas:ETH'},                          # a hold leg is missing
    {s: v for s, v in HELD_DIV.items() if s != 'pas:HYPE'},                         # HYPE is missing
    dict(HELD_DIV, **{'pas:USDJPY': D('1000')}),                                    # USDJPY is not flat
    dict(HELD_DIV, **{'pas:SP500': D('50000')}),                                    # SP500 above its prior budget
    dict(HELD_DIV, **{'pas:EWJ': D('1000')}),                                       # a market outside the basket
    dict(HELD_DIV, **{'pas:HYPE': D('45000')}),                                     # less HYPE than the move
])
def test_diversify_budgets_refuse_a_missing_foreign_or_overfull_leg(held):
    with pytest.raises(SystemExit):
        run_carry_module().diversify_notionals(held, PRIOR_DIV)


def test_diversify_trims_hype_first_then_buys_sp500_and_sells_usdjpy(tmp_path, monkeypatch):
    rc = run_carry_module()
    held = {'pas:BTC': D('0.26485'), 'pas:ETH': D('8.6261'), 'pas:HYPE': D('1252.69')}  # the 2 Nov 22:00 basket
    marked = {s: q * D(str(SPECS[s][1])) for s, q in held.items()}
    legs = rc.diversify_notionals(marked, PRIOR_DIV)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, **DIV_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(4000):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in SPECS):
            break
    attempts = w.events('CHILD_ATTEMPT')
    trims = [i for i, e in enumerate(attempts) if e['key'].startswith('carry-trim:')]
    entries = [i for i, e in enumerate(attempts) if e['entry']]
    assert trims and {attempts[i]['symbol'] for i in trims} == {'pas:HYPE'}         # only HYPE is trimmed
    assert all(not attempts[i]['entry'] and attempts[i]['tif'] == 'Ioc' for i in trims)
    assert {(attempts[i]['symbol'], attempts[i]['side']) for i in entries} == {('pas:SP500', 'BUY'), ('pas:USDJPY', 'SELL')}
    assert max(trims) < min(entries)                                                # every trim before any entry
    for s in rc.SHIFT_HOLD_LEGS:
        assert w.position(s) == held[s]                                             # BTC and ETH exactly as held
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in SPECS}
    sold = marked['pas:HYPE'] - value['pas:HYPE']
    assert D('49800') < sold <= D('50000')                                          # about $50k, never a sweep
    assert D('59700') < value['pas:SP500'] <= D('59900') and w.position('pas:SP500') > 0
    assert D('14800') < value['pas:USDJPY'] <= D('15000') and w.position('pas:USDJPY') < 0   # USDJPY is short
    assert sum(value.values()) <= D('99998.337076') * D('1.85')                     # exposure only fell
    for s in SPECS:
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]            # one full-size stop per leg
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- EWJ joins the basket LONG at the 2x setting with the reserved $25k (2 Nov 22:05 IST, second step) ----------
from exchange.carry_runtime import CARRY_BASKET_EWJ

EWJ_MARKETS = tuple(s for s, _ in CARRY_BASKET_EWJ)
HELD_EWJ = {'pas:BTC': D('20634.73'), 'pas:ETH': D('19767.57'), 'pas:HYPE': D('57390.00'), 'pas:SP500': D('31000.00'),
            'pas:USDJPY': D('15010.00')}
PRIOR_EWJ = (('pas:BTC', '20700'), ('pas:ETH', '19800'), ('pas:HYPE', '57400'), ('pas:SP500', '59900'),
             ('pas:USDJPY', '15000'))
MODES_EWJ = {'pas:BTC': 'HOLD', 'pas:ETH': 'HOLD', 'pas:HYPE': 'HOLD', 'pas:SP500': 'BUILD', 'pas:USDJPY': 'HOLD'}
EWJ_KW = dict(sides=CARRY_BASKET_EWJ, markets=EWJ_MARKETS, max_positions=6, starting_equity='99998.337076',
              leverage=2, taker_depth_bps=5)


def test_ewj_budgets_hold_completed_legs_keep_building_the_rest_and_give_ewj_25k():
    legs, hold = run_carry_module().ewj_notionals('99998.337076', HELD_EWJ, PRIOR_EWJ, MODES_EWJ)
    assert legs == (('pas:BTC', '20700'), ('pas:ETH', '19800'), ('pas:HYPE', '57400'), ('pas:SP500', '59900'),
                    ('pas:USDJPY', '15100'), ('pas:EWJ', '25000'))
    assert hold == ('pas:BTC', 'pas:ETH', 'pas:HYPE', 'pas:USDJPY')                   # SP500 is still building
    assert sum(D(v) for _, v in legs) <= D('99998.337076') * 2                       # 2x, never above it
    m = basket_mandate(leg_notionals=legs, hold_legs=hold, **EWJ_KW).require()
    assert m.basket['pas:EWJ'] == 'LONG' and m.max_positions == 6 and m.close_legs == ()


@pytest.mark.parametrize('held,prior,modes', [
    (HELD_EWJ, PRIOR_EWJ, dict(MODES_EWJ, **{'pas:HYPE': 'BUILD'})),                # HYPE trim not verified done
    (dict(HELD_EWJ, **{'pas:EWJ': D('1000')}), PRIOR_EWJ, MODES_EWJ),                 # EWJ already held
    (dict(HELD_EWJ, **{'pas:EWY': D('1000')}), PRIOR_EWJ, MODES_EWJ),                 # a position outside the basket
    (HELD_EWJ, PRIOR_EWJ[:3] + (('pas:SP500', '75000'), PRIOR_EWJ[4]), MODES_EWJ),  # 2x cap leaves EWJ < $15k
])
def test_ewj_budgets_refuse_an_unfinished_trim_a_held_ewj_or_too_little_room(held, prior, modes):
    with pytest.raises(SystemExit):
        run_carry_module().ewj_notionals('99998.337076', held, prior, modes)


@pytest.mark.parametrize('change', [
    dict(sides=CARRY_BASKET + (('pas:EWJ', 'SHORT'),)),                             # EWJ only ever LONG
    dict(max_positions=5),                                                          # six legs need six positions
    dict(markets=EWJ_MARKETS[:5]),                                                  # markets must match the sides
    dict(sides=CARRY_BASKET_EWJ + (('pas:EWY', 'LONG'),), markets=EWJ_MARKETS + ('pas:EWY',), max_positions=7),
    dict(leg_notionals=PRIOR_EWJ + (('pas:EWJ', '28000'),)),                        # above 2x the starting equity
])
def test_six_leg_mandate_rejects_anything_else(change):
    base = dict(EWJ_KW, leg_notionals=PRIOR_EWJ + (('pas:EWJ', '25000'),), hold_legs=('pas:BTC', 'pas:ETH'))
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(**dict(base, **change)).require()


def test_ewj_is_a_carry_entry_market_and_the_guard_takes_six_legs(tmp_path):
    require_entry('pas:EWJ', 'CARRY')
    with pytest.raises(ExchangeError, match='V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY'):
        require_entry('pas:EWJ')                                                    # never for other runtimes
    journal = ExecutionJournal(tmp_path / 'j.sqlite', session_id='offline:carry-guard', team_address='0x' + '1' * 40)
    CarryPositionGuard(journal, clock_ms=lambda: 1, sides=CARRY_BASKET_EWJ, max_positions=6)
    with pytest.raises(ExchangeError, match='INVALID_CARRY_POSITION_GUARD'):
        CarryPositionGuard(journal, clock_ms=lambda: 1, sides=CARRY_BASKET_EWJ, max_positions=7)
    journal.close()


def test_raise_plan_sets_a_flat_ewj_from_20x_down_to_2x_and_nothing_else(monkeypatch, tmp_path):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    account.leverage.update({s: dict(type='cross', value=2) for s in account.leverage})
    account.leverage['pas:EWJ'] = dict(type='cross', value=20)
    plan = mod.raise_plan(tmp_path, client, account, provenance='x')
    assert [(c['symbol'], c['before']) for c in plan['changes']] == [('pas:EWJ', dict(type='cross', value=20))]
    assert plan['changes'][0]['requested_action'] == dict(type='updateLeverage', asset=client.market('pas:EWJ').asset_id,
                                                         isCross=True, leverage=2)
    assert sorted(plan['already_two_x_cross']) == sorted(set(CARRY_ENTRY_MARKETS) - {'pas:EWJ'})
    assert plan['orders_permitted'] is False and plan['account_mode_change'] is False


@pytest.mark.parametrize('ewj,held', [
    (dict(type='cross', value=20), D('10')),                                        # EWJ holds a position
    (dict(type='isolated', value=20), None),                                        # never a margin-mode switch
    (dict(type='cross', value=3), D('-10')),                                        # held (wrong side) as well
])
def test_raise_plan_refuses_ewj_unless_flat_and_cross(monkeypatch, tmp_path, ewj, held):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    account.leverage.update({s: dict(type='cross', value=2) for s in account.leverage})
    account.leverage['pas:EWJ'] = ewj
    if held is not None:
        account.positions['pas:EWJ'] = held
    with pytest.raises(ExchangeError, match='ONLY_A_RAISE_FROM_1X_CROSS|CARRY_BASKET_POSITIONS_ONLY'):
        mod.raise_plan(tmp_path, client, account, provenance='x')


def test_ewj_joins_long_while_completed_legs_are_held_and_sp500_finishes(tmp_path, monkeypatch):
    monkeypatch.setitem(SPECS, 'pas:EWJ', (2, D('93.8'), '60'))
    rc = run_carry_module()
    held = {'pas:BTC': D('0.26485'), 'pas:ETH': D('8.6261'), 'pas:HYPE': D('745.45'), 'pas:SP500': D('4.1'),
            'pas:USDJPY': D('-95.6')}                                                # after the first step
    marked = {s: abs(q) * D(str(SPECS[s][1])) for s, q in held.items()}
    prior = (('pas:BTC', '21200'), ('pas:ETH', '20300'), ('pas:HYPE', '57400'), ('pas:SP500', '59900'),
             ('pas:USDJPY', '15000'))
    legs, hold = rc.ewj_notionals('99998.337076', marked, prior, MODES_EWJ)
    assert dict(legs)['pas:EWJ'] == '25000' and hold == ('pas:BTC', 'pas:ETH', 'pas:HYPE', 'pas:USDJPY')
    w = World(tmp_path, monkeypatch, leg_notionals=legs, hold_legs=hold, **EWJ_KW)
    w.venue.leverage.update({s: dict(type='cross', value=2) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(4000):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in EWJ_MARKETS):
            break
    attempts = w.events('CHILD_ATTEMPT')
    assert not [e for e in attempts if e['key'].startswith('carry-trim:')]          # nothing is sold
    assert {(e['symbol'], e['side']) for e in attempts if e['entry']} == {('pas:SP500', 'BUY'), ('pas:EWJ', 'BUY')}
    for s in hold:
        assert w.position(s) == held[s]                                             # held exactly as they were
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in EWJ_MARKETS}
    assert w.position('pas:EWJ') > 0 and D('24800') < value['pas:EWJ'] <= D('25000')
    assert D('59700') < value['pas:SP500'] <= D('59900')
    assert sum(value.values()) <= D('99998.337076') * 2                             # exposure stays within 2x
    for s in EWJ_MARKETS:
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]            # one full-size stop per leg
    assert w.r.order_errors == 0 and not w.r.state['halted']


# ---------- HYPE to $150k with every other leg unchanged, 4x setting, about 2.9x exposure (2 Nov 23:20 IST) ----------
PRIOR_150K = (('pas:BTC', '20600'), ('pas:ETH', '19600'), ('pas:HYPE', '56600'), ('pas:SP500', '59900'),
              ('pas:USDJPY', '15000'), ('pas:EWJ', '25000'))
HELD_150K = {'pas:BTC': D('20480.12'), 'pas:ETH': D('19551.80'), 'pas:HYPE': D('56301.07'), 'pas:SP500': D('25012.40'),
             'pas:EWJ': D('750.00')}                                                 # marked 2 Nov 23:15 IST
MODES_150K = {'pas:BTC': 'HOLD', 'pas:ETH': 'HOLD', 'pas:HYPE': 'HOLD', 'pas:SP500': 'BUILD', 'pas:USDJPY': 'BUILD',
              'pas:EWJ': 'BUILD'}
KW_4X = dict(EWJ_KW, leverage=4)


def test_hype_up_budgets_give_hype_150k_and_keep_every_other_leg():
    legs, hold = run_carry_module().hype_up_notionals(HELD_150K, PRIOR_150K, MODES_150K)
    assert legs == (('pas:BTC', '20500'), ('pas:ETH', '19600'), ('pas:HYPE', '150000'), ('pas:SP500', '59900'),
                    ('pas:USDJPY', '15000'), ('pas:EWJ', '25000'))
    assert hold == ('pas:BTC', 'pas:ETH')                                            # HYPE grows; the rest keep building
    assert D('2.9') * D('99998.337076') < sum(D(v) for _, v in legs) <= D('2.95') * D('99998.337076')
    m = basket_mandate(leg_notionals=legs, hold_legs=hold, **KW_4X).require()
    assert m.leverage == 4 and m.notional_for('pas:HYPE') == D('150000')


@pytest.mark.parametrize('held,prior', [
    (dict(HELD_150K, **{'pas:HYPE': D('150000')}), PRIOR_150K),                       # nothing to buy: never a sale
    ({s: v for s, v in HELD_150K.items() if s != 'pas:BTC'}, PRIOR_150K),            # a hold leg is missing
    (HELD_150K, PRIOR_150K[:5]),                                                     # EWJ has no prior budget
    (dict(HELD_150K, **{'pas:EWY': D('100')}), PRIOR_150K),                           # a position outside the basket
])
def test_hype_up_budgets_refuse_a_sale_or_a_missing_or_foreign_leg(held, prior):
    with pytest.raises(SystemExit):
        run_carry_module().hype_up_notionals(held, prior, MODES_150K)


@pytest.mark.parametrize('change', [
    dict(leg_notionals=PRIOR_150K[:2] + (('pas:HYPE', '155100'),) + PRIOR_150K[3:]),   # leg above $155k
    dict(leg_notionals=PRIOR_150K[:2] + (('pas:HYPE', '155000'),) + PRIOR_150K[3:5] + (('pas:EWJ', '25000'),),
         starting_equity='99000'),                                                    # above 2.95x the start
    dict(leverage=3),                                                                 # 1, 2 or 4 only
    dict(leverage=5),
    dict(leg_notionals=()),                                                           # 4x needs explicit legs
    dict(close_legs=('pas:USDJPY',)),                                                 # a close leg has no budget
])
def test_four_x_mandate_rejects_anything_else(change):
    base = dict(KW_4X, leg_notionals=PRIOR_150K[:2] + (('pas:HYPE', '150000'),) + PRIOR_150K[3:],
                hold_legs=('pas:BTC', 'pas:ETH'))
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(**dict(base, **change)).require()


def test_raise_plan_to_4x_raises_only_from_2x_cross(monkeypatch, tmp_path):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    account.leverage.update({s: dict(type='cross', value=2) for s in account.leverage})
    account.leverage['pas:SP500'] = dict(type='cross', value=4)                     # already raised: skipped
    plan = mod.raise_plan(tmp_path, client, account, provenance='x', target=4)
    assert [c['symbol'] for c in plan['changes']] == ['pas:BTC', 'pas:ETH', 'pas:EWJ', 'pas:HYPE', 'pas:USDJPY']
    assert all(c['before'] == dict(type='cross', value=2) and c['requested_action'] == dict(
        type='updateLeverage', asset=client.market(c['symbol']).asset_id, isCross=True, leverage=4) for c in plan['changes'])
    assert plan['already_four_x_cross'] == ['pas:SP500'] and plan['configuration_scope'] == 'CARRY_4X'
    assert plan['target_leverage'] == 4 and plan['orders_permitted'] is False and plan['account_mode_change'] is False
    monkeypatch.setattr('exchange.paper_operations.active_source_hash', lambda root: plan['source_hash'])
    assert mod.require_plan(tmp_path, plan, plan['observed_ms'] + 1000) == plan
    with pytest.raises(ExchangeError, match='FRESH_EXACT_CARRY_LEVERAGE_PLAN_REQUIRED'):
        mod.require_plan(tmp_path, dict(plan, configuration_scope='CARRY_2X'), plan['observed_ms'])


@pytest.mark.parametrize('before', [dict(type='cross', value=1), dict(type='cross', value=3),
                                    dict(type='isolated', value=2), dict(type='cross', value=20)])
def test_raise_plan_to_4x_refuses_anything_but_2x_cross(monkeypatch, tmp_path, before):
    account = RaiseAccount()
    mod, client, _ = raise_world(monkeypatch, account)
    account.leverage.update({s: dict(type='cross', value=2) for s in account.leverage})
    account.leverage['pas:EWJ'] = before                                             # no EWJ exception at 4x
    with pytest.raises(ExchangeError, match='ONLY_A_RAISE_FROM_1X_CROSS'):
        mod.raise_plan(tmp_path, client, account, provenance='x', target=4)
    with pytest.raises(ExchangeError, match='UNSUPPORTED_TARGET_LEVERAGE'):
        mod.raise_plan(tmp_path, client, account, provenance='x', target=3)


def test_hype_grows_to_150k_with_ioc_children_while_every_other_leg_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setitem(SPECS, 'pas:EWJ', (2, D('93.8'), '60'))
    rc = run_carry_module()
    held = {'pas:BTC': D('0.26485'), 'pas:ETH': D('8.6261'), 'pas:HYPE': D('735.07'), 'pas:SP500': D('7.850'),
            'pas:USDJPY': D('-95.6'), 'pas:EWJ': D('266.5')}                         # every other leg already built
    marked = {s: abs(q) * D(str(SPECS[s][1])) for s, q in held.items()}
    modes = {s: 'HOLD' for s in held}
    legs, hold = rc.hype_up_notionals(marked, PRIOR_150K, modes)
    assert hold == ('pas:BTC', 'pas:ETH', 'pas:SP500', 'pas:USDJPY', 'pas:EWJ') and dict(legs)['pas:HYPE'] == '150000'
    w = World(tmp_path, monkeypatch, leg_notionals=legs, hold_legs=hold, **KW_4X)
    w.venue.leverage.update({s: dict(type='cross', value=4) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(4000):
        w.step(31000)
        if all(w.leg(s)['mode'] == 'HOLD' for s in EWJ_MARKETS):
            break
    attempts = w.events('CHILD_ATTEMPT')
    assert attempts and all(e['symbol'] == 'pas:HYPE' and e['entry'] and e['tif'] == 'Ioc' for e in attempts)
    for s in hold:
        assert w.position(s) == held[s]                                             # unchanged, as ordered
    value = {s: abs(w.position(s)) * D(str(SPECS[s][1])) for s in EWJ_MARKETS}
    assert D('149800') < value['pas:HYPE'] <= D('150000')
    assert sum(value.values()) <= D('2.95') * D('99998.337076')                     # exposure capped at 2.95x
    for s in EWJ_MARKETS:
        leg = w.leg(s)
        assert leg['mode'] == 'HOLD' and leg['verified']['problems'] == []
        assert [D(o['sz']) for o in w.stops(s)] == [abs(w.position(s))]            # HYPE's stop sized to $150k
    assert w.r.order_errors == 0 and not w.r.state['halted']


def test_carry_4x_transport_signs_only_the_approved_4x_cross_action_once(tmp_path, monkeypatch):
    import socket
    from eth_account import Account
    from exchange import leverage_configuration as lc, pas_configuration as pc
    from exchange.pas_configuration import PasConfigurationApproval
    from exchange.sdk_transport import build_exchange
    from exchange.execution_safety import NonceManager, HyperliquidRateLimitManager
    from exchange.execution_journal import fingerprint
    from exchange.hyperliquid_client import HyperliquidClient
    from test_pas_execution_faults import PasLiveFixture
    # Legacy suites install practice (par) defaults at import; a PAS test selects its own profile.
    monkeypatch.setenv('HL_DEX', 'pas'); monkeypatch.setenv('SIGNAL_DATA_MODE', 'PAS_NATIVE_ONLY')
    signer = Account.create(); f = PasLiveFixture(signer.address); monkeypatch.setattr(pc, 'API', signer.address)
    monkeypatch.setattr(pc, 'TEAM', f.active['user']); team = f.active['user']
    c = HyperliquidClient(f, clock_ms=lambda: f.now, venue='pas'); c.startup()
    four = dict(type='updateLeverage', asset=c.market('pas:BTC').asset_id, isCross=True, leverage=4)
    plan = dict(source_hash='b' * 64, configuration_scope='CARRY_4X', target_leverage=4, changes=[dict(requested_action=four)])
    plan['plan_hash'] = fingerprint(plan)
    a = PasConfigurationApproval(plan['plan_hash'], 'b' * 64, 'c' * 64, f.now, f.now + 900000, socket.gethostname(),
                                 'APPROVE PAS CONFIGURATION ' + plan['plan_hash'], True, True, team, signer.address)
    j = ExecutionJournal(tmp_path / 'off.sqlite', session_id='OFFLINE', team_address=team)
    n = NonceManager(tmp_path / 'nonce.sqlite', signer.address, clock_ms=lambda: f.now, journal=j)
    rates = HyperliquidRateLimitManager(j, clock_ms=lambda: f.now)
    wires = []

    def sdk(wallet, client, nonces, sink):
        s = build_exchange(wallet, client, nonces, sink, offline=True)
        s.session.post = lambda url, **kw: (wires.append(kw['json']) or SimpleNamespace(
            status_code=200, json=lambda: dict(status='ok', response=dict(type='default'))))
        return s
    monkeypatch.setattr(lc, 'build_exchange', sdk)
    two = dict(plan, changes=[dict(requested_action=dict(four, leverage=2))]); two.pop('plan_hash')
    two['plan_hash'] = fingerprint(two)
    with pytest.raises(ExchangeError, match='V4_BTC_EWY_CONFIGURATION_ACTIONS_ONLY'):   # a 2x action under CARRY_4X
        lc.LeverageConfigurationTransport(c, signer, team, n, replace(a, plan_hash=two['plan_hash'],
                                          exact_phrase='APPROVE PAS CONFIGURATION ' + two['plan_hash']),
                                          rates=rates, readiness_guard=lambda: None, approved_plan=two)
    t = lc.LeverageConfigurationTransport(c, signer, team, n, a, rates=rates, readiness_guard=lambda: None,
                                          approved_plan=plan)
    try:
        assert t.target_leverage == 4
        t.set_target_cross('pas:BTC')
        assert len(wires) == 1 and wires[0]['action'] == four                          # exactly the approved action
        with pytest.raises(ExchangeError):
            t.set_target_cross('pas:BTC')                                              # single use
        with pytest.raises(ExchangeError):
            t.set_target_cross('pas:ETH')                                              # never an unapproved market
        assert len(wires) == 1
    finally:
        t.close(); n.close(); j.close(); c.close()


# ---------- account halt moved from -5% to -9.5% (a ~6% HYPE fall at $150k), everything else unchanged (3 Nov 00:10 IST) ----------
LEGS_4X = PRIOR_150K[:2] + (('pas:HYPE', '150000'),) + PRIOR_150K[3:]


def test_carry_halt_may_be_nine_and_a_half_percent_and_nothing_else():
    m = basket_mandate(leg_notionals=LEGS_4X, hold_legs=('pas:BTC', 'pas:ETH'), account_loss_halt='0.095', **KW_4X).require()
    assert m.account_loss_halt == '0.095'
    for other in ('0.06', '0.09', '0.096', '0.10'):
        with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
            basket_mandate(leg_notionals=LEGS_4X, hold_legs=('pas:BTC', 'pas:ETH'), account_loss_halt=other,
                           **KW_4X).require()
    from test_funding_carry import mandate as funding_mandate
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        funding_mandate(account_loss_halt='0.095').require()                       # other runtimes keep at most 5%


def test_keep_budgets_hold_completed_legs_and_keep_every_other_budget():
    held = {'pas:BTC': D('20410.00'), 'pas:ETH': D('19440.00'), 'pas:HYPE': D('149870.00'), 'pas:SP500': D('41000.00'),
            'pas:EWJ': D('6000.00')}
    modes = dict(MODES_150K, **{'pas:HYPE': 'HOLD'})
    legs, hold = run_carry_module().keep_notionals(held, LEGS_4X, modes)
    assert hold == ('pas:BTC', 'pas:ETH', 'pas:HYPE')                               # HYPE complete: held as it is
    assert legs == (('pas:BTC', '20500'), ('pas:ETH', '19500'), ('pas:HYPE', '149900'), ('pas:SP500', '59900'),
                    ('pas:USDJPY', '15000'), ('pas:EWJ', '25000'))                   # the rest keep their budgets
    legs, hold = run_carry_module().keep_notionals(held, LEGS_4X, dict(MODES_150K, **{'pas:HYPE': 'BUILD'}))
    assert dict(legs)['pas:HYPE'] == '150000' and 'pas:HYPE' not in hold            # still building: same budget
    with pytest.raises(SystemExit):
        run_carry_module().keep_notionals(dict(held, **{'pas:EWY': D('1')}), LEGS_4X, modes)


def test_nine_and_a_half_percent_halt_rides_a_six_percent_hype_fall_and_flattens_beyond(tmp_path, monkeypatch):
    monkeypatch.setitem(SPECS, 'pas:EWJ', (2, D('93.8'), '60'))
    w = World(tmp_path, monkeypatch, leg_notionals=LEGS_4X, hold_legs=('pas:BTC', 'pas:ETH'), account_loss_halt='0.095',
              **KW_4X)
    w.venue.leverage.update({s: dict(type='cross', value=4) for s in SPECS})
    seed(w, {'pas:BTC': D('0.26485'), 'pas:ETH': D('8.6261'), 'pas:HYPE': D('1948.05')})
    w.r.startup()
    w.r.account.get_equity = lambda: SimpleNamespace(collateral_balance=D('90522'))   # $99.5k less 6% of $150k
    w.step(31000)
    assert not w.r.state['halted']                                                  # rides the 6% HYPE fall
    w.r.account.get_equity = lambda: SimpleNamespace(collateral_balance=D('90498'))   # -9.5% of $99,998
    w.step(31000)
    assert w.r.state['halted'] and str(w.r.state['halted']['reason']).startswith('ACCOUNT_LOSS_HALT')
    assert {s for s, leg in w.r.state['legs'].items() if leg['mode'] == 'UNWIND'} >= {'pas:BTC', 'pas:ETH', 'pas:HYPE'}


# ---------- 3 Nov: BTC long -> $20k short ----------
FLIP_PRIOR = (('pas:BTC', '20400'), ('pas:ETH', '19500'), ('pas:HYPE', '150000'), ('pas:SP500', '59900'),
              ('pas:USDJPY', '15100'), ('pas:EWJ', '25000'))
FLIP_HELD = {'pas:BTC': D('20323.10'), 'pas:ETH': D('19499.20'), 'pas:HYPE': D('104183.00'), 'pas:SP500': D('59880.00'),
             'pas:USDJPY': D('15018.00'), 'pas:EWJ': D('25021.00')}                 # marked 3 Nov 15:10 IST
FLIP_MODES = {'pas:BTC': 'HOLD', 'pas:ETH': 'HOLD', 'pas:HYPE': 'BUILD', 'pas:SP500': 'HOLD', 'pas:USDJPY': 'HOLD',
              'pas:EWJ': 'HOLD'}


def test_btc_flip_budgets_close_the_long_first_then_short_20k_and_keep_every_other_leg():
    rc = run_carry_module()
    legs, hold, close = rc.flip_notionals(FLIP_HELD, FLIP_PRIOR, FLIP_MODES, True)
    assert close == ('pas:BTC',) and hold == ('pas:ETH', 'pas:SP500', 'pas:USDJPY', 'pas:EWJ')
    assert legs == (('pas:ETH', '19500'), ('pas:HYPE', '150000'), ('pas:SP500', '59900'), ('pas:USDJPY', '15100'),
                    ('pas:EWJ', '25100'))                                         # BTC has no budget while closing
    flat = {s: v for s, v in FLIP_HELD.items() if s != 'pas:BTC'}
    legs2, hold2, close2 = rc.flip_notionals(flat, legs, dict(FLIP_MODES, **{'pas:BTC': 'CLOSED'}), False)
    assert close2 == () and hold2 == hold and legs2[0] == ('pas:BTC', '20000')
    assert dict(legs2[1:]) == dict(legs)                                            # nothing else changes
    with pytest.raises(SystemExit):
        rc.flip_notionals(dict(flat, **{'pas:EWY': D('1')}), legs, FLIP_MODES, False)


def test_btc_flip_mandates_are_valid_at_4x_and_btc_is_the_only_side_that_changes():
    rc = run_carry_module()
    legs, hold, close = rc.flip_notionals(FLIP_HELD, FLIP_PRIOR, FLIP_MODES, True)
    basket_mandate(**dict(KW_4X, leg_notionals=legs, hold_legs=hold, close_legs=close, account_loss_halt='0.095')).require()
    flat = {s: v for s, v in FLIP_HELD.items() if s != 'pas:BTC'}
    legs2, hold2, _ = rc.flip_notionals(flat, legs, dict(FLIP_MODES, **{'pas:BTC': 'CLOSED'}), False)
    m = basket_mandate(**dict(KW_4X, sides=CARRY_BASKET_EWJ_BTC_SHORT, leg_notionals=legs2, hold_legs=hold2,
                              account_loss_halt='0.095')).require()
    assert m.basket == dict(dict(CARRY_BASKET_EWJ), **{'pas:BTC': 'SHORT'})
    eth_short = tuple((s, 'SHORT' if s == 'pas:ETH' else d) for s, d in CARRY_BASKET_EWJ)
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        basket_mandate(**dict(KW_4X, sides=eth_short, leg_notionals=legs2, hold_legs=hold2)).require()


def test_btc_long_is_sold_to_flat_then_shorted_with_sliced_children_and_nothing_else_moves(tmp_path, monkeypatch):
    rc = run_carry_module()
    monkeypatch.setitem(SPECS, 'pas:EWJ', (2, D('93.8'), '60'))
    held = {'pas:BTC': D('0.26485'), 'pas:ETH': D('8.6261'), 'pas:HYPE': D('1948.05'), 'pas:SP500': D('7.85'),
            'pas:USDJPY': D('-95.11'), 'pas:EWJ': D('266.6')}
    marked = {s: abs(q) * D(str(SPECS[s][1])) for s, q in held.items()}
    modes = dict(FLIP_MODES, **{'pas:HYPE': 'HOLD'})
    legs, hold, close = rc.flip_notionals(marked, FLIP_PRIOR, modes, True)
    w = World(tmp_path, monkeypatch, leg_notionals=legs, hold_legs=hold, close_legs=close, account_loss_halt='0.095',
              **KW_4X)
    w.venue.leverage.update({s: dict(type='cross', value=4) for s in SPECS})
    seed(w, held)
    w.r.startup()
    for _ in range(600):
        w.step(31000)
        if w.leg('pas:BTC')['mode'] == 'CLOSED':
            break
    assert w.position('pas:BTC') == 0 and not w.stops('pas:BTC') and not w.children('pas:BTC')
    outs = [e for e in w.events('CHILD_ATTEMPT') if e['symbol'] == 'pas:BTC']
    assert outs and all(e['key'].startswith('carry-out:') and not e['entry'] and e['tif'] == 'Ioc' for e in outs)
    assert all(D(e['quantity']) <= D(e['touch_quantity']) * D('0.25') for e in outs)  # never a sweep
    assert all(w.position(s) == q for s, q in held.items() if s != 'pas:BTC')       # nothing else moved
    assert w.r.order_errors == 0 and not w.r.state['halted']
    # Second step: rebind to the BTC SHORT basket (new mandate, fresh state, same journal and exchange).
    flat = {s: v for s, v in marked.items() if s != 'pas:BTC'}
    legs2, hold2, _ = rc.flip_notionals(flat, legs, {s: l['mode'] for s, l in w.r.state['legs'].items()}, False)
    (tmp_path / 'state').rename(tmp_path / 'state_closing')
    w2 = World(tmp_path, monkeypatch, venue=w.venue, books=w.books, clock=w.clock, leg_notionals=legs2, hold_legs=hold2,
               account_loss_halt='0.095', **dict(KW_4X, sides=CARRY_BASKET_EWJ_BTC_SHORT))
    w2.r.startup()
    w2.clock[0] += 2 * HOUR                                                          # past the maker window
    for _ in range(1500):
        w2.step(31000)
        if w2.leg('pas:BTC')['mode'] == 'HOLD':
            break
    btc = w2.position('pas:BTC')
    assert btc < 0 and abs(abs(btc) * D('80000') - D('20000')) < 50                 # $20k SHORT
    assert [D(o['sz']) for o in w2.stops('pas:BTC')] == [abs(btc)]                   # one full-size stop
    assert D(w2.stops('pas:BTC')[0]['triggerPx']) > D('80000')                       # above the price for a short
    ins = [e for e in w2.events('CHILD_ATTEMPT') if e['symbol'] == 'pas:BTC']
    assert ins and all(e['entry'] and e['side'] == 'SELL' for e in ins)
    assert all(w2.position(s) == q for s, q in held.items() if s != 'pas:BTC')
    assert w2.r.order_errors == 0 and not w2.r.state['halted']


def test_an_exchange_special_status_skips_the_child_and_is_not_an_order_error(tmp_path, monkeypatch):
    # 3 Nov 16:37 IST: exchangeStatus flickered a special status twice in 15 min; each refusal counted toward the
    # 3-error halt-and-flatten. Refusing is right; it is now a skip that retries on the next cycle.
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    calls = []

    def gate(**k):
        calls.append(k)
        raise ExchangeError('EXCHANGE_SPECIAL_STATUS_REQUIRES_REVIEW')
    w.r.preflight = gate
    for _ in range(6):
        w.step(31000)
    assert calls and w.r.order_errors == 0 and not w.r.state['halted'] and not w.children()
    assert {e['code'] for e in w.events('CHILD_SKIPPED')} == {'EXCHANGE_SPECIAL_STATUS_REQUIRES_REVIEW'}
    w.r.preflight = lambda **k: None                                                # status clear: building resumes
    w.step(31000)
    assert w.children()
