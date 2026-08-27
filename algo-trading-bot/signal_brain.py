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

from typing import Any, Optional, Union

import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Rolling 14-period Average True Range (ATR-14) across completed bars:
        TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
        ATR_{14, t} = 1/14 * sum_{i=0}^{13} TR_{t-i}

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

    atr = true_range.rolling(period, min_periods=1).mean()
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

    Strategy Logic (VWAP_PULLBACK_BUY)
    ──────────────────────────────────
    1. Prior Displacement: Close_{t-1} > VWAP_{t-1} (firmly above on previous bar).
    2. Dynamic Volatility Touch: Low_t <= VWAP_t + (0.20 * ATR_{14, t}).
    3. Bullish Rejection Close: Close_t > VWAP_t (closes back above VWAP).

    Anti-Spam State Lock
    ────────────────────
    After a signal fires at Candle T, state transitions to LOCKED.
    To unlock, price must displace away from VWAP such that:
        Low_k > VWAP_k + (0.20 * ATR_{14, k})
    for at least 2 consecutive candles (k = T+1, T+2) before another touch can register.

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
        • ATR_14     (float) — Rolling 14-period ATR.
        • Buy_Signal (bool)  — True only if all conditions converge and unlocked.
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

    # ── 2. Rolling 14-period ATR (volatility proxy) ────────────────────
    out["ATR_14"] = compute_atr(out, period=14)

    # ── 3. Trend Displacement Check (Candle t-1 firmly above VWAP) ────
    close_above_vwap_tm1 = (out["Close"].astype(float) > out["VWAP"]).shift(1)

    # ── 4. Dynamic ATR Penetration / Touch ────────────────────────────
    # Low_t <= VWAP_t + (0.20 * ATR_14_t)
    dynamic_band = out["VWAP"] + 0.20 * out["ATR_14"]
    low_tests_vwap = out["Low"].astype(float) <= dynamic_band

    # ── 5. Rebound & Close back above VWAP ────────────────────────────
    close_bounces = out["Close"].astype(float) > out["VWAP"]

    # Raw signal (ignores anti-spam lock)
    raw_signal = (
        close_above_vwap_tm1.fillna(False).astype(bool)
        & low_tests_vwap.fillna(False).astype(bool)
        & close_bounces.fillna(False).astype(bool)
    )

    # ── 6. Anti-Spam State Lock ───────────────────────────────────────
    # After a signal fires at Candle T, state transitions to LOCKED.
    # To unlock, price must displace away from VWAP such that:
    #     Low_k > VWAP_k + (0.20 * ATR_{14, k})
    # for at least 2 consecutive candles (k = T+1, T+2).
    buy_signal_vals: list[bool] = [False] * len(raw_signal)
    locked = False
    consecutive_displaced = 0

    raw_arr = raw_signal.to_numpy()
    low_arr = out["Low"].astype(float).to_numpy()
    dynamic_band_arr = dynamic_band.to_numpy()

    for i in range(len(raw_arr)):
        is_raw_true = bool(raw_arr[i])
        # Check if candle low displaced away above the dynamic tolerance band
        is_displaced_away = bool(low_arr[i] > dynamic_band_arr[i])

        if locked:
            if is_displaced_away:
                consecutive_displaced += 1
                if consecutive_displaced >= 2:
                    locked = False
            else:
                consecutive_displaced = 0

            buy_signal_vals[i] = False
            continue

        if is_raw_true:
            buy_signal_vals[i] = True
            locked = True
            consecutive_displaced = 0
        else:
            buy_signal_vals[i] = False

    out["Buy_Signal"] = buy_signal_vals

    return out


def update_cpp_tick(
    cpp_engine: Any,
    price: float,
    volume: float,
    current_atr: Optional[float] = None,
) -> dict:
    """
    Feed live price, volume, and dynamic ATR into the native C++ VwapEngine / PyQuantEngine.
    If current_atr is not yet calculated (e.g. initial bars), safely passes 0.0 fallback.
    """
    atr_val = (
        float(current_atr)
        if (current_atr is not None and not np.isnan(current_atr) and current_atr > 0.0)
        else 0.0
    )
    if hasattr(cpp_engine, "update_tick"):
        cpp_engine.update_tick(price, volume, atr_val)
    elif hasattr(cpp_engine, "push_tick"):
        cpp_engine.push_tick({
            "price": price,
            "volume": volume,
            "current_atr": atr_val,
        })
    return cpp_engine.snapshot() if hasattr(cpp_engine, "snapshot") else {}
