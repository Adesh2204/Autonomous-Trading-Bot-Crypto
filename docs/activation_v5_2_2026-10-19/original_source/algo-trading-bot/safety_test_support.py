"""Offline broker fixtures; never import or instantiate a real SmartAPI session."""
import config
import json
from datetime import timedelta
from execution_engine import PaperTrader
from execution_adapters import SmartAPIExecutionAdapter
from execution_safety import SafetyError
from test_safety_v6 import NOW, IDENTITY, payload, quote
from test_broker_safety_v6 import capabilities


def allow_offline_broker_protocol(monkeypatch):
    """Exercise legacy accounting with local fakes, never a real SDK client.

    This test-only patch preserves protocol coverage while production refuses
    Angel One. No runtime bypass exists.
    """
    import order_guard
    from test_broker_safety_v6 import Broker

    def mock_permission(venue, *, client=None):
        if venue != 'ANGEL_ONE' or not isinstance(client, (Broker, ScenarioBroker)):
            raise order_guard.OrderRoutingBlocked('NON_FIXTURE_TRANSPORT_FORBIDDEN')

    monkeypatch.setattr(order_guard, 'require_exchange_orders', mock_permission)


class ScenarioBroker:
    def __init__(self, response='string', partial_entry=None, partial_exit=None):
        self.response=response
        self.partial_entry=partial_entry
        self.partial_exit=partial_exit
        self.orders=[]
        self.requests=[]
        self.netqty=0
        self.fail_submit=None
        self.reject=False
        self.fail_snapshot=False
        self.protection_ok=True

    def rmsLimit(self):
        return {'status':True,'data':{'availablecash':'50000'}}

    def position(self):
        if self.fail_snapshot:raise ConnectionError('mock position unavailable')
        return {'status':True,'data':([] if not self.netqty else [{
            'symboltoken':IDENTITY.token,'tradingsymbol':IDENTITY.trading_symbol,
            'exchange':'NSE','producttype':'INTRADAY','netqty':str(self.netqty),'averageprice':'300'}])}

    def orderBook(self):
        if self.fail_snapshot:raise ConnectionError('mock order book unavailable')
        return {'status':True,'data':self.orders}

    def placeOrder(self, params):
        self.requests.append(dict(params))
        if self.reject:return {'status':False,'message':'mock rejection'}
        order_id=str(len(self.requests))
        quantity=int(params['quantity'])
        protection=params['variety']=='STOPLOSS'
        filled=0 if protection else min(quantity,
            self.partial_entry if self.netqty==0 and self.partial_entry is not None else
            self.partial_exit if self.netqty!=0 and self.partial_exit is not None else quantity)
        row=dict(params,orderid=order_id,filledshares=str(filled),averageprice=params['price'],
            status=('trigger pending' if self.protection_ok else 'rejected') if protection else
                'complete' if filled==quantity else 'cancelled')
        self.orders.append(row)
        if not protection:self.netqty+=(1 if params['transactiontype']=='BUY' else -1)*filled
        if not protection and self.fail_submit:
            raise self.fail_submit
        if self.response=='missing':return {'status':True,'data':{}}
        return {'status':True,'data':{'orderid':order_id}} if self.response=='dict' else order_id

    def cancelOrder(self, order_id, variety):
        next(o for o in self.orders if o['orderid']==order_id)['status']='cancelled'
        return {'status':True,'data':{'orderid':order_id}}


def paper_trader(tmp_path, **kwargs):
    return PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'trades.csv'),**kwargs)


def live_trader(tmp_path, monkeypatch, broker=None):
    """LIVE exercises only the deterministic broker above, with explicit mock capabilities."""
    allow_offline_broker_protocol(monkeypatch)
    broker=broker or ScenarioBroker()
    monkeypatch.setattr(config,'LIVE_MODE',True)
    monkeypatch.setattr(config,'LIVE_VALIDATION_APPROVED',True)
    from activation_gate import source_fingerprint,P0_CHECKS,BROKER_CHECKS
    tmp_path.mkdir(parents=True,exist_ok=True)
    evidence_path=tmp_path/'MOCK_ONLY_activation.json'
    evidence_path.write_text(json.dumps({'environment':'LIVE','recommendation':'OBSERVED_LIVE_PILOT_READY',
        'generated_at':NOW.isoformat(),'verified_until':(NOW+timedelta(hours=1)).isoformat(),
        'source_fingerprint':source_fingerprint(),'tests':{'failed':0,'passed':len(P0_CHECKS),'artifact':'OFFLINE_MOCK_PROTOCOL_FIXTURE'},
        'p0_checks':dict.fromkeys(P0_CHECKS,'PASS'),'broker_checks':dict.fromkeys(BROKER_CHECKS,'PASS'),
        'broker_evidence':'OFFLINE MOCK ONLY; NEVER APPLIES TO A REAL ACCOUNT'}))
    monkeypatch.setattr(config,'LIVE_ACTIVATION_EVIDENCE_FILE',str(evidence_path))
    adapter=SmartAPIExecutionAdapter(broker,capabilities(),lambda:NOW)
    trader=PaperTrader(environment='LIVE',adapter=adapter,clock=lambda:NOW,csv_log_path=str(tmp_path/'live.csv'))
    return trader,broker


def assert_unknown_submission(tmp_path, monkeypatch, failure=None, response='string'):
    broker=ScenarioBroker(response=response)
    broker.fail_submit=failure
    trader,broker=live_trader(tmp_path,monkeypatch,broker)
    assert trader.execute_trade(payload(),timestamp=NOW) is None
    assert trader.is_halted
    assert len(broker.requests)==1
    assert not trader.journal.trades()
    assert trader.journal.reservations()
    assert trader.execute_trade(payload(),timestamp=NOW) is None
    assert len(broker.requests)==1
    assert not trader.reconcile_broker('RECOVERY')
    assert trader.journal.get_meta('recovered_exposure')['positions'][0]['netqty']
    trader.shutdown()


def assert_unknown_exit(tmp_path, monkeypatch, failure=None):
    trader,broker=live_trader(tmp_path,monkeypatch)
    assert trader.execute_trade(payload(),timestamp=NOW)
    broker.fail_submit=failure or TimeoutError('mock exit timeout')
    assert trader.close_position(300,NOW) is None
    count=len(broker.requests)
    assert trader.is_halted and trader.has_open_position
    assert not trader.journal.trades()
    assert trader.close_position(300,NOW) is None
    assert len(broker.requests)==count
    trader.shutdown()
