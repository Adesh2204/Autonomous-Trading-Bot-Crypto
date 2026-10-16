"""Bounded rotation: confirmations are distinct completed bars, never quote polls."""
import config
from runtime_observation import observe_signal


def promote_reserves(stream,now):
    from signal_brain import generate_vwap_signal, detect_daily_bias
    states=list(stream.active_symbols.values())
    if not any(s.watchlist_role=='RESERVE' for s in states):
        return
    held=(stream.paper_trader.open_position or {}).get('token') if stream.paper_trader.has_open_position else None
    last=getattr(stream,'_last_reserve_promotion',None)
    cooling=last is not None and (now-last).total_seconds()<config.RESERVE_PROMOTION_COOLDOWN_SECONDS
    eligible=[]
    observations={}
    for state in states:
        o=observe_signal(state,stream.paper_trader,stream.schedule,now,generate_vwap_signal,detect_daily_bias)
        observations[state.token]=o
        if state.watchlist_role!='RESERVE':
            continue
        required=('session_data','warmup','feed','identity','signal_freshness','indicators','atr_floor',
                  'atr_hysteresis','symbol_state','quote_freshness','spread','depth','time','risk')
        valid=all(o.gates.get(g)=='PASS' for g in required) and o.bias in {'LONG_BIAS','SHORT_BIAS','NEUTRAL'}
        if not valid:
            state.promotion_confirmations=0
        elif o.candle_timestamp != getattr(state,'last_promotion_candle',None):
            state.promotion_confirmations+=1
        state.last_promotion_candle=o.candle_timestamp
        if valid and state.promotion_confirmations>=config.RESERVE_CONFIRMATION_CANDLES:
            eligible.append((o.opportunity_score,state))
    if cooling or not eligible:
        return
    primary=[s for s in states if s.watchlist_role=='PRIMARY']
    weak=[s for s in primary if s.token!=held and any(observations[s.token].gates.get(g)!='PASS'
          for g in ('session_data','warmup','feed','atr_floor','atr_hysteresis','symbol_state'))]
    if len(primary)>=config.SCREEN_TOP_N and not weak:
        return
    promoted=sorted(eligible,key=lambda pair:(-pair[0],pair[1].rank,pair[1].symbol))[0][1]
    demoted=sorted(weak,key=lambda s:(s.rank,s.symbol),reverse=True)[0] if weak else None
    if demoted:
        demoted.watchlist_role='RESERVE'
        demoted.promotion_confirmations=0
        demoted.last_promotion_time=now
    promoted.watchlist_role='PRIMARY'
    promoted.last_promotion_time=now
    promoted.promotion_confirmations=0
    stream._last_reserve_promotion=now
    event={'timestamp':str(now),'promoted':promoted.symbol,'demoted':demoted.symbol if demoted else None,
           'reason':'CURRENT_SESSION_CONFIRMED','confirmations':config.RESERVE_CONFIRMATION_CANDLES,
           'risk_budgets_reset':False}
    stream.telemetry.promotions.append(event)
    stream.paper_trader._event('RESERVE_PROMOTION',**event)
