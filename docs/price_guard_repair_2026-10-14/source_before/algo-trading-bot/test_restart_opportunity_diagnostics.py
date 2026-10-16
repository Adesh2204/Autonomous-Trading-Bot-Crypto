"""Offline recovery/funnel evidence; synthetic fixtures, no exchange HTTP writes."""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal as D
import hashlib,json,os,signal,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
import pytest

from test_live_exchange_execution import live,NOW,TEAM
from test_crypto_paper_infrastructure import POLICY,FEES,bar,signal_scan,universe,make_bot
from exchange.base_exchange import ExchangeError,Fill
from exchange.live_recovery import LiveAccountRecovery,AccountReconciler
from exchange.startup_recovery import StartupState
from exchange.execution_journal import ExecutionJournal,fingerprint
from exchange.order_lifecycle import OrderRequest
from crypto_strategy_state import CryptoStrategyState
from live_execution_session import LiveExecutionSession
from risk.portfolio_risk import PortfolioRisk
from market_regime_scanner import ScannerPolicy,ScanResult,MarketDiagnostic
from opportunity_funnel import OpportunityFunnel,STAGES,RejectionReason,reason_code
from counterfactual_research import CounterfactualResearch,ResearchVariant,BASELINE_POLICY


def session(live):
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    live.executor.recovery=recovery
    s=LiveExecutionSession(live.market,SimpleNamespace(),live.executor,PortfolioRisk(POLICY,FEES))
    s.attach_account_stream(SimpleNamespace(executor=live.executor,healthy=True))
    return s


def seed(live,quantity='.2',*,stop='95',target='105',cursor=NOW-60000):
    r=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    m=CryptoStrategyState('par:BTC',lambda *args:None,clock_ms=live.client.clock_ms)
    m.last_candle_ms=cursor
    if D(quantity):
        m.confirm_entry(SimpleNamespace(side='BUY' if D(quantity)>0 else 'SELL',quantity=abs(D(quantity)),price=D(100)),
                        SimpleNamespace(stop=D(stop),target=D(target)))
    r.managers[m.symbol]=m
    live.fixture.position(quantity)
    r.persist_manager(m,candidate_id='seed')
    assert r.recover().ready
    return r,m


@pytest.mark.parametrize('quantity',['0','.2','-.2'])
def test_restart_known_flat_long_short_exchange_authority(live,quantity):
    seed(live,quantity,stop='95' if D(quantity)>=0 else '105',target='105' if D(quantity)>=0 else '95')
    s=session(live)
    assert s.execution.entries_paused
    assert s.startup().ready
    assert s.startup_recovery.state==StartupState.READY
    assert s.recovery.state.quantities.get('par:BTC',D(0))==D(quantity)
    assert s.startup_recovery.post_stream_verified
    assert s.startup_recovery.report()['position_match']


@pytest.mark.parametrize('local,actual,reason',[('0','.2','MISSING_MANAGEMENT_HISTORY'),('.2','0','UNEXPLAINED_FLAT_POSITION'),
    ('.2','.3','MANAGEMENT_QUANTITY_MISMATCH'),('.2','-.2','MANAGEMENT_QUANTITY_MISMATCH')])
def test_mismatch_adopts_actual_and_never_unlocks(live,local,actual,reason):
    seed(live,local)
    live.fixture.position(actual)
    s=session(live)
    report=s.startup()
    assert not report.ready and any(reason in r for r in report.reasons)
    assert s.recovery.state.quantities.get('par:BTC',D(0))==D(actual)
    assert s.execution.entries_paused and s.startup_recovery.state==StartupState.POSITION_REVIEW
    assert not live.transport.signed_payloads


def test_missing_checkpoint_open_position_is_never_flat(live):
    live.fixture.position('.2')
    s=session(live)
    assert not s.startup().ready
    report=s.startup_recovery.report()
    assert report['exchange_positions']==1 and report['strategy_state']!='RESTORED'
    assert report['entry_status']=='ENTRY_PAUSED'


@pytest.mark.parametrize('clean,expected',[(False,'UNCLEAN'),(True,'CLEAN')])
def test_clean_and_unclean_shutdown_markers(live,clean,expected):
    s=session(live);s.startup()
    if clean:s.startup_recovery.clean_shutdown()
    again=session(live)
    assert again.startup_recovery.previous_shutdown==expected
    assert again.execution.entries_paused
    assert live.journal.control('recovery_lifecycle')['clean'] is False


