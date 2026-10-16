"""Read-only hourly reference data. No market client, order methods or live adapter.

The availability convention is bar close, not a verified historical publication
receipt. Mainnet reference OHLCV cannot certify competition execution or labels.
"""
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

from .common import MARKETS, ResearchError, ROOT, stamp

COLUMNS = ('time', 'open', 'high', 'low', 'close', 'volume', 'trades')
HOUR_MS = 3_600_000
FILES = {s.split(':')[1] + '.csv': s for s in MARKETS}
SOURCE_MARKETS = dict(zip(MARKETS, ('BTC', 'ETH', 'HYPE', 'xyz:SP500', 'xyz:EWY',
    'xyz:EWJ', 'xyz:BRENTOIL', 'xyz:GOLD', 'xyz:EUR', 'xyz:JPY')))
DATA_ROOT = ROOT / 'algo-trading-bot/data/history'


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value, *, positive=False):
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ResearchError('NONNUMERIC_VALUE') from None
    if not result.is_finite() or result < 0 or positive and result <= 0:
        raise ResearchError('INVALID_NUMERIC_VALUE')
    return result


def hour_start(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
        raise ResearchError('EXPLICIT_UTC_TIMESTAMP_REQUIRED')
    try:
        result = int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        raise ResearchError('INVALID_TIMESTAMP') from None
    if result < 0 or result % HOUR_MS:
        raise ResearchError('MISALIGNED_HOURLY_TIMESTAMP')
    return result


@dataclass(frozen=True)
class HistoricalBar:
    symbol: str
    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int
    interval: str = '1h'
    source: str = 'MAINNET_REFERENCE_OHLCV_RESEARCH_ONLY'

    def __post_init__(self):
        if (self.symbol not in MARKETS or self.interval != '1h' or
                self.source != 'MAINNET_REFERENCE_OHLCV_RESEARCH_ONLY' or
                type(self.timestamp_ms) is not int or self.timestamp_ms < 0 or self.timestamp_ms % HOUR_MS):
            raise ResearchError('HOURLY_REFERENCE_IDENTITY_REQUIRED')

    @property
    def close_timestamp_ms(self):
        return self.timestamp_ms + HOUR_MS


def validate_csv(path, *, now_ms=None):
    path = Path(path)
    if path.name not in FILES or path.is_symlink() or not path.is_file():
        raise ResearchError('EXPECTED_REGULAR_MARKET_CSV_REQUIRED')
    now_ms = stamp(now_ms) if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    raw = path.read_bytes()
    report = dict(market=FILES[path.name], source_market=SOURCE_MARKETS[FILES[path.name]],
        path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(), interval='1h',
        rows=0, start_timestamp=None, end_timestamp=None, missing_rows=0,
        duplicates=0, duplicate_rows=0, invalid_values=0, chronological=True,
        missing_hour_examples=[], issues={}, examples=[], status='FAIL',
        missing_scope='Only hours between first and last valid timestamps; no pre-listing rows assumed')
    issues = Counter()
    bars = []
    times = []
    seen_times = set()
    seen_rows = set()
    previous = None
    def issue(line, reason):
        issues[reason] += 1
        if len(report['examples']) < 10:
            report['examples'].append(dict(line=line, reason=reason))
    try:
        reader = csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        if tuple(next(reader, ())) != COLUMNS:
            raise ResearchError('CSV_COLUMNS_MISMATCH')
        for line, values in enumerate(reader, 2):
            report['rows'] += 1
            if len(values) != len(COLUMNS):
                report['invalid_values'] += 1
                issue(line, 'CSV_FIELD_COUNT_MISMATCH')
                continue
            row = tuple(values)
            if row in seen_rows:
                report['duplicate_rows'] += 1
            seen_rows.add(row)
            try:
                t = hour_start(values[0])
                times.append(t)
                if t in seen_times:
                    report['duplicates'] += 1
                    issue(line, 'DUPLICATE_TIMESTAMP')
                seen_times.add(t)
                if previous is not None and t <= previous:
                    report['chronological'] = False
                    issue(line, 'NONCHRONOLOGICAL_TIMESTAMP')
                previous = t
                if t + HOUR_MS > now_ms:
                    raise ResearchError('FUTURE_OR_INCOMPLETE_HOUR')
                o, h, low, close = [number(v, positive=True) for v in values[1:5]]
                volume = number(values[5])
                if h < max(o, low, close) or low > min(o, h, close):
                    raise ResearchError('IMPOSSIBLE_OHLC')
                if not re.fullmatch(r'\d+', values[6]):
                    raise ResearchError('INVALID_TRADE_COUNT')
                trades = int(values[6])
                if volume == 0 and trades > 0:
                    raise ResearchError('ZERO_VOLUME_WITH_REPORTED_TRADES')
                bars.append(HistoricalBar(FILES[path.name], t, o, h, low, close, volume, trades))
            except ResearchError as exc:
                report['invalid_values'] += 1
                issue(line, str(exc))
    except (UnicodeError, csv.Error, ResearchError) as exc:
        issue(None, str(exc) if isinstance(exc, ResearchError) else 'UNREADABLE_CSV')
        report['invalid_values'] += 1
    if times:
        ordered = sorted(set(times))  # Diagnostic only; never sorts accepted input.
        report['start_timestamp'] = datetime.fromtimestamp(ordered[0] / 1000, timezone.utc).isoformat()
        report['end_timestamp'] = datetime.fromtimestamp(ordered[-1] / 1000, timezone.utc).isoformat()
        for a, b in zip(ordered, ordered[1:]):
            count = (b - a) // HOUR_MS - 1
            if count > 0:
                report['missing_rows'] += count
                if len(report['missing_hour_examples']) < 10:
                    report['missing_hour_examples'].append(dict(first_missing_ms=a + HOUR_MS, count=count))
    if not report['rows']:
        issue(None, 'EMPTY_MARKET_HISTORY')
    report['issues'] = dict(issues)
    if not issues:
        report['status'] = 'PASS_WITH_GAPS' if report['missing_rows'] else 'PASS'
    return report, tuple(bars)


def validate_directory(directory, *, now_ms=None):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ResearchError('REGULAR_HISTORY_DIRECTORY_REQUIRED')
    discovered = sorted(p.name for p in directory.iterdir())
    missing = sorted(set(FILES) - set(discovered))
    unexpected = [name for name in discovered if name not in {*FILES, 'README.md', 'history.zip', '.DS_Store'}]
    reports = [validate_csv(directory / name, now_ms=now_ms)[0] for name in sorted(FILES) if name in discovered]
    return dict(directory=str(directory.resolve()), discovered=discovered, missing_files=missing,
        unexpected_files=unexpected, markets=reports, total_rows=sum(r['rows'] for r in reports),
        schema_valid=not missing and not unexpected and all(r['status'] != 'FAIL' for r in reports),
        complete_hourly_coverage=not missing and len(reports) == len(FILES) and all(r['status'] == 'PASS' for r in reports),
        official_provenance_verified=False, source_kind='CLAIMED_MAINNET_REFERENCE_OHLCV',
        execution_capability=False, strategy_timeframe_compatible=False,
        source_note='README claims organizer/mainnet origin; content checks alone cannot authenticate that claim.')


class HistoricalDataset:
    execution_capability = False
    production_strategy_compatible = False

    def __init__(self, directory, *, now_ms=None):
        self.directory = Path(directory)
        self.validation = validate_directory(directory, now_ms=now_ms)
        if not self.validation['schema_valid']:
            raise ResearchError('HISTORY_VALIDATION_FAILED')
        self.bars = {}
        for expected in self.validation['markets']:
            result, bars = validate_csv(self.directory / Path(expected['path']).name, now_ms=now_ms)
            if result['status'] == 'FAIL' or result['sha256'] != expected['sha256']:
                raise ResearchError('HISTORY_CHANGED_AFTER_VALIDATION')
            self.bars[result['market']] = bars

    def as_of(self, symbol, decision_ms):
        decision_ms = stamp(decision_ms)
        if symbol not in self.bars:
            raise ResearchError('UNKNOWN_RESEARCH_MARKET')
        # The current hour's high/low/volume become available only after close.
        return tuple(b for b in self.bars[symbol] if b.close_timestamp_ms <= decision_ms)


def inspect_archive(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000_000:
        raise ResearchError('REGULAR_BOUNDED_ZIP_REQUIRED')
    files = []
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or len(members) > 64:
            raise ResearchError('ZIP_MEMBER_LIMIT')
        seen = set()
        total = 0
        for member in members:
            name = member.orig_filename
            parts = PurePosixPath(name).parts
            if (not name or '\\' in name or '\x00' in name or ':' in name or name.startswith('/') or
                    any(p in {'.', '..'} for p in name.split('/')) or len(parts) > 2):
                raise ResearchError('UNSAFE_ZIP_PATH')
            if len(parts) == 2 and parts[0] not in {'history', 'perpetual_alpha_history'}:
                raise ResearchError('UNEXPECTED_ZIP_DIRECTORY')
            mode = member.external_attr >> 16
            if (stat.S_ISLNK(mode) or not member.is_dir() and mode & 0o111 or
                    stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR} or member.flag_bits & 1):
                raise ResearchError('UNSAFE_ZIP_MEMBER_TYPE')
            if member.is_dir():
                if parts not in {('history',), ('perpetual_alpha_history',)}:
                    raise ResearchError('UNEXPECTED_ZIP_DIRECTORY')
                continue
            basename = parts[-1]
            if basename not in {*FILES, 'README.md'} or basename.casefold() in seen:
                raise ResearchError('UNEXPECTED_OR_DUPLICATE_ZIP_FILE')
            seen.add(basename.casefold())
            total += member.file_size
            if (member.file_size > 16_000_000 or total > 100_000_000 or
                    member.file_size > 1000 * max(member.compress_size, 1) or
                    member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ResearchError('ZIP_EXPANSION_LIMIT')
            content = archive.read(member)  # CRC checked; no script is executed.
            try:
                content.decode('utf-8-sig')
            except UnicodeError:
                raise ResearchError('NON_TEXT_ZIP_MEMBER') from None
            files.append(dict(member=member.filename, filename=basename, size=member.file_size,
                              sha256=hashlib.sha256(content).hexdigest()))
    if {f['filename'] for f in files if f['filename'].endswith('.csv')} != set(FILES):
        raise ResearchError('MISSING_ARCHIVE_MARKETS')
    return dict(path=str(path.resolve()), sha256=file_sha(path), files=files,
                suspicious_files=[], passed=True, extraction_performed=False)


def extract_archive(path, destination, *, data_root=DATA_ROOT):
    report = inspect_archive(path)
    destination, data_root = Path(destination), Path(data_root)
    if data_root.is_symlink() or any(p.is_symlink() for p in destination.parents) or destination.is_symlink():
        raise ResearchError('SYMLINK_EXTRACTION_ROOT_PROHIBITED')
    resolved = destination.resolve()
    if not resolved.is_relative_to(data_root.resolve()) or resolved == data_root.resolve() or destination.exists():
        raise ResearchError('NEW_DEDICATED_EXTRACTION_DIRECTORY_REQUIRED')
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in report['files']:
                content = archive.read(entry['member'])
                if hashlib.sha256(content).hexdigest() != entry['sha256']:
                    raise ResearchError('ARCHIVE_CHANGED_AFTER_INSPECTION')
                with (destination / entry['filename']).open('xb') as stream:
                    stream.write(content)
        if file_sha(path) != report['sha256']:
            raise ResearchError('ARCHIVE_CHANGED_AFTER_INSPECTION')
        validation = validate_directory(destination)
        if not validation['schema_valid']:
            raise ResearchError('EXTRACTED_HISTORY_VALIDATION_FAILED')
        report.update(extraction_performed=True, destination=str(resolved), validation=validation)
    except Exception:
        shutil.rmtree(destination)  # Only the new directory created by this call.
        raise
    return report
