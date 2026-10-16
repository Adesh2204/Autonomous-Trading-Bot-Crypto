"""Public-address presence is not verified funding or trading authorization."""
import re


def readiness(address=None, *, market_ready=False):
    present=isinstance(address,str) and bool(re.fullmatch(r'0x[0-9a-fA-F]{40}',address)) and int(address[2:],16)!=0
    return dict(account_status='CONFIGURED_UNVERIFIED' if present else 'NOT_CONFIGURED',
        wallet_ready=False,public_address_configured=bool(present),
        market_data_ready=bool(market_ready),paper_trading_ready=bool(market_ready),
        live_execution_ready=False,signed_actions='DISABLED',
        reason='Manual funded-wallet verification and explicit future authorization required')
