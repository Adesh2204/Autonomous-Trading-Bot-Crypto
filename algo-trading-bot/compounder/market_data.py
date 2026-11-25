"""Read-only Hyperliquid mainnet public data (no keys). Used by the paper runner and the live
runner's fresh reads. Every call has a timeout and bounded retries; failures raise DataError."""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

import requests

MAINNET_INFO = "https://api.hyperliquid.xyz/info"
BAR_MS = {"1m": 60_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class DataError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetSpec:
    coin: str
    size_decimals: int
    max_leverage: int
    qty_step: float = 0.0       # 0 = use size_decimals (Hyperliquid)
    min_notional: float = 0.0   # per-instrument minimum order value in USD (0 = venue default)
    price_step: float = 0.0     # tick size where the venue publishes one (CoinDCX)


@dataclass(frozen=True)
class AssetContext:
    coin: str
    mark: float
    oracle: float
    mid: float | None
    funding_hourly: float
    impact_bid: float | None
    impact_ask: float | None


class HyperliquidPublic:
    venue = "hyperliquid"

    def __init__(self, url: str = MAINNET_INFO, *, timeout: float = 10.0, retries: int = 3,
                 session: requests.Session | None = None, clock=time.time):
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.clock = clock

    def _post(self, payload: dict):
        last = None
        for attempt in range(self.retries):
            try:
                r = self.session.post(self.url, json=payload, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP_{r.status_code}"
            except requests.RequestException as exc:  # network trouble: retry, then fail closed
                last = type(exc).__name__
            time.sleep(1.5 * (attempt + 1))
        raise DataError(f"HL_INFO_UNAVAILABLE:{payload.get('type')}:{last}")

    def specs(self) -> dict[str, AssetSpec]:
        meta = self._post({"type": "meta"})
        out = {}
        for a in meta.get("universe", []):
            if a.get("isDelisted"):
                continue
            out[a["name"]] = AssetSpec(a["name"], int(a["szDecimals"]), int(a["maxLeverage"]))
        if not out:
            raise DataError("HL_META_EMPTY")
        return out

    def contexts(self) -> dict[str, AssetContext]:
        meta, ctxs = self._post({"type": "metaAndAssetCtxs"})
        out = {}
        for a, c in zip(meta["universe"], ctxs):
            impact = c.get("impactPxs") or [None, None]
            out[a["name"]] = AssetContext(
                coin=a["name"], mark=float(c["markPx"]), oracle=float(c["oraclePx"]),
                mid=float(c["midPx"]) if c.get("midPx") else None, funding_hourly=float(c["funding"]),
                impact_bid=float(impact[0]) if impact[0] else None, impact_ask=float(impact[1]) if impact[1] else None)
        return out

    def book(self, coin: str) -> tuple[list[tuple[float, float]], list[tuple[float, float]], int]:
        """(bids, asks, time_ms); each level (price, size), best first."""
        snap = self._post({"type": "l2Book", "coin": coin})
        levels = snap.get("levels") or [[], []]
        bids = [(float(x["px"]), float(x["sz"])) for x in levels[0]]
        asks = [(float(x["px"]), float(x["sz"])) for x in levels[1]]
        if not bids or not asks:
            raise DataError(f"HL_BOOK_EMPTY:{coin}")
        return bids, asks, int(snap.get("time", 0))

    def candles(self, coin: str, interval: str, bars: int) -> list[dict]:
        """The last ``bars`` COMPLETED candles, oldest first."""
        now_ms = int(self.clock() * 1000)
        step = BAR_MS[interval]
        start = now_ms - (bars + 2) * step
        rows = self._post({"type": "candleSnapshot",
                           "req": {"coin": coin, "interval": interval, "startTime": start, "endTime": now_ms}})
        done = [r for r in rows if int(r["t"]) + step <= now_ms]
        return done[-bars:]

    def funding_history(self, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        rows = self._post({"type": "fundingHistory", "coin": coin, "startTime": start_ms, "endTime": end_ms})
        return [(int(r["time"]), float(r["fundingRate"])) for r in rows]


def walk_book(levels: list[tuple[float, float]], qty: float) -> float | None:
    """Volume-weighted fill price for ``qty`` taken from ``levels`` (best first); None if the
    visible book is too thin (the order would sweep it, which the bot never does)."""
    remaining, cost = qty, 0.0
    for px, sz in levels:
        take = min(remaining, sz)
        cost += take * px
        remaining -= take
        if remaining <= 1e-12:
            return cost / qty
    return None


def decimal_px(px: float, size_decimals: int, *, perp: bool = True) -> Decimal:
    """Hyperliquid price rule (same as the official SDK's slippage price): 5 significant
    figures, then at most (6 - szDecimals) decimals for perps (8 - szDecimals for spot)."""
    max_dec = (6 if perp else 8) - size_decimals
    return Decimal(repr(round(float(f"{px:.5g}"), max_dec)))
