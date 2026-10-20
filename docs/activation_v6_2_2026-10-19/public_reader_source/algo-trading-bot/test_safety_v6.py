"""Financial regression tests; all broker interactions are deterministic mocks."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from execution_safety import InstrumentIdentity, MarketQuote, FeeModel, estimate_trade_economics, solve_quantity
from safety_journal import SafetyJournal
from execution_engine import PaperTrader

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo('Asia/Kolkata'))
IDENTITY = InstrumentIdentity('JIOFIN', 'NSE', '18143', 'JIOFIN-EQ', 'EQ', .05, 1, 'CASH', NOW)

def quote(price=300.0, **kwargs):
    return MarketQuote(price-.05, price+.05, 1000, 1000, NOW, price, **kwargs)

@pytest.fixture
def trader(tmp_path):
    t = PaperTrader(csv_log_path=str(tmp_path/'test.csv'), environment='TEST', clock=lambda: NOW)
    yield t
    t.shutdown()

def payload(atr=5., close=300.):
    return {'symbol':'JIOFIN', 'VWAP':300., 'Close':close, 'ATR_14':atr,
            'instrument':IDENTITY, 'quote':quote(close), 'signal_id':str(close)+str(atr), 'signal_type':'PULLBACK_LONG'}

def test_risk_122_is_reduced_or_rejected(trader):
    ticket = trader.execute_trade(payload(), timestamp=NOW)
    assert ticket is None or ticket['estimated_net_loss'] <= 100
    assert ticket is None or ticket['quantity'] < 11

def test_wrong_token_never_routes(trader):
    p=payload(); p['token']='4907'
    assert trader.execute_trade(p, timestamp=NOW) is None
    assert trader.last_rejection == 'INSTRUMENT_IDENTITY_MISMATCH'

def test_paper_entry_cannot_fill_old_vwap(trader):
    p=payload(atr=4., close=303.)
    ticket=trader.execute_trade(p, timestamp=NOW)
    if ticket is None:
        assert trader.last_rejection in {'NO_ECONOMICALLY_VALID_QUANTITY','FRICTION_FAILED'}
    else:
        assert ticket['actual_entry_fill'] >= 303.

def test_stop_gap_uses_executable_price(trader):
    ticket=trader.execute_trade(payload(), timestamp=NOW)
    assert ticket
    trader.set_quote(IDENTITY, MarketQuote(284.95,285.05,1000,1000,NOW,285.))
    result=trader.notify_candle_close({'Timestamp':NOW,'Close':285.})
    assert result['actual_exit_price'] <= 285.

def test_remaining_daily_budget_does_not_reset_after_profit(tmp_path):
    j=SafetyJournal(tmp_path/'journal.db','TEST')
    j.start_day(NOW.date())
    j.reserve('a',70); j.finish('a',-70)
    j.reserve('b',50); j.finish('b',250)
    assert j.remaining(200) == 130
    j.close()

def test_daily_40_cannot_reserve_70(tmp_path):
    j=SafetyJournal(tmp_path/'journal.db','TEST'); j.start_day(NOW.date())
    j.reserve('old',160); j.finish('old',-160)
    assert not j.can_reserve(70,200)
    j.close()

def test_one_position_and_scale_in_blocked(trader):
    assert trader.execute_trade(payload(),timestamp=NOW)
    assert trader.execute_trade(payload(),timestamp=NOW) is None
    assert trader.last_rejection == 'POSITION_ALREADY_OPEN'
    assert trader.open_position['current_tranches'] == 1

def test_quantity_checks_all_integer_candidates():
    result=solve_quantity('BUY',300.,290.,320.,10000.,100.,200.,1.2,.0005,1)
    assert result is not None
    assert result.net_stop_loss <= 100
    assert result.cash_required <= 10000
    assert result.net_rr >= 1.2

def test_long_short_fees_are_sided_correctly():
    f=FeeModel()
    assert f.leg('BUY',300.,10)['stt'] == 0
    assert f.leg('SELL',300.,10)['stamp_duty'] == 0
    e=estimate_trade_economics('SELL',10,300.,310.,280.,0.)
    assert e.gross_target_profit == 200
    assert e.gross_stop_loss == 100

def test_duplicate_fill_idempotent(tmp_path):
    j=SafetyJournal(tmp_path/'j.db','TEST'); j.start_day(NOW.date())
    fill={'order_id':'o','fill_id':'f','quantity':8,'price':300.,'fees':6.}
    assert j.record_fill(fill)
    assert not j.record_fill(fill)
    assert len(j.fills()) == 1
    j.close()

def test_restart_retains_budget_and_open_position(tmp_path):
    path=tmp_path/'j.db'; j=SafetyJournal(path,'TEST'); j.start_day(NOW.date())
    j.reserve('a',70); j.save_position({'trade_id':'a','quantity':8})
    j.close(); k=SafetyJournal(path,'TEST'); k.start_day(NOW.date())
    assert k.remaining(200) == 130
    assert k.load_position()['quantity'] == 8
    k.close()

def test_single_tranche_initialization_no_crash(trader):
    assert trader.max_tranches == 1
    assert trader.tranche_capitals == [10000.]

def test_cutoff_blocks_entry(trader):
    after=NOW.replace(hour=14,minute=30)
    assert trader.execute_trade(payload(),timestamp=after) is None
    assert trader.last_rejection == 'ENTRY_CUTOFF_REACHED'

def test_stale_quote_blocks(trader):
    p=payload(); p['quote']=MarketQuote(299.95,300.05,100,100,NOW-timedelta(seconds=20),300.)
    assert trader.execute_trade(p,timestamp=NOW) is None
    assert trader.last_rejection == 'QUOTE_STALE'

def test_no_identity_blocks(trader):
    p=payload(); del p['instrument']
    assert trader.execute_trade(p,timestamp=NOW) is None
    assert trader.last_rejection == 'INSTRUMENT_IDENTITY_MISMATCH'

def test_environment_cannot_reuse_ledger(tmp_path):
    path=tmp_path/'j.db'; SafetyJournal(path,'TEST').close()
    with pytest.raises(ValueError,match='ENVIRONMENT'):
        SafetyJournal(path,'LIVE')

def test_frozen_strategy_bytes():
    import hashlib
    assert hashlib.sha256((Path(__file__).parent/'signal_brain.py').read_bytes()).hexdigest() == 'bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83'
