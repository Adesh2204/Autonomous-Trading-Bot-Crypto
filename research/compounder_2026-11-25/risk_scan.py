"""Leverage/risk scan and forward-outcome bootstrap for one candidate (research only).

Usage: python risk_scan.py <CANDIDATE_NAME> [binance|hl]
Runs the out-of-sample window at several risk fractions (the knob that sets leverage) and
block-bootstraps the after-tax daily equity returns to estimate the chance of being up after
2 weeks, 1 month, 3 months and 1 year. Prints JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "algo-trading-bot"))

from run_research import BAR_MS, OOS_END, OOS_START, OOS_UNIVERSE, load_binance, load_hl, ms, universe  # noqa: E402
from compounder.backtest import RiskParams, metrics, run  # noqa: E402
from compounder.costs import HYPERLIQUID, TaxPolicy  # noqa: E402
from compounder.strategy import CANDIDATES  # noqa: E402


def block_bootstrap(daily: np.ndarray, horizon: int, n: int = 20000, block: int = 10, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    size = len(daily)
    for k in range(n):
        acc, got = 1.0, 0
        while got < horizon:
            start = rng.integers(0, size - block)
            take = min(block, horizon - got)
            acc *= np.prod(1 + daily[start:start + take])
            got += take
        out[k] = acc - 1
    return out


def main(name: str, source: str, tax_mode: str) -> None:
    p = next(c for c in CANDIDATES if c.name == name)
    loader = load_hl if source == "hl" else load_binance
    bars = universe(loader, OOS_UNIVERSE, p.timeframe)
    rows = []
    best = None
    for rf in (0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05):
        risk = RiskParams(risk_fraction=rf, max_position_leverage=3.0, max_gross_leverage=5.0, leverage_setting=10.0)
        res = run(bars, p, HYPERLIQUID, risk, tax_policy=TaxPolicy(tax_mode), start_ms=ms(OOS_START),
                  end_ms=ms(OOS_END), bar_ms=BAR_MS[p.timeframe])
        m = metrics(res)
        row = {"risk_per_trade": rf, "return_after_tax": round(m["return_after_tax"], 4),
               "cagr_after_tax": round(m["cagr_after_tax"], 4), "max_dd_after_tax": round(m["max_dd_after_tax"], 4),
               "trades": m["trades"], "liquidated": m["liquidated"]}
        rows.append(row)
        if rf == 0.01:
            best = res
        print(json.dumps(row), flush=True)
    eq = np.concatenate([[best.start_equity], best.after_tax])
    step = int(np.median(np.diff(best.curve_t)))
    per_day = max(1, 86_400_000 // step)
    daily = eq[::per_day]
    rets = np.diff(daily) / daily[:-1]
    horizons = {"2_weeks": 14, "1_month": 30, "3_months": 91, "1_year": 365}
    boot = {}
    for label, days in horizons.items():
        sims = block_bootstrap(rets, days)
        boot[label] = {"p_up": round(float((sims > 0).mean()), 3), "median": round(float(np.median(sims)), 4),
                       "p5": round(float(np.percentile(sims, 5)), 4), "p95": round(float(np.percentile(sims, 95)), 4)}
    print(json.dumps({"candidate": name, "source": source, "tax": tax_mode, "bootstrap_at_1pct_risk": boot}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "binance",
         sys.argv[3] if len(sys.argv) > 3 else "VDA_PER_TRADE")
