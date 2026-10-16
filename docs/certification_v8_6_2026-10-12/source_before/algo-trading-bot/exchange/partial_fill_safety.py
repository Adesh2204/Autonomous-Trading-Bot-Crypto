"""Conservative certification sizing under the documented $10 order minimum.

No documented par exemption for a sub-minimum full close or stop was found.
This module grants no exemption and never enlarges a position or close size.
An offline fixture is not evidence of actual exchange acceptance.
"""
from decimal import Decimal as D

from .base_exchange import ExchangeError, decimal

MIN_NOTIONAL = D('10')
VENUE_EXCEPTION_STATUS = 'NOT_ESTABLISHED_BY_AUTHORITATIVE_DOCUMENTATION'


def partial_path_assessment(spec, proposal):
    """Smallest entry fill and exit remainder are one runtime lot, not entry size."""
    if spec.symbol != proposal.symbol or spec.asset_id != proposal.asset_id:
        raise ExchangeError('CERTIFICATION_MARKET_MAPPING_CHANGED')
    quantity = decimal(proposal.quantity, positive=True)
    if quantity % spec.size_step or spec.normalize_size(quantity) != quantity:
        raise ExchangeError('CERTIFICATION_ENTRY_SIZE_NOT_EXACT')
    prices = {name: decimal(getattr(proposal, name), positive=True)
              for name in ('entry_limit', 'stop_limit', 'exit_bound')}
    notionals = {name: spec.size_step * price for name, price in prices.items()}
    ready = all(value >= MIN_NOTIONAL for value in notionals.values())
    return dict(symbol=spec.symbol, asset_id=spec.asset_id, size_step=str(spec.size_step),
        minimum_order_notional=str(MIN_NOTIONAL), smallest_possible_fill=str(spec.size_step),
        smallest_possible_exit_remainder=str(spec.size_step),
        one_lot_notionals={name: str(value) for name, value in notionals.items()},
        subminimum_full_close_exception=VENUE_EXCEPTION_STATUS,
        subminimum_protection_exception=VENUE_EXCEPTION_STATUS,
        entry_admissible_under_documented_minimum=ready,
        blocker=None if ready else 'SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED',
        scope='REVIEWED_LIMIT_PRICES_ONLY_NOT_A_FILL_OR_PROTECTION_GUARANTEE')


def exact_full_close_size(spec, position, *, side, maximum_quantity, limit_price):
    """Full observed remainder, with no rounding away dust or oversizing to $10."""
    if position.symbol != spec.symbol:
        raise ExchangeError('CERTIFICATION_RESIDUAL_MARKET_CONFLICT')
    signed = decimal(position.quantity)
    quantity = abs(signed)
    if (not quantity or side not in {'BUY', 'SELL'} or
            (signed > 0) == (side == 'BUY') or quantity > decimal(maximum_quantity, positive=True)):
        raise ExchangeError('CERTIFICATION_RESIDUAL_DIRECTION_OR_SIZE_CONFLICT')
    if quantity % spec.size_step or spec.normalize_size(quantity) != quantity:
        raise ExchangeError('CERTIFICATION_RESIDUAL_PRECISION_UNREPRESENTABLE')
    price = decimal(limit_price, positive=True)
    if spec.normalize_price(price, side) != price:
        raise ExchangeError('CERTIFICATION_CLOSE_PRICE_NOT_EXACT')
    if quantity * price < MIN_NOTIONAL:
        raise ExchangeError('SUB_MINIMUM_RESIDUAL_CLOSE_NOT_VERIFIED')
    return quantity


def residual_observation(spec, position, proposal, observed_ms):
    """Durable evidence of remaining exposure, never a synthetic flattening."""
    quantity = abs(decimal(position.quantity))
    exact = bool(quantity and quantity % spec.size_step == 0)
    return dict(symbol=position.symbol, signed_quantity=str(position.quantity),
        quantity=str(quantity), observed_ms=observed_ms, size_step=str(spec.size_step),
        lot_representable=exact,
        protection_limit_notional=str(quantity * decimal(proposal.stop_limit)),
        approved_exit_bound_notional=str(quantity * decimal(proposal.exit_bound)),
        subminimum_at_reviewed_bounds=quantity * min(decimal(proposal.stop_limit),
            decimal(proposal.exit_bound)) < MIN_NOTIONAL,
        operator_review_required=(not exact or quantity * min(decimal(proposal.stop_limit),
            decimal(proposal.exit_bound)) < MIN_NOTIONAL),
        full_close_exception_status=VENUE_EXCEPTION_STATUS)


# Explicit documented orderStatus values. Never infer rejection from unknownOid
# or from a missing order in a current open-order list.
TERMINAL_REJECTIONS = frozenset({
    'rejected', 'tickRejected', 'minTradeNtlRejected', 'perpMarginRejected',
    'reduceOnlyRejected', 'badAloPxRejected', 'iocCancelRejected',
    'badTriggerPxRejected', 'marketOrderNoLiquidityRejected',
    'positionIncreaseAtOpenInterestCapRejected', 'positionFlipAtOpenInterestCapRejected',
    'tooAggressiveAtOpenInterestCapRejected', 'openInterestIncreaseRejected',
    'insufficientSpotBalanceRejected', 'oracleRejected', 'perpMaxPositionRejected',
})
TERMINAL_CANCELLATIONS = frozenset({
    'canceled', 'cancelled', 'marginCanceled', 'vaultWithdrawalCanceled',
    'openInterestCapCanceled', 'selfTradeCanceled', 'reduceOnlyCanceled',
    'siblingFilledCanceled', 'delistedCanceled', 'liquidatedCanceled', 'scheduledCancel',
})
