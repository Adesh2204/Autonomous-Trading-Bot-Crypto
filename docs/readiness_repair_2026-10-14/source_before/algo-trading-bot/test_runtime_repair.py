"""Regression evidence for the Oct-01 engineering repair; never contacts a broker."""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from premarket_screener import validate_candle_data


def session_frame(day=date(2026, 10, 1), count=247):
    start = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=15)
    return pd.DataFrame({"Timestamp": [start + timedelta(minutes=i) for i in range(count)],
                         "Open": 200., "High": 201., "Low": 199., "Close": 200., "Volume": 1000.})


@pytest.mark.parametrize("defect", ["duplicate", "nan_price", "nan_volume", "missing_timestamp", "nat"])
def test_reject_previously_accepted_malformed_history(defect):
    frame = session_frame()
    if defect == "duplicate":
        frame.loc[1, "Timestamp"] = frame.loc[0, "Timestamp"]
    elif defect == "nan_price":
        frame.loc[1, "Close"] = float("nan")
    elif defect == "nan_volume":
        frame.loc[1, "Volume"] = float("nan")
    elif defect == "missing_timestamp":
        frame = frame.drop(columns="Timestamp")
    else:
        frame.loc[1, "Timestamp"] = pd.NaT
    assert not validate_candle_data(frame, min_candles=15)[0]


def test_reject_wrong_requested_session():
    assert not validate_candle_data(session_frame(), min_candles=15,
                                    session_date=date(2026, 9, 30))[0]


def test_late_start_restores_morning_and_vwap_before_ready():
    from symbol_state import create_isolated_symbol_state
    from session_bootstrap import prepare_session_repair, commit_session_repair
    from historical_data import ist_timestamp
    state = create_isolated_symbol_state("TEST", "1", "TEST-EQ", strict_session=True)
    now = ist_timestamp("2026-10-01 13:22:30")
    requests = []
    def fetch(ctx):
        requests.append(ctx)
        return session_frame()
    assert state.data_status == "BOOTSTRAPPING"
    repairs = prepare_session_repair(state, now, fetch)
    assert state.builder.candle_count == 0
    report = commit_session_repair(state, now, repairs)
    assert state.data_status == "READY"
    assert report["expected_count"] == report["valid_count"] == 247
    assert state.builder.vwap == 200.
    assert str(requests[0].start.time()) == "09:15:00"
    assert str(requests[0].end.time()) == "13:21:00"


def test_partial_first_minute_discarded_and_overlap_replaced():
    from candle_builder import CandleBuilder
    from historical_data import HistoryContext, ist_timestamp
    builder = CandleBuilder(strict_session=True)
    ctx = HistoryContext("NSE", "1", date(2026, 10, 1), end=ist_timestamp("2026-10-01 13:21"),
                         now=ist_timestamp("2026-10-01 13:22:30"), require_complete=True)
    builder.seed_history(session_frame(), ctx)
    builder.on_tick(250., 90., ist_timestamp("2026-10-01 13:22:30"))
    builder.on_tick(200., 10., ist_timestamp("2026-10-01 13:23:01"))
    assert builder.candle_count == 247  # 13:22 was only half observed
    assert builder.recovery_required
    repaired = session_frame(count=248)
    ctx = HistoryContext("NSE", "1", ctx.session_date, end=ist_timestamp("2026-10-01 13:22"),
                         now=ist_timestamp("2026-10-01 13:23:01"), require_complete=True)
    builder.seed_history(repaired, ctx, "RECONCILED")
    builder.seed_history(repaired, ctx, "RECONCILED")
    assert len(builder.df) == 248 and builder.df.Volume.sum() == 248000
    assert builder.vwap == 200.
    builder.on_tick(201., 10., ist_timestamp("2026-10-01 13:24:01"))
    assert builder.first_live_completed_timestamp > builder.historical_last_timestamp


