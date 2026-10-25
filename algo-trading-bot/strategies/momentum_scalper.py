"""Overnight momentum scalper: 5m breakout in the direction of the 15m EMA trend.

Pure decision logic and guardrail state. No I/O, no signing, no exchange access.
Runs inside the committed scored limits: BTC/EWY, LONG-only, one position,
<= $1,000 per entry, <= 2 entries per hour, 1x. A SHORT setup is detected and
reported but never traded while the committed scope is LONG-only.

Research note (2026-10-23): 5m breakouts did not clear costs out of sample.
This strategy was chosen by the user to guarantee overnight activity. 2026-10-25:
the time stop and the forced trade are off by default (user directive).
"""
from dataclasses import dataclass, field
from decimal import Decimal as D

MIN_MS = 60000


@dataclass(frozen=True)
class ScalpParams:
    markets: tuple = ('pas:BTC', 'pas:EWY')
    directions: tuple = ('LONG',)
    breakout_bars: int = 6
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    tp_atr: D = D('1.5')
    sl_atr: D = D('1.0')
    # A 1-ATR stop on 5m bars can sit inside the spread; the exchange stop must
    # rest below the mark, so the stop distance has a 0.15% floor (TP keeps 1.5:1).
    min_stop_fraction: D = D('0.0015')
    # User directive 2026-10-25: no 60-minute time exit and no 45-minute forced
    # trade. None disables each; a trade leaves only by its stop or take-profit.
    time_stop_ms: int | None = None
    guarantee_ms: int | None = None
    # The take-profit must clear a taker entry and a taker exit (0.09% each on
    # pas, userCrossRate x2) plus a minimum net gain, so a win is never eaten by fees.
    fee_rate: D = D('0.0009')
    min_net_fraction: D = D('0.0005')
    risk_fraction: D = D('0.004')

    def __post_init__(self):
        if (not self.markets or not set(self.directions) <= {'LONG', 'SHORT'} or not self.directions
                or self.ema_fast >= self.ema_slow or self.breakout_bars < 2 or self.tp_atr <= self.sl_atr
                or not D(0) < self.risk_fraction <= D('0.005')):
            raise ValueError('INVALID_SCALP_PARAMS')


def ema(values, n):
    out, a = [], D(2) / (n + 1)
    for v in values:
        out.append(v if not out else a * v + (1 - a) * out[-1])
    return out


def atr(bars, n):
    """Simple-average true range of the last n bars; None if too short."""
    if len(bars) < n + 1:
        return None
    trs = [max(b['h'] - b['l'], abs(b['h'] - p['c']), abs(b['l'] - p['c'])) for p, b in zip(bars, bars[1:])]
    return sum(trs[-n:], D(0)) / n


def trend(bars15, p):
    if len(bars15) < p.ema_slow:
        return None
    closes = [b['c'] for b in bars15]
    fast, slow = ema(closes, p.ema_fast)[-1], ema(closes, p.ema_slow)[-1]
    return 'UP' if fast > slow else 'DOWN' if fast < slow else None


def setup(bars5, bars15, p):
    """Breakout on the last completed 5m bar, filtered by the 15m trend.

    Returns dict(side, reason, atr, ...) or None. A SHORT outside the permitted
    directions comes back with side=None and the blocking reason.
    """
    if len(bars5) < max(p.breakout_bars + 1, p.atr_period + 1):
        return None
    t = trend(bars15, p)
    last, prior = bars5[-1], bars5[-1 - p.breakout_bars:-1]
    value = atr(bars5, p.atr_period)
    if t == 'UP' and last['c'] > max(b['h'] for b in prior):
        side = 'LONG'
    elif t == 'DOWN' and last['c'] < min(b['l'] for b in prior):
        side = 'SHORT'
    else:
        return None
    if side not in p.directions:
        return dict(side=None, detected=side, reason='SHORT_PROHIBITED_BY_COMMITTED_SCOPE', atr=value, bar_ms=last['t'])
    return dict(side=side, detected=side, reason='BREAKOUT_WITH_15M_TREND', atr=value, bar_ms=last['t'])


def guaranteed(bars5, bars15, p):
    """Fallback trade in the 15m trend direction, if that direction is permitted."""
    t = trend(bars15, p)
    value = atr(bars5, p.atr_period)
    side = 'LONG' if t == 'UP' else 'SHORT' if t == 'DOWN' else None
    if side is None or value is None:
        return None
    if side not in p.directions:
        return dict(side=None, detected=side, reason='GUARANTEE_SHORT_PROHIBITED_BY_COMMITTED_SCOPE',
                    atr=value, bar_ms=bars5[-1]['t'])
    return dict(side=side, detected=side, reason='TRADE_GUARANTEE_45_MIN', atr=value, bar_ms=bars5[-1]['t'])


