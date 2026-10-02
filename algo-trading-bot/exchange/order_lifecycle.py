"""Generic order requests and per-operation exchange response interpretation."""
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from .base_exchange import ExchangeError, decimal


class OrderState(str, Enum):
    CREATED='CREATED'
    SUBMITTED='SUBMITTED'
    ACKNOWLEDGED='ACKNOWLEDGED'
    OPEN='OPEN'
    PARTIALLY_FILLED='PARTIALLY_FILLED'
    FILLED='FILLED'
    CANCEL_PENDING='CANCEL_PENDING'
    CANCELLED='CANCELLED'
    REJECTED='REJECTED'


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    order_type: str='LIMIT'
    reduce_only: bool=False
    strategy_id: str='VWAP_BASELINE'
    tif: str='Gtc'
    client_order_id: str | None=None

    def __post_init__(self):
        if (not isinstance(self.symbol,str) or not self.symbol.startswith('par:') or
                self.side not in {'BUY','SELL'} or self.order_type!='LIMIT' or
                type(self.reduce_only) is not bool or self.tif not in {'Gtc','Ioc','Alo'} or
                not isinstance(self.strategy_id,str) or not self.strategy_id or
                (self.client_order_id is not None and
                 (not isinstance(self.client_order_id,str) or not self.client_order_id))):
            raise ExchangeError('INVALID_ORDER_REQUEST')
        object.__setattr__(self,'quantity',decimal(self.quantity,positive=True))
        object.__setattr__(self,'price',decimal(self.price,positive=True))


@dataclass(frozen=True)
class OrderOutcome:
    state: OrderState
    exchange_order_id: str | None=None
    filled_quantity: Decimal=Decimal(0)
    average_price: Decimal | None=None
    error: str | None=None


def parse_order_results(response, requests):
    """Offline decoder only; it never submits or signs a request."""
    if not isinstance(response,dict) or response.get('status') not in {'ok','err'}:
        raise ExchangeError('UNKNOWN_ORDER_RESPONSE')
    if response['status']=='err':
        return [OrderOutcome(OrderState.REJECTED,error=str(response.get('response')))
                for request in requests]
    try:
        body=response['response']
        if body['type']!='order':
            raise ExchangeError('UNKNOWN_ORDER_RESPONSE')
        statuses=body['data']['statuses']
        if not isinstance(statuses,list) or len(statuses)!=len(requests):
            raise ExchangeError('ORDER_RESULT_COUNT_MISMATCH')
        outcomes=[]
        for status,request in zip(statuses,requests):
            if not isinstance(status,dict) or len(status)!=1:
                raise ExchangeError('UNKNOWN_ORDER_RESPONSE')
            if 'error' in status:
                outcomes.append(OrderOutcome(OrderState.REJECTED,error=str(status['error'])))
                continue
            key='filled' if 'filled' in status else 'resting'
            row=status[key]
            oid=row['oid']
            if isinstance(oid,bool) or not isinstance(oid,int) or oid<0:
                raise ExchangeError('INVALID_ORDER_ID')
            if key=='resting':
                outcomes.append(OrderOutcome(OrderState.OPEN,str(oid)))
                continue
            size=decimal(row['totalSz'],positive=True)
            if size>request.quantity:
                raise ExchangeError('FILL_EXCEEDS_REQUEST')
            state=OrderState.FILLED if size==request.quantity else OrderState.PARTIALLY_FILLED
            # IOC remainder is cancelled even when some size executed.
            if size<request.quantity and request.tif=='Ioc':
                state=OrderState.CANCELLED
            outcomes.append(OrderOutcome(state,str(oid),size,decimal(row['avgPx'],positive=True)))
        return outcomes
    except (KeyError,TypeError) as exc:
        raise ExchangeError('UNKNOWN_ORDER_RESPONSE') from exc
