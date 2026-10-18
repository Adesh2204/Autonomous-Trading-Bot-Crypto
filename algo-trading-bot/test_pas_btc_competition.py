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


def test_restarted_position_can_become_protected_only_after_reconciliation():
    from exchange.position_states import PositionState, PositionStateJournal
    class Journal:
        def control(self, key, value): pass
        def event(self, kind, ts, **data): pass
    machine = PositionStateJournal(Journal(), lambda: 2000, market="pas:BTC")
    with pytest.raises(Exception, match="POSITION_STATE_RECONCILIATION_REQUIRED"):
        machine.transition(PositionState.PROTECTED, "unverified")
    machine.transition(PositionState.PROTECTED, "position and stop verified", reconciled=True,
                       evidence={"protection_verified": True})
    machine.transition(PositionState.MANAGING, "manage", evidence={"protection_verified": True})
    assert machine.report()["state"] == "MANAGING"



def test_full_startup_resolves_runtime_api_coin_from_competition_dex_metadata():
    calls = []
    def transport(payload):
        calls.append(payload)
        query = payload["type"]
        if query == "perpDexs":
            return [None, {"name": "runtime-x", "competition_market": "pas", "fullName": "PAS"}]
        if query == "meta":
            assert payload["dex"] == "runtime-x"
            return {"universe": [
                {"name": "BTC", "szDecimals": 4, "maxLeverage": 20},
                {"name": "ETH", "szDecimals": 3, "maxLeverage": 10},
            ], "marginTables": [], "collateralToken": 7}
        if query == "spotMeta":
            return {"tokens": [{"index": 7, "name": "USDPR"}]}
        raise AssertionError("unexpected query: " + query)

    client = HyperliquidClient(transport=transport)
    client.startup()
    assert client.competition_market == "pas"
    assert client.api_dex == "runtime-x"
    assert client.api_market == "runtime-x:BTC"
    assert set(client.markets) == {"runtime-x:BTC"}
    assert all(payload.get("dex") != "par" for payload in calls)
    assert client.market_mapping["verification"] == "VERIFIED_FROM_LIVE_PERP_DEX_AND_MARKET_METADATA"


def test_startup_never_falls_back_to_par_when_pas_identity_is_missing():
    def transport(payload):
        if payload["type"] == "perpDexs":
            return [None, {"name": "par", "fullName": "Perpetual Alpha"}]
        raise AssertionError("metadata should not be requested for an unverified DEX")

    client = HyperliquidClient(transport=transport)
    with pytest.raises(VenueMismatch, match="PAS_DEX_MAPPING_UNVERIFIED"):
        client.startup()
    assert client.ready is False
    assert client.api_market is None


def test_production_profile_rejects_risk_ceiling_relaxation(tmp_path):
    import importlib.util
    import json
    from pathlib import Path

    runner_path = Path(__file__).resolve().parents[1] / "scripts" / "run_pas_btc.py"
    spec = importlib.util.spec_from_file_location("run_pas_btc_profile_test", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    profile_path = runner_path.parents[1] / "configs" / "pas_btc_production.example.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["risk"]["risk_fraction"] = "0.1"
    altered = tmp_path / "unsafe-profile.json"
    altered.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(Exception, match="PAS_BTC_RISK_CEILING_EXCEEDED:risk_fraction"):
        runner.load_profile(altered)


def test_snapshot_failure_latch_survives_a_process_restart():
    from types import SimpleNamespace
    from exchange.competition_market import SCORING_START_MS
    from exchange.competition_snapshot import CompetitionSnapshotRecorder

    class Journal:
        def __init__(self):
            self.values = {}
            self.events = []
        def control(self, key, value=None):
            if value is None:
                return self.values.get(key)
            self.values[key] = value
        def event(self, kind, ts, **data):
            self.events.append((kind, ts, data))

    class Session:
        def __init__(self):
            self.journal = Journal()
            self.execution = SimpleNamespace(entries_paused=False)
        def clock_ms(self):
            return SCORING_START_MS + 60 * 60 * 1000  # 13:00 UTC: snapshot was missed.

    session = Session()
    recorder = CompetitionSnapshotRecorder(session)
    first = recorder.observe()
    assert first["status"] == "SKIPPED"
    assert session.execution.entries_paused is True
    session.execution.entries_paused = False  # Simulate an incorrectly cleared latch.
    second = recorder.observe()
    assert second["status"] == "SKIPPED"
    assert session.execution.entries_paused is True
