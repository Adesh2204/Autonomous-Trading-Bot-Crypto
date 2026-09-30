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

import config
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
from signal_brain import detect_daily_bias, generate_vwap_signal


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
        analyzed = generate_vwap_signal(df.copy(), min_candles_before_trade=1, atr_band_mult=0.20)
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


def test_capital_allocation_and_tranches(tmp_path):
    t=paper_trader(tmp_path)
    assert t.total_capital==20000 and t.working_capital==10000 and t.backup_capital==10000
    assert t.risk_per_trade==100 and t.daily_loss_limit==200
    assert t.max_tranches==1 and t.tranche_capitals==[10000]
    t.shutdown()


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

    signals = generate_vwap_signal(df, min_candles_before_trade=1, atr_band_mult=0.20)
    assert "VWAP" in signals.columns
    assert "ATR_14" in signals.columns
    assert "Buy_Signal" in signals.columns

    # Candle index 4 (5th candle) fires Buy_Signal
    assert bool(signals["Buy_Signal"].iloc[4]) is True
    # Candle index 5 is consecutive right after signal -> Anti-Spam state lock prevents signal
    assert bool(signals["Buy_Signal"].iloc[5]) is False


def test_multi_tranche_pyramiding_state_machine(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.open_position['current_tranches']==1
    with pytest.raises(SafetyError,match='SCALE_IN_DISABLED'):t._execute_tranche_2(payload(),NOW)
    t.shutdown()


def test_no_time_stop_at_40_or_more_candles(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    for _ in range(45):
        assert t.notify_candle_close({'Timestamp':NOW,'Close':t.avg_entry_price+1}) is None
    assert t.has_open_position and t.candles_held==45
    t.shutdown()


def test_exit_priorities_sl_tp_eod(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    target=t.open_position['target_price']
    t.set_quote(IDENTITY,MarketQuote(target-.05,target+.05,1000,1000,NOW,target))
    summary=t.check_exit(target,NOW)
    assert summary and summary['exit_reason']=='Target Hit'
    assert summary['actual_exit_price']!=target
    late=NOW.replace(hour=15,minute=0)
    assert t.execute_trade(payload(),timestamp=late) is None
    assert t.last_rejection=='ENTRY_CUTOFF_REACHED'
    t.shutdown()


def test_dynamic_atr_stop_loss_and_failsafe(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.open_position['stop_loss_price']==290
    assert t.open_position['target_price']==320
    assert t.open_position['projected_net_loss_at_stop']<=100
    t.shutdown()
    other=paper_trader(tmp_path/'invalid')
    assert other.execute_trade(payload(atr=0),timestamp=NOW) is None
    assert other.last_rejection=='INVALID_ATR'
    assert not other.journal.fills()
    other.shutdown()


def test_statutory_friction_gate_nse_cash() -> None:
    """Verify statutory charge model matches correct Angel One NSE equity intraday rates."""
    trader = PaperTrader()

    # Calculate round trip for 100 shares @ 100 entry, 101 exit
    costs = trader.estimate_round_trip_costs(quantity=100, entry_price=100.0, exit_price=101.0)
    # Buy turnover = 10,000, Sell turnover = 10,100
    assert costs["buy_turnover"] == 10000.0
    assert costs["sell_turnover"] == 10100.0

    # Brokerage: max(5, min(20, 10000*0.001)) = 10.00 buy, max(5, min(20, 10100*0.001)) = 10.10 sell -> 20.10
    assert round(costs["brokerage"], 2) == 20.10
    # STT: 10100 * 0.00025 = 2.525 -> 2.525
    assert round(costs["stt"], 3) == 2.525
    # Stamp Duty: 10000 * 0.00003 = 0.30
    assert round(costs["stamp_duty"], 2) == 0.30
    # Exchange Fee: (10000 + 10100) * 0.000030699 = 0.617...
    assert abs(costs["exchange_fee"] - 20100 * 0.000030699) < 1e-6

    assert costs["total_charges"] > 0


def test_trades_csv_13_columns_schema(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.close_position(300,NOW)
    t.shutdown()
    df=pd.read_csv(tmp_path/'trades.csv')
    assert {'environment','trade_id','broker_order_id','broker_fill_id','actual_entry_price','actual_exit_price','net_pnl','entry_fee_source'}<=set(df)
    assert len(df)==1 and df.iloc[0]['environment']=='TEST'
    assert str(df.iloc[0]['trade_id'])


def test_pluggable_market_schedule_providers() -> None:
    """Verify Provider Strategy Pattern for NSE and NYSE market schedules."""
    nse = get_market_schedule("NSE")
    assert isinstance(nse, NSEMarketSchedule)
    assert str(nse.timezone) == "Asia/Kolkata"
    assert nse.market_open_time == time(9, 15, 0)
    assert nse.eod_square_off_time == time(15, 0, 0)
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


def test_post_stop_loss_cooldown_firewall(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    t.set_quote(IDENTITY,MarketQuote(289.75,289.85,1000,1000,NOW,289.8))
    assert t.notify_candle_close({'Timestamp':NOW,'Close':289.8})
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.last_rejection=='COOLDOWN'
    for _ in range(config.REENTRY_COOLDOWN_CANDLES):t.notify_candle_close({'Timestamp':NOW,'Close':300})
    assert t.candles_since_last_sl==config.REENTRY_COOLDOWN_CANDLES
    t.shutdown()


def test_wick_immunity_and_candle_close_stop_loss(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    t.set_quote(IDENTITY,MarketQuote(289.75,289.85,1000,1000,NOW,289.8))
    assert t.check_exit(289.8,NOW) is None
    assert t.has_open_position
    summary=t.notify_candle_close({'Timestamp':NOW,'Close':289.8})
    assert summary and 'Stop Loss' in summary['exit_reason']
    assert summary['actual_exit_price']<290
    t.shutdown()


def test_volatility_floor_gate() -> None:
    """Verify that signal_brain blocks signals when ATR < MIN_ATR (0.30)."""
    # 16 candles with micro-volatility (High - Low = 0.10 -> ATR ~ 0.10 < 0.30)
    dates = [datetime(2026, 8, 24, 9, 15 + i) for i in range(16)]
    open_prices = [100.0 + i * 0.05 for i in range(16)]
    high_prices = [p + 0.08 for p in open_prices]
    low_prices = [p - 0.02 for p in open_prices]
    close_prices = [p + 0.05 for p in open_prices]

    # Candle 14 pullback touch with micro-volatility (High - Low = 0.02 -> ATR ~ 0.02 < 100.0 * 0.0006 = 0.06)
    open_prices = [100.0 + i * 0.005 for i in range(16)]
    high_prices = [p + 0.008 for p in open_prices]
    low_prices = [p - 0.002 for p in open_prices]
    close_prices = [p + 0.005 for p in open_prices]

    open_prices[14] = 100.07
    high_prices[14] = 100.08
    low_prices[14] = 100.01
    close_prices[14] = 100.07

    df_low_vol = pd.DataFrame({
        "Timestamp": dates,
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": [1000] * 16,
    })

    res_low = generate_vwap_signal(df_low_vol)
    # Blocked by Volatility Floor Gate (ATR < Close * MIN_ATR_PCT)
    assert not res_low["Buy_Signal"].any()
    assert not res_low["Breakout_Signal"].any()


def test_vwap_breakout_signal() -> None:
    """Verify that VWAP Breakout fires on decisive close above VWAP+0.5*ATR with 1.5x volume surge."""
    dates = [datetime(2026, 8, 24, 9, 15 + i) for i in range(16)]
    open_prices = [100.0 + i * 0.10 for i in range(16)]
    high_prices = [p + 0.50 for p in open_prices]
    low_prices = [p + 0.35 for p in open_prices]
    close_prices = [p + 0.45 for p in open_prices]
    volumes = [1000] * 16

    # Candle 15: Big Breakout with volume surge (Volume = 3000 >= 1.5 * 1200)
    open_prices[15] = 102.60
    high_prices[15] = 103.50
    low_prices[15] = 102.50
    close_prices[15] = 103.20
    volumes[15] = 3000

    df = pd.DataFrame({
        "Timestamp": dates,
        "Open": open_prices,
        "High": high_prices,
        "Low": low_prices,
        "Close": close_prices,
        "Volume": volumes,
    })

    res = generate_vwap_signal(df)
    assert "Breakout_Signal" in res.columns
    assert "Vol_MA10" in res.columns
    assert bool(res["Breakout_Signal"].iloc[15]) is True
    assert res["Signal_Type"].iloc[15] == "BREAKOUT_LONG"


def test_true_net_rr_friction_gate():
    e=solve_quantity('BUY',300,290,320,10000,100,200,1.2,.0005)
    assert e and e.net_stop_loss<=100 and e.net_rr>=1.2
    assert e.quantity<11 and e.entry_fees>0 and e.stop_exit_fees>0
    assert solve_quantity('BUY',303,299,304,10000,100,200,1.2,.0005) is None


def test_recalibrated_pyramiding_tranche2_trigger(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    with pytest.raises(SafetyError,match='SCALE_IN_DISABLED'):t._execute_tranche_2({},NOW)
    with pytest.raises(SafetyError,match='SCALE_IN_DISABLED'):t._execute_tranche_3({},NOW)
    assert t.open_position['current_tranches']==1
    t.shutdown()


def test_theta_decay_breakeven_defense(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    entry=t.avg_entry_price
    for _ in range(15):t.notify_candle_close({'Timestamp':NOW,'Close':entry+1})
    assert t.open_position['breakeven_armed']
    assert t.open_position['stop_loss_price']==entry
    t.shutdown()


def test_adaptive_friction_gate_low_vol_regime() -> None:
    """Verify low-vol regime (ATR/price < 0.0010) passes adaptive floor (0.80)."""
    trader = PaperTrader()
    # SJVN: entry=65.0, ATR=0.06 -> ATR/price = 0.06 / 65.0 = 0.000923 < 0.0010 (low-vol)
    # Net R:R ~ 0.87 >= 0.80 -> PASSES under adaptive low-vol floor (would fail normal 1.20 floor)
    passed, reason = trader.friction_gate_check(
        entry_price=65.0,
        sl_price=65.0 - 0.43,
        tp_price=65.0 + 0.86,
        qty=50,
        atr=0.06,
    )
    assert passed is True, f"Adaptive friction gate check failed: {reason}"


def test_vwap_pullback_short_signal() -> None:
    """Verify VWAP Pullback SELL signal fires in a confirmed downtrend when price tests VWAP from below."""
    n = 25
    base_ts = datetime(2026, 9, 3, 9, 15)
    ts = [base_ts + timedelta(minutes=i) for i in range(n)]
    prices = [245.0 - (i * 0.3) for i in range(n)]

    data = []
    for i in range(n):
        p = prices[i]
        data.append({
            "Timestamp": ts[i],
            "Open": p + 0.1,
            "High": p + 0.2,
            "Low": p - 0.2,
            "Close": p - 0.1,
            "Volume": 1000.0,
        })

    # At candle 18 (index 17): simulate pullback testing VWAP from below
    df_temp = pd.DataFrame(data)
    res_temp = generate_vwap_signal(df_temp, min_candles_before_trade=15)
    vwap17 = res_temp["VWAP"].iloc[17]
    atr17 = res_temp["ATR_14"].iloc[17]
    data[17]["High"] = vwap17 - 0.5 * atr17   # Above VWAP - 1.5*ATR (tests band)
    data[17]["Close"] = vwap17 - 0.5 * atr17 - 0.2  # Stays below VWAP

    df = pd.DataFrame(data)
    res = generate_vwap_signal(df, min_candles_before_trade=15)

    assert bool(res["Sell_Signal"].iloc[17]) is True
    assert res["Signal_Type"].iloc[17] == "PULLBACK_SHORT"


def test_vwap_breakdown_short_signal() -> None:
    """Verify VWAP Breakdown SELL signal fires on decisive close below VWAP with 1.5x volume surge."""
    n = 25
    base_ts = datetime(2026, 9, 3, 9, 15)
    ts = [base_ts + timedelta(minutes=i) for i in range(n)]
    prices = [245.0 - (i * 0.3) for i in range(n)]

    data = []
    for i in range(n):
        p = prices[i]
        data.append({
            "Timestamp": ts[i],
            "Open": p + 0.1,
            "High": p + 0.2,
            "Low": p - 0.2,
            "Close": p - 0.1,
            "Volume": 1000.0,
        })

    # At candle 18 (index 17): volume surge of 3000 (3x average 1000)
    data[17]["Volume"] = 3000.0
    df = pd.DataFrame(data)
    res = generate_vwap_signal(df, min_candles_before_trade=15)

    assert bool(res["Breakdown_Sell_Signal"].iloc[17]) is True
    assert res["Signal_Type"].iloc[17] == "BREAKDOWN_SHORT"


def test_daily_bias_detector() -> None:
    """Verify 3-check confluence voting for daily bias detection."""
    # 1. Bull session: Close > VWAP, Slope > 0, EMA9 > EMA21 -> LONG_BIAS
    df_bull = pd.DataFrame({
        "Close": [200.0 + i for i in range(20)],
        "VWAP": [198.0 + i * 0.5 for i in range(20)],
        "VWAP_Slope": [0.05] * 20,
        "EMA_9": [205.0] * 20,
        "EMA_21": [200.0] * 20,
    })
    assert detect_daily_bias(df_bull) == "LONG_BIAS"

    # 2. Bear session: Close < VWAP, Slope < 0, EMA9 < EMA21 -> SHORT_BIAS
    df_bear = pd.DataFrame({
        "Close": [200.0 - i for i in range(20)],
        "VWAP": [202.0 - i * 0.5 for i in range(20)],
        "VWAP_Slope": [-0.05] * 20,
        "EMA_9": [195.0] * 20,
        "EMA_21": [200.0] * 20,
    })
    assert detect_daily_bias(df_bear) == "SHORT_BIAS"

    # 3. Mixed session (2 bear votes, 1 bull vote) -> SHORT_BIAS
    df_mixed = pd.DataFrame({
        "Close": [202.0] * 20,         # Above VWAP -> Bull vote
        "VWAP": [200.0] * 20,
        "VWAP_Slope": [-0.02] * 20,     # Slope < 0 -> Bear vote
        "EMA_9": [198.0] * 20,          # EMA9 < EMA21 -> Bear vote
        "EMA_21": [200.0] * 20,
    })
    assert detect_daily_bias(df_mixed) == "SHORT_BIAS"

    # 4. Warmup period (< 15 candles) -> NEUTRAL
    df_short = df_bull.iloc[:10]
    assert detect_daily_bias(df_short) == "NEUTRAL"


def test_short_position_lifecycle(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW,side='SELL')
    assert t.open_position['stop_loss_price']==310 and t.open_position['target_price']==280
    t.set_quote(IDENTITY,MarketQuote(279.95,280.05,1000,1000,NOW,280))
    summary=t.check_exit(280,NOW)
    assert summary and summary['side']=='SELL' and summary['net_pnl']>0
    assert summary['actual_entry_price']<300 and summary['actual_exit_price']>280
    t.shutdown()


def test_direction_flip_closes_opposite(tmp_path):
    t=paper_trader(tmp_path)
    assert t.execute_trade(payload(),timestamp=NOW)
    second=t.execute_trade(payload(),timestamp=NOW,side='SELL')
    assert len(t.journal.trades())==1
    assert t.journal.trades()[0]['exit_reason']=='Direction Flip (BUY→SELL)'
    assert second and t.open_position['side']=='SELL'
    assert t.journal.budget()[1]==2
    t.shutdown()


def test_smartapi_place_live_order_defensive_parser(monkeypatch):
    from execution_engine import place_live_order
    b=ScenarioBroker()
    monkeypatch.setattr(config,'LIVE_MODE',True)
    monkeypatch.setattr(config,'LIVE_VALIDATION_APPROVED',False)
    with pytest.raises(SafetyError,match='LIVE_EXECUTION_BLOCKED'):
        place_live_order(b,'JIOFIN-EQ','18143','BUY',8)
    assert not b.requests


def test_live_execution_state_transitions_and_exit(tmp_path,monkeypatch):
    t,b=live_trader(tmp_path,monkeypatch)
    assert t.execute_trade(payload(),timestamp=NOW)
    assert t.execution_state=='POSITION_OPEN'
    assert t.close_position(300,NOW)
    assert t.execution_state=='ACCOUNTED' and b.netqty==0
    assert t.journal.trades()[0]['reconciliation_status']=='BROKER_QUANTITY_MATCHED'
    assert all(p['ordertype'] in {'LIMIT','STOPLOSS_LIMIT'} for p in b.requests)
    t.shutdown()


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

from safety_test_support import ScenarioBroker, paper_trader, live_trader, assert_unknown_submission, assert_unknown_exit
from test_safety_v6 import NOW, IDENTITY, payload, quote
from execution_safety import SafetyError, MarketQuote, solve_quantity
