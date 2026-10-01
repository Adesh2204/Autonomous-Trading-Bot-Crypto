"""Observe the frozen strategy independently of permission to execute it.

This module never submits an order. Gate results are PASS/BLOCKED/NOT_EVALUATED;
unknown inputs are never reported as passed. Each observation carries every blocker.
"""
from dataclasses import asdict, dataclass, field
from collections import Counter
import json
import logging
import math
import uuid
import pandas as pd
import config
from execution_safety import ExecutionQualityGate, SafetyError, solve_quantity
from historical_data import ist_timestamp
from opportunity_engine import score_opportunity, same_time_rvol


@dataclass
class SignalObservation:
    symbol: str
    token: str
    timestamp: str
    candle_timestamp: str | None = None
    side: str | None = None
    signal_generated: bool = False
    bias: str = "UNKNOWN"
    data_status: str = "BOOTSTRAPPING"
    volatility_status: str = "UNKNOWN"
    reference_entry: float | None = None
    reference_stop: float | None = None
    reference_target: float | None = None
    economic_model_entry: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    expected_quantity: int | None = None
    rvol: float | None = None
    rvol_status: str = "INSUFFICIENT_HISTORY"
    gates: dict = field(default_factory=dict)
    blocking_reasons: list = field(default_factory=list)
    executable: bool = False
    quote: dict | None = None
    economics: dict | None = None
    opportunity_score: float = 0.
    signal_type: str | None = None
    close: float | None = None

    def gate(self, name, passed, reason):
        self.gates[name] = "NOT_EVALUATED" if passed is None else "PASS" if passed else "BLOCKED"
        if passed is False and reason not in self.blocking_reasons:
            self.blocking_reasons.append(reason)

    def report(self):
        return asdict(self)

    @property
    def signal_id(self):
        return f'{self.token}:{self.candle_timestamp}:{self.side}'


