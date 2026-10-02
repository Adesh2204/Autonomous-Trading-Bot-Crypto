"""Exchange-reported USDPR payments. Public funding rates are different data."""
from dataclasses import dataclass

from .base_exchange import ExchangeError, decimal


@dataclass(frozen=True)
class AccountFunding:
    symbol: str
    timestamp_ms: int
    event_hash: str
    cashflow: object
    position_quantity: object
    funding_rate: object
    collateral: str='USDPR'
    source: str='EXCHANGE_REPORTED_USER_FUNDING'

    def __post_init__(self):
        if (not isinstance(self.symbol,str) or not self.symbol.startswith('par:') or
                type(self.timestamp_ms) is not int or self.timestamp_ms<0 or
                not isinstance(self.event_hash,str) or not self.event_hash or self.collateral!='USDPR'):
            raise ExchangeError('INVALID_ACCOUNT_FUNDING')
        for name in ('cashflow','position_quantity','funding_rate'):
            object.__setattr__(self,name,decimal(getattr(self,name)))

    @property
    def identity(self):
        return self.symbol,self.timestamp_ms,self.event_hash
