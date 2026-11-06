"""Human terminal entry point: refresh, review, approve, apply 1x CROSS on the carry markets.

Same route as docs/continuous_2026-10-24/configure_hype.py, with the carry
configuration scope: the plan targets the carry basket (BTC, ETH, HYPE, SP500,
USDJPY) as well as the scalper markets, so only markets not already at 1x CROSS
(ETH, SP500 and USDJPY on 25 Oct) appear as changes. The existing approval
function requires real interactive input. No orders, protection, transfers or
account-mode changes are authorized; no runtime may be running because it
shares the signer and nonce store.
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
    import subprocess
    for name in ('run_continuous.py start','run_carry.py start'):
        if subprocess.run(['pgrep','-f',name],capture_output=True).returncode==0:
            raise SystemExit(f'A runtime is running ({name}). Stop it first (stop.flag + SIGTERM).')
    from types import SimpleNamespace
    from exchange.pas_operations import dispatch
    from exchange.pas_configuration import approve_configuration,execute_configuration
    from exchange.long_session import require_release,sha
    from exchange.paper_operations import active_source_hash
    from exchange.terminal_app import locked
    from exchange.base_exchange import ExchangeError
    release=HERE/'regression_release/test_receipt.json'
    require_release(ROOT,release,active_source_hash(ROOT),sha(release))
    state=ROOT/'runtime/testnet/anchorium-bot-1'
    if locked(state/'pas-configuration-owner.lock'):
        raise ExchangeError('ANOTHER_ACCOUNT_CONTROLLER_OR_CONFIGURATION_IS_ACTIVE')
    journal=state/'pas-configuration.sqlite'
    if journal.exists():
        # The configuration journal is bound to one plan session (see AGENTS.md, 25 Oct 01:05 IST).
        archived=state/('pas-configuration_hype_2026-10-25.sqlite')
        if archived.exists():
            raise SystemExit(f'{journal} exists and {archived} is taken; archive it by hand first.')
        for suffix in ('-wal','-shm',''):     # sidecars move with the database
            part=Path(str(journal)+suffix)
            if part.exists():
                part.rename(str(archived)+suffix)
        print(f'Archived the completed HYPE configuration journal as {archived.name}')
    review=HERE/('carry_configuration_'+str(time.time_ns()//1000000))
    args=SimpleNamespace(command='configuration-review',output=review,
        operator_confirmation=ROOT/'docs/activation_v6_2026-10-19/operator_identity/operator_confirmation.json',
        organizer_confirmation=None,isolate_original_for_configuration=True,configuration_scope='CARRY')
    print('Fetching fresh unsigned evidence. You will review the exact plan below.')
    print('Accepting the exact phrase immediately applies 1x CROSS to the listed carry markets only. It places no order.')
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