def levels(entry, atr_value, side, p):
    """Stop and take-profit at 1.5:1, with the take-profit floored above round-trip fees."""
    distance = max(p.sl_atr * atr_value, p.min_stop_fraction * entry)
    reward = max(distance * p.tp_atr / p.sl_atr, entry * (2 * p.fee_rate + p.min_net_fraction))
    if side == 'LONG':
        return entry - distance, entry + reward
    return entry + distance, entry - reward


def size(*, equity, risk_fraction, stop_distance, price, max_notional, top_quantity, participation, half=False):
    """Risk-based quantity, then every cap; the smallest bound wins."""
    quantity = min(equity * risk_fraction / stop_distance, max_notional / price, top_quantity * participation)
    return quantity / 2 if half else quantity


@dataclass
class NightGuard:
    """Profit locks, loss cap and loss-streak pause, as % of starting equity."""
    t1: D
    t2: D
    t3: D
    loss_cap: D = D('-2.0')
    t1_floor: D = D('0.1')
    hit_t1: bool = False
    hit_t2: bool = False
    losing_streak: int = 0
    paused_until_ms: int = 0
    half_size: bool = False
    events: list = field(default_factory=list)

    def check(self, pnl_pct):
        """Return ('HALT', reason) when the night must end, else None."""
        if pnl_pct <= self.loss_cap:
            return 'HALT', 'LOSS_CAP'
        if pnl_pct >= self.t3:
            return 'HALT', 'T3_LOCK_NIGHT_WON'
        if pnl_pct >= self.t2 and not self.hit_t2:
            self.hit_t2 = True
            self.events.append('T2_HIT_SIZE_HALVED')
        if pnl_pct >= self.t1 and not self.hit_t1:
            self.hit_t1 = True
            self.events.append('T1_HIT')
        if self.hit_t2 and pnl_pct <= self.t1:
            return 'HALT', 'T2_PROFIT_LOCK'
        if self.hit_t1 and pnl_pct <= self.t1_floor:
            return 'HALT', 'T1_PROFIT_LOCK'
        return None

    def trade_closed(self, net, now_ms):
        if net < 0:
            self.losing_streak += 1
            if self.losing_streak >= 3:
                self.paused_until_ms = now_ms + 30 * MIN_MS
                self.half_size = True
                self.losing_streak = 0
                self.events.append('THREE_LOSSES_PAUSE_30M_THEN_HALF_SIZE')
        else:
            self.losing_streak = 0

    def size_factor_half(self):
        return self.half_size or self.hit_t2

    def paused(self, now_ms):
        return now_ms < self.paused_until_ms


def official_q(r, sigma, *, lam=D('1.5'), c=D('0.05'), eps=D('0.005')):
    """Competition financial score Q = (max(R,0)+eps) / (|R| + lam*sigma + c)."""
    return (max(r, D(0)) + eps) / (abs(r) + lam * sigma + c)


@dataclass
class DayGuard:
    """Rank protection for a volatility-adjusted score: lock gains, cap losses.

    `check` takes the competition return in % (prior official R plus today's).
    Returns ('HALT', reason), ('LOCK', reason) or None.
    """
    lock: D
    loss_cap: D = D('-0.30')
    locked: bool = False
    resumed_half: bool = False
    losing_streak: int = 0
    paused_until_ms: int = 0
    half_size: bool = False
    events: list = field(default_factory=list)

    def check(self, return_pct):
        if return_pct <= self.loss_cap:
            return 'HALT', 'LOSS_CAP_0_30_PCT'
        if return_pct >= self.lock and not self.locked:
            self.locked = True
            self.resumed_half = False
            self.events.append('LOCK_REACHED')
            return 'LOCK', 'LOCK_REACHED'
        return None

    def resume_if_below(self, estimated_rank, target_rank=6):
        """While locked, resume at half size only if the estimated rank fell below target."""
        if self.locked and estimated_rank is not None and estimated_rank > target_rank:
            self.locked = False
            self.resumed_half = True
            self.events.append('LOCK_RESUMED_HALF_SIZE')
            return True
        return False

    def trade_closed(self, net, now_ms):
        NightGuard.trade_closed(self, net, now_ms)

    def size_factor_half(self):
        return self.half_size or self.resumed_half

    def paused(self, now_ms):
        return self.locked or now_ms < self.paused_until_ms


def estimated_rank(my_q, others):
    """Rank if my Q were published now; `others` are the other teams' published Q values."""
    return 1 + sum(1 for q in others if q > my_q)
