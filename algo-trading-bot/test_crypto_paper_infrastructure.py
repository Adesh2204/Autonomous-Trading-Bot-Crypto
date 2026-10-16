"""Synthetic offline infrastructure evidence, never competition returns."""
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime,timezone
from decimal import Decimal as D
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from candle_normalizer import candles_to_frame
from crypto_paper_bot import CryptoPaperBot
from crypto_strategy_state import CryptoStrategyState
from exchange.base_exchange import Candle,ExchangeError,MarketSpec,Quote,VenueMismatch
from exchange.hyperliquid_client import HyperliquidClient,EXPECTED_MARKETS
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.order_lifecycle import OrderRequest,OrderState,parse_order_results
from exchange.paper_execution import PaperExecution,PaperFill
from exchange.paper_portfolio import PaperPortfolio,FundingSettlement
from exchange.perpetual_economics import FeeSchedule,estimate_trade
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy,MarketDiagnostic,ScanResult
from risk.models import RiskPolicy,RiskDecision
from risk.portfolio_risk import PortfolioRisk
from session_manager import SessionManager
from strategy_contract import ManagementState
from safety_errors import SafetyError
from test_exchange_migration import PublicInfoFixture,NOW

ROOT=Path(__file__).resolve().parents[1]
FEES=FeeSchedule(D('.0003'),D('.0009'),'SYNTHETIC_TEST_ASSUMPTION')
POLICY=RiskPolicy(D('.005'),D('.01'),D('1'),D('.5'),D('2'),D('.001'),D('50'),D('15'),
                  D('.1'),D('5'),D('1'),1)
SPEC=MarketSpec('par:BTC',4,10,110000)


def q(now=NOW, *, bid='99.99',ask='100.01',depth='100',mark='100',oracle='100',funding='.0001'):
    return Quote('par:BTC',now,D(bid),D(ask),D(depth),D(depth),(D(bid)+D(ask))/2,
                 D(mark),D(oracle),D(funding),D('100'),D('100000'),mark_timestamp_ms=now)


def bar(start=NOW-60000, *, close='100',symbol='par:BTC'):
    price=D(close)
    return Candle(symbol,'1m',start,start+59999,price,price+D('2'),price-D('2'),price,D('10'))


@pytest.fixture
def paper():
    clock=[NOW]
    execution=PaperExecution({'par:BTC':SPEC},fees=FEES,starting_collateral=1000,clock_ms=lambda:clock[0])
    return clock,execution


def test_runtime_universe_includes_new_par_markets_and_skips_delisted_nonrequired():
    transport=PublicInfoFixture()
    transport.metadata['universe'] += [dict(name='par:NEW',szDecimals=2,maxLeverage=5),
                                        dict(name='par:OLD',szDecimals=2,maxLeverage=5,isDelisted=True)]
    client=HyperliquidClient(transport)
    client.startup()
    assert 'par:NEW' in client.markets and 'par:OLD' not in client.markets
    assert client.market('par:NEW').asset_id==110010
    client.post_info('l2Book',coin='par:NEW')
    assert transport.calls[-1]=={'type':'l2Book','coin':'par:NEW'}


def test_runtime_margin_table_is_used_and_changes_revoke_registry():
    transport=PublicInfoFixture()
    transport.metadata['universe'][0]['marginTableId']=51
    transport.metadata['marginTables']=[[51,{'marginTiers':[{'lowerBound':'0','maxLeverage':10},
                                                        {'lowerBound':'1000','maxLeverage':5}]}]]
    client=HyperliquidClient(transport)
    client.startup()
    spec=client.market(transport.metadata['universe'][0]['name'])
    assert spec.maintenance_margin(1500)==D('100')
    assert spec.maximum_leverage_at(1500)==5
    metadata=deepcopy(transport.metadata)
    metadata['marginTables'][0][1]['marginTiers'][1]['maxLeverage']=4
    with pytest.raises(VenueMismatch):
        client.validate_metadata(metadata)
    assert not client.ready


def test_missing_custom_margin_table_aborts_startup():
    transport=PublicInfoFixture()
    transport.metadata['universe'][0]['marginTableId']=50
    with pytest.raises(VenueMismatch):
        HyperliquidClient(transport).startup()


@pytest.mark.parametrize('tiers', [((D('1'),10),),((D(0),10),(D(0),5)),
                                   ((D(0),10),(D(100),20)),((D(0),5),)])
def test_invalid_margin_tiers_rejected(tiers):
    with pytest.raises(ExchangeError):
        MarketSpec('par:BTC',4,10,0,tiers)


def test_session_is_continuous_and_anchor_explicit_even_on_weekend():
    session=SessionManager()
    saturday=datetime(2026,10,3,20,30,tzinfo=timezone.utc)
    assert session.get_vwap_anchor(saturday)==saturday.replace(hour=0,minute=0)
    assert session.can_enter_new_positions(saturday) and not session.is_eod_square_off(saturday)
    with pytest.raises(SafetyError):
        session.localize(datetime(2026,10,3))


