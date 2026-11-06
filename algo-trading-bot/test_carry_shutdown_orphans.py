"""Bug #13 (25 Oct 19:50 UTC): stop.flag shutdown left two resting entry children on the book.

The single cancel attempt failed with ACCOUNT_NOT_READY, the process exited, and both maker
buys filled 3 and 10 minutes later with no bot running and no exchange stop.
"""
from exchange.base_exchange import ExchangeError
from test_carry_profile import World


def resting_world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.r.startup()
    for _ in range(3):
        w.step()
    assert w.children()                                  # maker children rest on the book
    return w


def flaky(w, failures):
    original = w.r.executor.cancel_order
    calls = []

    def cancel(symbol, oid, *, critical=False):
        calls.append((symbol, critical))
        if len(calls) <= failures:
            raise ExchangeError('ACCOUNT_NOT_READY')
        return original(symbol, oid, critical=critical)
    w.r.executor.cancel_order = cancel
    return calls


def test_a_failed_shutdown_cancel_is_retried_until_nothing_rests(tmp_path, monkeypatch):
    w = resting_world(tmp_path, monkeypatch)
    calls = flaky(w, failures=1)
    reads = []
    w.r.preflight = lambda **k: reads.append(k)
    assert w.r.shutdown('STOP_FLAG') is True
    assert not w.children()
    assert all(critical for _, critical in calls)        # a cancel only removes exposure
    assert reads                                           # account truth re-read before the retry
    assert any(e.get('attempt') == 1 for e in w.events('CHILD_CANCEL_ERROR'))
    assert w.events('STOPPED')[-1]['complete'] is True


def test_shutdown_never_reports_clean_while_an_order_still_rests(tmp_path, monkeypatch):
    w = resting_world(tmp_path, monkeypatch)
    w.r.SHUTDOWN_DEADLINE_MS = 30000                       # 2 retry rounds in the test
    flaky(w, failures=10 ** 6)
    assert w.r.shutdown('STOP_FLAG') is False
    assert w.children()                                    # honest: still resting
    assert w.events('SHUTDOWN_INCOMPLETE_RESTING_ORDERS')
    assert (w.r.state_dir / 'SHUTDOWN_INCOMPLETE').exists()
    assert w.events('STOPPED')[-1]['complete'] is False


def test_an_order_the_journal_calls_settled_is_still_cancelled_if_the_exchange_shows_it(tmp_path, monkeypatch):
    w = resting_world(tmp_path, monkeypatch)
    symbol = next(s for s, leg in w.r.state['legs'].items() if leg['child'])
    oid = w.r.state['legs'][symbol]['child']['oid']
    ours = {symbol: oid}
    w.r.state['legs'][symbol]['child'] = None              # journal view: settled
    assert w.r._shutdown_until_no_child_rests(ours) is True
    assert str(oid) not in {str(o['oid']) for o in w.children(symbol)}