def observe_signal(state, trader, schedule, now, generate, detect_bias):
    o = SignalObservation(state.symbol, state.token, now.isoformat())
    state.refresh_maturity()
    o.data_status, o.volatility_status = state.data_status, state.volatility_status
    df = state.current_candle_df
    o.gate('session_data', not state.builder.recovery_required, state.builder.recovery_reason or 'SESSION_HISTORY_INCOMPLETE')
    o.gate('warmup', df is not None and len(df) >= config.MIN_CANDLES_BEFORE_TRADE, 'WARMUP')
    o.gate('feed', state.feed_monitor.state.value == 'HEALTHY', 'NO_MARKET_DATA')
    o.gate('time', schedule.can_enter_new_positions(now), 'ENTRY_CUTOFF_REACHED')
    o.gate('watchlist', state.watchlist_role == 'PRIMARY', 'RESERVE_NOT_PROMOTED')
    o.gate('symbol_state', state.execution_state.value == 'ACTIVE',
           'VOLATILITY_STANDBY' if state.execution_state.value == 'STANDBY' else 'SYMBOL_'+state.execution_state.value)
    try:
        state.instrument.validate(state.symbol,state.token,state.exchange,now)
        o.gate('identity',True,'')
    except (SafetyError, AttributeError, TypeError):
        o.gate('identity',False,'INSTRUMENT_IDENTITY_MISMATCH')
    risk_reasons=[]
    if trader._halted:
        risk_reasons.append('UNKNOWN_BROKER_STATE')
    if trader.journal.budget()[1] >= config.MAX_NEW_SETUPS:
        risk_reasons.append('MAX_NEW_SETUPS_REACHED')
    remaining = trader.journal.remaining(trader.daily_loss_limit)
    if remaining <= 0:
        risk_reasons.append('DAILY_RISK_EXHAUSTED')
    if trader.candles_since_last_sl < trader.reentry_cooldown_candles:
        risk_reasons.append('COOLDOWN')
    o.gate('risk',not risk_reasons,risk_reasons[0] if risk_reasons else '')
    o.blocking_reasons.extend(r for r in risk_reasons if r not in o.blocking_reasons)
    o.gate('position_capacity',not trader.has_open_position,'POSITION_ALREADY_OPEN')
    latest=None
    if df is not None and len(df):
        result=generate(df.copy())
        latest=result.iloc[-1]
        o.candle_timestamp=str(latest.Timestamp)
        candle_time=ist_timestamp(latest.Timestamp)
        o.gate('signal_freshness', 0 <= (now-candle_time).total_seconds() <= config.CLOSED_SIGNAL_MAX_AGE_SECONDS, 'STALE_SIGNAL_CANDLE')
        long=bool(latest.get('Buy_Signal',False)) or bool(latest.get('Breakout_Signal',False))
        short=bool(latest.get('Sell_Signal',False)) or bool(latest.get('Breakdown_Sell_Signal',False))
        o.signal_generated=long or short
        o.bias=detect_bias(result)
        allowed_long=long and o.bias!='SHORT_BIAS'
        allowed_short=short and o.bias!='LONG_BIAS'
        o.side='BUY' if allowed_long else 'SELL' if allowed_short else 'BUY' if long else 'SELL' if short else None
        o.gate('bias', (allowed_long or allowed_short) if o.signal_generated else None,'DAILY_BIAS_CONFLICT')
        o.close=float(latest.Close)
        o.atr=float(latest.get('ATR_14',float('nan')))
        o.reference_entry=float(latest.get('VWAP',float('nan')))
        finite=all(math.isfinite(v) and v>0 for v in (o.close,o.atr,o.reference_entry))
        o.gate('indicators',finite,'INVALID_INDICATORS')
        if finite:
            o.atr_pct=o.atr/o.close
            o.gate('atr_floor',o.atr_pct >= config.INTRADAY_ATR_MIN_PCT,'ATR_BELOW_LIVE_MINIMUM')
            o.gate('atr_hysteresis',state.atr_firewall.status.value=='ACTIVE','ATR_PERSISTENT_LOW_STANDBY')
            if o.side:
                sign=1 if o.side=='BUY' else -1
                distance=round(config.SL_ATR_MULT*o.atr,2)
                o.reference_stop=round(o.reference_entry-sign*distance,2)
                o.reference_target=round(o.reference_entry+sign*2*distance,2)
        else:
            o.atr=o.atr if math.isfinite(o.atr) else None
            o.reference_entry=o.reference_entry if math.isfinite(o.reference_entry) else None
        o.signal_type=latest.get('Signal_Type')
    else:
        for name in ('signal_freshness','bias','indicators','atr_floor','atr_hysteresis'):
            o.gate(name,None,'')
    o.gate('signal',o.signal_generated,'NO_CORE_SIGNAL')
    quote=state.quote
    expected=None
    if quote is not None:
        age=(now-quote.timestamp).total_seconds() if quote.timestamp.tzinfo is not None else None
        o.quote={'timestamp':str(quote.timestamp),'bid':quote.bid,'ask':quote.ask,
                 'bid_quantity':quote.bid_quantity,'ask_quantity':quote.ask_quantity,
                 'spread':quote.ask-quote.bid,'spread_pct':quote.spread_pct if math.isfinite(quote.spread_pct) else None,
                 'ltp':quote.last,'age_seconds':age,'feed_health':state.feed_monitor.state.value,
                 'expected_quantity':None,'source':'OBSERVED_LIVE_QUOTE'}
        o.gate('quote_freshness',age is not None and 0 <= age <= config.EXECUTION_QUOTE_MAX_AGE_SECONDS,'QUOTE_STALE')
        o.gate('spread',math.isfinite(quote.spread_pct) and 0 <= quote.spread_pct <= config.SCREEN_MAX_SPREAD_PCT,'SPREAD_TOO_WIDE')
        depth=quote.ask_quantity if o.side=='BUY' else quote.bid_quantity if o.side=='SELL' else min(quote.ask_quantity,quote.bid_quantity)
        o.gate('depth',state.last_depth_available and depth*config.BEST_LEVEL_MAX_PARTICIPATION >= 1,'DEPTH_INSUFFICIENT')
        if o.side:
            try:
                expected=ExecutionQualityGate().validate(quote,o.side,now)
                o.gate('execution_quality',True,'')
            except SafetyError as exc:
                o.gate('execution_quality',False,str(exc))
    else:
        o.gate('quote_freshness',False,'NO_VALID_BID_ASK')
        for name in ('spread','depth','execution_quality'):
            o.gate(name,None,'')
    if expected is not None and o.reference_stop is not None and o.gates['identity']=='PASS':
        floor=config.MIN_NET_RR_LOW_VOL if o.atr/o.reference_entry < config.LOW_VOL_ATR_PCT else config.MIN_NET_RR_NORMAL
        economics=solve_quantity(o.side,expected,o.reference_stop,o.reference_target,trader.working_capital,
            trader.risk_per_trade,remaining,floor,config.SLIPPAGE_HAIRCUT_PCT,state.instrument.lot_size,
            int(depth*config.BEST_LEVEL_MAX_PARTICIPATION),exit_spread_pct=config.SCREEN_MAX_SPREAD_PCT/2,
            tick_size=state.instrument.tick_size)
        o.gate('economics',economics is not None,'NO_ECONOMICALLY_VALID_QUANTITY')
        if economics:
            o.economics=asdict(economics)
            o.economic_model_entry=economics.estimated_entry
            o.expected_quantity=economics.quantity
            o.quote['expected_quantity']=economics.quantity
    else:
        o.gate('economics',None,'')
    o.rvol=same_time_rvol(state.cumulative_volume,now.time().replace(tzinfo=None),state.volume_profiles,now.date())
    o.rvol_status='AVAILABLE' if o.rvol is not None else 'INSUFFICIENT_HISTORY'
    if quote and o.atr_pct is not None and math.isfinite(quote.spread_pct):
        o.opportunity_score=score_opportunity(state.cumulative_volume,quote.spread_pct*100,
            min(quote.ask_quantity,quote.bid_quantity),o.atr_pct*100,o.rvol).total
    o.executable=all(v=='PASS' for v in o.gates.values()) and o.economics is not None
    return o


