"""Read-only collection and isolated research; no live or regular PAPER orders.

Uses a fixed, explicitly ex-post two-stock basket. This is not a portfolio or
stock-picker backtest and cannot establish an unbiased universe-selection edge.
"""
import sys,json,logging
from pathlib import Path
from datetime import date
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
import pandas as pd
from historical_data import HistoryContext,ist_timestamp,validate_history
from history_service import HistoryService,OPTIONAL_RVOL
from premarket_screener import find_previous_completed_market_session
from premarket_check import ReadOnlyMarketData
from research_harness import evaluate_manifest
from signal_brain import compute_atr


def evaluate_collected_manifest(manifest, output):
    """Keep missing coverage visible without changing the predetermined split."""
    try:
        comparison = evaluate_manifest(manifest, output)
    except ValueError as exc:
        cases = manifest['sessions']
        reason = str(exc)
        coverage_failure = reason == 'BOTH_RESEARCH_SPLITS_REQUIRED' or (
            reason == 'EXPLICIT_RESEARCH_SPLITS_REQUIRED' and not cases)
        if not coverage_failure:
            raise
        comparison = {
            'research_only': True, 'live_eligible': False,
            'automatic_policy_promotion': False,
            'status': 'BLOCKED_INCOMPLETE_RESEARCH_COVERAGE',
            'reason': reason,
            'regimes_supplied': sorted({c['regime'] for c in cases}),
            'results': [],
        }
    else:
        comparison['status'] = 'COMPLETED_RESEARCH_ONLY'
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'comparison.json').write_text(json.dumps(comparison, indent=2, default=str)+'\n')
    return comparison


def update_evaluation_summary(summary, manifest, comparison, output):
    cases = manifest['sessions']
    summary.update({
        'status': comparison['status'],
        'accepted_cases': len(cases),
        'accepted_distinct_dates': len({c['date'] for c in cases}),
        'accepted_development_cases': sum(c['split'] == 'DEVELOPMENT' for c in cases),
        'accepted_held_out_cases': sum(c['split'] == 'HELD_OUT' for c in cases),
        'regimes_supplied': comparison['regimes_supplied'],
        'full_comparison': str(Path(output)/'comparison.json'),
        'instrument_metadata_basis': 'VERIFIED_CURRENT_BROKER_MASTER; HISTORICAL_TOKEN_CONTINUITY_ASSUMED',
        'results': [{k:v for k,v in r.items() if k != 'cases'} for r in comparison['results']],
    })
    summary.pop('reason', None)
    if comparison['status'] == 'BLOCKED_INCOMPLETE_RESEARCH_COVERAGE':
        summary['basis'] = 'ACTUAL_READ_ONLY_HISTORY_COLLECTION; NO PERFORMANCE CLAIM'
        summary['reason'] = comparison['reason'] + (
            '. The original date split was preserved; incomplete older sessions were '
            'not filled or reassigned to manufacture a valid evaluation.')
    return summary


