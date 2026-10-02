"""Adversarial audit cases added before the corresponding safety repairs."""
from datetime import timedelta
import math
import pytest

from test_safety_v6 import NOW, IDENTITY, quote, payload
from test_broker_safety_v6 import Broker, capabilities
from execution_adapters import SmartAPIExecutionAdapter, PaperExecutionAdapter
from execution_engine import PaperTrader
from execution_safety import SafetyError
from opportunity_engine import same_time_rvol


@pytest.fixture(autouse=True)
def offline_protocol_only(monkeypatch):
    from safety_test_support import allow_offline_broker_protocol
    allow_offline_broker_protocol(monkeypatch)


@pytest.mark.parametrize('cash', ['nan', 'inf', True, '-1'])
def test_nonfinite_or_boolean_broker_cash_is_blocked(cash):
    broker = Broker()
    broker.rmsLimit = lambda: {'status': True, 'data': {'availablecash': cash}}
    adapter = SmartAPIExecutionAdapter(broker, capabilities(), lambda: NOW)
    with pytest.raises(SafetyError):
        adapter.available_cash()


def test_same_time_rvol_rejects_current_and_future_sessions():
    profiles = [
        {'session_date': str(NOW.date()-timedelta(days=i)), 'cumulative_volume': {'10:00': 100}}
        for i in (1, 2, 3)
    ]
    profiles += [{'session_date': str(NOW.date()), 'cumulative_volume': {'10:00': 90000}}]
    assert same_time_rvol(200, NOW.time().replace(tzinfo=None), profiles, NOW.date()) == 2


def test_known_stale_quote_exit_can_retry_without_duplicate_order(tmp_path):
    trader = PaperTrader(environment='TEST', clock=lambda: NOW, csv_log_path=str(tmp_path/'x.csv'))
    assert trader.execute_trade(payload(), timestamp=NOW)
    late = NOW + timedelta(minutes=1)
    assert trader.close_position(300, late) is None
    trader.set_quote(IDENTITY, quote_at(late))
    assert trader.close_position(300, late)
    assert len(trader.journal.trades()) == 1
    trader.shutdown()


def quote_at(when):
    from execution_safety import MarketQuote
    return MarketQuote(299.95, 300.05, 1000, 1000, when, 300)


def test_failure_halt_is_durable_after_completed_emergency_exit(tmp_path):
    class ProtectionFailure(PaperExecutionAdapter):
        def protect(self, *args, **kwargs):
            raise SafetyError('PROTECTION_FAILED')
    path = str(tmp_path/'x.csv')
    trader = PaperTrader(environment='TEST', adapter=ProtectionFailure(), clock=lambda: NOW, csv_log_path=path)
    assert trader.execute_trade(payload(), timestamp=NOW) is None
    assert not trader.has_open_position
    trader.shutdown()
    restored = PaperTrader(environment='TEST', clock=lambda: NOW, csv_log_path=path)
    assert restored.is_halted
    assert restored.execute_trade(payload(), timestamp=NOW) is None
    restored.shutdown()


def test_fill_rejects_nonfinite_price_and_charges():
    broker = Broker()
    adapter = SmartAPIExecutionAdapter(broker, capabilities(), lambda: NOW)
    order_id = broker.placeOrder({'variety':'NORMAL', 'tradingsymbol':IDENTITY.trading_symbol,
        'symboltoken':IDENTITY.token, 'exchange':'NSE', 'transactiontype':'BUY',
        'quantity':'8', 'price':'300'})
    broker.orders[0]['averageprice'] = 'nan'
    with pytest.raises(SafetyError):
        adapter.read_fill(order_id, IDENTITY, 'BUY', 8)
    broker.orders[0]['averageprice'] = '300'
    broker.orders[0]['totalcharges'] = 'nan'
    with pytest.raises(SafetyError):
        adapter.read_fill(order_id, IDENTITY, 'BUY', 8)


def test_replay_rejects_empty_and_nonfinite_prices(tmp_path):
    import pandas as pd
    from replay_engine import replay
    frame = pd.DataFrame(columns=['Timestamp','Open','High','Low','Close','Volume'])
    with pytest.raises(SafetyError):
        replay(frame, IDENTITY, 'SYNTHETIC_TEST_FIXTURE', tmp_path)
    frame.loc[0] = [NOW, 300, 301, 299, math.nan, 1000]
    with pytest.raises(SafetyError):
        replay(frame, IDENTITY, 'SYNTHETIC_TEST_FIXTURE', tmp_path)


def test_identity_cannot_embed_different_trading_symbol():
    from dataclasses import replace
    with pytest.raises(SafetyError):
        replace(IDENTITY, trading_symbol='SJVN-EQ').validate('JIOFIN', now=NOW)


def test_nonfinite_depth_is_not_liquidity():
    from execution_safety import MarketQuote, ExecutionQualityGate
    bad=MarketQuote(299.95,300.05,math.nan,math.inf,NOW,300)
    with pytest.raises(SafetyError):
        ExecutionQualityGate().validate(bad,'BUY',NOW,8)


def test_protective_ack_must_match_instrument():
    broker=Broker()
    original=broker.placeOrder
    def misroute(params):
        order_id=original(params)
        broker.orders[-1]['symboltoken']='4907'
        return order_id
    broker.placeOrder=misroute
    adapter=SmartAPIExecutionAdapter(broker,capabilities(),lambda:NOW)
    with pytest.raises(SafetyError):
        adapter.protect(IDENTITY,'SELL',8,290,NOW)


def test_projected_risk_includes_exit_spread_and_tick_rounding():
    from execution_safety import estimate_trade_economics
    economics=estimate_trade_economics('BUY',8,300,290,320,.0005,
        exit_spread_pct=.0015/2,tick_size=.05)
    assert economics.net_stop_loss>estimate_trade_economics('BUY',8,300,290,320,.0005).net_stop_loss
    assert economics.estimated_spread_cost>0


