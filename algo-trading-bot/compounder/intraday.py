"""Intraday (day-trading) rules: trade with the day's market direction, flat every night.

Shared by the backtest (``run_intraday``) and the 24/7 runner (``IntradayRunner`` in runner.py).
All times are UTC; one trading day = 00:00-24:00 UTC (05:30-05:30 IST).

Market direction ("regime") for day D: the close of day D-1 versus its SMA(``regime_sma``) of
daily closes (built from the hourly bars). Above -> only longs that day; below -> only shorts.
``regime_sma = 0`` switches the filter off (both directions every day).

Kinds (pre-registered 25 Nov 2026, nothing tuned):
  ORB  opening-range breakout: the range is the first ``or_bars`` hourly bars of the day; enter at
       the close of the first later bar that closes beyond it in the regime direction; stop at the
       other side of the range.
  DON  hourly Donchian breakout: close beyond the prior ``entry_n``-bar high/low in the regime
       direction; stop ``stop_atr`` x ATR(``atr_n``); early exit on the opposite ``exit_n``-bar
       channel.
Both: at most one entry per coin per day, no entry on bars closing after ``last_entry_hour``,
every position closed at the close of the 23:00 bar, stop distance must lie in
[``min_stop``, ``max_stop``] or the trade is skipped.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .backtest import Position, Result, Trade, _funding_between, _open_nets, _unrealized
from .costs import TaxLedger, TaxPolicy, VenueCosts
from .indicators import prior_max, prior_min, wilder_atr
from .sizing import RiskParams, size_order

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


@dataclass(frozen=True)
class IntradayParams:
    name: str
    kind: str                  # "ORB" or "DON"
    timeframe: str = "1h"
    or_bars: int = 4
    entry_n: int = 24
    exit_n: int = 12
    atr_n: int = 24
    stop_atr: float = 2.0
    regime_sma: int = 20
    last_entry_hour: int = 20
    min_stop: float = 0.002
    max_stop: float = 0.05
    allow_short: bool = True

    @property
    def history_bars(self) -> int:
        return max(24 * (self.regime_sma + 3), self.entry_n + self.atr_n + 5, 72)


INTRADAY_CANDIDATES = (
    IntradayParams("ID_ORB4_REGIME", "ORB"),
    IntradayParams("ID_DON24_REGIME", "DON"),
    IntradayParams("ID_DON24_BOTH", "DON", regime_sma=0),
)


def intraday_arrays(t, h, lo, c, p: IntradayParams) -> dict:
    """Per-bar arrays; index i uses only bars 0..i (bar i completed)."""
    t = np.asarray(t, dtype=np.int64)
    h = np.asarray(h, dtype=float)
    lo = np.asarray(lo, dtype=float)
    c = np.asarray(c, dtype=float)
    n = len(c)
    day = t // DAY_MS
    hour = (t % DAY_MS) // HOUR_MS
    # daily closes from complete days only (the 23:00 bar closes the day)
    regime = np.zeros(n)
    if p.regime_sma > 0:
        closes = {}
        for i in range(n):
            if hour[i] == 23:
                closes[int(day[i])] = c[i]
        days = sorted(closes)
        vals = np.array([closes[d] for d in days])
        sig = {}
        for k in range(p.regime_sma - 1, len(days)):
            sma = vals[k - p.regime_sma + 1:k + 1].mean()
            # only valid for the next day if the calendar is contiguous
            sig[days[k] + 1] = 1.0 if vals[k] > sma else (-1.0 if vals[k] < sma else 0.0)
        regime = np.array([sig.get(int(d), 0.0) for d in day])
    or_hi = np.full(n, np.nan)
    or_lo = np.full(n, np.nan)
    if p.kind == "ORB":
        cur_day, hi, lw, cnt = None, -np.inf, np.inf, 0
        for i in range(n):
            if day[i] != cur_day:
                cur_day, hi, lw, cnt = day[i], -np.inf, np.inf, 0
            if hour[i] < p.or_bars:
                hi, lw, cnt = max(hi, h[i]), min(lw, lo[i]), cnt + 1
            elif cnt == p.or_bars:
                or_hi[i], or_lo[i] = hi, lw
    return {
        "t": t, "c": c, "day": day, "hour": hour, "regime": regime, "or_hi": or_hi, "or_lo": or_lo,
        "atr": wilder_atr(h, lo, c, p.atr_n),
        "don_hi": prior_max(h, p.entry_n), "don_lo": prior_min(lo, p.entry_n),
        "ex_hi": prior_max(h, p.exit_n), "ex_lo": prior_min(lo, p.exit_n),
    }


def entry_decision(a: dict, i: int, p: IntradayParams) -> tuple[int, float | None]:
    """(side, stop) for completed bar i, or (0, None). The caller enforces one entry per day."""
    if a["hour"][i] + 1 > p.last_entry_hour or a["hour"][i] == 23:
        return 0, None
    close = a["c"][i]
    regime = a["regime"][i]
    want_long = regime > 0 if p.regime_sma > 0 else True
    want_short = (regime < 0 if p.regime_sma > 0 else True) and p.allow_short
    side, stop = 0, None
    if p.kind == "ORB":
        hi, lw = a["or_hi"][i], a["or_lo"][i]
        if not (np.isfinite(hi) and np.isfinite(lw)):
            return 0, None
        if want_long and close > hi:
            side, stop = 1, lw
        elif want_short and close < lw:
            side, stop = -1, hi
    else:
        up, dn, atr = a["don_hi"][i], a["don_lo"][i], a["atr"][i]
        if not (np.isfinite(up) and np.isfinite(dn) and np.isfinite(atr)) or atr <= 0:
            return 0, None
        if want_long and close > up:
            side, stop = 1, close - p.stop_atr * atr
        elif want_short and close < dn:
            side, stop = -1, close + p.stop_atr * atr
    if side == 0:
        return 0, None
    dist = abs(close - stop) / close
    if dist < p.min_stop or dist > p.max_stop:
        return 0, None
    return side, float(stop)


def exit_decision(a: dict, i: int, side: int, p: IntradayParams) -> str | None:
    if a["hour"][i] == 23:
        return "END_OF_DAY"
    if p.kind == "DON":
        if side > 0 and np.isfinite(a["ex_lo"][i]) and a["c"][i] < a["ex_lo"][i]:
            return "CHANNEL"
        if side < 0 and np.isfinite(a["ex_hi"][i]) and a["c"][i] > a["ex_hi"][i]:
            return "CHANNEL"
    return None


def run_intraday(bars: list, p: IntradayParams, costs: VenueCosts, risk: RiskParams, *,
                 tax_policy: TaxPolicy | None = None, start_equity: float = 1000.0,
                 start_ms: int | None = None, end_ms: int | None = None,
                 min_notional_by_symbol: dict | None = None, qty_step_by_symbol: dict | None = None) -> Result:
    tax = TaxLedger(tax_policy or TaxPolicy())
    arrs = {b.symbol: intraday_arrays(b.t, b.h, b.lo, b.c, p) for b in bars}
    index = {b.symbol: {int(x): k for k, x in enumerate(b.t)} for b in bars}
    by_symbol = {b.symbol: b for b in bars}
    times = sorted({int(x) for b in bars for x in b.t})
    times = [x for x in times if (start_ms is None or x >= start_ms) and (end_ms is None or x < end_ms)]
    cash = start_equity
    positions: dict[str, Position] = {}
    entered: dict[str, int] = {}
    trades: list[Trade] = []
    curve_t, curve_eq, curve_at = [], [], []
    last_close: dict[str, float] = {}

    def close(pos: Position, ref: float, ts: int, reason: str, stop: bool) -> None:
        nonlocal cash
        slip = costs.slip(pos.symbol, stop=stop)
        fill = ref * (1 - pos.side * slip)
        fee = costs.fee(pos.qty * fill)
        gross = pos.side * pos.qty * (fill - pos.entry_price)
        cash += gross - fee
        net = gross - pos.fees - fee + pos.funding
        taxed = tax.on_trade_closed(ts, net)
        trades.append(Trade(pos.symbol, pos.side, pos.qty, pos.entry_time, ts, pos.entry_price, fill, gross,
                            pos.fees + fee, pos.funding, pos.slippage + pos.qty * ref * slip, net, taxed, reason))
        del positions[pos.symbol]

    for t in times:
        end = t + HOUR_MS
        for sym in list(positions):
            pos, b = positions[sym], by_symbol[sym]
            i = index[sym].get(t)
            if i is None:
                continue
            rate = _funding_between(b, t, end)
            if rate:
                pay = -pos.side * pos.qty * float(b.o[i]) * rate
                pos.funding += pay
                cash += pay
            if pos.side > 0 and b.lo[i] <= pos.stop:
                close(pos, min(float(b.o[i]), pos.stop), end, "STOP", True)
            elif pos.side < 0 and b.h[i] >= pos.stop:
                close(pos, max(float(b.o[i]), pos.stop), end, "STOP", True)
        for sym in list(positions):
            i = index[sym].get(t)
            if i is None:
                continue
            reason = exit_decision(arrs[sym], i, positions[sym].side, p)
            if reason:
                close(positions[sym], float(by_symbol[sym].c[i]), end, reason, False)
        for b in bars:
            i = index[b.symbol].get(t)
            if i is not None:
                last_close[b.symbol] = float(b.c[i])
        equity = cash + _unrealized(positions, last_close)
        tradable = equity - tax.reserve - tax.pending_on(end, _open_nets(positions, last_close, costs))
        gross = sum(q.qty * last_close[s] for s, q in positions.items())
        if tradable > 0:
            for b in bars:
                sym = b.symbol
                i = index[sym].get(t)
                if i is None or sym in positions or entered.get(sym) == int(arrs[sym]["day"][i]):
                    continue
                side, stop_lvl = entry_decision(arrs[sym], i, p)
                if side == 0:
                    continue
                ref = float(b.c[i])
                slip = costs.slip(sym)
                fill = ref * (1 + side * slip)
                stop = stop_lvl if (side > 0 and stop_lvl < fill) or (side < 0 and stop_lvl > fill) else None
                if stop is None:
                    continue
                open_risk = sum(max(0.0, q.side * q.qty * (last_close[s] - q.stop)) for s, q in positions.items())
                qty = size_order(tradable, fill, stop, gross, risk,
                                 (min_notional_by_symbol or {}).get(sym, costs.min_notional),
                                 qty_step=(qty_step_by_symbol or {}).get(sym), open_risk=open_risk)
                if qty <= 0:
                    continue
                fee = costs.fee(qty * fill)
                cash -= fee
                positions[sym] = Position(sym, side, qty, fill, end, stop, fee, 0.0, qty * ref * slip)
                entered[sym] = int(arrs[sym]["day"][i])
                gross += qty * fill
        equity = cash + _unrealized(positions, last_close)
        curve_t.append(end)
        curve_eq.append(equity)
        curve_at.append(equity - tax.reserve - tax.pending_on(end, _open_nets(positions, last_close, costs)))
    for s in list(positions):
        close(positions[s], last_close[s], curve_t[-1], "END", False)
    if curve_t:
        curve_eq[-1] = cash
        curve_at[-1] = cash - tax.reserve
    return Result(trades, np.array(curve_t), np.array(curve_eq), np.array(curve_at), tax, start_equity, False)
