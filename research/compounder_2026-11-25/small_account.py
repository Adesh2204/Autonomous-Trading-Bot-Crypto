"""What the Rs 1,000 practice profile would have done, 2024-01-01 .. 2026-11-25 (research only).

Same rules as the Rs 1,000 practice bots: D55_20_LS, 2% risk, venue-minimum orders allowed when
their stop risk is <= 20% of equity, all open stop risks <= 40%, gross <= 5x, 10x setting.
Per-coin minimums/steps are today's venue values (Hyperliquid $10; CoinDCX $60 BTC, $24 ETH/LINK,
$6 others; Delta India one contract). CoinDCX and Delta use Binance prices and funding as the
proxy (CoinDCX's published funding rate equals Binance's). Prints JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "algo-trading-bot"))

from risk_scan import block_bootstrap  # noqa: E402
from run_research import OOS_END, OOS_START, OOS_UNIVERSE, load_binance, load_hl, ms, universe  # noqa: E402
from compounder.backtest import metrics, run  # noqa: E402
from compounder.costs import COINDCX_FUTURES, DELTA_INDIA, HYPERLIQUID, TaxPolicy  # noqa: E402
from compounder.sizing import RiskParams  # noqa: E402
from compounder.strategy import CANDIDATES  # noqa: E402

USD_INR = 105.13
START = round(1000 / USD_INR, 2)
SMALL = RiskParams(0.02, 3.0, 5.0, 10.0, min_size_max_risk=0.20, max_open_risk=0.40)
HL_STEPS = {"BTC": 1e-5, "ETH": 1e-4, "SOL": 0.01, "AVAX": 0.01, "BNB": 0.001, "DOGE": 1.0, "LINK": 0.1,
            "XRP": 1.0, "TRX": 1.0, "ADA": 1.0}
DCX_MIN = {"BTC": 60.0, "ETH": 24.0, "LINK": 24.0}
DCX_STEPS = {"BTC": 0.001, "ETH": 0.001, "BNB": 0.01, "SOL": 0.01, "XRP": 0.1, "ADA": 1.0, "AVAX": 1.0,
             "DOGE": 1.0, "TRX": 1.0, "LINK": 0.01}
DELTA_STEPS = {"BTC": 0.001, "ETH": 0.01, "BNB": 0.1, "SOL": 1.0, "XRP": 1.0, "ADA": 1.0, "AVAX": 1.0,
               "DOGE": 100.0, "TRX": 1.0, "LINK": 1.0}

VENUES = {
    "hyperliquid": (load_hl, HYPERLIQUID, None, HL_STEPS),
    "coindcx": (load_binance, COINDCX_FUTURES, {s: DCX_MIN.get(s, 6.0) for s in OOS_UNIVERSE}, DCX_STEPS),
    "delta_india": (load_binance, DELTA_INDIA, None, DELTA_STEPS),
}


def main() -> None:
    p = next(c for c in CANDIDATES if c.name == "D55_20_LS")
    out = {}
    for venue, (loader, costs, mins, steps) in VENUES.items():
        bars = universe(loader, OOS_UNIVERSE, "1d")
        row = {}
        for mode in ("VDA_PER_TRADE", "BUSINESS_NET_ANNUAL"):
            res = run(bars, p, costs, SMALL, tax_policy=TaxPolicy(mode), start_equity=START,
                      start_ms=ms(OOS_START), end_ms=ms(OOS_END), min_notional_by_symbol=mins,
                      qty_step_by_symbol=steps)
            m = metrics(res)
            low = float(np.min(res.after_tax))
            row[mode] = {"end_inr": round(res.after_tax[-1] * USD_INR), "lowest_inr": round(low * USD_INR),
                         "highest_inr": round(float(np.max(res.after_tax)) * USD_INR),
                         "return": round(m["return_after_tax"], 4), "max_dd": round(m["max_dd_after_tax"], 4),
                         "trades": m["trades"], "win_rate": round(m["win_rate"], 3),
                         "coins_traded": sorted({t.symbol for t in res.trades})}
            if mode == "VDA_PER_TRADE":
                eq = np.concatenate([[res.start_equity], res.after_tax])
                rets = np.diff(eq) / eq[:-1]
                row["chance_up"] = {k: round(float((block_bootstrap(rets, d) > 0).mean()), 3)
                                    for k, d in (("2_weeks", 14), ("1_month", 30), ("3_months", 91))}
        out[venue] = row
        print(venue, json.dumps(row), flush=True)
    (HERE / "small_account_results.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
