import sqlite3
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest

from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient
from exchange.rate_limits import HyperliquidRateLimitManager, PasCandleBudget


class FakeClock:
    def __init__(self, now=1_000_000):
        self.now = now
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.now

    def advance(self, milliseconds):
        with self.lock:
            self.now += milliseconds


class FakeJournal:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.execute('CREATE TABLE controls (name TEXT PRIMARY KEY, value TEXT)')
        self.session_id = 'offline-test'

    @contextmanager
    def transaction(self):
        yield

    def event(self, *args, **kwargs):
        pass


def candle_request(coin, slots):
    return dict(coin=coin, interval='1m', startTime=0, endTime=(slots - 1) * 60_000)


def pas_client(budget, calls):
    client = HyperliquidClient(transport=lambda payload: calls.append(payload) or [])
    client.candle_budget = budget
    # These tests focus on budget admission, not runtime metadata discovery.
    client._validate_coin = lambda symbol: None
    return client


def test_exact_300_admitted_301_rejected_before_transport_and_boundary_expires():
    clock = FakeClock()
    budget = PasCandleBudget(clock_ms=clock)
    calls = []
    client = pas_client(budget, calls)

    client.post_info('candleSnapshot', req=candle_request('pas:BTC', 300))
    assert len(calls) == 1
    assert budget.report()['used'] == 300

    with pytest.raises(ExchangeError) as rejected:
        client.post_info('candleSnapshot', req=candle_request('pas:BTC', 301))
    assert str(rejected.value) == 'PAS_CANDLE_BUDGET_EXHAUSTED'
    assert rejected.value.retry_after_ms is None  # 301 slots can never fit this cap.
    assert len(calls) == 1
    assert budget.report()['used'] == 300

    clock.advance(60_000)
    client.post_info('candleSnapshot', req=candle_request('pas:BTC', 300))
    assert len(calls) == 2
    assert budget.report()['used'] == 300


def test_oversize_request_is_impossible_to_retry_even_with_empty_window():
    budget = PasCandleBudget(clock_ms=FakeClock())
    with pytest.raises(ExchangeError) as rejected:
        budget.reserve(301)
    assert str(rejected.value) == 'PAS_CANDLE_BUDGET_EXHAUSTED'
    assert rejected.value.retry_after_ms is None
    assert budget.report()['used'] == 0


def test_btc_and_ewy_share_budget_and_rejection_reports_window_wait():
    clock = FakeClock()
    budget = PasCandleBudget(clock_ms=clock)
    calls = []
    client = pas_client(budget, calls)
    client.post_info('candleSnapshot', req=candle_request('pas:BTC', 200))
    client.post_info('candleSnapshot', req=candle_request('pas:EWY', 100))

    with pytest.raises(ExchangeError) as rejected:
        client.post_info('candleSnapshot', req=candle_request('pas:EWY', 1))
    assert str(rejected.value) == 'PAS_CANDLE_BUDGET_EXHAUSTED'
    assert rejected.value.retry_after_ms == 60_000
    assert len(calls) == 2
    assert budget.report()['used'] == 300


def test_retries_charge_each_attempt_and_account_safety_read_is_not_candle_budgeted():
    clock = FakeClock()
    budget = PasCandleBudget(clock_ms=clock)
    manager = HyperliquidRateLimitManager(FakeJournal(), clock_ms=clock,
        wait=clock.advance, jitter=lambda: 0)
    calls = []

    def flaky_read():
        calls.append('candle')
        if len(calls) == 1:
            error = ExchangeError('INFO_READ_TIMEOUT')
            error.retryable = True
            raise error
        return []

    result = manager.read('candleSnapshot', flaky_read, expected_items=150,
                          candle_budget=budget)
    assert result == []
    assert len(calls) == 2
    assert budget.report()['used'] == 300

    manager.read('clearinghouseState', lambda: {'assetPositions': []}, candle_budget=budget)
    assert budget.report()['used'] == 300


def test_coalesced_concurrent_read_charges_only_the_single_upstream_attempt():
    clock = FakeClock()
    budget = PasCandleBudget(clock_ms=clock)
    manager = HyperliquidRateLimitManager(FakeJournal(), clock_ms=clock,
                                          wait=clock.advance, jitter=lambda: 0)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def operation():
        calls.append(1)
        started.set()
        assert release.wait(3)
        return []

    def read():
        return manager.read('candleSnapshot', operation, request_key='same-request',
                            expected_items=300, candle_budget=budget)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read)
        assert started.wait(2)
        second = pool.submit(read)
        deadline = time.monotonic() + 2
        while manager.coalesced_reads == 0 and time.monotonic() < deadline:
            time.sleep(.005)
        assert manager.coalesced_reads == 1
        release.set()
        assert first.result(timeout=2) == []
        assert second.result(timeout=2) == []

    assert len(calls) == 1
    assert budget.report()['used'] == 300


def test_concurrent_distinct_reservations_are_serialized():
    clock = FakeClock()
    budget = PasCandleBudget(clock_ms=clock)
    barrier = threading.Barrier(3)

    def reserve():
        barrier.wait()
        try:
            budget.reserve(200)
            return 'accepted'
        except ExchangeError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        barrier.wait()
        results = [future.result(timeout=2) for future in futures]
    assert results.count('accepted') == 1
    assert results.count('PAS_CANDLE_BUDGET_EXHAUSTED') == 1
    assert budget.report()['used'] == 200


@pytest.mark.parametrize('slots', [0, -1, True, False, 1.5, '300', None, 301])
def test_invalid_slot_counts_fail_closed_without_spending_budget(slots):
    budget = PasCandleBudget(clock_ms=FakeClock())
    with pytest.raises(ExchangeError) as rejected:
        budget.reserve(slots)
    assert str(rejected.value) == 'PAS_CANDLE_BUDGET_EXHAUSTED'
    assert rejected.value.retry_after_ms is None
    assert budget.report()['used'] == 0


def test_real_pas_clients_share_one_process_budget_without_loading_signers():
    from exchange.hyperliquid_client import RequestsInfoTransport
    from exchange.rate_limits import PAS_CANDLE_BUDGET
    # Type identity only; no session, HTTP, startup or private credential access.
    first = HyperliquidClient(transport=object.__new__(RequestsInfoTransport))
    second = HyperliquidClient(transport=object.__new__(RequestsInfoTransport))
    assert first.candle_budget is second.candle_budget is PAS_CANDLE_BUDGET
    offline = HyperliquidClient(transport=lambda _: [])
    assert offline.candle_budget is PAS_CANDLE_BUDGET
