"""Perpetual cost estimates. Estimates never replace actual fees on fills."""
from dataclasses import dataclass
from decimal import Decimal
from math import ceil

from .base_exchange import ExchangeError, decimal


@dataclass(frozen=True)
class FeeSchedule:
    maker: Decimal
    taker: Decimal
    source: str

    def __post_init__(self):
        object.__setattr__(self,'maker',decimal(self.maker))
        object.__setattr__(self,'taker',decimal(self.taker,nonnegative=True))
        if not self.source or abs(self.maker)>=1 or self.taker>=1:
            raise ExchangeError('INVALID_FEE_SCHEDULE')

    def fee(self, quantity, price, liquidity='TAKER'):
        if liquidity not in {'MAKER','TAKER'}:
            raise ExchangeError('UNKNOWN_FILL_LIQUIDITY')
        return decimal(quantity,positive=True)*decimal(price,positive=True)*(
            self.maker if liquidity=='MAKER' else self.taker)


@dataclass(frozen=True)
class TradeEconomics:
    gross_profit: Decimal
    fees: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    funding_cost: Decimal
    net_profit: Decimal
    stop_risk: Decimal
    net_rr: Decimal


def estimate_trade(side, quantity, reference, stop, target, quote, fees,
                   *, slippage_bps, holding_hours):
    if side not in {'BUY','SELL'}:
        raise ExchangeError('INVALID_SIDE')
    q=decimal(quantity,positive=True)
    ref,stop,target=(decimal(p,positive=True) for p in (reference,stop,target))
    sign=Decimal(1) if side=='BUY' else Decimal(-1)
    if sign*(target-ref)<=0 or sign*(ref-stop)<=0:
        raise ExchangeError('INVALID_STOP_TARGET_GEOMETRY')
    slip=decimal(slippage_bps,nonnegative=True)/10000
    hours=decimal(holding_hours,nonnegative=True)
    entry=quote.ask if side=='BUY' else quote.bid
    # Reference is the signal VWAP. Entry deviation already includes entry
    # spread; count only adverse deviation plus exit half-spread once.
    spread=q*(max(Decimal(0),sign*(entry-ref))+(quote.ask-quote.bid)/2)
    slippage=q*(entry+target)*slip
    fee=fees.fee(q,entry)+fees.fee(q,target)
    funding=q*quote.oracle*max(Decimal(0),sign*quote.hourly_funding)*ceil(hours)
    gross=q*sign*(target-ref)
    net=gross-fee-spread-slippage-funding
    stop_risk=q*sign*(ref-stop)+fees.fee(q,entry)+fees.fee(q,stop)+spread+q*(entry+stop)*slip+funding
    return TradeEconomics(gross,fee,spread,slippage,funding,net,stop_risk,
                          net/stop_risk if stop_risk>0 else Decimal(0))
