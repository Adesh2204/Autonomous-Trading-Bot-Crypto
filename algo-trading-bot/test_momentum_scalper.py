"""Overnight momentum scalper: signals, geometry, sizing, guards, schedule and restart."""
from decimal import Decimal as D
from types import SimpleNamespace
import json
import threading

import pytest

from exchange.base_exchange import ExchangeError, Position
from exchange.overnight_runtime import OvernightMandate, OvernightRuntime, ScalpLeg, ScalpProtection
from exchange.position_protection import ProtectionPolicy
from exchange.base_exchange import MarketSpec
from strategies.momentum_scalper import (NightGuard, ScalpParams, atr, guaranteed, levels, official_q, setup,
                                         size, trend)

P = ScalpParams()
T0 = 1792800000000 // 300000 * 300000


def bars(closes, step=300000, spread=D('0.5')):
    out = []
    for i, c in enumerate(closes):
        c = D(str(c))
        out.append(dict(t=T0 + i * step, o=c, h=c + spread, l=c - spread, c=c, v=D(1)))
    return out


UP15 = bars([100 + i * 0.5 for i in range(60)], step=900000)
DOWN15 = bars([130 - i * 0.5 for i in range(60)], step=900000)


def five(last):
    return bars([100] * 20 + [last])


# ---------- signals ----------
def test_trend_from_15m_emas():
    assert trend(UP15, P) == 'UP' and trend(DOWN15, P) == 'DOWN' and trend(UP15[:10], P) is None


def test_long_breakout_above_six_bar_high_in_uptrend():
    d = setup(five(101), UP15, P)
    assert d['side'] == 'LONG' and d['reason'] == 'BREAKOUT_WITH_15M_TREND' and d['atr'] > 0


def test_no_breakout_or_counter_trend_gives_no_long():
    assert setup(five(100.4), UP15, P) is None       # below prior high (100.5)
    assert setup(five(101), DOWN15, P) is None       # breakout against the trend


def test_short_breakdown_is_detected_but_blocked_by_committed_scope():
    d = setup(five(99), DOWN15, P)
    assert d['side'] is None and d['detected'] == 'SHORT' and d['reason'] == 'SHORT_PROHIBITED_BY_COMMITTED_SCOPE'
    allowed = ScalpParams(directions=('LONG', 'SHORT'))
    assert setup(five(99), DOWN15, allowed)['side'] == 'SHORT'


def test_trade_guarantee_follows_15m_trend_and_respects_scope():
    assert guaranteed(five(100), UP15, P)['side'] == 'LONG'
    blocked = guaranteed(five(100), DOWN15, P)
    assert blocked['side'] is None and blocked['detected'] == 'SHORT'


# ---------- geometry and sizing ----------
def test_take_profit_is_one_and_a_half_times_stop_with_floor():
    stop, target = levels(D(100), D('1'), 'LONG', P)
    assert (stop, target) == (D(99), D('101.5'))
    stop, target = levels(D(100), D('0.01'), 'LONG', P)     # ATR inside the 0.15% floor
    assert (100 - stop, target - 100) == (D('0.15'), D('0.225'))
    assert levels(D(100), D(1), 'SHORT', P) == (D(101), D('98.5'))


def test_atr_needs_history():
    assert atr(five(100)[:5], 14) is None and atr(five(101), 14) > 0


def test_size_takes_the_smallest_bound_and_halves():
    common = dict(equity=D(100000), risk_fraction=D('0.004'), stop_distance=D('0.15'), price=D(100),
                  participation=D('0.1'))
    assert size(max_notional=D(1000), top_quantity=D(1000), **common) == D(10)        # $1,000 cap
    assert size(max_notional=D(1000), top_quantity=D(50), **common) == D(5)           # 10% of top of book
    assert size(max_notional=D(1000), top_quantity=D(50), half=True, **common) == D('2.5')


# ---------- profit and loss guards ----------
def guard():
    return NightGuard(D('0.3'), D('0.5'), D('0.6'))


def test_t1_lock_halts_on_fallback_to_point_one():
    g = guard()
    assert g.check(D('0.31')) is None and g.hit_t1
    assert g.check(D('0.2')) is None
    assert g.check(D('0.1')) == ('HALT', 'T1_PROFIT_LOCK')


def test_t2_halves_size_then_locks_at_t1():
    g = guard()
    assert g.check(D('0.5')) is None and g.hit_t2 and g.size_factor_half()
    assert g.check(D('0.3')) == ('HALT', 'T2_PROFIT_LOCK')


