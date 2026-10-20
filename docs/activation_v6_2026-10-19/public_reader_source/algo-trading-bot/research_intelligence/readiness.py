"""Evidence-derived flags, paired portfolio comparisons and honest next steps."""
from collections import Counter
from pathlib import Path
import json
import time
import numpy as np
from .common import ROOT, ResearchError, digest, immutable_json, utc_day
from .campaign import audited_dataset, required_policies, verified_lab, read_lines, load_campaign
from .dataset import build_dataset
from .experiment import data_gate
from .models import evaluate_model
from strategy_freeze import verify_strategy_freeze


def paired_day_comparison(reference, alternative, *, min_days=20, seed=20261004):
    """Compare complete matched UTC days. Never pad absent days with zero P&L."""
    left={r['timestamp_ms']:r for r in reference}; right={r['timestamp_ms']:r for r in alternative}
    if set(left)!=set(right): return dict(passed=False,reason='PORTFOLIO_OBSERVATION_TIMES_NOT_MATCHED',complete_days=0)
    days={}
    for t in sorted(left): days.setdefault(t//86400000,[]).append(t)
    deltas=[]; daily=[]
    for day,ts in sorted(days.items()):
        start=day*86400000; end=start+86400000
        if ts[0]-start>5000 or end-ts[-1]>5000: continue
        a,b=ts[0],ts[-1]
        l=float(left[b]['equity'])-float(left[a]['equity']); r=float(right[b]['equity'])-float(right[a]['equity'])
        daily.append(dict(utc_day=utc_day(a),reference_net_change=l,alternative_net_change=r,difference=r-l))
        deltas.append(r-l)
    result=dict(passed=False,complete_days=len(deltas),daily=daily,lower_95=None,upper_95=None,
        method='Prespecified paired UTC day-block bootstrap, 1000 resamples; sampled marks and first/last partial days excluded.',
        scope='Local paper evidence, not a guarantee of future returns or an official score')
    if len(deltas)<min_days: return dict(result,reason='MORE_COMPLETE_MATCHED_DAYS_REQUIRED')
    rng=np.random.default_rng(seed)
    means=np.mean(rng.choice(np.asarray(deltas),size=(1000,len(deltas)),replace=True),axis=1)
    result.update(lower_95=float(np.quantile(means,.025)),upper_95=float(np.quantile(means,.975)),
                  passed=float(np.quantile(means,.025))>0,mean_daily_difference=float(np.mean(deltas)),
                  reason='POSITIVE_AFTER_COST_DIFFERENCE' if np.quantile(means,.025)>0 else 'IMPROVEMENT_NOT_ESTABLISHED')
    return result


def assess_readiness(labs, *, campaign_directory=None, now_ms=None):
    defaults=json.loads((ROOT/'research/configurations/experiment_defaults.json').read_text())
    rows,quality,assumptions,anchors,sources=audited_dataset(labs)
    checks={}
    for policy in required_policies(anchors):
        group=[r for r in rows if r['scoring_ready'] and r['label'] is not None and r['anchor_policy_id']==policy]
        counts=dict(usable_labeled_rows=len(group),labeled_dates=sorted({r['utc_day'] for r in group}),
            labeled_markets=sorted({r['symbol'] for r in group}),positive_outcomes=sum(r['label']==1 for r in group),
            negative_outcomes=sum(r['outcome']['net_result']<0 for r in group),
            directions={d:sum(r['direction']==d for r in group) for d in ('LONG','SHORT')})
        floor=dict(defaults,minimum_labeled_markets=3 if policy=='VWAP_BASELINE_UTC' else 1)
        checks[policy]=dict(**data_gate(counts,floor),counts=counts,
            remaining=dict(labeled_candidates=max(0,500-len(group)),labeled_days=max(0,20-len(counts['labeled_dates'])),
                positive=max(0,100-counts['positive_outcomes']),negative=max(0,100-counts['negative_outcomes'])),
            market_floor_scope='UTC cross-asset domain: three markets; each declared single-asset session domain: its one asset')
    verified=verify_strategy_freeze()
    flags=dict(BASELINE_PRESERVED=True,VWAP_RESEARCH_READY=True,SESSION_ANCHOR_VALIDATED=False,
        ML_DATA_READY=all(g['status']=='ELIGIBLE_FOR_RESEARCH_FIT' for g in checks.values()),
        ML_MODEL_VALIDATED=False,HOLDOUT_COMPLETE=False,PROMOTION_RECOMMENDED=False,PRODUCTION_CHANGED=False)
    classifications={}; comparisons={}; holdout=dict(status='NOT_SEALED',reasons=['Fit and seal models before a future evaluation window.'])
    if campaign_directory:
        campaign,controllers=load_campaign(campaign_directory)
        flags['ML_DATA_READY']=True  # The sealed earlier training domains passed admission.
        if digest(assumptions)!=digest(campaign['assumptions']) or digest(anchors)!=digest(campaign['anchor_config']):
            raise ResearchError('HOLDOUT_ASSUMPTIONS_CHANGED')
        if len(labs)!=1: raise ResearchError('ONE_CONTINUOUS_HOLDOUT_LAB_REQUIRED')
        lab=verified_lab(labs[0]); start=campaign['split']['holdout_start_ms']; end=campaign['holdout_end_ms']
        if lab['evaluation_start_ms']!=start or lab.get('evaluation_end_ms')!=end:
            raise ResearchError('HOLDOUT_WINDOW_NOT_MATCHED')
        if lab['models']!={k:v['version'] for k,v in campaign['models'].items()}: raise ResearchError('HOLDOUT_MODEL_SET_CHANGED')
        reasons=[]; now=time.time_ns()//1000000 if now_ms is None else now_ms
        if now<end: reasons.append('FUTURE_HOLDOUT_WINDOW_STILL_OPEN')
        series={arm:read_lines(Path(labs[0])/arm/'equity.jsonl') for arm in lab['portfolios']}
        for arm,samples in series.items():
            metric=lab['portfolios'][arm]
            if not samples or samples[0]['timestamp_ms']>start+5000 or samples[-1]['timestamp_ms']<end-5000:
                reasons.append(arm+':INCOMPLETE_WINDOW_COVERAGE')
            if metric['faults'] or metric['status'] in {'INCOMPLETE_EVIDENCE_PATH','ML_UNAVAILABLE'}:
                reasons.append(arm+':INCOMPLETE_PORTFOLIO_EVIDENCE')
        for policy,controller in controllers.items():
            group=[r for r in rows if r['label'] is not None and r['scoring_ready'] and r['anchor_policy_id']==policy
                and start<=r['decision_ms']<end and r['outcome_end_ms']<end]
            # UTC reference rows from both no-ML arms share hypotheses for
            # unconfigured markets. Score each UTC candidate once.
            if policy=='VWAP_BASELINE_UTC': group=[r for r in group if r['candidate_id'].startswith('UTC_NO_ML:')]
            if len(group)<defaults['minimum_holdout'] or any(sum(r['label']==c for r in group)<defaults['minimum_class_per_partition'] for c in (0,1)):
                reasons.append(policy+':MORE_HELD_OUT_LABELED_CANDIDATES_REQUIRED')
            metrics=evaluate_model(group,controller.model)
            classm=metrics['classification']; prior=campaign['models'][policy]['train_positive_fraction']
            null_brier=float(np.mean([(prior-r['label'])**2 for r in group])) if group else None
            classifications[policy]=dict(metrics=metrics,training_prior_brier=null_brier,
                passed=bool(classm['roc_auc'] is not None and classm['roc_auc']>.5 and null_brier is not None
                    and classm['brier_score']<null_brier and metrics['accepted_candidates']>=20))
        flags['HOLDOUT_COMPLETE']=not reasons
        holdout=dict(status='COMPLETE' if not reasons else 'INCOMPLETE',reasons=reasons,start_ms=start,end_ms=end,
                     models_sealed_before_window=True,holdout_used_for_tuning=False)
        for left,right in (('UTC_NO_ML','SESSION_NO_ML'),('UTC_NO_ML','UTC_ML'),('SESSION_NO_ML','SESSION_ML'),('UTC_NO_ML','SESSION_ML')):
            comparison=paired_day_comparison(series[left],series[right]); a=lab['portfolios'][left]; b=lab['portfolios'][right]
            risk_ok=a['max_drawdown'] is not None and b['max_drawdown'] is not None and b['max_drawdown']<=a['max_drawdown']+1e-12
            stress_ok=bool(b.get('cost_sensitivity') and b['cost_sensitivity'][-1]['stressed_net_pnl']>0)
            closed_ok=min(a['closed_trades'],b['closed_trades'])>=defaults['minimum_holdout']
            comparison.update(risk_not_worse=risk_ok,analytical_double_fee_and_10bps_stress_positive=stress_ok,
                completed_trade_floor_passed=closed_ok,passed=comparison['passed'] and risk_ok and stress_ok and closed_ok and flags['HOLDOUT_COMPLETE'])
            comparisons[left+'_VS_'+right]=comparison
        flags['SESSION_ANCHOR_VALIDATED']=comparisons['UTC_NO_ML_VS_SESSION_NO_ML']['passed']
        flags['ML_MODEL_VALIDATED']=all(r['passed'] for r in classifications.values()) and comparisons['UTC_NO_ML_VS_UTC_ML']['passed'] and comparisons['SESSION_NO_ML_VS_SESSION_ML']['passed']
        flags['PROMOTION_RECOMMENDED']=all(flags[k] for k in ('SESSION_ANCHOR_VALIDATED','ML_MODEL_VALIDATED','HOLDOUT_COMPLETE')) and comparisons['UTC_NO_ML_VS_SESSION_ML']['passed']
    diagnostic_counts=Counter()
    for lab in labs:
        for scan in read_lines(Path(lab)/'UTC_NO_ML/scans.jsonl'):
            for d in scan['diagnostics']:
                diagnostic_counts.update(d['reasons'] or ['QUALIFIED'])
    recommendations=[dict(step=1,action='Collect continuous public par receipts with fresh candles, BBO and mark/context clocks; investigate stale-market diagnostics.'),
        dict(step=2,action='Run the four independent paper portfolios; preserve scanner/risk/cooldown limits and audit every completed trade.'),
        dict(step=3,action='Accumulate adequate labeled evidence in each declared anchor domain. Never combine repeated replays into new data.'),
        dict(step=4,action='Choose explicit earlier train/calibration/validation dates and a future holdout, then seal model artifacts before it begins.'),
        dict(step=5,action='Record the complete future holdout; replay all four arms with the sealed models and inspect costs, drawdown and paired days.'),
        dict(step=6,action='Accept only evidence-supported improvements; retain the UTC deterministic baseline if alternatives do not beat it.'),
        dict(step=7,action='A promotion recommendation is a review proposal. Production activation still requires the existing explicit human verification process.')]
    return dict(schema_version=1,status=flags,quality=quality,data_readiness_by_policy=checks,source_labs=sources,
        holdout=holdout,classification_validation=classifications,portfolio_comparisons=comparisons,
        current_baseline_diagnostics=dict(diagnostic_counts),recommendation='PROMOTION_REVIEW_ONLY' if flags['PROMOTION_RECOMMENDED'] else 'MORE_EVIDENCE_REQUIRED',
        collection_capacity=dict(baseline_max_new_setups_per_day=assumptions['risk']['max_daily_setups'],
            optimistic_days_for_500_completed_trades=math_ceil(500/assumptions['risk']['max_daily_setups']),
            note='The 2-setups/day reference portfolio cannot yield 500 completed unique trades in a few weeks. Multiple arms/replays must not inflate the UTC sample. Historical candles alone cannot supply executable outcomes.'),
        next_steps=recommendations,exchange_orders_submitted=0,production_changed=False,
        meaning=dict(SESSION_ANCHOR_VALIDATED='Documented session hypothesis has adequate prospective, paired after-cost portfolio evidence.',
            ML_DATA_READY='Each model domain has enough genuine audited candidate labels and diversity.',
            ML_MODEL_VALIDATED='Sealed numerical models improve held-out calibration/classification and their independent portfolios pass risk/cost comparisons.',
            HOLDOUT_COMPLETE='The prespecified future window has ended, is fully observed, and has adequate audited labels.',
            PROMOTION_RECOMMENDED='A proposal for human review; it grants no exchange-write permission.',
            PRODUCTION_CHANGED='Must remain FALSE in this research task.'))


def math_ceil(value): return int(np.ceil(value))


def save_readiness(report, output):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    report=dict(report,sha256=digest(report)); immutable_json(output/'readiness.json',report)
    text=['# Anchorium research readiness','', 'These flags are derived from saved evidence. PAPER mode and the live-order lock remain enforced.','',
        '| Flag | Value | Meaning |','|---|---|---|']
    for key,value in report['status'].items(): text.append(f'| `{key}` | `{str(value).upper()}` | {report.get("meaning",{}).get(key,"Protected baseline and isolated research mechanisms.")} |')
    text+=['','## Data remaining','', '| Model domain | Labeled candidates | Labeled dates | Remaining candidates | Remaining dates |','|---|---:|---:|---:|---:|']
    for key,value in report['data_readiness_by_policy'].items():
        text.append(f'| {key} | {value["counts"]["usable_labeled_rows"]} | {len(value["counts"]["labeled_dates"])} | {value["remaining"]["labeled_candidates"]} | {value["remaining"]["labeled_days"]} |')
    text+=['','## Collection constraint','',report['collection_capacity']['note'],'','## Next steps','']
    text += [str(r['step'])+'. '+r['action'] for r in report['next_steps']]
    text+=['','## Current scan blockers','',json.dumps(report['current_baseline_diagnostics'],indent=2), '',
        'Results describe local paper research. No competition rank or future profit is guaranteed.']
    (output/'readiness.md').write_text('\n'.join(text)+'\n')
