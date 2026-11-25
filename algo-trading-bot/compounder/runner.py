"""24/7 runner: watches the market every ``poll_seconds`` and trades the frozen trend rules.

One loop iteration (``step``):
  1. read marks/funding for all coins (one public call);
  2. check every open position's hard stop (paper: simulated on the mark price, exactly how a
     Hyperliquid stop triggers; live: the stop rests on the exchange and fills itself), then retry
     any exit that failed earlier (live: until the exchange confirms the position is closed);
  3. charge/credit actual hourly funding to open positions;
  4. when a daily bar has completed, run exits then entries on that bar (same functions as the
     backtest), sizing every entry on after-tax equity so profits compound net of tax;
  5. apply circuit breakers (including the user's total-loss limit) and write the heartbeat.
Every money movement is journaled before the in-memory state is replaced on disk.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from decimal import Decimal
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import requests

from .brokers import Fill, OrderRefused, PaperBroker
from .costs import TaxLedger, TaxPolicy, VenueCosts
from .ledger import BotState, Journal, OpenPosition
from .market_data import BAR_MS, DataError, HyperliquidPublic
from .sizing import RiskParams, _floor_step, size_order, stop_safe_leverage
from .strategy import TrendParams, channel_exit, compute_signals, entry_side, initial_stop

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
STOP_FILL_WAIT_MS = 30 * 60_000   # live: wait this long for a stop's fills to appear before estimating them
LOSS_LIMIT_USE = 0.85             # open stop risk may use at most 85% of the room left above the loss floor
MIN_ORDER_BUFFER = 0.01           # orders stay >= 1% above the venue minimum at the actual (not estimated) price


@dataclass(frozen=True)
class RunnerConfig:
    run_dir: Path
    universe: tuple
    params: TrendParams
    risk: RiskParams
    costs: VenueCosts
    tax_policy: TaxPolicy
    start_equity: float
    mandate_hash: str = ""
    poll_seconds: float = 20.0
    history_bars: int = 300
    bar_settle_ms: int = 45_000          # wait after the close so the exchange finalizes the candle
    daily_loss_pause: float = 0.08       # after-tax equity down 8% on the UTC day -> no entries until tomorrow
    drawdown_halt: float = 0.45          # after-tax equity 45% below its peak -> no entries until a human resets
    max_consecutive_errors: int = 5
    inr_quote_url: str = "https://public.coindcx.com/market_data/current_prices"
    label: str = ""
    start_equity_inr: float | None = None
    max_total_loss_inr: float | None = None   # hard floor: start - this (after tax); None = no floor


@dataclass
class _Runtime:
    errors: int = 0
    last_status_ms: int = 0
    contexts: dict = field(default_factory=dict)
    specs: dict = field(default_factory=dict)
    inr: tuple = (0, None)


class Runner:
    def __init__(self, cfg: RunnerConfig, md: HyperliquidPublic, broker, *, clock=time.time, sleep=time.sleep):
        self.cfg = cfg
        self.md = md
        self.broker = broker
        self.clock = clock
        self.sleep = sleep
        self.journal = Journal(cfg.run_dir)
        self.rt = _Runtime()
        self.state = self._load_or_init()

    # ------------------------------------------------------------------ state
    def _load_or_init(self) -> BotState:
        st = self.journal.load()
        if st is not None:
            if st.mandate_hash != self.cfg.mandate_hash:
                raise RuntimeError("STATE_BELONGS_TO_ANOTHER_MANDATE: archive the run dir or use the same mandate")
            self.journal.event("RESUMED", positions=list(st.positions), cash=st.cash)
            return st
        now = self._now()
        st = BotState(mode=self.broker.mode, venue=self.cfg.costs.name, mandate_hash=self.cfg.mandate_hash,
                      start_equity=self.cfg.start_equity, cash=self.cfg.start_equity,
                      last_bar_processed=self._latest_completed_bar(now), last_funding_ms=now,
                      peak_after_tax=self.cfg.start_equity, day_start_after_tax=self.cfg.start_equity,
                      day_start_ms=now - now % DAY_MS)
        st.store_tax(TaxLedger(self.cfg.tax_policy))
        self.journal.save(st)
        self.journal.event("STARTED", mode=st.mode, start_equity=st.start_equity, universe=list(self.cfg.universe),
                           params=asdict(self.cfg.params), risk=asdict(self.cfg.risk), tax=asdict(self.cfg.tax_policy),
                           first_bar_to_trade=st.last_bar_processed + DAY_MS)
        return st

    def _now(self) -> int:
        return int(self.clock() * 1000)

    def _latest_completed_bar(self, now_ms: int) -> int:
        step = BAR_MS[self.cfg.params.timeframe]
        return (now_ms // step) * step - step

    # ------------------------------------------------------------------ valuation
    def _mark(self, coin: str) -> float:
        ctx = self.rt.contexts.get(coin)
        if ctx is None:
            raise DataError(f"NO_MARK:{coin}")
        return ctx.mark

    def valuation(self) -> dict:
        tax = self.state.tax_ledger()
        unrealized, open_nets = 0.0, []
        for coin, pos in self.state.open_positions().items():
            mark = self._mark(coin)
            u = pos.side * pos.qty * (mark - pos.entry_price)
            unrealized += u
            open_nets.append(u - pos.fees - self.cfg.costs.fee(pos.qty * mark) + pos.funding)
        equity = self.state.cash + unrealized
        if self.broker.mode == "LIVE":
            # exchange account value is the truth for live money (fees/funding/fills all inside it)
            equity = self.broker.account_value()
        pending = tax.pending_on(self._now(), open_nets)
        return {"equity": equity, "unrealized": unrealized, "tax_reserve": tax.reserve, "tax_pending": pending,
                "after_tax": equity - tax.reserve - pending,
                "gross": sum(p.qty * self._mark(c) for c, p in self.state.open_positions().items())}

    # ------------------------------------------------------------------ INR
    def _usd_inr(self) -> float | None:
        ts, rate = self.rt.inr
        if rate is not None and self._now() - ts < 600_000:
            return rate
        if hasattr(self.broker, "usd_inr"):
            try:
                rate = float(self.broker.usd_inr())
                self.rt.inr = (self._now(), rate)
                return rate
            except Exception:  # fall back to the public spot quote
                pass
        try:
            data = requests.get(self.cfg.inr_quote_url, timeout=8).json()
            if isinstance(data, list):   # CoinDCX INR-margin conversion endpoint
                rate = float(next(r for r in data if r.get("symbol") == "USDTINR")["conversion_price"])
            else:                        # CoinDCX public spot prices
                rate = float(data["USDTINR"])
            self.rt.inr = (self._now(), rate)
            return rate
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return rate

    # ------------------------------------------------------------------ fills -> ledger
    def _close(self, pos: OpenPosition, fill: Fill, reason: str) -> dict:
        tax = self.state.tax_ledger()
        gross = pos.side * pos.qty * (fill.price - pos.entry_price)
        net = gross - pos.fees - fill.fee + pos.funding
        # strict VDA base: price gain before fees (not deductible) + funding received
        reserved = tax.on_trade_closed(fill.time_ms, net, taxable=gross + max(0.0, pos.funding))
        self.state.cash += gross - fill.fee
        self.state.store_tax(tax)
        t = self.state.totals
        t["fees"] += fill.fee
        t["slippage"] += fill.slippage
        t["realized_net"] += net
        t["trades"] += 1
        t["wins"] += 1 if net > 0 else 0
        self.state.drop_position(pos.coin)
        inr = self._usd_inr()
        row = {"coin": pos.coin, "side": "LONG" if pos.side > 0 else "SHORT", "qty": pos.qty,
               "entry_time": pos.entry_time, "exit_time": fill.time_ms, "entry_price": pos.entry_price,
               "exit_price": fill.price, "gross_usd": gross, "fees_usd": pos.fees + fill.fee,
               "funding_usd": pos.funding, "slippage_usd": pos.slippage + fill.slippage, "net_usd": net,
               "tax_reserved_usd": reserved, "after_tax_usd": net - reserved, "reason": reason,
               "tax_mode": tax.policy.mode, "usd_inr": inr,
               "net_inr": net * inr if inr else None, "tax_reserved_inr": reserved * inr if inr else None,
               "mode": self.state.mode}
        self.journal.trade(row)
        self.journal.event("CLOSED", **row)
        self.journal.save(self.state)
        return row

    def _exit(self, coin: str, reason: str) -> dict | None:
        pos = self.state.open_positions()[coin]
        # close first, then cancel the stop: if the close fails, the exchange stop still protects
        fill = self.broker.market(coin, -pos.side, pos.qty, reduce_only=True, reason=reason)
        try:
            self.broker.cancel_stop(coin, pos.stop_order_id)
        except Exception as exc:  # the position is flat; a leftover reduce-only stop cannot open anything
            self.journal.event("STOP_CANCEL_AFTER_EXIT_FAILED", coin=coin, error=str(exc)[:300])
        return self._close(pos, fill, reason)

    def _queue_exit(self, coin: str, reason: str, error: str) -> None:
        """Remember an exit that failed; ``retry_exits`` tries it again every loop until it is done."""
        self.state.extra.setdefault("exit_retry", {})[coin] = reason
        self.journal.save(self.state)
        self.journal.event("EXIT_REFUSED", coin=coin, reason=reason, error=error[:300], will_retry=True)

    def retry_exits(self) -> None:
        retry = self.state.extra.get("exit_retry") or {}
        pending = self.state.extra.get("stop_fill_pending") or {}
        for coin in list(retry):
            if coin not in self.state.positions:
                retry.pop(coin)
                continue
            if coin in pending:
                continue   # already flat on the exchange; check_stops books its fills
            try:
                self._exit(coin, retry[coin])
            except (OrderRefused, DataError, requests.RequestException) as exc:
                self.journal.event("EXIT_RETRY_FAILED", coin=coin, error=str(exc)[:300])
                continue
            retry.pop(coin, None)
            self.journal.event("EXIT_RETRY_DONE", coin=coin)
        self.journal.save(self.state)

    # ------------------------------------------------------------------ loop pieces
    def check_stops(self) -> list:
        closed = []
        now = self._now()
        gap = now - self.state.last_stop_check_ms if self.state.last_stop_check_ms else 0
        for coin, pos in self.state.open_positions().items():
            if self.broker.mode == "PAPER" and gap > 3 * self.cfg.poll_seconds * 1000:
                # the paper runner was not watching (restart, sleep): replay the gap on 1m candles
                hit = self._stop_hit_while_away(pos, self.state.last_stop_check_ms, now)
                if hit is not None:
                    closed.append(self._close(pos, hit, "STOP_WHILE_AWAY"))
                    continue
            if self.broker.mode == "LIVE":
                row = self._check_live_stop(coin, pos, now)
                if row is not None:
                    closed.append(row)
                continue
            if self.broker.stop_triggered(coin, pos.side, pos.stop, self.rt.contexts):
                self.journal.event("STOP_TRIGGERED", coin=coin, stop=pos.stop, mark=self._mark(coin))
                fill = self.broker.market(coin, -pos.side, pos.qty, reduce_only=True, reason="STOP")
                closed.append(self._close(pos, fill, "STOP"))
        self.state.last_stop_check_ms = now
        return closed

    def _check_live_stop(self, coin: str, pos: OpenPosition, now: int) -> dict | None:
        """The exchange no longer shows the position: its stop (or an exit whose reply was lost) filled.
        Book the real fills. Fills can take a while to appear in the trade history; until then the
        loop carries on, and after STOP_FILL_WAIT_MS the exit is booked at an estimated price."""
        pending = self.state.extra.setdefault("stop_fill_pending", {})
        if not self.broker.stop_triggered(coin, pos.side, pos.stop, self.rt.contexts):
            if pending.pop(coin, None) is not None:   # the position is visible again: it was a read glitch
                self.journal.event("STOP_FILL_PENDING_CLEARED", coin=coin)
            return None
        reason = (self.state.extra.get("exit_retry") or {}).get(coin, "STOP")
        if coin not in pending:
            pending[coin] = now
            self.journal.save(self.state)
            self.journal.event("STOP_TRIGGERED", coin=coin, stop=pos.stop, mark=self._mark(coin), reason=reason)
        try:
            fill = self.broker.exit_fill_after_stop(coin, pos.side, pos.qty, pos.entry_time)
        except (DataError, requests.RequestException) as exc:
            if now - int(pending[coin]) < STOP_FILL_WAIT_MS:
                return None
            ref = pos.stop if reason == "STOP" else self._mark(coin)
            price = ref * (1 - pos.side * self.cfg.costs.slip(coin, stop=True))
            fill = Fill(coin, -pos.side, pos.qty, price, self.cfg.costs.fee(price * pos.qty), ref, now, reason)
            reason += "_ESTIMATED"
            self.journal.event("STOP_FILL_ESTIMATED", coin=coin, price=price, error=str(exc)[:300])
        else:
            if abs(fill.qty - pos.qty) > 1e-9:
                self.state.halted = "LIVE_POSITION_MISMATCH"
                self.journal.event("LIVE_POSITION_MISMATCH", coin=coin, expected=pos.qty, filled=fill.qty)
        pending.pop(coin, None)
        return self._close(pos, fill, reason)

    def _stop_hit_while_away(self, pos: OpenPosition, since_ms: int, now_ms: int) -> Fill | None:
        minutes = int(min(4900, (now_ms - since_ms) // 60_000 + 2))
        rows = [r for r in self.md.candles(pos.coin, "1m", minutes) if int(r["t"]) + 60_000 > since_ms]
        for r in rows:
            lo, hi, op = float(r["l"]), float(r["h"]), float(r["o"])
            if (pos.side > 0 and lo <= pos.stop) or (pos.side < 0 and hi >= pos.stop):
                ref = min(op, pos.stop) if pos.side > 0 else max(op, pos.stop)
                slip = self.cfg.costs.slip(pos.coin, stop=True)
                price = ref * (1 - pos.side * slip)
                self.journal.event("STOP_HIT_WHILE_AWAY", coin=pos.coin, stop=pos.stop, candle=int(r["t"]))
                return Fill(pos.coin, -pos.side, pos.qty, price, self.cfg.costs.fee(price * pos.qty), ref,
                            int(r["t"]) + 60_000, "STOP_WHILE_AWAY")
        return None

    def accrue_funding(self) -> None:
        # settle funding only for hours that ended >= 2 minutes ago (the record can lag the hour)
        now = self._now() - 120_000
        hour = now - now % HOUR_MS
        if hour <= self.state.last_funding_ms:
            return
        start = self.state.last_funding_ms
        for coin, pos in self.state.open_positions().items():
            begin = max(start, pos.entry_time)
            for ts, rate in self.broker.funding(coin, begin, hour):
                pay = -pos.side * pos.qty * self._mark(coin) * rate
                pos.funding += pay
                self.state.cash += pay
                self.state.totals["funding"] += pay
                self.journal.event("FUNDING", coin=coin, ts=ts, rate=rate, amount_usd=pay)
            self.state.put_position(pos)
        self.state.last_funding_ms = hour
        self.journal.save(self.state)

    def maybe_process_bar(self) -> bool:
        now = self._now()
        bar = self._latest_completed_bar(now)
        step = BAR_MS[self.cfg.params.timeframe]
        if bar <= self.state.last_bar_processed or now < bar + step + self.cfg.bar_settle_ms:
            return False
        self.process_bar(bar)
        return True

    def _signals_for(self, coin: str, bar: int):
        rows = self.md.candles(coin, self.cfg.params.timeframe, self.cfg.history_bars)
        if not rows or int(rows[-1]["t"]) != bar:
            return None
        h = np.array([float(r["h"]) for r in rows])
        lo = np.array([float(r["l"]) for r in rows])
        c = np.array([float(r["c"]) for r in rows])
        if len(c) <= self.cfg.params.warmup:
            return None
        return compute_signals(h, lo, c, self.cfg.params), float(c[-1]), len(c) - 1

    def process_bar(self, bar: int) -> None:
        p = self.cfg.params
        if hasattr(self.broker, "bar_hint"):
            self.broker.bar_hint = bar   # deterministic client order ids per bar and action
        signals = {}
        for coin in self.cfg.universe:
            try:
                signals[coin] = self._signals_for(coin, bar)
            except DataError as exc:
                signals[coin] = None
                self.journal.event("DATA_STALE", coin=coin, bar=bar, error=str(exc))
        # exits first
        for coin, pos in self.state.open_positions().items():
            got = signals.get(coin)
            if got is None:
                continue
            sig, close, i = got
            if channel_exit(pos.side, sig, i, close):
                try:
                    self._exit(coin, "CHANNEL")
                except (OrderRefused, DataError, requests.RequestException) as exc:
                    self._queue_exit(coin, "CHANNEL", str(exc))
        # entries on after-tax equity
        value = self.valuation()
        blocked = self.entries_blocked()
        decisions = []
        for coin in self.cfg.universe:
            got = signals.get(coin)
            if got is None or coin in self.state.positions:
                continue
            sig, close, i = got
            side = entry_side(sig, i, close, p)
            if side == 0:
                continue
            decisions.append(coin)
            if blocked:
                self.journal.event("ENTRY_SKIPPED", coin=coin, side=side, reason=blocked, bar=bar)
                continue
            try:
                self._enter(coin, side, float(sig.atr[i]), value, bar)
                value = self.valuation()
            except (OrderRefused, DataError) as exc:
                self.journal.event("ENTRY_REFUSED", coin=coin, side=side, error=str(exc), bar=bar)
        self.state.last_bar_processed = bar
        self.journal.save(self.state)
        self.journal.event("BAR_PROCESSED", bar=bar, signals=decisions, after_tax=value["after_tax"],
                           positions=list(self.state.positions))

    def _enter(self, coin: str, side: int, atr: float, value: dict, bar: int, stop_fn=None) -> None:
        """Open one position sized on after-tax equity. ``stop_fn(price) -> stop`` (default: the
        daily rule's ATR stop) is applied to the estimated fill for sizing and to the real fill."""
        spec = self.rt.specs.get(coin)
        if spec is None:
            raise DataError(f"NO_SPEC:{coin}")
        if stop_fn is None:
            def stop_fn(px):
                return initial_stop(side, px, atr, self.cfg.params)
        mark = self._mark(coin)
        est_fill = mark * (1 + side * self.cfg.costs.slip(coin))
        est_stop = stop_fn(est_fill)
        if (est_stop - est_fill) * side >= 0:
            raise OrderRefused(f"STOP_ON_WRONG_SIDE:{coin}")
        dist = abs(est_fill - est_stop) / est_fill
        lev = self._trade_leverage(coin, dist)
        step = spec.qty_step or float(Decimal(1).scaleb(-spec.size_decimals))
        min_notional = max(self.cfg.costs.min_notional, spec.min_notional) * (1 + MIN_ORDER_BUFFER)
        margin_used, open_risk = 0.0, 0.0
        for c, pos in self.state.open_positions().items():
            m = self._mark(c)
            margin_used += pos.qty * m / (pos.leverage or self._coin_leverage(c))
            open_risk += max(0.0, pos.side * pos.qty * (m - pos.stop))
        qty = size_order(value["after_tax"], est_fill, est_stop, value["gross"], self.cfg.risk, min_notional,
                         qty_step=step, open_risk=open_risk, free_margin=value["after_tax"] - margin_used,
                         coin_leverage=lev)
        if qty <= 0:
            self.journal.event("ENTRY_TOO_SMALL", coin=coin, side=side, after_tax=value["after_tax"],
                               min_notional=min_notional, stop_distance=dist, leverage=lev)
            return
        budget = self._loss_budget_usd(value)
        if budget is not None:
            # worst case if every stop fills: distance to the stop + fees + stop slippage, open trades included
            fee1 = self.cfg.costs.fee(1.0)
            at_risk = 0.0
            for c, pos in self.state.open_positions().items():
                m = self._mark(c)
                at_risk += pos.qty * (max(0.0, pos.side * (m - pos.stop))
                                      + pos.stop * (fee1 + self.cfg.costs.slip(c, stop=True)))
            per_unit = (abs(est_fill - est_stop) + mark * self.cfg.costs.slip(coin) + est_fill * fee1
                        + est_stop * (fee1 + self.cfg.costs.slip(coin, stop=True)))
            room = LOSS_LIMIT_USE * budget - at_risk
            if qty * per_unit > room:
                fit = _floor_step(room / per_unit, step) if room > 0 else 0.0
                if fit <= 0 or fit * est_fill < min_notional:
                    self.journal.event("ENTRY_SKIPPED_LOSS_LIMIT", coin=coin, side=side, room_usd=room,
                                       risk_usd=qty * per_unit, budget_usd=budget)
                    return
                qty = fit
        self.journal.event("ENTRY_INTENT", coin=coin, side=side, qty=qty, est_fill=est_fill, est_stop=est_stop,
                           atr=atr, bar=bar, after_tax=value["after_tax"], leverage=lev)
        fill = self.broker.market(coin, side, qty, reduce_only=False, reason="ENTRY", leverage=lev)
        stop = stop_fn(fill.price)
        pos = OpenPosition(coin=coin, side=side, qty=fill.qty, entry_price=fill.price, entry_time=fill.time_ms,
                           stop=stop, fees=fill.fee, funding=0.0, slippage=fill.slippage, entry_bar=bar,
                           leverage=float(lev))
        self.state.cash -= fill.fee
        self.state.totals["fees"] += fill.fee
        self.state.totals["slippage"] += fill.slippage
        self.state.put_position(pos)
        self.journal.save(self.state)
        self.journal.event("OPENED", coin=coin, side=side, qty=fill.qty, price=fill.price, fee=fill.fee, stop=stop,
                           slippage=fill.slippage, leverage=lev)
        try:
            if (stop - fill.price) * side >= 0:
                raise OrderRefused(f"FILL_BEYOND_STOP:{coin}")
            pos.stop_order_id = self.broker.place_stop(coin, side, fill.qty, stop)
            self.state.put_position(pos)
            self.journal.save(self.state)
            check = getattr(self.broker, "liquidation_ok", None)
            if check is not None and not check(coin, side, stop):
                raise OrderRefused(f"LIQUIDATION_BEFORE_STOP:{coin}")
        except Exception as exc:  # an unprotected (or liquidation-exposed) position is never kept
            self.journal.event("STOP_PLACEMENT_FAILED_FLATTENING", coin=coin, error=str(exc))
            try:
                self._exit(coin, "NO_STOP_FLATTEN")
            except Exception as exc2:   # keep trying every loop until the exchange confirms it is closed
                self._queue_exit(coin, "NO_STOP_FLATTEN", str(exc2))
            raise OrderRefused(f"STOP_PLACEMENT_FAILED:{coin}") from exc
        self.state.put_position(pos)
        self.journal.save(self.state)

    def _trade_leverage(self, coin: str, stop_distance: float) -> int:
        if self.cfg.risk.liquidation_buffer:
            spec = self.rt.specs.get(coin)
            return stop_safe_leverage(self.cfg.risk, stop_distance, spec.max_leverage if spec else None)
        return int(self._coin_leverage(coin)) or 1

    def _coin_leverage(self, coin: str) -> float:
        spec = self.rt.specs.get(coin)
        setting = self.cfg.risk.leverage_setting
        return min(setting, spec.max_leverage) if spec and spec.max_leverage else setting

    # ------------------------------------------------------------------ total-loss limit
    def _loss_budget_usd(self, value: dict) -> float | None:
        """USD the account may still lose before after-tax equity reaches the user's floor
        (start - max_total_loss_inr, in rupees). None when the mandate sets no floor."""
        if self.cfg.max_total_loss_inr is None:
            return None
        inr = self._usd_inr()
        if not inr:
            raise DataError("NO_USD_INR_RATE_FOR_LOSS_LIMIT")
        start_inr = self.cfg.start_equity_inr or self.cfg.start_equity * inr
        return value["after_tax"] - (start_inr - self.cfg.max_total_loss_inr) / inr

    def _enforce_loss_limit(self, value: dict) -> None:
        """At the floor: stop all entries for good and close every position (retried until done)."""
        budget = self._loss_budget_usd(value)
        if budget is None or budget > 0:
            return
        if self.state.halted != "LOSS_LIMIT":
            self.state.halted = "LOSS_LIMIT"
            self.journal.event("LOSS_LIMIT_REACHED", after_tax=value["after_tax"], usd_inr=self._usd_inr(),
                               max_total_loss_inr=self.cfg.max_total_loss_inr)
        retry = self.state.extra.setdefault("exit_retry", {})
        pending = self.state.extra.get("stop_fill_pending") or {}
        for coin in list(self.state.positions):
            if coin in retry or coin in pending:
                continue
            try:
                self._exit(coin, "LOSS_LIMIT")
            except (OrderRefused, DataError, requests.RequestException) as exc:
                self._queue_exit(coin, "LOSS_LIMIT", str(exc))
        self.journal.save(self.state)

    # ------------------------------------------------------------------ breakers
    def entries_blocked(self) -> str | None:
        if self.state.halted:
            return self.state.halted
        if self._now() < self.state.entries_paused_until:
            return "PAUSED_DAILY_LOSS"
        if (self.cfg.run_dir / "STOP").exists() or (self.cfg.run_dir / "NO_ENTRIES").exists():
            return "OPERATOR_NO_ENTRIES"
        return None

    def apply_breakers(self, value: dict) -> None:
        now = self._now()
        day = now - now % DAY_MS
        at = value["after_tax"]
        if day > self.state.day_start_ms:
            self.state.day_start_ms = day
            self.state.day_start_after_tax = at
        self.state.peak_after_tax = max(self.state.peak_after_tax, at)
        if at < self.state.day_start_after_tax * (1 - self.cfg.daily_loss_pause) and now >= self.state.entries_paused_until:
            self.state.entries_paused_until = day + DAY_MS
            self.journal.event("DAILY_LOSS_PAUSE", after_tax=at, day_start=self.state.day_start_after_tax)
        if not self.state.halted and at < self.state.peak_after_tax * (1 - self.cfg.drawdown_halt):
            self.state.halted = "DRAWDOWN_HALT"
            self.journal.event("DRAWDOWN_HALT", after_tax=at, peak=self.state.peak_after_tax)

    # ------------------------------------------------------------------ main
    def step(self) -> None:
        if not self.rt.specs:
            self.rt.specs = self.md.specs()
            missing = [c for c in self.cfg.universe if c not in self.rt.specs]
            if missing:
                raise RuntimeError(f"UNIVERSE_NOT_LISTED:{missing}")
        self.rt.contexts = self.md.contexts()
        if self.broker.mode == "LIVE":
            self.reconcile_live()
        self.check_stops()
        self.retry_exits()
        self.accrue_funding()
        if (self.cfg.run_dir / "FLATTEN").exists():
            pending = self.state.extra.get("stop_fill_pending") or {}
            for coin in list(self.state.positions):
                if coin not in pending:   # already flat on the exchange; check_stops books its fills
                    self._exit(coin, "OPERATOR_FLATTEN")
            (self.cfg.run_dir / "FLATTEN").unlink()
            self.journal.event("FLATTENED_BY_OPERATOR")
        self.maybe_process_bar()
        value = self.valuation()
        self._enforce_loss_limit(value)
        self.apply_breakers(value)
        self.journal.save(self.state)
        now = self._now()
        if now - self.rt.last_status_ms >= 60_000:
            self.rt.last_status_ms = now
            self._usd_inr()
            self.journal.status(self.status(value))

    def reconcile_live(self) -> None:
        """The exchange is the truth. A position the bot does not own (for example a lost order
        reply that filled later) is closed at once and new entries stop until a human checks."""
        ex = self.broker.positions()
        for coin, q in ex.items():
            if coin not in self.state.positions:
                self.journal.event("LIVE_UNKNOWN_POSITION", coin=coin, qty=q)
                side = 1 if q > 0 else -1
                try:
                    self.broker.market(coin, -side, abs(q), reduce_only=True, reason="UNKNOWN_POSITION_CLOSE")
                    self.journal.event("LIVE_UNKNOWN_POSITION_CLOSED", coin=coin)
                except (OrderRefused, DataError) as exc:
                    self.journal.event("LIVE_UNKNOWN_POSITION_CLOSE_FAILED", coin=coin, error=str(exc))
                self.state.halted = "LIVE_UNKNOWN_POSITION"
            else:
                mine = self.state.positions[coin]
                if abs(abs(q) - mine["qty"]) > 1e-9 or (q > 0) != (mine["side"] > 0):
                    self.state.halted = "LIVE_POSITION_MISMATCH"
                    self.journal.event("LIVE_POSITION_MISMATCH", coin=coin, exchange=q,
                                       bot=mine["side"] * mine["qty"])
        retry = self.state.extra.setdefault("exit_retry", {})
        for coin, pos in self.state.open_positions().items():
            if not pos.stop_order_id and coin not in retry:
                # e.g. the bot was stopped between the fill and the stop: never keep it without a stop
                retry[coin] = "NO_EXCHANGE_STOP"
                self.journal.event("LIVE_POSITION_WITHOUT_STOP", coin=coin)
        self.journal.save(self.state)

    def status(self, value: dict | None = None) -> dict:
        value = value or self.valuation()
        st = self.state
        step = BAR_MS[self.cfg.params.timeframe]
        nxt = st.last_bar_processed + 2 * step
        positions = {}
        for coin, pos in st.open_positions().items():
            mark = self._mark(coin)
            positions[coin] = {"side": "LONG" if pos.side > 0 else "SHORT", "qty": pos.qty,
                               "entry": pos.entry_price, "mark": mark, "stop": pos.stop,
                               "notional_usd": round(pos.qty * mark, 2),
                               "unrealized_usd": round(pos.side * pos.qty * (mark - pos.entry_price), 4),
                               "funding_usd": round(pos.funding, 4)}
        tax = st.tax_ledger()
        inr = self.rt.inr[1]
        return {
            "updated_utc": dt.datetime.fromtimestamp(self._now() / 1000, dt.timezone.utc).isoformat(timespec="seconds"),
            "label": self.cfg.label, "mode": st.mode, "venue": st.venue, "strategy": self.cfg.params.name,
            "usd_inr": inr, "after_tax_equity_inr": round(value["after_tax"] * inr, 2) if inr else None,
            "start_equity_inr": self.cfg.start_equity_inr,
            "start_equity_usd": st.start_equity,
            "equity_usd": round(value["equity"], 4),
            "after_tax_equity_usd": round(value["after_tax"], 4),
            "after_tax_return": round(value["after_tax"] / st.start_equity - 1, 6),
            "tax_mode": tax.policy.mode, "tax_reserved_usd": round(tax.reserve, 4),
            "tax_pending_on_open_usd": round(value["tax_pending"], 4),
            "fees_usd": round(st.totals["fees"], 4), "slippage_usd": round(st.totals["slippage"], 4),
            "funding_usd": round(st.totals["funding"], 4), "closed_trades": st.totals["trades"],
            "wins": st.totals["wins"], "gross_exposure_usd": round(value["gross"], 2),
            "effective_leverage": round(value["gross"] / value["after_tax"], 3) if value["after_tax"] > 0 else None,
            "positions": positions, "halted": st.halted,
            "entries_paused_until_utc": (dt.datetime.fromtimestamp(st.entries_paused_until / 1000, dt.timezone.utc)
                                         .isoformat(timespec="seconds") if st.entries_paused_until else None),
            "last_bar_processed_utc": dt.datetime.fromtimestamp(st.last_bar_processed / 1000, dt.timezone.utc).date().isoformat(),
            "next_decision_utc": dt.datetime.fromtimestamp(nxt / 1000, dt.timezone.utc).isoformat(timespec="minutes"),
            "loss_floor_inr": ((self.cfg.start_equity_inr or 0) - self.cfg.max_total_loss_inr
                               if self.cfg.max_total_loss_inr is not None and self.cfg.start_equity_inr else None),
            "peak_after_tax_usd": round(st.peak_after_tax, 4),
            "drawdown_from_peak": round(1 - value["after_tax"] / st.peak_after_tax, 6) if st.peak_after_tax > 0 else None,
        }

    def run_forever(self) -> None:
        self.journal.event("LOOP_START", poll_seconds=self.cfg.poll_seconds)
        while not (self.cfg.run_dir / "STOP").exists():
            try:
                self.step()
                self.rt.errors = 0
            except Exception as exc:  # never stop: open positions keep their exchange stops; retry next loop
                self.rt.errors += 1
                self.journal.event("STEP_ERROR", error=f"{type(exc).__name__}: {exc}"[:500],
                                   consecutive=self.rt.errors)
                if self.rt.errors >= self.cfg.max_consecutive_errors and not self.state.halted:
                    self.state.entries_paused_until = self._now() + HOUR_MS
                    self.journal.event("ERROR_PAUSE", until=self.state.entries_paused_until)
                    self.journal.save(self.state)
            self.sleep(self.cfg.poll_seconds)
        self.journal.event("LOOP_STOPPED_BY_OPERATOR", positions=list(self.state.positions))


class IntradayRunner(Runner):
    """Day trading: hourly decisions with compounder.intraday rules, flat at the end of each UTC day."""

    def _arrays_for(self, coin: str, bar: int):
        from .intraday import intraday_arrays
        p = self.cfg.params
        rows = self.md.candles(coin, p.timeframe, p.history_bars)
        if not rows or int(rows[-1]["t"]) != bar:
            return None
        t = np.array([int(r["t"]) for r in rows], dtype=np.int64)
        h = np.array([float(r["h"]) for r in rows])
        lo = np.array([float(r["l"]) for r in rows])
        c = np.array([float(r["c"]) for r in rows])
        return intraday_arrays(t, h, lo, c, p), len(c) - 1

    def process_bar(self, bar: int) -> None:
        from .intraday import DAY_MS as _DAY, entry_decision, exit_decision
        p = self.cfg.params
        if hasattr(self.broker, "bar_hint"):
            self.broker.bar_hint = bar
        day = bar // _DAY
        data = {}
        for coin in self.cfg.universe:
            try:
                data[coin] = self._arrays_for(coin, bar)
            except DataError as exc:
                data[coin] = None
                self.journal.event("DATA_STALE", coin=coin, bar=bar, error=str(exc))
        for coin, pos in self.state.open_positions().items():
            got = data.get(coin)
            reason = "END_OF_DAY_LATE" if pos.entry_bar // _DAY < day and (bar % _DAY) // HOUR_MS != 23 else None
            if reason is None and got is not None:
                reason = exit_decision(got[0], got[1], pos.side, p)
            if reason:
                try:
                    self._exit(coin, reason)
                except (OrderRefused, DataError, requests.RequestException) as exc:
                    self._queue_exit(coin, reason, str(exc))
        value = self.valuation()
        blocked = self.entries_blocked()
        entered = self.state.extra.setdefault("entered_day", {})
        signals = []
        for coin in self.cfg.universe:
            got = data.get(coin)
            if got is None or coin in self.state.positions or entered.get(coin) == day:
                continue
            a, i = got
            side, level = entry_decision(a, i, p)
            if side == 0:
                continue
            signals.append(coin)
            if blocked:
                self.journal.event("ENTRY_SKIPPED", coin=coin, side=side, reason=blocked, bar=bar)
                continue
            atr = float(a["atr"][i])
            if p.kind == "ORB":
                def stop_fn(px, level=level):
                    return level
            else:
                def stop_fn(px, side=side, atr=atr):
                    return px - side * p.stop_atr * atr
            entered[coin] = day
            try:
                self._enter(coin, side, atr, value, bar, stop_fn)
                value = self.valuation()
            except (OrderRefused, DataError) as exc:
                self.journal.event("ENTRY_REFUSED", coin=coin, side=side, error=str(exc), bar=bar)
        self.state.last_bar_processed = bar
        self.journal.save(self.state)
        self.journal.event("BAR_PROCESSED", bar=bar, signals=signals, after_tax=value["after_tax"],
                           positions=list(self.state.positions))
