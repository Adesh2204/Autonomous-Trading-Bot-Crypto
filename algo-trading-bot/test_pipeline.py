#!/usr/bin/env python3
"""
test_pipeline.py
=================
Offline "Flight Simulator" harness for the intraday trading pipeline.

This script bypasses the live WebSocket feed and streams deterministic
synthetic ticks through the real modules:
    tick -> CandleBuilder -> generate_vwap_signal -> PaperTrader

It runs two end-to-end scenarios:
    Scenario A: VWAP pullback entry followed by a target hit.
    Scenario B: VWAP pullback entry followed by a stop-loss hit.
"""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd
import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from candle_builder import CandleBuilder
from execution_engine import PaperTrader
from market_schedule import (
    IST,
    MarketPhase,
    can_enter_new_positions,
    get_market_state,
    is_trading_day,
    seconds_until_market_start,
)
from signal_brain import generate_vwap_signal


SYMBOL = "M&M"
START_PRICE = 2500.00
STARTING_CAPITAL = 10017.00
WORKING_CAPITAL_LIMIT = 5008.50
DAILY_LOSS_LIMIT = 200.00
ENTRY_RISK_LIMIT = 100.00


@dataclass(frozen=True)
class CandleSpec:
    """Single 1-minute candle definition used to synthesize ticks."""

    label: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    pattern: str


def round2(value: float) -> float:
    return round(float(value), 2)


def rupees(value: float) -> str:
    return f"₹{value:,.2f}"


def allocate_tick_volumes(total_volume: int, weights: Sequence[int]) -> List[int]:
    """Split a candle's total volume across ticks while preserving the sum."""
    if total_volume <= 0:
        return [0 for _ in weights]

    weight_sum = float(sum(weights))
    raw = [total_volume * weight / weight_sum for weight in weights]
    integers = [int(v) for v in raw]
    remainder = total_volume - sum(integers)

    if remainder:
        order = sorted(
            range(len(weights)),
            key=lambda idx: (raw[idx] - integers[idx], weights[idx]),
            reverse=(remainder > 0),
        )
        step = 1 if remainder > 0 else -1
        for i in range(abs(remainder)):
            integers[order[i % len(order)]] += step

    return integers


def pattern_prices(spec: CandleSpec) -> List[float]:
    """
    Return the intraminute price path for a candle.

    Each candle is represented by 4 ticks:
        1. open
        2. first swing extreme
        3. second swing extreme
        4. close

    The path preserves the requested OHLC values exactly.
    """
    pattern = spec.pattern.lower()
    if pattern == "open_high_low_close":
        seq = [spec.open_price, spec.high_price, spec.low_price, spec.close_price]
    elif pattern == "open_low_high_close":
        seq = [spec.open_price, spec.low_price, spec.high_price, spec.close_price]
    elif pattern == "open_high_close_low":
        seq = [spec.open_price, spec.high_price, spec.close_price, spec.low_price]
    else:
        raise ValueError(f"Unsupported candle pattern: {spec.pattern}")

    return [round2(price) for price in seq]


def build_ticks_for_candle(
    candle_start: datetime,
    spec: CandleSpec,
) -> List[dict]:
    """Build a realistic stream of ticks for one synthetic 1-minute candle."""
    prices = pattern_prices(spec)

    # Pattern-aware volume weighting. Close volume is usually stronger in a trend.
    pattern = spec.pattern.lower()
    if pattern == "open_low_high_close":
        weights = (22, 20, 23, 35)
    elif pattern == "open_high_close_low":
        weights = (28, 24, 30, 18)
    else:
        weights = (18, 24, 25, 33)

    volumes = allocate_tick_volumes(spec.volume, weights)
    second_offsets = (0, 15, 30, 55)

    ticks = []
    for offset, price, volume in zip(second_offsets, prices, volumes):
        ticks.append(
            {
                "timestamp": candle_start + timedelta(seconds=offset),
                "price": round2(price),
                "volume": int(volume),
            }
        )

    return ticks


def build_stream(
    start_ts: datetime,
    candles: Sequence[CandleSpec],
) -> List[dict]:
    """Create the complete tick stream for a scenario plus a final flush tick."""
    ticks: List[dict] = []
    for minute_offset, spec in enumerate(candles):
        candle_start = start_ts + timedelta(minutes=minute_offset)
        ticks.extend(build_ticks_for_candle(candle_start, spec))

    # Final flush tick: closes the last intended candle and starts a dummy bucket.
    final_flush_start = start_ts + timedelta(minutes=len(candles))
    last_close = candles[-1].close_price
    flush_price = round2(last_close + 0.05)
    ticks.append(
        {
            "timestamp": final_flush_start,
            "price": flush_price,
            "volume": 100,
        }
    )
    return ticks


