"""Bug #11 (fills are exchange truth) and bug #12 (a stop-update error is not a missing stop), 25 Oct.

Fixtures are the actual 25 Oct exchange rows for the HYPE short (10:35 UTC) and the BTC long
whose stop re-plan was rejected as DUPLICATE_ORDER (00:51 UTC).
"""
from decimal import Decimal as D
from types import SimpleNamespace

from exchange.base_exchange import Fill, Position
from exchange.compliance_guard import stop_beside_resting_take_profit
from exchange.fill_ledger import missing_trades, round_trips, stop_slippage_bps
from exchange.overnight_runtime import OvernightRuntime, ScalpProtection, STOP_REPAIR_READS
from exchange.position_protection import ProtectionStatus
from test_momentum_scalper import Fake, T0, held

HYPE_OPEN = dict(coin='pas:HYPE', side='A', sz='1.65', px='75.38', time=1792924525208, tid=113467239712450,
                 oid=63639699829, fee='0.111939', closedPnl='0.0', startPosition='0.0', feeToken='USDP')
HYPE_STOP = dict(coin='pas:HYPE', side='B', sz='1.65', px='75.53', time=1792924579960, tid=467890023547459,
                 oid=63639746376, fee='0.112162', closedPnl='-0.2475', startPosition='-1.65', feeToken='USDP')
HYPE_NET = D('-0.2475') - D('0.111939') - D('0.112162')          # -0.471601


def fill(row):
    return Fill(row['coin'], row['time'], str(row['tid']), str(row['oid']), 'BUY' if row['side'] == 'B' else 'SELL',
                D(row['sz']), D(row['px']), D(row['fee']), 'USDP', D(row['closedPnl']), D(row['startPosition']),
                'EXCHANGE_REPORTED_FILL')


# ---------- fill ledger ----------
def test_round_trip_from_the_actual_hype_fills():
    closed, open_ = round_trips([HYPE_STOP, HYPE_OPEN])
    assert open_ == {} and len(closed) == 1
    t = closed[0]
    assert (t['symbol'], t['side'], t['quantity'], t['net']) == ('pas:HYPE', 'SHORT', D('1.65'), HYPE_NET)
    assert (t['entry'], t['exit']) == (D('75.38'), D('75.53'))


def test_missing_trade_is_reported_once_and_partial_records_are_conflicts():
    missing, conflicts, _ = missing_trades([fill(HYPE_OPEN), fill(HYPE_STOP)], recorded_tids=set())
    assert len(missing) == 1 and conflicts == []
    missing, conflicts, _ = missing_trades([fill(HYPE_OPEN), fill(HYPE_STOP)], {str(HYPE_OPEN['tid']), str(HYPE_STOP['tid'])})
    assert missing == [] and conflicts == []
    missing, conflicts, _ = missing_trades([fill(HYPE_OPEN), fill(HYPE_STOP)], {str(HYPE_STOP['tid'])})
    assert missing == [] and len(conflicts) == 1


def test_stop_slippage_is_measured_against_the_trigger():
    assert round(stop_slippage_bps('75.53', '75.473', 'SHORT'), 2) == D('7.55')
    assert round(stop_slippage_bps('80353', '80402', 'LONG'), 2) == D('6.09')


# ---------- runtime: the placement response says 0, the exchange fills say otherwise ----------
class FillsFake(Fake):
    """The real enter()/manage()/reconcile_fills() over scripted exchange truth."""
    def __init__(self, tmp_path, *, fills, after_submit_positions, **kw):
        super().__init__(tmp_path, **kw)
        self._fills = fills
        self._after_submit = after_submit_positions
        self.events = []
        self.protected, self.tps = [], []
        self.saved = 0
        spec = SimpleNamespace(normalize_size=lambda q: q.quantize(D('0.01')), normalize_price=lambda p, side: p)
        self.client = SimpleNamespace(market=lambda s: spec)
        self.market = SimpleNamespace(get_quote=lambda s: SimpleNamespace(bid=D('75.36'), ask=D('75.40'),
                                                                          bid_quantity=D(100), ask_quantity=D(100),
                                                                          mid=D('75.38')))
        self.preflight = lambda **k: None
        result = SimpleNamespace(state=SimpleNamespace(value='FILLED'), exchange_order_id=str(HYPE_OPEN['oid']))

        def submit(request, permission):
            self._positions = dict(self._after_submit)
            return result
        self.executor.submit = submit
        self.account = SimpleNamespace(get_frontend_open_orders=lambda: [], get_fills=lambda **k: list(self._fills))

        def ensure_all(**k):
            self.protected.append(sorted(self._positions))
            self.protection.states = {s: dict(status='ACTIVE') for s in self._positions}
        self.protection = SimpleNamespace(states={}, entries_allowed=True, ensure_all=ensure_all)

    def _event(self, kind, **data):
        self.events.append((kind, data))

    def _save(self):
        self.saved += 1

    def place_take_profit(self, symbol):
        self.tps.append(symbol)
        self.state['open'][symbol]['tp_key'] = 'tp'

    def enter(self, symbol, decision, *, half):
        return OvernightRuntime.enter(self, symbol, decision, half=half)


