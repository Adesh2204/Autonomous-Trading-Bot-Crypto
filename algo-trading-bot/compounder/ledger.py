"""Durable bot state and the money ledger (atomic JSON state + append-only JSONL journals).

Files under the run directory:
  state.json    current positions, cash, tax ledger, totals (rewritten atomically)
  events.jsonl  every decision, fill, funding payment and halt (append-only, fsync'd)
  trades.jsonl  every closed trade with USD and INR values and the tax reserved for it
  status.json   heartbeat for humans/monitors (rewritten every minute)
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .costs import TaxLedger, TaxPolicy


@dataclass
class OpenPosition:
    coin: str
    side: int
    qty: float
    entry_price: float
    entry_time: int
    stop: float
    fees: float
    funding: float = 0.0
    slippage: float = 0.0
    entry_bar: int = 0
    stop_order_id: str | None = None
    leverage: float = 0.0


@dataclass
class BotState:
    mode: str
    venue: str
    mandate_hash: str
    start_equity: float
    cash: float
    positions: dict = field(default_factory=dict)
    tax: dict = field(default_factory=dict)
    last_bar_processed: int = 0
    last_funding_ms: int = 0
    last_stop_check_ms: int = 0
    peak_after_tax: float = 0.0
    day_start_after_tax: float = 0.0
    day_start_ms: int = 0
    halted: str | None = None
    entries_paused_until: int = 0
    totals: dict = field(default_factory=lambda: {"fees": 0.0, "slippage": 0.0, "funding": 0.0,
                                                  "realized_net": 0.0, "trades": 0, "wins": 0})
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    extra: dict = field(default_factory=dict)   # strategy scratch state (e.g. intraday entries per day)

    def open_positions(self) -> dict[str, OpenPosition]:
        return {k: OpenPosition(**v) for k, v in self.positions.items()}

    def put_position(self, pos: OpenPosition) -> None:
        self.positions[pos.coin] = asdict(pos)

    def drop_position(self, coin: str) -> None:
        self.positions.pop(coin, None)

    def tax_ledger(self) -> TaxLedger:
        t = self.tax or {}
        ledger = TaxLedger(TaxPolicy(**t.get("policy", {})))
        ledger.reserve = float(t.get("reserve", 0.0))
        ledger.fy_net = {int(k): float(v) for k, v in t.get("fy_net", {}).items()}
        ledger.fy_tax = {int(k): float(v) for k, v in t.get("fy_tax", {}).items()}
        return ledger

    def store_tax(self, ledger: TaxLedger) -> None:
        self.tax = {"policy": asdict(ledger.policy), "reserve": ledger.reserve,
                    "fy_net": {str(k): v for k, v in ledger.fy_net.items()},
                    "fy_tax": {str(k): v for k, v in ledger.fy_tax.items()}}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Journal:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.events_path = self.dir / "events.jsonl"
        self.trades_path = self.dir / "trades.jsonl"
        self.status_path = self.dir / "status.json"

    def load(self) -> BotState | None:
        if not self.state_path.exists():
            return None
        return BotState(**json.loads(self.state_path.read_text()))

    def save(self, state: BotState) -> None:
        _atomic_write(self.state_path, asdict(state))

    def _append(self, path: Path, row: dict) -> None:
        with open(path, "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def event(self, kind: str, **fields) -> dict:
        row = {"ts_ms": int(time.time() * 1000), "kind": kind, **fields}
        self._append(self.events_path, row)
        return row

    def trade(self, row: dict) -> None:
        self._append(self.trades_path, row)

    def status(self, payload: dict) -> None:
        _atomic_write(self.status_path, payload)

    def trades(self) -> list[dict]:
        if not self.trades_path.exists():
            return []
        return [json.loads(x) for x in self.trades_path.read_text().splitlines() if x.strip()]
