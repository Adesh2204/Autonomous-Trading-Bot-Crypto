"""Exercise today's existing main(), actual deep screener and Phase-5 constructor."""
from datetime import date
import json
from pathlib import Path

import pytest

import config
from discovery_data import DiscoveryDataSource
from execution_safety import SafetyError
from market_schedule import NSEMarketSchedule
from premarket_pipeline import load_startup_universe, run_premarket_pipeline
from test_market_discovery import (NOW, SESSION, FixtureDataSource, deep_fixture, envelope,
                                    full_market_fixture, master_row, snapshot, universe, FakeResponse)


def test_current_main_dry_run_initializes_real_phase5_top_three(monkeypatch, tmp_path):
    import live_stream
    base, symbols, market_snapshot = full_market_fixture()
    source = FixtureDataSource(symbols, market_snapshot)
    observed = {}
    original_pipeline = run_premarket_pipeline
    real_stream = live_stream.AngelOneLiveStream

    def startup_pipeline(**kwargs):
        kwargs.update(now=NOW, data_source=source, market_universe=base, data_fetcher=deep_fixture,
                      pacing_interval=0., report_path=tmp_path/'dry_run.json')
        result = original_pipeline(**kwargs)
        observed['pipeline'] = result
        return result

    def stream_factory(**kwargs):
        assert kwargs['watchlist'] is observed['pipeline'].screen.watchlist
        stream = real_stream(**kwargs)
        observed['stream'] = stream
        stream.run = lambda: observed.update(started=True)
        return stream

    def no_auth():
        raise RuntimeError('SYNTHETIC_TEST_FIXTURE: no broker authentication')

    monkeypatch.setattr(config, 'LIVE_MODE', False)
    monkeypatch.setattr(config, 'EXECUTION_ENVIRONMENT', 'TEST')
    monkeypatch.delenv('TRADING_SYMBOL', raising=False)
    for key in ('BROKER_API_KEY', 'BROKER_CLIENT_ID', 'BROKER_PIN', 'BROKER_TOTP_SECRET'):
        monkeypatch.setenv(key, 'SYNTHETIC_TEST_FIXTURE')
    monkeypatch.setattr(live_stream, 'to_ist', lambda value=None: NOW)
    monkeypatch.setattr(live_stream, 'angel_login', no_auth)
    monkeypatch.setattr(live_stream, 'run_premarket_pipeline', startup_pipeline)
    monkeypatch.setattr(live_stream, 'record_screening_report', lambda *args, **kwargs: None)
    monkeypatch.setattr(real_stream, '_install_signal_handlers', lambda self: None)
    monkeypatch.setattr(live_stream, 'AngelOneLiveStream', stream_factory)
    live_stream.main()
    assert observed['started']
    stream = observed['stream']
    try:
        assert len(stream.active_symbols) == 3 + config.RESERVE_WATCHLIST_SIZE
        assert sum(s.watchlist_role == 'PRIMARY' for s in stream.active_symbols.values()) == 3
        assert sum(s.watchlist_role == 'RESERVE' for s in stream.active_symbols.values()) == config.RESERVE_WATCHLIST_SIZE
        for token, state in stream.active_symbols.items():
            identity = observed['pipeline'].registry.resolve(state.symbol, token, NOW)
            assert state.instrument is identity
            assert state.trading_symbol == identity.trading_symbol
            assert state.exchange == identity.exchange == 'NSE'
        report = json.loads((tmp_path/'dry_run.json').read_text())
        assert report['deep_screen']['session_date'] == '2026-09-30'
        assert report['deep_screen']['watchlist_count'] == 3
        assert all(c.discovery_lineage['final_rank'] for c in stream.watchlist)
        assert config.LIVE_VALIDATION_APPROVED is False
        assert config.MAX_OPEN_POSITIONS == 1
    finally:
        stream.paper_trader.shutdown()


def test_main_legitimate_no_trade_never_constructs_stream(monkeypatch):
    import live_stream
    result = run_premarket_pipeline(now=NOW, market_universe=universe(),
        data_source=FixtureDataSource(['ABC'], snapshot()), data_fetcher=lambda c, d: None,
        pacing_interval=0.)
    monkeypatch.delenv('TRADING_SYMBOL', raising=False)
    monkeypatch.setattr(live_stream, 'angel_login', lambda: None)
    monkeypatch.setattr(live_stream, 'run_premarket_pipeline', lambda **kwargs: result)
    monkeypatch.setattr(live_stream, 'record_screening_report', lambda *args, **kwargs: None)
    def forbidden(**kwargs):
        raise AssertionError('No stream allowed for NO_TRADE')
    monkeypatch.setattr(live_stream, 'AngelOneLiveStream', forbidden)
    with pytest.raises(SystemExit) as caught:
        live_stream.main()
    assert caught.value.code == 0