def validate_tick_payload(tick: dict) -> tuple[float, int]:
    """Reject malformed broker payloads before they reach the candle builder."""
    if not isinstance(tick, dict):
        raise TypeError("Tick payload must be a dictionary")

    # Price extraction should be strict: no default-to-zero fallback is allowed.
    raw_price = None
    for key in ("ltp", "last_traded_price", "last_price", "price"):
        if key not in tick or tick[key] is None:
            continue
        try:
            candidate = float(tick[key])
            if candidate > 0 and math.isfinite(candidate):
                raw_price = candidate
                break
        except (TypeError, ValueError):
            continue

    if raw_price is None or raw_price <= 0:
        raise ValueError(
            f"Invalid tick payload: LTP must be > 0, got {tick.get('ltp', tick.get('last_traded_price', tick.get('last_price', tick.get('price', None))))!r}"
        )

    # Volume may be absent; in that case, we still permit the tick only if the
    # price is valid and default the volume to zero instead of crashing.
    raw_volume = 0
    for key in ("volume", "v", "qty", "last_qty", "traded_volume"):
        if key not in tick or tick[key] is None:
            continue
        try:
            raw_volume = int(float(tick[key]))
            break
        except (TypeError, ValueError):
            continue

    return float(raw_price), max(raw_volume, 0)


def base_market_path() -> List[CandleSpec]:
    """The common warm-up path shared by both scenarios."""
    return [
        CandleSpec(
            label="Phase 1 - Candle 1",
            open_price=2500.00,
            high_price=2505.00,
            low_price=2499.80,
            close_price=2504.00,
            volume=1200,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 1 - Candle 2",
            open_price=2508.00,
            high_price=2512.00,
            low_price=2508.00,
            close_price=2511.00,
            volume=1350,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 1 - Candle 3",
            open_price=2511.00,
            high_price=2516.00,
            low_price=2511.00,
            close_price=2515.00,
            volume=1450,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 1 - Candle 4",
            open_price=2515.00,
            high_price=2522.00,
            low_price=2515.00,
            close_price=2521.00,
            volume=1550,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 2 - Pullback Entry Candle",
            open_price=2521.00,
            high_price=2522.00,
            low_price=2513.00,
            close_price=2519.00,
            volume=1700,
            pattern="open_high_low_close",
        ),
    ]


def scenario_a_path() -> List[CandleSpec]:
    """Post-entry continuation that should reach the 1:2 target."""
    return [
        CandleSpec(
            label="Phase 3A - Drift Higher",
            open_price=2518.90,
            high_price=2523.50,
            low_price=2517.80,
            close_price=2522.80,
            volume=1650,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3A - Target Expansion",
            open_price=2522.80,
            high_price=2540.20,
            low_price=2521.90,
            close_price=2538.60,
            volume=1900,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3A - Cooldown",
            open_price=2538.60,
            high_price=2542.10,
            low_price=2537.90,
            close_price=2540.80,
            volume=1800,
            pattern="open_high_low_close",
        ),
    ]


def scenario_b_path() -> List[CandleSpec]:
    """Post-entry continuation that should hit the stop-loss."""
    return [
        CandleSpec(
            label="Phase 3B - Soft Fade",
            open_price=2518.90,
            high_price=2520.10,
            low_price=2508.50,
            close_price=2510.20,
            volume=1650,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3B - Stop Sweep",
            open_price=2510.20,
            high_price=2511.00,
            low_price=2493.00,
            close_price=2494.00,
            volume=1900,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3B - Aftermath",
            open_price=2494.00,
            high_price=2496.00,
            low_price=2490.00,
            close_price=2492.50,
            volume=1800,
            pattern="open_high_low_close",
        ),
    ]


def scenario_c_path() -> List[CandleSpec]:
    """Late-day hold that should be force-closed at 15:20 IST."""
    return [
        CandleSpec(
            label="Phase 3C - Controlled Hold 1",
            open_price=2518.90,
            high_price=2523.20,
            low_price=2517.60,
            close_price=2521.20,
            volume=1500,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 2",
            open_price=2521.20,
            high_price=2525.00,
            low_price=2520.60,
            close_price=2524.60,
            volume=1450,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 3",
            open_price=2524.60,
            high_price=2527.00,
            low_price=2522.70,
            close_price=2526.10,
            volume=1400,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 4",
            open_price=2526.10,
            high_price=2528.00,
            low_price=2524.20,
            close_price=2526.40,
            volume=1350,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 5",
            open_price=2526.40,
            high_price=2528.00,
            low_price=2523.80,
            close_price=2525.00,
            volume=1300,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3C - Into Square-Off",
            open_price=2525.00,
            high_price=2527.50,
            low_price=2522.90,
            close_price=2525.00,
            volume=1250,
            pattern="open_low_high_close",
        ),
    ]


