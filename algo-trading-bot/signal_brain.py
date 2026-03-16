"""
signal_brain.py — Signal Generation Layer (The Brain)
=====================================================
Contains vectorized indicator calculations and high-probability
signal detection logic. Designed for sub-millisecond execution
on DataFrames populated by the Data Ingestion Layer.
"""

import pandas as pd
import numpy as np


def generate_vwap_signal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Intraday VWAP and detect a high-probability
    "VWAP Pullback Buy Signal" using purely vectorized Pandas logic.

    Strategy Logic
    ──────────────
    1. VWAP Calculation  — Cumulative (TP × Volume) / Cumulative Volume
    2. Trend Confirmation — Previous 3 candles all closed ABOVE the VWAP,
       confirming intraday bullishness.
    3. Pullback Trigger   — Current candle's Low touches or dips slightly
       BELOW the VWAP (testing support), but Close bounces back ABOVE it,
       indicating institutional buyers are defending the VWAP line.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: Open, High, Low, Close, Volume.
        Rows should represent intraday candles (1-min / 5-min) for a
        SINGLE trading session. VWAP resets each session.

    Returns
    -------
    pd.DataFrame
        Original DataFrame enriched with two new columns:
        • VWAP       (float)  — The running intraday VWAP value.
        • Buy_Signal (bool)   — True ONLY on candles where all three
                                conditions converge.
    """

    # ── 0. Input Validation ─────────────────────────────────────────────
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    if df.empty:
        df["VWAP"] = np.nan
        df["Buy_Signal"] = False
        return df

    # ── 1. VWAP Calculation (Vectorized) ────────────────────────────────
    # Typical Price is the market's consensus "fair value" for each candle.
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3

    # Cumulative (TP × Volume) / Cumulative Volume
    # This gives us a running, volume-anchored average price for the day.
    cumulative_tp_vol = (typical_price * df["Volume"]).cumsum()
    cumulative_vol = df["Volume"].cumsum()

    # Guard against division-by-zero when cumulative volume is 0
    # (e.g., pre-market candles with no volume).
    df["VWAP"] = np.where(
        cumulative_vol == 0,
        np.nan,
        cumulative_tp_vol / cumulative_vol,
    )

    # ── 2. Trend Confirmation ───────────────────────────────────────────
    # All 3 previous candles must have closed ABOVE their respective VWAP
    # value. This filters out choppy / bearish sessions where a pullback
    # to VWAP is more likely a breakdown than a bounce.
    close_above_vwap = df["Close"] > df["VWAP"]

    trend_confirmed = (
        close_above_vwap.shift(1)    # candle at t-1 closed above VWAP
        & close_above_vwap.shift(2)  # candle at t-2 closed above VWAP
        & close_above_vwap.shift(3)  # candle at t-3 closed above VWAP
    )

    # ── 3. Pullback Entry Trigger ───────────────────────────────────────
    # The current candle must:
    #   a) Have its Low touch or slightly pierce BELOW the VWAP
    #      (price is "testing" VWAP as dynamic support).
    #   b) Close ABOVE the VWAP (buyers absorbed selling pressure and
    #      pushed price back up — a classic institutional defense).
    #
    # A small tolerance (0.1 % above VWAP) is added to the Low condition
    # so we don't miss candles that got extremely close to VWAP without
    # technically touching it — a common occurrence on liquid instruments.
    tolerance = df["VWAP"] * 0.001  # 0.1 % cushion

    low_tests_vwap = df["Low"] <= (df["VWAP"] + tolerance)
    close_bounces  = df["Close"] > df["VWAP"]

    # ── 4. Combine All Conditions into Final Signal ─────────────────────
    df["Buy_Signal"] = (
        trend_confirmed
        & low_tests_vwap
        & close_bounces
    ).fillna(False).astype(bool)

    return df
