"""Deterministic SYNTHETIC_TEST_FIXTURE coverage; no trading or real data claims."""
from datetime import date, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import zipfile

import numpy as np
import pandas as pd
import pytest
import requests

import config
from discovery_data import (DiscoveryDataSource, RequestAccounting, checksum,
                             parse_bhavcopy, parse_equity_reference)
from execution_safety import SafetyError
from market_discovery import MarketSnapshot, discover_nse_candidates
from market_universe import build_market_universe, configured_fallback, load_master_envelope
from premarket_pipeline import run_premarket_pipeline

NOW = datetime(2026, 10, 1, 8, 45, tzinfo=ZoneInfo('Asia/Kolkata'))
SESSION = date(2026, 9, 30)
FROZEN_HASH = 'bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83'


def master_row(base_symbol='ABC', token='123', **changes):
    row = {'symbol': base_symbol + '-EQ', 'token': token, 'exch_seg': 'NSE',
           'lotsize': '1', 'tick_size': '5', 'instrumenttype': ''}
    row.update(changes)
    return row


def envelope(rows, eligible=None, stamp=NOW):
    return {'records': rows, 'source_timestamp': stamp.isoformat(),
            'intraday_symbols': eligible if eligible is not None else ['ABC'],
            'restricted_symbols': [], 'sources': ['SYNTHETIC_TEST_FIXTURE_BROKER_MASTER']}


def universe(rows=None):
    return build_market_universe(envelope(rows or [master_row()]), NOW, equity_symbols=['ABC'], min_records=1)


def snapshot(rows=None, **changes):
    fields = dict(session_date=SESSION, source='SYNTHETIC_TEST_FIXTURE', source_timestamp=NOW,
        available_at=NOW, records=rows or [{'symbol': 'ABC', 'series': 'EQ', 'market_date': SESSION.isoformat(),
            'close': 200., 'high': 205., 'low': 195., 'volume': 6_000_000, 'turnover': 1_200_000_000.}])
    fields.update(changes)
    return MarketSnapshot(**fields)


def full_market_fixture():
    """1000 raw -> 600 stock equities -> 180 coarse -> 60 deep -> 12 qualified -> 3."""
    symbols = [f'STOCK{i:04}' for i in range(600)]
    rows = [master_row(s, str(10_000 + i)) for i, s in enumerate(symbols)]
    rows += [master_row(f'BSE{i:03}', str(20_000 + i), exch_seg='BSE') for i in range(100)]
    rows += [master_row(f'BAD{i:03}', str(30_000 + i), symbol=f'BAD{i:03}-BE') for i in range(100)]
    funds = [f'FUND{i:03}' for i in range(100)]
    rows += [master_row(s, str(40_000 + i)) for i, s in enumerate(funds)]
    rows += [master_row(f'INELIGIBLE{i:03}', str(50_000 + i)) for i in range(100)]
    base = build_market_universe(envelope(rows, symbols + funds), NOW)
    records = []
    for i, symbol in enumerate(symbols):
        volume = 6_000_000 + (180 - i) * 1000 if i < 180 else 4_000_000
        records.append({'symbol': symbol, 'series': 'EQ', 'market_date': SESSION.isoformat(),
            'close': 200., 'high': 220. - i * .02, 'low': 180.,
            'volume': volume, 'turnover': volume * 200.})
    return base, symbols, snapshot(records)


class FixtureDataSource:
    def __init__(self, symbols, market_snapshot, failure=None):
        self.symbols = symbols
        self.market_snapshot = market_snapshot
        self.failure = failure
        self.accounting = RequestAccounting()

    def equity_symbols(self, session, now):
        if self.failure:
            raise SafetyError(self.failure)
        assert session == SESSION
        return self.symbols

    def snapshot(self, session, now):
        assert session == SESSION
        return self.market_snapshot


def deep_fixture(candidate, session):
    index = int(candidate['symbol'][5:])
    prices = 200. + np.linspace(-3, 3, 375) * (1 if index % 2 else -1)
    atr = 1.4 + index * .05 if index < 12 else .2
    return pd.DataFrame({'Timestamp': pd.date_range(datetime.combine(session, datetime.min.time()).replace(hour=9, minute=15),
        periods=375, freq='min'), 'Open': prices, 'High': prices + atr / 2,
        'Low': prices - atr / 2, 'Close': prices, 'Volume': 20_000})


