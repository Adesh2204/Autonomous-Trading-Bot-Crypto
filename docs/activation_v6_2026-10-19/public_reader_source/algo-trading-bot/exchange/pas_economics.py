"""Observation-only documented fee scenario alongside the unchanged stress guard."""
from dataclasses import asdict
from .base_exchange import decimal,ExchangeError
from .hyperliquid_market_data import make_quote
from .perpetual_economics import FeeSchedule,estimate_trade


def fee_scenarios(book,context,row,*,quantity,base_taker_rate,now_ms,context_ms,base_maker_rate=None):
    base=decimal(base_taker_rate,nonnegative=True)
    result=dict(base_taker_rate=str(base),documented_pas_rate_estimate=str(base*2),
        unchanged_signing_stress_rate=str(base*6),actual_charged_rate=None,
        documented_source='https://perpetual-alpha26.github.io/docs/#venue-mechanics',
        expected_net_pnl=None,scenario_only=True,production_fee_policy_changed=False,
        assumption='Published PAS positive base-rate multiplier=2; actual fill fee/feeToken govern charges',
        documented_target_scenario=None,stress_target_scenario=None)
    try:
        q=decimal(quantity,nonnegative=True);bid=book.bids[0].price;ask=book.asks[0].price
        oracle=decimal(context['oraclePx'],positive=True);mark=decimal(context['markPx'],positive=True)
        if not 0<=now_ms-book.timestamp_ms<=5000 or not 0<=now_ms-context_ms<=5000:
            raise ExchangeError('STALE_COST_SENSITIVITY')
        result.update(quantity=str(q),hourly_funding=str(decimal(context['funding'])),
            mark_oracle_divergence_bps=str((mark-oracle)/oracle*10000),
            book_mid_oracle_divergence_bps=str(((bid+ask)/2-oracle)/oracle*10000),
            documented_taker_roundtrip_fee=str(q*(ask+bid)*base*2),
            stress_taker_roundtrip_fee=str(q*(ask+bid)*base*6),
            immediate_roundtrip_spread=str(q*(ask-bid)),
            maker_sensitivity_assumption='Hypothetical maker entry and taker exit; no maker fill or execution switch implied')
        if base_maker_rate is not None:
            maker=decimal(base_maker_rate)
            result['documented_maker_entry_taker_exit_fee']=str(q*(ask*maker*2+bid*base*2))
    except (ExchangeError,KeyError,IndexError):result['cost_sensitivity_reason']='FRESH_BOTH_SIDE_CONTEXT_REQUIRED'
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
