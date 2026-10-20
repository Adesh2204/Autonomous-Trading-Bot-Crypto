"""Isolated V2 development. All signatures use ephemeral wallets; HTTP forbidden."""
from dataclasses import replace,asdict
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from exchange.base_exchange import MarketSpec,BookLevel,OrderBook,Candle,ExchangeError
from exchange.capital_allocation import CapitalLimits,allocate,walk_book
from exchange.quant_observation import classify_signal,completed_higher_timeframe,explain_market
from exchange.bounded_daily_session import DailyMandate,DailyLifecycle,TradeState,deployment_readiness
from exchange.execution_journal import ExecutionJournal
from exchange.public_quant_operator import ReadOnlyReceipts
from research_lab.quant_exits import ExitPolicy,POLICIES,episode
from research_lab.quant_campaign import synthetic_path,REGIMES,TIERS
from test_live_exchange_execution import live,permission
from test_testnet_certification_v8 import FakeCertificationVenue
from exchange.order_lifecycle import OrderRequest

NOW=1792126800000
SPEC=MarketSpec('par:BTC',4,40,2670000)
TEAM='0x'+'1'*40
API='0x'+'2'*40
HASH='ab'*32

def book(now=NOW,bid='99.99',ask='100.01',bidqty='10000',askqty='10000'):
    return OrderBook('par:BTC',now,(BookLevel(D(bid),D(bidqty)),BookLevel(D(bid)-1,D(1000000))),
        (BookLevel(D(ask),D(askqty)),BookLevel(D(ask)+1,D(1000000))),now,now)

def plan(b=None,side='BUY',target=D(1000),**changes):
    b=b or book();kw=dict(now_ms=b.timestamp_ms,free_collateral=D(1000000),equity=D(1000000),entry_fee=D('.0027'),exit_fee=D('.0027'))
    kw.update(changes)
    return allocate(SPEC,b,side,D(99) if side=='BUY' else D(101),
        CapitalLimits(D(20000),target,target,target*2),**kw)

@pytest.mark.parametrize('target',TIERS)
@pytest.mark.parametrize('side',['BUY','SELL'])
def test_sizing_every_requested_tier_and_direction_is_rounded_down(target,side):
    b=book();p=plan(b,side,D(target))
    assert p['notional']<=target and p['quantity']%SPEC.size_step==0
    assert p['quantity']<=min(b.bids[0].quantity,b.asks[0].quantity)*D('.1')
    assert p['intended_loss']<=p['risk_budget'] and p['risk_budget']<=100
    assert p['authority_granted'] is False and p['loss_bound_is_guaranteed'] is False

@pytest.mark.parametrize('damage',['risk','daily','participation','margin','leverage','slippage'])
def test_capital_cannot_relax_preserved_limits(damage):
    kw={'risk':dict(risk_fraction='.006'),'daily':dict(daily_loss_fraction='.02'),
        'participation':dict(participation='.5'),'margin':dict(margin_fraction='.6'),
        'leverage':dict(leverage=2),'slippage':dict(slippage_bps=6)}[damage]
    with pytest.raises(ExchangeError):CapitalLimits(D(20000),D(1000),D(1000),D(2000),**kw)

@pytest.mark.parametrize('side',['BUY','SELL'])
def test_deep_aggregate_book_cannot_bypass_thin_opposite_best(side):
    b=book(bidqty='.0001');p=plan(b,side)
    assert p['quantity']==0 and p['entry_capacity']['raw_l2_quantity']>0

@pytest.mark.parametrize('change',[dict(existing_positions=1),dict(unresolved_orders=1),
    dict(current_exposure=1),dict(correlated_exposure=1),dict(daily_loss=200),
    dict(cumulative_allocation=2000),dict(equity=1),dict(free_collateral=0)])
def test_risk_exposure_and_account_constraints_zero_size(change):
    assert plan(**change)['quantity']==0

@pytest.mark.parametrize('bad',['NaN','Infinity','-1',True])
def test_nonfinite_negative_and_boolean_finance_is_rejected(bad):
    with pytest.raises(ExchangeError):plan(free_collateral=bad)

