"""Brokers: PaperBroker fills against Hyperliquid's live public order book (no keys, no orders).

A broker answers three questions for the runner:
  market(coin, side, qty, reduce_only) -> Fill      (taker order, walks the visible book)
  stop_triggered(coin, pos_side, stop) -> bool      (Hyperliquid stops trigger on the mark price)
  funding(coin, start_ms, end_ms) -> [(t, rate)]    (actual hourly funding)
The live broker (hl_live.py) implements the same interface with signed exchange actions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .costs import VenueCosts
from .market_data import DataError, HyperliquidPublic, walk_book


class OrderRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class Fill:
    coin: str
    side: int          # +1 bought, -1 sold
    qty: float
    price: float       # average fill price
    fee: float         # fee paid (incl. GST where the venue charges it)
    mid: float         # mid at decision time (slippage reference)
    time_ms: int
    reason: str

    @property
    def slippage(self) -> float:
        return abs(self.price - self.mid) * self.qty


class PaperBroker:
    mode = "PAPER"

    def __init__(self, md: HyperliquidPublic, costs: VenueCosts, *, max_deviation: float = 0.01, clock=time.time):
        self.md = md
        self.costs = costs
        self.max_deviation = max_deviation
        self.clock = clock

    def market(self, coin: str, side: int, qty: float, *, reduce_only: bool, reason: str,
               leverage: int | None = None) -> Fill:
        bids, asks, _ = self.md.book(coin)
        mid = (bids[0][0] + asks[0][0]) / 2
        levels = asks if side > 0 else bids
        px = walk_book(levels, qty)
        if px is None:
            raise OrderRefused(f"THIN_BOOK:{coin}")
        if abs(px / mid - 1) > self.max_deviation:
            raise OrderRefused(f"PRICE_DEVIATION:{coin}:{px / mid - 1:.4%}")
        return Fill(coin, side, qty, px, self.costs.fee(px * qty), mid, int(self.clock() * 1000), reason)

    def stop_triggered(self, coin: str, pos_side: int, stop: float, contexts: dict) -> bool:
        ctx = contexts.get(coin)
        if ctx is None:
            raise DataError(f"NO_CONTEXT:{coin}")
        return ctx.mark <= stop if pos_side > 0 else ctx.mark >= stop

    def funding(self, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return [x for x in self.md.funding_history(coin, start_ms, end_ms) if start_ms < x[0] <= end_ms]

    # Paper stops live in the bot's state; nothing rests anywhere.
    def place_stop(self, coin: str, pos_side: int, qty: float, trigger: float) -> str | None:
        return None

    def cancel_stop(self, coin: str, order_id: str | None) -> None:
        return None
