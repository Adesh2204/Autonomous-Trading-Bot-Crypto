"""Fresh read before every order: the stop and the flatten on the real signed submit path.

Reproduces the 2026-10-24 day-session failure on the offline signed fixture: after
an idle period the clock needs two fresh confirmations, and a hot rolling read
budget stalls the guarded context load after the book has been read, so every
5 s rule (book, account, readiness, permission) is exceeded. The FreshReadGate
takes those waits before the permission is issued.
"""
from decimal import Decimal as D
from types import SimpleNamespace

from exchange.carry_runtime import BasketPositionGuard, CarryExecution
from exchange.overnight_runtime import FreshReadGate, OvernightRuntime, ScalpLeg, ScalpProtection, STALE_CODES
from exchange.position_protection import ProtectionPolicy
from test_live_exchange_execution import live, response  # noqa: F401  (offline signed fixture)

READ_MS = 230           # measured per read from this host; a guarded load is ~17 reads (~4 s)


def stack(live, *, gate=True):
    """Real CarryExecution + ScalpProtection; a held 0.2 long at 100 whose stop is not yet placed."""
    fx = live.fixture
    call = fx.__call__

    class Exchange(type(fx)):
        def __call__(self, payload):                 # every read takes READ_MS; the book is always current
            fx.now += READ_MS
            fx.book['time'] = fx.now
            return call(payload)
    fx.__class__ = Exchange
    e = CarryExecution(live.client, transport=live.transport, account=live.account, journal=live.journal,
                       context_provider=live.provider, validator=live.validator, recovery=live.executor.recovery,
                       clock_health=live.clock, rate_limits=live.rate)
    e.entries_paused, e.max_positions, e.allowed_markets = False, 1, frozenset({'par:BTC'})
    e.position_guard = BasketPositionGuard(live.journal, clock_ms=live.client.clock_ms, max_positions=1)
    e.compliance_guard.position_guard = e.position_guard
    e.compliance_guard.extra_setup_types = frozenset({'MOMENTUM_LONG'})
    leg = ScalpLeg('par:BTC')
    protection = ScalpProtection(e, policy=ProtectionPolicy(True, 'x', D(1), D('0.01')), managers={'par:BTC': leg})
    fx.position('.2', '100')
    leg.plan_stop = D('99.5')
    leg.sync(live.account.get_positions()['par:BTC'])

    original = live.provider.load

    def load(request, **k):
        """The book is read first; a hot rolling budget then stalls the remaining reads."""
        stall = live.rate.read_budget_delay_ms(232)
        context = original(request, **k)
        fx.now += stall
        live.rate.weights.append((fx.now, 232))
        return context
    live.provider.load = load

    def transmit(payload, _send=live.transport.transmit):
        result = _send(payload)
        order = payload['action'].get('orders', [{}])[0]
        if 'trigger' in order.get('t', {}):            # the exchange now rests our stop
            fx.orders.append(dict(coin='par:BTC', oid=21, cloid=order['c'], side='B' if order['b'] else 'A',
                                  sz=order['s'], limitPx=order['p'], triggerPx=order['t']['trigger']['triggerPx'],
                                  isTrigger=True, reduceOnly=True, orderType='Stop Market', timestamp=fx.now))
            fx.status = dict(status='order', order=dict(status='open', order=dict(fx.orders[-1])))
        elif order.get('r'):                           # a reduce-only IOC exit filled
            fx.position('0')
        return result
    live.transport.transmit = transmit

    def sleep(seconds):
        fx.now += int(seconds * 1000)
    fresh = FreshReadGate(barrier=SimpleNamespace(require=lambda **k: None),
                          recovery=SimpleNamespace(last_report=SimpleNamespace(ready=True)), rates=live.rate,
                          clock=live.clock, client=live.client, market=live.market, symbol='par:BTC', sleep=sleep)
    protection.before_action = fresh if gate else None
    return e, protection, leg, fresh


def idle_and_hot(live):
    """40 s since the last clock reference, and 900 weight spent in the last 2 s."""
    live.clock.observe(live.fixture.now, live.fixture.now, live.fixture.now)
    live.fixture.now += 40000
    live.fixture.book['time'] = live.fixture.now
    live.rate.weights = [(live.fixture.now - 2000, 900)]


