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
from exchange.carry_runtime import CARRY_BASKET, CARRY_PROFILE, CarryExecution, CarryMandate
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
    dict(leg_notional='9501'), dict(max_positions=4), dict(sides=CARRY_BASKET[:4] + (('pas:USDJPY', 'LONG'),)),
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
    assert PAS_ENTRY_MARKETS == {'pas:BTC', 'pas:EWY', 'pas:HYPE'} and len(CARRY_ENTRY_MARKETS) == 5


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
    def __init__(self, tmp_path, monkeypatch, *, venue=None, books=None, clock=None, maker_fill_chance=0.0):
        monkeypatch.setattr(carry_basket.time, 'sleep', lambda s: None)
        self.m = basket_mandate().require()
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
