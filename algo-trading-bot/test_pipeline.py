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
    BaseMarketSchedule,
    MarketPhase,
    NSEMarketSchedule,
    NYSEMarketSchedule,
    can_enter_new_positions,
    get_market_schedule,
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
            high_price=2521.20,
            low_price=2517.60,
            close_price=2520.20,
            volume=1500,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 2",
            open_price=2520.20,
            high_price=2522.00,
            low_price=2518.60,
            close_price=2521.60,
            volume=1450,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 3",
            open_price=2521.60,
            high_price=2523.00,
            low_price=2519.70,
            close_price=2522.10,
            volume=1400,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 4",
            open_price=2522.10,
            high_price=2523.50,
            low_price=2520.20,
            close_price=2522.40,
            volume=1350,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 5",
            open_price=2522.40,
            high_price=2523.80,
            low_price=2519.80,
            close_price=2521.00,
            volume=1300,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3C - Into Square-Off",
            open_price=2521.00,
            high_price=2522.50,
            low_price=2519.90,
            close_price=2521.00,
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
        analyzed = generate_vwap_signal(df.copy(), min_candles_before_trade=1)
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

        signal_timestamp = self.current_timestamp or timestamp
        candle_exit_summary = self.trader.notify_candle_close(
            candle=latest.to_dict() if hasattr(latest, "to_dict") else dict(latest),
            timestamp=signal_timestamp,
            latest_price=close_price,
        )
        if candle_exit_summary is not None:
            self.exit_summary = candle_exit_summary
            self._print_exit_summary(candle_exit_summary)
            return

        if bool(latest["Buy_Signal"]):
            state = get_market_state(signal_timestamp)
            if not can_enter_new_positions(signal_timestamp):
                logging.info(
                    f"[{self.scenario_name}] Buy signal rejected | "
                    f"State:{state.value} | Timestamp:{signal_timestamp}"
                )
                return

            available_capital = float(self.trader.working_capital)
            atr_val = float(latest["ATR_14"]) if "ATR_14" in latest and pd.notna(latest["ATR_14"]) else 8.35
            ticket = self.trader.execute_trade(
                {
                    "VWAP": vwap,
                    "Close": close_price,
                    "symbol": SYMBOL,
                    "timestamp": signal_timestamp,
                    "ATR_14": atr_val,
                },
                timestamp=signal_timestamp,
                atr_14=atr_val,
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
            if exit_summary.get("reason") == "EOD Auto-Square-Off" or exit_summary.get("exit_reason") == "EOD Auto-Square-Off":
                self.square_off_triggered = True
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
    assert trader.total_capital == 10010.06
    assert trader.working_capital == 5005.03
    assert trader.backup_capital == 5005.03
    assert trader.risk_per_trade == 100.00
    assert trader.daily_loss_limit == 200.00

    # Tranches: 33%, 33%, 34% of 5005.03
    assert len(trader.tranche_capitals) == 3
    assert trader.tranche_capitals[0] == 1651.66
    assert trader.tranche_capitals[1] == 1651.66
    assert trader.tranche_capitals[2] == 1701.71
    assert round(sum(trader.tranche_capitals), 2) == 5005.03


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

    signals = generate_vwap_signal(df, min_candles_before_trade=1)
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

    # ── 1. TRANCHE 1 (Base Entry @ ₹100, ATR=0.50 -> SL dist=1.00)
    ticket1 = trader.execute_trade(
        {"VWAP": 100.00, "Close": 100.20, "symbol": "TATASTEEL", "ATR_14": 0.50},
        timestamp=t0,
    )
    assert ticket1 is not None
    assert trader.state.value == "HOLDING_TRANCHE_1"
    assert ticket1["tranche_number"] == 1
    # Quantity: floor(1652.80 / 100) = 16 shares
    assert ticket1["quantity"] == 16
    assert trader._open_position["stop_loss_price"] == 99.00   # 100 - 2.0*0.50 = 99.00
    assert trader._open_position["target_price"] == 102.00      # 100 + 2.0*1.00 = 102.00 (1:2 R:R)

    # ── 2. Guard: Scale-in below +0.30% gain is rejected ──────────────
    ticket_fail = trader.execute_trade(
        {"VWAP": 100.20, "Close": 100.20, "symbol": "TATASTEEL", "ATR_14": 0.50},
        timestamp=t0 + timedelta(minutes=1),
    )
    assert ticket_fail is None
    assert trader.state.value == "HOLDING_TRANCHE_1"

    # ── 3. TRANCHE 2 (Scale 1 @ ₹100.60, gain +0.60% >= +0.50%) ───────
    t1 = t0 + timedelta(minutes=2)
    ticket2 = trader.execute_trade(
        {"VWAP": 100.60, "Close": 100.60, "symbol": "TATASTEEL", "ATR_14": 0.50},
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
    # Anchored Target: Remains fixed at Tranche 1 target (102.00)
    assert trader._open_position["target_price"] == 102.00

    # ── 4. TRANCHE 3 (Scale 2 @ ₹101.20, gain +0.60% from T2 >= +0.50%)
    t2 = t0 + timedelta(minutes=4)
    ticket3 = trader.execute_trade(
        {"VWAP": 101.20, "Close": 101.20, "symbol": "TATASTEEL", "ATR_14": 0.50},
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
    # Anchored Target: Remains fixed at Tranche 1 target (102.00)
    assert trader._open_position["target_price"] == 102.00

    # ── 5. Target Hit Exit @ ₹102.05 (Exits at Anchored Target ₹102.00) ────
    exit_summary = trader.check_exit(102.05, timestamp=t0 + timedelta(minutes=6))
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
        {"VWAP": 200.00, "Close": 200.20, "symbol": "TATAMOTORS", "ATR_14": 0.6666666666666666},
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
    """Verify strict exit priority: Priority 1 (TP tick) -> Priority 2 (15:20 EOD) -> Candle-Close SL."""
    csv_path = str(tmp_path / "test_exit_prio.csv")

    # Case 1: Stop Loss Triggered on Confirmed Candle Close (Wick-Immune)
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50, csv_log_path=csv_path)
    trader.execute_trade(
        {"VWAP": 100.00, "Close": 100.00, "symbol": "ITC", "ATR_14": 0.3333333333333333},
        timestamp=datetime(2026, 8, 24, 9, 20),
    )
    # Intra-candle tick does NOT exit on SL (Wick Immunity)
    res_tick_sl = trader.check_exit(99.00, timestamp=datetime(2026, 8, 24, 9, 25))
    assert res_tick_sl is None
    assert trader.has_open_position

    # Candle close confirms SL breach
    res_sl = trader.notify_candle_close(latest_price=99.00, timestamp=datetime(2026, 8, 24, 9, 25))
    assert res_sl is not None
    assert res_sl["exit_reason"] == "Stop Loss (Close-Based)"
    assert not trader.has_open_position

    # Case 2: Target Triggered (Instant Tick Execution)
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50, csv_log_path=csv_path)
    trader.execute_trade(
        {"VWAP": 100.00, "Close": 100.00, "symbol": "ITC", "ATR_14": 0.3333333333333333},
        timestamp=datetime(2026, 8, 24, 9, 20),
    )
    res_tp = trader.check_exit(101.50, timestamp=datetime(2026, 8, 24, 9, 25))
    assert res_tp is not None
    assert res_tp["exit_reason"] == "Target Hit"

    # Case 3: EOD Auto-Square-Off
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50, csv_log_path=csv_path)
    trader.execute_trade(
        {"VWAP": 100.00, "Close": 100.00, "symbol": "ITC", "ATR_14": 0.3333333333333333},
        timestamp=datetime(2026, 8, 24, 9, 20),
    )
    res_eod = trader.square_off_all_positions(
        "EOD Auto-Square-Off",
        latest_price=100.20,
        timestamp=datetime(2026, 8, 24, 15, 20),
    )
    assert res_eod is not None
    assert res_eod["exit_reason"] == "EOD Auto-Square-Off"


