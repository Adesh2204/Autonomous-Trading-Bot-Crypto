"""Candidate rows, explicit as-of feature evidence and after-cost labels.

No random candles become training rows. Missing/unproven observations are null;
rejected candidates never acquire pretend fills. Outputs have no order methods.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from .common import ResearchError, MARKETS, digest, finite, stamp, utc_day

NUMERIC = ('atr_fraction','vwap_distance_fraction','vwap_slope_fraction','ema9','ema21',
           'ema_separation_fraction','candles_since_anchor','realized_volatility',
           'spread_bps','bid_depth_notional','ask_depth_notional','total_depth_notional',
           'book_imbalance','estimated_slippage_bps','available_liquidity',
           'funding_rate','open_interest','mark_oracle_bps','utc_hour','weekday')
CATEGORICAL = ('symbol','asset_class','setup_type','direction','daily_bias','anchor_policy_id')
REQUIRED = ('atr_fraction','vwap_distance_fraction','ema_separation_fraction','spread_bps')
SETUPS = {'PULLBACK_LONG':'LONG','BREAKOUT_LONG':'LONG','PULLBACK_SHORT':'SHORT','BREAKDOWN_SHORT':'SHORT'}
ASSET_CLASS = {'par:BTC':'CRYPTO','par:ETH':'CRYPTO','par:HYPE':'CRYPTO','par:SP500':'EQUITY_INDEX',
               'par:EWY':'EQUITY_REFERENCE','par:EWJ':'EQUITY_REFERENCE','par:BRENT':'COMMODITY',
               'par:GOLD':'COMMODITY','par:USDEUR':'FX','par:USDJPY':'FX'}


def feature_manifest():
    formulas = dict(atr_fraction='ATR_14 / close',vwap_distance_fraction='(close - VWAP) / close',
        vwap_slope_fraction='VWAP_Slope / close',ema9='Frozen EMA_9',ema21='Frozen EMA_21',
        ema_separation_fraction='(EMA_9 - EMA_21) / close',candles_since_anchor='Observed completed bars since configured anchor; never wall-clock missing bars',
        realized_volatility='Recorded scanner population standard deviation of log returns over its saved history window (300 bars in the unchanged baseline)',
        spread_bps='(ask - bid) / ((bid + ask)/2) * 10000',
        bid_depth_notional='Sum bid price * quantity in observed book',ask_depth_notional='Sum ask price * quantity in observed book',
        total_depth_notional='bid_depth_notional + ask_depth_notional',book_imbalance='(bid_depth - ask_depth)/(bid_depth + ask_depth)',
        estimated_slippage_bps='Decision-time risk estimate, never realized exit slippage',available_liquidity='Observed window quote notional',
        funding_rate='Decision-time snapshot hourly rate, never future settlement',open_interest='Observed context quantity',
        mark_oracle_bps='(mark - oracle)/oracle * 10000',utc_hour='Decision UTC hour',weekday='Decision weekday, Monday=0')
    entries=[]
    for name in NUMERIC+CATEGORICAL:
        unit=('bps' if name.endswith('bps') else 'quote_currency' if 'notional' in name or name=='available_liquidity' else
              'price' if name in {'ema9','ema21'} else 'base_quantity' if name=='open_interest' else
              'categorical' if name in CATEGORICAL else 'count' if name in {'utc_hour','weekday','candles_since_anchor'} else 'fraction')
        max_age=(5000 if name in {'spread_bps','bid_depth_notional','ask_depth_notional','total_depth_notional','book_imbalance','estimated_slippage_bps'} else
                 60000 if name in {'funding_rate','open_interest','mark_oracle_bps'} else
                 None if name in CATEGORICAL or name in {'utc_hour','weekday'} else 120000)
        entries.append(dict(name=name,formula=formulas.get(name,'Explicit deterministic candidate metadata'),
            source='Per-row evidence.source and evidence.source_ms',timestamp='Per-row source_ms <= decision_ms',
            availability_time='Per-row available_ms between source_ms and decision_ms',units=unit,
            normalization='Training-only standardization' if name in NUMERIC else 'Training-only one-hot vocabulary',
            missing_behavior='ML_UNAVAILABLE if required; optional numeric train-median imputation with missing indicator, optional categorical UNKNOWN',
            required=name in REQUIRED,max_age_ms=max_age))
    return dict(schema_version=1,features=entries,required_features=list(REQUIRED),label='POSITIVE_NET_OUTCOME',
        label_definition='1 if completed gross_result - fees - slippage - funding_cost > 0, else 0; full unchanged-management execution and cost lineage required',
        feature_outcome_separation=True)


def regime(features):
    a=features.get('atr_fraction'); spread=features.get('spread_bps'); trend=features.get('ema_separation_fraction')
    axes=[]
    if a is not None: axes.append('HIGH_VOLATILITY' if a>=.004 else 'LOW_VOLATILITY')
    if trend is not None: axes.append('TRENDING_UP' if trend>.001 else 'TRENDING_DOWN' if trend<-.001 else 'RANGE_CHOP')
    if spread is not None: axes.append('HIGH_SPREAD' if spread>15 else 'SPREAD_WITHIN_BASELINE')
    depth=features.get('total_depth_notional')
    if depth is not None: axes.append('LOW_LIQUIDITY' if depth<10 else 'OBSERVED_DEPTH_AT_LEAST_10')
    return axes or ['REGIME_UNAVAILABLE']


def validate_outcome(outcome, row, assumptions_hash):
    if outcome is None: return None
    if row['candidate_kind']=='REJECTED_CANDIDATE': return None
    if (outcome.get('candidate_id')!=row['candidate_id'] or outcome.get('decision_ms')!=row['decision_ms'] or
        outcome.get('symbol')!=row['symbol'] or outcome.get('direction')!=row['direction'] or
        outcome.get('anchor_policy_id')!=row['anchor_policy_id']): raise ResearchError('OUTCOME_IDENTITY_MISMATCH')
    end=stamp(outcome.get('completed_ms'))
    if end<=row['decision_ms']: raise ResearchError('OUTCOME_COMPLETION_MUST_FOLLOW_DECISION')
    if (outcome.get('source') not in {'RECORDED_PAPER_SIMULATION','EXCHANGE_REPORTED'} or
        outcome.get('fill_model')!='OBSERVED_EXECUTABLE_BBO' or not outcome.get('entry_fill_ids') or
        not outcome.get('exit_fill_ids') or outcome.get('management_version')!='FROZEN_BASELINE' or
        outcome.get('assumptions_hash')!=assumptions_hash): raise ResearchError('CREDIBLE_EXECUTION_AND_COST_LINEAGE_REQUIRED')
    c={k:finite(outcome.get(k)) for k in ('gross_result','fees','slippage','funding_cost')}
    if c['fees']<0 or c['slippage']<0: raise ResearchError('INVALID_COST')
    net=c['gross_result']-c['fees']-c['slippage']-c['funding_cost']
    return dict(**c,net_result=net,completed_ms=end,label=int(net>0),source=outcome['source'],
                fill_ids=list(outcome['entry_fill_ids'])+list(outcome['exit_fill_ids']),
                result_kind='CONDITIONAL_RECORDED_CANDIDATE_OUTCOME_NOT_ALTERNATE_PORTFOLIO')


def build_dataset(observations, outcomes=None, *, assumptions=None):
    """Input unit is an explicit valid frozen-strategy candidate + evidence map."""
    observations=list(observations)
    outcomes=deepcopy(outcomes or {}); rows=[]; rejected=[]; seen=set(); duplicates=0; stale=0
    assumptions_hash=digest(assumptions or {})
    for observation in observations:
        o=deepcopy(observation);cid=o.get('candidate_id')
        if not cid: rejected.append(dict(candidate_id=None,reason='CANDIDATE_ID_REQUIRED'));continue
        if cid in seen: duplicates+=1;rejected.append(dict(candidate_id=cid,reason='DUPLICATE_CANDIDATE'));continue
        seen.add(cid)
        if o.get('symbol') not in MARKETS: rejected.append(dict(candidate_id=cid,reason='UNKNOWN_MARKET'));continue
        setup=o.get('setup_type');direction=o.get('direction')
        if setup not in SETUPS or SETUPS[setup]!=direction or o.get('valid_strategy_candidate') is not True:
            rejected.append(dict(candidate_id=cid,reason='NOT_A_VALID_DETERMINISTIC_CANDIDATE'));continue
        t=stamp(o.get('decision_ms')); kind=o.get('candidate_kind','REJECTED_CANDIDATE')
        if kind not in {'EXECUTED_CANDIDATE','PAPER_EXECUTABLE_CANDIDATE','REJECTED_CANDIDATE','COUNTERFACTUAL_CANDIDATE'}:
            raise ResearchError('CANDIDATE_KIND_REQUIRED')
        if not o.get('anchor_policy_id'): raise ResearchError('ANCHOR_IDENTITY_REQUIRED')
        values={n:None for n in NUMERIC+CATEGORICAL};proof={};issues=[]
        for name,e in o.get('feature_evidence',{}).items():
            if name not in values: raise ResearchError('UNKNOWN_OR_OUTCOME_FEATURE_FORBIDDEN')
            if not e or e.get('value') is None: continue
            source=stamp(e.get('source_ms')); available=stamp(e.get('available_ms'))
            if not e.get('source') or available<source or available>t or source>t: raise ResearchError('FEATURE_NOT_AVAILABLE_AT_DECISION')
            entry=next(f for f in feature_manifest()['features'] if f['name']==name)
            if e.get('units')!=entry['units']: raise ResearchError('FEATURE_UNIT_MISMATCH')
            age=entry['max_age_ms']
            if age is not None and t-source>age:
                issues.append(name+':STALE');stale+=1;continue
            values[name]=finite(e['value']) if name in NUMERIC else str(e['value'])
            proof[name]=dict(source=e['source'],source_ms=source,available_ms=available,units=e['units'])
        dt=datetime.fromtimestamp(t/1000,timezone.utc)
        metadata=dict(symbol=o['symbol'],asset_class=ASSET_CLASS[o['symbol']],setup_type=setup,direction=direction,
                      anchor_policy_id=o['anchor_policy_id'],utc_hour=dt.hour,weekday=dt.weekday())
        for name,value in metadata.items():
            if values[name] is not None and values[name]!=value: raise ResearchError('CANDIDATE_METADATA_CONFLICT')
            values[name]=value; proof[name]=dict(source='DETERMINISTIC_CANDIDATE_IDENTITY',source_ms=t,available_ms=t,
                units=next(f['units'] for f in feature_manifest()['features'] if f['name']==name))
        if values['atr_fraction'] is not None and values['atr_fraction']<=0:raise ResearchError('INVALID_ATR_FRACTION')
        if values['spread_bps'] is not None and values['spread_bps']<0:raise ResearchError('NEGATIVE_SPREAD')
        if values['book_imbalance'] is not None and not -1<=values['book_imbalance']<=1:raise ResearchError('INVALID_BOOK_IMBALANCE')
        missing=[n for n in REQUIRED if values[n] is None]
        row=dict(candidate_id=cid,decision_ms=t,utc_day=utc_day(t),symbol=o['symbol'],direction=direction,
                 setup_type=setup,anchor_policy_id=o['anchor_policy_id'],candidate_kind=kind,
                 features=values,feature_provenance=proof,feature_issues=issues,
                 scoring_ready=not missing,missing_required=missing,regime=regime(values),
                 risk_decision=o.get('risk_decision','NOT_OBSERVED'),source=o.get('source','SAVED_CANDIDATE_EVIDENCE'))
        row['outcome']=validate_outcome(outcomes.get(cid),row,assumptions_hash)
        row['label']=None if row['outcome'] is None else row['outcome']['label']
        row['outcome_end_ms']=None if row['outcome'] is None else row['outcome']['completed_ms']
        rows.append(row)
    eligible=[r for r in rows if r['scoring_ready'] and r['label'] is not None]
    positives=sum(r['label']==1 for r in eligible);negative=sum(r['outcome']['net_result']<0 for r in eligible)
    quality=dict(input_observations=len(observations),
        candidate_rows=len(rows),usable_labeled_rows=len(eligible),positive_outcomes=positives,negative_outcomes=negative,
        zero_outcomes=sum(r['outcome']['net_result']==0 for r in eligible),non_positive_class=sum(r['label']==0 for r in eligible),
        positive_fraction=positives/len(eligible) if eligible else None,markets=sorted({r['symbol'] for r in rows}),
        dates=sorted({r['utc_day'] for r in rows}),labeled_markets=sorted({r['symbol'] for r in eligible}),
        labeled_dates=sorted({r['utc_day'] for r in eligible}),directions=dict(Counter(r['direction'] for r in eligible)),
        missing_features={n:sum(r['features'][n] is None for r in rows) for n in NUMERIC+CATEGORICAL},
        stale_features=stale,duplicate_candidates=duplicates,rejected_observations=rejected,
        assumptions_hash=assumptions_hash,feature_manifest_hash=digest(feature_manifest()))
    return rows,quality


def from_opportunity_traces(traces, *, feature_observations=None):
    """Existing all-market traces are NOT all candidates; copy valid setups only.

    Extra feature evidence must come from saved, timestamped records. VWAP/ATR
    observations can be copied from the trace; EMA/book/funding stay missing when
    absent. Full values are never reconstructed from future outcomes.
    """
    extra=feature_observations or {};result=[];ignored=[]
    manifest={x['name']:x for x in feature_manifest()['features']}
    for t in traces:
        signal=t.get('signal') or {};setup=signal.get('signal_type')
        if setup not in SETUPS or not (signal.get('long') or signal.get('short')):
            ignored.append(dict(candidate_id=t.get('candidate_id'),reason='NO_VALID_STRATEGY_SETUP'));continue
        d=stamp(t['decision_ms']); a=stamp(t.get('available_at_ms'));close_ms=stamp(signal.get('timestamp_ms'))+60000
        if close_ms>d or a>d: raise ResearchError('OPEN_OR_FUTURE_CANDIDATE')
        evidence=deepcopy(extra.get(t['candidate_id'],{}))
        p=finite(t.get('metrics',{}).get('close'));atr=finite(signal.get('atr'));vwap=finite(signal.get('reference'))
        if p<=0 or atr<=0 or vwap<=0: raise ResearchError('INVALID_CANDIDATE_INDICATORS')
        known={'atr_fraction':atr/p,'vwap_distance_fraction':(p-vwap)/p,'daily_bias':signal.get('bias')}
        for name in ('ema9','ema21','realized_volatility'):
            if t.get('metrics',{}).get(name) is not None:known[name]=t['metrics'][name]
        # Aggregate scanner metrics do not preserve a separate book source clock.
        # A contemporaneous spread requires explicit extra feature evidence.
        for name,value in known.items():
            if value is not None:
                evidence.setdefault(name,dict(value=value,source='SAVED_FROZEN_CANDIDATE_TRACE',source_ms=close_ms,
                                               available_ms=a,units=manifest[name]['units']))
        if 'ema9' in evidence and 'ema21' in evidence and 'ema_separation_fraction' not in evidence:
            e9=evidence['ema9'];e21=evidence['ema21']
            evidence['ema_separation_fraction']=dict(value=(finite(e9['value'])-finite(e21['value']))/p,
                source='DERIVED_FROM_TIMESTAMPED_EMA_EVIDENCE',source_ms=min(e9['source_ms'],e21['source_ms']),
                available_ms=max(e9['available_ms'],e21['available_ms']),units='fraction')
        kind='EXECUTED_CANDIDATE' if t['stages']['FILLED']['status']=='PASS' else 'REJECTED_CANDIDATE'
        result.append(dict(candidate_id=t['candidate_id'],symbol=t['symbol'],decision_ms=d,
            valid_strategy_candidate=True,setup_type=setup,direction=SETUPS[setup],anchor_policy_id='VWAP_BASELINE_UTC',
            candidate_kind=kind,feature_evidence=evidence,source=t.get('source'),
            risk_decision=t['stages'].get('RISK_PASS',{}).get('status','NOT_OBSERVED')))
    return result,ignored


def feature_evidence_from_events(events):
    """Bridge existing timestamped MARKET_DATA snapshots to candidate evidence.

    Book source time is its reported clock; context source time is explicitly the
    local observed-at clock, not an invented exchange funding timestamp.
    """
    result={};units={e['name']:e['units'] for e in feature_manifest()['features']}
    for e in events:
        snapshot=e.get('market_snapshot');cid=e.get('candidate_id')
        if not cid or not snapshot:continue
        if cid in result:raise ResearchError('DUPLICATE_FEATURE_SNAPSHOT')
        b=finite(snapshot['bid']);a=finite(snapshot['ask']);mid=(a+b)/2
        if b<=0 or a<b:raise ResearchError('INVALID_SNAPSHOT_BBO')
        spread=(a-b)/mid*10000
        if abs(spread-finite(snapshot['spread_bps']))>1e-6:raise ResearchError('SPREAD_FORMULA_MISMATCH')
        bid=finite(snapshot['bid_depth_notional']);ask=finite(snapshot['ask_depth_notional'])
        if bid<0 or ask<0 or bid+ask<=0:raise ResearchError('INVALID_BOOK_DEPTH')
        source=stamp(snapshot['orderbook_timestamp_ms']);context=stamp(snapshot['mark_observed_at_ms'])
        iso=snapshot.get('processed_ts') or snapshot.get('received_ts')
        if not iso:raise ResearchError('SNAPSHOT_AVAILABILITY_UNPROVEN')
        dt=datetime.fromisoformat(iso)
        if dt.tzinfo is None:raise ResearchError('AWARE_SNAPSHOT_CLOCK_REQUIRED')
        available=int(dt.timestamp()*1000)
        book=dict(spread_bps=spread,bid_depth_notional=bid,ask_depth_notional=ask,
                  total_depth_notional=bid+ask,book_imbalance=(bid-ask)/(bid+ask))
        features={n:dict(value=v,source='SAVED_EXCHANGE_BOOK_SNAPSHOT',source_ms=source,available_ms=available,units=units[n]) for n,v in book.items()}
        mark=finite(snapshot['mark_price']);oracle=finite(snapshot['oracle_price'])
        if mark<=0 or oracle<=0:raise ResearchError('INVALID_MARK_ORACLE')
        for n,value in dict(funding_rate=snapshot['funding'],open_interest=snapshot.get('open_interest'),mark_oracle_bps=(mark-oracle)/oracle*10000).items():
            if value is not None:features[n]=dict(value=value,source='SAVED_CONTEXT_LOCAL_OBSERVATION_CLOCK_EXCHANGE_TIME_UNKNOWN',source_ms=context,available_ms=max(context,available),units=units[n])
        result[cid]=features
    return result