@pytest.mark.parametrize('anchor',['ROLLING','NSE_OPEN','ANCHORED_OPTIMIZED'])
def test_unvalidated_vwap_anchor_not_silently_enabled(anchor):
    from safety_errors import SafetyError
    with pytest.raises(SafetyError,match='UNVALIDATED_VWAP_ANCHOR'):
        SessionManager(anchor)


def test_normalizer_preserves_fractional_volume_and_utc_shape():
    c=replace(bar(),volume=D('.0017'))
    frame=candles_to_frame([c])
    assert list(frame)==['Timestamp','Open','High','Low','Close','Volume']
    assert str(frame.Timestamp.dt.tz)=='UTC' and frame.Volume.iloc[0]==.0017


def test_partial_fills_consume_depth_once_and_complete_on_new_observations(paper):
    clock,execution=paper
    order=execution.submit(OrderRequest('par:BTC','BUY',D('1'),D('100.01')))
    quote=q(depth='.3')
    first=execution.simulate_fill(order.order_id,quote)
    assert first.quantity==D('.3') and execution.orders[order.order_id].status=='PARTIALLY_FILLED'
    assert execution.simulate_fill(order.order_id,quote) is None
    for _ in range(3):
        clock[0]+=1
        execution.simulate_fill(order.order_id,replace(quote,timestamp_ms=clock[0]))
    assert execution.orders[order.order_id].status=='FILLED'
    assert sum(f.quantity for f in execution.fills)==1
    assert len({f.fill_id for f in execution.fills})==4
    assert execution.portfolio.reservations=={}


def test_ioc_partial_fill_cancels_only_unfilled_remainder(paper):
    _,execution=paper
    order=execution.submit(OrderRequest('par:BTC','BUY',1,'100.01',tif='Ioc'))
    fill=execution.simulate_fill(order.order_id,q(depth='.25'))
    assert fill.quantity==D('.25')
    assert execution.orders[order.order_id].remaining_quantity==D('.75')
    assert execution.orders[order.order_id].status=='CANCELLED'
    states=[e['state'] for e in execution.events]
    assert states==['CREATED','SUBMITTED','ACKNOWLEDGED','OPEN','PARTIALLY_FILLED','CANCEL_PENDING','CANCELLED']
    assert execution.portfolio.positions['par:BTC'].quantity==D('.25')
    assert execution.portfolio.reservations=={}


def test_idempotent_request_cannot_duplicate_or_change_order(paper):
    _,execution=paper
    request=OrderRequest('par:BTC','BUY',1,'100.01',client_order_id='fixture-1')
    first=execution.submit(request)
    assert execution.submit(request)==first and len(execution.orders)==1
    with pytest.raises(ExchangeError,match='CONFLICTING_CLIENT'):
        execution.submit(replace(request,quantity=D('2')))


def test_post_only_does_not_invent_maker_fills(paper):
    clock,execution=paper
    crossing=execution.submit(OrderRequest('par:BTC','BUY',1,'100.01',tif='Alo'))
    assert execution.simulate_fill(crossing.order_id,q()) is None
    assert execution.orders[crossing.order_id].status=='REJECTED'
    passive=execution.submit(OrderRequest('par:BTC','BUY',1,'99.99',tif='Alo'))
    execution.simulate_fill(passive.order_id,q())
    clock[0]+=1
    execution.simulate_fill(passive.order_id,q(clock[0],bid='99.98',ask='99.99'))
    assert execution.orders[passive.order_id].status=='OPEN' and execution.fills==[]


def test_pending_orders_reserve_one_shared_margin_pool(paper):
    _,execution=paper
    first=execution.place_order('par:BTC','BUY',D('8'),'100.01')
    with pytest.raises(ExchangeError,match='MARGIN_INSUFFICIENT'):
        execution.place_order('par:BTC','BUY',D('3'),'100.01')
    execution.cancel_order('par:BTC',first.order_id)
    assert execution.place_order('par:BTC','BUY',D('3'),'100.01').status=='OPEN'


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_shared_ledger_realized_unrealized_fees_and_funding(side):
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    fill=PaperFill('fixture','par:BTC',side,D('1'),D('100'),D('1'),NOW-1000)
    portfolio.apply_fill(fill,2)
    assert portfolio.apply_fill(fill,2) is False
    quote=q(mark='110',oracle='120')
    snapshot=portfolio.snapshot({'par:BTC':quote},NOW)
    assert snapshot.cash==999
    assert snapshot.unrealized_pnl==(10 if side=='BUY' else -10)
    assert snapshot.initial_margin==55 and snapshot.maintenance_margin_estimate==D('5.5')
    event=FundingSettlement('par:BTC',NOW,D('120'),D('.01'),'OBSERVED_SETTLEMENT')
    flow=portfolio.settle_funding(event,NOW)
    assert flow==(D('-1.2') if side=='BUY' else D('1.2'))
    assert portfolio.settle_funding(event,NOW)==0
    exit_side='SELL' if side=='BUY' else 'BUY'
    portfolio.apply_fill(PaperFill('exit','par:BTC',exit_side,D('1'),D('110'),D('1'),NOW+1),2)
    assert not portfolio.positions
    assert portfolio.cash==D('1000')+(10 if side=='BUY' else -10)-2+flow