def test_full_market_input_filter_and_no_etf_assumption():
    rows = [master_row(), master_row('ETF', '124'), master_row('BE', '125', symbol='BE-BE'),
            master_row('BSE', '126', exch_seg='BSE'), None]
    result = build_market_universe(envelope(rows, ['ABC', 'ETF', 'BE', 'BSE']), NOW,
                                   equity_symbols=['ABC'], min_records=1)
    assert [i.symbol for i in result.instruments] == ['ABC']
    assert {r.reason for r in result.rejected_records} == {'NOT_EQUITY', 'INVALID_SERIES', 'NOT_NSE', 'SCHEMA_VALIDATION_FAILED'}


@pytest.mark.parametrize('age', [timedelta(hours=25), timedelta(hours=-1)])
def test_stale_or_future_master_rejected(age):
    with pytest.raises(SafetyError, match='STALE'):
        build_market_universe(envelope([master_row()], stamp=NOW - age), NOW, min_records=1)


@pytest.mark.parametrize('changes', [{'token': ''}, {'token': True}, {'token': 'guess'},
    {'token': 0}, {'tick_size': 'NaN'}, {'lotsize': True}, {'lotsize': '1.5'}])
def test_unresolved_instrument_identity_excluded(changes):
    result = universe([master_row(**changes)])
    assert result.eligible_equity_count == 0
    assert result.rejected_records


def test_conflicting_tokens_and_symbols_exclude_every_conflict():
    rows = [master_row('ABC', '123'), master_row('XYZ', '123'), master_row('ABC', '999')]
    result = build_market_universe(envelope(rows, ['ABC', 'XYZ']), NOW, min_records=1)
    assert result.eligible_equity_count == 0
    assert len(result.rejected_records) == 3
    assert {r.reason for r in result.rejected_records} == {'AMBIGUOUS_INSTRUMENT_MASTER'}


def test_identical_duplicates_deduplicate_with_reason():
    result = universe([master_row(), master_row()])
    assert result.eligible_equity_count == 1
    assert result.rejected_records[0].reason == 'DUPLICATE_INSTRUMENT'


def test_conflicts_with_ineligible_records_still_invalidate_the_token():
    result = build_market_universe(envelope([master_row(), master_row('OTHER', '123')]), NOW, min_records=1)
    assert result.eligible_equity_count == 0
    assert 'AMBIGUOUS_INSTRUMENT_MASTER' in {r.reason for r in result.rejected_records}


def test_normalization_and_exclusion(monkeypatch):
    row = master_row(symbol=' abc-eq ', exch_seg=' nse ', token=123)
    result = build_market_universe(envelope([row], [' abc-eq ']), NOW, min_records=1)
    assert result.instruments[0].symbol == 'ABC'
    monkeypatch.setattr(config, 'EXCLUSION_LIST', [' abc-eq '])
    rejected = build_market_universe(envelope([row], ['ABC']), NOW, min_records=1)
    assert rejected.rejected_records[0].reason == 'EXCLUDED_SYMBOL'


@pytest.mark.parametrize('field,value,reason', [('close', 149, 'PRICE_BELOW_DISCOVERY_MIN'),
    ('close', 351, 'PRICE_ABOVE_DISCOVERY_MAX'), ('volume', 4_999_999, 'VOLUME_BELOW_DISCOVERY_MIN'),
    ('close', float('nan'), 'INVALID_CLOSE_OR_OHLC'), ('high', float('inf'), 'INVALID_CLOSE_OR_OHLC'),
    ('low', 206, 'INVALID_OHLC'), ('volume', None, 'MISSING_VOLUME'),
    ('volume', float('inf'), 'INVALID_VOLUME'), ('turnover', -1, 'INVALID_TURNOVER')])
def test_coarse_filters_explain_every_rejection(field, value, reason):
    snap = snapshot()
    snap.records[0].update({field: value})
    if field == 'close' and value == 149:
        snap.records[0]['low'] = 140
    if field == 'close' and value == 351:
        snap.records[0]['high'] = 360
    result = discover_nse_candidates(universe(), snap, SESSION, NOW)
    assert result.success and not result.selected_candidates
    assert reason in [r.reason for r in result.rejected_candidates]