def test_unknown_first_shutdown_and_readonly_position_unknown(live):
    s=session(live)
    assert s.startup_recovery.previous_shutdown=='UNKNOWN'
    assert s.startup_recovery.report()['exchange_positions'] is None
    assert s.startup_recovery.report()['position_match'] is None


def test_corrupted_checkpoint_retains_actual_account_and_fails_closed(live):
    seed(live)
    live.journal.db.execute("UPDATE recovery_snapshots SET data='{}' WHERE seq=(SELECT MAX(seq) FROM recovery_snapshots)")
    s=session(live)
    assert s.recovery.checkpoint_error=='RECOVERY_CHECKPOINT_CORRUPT'
    assert not s.startup().ready
    assert s.recovery.state.positions['par:BTC'].quantity==D('.2')
    assert s.execution.entries_paused
    assert session(live).recovery.checkpoint_error=='RECOVERY_CHECKPOINT_CORRUPT'


def test_atomic_combined_checkpoint_previous_copy_and_rollback(live,monkeypatch):
    r,m=seed(live)
    before=deepcopy(live.journal.recovery_snapshot())
    original=live.journal.db
    # A failure between writes must roll back the entire SQLite transaction.
    with pytest.raises(RuntimeError):
        with live.journal.transaction():
            live.journal.db.execute("UPDATE management SET data='{}'")
            live.journal.db.execute("UPDATE account_checkpoint SET data='{}'")
            raise RuntimeError('crash-injection')
    assert live.journal.recovery_snapshot()==before
    assert D(live.journal.management()['par:BTC']['position']['quantity'])==D('.2')
    r.persist_manager(m,candidate_id='updated')
    assert live.journal.db.execute('SELECT COUNT(*) FROM recovery_snapshots').fetchone()[0]==2


@pytest.mark.parametrize('bad',['negative_count','open_cursor','negative_cursor'])
def test_bad_management_evidence_is_rejected(live,bad):
    r,m=seed(live)
    data=r.saved_management or live.journal.management()
    record=deepcopy(data['par:BTC'])
    if bad=='negative_count':record['candles_held']=-1
    elif bad=='open_cursor':record['last_candle_ms']=NOW-59999
    else:record['last_candle_ms']=-60000
    r.saved_management={'par:BTC':record}
    with pytest.raises(ExchangeError):r.restore_manager(m)


def test_breakeven_stop_target_cooldown_and_counters_survive(live):
    r,m=seed(live)
    m._open_position.update(stop_loss_price=100.0,breakeven_armed=True)
    m.candles_held=7;m.candles_since_last_sl=4;m.daily_bias='LONG_BIAS'
    r.persist_manager(m,candidate_id='seed',direction_flip_intent={'side':'SELL'},exit_reason='Target Hit')
    s=session(live)
    held=s.managers['par:BTC']
    assert held._open_position['stop_loss_price']==100 and held._open_position['breakeven_armed']
    assert held._open_position['target_price']==105 and held.candles_held==7 and held.candles_since_last_sl==4
    assert s.exit_reasons['par:BTC']=='Target Hit'
    assert live.journal.recovery_snapshot()['management']['par:BTC']['direction_flip_intent']=={'side':'SELL'}


@pytest.mark.parametrize('gap,complete',[(0,True),(1,True),(3,True),(3,False)])
def test_exposed_completed_candle_backfill_exact_and_no_wallclock_counts(live,monkeypatch,gap,complete):
    seed(live,cursor=NOW-60000-gap*60000)
    s=session(live)
    bars=[bar(t,close='100') for t in range(NOW-gap*60000,NOW,60000)]
    if not complete:bars=bars[1:]
    monkeypatch.setattr(s.market,'get_candles',lambda *args,**kwargs:bars)
    s.startup()
    if complete:
        assert s.startup_recovery.state==StartupState.READY
        assert s.managers['par:BTC'].candles_held==gap
        assert s.managers['par:BTC'].last_candle_ms==NOW-60000
    else:
        assert s.startup_recovery.state==StartupState.POSITION_REVIEW
        assert s.managers['par:BTC'].candles_held==0
    assert not live.transport.signed_payloads


