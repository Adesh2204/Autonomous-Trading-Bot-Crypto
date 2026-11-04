"""Human terminal entry point: raise pas:HYPE from 4x to 5x CROSS. Configuration only.

4 Nov 2026 21:15 IST (user, strict: "Only hype use full funding and make sure you use 5x leverage ... start buying more
and more of HYPE now"): at a 4x setting the exchange cannot hold 5x the equity in HYPE, so
exchange/carry_leverage_raise.py (target 5, scope CARRY_5X) refuses anything but 4x -> 5x CROSS on pas:HYPE, with only
the carry basket open (flat after the 4 Nov sell-all). It places, cancels and changes no order or position. The carry
runtime must be stopped: it shares the signer and nonce store.
"""
from pathlib import Path
import json, os, subprocess, sys, time
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run this command yourself in a real Terminal. No acceptance is generated from chat or redirected input.')
    os.environ.update(ANCHORIUM_PUBLIC_ONLY='true', EXECUTION_MODE='PAPER', ALLOW_LIVE_ORDERS='false', HL_DEX='pas',
                      SIGNAL_DATA_MODE='PAS_NATIVE_ONLY')
    for name in ('run_continuous.py', 'run_carry.py'):
        if subprocess.run(['pgrep', '-f', name], capture_output=True).returncode == 0:
            raise SystemExit(f'A runtime is running ({name}). Stop it first (stop.flag).')
    from exchange.carry_leverage_raise import raise_plan, approve_raise, execute_raise, read_only_client
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.long_session import require_release, sha
    from exchange.paper_operations import active_source_hash
    from exchange.terminal_app import locked
    from exchange.testnet_certification import TEAM
    release = HERE / 'regression_release/test_receipt.json'
    require_release(ROOT, release, active_source_hash(ROOT), sha(release))
    state = ROOT / 'runtime/testnet/anchorium-bot-1'
    if locked(state / 'pas-configuration-owner.lock'):
        raise SystemExit('Another configuration or account controller is active.')
    journal = state / 'pas-configuration.sqlite'
    if journal.exists():
        raise SystemExit(f'{journal} exists from an earlier configuration; archive it by hand first.')
    review = HERE / ('carry_5x_raise_' + str(time.time_ns() // 1000000))
    print('Reading the account (no signing). You will review the exact plan below.')
    client, reads = read_only_client(review / 'plan_reads')
    try:
        plan = raise_plan(ROOT, client, HyperliquidAccount(client, TEAM),
                          provenance=str(review / 'plan_reads/info_receipts.jsonl'), target=5)
    finally:
        client.close()
        reads.close()
    (review / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps(dict(changes=[(c['symbol'], c['before'], c['requested_action']['leverage']) for c in plan['changes']],
                          open_basket=plan['open_basket']['positions']), indent=2))
    print('Accepting the exact phrase immediately raises pas:HYPE from 4x to 5x CROSS. It places no order.')
    approved = approve_raise(ROOT, review / 'plan.json', release, review / 'acceptance.json')
    print(json.dumps(approved, indent=2))
    applied = execute_raise(ROOT, review / 'plan.json', release, review / 'acceptance.json', review / 'applied')
    print(json.dumps(applied, indent=2, default=str))
    return 0 if applied.get('status') == 'SELECTED_MARKETS_FIVE_X_CROSS_VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
