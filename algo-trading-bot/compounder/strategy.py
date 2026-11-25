"""Close-confirmed Donchian trend breakout with a fixed ATR hard stop.

Rules (evaluated once per completed bar, identical in backtest, paper and live):
  * Long entry  when close > highest high of the previous ``entry_n`` bars.
  * Short entry when close < lowest low of the previous ``entry_n`` bars (if ``allow_short``).
  * Long exit   when close < lowest low of the previous ``exit_n`` bars (trailing channel).
  * Short exit  when close > highest high of the previous ``exit_n`` bars.
  * Hard stop   ``stop_atr`` x ATR(``atr_n``) from the entry fill, resting on the exchange as a
                reduce-only stop-market order so it works between bar closes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .indicators import prior_max, prior_min, wilder_atr


@dataclass(frozen=True)
class TrendParams:
    name: str
    timeframe: str = "1d"
    entry_n: int = 20
    exit_n: int = 10
    atr_n: int = 20
    stop_atr: float = 2.0
    allow_short: bool = True
    # Optional add-ons (0 = off; every existing mandate leaves them off):
    trail_atr: float = 0.0        # chandelier trailing stop: best price since entry -/+ trail_atr x ATR
    rotation_top: int = 0         # longs only in the N strongest coins, shorts only in the N weakest
    rotation_lookback: int = 90   # momentum window (days) for the ranking
    universe_size: int = 0        # each month keep only the N most-traded coins (0 = all)

    @property
    def warmup(self) -> int:
        return max(self.entry_n, self.exit_n, self.atr_n, self.rotation_lookback if self.rotation_top else 0) + 1


@dataclass(frozen=True)
class Signals:
    upper: np.ndarray
    lower: np.ndarray
    exit_hi: np.ndarray
    exit_lo: np.ndarray
    atr: np.ndarray


def compute_signals(high, low, close, p: TrendParams) -> Signals:
    return Signals(
        upper=prior_max(high, p.entry_n),
        lower=prior_min(low, p.entry_n),
        exit_hi=prior_max(high, p.exit_n),
        exit_lo=prior_min(low, p.exit_n),
        atr=wilder_atr(high, low, close, p.atr_n),
    )


def entry_side(sig: Signals, i: int, close_i: float, p: TrendParams) -> int:
    """+1 long, -1 short, 0 none for completed bar ``i``."""
    up, lo, atr = sig.upper[i], sig.lower[i], sig.atr[i]
    if not (np.isfinite(up) and np.isfinite(lo) and np.isfinite(atr)) or atr <= 0:
        return 0
    if close_i > up:
        return 1
    if p.allow_short and close_i < lo:
        return -1
    return 0


def channel_exit(side: int, sig: Signals, i: int, close_i: float) -> bool:
    if side > 0:
        level = sig.exit_lo[i]
        return bool(np.isfinite(level) and close_i < level)
    level = sig.exit_hi[i]
    return bool(np.isfinite(level) and close_i > level)


def initial_stop(side: int, fill_price: float, atr_i: float, p: TrendParams) -> float:
    return fill_price - side * p.stop_atr * atr_i


def trail_stop(side: int, stop: float, best: float, atr: float, k: float) -> float:
    """Chandelier trailing stop: never loosens; follows the best price since entry."""
    if k <= 0 or not np.isfinite(atr) or atr <= 0:
        return stop
    cand = best - side * k * atr
    return max(stop, cand) if side > 0 else min(stop, cand)


def momentum_score(c, i: int, lookback: int) -> float:
    """Risk-adjusted momentum at completed bar i: lookback return / (daily vol x sqrt(lookback))."""
    c = np.asarray(c, dtype=float)
    if i < lookback or c[i - lookback] <= 0:
        return float("nan")
    window = c[i - lookback:i + 1]
    rets = np.diff(np.log(window))
    vol = rets.std() * np.sqrt(lookback)
    if not np.isfinite(vol) or vol <= 0:
        return float("nan")
    return float((c[i] / c[i - lookback] - 1.0) / vol)


def rotation_sides(scores: dict, top: int) -> dict:
    """{coin: allowed sides}: +1 for the ``top`` strongest positive scores, -1 for the ``top`` weakest
    negative scores. Coins without a valid score get nothing."""
    valid = {k: v for k, v in scores.items() if np.isfinite(v)}
    ranked = sorted(valid, key=lambda k: valid[k], reverse=True)
    out = {k: set() for k in scores}
    for k in ranked[:top]:
        if valid[k] > 0:
            out[k].add(1)
    for k in ranked[::-1][:top]:
        if valid[k] < 0:
            out[k].add(-1)
    return out


def top_by_volume(dollar_volume: dict, size: int) -> set:
    """The ``size`` coins with the largest trailing dollar volume (all coins if size == 0)."""
    valid = {k: v for k, v in dollar_volume.items() if np.isfinite(v) and v > 0}
    if size <= 0:
        return set(valid)
    return set(sorted(valid, key=lambda k: valid[k], reverse=True)[:size])


# Pre-registered candidates (25 Nov 2026), fixed from the classic Turtle rules; nothing tuned.
CANDIDATES = (
    TrendParams("D20_10_LS", "1d", 20, 10, 20, 2.0, True),
    TrendParams("D20_10_L", "1d", 20, 10, 20, 2.0, False),
    TrendParams("D55_20_LS", "1d", 55, 20, 20, 2.0, True),
    TrendParams("D55_20_L", "1d", 55, 20, 20, 2.0, False),
    TrendParams("H4_20_10_LS", "4h", 20, 10, 20, 2.0, True),
    TrendParams("H4_20_10_L", "4h", 20, 10, 20, 2.0, False),
)
