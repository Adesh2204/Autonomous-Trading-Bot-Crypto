"""Day session: SHORT entries/exits, P&L sign, rank protection and per-entry exchange verification."""
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from exchange.base_exchange import MarketSpec, Position
from exchange.day_runtime import DayRuntime, live_q
from exchange.overnight_runtime import OvernightRuntime, ScalpLeg
from strategies.momentum_scalper import DayGuard, ScalpParams, estimated_rank, guaranteed, setup
from test_momentum_scalper import DOWN15, T0, Fake, five, mandate
from test_live_exchange_execution import live  # noqa: F401  (offline signed fixture)

BOTH = ScalpParams(directions=('LONG', 'SHORT'))


def test_short_breakdown_and_guarantee_trade_when_short_is_permitted():
    assert setup(five(99), DOWN15, BOTH)['side'] == 'SHORT'
    assert guaranteed(five(100), DOWN15, BOTH)['side'] == 'SHORT'


class Exchange(Fake):
    """Fake runtime whose executor fills IOC orders and rests reduce-only take-profits."""
    def __init__(self, tmp_path, **kw):
        super().__init__(tmp_path, now=T0, **kw)
        self.m = mandate(directions=('LONG', 'SHORT')).require()
        self.p = BOTH
        self.requests = []
        self.preflight = lambda **k: None
        self.last_account_ms = 0
        self.client = SimpleNamespace(market=lambda s: MarketSpec(s, 2, 20, 1))
        self.market = SimpleNamespace(get_quote=lambda s: SimpleNamespace(
            bid=D('99.9'), ask=D('100.1'), mid=D('100'), bid_quantity=D(80), ask_quantity=D(80)))
        self.executor = SimpleNamespace(entries_paused=False, submit=self._submit, cancel_order=lambda *a, **k: None,
                                        recover_uncertain=lambda key: None, journal=SimpleNamespace(event=lambda *a, **k: None))

    def _submit(self, request, permission):
        self.requests.append((request, permission))
        if not request.reduce_only:
            sign = 1 if request.side == 'BUY' else -1
            self._positions[request.symbol] = Position(request.symbol, sign * request.quantity, request.price,
                                                       D(0), D(0), None)
            return SimpleNamespace(state=SimpleNamespace(value='FILLED'), exchange_order_id='1')
        if request.tif == 'Gtc':
            self._orders.append(dict(coin=request.symbol, oid=2, isTrigger=False, reduceOnly=True,
                                     side='A' if request.side == 'SELL' else 'B', sz=str(request.quantity)))
            return SimpleNamespace(state=SimpleNamespace(value='OPEN'), exchange_order_id='2')
        self._positions.pop(request.symbol, None)
        return SimpleNamespace(state=SimpleNamespace(value='FILLED'), exchange_order_id='3')

    def equity(self, positions=None):
        return D(100000)


def short_decision():
    return dict(side='SHORT', atr=D('0.5'), reason='BREAKDOWN', signal_ms=T0 - 60000, bar_ms=T0 - 300000)


def test_short_entry_sells_at_bid_with_stop_above_and_reduce_only_tp_below(tmp_path):
    r = Exchange(tmp_path)
    OvernightRuntime.enter(r, 'pas:EWY', short_decision(), half=False)
    (entry, eperm), (tp, tperm) = r.requests
    assert (entry.side, entry.price, entry.reduce_only, entry.tif, entry.strategy_id) == \
        ('SELL', D('99.9'), False, 'Ioc', 'MOMENTUM_SHORT')
    assert entry.quantity == D('8') and eperm.provenance.setup_type == 'MOMENTUM_SHORT'   # 10% of 80 at top of book
    trade = r.state['open']['pas:EWY']
    assert trade['side'] == 'SHORT' and D(trade['stop']) > D('99.9') > D(trade['target'])
    assert (tp.side, tp.reduce_only, tp.tif, tp.price) == ('BUY', True, 'Gtc', D(trade['target']).quantize(D('0.01')))
    assert tperm.provenance.classification == 'STRATEGY_EXIT'