def test_causal_funding_rejects_historical_current_position_or_future_event():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    portfolio.apply_fill(PaperFill('1','par:BTC','BUY',1,D('100'),D('0'),NOW+1),1)
    with pytest.raises(ExchangeError,match='NON_CAUSAL'):
        portfolio.settle_funding(FundingSettlement('par:BTC',NOW,100,'.01','OBSERVED_SETTLEMENT'),NOW+1)
    with pytest.raises(ExchangeError,match='TIME_INVALID'):
        portfolio.settle_funding(FundingSettlement('par:BTC',NOW+3600000,100,'.01','OBSERVED_SETTLEMENT'),NOW+1)


def test_stale_or_missing_marks_never_produce_equity():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    portfolio.apply_fill(PaperFill('1','par:BTC','BUY',1,D('100'),D('0'),NOW),1)
    with pytest.raises(ExchangeError,match='MARK_MISSING_OR_STALE'):
        portfolio.snapshot({},NOW)
    with pytest.raises(ExchangeError,match='MARK_MISSING_OR_STALE'):
        portfolio.snapshot({'par:BTC':q(NOW-5001)},NOW)


def test_cost_gate_uses_oracle_for_funding_and_no_expected_credit():
    quote=q(mark='90',oracle='120',funding='.01')
    long=estimate_trade('BUY',1,100,96,108,quote,FEES,slippage_bps=5,holding_hours=1)
    assert long.funding_cost==D('1.2') and long.fees>0 and long.spread_cost>0
    short=estimate_trade('SELL',1,100,104,92,quote,FEES,slippage_bps=5,holding_hours=1)
    assert short.funding_cost==0
    assert long.net_profit==long.gross_profit-long.fees-long.spread_cost-long.slippage_cost-long.funding_cost


def test_risk_sizes_fractionally_without_changing_stop_target_multipliers():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    decision=PortfolioRisk(POLICY,FEES).assess(SPEC,'BUY',100,2,q(),portfolio,{},NOW)
    assert decision.allowed and decision.quantity%SPEC.size_step==0
    assert decision.stop==96 and decision.target==108
    assert decision.economics.stop_risk<=5 and decision.quantity<2
    short=PortfolioRisk(POLICY,FEES).assess(SPEC,'SELL',100,2,q(),portfolio,{},NOW)
    assert short.allowed and short.stop==104 and short.target==92


def test_subcent_atr_does_not_round_strategy_stop_to_zero():
    spec=MarketSpec('par:BTC',4,10,0)
    quote=q(bid='1.0000',ask='1.0001',depth='1000',mark='1',oracle='1')
    decision=PortfolioRisk(POLICY,FeeSchedule(0,0,'TEST')).assess(
        spec,'BUY',1,'.004',quote,PaperPortfolio({'par:BTC':spec},1000),{},NOW)
    assert decision.allowed and decision.stop==D('.992') and decision.target==D('1.016')


@pytest.mark.parametrize('change,reason', [
    ({'bid':'99','ask':'101'},'SPREAD_TOO_WIDE'),
    ({'mark':'110'},'MARK_ORACLE_DIVERGENCE'),
    ({'funding':'.02'},'NET_EDGE_OR_RR_INSUFFICIENT'),
    ({'depth':'.001'},'ORDER_BELOW_MINIMUM_NOTIONAL'),
])
def test_perpetual_risk_rejections(change,reason):
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    decision=PortfolioRisk(POLICY,FEES).assess(SPEC,'BUY',100,2,q(**change),portfolio,{},NOW)
    assert not decision.allowed and reason in decision.reasons


def test_daily_limit_and_tier_leverage_cannot_be_bypassed():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    risk=PortfolioRisk(POLICY,FEES)
    for values,reason in [({'daily_setups':2},'MAX_NEW_SETUPS_REACHED'),
                          ({'daily_loss':D('10')},'DAILY_RISK_EXHAUSTED')]:
        decision=risk.assess(SPEC,'BUY',100,2,q(),portfolio,{},NOW,**values)
        assert not decision.allowed and reason in decision.reasons
    risk=PortfolioRisk(replace(POLICY,leverage=11),FEES)
    assert risk.assess(SPEC,'BUY',100,2,q(),portfolio,{},NOW).reasons==('LEVERAGE_EXCEEDS_RUNTIME_LIMIT',)


def test_request_level_ok_does_not_hide_individual_rejection_and_ioc_partial():
    requests=[OrderRequest('par:BTC','BUY',1,100),OrderRequest('par:BTC','BUY',1,100,tif='Ioc')]
    response={'status':'ok','response':{'type':'order','data':{'statuses':[
        {'error':'Insufficient margin'},{'filled':{'oid':1,'totalSz':'.25','avgPx':'100'}}]}}}
    result=parse_order_results(response,requests)
    assert result[0].state==OrderState.REJECTED and result[0].error=='Insufficient margin'
    assert result[1].state==OrderState.CANCELLED and result[1].filled_quantity==D('.25')


