"""Read-only one-lot LONG review. It never grants an SDK execution permit.

Reviewed prices mirror the existing isolated certification test, not VWAP stops.
No book is reconstructed from a mark, oracle, candle or prior observation.
"""
from decimal import Decimal as D

from .base_exchange import ExchangeError, VenueMismatch, decimal
from .hyperliquid_client import EXPECTED_MARKETS
from .hyperliquid_market_data import make_quote, parse_book
from .partial_fill_safety import MIN_NOTIONAL, VENUE_EXCEPTION_STATUS


def review_one_lot_long(spec, raw_book, context, active_asset, *, now_ms,
                        context_observed_ms, taker_fee_rate, max_notional=D(25)):
    """Independently report price, liquidity, margin and minimum-size blockers.

An eligible review is only a mathematical candidate for a subsequent fresh
account/central-validator preflight and exact human approval. It is not a
CertificationProposal and says nothing about actual protection acceptance.
"""
    if spec.symbol not in EXPECTED_MARKETS:
        raise VenueMismatch('OFFICIAL_PAR_MARKET_REQUIRED')
    cap = decimal(max_notional, positive=True)
    if cap > 25:
        raise ExchangeError('CERTIFICATION_NOTIONAL_CAP_INCREASE_PROHIBITED')
    fee = decimal(taker_fee_rate, nonnegative=True)
    mark = decimal(context['markPx'], positive=True)
    oracle = decimal(context['oraclePx'], positive=True)
    blockers = []
    row = dict(symbol=spec.symbol, asset_id=spec.asset_id, size_decimals=spec.size_decimals,
        lot_size=str(spec.size_step), max_leverage=spec.max_leverage,
        observed_ms=now_ms, context_observed_ms=context_observed_ms,
        mark=str(mark), oracle=str(oracle), mark_lot_notional=str(spec.size_step*mark),
        oracle_lot_notional=str(spec.size_step*oracle), reviewed_notional_cap=str(cap),
        minimum_order_notional=str(MIN_NOTIONAL), reviewed_quantity=str(spec.size_step),
        subminimum_close_evidence=VENUE_EXCEPTION_STATUS,
        subminimum_protection_evidence=VENUE_EXCEPTION_STATUS,
        exchange_protection_accepted=False, order_authorized=False, executable=False,
        eligible_under_reviewed_bounds=False, blockers=blockers,
        prices=None, limit_notionals=None, depth=None, estimated_round_trip_fee=None,
        planned_loss_at_bound_including_fees=None,
        scope='READ_ONLY_REVIEW_NOT_AN_EXECUTION_OR_FILL_GUARANTEE')
    try:
        book = parse_book(raw_book, spec.symbol)
        quote = make_quote(book, context, now_ms, mark_timestamp_ms=context_observed_ms)
    except ExchangeError as exc:
        blockers.append(str(exc))
        return row
    if type(context_observed_ms) is not int or not 0 <= now_ms-context_observed_ms <= 5000:
        blockers.append('ASSET_CONTEXT_OBSERVATION_STALE')
    if quote.ask == quote.bid:
        blockers.append('CERTIFICATION_NONZERO_SPREAD_REQUIRED')
    spread = (quote.ask-quote.bid)/quote.mid*10000
    mark_gap = abs(mark-oracle)/oracle*10000
    mid_gap = abs(quote.mid-oracle)/oracle*10000
    if spread > 15: blockers.append('CERTIFICATION_SPREAD_EXCEEDED')
    if mark_gap > 50: blockers.append('CERTIFICATION_MARK_ORACLE_DIVERGENCE')
    if mid_gap > 100: blockers.append('CERTIFICATION_MID_ORACLE_DIVERGENCE')
    entry = spec.normalize_price(quote.ask*D('1.0005'), 'BUY')
    trigger = spec.normalize_price(quote.bid*D('.99'), 'SELL')
    bound = spec.normalize_price(trigger*D('.995'), 'SELL')
    if not bound < trigger < entry or entry < quote.ask:
        blockers.append('CERTIFICATION_PRICE_GEOMETRY_OR_ENTRY_CROSSING')
    size = spec.size_step
    notionals = dict(entry_limit=size*entry, stop_limit=size*bound, exit_bound=size*bound)
    if notionals['entry_limit'] < MIN_NOTIONAL:
        blockers.append('ONE_LOT_ENTRY_BELOW_MINIMUM')
    if min(notionals['stop_limit'], notionals['exit_bound']) < MIN_NOTIONAL:
        blockers.append('ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM')
    if min(notionals.values()) == MIN_NOTIONAL:
        blockers.append('ONE_LOT_NO_MINIMUM_HEADROOM')
    if max(notionals['entry_limit'], size*mark) > cap:
        blockers.append('ONE_LOT_EXCEEDS_REVIEWED_NOTIONAL_CAP')
    if size > min(quote.bid_quantity, quote.ask_quantity)*D('.1'):
        blockers.append('CERTIFICATION_BBO_DEPTH_FRACTION_EXCEEDED')
    if active_asset.get('coin') != spec.symbol:
        blockers.append('ACTIVE_ASSET_MARKET_IDENTITY_CONFLICT')
    if active_asset.get('leverage') != dict(type='cross', value=1):
        blockers.append('CERTIFICATION_ONE_X_CROSS_REQUIRED')
    try:
        capacity = decimal(active_asset['availableToTrade'][0], nonnegative=True)
        maximum_size = decimal(active_asset['maxTradeSzs'][0], nonnegative=True)
        if size > maximum_size or notionals['entry_limit']*(1+fee*4) > capacity:
            blockers.append('CERTIFICATION_SIDE_CAPACITY_INSUFFICIENT')
    except (ExchangeError, KeyError, TypeError, IndexError):
        blockers.append('CERTIFICATION_SIDE_CAPACITY_UNAVAILABLE')
        capacity = maximum_size = None
    estimated_fee = size*(entry+bound)*fee
    planned_loss = size*(entry-bound)+estimated_fee
    if planned_loss > 10: blockers.append('CERTIFICATION_LOSS_BUDGET_EXCEEDED')
    row.update(prices=dict(entry_limit=str(entry), stop_trigger=str(trigger),
        stop_limit=str(bound), exit_bound=str(bound)),
        limit_notionals={k:str(v) for k,v in notionals.items()},
        minimum_headroom_at_bound=str(min(notionals.values())-MIN_NOTIONAL),
        spread_bps=str(spread), mark_oracle_bps=str(mark_gap), mid_oracle_bps=str(mid_gap),
        quote=dict(bid=str(quote.bid), ask=str(quote.ask), timestamp_ms=book.timestamp_ms),
        depth=dict(best_bid_quantity=str(quote.bid_quantity), best_ask_quantity=str(quote.ask_quantity),
            entry_quantity_within_limit=str(sum((x.quantity for x in book.asks if x.price <= entry), D(0))),
            exit_quantity_within_bound=str(sum((x.quantity for x in book.bids if x.price >= bound), D(0))),
            levels_at_bid=len(book.bids), levels_at_ask=len(book.asks),
            scope='CURRENT_BOOK_ONLY_NOT_FUTURE_STOP_LIQUIDITY'),
        available_long_collateral=None if capacity is None else str(capacity),
        maximum_long_size=None if maximum_size is None else str(maximum_size),
        estimated_round_trip_fee=str(estimated_fee),
        planned_loss_at_bound_including_fees=str(planned_loss),
        eligible_under_reviewed_bounds=not blockers)
    return row