@pytest.mark.parametrize('close,target_touch',[('90',False),('100',True)])
def test_downtime_stop_or_target_touch_requires_review_without_fake_fill(live,monkeypatch,close,target_touch):
    seed(live,cursor=NOW-120000)
    s=session(live)
    b=bar(NOW-60000,close=close)
    if target_touch:b=replace(b,high=D(106))
    monkeypatch.setattr(s.market,'get_candles',lambda *a,**k:[b])
    s.startup()
    assert s.startup_recovery.state==StartupState.POSITION_REVIEW
    assert not s.recovery.state.fills and not live.transport.signed_payloads
    assert s.managers['par:BTC']._open_position['stop_loss_price']==95


def test_unknown_open_order_is_classified_and_not_cancelled(live):
    seed(live,'0')
    live.fixture.orders=[dict(coin='par:BTC',oid=42,side='B',sz='.2',limitPx='100')]
    s=session(live);s.startup()
    report=s.startup_recovery.report()
    assert report['unknown_orders']==1 and report['order_classifications']['42']=='UNKNOWN'
    assert report['entry_status']=='ENTRY_PAUSED' and not live.transport.signed_payloads


def test_metadata_change_requires_review_on_restart(live):
    seed(live)
    live.fixture.metadata['universe'][0]['szDecimals']=3
    s=session(live)
    with pytest.raises(ExchangeError,match='STARTUP_RECOVERY_FAILED'):s.startup()
    assert s.startup_recovery.state==StartupState.FAILED_SAFE


def test_post_stream_second_reconciliation_and_generation(live,monkeypatch):
    s=session(live)
    stream=SimpleNamespace(executor=live.executor,healthy=False,connected=True,subscribed={'userFills'},CHANNELS=('userFills',),generation=1)
    s.attach_account_stream(stream)
    count=[0];original=s.recovery.recover
    def observed():count[0]+=1;return original()
    monkeypatch.setattr(s.recovery,'recover',observed)
    s.startup()
    assert s.execution.entries_paused and not s.startup_recovery.post_stream_verified
    assert s.startup_recovery.after_stream(1)
    assert count[0]>=2 and s.startup_recovery.stream_generation==1
    assert s.startup_recovery.post_stream_verified


@pytest.mark.parametrize('kind',['fill','funding'])
def test_overlap_event_duplicates_not_double_accounted(live,kind):
    if kind=='fill':live.fixture.fill('.2',closed='1')
    else:live.fixture.funding=[dict(time=NOW,hash='fund1',delta=dict(type='funding',coin='par:BTC',usdc='.2',szi='.2',fundingRate='.0001'))]
    r=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    first=r.recover().accounting['realized']
    live.fixture.now+=1000
    for _ in range(3):assert r.recover().accounting['realized']==first
    again=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    assert again.recover().accounting['realized']==first


@pytest.mark.parametrize('kind,limit',[('fill',2000),('funding',500)])
def test_full_history_page_remains_barrier(live,kind,limit):
    if kind=='fill':live.fixture.fills=[dict(coin='par:BTC',time=NOW,tid=i,oid=11,side='B',sz='.1',px='100',fee='.1',feeToken='USDPR',closedPnl='0') for i in range(limit)]
    else:live.fixture.funding=[dict(time=NOW,hash=str(i),delta=dict(type='funding',coin='par:BTC',usdc='.1',szi='.2',fundingRate='.01')) for i in range(limit)]
    s=session(live)
    with pytest.raises(ExchangeError):s.startup()
    assert s.execution.entries_paused and s.startup_recovery.state==StartupState.FAILED_SAFE


@pytest.mark.parametrize('point',['entry_fill','ledger_before_checkpoint','checkpoint_before_manager','exit_before_response',
                                 'partial_exit','funding_boundary','ws_reconnection','protection_creation'])
