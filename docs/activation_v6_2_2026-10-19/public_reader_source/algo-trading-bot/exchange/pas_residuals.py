"""Exact PAS residual classification, separate from native-stop qualification.

The operator-reported full-position exception is not native-stop evidence.
This pure planner never signs, expands size, rounds away dust or grants permits.
"""
from dataclasses import dataclass
from .base_exchange import ExchangeError, NormalizedOrder, decimal
from .venue_profiles import SCORED


def classify_reduction(spec,position,request,*,now_ms,position_ms,reconciled):
    if (spec.symbol not in SCORED.markets or request.symbol!=spec.symbol or
            type(now_ms) is not int or type(position_ms) is not int or not 0<=now_ms-position_ms<=5000
            or reconciled is not True):
        raise ExchangeError('PAS_FRESH_EXACT_POSITION_EVIDENCE_REQUIRED')
    quantity=decimal(request.quantity,positive=True);price=decimal(request.price,positive=True)
    if spec.normalize_size(quantity)!=quantity or spec.normalize_price(price,request.side)!=price:
        raise ExchangeError('PAS_CLOSE_PRECISION_CANNOT_LEAVE_RESIDUAL')
    if request.reduce_only is not True:
        if quantity*price<10:raise ExchangeError('ORDER_BELOW_MINIMUM_NOTIONAL')
        return dict(kind='ENTRY',minimum_exception=False,signing_authority=False)
    if (position is None or position.symbol!=spec.symbol or not position.quantity
            or request.side not in {'BUY','SELL'} or (position.quantity>0)==(request.side=='BUY')
            or quantity>abs(position.quantity)):
        raise ExchangeError('PAS_REDUCE_ONLY_POSITION_MISMATCH')
    full=quantity==abs(position.quantity)
    if not full and quantity*price<10:raise ExchangeError('PARTIAL_REDUCTION_BELOW_MINIMUM')
    if request.order_type!='LIMIT' or request.tif!='Ioc':
        raise ExchangeError('PAS_NATIVE_ROUTE_REQUIRES_SEPARATE_QUALIFICATION')
    return dict(kind='FULL_POSITION_CLOSE' if full else 'PARTIAL_REDUCTION',
        minimum_exception=bool(full and quantity*price<10),quantity=str(quantity),
        normal_order=NormalizedOrder(spec.symbol,request.side,quantity,price,spec.asset_id,True,'Ioc'),
        organizer_clarification='OPERATOR_REPORTED; original organizer record and genuine PAS route proof still required',
        genuine_venue_route_qualified=False,native_stop_qualified=False,signing_authority=False)
