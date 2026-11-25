"""Fetch public market history for the compounder research (no keys, read-only).

Sources (public endpoints only):
  * Binance USD-M futures: daily/4h klines and 8h funding history (long history, 2019+).
  * Hyperliquid mainnet: daily/4h/1h candles and hourly funding history (the venue we would trade).

Raw responses are cached as JSON under runtime/compounder/data/ (gitignored).
Re-running only fetches what is missing.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "runtime" / "compounder" / "data"
DATA.mkdir(parents=True, exist_ok=True)

BINANCE = "https://fapi.binance.com"
HL = "https://api.hyperliquid.xyz/info"

BINANCE_SYMBOLS = [
    "BTC", "ETH", "XRP", "BCH", "LTC", "BNB", "EOS", "XTZ", "XLM", "ADA",
    "SOL", "AVAX", "DOGE", "TRX", "LINK", "DOT", "HYPE",
]
HL_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "TRX", "LINK", "HYPE", "LTC", "BCH", "DOT"]

START_MS = 1567296000000  # 2019-09-01
NOW_MS = int(time.time() * 1000)
INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "research-client"})


def _get(url: str, params: dict, tries: int = 5):
    for attempt in range(tries):
        r = SESSION.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (418, 429):
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 400:
            return None
        time.sleep(2)
    r.raise_for_status()


def _post(payload: dict, tries: int = 6):
    for attempt in range(tries):
        r = SESSION.post(HL, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()


def binance_klines(sym: str, interval: str) -> Path:
    out = DATA / f"binance_{sym}_{interval}.json"
    if out.exists():
        return out
    rows, start = [], START_MS
    while start < NOW_MS:
        batch = _get(f"{BINANCE}/fapi/v1/klines", {"symbol": f"{sym}USDT", "interval": interval,
                                                    "startTime": start, "limit": 1500})
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + INTERVAL_MS[interval]
        if nxt <= start or len(batch) < 2:
            break
        start = nxt
        time.sleep(0.25)
    out.write_text(json.dumps(rows))
    return out


def binance_funding(sym: str) -> Path:
    out = DATA / f"binance_{sym}_funding.json"
    if out.exists():
        return out
    rows, start = [], START_MS
    while start < NOW_MS:
        batch = _get(f"{BINANCE}/fapi/v1/fundingRate", {"symbol": f"{sym}USDT", "startTime": start, "limit": 1000})
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1]["fundingTime"] + 1
        if nxt <= start or len(batch) < 1000:
            break
        start = nxt
        time.sleep(0.25)
    out.write_text(json.dumps(rows))
    return out


def hl_candles(coin: str, interval: str) -> Path:
    out = DATA / f"hl_{coin}_{interval}.json"
    if out.exists():
        return out
    rows, start = [], 1640995200000  # 2022-01-01; HL serves at most the latest 5000 candles
    while start < NOW_MS:
        batch = _post({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                                                         "startTime": start, "endTime": NOW_MS}})
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1]["t"] + INTERVAL_MS[interval]
        if nxt <= start or len(batch) < 2:
            break
        start = nxt
        time.sleep(0.3)
    dedup = {r["t"]: r for r in rows}
    out.write_text(json.dumps([dedup[k] for k in sorted(dedup)]))
    return out


def hl_funding(coin: str) -> Path:
    out = DATA / f"hl_{coin}_funding.json"
    if out.exists():
        return out
    rows, start = [], 1672531200000  # 2023-01-01
    while start < NOW_MS:
        batch = _post({"type": "fundingHistory", "coin": coin, "startTime": start, "endTime": NOW_MS})
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1]["time"] + 1
        if nxt <= start or len(batch) < 2:
            break
        start = nxt
        time.sleep(0.3)
    dedup = {r["time"]: r for r in rows}
    out.write_text(json.dumps([dedup[k] for k in sorted(dedup)]))
    return out


def main(which: str) -> None:
    if which in ("binance", "all"):
        for s in BINANCE_SYMBOLS:
            for iv in ("1d", "4h"):
                p = binance_klines(s, iv)
                print("binance", s, iv, len(json.loads(p.read_text())), flush=True)
            p = binance_funding(s)
            print("binance", s, "funding", len(json.loads(p.read_text())), flush=True)
    if which in ("hl", "all"):
        for c in HL_COINS:
            for iv in ("1d", "4h", "1h"):
                p = hl_candles(c, iv)
                print("hl", c, iv, len(json.loads(p.read_text())), flush=True)
            p = hl_funding(c)
            print("hl", c, "funding", len(json.loads(p.read_text())), flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
