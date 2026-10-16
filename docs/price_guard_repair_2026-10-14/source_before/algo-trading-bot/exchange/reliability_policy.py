"""Venue limits and operational reserves; no strategy parameters."""
from dataclasses import dataclass
from enum import Enum, IntEnum
from .base_exchange import ExchangeError


class RequestPriority(IntEnum):
    SAFETY=0
    EXECUTION=1
    DECISION=2
    OPTIONAL=3


class RateState(str,Enum):
    HEALTHY='HEALTHY'
    CAUTION='CAUTION'
    THROTTLED='THROTTLED'
    EXHAUSTED='EXHAUSTED'
    UNKNOWN='UNKNOWN'


class ClockState(str,Enum):
    HEALTHY='HEALTHY'
    WARNING='WARNING'
    UNSAFE='UNSAFE'


@dataclass(frozen=True)
class HyperliquidRatePolicy:
    ip_weight_per_minute: int=1200
    ip_safety_reserve: int=120
    daily_actions: int=50000
    daily_safety_reserve: int=500
    account_action_reserve: int=10
    max_open_orders: int=1000
    max_ws_connections: int=10
    max_ws_subscriptions: int=1000
    max_ws_unique_users: int=10
    venue_ws_connections_per_minute: int=30
    max_ws_messages_per_minute: int=2000
    ws_reconnects_per_minute: int=5
    budget_max_age_ms: int=60000
    optional_poll_interval_ms: int=5000
    read_retry_attempts: int=3
    backoff_base_ms: int=1000
    backoff_max_ms: int=30000
    exhausted_safety_action_interval_ms: int=10000
    caution_fraction: float=.75
    throttle_fraction: float=.9

    def __post_init__(self):
        for name,value in self.__dict__.items():
            if name.endswith('fraction'):
                if not isinstance(value,(int,float)) or not 0<value<1:
                    raise ExchangeError('INVALID_RATE_POLICY')
            elif type(value) is not int or value<1:
                raise ExchangeError('INVALID_RATE_POLICY')
        if (self.ip_safety_reserve>=self.ip_weight_per_minute or
                self.daily_safety_reserve>=self.daily_actions or self.caution_fraction>=self.throttle_fraction or
                self.ws_reconnects_per_minute>self.venue_ws_connections_per_minute):
            raise ExchangeError('INVALID_RATE_RESERVE_POLICY')


def load_reliability_policy(path):
    """Public, explicit configuration; loading it never authorizes exchange writes."""
    import json
    from pathlib import Path
    from .position_protection import ProtectionPolicy
    try:
        value=json.loads(Path(path).read_text())
        if set(value)!={'rate_limits','clock','protection'}:
            raise ValueError
        rates=HyperliquidRatePolicy(**value['rate_limits'])
        clock=value['clock']
        if set(clock)!={'max_skew_ms','max_age_ms'} or any(type(x) is not int or x<1 for x in clock.values()):
            raise ValueError
        protection=ProtectionPolicy(**value['protection'])
        if type(protection.enabled) is not bool:
            raise ValueError
        if protection.enabled:
            protection.require()
        return rates,dict(clock),protection
    except (KeyError,TypeError,ValueError):
        raise ExchangeError('INVALID_RELIABILITY_POLICY_FILE') from None
