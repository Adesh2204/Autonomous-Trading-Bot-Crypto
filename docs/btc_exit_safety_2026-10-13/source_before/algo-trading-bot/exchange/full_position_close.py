"""Narrow historical testnet par close scope; never a stop or entry exception.

V8.5 independently re-read original orders and matching full-position fills.
Evidence SHA-256: c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764
docs/certification_v8_5_2026-10-12/independent_close_readback/one_lot_readback.json
This is observational scope, not a claim of a documented universal exemption.
Normal minimum validation and all authorization gates remain independent.
"""
from decimal import Decimal as D
from types import MappingProxyType

from .base_exchange import ExchangeError, NormalizedOrder, decimal

FULL_POSITION_CLOSE = 'VERIFIED_EXACT_FULL_POSITION_IOC_CLOSE'
# symbol -> (asset ID, size decimals, close side -> exact observed sizes/OIDs).
# No extrapolation to other sizes, directions, instruments or trigger orders.
SCOPES = MappingProxyType({
    'par:BTC': (2670000, 4, (('BUY', '.0001', 62391880965), ('SELL', '.0001', 62228843959))),
    'par:ETH': (2670001, 4, (('BUY', '.0001', 61841673908),)),
    'par:HYPE': (2670002, 2, (('BUY', '.01', 61878767079),)),
    'par:BRENT': (2670006, 2, (('SELL', '.01', 61912483832),)),
    'par:EWJ': (2670005, 3, (('BUY', '.001', 61956380536),)),
})


def observed_scope(spec, side, quantity):
    row = SCOPES.get(spec.symbol)
    if row is None or (spec.asset_id, spec.size_decimals) != row[:2]:
        raise ExchangeError('SUBMINIMUM_FULL_CLOSE_SCOPE_NOT_VERIFIED')
    match = [oid for direction, size, oid in row[2]
             if direction == side and decimal(quantity) == D(size)]
    if len(match) != 1:
        raise ExchangeError('SUBMINIMUM_FULL_CLOSE_SCOPE_NOT_VERIFIED')
    return dict(scope=FULL_POSITION_CLOSE, historical_oid=match[0],
                evidence='V8.5_ORIGINAL_ORDER_AND_FULL_POSITION_FILL_READBACK',
                evidence_sha256='c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764')


def normalize_exact_full_close(spec, request, context, now_ms):
    """No rounding of a held position; require independent fresh account truth."""
    if (request.reduce_only is not True or request.order_type != 'LIMIT' or request.tif != 'Ioc'
            or request.strategy_id not in {'EXACT_FULL_POSITION_CLOSE', 'TESTNET_CERTIFICATION_EXIT'}):
        raise ExchangeError('EXACT_FULL_CLOSE_OPERATION_REQUIRED')
    if not context.reconciled or not 0 <= now_ms-context.account_ms <= 5000:
        raise ExchangeError('EXACT_FULL_CLOSE_FRESH_RECONCILIATION_REQUIRED')
    if len(context.positions) != 1 or request.symbol not in context.positions:
        raise ExchangeError('EXACT_FULL_CLOSE_SOLE_POSITION_REQUIRED')
    held = context.positions[request.symbol]
    quantity = decimal(request.quantity, positive=True)
    price = decimal(request.price, positive=True)
    if (held.symbol != request.symbol or not held.quantity or quantity != abs(held.quantity)
            or (held.quantity > 0) == (request.side == 'BUY')):
        raise ExchangeError('EXACT_FULL_CLOSE_POSITION_MISMATCH')
    if spec.normalize_size(quantity) != quantity or spec.normalize_price(price, request.side) != price:
        raise ExchangeError('EXACT_FULL_CLOSE_PRECISION_MISMATCH')
    scope = observed_scope(spec, request.side, quantity) if quantity*price < 10 else None
    return NormalizedOrder(request.symbol, request.side, quantity, price, spec.asset_id, True, 'Ioc'), scope
