"""Observation-only documented fee scenario alongside the unchanged stress guard."""
from dataclasses import asdict
from .base_exchange import decimal,ExchangeError
from .hyperliquid_market_data import make_quote
from .perpetual_economics import FeeSchedule,estimate_trade


def fee_scenarios(book,context,row,*,quantity,base_taker_rate,now_ms,context_ms):
    base=decimal(base_taker_rate,nonnegative=True)
    result=dict(base_taker_rate=str(base),documented_pas_rate_estimate=str(base*2),
        unchanged_signing_stress_rate=str(base*6),actual_charged_rate=None,
        documented_source='https://perpetual-alpha26.github.io/docs/#venue-mechanics',
        expected_net_pnl=None,scenario_only=True,production_fee_policy_changed=False,
        assumption='Published PAS positive base-rate multiplier=2; actual fill fee/feeToken govern charges',
        documented_target_scenario=None,stress_target_scenario=None)
    if row.get('baseline_long') is not True or row.get('baseline_short') is True:return result
    try:
        q=decimal(quantity,positive=True);metrics=row['metrics']
        quote=make_quote(book,context,now_ms,mark_timestamp_ms=context_ms)
        for name,multiplier in (('documented_target_scenario',2),('stress_target_scenario',6)):
            trade=estimate_trade('BUY',q,metrics['vwap'],row['baseline_stop'],row['baseline_target'],quote,
                FeeSchedule(0,base*multiplier,'DOCUMENTED_PAS_ESTIMATE' if multiplier==2 else 'UNCHANGED_6X_STRESS'),slippage_bps=5,holding_hours=1)
            result[name]={k:str(v) for k,v in asdict(trade).items()}
    except (ExchangeError,KeyError,ValueError):result['reason']='FRESH_COMPLETE_FROZEN_TARGET_SCENARIO_UNAVAILABLE'
    return result
