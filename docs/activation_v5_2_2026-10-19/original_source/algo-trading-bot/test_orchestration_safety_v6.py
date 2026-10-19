"""Infrastructure orchestration tests with explicit core-output fixtures."""
from datetime import timedelta
import threading
import pandas as pd
import pytest

from test_safety_v6 import NOW, IDENTITY, payload, quote
from safety_test_support import paper_trader
from live_stream import AngelOneLiveStream
from symbol_state import create_isolated_symbol_state, SymbolExecutionState
from feed_integrity import FeedHealthState
from market_schedule import get_market_schedule
from execution_safety import SafetyError


def orchestration(tmp_path,monkeypatch,side='BUY',age_seconds=60):
    import live_stream
    stream=AngelOneLiveStream.__new__(AngelOneLiveStream)
    stream._execution_lock=threading.Lock()
    stream.paper_trader=paper_trader(tmp_path)
    stream.schedule=get_market_schedule('NSE')
    stream.angel_session=None
    state=create_isolated_symbol_state(IDENTITY.symbol,IDENTITY.token,IDENTITY.trading_symbol,rank=1)
    state.instrument=IDENTITY
    state.execution_state=SymbolExecutionState.ACTIVE
    state.feed_monitor.state=FeedHealthState.HEALTHY
    state.quote=quote(); state.last_spread_pct=.04; state.last_depth_available=True
    state.current_candle_df=pd.DataFrame([{'Timestamp':NOW-timedelta(seconds=age_seconds),
        'Open':300,'High':302,'Low':298,'Close':300,'Volume':10000,
        'VWAP':300,'ATR_14':5,'Buy_Signal':side=='BUY','Sell_Signal':side=='SELL',
        'Breakout_Signal':False,'Breakdown_Sell_Signal':False,'Signal_Type':'CORE_OUTPUT_FIXTURE'}]*15)
    stream.active_symbols={state.token:state}
    # This test isolates routing; separate regression tests run the frozen core itself.
    monkeypatch.setattr(live_stream,'generate_vwap_signal',lambda frame:frame)
    monkeypatch.setattr(live_stream,'detect_daily_bias',lambda frame:'NEUTRAL')
    return stream,state


def test_opposite_signal_reaches_existing_direction_flip(tmp_path,monkeypatch):
    stream,state=orchestration(tmp_path,monkeypatch,side='SELL')
    assert stream.paper_trader.execute_trade(payload(),timestamp=NOW)
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    assert len(stream.paper_trader.journal.trades())==1
    assert stream.paper_trader.open_position['side']=='SELL'
    stream.paper_trader.shutdown()


def test_completed_bar_cannot_submit_twice(tmp_path,monkeypatch):
    stream,state=orchestration(tmp_path,monkeypatch)
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    assert stream.paper_trader.has_open_position
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    assert stream.paper_trader.journal.budget()[1]==1
    stream.paper_trader.shutdown()


def test_stale_closed_bar_cannot_trade_on_fresh_quote(tmp_path,monkeypatch):
    stream,state=orchestration(tmp_path,monkeypatch,age_seconds=600)
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    assert not stream.paper_trader.has_open_position
    assert stream.paper_trader.journal.report()['rejections']['STALE_SIGNAL_CANDLE']==1
    stream.paper_trader.shutdown()


@pytest.mark.parametrize('timestamp',[None,'invalid'])
def test_missing_exchange_time_cannot_be_replaced_with_now(timestamp):
    from live_stream import _parse_tick_timestamp
    with pytest.raises(ValueError):_parse_tick_timestamp(timestamp)


def test_history_requires_authoritative_identity_before_login():
    from backtest_engine import fetch_historical_candles
    with pytest.raises(SafetyError,match='INSTRUMENT'):
        fetch_historical_candles('JIOFIN')


def test_flip_closes_before_replacement_economics_are_rejected(tmp_path,monkeypatch):
    stream,state=orchestration(tmp_path,monkeypatch,side='SELL')
    assert stream.paper_trader.execute_trade(payload(),timestamp=NOW)
    state.current_candle_df['ATR_14']=.1
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    assert not stream.paper_trader.has_open_position
    assert len(stream.paper_trader.journal.trades())==1
    assert stream.paper_trader.journal.budget()[1]==1
    stream.paper_trader.shutdown()


def test_flip_after_entry_cutoff_can_exit_without_new_entry(tmp_path,monkeypatch):
    from execution_safety import MarketQuote
    stream,state=orchestration(tmp_path,monkeypatch,side='SELL')
    assert stream.paper_trader.execute_trade(payload(),timestamp=NOW)
    late=NOW.replace(hour=14,minute=31)
    state.current_candle_df['Timestamp']=late-timedelta(minutes=1)
    state.quote=MarketQuote(299.95,300.05,1000,1000,late,300)
    stream.paper_trader.set_quote(IDENTITY,state.quote)
    stream._evaluate_watchlist_orchestrator(evaluation_time=late)
    assert not stream.paper_trader.has_open_position
    assert len(stream.paper_trader.journal.trades())==1
    assert stream.paper_trader.journal.budget()[1]==1
    stream.paper_trader.shutdown()
