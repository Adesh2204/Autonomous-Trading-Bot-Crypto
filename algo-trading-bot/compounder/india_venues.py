"""Read-only public market data for Indian futures venues (no keys, no orders).

Both classes expose the HyperliquidPublic interface the runner and PaperBroker use:
  specs(), contexts(), book(coin), candles(coin, interval, bars), funding_history(coin, a, b)
Quantities are always in COINS (Delta's contracts are converted with their contract value).

Funding: both venues settle every 8 hours. Neither publishes a public funding-history endpoint we
can rely on, so the adapter records the published rate on every contexts() call (the runner calls
it every 20 s) and charges, at each 00:00/08:00/16:00 UTC settlement:
  * CoinDCX: ``fr`` read after the settlement (the rate just settled; it equals Binance's settled
    rate, checked on 25 Nov 2026 for BTC and TRX);
  * Delta India: ``funding_rate`` (percent per 8 h) read before the settlement (the rate due).
"""
from __future__ import annotations

import time
from decimal import Decimal

import requests

from .market_data import BAR_MS, AssetContext, AssetSpec, DataError

FUNDING_STEP_MS = 8 * 3_600_000


def funding_times(start_ms: int, end_ms: int) -> list[int]:
    """8-hour settlement times (00/08/16 UTC) with start < T <= end."""
    first = (start_ms // FUNDING_STEP_MS + 1) * FUNDING_STEP_MS
    return list(range(first, end_ms + 1, FUNDING_STEP_MS))


def _decimals(step: float) -> int:
    exp = Decimal(repr(step)).normalize().as_tuple().exponent
    return max(0, -int(exp))


class _Public:
    venue = "base"

    def __init__(self, universe, *, timeout: float = 10.0, retries: int = 3, session=None, clock=time.time):
        self.universe = tuple(universe)
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.clock = clock
        self._obs: dict[str, list[tuple[int, float]]] = {}

    def _now(self) -> int:
        return int(self.clock() * 1000)

    def _get(self, url: str, params: dict | None = None):
        last = None
        for attempt in range(self.retries):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP_{r.status_code}"
            except (requests.RequestException, ValueError) as exc:
                last = type(exc).__name__
            time.sleep(1.5 * (attempt + 1))
        raise DataError(f"{self.venue.upper()}_UNAVAILABLE:{url.rsplit('/', 1)[-1]}:{last}")

    def _observe(self, coin: str, ts: int, rate: float) -> None:
        obs = self._obs.setdefault(coin, [])
        if not obs or ts - obs[-1][0] >= 60_000:
            obs.append((ts, rate))
            del obs[:-1500]

    def _rate_for(self, coin: str, settle_ms: int) -> float | None:
        raise NotImplementedError

    def funding_history(self, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        out = []
        for t in funding_times(start_ms, end_ms):
            rate = self._rate_for(coin, t)
            if rate is not None:
                out.append((t, rate))
        return out


class CoinDCXPublic(_Public):
    venue = "coindcx_futures"
    API = "https://api.coindcx.com"
    PUB = "https://public.coindcx.com"
    RESOLUTION = {"1d": "1D", "1m": "1", "1h": "60"}

    @staticmethod
    def pair(coin: str) -> str:
        return f"B-{coin}_USDT"

    def specs(self) -> dict[str, AssetSpec]:
        out = {}
        for coin in self.universe:
            d = self._get(f"{self.API}/exchange/v1/derivatives/futures/data/instrument",
                          {"pair": self.pair(coin), "margin_currency_short_name": "USDT"}).get("instrument") or {}
            if d.get("status") != "active" or d.get("exit_only"):
                continue
            step = float(d["quantity_increment"])
            out[coin] = AssetSpec(coin, _decimals(step), int(float(d["max_leverage_long"])), qty_step=step,
                                  min_notional=float(d["min_notional"]), price_step=float(d["price_increment"]))
        if not out:
            raise DataError("COINDCX_NO_ACTIVE_INSTRUMENTS")
        return out

    def contexts(self) -> dict[str, AssetContext]:
        prices = self._get(f"{self.PUB}/market_data/v3/current_prices/futures/rt").get("prices") or {}
        now = self._now()
        out = {}
        for coin in self.universe:
            p = prices.get(self.pair(coin))
            if not p:
                continue
            mark, last, fr = float(p["mp"]), float(p["ls"]), float(p.get("fr") or 0.0)
            self._observe(coin, now, fr)
            out[coin] = AssetContext(coin, mark, mark, last, fr / 8, None, None)
        return out

    def _rate_for(self, coin: str, settle_ms: int) -> float | None:
        obs = self._obs.get(coin) or []
        after = [r for ts, r in obs if ts >= settle_ms + 60_000]
        if after:
            return after[0]
        return obs[-1][1] if obs else None

    def book(self, coin: str):
        d = self._get(f"{self.PUB}/market_data/v3/orderbook/{self.pair(coin)}-futures/50")
        bids = sorted(((float(p), float(q)) for p, q in (d.get("bids") or {}).items() if float(q) > 0), reverse=True)
        asks = sorted((float(p), float(q)) for p, q in (d.get("asks") or {}).items() if float(q) > 0)
        if not bids or not asks:
            raise DataError(f"COINDCX_BOOK_EMPTY:{coin}")
        return bids, asks, int(d.get("ts", 0))

    def candles(self, coin: str, interval: str, bars: int) -> list[dict]:
        step = BAR_MS[interval]
        now = self._now()
        d = self._get(f"{self.PUB}/market_data/candlesticks",
                      {"pair": self.pair(coin), "from": (now - (bars + 2) * step) // 1000, "to": now // 1000,
                       "resolution": self.RESOLUTION[interval], "pcode": "f"})
        rows = sorted(d.get("data") or [], key=lambda r: int(r["time"]))
        done = [{"t": int(r["time"]), "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"]}
                for r in rows if int(r["time"]) + step <= now]
        return done[-bars:]


class DeltaIndiaPublic(_Public):
    venue = "delta_india"
    API = "https://api.india.delta.exchange"

    def __init__(self, universe, **kw):
        super().__init__(universe, **kw)
        self._cv: dict[str, float] = {}

    @staticmethod
    def symbol(coin: str) -> str:
        return f"{coin}USD"

    def specs(self) -> dict[str, AssetSpec]:
        out = {}
        for coin in self.universe:
            p = self._get(f"{self.API}/v2/products/{self.symbol(coin)}").get("result") or {}
            if p.get("contract_type") != "perpetual_futures" or p.get("state") != "live":
                continue
            cv = float(p["contract_value"])
            self._cv[coin] = cv
            out[coin] = AssetSpec(coin, _decimals(cv), int(100 / float(p["initial_margin"])), qty_step=cv,
                                  min_notional=0.0)
        if not out:
            raise DataError("DELTA_NO_LIVE_PRODUCTS")
        return out

    def contexts(self) -> dict[str, AssetContext]:
        rows = self._get(f"{self.API}/v2/tickers", {"contract_types": "perpetual_futures"}).get("result") or []
        by_sym = {r.get("symbol"): r for r in rows}
        now = self._now()
        out = {}
        for coin in self.universe:
            r = by_sym.get(self.symbol(coin))
            if not r or r.get("mark_price") in (None, ""):
                continue
            mark = float(r["mark_price"])
            q = r.get("quotes") or {}
            mid = None
            if q.get("best_bid") and q.get("best_ask"):
                mid = (float(q["best_bid"]) + float(q["best_ask"])) / 2
            fr = float(r.get("funding_rate") or 0.0) / 100.0   # percent per 8 h -> fraction
            self._observe(coin, now, fr)
            out[coin] = AssetContext(coin, mark, float(r.get("spot_price") or mark), mid, fr / 8, None, None)
        return out

    def _rate_for(self, coin: str, settle_ms: int) -> float | None:
        obs = self._obs.get(coin) or []
        before = [r for ts, r in obs if ts < settle_ms]
        if before:
            return before[-1]
        return obs[0][1] if obs else None

    def _contract_value(self, coin: str) -> float:
        if coin not in self._cv:
            self.specs()
        return self._cv[coin]

    def book(self, coin: str):
        d = self._get(f"{self.API}/v2/l2orderbook/{self.symbol(coin)}").get("result") or {}
        cv = self._contract_value(coin)
        bids = sorted(((float(x["price"]), float(x["size"]) * cv) for x in d.get("buy") or []), reverse=True)
        asks = sorted((float(x["price"]), float(x["size"]) * cv) for x in d.get("sell") or [])
        if not bids or not asks:
            raise DataError(f"DELTA_BOOK_EMPTY:{coin}")
        return bids, asks, self._now()

    def candles(self, coin: str, interval: str, bars: int) -> list[dict]:
        step = BAR_MS[interval]
        now = self._now()
        d = self._get(f"{self.API}/v2/history/candles",
                      {"resolution": interval, "symbol": self.symbol(coin),
                       "start": (now - (bars + 2) * step) // 1000, "end": now // 1000})
        rows = sorted(d.get("result") or [], key=lambda r: int(r["time"]))
        done = [{"t": int(r["time"]) * 1000, "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"]}
                for r in rows if int(r["time"]) * 1000 + step <= now]
        return done[-bars:]
