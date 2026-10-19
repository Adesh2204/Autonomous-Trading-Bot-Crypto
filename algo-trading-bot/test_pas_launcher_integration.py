"""Actual PAS launcher/preflight integration using unsigned in-memory /info fixtures.

No account signer, exchange transport, real market history or activation is used.
Only public transport, wall clock and Git subprocess boundaries are substituted.
"""
from copy import deepcopy
import json

import pytest

from exchange.base_exchange import ExchangeError
from exchange.competition_market import SCORING_START_MS
from exchange.hyperliquid_client import HyperliquidClient
from exchange.rate_limits import PasCandleBudget
from test_exchange_migration import TEAM
from test_pas_active_leverage_readiness import AccountFixture, SIGNER
from test_pas_launcher_regressions import ROOT, runner


class LauncherInfoFixture(AccountFixture):
    def __init__(self):
        super().__init__()
        self.now = SCORING_START_MS + 600_000
        self.state['assetPositions'] = []
        self.agents = [dict(address=SIGNER, validUntil=self.now + 86_400_000)]
        for context in self.contexts:
            context['openInterest'] = '0'

    def __call__(self, payload):
        if payload['type'] == 'perpDexLimits':
            self.calls.append(deepcopy(payload))
            return dict(totalOiCap='50000000', coinToOiCap=[
                [row['name'], '10000000'] for row in self.metadata['universe']])
        if payload['type'] == 'l2Book':
            self.book['time'] = self.now
        return super().__call__(payload)


@pytest.fixture
def launcher_path(monkeypatch, tmp_path):
    fixture = LauncherInfoFixture()
    client = HyperliquidClient(fixture, clock_ms=lambda: fixture.now, venue='pas')
    # Real 300-slot limiter; its finite wait advances only the offline clock.
    client.candle_budget = PasCandleBudget(clock_ms=lambda: fixture.now)
    monkeypatch.setattr(runner, 'HyperliquidClient', lambda **kwargs: client)
    monkeypatch.setattr(runner.time, 'time_ns', lambda: fixture.now * 1_000_000)
    monkeypatch.setattr(runner.time, 'sleep',
                        lambda seconds: setattr(fixture, 'now', fixture.now + int(seconds * 1000)))
    for name, value in dict(
        TRADING_VENUE='HYPERLIQUID_TESTNET', HL_NETWORK='testnet', HL_DEX='pas',
        HL_COMPETITION_MARKET='pas', EXECUTION_MODE='HYPERLIQUID_TESTNET_LIVE',
        ALLOW_LIVE_ORDERS='true',
    ).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('API_WALLET_PRIVATE_KEY', raising=False)
    import exchange.live_runtime as runtime
    monkeypatch.setattr(runtime, 'build_live_runtime',
                        lambda **kwargs: pytest.fail('NO_SIGNER_OR_RUNTIME_MAY_BE_BUILT'))
    certificate = tmp_path / 'offline-certificate.json'
    profile = ROOT / 'configs/pas_btc_production.example.json'
    evidence = dict(
        status='READY_FOR_SCORED_PHASE', competition_market='pas', api_dex='pas',
        api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'}, active_base_assets=['BTC', 'EWY'],
        network='testnet', team_wallet=TEAM, api_wallet_address=SIGNER,
        commit_sha='offline-release', profile_sha256=runner.hashlib.sha256(profile.read_bytes()).hexdigest(),
        checks={name: True for name in runner.CRITICAL_TESTS},
        market_checks={symbol: {name: True for name in (
            'market_data', 'order_validation', 'controlled_order_lifecycle', 'actual_fill',
            'protection', 'exit', 'partial_fill', 'restart_recovery')}
            for symbol in ('pas:BTC', 'pas:EWY')},
    )
    certificate.write_text(json.dumps(evidence))
    arguments = [
        '--run-live', '--confirm-live-testnet', '--team-wallet', TEAM,
        '--api-wallet-address', SIGNER, '--approval-id', 'OFFLINE_ONLY_NO_PERMISSION',
        '--approval-expires-ms', str(fixture.now + 600_000), '--fee-scale-verified', '1',
        '--certification-report', str(certificate),
    ]
    git_calls = []
    def git_output(args, **kwargs):
        git_calls.append(args)
        return 'offline-release\n' if args[1] == 'rev-parse' else ''
    monkeypatch.setattr(runner.subprocess, 'check_output', git_output)
    return fixture, arguments, certificate, evidence, git_calls


def assert_both_public_markets_read(fixture):
    assert {row['req']['coin'] for row in fixture.calls if row['type'] == 'candleSnapshot'} == {
        'pas:BTC', 'pas:EWY'}
    assert {row['coin'] for row in fixture.calls if row['type'] == 'l2Book'} == {
        'pas:BTC', 'pas:EWY'}
    assert all(row['type'] not in {'order', 'updateLeverage', 'approveAgent'} for row in fixture.calls)


