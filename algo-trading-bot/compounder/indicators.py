"""Indicators on completed bars. Identical code feeds the backtest and the live/paper runner."""
from __future__ import annotations

import numpy as np


def wilder_atr(high, low, close, n: int) -> np.ndarray:
    """Wilder ATR. ``atr[i]`` uses bars 0..i (bar i completed). NaN until ``n`` bars exist."""
    h = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    size = len(c)
    atr = np.full(size, np.nan)
    if size < n or n <= 0:
        return atr
    tr = np.empty(size)
    tr[0] = h[0] - lo[0]
    prev = c[:-1]
    tr[1:] = np.maximum(h[1:] - lo[1:], np.maximum(np.abs(h[1:] - prev), np.abs(lo[1:] - prev)))
    atr[n - 1] = tr[:n].mean()
    for i in range(n, size):
        atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / n
    return atr


def prior_max(x, n: int) -> np.ndarray:
    """``out[i] = max(x[i-n .. i-1])`` (the n bars before bar i). NaN until n prior bars exist."""
    a = np.asarray(x, dtype=float)
    out = np.full(len(a), np.nan)
    if n <= 0 or len(a) <= n:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(a, n)  # windows[j] = a[j .. j+n-1]
    out[n:] = windows[:-1].max(axis=1)
    return out


def prior_min(x, n: int) -> np.ndarray:
    """``out[i] = min(x[i-n .. i-1])``. NaN until n prior bars exist."""
    a = np.asarray(x, dtype=float)
    out = np.full(len(a), np.nan)
    if n <= 0 or len(a) <= n:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(a, n)
    out[n:] = windows[:-1].min(axis=1)
    return out