class OpportunityTelemetry:
    def __init__(self,run_id='TEST'):
        self.run_id=run_id
        self.latest={}
        self.observations={}
        self.last_log={}
        self.gate_counts=Counter()
        self.ever_executable=set()
        self.rejected_gates={}
        self.promotions=[]
        self.feed_interruptions=0
        self.peak_exposure=0.

    def record(self,observation,trader):
        o=observation
        key=f'{o.token}:{o.candle_timestamp}'
        signature=(o.side,tuple(o.gates.items()),o.executable)
        if self.latest.get(key)==signature:
            return False
        self.latest[key]=signature
        self.observations[key]=o.report()
        if o.executable:self.ever_executable.add(key)
        self.rejected_gates.setdefault(key,set()).update(o.blocking_reasons)
        payload=o.report() | {'run_id':self.run_id}
        # Every changed decision persists; terminal prints only a change or timed summary.
        trader.journal.event(str(uuid.uuid4()),'SIGNAL_OBSERVATION',payload)
        if o.signal_generated and o.quote:
            trader.journal.event(str(uuid.uuid4()),'OPPORTUNITY_QUOTE',o.quote|{'run_id':self.run_id,'symbol':o.symbol,'signal_id':o.signal_id})
        previous=self.last_log.get(o.symbol)
        now=ist_timestamp(o.timestamp)
        reasons=tuple(o.blocking_reasons)
        if previous is None or previous[0]!=reasons or (now-previous[1]).total_seconds() >= config.REJECTION_LOG_INTERVAL_SECONDS:
            logging.info('[OPPORTUNITY] %s signal=%s executable=%s blocked=%s',o.symbol,o.side,o.executable,o.blocking_reasons)
            self.last_log[o.symbol]=(reasons,now)
        if o.blocking_reasons:
            # Keep compatibility with daily aggregate reports, one exact rejection per bar/gate.
            for reason in o.blocking_reasons:
                trader.journal.event(f'{self.run_id}:{key}:{reason}','REJECTED',
                    {'run_id':self.run_id,'symbol':o.symbol,'reason':reason,'signal_id':o.signal_id})
        return True

    def summary(self):
        rows=list(self.observations.values())
        reasons=Counter(r for reasons in self.rejected_gates.values() for r in reasons)
        signals=[r for r in rows if r['signal_generated']]
        counts={'completed_bar_observations':len(rows),'potential_signals':len(signals),
                'executable_signals':len(self.ever_executable),
                'live_atr_eligible_symbols':len({r['symbol'] for r in rows if r['gates'].get('atr_floor')=='PASS'}),
                'signals_passing_liquidity':sum(all(r['gates'].get(g)=='PASS' for g in ('feed','quote_freshness','spread','depth','execution_quality')) for r in signals),
                'signals_passing_economics':sum(r['gates'].get('economics')=='PASS' for r in signals),
                'signals_passing_risk':sum(r['gates'].get('risk')=='PASS' for r in signals)}
        return {'counts':counts,'gate_rejections':dict(reasons),'reserve_promotions':self.promotions,
                'feed_interruptions':self.feed_interruptions,'peak_exposure':self.peak_exposure,
                'denominator_note':'symbol counts and unique completed-bar observations are distinct units; gate counts overlap',
                'signal_gate_pass_percent':{k:(v/len(signals)*100 if signals else None) for k,v in counts.items() if k.startswith('signals_passing')}}
