"""Credential-free Phase 0 check. No broker SDK, login, wallet, or network."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))

import config
from disabled_angel_client import DisabledAngelOneClient
from order_guard import OrderRoutingBlocked, require_exchange_orders
from signal_brain import generate_vwap_signal
from venue_config import MigrationPolicyError, require_paper_migration


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def is_blocked(action):
    try:
        action()
    except OrderRoutingBlocked:
        return True
    return False


def main():
    try:
        require_paper_migration()
        migration_policy_valid = True
    except MigrationPolicyError:
        migration_policy_valid = False
    baseline = git('show', 'nse-working-baseline:algo-trading-bot/signal_brain.py')
    current = (ROOT/'algo-trading-bot/signal_brain.py').read_bytes()
    common_dir = Path(git('rev-parse', '--git-common-dir').decode().strip())
    if not common_dir.is_absolute():
        common_dir = ROOT/common_dir
    checks = {
        'project_is_perpetual_alpha': config.PROJECT_NAME == 'anchorium-perpetual-alpha',
        'independent_git_directory': common_dir.resolve() == (ROOT/'.git').resolve(),
        'migration_branch': git('branch', '--show-current').decode().strip() == 'perpetual-alpha-migration',
        'testnet_venue': config.TRADING_VENUE == 'HYPERLIQUID_TESTNET',
        'paper_execution_mode': config.EXECUTION_MODE == 'PAPER',
        'migration_policy_valid': migration_policy_valid,
        'orders_disabled': config.ALLOW_LIVE_ORDERS is False,
        'angel_one_client_disabled': is_blocked(DisabledAngelOneClient),
        'angel_one_order_boundary_disabled': is_blocked(lambda: require_exchange_orders('ANGEL_ONE')),
        'testnet_order_boundary_disabled': is_blocked(lambda: require_exchange_orders('HYPERLIQUID_TESTNET')),
        'signal_logic_present': callable(generate_vwap_signal),
        'signal_source_unchanged': hashlib.sha256(current).digest() == hashlib.sha256(baseline).digest(),
    }
    print(json.dumps({'project': config.PROJECT_NAME, 'checks': checks,
                      'passed': all(checks.values())}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