@pytest.mark.parametrize('wrong_market', ['pas:BTC', 'pas:EWY'])
@pytest.mark.parametrize('wrong_target', [0, 2, 20, 'isolated'])
def test_actual_launcher_preflight_rejects_each_wrong_leverage_market(launcher_path, wrong_market, wrong_target):
    fixture, arguments, _, _, git_calls = launcher_path
    if wrong_target == 'isolated':
        fixture.active_margin_modes[wrong_market] = 'isolated'
    else:
        fixture.active_leverages[wrong_market] = wrong_target
    with pytest.raises(SystemExit, match='current read-only preflight checks failed'):
        runner.main(arguments)
    assert_both_public_markets_read(fixture)
    assert any(row['type'] == 'activeAssetData' and row['coin'] == wrong_market
               for row in fixture.calls)
    assert not git_calls  # Failed leverage preflight cannot even consume a certificate.


@pytest.mark.parametrize('damage,expected', [
    ('tracked_source', 'CERTIFICATION_SOURCE_OR_CONFIG_DIRTY'),
    ('untracked_source', 'CERTIFICATION_SOURCE_OR_CONFIG_DIRTY'),
    ('untracked_profile', 'CERTIFICATION_SOURCE_OR_CONFIG_DIRTY'),
    ('missing_profile_hash', 'CERTIFICATION_SELECTED_PROFILE_MISMATCH'),
    ('different_selected_profile', 'CERTIFICATION_SELECTED_PROFILE_MISMATCH'),
    ('clean', 'protection policy remains disabled'),
])
def test_actual_launcher_reaches_real_certificate_gates_after_both_asset_preflight(
        launcher_path, monkeypatch, tmp_path, damage, expected):
    fixture, arguments, certificate, evidence, git_calls = launcher_path
    if damage == 'missing_profile_hash':
        evidence.pop('profile_sha256')
        certificate.write_text(json.dumps(evidence))
    elif damage == 'different_selected_profile':
        # Still inside allowed risk bounds: only fresh certification can approve it.
        profile = json.loads((ROOT / 'configs/pas_btc_production.example.json').read_text())
        profile['risk']['risk_fraction'] = '0.0024'
        selected = tmp_path / 'different-approved-shape.json'
        selected.write_text(json.dumps(profile))
        arguments += ['--profile', str(selected)]
    statuses = dict(tracked_source=' M scripts/run_pas_btc.py\n',
                    untracked_source='?? scripts/unreviewed.py\n',
                    untracked_profile='?? configs/unreviewed.json\n')
    if damage in statuses:
        def dirty_git(args, **kwargs):
            git_calls.append(args)
            if args[1] == 'rev-parse':
                return 'offline-release\n'
            assert '--untracked-files=all' in args
            return statuses[damage]
        monkeypatch.setattr(runner.subprocess, 'check_output', dirty_git)
    exception = SystemExit if damage == 'clean' else ExchangeError
    with pytest.raises(exception, match=expected):
        runner.main(arguments)
    assert_both_public_markets_read(fixture)
    assert {row['coin'] for row in fixture.calls if row['type'] == 'activeAssetData'} == {
        'pas:BTC', 'pas:EWY'}
    assert any(args[1] == 'rev-parse' for args in git_calls)
    assert any(args[1] == 'status' for args in git_calls)


def test_actual_launcher_rejects_weakened_profile_before_public_reads(launcher_path, tmp_path):
    fixture, arguments, _, _, git_calls = launcher_path
    profile = json.loads((ROOT / 'configs/pas_btc_production.example.json').read_text())
    profile['risk']['max_reconnect_failures'] = 6
    selected = tmp_path / 'weaker.json'
    selected.write_text(json.dumps(profile))
    with pytest.raises(ExchangeError, match='RELIABILITY_OR_MARGIN_POLICY_WEAKENED'):
        runner.main(arguments + ['--profile', str(selected)])
    assert not fixture.calls and not git_calls


def test_profile_replacement_during_preflight_cannot_reach_runtime(
        launcher_path, monkeypatch, tmp_path):
    fixture, arguments, _, _, _ = launcher_path
    selected = tmp_path / 'selected-profile.json'
    original_bytes = (ROOT / 'configs/pas_btc_production.example.json').read_bytes()
    selected.write_bytes(original_bytes)
    replacement = json.loads(original_bytes)
    replacement['risk']['risk_fraction'] = '0.0024'
    original_preflight = runner.read_only_preflight

    def replace_after_preflight(*args, **kwargs):
        result = original_preflight(*args, **kwargs)
        selected.write_text(json.dumps(replacement))
        return result

    monkeypatch.setattr(runner, 'read_only_preflight', replace_after_preflight)
    monkeypatch.setattr(runner, 'load_reliability_policy',
                        lambda _path: (None, {}, type('Policy', (), {'enabled': True})()))
    with pytest.raises(ExchangeError, match='PROFILE_CHANGED_AFTER_VALIDATION'):
        runner.main(arguments + ['--profile', str(selected)])
    assert_both_public_markets_read(fixture)
    assert not any(row['type'] in {'order', 'updateLeverage', 'approveAgent'}
                   for row in fixture.calls)