def test_immature_candles_do_not_confirm_volatility_collapse():
    from symbol_state import create_isolated_symbol_state, SymbolExecutionState
    state = create_isolated_symbol_state("TEST", "1", "TEST-EQ")
    state.execution_state = SymbolExecutionState.ACTIVE
    for n in range(1, 15):
        state.current_candle_df = session_frame(count=n)
        state.record_periodic_atr(.1, 200., state.current_candle_df.Timestamp.iloc[-1], completed_count=n)
    assert state.execution_state == SymbolExecutionState.ACTIVE
    assert state.volatility_status == "UNKNOWN"
    assert state.atr_firewall.consecutive_low_readings == 0
    for n in (15, 16):
        state.current_candle_df = session_frame(count=n)
        state.record_periodic_atr(.1, 200., state.current_candle_df.Timestamp.iloc[-1], completed_count=n)
    assert state.volatility_status == "STANDBY"


def test_history_cache_validated_and_shared_between_clients(tmp_path):
    from history_service import HistoryService, SharedHistoryBudget
    from historical_data import HistoryContext, ist_timestamp, OHLCV
    frame = session_frame(count=375)
    class Broker:
        calls = 0
        def getCandleData(self, params):
            self.calls += 1
            return {"status": True, "data": frame[OHLCV].values.tolist()}
    broker = Broker()
    clock = [100.]
    budget = SharedHistoryBudget(tmp_path/'budget.sqlite3', clock=lambda: clock[0],
                                sleep=lambda delay: clock.__setitem__(0,clock[0]+delay), interval=1.5)
    ctx = HistoryContext("NSE", "1", date(2026,10,1), now=ist_timestamp("2026-10-01 16:00"))
    one = HistoryService(broker,tmp_path,budget=budget)
    two = HistoryService(broker,tmp_path,budget=budget)
    assert len(one.fetch(ctx)) == len(two.fetch(ctx)) == 375
    assert broker.calls == 1 and two.metrics['cache_hits'] == 1
    import json
    path = one.cache_path(ctx)
    corrupted = json.loads(path.read_text())
    corrupted['bars'][0]['Close'] = None
    path.write_text(json.dumps(corrupted))
    assert len(two.fetch(ctx)) == 375 and broker.calls == 2


def test_shared_budget_paces_separate_instances_and_priority(tmp_path):
    from history_service import SharedHistoryBudget
    now = [100.]
    kwargs = dict(clock=lambda: now[0],sleep=lambda d: now.__setitem__(0,now[0]+d),
                  interval=1.5,per_minute=2,per_hour=100)
    one = SharedHistoryBudget(tmp_path/'shared.sqlite3', **kwargs)
    two = SharedHistoryBudget(tmp_path/'shared.sqlite3', **kwargs)
    a,b,c = one.acquire(2),two.acquire(2),one.acquire(1)
    assert b-a >= 1.5 and c-a >= 60
    # A queued recovery request takes precedence over optional RVOL.
    with one.connect() as db:
        db.execute('INSERT INTO queue VALUES(?,?,?,?)',('recovery',1,now[0],now[0]+10))
    from premarket_screener import HistoricalDataUnavailable
    with pytest.raises(HistoricalDataUnavailable):
        two.acquire(4,timeout=1.)


@pytest.mark.parametrize('defect,reason', [
    ('future','FUTURE_OR_PARTIAL_CANDLE'),('outside','OUTSIDE_SESSION'),
    ('order','STALE_DATA'),('negative_volume','INVALID_QUOTE'),
    ('infinite','NONFINITE_OHLCV'),('bad_shape','INVALID_QUOTE'),
    ('gap','INCOMPLETE_SESSION_HISTORY'),('misaligned','MISALIGNED_TIMEFRAME')])
