"""Production lockout tests: never replace the permission guard with a fake."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import config as legacy_config
import venue_config as config
import order_guard
from disabled_angel_client import DisabledAngelOneClient
from execution_adapters import SmartAPIExecutionAdapter, PaperExecutionAdapter
from execution_engine import PaperTrader, ReadOnlySmartConnectWrapper
from test_safety_v6 import NOW, IDENTITY, quote

ROOT = Path(__file__).resolve().parents[1]


class TransportTrap:
    """Any access reaching a broker proves that the boundary failed."""
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError('Transport must not be touched')


@pytest.mark.parametrize('allow', [False, True, 'false', None])
@pytest.mark.parametrize('venue', ['HYPERLIQUID_TESTNET', 'ANGEL_ONE', 'HYPERLIQUID_MAINNET'])
def test_phase0_never_authorizes_an_exchange_transport(monkeypatch, allow, venue):
    monkeypatch.setattr(config, 'ALLOW_LIVE_ORDERS', allow)
    monkeypatch.setattr(legacy_config, 'LIVE_MODE', True)
    monkeypatch.setattr(legacy_config, 'LIVE_VALIDATION_APPROVED', True)
    with pytest.raises(order_guard.OrderRoutingBlocked):
        order_guard.require_exchange_orders(venue)


@pytest.mark.parametrize('allow', [False, True])
@pytest.mark.parametrize('operation', ['_submit', 'execute', 'protect', 'cancel'])
def test_all_legacy_write_paths_stop_before_broker_access(monkeypatch, allow, operation):
    monkeypatch.setattr(config, 'ALLOW_LIVE_ORDERS', allow)
    monkeypatch.setattr(legacy_config, 'LIVE_MODE', True)
    monkeypatch.setattr(legacy_config, 'LIVE_VALIDATION_APPROVED', True)
    broker = TransportTrap()
    adapter = SmartAPIExecutionAdapter(broker, None, lambda: pytest.fail('Clock must not be called'))
    arguments = {
        '_submit': ({},),
        'execute': (None, 'BUY', 1, None, NOW),
        'protect': (None, 'SELL', 1, 1, NOW),
        'cancel': ('order-id',),
    }
    with pytest.raises(order_guard.OrderRoutingBlocked, match='ANGEL_ONE_EXECUTION_DISABLED'):
        getattr(adapter, operation)(*arguments[operation])
    assert broker.calls == []


def test_live_trader_cannot_activate_from_legacy_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy_config, 'LIVE_MODE', True)
    monkeypatch.setattr(legacy_config, 'LIVE_VALIDATION_APPROVED', True)
    monkeypatch.setattr(config, 'ALLOW_LIVE_ORDERS', False)
    broker = TransportTrap()
    adapter = SmartAPIExecutionAdapter(broker, None, lambda: NOW)
    with pytest.raises(order_guard.OrderRoutingBlocked):
        PaperTrader(environment='LIVE', adapter=adapter, clock=lambda: NOW,
                    csv_log_path=str(tmp_path/'unused.csv'))
    assert broker.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('allow', [False, True])
def test_disabled_sdk_client_needs_no_credentials(monkeypatch, allow):
    monkeypatch.setattr(config, 'ALLOW_LIVE_ORDERS', allow)
    with pytest.raises(order_guard.OrderRoutingBlocked, match='ANGEL_ONE_EXECUTION_DISABLED'):
        DisabledAngelOneClient()
    from test_login import run_login_test
    with pytest.raises(order_guard.OrderRoutingBlocked):
        run_login_test()


@pytest.mark.parametrize('method', [
    'placeOrder', 'modifyOrder', 'cancelOrder', 'placeOrderFullResponse',
    'gttCreateRule', 'gttModifyRule', 'gttCancelRule', '_request', '_postRequest',
    '_putRequest', '_deleteRequest', 'generateSession', 'create_order',
])
def test_read_only_proxy_cannot_forward_mutations_or_raw_transport(method):
    broker = TransportTrap()
    proxy = ReadOnlySmartConnectWrapper(broker)
    with pytest.raises((order_guard.OrderRoutingBlocked, AssertionError)):
        getattr(proxy, method)({})
    assert broker.calls == []


def test_read_only_proxy_preserves_explicit_reads():
    class Reader:
        def orderBook(self):
            return {'status': True, 'data': []}
    assert ReadOnlySmartConnectWrapper(Reader()).orderBook()['data'] == []


def test_paper_fill_remains_a_local_simulation():
    fill = PaperExecutionAdapter().execute(IDENTITY, 'BUY', 1, quote(), NOW)
    assert fill.order_id.startswith('paper-')


@pytest.mark.parametrize('value', ['', 'false', 'FALSE', '0', 'yes', 'invalid', 'true'])
def test_permission_environment_is_strict_and_credential_free(value):
    env = {key: val for key, val in os.environ.items()
           if not any(word in key.upper() for word in ('BROKER', 'ANGEL', 'WALLET', 'PRIVATE_KEY', 'TOTP'))}
    env['ALLOW_LIVE_ORDERS'] = value
    env['TRADING_VENUE'] = 'HYPERLIQUID_TESTNET'
    result = subprocess.run([
        sys.executable, '-c',
        'import config, json; print(json.dumps([config.TRADING_VENUE, config.ALLOW_LIVE_ORDERS]))',
    ], cwd=ROOT/'algo-trading-bot', env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ['HYPERLIQUID_TESTNET', value == 'true']


def test_runtime_environment_can_revoke_permission(monkeypatch):
    monkeypatch.setattr(config, 'ALLOW_LIVE_ORDERS', True)
    monkeypatch.setenv('ALLOW_LIVE_ORDERS', 'false')
    with pytest.raises(order_guard.OrderRoutingBlocked, match='ALLOW_LIVE_ORDERS_FALSE'):
        order_guard.require_exchange_orders('HYPERLIQUID_TESTNET')


def test_no_production_module_imports_the_live_angel_client():
    for path in (ROOT/'algo-trading-bot').glob('*.py'):
        if path.name.startswith('test_') or path.name == 'safety_test_support.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('SmartApi'):
                assert all(alias.name != 'SmartConnect' for alias in node.names), path.name
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith('SmartApi.smartConnect')
                           and alias.name != 'SmartApi' for alias in node.names), path.name


def test_signal_source_matches_the_tagged_baseline():
    baseline = subprocess.run([
        'git', 'show', 'nse-working-baseline:algo-trading-bot/signal_brain.py',
    ], cwd=ROOT, capture_output=True, check=True).stdout
    current = (ROOT/'algo-trading-bot/signal_brain.py').read_bytes()
    assert hashlib.sha256(current).digest() == hashlib.sha256(baseline).digest()


def test_clone_environment_contains_only_development_settings():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT/'algo-trading-bot/.env')
    assert values == {'TRADING_VENUE': 'HYPERLIQUID_TESTNET',
                      'EXECUTION_MODE': 'PAPER', 'ALLOW_LIVE_ORDERS': 'false'}
