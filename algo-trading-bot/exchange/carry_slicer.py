"""Sliced building and unwinding of a carry leg (user directive 25 Oct 2026, "YES, CARRY").

Organizer rule: no moving a thin book. A leg is never entered or exited with one
large order. Each leg works one child order at a time:

  * maker phase: a post-only (Alo) child at our side of the touch (bid for a
    buy, ask for a sell); a child still unfilled after `reprice_ms` is
    re-priced at the current touch;
  * after `maker_window_ms` the remainder is finished with IOC children whose
    limit IS the opposite touch, so a child can never walk past the best level;
    taker children on one leg are at least `taker_gap_ms` apart so the book refills;
  * every child is at most `book_share` of the smaller touch quantity (the
    book-impact rule the scalper uses) and never more than what is left.

Pure decisions: no I/O, no signing, no exchange access.
"""
from dataclasses import dataclass
from decimal import Decimal as D
from types import SimpleNamespace

MAKER, TAKER = 'MAKER', 'TAKER'


def top(book):
    """Touch of an L2 book (one cheap read) in the shape `child` expects; None when a side is empty."""
    if not book.bids or not book.asks:
        return None
    bid, ask = book.bids[0], book.asks[0]
    return SimpleNamespace(bid=bid.price, ask=ask.price, bid_quantity=bid.quantity, ask_quantity=ask.quantity,
                           mid=(bid.price + ask.price) / 2, timestamp_ms=book.timestamp_ms)


@dataclass(frozen=True)
class SliceParams:
    book_share: D = D('0.25')
    maker_window_ms: int = 2 * 3600000
    reprice_ms: int = 600000
    taker_gap_ms: int = 30000
    # Exchange minimum is $10; stay clear of it after rounding down.
    min_notional: D = D('11')
    # 0: an IOC child takes the touch only. 5 (user choice 26 Oct): its limit may sit up to 5 bps past
    # the touch and it takes at most book_share of the depth posted inside that limit.
    taker_depth_bps: int = 0

    def __post_init__(self):
        if (not D(0) < self.book_share <= D('0.25') or self.maker_window_ms < 0 or self.reprice_ms <= 0
                or self.taker_gap_ms < 0 or self.min_notional < 10 or self.taker_depth_bps not in (0, 5)):
            raise ValueError('INVALID_SLICE_PARAMS')


def phase(started_ms, now_ms, params, *, maker=True):
    """MAKER until the window has elapsed since the leg started, then TAKER."""
    return MAKER if maker and now_ms - started_ms < params.maker_window_ms else TAKER


def remaining(target, held):
    """Unsigned quantity still to build (entry) or unwind (target 0)."""
    return max(abs(target) - abs(held), D(0))


def _lots(spec, quantity):
    """Round down to the lot; anything under one lot is zero (normalize_size refuses it)."""
    return spec.normalize_size(quantity) if quantity >= spec.size_step else D(0)


def depth_within(book, order_side, limit):
    """Displayed quantity an order on `order_side` with this limit could take."""
    levels = book.asks if order_side == 'BUY' else book.bids
    return sum((l.quantity for l in levels if (l.price <= limit if order_side == 'BUY' else l.price >= limit)), D(0))


def child(order_side, left, quote, spec, kind, params, book=None):
    """Next child for `left` quantity, or (None, reason).

    order_side: 'BUY' or 'SELL'; quote has bid/ask and bid_quantity/ask_quantity; `book` (the L2
    book the quote came from) sizes an IOC child when params.taker_depth_bps is set.
    """
    if left <= 0:
        return None, 'LEG_COMPLETE'
    touch = min(quote.bid_quantity, quote.ask_quantity)
    cap = touch * params.book_share
    if kind == MAKER:
        price, tif = (quote.bid if order_side == 'BUY' else quote.ask), 'Alo'
    else:
        price, tif = (quote.ask if order_side == 'BUY' else quote.bid), 'Ioc'
        if params.taker_depth_bps and book is not None:
            step = D(params.taker_depth_bps) / 10000
            price = price * (1 + step) if order_side == 'BUY' else price * (1 - step)
    price = spec.normalize_price(price, order_side)
    if kind == TAKER and params.taker_depth_bps and book is not None:
        cap = depth_within(book, order_side, price) * params.book_share
    quantity = _lots(spec, min(left, cap))
    if left * price < params.min_notional:
        return None, 'REMAINDER_BELOW_MINIMUM'
    rest = left - quantity
    if 0 < rest and rest * price < params.min_notional:
        # Never strand a remainder below the exchange minimum: leave at least one minimum child.
        floor = _lots(spec, params.min_notional / price)
        floor = floor if floor * price >= params.min_notional else floor + spec.size_step
        quantity = _lots(spec, left - floor)
    if quantity <= 0 or quantity * price < params.min_notional:
        return None, 'TOUCH_TOO_THIN'
    return dict(side=order_side, quantity=quantity, price=price, tif=tif, kind=kind,
                touch_quantity=touch, cap_quantity=cap), None


def stale(child_row, quote, now_ms, params):
    """A resting maker child is re-priced when unfilled after `reprice_ms` and no longer at the touch."""
    if now_ms - child_row['placed_ms'] < params.reprice_ms:
        return False
    touch = quote.bid if child_row['side'] == 'BUY' else quote.ask
    return D(str(child_row['price'])) != touch


def taker_ready(last_taker_ms, now_ms, params):
    return last_taker_ms is None or now_ms - last_taker_ms >= params.taker_gap_ms
