"""Funding-carry strategy, basket guards, protection geometry and overnight guardrails."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import json

import pytest

from exchange.base_exchange import ExchangeError, MarketSpec, Position
from exchange.carry_runtime import (BasketPositionGuard, CarryAccountRecovery, CarryExecution, CarryLeg,
                                    CarryMandate, CarryProtection, CarryRuntime, l2_capacity, resting_protection)
from exchange.compliance_guard import SIGNAL_AGE_ALLOWANCE_MS
from exchange.position_protection import ProtectionPolicy
from strategies import STRATEGIES, select
from strategies.funding_carry import (CarryParams, FundingCarry, HOUR_MS, fill_deviation, loss_halt,
                                      marked_equity, paying, receiving_side, stop_price, trailing_mean)
from test_live_exchange_execution import live, permission
from test_single_position_compliance import evaluate, request
from test_exchange_migration import NOW

T = 1792800000000 // HOUR_MS * HOUR_MS   # an exact hour
PARAMS = CarryParams(markets=('pas:BTC', 'pas:USDJPY'))


def rates(value, hours=24, end=T):
    return {end - i * HOUR_MS: D(value) for i in range(hours)}


def pos(symbol, qty, entry='100', upnl='0', liq=None):
    return Position(symbol, D(qty), D(entry), D(upnl), D(0), D(liq) if liq else None)


# ---------- strategy ----------
def test_selection_switch_exposes_only_registered_strategies():
    assert select('funding_carry') is FundingCarry and set(STRATEGIES) == {'funding_carry'}
    with pytest.raises(ValueError, match='UNKNOWN_STRATEGY'):
        select('vwap_pullback')


def test_negative_funding_enters_long_and_positive_enters_short():
    exits, entries = FundingCarry(PARAMS).decide(
        {'pas:BTC': rates('-0.0001'), 'pas:USDJPY': rates('0.00007')}, {}, {}, T + 60000)
    assert exits == [] and [(e['symbol'], e['side']) for e in entries] == [('pas:BTC', 'LONG'), ('pas:USDJPY', 'SHORT')]


def test_funding_inside_threshold_or_too_little_history_gives_no_signal():
    exits, entries = FundingCarry(PARAMS).decide(
        {'pas:BTC': rates('-0.00001'), 'pas:USDJPY': rates('0.0001', hours=10)}, {}, {}, T + 60000)
    assert exits == entries == []
    assert trailing_mean(rates('1', hours=10), T, 24) is None


def test_held_leg_exits_only_when_clearly_paying():
    s = FundingCarry(PARAMS)
    neutral = s.decide({'pas:BTC': rates('0.00001')}, {'pas:BTC': D('0.2')}, {}, T)
    assert neutral == ([], [])                      # hysteresis: weak funding is not an exit
    exits, _ = s.decide({'pas:BTC': rates('0.0001')}, {'pas:BTC': D('0.2')}, {}, T)
    assert exits[0]['symbol'] == 'pas:BTC' and exits[0]['reason'] == 'FUNDING_TURNED_AGAINST'
    exits, _ = s.decide({'pas:USDJPY': rates('-0.0001')}, {'pas:USDJPY': D('-5')}, {}, T)
    assert exits[0]['side'] == 'SHORT'


def test_cooldown_after_exchange_stop():
    s = FundingCarry(PARAMS)
    f = {'pas:BTC': rates('-0.0001')}
    assert s.decide(f, {}, {'pas:BTC': T - HOUR_MS}, T)[1] == []
    assert s.decide(f, {}, {'pas:BTC': T - 24 * HOUR_MS}, T)[1][0]['symbol'] == 'pas:BTC'


def test_funding_sign_convention():
    assert receiving_side(D('-0.0001'), D('0.00002')) == 'LONG'
    assert receiving_side(D('0.0001'), D('0.00002')) == 'SHORT'
    assert paying('LONG', D('0.0001'), D('0.00002')) and paying('SHORT', D('-0.0001'), D('0.00002'))
    assert not paying('LONG', D('-0.0001'), D('0.00002'))


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        CarryParams(markets=())
    with pytest.raises(ValueError):
        CarryParams(threshold=D(0))


# ---------- math and guardrails ----------
def test_stop_prices_both_directions():
    assert stop_price(D(100), 'LONG', D('0.08')) == D('92.00')
    assert stop_price(D(100), 'SHORT', D('0.08')) == D('108.00')


def test_marked_equity_adds_unrealized_once_and_loss_halt_boundary():
    equity = marked_equity(D(100000), {'a': pos('pas:BTC', '1', upnl='-3000'), 'b': pos('pas:ETH', '-1', upnl='-2000')})
    assert equity == D(95000)
    assert loss_halt(D(100000), equity, D('0.05')) and not loss_halt(D(100000), D('95001'), D('0.05'))


def test_fill_deviation():
    assert fill_deviation(D(100), D('100.6')) == D('0.006')


def test_leg_sizing_rounds_down_to_lot():
    spec = MarketSpec('pas:BTC', 5, 40, 1)
    assert spec.normalize_size(D(19000) / D('81440.5')) == D('0.23329')   # 0.233299... rounds down


def test_l2_capacity_counts_only_depth_inside_limit():
    book = SimpleNamespace(asks=[SimpleNamespace(price=D(100), quantity=D(1)), SimpleNamespace(price=D(101), quantity=D(3)),
                                 SimpleNamespace(price=D(103), quantity=D(50))],
                           bids=[SimpleNamespace(price=D(99), quantity=D(2)), SimpleNamespace(price=D(97), quantity=D(9))])
    assert l2_capacity(book, 'BUY', D(101), D('0.25')) == D(1)
    assert l2_capacity(book, 'SELL', D(98), D('0.5')) == D(1)


# ---------- protection geometry ----------
def protection(stop='0.08'):
    p = CarryProtection.__new__(CarryProtection)
    p.stop_fraction = D(stop)
    p.policy = ProtectionPolicy(True, 'test-approval', D(1), D('0.01'))
    p.executor = SimpleNamespace(client=SimpleNamespace(market=lambda s: MarketSpec(s, 2, 20, 1)))
    return p


@pytest.mark.parametrize('qty,side,trigger,limit', [('3', 'SELL', D('92'), D('91.08')),
                                                    ('-3', 'BUY', D('108'), D('109.08'))])
def test_protection_plan_is_entry_minus_or_plus_eight_percent(qty, side, trigger, limit):
    leg = CarryLeg('pas:EWY', '0.08')
    position = pos('pas:EWY', qty)
    leg.sync(position)
    plan = protection()._plan('pas:EWY', position, leg, NOW)
    assert (plan.side, plan.quantity, plan.trigger_price, plan.limit_price) == (side, D(3), trigger, limit)
    assert plan.is_market is True and plan.classification == 'CATASTROPHIC_STOP'


def test_protection_requires_matching_leg_and_respects_liquidation():
    leg = CarryLeg('pas:EWY', '0.08')
    with pytest.raises(ExchangeError, match='PROTECTION_MANAGEMENT_EVIDENCE_REQUIRED'):
        protection()._plan('pas:EWY', pos('pas:EWY', '3'), leg, NOW)
    position = pos('pas:EWY', '3', liq='95')
    leg.sync(position)
    with pytest.raises(ExchangeError, match='PROTECTION_TRIGGER_BEYOND_LIQUIDATION'):
        protection()._plan('pas:EWY', position, leg, NOW)


def test_leg_mirrors_exchange_truth_and_flat_clears():
    leg = CarryLeg('pas:BTC', '0.08')
    leg.sync(pos('pas:BTC', '-0.2', entry='80000'))
    assert leg._open_position['side'] == 'SELL' and leg._open_position['stop_loss_price'] == D('86400.00')
    leg.sync(None)
    assert not leg.has_open_position


# ---------- basket guards ----------
class Orders:
    def __init__(self, positions, orders):
        self.positions, self.orders = positions, orders

    def get_positions(self):
        return self.positions

    def get_frontend_open_orders(self):
        return self.orders


def basket(positions, orders, max_positions=5):
    e = CarryExecution.__new__(CarryExecution)
    e.account = Orders(positions, orders)
    e.max_positions = max_positions
    e.allowed_markets = frozenset({'pas:BTC', 'pas:ETH', 'pas:SP500'})
    e.position_guard = SimpleNamespace(revoke=lambda reason: None)
    e.journal = SimpleNamespace(event=lambda *a, **k: None)
    e.entries_paused = False
    return e


STOP = dict(coin='pas:BTC', isTrigger=True, reduceOnly=True)


def test_basket_entry_allowed_next_to_protected_leg():
    basket({'pas:BTC': pos('pas:BTC', '1')}, [STOP])._require_entry_account(NOW, request(symbol='pas:ETH'))


@pytest.mark.parametrize('positions,orders,symbol,max_positions', [
    ({'pas:BTC': pos('pas:BTC', '1')}, [STOP], 'pas:BTC', 5),                               # same market
    ({'pas:BTC': pos('pas:BTC', '1')}, [STOP], 'pas:ETH', 1),                               # basket full
    ({'pas:BTC': pos('pas:BTC', '1')}, [dict(STOP, isTrigger=False)], 'pas:ETH', 5),        # resting entry/limit
    ({'pas:BTC': pos('pas:BTC', '1')}, [dict(STOP, coin='pas:GOLD')], 'pas:ETH', 5),        # stop on a flat market
    ({'pas:GOLD': pos('pas:GOLD', '1')}, [], 'pas:ETH', 5),                                 # foreign exposure
])
def test_basket_entry_blocked(positions, orders, symbol, max_positions):
    e = basket(positions, orders, max_positions)
    with pytest.raises(ExchangeError, match='ACCOUNT_CHANGED_BEFORE_SIGNING'):
        e._require_entry_account(NOW, request(symbol=symbol))
    assert e.entries_paused


def test_scalper_resting_take_profit_on_a_held_leg_allows_the_next_market():
    tp = dict(STOP, isTrigger=False)
    e = basket({'pas:BTC': pos('pas:BTC', '1')}, [STOP, tp])
    e.resting_take_profits = True
    e._require_entry_account(NOW, request(symbol='pas:ETH'))
    for bad in (dict(tp, reduceOnly=False), dict(tp, coin='pas:SP500')):     # an entry, or a flat market's order
        e = basket({'pas:BTC': pos('pas:BTC', '1')}, [STOP, bad])
        e.resting_take_profits = True
        with pytest.raises(ExchangeError, match='ACCOUNT_CHANGED_BEFORE_SIGNING'):
            e._require_entry_account(NOW, request(symbol='pas:ETH'))


def test_only_our_resting_stops_are_filtered_from_pending_exits():
    stop = dict(state='OPEN', request=json.dumps(dict(strategy_id='CATASTROPHIC_STOP')))
    exit_order = dict(state='OPEN', request=json.dumps(dict(strategy_id='CARRY_EXIT')))
    pending_stop = dict(state='SUBMITTED', request=json.dumps(dict(strategy_id='CATASTROPHIC_STOP')))
    assert resting_protection(stop) and not resting_protection(exit_order) and not resting_protection(pending_stop)


def test_recovery_allows_basket_but_flags_excess_and_foreign_markets():
    r = CarryAccountRecovery.__new__(CarryAccountRecovery)
    r.markets, r.max_positions = {'pas:BTC', 'pas:ETH'}, 2
    r.state = SimpleNamespace(positions={'pas:BTC': 1, 'pas:ETH': 1})
    assert r.concurrent_exposure_reasons() == []
    r.state.positions = {'pas:BTC': 1, 'pas:ETH': 1, 'pas:GOLD': 1}
    assert set(r.concurrent_exposure_reasons()) == {'UNEXPECTED_CONCURRENT_EXPOSURE', 'UNEXPECTED_MARKET_EXPOSURE:pas:GOLD'}


# ---------- mandate ----------
def mandate(**changes):
    from exchange.competition_windows import SCORED_START_MS, SCORED_END_MS
    from exchange.venue_profiles import venue_profile
    base = dict(team_wallet='0x' + '1' * 40, api_wallet='0x' + '2' * 40, markets=('pas:BTC', 'pas:ETH'),
                starts_ms=SCORED_START_MS + 1, flatten_ms=SCORED_END_MS - 1800000, expires_ms=SCORED_END_MS - 300000,
                starting_equity='100000', leg_notional='19000', source_hash='a' * 64, release_sha256='b' * 64,
                venue_identity=venue_profile('pas').identity, approval_reference='checkpoint approval')
    return CarryMandate(**dict(base, **changes))


def test_valid_mandate_and_identity_is_stable():
    assert mandate().require().identity == mandate().identity


@pytest.mark.parametrize('change', [dict(leverage=2), dict(account_loss_halt='0.06'), dict(position_stop='0.09'),
    dict(max_positions=6), dict(leg_notional='60000'), dict(expires_ms=10 ** 13), dict(markets=('par:BTC',)),
    dict(api_wallet='0x' + '1' * 40), dict(approval_reference=' '), dict(dex='par')])
def test_mandate_rejects_out_of_policy_values(change):
    with pytest.raises(ExchangeError, match='INVALID_CARRY_MANDATE'):
        mandate(**change).require()


# ---------- runtime guardrails ----------
class FakeRuntime(CarryRuntime):
    def __init__(self, tmp_path, positions=None, equity=D(100000)):
        self.m = mandate().require()
        self.state_dir = tmp_path
        self.clock_ms = lambda: NOW
        self.start_equity = D(100000)
        self.state = dict(mandate='x', halted=None, stopped_at={}, trades=[], breakers=[], last_report_day=None)
        self.order_errors = 0
        self.disconnected_since = None
        self.executor = SimpleNamespace(entries_paused=False, journal=SimpleNamespace(event=lambda *a, **k: None))
        self.flattened = []
        self._positions = positions or {}
        self.stream = SimpleNamespace(connected=True, poll=lambda: None, pending=False, ready=True, healthy=False)

    def flatten_all(self, reason):
        self.flattened.append(reason)

    def positions(self):
        return self._positions


def test_three_consecutive_order_errors_halt_entries_without_flatten(tmp_path):
    r = FakeRuntime(tmp_path)
    for _ in range(3):
        r._note_order_error(ExchangeError('X'), 'entry')
    assert r.state['halted']['reason'] == 'CONSECUTIVE_ORDER_ERRORS' and r.executor.entries_paused and not r.flattened
    assert json.loads((tmp_path / 'carry_state.json').read_text())['halted']


def test_account_loss_halt_flattens(tmp_path):
    r = FakeRuntime(tmp_path)
    r.halt('ACCOUNT_LOSS_HALT:94000', flatten=True)
    assert r.flattened == ['ACCOUNT_LOSS_HALT:94000']


def test_disconnect_over_five_minutes_halts(tmp_path):
    r = FakeRuntime(tmp_path)
    clock = [NOW]
    r.clock_ms = lambda: clock[0]
    for t in (NOW, NOW + 200000, NOW + 300001):
        clock[0] = t
        r._stream_health()
    assert r.state['halted']['reason'] == 'API_DISCONNECT_OVER_LIMIT'


def test_leg_closed_by_exchange_starts_cooldown(tmp_path):
    r = FakeRuntime(tmp_path)
    r._record_stops({'pas:BTC', 'pas:ETH'}, {'pas:ETH'})
    assert r.state['stopped_at'] == {'pas:BTC': NOW}


# ---------- compliance hooks on the real guard ----------
def test_signal_age_allowance_keeps_one_minute_window():
    assert SIGNAL_AGE_ALLOWANCE_MS == {60000: 120000, 3600000: 300000}


def carry_token(req, *, setup='CARRY_LONG', signal_ms=NOW - HOUR_MS, interval=HOUR_MS):
    token = permission(req)
    return replace(token, provenance=replace(token.provenance, setup_type=setup, signal_timestamp_ms=signal_ms,
                                             signal_interval_ms=interval))


def test_carry_setup_rejected_unless_owner_opts_in(live):
    req = request()
    assert evaluate(live, req, token=carry_token(req)).code == 'UNEXPLAINED_ORDER'
    live.executor.compliance_guard.extra_setup_types = frozenset({'CARRY_LONG', 'CARRY_SHORT'})
    assert evaluate(live, req, token=carry_token(req)).allowed


@pytest.mark.parametrize('signal_ms,allowed', [(NOW - HOUR_MS, True), (NOW - HOUR_MS - 300000, True),
    (NOW - HOUR_MS - 300001, False), (NOW - HOUR_MS + 1, False)])
def test_hourly_signal_age_window(live, signal_ms, allowed):
    live.executor.compliance_guard.extra_setup_types = frozenset({'CARRY_LONG'})
    req = request()
    assert evaluate(live, req, token=carry_token(req, signal_ms=signal_ms)).allowed is allowed


def test_unknown_interval_is_rejected(live):
    live.executor.compliance_guard.extra_setup_types = frozenset({'CARRY_LONG'})
    req = request()
    assert evaluate(live, req, token=carry_token(req, interval=900000)).code == 'MISSING_STRATEGY_PROVENANCE'


def test_l2_hook_replaces_bbo_rule_only_when_installed(live):
    req = request()
    ctx = live.provider.load(req)
    thin = replace(ctx, quote=replace(ctx.quote, ask_quantity=D('.1')))
    assert evaluate(live, req, context=thin).code == 'BOOK_MANIPULATION_RISK'          # default BBO rule
    live.executor.compliance_guard.l2_entry_capacity = lambda r: D('5')
    assert evaluate(live, req, context=thin).allowed                                      # enough L2 depth
    live.executor.compliance_guard.l2_entry_capacity = lambda r: D('.1')
    assert evaluate(live, req, context=thin).code == 'BOOK_MANIPULATION_RISK'
