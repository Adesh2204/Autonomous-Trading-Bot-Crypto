import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

from test_safety_v6 import NOW, IDENTITY, quote, payload
from execution_engine import PaperTrader
from execution_safety import SafetyError, MarketQuote
from instrument_registry import InstrumentRegistry
from opportunity_engine import same_time_rvol, arbitration_key

def test_master_resolves_once_and_rejects_guess():
    rows=[{'exch_seg':'NSE','symbol':'JIOFIN-EQ','token':'18143','tick_size':'5','lotsize':'1'}]
    r=InstrumentRegistry(rows,NOW,['JIOFIN'])
    assert r.resolve('JIOFIN') is r.resolve('JIOFIN-EQ')
    with pytest.raises(SafetyError):r.resolve('JIOFIN','4907',NOW)
    assert r.resolve('JIOFIN').tick_size==.05

def test_master_stale_and_duplicate_fail_closed(tmp_path):
    row={'exch_seg':'NSE','symbol':'JIOFIN-EQ','token':'18143','tick_size':'5','lotsize':'1'}
    with pytest.raises(SafetyError):InstrumentRegistry([row,row],NOW,['JIOFIN'])
    p=tmp_path/'master.json'; p.write_text(json.dumps({'records':[row],'source_timestamp':(NOW-timedelta(days=2)).isoformat(),'intraday_symbols':['JIOFIN']}))
    with pytest.raises(SafetyError,match='STALE'):InstrumentRegistry.load(p,NOW)

def test_same_clock_rvol_excludes_later_volume():
    profiles=[{'10:00':100.,'15:00':10000.}]*3
    assert same_time_rvol(200.,NOW.time().replace(tzinfo=None),profiles)==2.

def test_arbitration_uses_quality_before_rupee_profit():
    a={'execution_quality':.9,'net_rr':1.3,'depth':200,'opportunity_score':3.,'timestamp':'a','symbol':'A','rupee_profit':20}
    b=dict(a,execution_quality=.8,rupee_profit=1000,symbol='B')
    assert sorted([b,a],key=arbitration_key)[0] is a

def test_pilot_preserves_stop_target_and_close_based_stop(tmp_path):
    t=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    ticket=t.execute_trade(payload(),timestamp=NOW)
    assert ticket['stop_loss_price']==290. and ticket['target_price']==320.
    t.set_quote(IDENTITY,MarketQuote(289.75,289.85,1000,1000,NOW,289.8))
    assert t.check_exit(289.8,NOW) is None
    assert t.has_open_position
    assert t.notify_candle_close({'Timestamp':NOW,'Close':289.8})
    assert t.candles_since_last_sl==0
    t.shutdown()

def test_original_breakeven_math_preserved(tmp_path):
    t=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert t.execute_trade(payload(),timestamp=NOW)
    entry=t.avg_entry_price
    for i in range(15):t.notify_candle_close({'Timestamp':NOW,'Close':entry+1.})
    assert t.open_position['stop_loss_price']==entry
    assert t.open_position['breakeven_armed']
    t.shutdown()

def test_valid_direction_flip_closes_before_opposite_entry(tmp_path):
    t=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert t.execute_trade(payload(),timestamp=NOW)
    short=payload(); short['signal_id']='short'
    second=t.execute_trade(short,timestamp=NOW,side='SELL')
    assert len(t.journal.trades())==1
    assert t.journal.trades()[0]['exit_reason']=='Direction Flip (BUY→SELL)'
    assert second is None or t.open_position['side']=='SELL'
    t.shutdown()

def test_single_session_replay_is_explicit_and_non_phantom(tmp_path):
    from replay_engine import replay
    timestamps=pd.date_range(NOW.replace(hour=9,minute=15),periods=45,freq='min')
    close=np.linspace(290,310,len(timestamps))
    df=pd.DataFrame({'Timestamp':timestamps,'Open':close,'High':close+1.5,'Low':close-1.5,'Close':close,'Volume':10000})
    with pytest.raises(SafetyError):replay(df,IDENTITY,None,tmp_path)
    trades,curve,metadata=replay(df,IDENTITY,'SYNTHETIC_TEST_FIXTURE',tmp_path)
    assert metadata['unattended_live_eligible'] is False
    assert metadata['provenance']=='SYNTHETIC_TEST_FIXTURE'
    assert curve is not None
    for trade in trades:
        assert trade['environment']=='REPLAY'
        assert trade['actual_entry_price']>0

