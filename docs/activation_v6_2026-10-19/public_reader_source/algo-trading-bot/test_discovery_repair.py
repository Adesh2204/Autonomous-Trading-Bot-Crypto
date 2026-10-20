"""Regression cases for strict universe selection and official endpoint recovery."""
import json
from datetime import date

import pytest
import requests

import config
from discovery_data import DiscoveryDataSource
from execution_safety import SafetyError
from premarket_pipeline import run_premarket_pipeline
from market_schedule import NSE_CONFIRMED_CLOSURES, NSEMarketSchedule
from test_market_discovery import (NOW, SESSION, FakeResponse, FixtureDataSource, bhav_bytes,
    deep_fixture, full_market_fixture, small_schema, snapshot, universe)


@pytest.mark.parametrize('error', [requests.ReadTimeout, requests.ConnectionError])
def test_failed_primary_uses_official_alternate_and_caches_actual_source(tmp_path, small_schema, error):
    calls = []
    primary = config.DISCOVERY_BHAVCOPY_URL.format(session='20260930')
    alternate = config.DISCOVERY_BHAVCOPY_ALTERNATES[0].format(session='20260930')
    def get(url, **kwargs):
        calls.append(url)
        if url == primary:
            raise error('primary unavailable')
        return FakeResponse(bhav_bytes(zip_output=True))
    source = DiscoveryDataSource(tmp_path, get=get, sleep=lambda _: None, clock=lambda: NOW)
    first = source.snapshot(SESSION, NOW)
    assert calls == [primary, alternate]
    assert first.source == alternate
    assert source.snapshot(SESSION, NOW).cache_hit
    assert len(calls) == 2
    assert source.accounting.failures == source.accounting.retries == 1
    assert source.datasets['snapshot']['source'] == alternate


def test_partial_body_timeout_retries_entire_file_and_closes_responses(tmp_path, small_schema):
    class Interrupted(FakeResponse):
        def iter_content(self, chunk_size):
            yield b'partial body must be discarded'
            raise requests.ReadTimeout('body interrupted')
    first = Interrupted(b'')
    second = FakeResponse(bhav_bytes())
    responses = iter([first, second])
    source = DiscoveryDataSource(tmp_path, get=lambda *a, **k: next(responses),
        sleep=lambda _: None, clock=lambda: NOW)
    assert source.snapshot(SESSION, NOW).records[0]['symbol'] == 'ABC'
    assert first.closed and second.closed
    assert source.accounting.bulk_market_data_calls == 2


@pytest.mark.parametrize('status', [404, 429, 503])
def test_http_endpoint_failure_can_recover_from_second_official_source(tmp_path, small_schema, status):
    responses = iter([FakeResponse(b'failure', status), FakeResponse(bhav_bytes())])
    source = DiscoveryDataSource(tmp_path, get=lambda *a, **k: next(responses),
        sleep=lambda _: None, clock=lambda: NOW)
    assert source.snapshot(SESSION, NOW).records
    assert source.accounting.endpoint_attempts[0]['status'] == status
    assert source.accounting.endpoint_attempts[1]['status'] == 200


def test_retries_share_one_budget_across_endpoints_and_log_url(tmp_path, caplog):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        raise requests.ReadTimeout('unavailable')
    source = DiscoveryDataSource(tmp_path, get=get, sleep=lambda _: None)
    with pytest.raises(SafetyError, match='DATA_SOURCE_ERROR'):
        source.snapshot(SESSION, NOW)
    assert len(calls) == config.SCREEN_API_MAX_RETRIES == 3
    assert calls[0] != calls[1] and calls[0] == calls[2]
    assert all(url in caplog.text for url in calls)
    assert not (tmp_path/SESSION.isoformat()/'snapshot.json').exists()


def test_bad_schema_is_not_replaced_by_a_stock_list_or_cached(tmp_path, small_schema):
    source = DiscoveryDataSource(tmp_path, get=lambda *a, **k: FakeResponse(b'<html>Unavailable</html>'),
        sleep=lambda _: None, clock=lambda: NOW)
    result = run_premarket_pipeline(now=NOW, market_universe=universe(), data_source=source,
        data_fetcher=lambda *a: pytest.fail('Must not use a configured stock list'), pacing_interval=0.)
    assert result.readiness == 'BLOCKED' and result.screen.total_candidates == 0
    assert not (tmp_path/SESSION.isoformat()/'equities.json').exists()


