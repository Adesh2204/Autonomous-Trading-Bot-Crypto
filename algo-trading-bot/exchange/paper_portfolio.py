"""One explicitly labelled paper collateral pool for perpetual positions."""
from dataclasses import dataclass
from decimal import Decimal
import time

from .base_exchange import ExchangeError, decimal
from .event_timing import timing


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    leverage: int


@dataclass(frozen=True)
class PortfolioSnapshot:
    timestamp_ms: int
    cash: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    initial_margin: Decimal
    maintenance_margin_estimate: Decimal
    order_reservations: Decimal
    available_margin: Decimal
    gross_notional: Decimal
    realized_pnl: Decimal
    fees_paid: Decimal
    funding_cashflow: Decimal
    collateral: str='USDP'


@dataclass(frozen=True)
class FundingSettlement:
    symbol: str
    timestamp_ms: int
    oracle_price: Decimal
    hourly_rate: Decimal
    source: str

    def __post_init__(self):
        if (type(self.timestamp_ms) is not int or self.timestamp_ms<0 or
                self.timestamp_ms % 3600000 or self.source not in
                {'OBSERVED_SETTLEMENT','PAPER_SNAPSHOT_ESTIMATE'}):
            raise ExchangeError('INVALID_FUNDING_SETTLEMENT')
        object.__setattr__(self,'oracle_price',decimal(self.oracle_price,positive=True))
        object.__setattr__(self,'hourly_rate',decimal(self.hourly_rate))


class PaperPortfolio:
    def __init__(self, specifications, starting_collateral, *, clock_ms=None, collateral='USDP'):
        self.clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)
        self.specs=dict(specifications)
        if not isinstance(collateral,str) or not collateral.strip():
            raise ExchangeError('PAPER_COLLATERAL_IDENTITY_REQUIRED')
        self.collateral=collateral.strip()
        self.starting_collateral=decimal(starting_collateral,positive=True)
        self.cash=self.starting_collateral
        self.positions={}
        self.reservations={}
        self.realized_pnl=Decimal(0)
        self.fees_paid=Decimal(0)
        self.funding_cashflow=Decimal(0)
        self.events=[]
        self._fills={}
        self._funding={}
        self.last_event_ms=-1

    def _causal(self, timestamp_ms):
        if type(timestamp_ms) is not int or timestamp_ms<self.last_event_ms:
            raise ExchangeError('NON_CAUSAL_PORTFOLIO_EVENT')

    def apply_fill(self, fill, leverage):
        prior=self._fills.get(fill.fill_id)
        if prior is not None:
            if prior!=fill:
                raise ExchangeError('CONFLICTING_PAPER_FILL')
            return False
        self._causal(fill.timestamp_ms)
        spec=self.specs[fill.symbol]
        if type(leverage) is not int or not 1<=leverage<=spec.max_leverage:
            raise ExchangeError('INVALID_PAPER_LEVERAGE')
        q=decimal(fill.quantity,positive=True)
        price=decimal(fill.price,positive=True)
        fee=decimal(fill.fee)
        if fill.side not in {'BUY','SELL'}:
            raise ExchangeError('INVALID_SIDE')
        delta=q if fill.side=='BUY' else -q
        position=self.positions.get(fill.symbol)
        held=position.quantity if position else Decimal(0)
        pnl=Decimal(0)
        if held and (held>0)!=(delta>0):
            closed=min(abs(held),abs(delta))
            pnl=closed*(price-position.entry_price)*(1 if held>0 else -1)
        remaining=held+delta
        if not remaining:
            self.positions.pop(fill.symbol,None)
        else:
            if not held or (held>0)!=(remaining>0):
                entry=price
            elif (held>0)==(delta>0):
                entry=(abs(held)*position.entry_price+q*price)/abs(remaining)
            else:
                entry=position.entry_price
            self.positions[fill.symbol]=PaperPosition(fill.symbol,remaining,entry,leverage)
        self.realized_pnl+=pnl
        self.fees_paid+=fee
        self.cash+=pnl-fee
        self._fills[fill.fill_id]=fill
        self.last_event_ms=fill.timestamp_ms
        self.events.append(dict(kind='FILL_ACCOUNTED',fill_id=fill.fill_id,symbol=fill.symbol,
                                realized_pnl=pnl,fee=fee,cash=self.cash,leverage=leverage,timestamp_ms=fill.timestamp_ms,
                                quantity_after=remaining,entry_price_after=self.positions[fill.symbol].entry_price if remaining else None,
                                candidate_id=fill.candidate_id,order_id=fill.order_id,
                                **timing(self.clock_ms()),
                                observed_ns=time.monotonic_ns()))
        return True

    def settle_funding(self, event, now_ms):
        if event.symbol not in self.specs or event.timestamp_ms>now_ms:
            raise ExchangeError('FUNDING_IDENTITY_OR_TIME_INVALID')
        key=(event.symbol,event.timestamp_ms)
        prior=self._funding.get(key)
        if prior is not None:
            if prior!=event:
                raise ExchangeError('CONFLICTING_FUNDING_SETTLEMENT')
            return Decimal(0)
        self._causal(event.timestamp_ms)
        position=self.positions.get(event.symbol)
        flow=-(position.quantity if position else Decimal(0))*event.oracle_price*event.hourly_rate
        self.cash+=flow
        self.funding_cashflow+=flow
        self._funding[key]=event
        self.last_event_ms=event.timestamp_ms
        self.events.append(dict(kind='FUNDING',symbol=event.symbol,timestamp_ms=event.timestamp_ms,
                                cashflow=flow,source=event.source,oracle_price=event.oracle_price,
                                hourly_rate=event.hourly_rate,**timing(self.clock_ms(),source=event.source),
                                observed_ns=time.monotonic_ns()))
        return flow

    def snapshot(self, quotes, now_ms):
        unrealized=Decimal(0)
        margin=Decimal(0)
        maintenance=Decimal(0)
        gross=Decimal(0)
        for symbol,p in self.positions.items():
            quote=quotes.get(symbol)
            if quote is None or quote.symbol!=symbol or not 0<=now_ms-quote.timestamp_ms<=5000:
                raise ExchangeError('PORTFOLIO_MARK_MISSING_OR_STALE')
            if quote.mark_timestamp_ms is None or not 0<=now_ms-quote.mark_timestamp_ms<=60000:
                raise ExchangeError('PORTFOLIO_MARK_CONTEXT_MISSING_OR_STALE')
            mark=decimal(quote.mark,positive=True)
            unrealized+=p.quantity*(mark-p.entry_price)
            notional=abs(p.quantity)*mark
            gross+=notional
            margin+=notional/p.leverage
            maintenance+=self.specs[symbol].maintenance_margin(notional)
        equity=self.cash+unrealized
        reservations=sum(self.reservations.values(),Decimal(0))
        return PortfolioSnapshot(now_ms,self.cash,unrealized,equity,margin,maintenance,
            reservations,max(Decimal(0),equity-margin-reservations),gross,self.realized_pnl,
            self.fees_paid,self.funding_cashflow,self.collateral)