def test_stale_book_and_wrong_stop_direction_are_blocked():
    with pytest.raises(ExchangeError):plan(now_ms=NOW+5001)
    with pytest.raises(ExchangeError):allocate(SPEC,book(),'BUY',101,CapitalLimits(20000,1000,1000,2000),
        now_ms=NOW,free_collateral=20000,equity=20000,entry_fee=0,exit_fee=0)

def test_finite_book_walk_never_creates_liquidity():
    b=book(bidqty='1',askqty='1')
    r=walk_book(b,'BUY',D(500),limit=D('100.02'),participation=D('.1'))
    assert r['filled_quantity']==D('.1') and r['residual_quantity']==D('499.9') and not r['full_fill']

@pytest.mark.parametrize('long,short,trend,expected',[(True,False,'BULLISH','LONG'),
    (False,True,'BEARISH','SHORT'),(True,True,'BULLISH','NO_TRADE'),
    (True,False,'BEARISH','NO_TRADE'),(False,False,'BULLISH','NO_TRADE'),
    (False,True,None,'NO_TRADE')])
def test_deterministic_long_short_no_trade_explanations(long,short,trend,expected):
    r=classify_signal(baseline_long=long,baseline_short=short,higher_trend=trend,eligible=True,reasons=[])
    assert r['decision']==expected and r['confidence_probability'] is None

def candles(count=900):
    start=NOW//86400000*86400000-count*60000
    return [Candle('par:BTC','1m',start+i*60000,start+(i+1)*60000-1,
        D(100)+D(i)/100,D(101)+D(i)/100,D(99)+D(i)/100,D(100)+D(i)/100,D(10),
        start+(i+1)*60000,start+(i+1)*60000) for i in range(count)]

def test_higher_timeframe_uses_complete_contiguous_buckets_only():
    c=candles();now=c[-1].timestamp_ms+60000
    r=completed_higher_timeframe(c,now)
    assert r['status']=='READY' and r['latest_complete_ms']<=now and r['trend']=='BULLISH'
    assert completed_higher_timeframe(c[:20],now)['status']=='WARMUP_INSUFFICIENT'
    with pytest.raises(ExchangeError):completed_higher_timeframe(c,now-1)

def test_gap_does_not_generate_frozen_strategy_signal_or_fill():
    c=candles();now=c[-1].timestamp_ms+60000
    r=explain_market(SPEC,book(now),c[:30]+c[31:],dict(markPx=100,oraclePx=100,funding=0),now_ms=now,context_ms=now)
    assert r['decision']=='NO_TRADE' and any('GAP' in x for x in r['reasons'])

@pytest.mark.parametrize('policy',POLICIES)
@pytest.mark.parametrize('direction',['LONG','SHORT'])
def test_each_exit_policy_and_direction_has_correct_reduce_only_side(policy,direction):
    path=synthetic_path('BULL' if direction=='LONG' else 'BEAR')
    r=episode(SPEC,path,direction,1000,ExitPolicy(policy))
    assert r['status']=='SIMULATED_CLOSED' and r['remaining_quantity']==0
    assert r['fills'][0]['side']==('BUY' if direction=='LONG' else 'SELL')
    assert all(f['reduce_only'] and f['side']==('SELL' if direction=='LONG' else 'BUY') for f in r['fills'][1:])
    assert r['exchange_orders_submitted']==0 and r['sharpe'] is None

@pytest.mark.parametrize('target',TIERS)
@pytest.mark.parametrize('direction',['LONG','SHORT'])
def test_virtual_large_trade_cannot_fill_beyond_recorded_bbo_cap(target,direction):
    p=synthetic_path('BULL');p[0]['book']=book(p[0]['at_ms'],bidqty='.1',askqty='.1')
    r=episode(SPEC,p,direction,target,ExitPolicy('TIME'))
    assert r['status']=='ENTRY_CAPACITY_BLOCKED' and not r['fills']

