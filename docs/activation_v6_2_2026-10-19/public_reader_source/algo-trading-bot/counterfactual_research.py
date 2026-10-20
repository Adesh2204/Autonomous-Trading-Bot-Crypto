"""Saved-observation research. No exchange client, signer or executor accepted.

Admissions use only information available at decision time. Later outcomes are
optional evaluation evidence, never admission features. No policy promotion.
"""
from copy import deepcopy
from dataclasses import asdict,dataclass
from decimal import Decimal
import json,math
from pathlib import Path

from exchange.base_exchange import ExchangeError


@dataclass(frozen=True)
class ResearchVariant:
    name:str
    atr_floor:Decimal=Decimal('.004')
    spread_bps:Decimal=Decimal('15')
    top_n:int=3

    def __post_init__(self):
        if not self.name or type(self.top_n) is not int or not 1<=self.top_n<=10:
            raise ExchangeError('INVALID_COUNTERFACTUAL_POLICY')
        for key in ('atr_floor','spread_bps'):
            value=Decimal(str(getattr(self,key)))
            if not value.is_finite() or value<=0:raise ExchangeError('INVALID_COUNTERFACTUAL_POLICY')
            object.__setattr__(self,key,value)
        if self.name=='BASELINE_POLICY' and (self.atr_floor,self.spread_bps,self.top_n)!=(Decimal('.004'),Decimal(15),3):
            raise ExchangeError('BASELINE_POLICY_IMMUTABLE')

BASELINE_POLICY=ResearchVariant('BASELINE_POLICY')
VARIANTS=(BASELINE_POLICY,ResearchVariant('ATR_035',Decimal('.0035')),
          ResearchVariant('ATR_030',Decimal('.003')),ResearchVariant('TOP5',top_n=5),
          ResearchVariant('SPREAD20',spread_bps=Decimal(20)))


def _performance(selected,outcomes,*,before=None,after=None):
    observations=[]
    for cid in selected:
        o=outcomes.get(cid)
        if o is None:continue
        if type(o.get('completed_ms')) is not int:raise ExchangeError('OUTCOME_COMPLETION_REQUIRED')
        if before is not None and o['completed_ms']>=before:continue  # embargo across holdout boundary
        if after is not None and o['decision_ms']<after:continue
        if o['completed_ms']<o['decision_ms']:raise ExchangeError('OUTCOME_TIME_REGRESSED')
        if o.get('source') not in {'RECORDED_PAPER_SIMULATION','EXCHANGE_REPORTED'}:
            raise ExchangeError('OUTCOME_PROVENANCE_REQUIRED')
        components={k:Decimal(str(o[k])) for k in ('gross_result','fees','slippage','funding_cost')}
        if any(not v.is_finite() for v in components.values()) or components['fees']<0 or components['slippage']<0:
            raise ExchangeError('INVALID_RESEARCH_COST_EVIDENCE')
        net=components['gross_result']-components['fees']-components['slippage']-components['funding_cost']
        observations.append((o['completed_ms'],net,components))
    observations.sort(key=lambda o:o[0])
    if not observations:return dict(evaluated_outcomes=0,gross_result=None,net_result=None,max_drawdown_amount=None,
        net_result_sample_volatility=None,expected_costs=None,status='OUTCOME_EVIDENCE_UNAVAILABLE')
    nets=[o[1] for o in observations]
    equity=peak=Decimal(0);dd=Decimal(0)
    for v in nets:
        equity+=v;peak=max(peak,equity);dd=max(dd,peak-equity)
    mean=sum(nets)/len(nets)
    volatility=(sum((v-mean)**2 for v in nets)/(len(nets)-1)).sqrt() if len(nets)>1 else None
    return dict(evaluated_outcomes=len(nets),gross_result=sum(o[2]['gross_result'] for o in observations),
        net_result=sum(nets),max_drawdown_amount=dd,net_result_sample_volatility=volatility,
        expected_costs={k:sum(o[2][k] for o in observations) for k in ('fees','slippage','funding_cost')},
        status='CONDITIONAL_RECORDED_OUTCOME_COMPARISON_NOT_EXECUTED_COUNTERFACTUAL_TRADES')