@pytest.mark.parametrize('status',[{'filled':{'oid':1,'totalSz':'2','avgPx':'100'}},
                                  {'resting':{'oid':True}},'success',{'unknown':{}}])
def test_unknown_order_results_fail_closed(status):
    with pytest.raises(ExchangeError):
        parse_order_results({'status':'ok','response':{'type':'order','data':{'statuses':[status]}}},
                            [OrderRequest('par:BTC','BUY',1,100)])


@pytest.fixture
def universe():
    transport=PublicInfoFixture()
    transport.metadata['universe'].append(dict(name='par:NEW',szDecimals=4,maxLeverage=10))
    transport.contexts=[dict(markPx='100',oraclePx='100',funding='.0001',openInterest='100',dayNtlVlm='100000')
                        for row in transport.metadata['universe']]
    transport.book=dict(coin='par:BTC',time=NOW,levels=[[dict(px='99.99',sz='100')],[dict(px='100.01',sz='100')]])
    def info(payload):
        if payload['type']=='candleSnapshot':
            req=payload['req']
            return [dict(t=t,T=t+59999,s=req['coin'],i='1m',o='100',h='102',l='98',c='100',v='10')
                    for t in range(req['startTime'],req['endTime']+1,60000)]
        return transport(payload)
    client=HyperliquidClient(info,clock_ms=lambda:transport.now)
    client.startup()
    market=HyperliquidMarketData(client)
    scanner=MarketRegimeScanner(market,ScannerPolicy('.004',15,0,10,history_bars=30))
    return transport,market,scanner


def test_scanner_covers_entire_runtime_universe_has_comparable_units_and_stable_top_three(universe):
    transport,market,scanner=universe
    result=scanner.scan()
    assert len(result.diagnostics)==11 and any(d.symbol=='par:NEW' for d in result.diagnostics)
    assert len(result.watchlist)==3 and result.watchlist==sorted(result.watchlist)
    first=result.diagnostics[0]
    assert first.metrics['atr_percent']==D('4.00')
    assert first.metrics['spread_bps']==D('2')
    assert first.metrics['open_interest']==100
    assert all(not d.signal['long'] and not d.signal['short'] for d in result.diagnostics)


def test_scanner_no_qualification_is_no_trade_without_threshold_relaxation(universe):
    _,_,scanner=universe
    scanner.policy=replace(scanner.policy,min_atr_fraction=D('.5'))
    result=scanner.scan()
    assert result.status=='NO_TRADE' and result.watchlist==[]
    assert all('ATR_BELOW_BASELINE_SCANNER_FLOOR' in d.reasons for d in result.diagnostics)


def make_bot(universe):
    transport,market,scanner=universe
    execution=PaperExecution(market.client.markets,fees=FEES,starting_collateral=1000,
                             clock_ms=market.client.clock_ms)
    return transport,CryptoPaperBot(market,scanner,execution,PortfolioRisk(POLICY,FEES))


def signal_scan(now,side='BUY'):
    diagnostic=MarketDiagnostic('par:BTC',True,signal=dict(symbol='par:BTC',timestamp_ms=now-60000,
        reference=D(100),atr=D(2),bias='NEUTRAL',long=side=='BUY',short=side=='SELL',
        signal_type='PULLBACK_LONG' if side=='BUY' else 'PULLBACK_SHORT'),
        candles=[bar(now-60000)])
    return ScanResult(now,[diagnostic],['par:BTC'],'ACTIVE')


def test_generic_paper_pipeline_and_direction_flip_reconcile_before_new_entry(universe):
    transport,bot=make_bot(universe)
    scan=signal_scan(NOW)
    bot.consume_scan(scan)
    assert len(bot.execution.fills)==1 and bot.execution.portfolio.positions['par:BTC'].quantity>0
    bot.consume_scan(scan)
    assert len(bot.execution.fills)==1
    transport.now+=60000
    transport.book['time']=transport.now
    bot.consume_scan(signal_scan(transport.now,'SELL'))
    assert bot.execution.portfolio.positions['par:BTC'].quantity<0
    assert len(bot.execution.fills)==3
    assert any(d['kind']=='EXIT_FILL' and d['reason']=='Direction Flip' for d in bot.decisions)
    assert bot.report()['exchange_orders_submitted']==0