def test_killed_process_transaction_preserves_previous_truth_and_no_duplicate_accounting(live,point):
    r,m=seed(live)
    live.fixture.funding=[dict(time=NOW,hash='fund1',delta=dict(type='funding',coin='par:BTC',usdc='.2',szi='.2',fundingRate='.0001'))]
    r.recover()
    before=live.journal.recovery_snapshot()
    # Kill a separate process while it owns a multi-table checkpoint write.
    # Each named boundary is tested at a distinct write prefix. OS termination
    # cannot run Python finally blocks; WAL must preserve the previous commit.
    code=r'''
import os,signal,sys
from exchange.execution_journal import ExecutionJournal
j=ExecutionJournal(sys.argv[1],session_id='offline:test',team_address=sys.argv[2])
steps=["UPDATE account_checkpoint SET data='{}'","UPDATE management SET data='{}'",
       "UPDATE recovery_snapshots SET data='{}'","INSERT OR REPLACE INTO controls VALUES ('live_risk_state','{}')"]
with j.transaction():
    for q in steps[:int(sys.argv[3])]:j.db.execute(q)
    os.kill(os.getpid(),signal.SIGKILL)
'''
    prefix=1+['entry_fill','ledger_before_checkpoint','checkpoint_before_manager','exit_before_response',
              'partial_exit','funding_boundary','ws_reconnection','protection_creation'].index(point)%4
    result=subprocess.run([sys.executable,'-c',code,str(live.journal.path),TEAM,str(prefix)],cwd=Path(__file__).parent,
                          capture_output=True,text=True,timeout=10)
    assert result.returncode==-signal.SIGKILL
    assert live.journal.recovery_snapshot()==before
    s=session(live);s.startup()
    assert s.recovery.state.positions['par:BTC'].quantity==D('.2')
    assert s.recovery.state.report()['realized']['actual_funding_cashflow']==D('.2')
    assert len(s.recovery.state.funding)==1 and not live.transport.signed_payloads


@pytest.fixture
def funnel_scan():
    p=ScannerPolicy('.004',15,0,10)
    diagnostics=[]
    for i in range(6):
        symbol='par:'+['BTC','ETH','HYPE','SP500','EWY','EWJ'][i]
        signal=dict(timestamp_ms=NOW-60000,long=i>=3,short=False,reference=D(100),atr=D(1),bias='NEUTRAL')
        d=MarketDiagnostic(symbol,True,metrics=dict(atr_fraction=D('.0055')-D(i)*D('.0001'),spread_bps=D(2),window_notional_approx=D(10000),bbo_notional=D(100)),
            signal=signal,candles=[bar(NOW-60000-j*60000,symbol=symbol) for j in range(300)],snapshot=object(),evidence={'scanner_rank':i+1})
        diagnostics.append(d)
    return ScanResult(NOW,diagnostics,[d.symbol for d in diagnostics[:3]],'ACTIVE'),p


def test_every_market_trace_and_top3_nonselected_setups(funnel_scan):
    scan,p=funnel_scan;f=OpportunityFunnel();f.observe_scan(scan,p)
    assert len(f.traces)==6 and all(set(t['stages'])==set(STAGES) for t in f.traces.values())
    exclusions=f.report()['top3_exclusions']
    assert [e['rank'] for e in exclusions]==[4,5,6] and all(e['available_setup'] for e in exclusions)
    assert all(t['stages']['STRATEGY_EVALUATED']['status']=='NOT_REACHED' for t in f.traces.values() if not t['selected'])


@pytest.mark.parametrize('raw,code',[('COMPLETED_CANDLE_STALE','STALE_CANDLE'),('ORDERBOOK_STALE','STALE_BOOK'),
 ('INSUFFICIENT_COMPLETED_HISTORY','INSUFFICIENT_HISTORY'),('ATR_BELOW_BASELINE_SCANNER_FLOOR','ATR_BELOW_SCANNER_FLOOR'),
 ('SPREAD_TOO_WIDE','SPREAD_TOO_WIDE'),('BBO_DEPTH_INSUFFICIENT','INSUFFICIENT_DEPTH')])
def test_rejection_taxonomy_first_blocking_reason(funnel_scan,raw,code):
    scan,p=funnel_scan;d=scan.diagnostics[0];d.qualified=False;d.reasons=[raw,'SPREAD_TOO_WIDE'];scan.watchlist.remove(d.symbol)
    f=OpportunityFunnel();f.observe_scan(scan,p)
    t=f.traces[f'{d.symbol}:{NOW}']
    assert t['first_blocking_reason']==code and code in t['all_observed_failed_conditions']


