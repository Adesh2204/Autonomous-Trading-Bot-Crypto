"""
market_schedule.py - Pluggable Market Schedule Provider Engine.

VERSION UPDATE (2026-08-27): Refactored into a Strategy / Provider pattern
using Python's abc (Abstract Base Class) module. Decouples the execution
pipeline from Indian market hours and enables multi-exchange execution
(NSE, NYSE, NASDAQ, 24/7 Crypto) with 100% backward compatibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
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


ClockValue = Union[datetime, time]


class MarketPhase(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    ACTIVE_TRADING = "ACTIVE_TRADING"
    CLOSE_ONLY = "CLOSE_ONLY"
    SQUARE_OFF = "SQUARE_OFF"
    CLOSED = "CLOSED"


# ────────────────────────────────────────────────────────────────────────
#  ABSTRACT BASE SCHEDULE PROVIDER (ABC)
# ────────────────────────────────────────────────────────────────────────

class BaseMarketSchedule(ABC):
    """
    Abstract Base Class defining the contract for exchange market schedules.
    """

    @property
    @abstractmethod
    def timezone(self) -> ZoneInfo:
        """Return the exchange's native ZoneInfo timezone."""
        pass

    @property
    @abstractmethod
    def market_open_time(self) -> time:
        """Return regular market open wall-clock time."""
        pass

    @property
    @abstractmethod
    def entry_cutoff_time(self) -> time:
        """Return latest time for initiating new trade entries."""
        pass

    @property
    @abstractmethod
    def eod_square_off_time(self) -> time:
        """Return mandatory EOD auto-square-off cutoff time."""
        pass

    @property
    @abstractmethod
    def market_close_time(self) -> time:
        """Return regular market close wall-clock time."""
        pass

    @abstractmethod
    def is_trading_day(self, current_date: date) -> bool:
        """Return True if exchange is open for trading on current_date."""
        pass

    @abstractmethod
    def holiday_name(self, current_date: date) -> Optional[str]:
        """Return holiday label if the market is closed on current_date."""
        pass

    def localize(self, value: Optional[datetime] = None) -> datetime:
        """
        Convert or attach the exchange's native timezone to datetime.
        Naive datetimes are assumed to be in local exchange wall-clock time.
        """
        if value is None:
            return datetime.now(tz=self.timezone)
        if value.tzinfo is None:
            return value.replace(tzinfo=self.timezone)
        return value.astimezone(self.timezone)

    def is_market_open(self, dt: Optional[datetime] = None) -> bool:
        """Return True if timestamp is within active regular trading hours."""
        loc_dt = self.localize(dt)
        if not self.is_trading_day(loc_dt.date()):
            return False
        t = loc_dt.time()
        return self.market_open_time <= t < self.market_close_time

    def is_eod_square_off(self, dt: Optional[datetime] = None) -> bool:
        """Return True if timestamp has reached or passed the EOD square-off threshold."""
        loc_dt = self.localize(dt)
        if not self.is_trading_day(loc_dt.date()):
            return False
        t = loc_dt.time()
        return t >= self.eod_square_off_time

    def get_market_open_time(self, dt: Optional[datetime] = None) -> datetime:
        """Return localized session open datetime for the target date."""
        loc_dt = self.localize(dt)
        return datetime.combine(loc_dt.date(), self.market_open_time, tzinfo=self.timezone)

    def get_eod_square_off_time(self, dt: Optional[datetime] = None) -> datetime:
        """Return localized session EOD auto-square-off datetime for target date."""
        loc_dt = self.localize(dt)
        return datetime.combine(loc_dt.date(), self.eod_square_off_time, tzinfo=self.timezone)

    def get_market_state(self, current_time: ClockValue) -> MarketPhase:
        """
        Resolve the current market phase.
        A datetime input also validates the trading date against exchange calendars.
        """
        if isinstance(current_time, datetime):
            loc_dt = self.localize(current_time)
            if not self.is_trading_day(loc_dt.date()):
                return MarketPhase.CLOSED
            market_time = loc_dt.time()
        else:
            market_time = current_time

        if market_time < self.market_open_time:
            return MarketPhase.PRE_MARKET
        if market_time < self.entry_cutoff_time:
            return MarketPhase.ACTIVE_TRADING
        if market_time < self.eod_square_off_time:
            return MarketPhase.CLOSE_ONLY
        if market_time < self.market_close_time:
            return MarketPhase.SQUARE_OFF
        return MarketPhase.CLOSED

    def can_enter_new_positions(self, current_time: ClockValue) -> bool:
        """Return True only during active trading window before entry cutoff."""
        return self.get_market_state(current_time) == MarketPhase.ACTIVE_TRADING

    def seconds_until_market_start(self, current_dt: Optional[datetime] = None) -> float:
        """
        Return seconds until next market open, skipping holidays and weekends.
        """
        loc_now = self.localize(current_dt)
        check_date = loc_now.date()

        while True:
            open_dt = datetime.combine(check_date, self.market_open_time, tzinfo=self.timezone)
            if self.is_trading_day(check_date) and open_dt > loc_now:
                return (open_dt - loc_now).total_seconds()
            check_date += timedelta(days=1)


