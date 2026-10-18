"""Safety tests for the PAS-to-API discovery and BTC-only market registry."""
import pytest

from exchange.base_exchange import VenueMismatch
from exchange.competition_market import (
    canonical_api_market,
    resolve_collateral_token,
    is_scored_phase, SCORING_START_MS, SCORING_END_MS,
    resolve_competition_dex,
)
from exchange.hyperliquid_client import HyperliquidClient


def test_competition_key_can_map_to_runtime_api_alias():
    dex = [None, {"name": "pas", "fullName": "PAS"}]
    api_name, index, identity = resolve_competition_dex(dex)
    assert api_name == "pas"
    assert index == 1
    assert identity["fullName"] == "PAS"


def test_different_api_alias_requires_explicit_competition_metadata():
    dex = [None, {"name": "runtime-x", "competition_market": "pas"}]
    assert resolve_competition_dex(dex)[:2] == ("runtime-x", 1)


@pytest.mark.parametrize("dexes", [
    [],
    [None, {"name": "some-other-dex", "fullName": "unrelated"}],
    [None, {"name": "pas"}, {"name": "runtime-x", "competition_market": "pas"}],
    [None, {"name": "par", "fullName": "Perpetual Alpha"}],
])
def test_unverified_or_ambiguous_mapping_fails_closed(dexes):
    with pytest.raises(VenueMismatch, match="PAS_DEX_MAPPING_UNVERIFIED"):
        resolve_competition_dex(dexes)


def test_canonical_market_name_uses_discovered_api_alias():
    assert canonical_api_market("runtime-x", "BTC") == "runtime-x:BTC"
    assert canonical_api_market("runtime-x", "runtime-x:BTC") == "runtime-x:BTC"
    with pytest.raises(VenueMismatch, match="MARKET_METADATA_DEX_MISMATCH"):
        canonical_api_market("runtime-x", "par:BTC")


def test_collateral_token_name_is_resolved_from_runtime_spot_metadata():
    assert resolve_collateral_token(7, {"tokens": [
        {"index": 1, "name": "USDC"},
        {"index": 7, "name": "USDP"},
    ]}) == "USDP"
    with pytest.raises(VenueMismatch, match="PAS_COLLATERAL_MAPPING_UNVERIFIED"):
        resolve_collateral_token(7, {"tokens": [{"index": 7, "name": "USDP"},
                                                {"index": 7, "name": "USDP"}]})


def test_market_registry_exposes_only_btc_even_when_dex_lists_other_markets():
    client = HyperliquidClient(transport=lambda payload: {})
    client.api_dex = "pas"
    metadata = {
        "universe": [
            {"name": "BTC", "szDecimals": 4, "maxLeverage": 40},
            {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
            {"name": "HYPE", "szDecimals": 2, "maxLeverage": 10},
        ],
        "marginTables": [],
        "collateralToken": 7,
    }
    specs = client._parse_specs(metadata, 271)
    assert list(specs) == ["pas:BTC"]
    assert specs["pas:BTC"].asset_id == 2_810_000


def test_scored_phase_window_is_utc_half_open():
    assert not is_scored_phase(SCORING_START_MS - 1)
    assert is_scored_phase(SCORING_START_MS)
    assert is_scored_phase(SCORING_END_MS - 1)
    assert not is_scored_phase(SCORING_END_MS)


def test_position_state_requires_authoritative_reconciliation_before_live_state():
    from exchange.position_states import PositionState, PositionStateJournal
    class Journal:
        def __init__(self):
            self.controls = {}
            self.events = []
        def control(self, key, value):
            self.controls[key] = value
        def event(self, kind, ts, **data):
            self.events.append((kind, ts, data))
    journal = Journal()
    machine = PositionStateJournal(journal, lambda: 1000, market="pas:BTC")
    with pytest.raises(Exception, match="POSITION_STATE_RECONCILIATION_REQUIRED"):
        machine.transition(PositionState.FLAT, "not reconciled")
    machine.transition(PositionState.FLAT, "account read confirmed flat", reconciled=True)
    machine.transition(PositionState.SIGNAL_DETECTED, "signal")
    machine.transition(PositionState.ORDER_SUBMITTED, "order")
    machine.transition(PositionState.PARTIALLY_FILLED, "partial fill")
    machine.transition(PositionState.PROTECTION_PENDING, "protection pending")
    machine.transition(PositionState.PROTECTED, "stop verified")
    machine.transition(PositionState.MANAGING, "protected")
    assert machine.report()["state"] == "MANAGING"
    assert journal.events[-1][0] == "BTC_POSITION_STATE"
