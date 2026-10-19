"""Versioned price envelope for one separately approved native experiment.

The approved proposal never changes. Select once from fresh context BEFORE the
durable intent/wire is created, then only validate that immutable wire at each
SDK boundary. Ordinary strategy and legacy qualification price rules are intact.
"""
from dataclasses import dataclass
from decimal import Decimal as D

from .base_exchange import ExchangeError, decimal
from .native_qualification import NativeQualificationProposal, NativeQualificationApproval

CORRIDOR_MODE = 'NATIVE_CURRENT_ASK_CORRIDOR_IOC_V2'


@dataclass(frozen=True)
class CorridorNativeProposal(NativeQualificationProposal):
    pricing_mode: str = CORRIDOR_MODE
    minimum_ask: str = ''
    maximum_ask: str = ''
    maximum_buy_price: str = ''
    maximum_adverse_movement_bps: str = '10'
    maximum_adverse_movement_absolute: str = '100'
    maximum_favourable_movement_bps: str = '10'
    maximum_favourable_movement_absolute: str = '100'
    reference_funding_rate: str = '0'
    maximum_abs_funding_rate: str = '.001'

    def require(self):
        super().require()
        if self.pricing_mode != CORRIDOR_MODE or decimal(self.entry_slippage_bps) != 5:
            raise ExchangeError('NATIVE_CORRIDOR_ROUTE_POLICY_REQUIRED')
        lo, hi, cap = (decimal(x, positive=True) for x in
            (self.minimum_ask, self.maximum_ask, self.maximum_buy_price))
        ref = decimal(self.reference_ask, positive=True)
        if (not lo <= ref <= hi <= cap or cap != decimal(self.entry_limit)
                or not 0 < decimal(self.maximum_adverse_movement_bps) <= 10
                or not 0 < decimal(self.maximum_favourable_movement_bps) <= 10
                or not 0 < decimal(self.maximum_adverse_movement_absolute) <= 100
                or not 0 < decimal(self.maximum_favourable_movement_absolute) <= 100
                or not 0 < decimal(self.maximum_abs_funding_rate) <= D('.001')
                or abs(decimal(self.reference_funding_rate)) > decimal(self.maximum_abs_funding_rate)):
            raise ExchangeError('INVALID_EXACT_NATIVE_PRICE_CORRIDOR')
        return self


@dataclass(frozen=True)
class CorridorNativeApproval(NativeQualificationApproval):
    bounded_price_corridor_accepted: bool = False
    unqualified_native_test_exception_accepted: bool = False


def corridor_bounds(spec, reference_ask, *, adverse_bps='10', adverse_absolute='100',
                    favourable_bps='10', favourable_absolute='100'):
    ref = decimal(reference_ask, positive=True)
    adverse = min(ref*decimal(adverse_bps, positive=True)/10000,
                  decimal(adverse_absolute, positive=True))
    favourable = min(ref*decimal(favourable_bps, positive=True)/10000,
                     decimal(favourable_absolute, positive=True))
    lo = spec.normalize_price(ref-favourable, 'SELL')
    hi = spec.normalize_price(ref+adverse, 'BUY')
    cap = spec.normalize_price(hi*D('1.0005'), 'BUY')
    return dict(minimum_ask=str(lo), maximum_ask=str(hi), maximum_buy_price=str(cap))


def require_corridor_mapping(spec, proposal):
    p = proposal.require()
    expected = corridor_bounds(spec, p.reference_ask,
        adverse_bps=p.maximum_adverse_movement_bps, adverse_absolute=p.maximum_adverse_movement_absolute,
        favourable_bps=p.maximum_favourable_movement_bps, favourable_absolute=p.maximum_favourable_movement_absolute)
    if any(decimal(getattr(p, k)) != decimal(v) for k, v in expected.items()):
        raise ExchangeError('NATIVE_CORRIDOR_PRECISION_OR_ENVELOPE_CHANGED')
    return expected


def select_entry_price(spec, proposal, current_ask):
    require_corridor_mapping(spec, proposal)
    ask = decimal(current_ask, positive=True)
    if not decimal(proposal.minimum_ask) <= ask <= decimal(proposal.maximum_ask):
        raise ExchangeError('NATIVE_CURRENT_ASK_OUTSIDE_APPROVED_CORRIDOR')
    price = spec.normalize_price(ask*D('1.0005'), 'BUY')
    if not ask <= price <= decimal(proposal.maximum_buy_price):
        raise ExchangeError('NATIVE_CORRIDOR_EXECUTABLE_ROUNDING_REQUIRED')
    return price


def check_selected_price(context, proposal, price):
    p = proposal.require(); spec = context.spec; ask = context.quote.ask
    require_corridor_mapping(spec, p)
    px = decimal(price, positive=True)
    if (not decimal(p.minimum_ask) <= ask <= decimal(p.maximum_ask)
            or spec.normalize_price(px, 'BUY') != px
            or not ask <= px <= ask*D('1.0005') or px > decimal(p.maximum_buy_price)):
        raise ExchangeError('NATIVE_SELECTED_WIRE_OUTSIDE_FRESH_CORRIDOR')
    try:
        funding = abs(decimal(context.contexts[p.symbol]['funding']))
    except (KeyError, TypeError):
        raise ExchangeError('NATIVE_CURRENT_FUNDING_REQUIRED') from None
    if funding > decimal(p.maximum_abs_funding_rate):
        raise ExchangeError('NATIVE_FUNDING_ABOVE_APPROVED_CEILING')
    # A funding boundary can occur within five minutes: reserve one full hourly
    # observation, not a fictitious pro-rata charge or a prediction of actual P&L.
    qty = decimal(p.quantity); floor = decimal(p.exit_bound)
    reserve = qty*px*funding
    planned = qty*(px-floor)+qty*(px+floor)*decimal(p.taker_fee_rate)+reserve
    if planned > decimal(p.session_loss_budget):
        raise ExchangeError('NATIVE_CORRIDOR_LOSS_AND_FUNDING_RESERVE_EXCEEDED')
    return dict(price=str(px), current_ask=str(ask), maximum_buy_price=p.maximum_buy_price,
        observed_abs_funding_rate=str(funding), funding_reserve=str(reserve),
        planned_loss_plus_reserve=str(planned))