# ────────────────────────────────────────────────────────────────────────
#  CONCRETE PROVIDERS
# ────────────────────────────────────────────────────────────────────────

class NSEMarketSchedule(BaseMarketSchedule):
    """
    National Stock Exchange of India (NSE) / BSE Market Schedule Provider.
    Timezone: Asia/Kolkata (IST)
    Trading Hours: 09:15 - 15:30 IST
    Entry Cutoff: 15:15 IST
    EOD Auto-Square-Off: 15:20 IST
    """

    def __init__(self, calendar_name: str = "BSE") -> None:
        self._tz = ZoneInfo("Asia/Kolkata")
        self._calendar = mcal.get_calendar(calendar_name) if mcal is not None else None

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    @property
    def market_open_time(self) -> time:
        return time(9, 15, 0)

    @property
    def entry_cutoff_time(self) -> time:
        return time(15, 15, 0)

    @property
    def eod_square_off_time(self) -> time:
        return time(15, 20, 0)

    @property
    def market_close_time(self) -> time:
        return time(15, 30, 0)

    def is_trading_day(self, current_date: date) -> bool:
        if self._calendar is not None:
            schedule = self._calendar.schedule(
                start_date=current_date,
                end_date=current_date,
            )
            if not schedule.empty:
                return True

        if holidays is not None:
            india_financial = holidays.financial_holidays("IND")
            if current_date.weekday() >= 5:
                return False
            return current_date not in india_financial

        return current_date.weekday() < 5

    def holiday_name(self, current_date: date) -> Optional[str]:
        if self.is_trading_day(current_date):
            return None
        if current_date.weekday() >= 5:
            return "Weekend"
        if holidays is None:
            return "Exchange Closed"
        india_financial = holidays.financial_holidays("IND")
        return india_financial.get(current_date, "Exchange Closed")


class NYSEMarketSchedule(BaseMarketSchedule):
    """
    New York Stock Exchange (NYSE / NASDAQ) Market Schedule Provider.
    Timezone: America/New_York (EST/EDT)
    Trading Hours: 09:30 - 16:00 EST
    Entry Cutoff: 15:30 EST
    EOD Auto-Square-Off: 15:45 EST
    """

    def __init__(self, calendar_name: str = "NYSE") -> None:
        self._tz = ZoneInfo("America/New_York")
        self._calendar = mcal.get_calendar(calendar_name) if mcal is not None else None

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    @property
    def market_open_time(self) -> time:
        return time(9, 30, 0)

    @property
    def entry_cutoff_time(self) -> time:
        return time(15, 30, 0)

    @property
    def eod_square_off_time(self) -> time:
        return time(15, 45, 0)

    @property
    def market_close_time(self) -> time:
        return time(16, 0, 0)

    def is_trading_day(self, current_date: date) -> bool:
        if self._calendar is not None:
            schedule = self._calendar.schedule(
                start_date=current_date,
                end_date=current_date,
            )
            if not schedule.empty:
                return True

        if holidays is not None:
            us_holidays = holidays.US()
            if current_date.weekday() >= 5:
                return False
            return current_date not in us_holidays

        return current_date.weekday() < 5

    def holiday_name(self, current_date: date) -> Optional[str]:
        if self.is_trading_day(current_date):
            return None
        if current_date.weekday() >= 5:
            return "Weekend"
        if holidays is None:
            return "Exchange Closed"
        us_holidays = holidays.US()
        return us_holidays.get(current_date, "Exchange Closed")


