"""Execution adapters: confirmed fills and supported limit/protective order path.

Live capability verification is account-specific and expires. No MARKET/IOC requests.
"""
from dataclasses import dataclass
from datetime import datetime
import time
import uuid
import math
import config
from execution_safety import FeeModel, SafetyError, ExecutionQualityGate

@dataclass(frozen=True)
class FillResult:
    order_id: str
    fill_id: str
    quantity: int
    price: float
    fees: float
    status: str = 'FILLED'
    fee_source: str = 'ESTIMATED_STANDARD'

    def __post_init__(self):
        if (not isinstance(self.quantity,int) or isinstance(self.quantity,bool) or self.quantity<1 or
            not self.order_id or not self.fill_id or not math.isfinite(self.price) or self.price<=0 or
            not math.isfinite(self.fees) or self.fees<0 or self.status not in {'FILLED','PARTIALLY_FILLED'}):
            raise SafetyError('INVALID_CONFIRMED_FILL')

    def to_dict(self): return dict(self.__dict__)

@dataclass(frozen=True)
class BrokerCapabilities:
    verified_until: datetime
    static_ip_verified: bool
    limit_orders_verified: bool
    stop_limit_verified: bool
    cancellation_verified: bool
    evidence: str

    def validate(self,now):
        if (self.verified_until.tzinfo is None or now>self.verified_until or
            not all((self.static_ip_verified,self.limit_orders_verified,self.stop_limit_verified,self.cancellation_verified)) or not self.evidence):
            raise SafetyError('BROKER_CAPABILITIES_UNVERIFIED')

class PaperExecutionAdapter:
    is_live=False
    def __init__(self,fill_slippage_pct=None):
        self.fill_slippage_pct=config.PAPER_FILL_SLIPPAGE_PCT if fill_slippage_pct is None else fill_slippage_pct
        if not math.isfinite(self.fill_slippage_pct) or not 0 <= self.fill_slippage_pct < 1:
            raise SafetyError('INVALID_PAPER_FILL_ASSUMPTION')

    def execute(self,instrument,side,quantity,quote,now,limit=None):
        instrument.validate(instrument.symbol,now=now)
        price=ExecutionQualityGate().validate(quote,side,now,quantity)
        price=instrument.price(price*(1+(1 if side=='BUY' else -1)*self.fill_slippage_pct),side)
        if limit is not None and ((side=='BUY' and price>limit) or (side=='SELL' and price<limit)):
            raise SafetyError('ORDER_PRICE_OUTSIDE_LIMIT')
        return FillResult('paper-'+str(uuid.uuid4()),str(uuid.uuid4()),quantity,price,FeeModel().leg(side,price,quantity)['total_charges'])

    def protect(self,instrument,side,quantity,stop,now,limit=None):
        return 'paper-protection-'+str(uuid.uuid4())
    def cancel(self,order_id):return True
    def snapshot(self):return [],[]

