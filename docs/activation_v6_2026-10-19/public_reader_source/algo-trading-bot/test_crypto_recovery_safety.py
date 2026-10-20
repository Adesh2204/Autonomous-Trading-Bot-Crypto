"""Recovery/accounting safety evidence using synthetic fixtures only."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import json
import subprocess
import sys
import threading

import pytest

from exchange.base_exchange import ExchangeError,Position,BookLevel,OrderBook
from exchange.account_events import AccountFunding
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from exchange.market_snapshot import MarketSnapshot
from exchange.paper_execution import PaperExecution,PaperFill
from exchange.paper_portfolio import PaperPortfolio,FundingSettlement
from exchange.paper_reconciliation import PaperReconciliation
from risk.circuit_breakers import CircuitBreakers,RiskState
from risk.exposure_manager import ExposureManager
from risk.portfolio_risk import PortfolioRisk
from market_stream import MarketStream
from test_exchange_migration import PublicInfoFixture,NOW,TEAM
from test_crypto_paper_infrastructure import universe,make_bot,signal_scan,q,bar,POLICY,FEES,SPEC,ROOT,load_paper_cli


class AccountFixture(PublicInfoFixture):
    def __init__(self):
        super().__init__()
        self.state['assetPositions'][0]['position'].update(szi='.04',entryPx='100.18')
        self.orders=[]
        self.fills=[dict(coin='par:BTC',time=NOW,tid=7,oid=1,side='A',sz='.01',px='101.84',
                        fee='.3',feeToken='USDPR',closedPnl='.0166',startPosition='.05')]
        self.funding=[dict(time=NOW,hash='0xfunding1',delta=dict(type='funding',coin='par:BTC',
                            usdc='.121234',szi='.04',fundingRate='.0001'))]

    def __call__(self,payload):
        if payload['type'] in {'userFillsByTime','userFunding'}:
            self.calls.append(deepcopy(payload))
            events=self.fills if payload['type']=='userFillsByTime' else self.funding
            return deepcopy([row for row in events if payload['startTime']<=row.get('time',NOW)<=payload['endTime']])
        return super().__call__(payload)


@pytest.fixture
def account():
    fixture=AccountFixture()
    client=HyperliquidClient(fixture,clock_ms=lambda:fixture.now)
    client.startup()
    return fixture,HyperliquidAccount(client,TEAM)


def test_account_recovers_actual_quantity_fill_price_fees_and_reported_funding(account):
    fixture,account=account
    state=ExchangeTruthState(quantities={'par:BTC':D('.05')},initialized=True)
    reconciler=HyperliquidReconciliation(account)
    report=reconciler.recover(state,start_ms=NOW-60000)
    assert not report['entries_paused'] and state.quantities['par:BTC']==D('.04')
    assert report['fills'][0]['price']==D('101.84')
    assert report['positions'][0]['entry_price']==D('100.18')
    assert report['realized']['actual_fill_fees']==D('.3')
    assert report['realized']['actual_funding_cashflow']==D('.121234')
    assert report['realized']['net_after_fees_and_funding']==D('.0166')-D('.3')+D('.121234')
    repeated=reconciler.recover(state,start_ms=NOW-60000)
    assert repeated['realized']==report['realized'] and len(state.fills)==len(state.funding)==1
    assert all(p.get('dex')=='par' for p in fixture.calls if p['type'] in {'clearinghouseState','openOrders'})
    assert all(p.get('user')==TEAM for p in fixture.calls if p['type'] in {'userFillsByTime','userFunding'})
    assert not any('action' in p or 'signature' in p for p in fixture.calls)


def test_unexplained_exchange_delta_stays_paused_until_missing_fill_arrives(account):
    fixture,account=account
    fill=fixture.fills.pop()
    state=ExchangeTruthState(quantities={'par:BTC':D('.05')},initialized=True)
    reconciler=HyperliquidReconciliation(account)
    first=reconciler.recover(state,start_ms=NOW-60000)
    assert first['entries_paused'] and state.quantities['par:BTC']==D('.04')
    assert reconciler.recover(state,start_ms=NOW-60000)['entries_paused']
    fixture.fills.append(fill)
    assert not reconciler.recover(state,start_ms=NOW-60000)['entries_paused']
    assert state.quantity_evidence['par:BTC']==D('.04')


def test_missing_closed_pnl_never_becomes_theoretical_profit(account):
    fixture,account=account
    del fixture.fills[0]['closedPnl']
    report=HyperliquidReconciliation(account).recover(ExchangeTruthState(),start_ms=NOW-60000)
    assert report['entries_paused'] and report['realized']['net_after_fees_and_funding'] is None
    assert 'REPORTED_CLOSED_PNL_MISSING' in report['reasons']


@pytest.mark.parametrize('field,value',[('fee','NaN'),('px','Infinity'),('sz','0'),('feeToken','USDC')])
def test_invalid_account_fill_cannot_mutate_mirror(account,field,value):
    fixture,account=account
    fixture.fills[0][field]=value
    state=ExchangeTruthState(quantities={'par:BTC':D('.05')},initialized=True)
    with pytest.raises(ExchangeError):
        HyperliquidReconciliation(account).recover(state,start_ms=NOW-60000)
    assert state.entries_paused and state.quantities['par:BTC']==D('.05') and not state.fills


def test_conflicting_account_event_is_atomic_and_pauses_entries(account):
    fixture,account=account
    state=ExchangeTruthState()
    reconciler=HyperliquidReconciliation(account)
    reconciler.recover(state,start_ms=NOW-60000)
    fixture.funding[0]['delta']['usdc']='10'
    with pytest.raises(ExchangeError,match='CONFLICTING_RECONCILED_EVENT'):
        reconciler.recover(state,start_ms=NOW-60000)
    assert state.entries_paused
    assert state.report()['realized']['actual_funding_cashflow']==D('.121234')


def test_account_failure_keeps_prior_view_and_global_pause(account,monkeypatch):
    _,account=account
    state=ExchangeTruthState(quantities={'par:BTC':D('.05')},initialized=True)
    def fail(*args): raise ExchangeError('ACCOUNT_REST_OFFLINE')
    monkeypatch.setattr(account,'get_funding',fail)
    with pytest.raises(ExchangeError,match='ACCOUNT_REST_OFFLINE'):
        HyperliquidReconciliation(account).recover(state,start_ms=NOW-60000)
    assert state.entries_paused and state.quantities['par:BTC']==D('.05')
    assert not state.fills and not state.events


def test_recovery_refuses_nonatomic_position_changes(account,monkeypatch):
    _,account=account
    original=account.get_positions
    calls=[0]
    def changing():
        calls[0]+=1
        positions=original()
        if calls[0]>1:
            positions['par:BTC']=replace(positions['par:BTC'],quantity=D('.03'))
        return positions
    monkeypatch.setattr(account,'get_positions',changing)
    state=ExchangeTruthState()
    with pytest.raises(ExchangeError,match='ACCOUNT_CHANGED_DURING_RECONCILIATION'):
        HyperliquidReconciliation(account).recover(state,start_ms=NOW-60000)
    assert state.entries_paused and not state.initialized


def test_recovery_history_gap_and_truncated_page_do_not_resume(account):
    fixture,account=account
    state=ExchangeTruthState()
    reconciler=HyperliquidReconciliation(account)
    reconciler.recover(state,start_ms=NOW-60000)
    fixture.now+=60000
    fixture.fills=[];fixture.funding=[]
    with pytest.raises(ExchangeError,match='HISTORY_WINDOW_GAP'):
        reconciler.recover(state,start_ms=NOW+1)
    fixture.fills=[dict(coin='BTC')]*2000
    with pytest.raises(ExchangeError,match='PAGE_LIMIT'):
        account.get_fills(start_ms=NOW-60000)
    assert state.entries_paused


def test_funding_uses_reported_payment_filters_other_dex_and_composite_identity(account):
    fixture,account=account
    fixture.funding.append(dict(time=NOW,hash='0xfunding1',delta=dict(type='funding',coin='BTC',
                                 usdc='999',szi='1',fundingRate='.1')))
    duplicate=deepcopy(fixture.funding[0])
    duplicate['delta']['coin']='par:ETH'
    fixture.funding.extend([duplicate,deepcopy(fixture.funding[0])])
    events=account.get_funding(NOW-60000)
    assert len(events)==2 and all(e.cashflow==D('.121234') for e in events)


def test_actual_bbo_entry_exit_are_accounting_prices_with_quantity_fees_and_funding():
    execution=PaperExecution({'par:BTC':SPEC},clock_ms=lambda:NOW,fees=FEES,starting_collateral=1000)
    entry=execution.place_order('par:BTC','BUY',2,'100.50')
    execution.simulate_fill(entry.order_id,q(bid='100.16',ask='100.18',mark='120',oracle='80'))
    assert execution.portfolio.positions['par:BTC'].entry_price==D('100.18')
    execution.portfolio.settle_funding(FundingSettlement('par:BTC',NOW,D('80'),D('.0001'),
                                                        'PAPER_SNAPSHOT_ESTIMATE'),NOW)
    exit_order=execution.place_order('par:BTC','SELL',2,'101.50',reduce_only=True)
    execution.simulate_fill(exit_order.order_id,q(bid='101.84',ask='101.86',mark='130',oracle='75'))
    assert execution.fills[-1].price==D('101.84')
    expected=2*(D('101.84')-D('100.18'))-sum(f.fee for f in execution.fills)-2*D('80')*D('.0001')
    assert execution.portfolio.cash==D(1000)+expected
    assert execution.portfolio.realized_pnl==2*(D('101.84')-D('100.18'))


def test_paper_recovery_repairs_local_quantity_and_cash_from_recorded_fill_truth(universe):
    _,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    truth=bot.execution.portfolio.positions['par:BTC'].quantity
    cash=bot.execution.portfolio.cash
    bot.execution.positions['par:BTC']=truth+D('.01')
    bot.managers['par:BTC']._open_position['quantity']=truth+D('.01')
    bot.execution.portfolio.cash=D('777')
    report=bot.reconcile_paper_state()
    assert not report['entries_paused'] and not report['exchange_account_verified']
    assert bot.execution.positions['par:BTC']==truth
    assert bot.managers['par:BTC']._open_position['quantity']==truth
    assert bot.execution.portfolio.cash==cash
    assert len(bot.execution.fills)==1 and len(bot.execution.orders)==1


def test_paper_recovery_cannot_invent_missing_strategy_or_fill_evidence(universe):
    _,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    manager=bot.managers.pop('par:BTC')
    assert bot.reconcile_paper_state()['entries_paused']
    bot.managers['par:BTC']=manager
    bot.execution.fills.clear()
    with pytest.raises(ExchangeError,match='FILL_EVIDENCE_MISSING'):
        bot.reconcile_paper_state()


def build_stream(universe):
    transport,bot=make_bot(universe)
    engine=ParMarketDataEngine(bot.market,history_bars=30,include_trades=True)
    stream=MarketStream(engine,POLICY)
    engine.connected=True
    engine.reconcile_history()
    assert stream.poll(bot)
    return transport,bot,engine,stream


def test_one_stale_symbol_does_not_block_other_healthy_symbols(universe):
    _,bot,engine,stream=build_stream(universe)
    engine.books['par:GOLD']=replace(engine.books['par:GOLD'],timestamp_ms=NOW-6000)
    engine.tick_times['par:GOLD']=NOW-6000
    stream.poll(bot)
    assert bot.breakers.state==RiskState.CAUTION
    assert bot.breakers.entry_reasons('par:GOLD') and not bot.breakers.entry_reasons('par:BTC')
    bot.consume_scan(signal_scan(NOW))
    assert len(bot.execution.fills)==1 and bot.execution.positions['par:BTC']>0


@pytest.mark.parametrize('clock',[ 'last_tick_time','last_candle_time','last_orderbook_time','last_mark_time'])
def test_independent_stale_clock_pauses_only_that_market(universe,monkeypatch,clock):
    _,bot,engine,stream=build_stream(universe)
    original=engine.get_observations
    def stale(symbol):
        values=original(symbol)
        if symbol=='par:BTC': values[clock]=NOW-180000
        return values
    monkeypatch.setattr(engine,'get_observations',stale)
    stream.poll(bot)
    bot.consume_scan(signal_scan(NOW))
    assert bot.execution.fills==[] and bot.breakers.entry_reasons('par:BTC')
    assert not bot.breakers.entry_reasons('par:ETH')


def test_reconnect_does_not_resume_until_account_callback_passes(universe):
    transport,bot,engine,stream=build_stream(universe)
    engine.connected=engine.reconciled=False
    assert not stream.poll(bot)
    bot.consume_scan(signal_scan(NOW))
    assert not bot.execution.fills
    engine.connected=True
    engine.reconcile_history()
    def fail(): raise ExchangeError('ACCOUNT_REST_OFFLINE')
    stream.account_recovery=fail
    assert not stream.poll(bot)
    assert bot.breakers.state==RiskState.ENTRY_PAUSED
    transport.now+=5000;transport.book['time']=transport.now
    engine.reconcile_history()
    stream.account_recovery=lambda:dict(entries_paused=False,source='SYNTHETIC_ACCOUNT_FIXTURE')
    assert stream.poll(bot)
    assert not bot.breakers.global_blocks
    assert stream.accepted_generation==engine.recovery_generation
    assert bot.reconciler.last_report['source']=='LOCAL_PAPER_FILL_REPLAY'


def test_stream_generation_change_during_account_read_cannot_resume(universe):
    _,bot,engine,stream=build_stream(universe)
    engine.reconcile_history()
    def changed():
        engine.recovery_generation+=1
        return dict(entries_paused=False,source='SYNTHETIC_ACCOUNT_FIXTURE')
    stream.account_recovery=changed
    assert not stream.poll(bot)
    assert 'STREAM_CHANGED_DURING_ACCOUNT_RECOVERY' in bot.breakers.entry_reasons('par:BTC')


def test_market_snapshot_prices_depth_and_imbalance_are_distinct(universe):
    _,bot,engine,stream=build_stream(universe)
    engine.books['par:BTC']=OrderBook('par:BTC',NOW,
        (BookLevel(D('99.99'),D(100)),BookLevel(D('99.98'),D(50))),
        (BookLevel(D('100.01'),D(10)),BookLevel(D('100.02'),D(20))))
    engine.ingest(dict(channel='trades',data=[dict(coin='par:BTC',time=NOW,tid=7,side='A',px='90',sz='1')]))
    snapshot=engine.get_snapshot('par:BTC')
    assert snapshot.last_trade_price==90 and snapshot.mid==snapshot.mark_price==100
    assert snapshot.bid_depth_notional==D('99.99')*100+D('99.98')*50
    assert snapshot.orderbook_imbalance==(snapshot.bid_depth_notional-snapshot.ask_depth_notional)/(
        snapshot.bid_depth_notional+snapshot.ask_depth_notional)
    assert engine.get_snapshot('par:ETH').last_trade_price is None
    order=bot.execution.place_order('par:BTC','BUY',1,'100.01')
    fill=bot.execution.simulate_fill(order.order_id,engine.get_quote('par:BTC'))
    assert fill.price==D('100.01')


def test_receive_stall_and_retry_budget_pause_without_exchange_writes(universe,monkeypatch):
    import exchange.hyperliquid_market_data as data_module
    transport,bot=make_bot(universe)
    clock=[0.]
    monkeypatch.setattr(data_module.time,'monotonic',lambda:clock[0])
    class Socket:
        closed=False
        def send(self,message): pass
        def recv(self): clock[0]+=46;raise TimeoutError()
        def close(self): self.closed=True
    socket=Socket()
    engine=ParMarketDataEngine(bot.market,connect=lambda:socket,history_bars=30)
    stream=MarketStream(engine,replace(POLICY,max_reconnect_failures=1))
    with pytest.raises(ExchangeError,match='RECONNECT_LIMIT'):
        stream.run(threading.Event())
    assert socket.closed and engine.last_error.endswith('HOST_PROCESSING_GAP_DETECTED')
    assert not stream.poll(bot) and bot.breakers.state==RiskState.ENTRY_PAUSED
    assert len(bot.execution.orders)==0


def test_exposure_reports_gross_net_directional_per_symbol_margin_and_count():
    specs={s:replace(SPEC,symbol=s) for s in ('par:BTC','par:ETH','par:GOLD')}
    portfolio=PaperPortfolio(specs,1000)
    for symbol,side,qty,price in (('par:BTC','BUY',2,100),('par:ETH','SELL',D('1.5'),200),('par:GOLD','BUY',1,50)):
        portfolio.apply_fill(PaperFill(symbol,symbol,side,qty,D(price),D(0),NOW),1)
    quotes={s:replace(q(bid=str(mark-D('.01')),ask=str(mark+D('.01')),mark=str(mark)),symbol=s)
            for s,mark in (('par:BTC',D(101)),('par:ETH',D(198)),('par:GOLD',D(50)))}
    snapshot=portfolio.snapshot(quotes,NOW)
    metrics=ExposureManager.metrics(snapshot,portfolio,quotes)
    assert metrics['total_gross_exposure']==549 and metrics['total_net_exposure']==-45
    assert metrics['directional_concentration']==D(297)/549 and metrics['position_count']==3
    assert metrics['per_symbol_exposure']['par:ETH']['signed_notional']==-297
    assert metrics['margin_utilization']==D(549)/1005


@pytest.mark.parametrize('changes,reason',[
    ({'max_symbol_equity_multiple':'.001'},'SYMBOL_EXPOSURE_LIMIT'),
    ({'max_net_equity_multiple':'.001'},'NET_EXPOSURE_LIMIT'),
    ({'max_directional_equity_multiple':'.001'},'DIRECTIONAL_EXPOSURE_LIMIT')])
def test_exposure_limits_reject_positive_edge(changes,reason):
    policy=replace(POLICY,**changes)
    decision=PortfolioRisk(policy,FEES).assess(SPEC,'BUY',100,2,q(),PaperPortfolio({'par:BTC':SPEC},1000),{},NOW)
    assert decision.reasons==(reason,)


def test_leverage_changes_margin_without_multiplying_stop_risk_quantity():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    one=PortfolioRisk(POLICY,FEES).assess(SPEC,'BUY',100,2,q(),portfolio,{},NOW)
    ten=PortfolioRisk(replace(POLICY,leverage=10),FEES).assess(SPEC,'BUY',100,2,q(),portfolio,{},NOW)
    assert one.allowed and ten.allowed and one.quantity==ten.quantity
    assert one.economics.stop_risk==ten.economics.stop_risk<=5


def test_risk_states_are_scoped_and_never_flatten_positions(universe):
    _,bot=make_bot(universe)
    portfolio=bot.execution.portfolio
    snapshot=portfolio.snapshot({},NOW)
    breaker=bot.breakers
    breaker.evaluate(snapshot,daily_loss=0,drawdown=0)
    assert breaker.state==RiskState.NORMAL
    breaker.evaluate(snapshot,daily_loss=0,drawdown=D('.04'))
    assert breaker.state==RiskState.CAUTION
    breaker.evaluate(snapshot,daily_loss=0,drawdown=D('.05'))
    assert breaker.state==RiskState.ENTRY_PAUSED and breaker.entry_reasons('par:ETH')==('MAX_DRAWDOWN',)
    breaker.evaluate(replace(snapshot,equity=0),daily_loss=0,drawdown=D('.05'))
    assert breaker.state==RiskState.EMERGENCY
    assert not bot.execution.orders and not bot.execution.fills


def test_consecutive_order_errors_latch_and_reconnect_limits_pause_all(universe):
    _,bot=make_bot(universe)
    for _ in range(3): bot.breakers.order_result(False)
    assert bot.breakers.entry_reasons('par:BTC')==('MAX_CONSECUTIVE_ORDER_ERRORS',)
    bot.breakers.order_result(True)
    assert bot.breakers.entry_reasons('par:ETH')==('MAX_CONSECUTIVE_ORDER_ERRORS',)
    bot.breakers.update_reconnects(5)
    assert 'MAX_RECONNECT_FAILURES' in bot.breakers.entry_reasons('par:GOLD')
    assert not bot.execution.fills


def test_mark_age_gate_is_independent_of_fresh_executable_book():
    quote=replace(q(),mark_timestamp_ms=NOW-60001)
    decision=PortfolioRisk(POLICY,FEES).assess(SPEC,'BUY',100,2,quote,PaperPortfolio({'par:BTC':SPEC},1000),{},NOW)
    assert decision.reasons==('MARK_DATA_STALE',)


@pytest.mark.parametrize('settings',[{'max_drawdown_fraction':0},{'max_data_age_ms':True},
    {'max_mark_age_ms':60001},{'max_reconnect_failures':0},{'max_symbol_equity_multiple':'NaN'}])
def test_invalid_new_safety_limits_rejected(settings):
    with pytest.raises(ExchangeError): replace(POLICY,**settings)


def test_account_observer_arguments_rejected_before_output_or_network(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_crypto_paper.py'),'--account-address','private-key-text',
                           '--output',str(tmp_path/'run')],capture_output=True,text=True)
    assert result.returncode!=0 and 'PUBLIC_TEAM_ADDRESS_REQUIRED' in result.stderr
    assert not (tmp_path/'run').exists()


def test_new_recovery_core_imports_no_stock_sessions_or_broker_transport():
    script='import sys,json; import market_stream,exchange.hyperliquid_reconciliation,risk.circuit_breakers; '
    script+='print(json.dumps(sorted(set(sys.modules)&{"config","safe_trader","execution_engine","SmartApi","pyotp","market_schedule","pandas_market_calendars"})))'
    result=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'algo-trading-bot',capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==[]


def test_untracked_open_order_is_adopted_but_blocks_new_entries(account):
    fixture,account=account
    fixture.orders=[dict(coin='par:BTC',oid=1,sz='.02')]
    state=ExchangeTruthState()
    report=HyperliquidReconciliation(account).recover(state,start_ms=NOW-60000)
    assert report['entries_paused'] and 'UNTRACKED_EXCHANGE_OPEN_ORDERS' in report['reasons']
    assert state.orders['1']['sz']=='.02' and fixture.orders[0]['sz']=='.02'
    fixture.orders=[]
    assert not HyperliquidReconciliation(account).recover(state,start_ms=NOW-60000)['entries_paused']


@pytest.mark.parametrize('value',[True,None,'',-1,1.5])
def test_invalid_exchange_identity_cannot_reconcile(account,value):
    fixture,account=account
    fixture.fills[0]['tid']=value
    with pytest.raises(ExchangeError,match='EVENT_ID'):
        account.get_fills()


def test_missing_context_timestamp_rejects_risk_and_accounted_fill():
    quote=replace(q(),mark_timestamp_ms=None)
    decision=PortfolioRisk(POLICY,FEES).assess(SPEC,'BUY',100,2,quote,PaperPortfolio({'par:BTC':SPEC},1000),{},NOW)
    assert decision.reasons==('MARK_TIMESTAMP_REQUIRED',)
    execution=PaperExecution({'par:BTC':SPEC},clock_ms=lambda:NOW,fees=FEES,starting_collateral=1000)
    order=execution.place_order('par:BTC','BUY',1,'100.01')
    with pytest.raises(ExchangeError,match='MARK_CONTEXT'):
        execution.simulate_fill(order.order_id,quote)
    assert not execution.fills and execution.portfolio.cash==1000


def test_old_mark_context_cannot_value_held_portfolio():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    portfolio.apply_fill(PaperFill('1','par:BTC','BUY',1,D(100),D(0),NOW),1)
    with pytest.raises(ExchangeError,match='MARK_CONTEXT'):
        portfolio.snapshot({'par:BTC':replace(q(),mark_timestamp_ms=NOW-60001)},NOW)


def test_incremental_account_window_preserves_cumulative_observed_pnl(account):
    fixture,account=account
    state=ExchangeTruthState()
    reconciler=HyperliquidReconciliation(account)
    reconciler.recover_incremental(state,initial_start_ms=NOW-60000)
    fixture.now+=120000
    reconciler.recover_incremental(state,initial_start_ms=NOW-60000)
    fixture.now+=120000
    fixture.funding.append(dict(time=fixture.now,hash='0xfunding2',delta=dict(type='funding',coin='par:BTC',
                                    usdc='-.2',szi='.04',fundingRate='.001')))
    report=reconciler.recover_incremental(state,initial_start_ms=NOW-60000)
    assert not report['entries_paused']
    assert report['accounting_window_ms']==(NOW-60000,fixture.now)
    assert report['latest_query_window_ms']==(NOW+60000,fixture.now)
    assert report['realized']['actual_funding_cashflow']==D('.121234')-D('.2')
    assert report['realized']['actual_fill_fees']==D('.3')


def test_empty_book_during_rest_recovery_only_pauses_that_market(universe,monkeypatch):
    _,bot=make_bot(universe)
    original=bot.market.get_orderbook
    def empty(symbol):
        if symbol=='par:GOLD': raise ExchangeError('NO_EXECUTABLE_TWO_SIDED_BOOK')
        return original(symbol)
    monkeypatch.setattr(bot.market,'get_orderbook',empty)
    engine=ParMarketDataEngine(bot.market,history_bars=30)
    stream=MarketStream(engine,POLICY)
    engine.connected=True
    engine.reconcile_history()
    assert stream.poll(bot)
    assert not bot.breakers.entry_reasons('par:BTC') and bot.breakers.entry_reasons('par:GOLD')
    assert engine.unavailable_books['par:GOLD']=='NO_EXECUTABLE_TWO_SIDED_BOOK'


def test_empty_stream_book_is_symbol_paused_and_valid_book_restores_it(universe):
    transport,bot,engine,stream=build_stream(universe)
    engine.ingest(dict(channel='l2Book',data=dict(coin='par:GOLD',time=NOW,levels=[[],[]])))
    assert stream.poll(bot) and engine.connected and engine.reconciled
    assert bot.breakers.entry_reasons('par:GOLD') and not bot.breakers.entry_reasons('par:BTC')
    engine.ingest(dict(channel='l2Book',data=dict(transport.book,coin='par:GOLD')))
    stream.poll(bot)
    assert not bot.breakers.entry_reasons('par:GOLD')