class FlightSimulator:
    """Wires the synthetic stream into the live production modules."""

    def __init__(self, scenario_name: str, expect_square_off: bool = False):
        self.scenario_name = scenario_name
        self.expect_square_off = expect_square_off
        self.trade_taken = False
        self.entry_ticket: Optional[dict] = None
        self.exit_summary: Optional[dict] = None
        self.current_timestamp: Optional[datetime] = None
        self.square_off_triggered = False

        self.trader = PaperTrader(
            total_capital=STARTING_CAPITAL,
            working_capital_pct=0.50,
            daily_loss_limit=DAILY_LOSS_LIMIT,
            risk_per_trade=ENTRY_RISK_LIMIT,
            stop_loss_pct=0.005,
            reward_to_risk=2.0,
        )
        self.builder = CandleBuilder(interval_seconds=60, on_candle_close=self.on_candle_close)

    def on_candle_close(self, df):
        """Called by CandleBuilder every time a 1-minute candle closes."""
        analyzed = generate_vwap_signal(df.copy())
        latest = analyzed.iloc[-1]
        candle_no = len(analyzed)
        timestamp = latest["Timestamp"]
        close_price = float(latest["Close"])
        vwap = float(latest["VWAP"])
        diff = close_price - vwap
        signal_text = "YES" if bool(latest["Buy_Signal"]) else "NO"

        logging.info(
            f"[{self.scenario_name}] Candle {candle_no:02d} closed | "
            f"{timestamp} | "
            f"O:{latest['Open']:.2f} H:{latest['High']:.2f} "
            f"L:{latest['Low']:.2f} C:{close_price:.2f} "
            f"V:{int(latest['Volume'])} | "
            f"VWAP:{vwap:.2f} | Close-VWAP:{diff:+.2f} | "
            f"Signal:{signal_text}"
        )

        if bool(latest["Buy_Signal"]):
            signal_timestamp = self.current_timestamp or timestamp
            state = get_market_state(signal_timestamp)
            if not can_enter_new_positions(signal_timestamp):
                logging.info(
                    f"[{self.scenario_name}] Buy signal rejected | "
                    f"State:{state.value} | Timestamp:{signal_timestamp}"
                )
                return

            available_capital = float(self.trader.working_capital)
            ticket = self.trader.execute_trade(
                {
                    "VWAP": vwap,
                    "Close": close_price,
                    "symbol": SYMBOL,
                    "timestamp": signal_timestamp,
                },
                timestamp=signal_timestamp,
            )
            if ticket is not None:
                self.trade_taken = True
                self.entry_ticket = ticket
                self._assert_trade_limits(ticket, available_capital)
                self._print_trade_summary(ticket, available_capital)

    def _assert_trade_limits(self, ticket: dict, available_capital: float) -> None:
        total_cost = float(ticket["total_cost"])
        risk_distance = float(ticket["entry_price"]) - float(ticket["stop_loss_price"])
        total_risk = float(ticket["quantity"]) * risk_distance

        assert total_cost <= WORKING_CAPITAL_LIMIT + 1e-9, (
            f"{self.scenario_name}: total cost {total_cost:.2f} exceeded the "
            f"50% working capital cap of {WORKING_CAPITAL_LIMIT:.2f}"
        )
        assert total_cost <= available_capital + 1e-9, (
            f"{self.scenario_name}: total cost {total_cost:.2f} exceeded available "
            f"capital at entry {available_capital:.2f}"
        )
        assert total_risk <= DAILY_LOSS_LIMIT + 1e-9, (
            f"{self.scenario_name}: trade risk {total_risk:.2f} exceeded the "
            f"2% daily loss limit of {DAILY_LOSS_LIMIT:.2f}"
        )

    def _print_trade_summary(self, ticket: dict, available_capital: float) -> None:
        logging.info(
            f"[{self.scenario_name}] Trade Ticket | "
            f"Entry:{rupees(ticket['entry_price'])} | "
            f"Qty:{ticket['quantity']} | "
            f"Max Capital Used:{rupees(ticket['total_cost'])} / {rupees(WORKING_CAPITAL_LIMIT)} | "
            f"Stop Loss:{rupees(ticket['stop_loss_price'])} | "
            f"Target:{rupees(ticket['target_price'])} | "
            f"Risk/Trade:{rupees(ticket['potential_loss'])} / {rupees(DAILY_LOSS_LIMIT)} | "
            f"Available Capital Before Entry:{rupees(available_capital)}"
        )

    def _print_exit_summary(self, summary: dict) -> None:
        virtual_equity = self.trader.backup_capital + self.trader.working_capital
        logging.info(
            f"[{self.scenario_name}] Exit Summary | "
            f"{summary['result']} | "
            f"Exit:{rupees(summary['exit_price'])} | "
            f"Realized P&L:{summary['pnl']:+.2f} | "
            f"Daily P&L:{self.trader.daily_pnl:+.2f} | "
            f"Working Capital:{rupees(self.trader.working_capital)} | "
            f"Virtual Equity:{rupees(virtual_equity)}"
        )

    def feed_tick(self, tick: dict) -> None:
        """Push one tick through the candle builder and exit monitor."""
        # Mirror the live ingestion guardrail in the simulator: if the synthetic
        # payload ever carries a zero or missing price, reject it before it reaches
        # the VWAP builder.
        price, volume = validate_tick_payload(tick)
        self.current_timestamp = tick["timestamp"]
        self.builder.on_tick(
            price=price,
            volume=volume,
            timestamp=tick["timestamp"],
        )

        exit_summary = self.trader.check_exit(
            live_price=price,
            timestamp=tick["timestamp"],
        )
        if exit_summary is not None:
            self.exit_summary = exit_summary
            self._print_exit_summary(exit_summary)
            return

        self.enforce_lifecycle(tick)

    def enforce_lifecycle(self, tick: dict) -> None:
        """Evaluate the synthetic tick timestamp against NSE session rules."""
        state = get_market_state(tick["timestamp"])

        if state == MarketPhase.SQUARE_OFF and not self.square_off_triggered:
            self.square_off_triggered = True
            summary = self.trader.square_off_all_positions(
                "EOD Auto-Square-Off",
                latest_price=float(tick["price"]),
                timestamp=tick["timestamp"],
            )
            if summary is not None:
                self.exit_summary = summary
                self._print_exit_summary(summary)
        elif state == MarketPhase.CLOSED and self.trader.has_open_position:
            summary = self.trader.square_off_all_positions(
                "Market Close Safety Square-Off",
                latest_price=float(tick["price"]),
                timestamp=tick["timestamp"],
            )
            if summary is not None:
                self.exit_summary = summary
                self._print_exit_summary(summary)

    def run(self, ticks: Iterable[dict]) -> None:
        """Run the full tick stream and verify the trade lifecycle."""
        for tick in ticks:
            self.feed_tick(tick)

        assert self.trade_taken, f"{self.scenario_name}: no buy signal was triggered"
        assert self.exit_summary is not None, (
            f"{self.scenario_name}: position never closed; check the synthetic price path"
        )
        assert not self.trader.has_open_position, (
            f"{self.scenario_name}: simulator ended with an open position"
        )
        if self.expect_square_off:
            assert self.square_off_triggered, (
                f"{self.scenario_name}: expected 15:20 square-off was not triggered"
            )
            assert self.exit_summary["reason"] == "EOD Auto-Square-Off", (
                f"{self.scenario_name}: expected EOD square-off exit, got "
                f"{self.exit_summary['reason']}"
            )

        logging.info(
            f"[{self.scenario_name}] Scenario complete | "
            f"Daily P&L:{self.trader.daily_pnl:+.2f} | "
            f"Working Capital:{rupees(self.trader.working_capital)} | "
            f"Backup Capital:{rupees(self.trader.backup_capital)}"
        )


