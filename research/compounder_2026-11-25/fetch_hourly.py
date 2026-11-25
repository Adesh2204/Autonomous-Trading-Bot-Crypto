"""Fetch Binance USD-M 1h klines from 2022-01-01 for the intraday research (public, no keys).
CoinDCX futures quote Binance-sourced prices and publish Binance's funding rate."""
import json, sys, time
from pathlib import Path
import requests
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "runtime" / "compounder" / "data"
START = 1640995200000  # 2022-01-01
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "TRX", "LINK"]
s = requests.Session()
for c in COINS:
    out = DATA / f"binance_{c}_1h.json"
    if out.exists():
        continue
    rows, start, now = [], START, int(time.time() * 1000)
    while start < now:
        for attempt in range(5):
            r = s.get("https://fapi.binance.com/fapi/v1/klines",
                      params={"symbol": f"{c}USDT", "interval": "1h", "startTime": start, "limit": 1500}, timeout=30)
            if r.status_code == 200:
                break
            time.sleep(5 * (attempt + 1))
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        start = batch[-1][0] + 3_600_000
        time.sleep(0.25)
    out.write_text(json.dumps(rows))
    print(c, len(rows), flush=True)