def test_duplicate_entry_fill_cannot_open_a_second_trade(tmp_path):
    from execution_adapters import FillResult
    class RepeatEntry(PaperExecutionAdapter):
        def execute(self,instrument,side,quantity,quote,now,limit=None):
            fill=super().execute(instrument,side,quantity,quote,now,limit)
            return FillResult('repeated-entry','same-fill',fill.quantity,fill.price,fill.fees) if side=='BUY' else fill
    trader=PaperTrader(environment='TEST',adapter=RepeatEntry(),clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert trader.execute_trade(payload(),timestamp=NOW)
    assert trader.close_position(300,NOW)
    assert trader.execute_trade(payload(),timestamp=NOW) is None
    assert trader.is_halted and not trader.has_open_position
    assert len(trader.journal.trades())==1
    trader.shutdown()


def test_attempt_limit_is_atomic_inside_journal(tmp_path):
    from safety_journal import SafetyJournal
    journal=SafetyJournal(tmp_path/'x.db','TEST'); journal.start_day(NOW.date())
    for trade_id in ('one','two'):
        journal.reserve(trade_id,40,200); journal.finish(trade_id,20)
    with pytest.raises(ValueError,match='MAX_NEW_SETUPS'):
        journal.reserve('third',40,200)
    assert journal.budget()[1]==2
    journal.close()


def test_report_includes_observed_unrealized_drawdown(tmp_path):
    trader=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert trader.execute_trade(payload(),timestamp=NOW)
    trader.check_exit(310,NOW)
    trader.check_exit(295,NOW)
    report=trader.journal.report()
    assert report['peak_intraday_drawdown']>100
    assert report['completed_trades']==0
    assert report['realized_peak_drawdown']==0
    trader.shutdown()


def test_restart_preserves_breakeven_candle_count(tmp_path):
    path=str(tmp_path/'x.csv')
    trader=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=path)
    assert trader.execute_trade(payload(),timestamp=NOW)
    entry=trader.avg_entry_price
    for _ in range(14):trader.notify_candle_close({'Timestamp':NOW,'Close':entry+1})
    trader.shutdown()
    restored=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=path)
    assert restored.candles_held==14
    restored.notify_candle_close({'Timestamp':NOW,'Close':entry+1})
    assert restored.open_position['stop_loss_price']==entry
    restored.shutdown()


def test_restart_cannot_erase_stop_cooldown(tmp_path):
    path=str(tmp_path/'x.csv')
    trader=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=path)
    assert trader.execute_trade(payload(),timestamp=NOW)
    from execution_safety import MarketQuote
    trader.set_quote(IDENTITY,MarketQuote(289.75,289.85,1000,1000,NOW,289.8))
    assert trader.notify_candle_close({'Timestamp':NOW,'Close':289.8})
    trader.shutdown()
    restored=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=path)
    assert restored.candles_since_last_sl==0
    assert restored.execute_trade(payload(),timestamp=NOW) is None
    assert restored.last_rejection=='COOLDOWN'
    restored.shutdown()


def test_capital_protection_is_separate_from_strategy_stop(tmp_path):
    trader=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert trader.execute_trade(payload(),timestamp=NOW)
    position=trader.open_position
    assert position['stop_loss_price']==290
    assert position['emergency_trigger_price']<290
    assert position['protection_basis']=='CAPITAL_LOSS_LIMIT'
    trader.shutdown()


def test_paper_capital_emergency_is_explicit_and_halts(tmp_path):
    from execution_safety import MarketQuote
    trader=PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    assert trader.execute_trade(payload(),timestamp=NOW)
    trader.set_quote(IDENTITY,MarketQuote(284.95,285.05,1000,1000,NOW,285))
    result=trader.check_exit(285,NOW)
    assert result and result['exit_reason']=='Capital Protection Emergency'
    assert trader.is_halted and not trader.has_open_position
    trader.shutdown()


def test_csv_from_another_environment_cannot_be_overwritten(tmp_path):
    path=tmp_path/'foreign.csv'
    original='environment,trade_id,net_pnl\nLIVE,real-trade,10\n'
    path.write_text(original)
    with pytest.raises(SafetyError):
        PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(path))
    assert path.read_text()==original


def test_existing_trade_csv_without_journal_blocks_reset(tmp_path):
    path=tmp_path/'orphan.csv'
    path.write_text('environment,trade_id,net_pnl\nTEST,previous-loss,-150\n')
    with pytest.raises(SafetyError,match='JOURNAL_MISSING'):
        PaperTrader(environment='TEST',clock=lambda:NOW,csv_log_path=str(path))


def test_fill_persistence_failure_halts_and_protects_known_exposure(tmp_path,monkeypatch):
    import sqlite3
    class ProtectionRecorder(PaperExecutionAdapter):
        protected=0
        def protect(self,instrument,side,quantity,stop,now,limit=None):
            self.protected=quantity
            return super().protect(instrument,side,quantity,stop,now,limit)
    adapter=ProtectionRecorder()
    trader=PaperTrader(environment='TEST',adapter=adapter,clock=lambda:NOW,csv_log_path=str(tmp_path/'x.csv'))
    monkeypatch.setattr(trader.journal,'record_fill',lambda fill:(_ for _ in ()).throw(sqlite3.OperationalError('mock disk failure')))
    assert trader.execute_trade(payload(),timestamp=NOW) is None
    assert trader.is_halted
    assert trader.recovered_broker_positions[0]['quantity']==adapter.protected>0
    assert not trader.journal.trades()
    assert trader.execute_trade(payload(),timestamp=NOW) is None
    trader.shutdown()