def test_strict_history_contract(defect,reason):
    from historical_data import HistoryContext,validate_history,ist_timestamp
    df=session_frame(count=375)
    ctx=HistoryContext('NSE','1',date(2026,10,1),now=ist_timestamp('2026-10-01 16:00'),require_complete=True)
    if defect=='future':
        from dataclasses import replace
        ctx=replace(ctx,now=ist_timestamp('2026-10-01 13:22:30'))
    elif defect=='outside':df.loc[0,'Timestamp']=datetime(2026,10,1,9,14)
    elif defect=='order':df=df.iloc[::-1]
    elif defect=='negative_volume':df.loc[0,'Volume']=-1
    elif defect=='infinite':df.loc[0,'High']=float('inf')
    elif defect=='bad_shape':df.loc[0,'High']=199
    elif defect=='gap':df=df.drop(index=40)
    else:df.loc[0,'Timestamp']+=timedelta(seconds=1)
    result=validate_history(df,ctx)
    assert not result.valid and result.reason==reason


def test_reconnect_only_requests_missing_completed_minutes():
    from symbol_state import create_isolated_symbol_state
    from historical_data import HistoryContext,ist_timestamp
    from session_bootstrap import prepare_session_repair,commit_session_repair
    state=create_isolated_symbol_state('TEST','1','TEST-EQ',strict_session=True)
    before=ist_timestamp('2026-10-01 13:22:30')
    context=HistoryContext('NSE','1',before.date(),end=before.floor('min')-pd.Timedelta(minutes=1),now=before)
    state.builder.seed_history(session_frame(),context)
    state.builder.mark_connection_boundary()
    now=ist_timestamp('2026-10-01 13:25:30')
    requested=[]
    def fetch(ctx):
        requested.append((str(ctx.start.time()),str(ctx.end.time())))
        return session_frame(count=250).iloc[247:].copy()
    repairs=prepare_session_repair(state,now,fetch)
    assert state.builder.recovery_required and state.data_status=='BOOTSTRAPPING'
    commit_session_repair(state,now,repairs)
    assert requested==[('13:22:00','13:24:00')]
    assert state.builder.candle_count==250 and state.builder.df.Volume.sum()==250000
    assert not state.builder.recovery_required and state.data_status=='READY'


def test_session_repair_cannot_accept_missing_bar_or_previous_day():
    from session_bootstrap import prepare_session_repair
    from symbol_state import create_isolated_symbol_state
    from historical_data import ist_timestamp
    state=create_isolated_symbol_state('TEST','1','TEST-EQ',strict_session=True)
    now=ist_timestamp('2026-10-01 13:22:30')
    for frame in (session_frame().drop(index=15),session_frame(day=date(2026,9,30))):
        with pytest.raises(ValueError):prepare_session_repair(state,now,lambda ctx:frame)
        assert state.builder.candle_count==0 and state.builder.recovery_required


def test_rvol_minimum_round_robin_before_extra_sessions(monkeypatch):
    import config,premarket_screener as screen
    class Broker:
        def begin_optional_history(self):pass
    candidates=[dict(symbol=f'TEST{i}',token=str(i),exchange='NSE') for i in range(6)]
    requested=[]
    def fetch(api,symbol,token,exchange,day):
        requested.append((symbol,day))
        frame=session_frame(day,count=375); frame['Volume']=20000
        return frame
    monkeypatch.setattr(screen,'fetch_historical_session_candles',fetch)
    monkeypatch.setattr(config,'OPPORTUNITY_RVOL_SESSIONS',4)
    def initial(c,day):
        frame=session_frame(day,count=375); frame['Volume']=20000
        return frame
    result=screen.run_premarket_screener(Broker(),universe=candidates,session_date=date(2026,9,30),
        data_fetcher=initial,pacing_interval=0,top_n=3)
    symbols=[c.symbol for c in result.watchlist+result.reserves]
    assert [s for s,d in requested[:12]]==symbols*2
    assert all(len(c.volume_profiles)==4 for c in result.watchlist+result.reserves)