def test_without_the_gate_the_stop_misses_the_freshness_window(live):
    e, protection, leg, _ = stack(live, gate=False)
    idle_and_hot(live)
    protection.ensure_all()
    state = protection.states['par:BTC']
    assert state['status'] == 'ERROR' and state['reason'] in STALE_CODES | {'EXCHANGE_CONTEXT_UNAVAILABLE'}
    assert live.transport.signed_payloads == []


def test_stop_is_signed_inside_the_freshness_window_after_an_idle_hot_period(live):
    e, protection, leg, _ = stack(live)
    idle_and_hot(live)
    started = live.fixture.now
    live.transport.responses = [response({'resting': {'oid': 21}})]
    protection.ensure_all()
    assert protection.states['par:BTC']['status'] == 'ACTIVE', protection.states['par:BTC']
    (payload,) = live.transport.signed_payloads
    order = payload['action']['orders'][0]
    assert order['r'] is True and order['t']['trigger']['tpsl'] == 'sl' and order['b'] is False
    # The ~58 s budget wait and the two clock confirmations happened before the stop's permission.
    assert live.fixture.now - started > 55000 and live.clock.healthy


def runtime_for_exit(live, e, protection, fresh, tmp_path):
    r = OvernightRuntime.__new__(OvernightRuntime)
    r.m = SimpleNamespace(exit_slippage='0.005', markets=('par:BTC',))
    r.state = dict(trade=None, halted=None)
    r.state_dir = tmp_path
    r.executor, r.protection, r.account, r.client, r.market = e, protection, live.account, live.client, live.market
    r.recovery = live.executor.recovery
    r.clock_ms = live.client.clock_ms
    r.preflight = fresh
    return r


def test_flatten_succeeds_with_a_stale_main_loop(live, tmp_path):
    e, protection, leg, fresh = stack(live)
    idle_and_hot(live)
    r = runtime_for_exit(live, e, protection, fresh, tmp_path)
    live.transport.responses = [response({'filled': {'oid': 31, 'totalSz': '.2', 'avgPx': '99.9'}})]
    result = r.exit('par:BTC', 'HALT_TEST')
    assert result.state.value == 'FILLED' and r.positions() == {}
    (payload,) = live.transport.signed_payloads
    assert payload['action']['orders'][0]['r'] is True and payload['action']['orders'][0]['b'] is False


def test_flatten_retries_a_stale_snapshot_with_a_fresh_read(live, tmp_path):
    e, protection, leg, fresh = stack(live)
    r = runtime_for_exit(live, e, protection, fresh, tmp_path)
    load, slowed = live.provider.load, []

    def once_slow(request, **k):                       # the first exit load stalls 25 s, as observed live
        context = load(request, **k)
        if not slowed:
            slowed.append(1)
            live.fixture.now += 25000
        return context
    live.provider.load = once_slow
    live.transport.responses = [response({'filled': {'oid': 31, 'totalSz': '.2', 'avgPx': '99.9'}})]
    result = r.exit('par:BTC', 'HALT_TEST')
    assert result.state.value == 'FILLED' and r.positions() == {} and len(live.transport.signed_payloads) == 1
    kinds = [__import__('json').loads(x)['kind'] for x in (tmp_path / 'overnight_events.jsonl').read_text().splitlines()]
    assert kinds.count('EXIT_RETRY_AFTER_STALE_SNAPSHOT') == 1


def test_entry_gate_refuses_without_headroom_and_never_waits_past_the_signal_window(live):
    from exchange.base_exchange import ExchangeError
    import pytest
    fx = live.fixture
    slept = []
    gate = FreshReadGate(barrier=SimpleNamespace(require=lambda **k: None),
                         recovery=SimpleNamespace(last_report=SimpleNamespace(ready=True)), rates=live.rate,
                         clock=live.clock, client=live.client, market=live.market, symbol='par:BTC',
                         sleep=lambda s: (slept.append(s), setattr(fx, 'now', fx.now + int(s * 1000))))
    live.rate.weights = [(fx.now - 1000, 600)]          # 600 + 880 > 1080 for ~59 s
    with pytest.raises(ExchangeError, match='ENTRY_READ_BUDGET_HEADROOM_UNAVAILABLE'):
        gate(entry=True)
    assert sum(slept) == 0                              # the wait would exceed 25 s: refuse at once
