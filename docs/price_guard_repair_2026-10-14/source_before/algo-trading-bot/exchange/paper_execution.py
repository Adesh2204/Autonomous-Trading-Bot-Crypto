"""Local order lifecycle and top-of-book fills, never an exchange transport."""
from dataclasses import dataclass, replace, field
from decimal import Decimal
import uuid
import time

from venue_config import require_paper_migration
from .base_exchange import ExchangeError, NormalizedOrder, Quote, decimal
from .order_lifecycle import OrderRequest
from .event_timing import timing
from .paper_portfolio import PaperPortfolio
from .perpetual_economics import FeeSchedule

TERMINAL={'FILLED','CANCELLED','REJECTED'}


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    order: NormalizedOrder
    status: str='OPEN'
    filled_quantity: Decimal=Decimal(0)
    strategy_id: str='VWAP_BASELINE'

    @property
    def remaining_quantity(self):
        return self.order.quantity-self.filled_quantity


@dataclass(frozen=True)
class PaperFill:
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    timestamp_ms: int
    simulated: bool=True
    fill_id: str=field(default_factory=lambda: 'paper-fill-'+uuid.uuid4().hex)
    liquidity: str='TAKER'
    fee_token: str='USDPR'
    exchange_ts: str | None=None
    received_ts: str | None=None
    processed_ts: str | None=None
    candidate_id: str | None=None