def test_standby_signal_and_all_blockers_visible_no_order(tmp_path,monkeypatch):
    from test_orchestration_safety_v6 import orchestration
    from test_safety_v6 import NOW
    from symbol_state import SymbolExecutionState
    stream,state=orchestration(tmp_path,monkeypatch)
    state.execution_state=SymbolExecutionState.STANDBY
    state.current_candle_df['ATR_14']=.1
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    row=next(iter(stream.telemetry.observations.values()))
    assert row['signal_generated'] and row['side']=='BUY' and not row['executable']
    assert {'VOLATILITY_STANDBY','ATR_BELOW_LIVE_MINIMUM'}<=set(row['blocking_reasons'])
    assert stream.telemetry.summary()['counts']['potential_signals']==1
    assert stream.paper_trader.journal.budget()[1]==0
    assert not stream.paper_trader.journal.fills()
    assert stream.paper_trader.journal.db.execute("SELECT COUNT(*) FROM events WHERE kind='OPPORTUNITY_QUOTE'").fetchone()[0]==1
    stream.paper_trader.shutdown()


def test_session_block_does_not_prevent_existing_position_exit(tmp_path,monkeypatch):
    from test_orchestration_safety_v6 import orchestration
    from test_safety_v6 import NOW,payload,quote
    stream,state=orchestration(tmp_path,monkeypatch)
    assert stream.paper_trader.execute_trade(payload(),timestamp=NOW)
    state.builder.recovery_required=True
    stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
    assert stream.paper_trader.has_open_position
    # The independent quote-driven protection path remains available during repair.
    stream.paper_trader.set_quote(state.instrument,quote())
    assert stream.paper_trader.close_position(300,NOW,'TEST_EXIT_DURING_RECOVERY')
    assert not stream.paper_trader.has_open_position
    stream.paper_trader.shutdown()


def test_economic_haircut_cannot_rewrite_paper_fill_or_signal_levels(tmp_path,monkeypatch):
    import config
    from test_safety_v6 import NOW,IDENTITY,payload,quote
    from safety_test_support import paper_trader
    from execution_adapters import PaperExecutionAdapter
    adapter=PaperExecutionAdapter()
    original=adapter.execute(IDENTITY,'BUY',1,quote(),NOW).price
    monkeypatch.setattr(config,'SLIPPAGE_HAIRCUT_PCT',.0015)
    assert adapter.execute(IDENTITY,'BUY',1,quote(),NOW).price==original
    trader=paper_trader(tmp_path)
    assert trader.execute_trade(payload(),timestamp=NOW)
    position=trader.open_position
    assert position['signal_price']==300.
    assert position['stop_loss_price']==290. and position['target_price']==320.
    assert position['average_entry_price']==original
    assert position['requested_order_price']==original
    import json
    rows=trader.journal.db.execute("SELECT payload FROM events WHERE kind='ECONOMICALLY_VALIDATED'").fetchall()
    model=json.loads(rows[0][0])['economics']['estimated_entry']
    assert model>original>position['signal_price']
    assert trader.close_position(300,NOW,'TEST_EXIT')
    closed=trader.journal.trades()[0]
    fills=trader.journal.fills()
    gross=(fills[-1]['price']-fills[0]['price'])*fills[0]['quantity']
    assert closed['gross_pnl']==round(gross,2)
    assert closed['net_pnl']==round(gross-sum(f['fees'] for f in fills),2)
    trader.shutdown()


def test_regular_lock_rejects_second_process_and_releases(tmp_path):
    from run_context import RegularInstanceLock
    import subprocess,sys
    path=tmp_path/'run.lock'
    code="from run_context import RegularInstanceLock; import sys; lock=RegularInstanceLock(sys.argv[1]); lock.__enter__()"
    from pathlib import Path
    with RegularInstanceLock(path):
        proc=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(__file__).parent,capture_output=True,text=True)
        assert proc.returncode!=0 and 'REGULAR_INSTANCE_ALREADY_RUNNING' in proc.stderr
    with RegularInstanceLock(path):pass


def test_reuse_authenticated_session_without_second_login(monkeypatch):
    import live_stream
    stream=live_stream.AngelOneLiveStream.__new__(live_stream.AngelOneLiveStream)
    class Session:
        access_token='SYNTHETIC_AUTH_TOKEN'
        feed_token='SYNTHETIC_FEED_TOKEN'
    stream.angel_session=Session()
    monkeypatch.setattr(live_stream,'SmartConnect',lambda **kw:pytest.fail('Duplicate login forbidden'))
    stream.login()
    assert stream.smart_api is stream.angel_session


