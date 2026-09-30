"""Transparent ranking and same-clock cumulative RVOL; never produces a signal."""
from dataclasses import dataclass
from datetime import time, date
import pandas as pd
import math

def build_volume_profile(candles,session_date):
    ordered=candles.sort_values('Timestamp')
    timestamps=pd.to_datetime(ordered['Timestamp'])+pd.Timedelta(minutes=1)
    cumulative=pd.to_numeric(ordered['Volume'],errors='raise').cumsum()
    return {'session_date':str(session_date),'cumulative_volume':
        {ts.strftime('%H:%M:%S'):float(v) for ts,v in zip(timestamps,cumulative)}}

def same_time_rvol(current_volume,clock_time,historical_profiles,current_date=None):
    samples=[]
    for profile in historical_profiles:
        if 'session_date' in profile:
            if current_date is not None and date.fromisoformat(profile['session_date'])>=current_date:continue
            profile=profile['cumulative_volume']
        elif current_date is not None:
            continue # Undated profiles cannot establish absence of lookahead in production.
        eligible=[(k,v) for k,v in profile.items() if time.fromisoformat(k)<=clock_time and math.isfinite(float(v))]
        if eligible:
            value=max(eligible,key=lambda pair:time.fromisoformat(pair[0]))[1]
            if value>0:samples.append(value)
    if len(samples)<3 or current_volume<0:return None
    return current_volume/(sum(samples)/len(samples))

@dataclass(frozen=True)
class OpportunityScore:
    liquidity: float
    spread: float
    depth: float
    volatility: float
    participation: float
    reliability: float
    @property
    def total(self):return sum(self.__dict__.values())

def score_opportunity(volume,spread_pct,depth,atr_pct,rvol=None,reliable=True):
    return OpportunityScore(min(1.,max(0.,volume)/10_000_000),
        max(0.,1.-spread_pct/.15) if spread_pct is not None else 0.,
        min(1.,max(0.,depth)/1000),min(1.,max(0.,atr_pct)/1.),
        min(1.,rvol/2.) if rvol is not None else 0.,1. if reliable else 0.)

def arbitration_key(candidate):
    """Quality, post-cost R:R, depth, score, timestamp, symbol: stable tie breaks."""
    return (-candidate['execution_quality'],-candidate['net_rr'],-candidate['depth'],
            -candidate['opportunity_score'],candidate['timestamp'],candidate['symbol'])