def test_simultaneous_failures_do_not_change_actual_first_gate(funnel_scan):
    scan,p=funnel_scan;d=scan.diagnostics[0]
    d.metrics.update(atr_fraction=D('.001'),spread_bps=D(25),bbo_notional=D(0))
    d.qualified=False;d.reasons=['ATR_BELOW_BASELINE_SCANNER_FLOOR','SPREAD_TOO_WIDE','BBO_DEPTH_INSUFFICIENT']
    f=OpportunityFunnel();f.observe_scan(scan,p);t=f.traces[f'{d.symbol}:{NOW}']
    assert t['first_blocking_reason']=='ATR_BELOW_SCANNER_FLOOR'
    assert {'ATR_BELOW_SCANNER_FLOOR','SPREAD_TOO_WIDE','INSUFFICIENT_DEPTH'}<=set(t['all_observed_failed_conditions'])


@pytest.mark.parametrize('event,details,stage',[
 ('RISK_DECISION',{'decision':{'allowed':False,'reasons':['NET_EDGE_OR_RR_INSUFFICIENT']}},'FRICTION_PASS'),
 ('RISK_DECISION',{'decision':{'allowed':False,'reasons':['PORTFOLIO_MARGIN_LIMIT']}},'RISK_PASS'),
 ('ENTRY_REJECTED',{'reason':'ENTRY_PAUSED'},'EXECUTION_PERMISSION')])
def test_downstream_rejections_are_distinct(funnel_scan,event,details,stage):
    scan,p=funnel_scan;scan.diagnostics[0].signal['long']=True
    f=OpportunityFunnel();f.observe_scan(scan,p);cid=f'par:BTC:{NOW}'
    f.event(event,cid,details,NOW)
    assert f.traces[cid]['stages'][stage]['status']=='FAIL'


def test_fill_and_completion_exactly_once_percentages_and_export(funnel_scan,tmp_path):
    scan,p=funnel_scan;scan.diagnostics[0].signal['long']=True
    f=OpportunityFunnel();f.observe_scan(scan,p);f.observe_scan(scan,p)
    cid=f'par:BTC:{NOW}'
    for _ in range(3):
        f.event('ENTRY_FILL',cid,{},NOW);f.event('TRADE_PNL',cid,{},NOW)
    report=f.export(tmp_path)
    rows={r['stage']:r for r in report['session']['stages']}
    assert rows['FILLED']['passed']==rows['TRADE_COMPLETED']['passed']==1
    assert rows['FILLED']['percent_of_observations']==100/6
    assert all(r['passed']+r['failed']+r['not_reached']+r['not_observed']==6 for r in rows.values())
    assert report['session']['bottleneck_status']=='INSUFFICIENT OBSERVATIONS'
    assert all((tmp_path/name).exists() for name in ('funnel_summary.json','funnel_summary.csv','hourly_funnel.json','atr_spread_distributions.json','opportunity_report.txt'))


def test_persisted_funnel_survives_restart_without_duplicate_counts(live,funnel_scan):
    scan,p=funnel_scan;f=OpportunityFunnel(journal=live.journal);f.observe_scan(scan,p)
    again=OpportunityFunnel(journal=live.journal);again.observe_scan(scan,p)
    assert len(again.traces)==6


def test_diagnostics_are_observational_and_policy_stays_baseline(universe):
    _,bot=make_bot(universe)
    before=asdict(bot.scanner.policy)
    scan=bot.scanner.scan();bot.consume_scan(scan)
    assert asdict(bot.scanner.policy)==before and bot.scanner.policy.top_n==3
    assert len(bot.funnel.traces)==len(scan.diagnostics)
    assert all(d.evidence['brain']['status']=='OBSERVED_FROZEN_LOCALS' for d in scan.diagnostics)


def test_passive_brain_outputs_and_trace_hook_restored(universe):
    from brain_observation import observe_frozen_call
    _,market,scanner=universe
    candles=market.get_candles('par:BTC',NOW-300*60000,NOW-1,now_ms=NOW)
    before=scanner.brain.evaluate_candles(candles)
    after,evidence=observe_frozen_call(lambda:scanner.brain.evaluate_candles(candles))
    assert before.equals(after) and sys.gettrace() is None
    assert evidence['status']=='OBSERVED_FROZEN_LOCALS'