class CounterfactualResearch:
    def __init__(self,variants=VARIANTS):
        self.variants=tuple(variants)
        if not all(type(v) is ResearchVariant for v in self.variants) or len({v.name for v in self.variants})!=len(self.variants):
            raise ExchangeError('ISOLATED_RESEARCH_VARIANTS_REQUIRED')
        if BASELINE_POLICY not in self.variants:raise ExchangeError('BASELINE_POLICY_REQUIRED')

    def evaluate(self,observations,*,holdout_start_ms=None,outcomes=None):
        rows=deepcopy(list(observations));outcomes=deepcopy(outcomes or {})
        if holdout_start_ms is not None and type(holdout_start_ms) is not int:
            raise ExchangeError('CHRONOLOGICAL_HOLDOUT_REQUIRED')
        for t in rows:
            if (type(t.get('decision_ms')) is not int or type(t.get('available_at_ms')) is not int or
                t['available_at_ms']>t['decision_ms']):raise ExchangeError('RESEARCH_LOOKAHEAD_FORBIDDEN')
            stamp=(t.get('signal') or {}).get('timestamp_ms')
            if stamp is not None and stamp+60000>t['decision_ms']:raise ExchangeError('OPEN_OR_FUTURE_SIGNAL_FORBIDDEN')
            cid=t['candidate_id']
            if cid in outcomes and outcomes[cid]['decision_ms']!=t['decision_ms']:
                raise ExchangeError('OUTCOME_CANDIDATE_IDENTITY_CONFLICT')
        if len({t['candidate_id'] for t in rows})!=len(rows):raise ExchangeError('DUPLICATE_RESEARCH_OBSERVATION')
        results=[]
        for variant in self.variants:
            chosen=[];admitted=[]
            cycles=sorted({t['decision_ms'] for t in rows})
            for cycle in cycles:
                candidates=[]
                for t in rows:
                    if t['decision_ms']!=cycle:continue
                    m=t['metrics'];p=t.get('scanner_policy') or {}
                    if t['stages']['MARKET_DATA_HEALTHY']['status']!='PASS' or t['stages']['ENOUGH_HISTORY']['status']!='PASS':continue
                    required=('atr_fraction','spread_bps','window_notional_approx','bbo_notional')
                    if not all(k in m for k in required):continue
                    if (Decimal(str(m['atr_fraction']))<variant.atr_floor or Decimal(str(m['spread_bps']))>variant.spread_bps or
                        Decimal(str(m['window_notional_approx']))<=0 or Decimal(str(m['bbo_notional']))<=0 or
                        Decimal(str(m['window_notional_approx']))<Decimal(str(p.get('min_window_notional',0))) or
                        Decimal(str(m['bbo_notional']))<Decimal(str(p.get('min_bbo_notional',10)))):continue
                    candidates.append(t)
                factors={'atr_fraction':1,'spread_bps':-1,'window_notional_approx':1,'bbo_notional':1}
                def score(t):
                    ranks=[]
                    for key,direction in factors.items():
                        value=direction*Decimal(str(t['metrics'][key]))
                        below=sum(direction*Decimal(str(x['metrics'][key]))<value for x in candidates)
                        ties=sum(direction*Decimal(str(x['metrics'][key]))==value for x in candidates)
                        ranks.append((Decimal(below)+Decimal(ties)/2)/len(candidates))
                    return sum(ranks)/4
                scores={t['candidate_id']:score(t) for t in candidates}
                candidates.sort(key=lambda t:(-scores[t['candidate_id']],-Decimal(str(t['metrics']['atr_fraction'])),t['symbol']))
                admitted.extend(t['candidate_id'] for t in candidates)
                chosen.extend(t['candidate_id'] for t in candidates[:variant.top_n])
            setup=[cid for cid in chosen if next(t for t in rows if t['candidate_id']==cid)['side_channel_signal']]
            costs=[dict(candidate_id=t['candidate_id'],economics=t['expected_economics']) for t in rows
                   if t['candidate_id'] in setup and t.get('expected_economics')]
            train=[cid for cid in setup if holdout_start_ms is not None and next(t for t in rows if t['candidate_id']==cid)['decision_ms']<holdout_start_ms]
            holdout=[cid for cid in setup if holdout_start_ms is not None and next(t for t in rows if t['candidate_id']==cid)['decision_ms']>=holdout_start_ms]
            results.append(dict(policy=asdict(variant),admitted_candidates=len(admitted),selected_candidates=len(chosen),
                available_frozen_setups=len(setup),selected_candidate_ids=chosen,setup_candidate_ids=setup,
                expected_cost_observations=costs,
                all_recorded_outcomes=_performance(setup,outcomes),
                research_window=_performance(train,outcomes,before=holdout_start_ms),
                untouched_holdout=_performance(holdout,outcomes,after=holdout_start_ms)))
        days={t.get('utc_day') for t in rows}
        return dict(label='COUNTERFACTUAL — NOT LIVE POLICY',production_policy_changed=False,
            exchange_orders_submitted=0,order_capability=False,baseline_policy=asdict(BASELINE_POLICY),
            observation_count=len(rows),dates=len(days),holdout_start_ms=holdout_start_ms,
            research_status='INSUFFICIENT OBSERVATIONS' if len(days)<3 or len(rows)<100 else 'OBSERVATIONS_ONLY_REVIEW_REQUIRED',
            variants=results,automatic_promotion=False,
            note='No trades are generated. Setups are the unchanged frozen brain observations. Missing outcome/cost evidence stays null. Recorded outcomes are conditional comparisons, not proof relaxed admission would have produced the same fills or portfolio path. Threshold proposals require multi-session, regime and untouched holdout evidence.')

    def export(self,observations,directory,**kwargs):
        report=self.evaluate(observations,**kwargs)
        path=Path(directory);path.mkdir(parents=True,exist_ok=True)
        (path/'counterfactual_research.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
        (path/'counterfactual_research.txt').write_text(report['label']+'\n'+report['research_status']+'\n'+
            '\n'.join(v['policy']['name']+': '+str(v['available_frozen_setups'])+' observed setups; net='+
                      str(v['all_recorded_outcomes']['net_result']) for v in report['variants'])+'\n')
        return report