class Crypto247MarketSchedule(BaseMarketSchedule):
    """
    24/7 Cryptocurrency Market Schedule Provider.
    Timezone: UTC
    Trading Hours: Continuous 24/7 (Never Closed)
    """

    def __init__(self) -> None:
        self._tz = ZoneInfo("UTC")

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    @property
    def market_open_time(self) -> time:
        return time(0, 0, 0)

    @property
    def entry_cutoff_time(self) -> time:
        return time(23, 59, 59)

    @property
    def eod_square_off_time(self) -> time:
        return time(23, 59, 59)

    @property
    def market_close_time(self) -> time:
        return time(23, 59, 59)

    def is_trading_day(self, current_date: date) -> bool:
        return True

    def holiday_name(self, current_date: date) -> Optional[str]:
        return None

    def is_market_open(self, dt: Optional[datetime] = None) -> bool:
        return True

    def is_eod_square_off(self, dt: Optional[datetime] = None) -> bool:
        return False

    def get_market_state(self, current_time: ClockValue) -> MarketPhase:
        return MarketPhase.ACTIVE_TRADING


# ────────────────────────────────────────────────────────────────────────
#  FACTORY FUNCTION
# ────────────────────────────────────────────────────────────────────────

def get_market_schedule(market_name: str = "NSE") -> BaseMarketSchedule:
    """
    Factory function resolving configured BaseMarketSchedule provider.
    """
    market = (market_name or "NSE").upper()
    if market in ("NSE", "BSE", "INDIA", "IND"):
        return NSEMarketSchedule()
    elif market in ("NYSE", "NASDAQ", "US"):
        return NYSEMarketSchedule()
    elif market in ("CRYPTO", "247", "24/7"):
        return Crypto247MarketSchedule()
    else:
        raise ValueError(f"Unsupported market schedule: {market_name}")


# ────────────────────────────────────────────────────────────────────────
#  BACKWARD COMPATIBILITY ALIASES & DEFAULT CONSTANTS
# ────────────────────────────────────────────────────────────────────────

IST = ZoneInfo("Asia/Kolkata")
MARKET_START = time(9, 15, 0)
ENTRY_CUTOFF = time(15, 15, 0)
AUTO_SQUARE_OFF = time(15, 20, 0)
MARKET_CLOSE = time(15, 30, 0)

_DEFAULT_SCHEDULE = NSEMarketSchedule()


def to_ist(value: Optional[datetime] = None) -> datetime:
    """Return timezone-aware datetime in native IST."""
    return _DEFAULT_SCHEDULE.localize(value)


def is_trading_day(current_date: date) -> bool:
    """Return True if BSE/NSE has a valid trading session on current_date."""
    return _DEFAULT_SCHEDULE.is_trading_day(current_date)


def holiday_name(current_date: date) -> Optional[str]:
    """Return holiday label if closed on a weekday."""
    return _DEFAULT_SCHEDULE.holiday_name(current_date)


def get_market_state(current_time: ClockValue) -> MarketPhase:
    """Resolve current market phase for NSE."""
    return _DEFAULT_SCHEDULE.get_market_state(current_time)


def can_enter_new_positions(current_time: ClockValue) -> bool:
    """Return True only during active trading entry window."""
    return _DEFAULT_SCHEDULE.can_enter_new_positions(current_time)


def seconds_until_market_start(current_dt: Optional[datetime] = None) -> float:
    """Return seconds until next NSE market open."""
    return _DEFAULT_SCHEDULE.seconds_until_market_start(current_dt)