@pytest.mark.parametrize('fault,expected',[('unknown_entry','UNKNOWN'),('rejected_entry','REJECTED'),
    ('unknown_exit','UNKNOWN'),('rejected_exit','UNPROTECTED_EXPOSURE'),
    ('partial_exit','RECOVERY_REQUIRED'),('stop_rejected','UNPROTECTED_EXPOSURE')])
def test_uncertain_rejected_or_partial_execution_has_no_automatic_retry(fault,expected):
    r=episode(SPEC,synthetic_path('BULL'),'LONG',1000,ExitPolicy('TIME'),fault=fault)
    assert r['status']==expected and r.get('exit_attempts',0)<=1 and r['realized_net'] is None

def test_required_stop_can_close_at_loss_and_gap_can_exceed_intended_risk():
    r=episode(SPEC,synthetic_path('GAP'),'LONG',50000,ExitPolicy('TRAILING'))
    assert r['status']=='SIMULATED_CLOSED' and r['realized_net']<0
    assert r['tail_loss_exceeds_intended_stop'] is True

def test_future_features_are_rejected_and_funding_sign_is_directional():
    p=synthetic_path('SIDEWAYS');p[1]['features_available_ms']=p[1]['at_ms']+1
    with pytest.raises(ExchangeError):episode(SPEC,p,'LONG',1000,ExitPolicy('TIME'))
    long=episode(SPEC,synthetic_path('LOW_VOL'),'LONG',1000,ExitPolicy('TIME'))
    short=episode(SPEC,synthetic_path('LOW_VOL'),'SHORT',1000,ExitPolicy('TIME'))
    assert long['funding']<0<short['funding']

def mandate(now=NOW,**changes):
    values=dict(session_id='fixture-day',team_wallet=TEAM,api_wallet=API,markets=('par:BTC',),
        directions=('LONG','SHORT'),starts_ms=now-1000,expires_ms=now+3600000,source_hash=HASH,
        signing_host='OFFLINE_HOST',bankroll='20000',maximum_notional='1000',
        maximum_total_exposure='1000',maximum_cumulative_allocation='2000')
    values.update(changes);return DailyMandate(**values).require()

def readbacks(m,now,mode='OFFLINE_FIXTURE'):
    return [dict(source=mode,team=m.team_wallet,positions=[],orders=[],ready=True,observed_ms=t) for t in (now-1,now)]

@pytest.fixture
def lifecycle(tmp_path):
    j=ExecutionJournal(tmp_path/'day.sqlite',session_id='offline:quant',team_address=TEAM)
    clock=[NOW];m=mandate();s=DailyLifecycle(j,m,clock_ms=lambda:clock[0],source_hash=lambda:HASH,mode='OFFLINE_FIXTURE')
    s.confirm_flat(readbacks(m,clock[0]));yield s,j,clock;j.close()

def start_entry(s,clock,direction='LONG',candidate='first'):
    s.candidate(candidate,'par:BTC',direction)
    p=plan(side='BUY' if direction=='LONG' else 'SELL',now_ms=clock[0])
    price=D('100.01') if direction=='LONG' else D('99.99')
    s.reserve_entry(p['quantity'],price,allocation=p,protection_fixture=True)
    return p

@pytest.mark.parametrize('direction',['LONG','SHORT'])
def test_complete_durable_lifecycle_and_two_readbacks(lifecycle,direction):
    s,j,clock=lifecycle;p=start_entry(s,clock,direction)
    s.entry_result(p['quantity'],order_id=1,fill_id=11,remainder_settled=True)
    s.protection_result(True);s.manage();request=s.reserve_exit()
    assert request['side']==('SELL' if direction=='LONG' else 'BUY') and request['reduce_only']
    s.exit_result(p['quantity'],order_id=2,fill_id=22,net_pnl='-.5')
    s.confirm_flat(readbacks(s.m,clock[0]));assert s.state==TradeState.FLAT_VERIFIED
    assert s.data['cycles']==1 and D(s.data['realized_net'])==D('-.5')
    with pytest.raises(ExchangeError):s.candidate('first','par:BTC',direction)