def test_dynamic_atr_stop_loss_and_failsafe() -> None:
    """Verify ATR validation failsafes and dynamic distance calculations."""
    trader = PaperTrader()
    t0 = datetime(2026, 8, 24, 9, 20)

    # 1. Missing ATR -> Rejection
    ticket_no_atr = trader.execute_trade(
        {"VWAP": 2500.00, "Close": 2502.00, "symbol": "M&M"},
        timestamp=t0,
    )
    assert ticket_no_atr is None
    assert trader.state.value == "IDLE"

    # 2. Zero / Negative ATR -> Rejection
    ticket_zero_atr = trader.execute_trade(
        {"VWAP": 2500.00, "Close": 2502.00, "symbol": "M&M", "ATR_14": 0.0},
        timestamp=t0,
    )
    assert ticket_zero_atr is None
    assert trader.state.value == "IDLE"

    # 3. Valid ATR -> Dynamic 1:2 R:R calculation (2.0 * ATR buffer)
    current_atr = 10.0
    ticket_valid = trader.execute_trade(
        {"VWAP": 2500.00, "Close": 2502.00, "symbol": "M&M", "ATR_14": current_atr},
        timestamp=t0,
    )
    assert ticket_valid is not None
    assert trader.state.value == "HOLDING_TRANCHE_1"

    # stop_loss_distance = 2.0 * 10.0 = 20.00
    # stop_loss = 2500.00 - 20.00 = 2480.00
    # target_price = 2500.00 + (2.0 * 20.00) = 2540.00
    assert ticket_valid["stop_loss_distance"] == 20.00
    assert ticket_valid["stop_loss_price"] == 2480.00
    assert ticket_valid["target_price"] == 2540.00
    assert ticket_valid["risk_distance"] == 20.00
    assert ticket_valid["atr_14"] == 10.0


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
        {"VWAP": 150.00, "Close": 150.20, "symbol": "COALINDIA", "ATR_14": 0.50},
        timestamp=datetime(2026, 8, 24, 9, 20),
    )
    trader.close_position(
        exit_price=151.50,
        timestamp=datetime(2026, 8, 24, 9, 35),
        reason="Target Hit",
    )
    trader.flush_logs()

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


