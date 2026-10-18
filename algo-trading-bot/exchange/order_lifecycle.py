"""Generic order requests and per-operation exchange response interpretation."""
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from .base_exchange import ExchangeError, decimal
from .execution_journal import safe_reason


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
    UNKNOWN='UNKNOWN'


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
        if (not isinstance(self.symbol,str) or not self.symbol.startswith(('par:', 'pas:')) or
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


ERROR_CODES = (
    ('invalid market', 'INVALID_MARKET'), ('wrong dex', 'WRONG_DEX'),
    ('not funded', 'ACCOUNT_NOT_FUNDED'),
    ('minimum value', 'MIN_ORDER_NOTIONAL'), ('invalid price', 'INVALID_PRICE'),
    ('tick size', 'INVALID_PRICE'), ('invalid size', 'INVALID_SIZE'),
    ('80%', 'PRICE_BAND_VIOLATION'), ('oracle', 'PRICE_BAND_VIOLATION'),
    ('open interest', 'OPEN_INTEREST_LIMIT'), ('insufficient margin', 'INSUFFICIENT_MARGIN'),
    ('leverage', 'INVALID_LEVERAGE'), ('reduce only', 'REDUCE_ONLY_VIOLATION'),
    ('post only', 'POST_ONLY_WOULD_CROSS'), ('immediately match', 'IOC_NO_LIQUIDITY'),
    ('no liquidity', 'IOC_NO_LIQUIDITY'), ('api wallet', 'API_WALLET_NOT_APPROVED'),
    ('does not exist', 'API_WALLET_NOT_APPROVED'), ('too many', 'RATE_LIMITED'),
    ('rate limit', 'RATE_LIMITED'), ('nonce', 'NONCE_ERROR'),
)


def classify_exchange_error(reason):
    raw = safe_reason(reason)
    return next((code for fragment,code in ERROR_CODES if fragment in raw.lower()),
                'UNKNOWN_EXCHANGE_ERROR'), raw


@dataclass(frozen=True)
class ExchangeActionResult:
    result: str
    state: OrderState
    exchange_order_id: str | None = None
    filled_quantity: Decimal = Decimal(0)
    average_price: Decimal | None = None
    remaining_quantity: Decimal = Decimal(0)
    remainder_cancelled: bool = False
    code: str | None = None
    reason: str | None = None


def parse_exchange_action_result(response, requests, *, action='order'):
    """No summary fill is an accounting fill. Fees require userFills evidence."""
    if not isinstance(response,dict) or response.get('status') not in {'ok','err'}:
        raise ExchangeError('UNKNOWN_EXCHANGE_RESPONSE')
    if response['status']=='err':
        code,reason=classify_exchange_error(response.get('response','Unknown request failure'))
        return [ExchangeActionResult('REQUEST_FAILED',OrderState.REJECTED,code=code,reason=reason) for _ in requests]
    try:
        body=response['response']
        if action=='updateLeverage':
            if body.get('type')!='default':
                raise ExchangeError('UNKNOWN_EXCHANGE_RESPONSE')
            return [ExchangeActionResult('ACTION_ACKNOWLEDGED',OrderState.ACKNOWLEDGED)]
        if body.get('type') not in ({'order'} if action in {'order','batchModify'} else {'cancel','cancelByCloid'}):
            raise ExchangeError('UNEXPECTED_EXCHANGE_RESPONSE_TYPE')
        statuses=body['data']['statuses']
        if not isinstance(statuses,list):
            raise ExchangeError('INVALID_EXCHANGE_STATUSES')
        # Some deterministic pre-validation errors apply once to the whole batch.
        if len(statuses)==1 and isinstance(statuses[0],dict) and set(statuses[0])=={'error'}:
            statuses=statuses*len(requests)
        if len(statuses)!=len(requests):
            raise ExchangeError('ORDER_RESULT_COUNT_MISMATCH')
        outcomes=[]
        for row,request in zip(statuses,requests):
            if row=='success' and action in {'cancel','cancelByCloid'}:
                outcomes.append(ExchangeActionResult('ORDER_CANCELLED',OrderState.CANCELLED))
                continue
            if not isinstance(row,dict) or len(row)!=1:
                raise ExchangeError('UNKNOWN_EXCHANGE_STATUS')
            if 'error' in row:
                code,reason=classify_exchange_error(row['error'])
                cancelled = code=='IOC_NO_LIQUIDITY' and request.tif=='Ioc'
                outcomes.append(ExchangeActionResult('IOC_CANCELLED' if cancelled else 'ORDER_REJECTED',
                    OrderState.CANCELLED if cancelled else OrderState.REJECTED,
                    remaining_quantity=request.quantity if cancelled else Decimal(0),
                    remainder_cancelled=cancelled,code=code,reason=reason))
                continue
            key=next(iter(row))
            if key not in {'filled','resting'}:
                raise ExchangeError('UNKNOWN_EXCHANGE_STATUS')
            data=row[key]
            oid=data['oid']
            if type(oid) is not int or oid<0:
                raise ExchangeError('INVALID_ORDER_ID')
            if key=='resting':
                outcomes.append(ExchangeActionResult('ORDER_RESTING',OrderState.OPEN,str(oid),remaining_quantity=request.quantity))
                continue
            size=decimal(data['totalSz'],positive=True)
            if size>request.quantity:
                raise ExchangeError('FILL_EXCEEDS_REQUEST')
            remaining=request.quantity-size
            partial=remaining>0
            outcomes.append(ExchangeActionResult('ORDER_PARTIALLY_FILLED' if partial else 'ORDER_FILLED',
                OrderState.PARTIALLY_FILLED if partial else OrderState.FILLED,str(oid),size,
                decimal(data['avgPx'],positive=True),remaining,partial and request.tif=='Ioc'))
        return outcomes
    except (KeyError,TypeError) as exc:
        raise ExchangeError('UNKNOWN_EXCHANGE_RESPONSE') from exc


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
