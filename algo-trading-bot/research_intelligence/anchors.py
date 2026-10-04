"""Only VWAP and VWAP-slope assignments change in an isolated trusted AST copy.

Changing _get_session_key would ALSO change EMA, volume MA and warmup. That is
deliberately not done. No module or function in the production brain is patched.
"""
import ast
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from strategy_freeze import verify_strategy_freeze
from .common import ROOT, ResearchError, stamp


@dataclass(frozen=True)
class VWAPAnchorPolicy:
    policy_id: str
    symbol: str = '*'
    anchor_type: str = 'UTC_MIDNIGHT'
    timezone: str = 'UTC'
    anchor_time: str = '00:00'
    source: str = 'Existing frozen production UTC-midnight baseline'
    rationale: str = 'Control'
    enabled_for_research: bool = True
    calendar_semantics: str = 'DAILY_WALL_CLOCK_REFERENCE_NOT_EXCHANGE_CALENDAR'

    def __post_init__(self):
        if self.symbol != '*' and not self.symbol.startswith('par:'): raise ResearchError('ANCHOR_SYMBOL_REQUIRED')
        if self.anchor_type not in {'UTC_MIDNIGHT','ASSET_SESSION_ANCHOR'}: raise ResearchError('UNIMPLEMENTED_ANCHOR')
        try:
            ZoneInfo(self.timezone); t = time.fromisoformat(self.anchor_time)
        except (ValueError, KeyError) as exc: raise ResearchError('INVALID_ANCHOR_CONFIG') from exc
        if t.second or t.microsecond or t.tzinfo: raise ResearchError('MINUTE_ANCHOR_REQUIRED')
        if not self.policy_id or not self.source or not self.rationale: raise ResearchError('ANCHOR_RATIONALE_REQUIRED')
        if self.policy_id == 'VWAP_BASELINE_UTC' and (self.anchor_type,self.timezone,self.anchor_time)!=('UTC_MIDNIGHT','UTC','00:00'):
            raise ResearchError('UTC_BASELINE_IMMUTABLE')
        if self.anchor_type == 'UTC_MIDNIGHT' and (self.timezone,self.anchor_time)!=('UTC','00:00'):
            raise ResearchError('UTC_POLICY_MUST_BE_MIDNIGHT')
        if type(self.enabled_for_research) is not bool: raise ResearchError('INVALID_ANCHOR_PERMISSION')

    def _boundary(self, date):
        naive = datetime.combine(date, time.fromisoformat(self.anchor_time)); zone = ZoneInfo(self.timezone)
        valid = []
        for fold in (0,1):
            local = naive.replace(tzinfo=zone,fold=fold); utc = local.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == naive: valid.append(utc)
        if not valid: raise ResearchError('NONEXISTENT_LOCAL_ANCHOR')
        if len(set(valid)) != 1: raise ResearchError('AMBIGUOUS_LOCAL_ANCHOR')
        return valid[0]

    def anchor_at(self, value):
        if not self.enabled_for_research: raise ResearchError('ANCHOR_DISABLED')
        if not isinstance(value, datetime) or value.tzinfo is None: raise ResearchError('AWARE_TIME_REQUIRED')
        value = value.astimezone(timezone.utc); date = value.astimezone(ZoneInfo(self.timezone)).date()
        boundary = self._boundary(date)
        return boundary if value >= boundary else self._boundary(date-timedelta(days=1))

    def report(self): return asdict(self)


VWAP_BASELINE_UTC = VWAPAnchorPolicy('VWAP_BASELINE_UTC')


