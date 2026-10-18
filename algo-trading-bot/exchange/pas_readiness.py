"""Unsigned PAS venue/account evidence; none of these observations grant authority."""
from .base_exchange import ExchangeError, decimal


def require_pas_market_status(client):
    if getattr(client,'dex',None)!='pas' or not client.ready:
        raise ExchangeError('VERIFIED_PAS_DISCOVERY_REQUIRED')
    status=client.post_info('exchangeStatus')
    if not isinstance(status,dict) or 'specialStatuses' not in status:
        raise ExchangeError('EXCHANGE_STATUS_SCHEMA_UNVERIFIED')
    if status['specialStatuses'] not in (None,[],{}):
        raise ExchangeError('EXCHANGE_SPECIAL_STATUS_REQUIRES_REVIEW')
    details=client.post_info('perpDexStatus')
    if not isinstance(details,dict) or 'totalNetDeposit' not in details:
        raise ExchangeError('PAS_DEX_STATUS_SCHEMA_UNVERIFIED')
    decimal(details['totalNetDeposit'],nonnegative=True)
    return dict(exchange=status,dex_status=details,observed_ms=client.clock_ms(),
        limitation='perpDexStatus reports deposits, not a market-open flag; phase permission, metadata and executable books are independent gates')
