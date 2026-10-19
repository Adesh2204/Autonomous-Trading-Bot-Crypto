"""Paper migration cannot be activated by flags or runtime environment changes."""
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import order_guard
import venue_config
from exchange.base_exchange import MarketSpec, Quote
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.paper_execution import PaperExecution

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def paper_policy(monkeypatch):
    monkeypatch.setattr(venue_config, 'TRADING_VENUE', 'HYPERLIQUID_TESTNET')
    monkeypatch.setattr(venue_config, 'EXECUTION_MODE', 'PAPER')
    monkeypatch.setattr(venue_config, 'ALLOW_LIVE_ORDERS', False)
    for name in ('TRADING_VENUE', 'EXECUTION_MODE', 'ALLOW_LIVE_ORDERS'):
        monkeypatch.delenv(name, raising=False)


def simulator():
    return PaperExecution({'par:BTC': MarketSpec('par:BTC', 4, 40, 100000)},
                          fee_rate='0.001', clock_ms=lambda: 1000)


def test_paper_policy_has_no_activation_or_wallet_requirement():
    assert venue_config.require_paper_migration() == {
        'TRADING_VENUE': 'HYPERLIQUID_TESTNET', 'EXECUTION_MODE': 'PAPER',
        'ALLOW_LIVE_ORDERS': False}
    assert simulator().is_live is False


@pytest.mark.parametrize('name,value,reason', [
    ('EXECUTION_MODE', 'HYPERLIQUID', 'PAPER_MODE_REQUIRED'),
    ('EXECUTION_MODE', 'LIVE', 'PAPER_MODE_REQUIRED'),
    ('EXECUTION_MODE', '', 'PAPER_MODE_REQUIRED'),
    ('ALLOW_LIVE_ORDERS', 'true', 'LIVE_ORDERS_MUST_BE_FALSE'),
    ('ALLOW_LIVE_ORDERS', 'yes', 'LIVE_ORDERS_MUST_BE_FALSE'),
    ('ALLOW_LIVE_ORDERS', '0', 'LIVE_ORDERS_MUST_BE_FALSE'),
    ('TRADING_VENUE', 'HYPERLIQUID_MAINNET', 'TESTNET_REQUIRED'),
    ('TRADING_VENUE', 'ANGEL_ONE', 'TESTNET_REQUIRED'),
])
def test_environment_cannot_change_migration_policy(monkeypatch, name, value, reason):
    monkeypatch.setenv(name, value)
    with pytest.raises(venue_config.MigrationPolicyError, match=reason):
        venue_config.require_paper_migration()
    with pytest.raises(venue_config.MigrationPolicyError, match=reason):
        simulator()


@pytest.mark.parametrize('name,value', [
    ('EXECUTION_MODE', 'HYPERLIQUID'), ('ALLOW_LIVE_ORDERS', True),
    ('TRADING_VENUE', 'ANGEL_ONE')])
def test_imported_configuration_also_must_remain_paper(monkeypatch, name, value):
    monkeypatch.setattr(venue_config, name, value)
    with pytest.raises(venue_config.MigrationPolicyError):
        simulator()


def test_runtime_mode_change_stops_new_local_orders(monkeypatch):
    paper = simulator()
    monkeypatch.setenv('EXECUTION_MODE', 'HYPERLIQUID')
    with pytest.raises(venue_config.MigrationPolicyError, match='PAPER_MODE_REQUIRED'):
        paper.place_order('par:BTC', 'BUY', '1', '101')
    assert paper.orders == {} and paper.fills == [] and paper.positions == {}


def test_runtime_live_flag_stops_fill_before_ledger_changes(monkeypatch):
    paper = simulator()
    order = paper.place_order('par:BTC', 'BUY', '1', '101')
    quote = Quote('par:BTC', 1000, Decimal('100'), Decimal('101'),
                  Decimal('10'), Decimal('10'), Decimal('100.5'),
                  Decimal('100.5'), Decimal('100.5'), Decimal('0'))
    monkeypatch.setenv('ALLOW_LIVE_ORDERS', 'true')
    with pytest.raises(venue_config.MigrationPolicyError, match='LIVE_ORDERS_MUST_BE_FALSE'):
        paper.simulate_fill(order.order_id, quote)
    assert paper.orders[order.order_id].status == 'OPEN'
    assert paper.fills == [] and paper.positions == {}
    assert paper.cancel_order('par:BTC', order.order_id).status == 'CANCELLED'


@pytest.mark.parametrize('mode', ['PAPER', 'HYPERLIQUID', 'LIVE', 'invalid'])
@pytest.mark.parametrize('operation', ['place_order', 'cancel_order', 'modify_order'])
def test_every_mode_keeps_signed_actions_disabled(monkeypatch, mode, operation):
    monkeypatch.setattr(venue_config, 'EXECUTION_MODE', mode)
    monkeypatch.setattr(venue_config, 'ALLOW_LIVE_ORDERS', True)
    monkeypatch.setenv('EXECUTION_MODE', mode)
    monkeypatch.setenv('ALLOW_LIVE_ORDERS', 'true')

    class TransportTrap:
        def __getattr__(self, name):
            pytest.fail('Signed execution touched transport: ' + name)

    execution = HyperliquidExecution(TransportTrap())
    args = ('par:BTC', 'BUY', '1', '101') if operation == 'place_order' else ('par:BTC', '1')
    with pytest.raises(order_guard.OrderRoutingBlocked):
        getattr(execution, operation)(*args)


@pytest.mark.parametrize('name,value', [
    ('EXECUTION_MODE', 'HYPERLIQUID'), ('ALLOW_LIVE_ORDERS', 'true')])
def test_probe_rejects_invalid_policy_before_public_network(monkeypatch, capsys, name, value):
    spec = importlib.util.spec_from_file_location('paper_policy_probe', ROOT/'scripts/par_market_data_check.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    calls = []

    class PublicTransportTrap:
        def startup(self):
            pytest.fail('Probe connected despite invalid migration policy')

        def close(self):
            calls.append('closed')

    monkeypatch.setattr(probe, 'HyperliquidClient', PublicTransportTrap)
    monkeypatch.setattr(sys, 'argv', ['par_market_data_check.py'])
    monkeypatch.setenv(name, value)
    assert probe.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report['passed'] is False and report['error'] == 'MigrationPolicyError'
    assert report['orders_submitted'] == 0 and calls == ['closed']
