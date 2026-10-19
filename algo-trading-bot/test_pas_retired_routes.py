"""Retired PAR write routes fail closed before credentials, network, or filesystem writes."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from exchange.base_exchange import ExchangeError
from exchange.par_retirement import RETIRED_PAR_WRITE_ROUTE

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

def test_legacy_pas_configuration_stops_before_any_io(tmp_path):
    from exchange.pas_configuration import approve_configuration, execute_configuration
    output = tmp_path / 'must-not-be-created'
    with pytest.raises(ExchangeError, match='RETIRED_PAS_1X_CONFIGURATION_WRITE_ROUTE'):
        approve_configuration(None, None, None, None, output)
    with pytest.raises(ExchangeError, match='RETIRED_PAS_1X_CONFIGURATION_WRITE_ROUTE'):
        execute_configuration(None, None, None, None, None, output)
    assert not output.exists()

def load_script(name):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("retired_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_native_execute_stops_before_output_creation(tmp_path):
    cli = load_script("run_native_qualification")
    output = tmp_path / "must-not-exist"
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        cli.main(["execute", "--output", str(output), "--test-receipt", "unused"])
    assert not output.exists()

def test_emergency_and_delegated_execute_stop_before_validation(tmp_path, monkeypatch):
    emergency = load_script("run_emergency_qualification")
    monkeypatch.setattr(sys, "argv", ["run_emergency_qualification", "--execute", "--output-directory", str(tmp_path / "e")])
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        emergency.main()
    delegated = load_script("run_delegated_qualification")
    monkeypatch.setattr(sys, "argv", ["run_delegated_qualification", "--execute"])
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        delegated.main()
    assert not (tmp_path / "e").exists()

def test_exit_recovery_and_leverage_stop_before_io(tmp_path, monkeypatch):
    exit_cli = load_script("run_exit_recovery")
    monkeypatch.setattr(sys, "argv", ["run_exit_recovery", "--execute", "--output-directory", str(tmp_path / "x"), "--test-receipt", "unused"])
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        exit_cli.main()
    leverage = load_script("configure_par_leverage")
    monkeypatch.setattr(sys, "argv", ["configure_par_leverage", "--team-address", "team", "--api-wallet-address", "api", "--state-directory", str(tmp_path / "state"), "--output", str(tmp_path / "report"), "--apply"])
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        leverage.main()
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "report").exists()

def test_runtime_builders_refuse_before_construction(tmp_path):
    from exchange.native_qualification_runtime import build_native_qualification
    from exchange.emergency_qualification import build_runtime
    from exchange.exit_recovery import execute
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        build_native_qualification(None, None, None, test_receipt=None, output=tmp_path)
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        build_runtime(None, None, None, test_receipt=None)
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        execute(None, None, None, None, None, None)

def test_legacy_long_session_builder_rejects_par_mandate_before_signer(tmp_path):
    from exchange.long_session import build_long_runtime
    mandate = tmp_path / "mandate.json"
    mandate.write_text(json.dumps({"daily": {"dex": "par"}}))
    with pytest.raises(ExchangeError, match="RETIRED_SCORED_SESSION_ROUTE"):
        build_long_runtime(None, mandate, None, None, None, scanner_policy=None, risk_policy=None)


def test_terminal_authorized_start_is_retired_before_state_creation(tmp_path):
    from types import SimpleNamespace
    from exchange.terminal_app import start, run_authorized
    args = SimpleNamespace(authorized=True, venue="pas", state=str(tmp_path / "state"))
    with pytest.raises(ExchangeError, match="RETIRED_AUTHORIZED_TERMINAL_ROUTE"):
        start(tmp_path, args)
    with pytest.raises(ExchangeError, match="RETIRED_AUTHORIZED_TERMINAL_ROUTE"):
        run_authorized(tmp_path, args, None, None)
    assert not (tmp_path / "state").exists()


def test_old_qualification_practice_certification_and_scored_clis_retire(tmp_path, monkeypatch):
    qualification = load_script("run_testnet_qualification")
    monkeypatch.setattr(sys, "argv", ["run_testnet_qualification", "--execute", "--output-directory", str(tmp_path / "q")])
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        qualification.main()
    practice = load_script("run_testnet_practice")
    monkeypatch.setattr(sys, "argv", ["run_testnet_practice", "--approval-file", str(tmp_path / "approval"), "--state-directory", str(tmp_path / "state"), "--session-id", "old", "--account-history-start-ms", "1", "--verified-fee-scale", "1"])
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        practice.main()
    certification = load_script("run_testnet_certification")
    with pytest.raises(ExchangeError, match=RETIRED_PAR_WRITE_ROUTE):
        certification.main(["--mode", "TESTNET_PRACTICE", "--output-directory", str(tmp_path / "c")])
    scored = load_script("run_long_session")
    monkeypatch.setattr(sys, "argv", ["run_long_session", "--mandate", "unused", "--acceptance", "unused", "--release", "unused", "--native-protection-evidence", "unused"])
    with pytest.raises(ExchangeError, match="RETIRED_SCORED_SESSION_ROUTE"):
        scored.main()
    assert not (tmp_path / "q").exists()
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "c").exists()