class SmartAPIExecutionAdapter:
    is_live=True
    TERMINAL={'complete','completed','rejected','cancelled','canceled','expired'}
    def __init__(self,broker,capabilities,clock):
        self.broker=broker; self.capabilities=capabilities; self.clock=clock
        self.on_order_acknowledged=None

    def _data(self,response):
        if not isinstance(response,dict) or response.get('status') is not True or not isinstance(response.get('data'),list):
            raise SafetyError('BROKER_DATA_UNAVAILABLE')
        return response['data']

    def snapshot(self):
        return self._data(self.broker.position()),self._data(self.broker.orderBook())

    def available_cash(self):
        response=self.broker.rmsLimit()
        if not isinstance(response,dict) or response.get('status') is not True or not isinstance(response.get('data'),dict):
            raise SafetyError('BROKER_CASH_UNVERIFIED')
        raw=response['data'].get('availablecash')
        try:cash=float(raw)
        except (ValueError,TypeError):raise SafetyError('BROKER_CASH_UNVERIFIED')
        if isinstance(raw,bool) or not math.isfinite(cash) or cash<0:raise SafetyError('BROKER_CASH_UNVERIFIED')
        return cash

    def _order(self,id):
        rows=self._data(self.broker.orderBook()); matched=[o for o in rows if str(o.get('orderid'))==id]
        if len(matched)!=1:raise SafetyError('UNKNOWN_BROKER_STATE')
        return matched[0]

    def read_fill(self,id,instrument,side,maximum_quantity):
        row=self._order(id)
        if (str(row.get('symboltoken'))!=instrument.token or row.get('tradingsymbol')!=instrument.trading_symbol or
            row.get('exchange')!=instrument.exchange or row.get('transactiontype')!=side):
            raise SafetyError('INSTRUMENT_IDENTITY_MISMATCH')
        q=int(float(row.get('filledshares',0)))
        if not q:return None
        price=float(row.get('averageprice',0))
        if q<0 or q>maximum_quantity or not math.isfinite(price) or price<=0:raise SafetyError('UNKNOWN_BROKER_STATE')
        fee=row.get('totalcharges')
        if fee is not None and (isinstance(fee,bool) or not math.isfinite(float(fee)) or float(fee)<0):
            raise SafetyError('BROKER_CHARGES_UNVERIFIED')
        return FillResult(id,id+'-terminal',q,price,float(fee) if fee is not None else FeeModel().leg(side,price,q)['total_charges'],
            'FILLED' if q==maximum_quantity else 'PARTIALLY_FILLED','BROKER' if fee is not None else 'ESTIMATED_STANDARD')

    def _submit(self,params):
        self.capabilities.validate(self.clock())
        try:r=self.broker.placeOrder(params)
        except Exception as exc:raise SafetyError('UNKNOWN_BROKER_STATE') from exc
        order_id=None
        if isinstance(r,str) and r.strip():order_id=r.strip()
        if isinstance(r,dict) and r.get('status') is False:raise SafetyError('BROKER_ORDER_REJECTED')
        if isinstance(r,dict) and r.get('status') is True and isinstance(r.get('data'),dict) and r['data'].get('orderid'):
            order_id=str(r['data']['orderid'])
        if order_id:
            if self.on_order_acknowledged:self.on_order_acknowledged(order_id,params)
            return order_id
        raise SafetyError('UNKNOWN_BROKER_STATE')

    def cancel(self,id):
        row=self._order(id)
        if str(row.get('status',row.get('orderstatus',''))).lower() in self.TERMINAL:return True
        try:self.broker.cancelOrder(id,row.get('variety','NORMAL'))
        except Exception as exc:raise SafetyError('UNKNOWN_BROKER_STATE') from exc
        deadline=time.monotonic()+config.BROKER_ORDER_TIMEOUT_SECONDS
        while time.monotonic()<deadline:
            if str(self._order(id).get('status','')).lower() in self.TERMINAL:return True
            time.sleep(config.BROKER_POLL_SECONDS)
        raise SafetyError('PARTIAL_FILL_STALLED')

    def execute(self,instrument,side,quantity,quote,now,limit=None,is_exit=False):
        instrument.validate(instrument.symbol,now=None if is_exit else now)
        reference=ExecutionQualityGate().validate(quote,side,now,quantity)
        if limit is None:limit=instrument.price(reference*(1+(1 if side=='BUY' else -1)*config.SLIPPAGE_HAIRCUT_PCT),side)
        params={'variety':'NORMAL','tradingsymbol':instrument.trading_symbol,'symboltoken':instrument.token,
            'exchange':instrument.exchange,'transactiontype':side,'quantity':str(quantity),
            'ordertype':'LIMIT','producttype':'INTRADAY','duration':'DAY','price':str(limit)}
        id=self._submit(params); deadline=time.monotonic()+config.BROKER_ORDER_TIMEOUT_SECONDS
        row=self._order(id)
        while str(row.get('status',row.get('orderstatus',''))).lower() not in self.TERMINAL and time.monotonic()<deadline:
            time.sleep(config.BROKER_POLL_SECONDS); row=self._order(id)
        if str(row.get('status',row.get('orderstatus',''))).lower() not in self.TERMINAL:
            self.cancel(id); row=self._order(id) # Unfilled remainder must be conclusively cancelled.
        q=int(float(row.get('filledshares',0))); price=float(row.get('averageprice',0))
        if q<=0:
            status=str(row.get('status','')).lower()
            raise SafetyError('BROKER_ORDER_REJECTED' if status=='rejected' else 'CANCELLED' if status in {'cancelled','canceled'} else 'EXPIRED')
        if q>quantity or price<=0 or ((side=='BUY' and price>limit+1e-8) or (side=='SELL' and price<limit-1e-8)):
            raise SafetyError('UNKNOWN_BROKER_STATE')
        return self.read_fill(id,instrument,side,quantity)

    def protect(self,instrument,side,quantity,stop,now,limit=None):
        # Separate emergency protection; original close-based strategy stop remains unchanged.
        sign=1 if side=='SELL' else -1
        if limit is None:
            trigger=instrument.price(stop*(1-sign*config.SLIPPAGE_HAIRCUT_PCT/2),side)
            limit=instrument.price(stop*(1-sign*config.SLIPPAGE_HAIRCUT_PCT),side)
        else:trigger=stop
        id=self._submit({'variety':'STOPLOSS','tradingsymbol':instrument.trading_symbol,'symboltoken':instrument.token,
            'exchange':instrument.exchange,'transactiontype':side,'quantity':str(quantity),'ordertype':'STOPLOSS_LIMIT',
            'producttype':'INTRADAY','duration':'DAY','triggerprice':str(trigger),'price':str(limit)})
        row=self._order(id); status=str(row.get('status',row.get('orderstatus',''))).lower()
        if (status not in {'open','trigger pending'} or int(float(row.get('quantity',0)))!=quantity or
            str(row.get('symboltoken'))!=instrument.token or row.get('tradingsymbol')!=instrument.trading_symbol or
            row.get('exchange')!=instrument.exchange or row.get('transactiontype')!=side):
            raise SafetyError('PROTECTION_FAILED')
        return id