def test_production_strategy_hash_and_mode_are_frozen():
    import hashlib,config
    from pathlib import Path
    assert hashlib.sha256((Path(__file__).parent/'signal_brain.py').read_bytes()).hexdigest()==\
        'bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83'
    assert config.LIVE_MODE is False and config.LIVE_VALIDATION_APPROVED is False
    assert config.INTRADAY_ATR_MIN_PCT==.004 and config.MIN_CANDLES_BEFORE_TRADE==15
    assert config.MAX_OPEN_POSITIONS==1


def test_reserve_promotion_requires_distinct_healthy_candles_and_preserves_budget(tmp_path,monkeypatch):
    import config
    import signal_brain
    from copy import copy
    from dataclasses import replace
    from test_orchestration_safety_v6 import orchestration
    from test_safety_v6 import NOW
    from symbol_state import SymbolExecutionState
    from runtime_observation import OpportunityTelemetry
    stream,primary=orchestration(tmp_path,monkeypatch)
    stream.telemetry=OpportunityTelemetry()
    primary.execution_state=SymbolExecutionState.STANDBY
    primary.current_candle_df['ATR_14']=.1
    reserve=copy(primary)
    reserve.token='RESERVE'; reserve.symbol='RESERVE'; reserve.watchlist_role='RESERVE'; reserve.rank=2
    reserve.instrument=replace(primary.instrument,token=reserve.token,symbol=reserve.symbol,trading_symbol='RESERVE-EQ')
    reserve.execution_state=SymbolExecutionState.ACTIVE
    reserve.current_candle_df=primary.current_candle_df.copy()
    reserve.current_candle_df['ATR_14']=5.
    stream.active_symbols[reserve.token]=reserve
    monkeypatch.setattr(config,'SCREEN_TOP_N',1)
    monkeypatch.setattr(signal_brain,'generate_vwap_signal',lambda frame:frame)
    monkeypatch.setattr(signal_brain,'detect_daily_bias',lambda frame:'NEUTRAL')
    before=stream.paper_trader.journal.budget()
    stream._promote_reserves(NOW)
    stream._promote_reserves(NOW)
    assert reserve.watchlist_role=='RESERVE' and reserve.promotion_confirmations==1
    later=NOW+timedelta(minutes=1)
    reserve.current_candle_df['Timestamp']+=timedelta(minutes=1)
    reserve.quote=replace(reserve.quote,timestamp=later)
    stream._promote_reserves(later)
    assert reserve.watchlist_role=='PRIMARY' and primary.watchlist_role=='RESERVE'
    assert stream.paper_trader.journal.budget()==before
    assert len(stream.telemetry.promotions)==1
    stream._promote_reserves(later)
    assert len(stream.telemetry.promotions)==1
    stream.paper_trader.shutdown()


def test_research_policy_does_not_modify_production_thresholds():
    import config
    from research_policy import VolatilityPolicy,ResearchPolicyState
    original=config.INTRADAY_ATR_MIN_PCT
    with pytest.raises(ValueError,match='DISTINCT_NAME'):
        VolatilityPolicy(live_atr_floor=.003)
    study=VolatilityPolicy(name='EXPLICIT_TEST_VARIANT',live_atr_floor=.003,standby_threshold=.002,recovery_threshold=.003)
    assert ResearchPolicyState(study).step(.7,200,15)==[]
    assert 'ATR_BELOW_LIVE_MINIMUM' in ResearchPolicyState(VolatilityPolicy()).step(.7,200,15)
    assert config.INTRADAY_ATR_MIN_PCT==original


def test_research_development_held_out_date_overlap_rejected(tmp_path):
    from research_harness import evaluate_manifest
    manifest={'sessions':[{'date':'2026-10-01','split':split} for split in ('DEVELOPMENT','HELD_OUT')]}
    with pytest.raises(ValueError,match='OVERLAP'):evaluate_manifest(manifest,tmp_path)