@pytest.mark.parametrize('count', [120, 17])
def test_top_cap_and_no_padding(count):
    rows = [master_row(f'S{i:03}', str(1000 + i)) for i in range(count)]
    base = build_market_universe(envelope(rows, [f'S{i:03}' for i in range(count)]), NOW,
        equity_symbols=[f'S{i:03}' for i in range(count)], min_records=1)
    records = [dict(snapshot().records[0], symbol=f'S{i:03}') for i in reversed(range(count))]
    result = discover_nse_candidates(base, snapshot(records), SESSION, NOW)
    assert len(result.selected_candidates) == min(count, config.MAX_DISCOVERY_CANDIDATES)
    assert result.selected_candidates[0].symbol == 'S000'
    assert result.selected_candidates[1].symbol == 'S001'
    assert result.coarse_qualified_count == count


@pytest.mark.parametrize('change,reason', [({'session_date': date(2026, 9, 29)}, 'CACHE_SESSION_MISMATCH'),
    ({'available_at': NOW + timedelta(minutes=1)}, 'LOOKAHEAD'),
    ({'source_timestamp': NOW.replace(tzinfo=None)}, 'LOOKAHEAD'),
    ({'source_timestamp': NOW.replace(day=30, month=9, hour=14)}, 'LOOKAHEAD')])
def test_session_and_availability_reject_lookahead(change, reason):
    result = discover_nse_candidates(universe(), snapshot(**change), SESSION, NOW)
    assert not result.success and reason in result.failure_reason


def test_full_pipeline_counts_direction_neutrality_lineage_and_core_freeze():
    before = hashlib.sha256(Path(__file__).with_name('signal_brain.py').read_bytes()).hexdigest()
    base, symbols, snap = full_market_fixture()
    calls = []
    def fetch(candidate, session):
        calls.append((candidate['symbol'], session))
        return deep_fixture(candidate, session)
    result = run_premarket_pipeline(now=NOW, market_universe=base,
        data_source=FixtureDataSource(symbols, snap), data_fetcher=fetch, pacing_interval=0.)
    assert result.discovery.raw_instrument_count == 1000
    assert result.discovery.eligible_equity_count == 600
    assert result.discovery.coarse_qualified_count == 180
    assert len(result.discovery.selected_candidates) == 60
    assert len(calls) == result.screen.total_candidates == 60
    assert {session for _, session in calls} == {SESSION} == {result.screen.session_date}
    assert len(result.screen.qualified_candidates) == 12
    assert len(result.screen.watchlist) == config.SCREEN_TOP_N == 3
    assert any(c.ema_fast < c.ema_slow for c in result.screen.qualified_candidates)
    for diagnostic in result.screen.watchlist:
        assert diagnostic.instrument is result.registry.resolve(diagnostic.symbol, diagnostic.token, NOW)
        assert diagnostic.discovery_lineage['final_rank'] in {1, 2, 3}
        assert diagnostic.discovery_lineage['discovery_session'] == SESSION.isoformat()
    assert before == FROZEN_HASH == hashlib.sha256(Path(__file__).with_name('signal_brain.py').read_bytes()).hexdigest()
    assert result.discovery.request_counts['historical_calls'] == 0
    assert result.discovery.elapsed_seconds < 2.


@pytest.mark.parametrize('auto,failure', [(False, None), (True, 'DATA_SOURCE_ERROR: reference unavailable')])
def test_configured_list_never_substitutes_for_market_discovery(monkeypatch, caplog, auto, failure):
    monkeypatch.setattr(config, 'AUTO_DISCOVER_UNIVERSE', auto)
    # Even a stale configuration enabling the retired fallback cannot re-enable it.
    monkeypatch.setattr(config, 'DISCOVERY_ALLOW_CONFIG_FALLBACK', True)
    monkeypatch.setattr(config, 'CANDIDATE_UNIVERSE', [{'symbol': 'ABC', 'trading_symbol': 'ABC-EQ',
                                                     'token': '123', 'exchange': 'NSE'}])
    result = run_premarket_pipeline(now=NOW, market_universe=universe(),
        data_source=FixtureDataSource(['ABC'], snapshot(), failure),
        data_fetcher=lambda c, d: pytest.fail('Blocked discovery cannot screen configured stocks'), pacing_interval=0.)
    assert result.readiness == 'BLOCKED'
    assert result.discovery.universe_source == 'UNAVAILABLE'
    assert result.screen.total_candidates == 0
    assert 'Using configured fallback universe' not in caplog.text
    assert result.report()['universe_audit']['configured_stock_list_used'] is False