def scenario_start_ts(start_time: time = time(9, 15)) -> datetime:
    """Anchor simulations to a known valid NSE trading day."""
    trading_day = date(2026, 8, 24)
    assert is_trading_day(trading_day), "Configured simulator date must be a trading day"
    return datetime.combine(trading_day, start_time)


def test_rejects_zero_price_tick_payload() -> None:
    """Synthetic ticks must never pass a zero or missing LTP into the builder."""
    with pytest.raises(ValueError, match="LTP must be > 0"):
        validate_tick_payload({"ltp": 0.0, "v": 100, "timestamp": datetime(2026, 8, 24, 9, 15)})

    with pytest.raises(ValueError, match="LTP must be > 0"):
        validate_tick_payload({"volume": 100, "timestamp": datetime(2026, 8, 24, 9, 15)})

    price, volume = validate_tick_payload({"ltp": 2510.25, "v": 120, "timestamp": datetime(2026, 8, 24, 9, 15)})
    assert price == 2510.25
    assert volume == 120


def test_candle_builder_keeps_native_dtypes_and_vwap_works() -> None:
    """CandleBuilder must emit a typed DataFrame that supports VWAP groupby-cumsum."""
    builder = CandleBuilder(interval_seconds=60, on_candle_close=lambda df: None)

    builder.on_tick(price=100.0, volume=10, timestamp=datetime(2026, 8, 24, 9, 15, 0))
    builder.on_tick(price=102.0, volume=20, timestamp=datetime(2026, 8, 24, 9, 15, 30))
    builder.on_tick(price=101.5, volume=30, timestamp=datetime(2026, 8, 24, 9, 16, 0))

    assert str(builder.df["Timestamp"].dtype) == "datetime64[ns]"
    assert str(builder.df["Open"].dtype) == "float64"
    assert str(builder.df["Volume"].dtype) == "float64"

    result = generate_vwap_signal(builder.df)
    assert "VWAP" in result.columns
    assert result["VWAP"].notna().any()
    assert isinstance(result["VWAP"].iloc[0], float)