def test_pluggable_market_schedule_providers() -> None:
    """Verify Provider Strategy Pattern for NSE and NYSE market schedules."""
    nse = get_market_schedule("NSE")
    assert isinstance(nse, NSEMarketSchedule)
    assert str(nse.timezone) == "Asia/Kolkata"
    assert nse.market_open_time == time(9, 15, 0)
    assert nse.eod_square_off_time == time(15, 20, 0)
    assert nse.market_close_time == time(15, 30, 0)

    nyse = get_market_schedule("NYSE")
    assert isinstance(nyse, NYSEMarketSchedule)
    assert str(nyse.timezone) == "America/New_York"
    assert nyse.market_open_time == time(9, 30, 0)
    assert nyse.eod_square_off_time == time(15, 45, 0)
    assert nyse.market_close_time == time(16, 0, 0)

    # Dependency Injection into PaperTrader
    trader_nyse = PaperTrader(schedule=nyse)
    assert trader_nyse.schedule == nyse

    # Test EOD square-off evaluation on NYSE schedule (15:45 EST)
    nyse_eod_ts = datetime(2026, 8, 24, 15, 46, tzinfo=nyse.timezone)
    assert nyse.is_eod_square_off(nyse_eod_ts) is True


def test_dual_layer_trend_regime_filter() -> None:
    """Verify Dual-Layer Trend Regime Filter (VWAP Slope + EMA Crossover Gatekeeper)."""
    from signal_brain import evaluate_regime_gate

    # 1. Gate 1: Negative VWAP Slope blocks BUY
    assert evaluate_regime_gate("BUY", vwap_slope=-0.05, ema9=105.0, ema21=100.0) is None
    assert evaluate_regime_gate("BUY", vwap_slope=0.0, ema9=105.0, ema21=100.0) is None

    # 2. Gate 2: EMA(9) < EMA(21) blocks BUY
    assert evaluate_regime_gate("BUY", vwap_slope=0.05, ema9=95.0, ema21=100.0) is None

    # 3. Both gates pass -> BUY validated
    assert evaluate_regime_gate("BUY", vwap_slope=0.05, ema9=105.0, ema21=100.0) == "BUY"

    # 4. Future Adaptive SHORT Regime Gate
    assert evaluate_regime_gate("SHORT", vwap_slope=0.05, ema9=95.0, ema21=100.0) is None
    assert evaluate_regime_gate("SHORT", vwap_slope=-0.05, ema9=105.0, ema21=100.0) is None
    assert evaluate_regime_gate("SHORT", vwap_slope=-0.05, ema9=95.0, ema21=100.0) == "SHORT"

    # 5. End-to-end integration: Bearish Downtrend suppresses raw pullback signals
    dates = [datetime(2026, 8, 24, 9, 15 + i) for i in range(12)]
    # Falling price series: 200 -> 190 -> 180 -> 170 -> 160 -> 150
    bearish_df = pd.DataFrame(
        {
            "Timestamp": dates,
            "Open":   [200.0, 198.0, 195.0, 190.0, 185.0, 180.0, 175.0, 170.0, 165.0, 160.0, 158.0, 157.0],
            "High":   [201.0, 199.0, 196.0, 191.0, 186.0, 181.0, 176.0, 171.0, 166.0, 161.0, 159.0, 158.0],
            "Low":    [197.0, 194.0, 189.0, 184.0, 179.0, 174.0, 169.0, 164.0, 159.0, 155.0, 156.0, 155.0],
            "Close":  [198.0, 195.0, 190.0, 185.0, 180.0, 175.0, 170.0, 165.0, 160.0, 158.0, 157.0, 156.0],
            "Volume": [1000] * 12,
        }
    )
    result = generate_vwap_signal(bearish_df, min_candles_before_trade=1)
    assert "VWAP_Slope" in result.columns
    assert "EMA_9" in result.columns
    assert "EMA_21" in result.columns
    # Ensure no BUY signal was permitted in this severe downtrend regime
    assert not result["Buy_Signal"].any()


