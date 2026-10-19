"""Explicit Oct 16–17 contract. Observation can outlive this finite capability."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo
from .base_exchange import ExchangeError,decimal
from .bounded_daily_session import DailyMandate
from .long_session import LongMandate

IST=ZoneInfo('Asia/Calcutta')
OVERNIGHT_MAX_EXPIRY_MS=1792218600000  # 17 October 2026 12:00 IST
OVERNIGHT_ACKS=('overnight_counters_and_losses_never_reset',
    'risk_recovery_until_hard_expiry_only','midnight_position_and_stop_risk')


@dataclass(frozen=True)
class OvernightLimits(DailyMandate):
    session_loss_fraction: str='0.01'
    midnight_policy: str='CARRY_ALL_ATTEMPTS_ALLOCATION_PNL_PEAK_DRAWDOWN_NO_RESET'

    def require(self):
        self._require_scope()
        start=datetime.fromtimestamp(self.starts_ms/1000,IST)
        end=datetime.fromtimestamp(self.expires_ms/1000,IST)
        if (start.date().isoformat()!='2026-10-16' or end.date().isoformat()!='2026-10-17'
                or self.expires_ms>OVERNIGHT_MAX_EXPIRY_MS or self.expires_ms-self.starts_ms>18*3600000
                or self.directions!=('LONG',) or decimal(self.bankroll)>20000
                or not 0<decimal(self.session_loss_fraction)==decimal(self.daily_loss_fraction)<=D('.01')
                or self.midnight_policy!='CARRY_ALL_ATTEMPTS_ALLOCATION_PNL_PEAK_DRAWDOWN_NO_RESET'):
            raise ExchangeError('INVALID_EXPLICIT_OCT16_17_OVERNIGHT_SCOPE')
        return self


@dataclass(frozen=True)
class OvernightLongMandate(LongMandate):
    entry_cutoff_buffer_ms: int=900000
    risk_close_buffer_ms: int=300000
    mode: str='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1'

    def require_contract(self,d):
        if (type(d) is not OvernightLimits or self.mode!='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1'
                or type(self.created_ms) is not int or type(self.approval_deadline_ms) is not int
                or datetime.fromtimestamp(self.created_ms/1000,IST).date().isoformat()!='2026-10-16'
                or type(self.risk_close_buffer_ms) is not int or self.risk_close_buffer_ms!=300000
                or self.entry_cutoff_buffer_ms!=900000
                or self.approval_deadline_ms>=d.expires_ms-self.entry_cutoff_buffer_ms):
            raise ExchangeError('EXACT_OVERNIGHT_ENTRY_AND_MANAGEMENT_WINDOWS_REQUIRED')