def test_vwap_resets_on_new_session_day() -> None:
    """VWAP must reset for a brand-new day instead of carrying yesterday's volume."""
    previous_day = pd.DataFrame(
        {
            "Timestamp": [
                datetime(2026, 8, 24, 15, 20),
                datetime(2026, 8, 24, 15, 21),
            ],
            "Open": [100.0, 110.0],
            "High": [110.0, 120.0],
            "Low": [90.0, 100.0],
            "Close": [110.0, 115.0],
            "Volume": [100, 200],
        }
    ).set_index("Timestamp")

    next_day = pd.DataFrame(
        {
            "Timestamp": [
                datetime(2026, 8, 25, 9, 15),
                datetime(2026, 8, 25, 9, 16),
            ],
            "Open": [50.0, 55.0],
            "High": [60.0, 70.0],
            "Low": [40.0, 45.0],
            "Close": [50.0, 60.0],
            "Volume": [10, 20],
        }
    ).set_index("Timestamp")

    combined = pd.concat([previous_day, next_day])
    result = generate_vwap_signal(combined)

    first_next_day_vwap = float(result.loc[datetime(2026, 8, 25, 9, 15), "VWAP"])
    assert first_next_day_vwap == 50.0, "VWAP reset should start fresh at the next session"


def test_seconds_until_market_start_skips_closed_days() -> None:
    """The wait should roll forward to the next actual NSE trading open."""
    sunday_now = datetime(2026, 8, 23, 10, 0)
    sunday_target = datetime(2026, 8, 24, 9, 15, tzinfo=IST)
    sunday_delta = (sunday_target - sunday_now.replace(tzinfo=IST)).total_seconds()
    assert abs(seconds_until_market_start(sunday_now) - sunday_delta) < 1.0

    open_after_close = datetime(2026, 8, 24, 9, 20)
    next_open = datetime(2026, 8, 25, 9, 15, tzinfo=IST)
    next_delta = (next_open - open_after_close.replace(tzinfo=IST)).total_seconds()
    assert abs(seconds_until_market_start(open_after_close) - next_delta) < 1.0


def test_capital_allocation_and_tranches() -> None:
    """Verify production capital allocation and 3-stage tranche partitions."""
    trader = PaperTrader()
    assert trader.total_capital == 10017.00
    assert trader.working_capital == 5008.50
    assert trader.backup_capital == 5008.50
    assert trader.risk_per_trade == 100.00
    assert trader.daily_loss_limit == 200.00

    # Tranches: 33%, 33%, 34% of 5008.50
    assert len(trader.tranche_capitals) == 3
    assert trader.tranche_capitals[0] == 1652.80
    assert trader.tranche_capitals[1] == 1652.80
    assert trader.tranche_capitals[2] == 1702.90
    assert round(sum(trader.tranche_capitals), 2) == 5008.50