def test_oct01_recorded_candles_remain_zero_eligible_entries():
    from pathlib import Path
    from research_policy import VolatilityPolicy,ResearchPolicyState
    from signal_brain import generate_vwap_signal,detect_daily_bias
    from market_schedule import get_market_schedule
    total=0; eligible=0
    for symbol in ('RSYSTEMS','RITES','ELEVATE'):
        frame=pd.read_csv(Path(__file__).resolve().parent.parent/'docs'/f'logged_candles_2026-10-01_{symbol}.csv')
        frame.Timestamp=pd.to_datetime(frame.Timestamp)
        result=generate_vwap_signal(frame)
        policy=ResearchPolicyState(VolatilityPolicy())
        for i,row in result.iterrows():
            reasons=policy.step(float(row.ATR_14),float(row.Close),i+1)
            long=bool(row.Buy_Signal) or bool(row.Breakout_Signal)
            short=bool(row.Sell_Signal) or bool(row.Breakdown_Sell_Signal)
            bias=detect_daily_bias(result.iloc[:i+1])
            long=long and bias!='SHORT_BIAS';short=short and bias!='LONG_BIAS'
            if (long or short) and get_market_schedule('NSE').can_enter_new_positions(row.Timestamp+pd.Timedelta(minutes=1)):
                total+=1
                eligible+=int(not reasons)
    assert total==10 and eligible==0


def test_partial_candle_and_prior_day_never_pollute_new_session_vwap():
    from candle_builder import CandleBuilder
    from historical_data import HistoryContext,ist_timestamp
    builder=CandleBuilder(strict_session=True)
    old=session_frame(day=date(2026,9,30),count=375)
    old[['Open','High','Low','Close']]+=100
    ctx=HistoryContext('NSE','1',date(2026,9,30),now=ist_timestamp('2026-10-01 13:22:30'))
    builder.seed_history(old,ctx)
    newctx=HistoryContext('NSE','1',date(2026,10,1),end=ist_timestamp('2026-10-01 13:21'),now=ctx.now)
    builder.seed_history(session_frame(),newctx)
    assert len(builder.df)==247 and builder.vwap==200.
    builder.on_tick(100.,100.,ist_timestamp('2026-09-30 14:00'))
    assert len(builder.df)==247 and builder.vwap==200.


def test_shadow_excursions_are_separate_from_fill_journal(tmp_path,monkeypatch):
    from test_orchestration_safety_v6 import orchestration
    from test_safety_v6 import NOW
    from runtime_observation import observe_signal
    from shadow_diagnostics import ShadowDiagnostics
    import live_stream
    stream,state=orchestration(tmp_path,monkeypatch)
    state.current_candle_df['ATR_14']=.1
    obs=observe_signal(state,stream.paper_trader,stream.schedule,NOW,
                       live_stream.generate_vwap_signal,live_stream.detect_daily_bias)
    shadow=ShadowDiagnostics(tmp_path/'run')
    shadow.record(obs)
    state.builder.df=pd.DataFrame([{'Timestamp':NOW,'High':350.,'Low':280.}])
    import json
    report=json.loads(shadow.finish(stream.active_symbols).read_text())
    assert report['production_pnl_credited']==0 and len(report['outcomes'])==1
    assert not stream.paper_trader.journal.trades() and not stream.paper_trader.journal.fills()
    stream.paper_trader.shutdown()


