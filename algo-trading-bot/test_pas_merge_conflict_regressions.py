"""Merged PAS conflict regressions: unsigned planning, controller gates, and session provenance."""
from copy import deepcopy
from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest

from exchange.base_exchange import ExchangeError
from exchange.entry_scope import PAS_ENTRY_MARKETS
from exchange.pas_configuration_plan import configuration_plan
from exchange.testnet_certification import TEAM
from exchange.venue_profiles import SCORED
from test_scored_opening_release import configuration_observation


@pytest.mark.parametrize("registration", [None, {}, {"status": "UNREVIEWED_ORGANIZER_RECORD"},
                                           {"status": "OPERATOR_REVIEWED_ORGANIZER_RECORD "}])
def test_configuration_plan_retains_registration_blocker_without_exact_review(registration):
    observation = configuration_observation()
    if registration is not None:
        observation["registration_evidence"] = registration
    before = deepcopy(observation)

    plan = configuration_plan(observation)

    assert observation == before
    assert "REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED" in plan["blockers"]
    assert plan["signing_authority"] == "NONE"
    assert plan["signatures_created"] == plan["exchange_writes"] == 0
    assert plan["entry_markets"] == sorted(PAS_ENTRY_MARKETS) == ["pas:BTC", "pas:EWY"]
    assert {change["symbol"] for change in plan["changes"]} == PAS_ENTRY_MARKETS
    assert all(change["requested_action"]["type"] == "updateLeverage"
               and change["requested_action"]["isCross"] is True
               and change["requested_action"]["leverage"] == 1
               for change in plan["changes"])


def test_configuration_plan_drops_registration_blocker_only_for_exact_review_status():
    observation = configuration_observation()
    observation["registration_evidence"] = {
        "team_wallet": TEAM,
        "status": "OPERATOR_REVIEWED_ORGANIZER_RECORD",
        "record_sha256": "a" * 64,
        "original_record_sha256": "b" * 64,
    }
    before = deepcopy(observation)

    plan = configuration_plan(observation)

    assert observation == before
    assert "REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED" not in plan["blockers"]
    assert plan["entry_markets"] == sorted(PAS_ENTRY_MARKETS)
    assert {change["symbol"] for change in plan["changes"]} == PAS_ENTRY_MARKETS
    assert all(change["requested_action"]["leverage"] == 1
               and change["requested_action"]["isCross"] is True
               for change in plan["changes"])
    assert plan["signing_authority"] == "NONE"
    assert plan["signatures_created"] == plan["exchange_writes"] == 0


def test_configuration_plan_recognizes_only_exact_one_cross_for_both_entries():
    observation = configuration_observation()
    for row in observation["markets"]:
        row["active_asset"]["leverage"] = {"type": "cross", "value": 1}
    before = deepcopy(observation)

    plan = configuration_plan(observation)

    assert observation == before
    assert plan["changes"] == []
    assert plan["already_target_cross"] == sorted(PAS_ENTRY_MARKETS)
    assert plan["entry_markets"] == sorted(PAS_ENTRY_MARKETS)
    assert plan["signing_authority"] == "NONE"
    assert plan["signatures_created"] == plan["exchange_writes"] == 0


@pytest.mark.parametrize("damage", ["missing", "twenty_x", "isolated", "stale", "boolean_one"])
def test_btc_only_selection_still_requires_fresh_exact_one_cross_on_both_assets(damage):
    from exchange.pas_controller import assess
    from test_activation_v5_2 import NOW, ready_report

    report = ready_report()
    report["markets"] = ["pas:BTC"]
    if damage == "missing":
        del report["liquidity"]["pas:EWY"]
    elif damage == "twenty_x":
        report["liquidity"]["pas:EWY"]["active_asset"]["leverage"]["value"] = 20
    elif damage == "isolated":
        report["liquidity"]["pas:EWY"]["active_asset"]["leverage"]["type"] = "isolated"
    elif damage == "stale":
        report["liquidity"]["pas:EWY"]["active_asset_ms"] = NOW - 360001
    else:
        report["liquidity"]["pas:EWY"]["active_asset"]["leverage"]["value"] = True

    result = assess(report, NOW)

    assert result["entry_markets"] == ["pas:BTC"]
    assert not result["gates"]["PAS_ACCOUNT_CONFIGURATION_VERIFIED"]
    assert result["signing_authority"] == "NONE"