def test_t3_and_loss_cap_halt():
    assert guard().check(D('0.6')) == ('HALT', 'T3_LOCK_NIGHT_WON')
    assert guard().check(D('-2.0')) == ('HALT', 'LOSS_CAP')
    assert guard().check(D('-1.99')) is None


def test_three_losses_pause_thirty_minutes_then_half_size():
    g = guard()
    for _ in range(3):
        g.trade_closed(D('-1'), T0)
    assert g.paused(T0 + 29 * 60000) and not g.paused(T0 + 30 * 60000) and g.half_size
    g2 = guard()
    g2.trade_closed(D('-1'), T0); g2.trade_closed(D('1'), T0); g2.trade_closed(D('-1'), T0)
    assert g2.losing_streak == 1 and not g2.half_size


def test_official_q_matches_published_formula():
    assert official_q(D(0), D(0)) == D('0.1')
    assert official_q(D('-0.001'), D(0)) < D('0.1') < official_q(D('0.001'), D(0))


# ---------- mandate: committed limits ----------
def mandate(**changes):
    from exchange.competition_windows import SCORED_START_MS, SCORED_END_MS
    from exchange.venue_profiles import venue_profile
    base = dict(team_wallet='0x' + '1' * 40, api_wallet='0x' + '2' * 40, markets=('pas:BTC', 'pas:EWY'),
                starts_ms=SCORED_START_MS + 1, flatten_ms=SCORED_END_MS - 3600000,
                exit_ms=SCORED_END_MS - 3300000, expires_ms=SCORED_END_MS - 2700000,
                starting_equity='100000', source_hash='a' * 64, release_sha256='b' * 64,
                venue_identity=venue_profile('pas').identity, approval_reference='overnight approval',
                t1_pct='0.3', t2_pct='0.5', t3_pct='0.6', target_notes='test')
    return OvernightMandate(**dict(base, **changes))


def test_valid_overnight_mandate():
    assert mandate().require().identity == mandate().identity


@pytest.mark.parametrize('change', [dict(markets=('pas:BTC', 'pas:EWY', 'pas:ETH')), dict(markets=('pas:ETH',)),
    dict(directions=('LONG', 'SHORT')), dict(max_positions=2), dict(leverage=3), dict(max_notional='1001'),
    dict(max_entries_per_hour=3), dict(risk_fraction='0.006'), dict(participation='0.25'),
    dict(loss_cap_pct='-2.5'), dict(t2_pct='0.2'), dict(exit_ms=10 ** 13), dict(dex='par')])
def test_mandate_stays_inside_committed_limits(change):
    with pytest.raises(ExchangeError, match='INVALID_OVERNIGHT_MANDATE'):
        mandate(**change).require()


# ---------- protection geometry ----------
def test_exchange_stop_sits_at_the_planned_stop():
    p = ScalpProtection.__new__(ScalpProtection)
    p.policy = ProtectionPolicy(True, 'x', D(1), D('0.01'))
    p.executor = SimpleNamespace(client=SimpleNamespace(market=lambda s: MarketSpec(s, 2, 20, 1)))
    leg = ScalpLeg('pas:EWY')
    leg.plan_stop = D('99.5')
    position = Position('pas:EWY', D(3), D(100), D(0), D(0), None)
    leg.sync(position)
    plan = p._plan('pas:EWY', position, leg, T0)
    assert (plan.side, plan.trigger_price, plan.limit_price, plan.is_market) == ('SELL', D('99.5'), D('98.505'), True)


def test_adopted_leg_without_plan_uses_default_stop():
    leg = ScalpLeg('pas:BTC')
    leg.sync(Position('pas:BTC', D('0.01'), D(80000), D(0), D(0), None))
    assert leg._open_position['stop_loss_price'] == D(80000) * (1 - ScalpLeg.DEFAULT_ADOPTED_STOP)


