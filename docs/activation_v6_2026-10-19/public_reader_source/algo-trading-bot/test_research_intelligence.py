"""Synthetic engineering evidence only; never trading-performance evidence."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime,timezone,timedelta
from pathlib import Path
import ast,json
import numpy as np
import pandas as pd
import pytest

from research_intelligence.anchors import VWAPAnchorPolicy,VWAP_BASELINE_UTC,AnchorResearchBrain
from research_intelligence.common import ResearchError,MARKETS,ROOT,digest,immutable_json,HoldoutLedger
from research_intelligence.dataset import build_dataset,feature_manifest,from_opportunity_traces,feature_evidence_from_events,regime,NUMERIC,CATEGORICAL
from research_intelligence.splits import ChronologicalSplit
from research_intelligence.models import train_models,MetaController,probability,fit_transform,transform,evaluate_model,save_model
from research_intelligence.metrics import classification,performance,day_block_interval
from research_intelligence.experiment import run_research,policies_from_config,anchor_observations,data_gate,aggregate_anchors


@pytest.fixture
def frame():
    n=1000;rng=np.random.default_rng(12);price=100+np.cumsum(rng.normal(.002,.25,n))
    return pd.DataFrame(dict(Timestamp=pd.date_range('2026-09-30 18:00',periods=n,freq='min',tz='UTC'),
        Open=price,High=price+.4,Low=price-.4,Close=price,Volume=rng.uniform(1,10,n)))


@pytest.fixture
def session():return VWAPAnchorPolicy('TEST_DAILY_REFERENCE','par:BTC','ASSET_SESSION_ANCHOR','UTC','06:00','Synthetic fixture reference','Test only')


@pytest.fixture(scope='module')
def corpus():
    units={f['name']:f['units'] for f in feature_manifest()['features']};obs=[];out={};base=int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp()*1000)
    assumptions=dict(source='SYNTHETIC_TEST_FIXTURE',fee='fixed',management='FROZEN_BASELINE',risk='UNCHANGED_TEST_CONTROL')
    rng=np.random.default_rng(51)
    for i in range(1000):
        t=base+(i//10)*86400000+(i%10)*3600000;cid='fixture-'+str(i);symbol=MARKETS[i%3];direction='LONG' if i%2 else 'SHORT';positive=(i%4 in (0,1))
        values=dict(atr_fraction=.005+rng.uniform(0,.002),vwap_distance_fraction=rng.uniform(-.01,.01),
            ema9=100+rng.uniform(-.1,.1),ema21=100,ema_separation_fraction=(.003 if positive else -.003)+rng.normal(0,.0005),
            spread_bps=5+rng.uniform(0,5),book_imbalance=rng.uniform(-.5,.5),daily_bias='NEUTRAL')
        evidence={n:dict(value=v,source='SYNTHETIC_TEST_FIXTURE',source_ms=t-1000,available_ms=t,units=units[n]) for n,v in values.items()}
        row=dict(candidate_id=cid,symbol=symbol,decision_ms=t,valid_strategy_candidate=True,setup_type='PULLBACK_'+direction,
                 direction=direction,anchor_policy_id='VWAP_BASELINE_UTC',candidate_kind='EXECUTED_CANDIDATE',feature_evidence=evidence,source='SYNTHETIC_TEST_FIXTURE')
        obs.append(row);out[cid]=dict(candidate_id=cid,symbol=symbol,direction=direction,decision_ms=t,anchor_policy_id='VWAP_BASELINE_UTC',
            completed_ms=t+600000,source='RECORDED_PAPER_SIMULATION',fill_model='OBSERVED_EXECUTABLE_BBO',entry_fill_ids=['fixture-entry-'+str(i)],exit_fill_ids=['fixture-exit-'+str(i)],
            management_version='FROZEN_BASELINE',assumptions_hash=digest(assumptions),gross_result=15 if positive else -10,fees=1,slippage=.5,funding_cost=.1)
    rows,quality=build_dataset(obs,out,assumptions=assumptions)
    split=ChronologicalSplit(base+60*86400000,base+80*86400000,base+70*86400000,3600000)
    return obs,out,assumptions,rows,quality,split


@pytest.fixture(scope='module')
def fitted(corpus):
    _,_,_,rows,_,split=corpus;parts=split.partition(rows)
    return train_models(parts,digest(feature_manifest()),'synthetic-source',digest(rows)),parts


def test_utc_baseline_exact_outputs(frame):
    from signal_brain import generate_vwap_signal
    before=frame.copy(deep=True);actual=AnchorResearchBrain().evaluate_frame(frame)
    pd.testing.assert_frame_equal(actual,generate_vwap_signal(frame));pd.testing.assert_frame_equal(frame,before)


def test_session_only_changes_vwap_and_slope_controls_fixed(frame,session):
    utc=AnchorResearchBrain().evaluate_frame(frame);alt=AnchorResearchBrain(session).evaluate_frame(frame)
    assert not utc.VWAP.equals(alt.VWAP)
    for column in ['ATR_14','EMA_9','EMA_21','Vol_MA10','Timestamp','Close','Volume']:
        pd.testing.assert_series_equal(utc[column],alt[column])
    import signal_brain
    assert signal_brain.generate_vwap_signal.__module__=='signal_brain'


def test_anchor_mathematics_first_boundary_and_volume(frame,session):
    result=AnchorResearchBrain(session).evaluate_frame(frame);i=frame.index[frame.Timestamp.dt.hour.eq(6)&frame.Timestamp.dt.minute.eq(0)][0]
    assert result.VWAP.iloc[i]==pytest.approx((frame.High.iloc[i]+frame.Low.iloc[i]+frame.Close.iloc[i])/3)
    typical=(frame.High.iloc[i:i+3]+frame.Low.iloc[i:i+3]+frame.Close.iloc[i:i+3])/3
    assert result.VWAP.iloc[i+2]==pytest.approx(float((typical*frame.Volume.iloc[i:i+3]).sum()/frame.Volume.iloc[i:i+3].sum()))


@pytest.mark.parametrize('length',[20,200,731,999])
def test_anchor_prefix_causality(frame,session,length):
    brain=AnchorResearchBrain(session);full=brain.evaluate_frame(frame);prefix=brain.evaluate_frame(frame.iloc[:length])
    pd.testing.assert_frame_equal(prefix,full.iloc[:length])


@pytest.mark.parametrize('damage',['duplicate','gap','naive','future','volume','ohlc'])
def test_anchor_invalid_input_rejected(frame,damage):
    f=frame.copy();decision=None
    if damage=='duplicate':f.loc[1,'Timestamp']=f.Timestamp.iloc[0]
    if damage=='gap':f=f.drop(index=1)
    if damage=='naive':f['Timestamp']=f.Timestamp.dt.tz_localize(None)
    if damage=='future':decision=int(f.Timestamp.iloc[-1].timestamp()*1000)
    if damage=='volume':f.loc[0,'Volume']=-1
    if damage=='ohlc':f.loc[0,'Low']=f.High.iloc[0]+1
    with pytest.raises(ResearchError):AnchorResearchBrain().evaluate_frame(f,decision)


def test_timestamp_timezone_normalizes_utc(frame):
    local=frame.copy();local.Timestamp=local.Timestamp.dt.tz_convert('Asia/Tokyo')
    pd.testing.assert_frame_equal(AnchorResearchBrain().evaluate_frame(local),AnchorResearchBrain().evaluate_frame(frame))


@pytest.mark.parametrize('date,utc_hour',[('2026-01-15',14),('2026-07-15',13),('2026-03-09',13),('2026-11-02',14)])
def test_dst_ny_reference(date,utc_hour):
    p=VWAPAnchorPolicy('NY_REFERENCE','par:SP500','ASSET_SESSION_ANCHOR','America/New_York','09:30','NYSE reference research','Fixture')
    d=datetime.fromisoformat(date).replace(hour=20,tzinfo=timezone.utc)
    assert p.anchor_at(d).hour==utc_hour and p.anchor_at(d).minute==30


@pytest.mark.parametrize('date,time,code',[('2026-03-08','02:30','NONEXISTENT'),('2026-11-01','01:30','AMBIGUOUS')])
def test_bad_local_dst_reference_fails_closed(date,time,code):
    p=VWAPAnchorPolicy('BAD_LOCAL','par:BTC','ASSET_SESSION_ANCHOR','America/New_York',time,'Fixture','Fixture')
    with pytest.raises(ResearchError,match=code):p.anchor_at(datetime.fromisoformat(date).replace(hour=20,tzinfo=timezone.utc))


def test_policy_immutable_baseline_protected():
    with pytest.raises(FrozenInstanceError):VWAP_BASELINE_UTC.anchor_time='06:00'
    with pytest.raises(ResearchError):VWAPAnchorPolicy('VWAP_BASELINE_UTC',anchor_type='ASSET_SESSION_ANCHOR',anchor_time='06:00')
    with pytest.raises(ResearchError):VWAPAnchorPolicy('ROLLING',anchor_type='ROLLING_VWAP')


def test_before_anchor_previous_day(session):
    assert session.anchor_at(datetime(2026,10,4,5,tzinfo=timezone.utc))==datetime(2026,10,3,6,tzinfo=timezone.utc)


def test_position_survives_anchor_and_utc_midnight():
    from crypto_strategy_state import CryptoStrategyState
    manager=CryptoStrategyState('par:BTC',lambda *a:pytest.fail('Anchor must not exit'),clock_ms=lambda:0)
    manager._open_position=dict(side='BUY',quantity=1,stop_loss_price=90,target_price=120,average_entry_price=100)
    manager.candles_held=7;manager._check_day_reset(datetime(2026,10,3,23,59,tzinfo=timezone.utc));manager._check_day_reset(datetime(2026,10,4,tzinfo=timezone.utc))
    assert manager.has_open_position and manager.candles_held==7


@pytest.mark.parametrize('damage',['future_source','future_available','source_after_available','unknown_feature','wrong_units','wrong_direction','negative_spread','bad_imbalance'])
def test_features_reject_leakage_and_bad_schema(corpus,damage):
    o=deepcopy(corpus[0][0]);e=o['feature_evidence']['atr_fraction']
    if damage=='future_source':e['source_ms']=o['decision_ms']+1
    if damage=='future_available':e['available_ms']=o['decision_ms']+1
    if damage=='source_after_available':e['available_ms']=e['source_ms']-1
    if damage=='unknown_feature':o['feature_evidence']['exit_price']=deepcopy(e)
    if damage=='wrong_units':e['units']='USDPR'
    if damage=='wrong_direction':o['direction']='LONG' if o['direction']=='SHORT' else 'SHORT'
    if damage=='negative_spread':o['feature_evidence']['spread_bps']['value']=-1
    if damage=='bad_imbalance':o['feature_evidence']['book_imbalance']['value']=2
    if damage=='wrong_direction':assert build_dataset([o])[0]==[]
    else:
        with pytest.raises(ResearchError):build_dataset([o])


@pytest.mark.parametrize('kind',['EXECUTED_CANDIDATE','PAPER_EXECUTABLE_CANDIDATE','COUNTERFACTUAL_CANDIDATE','REJECTED_CANDIDATE'])
def test_candidate_kind_not_fabricated_label(corpus,kind):
    o=deepcopy(corpus[0][0]);o['candidate_kind']=kind
    rows,_=build_dataset([o],corpus[1],assumptions=corpus[2]);assert (rows[0]['label'] is None)==(kind=='REJECTED_CANDIDATE')
    rows,_=build_dataset([o],assumptions=corpus[2]);assert rows[0]['label'] is None


@pytest.mark.parametrize('damage',['cost_hash','no_entry_fill','ohcl_fill','future_completion_regression','wrong_symbol','negative_fees','unknown_cost'])
def test_label_lineage_and_full_costs_required(corpus,damage):
    o=corpus[0][0];out={o['candidate_id']:deepcopy(corpus[1][o['candidate_id']])};v=out[o['candidate_id']]
    if damage=='cost_hash':v['assumptions_hash']='different'
    if damage=='no_entry_fill':v['entry_fill_ids']=[]
    if damage=='ohcl_fill':v['fill_model']='CANDLE_HIGH_LOW_GUESS'
    if damage=='future_completion_regression':v['completed_ms']=o['decision_ms']-1
    if damage=='wrong_symbol':v['symbol']='par:ETH'
    if damage=='negative_fees':v['fees']=-1
    if damage=='unknown_cost':v.pop('funding_cost')
    with pytest.raises(ResearchError):build_dataset([o],out,assumptions=corpus[2])


def test_missing_stale_and_duplicate_quality(corpus):
    o=deepcopy(corpus[0][0]);o['feature_evidence']['atr_fraction']['source_ms']-=200000
    rows,q=build_dataset([o,o]);assert len(rows)==1 and q['duplicate_candidates']==1 and q['stale_features']==1
    assert rows[0]['scoring_ready'] is False and rows[0]['features']['atr_fraction'] is None


def test_features_metadata_encoding_units_provenance(corpus):
    row=corpus[3][0]
    for n,value in row['features'].items():
        if value is not None:assert row['feature_provenance'][n]['source_ms']<=row['feature_provenance'][n]['available_ms']<=row['decision_ms']
    assert row['features']['symbol']=='par:BTC' and row['features']['direction']=='SHORT'
    assert row['outcome']['net_result']==pytest.approx(13.4)
    assert set(row['features'])==set(NUMERIC+CATEGORICAL)


def test_split_no_overlap_and_outcome_purge(corpus):
    rows=deepcopy(corpus[3]);split=corpus[5];rows[0]['decision_ms']=split.validation_start_ms-1000;rows[0]['outcome_end_ms']=split.validation_start_ms+1000
    p=split.partition(rows);assert rows[0]['candidate_id'] in [r['candidate_id'] for r in p['purged']]
    ids=[r['candidate_id'] for k in ('train','calibration','validation','holdout') for r in p[k]];assert len(ids)==len(set(ids))
    assert max(r['decision_ms'] for r in p['train'])<min(r['decision_ms'] for r in p['calibration'])<min(r['decision_ms'] for r in p['validation'])<min(r['decision_ms'] for r in p['holdout'])


def test_invalid_or_duplicate_split_rejected(corpus):
    with pytest.raises(ResearchError):ChronologicalSplit(30,20,25)
    with pytest.raises(ResearchError):corpus[5].partition([corpus[3][0],corpus[3][0]])


def test_transform_fit_only_training_and_unknown_market(corpus):
    p=corpus[5].partition(corpus[3]);state=fit_transform(p['train']);copy=deepcopy(state);held=deepcopy(p['holdout'])
    held[0]['features']['ema9']=100000;held[0]['features']['symbol']='par:EWJ';x=transform(held,state)
    assert state==copy and set(state['fit_candidate_ids'])=={r['candidate_id'] for r in p['train']}
    assert 'par:EWJ' not in state['vocab']['symbol'] and x.shape[1]==len(state['feature_names'])


@pytest.mark.parametrize('index',[0,1])
def test_models_calibration_reproducibility_explanations_direction(fitted,index):
    models,p=fitted;m=models[index];row=p['holdout'][0];a=MetaController(m).score(row);b=MetaController(m).score(row)
    assert a==b and a['direction']==row['direction'] and 0<=a['confidence']<=1 and a['explanation']
    assert m['calibration']['fit_candidate_ids']==[r['candidate_id'] for r in p['calibration']]
    assert m['threshold_candidate_ids']==[r['candidate_id'] for r in p['validation']]
    assert not set(m['threshold_candidate_ids'])&{r['candidate_id'] for r in p['holdout']}
    assert m['direction_prediction'] is False and m['order_capability'] is False


def test_holdout_changes_cannot_change_fit_transform_threshold(fitted,corpus):
    models,p=fitted;copy=deepcopy(p)
    for r in copy['holdout']:r['label']=1-r['label'];r['features']['ema9']=900000
    again=train_models(copy,digest(feature_manifest()),'synthetic-source',digest(corpus[3]))
    assert models==again


@pytest.mark.parametrize('damage',['no_model','required_missing','retired','future_proof','missing_proof'])
def test_unavailable_and_boundary_features(fitted,damage):
    models,p=fitted;row=deepcopy(p['holdout'][0]);m=deepcopy(models[0])
    if damage=='no_model':m=None
    if damage=='required_missing':row['features']['spread_bps']=None
    if damage=='retired':m['state']='RETIRED';m.pop('model_version');m['model_version']=digest(m)
    if damage=='future_proof':row['feature_provenance']['ema9']['available_ms']=row['decision_ms']+1
    if damage=='missing_proof':row['feature_provenance'].pop('spread_bps')
    if damage in {'future_proof','missing_proof'}:
        with pytest.raises(ResearchError):MetaController(m).score(row)
    else:
        result=MetaController(m).score(row);assert result['status']=='ML_UNAVAILABLE' and result['confidence'] is None


def test_model_version_load_failures_and_no_overwrite(fitted,tmp_path):
    m=fitted[0][0];p=tmp_path/'model.json';save_model(p,m);assert MetaController.load(p).model==m
    with pytest.raises(FileExistsError):save_model(p,m)
    p.write_text('{broken');assert MetaController.load(p).model is None
    modified=deepcopy(m);modified['threshold']=.99
    with pytest.raises(ResearchError):MetaController(modified)


def test_threshold_deterministic(fitted):
    m=fitted[0][0];r=fitted[1]['holdout'][0];score=MetaController(m).score(r)
    m=deepcopy(m);m['threshold']=score['confidence'];m.pop('model_version');m['model_version']=digest(m)
    assert MetaController(m).score(r)['status']=='ALLOW'


def test_classification_calibration_ties_and_metrics():
    metrics=classification([0,1,0,1],[.5]*4,.5)
    assert metrics['roc_auc']==.5 and metrics['pr_auc']==.5 and metrics['brier_score']==.25
    assert metrics['confusion_matrix']==dict(tn=0,fp=2,fn=0,tp=2)
    assert metrics['calibration'][0]['count']==4
    assert classification([1,1],[.8,.9],.5)['roc_auc'] is None


def test_cost_metrics_do_not_fake_portfolio_path(corpus):
    rows=corpus[3];a=performance(rows);b=performance(rows,cost_multiplier=2)
    assert b['net_pnl']<a['net_pnl'] and a['max_drawdown'] is None and a['time_in_market'] is None
    assert a['max_realized_drawdown'] is not None and day_block_interval(rows)['lower'] is not None
    assert performance([])['net_pnl'] is None


def test_holdout_seal_prevents_retuning(tmp_path):
    ledger=HoldoutLedger(tmp_path);assert ledger.claim({'ids':['a']},{'threshold':.5}) is True
    assert ledger.claim({'ids':['a']},{'threshold':.5}) is False
    with pytest.raises(ResearchError):ledger.claim({'ids':['a']},{'threshold':.6})


def test_saved_trace_skips_no_setup_without_candle_rows():
    traces=[json.loads(s) for s in (ROOT/'docs/restart_diagnostics_observations_2026-10-03/opportunity_traces.jsonl').read_text().splitlines()]
    rows,ignored=from_opportunity_traces(traces);assert rows==[] and len(ignored)==10


def test_snapshot_book_and_funding_clocks(corpus):
    t=corpus[3][0]['decision_ms'];iso=datetime.fromtimestamp((t-100)/1000,timezone.utc).isoformat()
    s=dict(bid=99,ask=101,spread_bps=200,bid_depth_notional=200,ask_depth_notional=100,
           orderbook_timestamp_ms=t-1000,mark_observed_at_ms=t-1000,processed_ts=iso,mark_price=100,oracle_price=100,funding=.0001,open_interest=100)
    features=feature_evidence_from_events([dict(candidate_id='a',market_snapshot=s)])['a']
    assert features['book_imbalance']['value']==pytest.approx(1/3) and features['spread_bps']['value']==200
    assert features['funding_rate']['source_ms']==t-1000 and 'EXCHANGE_TIME_UNKNOWN' in features['funding_rate']['source']
    s['spread_bps']=100
    with pytest.raises(ResearchError):feature_evidence_from_events([dict(candidate_id='a',market_snapshot=s)])


def test_no_execution_or_live_imports_in_research():
    forbidden={'requests','httpx','socket','hyperliquid','exchange.hyperliquid_execution','exchange.hyperliquid_client','live_execution_session','crypto_paper_bot'}
    for path in (ROOT/'algo-trading-bot/research_intelligence').glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):assert not any(n.name in forbidden for n in node.names)
            if isinstance(node,ast.ImportFrom):assert node.module not in forbidden
    assert not hasattr(MetaController,'place_order') and not hasattr(AnchorResearchBrain,'place_order')


def test_insufficient_data_generates_full_honest_matrix(tmp_path):
    traces=[json.loads(s) for s in (ROOT/'docs/restart_diagnostics_observations_2026-10-03/opportunity_traces.jsonl').read_text().splitlines()]
    config=json.loads((ROOT/'research/configurations/anchor_policies.json').read_text())
    out=tmp_path/'run';registry=tmp_path/'registry.jsonl';m=run_research(output=out,registry=registry,traces=traces,anchor_config=config)
    assert m['recommendation']=='MORE_DATA_REQUIRED' and m['quality']['candidate_rows']==0
    assert m['status']['ML_DATA_READY'] is False and m['status']['PRODUCTION_CHANGED'] is False
    assert len(m['matrix'])==4 and all(r['net_pnl'] is None for r in m['matrix'])
    assert (out/'ml/calibration.csv').read_text().count('\n')==1
    with pytest.raises(ResearchError):run_research(output=out,registry=registry,traces=traces)
    attempts=[json.loads(s) for s in registry.read_text().splitlines()];assert attempts[-1]['result']=='FAILED'


def test_complete_synthetic_fit_pipeline_not_promotion(corpus,tmp_path):
    obs,out,assumptions,rows,quality,split=corpus
    m=run_research(output=tmp_path/'synthetic',registry=tmp_path/'registry.jsonl',candidate_observations=obs,outcomes=out,assumptions=assumptions,split=split)
    assert m['status']['ML_DATA_READY'] and m['status']['HOLDOUT_COMPLETE']
    assert not m['status']['ML_MODEL_VALIDATED'] and not m['status']['PROMOTION_RECOMMENDED']
    model=json.loads((tmp_path/'synthetic/ml/model_manifest.json').read_text());assert len(model['models'])==2
    metrics=json.loads((tmp_path/'synthetic/ml/model_metrics.json').read_text())
    for item in metrics['models'].values():
        assert item['holdout']['classification']['rows']==200
        assert item['holdout']['classification']['brier_score']<.3
        assert item['holdout']['per_market_classification']


def test_anchor_source_config_and_absence_not_invented():
    config=json.loads((ROOT/'research/configurations/anchor_policies.json').read_text());p=policies_from_config(config)
    assert set(p)=={'par:SP500','par:EWY','par:EWJ'} and 'par:BRENT' not in p
    assert p['par:EWJ'].anchor_at(datetime(2026,10,4,5,tzinfo=timezone.utc))==datetime(2026,10,4,tzinfo=timezone.utc)


@pytest.mark.parametrize('damage',['missing_availability','received_after_decision','stale','gap','mixed_symbol','left_truncated'])
def test_saved_anchor_observation_rejects_unproven_data(frame,session,damage):
    t=int(frame.Timestamp.iloc[-1].timestamp()*1000)+60000
    candles=[dict(symbol='par:BTC',interval='1m',timestamp_ms=int(r.Timestamp.timestamp()*1000),
        close_timestamp_ms=int(r.Timestamp.timestamp()*1000)+59999,received_timestamp_ms=t,
        open=str(r.Open),high=str(r.High),low=str(r.Low),close=str(r.Close),volume=str(r.Volume)) for r in frame.itertuples()]
    if damage=='missing_availability':candles[0].pop('received_timestamp_ms')
    if damage=='received_after_decision':candles[0]['received_timestamp_ms']=t+1
    if damage=='stale':t+=300000
    if damage=='gap':candles.pop(2)
    if damage=='mixed_symbol':candles[0]['symbol']='par:ETH'
    if damage=='left_truncated':candles=candles[-10:]
    results=anchor_observations([dict(symbol='par:BTC',scan_observed_at_ms=t,candles=candles)],{'par:BTC':session})
    assert len(results)==2 and all(r['status']=='INCONCLUSIVE' for r in results)
    assert all(r['net_pnl'] is None and r['accepted_trades'] is None for r in results)


def test_saved_anchor_moment_not_retroactive_candle_training(frame,session):
    t=int(frame.Timestamp.iloc[-1].timestamp()*1000)+60000
    cs=[dict(symbol='par:BTC',interval='1m',timestamp_ms=int(r.Timestamp.timestamp()*1000),
        close_timestamp_ms=int(r.Timestamp.timestamp()*1000)+59999,received_timestamp_ms=t,
        open=str(r.Open),high=str(r.High),low=str(r.Low),close=str(r.Close),volume=str(r.Volume)) for r in frame.itertuples()]
    obs=dict(symbol='par:BTC',scan_observed_at_ms=t,candles=cs)
    results=anchor_observations([obs],{'par:BTC':session})
    assert len(results)==2 and all(r['decision_ms']==t and r['status']=='SIGNAL_OBSERVATION_ONLY' for r in results)
    with pytest.raises(ResearchError):anchor_observations([obs,obs],{'par:BTC':session})


@pytest.mark.parametrize('damage',['threshold','weights','scale','feature_order','model_type'])
def test_hash_valid_but_invalid_model_schema_not_loaded(fitted,tmp_path,damage):
    m=deepcopy(fitted[0][0]);m.pop('model_version')
    if damage=='threshold':m['threshold']=2
    if damage=='weights':m['parameters']['weights']=[]
    if damage=='scale':m['transform']['scales'][0]=0
    if damage=='feature_order':m['transform']['feature_names'].reverse()
    if damage=='model_type':m['model_type']='DIRECT_PRICE_PREDICTOR'
    m['model_version']=digest(m);p=tmp_path/'bad.json';p.write_text(json.dumps(m))
    assert MetaController.load(p).model is None


def test_stale_features_rechecked_at_scoring(fitted):
    m=fitted[0][0];r=deepcopy(fitted[1]['holdout'][0]);r['decision_ms']+=300000
    result=MetaController(m).score(r);assert result['status']=='ML_UNAVAILABLE' and result['confidence'] is None


def test_valid_saved_candidate_trace_exact_baseline_identity(corpus):
    o=corpus[0][0];t=o['decision_ms']
    trace=dict(candidate_id=o['candidate_id'],symbol=o['symbol'],decision_ms=t,available_at_ms=t,
        signal=dict(timestamp_ms=t-60000,signal_type=o['setup_type'],long=False,short=True,atr=.6,reference=99,bias='NEUTRAL'),
        metrics=dict(close=100,ema9=100,ema21=99,spread_bps=5),stages=dict(FILLED=dict(status='PASS'),RISK_PASS=dict(status='PASS')))
    candidates,ignored=from_opportunity_traces([trace],feature_observations={o['candidate_id']:o['feature_evidence']})
    rows,q=build_dataset(candidates);assert len(rows)==1 and rows[0]['direction']=='SHORT' and rows[0]['anchor_policy_id']=='VWAP_BASELINE_UTC'
    assert ignored==[] and q['usable_labeled_rows']==0


def test_baseline_no_ml_and_heuristic_same_cost_and_split(corpus,tmp_path):
    obs,out,assumptions,_,_,split=corpus
    target=tmp_path/'synthetic';run_research(output=target,registry=tmp_path/'registry.jsonl',candidate_observations=obs,outcomes=out,assumptions=assumptions,split=split)
    metrics=json.loads((target/'ml/model_metrics.json').read_text());segments=metrics['controls']['VWAP_BASELINE_UTC']['segments']
    assert set(segments)=={'train','calibration','validation','holdout'}
    assert segments['holdout']['NO_ML']['evaluated_outcomes']==200
    assert segments['holdout']['NO_ML']['net_pnl']==segments['holdout']['HEURISTIC']['net_pnl']


def test_utc_model_not_silently_used_for_session_anchor(fitted):
    m=fitted[0][0];row=deepcopy(fitted[1]['holdout'][0]);row['anchor_policy_id']='SESSION_RESEARCH_PROGRAM';row['features']['anchor_policy_id']=row['anchor_policy_id']
    assert MetaController(m).score(row)['status']=='ML_UNAVAILABLE'


def test_market_anchor_aggregation_observed_denominators():
    rows=[dict(experiment='UTC_NO_ML',symbol='par:BTC',decision_ms=i,utc_day='2026-10-02',
        status='SIGNAL_OBSERVATION_ONLY' if i<2 else 'INCONCLUSIVE',signal_count=1 if i==0 else 0,
        long_signals=1 if i==0 else 0,short_signals=0,reason='NO_PORTFOLIO_PATH') for i in range(3)]
    r=aggregate_anchors(rows)[0];assert r['observations']==3 and r['eligible_decision_observations']==2 and r['signal_frequency']==.5
    assert r['net_pnl'] is None and r['accepted_trades'] is None