def test_missed_funding_boundary_pauses_entries_and_does_not_invent_payment(universe):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    cash=bot.execution.portfolio.cash
    transport.now+=3600000+6000
    transport.book['time']=transport.now
    bot.observe({'par:BTC':bot.market.get_quote('par:BTC')})
    assert bot.accounting_halt=='MISSED_PAPER_FUNDING_BOUNDARY_REQUIRES_REPLAY'
    assert bot.execution.portfolio.funding_cashflow==0 and bot.execution.portfolio.cash==cash


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_frozen_management_parity_target_wick_close_stop_theta_and_counters(side):
    from execution_engine import LegacyPaperTrader,PyramidingState
    initial=dict(side=side,quantity=D('.25'),average_entry_price=100.,target_price=108. if side=='BUY' else 92.,
                 stop_loss_price=96. if side=='BUY' else 104.,current_tranches=1,
                 tranches=[{'entry_price':100.}],breakeven_armed=False,atr_14=2.)
    calls=[]
    manager=CryptoStrategyState('par:BTC',lambda symbol,reason:calls.append(reason),clock_ms=lambda:NOW)
    manager._open_position=deepcopy(initial)
    manager._state=ManagementState.HOLDING_TRANCHE_1
    manager.entry_atr=2.
    class BaselineHarness:
        lock=threading.RLock()
        schedule=SessionManager()
        max_tranches=1
        entry_atr=2.
        candles_held=0
        candles_since_last_sl=10000
        _state=PyramidingState.HOLDING_TRANCHE_1
        def _resolve_timestamp(self,value): return value
        def _check_day_reset(self,value): pass
        def _set_latest_price(self,price,when): pass
        def close_position(self,exit_price,timestamp,reason): self.calls.append(reason)
    baseline=BaselineHarness()
    baseline._open_position=deepcopy(initial)
    baseline.calls=[]
    timestamp=datetime.fromtimestamp(NOW/1000,timezone.utc)
    # Wick through stop on an ordinary tick is immune; target tick triggers.
    for price in (95. if side=='BUY' else 105.,108. if side=='BUY' else 92.):
        LegacyPaperTrader.check_exit(baseline,price,timestamp)
        manager.check_exit(price,timestamp)
    assert baseline.calls==calls==['Target Hit']
    calls.clear();baseline.calls.clear()
    # At 15 profitable completed candles the identical function arms breakeven.
    for i in range(15):
        candle={'Timestamp':timestamp,'Close':101. if side=='BUY' else 99.}
        LegacyPaperTrader.notify_candle_close(baseline,candle)
        manager.notify_candle_close(candle)
    assert manager._open_position==baseline._open_position
    assert manager._open_position['stop_loss_price']==100.
    assert manager.candles_held==baseline.candles_held==15
    assert manager.candles_since_last_sl==baseline.candles_since_last_sl
    candle={'Timestamp':timestamp,'Close':100.}
    LegacyPaperTrader.notify_candle_close(baseline,candle)
    manager.notify_candle_close(candle)
    assert baseline.calls==calls==['Breakeven Stop (Close-Based)']


def test_state_rejects_gaps_and_duplicate_close_is_idempotent():
    manager=CryptoStrategyState('par:BTC',lambda s,r:None,clock_ms=lambda:NOW)
    manager.completed_candle(bar(NOW-180000))
    before=manager.candles_since_last_sl
    manager.completed_candle(bar(NOW-180000))
    assert manager.candles_since_last_sl==before
    with pytest.raises(ExchangeError,match='STATE_CANDLE_GAP'):
        manager.completed_candle(bar(NOW-60000))


def test_new_infrastructure_imports_no_legacy_transport_accounting_or_calendars():
    script='import sys,json; import crypto_paper_bot,market_regime_scanner,risk.portfolio_risk; '
    script+='print(json.dumps(sorted(set(sys.modules)&{"SmartApi","pyotp","config","execution_engine","execution_safety","safe_trader","market_schedule","pandas_market_calendars"})))'
    result=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'algo-trading-bot',capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==[]


def test_generic_signed_submit_is_also_locked_without_transport():
    from order_guard import OrderRoutingBlocked
    with pytest.raises(OrderRoutingBlocked):
        HyperliquidExecution(object()).submit(OrderRequest('par:BTC','BUY',1,100))


@pytest.mark.parametrize('settings,reason',[
    ({'max_gross_equity_multiple':D('.01')},'PORTFOLIO_EXPOSURE_LIMIT'),
    ({'max_funding_cost_fraction':D('.0000001')},'FUNDING_COST_LIMIT'),
    ({'maintenance_buffer_multiple':D('300')},'LIQUIDATION_BUFFER_INSUFFICIENT'),
])
def test_independent_perpetual_gates_after_positive_edge(settings,reason):
    policy=replace(POLICY,**settings)
    decision=PortfolioRisk(policy,FEES).assess(SPEC,'BUY',100,2,q(),
        PaperPortfolio({'par:BTC':SPEC},1000),{},NOW)
    assert not decision.allowed and decision.reasons==(reason,)


def test_existing_position_can_block_shared_margin_before_new_entry():
    portfolio=PaperPortfolio({'par:BTC':SPEC},1000)
    portfolio.apply_fill(PaperFill('1','par:BTC','BUY',2,D('100'),D(0),NOW),1)
    decision=PortfolioRisk(replace(POLICY,max_margin_utilization=D('.1')),FEES).assess(
        SPEC,'BUY',100,2,q(),portfolio,{'par:BTC':q()},NOW)
    assert decision.reasons==('PORTFOLIO_MARGIN_LIMIT',)
    decision=PortfolioRisk(POLICY,FEES).assess(SPEC,'BUY',100,2,q(),portfolio,{'par:BTC':q()},NOW)
    assert decision.reasons==('PORTFOLIO_POSITION_LIMIT',)


