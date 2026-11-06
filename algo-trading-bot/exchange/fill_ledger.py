"""Exchange fills are the source of truth for every trade record (bug #11, 25 Oct).

On 25 Oct the HYPE short (10:35 UTC) was logged ``FILLED, filled 0``: the entry filled and the
exchange stop closed it 55 s later, before the runtime's first position read. The trade never
reached the journal, so its -$0.47 missed the losing streak and the period trade log (the loss cap
was unaffected because it reads exchange equity).

This module never reads the order-placement response or a single position snapshot to decide
whether a trade happened. It groups the exchange-reported fills (``userFillsByTime``; the account
WebSocket's ``userFills`` notifications only wake the read) into round trips by ``startPosition``
and size, and compares them with the fills the journal already attributed to a trade.

Pure functions only (stdlib Decimal); no exchange I/O happens here.
"""
from decimal import Decimal as D


def normalize(fill):
    """Fill object (base_exchange.Fill) or raw exchange row -> plain dict with Decimals."""
    if isinstance(fill, dict) and 'coin' in fill:
        signed = D(fill['sz']) if fill['side'] == 'B' else -D(fill['sz'])
        return dict(symbol=fill['coin'], ms=int(fill['time']), tid=str(fill['tid']), oid=str(fill['oid']),
                    signed=signed, px=D(fill['px']), fee=D(fill['fee']), closed_pnl=D(fill.get('closedPnl', '0')),
                    start=D(fill['startPosition']) if 'startPosition' in fill else None)
    side, qty = fill.side, D(fill.quantity)
    start = getattr(fill, 'start_position', None)
    return dict(symbol=fill.symbol, ms=int(fill.timestamp_ms), tid=str(fill.trade_id), oid=str(fill.order_id),
                signed=qty if side == 'BUY' else -qty, px=D(fill.price), fee=D(fill.fee),
                closed_pnl=D(fill.closed_pnl or 0), start=D(start) if start is not None else None)


def round_trips(fills):
    """Group fills per symbol into flat-to-flat round trips.

    Returns (closed, open): closed round trips (position back to 0) and, per symbol, the fills of a
    position that is still open. ``startPosition`` from the exchange anchors each fill; a fill whose
    start is non-zero and that has no open group is joined to a synthetic group (history began
    mid-position), flagged ``partial_history``.
    """
    rows = sorted((normalize(f) for f in fills), key=lambda r: (r['symbol'], r['ms'], r['tid']))
    closed, open_ = [], {}
    for r in rows:
        g = open_.get(r['symbol'])
        start = r['start'] if r['start'] is not None else (g['position'] if g else D(0))
        if g is None:
            g = dict(symbol=r['symbol'], fills=[], position=start, partial_history=start != 0)
            open_[r['symbol']] = g
        g['fills'].append(r)
        g['position'] = start + r['signed']
        if g['position'] == 0:
            closed.append(_summary(open_.pop(r['symbol'])))
    return closed, {s: _summary(g) for s, g in open_.items()}


def _summary(g):
    fills = g['fills']
    first = fills[0]
    side = 'LONG' if first['signed'] > 0 else 'SHORT'
    opening = [f for f in fills if (f['signed'] > 0) == (side == 'LONG')]
    qty = sum((abs(f['signed']) for f in opening), D(0))
    entry = sum((abs(f['signed']) * f['px'] for f in opening), D(0)) / qty if qty else None
    closing = [f for f in fills if (f['signed'] > 0) != (side == 'LONG')]
    cq = sum((abs(f['signed']) for f in closing), D(0))
    exit_px = sum((abs(f['signed']) * f['px'] for f in closing), D(0)) / cq if cq else None
    net = sum((f['closed_pnl'] - f['fee'] for f in fills), D(0))
    return dict(symbol=g['symbol'], side=side, entry_ms=first['ms'], exit_ms=fills[-1]['ms'],
                entry=entry, exit=exit_px, quantity=qty, net=net, fees=sum((f['fee'] for f in fills), D(0)),
                tids=[f['tid'] for f in fills], oids=sorted({f['oid'] for f in fills}),
                position=g['position'], partial_history=g['partial_history'])


def missing_trades(fills, recorded_tids):
    """Round trips whose fills the journal never attributed to a trade.

    A round trip is missing when none of its fills is recorded; one that is partly recorded is a
    journal conflict the caller must surface (never silently merged).
    """
    recorded = {str(t) for t in recorded_tids}
    closed, open_ = round_trips(fills)
    missing, conflicts = [], []
    for trip in closed:
        hit = [t for t in trip['tids'] if t in recorded]
        if not hit:
            missing.append(trip)
        elif len(hit) != len(trip['tids']):
            conflicts.append(dict(trip, recorded=hit))
    return missing, conflicts, open_


def entry_fills(fills, *, oid=None, cloid=None, symbol=None, since_ms=0):
    """Fills of one entry order: matched by exchange order id (preferred) or by symbol/time window."""
    rows = [normalize(f) for f in fills]
    if oid is not None:
        return [r for r in rows if r['oid'] == str(oid)]
    return [r for r in rows if r['symbol'] == symbol and r['ms'] >= since_ms]


def stop_slippage_bps(fill_px, trigger_px, position_side):
    """Adverse distance of a stop fill past its trigger, in bps (positive = worse than the trigger)."""
    fill_px, trigger_px = D(fill_px), D(trigger_px)
    if position_side == 'LONG':          # a sell stop: filling below the trigger is adverse
        return (trigger_px - fill_px) / trigger_px * 10000
    return (fill_px - trigger_px) / trigger_px * 10000