def test_counterfactual_variants_cannot_execute_or_mutate_policy(funnel_scan,tmp_path):
    scan,p=funnel_scan;f=OpportunityFunnel();f.observe_scan(scan,p)
    observations=list(f.traces.values());before=deepcopy(observations);policy=asdict(p)
    r=CounterfactualResearch().export(observations,tmp_path)
    assert observations==before and asdict(p)==policy
    assert not r['order_capability'] and not r['production_policy_changed'] and not r['automatic_promotion']
    assert not any(hasattr(CounterfactualResearch(),k) for k in ('submit','place_order','execution','signer','client'))
    baseline,top5=r['variants'][0],next(v for v in r['variants'] if v['policy']['name']=='TOP5')
    assert baseline['available_frozen_setups']==0 and top5['available_frozen_setups']==2
    assert top5['all_recorded_outcomes']['net_result'] is None


@pytest.mark.parametrize('damage',['future_availability','future_candle','duplicate'])
def test_research_rejects_lookahead_and_duplicate_inputs(funnel_scan,damage):
    scan,p=funnel_scan;f=OpportunityFunnel();f.observe_scan(scan,p);rows=list(f.traces.values())
    if damage=='future_availability':rows[0]['available_at_ms']=NOW+1
    elif damage=='future_candle':rows[0]['signal']['timestamp_ms']=NOW
    else:rows.append(deepcopy(rows[0]))
    with pytest.raises(ExchangeError):CounterfactualResearch().evaluate(rows)


def test_baseline_cannot_be_overwritten():
    with pytest.raises(ExchangeError):ResearchVariant('BASELINE_POLICY',D('.003'))
    with pytest.raises(ExchangeError):CounterfactualResearch([ResearchVariant('ONLY_EXPERIMENT')])


def test_holdout_costs_drawdown_embargo_without_admission_leak(funnel_scan):
    scan,p=funnel_scan;f=OpportunityFunnel();f.observe_scan(scan,p)
    rows=list(f.traces.values());cutoff=NOW+86400000
    for t in rows:t['side_channel_signal']=True
    later=deepcopy(rows)
    for t in later:
        t.update(candidate_id=t['candidate_id']+':later',decision_ms=cutoff,available_at_ms=cutoff,utc_day='2026-02-21')
        t['signal']['timestamp_ms']=cutoff-60000
    outcomes={t['candidate_id']:dict(decision_ms=t['decision_ms'],completed_ms=t['decision_ms']+60000,
        source='RECORDED_PAPER_SIMULATION',gross_result='1',fees='.3',slippage='.2',funding_cost='.1') for t in rows+later}
    r=CounterfactualResearch().evaluate(rows+later,holdout_start_ms=cutoff,outcomes=outcomes)
    baseline=r['variants'][0]
    assert baseline['research_window']['net_result']==D('1.2')
    assert baseline['untouched_holdout']['net_result']==D('1.2')
    outcomes[rows[0]['candidate_id']]['completed_ms']=cutoff+1
    again=CounterfactualResearch().evaluate(rows+later,holdout_start_ms=cutoff,outcomes=outcomes)
    assert again['variants'][0]['research_window']['evaluated_outcomes']==2
    assert again['variants'][0]['selected_candidate_ids']==baseline['selected_candidate_ids']


@pytest.mark.parametrize('point',['entry_fill','ledger_before_checkpoint','checkpoint_before_manager','exit_before_response',
                                 'partial_exit','funding_boundary','ws_reconnection','protection_creation'])