def main():
    output=ROOT/'algo-trading-bot'/'data'/'research'/'runtime_repair_2026-10-01'
    output.mkdir(parents=True,exist_ok=True)
    from instrument_registry import InstrumentRegistry
    registry=InstrumentRegistry.load(ROOT/'algo-trading-bot'/'data'/'instruments.json',ist_timestamp())
    if '--evaluate-only' in sys.argv:
        manifest=json.loads((output/'manifest.json').read_text())
        for case in manifest['sessions']:
            identity=registry.resolve(case['symbol'],case['token'],ist_timestamp())
            case['tick_size']=identity.tick_size
            case['lot_size']=identity.lot_size
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        logging.getLogger().setLevel(logging.WARNING)
        comparison=evaluate_collected_manifest(manifest,output/'evaluations')
        file=ROOT/'docs'/'runtime_repair_research_evaluation.json'
        summary=json.loads(file.read_text())
        update_evaluation_summary(summary,manifest,comparison,output/'evaluations')
        file.write_text(json.dumps(summary,indent=2,default=str)+'\n')
        print(json.dumps({'report':str(file),'status':summary['status'],
                         'accepted_cases':summary['accepted_cases'],'comparisons':len(summary['results'])}))
        return
    scan=json.loads((ROOT/'docs'/'runtime_repair_warm_scan.json').read_text())
    stocks=[r for r in scan['lineage'] if r['symbol'] in {'RSYSTEMS','RITES'}]
    from live_stream import angel_login
    service=HistoryService(ReadOnlyMarketData(angel_login()))
    reference=date(2026,10,1);days=[]
    for _ in range(20):
        reference=find_previous_completed_market_session(reference)
        days.append(reference)
    days=sorted(days)
    development=set(days[:12]);cases=[];excluded=[]
    for day in days:
        for stock in stocks:
            identity=registry.resolve(stock['symbol'],stock['token'],ist_timestamp())
            context=HistoryContext('NSE',stock['token'],day,stock['symbol'],require_complete=True)
            try:
                frame=service.fetch(context,priority=OPTIONAL_RVOL,timeout=60.)
                validation=validate_history(frame,context)
                if not validation.valid:
                    excluded.append({'date':str(day),'symbol':stock['symbol'],'reason':validation.reason})
                    continue
            except Exception as exc:
                excluded.append({'date':str(day),'symbol':stock['symbol'],'reason':str(exc)})
                continue
            first,last=float(frame.Open.iloc[0]),float(frame.Close.iloc[-1])
            span=float(frame.High.max()-frame.Low.min())
            efficiency=abs(last-first)/span if span else 0.
            trend='STRONG_TREND' if efficiency>=.6 else 'WEAK_TREND' if efficiency>=.25 else 'RANGE'
            direction='DECLINING' if last<first else 'RISING' if last>first else 'FLAT'
            volatility='HIGH_VOL' if float((compute_atr(frame)/frame.Close).median())>=.004 else 'LOW_VOL'
            file=output/f'{stock["symbol"]}_{day}.csv';frame.to_csv(file,index=False)
            cases.append({'date':str(day),'split':'DEVELOPMENT' if day in development else 'HELD_OUT',
                'path':str(file),'symbol':stock['symbol'],'token':stock['token'],'tick_size':identity.tick_size,
                'lot_size':identity.lot_size,
                'provenance':'ANGEL_ONE_VALIDATED_COMPLETE_SESSIONS_CURRENT_TOKEN_MAPPING_FIXED_EX_POST_BASKET',
                'regime':f'{trend}_{direction}_{volatility}'})
            logging.info('[RESEARCH DATA] %s %s %s',stock['symbol'],day,cases[-1]['regime'])
    manifest={'sessions':cases,'policies':[{}, {'name':'CONFIRMATION_3_RESEARCH','standby_confirmations':3,
        'recovery_confirmations':3,'firewall_low_confirmations':3,'firewall_recovery_confirmations':3}]}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    logging.getLogger().setLevel(logging.WARNING)
    comparison=evaluate_collected_manifest(manifest,output/'evaluations')
    summary={'basis':'REAL_CANDLE_RESEARCH_WITH_HYPOTHETICAL_QUOTES_AND_FILL_PATH',
        'fixed_basket':['RSYSTEMS','RITES'],'selection_bias_warning':'EX_POST FIXED BASKET; NOT AN UNBIASED STOCK-PICKER OR PORTFOLIO TEST',
        'requested_dates':[str(d) for d in days],'requested_trading_dates':len(days),
        'requested_symbol_sessions':len(days)*len(stocks),'accepted_cases':len(cases),
        'accepted_distinct_dates':len({c['date'] for c in cases}),'excluded':excluded,
        'excluded_cases':len(excluded),
        'provider_api':dict(service.metrics),'regime_rules':{'strong_trend_efficiency_min':.6,
          'weak_trend_efficiency_min':.25,'high_vol_median_atr_ratio_min':.004},
        'regimes_supplied':comparison['regimes_supplied'],'manifest':str(output/'manifest.json'),
        'full_comparison':str(output/'evaluations'/'comparison.json'),
        'production_pnl_credited':0,'real_orders_submitted':0,'live_eligible':False,
        'results':[]}
    update_evaluation_summary(summary,manifest,comparison,output/'evaluations')
    file=ROOT/'docs'/'runtime_repair_research_evaluation.json'
    file.write_text(json.dumps(summary,indent=2,default=str)+'\n')
    print(json.dumps(summary,indent=2,default=str))


if __name__=='__main__':main()