def with_hype(r):
    from exchange.overnight_runtime import ScalpLeg
    from test_momentum_scalper import mandate
    r.m = mandate(markets=('pas:BTC', 'pas:HYPE'), directions=('LONG', 'SHORT')).require()
    r.legs = {s: ScalpLeg(s) for s in r.m.markets}


DECISION = dict(side='SHORT', atr=D('0.0351'), reason='BREAKOUT_WITH_15M_TREND', signal_ms=T0 - 60000)


def test_filled_and_stopped_before_the_first_read_is_booked_from_fills(tmp_path):
    """The HYPE case: placement says FILLED, the position read says 0, the fills say a full round trip."""
    r = FillsFake(tmp_path, now=T0, fills=[fill(HYPE_OPEN), fill(HYPE_STOP)], after_submit_positions={})
    with_hype(r)
    r.enter('pas:HYPE', DECISION, half=False)
    result = dict(r.events)['ENTRY_RESULT']
    assert result['filled'] == D('-1.65') and result['position'] == 0 and result['fills'] == 1
    assert [t['net'] for t in r.state['trades']] == [str(HYPE_NET)]
    assert r.state['trades'][0]['reason'] == 'RECONCILED_FROM_EXCHANGE_FILLS'
    assert r.guard.losing_streak == 1                      # counted toward the losing streak
    # The loss cap reads exchange equity; the booked net is exactly what equity lost.
    assert D(r.state['trades'][0]['net']) == sum(f.closed_pnl - f.fee for f in r._fills)
    r.reconcile_fills(force=True)
    assert len(r.state['trades']) == 1 and r.guard.losing_streak == 1      # never booked twice


def test_late_visible_position_is_adopted_and_gets_stop_and_take_profit(tmp_path):
    """Placement says filled 0 and the first read is empty, but the exchange holds the short."""
    r = FillsFake(tmp_path, now=T0, fills=[fill(HYPE_OPEN)], after_submit_positions={})
    with_hype(r)
    r.enter('pas:HYPE', DECISION, half=False)
    assert r.state['trades'] == [] and r.state['open'] == {}
    r._positions = {'pas:HYPE': Position('pas:HYPE', D('-1.65'), D('75.38'), D(0), D(0), None)}
    r.manage()
    assert r.state['open']['pas:HYPE']['reason'] == 'ADOPTED_FROM_EXCHANGE_FILL'
    assert r.state['open']['pas:HYPE']['entry_ms'] == HYPE_OPEN['time']      # entry time from the fill
    assert r.protected and r.tps == ['pas:HYPE']                             # SL ensured and TP placed
    # It then closes on the exchange: booked once from fills, counted in the streak.
    r._fills = [fill(HYPE_OPEN), fill(HYPE_STOP)]
    r._positions = {}
    r.manage()
    assert [t['net'] for t in r.state['trades']] == [str(HYPE_NET)] and r.guard.losing_streak == 1
    assert r.reconcile_fills(force=True) == []


def test_reconcile_every_30_s_inserts_a_trade_the_journal_missed(tmp_path):
    r = FillsFake(tmp_path, now=T0, fills=[fill(HYPE_OPEN), fill(HYPE_STOP)], after_submit_positions={})
    assert len(r.reconcile_fills()) == 1 and r.guard.losing_streak == 1
    r.now += 10000
    assert r.reconcile_fills() == []                    # throttled inside 30 s
    r.now += 30000
    assert r.reconcile_fills() == [] and len(r.state['trades']) == 1