def validate_frame(frame, decision_ms=None):
    if frame.empty: raise ResearchError('NO_CANDLES')
    required = {'Timestamp','Open','High','Low','Close','Volume'}
    if not required.issubset(frame.columns): raise ResearchError('CANDLE_COLUMNS_REQUIRED')
    ts = pd.to_datetime(frame.Timestamp)
    if ts.dt.tz is None: raise ResearchError('AWARE_CANDLE_TIME_REQUIRED')
    # Convert explicitly: pandas may retain microsecond resolution.
    ms = np.array([int(t.timestamp()*1000) for t in ts], dtype='int64')
    if np.any(ms % 60000) or np.any(np.diff(ms) != 60000): raise ResearchError('CANDLE_GAP_DUPLICATE_OR_BOUNDARY')
    if decision_ms is not None and ms[-1]+60000 > stamp(decision_ms): raise ResearchError('FUTURE_OR_OPEN_CANDLE')
    values = frame[['Open','High','Low','Close','Volume']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:,:4]<=0).any() or (values[:,4]<0).any(): raise ResearchError('INVALID_CANDLE_VALUES')
    if (values[:,1] < values[:,:4].max(axis=1)).any() or (values[:,2]>values[:,:4].min(axis=1)).any(): raise ResearchError('INVALID_OHLC')
    return ts, ms


class AnchorResearchBrain:
    order_capability = False
    changed_assignments = ('VWAP','VWAP_Slope')

    def __init__(self, policy=VWAP_BASELINE_UTC):
        if type(policy) is not VWAPAnchorPolicy: raise ResearchError('ISOLATED_ANCHOR_POLICY_REQUIRED')
        self.policy = policy
        verify_strategy_freeze()
        if policy.anchor_type == 'UTC_MIDNIGHT':
            from signal_brain import generate_vwap_signal
            self.generate = generate_vwap_signal
            return
        tree = ast.parse((ROOT/'algo-trading-bot/signal_brain.py').read_text())
        function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='generate_vwap_signal')
        changed = []
        for node in function.body:
            if isinstance(node,ast.Assign) and len(node.targets)==1:
                target = node.targets[0]
                if isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name) and target.value.id=='out' and isinstance(target.slice,ast.Constant) and target.slice.value in self.changed_assignments:
                    name = target.slice.value
                    node.value = ast.Call(func=ast.Name(id='__research_'+name,ctx=ast.Load()),args=[ast.Name(id='out',ctx=ast.Load())],keywords=[])
                    changed.append(name)
        if tuple(changed) != self.changed_assignments: raise ResearchError('UNEXPECTED_FROZEN_BRAIN_STRUCTURE')
        namespace = dict(__name__='_isolated_anchor_research', __research_VWAP=self._vwap, __research_VWAP_Slope=self._slope)
        exec(compile(ast.fix_missing_locations(tree),'<hash-verified-anchor-research>','exec'),namespace)
        self.generate = namespace['generate_vwap_signal']

    def keys(self, frame):
        return pd.Index([self.policy.anchor_at(t.to_pydatetime()) for t in pd.to_datetime(frame.Timestamp)],name='anchor')

    def _vwap(self, frame):
        key = self.keys(frame); volume = frame.Volume.astype(float)
        typical = (frame.High.astype(float)+frame.Low.astype(float)+frame.Close.astype(float))/3
        total = volume.groupby(key).cumsum(); weighted = (typical*volume).groupby(key).cumsum()
        return np.divide(weighted,total,out=np.full(len(frame),np.nan),where=total.to_numpy()!=0)

    def _slope(self, frame):
        keys = self.keys(frame); vwap = frame.VWAP; count = frame.groupby(keys).cumcount()
        first = vwap.groupby(keys).transform('first'); past = vwap.groupby(keys).shift(10)
        return np.where(count>=10,(vwap-past)/10,np.where(count>0,(vwap-first)/np.maximum(count,1),0.0))

    def evaluate_frame(self, frame, decision_ms=None):
        verify_strategy_freeze(); ts,_=validate_frame(frame,decision_ms)
        frame=frame.copy();frame['Timestamp']=ts.dt.tz_convert('UTC')
        return self.generate(frame)

    def coverage_complete(self, frame):
        first = pd.to_datetime(frame.Timestamp.iloc[0]).to_pydatetime()
        last = pd.to_datetime(frame.Timestamp.iloc[-1]).to_pydatetime()
        return first <= self.policy.anchor_at(last)

    def evaluate_candles(self, candles):
        from candle_normalizer import candles_to_frame
        if self.policy.symbol not in {'*',candles[0].symbol}: raise ResearchError('ANCHOR_MARKET_MISMATCH')
        return self.evaluate_frame(candles_to_frame(candles))