def test_sigkill_actual_owner_lifecycle_recovers_external_exchange_truth(live,monkeypatch,tmp_path,point):
    from test_production_reliability import ProtectionVenue,live_session
    venue=ProtectionVenue(live,monkeypatch)
    owner,protection=live_session(live,venue)
    owner.startup();owner.consume_scan(signal_scan(NOW))
    held=live.account.get_position('par:BTC')
    initial=held.quantity
    entry=next(r for r in live.journal.intents() if json.loads(r['request'])['strategy_id']!='CATASTROPHIC_STOP')
    if point in {'entry_fill','ledger_before_checkpoint','checkpoint_before_manager'}:
        live.fixture.position(initial+D('.05'),entry=str(held.entry_price))
        live.fixture.fill('.05',price=str(held.entry_price),oid=int(entry['oid']),tid=777,fee='.01')
    elif point=='partial_exit':
        cid=entry['candidate']
        request=OrderRequest('par:BTC','SELL',initial,'100',reduce_only=True,strategy_id='VWAP_BASELINE_EXIT')
        row,_=live.journal.reserve('crash:partial-exit',asdict(request),cid,NOW)
        live.journal.update(row['intent_key'],'PARTIALLY_FILLED',NOW,oid='888',
            outcome=dict(filled_quantity='.05',remaining_quantity=initial-D('.05'),remainder_cancelled=True))
        owner.exit_reasons['par:BTC']='Target Hit';owner._persist('par:BTC')
        live.fixture.position(initial-D('.05'),entry=str(held.entry_price))
        live.fixture.fill('.05',side='A',price='100',oid=888,tid=888,closed='-.0005')
    elif point=='funding_boundary':
        live.fixture.funding=[dict(time=NOW,hash='fund-crash',delta=dict(type='funding',coin='par:BTC',usdc='.2',szi=str(initial),fundingRate='.0001'))]
    elif point=='protection_creation':
        for order in list(live.fixture.orders):venue._cancel(order['oid'])
    truth_path=tmp_path/'external-synthetic-exchange.json'
    truth={k:getattr(live.fixture,k) for k in ('state','orders','fills','funding','budget')}
    truth.update(statuses=venue.statuses,oid=venue.oid)
    truth_path.write_text(json.dumps(truth,default=str))
    worker=Path(__file__).parent/'test_fixtures/restart_crash_worker.py'
    killed=subprocess.run([sys.executable,str(worker),point,str(live.journal.path),str(truth_path)],
                          capture_output=True,text=True,timeout=30)
    assert killed.returncode==-signal.SIGKILL,killed.stderr
    # The mock exchange is outside the killed process. Read its durable actual
    # executions rather than inventing what a missing response might have meant.
    truth=json.loads(truth_path.read_text())
    for key in ('state','orders','fills','funding','budget'):setattr(live.fixture,key,truth[key])
    venue.statuses=truth['statuses'];venue.oid=truth['oid']
    restored,guard=live_session(live,venue)
    restored.startup()
    uncertain=[r for r in live.journal.intents() if r['state'] in {'UNKNOWN','SUBMITTED'} and
               json.loads(r['request'])['strategy_id']!='CATASTROPHIC_STOP']
    for row in uncertain:live.executor.recover_uncertain(row['intent_key'])
    restored.startup()
    actual=live.account.get_position('par:BTC')
    assert actual is not None
    assert restored.managers['par:BTC']._open_position['quantity']==actual.quantity
    assert restored.recovery.state.report()['realized']['actual_fill_fees']==sum(D(f['fee']) for f in live.fixture.fills)
    assert len(restored.recovery.state.fills)==len({(f['coin'],f['time'],f['tid'],f['oid']) for f in live.fixture.fills})
    assert guard.states['par:BTC']['status']=='ACTIVE'
    assert len(live.fixture.orders)==1 and D(live.fixture.orders[0]['sz'])==actual.quantity
    assert restored.startup_recovery.previous_shutdown=='UNCLEAN'
    before=deepcopy(restored.recovery.state.report()['realized'])
    restored.recovery.recover()
    assert restored.recovery.state.report()['realized']==before


@pytest.mark.parametrize('kind,count',[('fill',2100),('funding',600)])
def test_saturated_history_backfills_split_windows_without_missing_events(live,kind,count):
    start=NOW-count
    if kind=='fill':
        live.fixture.fills=[dict(coin='par:BTC',time=start+i,tid=i,oid=11,side='B',sz='.1',px='100',fee='.1',feeToken='USDPR',closedPnl='0') for i in range(count)]
        events=live.account.get_complete_fills(start,NOW)
    else:
        live.fixture.funding=[dict(time=start+i,hash=str(i),delta=dict(type='funding',coin='par:BTC',usdc='.1',szi='.2',fundingRate='.01')) for i in range(count)]
        events=live.account.get_complete_funding(start,NOW)
    assert len(events)==count and len({e.identity for e in events})==count
    assert len([p for p in live.fixture.calls if p['type'] in {'userFillsByTime','userFunding'}])>=3


def test_direction_flip_intent_persists_without_reversing_exchange(live):
    r,m=seed(live)
    r.persist_manager(m,candidate_id='seed',direction_flip_intent={'from':'BUY','to':'SELL','actual_flat_required':True})
    s=session(live)
    assert s.recovery.saved_management['par:BTC']['direction_flip_intent']['actual_flat_required']
    s.startup()
    assert live.account.get_position('par:BTC').quantity==D('.2') and not live.transport.signed_payloads