class PaperExecution:
    is_live=False
    execution_mode="PAPER"

    def __init__(self, market_specs, *, clock_ms, fee_rate=None, fees=None,
                 starting_collateral=None, leverage=1, id_factory=None):
        require_paper_migration()
        self.id_factory=id_factory or (lambda prefix: prefix+uuid.uuid4().hex)
        self.candidate_id=None
        self.order_candidates={}
        self.specs=dict(market_specs)
        if fees is None:
            if fee_rate is None:
                raise ExchangeError('EXPLICIT_PAPER_FEE_REQUIRED')
            fees=FeeSchedule(decimal(fee_rate,nonnegative=True),decimal(fee_rate,nonnegative=True),
                             'EXPLICIT_PAPER_ASSUMPTION')
        elif fee_rate is not None:
            raise ExchangeError('AMBIGUOUS_PAPER_FEES')
        if type(leverage) is not int or any(not 1<=leverage<=s.max_leverage for s in self.specs.values()):
            raise ExchangeError('INVALID_PAPER_LEVERAGE')
        self.fees=fees
        self.fee_rate=fees.taker
        self.leverage=leverage
        self.clock_ms=clock_ms
        self.orders={}
        self.fills=[]
        self.positions={}
        self.events=[]
        self.portfolio=PaperPortfolio(self.specs,starting_collateral,clock_ms=self.clock_ms) if starting_collateral is not None else None
        self.quotes={}
        self._client_ids={}
        self._liquidity_used={}
        self._alo_checked=set()

    def _event(self, oid, state, **details):
        self.events.append(dict(order_id=oid,state=state,timestamp_ms=self.clock_ms(),
                                observed_ns=time.monotonic_ns(),
                                candidate_id=self.order_candidates.get(oid,self.candidate_id),
                                **timing(self.clock_ms()),**details))

    def refresh_specs(self, specifications):
        incoming=dict(specifications)
        for symbol,quantity in self.positions.items():
            if quantity and incoming.get(symbol)!=self.specs[symbol]:
                raise ExchangeError('OPEN_POSITION_METADATA_CHANGED_REQUIRES_RECONCILIATION')
        for order in self.orders.values():
            if order.status not in TERMINAL and incoming.get(order.order.symbol)!=self.specs[order.order.symbol]:
                raise ExchangeError('OPEN_ORDER_METADATA_CHANGED_REQUIRES_RECONCILIATION')
        self.specs=incoming
        if self.portfolio:
            self.portfolio.specs=incoming

    def submit(self, request):
        if not isinstance(request,OrderRequest):
            raise ExchangeError('ORDER_REQUEST_REQUIRED')
        return self.place_order(request)

    def place_order(self, symbol, side=None, quantity=None, price=None, *, reduce_only=False, tif='Gtc'):
        require_paper_migration()
        request=symbol if isinstance(symbol,OrderRequest) else OrderRequest(
            symbol,side,quantity,price,reduce_only=reduce_only,tif=tif)
        if request.client_order_id in self._client_ids:
            prior,oid=self._client_ids[request.client_order_id]
            if prior!=request:
                raise ExchangeError('CONFLICTING_CLIENT_ORDER_ID')
            return self.orders[oid]
        if request.symbol not in self.specs:
            raise ExchangeError('UNKNOWN_PAPER_MARKET')
        order=self.specs[request.symbol].normalize_order(request.side,request.quantity,request.price,
                                                        reduce_only=request.reduce_only,tif=request.tif)
        held=self.positions.get(order.symbol,Decimal(0))
        if order.reduce_only and (not held or (order.side=='BUY')==(held>0) or order.quantity>abs(held)):
            raise ExchangeError('REDUCE_ONLY_WOULD_INCREASE_POSITION')
        oid=self.id_factory('paper-')
        if self.portfolio and not order.reduce_only:
            if self.leverage>self.specs[order.symbol].maximum_leverage_at(order.quantity*order.price):
                raise ExchangeError('LEVERAGE_EXCEEDS_RUNTIME_MARGIN_TIER')
            reserve=order.quantity*order.price/self.leverage+self.fees.fee(order.quantity,order.price)
            available=self.portfolio.snapshot(self.quotes,self.clock_ms()).available_margin
            if reserve>available:
                raise ExchangeError('PAPER_MARGIN_INSUFFICIENT')
            self.portfolio.reservations[oid]=reserve
        self.order_candidates[oid]=self.candidate_id
        for state in ('CREATED','SUBMITTED','ACKNOWLEDGED','OPEN'):
            self._event(oid,state,strategy_id=request.strategy_id,request=order.to_dict())
        result=PaperOrder(oid,order,strategy_id=request.strategy_id)
        self.orders[oid]=result
        if request.client_order_id is not None:
            self._client_ids[request.client_order_id]=(request,oid)
        return result

    def cancel_order(self, symbol, order_id):
        # Local cleanup remains available after policy revocation; no transport.
        existing=self.orders.get(order_id)
        if existing is None or existing.order.symbol!=symbol:
            raise ExchangeError('UNKNOWN_PAPER_ORDER')
        if existing.status not in TERMINAL:
            self._event(order_id,'CANCEL_PENDING')
            self.orders[order_id]=replace(existing,status='CANCELLED')
            self._event(order_id,'CANCELLED',unfilled=existing.remaining_quantity)
            if self.portfolio:
                self.portfolio.reservations.pop(order_id,None)
        return self.orders[order_id]

    def _reject(self, order_id, reason):
        self.orders[order_id]=replace(self.orders[order_id],status='REJECTED')
        self._event(order_id,'REJECTED',reason=reason)
        if self.portfolio:
            self.portfolio.reservations.pop(order_id,None)

    def simulate_fill(self, order_id, quote: Quote):
        require_paper_migration()
        resting=self.orders.get(order_id)
        if resting is None or resting.status in TERMINAL:
            raise ExchangeError('PAPER_ORDER_NOT_RESTING')
        order=resting.order
        now=self.clock_ms()
        if quote.symbol!=order.symbol or not 0<=now-quote.timestamp_ms<=5000:
            raise ExchangeError('PAPER_QUOTE_INVALID_OR_STALE')
        if self.portfolio and (quote.mark_timestamp_ms is None or not 0<=now-quote.mark_timestamp_ms<=60000):
            raise ExchangeError('PAPER_MARK_CONTEXT_INVALID_OR_STALE')
        bid,ask=(decimal(p,positive=True) for p in (quote.bid,quote.ask))
        if ask<bid:
            raise ExchangeError('PAPER_QUOTE_INVALID_OR_STALE')
        price=ask if order.side=='BUY' else bid
        depth=decimal(quote.ask_quantity if order.side=='BUY' else quote.bid_quantity,nonnegative=True)
        crosses=price<=order.price if order.side=='BUY' else price>=order.price
        if order.tif=='Alo':
            # No queue position or public-trade evidence: do not invent maker fills.
            first_observation=order_id not in self._alo_checked
            self._alo_checked.add(order_id)
            if crosses and first_observation:
                self.orders[order_id]=replace(resting,status='REJECTED')
                self._event(order_id,'REJECTED',reason='POST_ONLY_WOULD_CROSS')
                if self.portfolio:
                    self.portfolio.reservations.pop(order_id,None)
            return None
        if not crosses:
            if order.tif=='Ioc':
                self.cancel_order(order.symbol,order_id)
            return None
        key=(quote.symbol,quote.timestamp_ms,bid,ask,quote.bid_quantity,quote.ask_quantity,order.side)
        consumed=self._liquidity_used.get(key,Decimal(0))
        available=max(Decimal(0),depth-consumed)
        quantity=min(resting.remaining_quantity,available)
        held=self.positions.get(order.symbol,Decimal(0))
        if order.reduce_only:
            if not held or (order.side=='BUY')==(held>0):
                self.cancel_order(order.symbol,order_id)
                return None
            quantity=min(quantity,abs(held))
        try:
            quantity=self.specs[order.symbol].normalize_size(quantity)
        except ExchangeError:
            if order.tif=='Ioc':
                self.cancel_order(order.symbol,order_id)
            return None
        fill=PaperFill(order_id,order.symbol,order.side,quantity,price,
                       self.fees.fee(quantity,price),now,fill_id=self.id_factory("paper-fill-"),
                       received_ts=timing(now)["received_ts"],processed_ts=timing(now)["processed_ts"],
                       candidate_id=self.order_candidates.get(order_id))
        self.quotes[quote.symbol]=quote
        if self.portfolio:
            old_reserve=self.portfolio.reservations.get(order_id,Decimal(0))
            snapshot=self.portfolio.snapshot(self.quotes,now)
            held_notional=(abs(held)+quantity)*decimal(quote.mark,positive=True)
            if not order.reduce_only and self.leverage>self.specs[order.symbol].maximum_leverage_at(held_notional):
                self._reject(order_id,'LEVERAGE_EXCEEDS_RUNTIME_MARGIN_TIER')
                raise ExchangeError('LEVERAGE_EXCEEDS_RUNTIME_MARGIN_TIER')
            if not order.reduce_only and (
                    quantity*decimal(quote.mark,positive=True)/self.leverage+fill.fee>
                    snapshot.available_margin+old_reserve):
                self._reject(order_id,'PAPER_MARGIN_INSUFFICIENT_AT_FILL')
                raise ExchangeError('PAPER_MARGIN_INSUFFICIENT_AT_FILL')
            self.portfolio.apply_fill(fill,self.leverage)
        self.positions[order.symbol]=held+(quantity if order.side=='BUY' else -quantity)
        self._liquidity_used[key]=consumed+quantity
        self.fills.append(fill)
        total=resting.filled_quantity+quantity
        state='FILLED' if total==order.quantity else 'PARTIALLY_FILLED'
        self.orders[order_id]=replace(resting,status=state,filled_quantity=total)
        self._event(order_id,state,fill_id=fill.fill_id,quantity=quantity,price=price,fee=fill.fee,
            fee_token='USDPR',observed_book_time_ms=quote.timestamp_ms,bid=bid,ask=ask,
            observed_side_depth=depth,consumed_before=consumed)
        if self.portfolio:
            if state=='FILLED' or order.reduce_only:
                self.portfolio.reservations.pop(order_id,None)
            else:
                left=order.quantity-total
                self.portfolio.reservations[order_id]=left*order.price/self.leverage+self.fees.fee(left,order.price)
        if order.tif=='Ioc' and state=='PARTIALLY_FILLED':
            self.cancel_order(order.symbol,order_id)
        self._liquidity_used={k:v for k,v in self._liquidity_used.items() if now-k[1]<=5000}
        return fill