def test_short_exit_is_a_reduce_only_buy(tmp_path):
    r = Exchange(tmp_path)
    r._positions = {'pas:EWY': Position('pas:EWY', D(-8), D('99.9'), D(0), D(0), None)}
    r.state['open'] = {}
    OvernightRuntime.exit(r, 'pas:EWY', 'TIME_STOP_60_MIN')
    request, permission = r.requests[-1]
    assert (request.side, request.reduce_only, request.quantity) == ('BUY', True, D(8))
    assert permission.provenance.classification == 'PROTECTIVE_EXIT' and permission.reason == 'TIME_STOP_60_MIN'


@pytest.mark.parametrize('closed,fee,expected', [('2.40', '0.20', D('2.20')), ('-1.10', '0.20', D('-1.30'))])
def test_short_trade_net_uses_exchange_reported_pnl_sign(tmp_path, closed, fee, expected):
    r = Exchange(tmp_path)
    fills = [SimpleNamespace(symbol='pas:EWY', closed_pnl=D(0), fee=D('0.10')),
             SimpleNamespace(symbol='pas:EWY', closed_pnl=D(closed), fee=D(fee) - D('0.10'))]
    r.account = SimpleNamespace(get_fills=lambda **k: fills)
    r._closed_trade(dict(symbol='pas:EWY', side='SHORT', entry_ms=T0))
    assert D(r.state['trades'][-1]['net']) == expected
    assert r.guard.losing_streak == (1 if expected < 0 else 0)


def test_short_position_is_kept_when_short_is_permitted(tmp_path):
    r = Exchange(tmp_path)
    r._positions = {'pas:EWY': Position('pas:EWY', D(-8), D('99.9'), D(0), D(0), None)}
    r.protection = SimpleNamespace(states={'pas:EWY': dict(status='ACTIVE')}, ensure_all=lambda **k: None)
    r.state['open'] = {'pas:EWY': dict(symbol='pas:EWY', side='SHORT', entry_ms=T0, tp_key='k', target='99')}
    exits = []
    r.exit = lambda s, why: exits.append(why)
    r.manage()
    assert exits == []


# ---------- rank protection ----------
def test_lock_fires_once_and_pauses_until_rank_slips():
    g = DayGuard(lock=D('0.08'))
    assert g.check(D('0.05')) is None
    assert g.check(D('0.081')) == ('LOCK', 'LOCK_REACHED') and g.paused(T0)
    assert g.check(D('0.09')) is None
    assert not g.resume_if_below(6) and g.locked
    assert g.resume_if_below(7) and not g.paused(T0) and g.size_factor_half()


def test_day_loss_cap_halts_at_minus_point_three():
    assert DayGuard(lock=D('0.08')).check(D('-0.30')) == ('HALT', 'LOSS_CAP_0_30_PCT')
    assert DayGuard(lock=D('0.08')).check(D('-0.29')) is None


def test_live_q_and_estimated_rank_follow_published_formula():
    assert live_q(D(0), 5) == D('0.1')
    assert live_q(D('0.0414'), 5) > D('0.10607') > live_q(D('0.0412'), 5)
    assert estimated_rank(D('0.107'), [D('0.27'), D('0.17'), D('0.16'), D('0.115'), D('0.109'), D('0.106')]) == 6


# ---------- per-entry exchange verification ----------
class Verify(DayRuntime):
    def __init__(self, tmp_path, positions, orders):
        Fake.__init__(self, tmp_path, now=T0, positions=positions, orders=orders)
        self.m = mandate(directions=('LONG', 'SHORT')).require()
        self.guard = DayGuard(lock=D('0.08'))
        self.account = SimpleNamespace(get_frontend_open_orders=lambda: self._orders)
        self.state['open'] = {'pas:EWY': dict(symbol='pas:EWY', side='SHORT', quantity='-8', entry_ms=T0 - 6000)}

    positions = Fake.positions
    flatten_all = Fake.flatten_all
    equity = Fake.equity


