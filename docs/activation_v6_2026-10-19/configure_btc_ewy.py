"""Human terminal entry point: refresh, review, approve, apply two leverage changes.

The existing approval function requires real interactive input. No orders,
protection, transfers, account-mode changes, or trading mandate are authorized.
Accepted configuration is applied immediately, with original guard/readbacks.
"""
from pathlib import Path
import json,os,sys,time
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run this command yourself in a real Terminal. No acceptance is generated from chat or redirected input.')
    os.environ.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',HL_DEX='pas',SIGNAL_DATA_MODE='PAS_NATIVE_ONLY')
    from types import SimpleNamespace
    from exchange.pas_operations import dispatch
    from exchange.pas_configuration import approve_configuration,execute_configuration
    from exchange.long_session import require_release,sha
    from exchange.paper_operations import active_source_hash
    from exchange.terminal_app import locked
    from exchange.base_exchange import ExchangeError
    release=HERE/'regression_release_final/test_receipt.json'
    require_release(ROOT,release,active_source_hash(ROOT),sha(release))
    state=ROOT/'runtime/testnet/anchorium-bot-1'
    if locked(state/'pas-configuration-owner.lock'):
        raise ExchangeError('ANOTHER_ACCOUNT_CONTROLLER_OR_CONFIGURATION_IS_ACTIVE')
    review=HERE/('human_configuration_'+str(time.time_ns()//1000000))
    args=SimpleNamespace(command='configuration-review',output=review,
        operator_confirmation=HERE/'operator_identity/operator_confirmation.json',
        organizer_confirmation=None,isolate_original_for_configuration=True)
    print('Fetching fresh unsigned evidence. You will review the exact plan below.')
    print('Accepting the exact phrase immediately applies BTC/EWY 1x CROSS only. It does not activate trading.')
    result=dispatch(ROOT,args)
    print(json.dumps(dict(status=result.get('status'),changes=result.get('configuration_plan',{}).get('changes'),
        blockers=result.get('configuration_plan',{}).get('blockers')),indent=2))
    plan=review/'account_configuration_plan.json';discovery=review/'discovery.json';acceptance=review/'acceptance.json'
    approved=approve_configuration(ROOT,plan,discovery,release,acceptance)
    print(json.dumps(approved,indent=2))
    applied=execute_configuration(ROOT,plan,discovery,release,acceptance,review/'applied')
    print(json.dumps(applied,indent=2,default=str))
    return 0 if applied.get('status')=='SELECTED_MARKETS_ONE_X_CROSS_VERIFIED' else 1


if __name__=='__main__':
    raise SystemExit(main())
