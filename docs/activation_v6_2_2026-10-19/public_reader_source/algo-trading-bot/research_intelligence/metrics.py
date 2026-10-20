"""Classification/calibration and conditional, after-cost outcome evidence.

Candidate outcome subsets are not alternative portfolios. Missing mark-equity,
time-in-market or returns cannot be fabricated from their completion P&L.
"""
from collections import defaultdict
import math
import numpy as np
from .common import ResearchError, finite, utc_day


def classification(labels, probabilities, threshold):
    if len(labels)!=len(probabilities): raise ResearchError('METRIC_LENGTH_MISMATCH')
    if not len(labels): return dict(rows=0,precision=None,recall=None,roc_auc=None,pr_auc=None,brier_score=None,confusion_matrix=None,acceptance_rate=None,calibration=[])
    y=np.asarray(labels,dtype=int);p=np.asarray(probabilities,dtype=float)
    if not np.isin(y,[0,1]).all() or not np.isfinite(p).all() or np.any((p<0)|(p>1)): raise ResearchError('INVALID_CLASSIFICATION_INPUT')
    pred=p>=threshold;tp=int(np.sum(pred & (y==1)));fp=int(np.sum(pred & (y==0)));tn=int(np.sum(~pred & (y==0)));fn=int(np.sum(~pred & (y==1)))
    positives=int(y.sum());negatives=len(y)-positives
    # Mann-Whitney rank AUC with exact ties; no arbitrary order-based tie advantage.
    auc=None
    if positives and negatives:
        order=np.argsort(p,kind='stable');ranks=np.zeros(len(y));i=0
        while i<len(y):
            j=i+1
            while j<len(y) and p[order[j]]==p[order[i]]:j+=1
            ranks[order[i:j]]=(i+1+j)/2;i=j
        auc=float((ranks[y==1].sum()-positives*(positives+1)/2)/(positives*negatives))
    # Average precision by tied-score groups, matching non-interpolated PR area.
    ap=None
    if positives:
        ordered=sorted(set(p),reverse=True);last_recall=0;ap=0
        for score in ordered:
            mask=p>=score;t=int(np.sum(mask & (y==1)));rec=t/positives
            ap+=(rec-last_recall)*t/int(mask.sum());last_recall=rec
    bins=[]
    for i in range(10):
        mask=(p>=i/10)&(p<(i+1)/10 if i<9 else p<=1)
        if mask.any():bins.append(dict(lower=i/10,upper=(i+1)/10,count=int(mask.sum()),mean_probability=float(p[mask].mean()),observed_positive_fraction=float(y[mask].mean())))
    return dict(rows=len(y),precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,
        roc_auc=auc,pr_auc=ap,brier_score=float(np.mean((p-y)**2)),confusion_matrix=dict(tn=tn,fp=fp,fn=fn,tp=tp),
        acceptance_rate=float(pred.mean()),calibration=bins)


def performance(rows, *, cost_multiplier=1.0, capital=20000.0):
    recorded=[r for r in rows if r.get('outcome') is not None]
    empty=dict(evaluated_outcomes=0,win_rate=None,average_win=None,average_loss=None,expectancy=None,
        gross_pnl=None,fees=None,funding_cost=None,slippage=None,net_pnl=None,net_return=None,
        max_drawdown=None,daily_equity_volatility=None,time_in_market=None,max_realized_drawdown=None,
        daily_realized_equity_volatility=None)
    if not recorded:return dict(**empty,status='OUTCOME_EVIDENCE_UNAVAILABLE')
    records=sorted(recorded,key=lambda r:(r['outcome']['completed_ms'],r['candidate_id']))
    nets=[r['outcome']['gross_result']-cost_multiplier*(r['outcome']['fees']+r['outcome']['slippage'])-r['outcome']['funding_cost'] for r in records]
    wins=[x for x in nets if x>0];loss=[x for x in nets if x<=0];equity=peak=0.0;dd=0.0;daily=defaultdict(float)
    for r,net in zip(records,nets):
        equity+=net;peak=max(peak,equity);dd=max(dd,peak-equity);daily[utc_day(r['outcome']['completed_ms'])]+=net
    # Observed completion-day realized series, explicitly not mark-equity daily volatility.
    daily_returns=[x/capital for x in daily.values()]
    return dict(evaluated_outcomes=len(records),win_rate=len(wins)/len(records),average_win=sum(wins)/len(wins) if wins else None,
        average_loss=sum(loss)/len(loss) if loss else None,expectancy=sum(nets)/len(nets),
        gross_pnl=sum(r['outcome']['gross_result'] for r in records),fees=sum(r['outcome']['fees'] for r in records)*cost_multiplier,
        funding_cost=sum(r['outcome']['funding_cost'] for r in records),slippage=sum(r['outcome']['slippage'] for r in records)*cost_multiplier,
        net_pnl=sum(nets),net_return=sum(nets)/capital,max_realized_drawdown=dd,
        daily_realized_equity_volatility=float(np.std(daily_returns,ddof=1)) if len(daily_returns)>1 else None,
        max_drawdown=None,daily_equity_volatility=None,time_in_market=None,
        status='CONDITIONAL_RECORDED_OUTCOMES_NOT_ALTERNATE_PORTFOLIO',cost_multiplier=cost_multiplier,
        missing_portfolio_evidence='Mark-equity path, concurrent positions/capital reservations and held-time samples unavailable')


def grouped_performance(rows, key):
    groups=defaultdict(list)
    for r in rows:
        values=r[key] if isinstance(r[key],list) else [r[key]]
        for v in values:groups[str(v)].append(r)
    return {g:performance(v) for g,v in sorted(groups.items())}


def day_block_interval(rows, *, seed=20261004, resamples=200):
    """Resample whole observed completion days; never individual random time rows."""
    by_day=defaultdict(list)
    for r in rows:
        if r.get('outcome'):by_day[utc_day(r['outcome']['completed_ms'])].append(r['outcome']['net_result'])
    if len(by_day)<10 or sum(map(len,by_day.values()))<100:
        return dict(status='INSUFFICIENT_DAY_BLOCKS',lower=None,upper=None,observed_days=len(by_day))
    values=list(by_day.values());rng=np.random.default_rng(seed);means=[]
    for _ in range(resamples):
        sample=[x for i in rng.integers(0,len(values),len(values)) for x in values[i]];means.append(float(np.mean(sample)))
    return dict(status='DESCRIPTIVE_DAY_BLOCK_BOOTSTRAP_NOT_PROMOTION_PROOF',lower=float(np.quantile(means,.025)),
                upper=float(np.quantile(means,.975)),observed_days=len(values),resamples=resamples,seed=seed)
