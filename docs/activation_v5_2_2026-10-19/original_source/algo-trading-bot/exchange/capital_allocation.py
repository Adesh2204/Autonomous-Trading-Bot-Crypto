"""Deterministic research/session sizing; this module grants no order authority.

The baseline route retains 10% of BOTH best levels. Multi-level capacity is an
additional constraint, never a replacement for that restriction. Intended stop
risk is an estimate, not a guaranteed loss bound through gaps or stop failure.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal as D
from .base_exchange import ExchangeError, decimal


@dataclass(frozen=True)
class CapitalLimits:
    bankroll: D
    maximum_notional: D
    maximum_total_exposure: D
    maximum_cumulative_allocation: D
    risk_fraction: D=D('.005')
    daily_loss_fraction: D=D('.01')
    margin_fraction: D=D('.5')
    participation: D=D('.1')
    slippage_bps: D=D('5')
    leverage: int=1

    def __post_init__(self):
        for name in ('bankroll','maximum_notional','maximum_total_exposure',
                     'maximum_cumulative_allocation','risk_fraction','daily_loss_fraction',
                     'margin_fraction','participation','slippage_bps'):
            object.__setattr__(self,name,decimal(getattr(self,name),nonnegative=True))
        if (self.bankroll<=0 or self.risk_fraction>D('.005') or self.daily_loss_fraction>D('.01')
                or not 0<self.margin_fraction<=D('.5') or not 0<self.participation<=D('.1')
                or self.slippage_bps>D('5') or type(self.leverage) is not int or self.leverage!=1):
            raise ExchangeError('CAPITAL_BASELINE_LIMIT_RELAXATION_PROHIBITED')


def floor_quantity(spec, value):
    value=decimal(value,nonnegative=True)
    return value.quantize(spec.size_step,rounding='ROUND_DOWN')


def validate_book(book, now_ms, *, maximum_age_ms=5000):
    if (type(now_ms) is not int or not 0<=now_ms-book.timestamp_ms<=maximum_age_ms
            or not book.symbol.startswith('par:') or not book.bids or not book.asks):
        raise ExchangeError('CAPITAL_FRESH_PAR_BOOK_REQUIRED')
    for levels,reverse in ((book.bids,True),(book.asks,False)):
        prices=[decimal(x.price,positive=True) for x in levels]
        if (len(set(prices))!=len(prices) or prices!=sorted(prices,reverse=reverse)
                or any(decimal(x.quantity,positive=True)<=0 for x in levels)):
            raise ExchangeError('CAPITAL_INVALID_DEPTH')
    if book.asks[0].price<=book.bids[0].price:raise ExchangeError('CAPITAL_CROSSED_BOOK')


def depth_capacity(book, side, slippage_bps=D('5')):
    if side not in {'BUY','SELL'}:raise ExchangeError('CAPITAL_INVALID_SIDE')
    tolerance=decimal(slippage_bps,nonnegative=True)/10000
    levels=book.asks if side=='BUY' else book.bids
    best=levels[0].price
    limit=best*(1+tolerance if side=='BUY' else 1-tolerance)
    depth=sum((x.quantity for x in levels if x.price<=limit),D(0)) if side=='BUY' else sum(
        (x.quantity for x in levels if x.price>=limit),D(0))
    return dict(best_price=best,best_quantity=levels[0].quantity,
        raw_l2_quantity=depth,limit=limit,side=side)


def walk_book(book, side, quantity, *, limit, participation=D('1')):
    """Finite displayed-depth simulation; no extrapolation beyond supplied levels."""
    if side not in {'BUY','SELL'}:raise ExchangeError('CAPITAL_INVALID_SIDE')
    remaining=decimal(quantity,nonnegative=True);requested=remaining
    participation=decimal(participation,positive=True);limit=decimal(limit,positive=True)
    if participation>1:raise ExchangeError('INVALID_BOOK_PARTICIPATION')
    cost=D(0);worst=None;levels=book.asks if side=='BUY' else book.bids
    for level in levels:
        if side=='BUY' and level.price>limit or side=='SELL' and level.price<limit:break
        take=min(remaining,level.quantity*participation)
        cost+=take*level.price;remaining-=take
        if take:worst=level.price
        if not remaining:break
    filled=requested-remaining
    return dict(requested_quantity=requested,filled_quantity=filled,residual_quantity=remaining,
        cost=cost,vwap=cost/filled if filled else None,worst_price=worst,
        full_fill=remaining==0,evidence='FINITE_DISPLAYED_DEPTH_SIMULATION_NOT_EXCHANGE_FILL')


def allocate(spec, book, side, stop_price, limits, *, now_ms, free_collateral,
             equity, entry_fee, exit_fee, funding_cost_per_unit=D(0),
             current_exposure=D(0), correlated_exposure=D(0), cumulative_allocation=D(0),
             daily_loss=D(0), existing_positions=0, unresolved_orders=0,
             maximum_trade_quantity=None):
    """Take the tightest independent quantity bound, then round DOWN to runtime lot."""
    validate_book(book,now_ms)
    if book.symbol!=spec.symbol:raise ExchangeError('CAPITAL_MARKET_IDENTITY_MISMATCH')
    if side not in {'BUY','SELL'}:raise ExchangeError('CAPITAL_INVALID_SIDE')
    if any(type(x) is not int or x<0 for x in (existing_positions,unresolved_orders)):
        raise ExchangeError('CAPITAL_EXPOSURE_COUNTS_REQUIRED')
    names=('free_collateral','equity','entry_fee','exit_fee','funding_cost_per_unit',
           'current_exposure','correlated_exposure','cumulative_allocation','daily_loss')
    values=dict(zip(names,(free_collateral,equity,entry_fee,exit_fee,funding_cost_per_unit,
        current_exposure,correlated_exposure,cumulative_allocation,daily_loss)))
    v={k:decimal(x,nonnegative=True) for k,x in values.items()}
    if v['entry_fee']>D('.003') or v['exit_fee']>D('.003'):
        raise ExchangeError('CAPITAL_FEE_BOUND_EXCEEDED')
    entry=depth_capacity(book,side,limits.slippage_bps)
    close=depth_capacity(book,'SELL' if side=='BUY' else 'BUY',limits.slippage_bps)
    price=entry['best_price'];stop=decimal(stop_price,positive=True)
    if side=='BUY' and stop>=price or side=='SELL' and stop<=price:
        raise ExchangeError('CAPITAL_STOP_DIRECTION_INVALID')
    friction=price*(v['entry_fee']+v['exit_fee']+2*limits.slippage_bps/10000)+v['funding_cost_per_unit']
    unit_risk=abs(price-stop)+friction
    loss_remaining=max(D(0),limits.bankroll*limits.daily_loss_fraction-v['daily_loss'])
    risk_budget=min(limits.bankroll*limits.risk_fraction,loss_remaining)
    margin_headroom=min(v['free_collateral'],v['equity']*limits.margin_fraction)
    bounds=dict(approved_notional=limits.maximum_notional/price,
        total_exposure=max(D(0),limits.maximum_total_exposure-v['current_exposure']-v['correlated_exposure'])/price,
        cumulative_allocation=max(D(0),limits.maximum_cumulative_allocation-v['cumulative_allocation'])/price,
        intended_stop_loss=risk_budget/unit_risk,
        margin=margin_headroom/(price/limits.leverage+price*(v['entry_fee']+v['exit_fee'])),
        entry_bbo=entry['best_quantity']*limits.participation,
        close_bbo=close['best_quantity']*limits.participation,
        entry_l2=entry['raw_l2_quantity']*limits.participation,
        close_l2=close['raw_l2_quantity']*limits.participation)
    if maximum_trade_quantity is not None:
        bounds['exchange_available_trade_size']=decimal(maximum_trade_quantity,nonnegative=True)
    reasons=[]
    if existing_positions or unresolved_orders or v['current_exposure'] or v['correlated_exposure']:
        bounds['single_position']=D(0);reasons.append('GLOBAL_SINGLE_POSITION_OR_UNRESOLVED_ORDER')
    if limits.bankroll>v['equity']:
        bounds['bankroll_exceeds_equity']=D(0);reasons.append('APPROVED_BANKROLL_EXCEEDS_ACTUAL_EQUITY')
    if not loss_remaining:reasons.append('DAILY_LOSS_BUDGET_EXHAUSTED')
    quantity=floor_quantity(spec,min(bounds.values()))
    if quantity*price<D('10'):
        quantity=D(0);reasons.append('NO_LOT_MEETS_MINIMUM_WITHIN_ALL_BOUNDS')
    notional=quantity*price
    return dict(symbol=spec.symbol,side=side,observed_ms=now_ms,source_book_ms=book.timestamp_ms,
        free_collateral_observed=v['free_collateral'],quantity=quantity,notional=notional,intended_loss=quantity*unit_risk,
        risk_budget=risk_budget,loss_budget_remaining=loss_remaining,
        initial_margin=notional/limits.leverage,maintenance_margin=spec.maintenance_margin(notional),
        collateral_reserved=notional/limits.leverage+notional*(v['entry_fee']+v['exit_fee']),
        binding_limits=sorted(k for k,x in bounds.items() if x==min(bounds.values())),
        quantity_bounds=bounds,entry_capacity=entry,close_capacity=close,reasons=reasons,
        route='BASELINE_10_PERCENT_BOTH_BEST_LEVELS',limits=asdict(limits),
        authority_granted=False,loss_bound_is_guaranteed=False)
