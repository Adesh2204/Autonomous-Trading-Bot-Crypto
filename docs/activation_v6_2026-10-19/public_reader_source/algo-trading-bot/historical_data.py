"""Strict NSE completed-bar contract shared by screening, cache and session repair.

Provider timestamps are minute STARTS in Asia/Kolkata. Missing minutes are reported,
never fabricated. A caller restoring session VWAP must require complete coverage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

SCHEMA_VERSION = 1
OHLCV = ["Timestamp", "Open", "High", "Low", "Close", "Volume"]


def ist_timestamp(value=None):
    ts = pd.Timestamp(value if value is not None else datetime.now().astimezone())
    return ts.tz_localize("Asia/Kolkata") if ts.tzinfo is None else ts.tz_convert("Asia/Kolkata")


@dataclass(frozen=True)
class HistoryContext:
    exchange: str
    token: str
    session_date: date
    symbol: str = ""
    timeframe: str = "ONE_MINUTE"
    start: datetime | None = None
    end: datetime | None = None  # inclusive minute-start, never the forming bar
    now: datetime | None = None
    require_complete: bool = False


@dataclass
class HistoryValidation:
    valid: bool
    reason: str | None
    expected_count: int
    received_count: int
    valid_count: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    completeness_ratio: float = 0.
    missing_timestamps: list[str] | None = None
    validation_version: int = SCHEMA_VERSION

    def report(self):
        return asdict(self)


def bounds(context):
    opening = ist_timestamp(datetime.combine(context.session_date, time(9, 15)))
    last = opening.replace(hour=15, minute=29)
    start = ist_timestamp(context.start) if context.start is not None else opening
    end = ist_timestamp(context.end) if context.end is not None else last
    return start, end


def validate_history(frame, context: HistoryContext, min_candles=1):
    start, end = bounds(context)
    expected = pd.date_range(start, end, freq="min") if end >= start else pd.DatetimeIndex([])
    result = HistoryValidation(False, None, len(expected), len(frame) if frame is not None else 0)

    def fail(reason):
        result.reason = reason
        return result

    if context.exchange != "NSE" or context.timeframe != "ONE_MINUTE":
        return fail("UNSUPPORTED_HISTORY_CONTEXT")
    if not str(context.token).strip():
        return fail("MISSING_INSTRUMENT_IDENTITY")
    if frame is None or frame.empty or not set(OHLCV).issubset(frame.columns):
        return fail("INSUFFICIENT_DATA")
    if len(frame) < min_candles:
        return fail("INSUFFICIENT_DATA")
    try:
        timestamps = pd.DatetimeIndex([ist_timestamp(t) for t in frame.Timestamp])
    except (ValueError, TypeError, OverflowError):
        return fail("INVALID_TIMESTAMP")
    if timestamps.isna().any():
        return fail("INVALID_TIMESTAMP")
    if not timestamps.is_monotonic_increasing:
        return fail("STALE_DATA")
    if timestamps.has_duplicates:
        return fail("DUPLICATE_TIMESTAMP")
    if any(t.date() != context.session_date for t in timestamps):
        return fail("WRONG_SESSION_DATE")
    if not timestamps.equals(timestamps.floor("min")):
        return fail("MISALIGNED_TIMEFRAME")
    if any(t.time() < time(9, 15) or t.time() >= time(15, 30) for t in timestamps):
        return fail("OUTSIDE_SESSION")
    if (timestamps < start).any() or (timestamps > end).any():
        return fail("OUTSIDE_REQUESTED_RANGE")
    now = ist_timestamp(context.now)
    if (timestamps + pd.Timedelta(minutes=1) > now).any():
        return fail("FUTURE_OR_PARTIAL_CANDLE")
    try:
        values = frame[OHLCV[1:]].apply(pd.to_numeric, errors="raise").astype(float)
    except (ValueError, TypeError, OverflowError):
        return fail("INVALID_QUOTE")
    if not np.isfinite(values.to_numpy()).all():
        return fail("NONFINITE_OHLCV")
    o, h, l, c, v = (values[col] for col in OHLCV[1:])
    if ((values[OHLCV[1:5]] <= 0).any().any() or (v < 0).any()
            or (h < l).any() or (h < o).any() or (h < c).any()
            or (l > o).any() or (l > c).any()):
        return fail("INVALID_QUOTE")
    missing = expected.difference(timestamps)
    result.valid_count = len(frame)
    result.first_timestamp, result.last_timestamp = timestamps[0].isoformat(), timestamps[-1].isoformat()
    result.completeness_ratio = len(frame) / len(expected) if len(expected) else 0.
    result.missing_timestamps = [t.isoformat() for t in missing]
    if context.require_complete and len(missing):
        return fail("INCOMPLETE_SESSION_HISTORY")
    result.valid = True
    return result


def normalized_history(frame, source="HISTORICAL"):
    result = frame[OHLCV].copy()
    # Runtime uses timezone-aware IST consistently, avoiding local-machine timezone assumptions.
    result["Timestamp"] = pd.DatetimeIndex([ist_timestamp(t) for t in result.Timestamp])
    result[OHLCV[1:]] = result[OHLCV[1:]].astype(float)
    result["candle_source"] = source
    result["is_complete"] = True
    result["is_session_valid"] = True
    return result
