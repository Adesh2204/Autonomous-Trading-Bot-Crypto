"""Published 2026 windows, not team registration or organizer exception proof.

Source: https://perpetual-alpha26.github.io/schedule (checked October 17).
The Oct17-18 gap has no verified exception. No automatic venue/session promotion.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from .base_exchange import ExchangeError


def ms(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()*1000)


WINDOWS=((ms('2026-10-05T00:00:00'),ms('2026-10-17T00:00:00'),'PRACTICE'),
         (ms('2026-10-19T00:00:00'),ms('2026-11-07T00:00:00'),'SCORED'))


def require_published_window(starts_ms,expires_ms):
    # Dates are published without an exact timezone/cutoff; requiring the
    # finite operator window to fit these dates grants no time or venue right.
    if type(starts_ms) is not int or type(expires_ms) is not int or starts_ms>=expires_ms:
        raise ExchangeError('VALID_FINITE_TRADING_WINDOW_REQUIRED')
    for begin,end,phase in WINDOWS:
        if begin<=starts_ms<expires_ms<=end:return phase
    raise ExchangeError('ORGANIZER_TRADING_WINDOW_PERMISSION_NOT_VERIFIED')