# ---------- runtime schedule, guards and restart ----------
class Fake(OvernightRuntime):
    def __init__(self, tmp_path, *, now, positions=None, orders=None, equity=D(100000), state=None):
        self.m = mandate().require()
        self.p = P
        self.state_dir = tmp_path
        self.now = now
        self.clock_ms = lambda: self.now
        self.start_equity = D(100000)
        self._equity = equity
        self._positions = positions or {}
        self._orders = orders or []
        self.calls = []
        self.state = state or dict(mandate='x', halted=None, finished=None, trade=None, trades=[], entries=[],
                                   last_entry_ms=None, guard={})
        self.guard = guard()
        self.order_errors = 0
        self.disconnected_since = None
        self.last_heartbeat = 0
        self.bars = {}
        self.legs = {s: ScalpLeg(s) for s in self.m.markets}
        self.executor = SimpleNamespace(entries_paused=False, journal=SimpleNamespace(event=lambda *a, **k: None))
        self.protection = SimpleNamespace(states={}, entries_allowed=True, ensure_all=lambda **k: None)
        self.stream = SimpleNamespace(connected=True, poll=lambda: None, pending=False, ready=True, healthy=True)
        self.auth = SimpleNamespace(require=lambda *a: None)
        self.account = SimpleNamespace(get_frontend_open_orders=lambda: self._orders)
        self.recovery = SimpleNamespace(recover=lambda: None)

    def positions(self):
        return dict(self._positions)

    def own_orders(self):
        return list(self._orders)

    def equity(self, positions=None):
        return self._equity

    def flatten_all(self, reason):
        self.calls.append(('flatten', reason))
        self._positions, self._orders = {}, []

    def enter(self, symbol, decision, *, half):
        self.calls.append(('enter', symbol, half))
        self.state['entries'].append(self.now)
        self.state['last_entry_ms'] = self.now

    def _bars(self, symbol, interval, count):
        return {'5m': five(101), '15m': UP15}[interval]

    def most_liquid(self):
        return 'pas:BTC'

    def heartbeat(self, force=False):
        self.calls.append(('heartbeat',))

    def verify_flat(self):
        return (not self._positions and not self._orders), [dict(positions=len(self._positions), orders=len(self._orders))]


def held(symbol='pas:BTC'):
    return {symbol: Position(symbol, D('0.01'), D(80000), D(0), D(0), None)}


def test_decides_only_inside_post_close_window_and_once_per_bar(tmp_path):
    r = Fake(tmp_path, now=T0 + 3 * 300000 + 2000)          # 2 s after a close: too early
    r.decide()
    assert not any(c[0] == 'enter' for c in r.calls)
    r.now += 30000
    r.decide(); r.decide()
    assert [c for c in r.calls if c[0] == 'enter'] == [('enter', 'pas:BTC', False)]


def test_never_enters_while_holding_or_beyond_two_entries_per_hour(tmp_path):
    r = Fake(tmp_path, now=T0 + 300000 + 30000, positions=held())
    r.decide()
    assert not any(c[0] == 'enter' for c in r.calls)
    r = Fake(tmp_path, now=T0 + 300000 + 30000)
    r.state['entries'] = [r.now - 10 * 60000, r.now - 20 * 60000]
    r.decide()
    assert not any(c[0] == 'enter' for c in r.calls)


def test_trade_guarantee_half_size_after_45_quiet_minutes(tmp_path, monkeypatch):
    import strategies.momentum_scalper as s
    monkeypatch.setattr(s, 'setup', lambda *a: None)
    r = Fake(tmp_path, now=T0 + 300000 + 30000)
    r.state['last_entry_ms'] = r.now - 46 * 60000
    r.decide()
    assert ('enter', 'pas:BTC', True) in r.calls


def test_loss_cap_halts_and_flattens_in_run_loop(tmp_path):
    r = Fake(tmp_path, now=T0 + 60000, positions=held(), equity=D(98000))
    verdict = r.guard.check(r.pnl_pct(r.equity()))
    r.halt(verdict[1])
    assert r.state['halted']['reason'] == 'LOSS_CAP' and ('flatten', 'LOSS_CAP') in r.calls


def test_three_order_errors_halt_and_flatten(tmp_path):
    r = Fake(tmp_path, now=T0, positions=held())
    for _ in range(3):
        r._note_order_error(ExchangeError('X'), 'entry')
    assert r.state['halted']['reason'] == 'CONSECUTIVE_ORDER_ERRORS' and r.calls[-1][0] == 'flatten'


def test_disconnect_over_three_minutes_halts(tmp_path):
    r = Fake(tmp_path, now=T0)
    r.stream.healthy = False
    for t in (T0, T0 + 120000, T0 + 180001):
        r.now = t
        r._stream_health()
    assert r.state['halted']['reason'] == 'API_DISCONNECT_OVER_3_MIN'


