"""Explicit Oct17–18 practice contract; no authorization rolls to another day."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo
from .base_exchange import ExchangeError, decimal
from .bounded_daily_session import DailyMandate
from .long_session import LongMandate

IST=ZoneInfo('Asia/Calcutta')
PRACTICE_MAX_EXPIRY_MS=int(datetime(2026,10,18,23,57,tzinfo=IST).timestamp()*1000)
PRACTICE_MODE='EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1'
PRACTICE_ACKS=('overnight_counters_and_losses_never_reset',
    'risk_recovery_until_hard_expiry_only','midnight_position_and_stop_risk',
    'practice_oct17_18_no_automatic_renewal')


@dataclass(frozen=True)
class PracticeWeekendLimits(DailyMandate):
    session_loss_fraction: str='0.01'
    midnight_policy: str='CARRY_ALL_ATTEMPTS_ALLOCATION_PNL_PEAK_DRAWDOWN_NO_RESET'

    def require(self):
        self._require_scope()  # Keep original <=24h duration and all risk caps.
        start=datetime.fromtimestamp(self.starts_ms/1000,IST)
        end=datetime.fromtimestamp(self.expires_ms/1000,IST)
        if (start.date().isoformat()!='2026-10-17' or end.date().isoformat()!='2026-10-18'
                or self.expires_ms>PRACTICE_MAX_EXPIRY_MS or self.directions!=('LONG',)
                or decimal(self.bankroll)>20000
                or not 0<decimal(self.session_loss_fraction)==decimal(self.daily_loss_fraction)<=D('.01')
                or self.midnight_policy!='CARRY_ALL_ATTEMPTS_ALLOCATION_PNL_PEAK_DRAWDOWN_NO_RESET'):
            raise ExchangeError('INVALID_EXPLICIT_OCT17_18_PRACTICE_SCOPE')
        return self


@dataclass(frozen=True)
class PracticeWeekendLongMandate(LongMandate):
    entry_cutoff_buffer_ms: int=900000
    risk_close_buffer_ms: int=300000
    mode: str=PRACTICE_MODE

    def require_contract(self,d):
        if (type(d) is not PracticeWeekendLimits or self.mode!=PRACTICE_MODE
                or type(self.created_ms) is not int or type(self.approval_deadline_ms) is not int
                or datetime.fromtimestamp(self.created_ms/1000,IST).date().isoformat()!='2026-10-17'
                or datetime.fromtimestamp(self.approval_deadline_ms/1000,IST).date().isoformat()!='2026-10-17'
                or type(self.risk_close_buffer_ms) is not int or self.risk_close_buffer_ms!=300000
                or self.entry_cutoff_buffer_ms!=900000
                or self.approval_deadline_ms>=d.expires_ms-self.entry_cutoff_buffer_ms):
            raise ExchangeError('EXACT_PRACTICE_ENTRY_AND_MANAGEMENT_WINDOWS_REQUIRED')
