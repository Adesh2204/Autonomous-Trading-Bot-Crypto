"""
candle_builder.py — Candle Aggregation Layer
=============================================
Real-time tick-to-candle buffer that sits between the Data Ingestion
Layer (live_stream.py) and the Signal Generation Layer (signal_brain.py).

Architecture
────────────
  WebSocket tick → CandleBuilder.on_tick(price, volume, timestamp)
                       │
                       ├─ Accumulates ticks into the current 1-min bucket
                       │
                       └─ When the minute rolls over:
                            1. Finalizes the previous candle (OHLCV)
                            2. Appends it to the master DataFrame
                            3. Resets the buffer for the new minute
                            4. Fires an optional callback for downstream
                               consumers (e.g. signal_brain)

Design Principles
─────────────────
• Zero DataFrames are touched during tick ingestion — only plain Python
  scalars are updated, keeping the hot-path allocation-free.
• The master DataFrame is grown via pd.concat (one call per closed candle).
• Thread-safe: all mutations happen on the WebSocket thread itself,
  so no locks are needed.
"""

import math

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Callable, Optional


class CandleBuilder:
    """
    Lightweight real-time buffer that aggregates raw tick data into
    fixed-interval OHLCV candles.

    Parameters
    ----------
    interval_seconds : int
        Candle duration in seconds.  Default is 60 (1-minute candles).
    on_candle_close : callable, optional
        Callback fired every time a candle closes.  Receives the full
        master DataFrame as its sole argument.  Use this to plug in
        signal_brain.generate_vwap_signal(df) without blocking the
        WebSocket loop (the computation is vectorized and fast).

    Usage
    -----
    >>> from candle_builder import CandleBuilder
    >>> from signal_brain   import generate_vwap_signal
    >>>
    >>> builder = CandleBuilder(
    ...     interval_seconds=60,
    ...     on_candle_close=lambda df: print(generate_vwap_signal(df).tail(1)),
    ... )
    >>>
    >>> # Inside your WebSocket on_message callback:
    >>> builder.on_tick(price=1425.30, volume=120, timestamp=datetime.now())
    """

    def __init__(
        self,
        interval_seconds: int = 60,
        on_candle_close: Optional[Callable[[pd.DataFrame], None]] = None,
    ):
        self.interval_seconds = interval_seconds
        self.on_candle_close = on_candle_close

        # ── Master DataFrame — stores all finalized candles ─────────
        self._columns = ["Timestamp", "Open", "High", "Low", "Close", "Volume", "VWAP", "ATR_14"]
        self.df = self._empty_dataframe()

        # ── Current (in-progress) candle buffer ─────────────────────
        self._reset_buffer()

    # ────────────────────────────────────────────────────────────────
    #  PUBLIC API
    # ────────────────────────────────────────────────────────────────

    def on_tick(
        self,
        price: float,
        volume: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Ingest a single tick.  Called from the WebSocket on_message
        callback on every incoming price update.

        Parameters
        ----------
        price     : float    — Last Traded Price (LTP) from the tick.
        volume    : float    — Trade volume associated with this tick.
        timestamp : datetime — Tick timestamp.  Falls back to
                               datetime.now() if the broker doesn't
                               provide one in the payload.
        """
        if timestamp is None:
            timestamp = datetime.now()

        price, volume = self._validate_tick(price, volume)

        # Reset the in-memory session buffer when a new calendar date arrives.
        # This prevents yesterday's candle history from leaking into today's
        # VWAP and keeps memory bounded to the active trading session.
        if self._bucket_start is not None and timestamp.date() != self._bucket_start.date():
            self.df = self._empty_dataframe()
            self._reset_buffer()

        # ── Determine which 1-minute bucket this tick belongs to ────
        bucket_start = self._floor_timestamp(timestamp)

        # ── First tick ever — initialize the bucket ─────────────────
        if self._bucket_start is None:
            self._bucket_start = bucket_start
            self._init_candle(price, volume)
            return

        # ── Same bucket — update the running candle in O(1) ────────
        if bucket_start == self._bucket_start:
            self._update_candle(price, volume)
            return

        # ── New bucket — the previous candle just closed ────────────
        #    1. Finalize and persist the old candle.
        #    2. Reset the buffer and start tracking the new one.
        self._finalize_candle()
        self._bucket_start = bucket_start
        self._init_candle(price, volume)

    @property
    def candle_count(self) -> int:
        """Number of fully closed candles in the master DataFrame."""
        return len(self.df)

    @property
    def current_candle(self) -> Optional[dict]:
        """Snapshot of the in-progress (not yet closed) candle, or None."""
        if self._bucket_start is None:
            return None
        return {
            "Timestamp": self._bucket_start,
            "Open":   self._open,
            "High":   self._high,
            "Low":    self._low,
            "Close":  self._close,
            "Volume": self._volume,
        }

    @property
    def atr_14(self) -> Optional[float]:
        """Current rolling 14-period ATR from the most recent completed candle."""
        if self.df.empty or "ATR_14" not in self.df.columns:
            return None
        val = self.df["ATR_14"].iloc[-1]
        return float(val) if pd.notna(val) else None

    @property
    def vwap(self) -> Optional[float]:
        """Current cumulative session VWAP from the most recent completed candle."""
        if self.df.empty or "VWAP" not in self.df.columns:
            return None
        val = self.df["VWAP"].iloc[-1]
        return float(val) if pd.notna(val) else None

    @property
    def latest_completed_candle(self) -> Optional[dict]:
        """Snapshot summary of the most recently completed candle with VWAP and ATR_14."""
        if self.df.empty:
            return None
        last_row = self.df.iloc[-1]
        vwap_val = last_row.get("VWAP")
        atr_val = last_row.get("ATR_14")
        return {
            "Timestamp": last_row["Timestamp"],
            "Open": float(last_row["Open"]),
            "High": float(last_row["High"]),
            "Low": float(last_row["Low"]),
            "Close": float(last_row["Close"]),
            "Volume": float(last_row["Volume"]),
            "VWAP": float(vwap_val) if pd.notna(vwap_val) else None,
            "vwap": float(vwap_val) if pd.notna(vwap_val) else None,
            "ATR_14": float(atr_val) if pd.notna(atr_val) else None,
            "atr_14": float(atr_val) if pd.notna(atr_val) else None,
        }

    @property
    def last_candle_summary(self) -> Optional[dict]:
        """Alias for latest_completed_candle."""
        return self.latest_completed_candle

    # ────────────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ────────────────────────────────────────────────────────────────

    def _floor_timestamp(self, ts: datetime) -> datetime:
        """
        Floor a timestamp to the start of its interval bucket.

        Example (60-second interval):
            18:04:37 → 18:04:00
            18:05:00 → 18:05:00
        """
        seconds_since_midnight = (
            ts.hour * 3600 + ts.minute * 60 + ts.second
        )
        floored_seconds = (
            (seconds_since_midnight // self.interval_seconds)
            * self.interval_seconds
        )
        return ts.replace(
            hour=floored_seconds // 3600,
            minute=(floored_seconds % 3600) // 60,
            second=floored_seconds % 60,
            microsecond=0,
        )

    def _reset_buffer(self) -> None:
        """Clear the in-progress candle buffer to a clean state."""
        self._bucket_start: Optional[datetime] = None
        self._open:   float = 0.0
        self._high:   float = -np.inf
        self._low:    float = np.inf
        self._close:  float = 0.0
        self._volume: float = 0.0

    def _empty_dataframe(self) -> pd.DataFrame:
        """Create a typed empty DataFrame for finalized candle history."""
        return pd.DataFrame(
            {
                "Timestamp": pd.Series(dtype="datetime64[ns]"),
                "Open": pd.Series(dtype="float64"),
                "High": pd.Series(dtype="float64"),
                "Low": pd.Series(dtype="float64"),
                "Close": pd.Series(dtype="float64"),
                "Volume": pd.Series(dtype="float64"),
                "VWAP": pd.Series(dtype="float64"),
                "ATR_14": pd.Series(dtype="float64"),
            },
            columns=self._columns,
        )

    def _validate_tick(self, price: float, volume: float) -> tuple[float, float]:
        """Reject malformed ticks before they can poison OHLCV state."""
        try:
            price = float(price)
            volume = float(volume)
        except (TypeError, ValueError) as exc:
            raise ValueError("Tick price and volume must be numeric") from exc

        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"Tick price must be finite and positive, got {price!r}")
        if not math.isfinite(volume) or volume < 0:
            raise ValueError(f"Tick volume must be finite and non-negative, got {volume!r}")

        return price, volume

    def _init_candle(self, price: float, volume: float) -> None:
        """Start tracking a brand-new candle from the first tick."""
        self._open   = price
        self._high   = price
        self._low    = price
        self._close  = price
        self._volume = volume

    def _update_candle(self, price: float, volume: float) -> None:
        """
        Update the running candle with an incoming tick.
        Only plain scalar comparisons — no allocations, no DataFrame
        operations. This is the hot path; it must be allocation-free.
        """
        if price > self._high:
            self._high = price
        if price < self._low:
            self._low = price
        self._close   = price           # last tick = Close
        self._volume += volume          # accumulate volume

    def _compute_indicators(self) -> None:
        """Compute cumulative session VWAP and rolling 14-period Wilder ATR."""
        if self.df.empty:
            return

        high = self.df["High"].astype(float)
        low = self.df["Low"].astype(float)
        close = self.df["Close"].astype(float)
        volume = self.df["Volume"].astype(float)
        typical_price = (high + low + close) / 3.0

        if "Timestamp" in self.df.columns and not self.df["Timestamp"].empty:
            ts = pd.to_datetime(self.df["Timestamp"])
            session_key = pd.Index(ts.dt.date.to_list(), name="session_key")
        elif isinstance(self.df.index, pd.DatetimeIndex):
            session_key = pd.Index(self.df.index.date, name="session_key")
        else:
            session_key = pd.Index(np.zeros(len(self.df)), name="session_key")

        cumulative_tp_vol = (typical_price * volume).groupby(session_key).cumsum()
        cumulative_vol = volume.groupby(session_key).cumsum()

        self.df["VWAP"] = np.where(
            cumulative_vol == 0,
            np.nan,
            cumulative_tp_vol / cumulative_vol,
        )

        prev_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        self.df["ATR_14"] = true_range.ewm(
            alpha=1.0 / 14,
            adjust=False,
            min_periods=1,
        ).mean()

    def _finalize_candle(self) -> None:
        """
        Freeze the current buffer into a finalized candle row,
        append it to the master DataFrame, compute VWAP and rolling ATR-14,
        then fire the downstream callback (if registered).
        """
        new_candle = pd.DataFrame(
            [{
                "Timestamp": self._bucket_start,
                "Open":      self._open,
                "High":      self._high,
                "Low":       self._low,
                "Close":     self._close,
                "Volume":    self._volume,
                "VWAP":      np.nan,
                "ATR_14":    np.nan,
            }],
            columns=self._columns,
        )

        # Grow the master DataFrame by one row and calculate indicators
        self.df = pd.concat([self.df, new_candle], ignore_index=True)
        self._compute_indicators()

        # ── Fire callback so signal_brain can react immediately ─────
        if self.on_candle_close is not None:
            self.on_candle_close(self.df)

        # ── Reset for the next candle ───────────────────────────────
        self._reset_buffer()