def test_fresh_instrument_cache_reused_without_external_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DISCOVERY_MIN_MASTER_RECORDS', 1)
    path = tmp_path/'instruments.json'
    path.write_text(json.dumps(envelope([master_row()])))
    source = DiscoveryDataSource(tmp_path, get=lambda *args, **kwargs: pytest.fail('Cache should be reused'))
    result = load_startup_universe(None, source, NOW, str(path))
    assert result.registry.resolve('ABC').token == '123'
    assert source.accounting.instrument_source_calls == 0


def test_no_master_and_no_verified_fallback_blocks_safely(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'INSTRUMENT_MASTER_FILE', str(tmp_path/'absent.json'))
    result = run_premarket_pipeline(None, now=NOW, data_source=DiscoveryDataSource(tmp_path), pacing_interval=0.)
    assert result.readiness == 'BLOCKED'
    assert result.registry is None and result.screen.trading_day_status == 'NO_TRADE'
    assert result.discovery.failure_reason == 'BROKER_DATA_UNAVAILABLE'


def test_single_canonical_session_skips_holiday_and_weekend():
    from premarket_screener import find_previous_completed_market_session
    class HolidaySchedule(NSEMarketSchedule):
        def is_trading_day(self, day):
            return day.weekday() < 5 and day != date(2026, 10, 2)
    assert find_previous_completed_market_session(date(2026, 10, 5), HolidaySchedule()) == date(2026, 10, 1)


def test_stage_two_request_accounting_is_separate(monkeypatch):
    import premarket_screener
    monkeypatch.setattr(premarket_screener.time, 'sleep', lambda _: None)
    class FailedHistoricalBroker:
        def getCandleData(self, params):
            return {'status': True, 'data': []}
    from premarket_pipeline import _HistoricalRequestCounter
    broker=FailedHistoricalBroker()
    result = run_premarket_pipeline(broker, history_service=_HistoricalRequestCounter(broker), now=NOW, market_universe=universe(),
        data_source=FixtureDataSource(['ABC'], snapshot()), pacing_interval=0.)
    assert result.deep_historical_requests == config.SCREEN_API_MAX_RETRIES
    assert result.discovery.request_counts['historical_calls'] == 0
    assert result.screen.trading_day_status == 'NO_TRADE'


def test_disk_report_preserves_all_final_candidate_lineage(tmp_path):
    base, symbols, snap = full_market_fixture()
    result = run_premarket_pipeline(now=NOW, market_universe=base,
        data_source=FixtureDataSource(symbols, snap), data_fetcher=deep_fixture,
        pacing_interval=0., report_path=tmp_path/'startup.json')
    report = json.loads((tmp_path/'startup.json').read_text())
    assert report['discovery']['raw_instrument_count'] == 1000
    final = [row for row in report['lineage'] if row['final_rank']]
    assert len(final) == 3
    assert all(row['instrument_source'] == 'SYNTHETIC_TEST_FIXTURE_BROKER_MASTER' for row in final)
    assert all(row['qualification_result'] == 'QUALIFIED' for row in final)
    assert len(report['universe_rejections']) == 400
    assert len(result.registry.by_symbol) == 600


@pytest.mark.parametrize('exchange_key', ['Exchange', 'exchange'])
def test_broker_eligibility_schema_accepts_observed_and_legacy_keys(tmp_path, monkeypatch, exchange_key):
    from refresh_instruments import refresh_registry, MASTER_URL
    monkeypatch.setattr(config, 'DISCOVERY_MIN_MASTER_RECORDS', 1)
    class ReadOnlyBrokerFixture:
        api_key = 'TEST_ONLY'
        access_token = 'TEST_ONLY'
        def requestHeaders(self):
            return {}
    def get(url, **kwargs):
        data = [master_row()] if url == MASTER_URL else {'status': True, 'data': [
            {exchange_key: ' NSE ', 'SymbolName': ' abc-eq ', 'Multiplier': 3}]}
        return FakeResponse(json.dumps(data).encode())
    registry = refresh_registry(ReadOnlyBrokerFixture(), tmp_path/'master.json', NOW, get=get)
    assert registry.resolve('ABC').token == '123'
    assert (tmp_path/'master.json').exists()


@pytest.mark.parametrize('row', [{'SymbolName': 'ABC'}, {'Exchange': 'NSE', 'SymbolName': True},
    {'Exchange': 'NSE', 'exchange': 'BSE', 'SymbolName': 'ABC'}])
def test_unknown_or_ambiguous_eligibility_schema_fails(tmp_path, monkeypatch, row):
    from refresh_instruments import refresh_registry, MASTER_URL
    monkeypatch.setattr(config, 'DISCOVERY_MIN_MASTER_RECORDS', 1)
    class Broker:
        api_key = access_token = 'TEST_ONLY'
        def requestHeaders(self):
            return {}
    def get(url, **kwargs):
        data = [master_row()] if url == MASTER_URL else {'status': True, 'data': [row]}
        return FakeResponse(json.dumps(data).encode())
    with pytest.raises(SafetyError, match='SCHEMA_VALIDATION_FAILED'):
        refresh_registry(Broker(), tmp_path/'master.json', NOW, get=get)
    assert not (tmp_path/'master.json').exists()
