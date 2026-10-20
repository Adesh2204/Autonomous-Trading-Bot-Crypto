"""PAS-only public replay/recovery fixtures; synthetic, unsigned, PAPER/false."""
from copy import deepcopy
from decimal import Decimal as D
import json

import pytest

from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_client import HyperliquidClient
from exchange.replay import PublicReplayRecorder, ReplayTape
from test_exchange_migration import NOW


TEAM = "0x" + "1" * 40  # Synthetic public address only; no key or network access.


class PasReadFixture:
    """Minimal runtime-discovered BTC/EWY and USDP metadata fixture."""
    alias = "runtime-pas"

    def __init__(self):
        self.now = NOW
        self.calls = []
        self.state = {"assetPositions": [{"position": {
            "coin": f"{self.alias}:BTC", "szi": "0.05", "entryPx": "100",
            "unrealizedPnl": "0", "marginUsed": "2", "liquidationPx": None,
            "leverage": {"type": "cross", "value": 20},
        }}], "marginSummary": {"accountValue": "1000", "totalMarginUsed": "2"},
            "withdrawable": "998"}

    def __call__(self, payload):
        self.calls.append(deepcopy(payload))
        query = payload["type"]
        if query == "perpDexs":
            return [None, {"name": self.alias, "competition_market": "pas"}]
        if query == "meta":
            assert payload["dex"] == self.alias
            return {"universe": [
                {"name": "BTC", "szDecimals": 4, "maxLeverage": 20},
                {"name": "EWY", "szDecimals": 2, "maxLeverage": 20},
            ], "marginTables": [], "collateralToken": 7}
        if query == "spotMeta":
            return {"tokens": [{"index": 7, "name": "USDP"}]}
        if query == "clearinghouseState":
            return deepcopy(self.state)
        if query == "openOrders":
            return []
        if query == "userFills":
            return []
        if query == "userFunding":
            return []
        raise AssertionError(f"unexpected offline fixture query: {payload}")

    def close(self):
        pass


def test_pas_replay_startup_round_trips_recorded_operation_order(tmp_path):
    source = PasReadFixture()
    recorder = PublicReplayRecorder(source, clock_ms=lambda: source.now)
    recording_client = HyperliquidClient(recorder, clock_ms=recorder.clock_ms)
    recording_client.startup()
    tape_path = tmp_path / "pas-startup-tape.json"
    recorder.save(tape_path, parameters={}, provenance="SYNTHETIC_PAS_FIXTURE")

    replay_tape = ReplayTape(json.loads(tape_path.read_text()))
    replay_client = HyperliquidClient(replay_tape, clock_ms=replay_tape.clock_ms)
    replay_client.startup()
    completion = replay_tape.finish()

    assert set(replay_client.markets) == {"runtime-pas:BTC", "runtime-pas:EWY"}
    assert replay_client.collateral_token_name == "USDP"
    assert completion["consumed_operations"] == len(recorder.operations)
    assert completion["exchange_orders_submitted"] == 0
    assert [op["kind"] for op in recorder.operations] == [
        "info", "clock", "info", "clock", "info", "clock", "clock"
    ]
    assert all(call.get("dex") != "par" for call in source.calls)
    assert replay_client.ready


def test_pas_recovery_fixture_reads_runtime_active_position_without_writes():
    source = PasReadFixture()
    client = HyperliquidClient(source)
    client.startup()
    account = HyperliquidAccount(client, TEAM)

    positions = account.get_positions()
    orders = account.get_open_orders()
    assert set(positions) == {"runtime-pas:BTC"}
    assert positions["runtime-pas:BTC"].quantity == D("0.05")
    assert orders == []
    assert all(call["type"] not in {"order", "cancel", "updateLeverage"} for call in source.calls)
    assert all(call.get("dex") != "par" for call in source.calls)
    from venue_config import require_paper_migration
    assert client.competition_mode and require_paper_migration()["ALLOW_LIVE_ORDERS"] is False


def test_replay_operation_mismatch_does_not_consume_future_event():
    from exchange.replay import checksum
    body = {"schema_version": 1, "cycles": 1, "clock_model": "RECORDED_LOGICAL_CLOCK",
            "parameters": {}, "provenance": "SYNTHETIC_TEST",
            "operations": [{"kind": "clock", "value": NOW},
                           {"kind": "info", "payload": {"type": "meta"}, "response": {}}]}
    tape = ReplayTape(dict(body, sha256=checksum(body)))

    with pytest.raises(ExchangeError, match="REPLAY_OPERATION_MISMATCH"):
        tape({"type": "meta"})
    assert tape.clock_ms() == NOW
    assert tape({"type": "meta"}) == {}
    assert tape.finish()["consumed_operations"] == 2