@pytest.mark.parametrize('damage',['expiry','source','wrong_side','position','protection','stale_plan','risk'])
def test_entry_barriers_cannot_be_relaxed(lifecycle,damage):
    s,j,clock=lifecycle
    if damage=='expiry':clock[0]=s.m.expires_ms
    if damage=='source':s.source_hash=lambda:'ff'*32
    if damage=='wrong_side':
        with pytest.raises(ExchangeError):s.candidate('x','par:ETH','LONG')
        return
    if damage in {'expiry','source'}:
        with pytest.raises(ExchangeError):s.candidate('x','par:BTC','LONG')
        return
    s.candidate('x','par:BTC','LONG');p=plan()
    if damage=='position':s.data['quantity']='1'
    if damage=='stale_plan':p['observed_ms']=clock[0]-5001
    if damage=='risk':p['intended_loss']='101'
    with pytest.raises(ExchangeError):s.reserve_entry(p['quantity'],D('100.01'),allocation=p,protection_fixture=damage!='protection')

@pytest.mark.parametrize('kind',['unknown_entry','unknown_exit','partial_exit','stop_rejected'])
def test_failure_latches_recovery_and_restart_cannot_resume(lifecycle,kind):
    s,j,clock=lifecycle;p=start_entry(s,clock)
    if kind=='unknown_entry':s.entry_result(0,unknown=True)
    else:
        s.entry_result(p['quantity'],order_id=1,fill_id=11,remainder_settled=True)
        s.protection_result(kind!='stop_rejected')
        if kind=='stop_rejected':assert s.state==TradeState.UNPROTECTED_EXPOSURE
        s.reserve_exit();s.exit_result(p['quantity']/2 if kind=='partial_exit' else 0,
            order_id=2,fill_id=22,unknown=kind=='unknown_exit')
    with pytest.raises(ExchangeError):s.reserve_exit()
    restored=DailyLifecycle(j,s.m,clock_ms=lambda:clock[0],source_hash=lambda:HASH,mode='OFFLINE_FIXTURE')
    with pytest.raises(ExchangeError):restored.confirm_flat(readbacks(s.m,clock[0]))
    assert restored.shutdown()['state']=='RECOVERY_REQUIRED'

def test_two_trade_cap_and_daily_drawdown_are_durable(lifecycle):
    s,j,clock=lifecycle
    for index in range(2):
        p=start_entry(s,clock,candidate=str(index));s.entry_result(p['quantity'],order_id=1,fill_id=11)
        s.protection_result(True);s.reserve_exit();s.exit_result(p['quantity'],order_id=2,fill_id=22,net_pnl=1)
        s.confirm_flat(readbacks(s.m,clock[0]))
    s.candidate('third','par:BTC','LONG');p=plan()
    with pytest.raises(ExchangeError):s.reserve_entry(p['quantity'],D('100.01'),allocation=p,protection_fixture=True)

def test_drawdown_blocks_entries_but_not_authorized_risk_close(lifecycle):
    s,j,clock=lifecycle;p=start_entry(s,clock);s.entry_result(p['quantity'],order_id=1,fill_id=11)
    s.protection_result(False);s.data['drawdown']='300';request=s.reserve_exit()
    assert request['reduce_only'] is True

def test_observation_flags_never_create_actual_session_authority(tmp_path):
    j=ExecutionJournal(tmp_path/'real.sqlite',session_id='public-observer',team_address=TEAM)
    try:
        s=DailyLifecycle(j,mandate(),clock_ms=lambda:NOW,source_hash=lambda:HASH)
        s.confirm_flat(readbacks(s.m,NOW,'EXCHANGE_DIRECT_TESTNET_PAR_INFO'));s.candidate('x','par:BTC','LONG')
        with pytest.raises(ExchangeError):s.reserve_entry(1,100,allocation=plan(),protection_fixture=True)
        assert not deployment_readiness(protection_verified=True,short_cycle_verified=True,
            exact_session_approved=True,source_matches=True,fresh_account=True)['order_submission_enabled']
    finally:j.close()

