"""Full CLI + official SDK + real guards, ephemeral signer and fake exchange only."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
import pytest
from eth_account import Account
from exchange.base_exchange import ExchangeError
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager, NonceManager
from exchange.hyperliquid_client import HyperliquidClient
from exchange.leverage_configuration import LeverageConfigurationApproval
from exchange import leverage_configuration
from exchange.sdk_transport import build_exchange
from test_live_exchange_execution import LiveInfoFixture, NOW, TEAM


def test_complete_ten_market_cli_paces_without_retrying_signed_actions(tmp_path, monkeypatch):
    signer = Account.create()
    public = LiveInfoFixture(signer.address)
    settings = {row['name']:dict(type='cross', value=20) for row in public.metadata['universe']}
    actions, waits, weights = [], [], []
    class Public:
        def __call__(self, payload):
            if payload['type'] == 'l2Book':
                public.book['time'] = public.now
            if payload['type'] == 'activeAssetData':
                public.active['leverage'] = deepcopy(settings[payload['coin']])
            return public(payload)
        def close(self):
            pass
    def blocked_http(*args, **kwargs):
        pytest.fail('HTTP_PROHIBITED_IN_EPHEMERAL_CONFIGURATION_FIXTURE')
    import requests
    monkeypatch.setattr(requests.Session, 'post', blocked_http)
    spec = importlib.util.spec_from_file_location('paced_cli', ROOT / 'scripts/configure_par_leverage.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    def wait(ms):
        assert 0 < ms <= 1000
        waits.append(ms)
        public.now += ms
    class Rates(HyperliquidRateLimitManager):
        def __init__(self, journal, **kwargs):
            super().__init__(journal, clock_ms=lambda: public.now, wait=wait, jitter=lambda:1, **kwargs)
        def _weight(self, *args, **kwargs):
            super()._weight(*args, **kwargs)
            weights.append(self._usage())
    monkeypatch.setattr(cli, 'HyperliquidRateLimitManager', Rates)
    monkeypatch.setattr(cli, 'HyperliquidClient', lambda **kwargs: HyperliquidClient(Public(), clock_ms=lambda:public.now, **kwargs))
    monkeypatch.setattr(cli, 'ClockHealthMonitor', lambda **kwargs: ClockHealthMonitor(monotonic_ms=lambda:public.now, **kwargs))
    monkeypatch.setattr(cli, 'NonceManager', lambda path, address, **kwargs: NonceManager(path, address, clock_ms=lambda:public.now, **kwargs))
    monkeypatch.setattr(cli, 'read_api_key', lambda root:(signer.key.hex(), ['EPHEMERAL_IN_MEMORY']))
    def fake_sdk(wallet, client, nonces, sink):
        sdk = build_exchange(wallet, client, nonces, sink, offline=True)
        def post(url, *, json, **kwargs):
            action = deepcopy(json['action'])
            symbol = next(name for name, market in client.markets.items() if market.asset_id == action['asset'])
            assert url.endswith('/exchange') and action == dict(type='updateLeverage', asset=client.market(symbol).asset_id, isCross=True, leverage=1)
            settings[symbol] = dict(type='cross', value=1)
            actions.append(action)
            public.budget['nRequestsUsed'] += 1
            return SimpleNamespace(status_code=200, json=lambda:dict(status='ok', response=dict(type='default')))
        sdk.session.post = post
        return sdk
    monkeypatch.setattr(leverage_configuration, 'build_exchange', fake_sdk)
    approval = tmp_path / 'approval.json'
    approval.write_text(json.dumps(dict(approval_reference='EPHEMERAL_OFFLINE_FIXTURE_ONLY', team_address=TEAM,
        signer_address=signer.address, expires_ms=NOW+1_200_000, manual_wallet_verified=True)))
    # The CLI's first expiry check uses wall time; fixture time matches its configured clock.
    import time
    monkeypatch.setattr(time, 'time_ns', lambda: public.now * 1_000_000)
    output = tmp_path / 'receipt.json'
    monkeypatch.setattr(sys, 'argv', ['configure_par_leverage.py', '--apply', '--team-address', TEAM,
        '--api-wallet-address', signer.address, '--state-directory', str(tmp_path/'state'),
        '--output', str(output), '--manual-confirmation-file', str(approval)])
    assert cli.main() == 0
    receipt = json.loads(output.read_text())
    assert receipt['status'] == 'ALL_TEN_ONE_X_CROSS_VERIFIED'
    assert receipt['configuration_actions_submitted'] == len(actions) == 10
    assert receipt['orders_submitted'] == 0 and len(receipt['results']) == 10
    assert waits and max(weights) <= 1080
    assert all(row['observed_leverage'] == dict(type='cross',value=1) for row in receipt['final_verification']['rows'])
    assert not any(call['type'] in {'order','cancel','approveAgent','userSetAbstraction'} for call in public.calls)


def test_pacing_rechecks_approval_before_any_account_read(tmp_path):
    from exchange.leverage_configuration import wait_for_configuration_reads
    journal = ExecutionJournal(tmp_path/'budget.sqlite', session_id='OFFLINE_PACING', team_address=TEAM)
    now = [NOW]
    rates = HyperliquidRateLimitManager(journal, clock_ms=lambda:now[0], wait=lambda ms:now.__setitem__(0,now[0]+ms))
    signer = Account.create().address
    approval = LeverageConfigurationApproval('OFFLINE_ONLY', TEAM, signer, NOW+500, True)
    rates.weights = [(NOW, 1000)]
    try:
        with pytest.raises(ExchangeError, match='EXPLICIT_MANUAL_LEVERAGE_CONFIGURATION_APPROVAL_REQUIRED'):
            wait_for_configuration_reads(rates, approval, TEAM, signer)
        assert rates.weights == [(NOW,1000)]
        assert rates.daily_used() == 0
    finally:
        journal.close()
