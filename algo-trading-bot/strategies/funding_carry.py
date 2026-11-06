"""Funding-carry basket: hold the side of each market that receives funding.

Research basis (2026-10-23, pas testnet): no price-pattern candidate was
profitable out of sample after costs. Funding was the one structural effect:
longs earned ~0.11-0.19%/day on BTC/ETH/HYPE/SP500 and shorts ~0.075%/day on
USDJPY. This is a carry bet with price risk, not a validated price edge.

Pure decision logic. No I/O, no signing, no exchange access.
"""
from dataclasses import dataclass
from decimal import Decimal as D

HOUR_MS = 3600000


@dataclass(frozen=True)
class CarryParams:
    markets: tuple = ('pas:BTC', 'pas:ETH', 'pas:HYPE', 'pas:SP500', 'pas:USDJPY')
    # |mean hourly funding| must clear ~3x the 0.000625%/h interest floor
    # observed on markets with no premium (BRENT/GOLD), so only a real premium counts.
    threshold: D = D('0.00002')
    lookback_hours: int = 24
    # After an exchange stop-out, leave the market alone for a day.
    cooldown_hours: int = 24

    def __post_init__(self):
        if (not self.markets or len(set(self.markets)) != len(self.markets) or self.threshold <= 0
                or not 6 <= self.lookback_hours <= 72 or not 0 <= self.cooldown_hours <= 168):
            raise ValueError('INVALID_CARRY_PARAMS')


def trailing_mean(rates, now_ms, lookback_hours):
    """Mean of hourly funding settled in the last `lookback_hours` completed hours.

    `rates` maps settlement hour (ms) to rate. Too few observations -> None,
    which means "no opinion" rather than zero.
    """
    end = now_ms // HOUR_MS * HOUR_MS
    window = [r for h, r in rates.items() if end - lookback_hours * HOUR_MS < h <= end]
    if len(window) < lookback_hours * 3 // 4:
        return None
    return sum(window, D(0)) / len(window)


def receiving_side(mean, threshold):
    """Side that is paid funding. Positive funding: longs pay shorts."""
    if mean is None:
        return None
    if mean < -threshold:
        return 'LONG'
    if mean > threshold:
        return 'SHORT'
    return None


def paying(side, mean, threshold):
    """True when holding `side` now pays more than the threshold."""
    if mean is None:
        return False
    return mean > threshold if side == 'LONG' else mean < -threshold


class FundingCarry:
    name = 'funding_carry'

    def __init__(self, params=None):
        self.params = params or CarryParams()

    def decide(self, funding, positions, stopped_at, now_ms):
        """Return exits first, then entries.

        funding:    {symbol: {hour_ms: Decimal rate}}
        positions:  {symbol: signed Decimal quantity} (exchange truth)
        stopped_at: {symbol: ms of last exchange stop-out}
        """
        p = self.params
        exits, entries = [], []
        for symbol in p.markets:
            mean = trailing_mean(funding.get(symbol, {}), now_ms, p.lookback_hours)
            quantity = positions.get(symbol, D(0))
            held = 'LONG' if quantity > 0 else 'SHORT' if quantity < 0 else None
            if held:
                # Hysteresis: hold until the position is clearly paying.
                if paying(held, mean, p.threshold):
                    exits.append(dict(symbol=symbol, side=held, reason='FUNDING_TURNED_AGAINST',
                                      mean_funding=mean))
                continue
            want = receiving_side(mean, p.threshold)
            last_stop = stopped_at.get(symbol)
            if want and (last_stop is None or now_ms - last_stop >= p.cooldown_hours * HOUR_MS):
                entries.append(dict(symbol=symbol, side=want, mean_funding=mean))
        return exits, entries


def stop_price(entry, side, fraction):
    """Exchange stop level for a leg: entry -/+ fraction."""
    return entry * (1 - fraction) if side == 'LONG' else entry * (1 + fraction)


def marked_equity(collateral, positions):
    """Unified-account collateral excludes open P&L; add exchange-reported uPnL once."""
    return collateral + sum((p.unrealized_pnl for p in positions.values()), D(0))


def loss_halt(start_equity, equity, max_loss):
    return equity <= start_equity * (1 - max_loss)


def fill_deviation(expected, actual):
    return abs(actual - expected) / expected