def test_vwap_stabilization_and_deep_breakdown_filter() -> None:
    """Verify VWAP 15-minute stabilization gate and violent knife breakdown filter."""
    # 1. Test Stabilization Gate (Default 15 candles):
    # 14 candles should all yield Buy_Signal = False
    dates = [datetime(2026, 8, 24, 9, 15 + i) for i in range(16)]
    # Trending up candles
    open_prices = [100.0 + i * 2.0 for i in range(16)]
    high_prices = [p + 2.0 for p in open_prices]
    low_prices = [p - 0.5 for p in open_prices]
    close_prices = [p + 1.5 for p in open_prices]

    # Pre-calculate VWAP level up to candle 13 to place candle 14 pullback accurately
    # Candle 14 (15th candle): pullback touches VWAP (~115) and closes back above VWAP
    open_prices[14] = 118.0
    high_prices[14] = 119.0
    low_prices[14] = 114.0   # Dips below / tests VWAP + 0.2*ATR
    close_prices[14] = 116.0 # Rebounds and closes above VWAP

    df_16 = pd.DataFrame({
        "Timestamp": dates,
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": [1000] * 16,
    })

    # Run with default MIN_CANDLES_BEFORE_TRADE = 15
    res = generate_vwap_signal(df_16)
    # The first 14 candles (< 15) must be False
    assert not res["Buy_Signal"].iloc[:14].any()
    # The 15th candle (index 14) passes stabilization gate and fires
    assert bool(res["Buy_Signal"].iloc[14]) is True

    # 2. Test Deep Breakdown / Falling Knife Filter:
    # If candle N-1 low violently crashes < (VWAP - 1.0 * ATR), signal on candle N must be blocked
    df_knife = df_16.copy()
    # Force candle 13 (prior to pullback) to crash deeply below VWAP
    df_knife.loc[13, "Low"] = 50.0  # deep knife crash
    res_knife = generate_vwap_signal(df_knife)
    assert bool(res_knife["Buy_Signal"].iloc[14]) is False