# ---------- bug #12: stop update ----------
def test_stop_beside_a_resting_take_profit_is_not_a_duplicate():
    stop = SimpleNamespace(strategy_id='CATASTROPHIC_STOP', reduce_only=True)
    tp_row, tp_req = dict(oid='63607567954'), dict(strategy_id='MOMENTUM_TP', reduce_only=True)
    open_orders = [dict(oid=63607567954, isTrigger=False, reduceOnly=True)]
    assert stop_beside_resting_take_profit(stop, tp_req, tp_row, open_orders)
    # A second stop, a non-reduce-only order, or an order no longer resting stays a duplicate.
    assert not stop_beside_resting_take_profit(stop, dict(tp_req, strategy_id='CATASTROPHIC_STOP'), tp_row, open_orders)
    assert not stop_beside_resting_take_profit(stop, dict(tp_req, reduce_only=False), tp_row, open_orders)
    assert not stop_beside_resting_take_profit(stop, tp_req, tp_row, [dict(open_orders[0], isTrigger=True)])
    assert not stop_beside_resting_take_profit(SimpleNamespace(strategy_id='MOMENTUM_TP', reduce_only=True),
                                               tp_req, tp_row, open_orders)


BTC_LONG = Position('pas:BTC', D('0.00061'), D('80776'), D(0), D(0), None)
BTC_STOP = dict(coin='pas:BTC', oid=63607513616, isTrigger=True, reduceOnly=True, orderType='Stop Market', side='A',
                sz='0.00061', triggerPx='80657.0', limitPx='79851.0', cloid='0xabc', intent_key='protection:pas:BTC:11')


def protection(orders, position=BTC_LONG):
    p = ScalpProtection.__new__(ScalpProtection)
    p.states = {'pas:BTC': dict(status='ERROR', reason='DUPLICATE_ORDER')}
    p.account = SimpleNamespace(get_position=lambda s: position, get_frontend_open_orders=lambda: orders)
    p._discover = lambda o: ({'pas:BTC': [x for x in o if x['coin'] == 'pas:BTC']}, [])
    p.journal = SimpleNamespace(event=lambda *a, **k: None)
    p.clock_ms = lambda: T0
    p.executor = SimpleNamespace(entries_paused=False)
    return p


def test_duplicate_order_error_with_a_valid_existing_stop_keeps_the_position():
    p = protection([BTC_STOP, dict(BTC_STOP, oid=1, isTrigger=False, orderType='Limit', triggerPx='0')])
    p.keep_valid_existing_stops()
    assert p.states['pas:BTC']['status'] == ProtectionStatus.ACTIVE.value
    assert p.states['pas:BTC']['reason'] == 'KEPT_EXISTING_STOP_AFTER_UPDATE_ERROR'
    assert p.states['pas:BTC']['update_error'] == 'DUPLICATE_ORDER'


def test_an_invalid_existing_stop_is_not_kept():
    for bad in (dict(BTC_STOP, sz='0.0003'), dict(BTC_STOP, side='B'), dict(BTC_STOP, reduceOnly=False),
                dict(BTC_STOP, isTrigger=False)):
        p = protection([bad])
        p.keep_valid_existing_stops()
        assert p.states['pas:BTC']['status'] == 'ERROR'


class StopFake(Fake):
    def __init__(self, tmp_path, statuses):
        super().__init__(tmp_path, now=T0, positions=held())
        self.state['open'] = {'pas:BTC': dict(symbol='pas:BTC', entry_ms=T0, tp_key='tp')}
        self.statuses = list(statuses)
        self.reads, self.exits, self.events = 0, [], []

        def ensure_all(**k):
            self.reads += 1
            status = self.statuses.pop(0) if self.statuses else 'ERROR'
            self.protection.states = {'pas:BTC': dict(status=status)}
        self.protection = SimpleNamespace(states={'pas:BTC': dict(status='ERROR')}, entries_allowed=True,
                                          ensure_all=ensure_all)
        self.exit = lambda s, why: self.exits.append((s, why))
        self._event = lambda kind, **d: self.events.append(kind)


def test_kept_stop_after_a_duplicate_error_means_no_exit(tmp_path):
    r = StopFake(tmp_path, ['ACTIVE'])          # ensure_all kept the valid existing stop
    r.manage()
    assert r.exits == [] and r.reads == 1


def test_missing_stop_is_re_placed_on_the_second_fresh_read(tmp_path):
    r = StopFake(tmp_path, ['MISSING', 'ACTIVE'])
    r.manage()
    assert r.exits == [] and r.reads == 2 and r.events.count('STOP_REPAIR_RETRY') == 1


