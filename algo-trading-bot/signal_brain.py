"""
signal_brain.py — Signal Generation Layer (The Brain)
=====================================================
Contains vectorized indicator calculations (VWAP, ATR-14) and
strict, high-probability VWAP Pullback Buy Signal detection.

Strict 3-Condition Pullback Model (Dynamic ATR Band)
─────────────────────────────────────────────────────
1. Displacement Check : Candle N-1 must close firmly ABOVE VWAP_N-1.
2. Dynamic ATR Touch  : Candle N Low ≤ VWAP_N + (0.2 × ATR_14).
3. Rejection / Rebound: Candle N Close firmly ABOVE VWAP_N.

Anti-Spam State Lock
────────────────────
After a Buy_Signal fires, signal generation is locked until price
displaces above VWAP for at least 2 consecutive candles — preventing
the same pullback zone from firing repeated entries on adjacent
candles without a meaningful price re-acceleration first.

Scale-In (Pyramiding) Support
─────────────────────────────
Once the Anti-Spam lock resets, a new valid signal is emitted and the
Execution Layer treats it as a candidate scale-in (subject to its own
MAX_TRANCHES, Working Capital, and Risk Budget caps).
"""

import pandas as pd
import numpy as np


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's RMA-based Average True Range (ATR-14) across candles.

    ATR is calculated globally over the DataFrame but the Signal Brain
    uses it row-by-row in a rolling fashion. Vectorized implementation
    so the hot path stays sub-millisecond.

    Parameters
    ----------
    df : pd.DataFrame — Must contain columns High/Low/Close.
    period : int      — ATR lookback (default 14 for 1-minute candles).

    Returns
    -------
    pd.Series of ATR values aligned with the input index.
    """
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    prev_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    return atr


def _get_session_key(df: pd.DataFrame) -> pd.Index:
    """Return a date-level session key grouped by trading day."""
    if "Timestamp" in df.columns:
        ts = pd.to_datetime(df["Timestamp"])
        return pd.Index(ts.dt.date.to_list(), name="session_key")
    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Index(df.index.date, name="session_key")
    raise ValueError("DataFrame must contain a 'Timestamp' column or DatetimeIndex.")


def generate_vwap_signal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Intraday VWAP, rolling ATR-14, and detect a strict
    3-condition "VWAP Pullback Buy Signal" with Anti-Spam State Lock.

    Consecutive True signals on subsequent candles are only emitted
    after the 2-candle "displaced above VWAP" Anti-Spam reset has been
    satisfied. This avoids signal spam on adjacent pullback candles in
    the same consolidation zone.

    Strategy Logic
    ──────────────
    1. VWAP Calculation  — Cumulative (TP × Volume) / Cumulative Volume,
                           resetting per trading session (09:15 IST each day).
    2. ATR-14            — Wilder RMA rolling 14-period intraday volatility.
    3. Displacement (t-1)— Candle N-1 Close > VWAP_{N-1} firmly above.
    4. Dynamic ATR Touch — Candle N Low ≤ VWAP_N + (0.2 × ATR_14).
    5. Rebound Close     — Candle N Close > VWAP_N back above line.
    6. Anti-Spam Lock    — After True signal, require ≥ 2 consecutive candles
                           whose CLOSE is ABOVE VWAP before a new True may
                           fire (prevents signal spam).

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: Open, High, Low, Close, Volume.
        May span multiple sessions; VWAP resets at each session boundary.

    Returns
    -------
    pd.DataFrame
        Original DataFrame enriched with:
        • VWAP       (float) — Running session intraday VWAP.
        • ATR_14     (float) — Rolling 14-period Wilder ATR.
        • Buy_Signal (bool)  — True only if all 6 conditions converge.
    """
    # ── 0. Input Validation ─────────────────────────────────────────────
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    if df.empty:
        df = df.copy()
        df["VWAP"] = np.nan
        df["ATR_14"] = np.nan
        df["Buy_Signal"] = False
        return df

    out = df.copy()

    # ── 1. VWAP Calculation (Vectorized, daily-session reset) ──────────
    typical_price = (out["High"].astype(float) + out["Low"].astype(float) + out["Close"].astype(float)) / 3.0
    session_key = _get_session_key(out)

    cumulative_tp_vol = (typical_price * out["Volume"].astype(float)).groupby(session_key).cumsum()
    cumulative_vol = out["Volume"].astype(float).groupby(session_key).cumsum()

    out["VWAP"] = np.where(
        cumulative_vol == 0,
        np.nan,
        cumulative_tp_vol / cumulative_vol,
    )

    # ── 2. Rolling 14-period Wilder ATR (volatility proxy) ─────────────
    out["ATR_14"] = compute_atr(out, period=14)

    # ── 3. Trend Displacement Check (Candle N-1 firmly above VWAP) ─────
    close_above_vwap_tm1 = (out["Close"].astype(float) > out["VWAP"]).shift(1)

    # ── 4. Dynamic ATR Penetration / Touch ─────────────────────────────
    # Low_N <= VWAP_N + (0.2 * ATR_14)
    dynamic_band = out["VWAP"] + 0.2 * out["ATR_14"]
    low_tests_vwap = out["Low"].astype(float) <= dynamic_band

    # ── 5. Rebound & Close back above VWAP ─────────────────────────────
    close_bounces = out["Close"].astype(float) > out["VWAP"]

    # Raw signal (ignores anti-spam lock)
    raw_signal = (
        close_above_vwap_tm1.fillna(False).astype(bool)
        & low_tests_vwap.fillna(False).astype(bool)
        & close_bounces.fillna(False).astype(bool)
    )

    # ── 6. Anti-Spam State Lock ────────────────────────────────────────
    # After a True signal fires, the next True is blocked until at least
    # 2 consecutive candles have closed ABOVE VWAP (displacement reset).
    #
    # We walk the series sequentially because state depends on prior
    # True signals; this is O(n) with pure Python — cheap for ≤ 375
    # daily candles (09:15 → 15:29 IST).
    buy_signal_vals: list[bool] = [False] * len(raw_signal)
    lock_cooldown = 0  # number of additional required "Close > VWAP" candles

    raw_arr = raw_signal.to_numpy()
    close_arr = out["Close"].astype(float).to_numpy()
    vwap_arr = pd.Series(out["VWAP"]).astype(float).to_numpy()

    for i in range(len(raw_arr)):
        cs_raw = bool(raw_arr[i])
        close_above = bool(close_arr[i] > vwap_arr[i])

        if lock_cooldown > 0:
            if close_above:
                lock_cooldown -= 1
            buy_signal_vals[i] = False
            continue

        if cs_raw:
            buy_signal_vals[i] = True
            lock_cooldown = 2  # require ≥ 2 subsequent Close > VWAP before re-fire
        else:
            buy_signal_vals[i] = False

    out["Buy_Signal"] = buy_signal_vals

    return out
