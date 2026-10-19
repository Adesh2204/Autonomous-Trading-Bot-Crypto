"""Offline identity/configuration guard tests; synthetic keys, no exchange HTTP."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from eth_account import Account
import pytest

from exchange.base_exchange import ExchangeError
from exchange.execution_safety import NonceManager
from exchange.execution_journal import fingerprint
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.leverage_configuration import (LeverageConfigurationApproval,
    LeverageConfigurationTransport, configuration_plan)
from exchange.practice_preflight import read_api_key, api_signer, verify_private_identity, check_local_nonce_ownership
from exchange.sdk_transport import build_exchange
from exchange import leverage_configuration
from test_live_exchange_execution import LiveInfoFixture, NOW, TEAM


def test_actual_address_derivation_needs_api_key_not_team_key(tmp_path, monkeypatch):
    monkeypatch.delenv('API_WALLET_PRIVATE_KEY', raising=False)
    wallet = Account.create()
    (tmp_path / '.env').write_text('TEAM_WALLET_PRIVATE_KEY=unused\n')
    with pytest.raises(ExchangeError, match='API_KEY_MISSING'):
        read_api_key(tmp_path)
    (tmp_path / '.env').write_text('API_WALLET_PRIVATE_KEY=' + wallet.key.hex() + '\n')
    report = verify_private_identity(tmp_path, wallet.address, TEAM)
    assert report['status'] == 'MATCH' and report['derived_public_address'] == wallet.address
    assert not report['signature_created'] and report['exchange_actions_submitted'] == 0
    assert wallet.key.hex() not in repr(report)


def test_conflicting_key_sources_stop_without_credential_error_text(tmp_path, monkeypatch):
    monkeypatch.delenv('API_WALLET_PRIVATE_KEY', raising=False)
    first, second = Account.create(), Account.create()
    (tmp_path / 'algo-trading-bot').mkdir()
    (tmp_path / '.env').write_text('API_WALLET_PRIVATE_KEY=' + first.key.hex() + '\n')
    (tmp_path / 'algo-trading-bot/.env').write_text('API_WALLET_PRIVATE_KEY=' + second.key.hex() + '\n')
    with pytest.raises(ExchangeError, match='^CONFLICTING_API_KEY_SOURCES$'):
        read_api_key(tmp_path)


@pytest.mark.parametrize('key,expected,team,code', [
    ('INVALID_DO_NOT_LOG', TEAM, TEAM, 'SEPARATE_VALID_API_IDENTITY_REQUIRED'),
    ('INVALID_DO_NOT_LOG', '0x' + '7' * 40, TEAM, 'API_KEY_INVALID'),
    ('0x' + '1' * 64, '0x' + '7' * 40, TEAM, 'API_PRIVATE_PUBLIC_ADDRESS_MISMATCH')])
def test_private_verification_errors_are_constant_codes(key, expected, team, code):
    with pytest.raises(ExchangeError, match='^' + code + '$'):
        api_signer(key, expected, team)


def test_local_nonce_probe_allocates_no_nonce_and_rejects_second_process(tmp_path):
    signer = Account.create()
    root = Path(__file__).resolve().parents[1]
    report = check_local_nonce_ownership(tmp_path / 'nonces.sqlite', signer.address, TEAM, root=root)
    assert report['second_process_rejected'] and not report['nonce_allocated']
    assert not report['remote_ownership_verified'] and report['lease_released_after_check']
    owner = NonceManager(tmp_path / 'nonces.sqlite', signer.address)
    try:
        assert owner.db.execute('SELECT * FROM nonces').fetchall() == []
    finally:
        owner.close()


def test_future_nonce_history_is_rejected_without_reset_or_new_nonce(tmp_path):
    signer = Account.create()
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / 'nonces.sqlite'
    owner = NonceManager(path, signer.address)
    stored = owner.clock_ms() + 1_000_000
    owner.db.execute('INSERT INTO nonces VALUES (?,?)', (signer.address.lower(), stored))
    owner.close()
    with pytest.raises(ExchangeError, match='NONCE_HISTORY_CLOCK_UNSAFE'):
        check_local_nonce_ownership(path, signer.address, TEAM, root=root)
    owner = NonceManager(path, signer.address)
    try:
        assert owner.db.execute('SELECT last FROM nonces').fetchone()[0] == stored
    finally:
        owner.close()


@pytest.fixture
def config(tmp_path, monkeypatch):
    signer = Account.create()
    public = LiveInfoFixture(signer.address)
    client = HyperliquidClient(public, clock_ms=lambda: NOW)
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    public.active['leverage']['value'] = 20
    nonces = NonceManager(tmp_path / 'nonces.sqlite', signer.address, clock_ms=lambda: NOW)
    approval = LeverageConfigurationApproval('SYNTHETIC_CONFIG_ONLY', TEAM, signer.address, NOW + 100000, True)
    calls, checks = [], []
    # Offline SDK fields, ephemeral key and in-memory sink only. No constructor HTTP.
    monkeypatch.setattr(leverage_configuration, 'build_exchange',
        lambda signer, client, nonces, sink: build_exchange(signer, client, nonces, sink, offline=True))
    class Fixture(LeverageConfigurationTransport):
        def transmit(self, payload):
            self.check(payload['action'])
            self.transmitted = True
            calls.append(payload['action'])
            return dict(status='ok', response=dict(type='default'))
    transport = Fixture(client, signer, TEAM, nonces, approval,
                        rates=SimpleNamespace(reserve_info=lambda query: None),
                        readiness_guard=lambda: checks.append(True))
    yield SimpleNamespace(transport=transport, client=client, account=account, public=public,
                          signer=signer, nonces=nonces, approval=approval, calls=calls, checks=checks)
    transport.close()
    nonces.close()


def test_plan_uses_only_runtime_par_assets_one_x_cross_and_no_actions(config):
    plan = configuration_plan(config.client, config.account)
    assert len(plan['rows']) == 10 and all(r['change_required'] for r in plan['rows'])
    assert all(r['symbol'].startswith('par:') and r['desired_leverage'] == dict(type='cross', value=1) for r in plan['rows'])
    assert all(r['asset_id'] == config.client.market(r['symbol']).asset_id for r in plan['rows'])
    assert plan['exchange_actions_submitted'] == 0 and not plan['actual_orders_permitted']
    assert not config.calls


def test_real_exposure_or_unresolved_order_blocks_plan(config):
    config.public.position('0.1')
    with pytest.raises(ExchangeError, match='FLAT_ACCOUNT_WITHOUT_ORDERS_REQUIRED'):
        configuration_plan(config.client, config.account)
    config.public.position('0')
    config.public.orders = [dict(coin='par:BTC', oid=1, side='B', sz='.1', limitPx='100', timestamp=NOW)]
    with pytest.raises(ExchangeError, match='FLAT_ACCOUNT_WITHOUT_ORDERS_REQUIRED'):
        configuration_plan(config.client, config.account)


@pytest.mark.parametrize('value', [True, 0, '20'])
def test_malformed_leverage_cannot_be_reported_as_aligned(config, value):
    config.public.active['leverage']['value'] = value
    with pytest.raises(ExchangeError, match='INVALID_ACTIVE_ASSET_CONFIGURATION'):
        configuration_plan(config.client, config.account)


@pytest.mark.parametrize('action', [
    dict(type='order', asset=2670000, isCross=True, leverage=1),
    dict(type='updateLeverage', asset=2670000, isCross=False, leverage=1),
    dict(type='updateLeverage', asset=2670000, isCross=True, leverage=20),
    dict(type='updateLeverage', asset=2670000, isCross=True, leverage=True),
    dict(type='updateLeverage', asset=0, isCross=True, leverage=1),
    dict(type='updateLeverage', asset=2670000, isCross=True, leverage=1, extra='not-allowed')])
def test_even_exact_fingerprinted_forbidden_actions_fail_before_nonce(config, action):
    config.transport.expected = fingerprint(action)
    with pytest.raises(ExchangeError, match='EXACT_ONE_X_CROSS_ACTION_PERMIT_REQUIRED'):
        config.transport.check(action)
    assert config.nonces.db.execute('SELECT * FROM nonces').fetchall() == []
    assert not config.calls


@pytest.mark.parametrize('changes', [dict(manual_wallet_verified=False), dict(scope='TRADE'),
                                   dict(expires_ms=NOW), dict(approval_reference=''),
                                   dict(team_address='0x' + '3' * 40)])
def test_manual_config_approval_is_exact_and_never_live_order_authorization(config, changes):
    invalid = replace(config.approval, **changes)
    with pytest.raises(ExchangeError, match='EXPLICIT_MANUAL_LEVERAGE_CONFIGURATION_APPROVAL_REQUIRED'):
        invalid.require(TEAM, config.signer.address, NOW)
    from exchange.execution_safety import LiveAuthorization
    with pytest.raises(Exception):
        LiveAuthorization(config.approval, clock_ms=lambda: NOW).require(TEAM, config.signer.address)
    assert not config.calls


def test_offline_fixed_leverage_sdk_action_and_single_use_permit(config):
    result = config.transport.set_one_x_cross('par:BTC')
    assert result['status'] == 'ok'
    assert config.calls == [dict(type='updateLeverage', asset=config.client.market('par:BTC').asset_id, isCross=True, leverage=1)]
    assert len(config.checks) >= 2
    assert config.transport.expected is None
    with pytest.raises(ExchangeError, match='EXACT_ONE_X_CROSS_ACTION_PERMIT_REQUIRED'):
        config.transport.check(config.calls[0])
    assert not hasattr(config.transport, 'order') and not hasattr(config.transport, 'perform')


def test_expired_or_failed_readiness_never_allocates_nonce(config):
    config.transport.approval = replace(config.approval, expires_ms=NOW)
    with pytest.raises(ExchangeError):
        config.transport.set_one_x_cross('par:BTC')
    assert config.nonces.db.execute('SELECT * FROM nonces').fetchall() == []
    config.transport.approval = config.approval
    def unavailable():
        raise ExchangeError('ACCOUNT_NOT_FRESH')
    config.transport.readiness_guard = unavailable
    with pytest.raises(ExchangeError, match='ACCOUNT_NOT_FRESH'):
        config.transport.set_one_x_cross('par:BTC')
    assert config.nonces.db.execute('SELECT * FROM nonces').fetchall() == []
    assert not config.calls


def test_http_uncertainty_consumes_permit_counts_attempt_and_hides_transport_error(config, monkeypatch):
    action = dict(type='updateLeverage', asset=config.client.market('par:BTC').asset_id, isCross=True, leverage=1)
    config.transport.expected = fingerprint(action)
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(True)
        raise TimeoutError('SENSITIVE_TRANSPORT_DETAIL_DO_NOT_EXPORT')
    monkeypatch.setattr(config.transport._sdk.session, 'post', unavailable)
    payload = dict(action=action, nonce=NOW, signature={}, vaultAddress=None, expiresAfter=None)
    with pytest.raises(ExchangeError, match='^CONFIGURATION_RESPONSE_UNCERTAIN$'):
        LeverageConfigurationTransport.transmit(config.transport, payload)
    assert config.transport.transmission_attempts == 1
    with pytest.raises(ExchangeError, match='EXACT_ONE_X_CROSS_ACTION_PERMIT_REQUIRED'):
        LeverageConfigurationTransport.transmit(config.transport, payload)
    assert len(calls) == 1


def test_apply_without_manual_file_stops_before_client_or_private_signer(tmp_path, monkeypatch):
    import importlib.util
    import sys
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('config_cli_test', root / 'scripts/configure_par_leverage.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    def prohibited(*args, **kwargs):
        pytest.fail('client/key use before human verification')
    monkeypatch.setattr(cli, 'HyperliquidClient', prohibited)
    monkeypatch.setattr(cli, 'read_api_key', prohibited)
    monkeypatch.setattr(sys, 'argv', ['configure_par_leverage.py', '--apply', '--team-address', TEAM,
        '--api-wallet-address', Account.create().address, '--state-directory', str(tmp_path / 'state'),
        '--output', str(tmp_path / 'report.json')])
    assert cli.main() == 1
    import json
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['error'] == 'MANUAL_WALLET_CONFIRMATION_REQUIRED'
    assert report['configuration_actions_submitted'] == report['orders_submitted'] == 0
    assert not (tmp_path / 'state').exists()