def test_still_missing_after_two_fresh_reads_flattens(tmp_path):
    r = StopFake(tmp_path, ['ERROR', 'MISSING', 'ACTIVE'])
    r.manage()
    assert r.exits == [('pas:BTC', 'EXCHANGE_STOP_NOT_ACTIVE')] and r.reads == STOP_REPAIR_READS == 2


# ---------- Phase 1.3: request budget is measured per entry cycle ----------
def test_entry_cycle_logs_the_weight_it_used(tmp_path):
    r = Fake(tmp_path, now=T0 + 3 * 300000 + 20000)
    rates = SimpleNamespace(total_weight=1000, weight_by_query={'l2Book': 4})
    r.executor.rate_limits = rates
    events = []
    r._event = lambda kind, **d: events.append((kind, d))

    def enter(symbol, decision, *, half):
        rates.total_weight += 312
        rates.weight_by_query = {'l2Book': 8, 'frontendOpenOrders': 40}
        r.state['entries'].append(r.now)
    r.enter = enter
    r.decide()
    cycle = [d for k, d in events if k == 'ENTRY_CYCLE_WEIGHT']
    assert cycle and cycle[0]['weight'] == 312 and cycle[0]['by_query'] == {'l2Book': 4, 'frontendOpenOrders': 40}


def test_three_markets_are_evaluated_inside_one_minute_of_read_budget(tmp_path):
    """Signal evaluation for BTC/EWY/HYPE: 5m + 15m candles per market, cached per bar."""
    from exchange.rate_limits import HyperliquidRateLimitManager
    from test_momentum_scalper import mandate, five, UP15
    from exchange.execution_journal import ExecutionJournal
    journal = ExecutionJournal(tmp_path / 'j.sqlite', session_id='budget-test', team_address='0x' + '1' * 40)
    rates = HyperliquidRateLimitManager(journal, clock_ms=lambda: T0)
    r = Fake(tmp_path, now=T0 + 3 * 300000 + 20000)
    r.m = mandate(markets=('pas:BTC', 'pas:EWY', 'pas:HYPE'), max_positions=3).require()
    r.legs = {}
    r.enter = lambda *a, **k: None
    r._bars = lambda *a: OvernightRuntime._bars(r, *a)      # the real, cached candle reads

    def candles(symbol, start, end, *, interval, now_ms):
        step = {'5m': 300000, '15m': 900000}[interval]
        count = (end + 1 - start) // step
        rates.reserve_info('candleSnapshot', response_weight=count // 60)
        src = five(101) if interval == '5m' else UP15
        return [SimpleNamespace(timestamp_ms=end + 1 - (len(src) - i) * step, open=b['o'], high=b['h'], low=b['l'],
                                close=b['c'], volume=b['v']) for i, b in enumerate(src)]
    r.market = SimpleNamespace(get_candles=candles)
    r.decide()
    first = rates.total_weight
    assert rates.weight_by_query == {"candleSnapshot": first} and first == 3 * (20 + 21)   # 6 reads: 5m x40 and 15m x60 per market
    r.decide()                                    # same bar: decided once, nothing re-read
    assert first <= 200 and rates.total_weight == first
    assert rates.ip_weight_limit >= 1200 and first * 1 <= rates.ip_weight_limit / 6


# ---------- Phase 1.4: stop slippage is recorded per trade ----------
def test_closed_trade_records_expected_vs_actual_stop_fill(tmp_path):
    r = FillsFake(tmp_path, now=T0, fills=[fill(HYPE_OPEN), fill(HYPE_STOP)], after_submit_positions={})
    with_hype(r)
    r.protection.states = {'pas:HYPE': dict(status='ACTIVE', order_id=str(HYPE_STOP['oid']), trigger_price='75.473')}
    r.state['open'] = {'pas:HYPE': dict(symbol='pas:HYPE', side='SHORT', entry_ms=HYPE_OPEN['time'], quantity='-1.65',
                                        tp_key='tp')}
    r.manage()
    t = r.state['trades'][0]
    assert (t['stop_trigger'], t['stop_fill'], t['stop_slippage_bps']) == ('75.473', '75.53', '7.552')
    assert D(t['net']) == HYPE_NET and r.state['stop_slippage_bps'] == ['7.552']
