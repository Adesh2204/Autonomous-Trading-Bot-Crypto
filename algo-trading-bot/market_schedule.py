"""
market_schedule.py - NSE session and lifecycle rules.

This module is intentionally dependency-free so live trading and offline
simulation can use the same clock rules. Holiday dates are static snapshots
from the NSE trading holiday calendar for the equity/capital market segment.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional, Union
from zoneinfo import ZoneInfo


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


# NSE CM/Equity holidays for calendar year 2026.
# Source checked from NSE's trading holiday endpoint on 2026-08-23:
# https://www.nseindia.com/api/holiday-master?type=trading
NSE_HOLIDAYS = {
    2026: {
        date(2026, 1, 26): "Republic Day",
        date(2026, 2, 15): "Mahashivratri",
        date(2026, 3, 3): "Holi",
        date(2026, 3, 21): "Id-Ul-Fitr (Ramadan Eid)",
        date(2026, 3, 26): "Shri Ram Navami",
        date(2026, 3, 31): "Shri Mahavir Jayanti",
        date(2026, 4, 3): "Good Friday",
        date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
        date(2026, 5, 1): "Maharashtra Day",
        date(2026, 5, 28): "Bakri Id",
        date(2026, 6, 26): "Muharram",
        date(2026, 8, 15): "Independence Day",
        date(2026, 9, 14): "Ganesh Chaturthi",
        date(2026, 10, 2): "Mahatma Gandhi Jayanti",
        date(2026, 10, 20): "Dussehra",
        date(2026, 11, 8): "Diwali Laxmi Pujan",
        date(2026, 11, 10): "Diwali-Balipratipada",
        date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
        date(2026, 12, 25): "Christmas",
    },
}


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
    """Return True when the date is a weekday and not an NSE holiday."""
    if current_date.weekday() >= 5:
        return False
    return current_date not in NSE_HOLIDAYS.get(current_date.year, {})


def holiday_name(current_date: date) -> Optional[str]:
    """Return the NSE holiday name for a date, if one is configured."""
    return NSE_HOLIDAYS.get(current_date.year, {}).get(current_date)


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