SHORT_POS = {'pas:EWY': Position('pas:EWY', D(-8), D('99.9'), D(0), D(0), None)}
STOP = dict(coin='pas:EWY', oid=1, isTrigger=True, reduceOnly=True, side='B', sz='8', triggerPx='100.05')
TP = dict(coin='pas:EWY', oid=2, isTrigger=False, reduceOnly=True, side='B', sz='8', limitPx='99.6')


def test_first_entry_verification_passes_with_position_stop_and_tp(tmp_path):
    r = Verify(tmp_path, dict(SHORT_POS), [STOP, TP])
    assert r.verify_entry('pas:EWY', first=True) and r.state['first_trade_verified']['elapsed_s'] == 6
    assert r.state['halted'] is None


@pytest.mark.parametrize('orders,problem', [([TP], 'EXCHANGE_STOP_COUNT 0'), ([STOP], 'EXCHANGE_TAKE_PROFIT_COUNT 0'),
    ([dict(STOP, side='A'), TP], 'EXCHANGE_STOP_COUNT 0'), ([STOP, dict(TP, sz='7')], 'EXCHANGE_TAKE_PROFIT_COUNT 0')])
def test_failed_verification_flattens_and_halts_without_retry(tmp_path, orders, problem):
    r = Verify(tmp_path, dict(SHORT_POS), orders)
    assert not r.verify_entry('pas:EWY', first=True)
    assert problem in r.state['halted']['reason'] and ('flatten', r.state['halted']['reason']) in r.calls
    assert not r.state.get('first_trade_verified')


def test_wrong_side_is_a_verification_failure(tmp_path):
    r = Verify(tmp_path, {'pas:EWY': Position('pas:EWY', D(8), D('99.9'), D(0), D(0), None)},
               [dict(STOP, side='A'), dict(TP, side='A')])
    assert not r.verify_entry('pas:EWY', first=True) and 'POSITION_SIDE LONG' in r.state['halted']['reason']


def test_real_day_heartbeat_writes_status_with_score_rank_and_lock(tmp_path, monkeypatch):
    import json
    import exchange.day_runtime as dr
    board = dict(generated_at='g', teams=[dict(name='Team Anchorium', rank=10, q=0.1),
                 dict(name='A', rank=1, q=0.2), dict(name='B', rank=2, q=0.105)])
    monkeypatch.setattr(dr, 'fetch_leaderboard', lambda: board)
    r = Verify(tmp_path, dict(SHORT_POS), [STOP, TP])
    r.targets = dict(lock_pct='0.0808', days=5)
    r.prior_return_pct = D(0)
    r.start_equity = D(100000)
    r._equity = D(100010)
    r.board = None
    r.stream = SimpleNamespace(healthy=True)
    r.state['trades'] = [dict(net='1')]
    DayRuntime.heartbeat(r, force=True)
    status = json.loads((tmp_path / 'status.json').read_text())
    assert status['return_pct'] == '0.01000' and status['estimated_rank'] == 3 and status['published_rank'] == 10
    assert status['lock'] == dict(target_pct='0.0808', locked=False, resumed_half=False)
    assert status['position'][0]['side'] == 'SHORT' and status['trades'] == 1


