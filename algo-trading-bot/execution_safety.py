"""Execution-only identity, quote quality, transaction fees and integer sizing.

No imports from signal_brain and no indicator or strategy parameter overrides.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
import config

class SafetyError(ValueError):
    pass

def positive(value):
    return not isinstance(value,bool) and math.isfinite(float(value)) and float(value)>0

@dataclass(frozen=True)
class InstrumentIdentity:
    symbol: str
    exchange: str
    token: str
    trading_symbol: str
    series: str
    tick_size: float
    lot_size: int
    instrument_type: str
    source_timestamp: datetime
    intraday_eligible: bool = True

    def validate(self, symbol, token=None, exchange=None, now=None):
        if (symbol not in {self.symbol,self.trading_symbol} or
            (token is not None and str(token)!=self.token) or
            (exchange is not None and exchange!=self.exchange) or
            self.exchange!='NSE' or self.series!='EQ' or not self.intraday_eligible or
            self.trading_symbol!=self.symbol+'-EQ' or self.instrument_type!='CASH' or
            not isinstance(self.token,str) or not self.token or not positive(self.tick_size) or
            isinstance(self.lot_size,bool) or not isinstance(self.lot_size,int) or self.lot_size<1):
            raise SafetyError('INSTRUMENT_IDENTITY_MISMATCH')
        if self.source_timestamp.tzinfo is None:
            raise SafetyError('INSTRUMENT_MASTER_STALE')
        if now and not timedelta(0) <= now-self.source_timestamp <= timedelta(hours=config.INSTRUMENT_MAX_AGE_HOURS):
            raise SafetyError('INSTRUMENT_MASTER_STALE')

    def price(self, value, side):
        rounding=ROUND_CEILING if side=='BUY' else ROUND_FLOOR
        return float((Decimal(str(value))/Decimal(str(self.tick_size))).to_integral_value(rounding=rounding)*Decimal(str(self.tick_size)))

    def to_dict(self):
        data=asdict(self); data['source_timestamp']=self.source_timestamp.isoformat(); return data

    @classmethod
    def from_dict(cls,data):
        d=dict(data); d['source_timestamp']=datetime.fromisoformat(d['source_timestamp']); return cls(**d)

@dataclass(frozen=True)
class MarketQuote:
    bid: float
    ask: float
    bid_quantity: int
    ask_quantity: int
    timestamp: datetime
    last: float
    cumulative_volume: float = 0.

    @property
    def spread_pct(self):
        return (self.ask-self.bid)/self.bid if positive(self.bid) else math.inf

    def executable(self,side):
        return self.ask if side=='BUY' else self.bid

class ExecutionQualityGate:
    def validate(self,quote,side,now,quantity=1):
        if side not in {'BUY','SELL'} or isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<1:
            raise SafetyError('INVALID_EXECUTION_REQUEST')
        if not isinstance(quote,MarketQuote) or not positive(quote.bid) or not positive(quote.ask) or quote.ask<quote.bid:
            raise SafetyError('NO_VALID_BID_ASK')
        if quote.timestamp.tzinfo is None or not 0 <= (now-quote.timestamp).total_seconds() <= config.EXECUTION_QUOTE_MAX_AGE_SECONDS:
            raise SafetyError('QUOTE_STALE')
        if quote.spread_pct > config.SCREEN_MAX_SPREAD_PCT:
            raise SafetyError('SPREAD_TOO_WIDE')
        depth=quote.ask_quantity if side=='BUY' else quote.bid_quantity
        if not positive(depth):raise SafetyError('DEPTH_INSUFFICIENT')
        if quantity > depth*config.BEST_LEVEL_MAX_PARTICIPATION:
            raise SafetyError('DEPTH_INSUFFICIENT')
        if not positive(quote.last) or abs(quote.executable(side)/quote.last-1)>config.MAX_QUOTE_DISCONTINUITY_PCT:
            raise SafetyError('EXPECTED_IMPACT_TOO_HIGH')
        return quote.executable(side)

class FeeModel:
    """Single standard Angel One NSE cash intraday fee formula, per order."""
    def leg(self,side,price,quantity):
        if side not in {'BUY','SELL'} or quantity<=0 or not positive(price):
            raise SafetyError('INVALID_FEE_INPUT')
        v=price*quantity
        b=max(config.BROKERAGE_MIN,min(config.BROKERAGE_CAP,v*config.BROKERAGE_PCT))
        ex=v*config.NSE_TRANSACTION_RATE; sebi=v*config.SEBI_TURNOVER_RATE; ipft=v*config.IPFT_RATE
        stt=v*config.INTRADAY_STT_SELL_RATE if side=='SELL' else 0.
        stamp=v*config.INTRADAY_STAMP_BUY_RATE if side=='BUY' else 0.
        gst=(b+ex+sebi+ipft)*config.GST_RATE
        return {'turnover':v,'brokerage':b,'stt':stt,'stamp_duty':stamp,'exchange_fee':ex,
                'sebi_fee':sebi,'ipft':ipft,'gst':gst,'total_charges':b+ex+sebi+ipft+stt+stamp+gst}

@dataclass(frozen=True)
class TradeEconomics:
    quantity: int
    estimated_entry: float
    entry_notional: float
    cash_required: float
    entry_fees: float
    stop_exit_fees: float
    target_exit_fees: float
    gross_stop_loss: float
    net_stop_loss: float
    gross_target_profit: float
    net_target_profit: float
    net_rr: float
    estimated_slippage: float
    estimated_spread_cost: float = 0.

def estimate_trade_economics(side,quantity,estimated_entry,stop,target,slippage_allowance=None,*,exit_spread_pct=0.,tick_size=None):
    if side not in {'BUY','SELL'} or quantity<1 or not all(positive(x) for x in (estimated_entry,stop,target)):
        raise SafetyError('INVALID_ECONOMICS')
    slip=config.SLIPPAGE_HAIRCUT_PCT if slippage_allowance is None else slippage_allowance
    if not math.isfinite(slip) or slip<0 or slip>=1 or not math.isfinite(exit_spread_pct) or exit_spread_pct<0 or slip+exit_spread_pct>=1:
        raise SafetyError('INVALID_SLIPPAGE')
    sign=1 if side=='BUY' else -1
    # bid/ask has already incorporated spread; adding spread again would double count it.
    entry=estimated_entry*(1+sign*slip)
    stop_fill=stop*(1-sign*(slip+exit_spread_pct)); target_fill=target*(1-sign*(slip+exit_spread_pct))
    if tick_size is not None:
        if not positive(tick_size):raise SafetyError('INVALID_TICK_SIZE')
        rounding=ROUND_FLOOR if side=='BUY' else ROUND_CEILING
        def rounded(price):return float((Decimal(str(price))/Decimal(str(tick_size))).to_integral_value(rounding=rounding)*Decimal(str(tick_size)))
        stop_fill=rounded(stop_fill); target_fill=rounded(target_fill)
    if sign*(entry-stop_fill)<=0 or sign*(target_fill-entry)<=0:
        raise SafetyError('FRICTION_FAILED')
    f=FeeModel(); exit_side='SELL' if side=='BUY' else 'BUY'
    ec=f.leg(side,entry,quantity)['total_charges']
    sc=f.leg(exit_side,stop_fill,quantity)['total_charges']
    tc=f.leg(exit_side,target_fill,quantity)['total_charges']
    loss=sign*(entry-stop_fill)*quantity; gain=sign*(target_fill-entry)*quantity
    net_loss=loss+ec+sc; net_gain=gain-ec-tc
    adverse=quantity*(abs(entry-estimated_entry)+abs(stop_fill-stop))
    return TradeEconomics(quantity,entry,entry*quantity,entry*quantity+ec+config.CASH_BUFFER_RS,
                          ec,sc,tc,loss,net_loss,gain,net_gain,net_gain/net_loss,adverse,quantity*stop*exit_spread_pct)

def solve_quantity(side,entry,stop,target,cash,setup_risk,daily_remaining,required_rr,slippage=None,lot_size=1,max_quantity=None,*,exit_spread_pct=0.,tick_size=None):
    if not all(positive(x) for x in (cash,setup_risk,daily_remaining,entry)) or lot_size<1:
        return None
    cap=int(cash/entry)
    if max_quantity is not None: cap=min(cap,max_quantity)
    cap-=cap%lot_size
    for q in range(cap,0,-lot_size):
        try: e=estimate_trade_economics(side,q,entry,stop,target,slippage,exit_spread_pct=exit_spread_pct,tick_size=tick_size)
        except SafetyError: continue
        if e.cash_required<=cash and e.net_stop_loss<=min(setup_risk,daily_remaining) and e.net_rr>=required_rr and e.net_target_profit>=config.MIN_NET_PROFIT_RS:
            return e
    return None


def capital_protection_prices(instrument,side,entry,quantity,entry_fees,risk_budget,realized_exit_loss=0.):
    """Emergency boundary from rupee risk, independent of VWAP/ATR strategy levels.

    Limit price models estimated fees at that price. Stop-limit execution through a
    gap is not guaranteed; the quote watchdog separately requests liquidation.
    """
    remaining=risk_budget-entry_fees-realized_exit_loss
    if remaining<=0 or quantity<1:raise SafetyError('CAPITAL_RISK_BUDGET_EXHAUSTED')
    sign=1 if side=='BUY' else -1
    exit_side='SELL' if side=='BUY' else 'BUY'
    def loss(price):return sign*(entry-price)*quantity+FeeModel().leg(exit_side,price,quantity)['total_charges']
    low=instrument.tick_size if side=='BUY' else entry
    high=entry if side=='BUY' else entry+2*remaining/quantity+instrument.tick_size
    if loss(entry)>remaining:raise SafetyError('CAPITAL_RISK_BUDGET_EXHAUSTED')
    for _ in range(64):
        middle=(low+high)/2
        if (loss(middle)>remaining)==(side=='BUY'):low=middle
        else:high=middle
    boundary=high if side=='BUY' else low
    limit=instrument.price(boundary,'BUY' if side=='BUY' else 'SELL')
    trigger=limit+sign*instrument.tick_size
    return trigger,limit
