"""Official bulk files with bounded HTTP, schema validation and dated caches."""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from datetime import date, datetime
import hashlib
import io
import json
import logging
from pathlib import Path
import tempfile
import time
import zipfile

import requests
import config
from execution_safety import SafetyError
from market_discovery import MarketSnapshot
from market_universe import normalize_symbol, validate_source_timestamp

logger = logging.getLogger(__name__)


@dataclass
class RequestAccounting:
    instrument_source_calls: int = 0
    bulk_market_data_calls: int = 0
    quote_calls: int = 0
    historical_calls: int = 0
    retries: int = 0
    failures: int = 0
    cache_hits: int = 0

    def report(self):
        return asdict(self)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, suffix='.tmp', delete=False) as file:
            temp_path = Path(file.name)
            json.dump(data, file, default=str, sort_keys=True)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def checksum(records):
    payload = json.dumps(records, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def csv_records(content, required):
    try:
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        fields = [f.strip() for f in (reader.fieldnames or [])]
        if len(set(fields)) != len(fields) or not required.issubset(fields):
            raise SafetyError('SCHEMA_VALIDATION_FAILED: missing/duplicate CSV columns')
        reader.fieldnames = fields
        rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise SafetyError('SCHEMA_VALIDATION_FAILED: malformed CSV row')
        return rows
    except (UnicodeError, csv.Error) as exc:
        raise SafetyError('SCHEMA_VALIDATION_FAILED: CSV') from exc


def parse_equity_reference(content):
    rows = csv_records(content, {'SYMBOL', 'SERIES', 'ISIN NUMBER'})
    if len(rows) < config.DISCOVERY_MIN_REFERENCE_RECORDS:
        raise SafetyError('SCHEMA_VALIDATION_FAILED: reference record count')
    symbols = set()
    for row in rows:
        if str(row['SERIES']).strip().upper() != 'EQ':
            continue
        symbol = normalize_symbol(row['SYMBOL'])
        isin = row['ISIN NUMBER'].strip().upper()
        if not symbol or not isin.startswith('IN') or len(isin) != 12:
            raise SafetyError('SCHEMA_VALIDATION_FAILED: equity reference identity')
        if symbol in symbols:
            raise SafetyError('SCHEMA_VALIDATION_FAILED: duplicate equity reference')
        symbols.add(symbol)
    if not symbols:
        raise SafetyError('SCHEMA_VALIDATION_FAILED: empty equity reference')
    return sorted(symbols)


def parse_bhavcopy(content, expected_session):
    try:
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if (len(members) != 1 or not members[0].filename.lower().endswith('.csv') or
                        members[0].file_size > config.DISCOVERY_MAX_DOWNLOAD_BYTES):
                    raise SafetyError('SCHEMA_VALIDATION_FAILED: bhavcopy archive')
                content = archive.read(members[0])
        rows = csv_records(content, {'TradDt', 'BizDt', 'TckrSymb', 'SctySrs',
            'ClsPric', 'HghPric', 'LwPric', 'TtlTradgVol', 'TtlTrfVal'})
        if len(rows) < config.DISCOVERY_MIN_SNAPSHOT_RECORDS:
            raise SafetyError('SCHEMA_VALIDATION_FAILED: snapshot record count')
        records = []
        for row in rows:
            # Enforce the date on *every* row before filtering any security.
            if (date.fromisoformat(row['TradDt'].strip()) != expected_session or
                    date.fromisoformat(row['BizDt'].strip()) != expected_session):
                raise SafetyError('CACHE_SESSION_MISMATCH')
            records.append({'symbol': normalize_symbol(row['TckrSymb']),
                'series': row['SctySrs'].strip().upper(), 'market_date': expected_session.isoformat(),
                'close': row['ClsPric'].strip(), 'high': row['HghPric'].strip(),
                'low': row['LwPric'].strip(), 'volume': row['TtlTradgVol'].strip(),
                'turnover': row['TtlTrfVal'].strip()})
        return records
    except (ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, SafetyError):
            raise
        raise SafetyError('SCHEMA_VALIDATION_FAILED: bhavcopy') from exc


class DiscoveryDataSource:
    def __init__(self, cache_dir=None, *, get=None, sleep=time.sleep, clock=None):
        self.cache_dir = Path(cache_dir or config.DISCOVERY_CACHE_DIR or
                              Path(__file__).parent / 'data' / 'cache' / 'discovery')
        self.get = get or requests.get
        self.sleep = sleep
        self.accounting = RequestAccounting()
        self._last_request = None
        self.clock = clock

    def request(self, url, *, category='bulk_market_data_calls', **kwargs):
        """Sequential only. Counts every attempt, including refresh source calls."""
        attempts = config.SCREEN_API_MAX_RETRIES
        last_error = None
        for attempt in range(attempts):
            response = None
            if self._last_request is not None:
                elapsed = time.monotonic() - self._last_request
                self.sleep(max(0., config.SCREEN_API_REQUEST_INTERVAL - elapsed))
            if attempt:
                self.accounting.retries += 1
                self.sleep(config.SCREEN_API_BACKOFF_BASE * (2 ** (attempt - 1)))
            setattr(self.accounting, category, getattr(self.accounting, category) + 1)
            try:
                self._last_request = time.monotonic()
                kwargs['timeout'] = config.DISCOVERY_HTTP_TIMEOUT_SECONDS
                response = self.get(url, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                self.accounting.failures += 1
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                logger.warning('[DISCOVERY DATA] request failed attempt=%s status=%s error=%s',
                               attempt + 1, status, type(exc).__name__)
                if response is not None:
                    response.close()
                if status is not None and status < 500 and status != 429:
                    break
        raise SafetyError('DATA_SOURCE_ERROR: bounded HTTP failure') from last_error

    def instrument_get(self, url, **kwargs):
        return self.request(url, category='instrument_source_calls', **kwargs)

    def download(self, url):
        response = self.request(url, stream=True, headers={'User-Agent': 'AutonomousTradingBot/1.0'})
        chunks = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > config.DISCOVERY_MAX_DOWNLOAD_BYTES:
                    raise SafetyError('SCHEMA_VALIDATION_FAILED: download too large')
                chunks.append(chunk)
        except requests.RequestException as exc:
            self.accounting.failures += 1
            raise SafetyError('DATA_SOURCE_ERROR: incomplete download') from exc
        finally:
            response.close()
        if not total:
            raise SafetyError('SCHEMA_VALIDATION_FAILED: empty download')
        return b''.join(chunks)

    def _load_cache(self, path, session, source, schema, now, *, reference=False):
        data = json.loads(path.read_text())
        if data.get('session_date') != session.isoformat():
            raise SafetyError('CACHE_SESSION_MISMATCH')
        if data.get('source') != source or data.get('schema_version') != schema:
            raise SafetyError('SCHEMA_VALIDATION_FAILED: cache source/schema')
        records = data.get('records')
        if (not isinstance(records, list) or data.get('record_count') != len(records) or
                data.get('checksum') != checksum(records)):
            raise SafetyError('SCHEMA_VALIDATION_FAILED: cache checksum/count')
        source_stamp = datetime.fromisoformat(data['source_timestamp'])
        available = datetime.fromisoformat(data['available_at'])
        if (source_stamp.tzinfo is None or available.tzinfo is None or
                not source_stamp <= available <= now):
            raise SafetyError('LOOKAHEAD_OR_INVALID_AVAILABILITY')
        if reference:
            validate_source_timestamp(source_stamp, now)
            if (len(records) < config.DISCOVERY_MIN_REFERENCE_RECORDS or
                    any(not isinstance(s, str) or not s or s != normalize_symbol(s) for s in records) or
                    len(records) != len(set(records))):
                raise SafetyError('SCHEMA_VALIDATION_FAILED: reference cache')
        else:
            from market_schedule import get_market_schedule
            schedule = get_market_schedule('NSE')
            close = datetime.combine(session, schedule.market_close_time, tzinfo=schedule.timezone)
            if source_stamp < close:
                raise SafetyError('LOOKAHEAD_OR_INVALID_AVAILABILITY')
            if len(records) < config.DISCOVERY_MIN_SNAPSHOT_RECORDS:
                raise SafetyError('SCHEMA_VALIDATION_FAILED: snapshot cache count')
            required = {'symbol', 'series', 'market_date', 'close', 'high', 'low', 'volume', 'turnover'}
            if any(not isinstance(row, dict) or not required.issubset(row) for row in records):
                raise SafetyError('SCHEMA_VALIDATION_FAILED: snapshot cache columns')
            if any(row['market_date'] != session.isoformat() for row in records):
                raise SafetyError('CACHE_SESSION_MISMATCH')
        self.accounting.cache_hits += 1
        return data

    def _dataset(self, session, now, *, reference=False):
        if now.tzinfo is None or session >= now.date():
            raise SafetyError('LOOKAHEAD_OR_INVALID_AVAILABILITY')
        source = (config.DISCOVERY_EQUITY_REFERENCE_URL if reference else
                  config.DISCOVERY_BHAVCOPY_URL.format(session=session.strftime('%Y%m%d')))
        schema = 'NSE_EQUITY_REFERENCE_V1' if reference else 'NSE_CM_UDIFF_V1'
        path = self.cache_dir / session.isoformat() / ('equities.json' if reference else 'snapshot.json')
        try:
            data = self._load_cache(path, session, source, schema, now, reference=reference)
            return data, True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if path.exists():
                logger.warning('[DISCOVERY CACHE] cache rejected; reloading | %s', exc)
        content = self.download(source)
        records = parse_equity_reference(content) if reference else parse_bhavcopy(content, session)
        acquired = self.clock() if self.clock else datetime.now(tz=now.tzinfo)
        data = {'source': source, 'session_date': session.isoformat(), 'source_timestamp': acquired.isoformat(),
            'available_at': acquired.isoformat(), 'download_timestamp': acquired.isoformat(), 'schema_version': schema,
            'record_count': len(records), 'checksum': checksum(records), 'records': records}
        try:
            atomic_json(path, data)
        except OSError as exc:
            # Valid in-memory data may still be used; failed cache is explicit.
            logger.warning('[DISCOVERY CACHE] write unavailable | %s', type(exc).__name__)
        return data, False

    def equity_symbols(self, session, now):
        data, _ = self._dataset(session, now, reference=True)
        return data['records']

    def snapshot(self, session, now):
        data, hit = self._dataset(session, now)
        return MarketSnapshot(session, data['source'], datetime.fromisoformat(data['source_timestamp']),
            datetime.fromisoformat(data['available_at']), data['records'], data['checksum'], hit)
