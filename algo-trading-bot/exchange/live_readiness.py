"""Read-only funded-account verification. It never approves an agent or activates trading."""
from dataclasses import dataclass, asdict
import re

from .base_exchange import ExchangeError, decimal
from .execution_journal import safe_reason
from .competition_market import PAS_TARGET_LEVERAGE


def valid_address(value):
    return (isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{40}', value) is not None
            and int(value[2:], 16) != 0)


def require_pas_cross_1x(account):
    """Require fresh per-market 1x CROSS readbacks; this grants no write authority."""
    client = account.client
    api_markets = getattr(client, 'api_markets', None)
    api_dex = getattr(client, 'api_dex', None)
    if (not isinstance(api_markets, dict) or set(api_markets) != {'BTC', 'EWY'} or
            not isinstance(api_dex, str) or
            any(api_markets.get(base) != f'{api_dex}:{base}' for base in ('BTC', 'EWY')) or
            getattr(client, 'api_market', None) != api_markets.get('BTC')):
        raise ExchangeError('PAS_ACTIVE_ASSET_MAPPING_UNVERIFIED')
    observed = {}
    for base in ('BTC', 'EWY'):
        symbol = api_markets[base]
        try:
            active = account._query('activeAssetData', coin=symbol)
        except Exception as exc:
            raise ExchangeError('PAS_ACTIVE_ASSET_READBACK_UNAVAILABLE') from exc
        leverage = active.get('leverage') if isinstance(active, dict) else None
        user = active.get('user') if isinstance(active, dict) else None
        if (not isinstance(user, str) or user.lower() != account.team_address.lower()
                or active.get('coin') != symbol or not isinstance(leverage, dict)
                or leverage.get('type') != 'cross' or type(leverage.get('value')) is not int
                or leverage.get('value') != PAS_TARGET_LEVERAGE):
            raise ExchangeError('PAS_ACTIVE_ASSET_CROSS_1X_REQUIRED')
        observed[symbol] = dict(leverage)
    return observed


@dataclass(frozen=True)
class LiveReadiness:
    status: str
    reasons: tuple
    team_address: str | None
    signer_address: str | None
    observed_ms: int
    agent_expiry_ms: int | None = None
    collateral: str | None = None
    account_mode: str | None = None
    fees: dict | None = None
    account_budget: dict | None = None
    reconciliation_ready: bool = False
    clock_healthy: bool = False
    rate_limits_healthy: bool = False
    signed_transport_implemented: bool = True
    competition_market: str = 'pas'
    api_dex: str | None = None
    api_market: str | None = None
    collateral_token_name: str | None = None

    @property
    def account_ready(self):
        return self.status == 'READY'

    def report(self, *, market_ready, execution=None):
        live_permitted = False
        if execution is not None and self.account_ready and market_ready:
            try:
                from .sdk_transport import OfficialSDKTransport
                transport=execution.transport
                execution._dependencies()
                execution._require()
                now=execution.client.clock_ms()
                live_permitted = (type(transport) is OfficialSDKTransport and
                    transport.team_address.lower()==self.team_address.lower() and
                    transport.signer_address.lower()==self.signer_address.lower() and
                    transport._sdk.wallet.address.lower()==self.signer_address.lower() and
                    transport.nonces.healthy and execution.client.ready and
                    not execution.entries_paused and execution.recovery.last_report.ready and
                    execution.context_provider.feed_ready() and execution.clock_health.healthy and
                    execution.rate_limits.entries_allowed and
                    execution.protection is not None and execution.protection.entries_allowed and
                    0<=now-self.observed_ms<=5000 and
                    self.agent_expiry_ms is not None and self.agent_expiry_ms>now)
            except Exception:
                pass
        result = asdict(self)
        result.update(network='testnet', competition_market=self.competition_market,
                      dex=self.api_dex, api_market=self.api_market,
                      collateral=self.collateral_token_name, market_data_ready=bool(market_ready),
                      target_leverage=PAS_TARGET_LEVERAGE, margin_mode='cross',
                      paper_ready=bool(market_ready), live_orders_permitted=bool(live_permitted),
                      controlled_execution_certified=False,
                      live_ready=False,
                      final_status=('LIVE_TECHNICALLY_READY_CERTIFICATION_REQUIRED' if self.account_ready and live_permitted else
                                    'LIVE_TECHNICALLY_READY_BUT_LOCKED' if self.account_ready else
                                    'ACCOUNT_SETUP_REQUIRED'))
        return result


