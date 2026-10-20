"""Canonical NSE equity discovery, reusing the execution instrument registry."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path

import config
from execution_safety import InstrumentIdentity, SafetyError
from instrument_registry import InstrumentRegistry

logger = logging.getLogger(__name__)


def normalize_symbol(value):
    symbol = str(value or '').strip().upper()
    return symbol[:-3].strip() if symbol.endswith('-EQ') else symbol


def validate_source_timestamp(value, now):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if stamp.tzinfo is None or now.tzinfo is None:
            raise ValueError('Timezone required')
        if not timedelta(0) <= now - stamp <= timedelta(hours=config.INSTRUMENT_MAX_AGE_HOURS):
            raise ValueError('Source age')
    except (TypeError, ValueError) as exc:
        raise SafetyError('STALE_INSTRUMENT_MASTER') from exc
    return stamp


@dataclass(frozen=True)
class UniverseRejection:
    record_index: int
    symbol: str
    reason: str


@dataclass
class MarketUniverse:
    raw_instrument_count: int
    registry: InstrumentRegistry
    rejected_records: list[UniverseRejection]
    source_timestamp: datetime
    sources: list[str]
    equity_classification_verified: bool = False

    @property
    def instruments(self):
        return [self.registry.by_symbol[s] for s in sorted(self.registry.by_symbol)]

    @property
    def eligible_equity_count(self):
        return len(self.registry.by_symbol)

    def equity_only(self, equity_symbols):
        """Retain the exact canonical identity objects, without parsing them again."""
        stocks = {normalize_symbol(s) for s in equity_symbols}
        registry = InstrumentRegistry([], self.source_timestamp, [])
        rejected = list(self.rejected_records)
        for identity in self.instruments:
            if identity.symbol not in stocks:
                rejected.append(UniverseRejection(-1, identity.symbol, 'NOT_EQUITY'))
            else:
                registry.by_symbol[identity.symbol] = identity
                registry.by_token[identity.token] = identity
        return MarketUniverse(self.raw_instrument_count, registry, rejected, self.source_timestamp, self.sources, True)


def load_master_envelope(path, now):
    try:
        source = Path(path)
        data = json.loads(source.read_text())
        validate_source_timestamp(data.get('source_timestamp'), now)
        modified = datetime.fromtimestamp(source.stat().st_mtime, tz=now.tzinfo)
        # A refresh can finish after the frozen startup/session-resolution clock.
        validate_source_timestamp(modified, max(now, datetime.now(tz=now.tzinfo)))
        if not isinstance(data.get('records'), list):
            raise SafetyError('SCHEMA_VALIDATION_FAILED: instrument records')
        return data
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, SafetyError):
            raise
        raise SafetyError('INSTRUMENT_MASTER_UNAVAILABLE') from exc


def build_market_universe(envelope, now, equity_symbols=None, *, min_records=None):
    """No candidate cap here. EQ alone cannot distinguish stocks from ETFs.

    Dynamic discovery supplies NSE's equity-share reference membership. Without
    it this intermediate universe cannot certify a whole-market stock universe.
    """
    if not isinstance(envelope, dict):
        raise SafetyError('SCHEMA_VALIDATION_FAILED: instrument envelope')
    stamp = validate_source_timestamp(envelope.get('source_timestamp'), now)
    records = envelope.get('records')
    eligible = envelope.get('intraday_symbols')
    restricted = envelope.get('restricted_symbols', [])
    floor = config.DISCOVERY_MIN_MASTER_RECORDS if min_records is None else min_records
    if (not isinstance(records, list) or len(records) < floor or
            not isinstance(eligible, list) or not eligible or
            not all(isinstance(s, str) and s.strip() for s in eligible) or
            not isinstance(restricted, list) or
            not all(isinstance(s, str) for s in restricted)):
        raise SafetyError('SCHEMA_VALIDATION_FAILED: instrument count/eligibility')
    allowed = {normalize_symbol(s) for s in eligible}
    blocked = {normalize_symbol(s) for s in restricted + list(config.EXCLUSION_LIST)}
    stocks = None if equity_symbols is None else {normalize_symbol(s) for s in equity_symbols}
    rejected = []
    parsed = []
    raw_tokens = defaultdict(set)
    raw_symbols = defaultdict(set)
    for row in records:
        if not isinstance(row, dict) or str(row.get('exch_seg', '')).strip().upper() != 'NSE':
            continue
        trading = str(row.get('symbol', '')).strip().upper()
        token = str(row.get('token') or '').strip()
        if trading.endswith('-EQ') and token.isdigit() and int(token) > 0:
            symbol = normalize_symbol(trading)
            raw_tokens[token].add(symbol)
            raw_symbols[symbol].add(token)

    def reject(index, symbol, reason):
        rejected.append(UniverseRejection(index, symbol, reason))
        logger.debug('[UNIVERSE REJECT] %s | %s | record=%s', symbol, reason, index)

    for index, row in enumerate(records):
        symbol = normalize_symbol(row.get('symbol')) if isinstance(row, dict) else ''
        try:
            if not isinstance(row, dict):
                raise SafetyError('SCHEMA_VALIDATION_FAILED')
            exchange = str(row.get('exch_seg', '')).strip().upper()
            trading = str(row.get('symbol', '')).strip().upper()
            kind = str(row.get('instrumenttype') or 'CASH').strip().upper()
            if exchange != 'NSE':
                raise SafetyError('NOT_NSE')
            if not trading.endswith('-EQ'):
                raise SafetyError('INVALID_SERIES')
            trading = symbol + '-EQ'
            if kind != 'CASH' or (stocks is not None and symbol not in stocks):
                raise SafetyError('NOT_EQUITY')
            if symbol not in allowed:
                raise SafetyError('NOT_INTRADAY_ELIGIBLE')
            if symbol in blocked:
                raise SafetyError('EXCLUDED_SYMBOL')
            token_value = row.get('token')
            token = str(token_value or '').strip()
            if isinstance(token_value, bool) or not token.isdigit() or int(token) <= 0:
                raise SafetyError('INSTRUMENT_IDENTITY_UNRESOLVED')
            if len(raw_tokens[token]) != 1 or len(raw_symbols[symbol]) != 1:
                raise SafetyError('AMBIGUOUS_INSTRUMENT_MASTER')
            lot_value = row.get('lotsize')
            if isinstance(lot_value, bool) or str(lot_value).strip() != str(int(lot_value)):
                raise SafetyError('INSTRUMENT_IDENTITY_UNRESOLVED')
            if isinstance(row.get('tick_size'), bool):
                raise SafetyError('INSTRUMENT_IDENTITY_UNRESOLVED')
            identity = InstrumentIdentity(symbol, exchange, token, trading, 'EQ',
                float(row['tick_size']) / 100., int(lot_value), kind, stamp, True)
            identity.validate(symbol, now=now)
            parsed.append((index, identity))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            reason = str(exc) if isinstance(exc, SafetyError) else 'INSTRUMENT_IDENTITY_UNRESOLVED'
            reject(index, symbol, reason)

    by_symbol = defaultdict(list)
    by_token = defaultdict(list)
    for index, identity in parsed:
        by_symbol[identity.symbol].append((index, identity))
        by_token[identity.token].append((index, identity))
    accepted = []
    seen = set()
    for index, identity in parsed:
        conflicts = ({i for _, i in by_symbol[identity.symbol]} != {identity} or
                     {i for _, i in by_token[identity.token]} != {identity})
        if conflicts:
            reject(index, identity.symbol, 'AMBIGUOUS_INSTRUMENT_MASTER')
        elif identity in seen:
            reject(index, identity.symbol, 'DUPLICATE_INSTRUMENT')
        else:
            seen.add(identity)
            accepted.append({'exch_seg': identity.exchange, 'symbol': identity.trading_symbol,
                'token': identity.token, 'tick_size': identity.tick_size * 100,
                'lotsize': identity.lot_size, 'instrumenttype': identity.instrument_type})
    registry = InstrumentRegistry(accepted, stamp, sorted(allowed))
    result = MarketUniverse(len(records), registry, rejected, stamp, list(envelope.get('sources', [])),
                            equity_symbols is not None)
    logger.info('[UNIVERSE] raw=%s eligible=%s rejected=%s', len(records),
                result.eligible_equity_count, len(rejected))
    return result


def configured_fallback(registry, now):
    """Configured tokens must match fresh authoritative identities; never guessed."""
    candidates = []
    rejected = []
    seen = set()
    excluded = {normalize_symbol(s) for s in config.EXCLUSION_LIST}
    for index, row in enumerate(config.CANDIDATE_UNIVERSE):
        symbol = normalize_symbol(row.get('symbol'))
        try:
            identity = registry.resolve(symbol, row.get('token'), now)
            identity.validate(symbol, row.get('token'), str(row.get('exchange', '')).strip().upper(), now)
            if str(row.get('trading_symbol', '')).strip().upper() != identity.trading_symbol:
                raise SafetyError('INSTRUMENT_IDENTITY_UNRESOLVED')
            if symbol in excluded:
                raise SafetyError('EXCLUDED_SYMBOL')
            if symbol in seen:
                raise SafetyError('DUPLICATE_INSTRUMENT')
            seen.add(symbol)
            candidates.append({'symbol': symbol, 'trading_symbol': identity.trading_symbol,
                'token': identity.token, 'exchange': identity.exchange, 'instrument': identity})
        except SafetyError as exc:
            rejected.append(UniverseRejection(index, symbol, str(exc)))
            logger.warning('[FALLBACK REJECT] %s | %s', symbol, exc)
    return candidates[:config.MAX_DISCOVERY_CANDIDATES], rejected
