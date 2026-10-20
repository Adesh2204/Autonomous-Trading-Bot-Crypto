"""Causal hourly price features; no simulated trades, outcome labels or fitting."""
from collections import Counter
import math

import pandas as pd

from strategy_freeze import verify_strategy_freeze
from .common import ResearchError
from .organizer_history import HistoricalBar, HOUR_MS, SOURCE_MARKETS


def hourly_features(bars):
    bars = tuple(bars)
    if not bars:
        return []
    if any(type(b) is not HistoricalBar or b.symbol != bars[0].symbol for b in bars):
        raise ResearchError('HOURLY_REFERENCE_BARS_REQUIRED')
    if any(b.timestamp_ms <= a.timestamp_ms for a, b in zip(bars, bars[1:])):
        raise ResearchError('CHRONOLOGICAL_REFERENCE_BARS_REQUIRED')
    verify_strategy_freeze()
    # The unchanged ATR helper consumes the supplied bar frequency. These are
    # 14 HOURLY bars, explicitly different from the production 14 minute bars.
    from signal_brain import compute_atr
    frame = pd.DataFrame(dict(Timestamp=pd.to_datetime([b.timestamp_ms for b in bars], unit='ms', utc=True),
        High=[float(b.high) for b in bars], Low=[float(b.low) for b in bars],
        Close=[float(b.close) for b in bars], Volume=[float(b.volume) for b in bars]))
    if not all(math.isfinite(float(x)) for column in ('High', 'Low', 'Close', 'Volume') for x in frame[column]):
        raise ResearchError('REFERENCE_VALUES_NOT_FLOAT_REPRESENTABLE')
    # Gaps are explicit boundaries; never interpolate or carry a fictitious hour.
    group = frame.Timestamp.diff().ne(pd.Timedelta(hours=1)).cumsum()
    atr = pd.Series(index=frame.index, dtype=float)
    for _, part in frame.groupby(group):
        atr.loc[part.index] = compute_atr(part, period=14)
    returns = frame.Close.groupby(group).pct_change(fill_method=None)
    count = frame.groupby(group).cumcount() + 1
    # UTC daily HLC3 x volume is an hourly-bar proxy, not true traded VWAP.
    day = frame.Timestamp.dt.date
    weighted = ((frame.High + frame.Low + frame.Close) / 3 * frame.Volume).groupby(day).cumsum()
    volume = frame.Volume.groupby(day).cumsum()
    vwap = weighted / volume.where(volume > 0)
    anchor_complete = frame.groupby(day).cumcount() + 1 == frame.Timestamp.dt.hour + 1
    rows = []
    def value(x):
        return float(x) if pd.notna(x) and math.isfinite(float(x)) else None
    for i, bar in enumerate(bars):
        rows.append(dict(symbol=bar.symbol, source_market=SOURCE_MARKETS[bar.symbol],
            interval='1h', candle_open_ms=bar.timestamp_ms, decision_ms=bar.close_timestamp_ms,
            source=bar.source, availability='ASSUMED_COMPLETE_AT_HOUR_CLOSE_NOT_EXCHANGE_RECEIPT',
            hourly_close_to_close_return=value(returns.iloc[i]), hourly_atr14=value(atr.iloc[i]),
            hourly_atr_fraction=value(atr.iloc[i] / frame.Close.iloc[i]),
            hourly_atr_full_window=bool(count.iloc[i] >= 14),
            utc_hourly_bar_vwap_proxy=value(vwap.iloc[i]) if anchor_complete.iloc[i] else None,
            utc_day_hour_coverage_complete=bool(anchor_complete.iloc[i]),
            volume=float(bar.volume), utc_hour=frame.Timestamp.iloc[i].hour,
            weekday=frame.Timestamp.iloc[i].weekday(),
            spread=None, depth=None, slippage=None, fills=None, fee=None, funding=None,
            mark=None, oracle=None, label=None, production_signal=None,
            ml_scoring_ready=False, execution_capability=False, production_timeframe_compatible=False))
    return rows


def chronological_price_analysis(dataset):
    # Shared UTC boundaries prevent one market's future being another's training.
    times = sorted({b.close_timestamp_ms for bars in dataset.bars.values() for b in bars})
    if len(times) < 5:
        raise ResearchError('INSUFFICIENT_HISTORY_FOR_CHRONOLOGICAL_PARTITIONS')
    validation_start = times[int(len(times) * .6)]
    holdout_start = times[int(len(times) * .8)]
    summaries = []
    features = []
    for symbol in sorted(dataset.bars):
        # No holdout prices are evaluated for features, thresholds or fitting.
        visible = dataset.as_of(symbol, holdout_start - 1)
        rows = hourly_features(visible)
        for row in rows:
            row['partition'] = 'TRAIN' if row['decision_ms'] < validation_start else 'VALIDATION'
        training = [r for r in rows if r['partition'] == 'TRAIN' and r['hourly_atr_full_window']]
        values = pd.Series([r['hourly_atr_fraction'] for r in training], dtype=float)
        summaries.append(dict(symbol=symbol, rows=len(dataset.bars[symbol]),
            partitions=dict(Counter(('TRAIN' if b.close_timestamp_ms < validation_start else
                'VALIDATION' if b.close_timestamp_ms < holdout_start else 'HOLDOUT_RESERVED')
                for b in dataset.bars[symbol])), training_full_atr_rows=len(training),
            training_hourly_atr_fraction_quantiles={str(p): float(values.quantile(p)) for p in (.1, .5, .9)} if len(values) else {},
            training_hourly_atr_at_least_existing_004_floor=sum(v >= .004 for v in values) / len(values) if len(values) else None,
            floor_interpretation='Hourly descriptive comparison only; production minute threshold untouched',
            production_signal_frequency=None, baseline_backtest_pnl=None, ml_outcome_labels=0))
        features.extend(rows)
    return dict(source='HOURLY_MAINNET_REFERENCE_DESCRIPTIVE_RESEARCH',
        shared_utc_boundaries=dict(validation_start_ms=validation_start, holdout_start_ms=holdout_start),
        partitions='Chronological 60/20/20 by UTC bar-close times; no fitted transforms or models',
        holdout_prices_evaluated=False, holdout_complete=False, ml_data_ready=False,
        promotion_recommended=False, production_changed=False, execution_capability=False,
        markets=summaries, feature_rows=len(features),
        gaps_policy='ATR and returns reset at a real missing-hour boundary; no filled rows',
        limitations=['Hourly reference is not one-minute par data.', 'No quotes, execution or after-cost labels.',
            'Hourly-bar VWAP is a proxy; intrahour traded VWAP is unavailable.',
            'This is price-feature preparation, not the existing execution-labeled ML dataset.']), features
