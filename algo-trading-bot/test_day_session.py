"""Day session: SHORT entries/exits, P&L sign, rank protection and per-entry exchange verification."""
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from exchange.base_exchange import MarketSpec, Position
from exchange.day_runtime import DayRuntime, live_q
from exchange.overnight_runtime import OvernightRuntime, ScalpLeg
from strategies.momentum_scalper import DayGuard, ScalpParams, estimated_rank, guaranteed, setup
from test_momentum_scalper import DOWN15, T0, Fake, five, mandate

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
        self.preflight = lambda: None
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
    trade = r.state['trade']
    assert trade['side'] == 'SHORT' and D(trade['stop']) > D('99.9') > D(trade['target'])
    assert (tp.side, tp.reduce_only, tp.tif, tp.price) == ('BUY', True, 'Gtc', D(trade['target']).quantize(D('0.01')))
    assert tperm.provenance.classification == 'STRATEGY_EXIT'


def test_short_exit_is_a_reduce_only_buy(tmp_path):
    r = Exchange(tmp_path)
    r._positions = {'pas:EWY': Position('pas:EWY', D(-8), D('99.9'), D(0), D(0), None)}
    r.state['trade'] = None
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
    r.state['trade'] = dict(symbol='pas:EWY', side='SHORT', entry_ms=T0, tp_key='k', target='99')
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
        self.state['trade'] = dict(symbol='pas:EWY', side='SHORT', quantity='-8', entry_ms=T0 - 6000)

    positions = Fake.positions
    flatten_all = Fake.flatten_all


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
