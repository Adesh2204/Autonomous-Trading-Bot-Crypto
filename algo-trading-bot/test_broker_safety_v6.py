from datetime import timedelta
import pytest
import config
from execution_adapters import SmartAPIExecutionAdapter, BrokerCapabilities, PaperExecutionAdapter, FillResult
from execution_safety import SafetyError
from execution_engine import PaperTrader
from test_safety_v6 import NOW, IDENTITY, quote, payload

class Broker:
    def __init__(self,filled=8,protection=True):
        self.orders=[]; self.filled=filled; self.protection=protection; self.positions=[]; self.requests=[]
    def placeOrder(self,p):
        self.requests.append(p); id=str(len(self.requests))
        row=dict(p,orderid=id,status='trigger pending' if p['variety']=='STOPLOSS' and self.protection else 'rejected' if p['variety']=='STOPLOSS' else 'cancelled',
                 filledshares='0' if p['variety']=='STOPLOSS' else str(min(self.filled,int(p['quantity']))),averageprice=p['price'])
        self.orders.append(row); return id
    def orderBook(self):return {'status':True,'data':self.orders}
    def position(self):return {'status':True,'data':self.positions}
    def cancelOrder(self,id,variety):
        next(o for o in self.orders if o['orderid']==id)['status']='cancelled'
        return {'status':True}

def capabilities(**kwargs):
    d=dict(verified_until=NOW+timedelta(hours=1),static_ip_verified=True,limit_orders_verified=True,
           stop_limit_verified=True,cancellation_verified=True,evidence='mock broker protocol')
    d.update(kwargs); return BrokerCapabilities(**d)

def test_adapter_partial_entry_is_terminal_and_real():
    b=Broker(); a=SmartAPIExecutionAdapter(b,capabilities(),lambda:NOW)
    fill=a.execute(IDENTITY,'BUY',20,quote(),NOW)
    assert fill.quantity==8 and fill.status=='PARTIALLY_FILLED'
    assert b.requests[0]['symboltoken']=='18143'
    assert b.requests[0]['tradingsymbol']=='JIOFIN-EQ'
    assert b.requests[0]['ordertype']=='LIMIT'
    assert fill.price==float(b.orders[0]['averageprice'])

def test_protection_matches_actual_quantity():
    b=Broker(); a=SmartAPIExecutionAdapter(b,capabilities(),lambda:NOW)
    a.protect(IDENTITY,'SELL',8,290.,NOW)
    p=b.requests[0]
    assert p['quantity']=='8' and p['ordertype']=='STOPLOSS_LIMIT'
    assert float(p['price'])<=float(p['triggerprice'])

def test_capabilities_fail_closed():
    b=Broker(); a=SmartAPIExecutionAdapter(b,capabilities(static_ip_verified=False),lambda:NOW)
    with pytest.raises(SafetyError,match='CAPABILITIES'):
        a.execute(IDENTITY,'BUY',20,quote(),NOW)
    assert not b.requests

def test_protection_rejection_detected():
    a=SmartAPIExecutionAdapter(Broker(protection=False),capabilities(),lambda:NOW)
    with pytest.raises(SafetyError,match='PROTECTION_FAILED'):
        a.protect(IDENTITY,'SELL',8,290.,NOW)

class PartialPaper(PaperExecutionAdapter):
    def execute(self,instrument,side,quantity,quote,now,limit=None):
        f=super().execute(instrument,side,min(quantity,8),quote,now,limit)
        return FillResult(f.order_id,f.fill_id,f.quantity,f.price,f.fees,'PARTIALLY_FILLED')
    def protect(self,instrument,side,quantity,stop,now,limit=None):
        self.protected=quantity; return super().protect(instrument,side,quantity,stop,now,limit)

