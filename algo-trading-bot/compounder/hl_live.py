"""LIVE broker for Hyperliquid mainnet perps through an API (agent) wallet.

Locked unless ALL of these hold (checked by ``LiveGate.verify`` before the broker is built):
  * the mandate says mode LIVE and live_orders_allowed true, and names the account address;
  * a human typed the activation phrase in a real terminal (activation receipt bound to the
    mandate hash; see scripts/run_compounder.py activate-live);
  * the agent key file exists outside the repository with permissions 0600;
  * the exchange reports the agent as approved for that account, the account is funded, and it
    holds no position or order the bot does not own.
The agent key can trade but cannot withdraw (Hyperliquid agent-wallet rule).

Order rules: entries and exits are IOC limit orders priced at most ``max_slippage`` through the
touch (never a sweep beyond it); every entry gets a reduce-only stop-market trigger at once, and a
position whose stop cannot be placed is closed immediately (runner rule). Each order carries a
deterministic client order id (cloid) so a retry after a lost reply can never double an order.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .brokers import Fill, OrderRefused
from .costs import VenueCosts
from .market_data import DataError, HyperliquidPublic, decimal_px

MAINNET_URL = "https://api.hyperliquid.xyz"


class LiveLocked(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveGate:
    mandate: dict
    mandate_hash: str
    receipt_path: Path
    key_path: Path
    repo_root: Path

    def verify(self) -> None:
        m = self.mandate
        if m.get("mode") != "LIVE" or m.get("live_orders_allowed") is not True:
            raise LiveLocked("MANDATE_NOT_LIVE")
        addr = str(m.get("account_address") or "")
        if not (addr.startswith("0x") and len(addr) == 42) or int(addr, 16) == 0:
            raise LiveLocked("ACCOUNT_ADDRESS_NOT_CONFIGURED")
        if not self.receipt_path.exists():
            raise LiveLocked("NO_HUMAN_ACTIVATION_RECEIPT")
        receipt = json.loads(self.receipt_path.read_text())
        if receipt.get("mandate_hash") != self.mandate_hash or receipt.get("typed") != activation_phrase(addr):
            raise LiveLocked("ACTIVATION_RECEIPT_DOES_NOT_MATCH_MANDATE")
        key = self.key_path.resolve()
        if self.repo_root.resolve() in key.parents:
            raise LiveLocked("AGENT_KEY_INSIDE_REPOSITORY")
        if not key.exists():
            raise LiveLocked("AGENT_KEY_FILE_MISSING")
        if stat.S_IMODE(key.stat().st_mode) & 0o077:
            raise LiveLocked("AGENT_KEY_FILE_PERMISSIONS_MUST_BE_0600")


def activation_phrase(address: str) -> str:
    return f"I ACCEPT REAL LOSSES ON {address[-6:].upper()}"


def cloid_for(mandate_hash: str, coin: str, bar: int, action: str, attempt: int = 0) -> str:
    digest = hashlib.sha256(f"{mandate_hash}|{coin}|{bar}|{action}|{attempt}".encode()).hexdigest()
    return "0x" + digest[:32]


def load_agent_wallet(key_path: Path):
    from eth_account import Account
    raw = key_path.read_text().strip()
    wallet = Account.from_key(raw)
    del raw
    return wallet


class HyperliquidLiveBroker:
    """Same interface as PaperBroker plus account truth (``account_value``, ``positions``)."""
    mode = "LIVE"

    def __init__(self, *, exchange, info, md: HyperliquidPublic, costs: VenueCosts, account: str,
                 mandate_hash: str, size_decimals: dict, max_slippage: float = 0.005, clock=time.time):
        self.ex = exchange
        self.info = info
        self.md = md
        self.costs = costs
        self.account = account
        self.mandate_hash = mandate_hash
        self.size_decimals = size_decimals
        self.max_slippage = max_slippage
        self.clock = clock
        self.bar_hint = 0          # set by the runner before each decision (cloid input)

    # -------------------------------------------------------------- account truth
    def account_value(self) -> float:
        st = self.info.user_state(self.account)
        return float(st["marginSummary"]["accountValue"])

    def positions(self) -> dict:
        st = self.info.user_state(self.account)
        out = {}
        for ap in st.get("assetPositions", []):
            p = ap["position"]
            szi = float(p["szi"])
            if szi != 0:
                out[p["coin"]] = szi
        return out

    def open_orders(self) -> list:
        return self.info.open_orders(self.account)

    def preflight(self, agent_address: str, universe: tuple, owned_positions: dict, owned_stop_oids: set) -> dict:
        """Fresh checks before the live loop starts. Raises LiveLocked on anything unexpected."""
        agents = self.info.extra_agents(self.account) or []
        approved = {str(a.get("address", "")).lower() for a in agents}
        if agent_address.lower() not in approved:
            raise LiveLocked("AGENT_NOT_APPROVED_FOR_ACCOUNT")
        value = self.account_value()
        if value < 20:
            raise LiveLocked(f"ACCOUNT_NOT_FUNDED:{value}")
        for coin, szi in self.positions().items():
            mine = owned_positions.get(coin)
            if mine is None or abs(mine - szi) > 1e-12:
                raise LiveLocked(f"UNOWNED_OR_MISMATCHED_POSITION:{coin}:{szi}")
        for o in self.open_orders():
            if int(o["oid"]) not in owned_stop_oids:
                raise LiveLocked(f"UNOWNED_OPEN_ORDER:{o.get('coin')}:{o.get('oid')}")
        return {"account_value": value, "agents": sorted(approved)}

    # -------------------------------------------------------------- orders
    def _cloid(self, coin: str, action: str):
        from hyperliquid.utils.types import Cloid
        return Cloid.from_str(cloid_for(self.mandate_hash, coin, self.bar_hint, action))

    def _fill_from_response(self, coin: str, side: int, resp, mid: float, reason: str) -> Fill:
        if not isinstance(resp, dict) or resp.get("status") != "ok":
            raise OrderRefused(f"EXCHANGE_REJECTED:{coin}:{resp}")
        statuses = resp["response"]["data"]["statuses"]
        st = statuses[0]
        if "error" in st:
            raise OrderRefused(f"ORDER_ERROR:{coin}:{st['error']}")
        filled = st.get("filled")
        if not filled or float(filled["totalSz"]) <= 0:
            raise OrderRefused(f"IOC_NOT_FILLED:{coin}")
        qty = float(filled["totalSz"])
        px = float(filled["avgPx"])
        oid = int(filled["oid"])
        fee = self._fee_for(oid, px * qty)
        return Fill(coin, side, qty, px, fee, mid, int(self.clock() * 1000), reason)

    def _fee_for(self, oid: int, notional: float) -> float:
        """Actual fee from the account's fills; falls back to the schedule if not yet indexed."""
        try:
            fills = self.info.user_fills_by_time(self.account, int(self.clock() * 1000) - 600_000)
            fee = sum(float(f["fee"]) for f in fills if int(f.get("oid", -1)) == oid)
            if fee > 0:
                return fee
        except Exception:  # read failure never blocks bookkeeping; the schedule is the fallback
            pass
        return self.costs.fee(notional)

    def market(self, coin: str, side: int, qty: float, *, reduce_only: bool, reason: str,
               leverage: int | None = None) -> Fill:
        bids, asks, _ = self.md.book(coin)
        mid = (bids[0][0] + asks[0][0]) / 2
        touch = asks[0][0] if side > 0 else bids[0][0]
        limit = float(decimal_px(touch * (1 + side * self.max_slippage), self.size_decimals[coin]))
        action = ("EXIT_" if reduce_only else "ENTRY_") + reason
        resp = self.ex.order(coin, side > 0, qty, limit, {"limit": {"tif": "Ioc"}}, reduce_only=reduce_only,
                             cloid=self._cloid(coin, action))
        return self._fill_from_response(coin, side, resp, mid, reason)

    def place_stop(self, coin: str, pos_side: int, qty: float, trigger: float) -> str:
        trig = float(decimal_px(trigger, self.size_decimals[coin]))
        # stop-market: the limit is a 10% protection band; the trigger fires on the mark price
        limit = float(decimal_px(trig * (1 - pos_side * 0.10), self.size_decimals[coin]))
        resp = self.ex.order(coin, pos_side < 0, qty, limit,
                             {"trigger": {"triggerPx": trig, "isMarket": True, "tpsl": "sl"}},
                             reduce_only=True, cloid=self._cloid(coin, "STOP"))
        if not isinstance(resp, dict) or resp.get("status") != "ok":
            raise OrderRefused(f"STOP_REJECTED:{coin}:{resp}")
        st = resp["response"]["data"]["statuses"][0]
        if "error" in st:
            raise OrderRefused(f"STOP_ERROR:{coin}:{st['error']}")
        oid = (st.get("resting") or {}).get("oid")
        if oid is None:
            raise OrderRefused(f"STOP_NOT_RESTING:{coin}:{st}")
        return str(oid)

    def cancel_stop(self, coin: str, order_id: str | None) -> None:
        if order_id is None:
            return
        resp = self.ex.cancel(coin, int(order_id))
        if not isinstance(resp, dict) or resp.get("status") != "ok":
            raise OrderRefused(f"CANCEL_REJECTED:{coin}:{resp}")

    def stop_triggered(self, coin: str, pos_side: int, stop: float, contexts: dict) -> bool:
        """Live stops rest on the exchange; a stop has fired when the exchange no longer shows
        the position (the runner then books the actual exit fill)."""
        return coin not in self.positions()

    def exit_fill_after_stop(self, coin: str, pos_side: int, qty: float, since_ms: int) -> Fill:
        fills = [f for f in self.info.user_fills_by_time(self.account, since_ms) if f["coin"] == coin
                 and (f["side"] == ("A" if pos_side > 0 else "B"))]
        if not fills:
            raise DataError(f"STOP_FILL_NOT_INDEXED:{coin}")
        sz = sum(float(f["sz"]) for f in fills)
        px = sum(float(f["px"]) * float(f["sz"]) for f in fills) / sz
        fee = sum(float(f["fee"]) for f in fills)
        return Fill(coin, -pos_side, sz, px, fee, px, max(int(f["time"]) for f in fills), "STOP")

    def funding(self, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        """Actual funding rates (the runner multiplies by its position notional); the realized
        USDC amounts are reconciled against ``user_funding_history`` in the daily report."""
        return [x for x in self.md.funding_history(coin, start_ms, end_ms) if start_ms < x[0] <= end_ms]


def build_live_broker(gate: LiveGate, md: HyperliquidPublic, costs: VenueCosts, universe: tuple):
    """Verifies the gate, loads the agent key, and returns (broker, agent_address)."""
    gate.verify()
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    wallet = load_agent_wallet(gate.key_path)
    account = gate.mandate["account_address"]
    info = Info(MAINNET_URL, skip_ws=True)
    ex = Exchange(wallet, MAINNET_URL, account_address=account)
    specs = md.specs()
    broker = HyperliquidLiveBroker(exchange=ex, info=info, md=md, costs=costs, account=account,
                                   mandate_hash=gate.mandate_hash,
                                   size_decimals={c: specs[c].size_decimals for c in universe})
    return broker, wallet.address


def key_file_ok(path: Path) -> bool:
    return path.exists() and not (stat.S_IMODE(os.stat(path).st_mode) & 0o077)