def test_invalid_management_schema_still_discovers_actual_position(live):
    r,m=seed(live)
    record=live.journal.management()['par:BTC'];record['version']=999
    r.checkpoint(management={'par:BTC':record})
    s=session(live);s.startup()
    assert s.recovery.state.positions['par:BTC'].quantity==D('.2')
    assert s.recovery.checkpoint_error=='INVALID_MANAGEMENT_HISTORY' and s.execution.entries_paused


@pytest.mark.parametrize('configured',[False,True])
def test_read_only_startup_never_claims_flat_or_entry_ready(configured):
    from exchange.startup_recovery import read_only_startup_report
    report=read_only_startup_report(account_configured=configured,market_ready=True)
    assert report['state']==('READ_ONLY_READY' if configured else 'ACCOUNT_NOT_CONFIGURED')
    assert report['exchange_positions'] is None and report['entry_status']=='ENTRY_PAUSED' and not report['live_ready']


def test_public_feed_health_revokes_entry_even_after_startup(live):
    s=session(live);s.startup()
    assert s.startup_recovery.entry_ready
    s.market.engine=SimpleNamespace(connected=False,reconciled=False,last_receive_ms=None)
    assert not s.startup_recovery.entry_ready
    request=OrderRequest('par:BTC','BUY','.2','100',client_order_id='feed-loss')
    from test_live_exchange_execution import permission
    with pytest.raises(ExchangeError,match='STARTUP_ENTRY_LOCK_REQUIRED'):
        live.executor.submit(request,permission=permission(request))
    assert not live.transport.signed_payloads


@pytest.mark.parametrize('fault',[False,True])
def test_runtime_graceful_close_is_separate_from_unexpected_failure(live,fault):
    from exchange.live_runtime import LiveRuntime
    import threading
    s=session(live);s.startup()
    flags=[]
    stop=threading.Event()
    def cycle():
        if fault:raise RuntimeError('unexpected-process-failure')
        stop.set()
    s.cycle=cycle
    runtime=LiveRuntime(s,SimpleNamespace(revoke=lambda:None),SimpleNamespace(close=lambda:None),
        SimpleNamespace(close=lambda:None),live.journal,SimpleNamespace(close=lambda:None))
    runtime.close=lambda *,clean=True:flags.append(clean)
    if fault:
        with pytest.raises(RuntimeError):runtime.run(stop)
    else:runtime.run(stop)
    assert flags==[not fault]


def test_bias_and_cooldown_first_failure_matches_frozen_permits_order(funnel_scan):
    scan,p=funnel_scan;scan.diagnostics[0].signal['long']=True
    f=OpportunityFunnel();f.observe_scan(scan,p)
    manager=SimpleNamespace(daily_bias='SHORT_BIAS',candles_since_last_sl=0,parameters={'REENTRY_COOLDOWN_CANDLES':10})
    cid=f'par:BTC:{NOW}'
    f.permission_observation(cid,manager,'BUY')
    assert f.traces[cid]['first_blocking_reason']=='COOLDOWN'
    assert {'BIAS_MISMATCH','COOLDOWN'}<=set(f.traces[cid]['all_observed_failed_conditions'])


def test_admission_funnel_is_monotonic_without_claiming_unobserved_gates_pass(funnel_scan):
    scan,p=funnel_scan
    for d in scan.diagnostics:
        d.qualified=False;d.reasons=['COMPLETED_CANDLE_STALE'];d.signal=None
    scan.watchlist=[]
    f=OpportunityFunnel();f.observe_scan(scan,p)
    rows=f.report()['session']['stages']
    counts=[r['admission_survivors'] for r in rows]
    assert all(a>=b for a,b in zip(counts,counts[1:]))
    assert counts[:4]==[6,6,0,0]
    assert next(r for r in rows if r['stage']=='ENOUGH_HISTORY')['passed']==6


def test_whole_context_read_failure_traces_all_verified_markets_without_execution(universe,monkeypatch):
    _,bot=make_bot(universe)
    def failed():raise ExchangeError('INFO_REQUEST_FAILED')
    monkeypatch.setattr(bot.market,'get_asset_contexts',failed)
    with pytest.raises(ExchangeError):bot.cycle()
    assert len(bot.funnel.traces)==len(bot.market.client.markets)
    assert all(t['first_blocking_reason']=='MARKET_DATA_UNAVAILABLE' for t in bot.funnel.traces.values())
    assert not bot.execution.orders