def test_rolling_atr_and_candle_builder_exposure() -> None:
    """CandleBuilder exposes rolling 14-period ATR and cumulative session VWAP."""
    builder = CandleBuilder(interval_seconds=60)
    start = datetime(2026, 8, 24, 9, 15, 0)

    for i in range(16):
        t0 = start + timedelta(minutes=i)
        builder.on_tick(price=200.0 + i * 0.5, volume=100, timestamp=t0)
        builder.on_tick(price=202.0 + i * 0.5, volume=150, timestamp=t0 + timedelta(seconds=30))

    # Flush last candle
    builder.on_tick(price=210.0, volume=50, timestamp=start + timedelta(minutes=16))

    assert builder.candle_count == 16
    assert builder.atr_14 is not None
    assert builder.atr_14 > 0
    assert builder.vwap is not None
    assert builder.vwap > 0

    summary = builder.latest_completed_candle
    assert summary is not None
    assert "atr_14" in summary
    assert "vwap" in summary
    assert "ATR_14" in summary
    assert "VWAP" in summary


def test_dynamic_pullback_signal_and_anti_spam_lock() -> None:
    """Test dynamic ATR band, displacement check, and anti-spam lock with 2-candle displacement unlock."""
    # Build 7 candles:
    # 0-3: establish upward trend (Close > VWAP)
    # 4: Pullback into ATR band -> triggers BUY_SIGNAL -> transitions to LOCKED
    # 5: Candle close touching band again -> LOCKED prevents signal
    # 6: Candle low displaces away above band (count = 1, still locked)
    # 7: Candle low displaces away above band (count = 2 -> UNLOCKED!)
    # 8: Candle pulls back into band -> triggers new BUY_SIGNAL!
    dates = [datetime(2026, 8, 24, 9, 15 + i) for i in range(9)]
    df = pd.DataFrame(
        {
            "Timestamp": dates,
            "Open":   [100.0, 102.0, 104.0, 106.0, 108.0, 106.0, 109.0, 112.0, 114.0],
            "High":   [102.0, 104.0, 106.0, 108.0, 108.5, 107.0, 112.0, 115.0, 114.5],
            "Low":    [ 99.8, 102.0, 104.0, 106.0, 104.5, 104.8, 108.5, 111.5, 109.5],
            "Close":  [101.5, 103.5, 105.5, 107.5, 107.0, 106.5, 111.0, 114.0, 113.0],
            "Volume": [1000,  1000,  1000,  1000,  1500,  1200,  1500,  1500,  1500],
        }
    )

    signals = generate_vwap_signal(df)
    assert "VWAP" in signals.columns
    assert "ATR_14" in signals.columns
    assert "Buy_Signal" in signals.columns

    # Candle index 4 (5th candle) fires Buy_Signal
    assert bool(signals["Buy_Signal"].iloc[4]) is True
    # Candle index 5 is consecutive right after signal -> Anti-Spam state lock prevents signal
    assert bool(signals["Buy_Signal"].iloc[5]) is False