def test_stream_ticks_carry_identity_depth_and_real_volume(monkeypatch):
    from live_stream import AngelOneLiveStream
    from feed_integrity import ThreadSafeTickIngestionQueue
    stream=AngelOneLiveStream.__new__(AngelOneLiveStream)
    stream.active_symbols={IDENTITY.token:SimpleNamespace(symbol=IDENTITY.symbol,token=IDENTITY.token,exchange_type=1)}
    stream._cumulative_volumes={}; stream.ingestion_queue=ThreadSafeTickIngestionQueue()
    frame={'token':'18143','last_traded_price':30000,'exchange_timestamp':int(NOW.timestamp()*1000),
           'volume_trade_for_the_day':100,'best_5_buy_data':[{'price':29995,'quantity':1000}],
           'best_5_sell_data':[{'price':30005,'quantity':1500}]}
    stream._on_data(None,frame); frame=dict(frame,volume_trade_for_the_day=125); stream._on_data(None,frame)
    a=stream.ingestion_queue.get(); b=stream.ingestion_queue.get()
    assert a.volume==0 and b.volume==25
    assert b.price==300 and b.ask_quantity==1500 and b.cumulative_volume==125

def test_stream_constructor_rejects_unverified_identity(monkeypatch,tmp_path):
    import config
    from live_stream import AngelOneLiveStream
    monkeypatch.setattr(config,'INSTRUMENT_MASTER_FILE',str(tmp_path/'absent.json'))
    with pytest.raises(FileNotFoundError):AngelOneLiveStream(target_symbol='JIOFIN',target_token='4907')

def test_sensitive_logging_redacted():
    import logging
    from security_logging import BrokerSecretFilter
    record=logging.LogRecord('x',40,'x',1,'loginByPassword Request: password=secret',(),None)
    assert BrokerSecretFilter().filter(record)
    assert 'secret' not in record.getMessage()


def test_replay_executes_on_next_observation_with_prior_volume(tmp_path):
    from replay_engine import replay
    from signal_brain import generate_vwap_signal
    from test_phase5_multisymbol import _generate_synthetic_candle_df
    frame=_generate_synthetic_candle_df('JIOFIN',base_price=300)
    frame['Timestamp']=pd.date_range(NOW.replace(hour=9,minute=15),periods=15,freq='min')
    core=generate_vwap_signal(frame)
    assert core.iloc[-1]['Buy_Signal']
    ref=float(core.iloc[-1]['VWAP']); atr=float(core.iloc[-1]['ATR_14'])
    next_open=ref+.2
    next_row={'Timestamp':frame.iloc[-1]['Timestamp']+pd.Timedelta(minutes=1),
        'Open':next_open,'Low':next_open-.05,'High':ref+4*atr+2,'Close':next_open+.2,'Volume':0}
    frame=pd.concat([frame,pd.DataFrame([next_row])],ignore_index=True)
    trades,_,metadata=replay(frame,IDENTITY,'SYNTHETIC_TEST_FIXTURE',tmp_path)
    assert trades
    assert trades[0]['actual_entry_price']>=next_open
    assert trades[0]['actual_entry_price']!=ref
    assert trades[0]['net_pnl']>0
    assert 'previously completed bar volume' in ' '.join(metadata['assumptions'])


def test_no_trade_startup_still_emits_report(tmp_path,monkeypatch):
    import config
    from live_stream import record_screening_report
    monkeypatch.setattr(config,'LIVE_MODE',False)
    monkeypatch.setattr(config,'EXECUTION_ENVIRONMENT','TEST')
    report=record_screening_report(reason='INSTRUMENT_SOURCE_UNAVAILABLE',output_dir=tmp_path,now=NOW)
    assert report['completed_trades']==0
    assert report['no_trade_explanation']['INSTRUMENT_SOURCE_UNAVAILABLE']==1
    assert (tmp_path/'trades.report.json').exists()
