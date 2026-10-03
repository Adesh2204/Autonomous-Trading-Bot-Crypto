"""Explicit future-session assembly; no key creation, approval, funding or activation."""
from pathlib import Path
import os

from .base_exchange import ExchangeError
from .execution_journal import ExecutionJournal
from .execution_safety import (NonceManager,ClockHealthMonitor,HyperliquidRateLimitManager,
                               LiveAuthorization,HumanLiveApproval)
from .hyperliquid_client import HyperliquidClient
from .hyperliquid_account import HyperliquidAccount
from .hyperliquid_market_data import HyperliquidMarketData
from .live_recovery import LiveAccountRecovery
from .exchange_rules import LiveContextProvider,HyperliquidOrderValidator
from .hyperliquid_execution import HyperliquidExecution
from .sdk_transport import OfficialSDKTransport
from .live_account_stream import LiveAccountStream
from .perpetual_economics import FeeSchedule


class LiveRuntime:
    def __init__(self,session,authorization,transport,nonces,journal,public_transport):
        self.session=session
        self.authorization=authorization
        self.transport=transport
        self.nonces=nonces
        self.journal=journal
        self.public_transport=public_transport

    def deactivate(self):
        self.authorization.revoke()
        self.session.execution.entries_paused=True
        self.session.recovery.revoke('HUMAN_LIVE_AUTHORIZATION_REVOKED')
        if self.session.account_stream is not None:
            self.session.account_stream.disconnect('HUMAN_LIVE_AUTHORIZATION_REVOKED')

    def close(self):
        self.deactivate()
        self.transport.close()
        self.nonces.close()
        self.journal.close()
        self.public_transport.close()


def build_live_runtime(*,team_address,approval,session_id,initial_start_ms,risk_policy,
                       scanner_policy,state_directory,fee_scale_verified=None):
    """Called only in a separately authorized future testnet activation.

    PAPER/false stops before reading a key or opening an exchange client.
    The team key is never accepted. Account administration stays outside this API.
    fee_scale_verified is a manually verified venue fee-scale observation, not a
    profitability setting. It must currently equal the venue's published scale 1.
    """
    from eth_account import Account
    from market_regime_scanner import MarketRegimeScanner
    from risk.portfolio_risk import PortfolioRisk
    from live_execution_session import LiveExecutionSession
    from strategy_freeze import verify_strategy_freeze
    verify_strategy_freeze()
    if not isinstance(approval,HumanLiveApproval):
        raise ExchangeError('EXPLICIT_FUTURE_MANUAL_APPROVAL_REQUIRED')
    authorization=LiveAuthorization(approval)
    authorization.require(team_address,approval.signer_address)
    if fee_scale_verified!=1:
        raise ExchangeError('VENUE_FEE_SCALE_REVERIFICATION_REQUIRED')
    key=os.environ.get('API_WALLET_PRIVATE_KEY')
    if not key:
        raise ExchangeError('API_WALLET_SIGNER_REQUIRED')
    try:
        signer=Account.from_key(key)
    except Exception:
        raise ExchangeError('INVALID_API_WALLET_SIGNER') from None
    finally:
        key=None
    if signer.address.lower()!=approval.signer_address.lower():
        raise ExchangeError('APPROVED_API_WALLET_IDENTITY_MISMATCH')
    root=Path(state_directory)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    journal=ExecutionJournal(root/'account.sqlite',session_id=session_id,team_address=team_address)
    nonces=None
    transport=None
    client=None
    try:
        nonces=NonceManager(root/'nonces.sqlite',signer.address)
        rates=HyperliquidRateLimitManager(journal)
        client=HyperliquidClient(rate_limits=rates)
        client.startup()
        account=HyperliquidAccount(client,team_address)
        market=HyperliquidMarketData(client)
        clock=ClockHealthMonitor()
        recovery=LiveAccountRecovery(account,journal,initial_start_ms=initial_start_ms)
        holder={}
        provider=LiveContextProvider(market,account,signer.address,clock,rates,
            reconciliation_ready=lambda:recovery.last_report.ready,
            feed_ready=lambda:bool(holder.get('stream') and holder['stream'].healthy),
            policy_leverage=risk_policy.leverage)
        transport=OfficialSDKTransport(client,signer,team_address,nonces,authorization,rate_limits=rates)
        executor=HyperliquidExecution(client,transport=transport,account=account,journal=journal,
            context_provider=provider,validator=HyperliquidOrderValidator(client,policy_leverage=risk_policy.leverage),
            recovery=recovery,clock_health=clock,rate_limits=rates)
        base_fees=account._query('userFees')
        multiplier=1+fee_scale_verified
        from .base_exchange import decimal
        fees=FeeSchedule(decimal(base_fees['userAddRate'],nonnegative=True)*multiplier,
                         decimal(base_fees['userCrossRate'],nonnegative=True)*multiplier,
                         'VERIFIED_PAR_DEPLOYER_SCALE_1_TIMES_REPORTED_USER_BASE_RATES')
        session=LiveExecutionSession(market,MarketRegimeScanner(market,scanner_policy),executor,
                                     PortfolioRisk(risk_policy,fees))
        stream=LiveAccountStream(team_address,recovery,executor,clock_ms=client.clock_ms)
        holder['stream']=stream
        session.attach_account_stream(stream)
        session.startup()
        return LiveRuntime(session,authorization,transport,nonces,journal,client.transport)
    except Exception as exc:
        if transport is not None:
            transport.close()
        if nonces is not None:
            nonces.close()
        journal.close()
        if client is not None:
            client.transport.close()
        raise ExchangeError('LIVE_RUNTIME_SETUP_FAILED:'+type(exc).__name__) from None