def test_fallback_cannot_invent_or_refresh_a_configured_token(monkeypatch):
    monkeypatch.setattr(config, 'CANDIDATE_UNIVERSE', [{'symbol': 'ABC', 'trading_symbol': 'ABC-EQ',
                                                     'token': 'wrong', 'exchange': 'NSE'}])
    selected, rejected = configured_fallback(universe().registry, NOW)
    assert not selected and len(rejected) == 1


def test_dynamic_zero_or_deep_zero_never_triggers_fallback(monkeypatch):
    monkeypatch.setattr(config, 'CANDIDATE_UNIVERSE', [{'symbol': 'SHOULD_NOT_BE_USED'}])
    for volume in (6_000_000, 1):
        snap = snapshot()
        snap.records[0]['volume'] = volume
        result = run_premarket_pipeline(now=NOW, market_universe=universe(),
            data_source=FixtureDataSource(['ABC'], snap), data_fetcher=lambda c, d: None, pacing_interval=0.)
        assert result.discovery.success
        assert result.discovery.universe_source == 'DYNAMIC_NSE_DISCOVERY'
        assert result.screen.trading_day_status == 'NO_TRADE'
        assert result.screen.total_candidates == int(volume > 1)


def test_disabled_fallback_blocks_infrastructure_failure(monkeypatch):
    monkeypatch.setattr(config, 'DISCOVERY_ALLOW_CONFIG_FALLBACK', False)
    result = run_premarket_pipeline(now=NOW, market_universe=universe(),
        data_source=FixtureDataSource(['ABC'], snapshot(), 'DATA_SOURCE_ERROR'), pacing_interval=0.)
    assert result.readiness == 'BLOCKED' and not result.screen.watchlist