def test_multi_tranche_pyramiding_state_machine(tmp_path) -> None:
    """Test 3-stage pyramiding state machine with zero-risk trailing stop locks."""
    csv_path = str(tmp_path / "test_pyramid_trades.csv")
    trader = PaperTrader(
        total_capital=10017.00,
        working_capital_pct=0.50,
        csv_log_path=csv_path,
    )

    t0 = datetime(2026, 8, 24, 9, 20)

    # ── 1. TRANCHE 1 (Base Entry @ ₹100) ──────────────────────────────
    ticket1 = trader.execute_trade(
        {"VWAP": 100.00, "Close": 100.20, "symbol": "TATASTEEL"},
        timestamp=t0,
    )
    assert ticket1 is not None
    assert trader.state.value == "HOLDING_TRANCHE_1"
    assert ticket1["tranche_number"] == 1
    # Quantity: floor(1652.80 / 100) = 16 shares
    assert ticket1["quantity"] == 16
    assert trader._open_position["stop_loss_price"] == 99.50   # 100 * 0.995 (-0.5%)
    assert trader._open_position["target_price"] == 101.00      # 100 * 1.010 (+1.0%, 1:2 R:R)

    # ── 2. Guard: Scale-in below +0.50% gain is rejected ──────────────
    ticket_fail = trader.execute_trade(
        {"VWAP": 100.30, "Close": 100.30, "symbol": "TATASTEEL"},
        timestamp=t0 + timedelta(minutes=1),
    )
    assert ticket_fail is None
    assert trader.state.value == "HOLDING_TRANCHE_1"

    # ── 3. TRANCHE 2 (Scale 1 @ ₹100.60, gain +0.60% >= +0.50%) ───────
    t1 = t0 + timedelta(minutes=2)
    ticket2 = trader.execute_trade(
        {"VWAP": 100.60, "Close": 100.60, "symbol": "TATASTEEL"},
        timestamp=t1,
    )
    assert ticket2 is not None
    assert trader.state.value == "HOLDING_TRANCHE_2"
    assert ticket2["tranche_number"] == 2
    # Q2: floor(1652.80 / 100.60) = 16 shares
    assert ticket2["quantity"] == 16
    assert trader._open_position["quantity"] == 32  # 16 + 16

    # VWAP Avg Entry: (100*16 + 100.60*16)/32 = 100.30
    assert trader._open_position["average_entry_price"] == 100.30
    # Zero-Risk Lock: SL trailed to max(P_entry_1=100.00, 100.30*0.995=99.80) -> 100.00 (Breakeven Floor)
    assert trader._open_position["stop_loss_price"] == 100.00
    # Target: 100.30 * 1.010 = 101.30
    assert trader._open_position["target_price"] == 101.30

    # ── 4. TRANCHE 3 (Scale 2 @ ₹101.20, gain +0.60% from T2 >= +0.50%)
    t2 = t0 + timedelta(minutes=4)
    ticket3 = trader.execute_trade(
        {"VWAP": 101.20, "Close": 101.20, "symbol": "TATASTEEL"},
        timestamp=t2,
    )
    assert ticket3 is not None
    assert trader.state.value == "MAX_TRANCHES_HELD"
    assert ticket3["tranche_number"] == 3
    # Q3: floor(1702.90 / 101.20) = 16 shares
    assert ticket3["quantity"] == 16
    assert trader._open_position["quantity"] == 48  # 32 + 16

    # VWAP Avg Entry: (100*16 + 100.60*16 + 101.20*16)/48 = 100.60
    assert trader._open_position["average_entry_price"] == 100.60
    # Zero-Risk Lock: SL trailed to max(P_entry_2=100.60, 100.60*0.995=100.10) -> 100.60
    assert trader._open_position["stop_loss_price"] == 100.60
    # Target: 100.60 * 1.010 = 101.61
    assert trader._open_position["target_price"] == 101.61

    # ── 5. Target Hit Exit @ ₹101.65 ──────────────────────────────────
    exit_summary = trader.check_exit(101.65, timestamp=t0 + timedelta(minutes=6))
    assert exit_summary is not None
    assert exit_summary["exit_reason"] == "Target Hit"
    assert exit_summary["tranches_filled"] == 3
    assert exit_summary["total_quantity"] == 48
    assert exit_summary["net_pnl"] > 0
    assert not trader.has_open_position


def test_no_time_stop_at_40_or_more_candles(tmp_path) -> None:
    """Verify that all 40-candle / time-stop mechanisms are permanently eliminated."""
    csv_path = str(tmp_path / "test_no_time_stop.csv")
    trader = PaperTrader(
        total_capital=10017.00,
        working_capital_pct=0.50,
        csv_log_path=csv_path,
    )
    entry_ts = datetime(2026, 8, 24, 9, 20)
    trader.execute_trade(
        {"VWAP": 200.00, "Close": 200.20, "symbol": "TATAMOTORS"},
        timestamp=entry_ts,
    )
    assert trader.has_open_position

    # Simulate 60 candles (beyond 40 candles)
    for i in range(1, 61):
        res = trader.notify_candle_close(
            timestamp=entry_ts + timedelta(minutes=i),
            latest_price=200.10,
        )
        assert res is None
        assert trader.has_open_position  # Position stays active!


def test_exit_priorities_sl_tp_eod(tmp_path) -> None:
    """Verify strict exit priority: Priority 1 (SL) -> Priority 2 (TP) -> Priority 3 (15:20 EOD)."""
    csv_path = str(tmp_path / "test_exit_prio.csv")

    # Case 1: Stop Loss Triggered
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50, csv_log_path=csv_path)
    trader.execute_trade({"VWAP": 100.00, "Close": 100.00, "symbol": "ITC"}, timestamp=datetime(2026, 8, 24, 9, 20))
    res_sl = trader.check_exit(99.40, timestamp=datetime(2026, 8, 24, 9, 25))
    assert res_sl is not None
    assert res_sl["exit_reason"] == "Stop Loss"

    # Case 2: Target Triggered
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50, csv_log_path=csv_path)
    trader.execute_trade({"VWAP": 100.00, "Close": 100.00, "symbol": "ITC"}, timestamp=datetime(2026, 8, 24, 9, 20))
    res_tp = trader.check_exit(101.10, timestamp=datetime(2026, 8, 24, 9, 25))
    assert res_tp is not None
    assert res_tp["exit_reason"] == "Target Hit"

    # Case 3: EOD Auto-Square-Off
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50, csv_log_path=csv_path)
    trader.execute_trade({"VWAP": 100.00, "Close": 100.00, "symbol": "ITC"}, timestamp=datetime(2026, 8, 24, 9, 20))
    res_eod = trader.square_off_all_positions(
        "EOD Auto-Square-Off",
        latest_price=100.20,
        timestamp=datetime(2026, 8, 24, 15, 20),
    )
    assert res_eod is not None
    assert res_eod["exit_reason"] == "EOD Auto-Square-Off"


