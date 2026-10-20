"""Passive observations from the frozen function's last-bar local variables.

No alternative signal implementation or parameter override. Existing debuggers
are respected; unavailable internals remain NOT_OBSERVED.
"""
import inspect
import sys


def observe_frozen_call(call):
    from signal_brain import generate_vwap_signal
    evidence={}
    if sys.gettrace() is not None:
        return call(),dict(status='NOT_OBSERVED',reason='EXISTING_TRACE_HOOK')
    lines,start=inspect.getsourcelines(generate_vwap_signal)
    target=start+next(i for i,line in enumerate(lines) if line.strip()=='if locked:')
    code=generate_vwap_signal.__code__
    def trace(frame,event,arg):
        if frame.f_code is not code:
            return None
        if event=='line' and frame.f_lineno==target:
            v=frame.f_locals
            if v.get('i')==len(v.get('out',[]))-1:
                evidence.update(status='OBSERVED_FROZEN_LOCALS',anti_spam_pass=not v['locked'],
                    warmup_pass=bool(v['session_candle_count']>=v['min_candles_before_trade']),
                    brain_atr_pass=bool(v['current_atr_val']>=v['min_floor']),
                    raw_setup=any(bool(v[k][v['i']]) for k in ('raw_pullback_arr','raw_breakout_arr',
                                  'raw_pullback_short_arr','raw_breakdown_short_arr')))
        return trace
    try:
        sys.settrace(trace)
        result=call()
    finally:
        sys.settrace(None)
    return result,evidence