def test_full_day_lifecycle_runs_real_code_paths_end_to_end(tmp_path, monkeypatch):
    """startup -> heartbeat -> decide -> entry -> exchange verification -> 17:45 flatten -> 17:50 report."""
    import threading
    import exchange.day_runtime as dr
    from exchange.overnight_runtime import OvernightRuntime as O
    board = dict(generated_at='g', teams=[dict(name='Team Anchorium', rank=10, q=0.1), dict(name='A', rank=1, q=0.2)])
    monkeypatch.setattr(dr, 'fetch_leaderboard', lambda: board)

    class Live(Exchange, DayRuntime):
        enter = DayRuntime.enter
        verify_entry = DayRuntime.verify_entry
        heartbeat = DayRuntime.heartbeat
        _write_report = DayRuntime._write_report
        _apply_verdict = DayRuntime._apply_verdict
        _save = DayRuntime._save
        decide = DayRuntime.decide
        pnl_pct = DayRuntime.pnl_pct
        leaderboard = DayRuntime.leaderboard
        estimate = DayRuntime.estimate
        startup = O.startup
        cleanup_orders = O.cleanup_orders
        flatten_all = O.flatten_all
        exit = O.exit
        manage = O.manage

    r = Live(tmp_path)
    r.targets = dict(lock_pct='0.0808', r6_pct='0.0413', r5_pct='0.0651', days=5)
    r.report_path = tmp_path / 'report.md'
    r.guard = DayGuard(lock=D('0.0808'), loss_cap=D('-0.30'))
    r.prior_return_pct, r.board, r.board_ms = D(0), None, None
    r.stream = SimpleNamespace(healthy=True, background_receiving=True, receiver_fatal=None, pending=False,
                               connected=True, ready=True)
    r.account = SimpleNamespace(get_frontend_open_orders=lambda: r._orders, get_fills=lambda **k: [])

    def ensure_all(**k):            # exchange-side stop appears for any open position, vanishes when flat
        r._orders = [o for o in r._orders if not o.get('isTrigger')]
        for s, p in r._positions.items():
            r._orders.append(dict(coin=s, oid=9, isTrigger=True, reduceOnly=True, side='A' if p.quantity > 0 else 'B',
                                  sz=str(abs(p.quantity))))
        for s in [o['coin'] for o in r._orders if o['coin'] not in r._positions]:
            r._orders = [o for o in r._orders if o['coin'] in r._positions]
    class Protection:
        entries_allowed = True
        states = property(lambda self: {s: dict(status='ACTIVE') for s in r._positions})

        def ensure_all(self, **k):
            ensure_all()
    r.protection = Protection()
    flatten, exit_ms = r.m.flatten_ms, r.m.exit_ms
    r.now = T0 + 300000 * 7 + 20000                          # inside a post-close decision window
    times = iter([flatten, flatten + 30000, exit_ms])
    stop = threading.Event()

    def wait(seconds):
        r.now = next(times, exit_ms)
    stop.wait = wait
    assert r.run(stop) is True
    events = [__import__('json').loads(x) for x in (tmp_path / 'overnight_events.jsonl').read_text().splitlines()]
    kinds = [e['kind'] for e in events]
    assert 'ENTRY_VERIFIED' in kinds and 'SCHEDULED_FLATTEN_0845_IST' in kinds and kinds[-1] == 'FINISHED'
    assert r.state['first_trade_verified'] and r.state['finished']['flat'] and r._positions == {} and r._orders == []
    report = r.report_path.read_text().splitlines()
    assert report[0].startswith('Final return:') and 'published #10' in report[0]
    assert 'FLAT VERIFIED' in report[-1] and 'PASSED' in report[3]
    assert (tmp_path / 'status.json').exists()


@pytest.mark.parametrize('entry,age_ms,refreshed', [(True, 3001, True), (True, 3000, False), (False, 10000, False)])
def test_entry_boundary_reverifies_protection_read_only_when_stale(monkeypatch, entry, age_ms, refreshed):
    from exchange.carry_runtime import CarryExecution
    from exchange.hyperliquid_execution import HyperliquidExecution
    calls = []
    monkeypatch.setattr(HyperliquidExecution, '_guard', lambda self, *a, **k: calls.append('base'))
    e = CarryExecution.__new__(CarryExecution)
    e.client = SimpleNamespace(clock_ms=lambda: T0)
    e.protection = SimpleNamespace(last_verified_ms=T0 - age_ms,
                                   ensure_all=lambda **k: calls.append(('ensure_all', k)))
    e._guard(None, T0, entry=entry)
    assert calls == ([('ensure_all', dict(allow_actions=False)), 'base'] if refreshed else ['base'])