def verify_live_account_readiness(account, signer_address, *, clock_health, rate_limits,
                                  reconciliation_ready=False,critical=False):
    client = account.client
    now = client.clock_ms()
    reasons = []
    expiry = collateral = mode = fees = budget = None
    if client.competition_mode:
        api_markets = getattr(client, 'api_markets', None)
        if (client.api_dex is None or not isinstance(api_markets, dict) or
                set(api_markets) != {'BTC', 'EWY'} or
                api_markets.get('BTC') != client.api_market or
                any(not isinstance(symbol, str) or not symbol.endswith(':'+base)
                    for base, symbol in api_markets.items()) or
                set(client.markets) != set(api_markets.values())):
            reasons.append('PAS_ASSET_MAPPING_UNVERIFIED')
    if not valid_address(account.team_address) or not valid_address(signer_address):
        reasons.append('TEAM_AND_API_WALLET_REQUIRED')
    elif account.team_address.lower() == signer_address.lower():
        reasons.append('SEPARATE_API_WALLET_REQUIRED')
    if not client.ready or client.metadata_timestamp_ms is None or not 0 <= now-client.metadata_timestamp_ms <= 60000:
        reasons.append('MARKET_METADATA_NOT_READY')
    if reasons:
        return LiveReadiness('NOT_READY', tuple(reasons), account.team_address,
                             signer_address, now, api_dex=client.api_dex, api_market=client.api_market,
                             collateral_token_name=client.collateral_token_name)
    try:
        mode = account._query('userAbstraction')
        if mode != 'unifiedAccount':
            reasons.append('UNIFIED_ACCOUNT_REQUIRED')
        agents = account._query('extraAgents')
        if not isinstance(agents, list):
            raise ExchangeError('INVALID_API_WALLET_APPROVALS')
        matches = [a for a in agents if isinstance(a, dict) and isinstance(a.get('address'),str)
                   and a['address'].lower() == signer_address.lower()]
        lifecycle_key='api_wallet_lifecycle:'+signer_address.lower()
        lifecycle_row=rate_limits.journal.db.execute('SELECT value FROM controls WHERE name=?',(lifecycle_key,)).fetchone()
        lifecycle=lifecycle_row[0] if lifecycle_row else None
        if lifecycle=='RETIRED':
            reasons.append('API_WALLET_RETIRED_REQUIRES_FRESH_KEY')
        if len(matches) != 1:
            reasons.append('API_WALLET_NOT_APPROVED')
            if lifecycle=='VERIFIED':
                with rate_limits.journal.transaction():
                    rate_limits.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(lifecycle_key,'RETIRED'))
        else:
            expiry = matches[0].get('validUntil')
            if type(expiry) is not int or expiry <= client.clock_ms():
                reasons.append('API_WALLET_EXPIRED')
                lifecycle='RETIRED'
            elif lifecycle!='RETIRED':
                lifecycle='VERIFIED'
            with rate_limits.journal.transaction():
                rate_limits.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(lifecycle_key,lifecycle))
        if mode == 'unifiedAccount':
            eq = account.get_equity()
            collateral = str(eq.collateral_balance)
            if eq.collateral_balance <= 0 or eq.reported_account_value <= 0:
                reasons.append('ACCOUNT_NOT_FUNDED')
        if client.competition_mode and not critical:
            # Readiness is a market-wide statement: inspect both active PAS
            # markets before entry, not only the requested symbol. Preserve
            # existing critical reduce-only/cancel recovery; those actions
            # still require every identity, approval and exact-action check.
            try:
                require_pas_cross_1x(account)
            except ExchangeError as exc:
                if str(exc) not in {'PAS_ACTIVE_ASSET_CROSS_1X_REQUIRED',
                                    'PAS_ACTIVE_ASSET_READBACK_UNAVAILABLE',
                                    'PAS_ACTIVE_ASSET_MAPPING_UNVERIFIED'}:
                    raise
                reasons.append(str(exc))
        fees = account._query('userFees')
        if not isinstance(fees,dict):
            raise ExchangeError('USER_FEES_UNAVAILABLE')
        for name in ('userCrossRate','userAddRate'):
            decimal(fees[name], nonnegative=True)
        budget = account._query('userRateLimit')
        rate_limits.observe_info('userRateLimit', budget)
        orders = account.get_open_orders()
        rate_limits.observe_info('openOrders', orders)
        account.get_positions()
        if not reconciliation_ready:
            reasons.append('ACCOUNT_RECONCILIATION_REQUIRED')
        if not clock_health.healthy:
            reasons.append('CLOCK_HEALTH_REQUIRED')
        if not (rate_limits.safety_ready if critical else rate_limits.healthy):
            reasons.append('RATE_LIMIT_STATE_UNHEALTHY')
    except Exception as exc:
        reasons.append('ACCOUNT_QUERY_FAILED:' + safe_reason(type(exc).__name__))
    return LiveReadiness('NOT_READY' if reasons else 'READY', tuple(reasons),
                         account.team_address, signer_address, client.clock_ms(), expiry,
                         collateral, mode, fees, budget, bool(reconciliation_ready),
                         clock_health.healthy, rate_limits.safety_ready if critical else rate_limits.healthy,
                         competition_market='pas', api_dex=client.api_dex, api_market=client.api_market,
                         collateral_token_name=client.collateral_token_name)