def test_mark_growth_rejects_unfunded_fill_and_releases_reservation(paper):
    _,execution=paper
    order=execution.place_order('par:BTC','BUY',5,100)
    with pytest.raises(ExchangeError,match='MARGIN_INSUFFICIENT_AT_FILL'):
        execution.simulate_fill(order.order_id,q(bid='99.99',ask='100',mark='300',oracle='300'))
    assert execution.orders[order.order_id].status=='REJECTED'
    assert not execution.portfolio.reservations and execution.fills==[]
    assert execution.portfolio.cash==1000


def test_open_position_spec_change_cannot_silently_change_execution(paper):
    _,execution=paper
    order=execution.place_order('par:BTC','BUY',1,'100.01')
    execution.simulate_fill(order.order_id,q())
    with pytest.raises(ExchangeError,match='METADATA_CHANGED'):
        execution.refresh_specs({'par:BTC':replace(SPEC,size_decimals=3)})
    assert execution.specs['par:BTC']==SPEC


def test_partial_exit_intent_survives_price_moving_away_from_target(universe):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    held=bot.execution.portfolio.positions['par:BTC'].quantity
    transport.now+=1
    quote=q(transport.now,bid='108',ask='108.01',depth=str(held/2),mark='108',oracle='108')
    bot.observe({'par:BTC':quote})
    assert bot.execution.portfolio.positions['par:BTC'].quantity==held-SPEC.normalize_size(held/2)
    assert bot.pending_exit_reasons['par:BTC']=='Target Hit'
    transport.now+=1
    bot.observe({'par:BTC':q(transport.now,bid='105',ask='105.01',mark='105',oracle='105')})
    assert not bot.execution.portfolio.positions and not bot.pending_exit_reasons
    assert len(bot.closed_trades)==1 and bot.closed_trades[0]['net_pnl']>0


def test_midnight_funding_snapshot_is_explicit_estimate_and_deduplicated(universe):
    transport,bot=make_bot(universe)
    # Start away from the funding boundary, enter, then observe the next hour.
    transport.now=NOW+60000
    transport.book['time']=transport.now
    bot.consume_scan(signal_scan(transport.now))
    held=bot.execution.portfolio.positions['par:BTC'].quantity
    transport.now=NOW+3600000
    transport.book['time']=transport.now
    bot.observe({'par:BTC':bot.market.get_quote('par:BTC')})
    assert bot.execution.portfolio.funding_cashflow==-held*D('100')*D('.0001')
    events=[e for e in bot.execution.portfolio.events if e['kind']=='FUNDING']
    assert len(events)==1 and events[0]['source']=='PAPER_SNAPSHOT_ESTIMATE'
    bot.observe({'par:BTC':bot.market.get_quote('par:BTC')})
    assert len([e for e in bot.execution.portfolio.events if e['kind']=='FUNDING'])==1


@pytest.mark.parametrize('changes',[{'mark':D('NaN')},{'hourly_funding':D('Infinity')},
                                    {'ask':D('90')},{'mid':D('101')}])
def test_invalid_quote_fields_rejected_before_any_accounting(changes):
    with pytest.raises(ExchangeError):
        replace(q(),**changes)


def test_stop_cooldown_and_short_atr_state_preserved(universe):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW,'SELL'))
    manager=bot.managers['par:BTC']
    assert manager.entry_atr==2
    transport.now+=60000
    transport.book['time']=transport.now
    transport.book['levels']=[[dict(px='104.99',sz='100')],[dict(px='105.01',sz='100')]]
    transport.contexts=[dict(markPx='105',oraclePx='105',funding='.0001') for row in transport.metadata['universe']]
    bot.quotes['par:BTC']=bot.market.get_quote('par:BTC')
    manager.completed_candle(bar(NOW,close='105'))
    assert not manager.has_open_position and manager.candles_since_last_sl==0
    assert not manager.permits('SELL')
    for index in range(1,11):
        transport.now+=60000
        manager.completed_candle(bar(NOW+index*60000))
    assert manager.permits('SELL')


