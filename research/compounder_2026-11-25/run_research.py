"""Pre-registered compounder research (25 Nov 2026). Prints JSON results; nothing trades.

Protocol (fixed before any result was read):
  * Candidates: compounder.strategy.CANDIDATES (classic Turtle 20/10 and 55/20, daily and 4h,
    long/short and long-only). No parameter is tuned.
  * In-sample 2020-01-01 .. 2023-12-31 on the Jan-2020 top-10 coins that have Binance perps.
    Selection = best in-sample after-tax Sharpe at 1% risk.
  * Out-of-sample 2024-01-01 .. 2026-11-25 on the Jan-2024 top-10 coins (fixed ex ante).
  * Costs: Hyperliquid taker fee on every fill, slippage per side, extra stop slippage,
    actual funding history. Tax: Indian VDA rule (31.2% of each winning trade, no loss offset).
  * GO gate (out-of-sample, selected candidate, 1% risk):
      after-tax return > 0, after-tax profit factor > 1.10, >= 30 trades,
      max after-tax drawdown <= 30%, positive after tax with every cost doubled,
      and positive after tax on Hyperliquid's own candles+funding over the same window.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "algo-trading-bot"))

from compounder.backtest import Bars, RiskParams, metrics, run  # noqa: E402
from compounder.costs import HYPERLIQUID, TaxPolicy  # noqa: E402
from compounder.strategy import CANDIDATES  # noqa: E402

DATA = ROOT / "runtime" / "compounder" / "data"
IS_UNIVERSE = ["BTC", "ETH", "XRP", "BCH", "LTC", "BNB", "EOS", "XTZ", "XLM", "ADA"]
OOS_UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "TRX", "LINK"]
IS_START, IS_END = "2020-01-01", "2024-01-01"
OOS_START, OOS_END = "2024-01-01", "2026-11-26"
BAR_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000}


def ms(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def load_binance(sym: str, tf: str) -> Bars | None:
    path = DATA / f"binance_{sym}_{tf}.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    if not rows:
        return None
    now = dt.datetime.now(dt.timezone.utc).timestamp() * 1000
    rows = [r for r in rows if r[0] + BAR_MS[tf] <= now]  # completed bars only
    a = np.array([[float(x) for x in r[:5]] for r in rows])
    fund = json.loads((DATA / f"binance_{sym}_funding.json").read_text())
    ft = np.array([int(f["fundingTime"]) for f in fund], dtype=np.int64)
    fr = np.array([float(f["fundingRate"]) for f in fund])
    return Bars(sym, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], ft, fr)


def load_hl(sym: str, tf: str) -> Bars | None:
    path = DATA / f"hl_{sym}_{tf}.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    now = dt.datetime.now(dt.timezone.utc).timestamp() * 1000
    rows = [r for r in rows if int(r["t"]) + BAR_MS[tf] <= now]
    if not rows:
        return None
    t = np.array([int(r["t"]) for r in rows], dtype=np.int64)
    o = np.array([float(r["o"]) for r in rows])
    h = np.array([float(r["h"]) for r in rows])
    lo = np.array([float(r["l"]) for r in rows])
    c = np.array([float(r["c"]) for r in rows])
    fund = json.loads((DATA / f"hl_{sym}_funding.json").read_text())
    ft = np.array([int(f["time"]) for f in fund], dtype=np.int64)
    fr = np.array([float(f["fundingRate"]) for f in fund])
    return Bars(sym, t, o, h, lo, c, ft, fr)


def universe(loader, syms, tf):
    out = [loader(s, tf) for s in syms]
    return [b for b in out if b is not None]


def summarize(m: dict) -> dict:
    keys = ["trades", "win_rate", "pf_pre_tax", "pf_after_tax", "return_pre_tax", "return_after_tax",
            "cagr_after_tax", "max_dd_after_tax", "sharpe_after_tax", "fees", "slippage", "funding", "tax",
            "stops", "liquidated"]
    out = {}
    for k in keys:
        if k not in m:
            continue
        v = m[k]
        out[k] = bool(v) if isinstance(v, (bool, np.bool_)) else (int(v) if isinstance(v, (int, np.integer))
                                                               else round(float(v), 4))
    return out


def yearly(res) -> dict:
    out = {}
    t, eq = res.curve_t, res.after_tax
    prev = res.start_equity
    for year in sorted({dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year for x in t}):
        mask = np.array([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).year == year for x in t])
        last = eq[mask][-1]
        out[str(year)] = round(float(last / prev - 1), 4)
        prev = last
    return out


def main() -> None:
    risk = RiskParams(risk_fraction=0.01, max_position_leverage=1.0, max_gross_leverage=3.0)
    vda = TaxPolicy("VDA_PER_TRADE")
    report: dict = {"protocol": __doc__, "in_sample": {}, "out_of_sample": {}}

    for p in CANDIDATES:
        bars = universe(load_binance, IS_UNIVERSE, p.timeframe)
        res = run(bars, p, HYPERLIQUID, risk, tax_policy=vda, start_ms=ms(IS_START), end_ms=ms(IS_END),
                  bar_ms=BAR_MS[p.timeframe])
        report["in_sample"][p.name] = {**summarize(metrics(res)), "yearly": yearly(res)}
        print("IS", p.name, report["in_sample"][p.name], flush=True)

    selected = max(CANDIDATES, key=lambda p: report["in_sample"][p.name]["sharpe_after_tax"])
    report["selected"] = selected.name

    for p in CANDIDATES:
        bars = universe(load_binance, OOS_UNIVERSE, p.timeframe)
        res = run(bars, p, HYPERLIQUID, risk, tax_policy=vda, start_ms=ms(OOS_START), end_ms=ms(OOS_END),
                  bar_ms=BAR_MS[p.timeframe])
        row = {**summarize(metrics(res)), "yearly": yearly(res)}
        stressed = run(bars, p, HYPERLIQUID.stressed(2.0), risk, tax_policy=vda, start_ms=ms(OOS_START),
                       end_ms=ms(OOS_END), bar_ms=BAR_MS[p.timeframe])
        row["costs_x2_return_after_tax"] = round(metrics(stressed)["return_after_tax"], 4)
        for mode in ("BUSINESS_NET_ANNUAL", "NONE"):
            alt = run(bars, p, HYPERLIQUID, risk, tax_policy=TaxPolicy(mode), start_ms=ms(OOS_START),
                      end_ms=ms(OOS_END), bar_ms=BAR_MS[p.timeframe])
            row[f"return_{mode.lower()}"] = round(metrics(alt)["return_after_tax"], 4)
        hl_bars = universe(load_hl, OOS_UNIVERSE, p.timeframe)
        hl = run(hl_bars, p, HYPERLIQUID, risk, tax_policy=vda, start_ms=ms(OOS_START), end_ms=ms(OOS_END),
                 bar_ms=BAR_MS[p.timeframe])
        hm = metrics(hl)
        hl_business = run(hl_bars, p, HYPERLIQUID, risk, tax_policy=TaxPolicy("BUSINESS_NET_ANNUAL"),
                          start_ms=ms(OOS_START), end_ms=ms(OOS_END), bar_ms=BAR_MS[p.timeframe])
        hl_untaxed = run(hl_bars, p, HYPERLIQUID, risk, tax_policy=TaxPolicy("NONE"),
                         start_ms=ms(OOS_START), end_ms=ms(OOS_END), bar_ms=BAR_MS[p.timeframe])
        row["hl_venue"] = {"first_bar": dt.datetime.fromtimestamp(min(int(b.t[0]) for b in hl_bars) / 1000,
                                                                   dt.timezone.utc).date().isoformat(),
                           **summarize(hm), "yearly": yearly(hl),
                           "return_business_net_annual": round(metrics(hl_business)["return_after_tax"], 4),
                           "return_none": round(metrics(hl_untaxed)["return_after_tax"], 4)}
        report["out_of_sample"][p.name] = row
        print("OOS", p.name, json.dumps(row), flush=True)

    s = report["out_of_sample"][selected.name]
    gate = {
        "after_tax_return_positive": s["return_after_tax"] > 0,
        "pf_after_tax_gt_1_10": s["pf_after_tax"] > 1.10,
        "at_least_30_trades": s["trades"] >= 30,
        "max_dd_le_30pct": s["max_dd_after_tax"] <= 0.30,
        "costs_x2_still_positive": s["costs_x2_return_after_tax"] > 0,
        "hyperliquid_venue_positive": s["hl_venue"]["return_after_tax"] > 0,
    }
    report["gate"] = {k: bool(v) for k, v in gate.items()}
    report["verdict"] = "GO" if all(report["gate"].values()) else "NO-GO"
    out = ROOT / "research" / "compounder_2026-11-25" / "results.json"
    out.write_text(json.dumps(report, indent=1))
    print("SELECTED", selected.name, "VERDICT", report["verdict"], json.dumps(report["gate"]))


if __name__ == "__main__":
    main()