def test_full_market_record_audit_and_selected_tokens_come_from_master():
    base, symbols, snap = full_market_fixture()
    result = run_premarket_pipeline(now=NOW, market_universe=base,
        data_source=FixtureDataSource(symbols, snap), data_fetcher=deep_fixture, pacing_interval=0.)
    audit = result.report()['universe_audit']
    assert audit['raw_records_examined'] == 1000
    assert audit['eligible_instruments'] == 600 and audit['excluded_records'] == 400
    assert audit['record_accounting_complete'] and not audit['configured_stock_list_used']
    assert len(result.screen.watchlist) == 3
    for candidate in result.screen.watchlist:
        assert candidate.instrument is base.registry.resolve(candidate.symbol, candidate.token, NOW)


def test_main_data_failure_exits_nonzero_without_starting_stream(monkeypatch):
    import live_stream
    result = run_premarket_pipeline(now=NOW, market_universe=universe(),
        data_source=FixtureDataSource(['ABC'], snapshot(), 'DATA_SOURCE_ERROR'), pacing_interval=0.)
    monkeypatch.delenv('TRADING_SYMBOL', raising=False)
    monkeypatch.setattr(live_stream, 'angel_login', lambda: None)
    monkeypatch.setattr(live_stream, 'run_premarket_pipeline', lambda **k: result)
    monkeypatch.setattr(live_stream, 'record_screening_report', lambda *a, **k: None)
    monkeypatch.setattr(live_stream, 'AngelOneLiveStream', lambda **k: pytest.fail('Blocked startup must not trade'))
    with pytest.raises(SystemExit) as caught:
        live_stream.main()
    assert caught.value.code == 2


def test_check_command_exposes_market_data_only_and_stops_after_selection(monkeypatch, tmp_path):
    import premarket_check
    base, symbols, snap = full_market_fixture()
    result = run_premarket_pipeline(now=NOW, market_universe=base,
        data_source=FixtureDataSource(symbols, snap), data_fetcher=deep_fixture, pacing_interval=0.)
    class Broker:
        def placeOrder(self, *a, **k):
            pytest.fail('No order submission allowed')
    def pipeline(broker, **kwargs):
        for name in ('placeOrder', 'modifyOrder', 'cancelOrder', 'placeOrderFullResponse'):
            assert not hasattr(broker, name)
        return result
    monkeypatch.setattr(premarket_check, 'run_premarket_pipeline', pipeline)
    path = tmp_path/'check.json'
    observed, summary = premarket_check.run_check(Broker(), path)
    assert observed is result and len(summary['watchlist']) == 3
    assert summary['orders_submitted'] == 0
    assert not json.loads(path.read_text())['validation']['trading_engine_started']


@pytest.mark.parametrize('day', sorted(NSE_CONFIRMED_CLOSURES))
def test_official_exchange_holidays_override_stale_provider(day):
    import pandas as pd
    class StaleCalendar:
        def schedule(self, **kwargs):
            return pd.DataFrame({'open': [True]})  # Incorrectly says every day is open.
    schedule = NSEMarketSchedule()
    schedule._calendar = StaleCalendar()
    assert not schedule.is_trading_day(day)
    assert schedule.holiday_name(day) == NSE_CONFIRMED_CLOSURES[day]


def test_real_calendar_resolves_previous_session_across_october_holiday():
    from premarket_screener import find_previous_completed_market_session
    schedule = NSEMarketSchedule()
    assert find_previous_completed_market_session(date(2026, 10, 5), schedule) == date(2026, 10, 1)
    assert find_previous_completed_market_session(date(2026, 10, 1), schedule) == date(2026, 9, 30)


@pytest.mark.parametrize('response_kind', ['exception', 'response'])
def test_history_backoff_covers_retries_and_subsequent_symbols(response_kind):
    from premarket_pipeline import _HistoricalRequestCounter
    clock = [100.]
    times = []
    def sleep(delay):
        clock[0] += delay
    class Broker:
        def getCandleData(self, params):
            times.append(clock[0])
            if len(times) < 3:
                if response_kind == 'exception':
                    raise RuntimeError('Access denied because of exceeding access rate')
                return {'status': False, 'errorcode': 'AB1021', 'message': 'Too many requests'}
            return {'status': True, 'data': [[1]]}
    counter = _HistoricalRequestCounter(Broker(), clock=lambda: clock[0], sleep=sleep)
    for i in range(4):
        try:
            counter.getCandleData({'symboltoken': str(i)})
        except RuntimeError:
            assert response_kind == 'exception'
    assert counter.calls == 4 and counter.rate_limit_count == 2
    assert times[1] - times[0] >= config.DISCOVERY_HISTORY_RATE_BACKOFF_SECONDS
    assert times[2] - times[1] >= config.DISCOVERY_HISTORY_RATE_BACKOFF_SECONDS * 2
    assert times[3] - times[2] >= config.DISCOVERY_HISTORY_INTERVAL_SECONDS - 1e-8