def test_report_contains_only_labelled_paper_pnl_and_reproducible_source_bars(universe,tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('paper_cli',ROOT/'scripts/run_crypto_paper.py')
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    transport,bot=make_bot(universe)
    snapshot=bot.cycle()
    writer=cli.ReportWriter(tmp_path/'run','SYNTHETIC_TEST_FIXTURE')
    report=writer.save(bot,snapshot)
    saved=json.loads((tmp_path/'run/report.json').read_text())
    assert saved['balance_origin']=='HYPOTHETICAL_LOCAL_USDPR'
    assert saved['exchange_orders_submitted']==0 and saved['local_fills']==0
    assert saved['performance']['win_rate'] is None
    assert len((tmp_path/'run/candles.jsonl').read_text().splitlines())==11
    with pytest.raises(ExchangeError,match='OUTPUT_MUST_BE_NEW'):
        cli.ReportWriter(tmp_path/'run','OTHER')


def test_paper_cli_rejects_live_override_without_creating_output(tmp_path):
    import os
    env=dict(os.environ,EXECUTION_MODE='HYPERLIQUID',ALLOW_LIVE_ORDERS='true')
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_crypto_paper.py'),'--output',str(tmp_path/'forbidden')],
                          env=env,capture_output=True,text=True)
    assert result.returncode!=0 and 'PAPER_MODE_REQUIRED' in result.stderr
    assert not (tmp_path/'forbidden').exists()


def test_nan_no_signal_sentinel_is_saved_as_null(universe,monkeypatch,tmp_path):
    transport,market,scanner=universe
    original=scanner.brain.evaluate_candles
    def frame_with_nan(candles):
        frame=original(candles)
        frame['Signal_Type']=float('nan')
        return frame
    monkeypatch.setattr(scanner.brain,'evaluate_candles',frame_with_nan)
    scan=scanner.scan()
    assert all(d.signal['signal_type'] is None for d in scan.diagnostics)
    _,bot=make_bot(universe)
    bot.scanner=scanner
    bot.consume_scan(scan)
    encoded=json.dumps(bot.report(),default=str,allow_nan=False)
    assert json.loads(encoded)['diagnostics'][0]['signal']['signal_type'] is None


def test_paper_account_implements_generic_positions_fills_and_equity(paper):
    from exchange.paper_account import PaperAccount
    _,execution=paper
    order=execution.place_order('par:BTC','BUY',1,'100.01')
    execution.simulate_fill(order.order_id,q())
    account=PaperAccount(execution)
    assert account.get_position('par:BTC').quantity==1
    fills=account.get_fills()
    assert len(fills)==1 and fills[0].fee_token=='USDPR'
    assert account.get_equity().valuation_source=='PAPER_USDPR_MARK_ACCOUNTING'
    assert account.get_open_orders()==[]


def test_baseline_single_position_and_setup_limits_cannot_be_silently_increased():
    with pytest.raises(ExchangeError,match='BASELINE_PORTFOLIO_STATE_LIMIT_REQUIRED'):
        replace(POLICY,max_positions=2)
    with pytest.raises(ExchangeError,match='BASELINE_PORTFOLIO_STATE_LIMIT_REQUIRED'):
        replace(POLICY,max_daily_setups=3)


def test_opposite_signal_blocked_by_baseline_bias_cannot_close_position(universe):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    transport.now+=60000
    transport.book['time']=transport.now
    scan=signal_scan(transport.now,'SELL')
    scan.diagnostics[0].signal['bias']='LONG_BIAS'
    bot.consume_scan(scan)
    assert len(bot.execution.fills)==1 and bot.execution.portfolio.positions['par:BTC'].quantity>0
    assert bot.decisions[-1]['reason']=='BASELINE_BIAS_OR_COOLDOWN'


def test_idle_market_gap_preserves_known_cooldown_and_does_not_halt_other_markets(universe):
    _,bot=make_bot(universe)
    manager=bot._manager('par:BTC')
    manager.last_candle_ms=NOW-300000
    manager.candles_since_last_sl=3
    idle=MarketDiagnostic('par:BTC',False,reasons=['INSUFFICIENT_DATA'],candles=[bar()])
    candidate=signal_scan(NOW).diagnostics[0]
    candidate.symbol='par:ETH'
    candidate.signal['symbol']='par:ETH'
    candidate.candles=[bar(symbol='par:ETH')]
    bot.consume_scan(ScanResult(NOW,[idle,candidate],['par:ETH'],'ACTIVE'))
    assert bot.accounting_halt is None
    assert manager.candles_since_last_sl==4
    assert bot.execution.portfolio.positions['par:ETH'].quantity>0


def test_open_position_candle_gap_halts_entries_without_advancing_state(universe):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    transport.now+=300000
    transport.book['time']=transport.now
    bot.consume_scan(signal_scan(transport.now))
    assert bot.accounting_halt=='STRATEGY_STATE_CANDLE_GAP'
    assert bot.managers['par:BTC'].candles_held==0 and len(bot.execution.fills)==1


def test_completed_feed_bar_stops_position_between_scans_at_current_bbo(universe):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    transport.now+=60000
    transport.book['time']=transport.now
    # Wick alone leaves the position open. The completed candle is the trigger;
    # fill price is the current executable bid, never a made-up stop-price fill.
    bot.observe({'par:BTC':q(transport.now,bid='95.99',ask='96.01',mark='96',oracle='96')})
    assert bot.execution.portfolio.positions
    bot.observe_completed_candles({'par:BTC':[bar(NOW,close='96')]})
    assert not bot.execution.portfolio.positions
    assert bot.execution.fills[-1].price==D('95.99')
    assert bot.managers['par:BTC'].candles_since_last_sl==0
    assert 'Stop Loss' in bot.closed_trades[-1]['reason']
    assert bot.latest_scan.observed_at_ms==NOW


