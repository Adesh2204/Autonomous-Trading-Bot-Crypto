"""Offline engineering examples. No broker authentication or production journal.

Run from the repository root: .venv/bin/python scripts/runtime_repair_evidence.py
Uses declared synthetic fixtures and the user's recorded Oct-01 OHLCV separately.
"""
from pathlib import Path
import json
import sys
import tempfile
from dataclasses import replace
from datetime import date
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from test_runtime_repair import session_frame
from historical_data import HistoryContext,ist_timestamp,OHLCV
from session_bootstrap import prepare_session_repair,commit_session_repair
from symbol_state import create_isolated_symbol_state,SymbolExecutionState
from history_service import HistoryService,SharedHistoryBudget
from execution_safety import InstrumentIdentity,MarketQuote,estimate_trade_economics
from execution_adapters import PaperExecutionAdapter
from signal_brain import generate_vwap_signal,detect_daily_bias
from runtime_observation import OpportunityTelemetry,observe_signal
from market_schedule import get_market_schedule
from execution_engine import PaperTrader


def main():
    now=ist_timestamp('2026-10-01 13:22:30')
    state=create_isolated_symbol_state('FIXTURE','FIXTURE','FIXTURE-EQ',strict_session=True)
    history=session_frame()
    requests=[]
    def fetch(context):
        requests.append({'start':str(context.start),'end':str(context.end)})
        return history
    before=state.data_status
    pending=prepare_session_repair(state,now,fetch)
    validation=commit_session_repair(state,now,pending)
    report={'bootstrap':{'basis':'SYNTHETIC_ENGINEERING_FIXTURE','started_at':str(now),
        'before':before,'after':state.data_status,'requests':requests,'validation':validation,
        'restored_bars':state.builder.candle_count,'session_vwap':state.builder.vwap,'orders':0}}
    with tempfile.TemporaryDirectory(prefix='runtime-evidence-') as directory:
        directory=Path(directory)
        calls=[]
        clock=[100.]
        budget=SharedHistoryBudget(directory/'budget.sqlite3',clock=lambda:clock[0],
                                  sleep=lambda delay:clock.__setitem__(0,clock[0]+delay),interval=1.5)
        class FixtureBroker:
            def getCandleData(self,params):
                calls.append(dict(params))
                day=date.fromisoformat(params['fromdate'][:10])
                return {'status':True,'data':session_frame(day,375)[OHLCV].values.tolist()}
        one=HistoryService(FixtureBroker(),directory/'cache',budget=budget)
        two=HistoryService(FixtureBroker(),directory/'cache',budget=budget)
        contexts=[HistoryContext('NSE',str(token),date(2026,9,day),now=now) for day in (28,29,30) for token in (1,2,3)]
        for c in contexts:one.fetch(c)
        first=len(calls)
        for c in contexts:two.fetch(c)
        report['cache']={'basis':'SYNTHETIC_TWO_CLIENT_FIXTURE','unique_token_day_datasets':len(contexts),
                         'cold_requests':first,'warm_additional_requests':len(calls)-first,
                         'first_client':dict(one.metrics),'second_client':dict(two.metrics)}
        # Observe an actual recorded core pattern; historical order-book data was
        # not supplied, so this quote is explicitly a hypothetical engineering input.
        raw=pd.read_csv(ROOT/'docs'/'logged_candles_2026-10-01_RSYSTEMS.csv')
        raw.Timestamp=pd.to_datetime(raw.Timestamp)
        enriched=generate_vwap_signal(raw)
        index=next(i for i,row in enriched.iterrows() if i>=14 and bool(row.Buy_Signal or row.Breakout_Signal)
                   and detect_daily_bias(enriched.iloc[:i+1])!='SHORT_BIAS')
        observed_at=raw.iloc[index].Timestamp+pd.Timedelta(minutes=1)
        trader=PaperTrader(environment='TEST',clock=lambda:observed_at,csv_log_path=str(directory/'trades.csv'))
        sample=create_isolated_symbol_state('RSYSTEMS','13414','RSYSTEMS-EQ')
        sample.instrument=InstrumentIdentity('RSYSTEMS','NSE','13414','RSYSTEMS-EQ','EQ',.01,1,'CASH',observed_at)
        sample.current_candle_df=raw.iloc[:index+1].copy()
        sample.execution_state=SymbolExecutionState.STANDBY
        from feed_integrity import FeedHealthState
        sample.feed_monitor.state=FeedHealthState.HEALTHY
        last=float(raw.iloc[index].Close)
        sample.quote=MarketQuote(last-.05,last+.05,1000,1000,observed_at,last)
        sample.last_depth_available=True;sample.last_spread_pct=.04
        observation=observe_signal(sample,trader,get_market_schedule('NSE'),observed_at,generate_vwap_signal,detect_daily_bias)
        observation.quote['source']='HYPOTHETICAL_TEST_QUOTE; NOT OCT01 OBSERVED DEPTH'
        telemetry=OpportunityTelemetry('OFFLINE_ENGINEERING_EVIDENCE')
        telemetry.record(observation,trader)
        report['opportunity']={'input_candles':'USER_OCT01_LOG','quote_basis':'HYPOTHETICAL_TEST_QUOTE',
                               'observation':observation.report(),'funnel':telemetry.summary(),
                               'ledger_net_pnl':trader.journal.report()['net_pnl'],'fills':len(trader.journal.fills())}
        trader.shutdown()
        identity=InstrumentIdentity('FIXTURE','NSE','1','FIXTURE-EQ','EQ',.05,1,'CASH',now)
        quote=MarketQuote(299.95,300.05,1000,1000,now,300.)
        model=estimate_trade_economics('BUY',1,quote.ask,290.,320.,slippage_allowance=.0015,tick_size=.05)
        fill=PaperExecutionAdapter().execute(identity,'BUY',1,quote,now)
        report['accounting']={'basis':'SYNTHETIC_PRICE_SEPARATION_EXAMPLE; regression tests also reconcile the fill ledger',
            'strategy_reference':300.,'strategy_stop':290.,'strategy_target':320.,'economic_haircut':.0015,
            'economic_model_entry':model.estimated_entry,'paper_fill_slippage':.0005,'paper_fill_price':fill.price,
            'production_journal_writes':0}
    path=ROOT/'docs'/'runtime_repair_engineering_evidence.json'
    path.write_text(json.dumps(report,indent=2,default=str,allow_nan=False)+'\n')
    print(path)
    print(json.dumps({'restored_bars':report['bootstrap']['restored_bars'],
                      'cache_cold_requests':report['cache']['cold_requests'],
                      'cache_warm_requests':report['cache']['warm_additional_requests'],
                      'signal':report['opportunity']['observation']['side'],
                      'executable':report['opportunity']['observation']['executable'],
                      'prices':report['accounting']},indent=2))


if __name__=='__main__':
    main()
