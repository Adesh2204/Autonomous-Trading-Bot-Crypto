"""Synthetic engineering fixtures; never genuine research performance evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import ast
import json
import pytest

from research_intelligence.common import ROOT, ResearchError, digest, immutable_json
from research_intelligence.evidence import EvidenceWriter, ReceiptIndex, read_evidence, require_public
from research_lab.forward_lab import RecordedMarket, LabArm, run_forward_lab, PermissionRisk
from research_intelligence.campaign import verified_lab, audited_dataset, seal_campaign, campaign_identity
from research_intelligence.readiness import assess_readiness, paired_day_comparison, save_readiness
from research_intelligence.splits import ChronologicalSplit
from exchange.base_exchange import Candle, ExchangeError
from exchange.hyperliquid_market_data import parse_book
from risk.models import RiskDecision

BASE=int(datetime(2026,10,1,tzinfo=timezone.utc).timestamp()*1000)
NOW=BASE+310*60000+1000
CONFIG=json.loads((ROOT/'docs/paper_policy.example.json').read_text())
SYMBOLS=['par:BRENT','par:BTC','par:ETH','par:EWJ','par:EWY','par:GOLD','par:HYPE','par:SP500','par:USDEUR','par:USDJPY']


def fixture_frame(*,signal=False,now=NOW,price='100',histories=True):
    metadata=dict(collateralToken=20,universe=[dict(name=s,szDecimals=4,maxLeverage=10) for s in SYMBOLS])
    ctx=dict(markPx=price,oraclePx=price,funding='0',openInterest='1',dayNtlVlm='100000')
    books={}; cs={}; raw_cs={}; raw_books={}
    for s in SYMBOLS:
        bid=str(Decimal(price)-Decimal('.01')); ask=str(Decimal(price)+Decimal('.01'))
        raw_books[s]=dict(coin=s,time=now-1000,levels=[[dict(px=bid,sz='1000')],[dict(px=ask,sz='1000')]])
        books[s]=asdict(replace(parse_book(raw_books[s],s),received_timestamp_ms=now-3,processed_timestamp_ms=now-2))
        raw_cs[s]=[]; cs[s]=[]
        if histories:
            for i in range(310):
                p=Decimal('103') if signal and s=='par:BTC' and i==309 else Decimal('100')
                volume='100' if signal and s=='par:BTC' and i==309 else '10'
                t=BASE+i*60000
                raw_cs[s].append(dict(s=s,i='1m',t=t,T=t+59999,o=str(p),h=str(p+1),l=str(p-1),c=str(p),v=volume))
                cs[s].append(asdict(Candle(s,'1m',t,t+59999,p,p+1,p-1,p,Decimal(volume),received_timestamp_ms=now-4,processed_timestamp_ms=now-3)))
    f=dict(decision_ms=now,scan=histories,metadata=metadata,dexes=[None,dict(name='par')],
        books=books,contexts={s:deepcopy(ctx) for s in SYMBOLS},context_times={s:now-5 for s in SYMBOLS},
        histories=cs if histories else {},connected=True,generation=1,unavailable_books={})
    return json.loads(json.dumps(f,default=str)),raw_cs,raw_books


def write_capture(path,*,signal=False,source='SYNTHETIC_TEST_CAPTURE',two_frames=False):
    path.mkdir()
    manifest=dict(schema_version=1,source=source,created_ms=NOW-10,parameters=CONFIG,anchor_config=dict(policies=[]))
    manifest['sha256']=digest(manifest); immutable_json(path/'capture_manifest.json',manifest)
    writer=EvidenceWriter(path/'evidence.jsonl')
    def append_frame(frame,cs,books):
        t=frame['decision_ms']
        writer.append('INFO',dict(request=dict(type='perpDexs'),response=frame['dexes']),t-5)
        writer.append('INFO',dict(request=dict(type='meta',dex='par'),response=frame['metadata']),t-5)
        writer.append('INFO',dict(request=dict(type='metaAndAssetCtxs',dex='par'),response=[frame['metadata'],[frame['contexts'][s] for s in SYMBOLS]]),t-5)
        if frame['histories']:
            for s in SYMBOLS:
                writer.append('INFO',dict(request=dict(type='candleSnapshot',req=dict(coin=s,interval='1m',startTime=BASE,endTime=NOW-1)),response=cs[s]),t-5)
        for s in SYMBOLS: writer.append('INFO',dict(request=dict(type='l2Book',coin=s),response=books[s]),t-3)
        writer.append('FRAME',frame,t)
    f,cs,books=fixture_frame(signal=signal); append_frame(f,cs,books)
    if two_frames:
        f,cs,books=fixture_frame(now=NOW+1000,price='120',histories=False); append_frame(f,cs,books)
    writer.close(path/'capture_completion.json',status='COMPLETE')
    return path


@pytest.fixture
def capture(tmp_path): return write_capture(tmp_path/'capture')


@pytest.fixture
def lab(tmp_path,capture):
    out=tmp_path/'lab'; run_forward_lab(capture,out); return out


@pytest.mark.parametrize('payload',[
    {'type':'order'}, {'type':'userFills','user':'0x'+'1'*40}, {'type':'meta','dex':''},
    {'type':'l2Book','coin':'BTC'}, {'type':'meta','dex':'par','signature':{}},
    {'type':'candleSnapshot','req':{'coin':'par:BTC','interval':'5m','startTime':0,'endTime':1}},
    {'type':'perpDexs','nonce':1}, {'type':'perpDexs','user':'0x'+'1'*40},
    {'type':'meta','dex':'par','action':{}}, {'type':'meta','dex':'native'},
])
def test_recorder_public_boundary(payload):
    with pytest.raises(ResearchError): require_public(payload)


def test_public_query_acceptance():
    require_public(dict(type='meta',dex='par')); require_public(dict(type='perpDexs'))


def test_chain_and_raw_receipts_valid(capture):
    frames=list(read_evidence(capture)); assert len(frames)==1
    assert frames[0][0]['source']=='SYNTHETIC_TEST_CAPTURE'


def test_chain_payload_edit_detected(capture):
    p=capture/'evidence.jsonl'; rows=p.read_text().splitlines(); r=json.loads(rows[0]); r['observed_ms']+=1
    rows[0]=json.dumps(r); p.write_text('\n'.join(rows)+'\n')
    with pytest.raises(ResearchError,match='CHAIN'): list(read_evidence(capture))


def test_chain_truncation_detected(capture):
    p=capture/'evidence.jsonl'; rows=p.read_text().splitlines(); p.write_text('\n'.join(rows[:-1])+'\n')
    with pytest.raises(ResearchError,match='TRUNCATED'): list(read_evidence(capture))


def test_manifest_tamper_detected(capture):
    p=capture/'capture_manifest.json'; r=json.loads(p.read_text()); r['parameters']['risk']['max_daily_setups']=20; p.write_text(json.dumps(r))
    with pytest.raises(ResearchError,match='MANIFEST'): list(read_evidence(capture))


def test_unreceipted_book_even_with_valid_chain(tmp_path):
    path=write_capture(tmp_path/'cap'); rows=[json.loads(s) for s in (path/'evidence.jsonl').read_text().splitlines()]
    rows[-1]['payload']['books']['par:BTC']['bids'][0]['price']='90'
    w=EvidenceWriter(tmp_path/'replacement.jsonl')
    for r in rows: w.append(r['kind'],r['payload'],r['observed_ms'])
    w.close(tmp_path/'completion.json',status='COMPLETE')
    (path/'evidence.jsonl').write_bytes((tmp_path/'replacement.jsonl').read_bytes())
    (path/'capture_completion.json').write_bytes((tmp_path/'completion.json').read_bytes())
    with pytest.raises(ResearchError,match='RAW_RECEIPT'): list(read_evidence(path))


@pytest.mark.parametrize('field', ['context','book','candle'])
def test_future_availability_rejected(field):
    f,cs,books=fixture_frame(); idx=ReceiptIndex()
    if field=='context': f['context_times']['par:BTC']=NOW+1
    elif field=='book': f['books']['par:BTC']['received_timestamp_ms']=NOW+1
    else: f['histories']['par:BTC'][0]['received_timestamp_ms']=NOW+1
    for typ,response,request in [('perpDexs',f['dexes'],dict(type='perpDexs')),('meta',f['metadata'],dict(type='meta',dex='par')),
        ('metaAndAssetCtxs',[f['metadata'],[f['contexts'][s] for s in SYMBOLS]],dict(type='metaAndAssetCtxs',dex='par'))]:
        idx.add(dict(kind='INFO',observed_ms=NOW-5,payload=dict(request=request,response=response)))
    for s in SYMBOLS:
        idx.add(dict(kind='INFO',observed_ms=NOW-5,payload=dict(request=dict(type='candleSnapshot',req=dict(coin=s,interval='1m',startTime=BASE,endTime=NOW-1)),response=cs[s])))
        idx.add(dict(kind='INFO',observed_ms=NOW-3,payload=dict(request=dict(type='l2Book',coin=s),response=books[s])))
    with pytest.raises(ResearchError): idx.verify(f)


def test_no_ml_reference_arms_are_not_treated_as_ml(lab):
    m=verified_lab(lab)
    for name in ('UTC_NO_ML','SESSION_NO_ML'):
        assert m['portfolios'][name]['status']=='LOCAL_PAPER_OBSERVED_PATH'
        assert m['portfolios'][name]['comparison_eligible'] is True
    for name in ('UTC_ML','SESSION_ML'):
        assert m['portfolios'][name]['status']=='ML_UNAVAILABLE'
        assert m['portfolios'][name]['comparison_eligible'] is False


def test_four_reference_inputs_same_no_global_brain_patch(lab):
    import signal_brain
    assert signal_brain.generate_vwap_signal.__module__=='signal_brain'
    utc=json.loads((lab/'UTC_NO_ML/scans.jsonl').read_text())
    session=json.loads((lab/'SESSION_NO_ML/scans.jsonl').read_text())
    assert utc==session


def test_recorded_market_cannot_read_exchange_or_user():
    f,_,_=fixture_frame(); market=RecordedMarket(f)
    with pytest.raises(ResearchError): market._info(dict(type='userFees',user='0x'+'1'*40))
    with pytest.raises(ResearchError): market._info(dict(action='order'))


def test_missing_book_and_old_context_fail_safe():
    f,_,_=fixture_frame(); m=RecordedMarket(f); f['books'].pop('par:BTC'); m.update(f)
    with pytest.raises(ExchangeError,match='NO_EXECUTABLE'): m.get_quote('par:BTC')
    f,_,_=fixture_frame(); f['context_times']['par:BTC']=NOW-60001; m.update(f)
    with pytest.raises(ExchangeError,match='CONTEXT_STALE'): m.get_quote('par:BTC')


def test_existing_kernel_entry_exit_and_audited_aftercost_label(tmp_path):
    cap=write_capture(tmp_path/'cap',signal=True,two_frames=True)
    out=tmp_path/'lab'; result=run_forward_lab(cap,out)
    assert result['portfolios']['UTC_NO_ML']['closed_trades']==1
    assert result['portfolios']['SESSION_NO_ML']['closed_trades']==1
    assert result['portfolios']['UTC_ML']['closed_trades']==0
    outcomes=json.loads((out/'UTC_NO_ML/outcomes.json').read_text())
    assert len(outcomes)==1
    o=next(iter(outcomes.values())); assert o['gross_result']>0 and o['fees']>0 and o['slippage']==0
    assert o['entry_fill_ids'] and o['exit_fill_ids'] and o['label_audit_hash']
    assert result['portfolios']['UTC_NO_ML']['net_pnl']==pytest.approx(o['gross_result']-o['fees'])
    assert result['portfolios']['UTC_NO_ML']['time_in_market']==1
    verified_lab(out)


def test_stale_exit_tick_does_not_invent_fill():
    f,_,_=fixture_frame(signal=True); arm=LabArm('UTC_NO_ML',RecordedMarket(f),CONFIG,{})
    arm.step(f); assert len(arm.execution.fills)==1
    stale,_,_=fixture_frame(now=NOW+7000,price='120',histories=False)
    for s in stale['books']: stale['books'][s]['timestamp_ms']=NOW-1000
    arm.step(stale)
    assert len(arm.execution.fills)==1 and arm.faults
    assert arm.export()[1]=={}


def test_reconnect_and_gap_pause_new_entries():
    f,_,_=fixture_frame(); arm=LabArm('UTC_NO_ML',RecordedMarket(f),CONFIG,{})
    arm.step(f); f['decision_ms']+=6000; f['generation']=2; arm.step(f)
    assert any('OBSERVATION_GAP' in e['reason'] for e in arm.faults)
    assert arm.bot.breakers.entry_reasons('par:BTC')


def test_risk_veto_preserves_baseline_denial_and_geometry():
    denied=RiskDecision(False,('BASELINE_DENIED',))
    baseline=SimpleNamespace(policy=SimpleNamespace(),last_audit={},assess=lambda *a,**k:denied)
    p=PermissionRisk(baseline,'ML',{}); assert p.assess(None,None,None,None,None,None,None,NOW)==denied
    allowed=RiskDecision(True,(),Decimal('1'),Decimal('90'),Decimal('110'))
    baseline.assess=lambda *a,**k:allowed
    p=PermissionRisk(baseline,'NO_ML',{}); assert p.assess(None,None,None,None,None,None,None,NOW)==allowed
    p=PermissionRisk(baseline,'ML',{}); r=p.assess(SimpleNamespace(symbol='par:BTC'),None,None,None,None,None,None,NOW)
    assert not r.allowed and r.quantity==allowed.quantity and r.stop==allowed.stop and r.target==allowed.target


def test_lab_artifact_tamper_detected(lab):
    (lab/'UTC_NO_ML/equity.jsonl').write_text('{}\n')
    with pytest.raises(ResearchError,match='MODIFIED'): verified_lab(lab)


def test_synthetic_fixture_cannot_make_real_data_ready(lab):
    with pytest.raises(ResearchError,match='GENUINE'): audited_dataset([lab])


def test_small_public_labelled_fixture_insufficient_and_not_double_counted(tmp_path):
    cap=write_capture(tmp_path/'cap',signal=True,two_frames=True,source='PUBLIC_TESTNET_PAR_FORWARD_CAPTURE')
    out=tmp_path/'lab'; run_forward_lab(cap,out)
    rows,q,*_=audited_dataset([out]); assert len(rows)==1 and q['usable_labeled_rows']==1
    with pytest.raises(ResearchError,match='DUPLICATE'): audited_dataset([out,out])
    r=assess_readiness([out]); assert not r['status']['ML_DATA_READY']
    assert all(not r['status'][k] for k in ('HOLDOUT_COMPLETE','ML_MODEL_VALIDATED','PROMOTION_RECOMMENDED','PRODUCTION_CHANGED'))
    assert r['collection_capacity']['optimistic_days_for_500_completed_trades']==250
    status=tmp_path/'status'; save_readiness(r,status); assert (status/'readiness.md').exists()


def test_seal_refuses_past_holdout(tmp_path,lab):
    split=ChronologicalSplit(NOW-10000,NOW-1000,NOW-5000)
    with pytest.raises(ResearchError,match='PRECEDE'): seal_campaign([lab],tmp_path/'seal',split=split,holdout_end_ms=NOW+1,now_ms=NOW)


def test_seal_insufficient_explicit_gate_no_models(tmp_path):
    cap=write_capture(tmp_path/'cap',source='PUBLIC_TESTNET_PAR_FORWARD_CAPTURE'); out=tmp_path/'lab';run_forward_lab(cap,out)
    split=ChronologicalSplit(NOW+1000,NOW+3000,NOW+2000)
    result=seal_campaign([out],tmp_path/'seal',split=split,holdout_end_ms=NOW+4000,now_ms=NOW)
    assert result['status']=='MORE_DATA_REQUIRED'; assert not (tmp_path/'seal/sealed_campaign.json').exists()
    assert not result['models']


def daily_series(delta=0,days=20):
    rows=[]
    for i in range(days):
        rows.extend([dict(timestamp_ms=BASE+i*86400000+1000,equity=20000+i*delta),
                     dict(timestamp_ms=BASE+(i+1)*86400000-1000,equity=20000+(i+1)*delta)])
    return rows


def test_paired_day_bootstrap_positive_difference():
    result=paired_day_comparison(daily_series(),daily_series(2))
    assert result['passed'] and result['lower_95']==2 and result['complete_days']==20


def test_identical_or_losing_session_not_improvement():
    assert not paired_day_comparison(daily_series(),daily_series())['passed']
    assert not paired_day_comparison(daily_series(),daily_series(-1))['passed']


def test_paired_missing_times_and_partial_days():
    assert not paired_day_comparison(daily_series(),daily_series()[:-1])['passed']
    assert not paired_day_comparison(daily_series(days=19),daily_series(1,days=19))['passed']
    assert paired_day_comparison([dict(timestamp_ms=NOW,equity=20000)],[dict(timestamp_ms=NOW,equity=20000)])['complete_days']==0


def test_no_production_research_import_or_signed_transport():
    modules=['evidence.py','campaign.py','readiness.py']
    for name in modules:
        tree=ast.parse((ROOT/'algo-trading-bot/research_intelligence'/name).read_text())
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any('hyperliquid_execution' in n or 'signed' in n for n in imports)
    for name in ['crypto_paper_bot.py','signal_brain.py','market_regime_scanner.py','risk/portfolio_risk.py']:
        assert 'research_intelligence' not in (ROOT/'algo-trading-bot'/name).read_text()


def test_source_seal_covers_collector_and_management():
    paths=campaign_identity()['file_sha256']
    for path in ('scripts/collect_research_evidence.py','scripts/run_research_readiness.py','algo-trading-bot/crypto_paper_bot.py',
                 'algo-trading-bot/crypto_strategy_state.py','algo-trading-bot/exchange/paper_portfolio.py'):
        assert path in paths

def test_history_deltas_merge_and_retain_bounded_completed_window():
    f,_,_=fixture_frame(); f['history_limit']=310; m=RecordedMarket(f)
    delta=deepcopy(f); delta['decision_ms']=NOW+60000; delta['history_mode']='APPEND'
    for s in SYMBOLS:
        last=deepcopy(f['histories'][s][-1]); last['timestamp_ms']+=60000; last['close_timestamp_ms']+=60000
        last['received_timestamp_ms']=NOW+60000-4
        delta['histories'][s]=[last]
    m.update(delta)
    assert len(m.histories['par:BTC'])==310
    assert m.histories['par:BTC'][-1].timestamp_ms==BASE+310*60000
    assert m.histories['par:BTC'][0].timestamp_ms==BASE+60000


def test_receipt_cache_preserves_earliest_proof_for_identical_update():
    index={}; ReceiptIndex.remember(index,'value',10,2); ReceiptIndex.remember(index,'value',20,2)
    assert index['value']==10
    ReceiptIndex.remember(index,'other',30,2); ReceiptIndex.remember(index,'third',40,2)
    assert len(index)==2


def test_observation_clock_regression_fails_before_append(tmp_path):
    w=EvidenceWriter(tmp_path/'tape'); w.append('HEALTH',{},20)
    with pytest.raises(ResearchError,match='REGRESSED'): w.append('HEALTH',{},19)
    w.close(tmp_path/'completion',status='COMPLETE')


def test_positive_training_seal_uses_only_earlier_data_and_refuses_model_edit(tmp_path,monkeypatch):
    # Synthetic corpus tests training/sealing code only; filesystem provenance
    # admission is deliberately stubbed. Artifacts remain in pytest's temp dir.
    from test_research_intelligence import corpus
    from research_intelligence import campaign
    obs,out,assumptions,rows,q,split=corpus.__wrapped__()
    earlier=[r for r in rows if r['decision_ms']<split.holdout_start_ms]
    monkeypatch.setattr(campaign,'audited_dataset',lambda labs:(earlier,q,assumptions,dict(policies=[]),[]))
    result=seal_campaign([],tmp_path/'seal',split=split,holdout_end_ms=split.holdout_start_ms+30*86400000,
                         now_ms=split.holdout_start_ms-1)
    assert result['state']=='SEALED_RESEARCH' and result['activation_authorized'] is False
    c,controllers=campaign.load_campaign(tmp_path/'seal')
    model=controllers['VWAP_BASELINE_UTC'].model
    all_fit=set(model['transform']['fit_candidate_ids']+model['calibration']['fit_candidate_ids']+model['threshold_candidate_ids'])
    assert not all_fit.intersection(r['candidate_id'] for r in rows if r['decision_ms']>=split.holdout_start_ms)
    model_path=tmp_path/'seal'/result['models']['VWAP_BASELINE_UTC']['path']
    modified=json.loads(model_path.read_text());modified['threshold']=.01;model_path.write_text(json.dumps(modified))
    with pytest.raises(ResearchError,match='MODIFIED'): campaign.load_campaign(tmp_path/'seal')


def test_already_seen_holdout_rejected_even_with_sufficient_data(tmp_path,monkeypatch):
    from test_research_intelligence import corpus
    from research_intelligence import campaign
    obs,out,assumptions,rows,q,split=corpus.__wrapped__()
    monkeypatch.setattr(campaign,'audited_dataset',lambda labs:(rows,q,assumptions,dict(policies=[]),[]))
    with pytest.raises(ResearchError,match='ALREADY_OBSERVED'):
        seal_campaign([],tmp_path/'seal',split=split,holdout_end_ms=split.holdout_start_ms+30*86400000,
                      now_ms=split.holdout_start_ms-1)


def test_sealed_source_edit_rejected(tmp_path,monkeypatch):
    from test_research_intelligence import corpus
    from research_intelligence import campaign
    obs,out,assumptions,rows,q,split=corpus.__wrapped__()
    earlier=[r for r in rows if r['decision_ms']<split.holdout_start_ms]
    monkeypatch.setattr(campaign,'audited_dataset',lambda labs:(earlier,q,assumptions,dict(policies=[]),[]))
    seal_campaign([],tmp_path/'seal',split=split,holdout_end_ms=split.holdout_start_ms+30*86400000,
                  now_ms=split.holdout_start_ms-1)
    monkeypatch.setattr(campaign,'campaign_identity',lambda:dict(source_hash='changed'))
    with pytest.raises(ResearchError,match='SOURCE_CHANGED'): campaign.load_campaign(tmp_path/'seal')


def test_recorder_does_not_relabel_preclose_websocket_update_as_completed(monkeypatch):
    import sys
    sys.path.insert(0,str(ROOT/'scripts'))
    from collect_research_evidence import CaptureEngine
    from exchange.hyperliquid_market_data import ParMarketDataEngine
    bar=fixture_frame()[0]['histories']['par:BTC'][-1]
    c=Candle(**{k:Decimal(v) if k in {'open','high','low','close','volume'} else v for k,v in bar.items()})
    monkeypatch.setattr(ParMarketDataEngine,'get_completed_candles',lambda self,symbol:[replace(c,received_timestamp_ms=c.timestamp_ms+50000),c])
    engine=object.__new__(CaptureEngine)
    assert CaptureEngine.get_completed_candles(engine,'par:BTC')==[c]

def test_research_scanner_uses_exact_baseline_window_for_all_other_logic():
    import numpy as np
    import pandas as pd
    from research_intelligence.anchors import VWAPAnchorPolicy
    from market_regime_scanner import MarketRegimeScanner,ScannerPolicy
    from frozen_strategy import FrozenStrategy
    from candle_normalizer import candles_to_frame
    f,_,_=fixture_frame()
    # Three complete days supply a non-UTC reference while the production
    # scanner still asks for its original UTC/300-bar window.
    f['histories']['par:BTC']=[]
    rng=np.random.default_rng(21); prices=100+np.cumsum(rng.normal(0,.1,3000))
    for i,p in enumerate(prices):
        t=BASE-2690*60000+i*60000
        f['histories']['par:BTC'].append(dict(symbol='par:BTC',interval='1m',timestamp_ms=t,close_timestamp_ms=t+59999,
            open=str(p),high=str(p+1),low=str(p-1),close=str(p),volume='10',
            received_timestamp_ms=NOW-4,processed_timestamp_ms=NOW-3))
    market=RecordedMarket(f)
    baseline=MarketRegimeScanner(market,ScannerPolicy(**CONFIG['scanner']))
    reference=baseline.scan()
    utc=LabArm('UTC_NO_ML',RecordedMarket(f),CONFIG,{})
    actual=utc.scanner.scan()
    assert [c.timestamp_ms for c in actual.diagnostics[1].candles]==[c.timestamp_ms for c in reference.diagnostics[1].candles]
    assert actual.diagnostics[1].signal==reference.diagnostics[1].signal
    policy=VWAPAnchorPolicy('TEST_REFERENCE','par:BTC','ASSET_SESSION_ANCHOR','UTC','12:00','SYNTHETIC_FIXTURE','Test only')
    arm=LabArm('SESSION_NO_ML',RecordedMarket(f),CONFIG,{'par:BTC':policy})
    alternate=arm.scanner.scan()
    a=next(d for d in alternate.diagnostics if d.symbol=='par:BTC')
    b=next(d for d in reference.diagnostics if d.symbol=='par:BTC')
    assert [c.timestamp_ms for c in a.candles]==[c.timestamp_ms for c in b.candles]
    changed=arm.brain.evaluate_candles(a.candles)
    unchanged=FrozenStrategy(market).evaluate_candles(b.candles)
    for col in ('EMA_9','EMA_21','ATR_14','Vol_MA10','Timestamp','Close'):
        pd.testing.assert_series_equal(changed[col],unchanged[col])
    assert not changed.VWAP.equals(unchanged.VWAP)

def test_incremental_rest_finalization_records_after_close_without_synthetic_gap_fill(monkeypatch):
    import sys,threading
    from collections import defaultdict
    sys.path.insert(0,str(ROOT/'scripts'))
    from collect_research_evidence import CaptureEngine
    f,_,_=fixture_frame()
    raw=f['histories']['par:BTC'][-1]
    c=Candle(**{k:Decimal(v) if k in {'open','high','low','close','volume'} else v for k,v in raw.items()})
    engine=object.__new__(CaptureEngine);engine._lock=threading.RLock();engine.recovery_generation=1
    engine.connected=engine.reconciled=True;engine.symbols=('par:BTC',);engine.history_bars=3000;engine.candles=defaultdict(dict)
    engine.market=SimpleNamespace(get_candles=lambda *a,**k:[c])
    assert engine.finalize_completed(threading.Event(),NOW)==1
    assert engine.candles['par:BTC'][c.timestamp_ms]==c


def test_human_readable_split_dates_require_timezone():
    import sys
    sys.path.insert(0,str(ROOT/'scripts'))
    from run_research_readiness import timestamp_value
    assert timestamp_value('2026-10-01T00:00:00Z')==BASE
    with pytest.raises(ResearchError): timestamp_value('2026-10-01T00:00:00')

def test_raw_source_tamper_after_lab_export_still_prevents_training(lab):
    manifest=json.loads((lab/'lab_manifest.json').read_text())
    source=__import__('pathlib').Path(manifest['source_capture'])/'evidence.jsonl'
    source.write_text(source.read_text()+'{}\n')
    with pytest.raises((ResearchError,KeyError)): verified_lab(lab)
