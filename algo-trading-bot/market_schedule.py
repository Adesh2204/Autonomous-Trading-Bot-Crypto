"""
market_schedule.py - NSE session and lifecycle rules.

VERSION UPDATE (2026-08-25): Replaced legacy hardcoded holiday snapshots with
dynamic exchange-calendar resolution to prevent fabricated date regressions.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional, Union
from zoneinfo import ZoneInfo

try:
    import pandas_market_calendars as mcal
except ImportError:  # Optional in constrained environments.
    mcal = None

try:
    import holidays
except ImportError:  # Optional fallback when exchange calendar package is missing.
    holidays = None


IST = ZoneInfo("Asia/Kolkata")

MARKET_START = time(9, 15, 0)
ENTRY_CUTOFF = time(15, 15, 0)
AUTO_SQUARE_OFF = time(15, 20, 0)
MARKET_CLOSE = time(15, 30, 0)


class MarketPhase(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    ACTIVE_TRADING = "ACTIVE_TRADING"
    CLOSE_ONLY = "CLOSE_ONLY"
    SQUARE_OFF = "SQUARE_OFF"
    CLOSED = "CLOSED"


_BSE_CALENDAR = mcal.get_calendar("BSE") if mcal is not None else None


ClockValue = Union[datetime, time]


def to_ist(value: Optional[datetime] = None) -> datetime:
    """Return a timezone-aware IST datetime.

    Naive datetimes are assumed to already be wall-clock IST values. Do not pass
    a naive UTC timestamp here without converting it first.
    """
    if value is None:
        return datetime.now(tz=IST)
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def is_trading_day(current_date: date) -> bool:
    """Return True if BSE/NSE has a valid trading session on current_date."""
    if _BSE_CALENDAR is not None:
        schedule = _BSE_CALENDAR.schedule(
            start_date=current_date,
            end_date=current_date,
        )
        if not schedule.empty:
            return True

    # Fallback path: weekend or India financial holiday indicates closure.
    if holidays is not None:
        india_financial = holidays.financial_holidays("IND")
        if current_date.weekday() >= 5:
            return False
        return current_date not in india_financial

    return False


def holiday_name(current_date: date) -> Optional[str]:
    """Return a holiday label when the market is closed on a business day."""
    if is_trading_day(current_date):
        return None
    if current_date.weekday() >= 5:
        return "Weekend"
    if holidays is None:
        return "Exchange Closed"
    india_financial = holidays.financial_holidays("IND")
    return india_financial.get(current_date, "Exchange Closed")


def get_market_state(current_time: ClockValue) -> MarketPhase:
    """
    Resolve the current market phase.

    A datetime input also validates the trading date. A bare time input is
    treated as a trading-day time and is useful for unit tests.
    """
    if isinstance(current_time, datetime):
        current_dt = to_ist(current_time)
        if not is_trading_day(current_dt.date()):
            return MarketPhase.CLOSED
        market_time = current_dt.time()
    else:
        market_time = current_time

    if market_time < MARKET_START:
        return MarketPhase.PRE_MARKET
    if market_time < ENTRY_CUTOFF:
        return MarketPhase.ACTIVE_TRADING
    if market_time < AUTO_SQUARE_OFF:
        return MarketPhase.CLOSE_ONLY
    if market_time < MARKET_CLOSE:
        return MarketPhase.SQUARE_OFF
    return MarketPhase.CLOSED


def can_enter_new_positions(current_time: ClockValue) -> bool:
    """Return True only during the normal intraday entry window."""
    return get_market_state(current_time) == MarketPhase.ACTIVE_TRADING


def seconds_until_market_start(current_dt: Optional[datetime] = None) -> float:
    """Return seconds until the next actual NSE cash-market open.

    The function skips weekends, NSE holidays, and any session that has already
    started so callers can safely sleep until the next valid trading open.
    """
    ist_now = to_ist(current_dt)
    check_date = ist_now.date()

    while True:
        open_dt = datetime.combine(check_date, MARKET_START, tzinfo=IST)
        if is_trading_day(check_date) and open_dt > ist_now:
            return (open_dt - ist_now).total_seconds()
        check_date += timedelta(days=1)