def test_both_fresh_one_cross_readbacks_open_configuration_gate_not_session_approval():
    from exchange.pas_controller import assess
    from test_activation_v5_2 import NOW, ready_report

    report = ready_report()
    report["markets"] = ["pas:BTC"]

    result = assess(report, NOW)

    assert result["gates"]["PAS_ACCOUNT_CONFIGURATION_VERIFIED"] is True
    assert result["gates"]["EXACT_SESSION_APPROVAL_ACCEPTED"] is False
    assert result["signing_authority"] == "NONE"
    assert result["authorization_status"] == "AWAITING_HUMAN_SESSION_APPROVAL"


def test_native_proof_and_signal_cannot_be_composed_across_markets():
    from exchange.pas_controller import assess
    from test_activation_v5_2 import NOW, ready_report

    report = ready_report()
    report["native_proof_verification"]["markets"] = ["pas:BTC"]
    report["signals"] = [{"symbol": "pas:EWY", "decision": "LONG", "observed_ms": NOW}]

    result = assess(report, NOW)

    assert result["gates"]["PAS_ACCOUNT_CONFIGURATION_VERIFIED"] is True
    assert result["eligible_markets"] == ["pas:BTC"]
    assert result["opportunity_markets"] == []
    assert result["gates"]["EXECUTABLE_OPPORTUNITY_AVAILABLE"] is False


@dataclass(frozen=True)
class _Policy:
    name: str
    limit: int


def _manifest_session():
    from exchange.sdk_transport import OfflineSDKTransport
    from exchange.venue_profiles import BASE_MARKETS

    transport = object.__new__(OfflineSDKTransport)
    transport.signer_address = "0x" + "12" * 20
    client = SimpleNamespace(
        dex="pas",
        api_dex="canonical-api-dex",
        api_market="canonical-api-dex:BTC",
        competition_mode=True,
        competition_market="pas",
        collateral_token_name="USDP",
        venue=SCORED,
        markets={f"pas:{asset}": object() for asset in BASE_MARKETS},
    )
    return SimpleNamespace(
        journal=SimpleNamespace(session_id="offline:merged-manifest"),
        execution=SimpleNamespace(
            transport=transport,
            account=SimpleNamespace(team_address=TEAM),
            protection=SimpleNamespace(policy=_Policy("protection", 7)),
            rate_limits=SimpleNamespace(policy=_Policy("rate", 11)),
        ),
        market=SimpleNamespace(client=client),
        risk=SimpleNamespace(policy=_Policy("risk", 3)),
        scanner=SimpleNamespace(policy=_Policy("scanner", 5)),
        recovery=SimpleNamespace(initial_start_ms=123456789),
        clock_ms=lambda: 123456999,
    )


def test_live_manifest_merges_schema_three_competition_identity_and_pas_policy(monkeypatch, tmp_path):
    import live_session_results as results_module
    from exchange.execution_journal import fingerprint
    from exchange.venue_profiles import BASE_MARKETS

    monkeypatch.setattr(results_module, "verify_strategy_freeze", lambda: {"status": "FIXTURE_VERIFIED"})
    monkeypatch.setattr(results_module, "source_version", lambda paths: "source-version-fixture")
    monkeypatch.setattr(results_module, "subprocess", SimpleNamespace(check_output=lambda args, **kwargs:
        "fixture-commit" if args[1:3] == ["rev-parse", "HEAD"] else
        "fixture-branch" if args[1:3] == ["branch", "--show-current"] else ""))

    writer = results_module.LiveSessionResults(tmp_path / "results", _manifest_session())
    manifest = json.loads((writer.path / "session_manifest.json").read_text())
    config = manifest["configuration"]

    assert manifest["schema_version"] == 3
    assert manifest["execution_mode"] == "OFFLINE_SIGNED_FIXTURE"
    assert manifest["competition_market"] == config["competition_market"] == "pas"
    assert manifest["api_dex"] == config["dex"] == "canonical-api-dex"
    assert manifest["api_market"] == config["api_market"] == "canonical-api-dex:BTC"
    assert manifest["collateral_token"] == config["collateral_token"] == "USDP"
    assert manifest["dex"] == config["dex"] == "canonical-api-dex"
    assert manifest["collateral"] == config["collateral"] == "USDP"
    assert manifest["venue_identity"] == config["venue_identity"] == SCORED.identity
    assert config["entry_markets"] == sorted(PAS_ENTRY_MARKETS)
    assert config["account_reconciliation_markets"] == sorted(f"pas:{asset}" for asset in BASE_MARKETS)
    assert manifest["configuration_hash"] == fingerprint(config)
    assert manifest["risk_policy_hash"] == fingerprint(config["risk_policy"])
    assert manifest["scanner_policy_hash"] == fingerprint(config["scanner_policy"])
    assert config["risk_policy"] == {"name": "risk", "limit": 3}
    assert config["scanner_policy"] == {"name": "scanner", "limit": 5}
    assert config["protection_policy"] == {"name": "protection", "limit": 7}
    assert config["rate_policy"] == {"name": "rate", "limit": 11}


