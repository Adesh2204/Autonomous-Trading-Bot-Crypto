"""Portfolio backtest of the trend rules with fees, slippage, funding and the tax reserve.

Timeline: one step per completed bar (UTC). Inside a bar, in this order:
  1. funding events inside the bar are charged/credited to open positions;
  2. the resting hard stop is checked against the bar's range (gap-through fills at the open);
  3. at the close, channel exits are executed (market, taker);
  4. at the close, new entries are sized on after-tax equity and executed (market, taker).
Only after-tax equity (equity minus the tax reserve) is ever used to size the next trade, so
every profit is compounded net of fees, slippage, funding and tax.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .costs import TaxLedger, TaxPolicy, VenueCosts
from .sizing import RiskParams, size_order
from .strategy import (Signals, TrendParams, channel_exit, compute_signals, entry_side, initial_stop,
                       momentum_score, rotation_sides, top_by_volume, trail_stop)


@dataclass
class Bars:
    symbol: str
    t: np.ndarray       # bar open time, ms
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    funding_t: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    funding_r: np.ndarray = field(default_factory=lambda: np.empty(0))
    v: np.ndarray | None = None   # dollar (quote) volume per bar, for the monthly universe


@dataclass
class Position:
    symbol: str
    side: int
    qty: float
    entry_price: float
    entry_time: int
    stop: float
    fees: float
    funding: float = 0.0
    slippage: float = 0.0
    best: float = 0.0          # best price since entry (for the trailing stop)
    peak_profit: float = 0.0   # largest open profit seen at a bar close (USD)


@dataclass
class Trade:
    symbol: str
    side: int
    qty: float
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    gross: float
    fees: float
    funding: float
    slippage: float
    net: float
    tax: float
    reason: str
    peak_profit: float = 0.0   # best open profit before the exit (USD)


@dataclass
class Result:
    trades: list
    curve_t: np.ndarray
    equity: np.ndarray          # mark-to-market equity (before tax reserve)
    after_tax: np.ndarray       # equity minus tax reserve (what compounds)
    tax: TaxLedger
    start_equity: float
    liquidated: bool = False


def _funding_between(b: Bars, t0: int, t1: int) -> float:
    """Sum of funding rates with t0 < time <= t1."""
    if b.funding_t.size == 0:
        return 0.0
    i0 = np.searchsorted(b.funding_t, t0, side="right")
    i1 = np.searchsorted(b.funding_t, t1, side="right")
    return float(b.funding_r[i0:i1].sum())


def _unrealized(positions: dict, last_close: dict) -> float:
    return sum(pos.side * pos.qty * (last_close[s] - pos.entry_price) for s, pos in positions.items())


def _open_nets(positions: dict, last_close: dict, costs: VenueCosts) -> list[float]:
    """Net P&L of each open position if closed now at the last close (exit fee included)."""
    return [pos.side * pos.qty * (last_close[s] - pos.entry_price) - pos.fees
            - costs.fee(pos.qty * last_close[s]) + pos.funding for s, pos in positions.items()]


def run(bars: list[Bars], p: TrendParams, costs: VenueCosts, risk: RiskParams, *,
        tax_policy: TaxPolicy | None = None, start_equity: float = 1000.0,
        start_ms: int | None = None, end_ms: int | None = None, bar_ms: int = 86_400_000,
        universe_from: dict | None = None, min_notional_by_symbol: dict | None = None,
        qty_step_by_symbol: dict | None = None, guard_dd: float | None = None,
        guard_pause_days: int = 30) -> Result:
    """Run the portfolio. ``universe_from`` maps symbol -> first ms it may be traded.
    ``min_notional_by_symbol`` / ``qty_step_by_symbol`` model per-instrument venue minimums."""
    tax = TaxLedger(tax_policy or TaxPolicy())
    sigs: dict[str, Signals] = {b.symbol: compute_signals(b.h, b.lo, b.c, p) for b in bars}
    index = {b.symbol: {int(t): i for i, t in enumerate(b.t)} for b in bars}
    by_symbol = {b.symbol: b for b in bars}
    rot = p.rotation_top > 0
    dvol30 = {}
    if p.universe_size > 0:
        for b in bars:
            v = b.v if b.v is not None else np.full(len(b.c), np.nan)
            dvol30[b.symbol] = np.convolve(np.nan_to_num(v), np.ones(30) / 30.0, mode="full")[:len(v)]
            dvol30[b.symbol][:29] = np.nan
    month_universe: dict = {}
    guard_until = 0
    guard_peak = start_equity
    times = sorted({int(t) for b in bars for t in b.t})
    if start_ms is not None:
        times = [t for t in times if t >= start_ms]
    if end_ms is not None:
        times = [t for t in times if t < end_ms]

    cash = start_equity          # realized money (perp collateral)
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    curve_t, curve_eq, curve_at = [], [], []
    last_close: dict[str, float] = {}
    liquidated = False

    def close_position(pos: Position, ref: float, ts: int, reason: str, *, stop: bool) -> None:
        nonlocal cash
        slip = costs.slip(pos.symbol, stop=stop)
        fill = ref * (1 - pos.side * slip)
        notional = pos.qty * fill
        fee = costs.fee(notional)
        gross = pos.side * pos.qty * (fill - pos.entry_price)
        slip_cost = pos.qty * ref * slip
        cash += gross - fee
        net = gross - pos.fees - fee + pos.funding
        tax_change = tax.on_trade_closed(ts, net)
        trades.append(Trade(pos.symbol, pos.side, pos.qty, pos.entry_time, ts, pos.entry_price, fill, gross,
                            pos.fees + fee, pos.funding, pos.slippage + slip_cost, net, tax_change, reason,
                            pos.peak_profit))
        del positions[pos.symbol]

    for t in times:
        bar_end = t + bar_ms
        # 1-2. funding and resting stops during the bar
        for sym in list(positions):
            pos = positions[sym]
            i = index[sym].get(t)
            b = by_symbol[sym]
            if i is None:
                continue
            rate = _funding_between(b, t, bar_end)
            if rate:
                pay = -pos.side * pos.qty * b.o[i] * rate
                pos.funding += pay
                cash += pay
            if pos.side > 0 and b.lo[i] <= pos.stop:
                close_position(pos, min(b.o[i], pos.stop), bar_end, "STOP", stop=True)
            elif pos.side < 0 and b.h[i] >= pos.stop:
                close_position(pos, max(b.o[i], pos.stop), bar_end, "STOP", stop=True)

        # 3. channel exits at the close; delisted symbols are closed at their last close
        for sym in list(positions):
            pos = positions[sym]
            i = index[sym].get(t)
            b = by_symbol[sym]
            if i is None:
                if t > int(b.t[-1]):
                    close_position(pos, last_close[sym], t, "DELISTED", stop=False)
                continue
            if channel_exit(pos.side, sigs[sym], i, b.c[i]):
                close_position(pos, b.c[i], bar_end, "CHANNEL", stop=False)

        for b in bars:
            i = index[b.symbol].get(t)
            if i is not None:
                last_close[b.symbol] = float(b.c[i])

        for sym, pos in positions.items():   # trailing stop, effective from the next bar
            i = index[sym].get(t)
            if i is None:
                continue
            b = by_symbol[sym]
            pos.best = max(pos.best, float(b.h[i])) if pos.side > 0 else min(pos.best, float(b.lo[i]))
            pos.peak_profit = max(pos.peak_profit, pos.side * pos.qty * (last_close[sym] - pos.entry_price))
            if p.trail_atr > 0:
                pos.stop = trail_stop(pos.side, pos.stop, pos.best, float(sigs[sym].atr[i]), p.trail_atr)

        equity = cash + _unrealized(positions, last_close)
        tradable = equity - tax.reserve - tax.pending_on(bar_end, _open_nets(positions, last_close, costs))
        gross_now = sum(pos.qty * last_close[s] for s, pos in positions.items())
        # cross-margin liquidation check (maintenance ~ half of initial at the setting)
        if gross_now > 0 and equity < 0.5 * gross_now / risk.leverage_setting:
            for s in list(positions):
                close_position(positions[s], last_close[s], bar_end, "LIQUIDATION", stop=True)
            liquidated = True

        # account equity guard: a fall of guard_dd from the peak closes everything and pauses entries
        if guard_dd:
            at_now = equity - tax.reserve - tax.pending_on(bar_end, _open_nets(positions, last_close, costs))
            guard_peak = max(guard_peak, at_now)
            if t >= guard_until and at_now < guard_peak * (1 - guard_dd):
                for s2 in list(positions):
                    close_position(positions[s2], last_close[s2], bar_end, "EQUITY_GUARD", stop=False)
                guard_until = bar_end + guard_pause_days * 86_400_000
                equity = cash
                tradable = equity - tax.reserve
                gross_now = 0.0
                guard_peak = tradable
        allowed = None
        if rot:
            month = int(t // (30 * 86_400_000))
            if p.universe_size > 0 and month not in month_universe:
                vols = {}
                for b in bars:
                    i = index[b.symbol].get(t)
                    vols[b.symbol] = float(dvol30[b.symbol][i]) if i is not None and i >= p.warmup else float("nan")
                month_universe[month] = top_by_volume(vols, p.universe_size)
            scores = {}
            for b in bars:
                i = index[b.symbol].get(t)
                eligible = p.universe_size <= 0 or b.symbol in month_universe.get(month, set())
                scores[b.symbol] = (momentum_score(b.c, i, p.rotation_lookback)
                                    if i is not None and eligible else float("nan"))
            allowed = rotation_sides(scores, p.rotation_top)

        # 4. entries
        if not liquidated and tradable > 0 and t >= guard_until:
            for b in bars:
                sym = b.symbol
                if sym in positions:
                    continue
                if universe_from is not None and (sym not in universe_from or t < universe_from[sym]):
                    continue
                i = index[sym].get(t)
                if i is None or i < p.warmup:
                    continue
                side = entry_side(sigs[sym], i, b.c[i], p)
                if side == 0 or (allowed is not None and side not in allowed.get(sym, set())):
                    continue
                ref = float(b.c[i])
                slip = costs.slip(sym)
                fill = ref * (1 + side * slip)
                stop = initial_stop(side, fill, float(sigs[sym].atr[i]), p)
                open_risk = sum(max(0.0, q.side * q.qty * (last_close[s2] - q.stop)) for s2, q in positions.items())
                qty = size_order(tradable, fill, stop, gross_now, risk,
                                 (min_notional_by_symbol or {}).get(sym, costs.min_notional),
                                 qty_step=(qty_step_by_symbol or {}).get(sym), open_risk=open_risk)
                if qty <= 0:
                    continue
                fee = costs.fee(qty * fill)
                cash -= fee
                positions[sym] = Position(sym, side, qty, fill, bar_end, stop, fee, 0.0, qty * ref * slip, fill)
                gross_now += qty * fill

        equity = cash + _unrealized(positions, last_close)
        curve_t.append(bar_end)
        curve_eq.append(equity)
        curve_at.append(equity - tax.reserve - tax.pending_on(bar_end, _open_nets(positions, last_close, costs)))
        if liquidated:
            break

    if positions:  # mark open positions out at the last close (for reporting)
        for s in list(positions):
            close_position(positions[s], last_close[s], curve_t[-1], "END", stop=False)
        curve_eq[-1] = cash
        curve_at[-1] = cash - tax.reserve
    return Result(trades, np.array(curve_t), np.array(curve_eq), np.array(curve_at), tax, start_equity, liquidated)


def metrics(res: Result) -> dict:
    tr = res.trades
    eq = res.after_tax
    if len(eq) == 0:
        return {"trades": 0}
    peak = np.maximum.accumulate(np.concatenate([[res.start_equity], eq]))
    dd = 1 - np.concatenate([[res.start_equity], eq]) / peak
    years = max((res.curve_t[-1] - res.curve_t[0]) / (365.25 * 86_400_000), 1e-9)
    final_pre = res.equity[-1]
    final_at = eq[-1]
    rets = np.diff(np.concatenate([[res.start_equity], eq])) / np.concatenate([[res.start_equity], eq])[:-1]
    per_year = 365.25 * 86_400_000 / max(np.median(np.diff(res.curve_t)) if len(res.curve_t) > 1 else 86_400_000, 1)
    sharpe = float(np.mean(rets) / np.std(rets) * math.sqrt(per_year)) if np.std(rets) > 0 else 0.0
    wins = [x.net for x in tr if x.net > 0]
    losses = [x.net for x in tr if x.net <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    after_tax_win = gross_win - sum(x.tax for x in tr if x.tax > 0)
    return {
        "trades": len(tr),
        "win_rate": len(wins) / len(tr) if tr else 0.0,
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "pf_pre_tax": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "pf_after_tax": after_tax_win / gross_loss if gross_loss > 0 else float("inf"),
        "return_pre_tax": final_pre / res.start_equity - 1,
        "return_after_tax": final_at / res.start_equity - 1,
        "cagr_after_tax": (final_at / res.start_equity) ** (1 / years) - 1 if final_at > 0 else -1.0,
        "max_dd_after_tax": float(dd.max()),
        "sharpe_after_tax": sharpe,
        "fees": sum(x.fees for x in tr),
        "slippage": sum(x.slippage for x in tr),
        "funding": sum(x.funding for x in tr),
        "tax": res.tax.total_tax,
        "years": years,
        "liquidated": res.liquidated,
        "stops": sum(1 for x in tr if x.reason == "STOP"),
    }