def test_history_service_backoff_and_invalid_responses_never_cached(tmp_path):
    from history_service import HistoryService,SharedHistoryBudget
    from historical_data import HistoryContext,ist_timestamp,OHLCV
    clock=[100.];calls=[]
    class Broker:
        invalid=False
        def getCandleData(self,params):
            calls.append(clock[0])
            if len(calls)==1:return {'status':False,'errorcode':'AB1021','message':'rate limit'}
            frame=session_frame(count=375)
            if self.invalid:frame.loc[5,'Close']=float('nan')
            return {'status':True,'data':frame[OHLCV].values.tolist()}
    broker=Broker()
    budget=SharedHistoryBudget(tmp_path/'budget',clock=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n),interval=1.5)
    service=HistoryService(broker,tmp_path,budget=budget,clock=lambda:clock[0])
    ctx=HistoryContext('NSE','1',date(2026,10,1),now=ist_timestamp('2026-10-01 16:00'))
    assert len(service.fetch(ctx))==375
    assert calls[1]-calls[0]>=5 and service.rate_limit_count==1
    from dataclasses import replace
    broker.invalid=True
    badctx=replace(ctx,token='2')
    assert service.fetch(badctx) is None and not service.cache_path(badctx).exists()
    assert service.metrics['validation_failures']==1


def test_empty_provider_session_has_no_retry_or_cache(tmp_path):
    from history_service import HistoryService,SharedHistoryBudget
    from historical_data import HistoryContext,ist_timestamp
    class Empty:
        def getCandleData(self,params):return {'status':True,'data':[]}
    service=HistoryService(Empty(),tmp_path,budget=SharedHistoryBudget(tmp_path/'budget',interval=0))
    ctx=HistoryContext('NSE','1',date(2026,10,1),now=ist_timestamp('2026-10-01 16:00'))
    assert service.fetch(ctx) is None
    assert service.calls==1 and not service.cache_path(ctx).exists()


def test_minimum_rvol_requires_unique_prior_sessions():
    from opportunity_engine import same_time_rvol
    profile={'session_date':'2026-09-30','cumulative_volume':{'09:16:00':1000}}
    assert same_time_rvol(1000,datetime(2026,10,1,10).time(),[profile]*3,date(2026,10,1)) is None


def test_incomplete_cumulative_volume_profile_is_unknown():
    from opportunity_engine import build_volume_profile
    frame=session_frame(day=date(2026,9,30),count=375)
    assert build_volume_profile(frame,date(2026,9,30)) is not None
    assert build_volume_profile(frame.drop(index=40),date(2026,9,30)) is None


def test_manifest_runs_isolated_multisession_research(tmp_path):
    from research_harness import evaluate_manifest
    import config
    cases=[]
    for day,split in ((date(2026,9,29),'DEVELOPMENT'),(date(2026,9,30),'HELD_OUT')):
        path=tmp_path/f'{day}.csv';session_frame(day,20).to_csv(path,index=False)
        cases.append({'date':str(day),'split':split,'path':str(path),'symbol':'FIXTURE','token':'1',
                      'tick_size':.05,'provenance':'SYNTHETIC_ENGINEERING_FIXTURE_NOT_PROFIT_EVIDENCE','regime':'SYNTHETIC_FLAT'})
    result=evaluate_manifest({'sessions':cases},tmp_path/'research')
    assert result['research_only'] and not result['live_eligible']
    assert {r['split'] for r in result['results']}=={'DEVELOPMENT','HELD_OUT'}
    assert all(r['metrics']['net_pnl']==0 for r in result['results'])
    assert config.INTRADAY_ATR_MIN_PCT==.004


@pytest.mark.parametrize('cases', [[], [
    {'date':'2026-09-30','split':'HELD_OUT','regime':'SYNTHETIC_FLAT'}]])
def test_research_collection_reports_missing_split_without_fabricating_results(tmp_path, cases):
    import json, runpy
    from pathlib import Path
    script=Path(__file__).resolve().parents[1]/'scripts'/'runtime_repair_research_check.py'
    functions=runpy.run_path(str(script))
    manifest={'sessions':cases}
    result=functions['evaluate_collected_manifest'](manifest,tmp_path)
    assert result['status']=='BLOCKED_INCOMPLETE_RESEARCH_COVERAGE'
    assert result['results']==[] and not result['live_eligible']
    summary={'excluded_cases':36}
    functions['update_evaluation_summary'](summary,manifest,result,tmp_path)
    assert summary['accepted_development_cases']==0 and summary['excluded_cases']==36
    assert json.loads((tmp_path/'comparison.json').read_text())==result
    assert manifest['sessions']==cases


