"""Recover only missing completed minutes. No synthetic candles, no order methods."""
from datetime import datetime, time
import pandas as pd
from historical_data import HistoryContext, ist_timestamp, validate_history


def completed_end(now):
    now = ist_timestamp(now)
    return min(now.floor("min") - pd.Timedelta(minutes=1), now.replace(hour=15, minute=29, second=0, microsecond=0))


def missing_ranges(builder, now):
    now = ist_timestamp(now)
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end = completed_end(now)
    expected = pd.date_range(start, end, freq="min") if end >= start else pd.DatetimeIndex([])
    existing = pd.DatetimeIndex([ist_timestamp(t) for t in builder.df.Timestamp])
    missing = expected.difference(existing)
    ranges = []
    for ts in missing:
        if ranges and ts == ranges[-1][1] + pd.Timedelta(minutes=1):
            ranges[-1] = (ranges[-1][0], ts)
        else:
            ranges.append((ts, ts))
    return ranges


def prepare_session_repair(state, now, fetch):
    """Read without mutating live state. Caller commits under its execution lock."""
    now = ist_timestamp(now)
    repairs = []
    import config
    ranges = missing_ranges(state.builder, now)
    if len(ranges) > config.HISTORY_MAX_REPAIR_RANGES:
        raise ValueError("HISTORY_TOO_FRAGMENTED")
    for start, end in ranges:
        context = HistoryContext(state.exchange, state.token, now.date(), state.symbol,
                                 start=start, end=end, now=now, require_complete=True)
        frame = fetch(context)
        validation = validate_history(frame, context)
        if not validation.valid:
            raise ValueError(validation.reason)
        repairs.append((frame, context))
    return repairs


def commit_session_repair(state, now, repairs):
    now = ist_timestamp(now)
    for frame, context in repairs:
        state.builder.seed_history(frame, context, source="RECONCILED" if not state.builder.df.empty else "HISTORICAL")
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end = completed_end(now)
    if end >= start:
        context = HistoryContext(state.exchange, state.token, now.date(), state.symbol,
                                 start=start, end=end, now=now, require_complete=True)
        # Newly closed live bars may extend beyond the request's snapshot.
        sample = state.builder.df.loc[state.builder.df.Timestamp <= end]
        result = validate_history(sample, context)
        if not result.valid:
            raise ValueError(result.reason)
        state.history_validation = result.report()
    else:
        state.history_validation = {"valid": True, "expected_count": 0, "valid_count": 0}
    state.builder.recovery_required = False
    state.builder.recovery_reason = None
    state.current_candle_df = state.builder.df.copy()
    state.refresh_maturity()
    if not state.builder.df.empty:
        row = state.builder.df.iloc[-1]
        state.record_periodic_atr(float(row.ATR_14), float(row.Close), row.Timestamp,
                                  completed_count=len(state.builder.df))
    return state.history_validation
