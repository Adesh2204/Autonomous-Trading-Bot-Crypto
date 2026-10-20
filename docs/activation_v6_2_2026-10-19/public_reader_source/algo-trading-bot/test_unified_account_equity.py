"""Unified USDPR regression: synthetic public responses, no real credentials."""
from copy import deepcopy
from decimal import Decimal

import pytest

from exchange.base_exchange import ExchangeError, VenueMismatch
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_client import HyperliquidClient
from test_exchange_migration import PublicInfoFixture, TEAM
from test_live_exchange_execution import live
from exchange.order_lifecycle import OrderRequest


@pytest.fixture
def unified():
    transport = PublicInfoFixture()
    client = HyperliquidClient(transport, clock_ms=lambda: transport.now)
    client.startup()
    return transport, client, HyperliquidAccount(client, TEAM)


def test_funded_unified_account_uses_spot_even_with_zero_dex_summary(unified):
    fixture, _, account = unified
    fixture.state = dict(assetPositions=[], marginSummary=dict(accountValue='0', totalMarginUsed='0'),
                         withdrawable='0', crossMaintenanceMarginUsed='0')
    fixture.spot = dict(balances=[dict(coin='USDPR', token=20, total='1000000', hold='0')],
                        tokenToAvailableAfterMaintenance=[[20, '1000000']])
    equity = account.get_equity()
    assert equity.reported_account_value == equity.collateral_balance == Decimal('1000000')
    assert equity.margin_used == 0
    assert equity.withdrawable is None
    assert equity.valuation_source == 'spotClearinghouseState.USDPR.total'


def test_held_collateral_is_not_inferred_free_margin_or_withdrawable(unified):
    fixture, _, account = unified
    fixture.spot['balances'][0]['hold'] = '700'
    equity = account.get_equity()
    assert equity.collateral_balance == equity.reported_account_value == Decimal('1000')
    assert equity.margin_used == Decimal('10')  # Position margin, not spot holds.
    assert equity.withdrawable is None


def test_unified_equity_does_not_add_dex_summary_or_unrealized_pnl(unified):
    fixture, _, account = unified
    fixture.state['marginSummary'] = dict(accountValue='123456', totalMarginUsed='999')
    fixture.state['assetPositions'][0]['position']['unrealizedPnl'] = '450'
    second = deepcopy(fixture.state['assetPositions'][0])
    second['position'].update(coin='par:ETH', szi='-2', unrealizedPnl='-100', marginUsed='25')
    fixture.state['assetPositions'].append(second)
    equity = account.get_equity()
    assert equity.reported_account_value == Decimal('1000')
    assert equity.margin_used == Decimal('35')


def test_missing_usdpr_is_unfunded_and_other_tokens_are_not_collateral(unified):
    fixture, _, account = unified
    fixture.spot['balances'] = [dict(coin='USDC', token=0, total='1000000', hold='0')]
    assert account.get_equity().reported_account_value == 0


@pytest.mark.parametrize('token', [None, True, '20', 21])
def test_usdpr_token_must_match_runtime_metadata(unified, token):
    fixture, _, account = unified
    fixture.spot['balances'][0]['token'] = token
    with pytest.raises(ExchangeError, match='COLLATERAL_TOKEN_MISMATCH'):
        account.get_equity()


def test_duplicate_usdpr_is_ambiguous(unified):
    fixture, _, account = unified
    fixture.spot['balances'].append(deepcopy(fixture.spot['balances'][0]))
    with pytest.raises(ExchangeError, match='AMBIGUOUS_COLLATERAL_BALANCE'):
        account.get_equity()


def test_duplicate_token_under_other_name_is_not_accepted(unified):
    fixture, _, account = unified
    fixture.spot['balances'].append(dict(coin='OTHER', token=20, total='1000'))
    with pytest.raises(ExchangeError, match='COLLATERAL_TOKEN_MISMATCH'):
        account.get_equity()


def test_runtime_collateral_cannot_be_substituted_by_other_coin(unified):
    fixture, _, account = unified
    fixture.spot['balances'] = [dict(coin='USDC', token=20, total='1000')]
    with pytest.raises(ExchangeError, match='COLLATERAL_TOKEN_MISMATCH'):
        account.get_equity()


@pytest.mark.parametrize('amount', ['-1', 'NaN', 'Infinity'])
def test_invalid_reported_balance_fails_closed(unified, amount):
    fixture, _, account = unified
    fixture.spot['balances'][0]['total'] = amount
    with pytest.raises(ExchangeError, match='INVALID_DECIMAL'):
        account.get_equity()


def test_collateral_metadata_change_invalidates_client(unified):
    fixture, client, _ = unified
    metadata = deepcopy(fixture.metadata)
    metadata['collateralToken'] = 21
    with pytest.raises(VenueMismatch, match='PAR_METADATA_CHANGED_RESTART_REQUIRED'):
        client.validate_metadata(metadata)
    assert not client.ready


def test_readiness_accepts_funded_spot_with_zero_dex_value_without_unlocking(live):
    live.fixture.state['marginSummary']['accountValue'] = '0'
    live.fixture.spot['balances'][0]['total'] = '1000000'
    context = live.provider.load(OrderRequest('par:BTC', 'BUY', '.1', '100'))
    assert context.readiness.account_ready
    report = context.readiness.report(market_ready=True)
    assert report['collateral'] == '1000000'
    assert not report['live_ready'] and not report['live_orders_permitted']
    assert not live.transport.signed_payloads
