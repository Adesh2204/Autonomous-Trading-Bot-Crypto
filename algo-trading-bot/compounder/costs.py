"""Venue trading costs and the Indian tax engine.

Fees are a fraction of notional per fill. ``gst_on_fees`` is the 18% GST Indian exchanges add to
their fee. Slippage is charged per side against the reference price (bar close for market orders,
the trigger for stop orders, plus an extra allowance because stop-market orders cross the book).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Hyperliquid base tier (docs, Nov 2026): perps taker 0.045%, maker 0.015%; spot 0.070% / 0.040%.
# CoinDCX USDT-M futures Regular 1: maker 0.02%, taker 0.05%, plus 18% GST on the fee.
LIQUID = ("BTC", "ETH")
MAJOR = ("SOL", "XRP", "BNB", "DOGE", "HYPE")


@dataclass(frozen=True)
class VenueCosts:
    name: str
    taker_fee: float
    maker_fee: float
    gst_on_fees: float = 0.0
    slip_bps_liquid: float = 2.0
    slip_bps_major: float = 4.0
    slip_bps_other: float = 8.0
    stop_extra_bps: float = 5.0
    min_notional: float = 10.0

    def fee(self, notional: float, *, maker: bool = False) -> float:
        rate = self.maker_fee if maker else self.taker_fee
        return abs(notional) * rate * (1.0 + self.gst_on_fees)

    def slip(self, symbol: str, *, stop: bool = False) -> float:
        if symbol in LIQUID:
            bps = self.slip_bps_liquid
        elif symbol in MAJOR:
            bps = self.slip_bps_major
        else:
            bps = self.slip_bps_other
        if stop:
            bps += self.stop_extra_bps
        return bps / 10_000.0

    def stressed(self, factor: float) -> "VenueCosts":
        """Every cost multiplied by ``factor`` (robustness check)."""
        return VenueCosts(
            name=f"{self.name}_x{factor:g}", taker_fee=self.taker_fee * factor, maker_fee=self.maker_fee * factor,
            gst_on_fees=self.gst_on_fees, slip_bps_liquid=self.slip_bps_liquid * factor,
            slip_bps_major=self.slip_bps_major * factor, slip_bps_other=self.slip_bps_other * factor,
            stop_extra_bps=self.stop_extra_bps * factor, min_notional=self.min_notional,
        )


HYPERLIQUID = VenueCosts("hyperliquid", taker_fee=0.00045, maker_fee=0.00015)
COINDCX_FUTURES = VenueCosts("coindcx_futures", taker_fee=0.0005, maker_fee=0.0002, gst_on_fees=0.18,
                             slip_bps_liquid=3.0, slip_bps_major=6.0, slip_bps_other=12.0, stop_extra_bps=8.0,
                             min_notional=6.0)


# Delta Exchange India perps: maker 0.02%, taker 0.05% (+18% GST); minimum = one contract.
DELTA_INDIA = VenueCosts("delta_india", taker_fee=0.0005, maker_fee=0.0002, gst_on_fees=0.18,
                         slip_bps_liquid=3.0, slip_bps_major=6.0, slip_bps_other=12.0, stop_extra_bps=8.0,
                         min_notional=0.0)


def indian_fy(ts_ms: int) -> int:
    """Indian financial year (April-March) labelled by its starting year: 1 Apr 2026 -> 2026."""
    d = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc)
    return d.year if d.month >= 4 else d.year - 1


@dataclass(frozen=True)
class TaxPolicy:
    """How the bot reserves tax before it compounds anything.

    VDA_PER_TRADE (default, conservative): Section 115BBH reading used by most Indian CAs and tax
        tools: 30% + 4% cess on every profitable closed trade; a losing trade reduces nothing.
    BUSINESS_NET_ANNUAL: the view that cash-settled crypto futures are (speculative) business income:
        tax on each financial year's net profit at ``business_rate``, with speculative losses
        carried forward 4 years. Only valid if the user's CA files it that way.
    NONE: no tax (research comparison only).
    """
    mode: str = "VDA_PER_TRADE"
    rate: float = 0.30
    cess: float = 0.04
    business_rate: float = 0.30
    carry_forward_years: int = 4

    @property
    def effective_rate(self) -> float:
        base = self.business_rate if self.mode == "BUSINESS_NET_ANNUAL" else self.rate
        return base * (1.0 + self.cess) if self.mode != "NONE" else 0.0


@dataclass
class TaxLedger:
    """Tracks the money set aside for tax. ``reserve`` is excluded from tradable equity."""
    policy: TaxPolicy = field(default_factory=TaxPolicy)
    reserve: float = 0.0
    fy_net: dict = field(default_factory=dict)
    fy_tax: dict = field(default_factory=dict)

    def on_trade_closed(self, ts_ms: int, net_pnl: float, taxable: float | None = None) -> float:
        """Record a closed trade; return the change in the tax reserve (can be negative only in
        BUSINESS_NET_ANNUAL mode when a loss follows a gain in the same financial year).

        ``taxable`` (VDA mode): the strict 115BBH base when it differs from the net P&L, i.e. the
        price gain before fees (fees are not deductible) plus any funding received."""
        fy = indian_fy(ts_ms)
        self.fy_net[fy] = self.fy_net.get(fy, 0.0) + net_pnl
        mode = self.policy.mode
        if mode == "NONE":
            return 0.0
        if mode == "VDA_PER_TRADE":
            base = net_pnl if taxable is None else taxable
            tax = self.policy.effective_rate * max(0.0, base)
            self.fy_tax[fy] = self.fy_tax.get(fy, 0.0) + tax
            self.reserve += tax
            return tax
        if mode == "BUSINESS_NET_ANNUAL":
            before = self.fy_tax.get(fy, 0.0)
            taxable = max(0.0, self.fy_net[fy] - self._carried_loss(fy))
            after = self.policy.effective_rate * taxable
            self.fy_tax[fy] = after
            self.reserve += after - before
            return after - before
        raise ValueError(f"unknown tax mode {mode}")

    def pending_on(self, ts_ms: int, open_nets: list[float]) -> float:
        """Extra tax that would be reserved if every open position (unrealized net P&L in
        ``open_nets``) were closed at ``ts_ms``. Used for the after-tax liquidation value."""
        mode = self.policy.mode
        if mode == "NONE" or not open_nets:
            return 0.0
        if mode == "VDA_PER_TRADE":
            return self.policy.effective_rate * sum(max(0.0, x) for x in open_nets)
        fy = indian_fy(ts_ms)
        before = self.fy_tax.get(fy, 0.0)
        taxable = max(0.0, self.fy_net.get(fy, 0.0) + sum(open_nets) - self._carried_loss(fy))
        return max(0.0, self.policy.effective_rate * taxable - before)

    def _carried_loss(self, fy: int) -> float:
        """Losses of earlier years still unused and inside the carry-forward window at ``fy``."""
        window = self.policy.carry_forward_years
        buckets: list[list[float]] = []  # [year, remaining loss], oldest first
        for year in sorted(y for y in self.fy_net if y < fy):
            net = self.fy_net[year]
            if net < 0:
                buckets.append([year, -net])
                continue
            gain = net
            for bucket in buckets:
                if gain <= 0:
                    break
                if year - bucket[0] > window:
                    continue
                used = min(gain, bucket[1])
                bucket[1] -= used
                gain -= used
        return sum(rem for year, rem in buckets if fy - year <= window)

    @property
    def total_tax(self) -> float:
        return sum(self.fy_tax.values())
