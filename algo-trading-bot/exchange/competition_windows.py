"""Published 2026 windows, not team registration or organizer exception proof.

Source: https://perpetual-alpha26.github.io/schedule (checked October 18).
The Oct17-18 gap has no verified exception. No automatic venue/session promotion.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .base_exchange import ExchangeError


def ms(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()*1000)


SCORED_START_MS=int(datetime(2026,10,19,12,tzinfo=timezone.utc).timestamp()*1000)
SCORED_END_MS=int(datetime(2026,11,6,12,tzinfo=timezone.utc).timestamp()*1000)
WINDOWS=((ms('2026-10-05T00:00:00'),ms('2026-10-17T00:00:00'),'PRACTICE'),
         (SCORED_START_MS,SCORED_END_MS,'SCORED'))


def require_published_window(starts_ms,expires_ms):
    # Scored bounds are explicitly UTC, including the final-day cutoff. A
    # finite session fitting them still grants no wallet or venue authority.
    if type(starts_ms) is not int or type(expires_ms) is not int or starts_ms>=expires_ms:
        raise ExchangeError('VALID_FINITE_TRADING_WINDOW_REQUIRED')
    for begin,end,phase in WINDOWS:
        if begin<=starts_ms<expires_ms<=end:return phase
    raise ExchangeError('ORGANIZER_TRADING_WINDOW_PERMISSION_NOT_VERIFIED')
