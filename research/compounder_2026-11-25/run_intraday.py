"""Pre-registered intraday (day-trading) research, 25 Nov 2026. Prints JSON; nothing trades.

Protocol, fixed before any intraday result was read:
  * Candidates: compounder.intraday.INTRADAY_CANDIDATES (opening-range breakout with the daily
    market direction; hourly Donchian breakout with and without the direction filter). Flat every
    day by 00:00 UTC, one entry per coin per day. Nothing tuned.
  * Data: Binance USD-M hourly candles and funding (CoinDCX futures use Binance prices and publish
    Binance's funding rate). Ten coins: BTC ETH BNB SOL XRP ADA AVAX DOGE TRX LINK.
  * In-sample 2022-01-01 .. 2023-12-31 (selection: best after-tax Sharpe at 1% risk);
    out-of-sample 2024-01-01 .. 2026-11-25 (the test).
  * Costs: CoinDCX taker 0.05% + 18% GST per fill, slippage 3/6/12 bps per side (+8 bps on stops),
    actual funding. Tax: 31.2% of each profitable trade, losses not offset.
  * Gate (out-of-sample, selected candidate): after-tax return > 0, after-tax profit factor > 1.10,
    >= 30 trades, max after-tax drawdown <= 30%, still positive with every cost doubled.
  * Also reported: the Rs 1,000 profile (2% risk, venue-minimum orders when their stop risk is
    <= 20%, open risk <= 40%, CoinDCX per-coin minimums).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "algo-trading-bot"))

from run_research import ms, summarize, yearly  # noqa: E402
from small_account import DCX_MIN, DCX_STEPS, SMALL, START, USD_INR  # noqa: E402
from compounder.backtest import Bars, metrics  # noqa: E402
from compounder.costs import COINDCX_FUTURES, TaxPolicy  # noqa: E402
from compounder.intraday import INTRADAY_CANDIDATES, run_intraday  # noqa: E402
from compounder.sizing import RiskParams  # noqa: E402

DATA = HERE.parents[1] / "runtime" / "compounder" / "data"
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "TRX", "LINK"]


def load_hourly(sym: str) -> Bars:
    rows = json.loads((DATA / f"binance_{sym}_1h.json").read_text())
    now = dt.datetime.now(dt.timezone.utc).timestamp() * 1000
    rows = [r for r in rows if r[0] + 3_600_000 <= now]
    a = np.array([[float(x) for x in r[:5]] for r in rows])
    fund = json.loads((DATA / f"binance_{sym}_funding.json").read_text())
    return Bars(sym, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4],
                np.array([int(f["fundingTime"]) for f in fund], dtype=np.int64),
                np.array([float(f["fundingRate"]) for f in fund]))


def main() -> None:
    bars = [load_hourly(s) for s in COINS]
    risk = RiskParams(0.01, 1.0, 3.0, 5.0)
    vda = TaxPolicy("VDA_PER_TRADE")
    report = {"protocol": __doc__, "in_sample": {}, "out_of_sample": {}, "rs1000": {}}
    for p in INTRADAY_CANDIDATES:
        res = run_intraday(bars, p, COINDCX_FUTURES, risk, tax_policy=vda, start_ms=ms("2022-01-01"),
                           end_ms=ms("2024-01-01"))
        report["in_sample"][p.name] = {**summarize(metrics(res)), "yearly": yearly(res)}
        print("IS", p.name, json.dumps(report["in_sample"][p.name]), flush=True)
    selected = max(INTRADAY_CANDIDATES, key=lambda p: report["in_sample"][p.name]["sharpe_after_tax"])
    report["selected"] = selected.name
    for p in INTRADAY_CANDIDATES:
        res = run_intraday(bars, p, COINDCX_FUTURES, risk, tax_policy=vda, start_ms=ms("2024-01-01"),
                           end_ms=ms("2026-11-26"))
        row = {**summarize(metrics(res)), "yearly": yearly(res)}
        for mode in ("NONE", "BUSINESS_NET_ANNUAL"):
            alt = run_intraday(bars, p, COINDCX_FUTURES, risk, tax_policy=TaxPolicy(mode),
                               start_ms=ms("2024-01-01"), end_ms=ms("2026-11-26"))
            row[f"return_{mode.lower()}"] = round(float(metrics(alt)["return_after_tax"]), 4)
        x2 = run_intraday(bars, p, COINDCX_FUTURES.stressed(2.0), risk, tax_policy=vda,
                          start_ms=ms("2024-01-01"), end_ms=ms("2026-11-26"))
        row["costs_x2_return_after_tax"] = round(float(metrics(x2)["return_after_tax"]), 4)
        small = run_intraday(bars, p, COINDCX_FUTURES, SMALL, tax_policy=vda, start_equity=START,
                             start_ms=ms("2024-01-01"), end_ms=ms("2026-11-26"),
                             min_notional_by_symbol={s: DCX_MIN.get(s, 6.0) for s in COINS},
                             qty_step_by_symbol=DCX_STEPS)
        sm = metrics(small)
        report["rs1000"][p.name] = {"end_inr": round(float(small.after_tax[-1]) * USD_INR),
                                    "lowest_inr": round(float(np.min(small.after_tax)) * USD_INR),
                                    "highest_inr": round(float(np.max(small.after_tax)) * USD_INR),
                                    "trades": sm["trades"], "win_rate": round(sm["win_rate"], 3)}
        report["out_of_sample"][p.name] = row
        print("OOS", p.name, json.dumps(row), "RS1000", json.dumps(report["rs1000"][p.name]), flush=True)
    s = report["out_of_sample"][selected.name]
    gate = {"after_tax_return_positive": s["return_after_tax"] > 0, "pf_after_tax_gt_1_10": s["pf_after_tax"] > 1.10,
            "at_least_30_trades": s["trades"] >= 30, "max_dd_le_30pct": s["max_dd_after_tax"] <= 0.30,
            "costs_x2_still_positive": s["costs_x2_return_after_tax"] > 0}
    report["gate"] = {k: bool(v) for k, v in gate.items()}
    report["verdict"] = "GO" if all(report["gate"].values()) else "NO-GO"
    (HERE / "intraday_results.json").write_text(json.dumps(report, indent=1))
    print("SELECTED", selected.name, "VERDICT", report["verdict"], json.dumps(report["gate"]))


if __name__ == "__main__":
    main()