def test_persistent_broker_throttling_blocks_without_releasing_partial_watchlist(monkeypatch):
    import premarket_pipeline
    monkeypatch.setattr(config, 'DISCOVERY_HISTORY_MAX_CONSECUTIVE_RATE_LIMITS', 2)
    monkeypatch.setattr(premarket_pipeline.time, 'sleep', lambda _: None)
    class ThrottledBroker:
        def getCandleData(self, params):
            raise RuntimeError('Access denied because of exceeding access rate')
    from premarket_pipeline import _HistoricalRequestCounter
    broker=ThrottledBroker()
    result = run_premarket_pipeline(broker, history_service=_HistoricalRequestCounter(broker), now=NOW, market_universe=universe(),
        data_source=FixtureDataSource(['ABC'], snapshot()), pacing_interval=0.)
    assert result.discovery.success  # NSE discovery worked; the broker history did not.
    assert result.readiness == 'BLOCKED'
    assert result.screen_failure_reason.startswith('HISTORY_RATE_LIMIT')
    assert result.deep_historical_requests == 2
    assert result.deep_rate_limit_responses == 2
    assert not result.screen.watchlist and result.screen.selected_candidate is None
    assert result.report()['deep_screen']['planned_candidates'] == 1
    assert result.report()['universe_audit']['configured_stock_list_used'] is False


def test_history_deadline_expires_before_sleep_or_external_request():
    from premarket_pipeline import _HistoricalRequestCounter
    from premarket_screener import HistoricalDataUnavailable
    clock = [100.]
    class NoRequests:
        def getCandleData(self, params):
            pytest.fail('No external request after budget expires')
    counter = _HistoricalRequestCounter(NoRequests(), clock=lambda: clock[0],
        sleep=lambda delay: pytest.fail('Must not sleep past the deadline'))
    counter.next_allowed = counter.deadline + 1
    with pytest.raises(HistoricalDataUnavailable, match='TIME_BUDGET'):
        counter.getCandleData({})
    assert counter.calls == 0


def test_historical_budget_failure_preserves_completed_diagnostics(monkeypatch):
    import premarket_screener
    from premarket_screener import HistoricalDataUnavailable
    base, symbols, snap = full_market_fixture()
    def fetched(**kwargs):
        if kwargs['symbol'] == 'STOCK0001':
            raise HistoricalDataUnavailable('HISTORY_TIME_BUDGET_EXHAUSTED')
        return deep_fixture({'symbol': kwargs['symbol']}, SESSION)
    monkeypatch.setattr(premarket_screener, 'fetch_historical_session_candles', fetched)
    result = run_premarket_pipeline(object(), now=NOW, market_universe=base,
        data_source=FixtureDataSource(symbols, snap), pacing_interval=0.)
    assert result.readiness == 'BLOCKED' and not result.screen.watchlist
    assert len(result.screen.diagnostics) == 1
    assert result.screen.diagnostics[0].qualified
    assert result.report()['lineage'][0]['final_rank'] is None


def test_optional_history_timeout_keeps_verified_ranking_and_marks_unknown_profiles(monkeypatch):
    import premarket_screener
    from premarket_screener import HistoricalDataUnavailable
    base, symbols, snap = full_market_fixture()
    def fetched(*args, **kwargs):
        if args:
            kwargs = {'symbol': args[1], 'session_date': args[4]}
        if kwargs['session_date'] != SESSION:
            raise HistoricalDataUnavailable('HISTORY_TIME_BUDGET_EXHAUSTED')
        return deep_fixture({'symbol': kwargs['symbol']}, SESSION)
    monkeypatch.setattr(premarket_screener, 'fetch_historical_session_candles', fetched)
    result = run_premarket_pipeline(object(), now=NOW, market_universe=base,
        data_source=FixtureDataSource(symbols, snap), pacing_interval=0.)
    assert result.readiness == 'DYNAMIC_DISCOVERY_READY'
    assert result.screen.trading_day_status == 'ACTIVE'
    assert len(result.screen.watchlist) == 3
    assert result.screen.history_warning == 'HISTORY_TIME_BUDGET_EXHAUSTED'
    assert result.screen_failure_reason is None
    assert all(len(c.volume_profiles) == 1 for c in result.screen.watchlist)
    assert result.report()['deep_screen']['history_warning'] == result.screen.history_warning
    assert all(c.discovery_lineage['final_rank'] in (1, 2, 3) for c in result.screen.watchlist)


def test_optional_history_has_its_own_shorter_budget():
    from premarket_pipeline import _HistoricalRequestCounter
    clock = [100.]
    counter = _HistoricalRequestCounter(object(), clock=lambda: clock[0])
    original_deadline = counter.deadline
    counter.begin_optional_history()
    assert counter.deadline == min(original_deadline, 100. + config.DISCOVERY_RVOL_MAX_RUNTIME_SECONDS)