@pytest.mark.parametrize('payload',[dict(type='order'),dict(type='l2Book',signature={}),dict(type='updateLeverage'),dict(type='transfer')])
def test_public_observer_cannot_send_signed_or_admin_actions(tmp_path,payload):
    calls=[];reader=ReadOnlyReceipts(lambda p:calls.append(p),tmp_path/'receipts')
    try:
        with pytest.raises(ExchangeError):reader(payload)
        assert calls==[]
    finally:reader.file.close()

@pytest.mark.parametrize('direction',['LONG','SHORT'])
def test_existing_ephemeral_sdk_entry_and_reduce_only_close_are_reused(live,monkeypatch,direction):
    """Real existing central guards/SDK wire, synthetic venue; never qualification."""
    l=live;venue=FakeCertificationVenue(l,monkeypatch,SimpleNamespace(claim_transmission=lambda _:None))
    side='BUY' if direction=='LONG' else 'SELL';price='100.01' if side=='BUY' else '99.99'
    entry=OrderRequest('par:BTC',side,'.2',price,tif='Ioc',client_order_id='quant-fixture-entry')
    opened=l.executor.submit(entry,permission=permission(entry))
    held=l.account.get_position('par:BTC')
    assert held and (held.quantity>0)==(direction=='LONG') and opened.filled_quantity==D('.2')
    close=OrderRequest('par:BTC','SELL' if side=='BUY' else 'BUY','.2',
        '99.99' if side=='BUY' else '100.01',reduce_only=True,tif='Ioc',client_order_id='quant-fixture-exit')
    covered=l.executor.submit(close,permission=permission(close,reason='OFFLINE_VALIDATED_RISK_CLOSE'))
    assert covered.filled_quantity==D('.2') and not l.account.get_positions() and not l.account.get_frontend_open_orders()
    assert len(l.transport.signed_payloads)==2 and venue.calls[-1]['orders'][0]['r'] is True


def test_exact_public_checkpoint_hashes_survive_and_tampering_is_detected(lifecycle):
    s,j,clock=lifecycle;s.candidate('cd'*32,'par:BTC','LONG')
    saved=j.control(s.key)
    assert saved['data']['entry']['candidate']=='cd'*32 and len(saved['checksum'])==64
    saved['data']['attempts']=99
    with j.transaction():j.db.execute('UPDATE controls SET value=? WHERE name=?',(json.dumps(saved),s.key))
    with pytest.raises(ExchangeError,match='CHECKPOINT_CORRUPT'):
        DailyLifecycle(j,s.m,clock_ms=lambda:clock[0],source_hash=lambda:HASH,mode='OFFLINE_FIXTURE')

def test_partial_exit_requires_fill_identity_and_daily_remaining_loss_bounds_entry(lifecycle):
    s,j,clock=lifecycle;s.data['drawdown']='199.99';s.candidate('x','par:BTC','LONG');p=plan()
    with pytest.raises(ExchangeError):s.reserve_entry(p['quantity'],'100.01',allocation=p,protection_fixture=True)
    s.data['drawdown']='0';s.reserve_entry(p['quantity'],'100.01',allocation=p,protection_fixture=True)
    s.entry_result(p['quantity'],order_id=1,fill_id=1);s.protection_result(True);s.reserve_exit()
    with pytest.raises(ExchangeError,match='FILL_IDENTITY'):s.exit_result(p['quantity']/2)
    assert D(s.data['quantity'])==p['quantity']

def test_partial_fill_evidence_is_durable_and_invalid_accounting_cannot_clear_exposure(lifecycle):
    s,j,clock=lifecycle;p=start_entry(s,clock)
    s.entry_result(p['quantity'],order_id=1,fill_id=11);s.protection_result(True);s.reserve_exit()
    with pytest.raises(ExchangeError):s.exit_result(p['quantity'],order_id=2,fill_id=22,net_pnl='NaN')
    assert D(s.data['quantity'])==p['quantity'] and s.state==TradeState.EXIT_SUBMITTED
    s.exit_result(p['quantity']/2,order_id=2,fill_id=22)
    saved=j.control(s.key)['data']
    assert saved['state']=='RECOVERY_REQUIRED' and saved['exit']['fill_id']=='22'
    assert D(saved['exit']['filled'])==D(saved['quantity'])==p['quantity']/2

