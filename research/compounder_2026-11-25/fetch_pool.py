"""Daily klines + funding (Binance USD-M, public) for the coin-rotation pool, incl. delisted coins
(MATIC, FTM, EOS...) where Binance still serves history, to limit survivorship bias."""
import json, time
from pathlib import Path
import requests
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "runtime" / "compounder" / "data"
POOL = ["BTC","ETH","BNB","SOL","XRP","ADA","AVAX","DOGE","TRX","LINK","DOT","LTC","BCH","XLM","ATOM","ETC","FIL",
        "NEAR","UNI","AAVE","ALGO","EOS","XTZ","VET","ICP","SAND","MANA","AXS","THETA","EGLD","FTM","MATIC","CRV",
        "SUSHI","COMP","MKR","SNX","GRT","CHZ","ZEC","DASH","KSM","RUNE","INJ","1000SHIB","SUI","APT","ARB","OP",
        "1000PEPE","WLD","TIA","SEI","ENA","TAO","HYPE","WIF","JUP","ONDO","LUNA","FTT"]
s = requests.Session()
def get(url, params):
    for a in range(6):
        r = s.get(url, params=params, timeout=30)
        if r.status_code == 200: return r.json()
        if r.status_code == 400: return None
        time.sleep(4 * (a + 1))
    return None
for c in POOL:
    out = DATA / f"binance_{c}_1d.json"
    if not out.exists():
        rows, start = [], 1567296000000
        while True:
            b = get("https://fapi.binance.com/fapi/v1/klines", {"symbol": f"{c}USDT", "interval": "1d", "startTime": start, "limit": 1500})
            if not b: break
            rows += b
            if len(b) < 1500: break
            start = b[-1][0] + 86_400_000
            time.sleep(0.2)
        out.write_text(json.dumps(rows))
    fo = DATA / f"binance_{c}_funding.json"
    if not fo.exists():
        rows, start = [], 1567296000000
        while True:
            b = get("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": f"{c}USDT", "startTime": start, "limit": 1000})
            if not b: break
            rows += b
            if len(b) < 1000: break
            start = b[-1]["fundingTime"] + 1
            time.sleep(0.2)
        fo.write_text(json.dumps(rows))
    print(c, len(json.loads(out.read_text())), flush=True)