def test_discovery_does_not_import_strategy_or_request_history():
    import ast
    source = Path(__file__).with_name('market_discovery.py').read_text()
    modules = [node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
    assert 'signal_brain' not in modules
    assert 'getCandleData' not in source and 'generate_vwap_signal' not in source


def test_raw_eq_membership_cannot_bypass_equity_classification():
    raw = build_market_universe(envelope([master_row()]), NOW, min_records=1)
    result = discover_nse_candidates(raw, snapshot(), SESSION, NOW)
    assert not result.success and result.failure_reason == 'EQUITY_CLASSIFICATION_UNVERIFIED'


def test_partial_snapshot_availability_is_explicit():
    rows = [master_row('ABC', '123'), master_row('XYZ', '124')]
    base = build_market_universe(envelope(rows, ['ABC', 'XYZ']), NOW,
        equity_symbols=['ABC', 'XYZ'], min_records=1)
    result = discover_nse_candidates(base, snapshot(), SESSION, NOW)
    assert result.success
    assert result.missing_snapshot_count == 1 and result.snapshot_coverage_pct == 50.
    assert result.rejected_candidates[0].symbol == 'XYZ'


def bhav_bytes(session=SESSION, *, zip_output=False, field_change=None):
    header = ['TradDt', 'BizDt', 'TckrSymb', 'SctySrs', 'ClsPric', 'HghPric', 'LwPric', 'TtlTradgVol', 'TtlTrfVal']
    values = [session.isoformat(), session.isoformat(), 'ABC', 'EQ', '200', '205', '195', '6000000', '1200000000']
    if field_change:
        header[0] = field_change
    data = (','.join(header) + '\n' + ','.join(values) + '\n').encode()
    if not zip_output:
        return data
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('bhavcopy.csv', data)
    return output.getvalue()


class FakeResponse:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status
        self.closed = False

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError('fixture HTTP failure', response=self)

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        self.closed = True

    def json(self):
        return json.loads(self.content)


@pytest.fixture
def small_schema(monkeypatch):
    monkeypatch.setattr(config, 'DISCOVERY_MIN_REFERENCE_RECORDS', 1)
    monkeypatch.setattr(config, 'DISCOVERY_MIN_SNAPSHOT_RECORDS', 1)


def test_bulk_schema_parsing_and_zip(small_schema):
    for zipped in (False, True):
        records = parse_bhavcopy(bhav_bytes(zip_output=zipped), SESSION)
        assert records[0]['close'] == '200'
        assert records[0]['market_date'] == SESSION.isoformat()
    symbols = parse_equity_reference(b'SYMBOL, SERIES, ISIN NUMBER\nABC, EQ, INE123456789\n')
    assert symbols == ['ABC']


@pytest.mark.parametrize('data,reason', [(b'price,volume\n123,99\n', 'SCHEMA_VALIDATION_FAILED'),
    (bhav_bytes(date(2026, 9, 29)), 'CACHE_SESSION_MISMATCH'),
    (bhav_bytes(field_change='UnknownDate'), 'SCHEMA_VALIDATION_FAILED')])
def test_changed_or_wrong_session_schema_fails(small_schema, data, reason):
    with pytest.raises(SafetyError, match=reason):
        parse_bhavcopy(data, SESSION)


def test_session_cache_reuse_integrity_and_date_invalidation(tmp_path, small_schema):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return FakeResponse(bhav_bytes(zip_output=True))
    source = DiscoveryDataSource(tmp_path, get=get, sleep=lambda _: None, clock=lambda: NOW)
    first = source.snapshot(SESSION, NOW)
    second = source.snapshot(SESSION, NOW)
    assert len(calls) == 1 and second.cache_hit and first.records == second.records
    assert source.accounting.bulk_market_data_calls == 1
    assert source.accounting.historical_calls == source.accounting.quote_calls == 0
    cache = tmp_path / SESSION.isoformat() / 'snapshot.json'
    data = json.loads(cache.read_text())
    data['session_date'] = '2026-09-29'
    cache.write_text(json.dumps(data))
    assert not source.snapshot(SESSION, NOW).cache_hit and len(calls) == 2
    data = json.loads(cache.read_text())
    data['records'][0]['close'] = '999'
    cache.write_text(json.dumps(data))
    assert not source.snapshot(SESSION, NOW).cache_hit and len(calls) == 3


def test_bounded_retries_and_accounting(tmp_path):
    waits = []
    def get(url, **kwargs):
        assert kwargs['timeout'] == config.DISCOVERY_HTTP_TIMEOUT_SECONDS
        raise requests.Timeout('fixture')
    source = DiscoveryDataSource(tmp_path, get=get, sleep=waits.append)
    with pytest.raises(SafetyError, match='DATA_SOURCE_ERROR'):
        source.snapshot(SESSION, NOW)
    assert source.accounting.bulk_market_data_calls == config.SCREEN_API_MAX_RETRIES
    assert source.accounting.retries == config.SCREEN_API_MAX_RETRIES - 1
    assert source.accounting.failures == config.SCREEN_API_MAX_RETRIES
    assert sum(waits) > 0


def test_404_is_not_retried_and_oversized_download_fails(tmp_path, monkeypatch):
    source = DiscoveryDataSource(tmp_path, get=lambda *a, **k: FakeResponse(b'error', 404), sleep=lambda _: None)
    with pytest.raises(SafetyError):
        source.snapshot(SESSION, NOW)
    assert source.accounting.bulk_market_data_calls == 2  # Each official endpoint checked once.
    monkeypatch.setattr(config, 'DISCOVERY_MAX_DOWNLOAD_BYTES', 4)
    response = FakeResponse(b'12345')
    source = DiscoveryDataSource(tmp_path, get=lambda *a, **k: response, sleep=lambda _: None)
    with pytest.raises(SafetyError, match='too large'):
        source.download('https://fixture.invalid')
    assert response.closed


def test_future_session_is_rejected_before_external_calls(tmp_path):
    source = DiscoveryDataSource(tmp_path, get=lambda *a, **k: pytest.fail('Future data must not be requested'))
    with pytest.raises(SafetyError, match='LOOKAHEAD'):
        source.snapshot(NOW.date(), NOW)
    assert source.accounting.bulk_market_data_calls == 0


def test_master_file_freshness_schema_count_and_source(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DISCOVERY_MIN_MASTER_RECORDS', 1)
    path = tmp_path / 'master.json'
    path.write_text(json.dumps(envelope([master_row()])))
    assert load_master_envelope(path, NOW)['records'][0]['token'] == '123'
    with pytest.raises(SafetyError, match='SCHEMA_VALIDATION_FAILED'):
        build_market_universe(envelope([]), NOW)
    path.write_text(json.dumps(envelope([master_row()], stamp=NOW-timedelta(days=2))))
    with pytest.raises(SafetyError, match='STALE'):
        load_master_envelope(path, NOW)
