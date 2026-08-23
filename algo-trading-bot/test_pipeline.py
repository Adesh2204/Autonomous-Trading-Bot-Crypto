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


SYMBOL = "DEMO-2500"
START_PRICE = 2500.00
STARTING_CAPITAL = 10_000.0
WORKING_CAPITAL_LIMIT = STARTING_CAPITAL * 0.50
DAILY_LOSS_LIMIT = STARTING_CAPITAL * 0.02
ENTRY_RISK_LIMIT = STARTING_CAPITAL * 0.01


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
            high_price=2504.50,
            low_price=2499.80,
            close_price=2503.90,
            volume=1200,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 1 - Candle 2",
            open_price=2503.90,
            high_price=2509.00,
            low_price=2503.40,
            close_price=2508.10,
            volume=1350,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 1 - Candle 3",
            open_price=2508.10,
            high_price=2514.50,
            low_price=2507.90,
            close_price=2513.60,
            volume=1450,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 1 - Candle 4",
            open_price=2513.60,
            high_price=2521.20,
            low_price=2513.20,
            close_price=2520.40,
            volume=1550,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 2 - Pullback Entry Candle",
            open_price=2520.40,
            high_price=2522.00,
            low_price=2512.80,
            close_price=2518.90,
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
            low_price=2498.20,
            close_price=2499.20,
            volume=1900,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3B - Aftermath",
            open_price=2499.20,
            high_price=2500.40,
            low_price=2495.80,
            close_price=2497.50,
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
            high_price=2527.00,
            low_price=2520.60,
            close_price=2524.60,
            volume=1450,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 3",
            open_price=2524.60,
            high_price=2529.00,
            low_price=2522.70,
            close_price=2526.10,
            volume=1400,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 4",
            open_price=2526.10,
            high_price=2531.20,
            low_price=2524.20,
            close_price=2528.40,
            volume=1350,
            pattern="open_low_high_close",
        ),
        CandleSpec(
            label="Phase 3C - Controlled Hold 5",
            open_price=2528.40,
            high_price=2532.00,
            low_price=2523.80,
            close_price=2525.00,
            volume=1300,
            pattern="open_high_low_close",
        ),
        CandleSpec(
            label="Phase 3C - Into Square-Off",
            open_price=2525.00,
            high_price=2530.50,
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
            daily_loss_limit_pct=0.02,
            risk_per_trade_pct=0.01,
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

        if bool(latest["Buy_Signal"]) and not self.trade_taken:
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
            if ticket is None:
                raise AssertionError(
                    f"{self.scenario_name}: buy signal was emitted but execute_trade() returned None"
                )

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