@pytest.mark.parametrize("changed_field", ["api_dex", "configuration_hash", "working_source_hash"])
def test_live_manifest_resume_rejects_changed_competition_or_policy_identity(
        monkeypatch, tmp_path, changed_field):
    import live_session_results as results_module

    monkeypatch.setattr(results_module, "verify_strategy_freeze", lambda: {"status": "FIXTURE_VERIFIED"})
    monkeypatch.setattr(results_module, "source_version", lambda paths: "source-version-fixture")
    monkeypatch.setattr(results_module, "subprocess", SimpleNamespace(check_output=lambda args, **kwargs:
        "fixture-commit" if args[1:3] == ["rev-parse", "HEAD"] else
        "fixture-branch" if args[1:3] == ["branch", "--show-current"] else ""))

    output = tmp_path / "resume"
    session = _manifest_session()
    writer = results_module.LiveSessionResults(output, session)
    path = writer.path / "session_manifest.json"
    altered = json.loads(path.read_text())
    altered[changed_field] = "changed"
    path.write_text(json.dumps(altered))

    with pytest.raises(ValueError, match="RESULT_MANIFEST_IDENTITY_OR_POLICY_CHANGED"):
        results_module.LiveSessionResults(output, session)


@dataclass(frozen=True)
class _CompliancePositionSnapshot:
    allowed: bool
    code: str
    reason: str


@dataclass
class _ComplianceJournal:
    events: list

    def control(self, _key):
        return None

    def event(self, kind, timestamp, **data):
        self.events.append((kind, timestamp, data))


def _direct_compliance_evaluate(*, symbol="pas:BTC", leverage=1, competition_mode=True,
                                position_allowed=True):
    from exchange.compliance_guard import ComplianceGuard, OrderProvenance
    from exchange.order_lifecycle import OrderRequest

    now = 1_800_000
    journal = _ComplianceJournal([])
    guard = ComplianceGuard(
        journal,
        SimpleNamespace(journal=journal),
        clock_ms=lambda: now,
        transport=SimpleNamespace(),
        execution_owner=SimpleNamespace(client=SimpleNamespace(competition_mode=competition_mode)),
    )
    request = OrderRequest(symbol, "BUY", "0.01", "100")
    # Intentionally wrong candidate: a leverage-valid request must proceed to
    # provenance validation rather than being accepted by the test fixture.
    provenance = OrderProvenance(
        candidate_id="different-candidate",
        strategy_id=request.strategy_id,
        setup_type="PULLBACK_LONG",
        signal_timestamp_ms=now - 60_000,
        source_market=symbol,
        direction=request.side,
        reason="fixture provenance",
        risk_decision={"allowed": True},
        execution_decision={"allowed": True},
    )
    permission = SimpleNamespace(candidate_id="candidate", provenance=provenance)
    position = _CompliancePositionSnapshot(
        allowed=position_allowed,
        code="POSITION_LIMIT",
        reason="fixture position rejection",
    )

    return guard.evaluate(request, SimpleNamespace(leverage=leverage), permission, position)


@pytest.mark.parametrize("symbol", ["pas:BTC", "pas:EWY"])
def test_competition_pas_target_leverage_passes_leverage_gate_then_checks_provenance(symbol):
    decision = _direct_compliance_evaluate(symbol=symbol, leverage=1, competition_mode=True)

    assert not decision.allowed
    assert decision.code == "MISSING_STRATEGY_PROVENANCE"


@pytest.mark.parametrize("leverage", [0, 2, 20, True, "1"])
def test_competition_pas_non_target_leverage_is_rejected(leverage):
    decision = _direct_compliance_evaluate(leverage=leverage, competition_mode=True)

    assert not decision.allowed
    assert decision.code == "INVALID_LEVERAGE"


def test_noncompetition_context_retains_exact_one_x_leverage_semantics():
    one_x = _direct_compliance_evaluate(leverage=1, competition_mode=False)
    twenty_x = _direct_compliance_evaluate(leverage=20, competition_mode=False)

    assert not one_x.allowed and one_x.code == "MISSING_STRATEGY_PROVENANCE"
    assert not twenty_x.allowed and twenty_x.code == "INVALID_LEVERAGE"


def test_competition_target_leverage_does_not_override_rejected_position_snapshot():
    decision = _direct_compliance_evaluate(leverage=1, competition_mode=True, position_allowed=False)

    assert not decision.allowed
    assert decision.code == "POSITION_LIMIT"
