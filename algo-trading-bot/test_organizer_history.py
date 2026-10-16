"""History safety, causal features and production isolation with local fixtures."""
import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import stat
import zipfile

import pytest

from candle_normalizer import candles_to_frame
from exchange.base_exchange import ExchangeError
from research_intelligence.common import ResearchError, ROOT
from research_intelligence.organizer_history import (COLUMNS, FILES, HOUR_MS,
    HistoricalDataset, validate_csv, validate_directory, inspect_archive, extract_archive)
from research_intelligence.reference_price_analysis import hourly_features, chronological_price_analysis
from research_intelligence import organizer_history

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)


def content(n=40):
    return ','.join(COLUMNS) + '\n' + ''.join(
        (START + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M:%SZ') +
        f',{100+i},{102+i},{99+i},{101+i},10,2\n' for i in range(n))


@pytest.fixture
def history(tmp_path):
    directory = tmp_path / 'history'
    directory.mkdir()
    for name in FILES:
        (directory / name).write_text(content())
    return directory


def archive(path, *, addition=None, prefix=''):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as stream:
        for name in FILES:
            stream.writestr(prefix + name, content())
        stream.writestr(prefix + 'README.md', 'Reference data only.\n')
        if addition:
            info, data = addition
            stream.writestr(info, data)
    return path


def test_all_markets_are_validated_without_official_provenance_claim(history):
    report = validate_directory(history, now_ms=NOW)
    assert report['schema_valid'] and report['complete_hourly_coverage']
    assert report['total_rows'] == 400
    assert not report['official_provenance_verified']
    assert not report['strategy_timeframe_compatible']


@pytest.mark.parametrize('old,new,reason', [
    ('time,open', 'timestamp,open', 'CSV_COLUMNS_MISMATCH'),
    ('2026-01-01T00:00:00Z', '2026-01-01T00:00:00', 'EXPLICIT_UTC_TIMESTAMP_REQUIRED'),
    ('2026-01-01T00:00:00Z', '2026-01-01T00:01:00Z', 'MISALIGNED_HOURLY_TIMESTAMP'),
    (',100,102,99,101,10,2', ',100,98,99,101,10,2', 'IMPOSSIBLE_OHLC'),
    (',100,102,99,101,10,2', ',0,102,99,101,10,2', 'INVALID_NUMERIC_VALUE'),
    (',100,102,99,101,10,2', ',100,102,99,101,NaN,2', 'INVALID_NUMERIC_VALUE'),
    (',100,102,99,101,10,2', ',100,102,99,101,10,-1', 'INVALID_TRADE_COUNT'),
    (',100,102,99,101,10,2', ',100,102,99,101,0,2', 'ZERO_VOLUME_WITH_REPORTED_TRADES'),
    (',100,102,99,101,10,2', ',100,102,99,101,10,2,extra', 'CSV_FIELD_COUNT_MISMATCH')])
def test_bad_csv_fails_without_repair(history, old, new, reason):
    path = history / 'BTC.csv'
    path.write_text(path.read_text().replace(old, new, 1))
    before = path.read_bytes()
    report, _ = validate_csv(path, now_ms=NOW)
    assert report['status'] == 'FAIL' and reason in report['issues']
    assert path.read_bytes() == before


def test_duplicates_and_wrong_order_are_reported_and_rejected(history):
    p = history / 'BTC.csv'
    rows = p.read_text().splitlines()
    p.write_text('\n'.join(rows[:3] + [rows[1]] + rows[3:]) + '\n')
    report, _ = validate_csv(p, now_ms=NOW)
    assert report['duplicates'] == report['duplicate_rows'] == 1
    assert not report['chronological'] and report['status'] == 'FAIL'
    with pytest.raises(ResearchError, match='HISTORY_VALIDATION_FAILED'):
        HistoricalDataset(history, now_ms=NOW)


def test_real_gaps_are_not_filled_and_features_reset_at_gap(history):
    p = history / 'BTC.csv'
    rows = p.read_text().splitlines()
    p.write_text('\n'.join(rows[:5] + rows[6:]) + '\n')
    report, bars = validate_csv(p, now_ms=NOW)
    assert report['missing_rows'] == 1 and report['status'] == 'PASS_WITH_GAPS'
    feature = next(r for r in hourly_features(bars) if r['candle_open_ms'] == bars[4].timestamp_ms)
    assert feature['hourly_close_to_close_return'] is None
    assert not feature['hourly_atr_full_window']
    assert len(bars) == 39


def test_missing_market_or_unexpected_script_blocks_dataset(history):
    (history / 'BTC.csv').unlink()
    assert validate_directory(history, now_ms=NOW)['missing_files'] == ['BTC.csv']
    (history / 'BTC.csv').write_text(content())
    (history / 'setup.py').write_text('raise RuntimeError("NEVER EXECUTE")')
    assert not validate_directory(history, now_ms=NOW)['schema_valid']


def test_open_hour_is_not_available_at_its_start(history):
    dataset = HistoricalDataset(history, now_ms=NOW)
    first = dataset.bars['par:BTC'][0]
    assert dataset.as_of('par:BTC', first.timestamp_ms + HOUR_MS - 1) == ()
    assert dataset.as_of('par:BTC', first.timestamp_ms + HOUR_MS) == (first,)


def test_future_candle_is_not_accepted_even_with_valid_ohlcv(history):
    report, _ = validate_csv(history / 'BTC.csv', now_ms=int(START.timestamp() * 1000))
    assert report['status'] == 'FAIL' and 'FUTURE_OR_INCOMPLETE_HOUR' in report['issues']


def test_hourly_history_cannot_be_passed_to_production_minute_adapter(history):
    dataset = HistoricalDataset(history, now_ms=NOW)
    bars = dataset.bars['par:BTC']
    with pytest.raises(ExchangeError, match='STRATEGY_CANDLE_IDENTITY_MISMATCH'):
        candles_to_frame(bars)
    with pytest.raises(ResearchError, match='HOURLY_REFERENCE_IDENTITY_REQUIRED'):
        replace(bars[0], interval='1m')
    assert not hasattr(dataset, 'get_quote') and not hasattr(dataset, 'get_candles')


def test_future_prices_cannot_change_past_features(history):
    bars = HistoricalDataset(history, now_ms=NOW).bars['par:BTC']
    before = hourly_features(bars[:20])
    altered = list(bars)
    altered[20:] = [replace(b, high=b.high * 100, close=b.close * 2) for b in bars[20:]]
    assert hourly_features(altered)[:20] == before
    assert all(r['decision_ms'] == r['candle_open_ms'] + HOUR_MS for r in before)
    assert all(r['label'] is None and r['spread'] is None and r['fills'] is None for r in before)


def test_holdout_prices_are_reserved_and_no_executable_labels_created(history):
    dataset = HistoricalDataset(history, now_ms=NOW)
    analysis, rows = chronological_price_analysis(dataset)
    boundary = analysis['shared_utc_boundaries']['holdout_start_ms']
    assert all(r['decision_ms'] < boundary for r in rows)
    assert not analysis['holdout_prices_evaluated'] and not analysis['ml_data_ready']
    assert not analysis['production_changed'] and not analysis['promotion_recommended']
    assert set(r['partition'] for r in rows) == {'TRAIN', 'VALIDATION'}


def test_truncated_utc_day_does_not_claim_a_complete_vwap_proxy(history):
    bars = HistoricalDataset(history, now_ms=NOW).bars['par:BTC']
    rows = hourly_features(bars[5:])
    assert not rows[0]['utc_day_hour_coverage_complete']
    assert rows[0]['utc_hourly_bar_vwap_proxy'] is None
    midnight = next(r for r in rows if r['utc_hour'] == 0)
    assert midnight['utc_day_hour_coverage_complete']
    assert midnight['utc_hourly_bar_vwap_proxy'] is not None


@pytest.mark.parametrize('name', ['../attack.py', '/absolute.csv', 'history/../../evil.csv',
    'history\\BTC.csv', 'C:BTC.csv', 'history/setup.py', 'unapproved/BTC.csv'])
def test_unsafe_zip_members_never_extract(history, tmp_path, name):
    p = archive(tmp_path / 'bad.zip', addition=(name, 'data'))
    destination = history / 'extracted'
    with pytest.raises(ResearchError):
        extract_archive(p, destination, data_root=history)
    assert not destination.exists()


@pytest.mark.parametrize('mode', [stat.S_IFLNK | 0o777, stat.S_IFREG | 0o755])
def test_symlink_or_executable_zip_member_rejected(history, tmp_path, mode):
    info = zipfile.ZipInfo('README.md')
    info.create_system = 3; info.external_attr = mode << 16
    with pytest.warns(UserWarning, match='Duplicate name'):
        p = archive(tmp_path / 'bad.zip', addition=(info, 'target'))
    with pytest.raises(ResearchError, match='UNSAFE_ZIP_MEMBER_TYPE'):
        inspect_archive(p)


def test_zip_duplicate_rejected(history, tmp_path):
    with pytest.warns(UserWarning):
        p = archive(tmp_path / 'bad.zip', addition=('BTC.csv', content()))
    with pytest.raises(ResearchError, match='DUPLICATE_ZIP_FILE'):
        inspect_archive(p)


def test_good_zip_extracts_only_data_into_new_history_child(history, tmp_path):
    p = archive(tmp_path / 'safe.zip', prefix='history/')
    with zipfile.ZipFile(p, 'a') as stream:
        stream.writestr('history/', '')
    old = (history / 'BTC.csv').read_bytes()
    report = extract_archive(p, history / 'extracted', data_root=history)
    assert report['passed'] and report['extraction_performed'] and report['validation']['schema_valid']
    assert (history / 'BTC.csv').read_bytes() == old
    with pytest.raises(ResearchError, match='NEW_DEDICATED_EXTRACTION_DIRECTORY_REQUIRED'):
        extract_archive(p, history / 'extracted', data_root=history)


def test_extraction_outside_history_and_symlink_root_rejected(history, tmp_path):
    p = archive(tmp_path / 'safe.zip')
    with pytest.raises(ResearchError, match='NEW_DEDICATED_EXTRACTION_DIRECTORY_REQUIRED'):
        extract_archive(p, tmp_path / 'other', data_root=history)
    linked = tmp_path / 'linked'
    linked.symlink_to(history, target_is_directory=True)
    with pytest.raises(ResearchError, match='SYMLINK_EXTRACTION_ROOT_PROHIBITED'):
        extract_archive(p, linked / 'extracted', data_root=linked)


def test_archive_change_after_inspection_removes_only_new_output(history, tmp_path, monkeypatch):
    p = archive(tmp_path / 'changing.zip')
    original = organizer_history.inspect_archive
    def inspect_then_change(path):
        report = original(path)
        archive(path, addition=('notes.txt', 'unexpected after inspection'))
        return report
    monkeypatch.setattr(organizer_history, 'inspect_archive', inspect_then_change)
    old = (history / 'BTC.csv').read_bytes()
    with pytest.raises(ResearchError, match='ARCHIVE_CHANGED_AFTER_INSPECTION'):
        extract_archive(p, history / 'extracted', data_root=history)
    assert not (history / 'extracted').exists()
    assert (history / 'BTC.csv').read_bytes() == old


def test_changed_csv_cannot_reuse_an_earlier_validation(history, monkeypatch):
    original = organizer_history.validate_directory
    def validate_then_change(directory, **kwargs):
        report = original(directory, **kwargs)
        p = Path(directory) / 'BTC.csv'
        p.write_text(content(41))
        return report
    monkeypatch.setattr(organizer_history, 'validate_directory', validate_then_change)
    with pytest.raises(ResearchError, match='HISTORY_CHANGED_AFTER_VALIDATION'):
        HistoricalDataset(history, now_ms=NOW)


def test_zip_expansion_bomb_rejected_before_output(history, tmp_path):
    p = tmp_path / 'large.zip'
    # Highly compressible data in an otherwise whitelisted text filename.
    with zipfile.ZipFile(p, 'w', compression=zipfile.ZIP_DEFLATED) as stream:
        for name in FILES:
            stream.writestr(name, content())
        stream.writestr('README.md', 'a' * 5_000_000)
    with pytest.raises(ResearchError, match='ZIP_EXPANSION_LIMIT'):
        extract_archive(p, history / 'extracted', data_root=history)
    assert not (history / 'extracted').exists()


def test_production_entry_points_do_not_import_historical_research():
    # Transitive AST imports from the actual production entry points. Tests,
    # research runners and audit-only modules are not production entry points.
    pending = [ROOT / 'scripts/run_crypto_paper.py', ROOT / 'scripts/run_practice.py',
               ROOT / 'scripts/run_testnet_practice.py']
    seen = set()
    base = ROOT / 'algo-trading-bot'
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not name.startswith(('research_intelligence', 'research_lab'))
                if isinstance(node, ast.ImportFrom) and node.level:
                    parent = path.parent
                    for _ in range(node.level - 1):
                        parent = parent.parent
                    target = parent.joinpath(*name.split('.')).with_suffix('.py')
                else:
                    target = base.joinpath(*name.split('.')).with_suffix('.py')
                    if not target.exists():
                        target = (ROOT / 'scripts').joinpath(*name.split('.')).with_suffix('.py')
                if target.exists():
                    pending.append(target)
    assert base / 'exchange/hyperliquid_market_data.py' in seen
    assert base / 'research_intelligence/organizer_history.py' not in seen
