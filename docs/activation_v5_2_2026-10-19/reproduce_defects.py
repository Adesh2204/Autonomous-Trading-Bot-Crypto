"""Reproduce prior source defects against the exact V4 commit, without HTTP."""
from pathlib import Path
import json,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from test_activation_v5_2 import ready_report,NOW
from exchange.pas_controller import assess
from exchange.pas_funding import current_funding

def old_module(path):
    raw=subprocess.check_output(['git','show','289e6fd:'+path],cwd=R,text=True)
    namespace={'__package__':'exchange','__name__':'exchange.v4_reproduction'}
    exec(compile(raw,'V4:'+path,'exec'),namespace)
    return namespace

old=old_module('algo-trading-bot/exchange/pas_controller.py')['assess']
r=ready_report();r['native_proof_verification']['markets']=['pas:BTC'];r['signals'][0]['symbol']='pas:EWY'
cross=dict(before=old(r,NOW)['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE'],
    after=assess(r,NOW)['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE'])
assert cross==dict(before=True,after=False)
r=ready_report();r['liquidity']['pas:BTC']['evidence_evaluation']['economically_viable_notional']='NaN'
try:old(r,NOW);error=None
except Exception as e:error=type(e).__name__
assert error=='InvalidOperation' and not assess(r,NOW)['gates']['EXECUTABLE_OPPORTUNITY_AVAILABLE']
old_funding=old_module('algo-trading-bot/exchange/pas_funding.py')['current_funding']
f=ready_report()['funding'];f['observed_ms']='bad'
try:old_funding(f,NOW);clock_error=None
except Exception as e:clock_error=type(e).__name__
assert clock_error=='TypeError' and current_funding(f,NOW)['status']=='USDP_STALE'
(O/'reproductions.json').write_text(json.dumps(dict(observed_ms=time.time_ns()//1000000,
    baseline_commit='289e6fd',fixture_only=True,exchange_writes=0,
    cross_market_protection_signal=cross,nonfinite_capacity=dict(before_error=error,after='BLOCKED_NO_EXCEPTION'),
    invalid_cached_funding_clock=dict(before_error=clock_error,after='USDP_STALE_NO_EXCEPTION'),
    tests='test_activation_v5_2.py and full source-matched regression'),indent=2)+'\n')
print('Three original failures reproduced; corrected behavior verified')