def test_0845_flatten_then_0850_verified_exit_without_new_entries(tmp_path, monkeypatch):
    import exchange.overnight_report as rep
    monkeypatch.setattr(rep, 'official_rank', lambda: dict(rank=10, teams=32, generated_at='t'))
    flatten = mandate().flatten_ms
    r = Fake(tmp_path, now=flatten, positions=held(), orders=[dict(coin='pas:BTC', oid=1)])
    times = iter([flatten + 60000, mandate().exit_ms])
    stop = threading.Event()
    stop.wait = lambda s: setattr(r, 'now', next(times, mandate().exit_ms))
    assert r.run(stop) is True
    assert ('flatten', 'SCHEDULED_FLATTEN_0845_IST') in r.calls and not any(c[0] == 'enter' for c in r.calls)
    assert r.state['finished']['flat'] is True
    report = next(tmp_path.glob('morning_report_*.md')).read_text().splitlines()
    assert report[0].startswith('Net P&L:') and 'rank: #10 of 32' in report[0]
    assert 'positions = 0, orders = 0 -> FLAT VERIFIED' in report[5] and 'git stash pop' in report[6]


def test_restart_adopts_open_position_and_never_double_enters(tmp_path):
    r = Fake(tmp_path, now=T0 + 300000 + 30000, positions=held())
    r.legs['pas:BTC'].sync(held()['pas:BTC'])
    r.cleanup_orders = lambda: None
    r._event = lambda *a, **k: None
    r.startup()
    assert r.state['trade']['reason'] == 'ADOPTED_ON_RESTART' and r.state['trade']['symbol'] == 'pas:BTC'
    r.decide()
    assert not any(c[0] == 'enter' for c in r.calls)


def test_position_outside_committed_scope_is_closed(tmp_path):
    r = Fake(tmp_path, now=T0, positions={'pas:ETH': Position('pas:ETH', D(1), D(2400), D(0), D(0), None)})
    exits = []
    r.exit = lambda s, why: exits.append((s, why))
    r.manage()
    assert exits == [('pas:ETH', 'OUTSIDE_COMMITTED_SCOPE')]


def test_short_position_is_closed_because_scope_is_long_only(tmp_path):
    r = Fake(tmp_path, now=T0, positions={'pas:BTC': Position('pas:BTC', D('-0.01'), D(80000), D(0), D(0), None)})
    exits = []
    r.exit = lambda s, why: exits.append((s, why))
    r.manage()
    assert exits == [('pas:BTC', 'OUTSIDE_COMMITTED_SCOPE')]


# ---------- shared-account barrier ----------
def barrier(monkeypatch, unresolved, status='unknownOid', par_positions=(), owned=()):
    import exchange.terminal_evidence as te
    from exchange.overnight_runtime import SharedAccountBarrier
    monkeypatch.setattr(te, 'local_execution_state', lambda root: dict(
        status='BLOCKED_UNRESOLVED_INTENT' if unresolved else 'NO_LOCAL_UNRESOLVED_INTENT', unresolved=list(unresolved)))
    reads = dict(clearinghouseState=dict(assetPositions=[dict(position=dict(szi=s)) for s in par_positions]),
                 openOrders=[], frontendOpenOrders=[])
    client = SimpleNamespace(clock_ms=lambda: T0, transport=lambda payload: reads[payload['type']],
                             read_cancel_event=None, rate_limits=SimpleNamespace(read=lambda kind, op, **k: op()))
    account = SimpleNamespace(_query=lambda q, **k: dict(status=status))
    return SharedAccountBarrier('.', account, client, lambda: set(owned))


def historical():
    from exchange.configuration_isolation import CLOID, INTENT
    return dict(journal='qualification', cloid=CLOID, state='UNKNOWN', intent_key=INTENT)


def test_barrier_exempts_only_the_exact_historical_intent_while_exchange_reports_it_unknown(monkeypatch):
    barrier(monkeypatch, [historical()]).require()
    barrier(monkeypatch, [dict(journal='pas', intent_key='mine', state='OPEN')], owned={'mine'}).require()
    with pytest.raises(ExchangeError, match='HISTORICAL_QUALIFICATION_INTENT_STATE_CHANGED'):
        barrier(monkeypatch, [historical()], status='order').require()


@pytest.mark.parametrize('row', [dict(journal='qualification', cloid='0x1', state='UNKNOWN', intent_key='other'),
                                 dict(journal='pas', intent_key='foreign', state='OPEN')])
def test_barrier_blocks_any_other_unresolved_intent(monkeypatch, row):
    with pytest.raises(ExchangeError, match='SHARED_ACCOUNT_UNRESOLVED_INTENT_BLOCKS_SIGNING'):
        barrier(monkeypatch, [historical(), row]).require()


def test_barrier_blocks_par_exposure(monkeypatch):
    with pytest.raises(ExchangeError, match='OTHER_DEX_EXPOSURE'):
        barrier(monkeypatch, [], par_positions=['0.1']).require()