def test_readiness_and_funnel_report_written_for_no_trade(tmp_path,monkeypatch):
    import config,json
    from test_orchestration_safety_v6 import orchestration
    from test_safety_v6 import NOW
    from run_context import RunContext
    from runtime_observation import OpportunityTelemetry
    stream,state=orchestration(tmp_path,monkeypatch)
    stream.telemetry=OpportunityTelemetry('REPORT_TEST')
    state.current_candle_df['ATR_14']=.1
    state.builder.df=state.current_candle_df.copy()
    monkeypatch.setattr(config,'EXECUTION_ENVIRONMENT','TEST')
    with RunContext('REGULAR',root=tmp_path/'runs') as context:
        stream.run_context=context
        context.stream=stream
        context.start_stage('STREAM_HEALTHY')
        stream._evaluate_watchlist_orchestrator(evaluation_time=NOW)
        readiness=context.write_readiness(stream,NOW)
        assert readiness['market_ready'] and not readiness['entry_allowed']
        report=context.write_session_summary(stream)
        assert report['result']=='NO_TRADE' and report['net_pnl']==0
        assert report['opportunity_funnel']['counts']['potential_signals']==1
        assert report['opportunity_funnel']['orders']==0
    assert json.loads((context.directory/'identity.json').read_text())['completed_at']
    stream.paper_trader.shutdown()


def test_restored_position_keeps_subscription_with_new_watchlist(monkeypatch):
    import live_stream,config
    from types import SimpleNamespace
    from test_phase5_multisymbol import _make_candidate_diagnostic
    from instrument_registry import InstrumentRegistry
    from execution_safety import InstrumentIdentity
    from historical_data import ist_timestamp
    now=ist_timestamp()
    candidates=[_make_candidate_diagnostic(f'SYM{i}',str(100+i),.6) for i in range(6)]
    registry=InstrumentRegistry([{'exch_seg':'NSE','symbol':c.trading_symbol,'token':c.token,'tick_size':'5','lotsize':'1'}
                                for c in candidates],now,[c.symbol for c in candidates])
    held=InstrumentIdentity('HELD','NSE','999','HELD-EQ','EQ',.05,1,'CASH',now)
    fake=SimpleNamespace(has_open_position=True,session_id='RECOVERY_FIXTURE',
                         open_position={'token':'999','instrument':held})
    monkeypatch.setattr(live_stream,'PaperTrader',lambda **kwargs:fake)
    monkeypatch.setattr(live_stream.AngelOneLiveStream,'_install_signal_handlers',lambda self:None)
    monkeypatch.setattr(config,'LIVE_MODE',False)
    for key in ('BROKER_API_KEY','BROKER_CLIENT_ID','BROKER_PIN','BROKER_TOTP_SECRET'):
        monkeypatch.setenv(key,'FIXTURE')
    stream=live_stream.AngelOneLiveStream(watchlist=candidates[:3],reserves=candidates[3:],registry=registry)
    assert len(stream.active_symbols)==6
    assert stream.active_symbols['999'].watchlist_role=='PROTECTION_ONLY'
    assert all(c.token in stream.active_symbols for c in candidates[:3])


def test_shared_history_budget_serializes_independent_processes(tmp_path):
    import subprocess,sys,json
    from pathlib import Path
    from history_service import SharedHistoryBudget
    path=tmp_path/'process-budget.sqlite3'
    SharedHistoryBudget(path,interval=.05)
    code=("from history_service import SharedHistoryBudget; import sys,json; "
          "b=SharedHistoryBudget(sys.argv[1],interval=.05); "
          "print(json.dumps([b.acquire(2),b.acquire(2)]))")
    processes=[subprocess.Popen([sys.executable,'-c',code,str(path)],cwd=Path(__file__).parent,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    times=[]
    for process in processes:
        out,err=process.communicate(timeout=10)
        assert process.returncode==0,err
        times.extend(json.loads(out))
    ordered=sorted(times)
    assert all(b-a>=.049 for a,b in zip(ordered,ordered[1:]))
