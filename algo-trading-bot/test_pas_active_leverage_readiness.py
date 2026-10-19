"""Read-only PAS account readiness regressions; synthetic transport only."""
import sqlite3
from types import SimpleNamespace

import pytest

from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_client import HyperliquidClient
from exchange.live_readiness import verify_live_account_readiness
from test_exchange_migration import NOW, TEAM
from test_pas_migration import PasFixture

SIGNER = '0x' + '2' * 40


class AccountFixture(PasFixture):
    def __init__(self):
        super().__init__()
        self.orders = []
        self.active_leverages = {'pas:BTC': 1, 'pas:EWY': 1}
        self.agents = [dict(address=SIGNER, validUntil=NOW + 86_400_000)]
        self.fees = dict(userCrossRate='.00045', userAddRate='.00015')
        self.budget = dict(nRequestsUsed=0, nRequestsCap=10000)

    def __call__(self, payload):
        query = payload['type']
        if query == 'activeAssetData':
            self.calls.append(dict(payload))
            symbol = payload['coin']
            return dict(user=TEAM, coin=symbol,
                        leverage=dict(type='cross', value=self.active_leverages[symbol]),
                        maxTradeSzs=['10', '10'], availableToTrade=['100000', '100000'])
        if query in {'extraAgents', 'userFees', 'userRateLimit'}:
            self.calls.append(dict(payload))
            return {'extraAgents': self.agents, 'userFees': self.fees,
                    'userRateLimit': self.budget}[query]
        return super().__call__(payload)


class RateState:
    def __init__(self):
        self.journal = self
        self.db = sqlite3.connect(':memory:')
        self.db.execute('create table controls (name text primary key, value text)')
        self.healthy = True
        self.safety_ready = True

    def observe_info(self, *_args):
        pass

    def transaction(self):
        return self.db


@pytest.fixture
def pas_account():
    fixture = AccountFixture()
    client = HyperliquidClient(fixture, clock_ms=lambda: fixture.now, venue='pas')
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    yield fixture, client, account


def readiness(account):
    rates = RateState()
    try:
        return verify_live_account_readiness(
            account, SIGNER, clock_health=SimpleNamespace(healthy=True),
            rate_limits=rates, reconciliation_ready=True)
    finally:
        rates.db.close()


@pytest.mark.parametrize('symbol', ['pas:BTC', 'pas:EWY'])
def test_pas_readiness_requires_cross_1x_for_both_markets(pas_account, symbol):
    fixture, _, account = pas_account
    fixture.active_leverages[symbol] = 20
    result = readiness(account)
    assert not result.account_ready
    assert 'PAS_ACTIVE_ASSET_CROSS_1X_REQUIRED' in result.reasons
    assert not result.report(market_ready=True)['live_orders_permitted']
    assert not fixture.calls or all(call['type'] != 'exchange' for call in fixture.calls)


def test_pas_readiness_accepts_verified_cross_1x_for_both_markets(pas_account):
    fixture, _, account = pas_account
    result = readiness(account)
    assert result.account_ready
    assert not result.report(market_ready=True)['live_orders_permitted']
    assert all(any(row.get('coin') == symbol for row in fixture.calls
                   if row['type'] == 'activeAssetData') for symbol in ('pas:BTC', 'pas:EWY'))


def test_entry_leverage_gate_does_not_disable_existing_critical_reduce_only_recovery(pas_account):
    fixture, _, account = pas_account
    fixture.active_leverages = {'pas:BTC': 20, 'pas:EWY': 20}
    rates = RateState()
    try:
        result = verify_live_account_readiness(
            account, SIGNER, clock_health=SimpleNamespace(healthy=True),
            rate_limits=rates, reconciliation_ready=True, critical=True)
    finally:
        rates.db.close()
    assert result.account_ready
    assert not result.report(market_ready=True)['live_orders_permitted']
    assert not any(row['type'] == 'activeAssetData' for row in fixture.calls)
    assert not readiness(account).account_ready


@pytest.mark.parametrize('damage', ['null', 'user', 'coin', 'isolated', 'bool', 'missing', 'unavailable'])
def test_pas_readiness_rejects_invalid_active_leverage_observations(pas_account, monkeypatch, damage):
    from exchange.base_exchange import ExchangeError
    _, _, account = pas_account
    query = account._query
    def damaged_query(name, **parameters):
        value = query(name, **parameters)
        if name != 'activeAssetData' or parameters['coin'] != 'pas:EWY':
            return value
        if damage == 'null':
            return None
        if damage == 'unavailable':
            raise ExchangeError('OFFLINE_READ_UNAVAILABLE')
        if damage == 'user':
            value['user'] = None
        elif damage == 'coin':
            value['coin'] = 'par:EWY'
        elif damage == 'isolated':
            value['leverage']['type'] = 'isolated'
        elif damage == 'bool':
            value['leverage']['value'] = True
        elif damage == 'missing':
            value.pop('leverage')
        return value
    monkeypatch.setattr(account, '_query', damaged_query)
    result = readiness(account)
    assert not result.account_ready
    assert not result.report(market_ready=True)['live_orders_permitted']


def test_unified_account_equity_uses_runtime_usdp_token_3307_not_usdpr():
    fixture = PasFixture()
    fixture.metadata['collateralToken'] = 3307
    fixture.tokens = [dict(name='USDP', index=3307), dict(name='USDPR', index=3032)]
    fixture.spot['balances'] = [
        dict(coin='USDP', token=3307, total='100000.0', hold='0.0'),
        dict(coin='USDPR', token=3032, total='1000000.050512', hold='0.0'),
    ]
    client = HyperliquidClient(fixture, clock_ms=lambda: fixture.now, venue='pas')
    client.startup()
    equity = HyperliquidAccount(client, TEAM).get_equity()
    assert client.collateral_token_id == 3307
    assert equity.collateral_balance == equity.reported_account_value == 100000
    assert equity.valuation_source == 'spotClearinghouseState.USDP.total'
