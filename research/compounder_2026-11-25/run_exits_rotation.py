"""Pre-registered test of "lock profit near the peak" and "pick the right coins" (25 Nov 2026).

Fixed before any result was read; nothing is tuned after:
  BASE   D55_20_LS on the ten core coins (the current daily plan)
  X3     BASE + chandelier trailing stop 3 x ATR(20) from the best price since entry (never loosens)
  X2     BASE + chandelier trailing stop 2 x ATR(20)
  G20    BASE + account guard: after-tax equity 20% below its peak -> close everything, no entries 30 days
  R      coin rotation on a 61-coin pool (delisted coins included where Binance still serves history):
         every 30 days keep the 20 most-traded coins (30-day dollar volume); longs only in the 5 with the
         strongest 90-day risk-adjusted momentum (score > 0), shorts only in the 5 weakest (score < 0);
         entries/exits are the same 55/20 breakout rules
  R_X3   R + 3 ATR trailing stop
  R_X2   R + 2 ATR trailing stop
Data: Binance daily candles + funding (CoinDCX futures use Binance prices and funding). Costs: CoinDCX
taker 0.05% + 18% GST, slippage 3/6/12 bps (+8 on stops). Tax: 31.2% of each winning trade, no offset.
In-sample 2020-01-01..2023-12-31 selects one variant by after-tax Sharpe ($1,000, 1% risk).
Adoption rule: the selected variant replaces BASE only if, out of sample (2024-01-01..now), its
after-tax return is >= BASE's and its max after-tax drawdown is at most 5 points worse.
Also reported for every variant: the Rs 1,000 CoinDCX profile out of sample, and how much of each
trade's best open profit was kept at the exit.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "algo-trading-bot"))

from run_research import ms, summarize  # noqa: E402
from small_account import SMALL, USD_INR  # noqa: E402
from compounder.backtest import Bars, metrics, run  # noqa: E402
from compounder.costs import COINDCX_FUTURES, TaxPolicy  # noqa: E402
from compounder.sizing import RiskParams  # noqa: E402
from compounder.strategy import TrendParams  # noqa: E402

DATA = HERE.parents[1] / "runtime" / "compounder" / "data"
CORE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "TRX", "LINK"]
POOL = json.loads((HERE / "pool.json").read_text())
DCX = json.loads((HERE / "coindcx_minimums.json").read_text())   # coin -> [min_notional, qty_step]
START_RS = round(1000 / 106.0, 2)

BASE = TrendParams("BASE", "1d", 55, 20, 20, 2.0, True)
VARIANTS = {
    "BASE": (BASE, CORE, None),
    "X3": (dataclasses.replace(BASE, name="X3", trail_atr=3.0), CORE, None),
    "X2": (dataclasses.replace(BASE, name="X2", trail_atr=2.0), CORE, None),
    "G20": (dataclasses.replace(BASE, name="G20"), CORE, 0.20),
    "R": (dataclasses.replace(BASE, name="R", rotation_top=5, rotation_lookback=90, universe_size=20), POOL, None),
    "R_X3": (dataclasses.replace(BASE, name="R_X3", trail_atr=3.0, rotation_top=5, rotation_lookback=90,
                                 universe_size=20), POOL, None),
    "R_X2": (dataclasses.replace(BASE, name="R_X2", trail_atr=2.0, rotation_top=5, rotation_lookback=90,
                                 universe_size=20), POOL, None),
}


def load(sym: str) -> Bars | None:
    path = DATA / f"binance_{sym}_1d.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    now = dt.datetime.now(dt.timezone.utc).timestamp() * 1000
    rows = [r for r in rows if r[0] + 86_400_000 <= now]
    if len(rows) < 120:
        return None
    a = np.array([[float(x) for x in r[:5]] + [float(r[7])] for r in rows])
    fpath = DATA / f"binance_{sym}_funding.json"
    fund = json.loads(fpath.read_text()) if fpath.exists() else []
    return Bars(sym, a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4],
                np.array([int(f["fundingTime"]) for f in fund], dtype=np.int64),
                np.array([float(f["fundingRate"]) for f in fund]), v=a[:, 5])


def kept_share(trades) -> float:
    """Of the best open profit reached by winning trades, the share actually kept at exit."""
    peak = sum(t.peak_profit for t in trades if t.peak_profit > 0)
    kept = sum(max(0.0, t.gross) for t in trades if t.peak_profit > 0)
    return round(kept / peak, 3) if peak > 0 else 0.0


def path_inr(res) -> dict:
    inr = res.after_tax * USD_INR * (1000 / (START_RS * USD_INR))
    t = res.curve_t
    day = lambda k: dt.datetime.fromtimestamp(t[k] / 1000, dt.timezone.utc).date()
    out = {"peak": round(float(inr.max())), "peak_date": day(int(inr.argmax())).isoformat(),
           "lowest": round(float(inr.min())), "end": round(float(inr[-1]))}
    for y in (2024, 2025):
        idx = [k for k in range(len(t)) if day(k).year == y]
        if idx:
            out[f"end_{y}"] = round(float(inr[idx[-1]]))
    first2k = next((k for k in range(len(inr)) if inr[k] >= 2000), None)
    out["first_2000"] = day(first2k).isoformat() if first2k is not None else None
    return out


def main() -> None:
    cache = {}
    def bars_for(syms):
        out = []
        for s in syms:
            if s not in cache:
                cache[s] = load(s)
            if cache[s] is not None:
                out.append(cache[s])
        return out

    risk = RiskParams(0.01, 1.0, 3.0, 5.0)
    vda = TaxPolicy("VDA_PER_TRADE")
    report = {"protocol": __doc__, "in_sample": {}, "out_of_sample": {}, "rs1000": {}}
    for name, (p, syms, guard) in VARIANTS.items():
        res = run(bars_for(syms), p, COINDCX_FUTURES, risk, tax_policy=vda, start_ms=ms("2020-01-01"),
                  end_ms=ms("2024-01-01"), guard_dd=guard)
        report["in_sample"][name] = summarize(metrics(res))
        print("IS", name, json.dumps(report["in_sample"][name]), flush=True)
    selected = max(VARIANTS, key=lambda n: report["in_sample"][n]["sharpe_after_tax"])
    report["selected"] = selected
    for name, (p, syms, guard) in VARIANTS.items():
        b = bars_for(syms)
        res = run(b, p, COINDCX_FUTURES, risk, tax_policy=vda, start_ms=ms("2024-01-01"), end_ms=ms("2026-11-26"),
                  guard_dd=guard)
        row = {**summarize(metrics(res)), "kept_of_peak_profit": kept_share(res.trades)}
        report["out_of_sample"][name] = row
        mins = {s: (DCX.get(s, [6.0, None])[0]) for s in syms}
        steps = {s: DCX[s][1] for s in syms if s in DCX and DCX[s][1]}
        small = run(b, p, COINDCX_FUTURES, dataclasses.replace(SMALL), tax_policy=vda, start_equity=START_RS,
                    start_ms=ms("2024-01-01"), end_ms=ms("2026-11-26"), guard_dd=guard,
                    min_notional_by_symbol=mins, qty_step_by_symbol=steps)
        report["rs1000"][name] = {**path_inr(small), "trades": len(small.trades),
                                  "kept_of_peak_profit": kept_share(small.trades),
                                  "coins": sorted({t.symbol for t in small.trades})}
        print("OOS", name, json.dumps(row), "RS1000", json.dumps(report["rs1000"][name]), flush=True)
    base, sel = report["out_of_sample"]["BASE"], report["out_of_sample"][selected]
    adopt = (selected != "BASE" and sel["return_after_tax"] >= base["return_after_tax"]
             and sel["max_dd_after_tax"] <= base["max_dd_after_tax"] + 0.05)
    report["adopt"] = selected if adopt else "BASE"
    (HERE / "exits_rotation_results.json").write_text(json.dumps(report, indent=1))
    print("SELECTED", selected, "ADOPT", report["adopt"])


if __name__ == "__main__":
    main()