def test_engine_partial_entry_quantity_and_protection(tmp_path):
    a=PartialPaper(); t=PaperTrader(environment='TEST',adapter=a,clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    ticket=t.execute_trade(payload(atr=4.),timestamp=NOW)
    assert ticket and ticket['quantity']==8 and a.protected==8
    assert t.open_position['quantity']==8
    t.shutdown()

class FailedProtection(PaperExecutionAdapter):
    def protect(self,*args,**kwargs):raise SafetyError('PROTECTION_FAILED')

def test_protection_failure_deterministically_unwinds(tmp_path):
    t=PaperTrader(environment='TEST',adapter=FailedProtection(),clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert not t.has_open_position
    assert t.journal.trades()[0]['exit_reason']=='Protection/Risk Emergency'
    t.shutdown()

def test_live_default_gate_prevents_activation(tmp_path):
    with pytest.raises(SafetyError,match='LIVE_EXECUTION_BLOCKED'):
        PaperTrader(environment='LIVE',clock=lambda:NOW,csv_log_path=str(tmp_path/'live.csv'))

def test_recovered_broker_exposure_blocks_entries(tmp_path):
    t=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    b=Broker(); b.positions=[{'tradingsymbol':'JIOFIN-EQ','symboltoken':'18143','netqty':'8','averageprice':'300'}]
    t.adapter=SmartAPIExecutionAdapter(b,capabilities(),lambda:NOW)
    assert not t.reconcile_broker('RESTART')
    assert t.recovered_broker_positions[0]['netqty']=='8'
    assert t.execute_trade(payload(),timestamp=NOW) is None
    t.shutdown()

def test_flatten_uses_fill_and_verifies_simulated_flat(tmp_path):
    t=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert t.execute_trade(payload(),timestamp=NOW)
    result=t.square_off_all_positions(timestamp=NOW.replace(hour=15,minute=0),latest_price=300.)
    assert result is None # Old quote is stale; do not fabricate a flatten fill.
    assert t.has_open_position
    t.shutdown()

def test_flatten_with_fresh_quote_completes(tmp_path):
    t=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert t.execute_trade(payload(),timestamp=NOW)
    late=NOW.replace(hour=15,minute=0)
    from execution_safety import MarketQuote
    t.set_quote(IDENTITY,MarketQuote(300.,300.1,1000,1000,late,300.05))
    summary=t.square_off_all_positions(timestamp=late,latest_price=300.05)
    assert summary and not t.has_open_position
    assert summary['reconciliation_status']=='SIMULATED'
    assert t.execute_trade(payload(),timestamp=late) is None
    t.shutdown()

class PartialExit(PaperExecutionAdapter):
    def execute(self,instrument,side,quantity,quote,now,limit=None):
        actual=min(2,quantity) if side=='SELL' else quantity
        f=super().execute(instrument,side,actual,quote,now,limit)
        return FillResult(f.order_id,f.fill_id,f.quantity,f.price,f.fees,'FILLED' if actual==quantity else 'PARTIALLY_FILLED')

def test_partial_exits_preserve_quantity_fees_and_protection(tmp_path):
    t=PaperTrader(environment='TEST',adapter=PartialExit(),clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    ticket=t.execute_trade(payload(),timestamp=NOW); original=ticket['quantity']
    assert t.close_position(300.,NOW) is None
    assert t.open_position['quantity']==original-2
    assert t.open_position['protection_id']
    result=None
    for _ in range(original):
        if t.has_open_position:result=t.close_position(300.,NOW)
    assert result and result['filled_quantity']==original
    assert len(result['exit_order_ids'])>1
    assert result['exit_fees']>6*len(result['exit_order_ids'])-.2
    assert len(t.journal.trades())==1
    t.shutdown()

class Ambiguous(PaperExecutionAdapter):
    def execute(self,*args,**kwargs):raise SafetyError('UNKNOWN_BROKER_STATE')

def test_unknown_order_durable_quarantine_after_restart(tmp_path):
    path=str(tmp_path/'x.csv')
    t=PaperTrader(environment='TEST',adapter=Ambiguous(),clock=lambda:NOW,csv_log_path=path)
    assert t.execute_trade(payload(),timestamp=NOW) is None
    assert t.is_halted
    t.shutdown()
    other=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=path)
    assert other.execute_trade(payload(),timestamp=NOW) is None
    assert other.last_rejection=='UNKNOWN_BROKER_STATE'
    other.shutdown()

def test_rejected_and_cancelled_orders_never_create_quantity():
    class Reject(Broker):
        def placeOrder(self,p):return {'status':False,'message':'rejected'}
    a=SmartAPIExecutionAdapter(Reject(),capabilities(),lambda:NOW)
    with pytest.raises(SafetyError,match='BROKER_ORDER_REJECTED'):
        a.execute(IDENTITY,'BUY',20,quote(),NOW)
    b=Broker(filled=0); a=SmartAPIExecutionAdapter(b,capabilities(),lambda:NOW)
    with pytest.raises(SafetyError,match='CANCELLED'):
        a.execute(IDENTITY,'BUY',20,quote(),NOW)

def test_duplicate_book_report_wrong_identity_blocked():
    b=Broker(); a=SmartAPIExecutionAdapter(b,capabilities(),lambda:NOW)
    original=b.placeOrder
    def wrong(p):
        id=original(p); b.orders[-1]['symboltoken']='4907'; return id
    b.placeOrder=wrong
    with pytest.raises(SafetyError,match='INSTRUMENT_IDENTITY_MISMATCH'):
        a.execute(IDENTITY,'BUY',20,quote(),NOW)

def test_direct_legacy_order_path_cannot_bypass_validation(monkeypatch):
    from execution_engine import place_live_order
    monkeypatch.setattr(config,'LIVE_MODE',True)
    monkeypatch.setattr(config,'LIVE_VALIDATION_APPROVED',False)
    b=Broker()
    with pytest.raises(SafetyError,match='LIVE_EXECUTION_BLOCKED'):
        place_live_order(b,'JIOFIN-EQ','18143','BUY',8)
    assert not b.requests