def test_exchange_max_trade_size_is_an_independent_quantity_bound():
    p=plan(maximum_trade_quantity='.2');assert p['quantity']==D('.2')
    assert 'exchange_available_trade_size' in p['binding_limits']
    with pytest.raises(ExchangeError):plan(existing_positions=True)

def test_exit_cost_changes_and_missing_funding_are_not_silently_ignored():
    path=synthetic_path('BULL')
    base=episode(SPEC,path,'LONG',1000,ExitPolicy('TIME'))
    for row in path:row['taker_fee']=D('.003')
    higher=episode(SPEC,path,'LONG',1000,ExitPolicy('TIME'))
    assert higher['realized_net']<base['realized_net'] and higher['exit_fee']>base['exit_fee']
    del path[0]['hourly_funding']
    with pytest.raises(ExchangeError,match='OBSERVED_FUNDING'):episode(SPEC,path,'LONG',1000,ExitPolicy('TIME'))

def test_public_receipts_preserve_cancel_progress_and_actual_http_error(tmp_path):
    import threading
    from exchange.hyperliquid_client import RequestsInfoTransport
    stop=threading.Event();progress=lambda *a,**k:None
    class Transport(RequestsInfoTransport):
        def __init__(self):pass
        def __call__(self,payload,*,cancel_event,progress):
            assert cancel_event is stop and progress is not None
            raise self._failure('INFO_HTTP_429',status_code=429,retry_after_ms=5000)
        def close(self):pass
    path=tmp_path/'receipt';reader=ReadOnlyReceipts(Transport(),path)
    try:
        with pytest.raises(ExchangeError,match='HTTP_429'):
            reader(dict(type='perpDexs'),cancel_event=stop,progress=progress)
        saved=json.loads(path.read_text());assert saved['status_code']==429 and saved['retry_after_ms']==5000
    finally:reader.close()

def test_public_context_reader_waits_for_metadata_restart(monkeypatch):
    import threading
    from exchange.public_quant_operator import SerializedPublicMarket
    from exchange.hyperliquid_market_data import HyperliquidMarketData
    entered=threading.Event();release=threading.Event();finished=threading.Event();errors=[]
    client=SimpleNamespace(request_lock=threading.RLock(),ready=False)
    market=SerializedPublicMarket(client)
    def contexts(self):
        assert self.client.ready
        return {'par:BTC':{}}
    monkeypatch.setattr(HyperliquidMarketData,'get_asset_contexts',contexts)
    def restart():
        with client.request_lock:
            entered.set();release.wait(2);client.ready=True
    def read():
        try:market.get_asset_contexts()
        except Exception as exc:errors.append(exc)
        finally:finished.set()
    first=threading.Thread(target=restart);first.start();assert entered.wait(1)
    second=threading.Thread(target=read);second.start()
    assert not finished.wait(.02)
    release.set();first.join(1);second.join(1)
    assert finished.is_set() and not errors