def test_post_stop_loss_cooldown_firewall() -> None:
    """Verify 10-candle cooldown firewall immediately following a Stop Loss."""
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50)
    # Default ready state
    assert trader.candles_since_last_exit == 999

    # Enter initial trade
    t0 = datetime(2026, 8, 24, 9, 30)
    ticket = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.5, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
    )
    assert ticket is not None
    assert trader.has_open_position is True

    # Stop loss hit -> close position
    t1 = datetime(2026, 8, 24, 9, 35)
    trader.close_position(exit_price=98.50, timestamp=t1, reason="Stop Loss")
    assert trader.has_open_position is False
    assert trader.candles_since_last_exit == 0

    # Next 1..9 candles: attempt to re-enter immediately -> blocked by cooldown
    for c in range(1, 10):
        trader.notify_candle_close(timestamp=datetime(2026, 8, 24, 9, 35 + c), latest_price=100.0)
        assert trader.candles_since_last_exit == c
        attempt = trader.execute_trade(
            {"VWAP": 100.0, "Close": 100.5, "symbol": "TATASTEEL", "ATR_14": 1.0},
            timestamp=datetime(2026, 8, 24, 9, 35 + c),
            atr_14=1.0,
        )
        assert attempt is None  # Blocked by cooldown!

    # 10th candle closes -> cooldown expires (candles_since_last_exit == 10)
    trader.notify_candle_close(timestamp=datetime(2026, 8, 24, 9, 45), latest_price=100.0)
    assert trader.candles_since_last_exit == 10

    # Trade is now allowed
    valid_ticket = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.5, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=datetime(2026, 8, 24, 9, 45),
        atr_14=1.0,
    )
    assert valid_ticket is not None
    assert trader.has_open_position is True


def test_wick_immunity_and_candle_close_stop_loss() -> None:
    """Verify that intra-candle wicks do not trigger Stop Loss, while candle closes and tick targets do."""
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50)
    # Entry @ 100.00 with ATR = 1.0 -> SL = 100 - (2.0 * 1.0) = 98.00, Target = 100 + 4.0 = 104.00
    t0 = datetime(2026, 8, 24, 9, 30)
    ticket = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.2, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
    )
    assert ticket is not None
    assert ticket["stop_loss_price"] == 98.00
    assert ticket["target_price"] == 104.00

    # 1. Wick Shakeout Test: Intraday tick flashes down to 97.40 (< 98.00 SL)
    wick_exit = trader.check_exit(97.40, timestamp=datetime(2026, 8, 24, 9, 31, 15))
    # Wick Immunity: Tick-based SL is DISABLED -> position remains intact!
    assert wick_exit is None
    assert trader.has_open_position is True

    # 2. Candle completes and closes at 98.50 (above SL) -> position survives!
    c1_exit = trader.notify_candle_close(latest_price=98.50, timestamp=datetime(2026, 8, 24, 9, 32))
    assert c1_exit is None
    assert trader.has_open_position is True

    # 3. Next candle formally closes at 97.80 (below 98.00 SL) -> Stop Loss triggers on candle close!
    c2_exit = trader.notify_candle_close(latest_price=97.80, timestamp=datetime(2026, 8, 24, 9, 33))
    assert c2_exit is not None
    assert c2_exit["exit_reason"] == "Stop Loss (Close-Based)"
    assert trader.has_open_position is False

    # 4. Instant Tick-Based Target Hit: Re-enter and verify target hits immediately on tick
    trader.candles_since_last_exit = 15  # bypass cooldown
    t1 = datetime(2026, 8, 24, 9, 50)
    trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.2, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t1,
        atr_14=1.0,
    )
    # Intra-candle tick surges to 104.50 (≥ 104.00 Target) -> triggers immediately on tick!
    target_exit = trader.check_exit(104.50, timestamp=datetime(2026, 8, 24, 9, 51, 30))
    assert target_exit is not None
    assert target_exit["exit_reason"] == "Target Hit"
    assert trader.has_open_position is False


