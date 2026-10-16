"""Local API identity and nonce checks. No signature or exchange transport."""
import os
from pathlib import Path
import subprocess
import sys

from .base_exchange import ExchangeError
from .execution_safety import NonceManager
from .live_readiness import valid_address
from .single_position_guard import AccountExecutionLease


def read_api_key(root):
    """Reject conflicting sources; never return credentials in reports/errors."""
    from dotenv import dotenv_values
    sources = []
    for path in (Path(root) / '.env', Path(root) / 'algo-trading-bot/.env'):
        if path.is_symlink():
            raise ExchangeError('SYMLINK_API_CREDENTIAL_FILE_PROHIBITED')
        if path.is_file():
            values = dotenv_values(path, interpolate=False)
            value = values.get('API_WALLET_PRIVATE_KEY')
            if value:
                sources.append((str(path.relative_to(root)), value))
    if os.environ.get('API_WALLET_PRIVATE_KEY'):
        sources.append(('PROCESS_ENV', os.environ['API_WALLET_PRIVATE_KEY']))
    if not sources:
        raise ExchangeError('API_KEY_MISSING')
    if len({key for _, key in sources}) != 1:
        raise ExchangeError('CONFLICTING_API_KEY_SOURCES')
    return sources[0][1], [name for name, _ in sources]


def api_signer(private_key, expected_address, team_address):
    from eth_account import Account
    if (not valid_address(expected_address) or not valid_address(team_address) or
            expected_address.lower() == team_address.lower()):
        raise ExchangeError('SEPARATE_VALID_API_IDENTITY_REQUIRED')
    try:
        signer = Account.from_key(private_key)
    except Exception:
        raise ExchangeError('API_KEY_INVALID') from None
    if signer.address.lower() != expected_address.lower():
        raise ExchangeError('API_PRIVATE_PUBLIC_ADDRESS_MISMATCH')
    return signer


def verify_private_identity(root, expected_address, team_address):
    key = signer = None
    try:
        key, sources = read_api_key(root)
        signer = api_signer(key, expected_address, team_address)
        return dict(status='MATCH', derived_public_address=signer.address,
                    expected_public_address=expected_address, team_address=team_address,
                    key_sources=sources, signature_created=False, exchange_actions_submitted=0)
    finally:
        key = signer = None


def check_local_nonce_ownership(path, signer_address, team_address, *, root):
    """Bind/reuse the real durable store, test exclusion, allocate NO nonce.

    A lease cannot detect another host. This is deliberately local certification
    only. Never erase a binding/history to make a check pass.
    """
    account_lease = AccountExecutionLease(team_address)
    nonces = None
    try:
        nonces = NonceManager(path, signer_address)
        before = nonces.db.execute('SELECT last FROM nonces WHERE signer=?', (signer_address.lower(),)).fetchone()
        if before and (type(before[0]) is not int or before[0] < 0 or
                       before[0] + 1 > nonces.clock_ms() + nonces.max_future_ms):
            raise ExchangeError('NONCE_HISTORY_CLOCK_UNSAFE')
        code = """import sys
from exchange.execution_safety import NonceManager
from exchange.base_exchange import ExchangeError
try:
    owner=NonceManager(sys.argv[1],sys.argv[2])
except ExchangeError as exc:
    print('SECOND_OWNER_REJECTED' if str(exc)=='API_WALLET_ALREADY_LEASED' else 'UNEXPECTED_LEASE_ERROR')
    raise SystemExit(0 if str(exc)=='API_WALLET_ALREADY_LEASED' else 2)
else:
    owner.close()
    print('SECOND_OWNER_UNEXPECTEDLY_ACQUIRED')
    raise SystemExit(3)
"""
        env = dict(os.environ)
        # The child needs only a public address; it never inherits our API key.
        env.pop('API_WALLET_PRIVATE_KEY', None)
        env['PYTHONPATH'] = str(Path(root) / 'algo-trading-bot')
        child = subprocess.run([sys.executable, '-c', code, str(path), signer_address],
                               env=env, cwd=root, capture_output=True, text=True, timeout=15)
        after = nonces.db.execute('SELECT last FROM nonces WHERE signer=?', (signer_address.lower(),)).fetchone()
        if child.returncode != 0 or child.stdout.strip() != 'SECOND_OWNER_REJECTED' or before != after or not nonces.healthy:
            raise ExchangeError('LOCAL_NONCE_OWNER_CHECK_FAILED')
        return dict(status='HEALTHY_LOCAL', second_process_rejected=True,
                    ownership_scope='CURRENT_HOST_AND_OS_USER_ONLY', remote_ownership_verified=False,
                    nonce_database=str(Path(path).resolve()), nonce_allocated=False,
                    signature_created=False, exchange_actions_submitted=0,
                    owner_during_check=nonces.owner, lease_released_after_check=True)
    finally:
        if nonces is not None:
            nonces.close()
        account_lease.close()
