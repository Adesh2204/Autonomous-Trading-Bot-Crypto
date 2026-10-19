"""Offline PAS discovery fixture regressions; no exchange transport or signing."""
import pytest

from exchange.base_exchange import VenueMismatch
from exchange.hyperliquid_client import HyperliquidClient
from test_exchange_migration import PasIdentityInfoFixture


def test_explicit_pas_fixture_discovers_exact_active_assets_and_usdp():
    fixture = PasIdentityInfoFixture()
    client = HyperliquidClient(fixture, venue='pas')

    client.startup()

    assert client.ready
    assert client.dex_identity == {
        'name': 'runtime-pas', 'competition_market': 'pas', 'fullName': 'PAS'
    }
    assert client.api_dex == 'runtime-pas'
    assert client.api_markets == {
        'BTC': 'runtime-pas:BTC', 'EWY': 'runtime-pas:EWY'
    }
    assert client.collateral_token_name == 'USDP'
    assert [call for call in fixture.calls if call['type'] == 'meta'] == [
        {'type': 'meta', 'dex': 'runtime-pas'}
    ]
    assert all(call.get('dex') != 'par' for call in fixture.calls)


@pytest.mark.parametrize(('damage', 'reason'), [
    ('ambiguous_dex', 'PAS_DEX_MAPPING_UNVERIFIED'),
    ('wrong_dex', 'PAS_DEX_MAPPING_UNVERIFIED'),
    ('wrong_coin_dex', 'MARKET_METADATA_DEX_MISMATCH'),
    ('missing_btc', 'PAS_ACTIVE_MARKET_MAPPING_UNVERIFIED'),
    ('missing_ewy', 'PAS_ACTIVE_MARKET_MAPPING_UNVERIFIED'),
    ('wrong_collateral', 'PAS_USDP_COLLATERAL_REQUIRED'),
])
def test_corrupt_pas_identity_fixture_fails_closed(damage, reason):
    fixture = PasIdentityInfoFixture(damage=damage)
    client = HyperliquidClient(fixture, venue='pas')

    with pytest.raises(VenueMismatch, match=reason):
        client.startup()

    assert not client.ready
    assert not client.markets
    assert all(call.get('dex') != 'par' for call in fixture.calls)
