"""Fail-closed exchange-write boundary for Anchorium's Perpetual Alpha clone.

Paper ledger events are local simulations, not exchange orders. Phase 0 has no
implemented exchange transport: even an accidental opt-in cannot submit orders.
Angel One execution remains forbidden when future testnet routing is added.
"""
import os

import venue_config as config
from safety_errors import SafetyError


class OrderRoutingBlocked(SafetyError):
    """An exchange mutation was rejected before contacting its transport."""


def require_exchange_orders(venue, *, client=None):
    """Check each write boundary. Credentials and LIVE_MODE grant no access.

    client identifies the transport for offline protocol tests; production policy
    never treats a supplied client as authorization.
    """
    if venue != "HYPERLIQUID_TESTNET":
        raise OrderRoutingBlocked("ANGEL_ONE_EXECUTION_DISABLED" if venue == "ANGEL_ONE"
                                  else "UNSUPPORTED_TRADING_VENUE")
    if config.TRADING_VENUE != "HYPERLIQUID_TESTNET":
        raise OrderRoutingBlocked("UNSUPPORTED_TRADING_VENUE")
    if config.ALLOW_LIVE_ORDERS is not True:
        raise OrderRoutingBlocked("ALLOW_LIVE_ORDERS_FALSE")
    # A runtime environment override can revoke permission after config import.
    if ("ALLOW_LIVE_ORDERS" in os.environ
            and os.environ["ALLOW_LIVE_ORDERS"].strip().lower() != "true"):
        raise OrderRoutingBlocked("ALLOW_LIVE_ORDERS_FALSE")
    runtime_mode = os.environ.get('EXECUTION_MODE', config.EXECUTION_MODE).strip().upper()
    if config.EXECUTION_MODE == 'PAPER' or runtime_mode == 'PAPER':
        raise OrderRoutingBlocked('PAPER_MODE_EXCHANGE_ORDERS_BLOCKED')
    if config.EXECUTION_MODE != 'HYPERLIQUID' or runtime_mode != 'HYPERLIQUID':
        raise OrderRoutingBlocked('UNSUPPORTED_EXECUTION_MODE')
    raise OrderRoutingBlocked("HYPERLIQUID_TESTNET_EXECUTION_NOT_IMPLEMENTED")