def test_volatility_floor_gate() -> None:
    """Verify that signal_brain blocks signals when ATR < MIN_ATR (0.30)."""
    # 16 candles with micro-volatility (High - Low = 0.10 -> ATR ~ 0.10 < 0.30)
    dates = [datetime(2026, 8, 24, 9, 15 + i) for i in range(16)]
    open_prices = [100.0 + i * 0.05 for i in range(16)]
    high_prices = [p + 0.08 for p in open_prices]
    low_prices = [p - 0.02 for p in open_prices]
    close_prices = [p + 0.05 for p in open_prices]

    # Candle 14 pullback touch
    open_prices[14] = 100.35
    high_prices[14] = 100.40
    low_prices[14] = 100.10
    close_prices[14] = 100.36

    df_low_vol = pd.DataFrame({
        "Timestamp": dates,
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": [1000] * 16,
    })

    res_low = generate_vwap_signal(df_low_vol)
    # Blocked by Volatility Floor Gate (ATR < 0.30)
    assert not res_low["Buy_Signal"].any()


def test_true_net_rr_friction_gate() -> None:
    """Verify that execution_engine aborts trades if Net R:R < 1.5 or Net Profit < 2x friction."""
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50)
    t0 = datetime(2026, 8, 24, 9, 30)

    # 1. Micro-ATR (e.g. 0.15) produces tiny profit where statutory friction destroys Net R:R
    ticket_micro = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.2, "symbol": "TATASTEEL", "ATR_14": 0.15},
        timestamp=t0,
        atr_14=0.15,
    )
    assert ticket_micro is None
    assert trader.has_open_position is False

    # 2. Healthy ATR (e.g. 1.0) produces robust profit and passes True Net-R:R Gate
    ticket_healthy = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.2, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
    )
    assert ticket_healthy is not None
    assert trader.has_open_position is True


def test_recalibrated_pyramiding_tranche2_trigger() -> None:
    """Verify that Tranche 2 unlocks at +0.30% gain (TRANCHE2_TRIGGER_PCT = 0.003)."""
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50)
    t0 = datetime(2026, 8, 24, 9, 30)

    # Base entry @ 100.00
    ticket1 = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
    )
    assert ticket1 is not None
    assert trader.state.value == "HOLDING_TRANCHE_1"

    # Price at 100.25 (+0.25% < +0.30% trigger) -> rejected
    t_fail = trader.execute_trade(
        {"VWAP": 100.25, "Close": 100.25, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0 + timedelta(minutes=1),
    )
    assert t_fail is None
    assert trader.state.value == "HOLDING_TRANCHE_1"

    # Price at 100.35 (+0.35% >= +0.30% trigger) -> Tranche 2 unlocked!
    ticket2 = trader.execute_trade(
        {"VWAP": 100.35, "Close": 100.35, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0 + timedelta(minutes=2),
    )
    assert ticket2 is not None
    assert trader.state.value == "HOLDING_TRANCHE_2"
    assert ticket2["tranche_number"] == 2


def test_theta_decay_breakeven_defense() -> None:
    """Verify that after 15 candles held in profit, Stop Loss is aggressively trailed to entry (risk = 0)."""
    trader = PaperTrader(total_capital=10017.00, working_capital_pct=0.50)
    t0 = datetime(2026, 8, 24, 9, 30)

    # Base entry @ 100.00 with ATR = 1.0 -> initial SL = 98.00
    ticket = trader.execute_trade(
        {"VWAP": 100.0, "Close": 100.0, "symbol": "TATASTEEL", "ATR_14": 1.0},
        timestamp=t0,
        atr_14=1.0,
    )
    assert ticket is not None
    assert trader.candles_held == 0
    assert trader._open_position["stop_loss_price"] == 98.00

    # Simulate 14 completed candles in mild profit (close = 100.15)
    for c in range(1, 15):
        trader.notify_candle_close(latest_price=100.15, timestamp=t0 + timedelta(minutes=c))
        assert trader.candles_held == c
        assert trader._open_position["stop_loss_price"] == 98.00  # Not yet 15 candles

    # 15th candle closes in profit (close = 100.15 > 100.00 entry) -> Theta Defense triggers!
    trader.notify_candle_close(latest_price=100.15, timestamp=t0 + timedelta(minutes=15))
    assert trader.candles_held == 15
    assert trader._open_position["stop_loss_price"] == 100.00  # Trailed to Breakeven!
    assert trader._open_position["breakeven_armed"] is True


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