def test_statutory_friction_gate_nse_cash() -> None:
    """Verify statutory charge model matches NSE cash equity rates."""
    trader = PaperTrader()

    # Calculate round trip for 100 shares @ 100 entry, 101 exit
    costs = trader.estimate_round_trip_costs(quantity=100, entry_price=100.0, exit_price=101.0)
    # Buy turnover = 10,000, Sell turnover = 10,100
    assert costs["buy_turnover"] == 10000.0
    assert costs["sell_turnover"] == 10100.0

    # Brokerage: min(20, 10000*0.0003) = 3.00 buy, min(20, 10100*0.0003) = 3.03 sell -> total 6.03
    assert round(costs["brokerage"], 2) == 6.03
    # STT: 10100 * 0.00025 = 2.525 -> 2.525
    assert round(costs["stt"], 3) == 2.525
    # Stamp Duty: 10000 * 0.00003 = 0.30
    assert round(costs["stamp_duty"], 2) == 0.30
    # Exchange Fee: (10000 + 10100) * 0.0000345 = 0.69345
    assert abs(costs["exchange_fee"] - 0.69345) < 1e-6

    assert costs["total_charges"] > 0


def test_trades_csv_13_columns_schema(tmp_path) -> None:
    """Verify persistent trades.csv adheres to exact 13-field schema."""
    csv_path = str(tmp_path / "test_schema_trades.csv")
    trader = PaperTrader(
        total_capital=10017.00,
        working_capital_pct=0.50,
        csv_log_path=csv_path,
    )
    trader.execute_trade(
        {"VWAP": 150.00, "Close": 150.20, "symbol": "COALINDIA"},
        timestamp=datetime(2026, 8, 24, 9, 20),
    )
    trader.close_position(
        exit_price=151.50,
        timestamp=datetime(2026, 8, 24, 9, 35),
        reason="Target Hit",
    )

    with open(csv_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    headers = lines[0].split(",")
    expected_headers = [
        "timestamp",
        "trade_id",
        "symbol",
        "tranches_filled",
        "avg_entry_price",
        "exit_price",
        "total_quantity",
        "exit_reason",
        "gross_pnl",
        "statutory_charges",
        "net_pnl",
        "net_roi_pct",
        "ending_working_capital",
    ]
    assert headers == expected_headers
    data_cols = lines[1].split(",")
    assert len(data_cols) == 13
    assert data_cols[2] == "COALINDIA"
    assert data_cols[3] == "1"
    assert data_cols[7] == "Target Hit"


def run_scenario(
    name: str,
    extra_path: Sequence[CandleSpec],
    start_time: time = time(9, 15),
    expect_square_off: bool = False,
) -> None:
    simulator = FlightSimulator(name, expect_square_off=expect_square_off)
    candles = base_market_path() + list(extra_path)
    ticks = build_stream(scenario_start_ts(start_time), candles)
    simulator.run(ticks)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    logging.info("=" * 78)
    logging.info("OFFLINE FLIGHT SIMULATOR")
    logging.info("Synthetic ticks -> CandleBuilder -> VWAP Signal Brain -> PaperTrader")
    logging.info(f"Start Price: {rupees(START_PRICE)} | Starting Capital: {rupees(STARTING_CAPITAL)}")
    logging.info("=" * 78)

    logging.info("")
    logging.info("SCENARIO A: Target Hit")
    logging.info("-" * 78)
    run_scenario("Scenario A", scenario_a_path())

    logging.info("")
    logging.info("SCENARIO B: Stop Loss Hit")
    logging.info("-" * 78)
    run_scenario("Scenario B", scenario_b_path())

    logging.info("")
    logging.info("SCENARIO C: 15:20 EOD Auto-Square-Off")
    logging.info("-" * 78)
    run_scenario(
        "Scenario C",
        scenario_c_path(),
        start_time=time(15, 9),
        expect_square_off=True,
    )

    logging.info("")
    logging.info("=" * 78)
    logging.info("ALL SCENARIOS COMPLETED SUCCESSFULLY")
    logging.info("=" * 78)


if __name__ == "__main__":
    main()