@pytest.mark.parametrize('failure',[None,'source','account_exposure','account_unknown','market_outage','expired'])
def test_public_operator_bounded_shutdown_reconciliation_and_no_signer(tmp_path,monkeypatch,failure):
    """Whole observer loop with public-only deterministic transport fixtures."""
    import threading
    import exchange.public_quant_operator as op
    import venue_config,strategy_freeze
    monkeypatch.setattr(venue_config,'require_paper_migration',lambda:None)
    monkeypatch.setattr(strategy_freeze,'verify_strategy_freeze',lambda:True)
    calls=[];hash_calls=[]
    def source(_):
        hash_calls.append(1)
        return 'ff'*32 if failure=='source' and len(hash_calls)>1 else HASH
    monkeypatch.setattr(op,'active_source_hash',source)
    stop=threading.Event()
    class Stream:
        connected=False;reconciled=False;last_error=None;reconnections=0
        def __init__(self,*a,**k):
            self._recovery_cancel=threading.Event();self.transport_health=SimpleNamespace(report=lambda:{})
        def run(self,event,**k):event.wait()
    class Client:
        markets={'par:BTC':SPEC}
        def __init__(self,transport,**k):self.transport=transport;self.request_lock=threading.RLock()
        def startup(self):calls.append('startup')
        def market(self,symbol):return SPEC
        def close(self):self.transport.close();calls.append('close')
    class Transport:
        def __call__(self,payload):calls.append(payload);return {}
        def close(self):pass
    class Truth:
        initialized=True;positions=[];orders=[];reasons=[]
        def report(self):return dict(positions=self.positions,open_orders=self.orders,fills=[],
            reported_account_equity=dict(reported_account_value='1000000',collateral_balance='1000000',margin_used='0'),
            realized=dict(net_after_fees_and_funding='0'))
    class Reconciler:
        def __init__(self,*a):pass
        def recover_incremental(self,truth,**k):
            calls.append('reconcile')
            if failure=='account_exposure':truth.positions=[dict(symbol='par:BTC',quantity='.1')]
            if failure=='account_unknown':truth.reasons=['UNKNOWN_HISTORY']
    class Market:
        def __init__(self,*a):pass
        def get_candles(self,*a,**k):
            if failure=='market_outage':raise ExchangeError('PUBLIC_DATA_OUTAGE')
            return []
        def get_asset_contexts(self):return {'par:BTC':dict(funding=0,markPx=100,oraclePx=100)}
        def get_orderbook(self,*a):stop.set();return book()
    if failure=='market_outage':
        original=Market.get_candles
        def missing(self,*a,**k):stop.set();return original(self,*a,**k)
        Market.get_candles=missing
    monkeypatch.setattr(op,'RequestsInfoTransport',Transport)
    monkeypatch.setattr(op,'SerializedPublicClient',Client)
    monkeypatch.setattr(op,'ParMarketDataEngine',Stream)
    monkeypatch.setattr(op,'SerializedPublicMarket',Market)
    monkeypatch.setattr(op,'SerializedStreamMarket',Market)
    monkeypatch.setattr(op,'HyperliquidAccount',lambda *a:SimpleNamespace(_query=lambda _:dict(userCrossRate='.00045')))
    monkeypatch.setattr(op,'ExchangeTruthState',Truth)
    monkeypatch.setattr(op,'HyperliquidReconciliation',Reconciler)
    monkeypatch.setattr(op,'load_reliability_policy',lambda _:(None,None,None))
    monkeypatch.setattr(op,'HyperliquidRateLimitManager',lambda *a,**k:SimpleNamespace(report=lambda:{}))
    out=tmp_path/'observation';root=Path(__file__).resolve().parents[1]
    if failure=='expired':
        with pytest.raises(ExchangeError,match='EXACT_BOUNDED'):
            op.observe(root,out,team_wallet=TEAM,markets=('par:BTC',),expires_ms=NOW,
                source_hash=HASH,clock_ms=lambda:NOW)
        assert calls==[];return
    result=op.observe(root,out,team_wallet=TEAM,markets=('par:BTC',),expires_ms=NOW+60000,
        source_hash=HASH,clock_ms=lambda:NOW,stop_event=stop)
    assert result['exchange_writes']==0 and result['signatures_created']==0
    assert result['signing_authority']=='NONE' and result['signing_revoked']
    assert result['journal_integrity']=='ok' and (out/'terminal_result.json').exists()
    assert calls[-1]=='close'
    if failure=='account_exposure':assert result['status']=='EXPOSURE_REQUIRES_HUMAN_REVIEW'
    elif failure in {'source','account_unknown'}:assert result['status']=='PUBLIC_SESSION_HALTED'
    else:
        assert result['clean'] and result['fresh_terminal_reconciliation']
        assert len(result['terminal_readbacks'])==2
        assert all(r['decision']=='NO_TRADE' for r in result['signals'])