def test_fresh_read_precedes_the_entry_quote_and_the_take_profit(tmp_path):
    r = Exchange(tmp_path)
    order = []
    r.preflight = lambda **k: order.append(('fresh', k.get('entry', False)))
    quote = r.market.get_quote
    r.market = SimpleNamespace(get_quote=lambda s: order.append('quote') or quote(s))
    r.protection = SimpleNamespace(states={}, entries_allowed=True, ensure_all=lambda **k: order.append('stop'))
    OvernightRuntime.enter(r, 'pas:EWY', short_decision(), half=False)
    # entry: fresh read (entry budget) -> quote; stop: protection hook; TP: fresh read before its permission
    assert order == [('fresh', True), 'quote', 'stop', ('fresh', False)]


def test_entry_is_skipped_not_errored_when_the_read_budget_has_no_room(tmp_path):
    from exchange.base_exchange import ExchangeError
    r = Exchange(tmp_path)

    def short(**k):
        raise ExchangeError('ENTRY_READ_BUDGET_HEADROOM_UNAVAILABLE')
    r.preflight = short
    assert OvernightRuntime.enter(r, 'pas:EWY', short_decision(), half=False) is None
    assert r.requests == [] and r.state['entries'] == []


def test_real_submit_path_signs_entry_after_slow_context_load(live):
    """Real CarryExecution + ScalpProtection + compliance + validator on the offline signed fixture."""
    from exchange.carry_runtime import BasketPositionGuard, CarryExecution
    from exchange.order_lifecycle import OrderRequest
    from exchange.overnight_runtime import OvernightRuntime as O, ScalpProtection
    from exchange.exchange_rules import RiskPermission
    from exchange.position_protection import ProtectionPolicy
    from test_live_exchange_execution import response
    e = CarryExecution(live.client, transport=live.transport, account=live.account, journal=live.journal,
                       context_provider=live.provider, validator=live.validator, recovery=live.executor.recovery,
                       clock_health=live.clock, rate_limits=live.rate)
    e.entries_paused, e.max_positions, e.allowed_markets = False, 1, frozenset({'par:BTC'})
    e.position_guard = BasketPositionGuard(live.journal, clock_ms=live.client.clock_ms, max_positions=1)
    e.compliance_guard.position_guard = e.position_guard
    e.compliance_guard.extra_setup_types = frozenset({'MOMENTUM_LONG'})
    protection = ScalpProtection(e, policy=ProtectionPolicy(True, 'x', D(1), D('0.01')), managers={})
    protection.ensure_all(allow_actions=False)
    assert protection.entries_allowed
    live.fixture.now += 3000                                   # preflight barrier, sizing, quote
    live.fixture.book['time'] = live.fixture.now
    original = live.provider.load

    def slow_load(request, **k):                               # ~4.2 s of sequential reads, as measured live
        live.fixture.now += 4200
        live.fixture.book['time'] = live.fixture.now           # the exchange returns a fresh book
        return original(request, **k)
    live.provider.load = slow_load
    req = OrderRequest('par:BTC', 'BUY', D('.2'), D('100'), tif='Ioc', strategy_id='MOMENTUM_LONG', client_order_id='k1')
    prov = O._provenance(None, 'k1', req, setup='MOMENTUM_LONG', signal_ms=live.fixture.now - 90000)
    perm = RiskPermission('k1', 'par:BTC', 'BUY', D('.2'), live.fixture.now, limit_price=D('100'), provenance=prov)
    live.transport.responses = [response({'filled': {'oid': 11, 'totalSz': '.2', 'avgPx': '99.98'}})]
    e.submit(req, permission=perm)
    assert len(live.transport.signed_payloads) == 1
