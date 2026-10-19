"""No-network regressions for the current PAS-only BTC/EWY engine registry."""
from types import SimpleNamespace

import pytest

from exchange.base_exchange import VenueMismatch
from exchange.competition_market import (
    COMPETITION_ACTIVE_BASE_ASSETS,
    COMPETITION_APPROVED_BASE_ASSETS,
    resolve_competition_dex,
)
from exchange.hyperliquid_client import HyperliquidClient, RequestsInfoTransport, TESTNET_API_URL
from exchange.sdk_transport import OfficialSDKTransport, _require_pas_market_mapping
from exchange.execution_safety import HumanLiveApproval, LiveAuthorization
from exchange.venue_profiles import SCORED, venue_profile


class MetadataFixture:
    def __init__(self, *, collateral="USDP", missing=(), alias="runtime-pas"):
        self.alias = alias
        self.collateral = collateral
        self.missing = set(missing)
        self.calls = []

    def __call__(self, payload):
        self.calls.append(dict(payload))
        query = payload["type"]
        if query == "perpDexs":
            return [None, {"name": self.alias, "competition_market": "pas"}]
        if query == "meta":
            assert payload["dex"] == self.alias
            universe = [
                {"name": "BTC", "szDecimals": 4, "maxLeverage": 20},
                {"name": "ETH", "szDecimals": 3, "maxLeverage": 10},
                {"name": "EWY", "szDecimals": 2, "maxLeverage": 8},
                {"name": "HYPE", "szDecimals": 2, "maxLeverage": 5},
            ]
            return {"universe": [row for row in universe if row["name"] not in self.missing],
                    "marginTables": [], "collateralToken": 7}
        if query == "spotMeta":
            return {"tokens": [{"index": 7, "name": self.collateral}]}
        if query == "l2Book":
            return {"coin": payload["coin"], "levels": [[], []]}
        raise AssertionError(f"unexpected offline fixture query: {query}")


def ready_client(*, collateral="USDP", missing=(), alias="runtime-pas"):
    source = MetadataFixture(collateral=collateral, missing=missing, alias=alias)
    client = HyperliquidClient(source)
    client.startup()
    return source, client


def test_active_set_is_exact_subset_of_approved_pas_universe():
    assert COMPETITION_ACTIVE_BASE_ASSETS == ("BTC", "EWY")
    assert set(COMPETITION_ACTIVE_BASE_ASSETS) <= set(COMPETITION_APPROVED_BASE_ASSETS)
    assert SCORED.markets == {"pas:BTC", "pas:EWY"}
    assert venue_profile().dex == "pas"


def test_startup_resolves_both_active_coins_dynamically_and_keeps_btc_accessor():
    source, client = ready_client()
    assert set(client.markets) == {"runtime-pas:BTC", "runtime-pas:EWY"}
    assert client.api_markets == {"BTC": "runtime-pas:BTC", "EWY": "runtime-pas:EWY"}
    assert client.api_market == client.api_markets["BTC"]
    assert client.market_mapping["api_markets"] == client.api_markets
    assert client.collateral_token_name == "USDP"
    assert all("par" not in str(call.get("dex", "")) for call in source.calls)
    assert client.market_mapping["verification"] == "VERIFIED_FROM_LIVE_PERP_DEX_AND_MARKET_METADATA"


def test_public_coin_boundary_accepts_only_the_two_verified_active_markets():
    _, client = ready_client()
    for symbol in ("runtime-pas:BTC", "runtime-pas:EWY"):
        assert client.post_info("l2Book", coin=symbol)["coin"] == symbol
    for symbol in ("runtime-pas:ETH", "par:BTC", "BTC"):
        with pytest.raises(VenueMismatch, match="PAS_ACTIVE_MARKET_REQUIRED"):
            client.post_info("l2Book", coin=symbol)


@pytest.mark.parametrize("missing", [{"BTC"}, {"EWY"}])
def test_startup_fails_closed_if_either_active_instrument_is_unverified(missing):
    client = HyperliquidClient(MetadataFixture(missing=missing))
    with pytest.raises(VenueMismatch, match="PAS_ACTIVE_MARKET_MAPPING_UNVERIFIED"):
        client.startup()
    assert not client.ready and not client.markets and client.api_market is None


def test_runtime_collateral_must_resolve_to_usdp():
    client = HyperliquidClient(MetadataFixture(collateral="USDPR"))
    with pytest.raises(VenueMismatch, match="PAS_USDP_COLLATERAL_REQUIRED"):
        client.startup()
    assert not client.ready


def test_retired_par_alias_cannot_be_relabelled_as_pas():
    with pytest.raises(VenueMismatch, match="PAS_DEX_MAPPING_UNVERIFIED"):
        resolve_competition_dex([None, {"name": "par", "competition_market": "pas"}])


def test_legacy_par_is_offline_only_and_cannot_use_real_requests_transport():
    with pytest.raises(VenueMismatch, match="PRODUCTION_PAS_ONLY"):
        HyperliquidClient(venue="par")
    fixture_client = HyperliquidClient(lambda payload: {}, venue="par")
    assert fixture_client.legacy_offline_read_only is True
    assert fixture_client.competition_mode is False


def test_explicit_offline_par_fixture_can_still_read_historical_universe():
    from exchange.hyperliquid_client import EXPECTED_MARKETS
    class Fixture:
        def __call__(self, payload):
            if payload["type"] == "perpDexs":
                return [None, {"name": "par"}]
            if payload["type"] == "meta":
                return {"universe": [
                    {"name": symbol, "szDecimals": 3, "maxLeverage": 10}
                    for symbol in sorted(EXPECTED_MARKETS)],
                    "marginTables": [], "collateralToken": 20}
            raise AssertionError(payload)
    client = HyperliquidClient(Fixture(), venue="par")
    assert set(client.startup()) == set(EXPECTED_MARKETS)
    assert client.legacy_offline_read_only is True
    with pytest.raises(Exception, match="SIGNED_VENUE"):
        OfficialSDKTransport._require_venue(client, LiveAuthorization())


def test_sdk_gate_requires_testnet_verified_active_map_and_pas_authorizer():
    _, client = ready_client()
    assert client.base_url == TESTNET_API_URL
    assert _require_pas_market_mapping(client) == client.api_markets
    invalid = LiveAuthorization(HumanLiveApproval("", "0x" + "1" * 40,
        "0x" + "2" * 40, 999999999999))
    with pytest.raises(Exception, match="SIGNED_VENUE"):
        OfficialSDKTransport._require_venue(client, invalid)
    approval = HumanLiveApproval("offline fixture only", "0x" + "1" * 40,
        "0x" + "2" * 40, 999999999999, competition_market="pas",
        active_base_assets=("BTC", "EWY"), network="testnet")
    authorization = LiveAuthorization(approval)
    # No HTTP occurs in this policy test; the concrete type is checked without
    # constructing a session or invoking its request method.
    client.transport = object.__new__(RequestsInfoTransport)
    assert OfficialSDKTransport._require_venue(client, authorization) is True

    client.api_markets = {"BTC": "runtime-pas:BTC"}
    with pytest.raises(Exception, match="SIGNED_VENUE_PAS_VERIFIED_MAPPING_REQUIRED"):
        _require_pas_market_mapping(client)