def test_completed_feed_and_scan_do_not_double_count_cooldown(universe):
    transport,bot=make_bot(universe)
    bot.observe_completed_candles({'par:BTC':[bar()]})
    transport.now+=60000
    transport.book['time']=transport.now
    bot.observe_completed_candles({'par:BTC':[bar(NOW)]})
    count=bot.managers['par:BTC'].candles_since_last_sl
    bot.consume_scan(signal_scan(transport.now))
    assert bot.managers['par:BTC'].candles_since_last_sl==count


def load_paper_cli():
    import importlib.util
    spec=importlib.util.spec_from_file_location('paper_cli',ROOT/'scripts/run_crypto_paper.py')
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def test_stale_shutdown_preserves_positions_and_events_without_fabricated_equity(universe,tmp_path):
    transport,bot=make_bot(universe)
    bot.consume_scan(signal_scan(NOW))
    transport.now+=6000
    with pytest.raises(ExchangeError,match='MARK_MISSING_OR_STALE'):
        bot.execution.portfolio.snapshot(bot.quotes,transport.now)
    writer=load_paper_cli().ReportWriter(tmp_path/'run','SYNTHETIC_TEST_FIXTURE')
    writer.save_halt(bot,'STALE_TEST',name='shutdown.json')
    saved=json.loads((tmp_path/'run/shutdown.json').read_text())
    assert saved['equity'] is None and saved['last_good_report'] is None
    assert saved['known_positions'][0]['quantity']==str(bot.execution.positions['par:BTC'])
    assert saved['exchange_orders_submitted']==0 and saved['ledger_events']


def test_continuous_cli_workers_feed_scanner_and_single_ledger_owner_offline(universe,tmp_path,monkeypatch):
    transport,market,scanner=universe
    cli=load_paper_cli()
    connections=[]
    ready=threading.Event()
    def client_factory():
        client=HyperliquidClient(market.client.transport,clock_ms=lambda:transport.now)
        connections.append(client)
        return client
    class Scanner(MarketRegimeScanner):
        def run(self,stop,interval):
            assert ready.wait(1)
            for _ in range(2):
                yield self.scan()
    class Engine:
        def __init__(self,market,**kwargs):
            self.market=market
            self.symbols=tuple(sorted(market.client.markets))
            self.connected=False
            self.reconciled=False
            self.recovery_generation=1
            self.messages=1
            self.consecutive_failures=0
            self.reconnections=0
            self.last_receive_ms=NOW
            self.last_error=None
            self.history_bars=kwargs['history_bars']
            self.recovery_status='RECONCILED'
            self.recovery_errors={}
            self.rates=None
            from exchange.feed_transport import FeedTransportHealth
            self.transport_health=FeedTransportHealth(wall_ms=lambda:NOW)
            from exchange.market_health import MarketHealthManager
            self.health_manager=MarketHealthManager(self.symbols,history_bars=self.history_bars)
        def publish_public_snapshot(self,*args):pass
        def note_scanner_failure(self,*args):pass
        def run(self,stop,**kwargs):
            self.connected=self.reconciled=True
            ready.set()
            stop.wait(5)
        def get_completed_candles(self,symbol):
            return [replace(bar(symbol=symbol),timestamp_ms=NOW-i*60000,
                close_timestamp_ms=NOW-(i-1)*60000-1) for i in range(self.history_bars,0,-1)]
        def get_quote(self,symbol):
            return replace(q(),symbol=symbol)
        def get_observations(self,symbol):
            return dict(last_tick_time=NOW,last_candle_time=NOW,last_orderbook_time=NOW,last_mark_time=NOW)
        def acknowledge_recovery(self,generation):
            assert generation==self.recovery_generation
        def get_snapshot(self,symbol):
            from exchange.market_snapshot import MarketSnapshot
            return MarketSnapshot.from_book(self.market.get_orderbook(symbol),
                self.market.get_asset_contexts()[symbol],NOW,mark_observed_at_ms=NOW)
    monkeypatch.setattr(cli,'HyperliquidClient',client_factory)
    monkeypatch.setattr(cli,'MarketRegimeScanner',Scanner)
    monkeypatch.setattr(cli,'ParMarketDataEngine',Engine)
    monkeypatch.setattr(sys,'argv',['run_crypto_paper.py','--cycles','2','--output',str(tmp_path/'run')])
    assert cli.main()==0
    saved=json.loads((tmp_path/'run/report.json').read_text())
    assert len(connections)==3 and saved['scanned_markets']==11
    assert saved['local_fills']==saved['exchange_orders_submitted']==0
    assert saved['strategy_state']['par:BTC']['candles_since_last_sl']==10001
    assert len((tmp_path/'run/equity.jsonl').read_text().splitlines())==2
