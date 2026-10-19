"""Offline/no-sign tests: no exchange client, key, nonce or SDK submission."""
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from exchange.base_exchange import ExchangeError
from exchange.live_runtime import verified_fee_scale

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pas_launcher_regressions', ROOT / 'scripts/run_pas_btc.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def fee_client(**overrides):
    values = dict(ready=True, clock_ms=lambda: 1000, metadata_timestamp_ms=900,
                  api_dex='pas', markets={'pas:BTC': object(), 'pas:EWY': object()},
                  dex_identity={'deployerFeeScale': '99'},
                  metadata={'universe': [
                      {'name': 'pas:BTC', 'deployerFeeScale': '1.0'},
                      {'name': 'pas:EWY', 'deployerFeeScale': '1.0'},
                      {'name': 'pas:ETH', 'deployerFeeScale': '9.0'}]})
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fee_scale_comes_from_each_active_asset_not_dex_identity():
    assert verified_fee_scale(fee_client(), '1') == Decimal('1')


@pytest.mark.parametrize('rows,expected', [
    ([{'name': 'BTC'}, {'name': 'EWY', 'deployerFeeScale': '1'}], 'UNAVAILABLE'),
    ([{'name': 'BTC', 'deployerFeeScale': '1'}, {'name': 'EWY', 'deployerFeeScale': '2'}], 'MISMATCH'),
    ([{'name': 'BTC', 'deployerFeeScale': '1'}], 'MISMATCH'),
    ([{'name': 'BTC', 'deployerFeeScale': '1'}] * 2, 'UNAVAILABLE'),
])
def test_incomplete_or_unequal_active_fees_fail_closed(rows, expected):
    with pytest.raises(ExchangeError, match=expected):
        verified_fee_scale(fee_client(metadata={'universe': rows}), '1')


def test_stale_fee_metadata_and_manual_mismatch_block():
    with pytest.raises(ExchangeError, match='NOT_CURRENT'):
        verified_fee_scale(fee_client(metadata_timestamp_ms=-100000), '1')
    with pytest.raises(ExchangeError, match='MANUAL_VERIFICATION_MISMATCH'):
        verified_fee_scale(fee_client(), '0')


def test_launcher_missing_imports_are_resolved():
    assert callable(runner.load_reliability_policy)
    assert callable(runner.HumanLiveApproval)


def test_pair_list_oi_caps_supports_btc_and_ewy():
    client = fee_client()
    limits = {'coinToOiCap': [['BTC', '10000000'], ['pas:EWY', '1000000']],
              'totalOiCap': '50000000'}
    assert runner.parse_oi_caps(limits, client) == {
        'pas:BTC': Decimal('10000000'), 'pas:EWY': Decimal('1000000')}


@pytest.mark.parametrize('pairs', [
    [['BTC', '10']],
    [['BTC', '10'], ['pas:BTC', '20'], ['EWY', '10']],
    [['BTC', '10'], ['EWY']],
    [['BTC', '10'], ['EWY', 'NaN']],
])
def test_bad_oi_limits_fail_closed(pairs):
    with pytest.raises(ExchangeError):
        runner.parse_oi_caps({'coinToOiCap': pairs, 'totalOiCap': '50'}, fee_client())


def test_profile_exactly_two_assets_but_one_global_position(tmp_path):
    path = ROOT / 'configs/pas_btc_production.example.json'
    profile, risk, scanner = runner.load_profile(path)
    assert profile['base_assets'] == ['BTC', 'EWY']
    assert risk.max_positions == 1 and risk.leverage == 1 and scanner.top_n == 1
    profile['base_assets'].append('ETH')
    changed = tmp_path / 'expanded.json'
    changed.write_text(json.dumps(profile))
    with pytest.raises(ExchangeError, match='PROFILE_IDENTITY_INVALID'):
        runner.load_profile(changed)


@pytest.mark.parametrize('caps', [
    {'btc': '10000000', 'dex_total': '50000000'},
    {'btc': '10000000', 'ewy': '10000001', 'dex_total': '50000000'},
    {'btc': '10000001', 'ewy': '10000000', 'dex_total': '50000000'},
    {'btc': '10000000', 'ewy': '10000000', 'dex_total': '50000001'},
    {'btc': '10000000', 'ewy': '10000000', 'dex_total': '50000000', 'eth': '10000000'},
])
def test_profile_cannot_omit_or_relax_active_oi_caps(tmp_path, caps):
    profile = json.loads((ROOT / 'configs/pas_btc_production.example.json').read_text())
    profile['production_oi_caps_usd'] = caps
    changed = tmp_path / 'invalid-oi.json'
    changed.write_text(json.dumps(profile))
    with pytest.raises(ExchangeError, match='COMPETITION_OI_CAPS_INVALID'):
        runner.load_profile(changed)


def test_btc_only_certificate_cannot_authorize_ewy(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda args, **kwargs:
                        'current\n' if args[1] == 'rev-parse' else '')
    evidence = dict(status='READY_FOR_SCORED_PHASE', competition_market='pas',
                    api_dex='pas', api_market='pas:BTC', commit_sha='current',
                    profile_sha256=runner.hashlib.sha256((ROOT / 'configs/pas_btc_production.example.json').read_bytes()).hexdigest(),
                    checks={name: True for name in runner.CRITICAL_TESTS})
    path = tmp_path / 'certificate.json'
    path.write_text(json.dumps(evidence))
    with pytest.raises(ExchangeError, match='NOT_CURRENT_OR_NOT_COMPLETE'):
        runner.verify_certification(path, 'pas', {'BTC': 'pas:BTC', 'EWY': 'pas:EWY'})
    evidence.update(api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'},
                    active_base_assets=['BTC', 'EWY'],
                    market_checks={symbol: {name: True for name in (
                        'market_data', 'order_validation', 'controlled_order_lifecycle',
                        'actual_fill', 'protection', 'exit', 'partial_fill', 'restart_recovery')}
                        for symbol in ('pas:BTC', 'pas:EWY')})
    path.write_text(json.dumps(evidence))
    runner.verify_certification(path, 'pas', evidence['api_markets'])


@pytest.mark.parametrize('status', [
    ' M algo-trading-bot/exchange/hyperliquid_market_data.py\n',
    '?? configs/uncertified.json\n',
    '?? scripts/unreviewed.py\n',
])
def test_certification_rejects_dirty_runtime_source_or_config(tmp_path, monkeypatch, status):
    def git_output(args, **_kwargs):
        if args[1] == 'rev-parse':
            return 'current\n'
        assert '--untracked-files=all' in args
        return status
    monkeypatch.setattr(runner.subprocess, 'check_output', git_output)
    evidence = dict(status='READY_FOR_SCORED_PHASE', competition_market='pas',
                    api_dex='pas', api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'},
                    active_base_assets=['BTC', 'EWY'], commit_sha='current',
                    checks={name: True for name in runner.CRITICAL_TESTS},
                    market_checks={symbol: {name: True for name in (
                        'market_data', 'order_validation', 'controlled_order_lifecycle',
                        'actual_fill', 'protection', 'exit', 'partial_fill', 'restart_recovery')}
                        for symbol in ('pas:BTC', 'pas:EWY')})
    path = tmp_path / 'certificate.json'
    path.write_text(json.dumps(evidence))
    with pytest.raises(ExchangeError, match='CERTIFICATION_SOURCE_OR_CONFIG_DIRTY'):
        runner.verify_certification(path, 'pas', evidence['api_markets'])


@pytest.mark.parametrize('field,value', [
    ('max_consecutive_order_errors', 4), ('max_reconnect_failures', 6),
    ('maintenance_buffer_multiple', '1'), ('holding_hours', '0'),
])
def test_profile_cannot_weaken_breakers_or_margin_assumptions(tmp_path, field, value):
    profile = json.loads((ROOT / 'configs/pas_btc_production.example.json').read_text())
    profile['risk'][field] = value
    path = tmp_path / 'weaker.json'
    path.write_text(json.dumps(profile))
    with pytest.raises(ExchangeError, match='RELIABILITY_OR_MARGIN_POLICY_WEAKENED'):
        runner.load_profile(path)


@pytest.mark.parametrize('certified_hash', [None, '0' * 64])
def test_certification_binds_the_exact_selected_profile(tmp_path, monkeypatch, certified_hash):
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda args, **kwargs:
                        'current\n' if args[1] == 'rev-parse' else '')
    profile = tmp_path / 'profile.json'
    profile.write_text('{}\n')
    certificate = tmp_path / 'certificate.json'
    certificate.write_text(json.dumps(dict(profile_sha256=certified_hash)))
    with pytest.raises(ExchangeError, match='CERTIFICATION_SELECTED_PROFILE_MISMATCH'):
        runner.verify_certification(certificate, 'pas', {'BTC': 'pas:BTC', 'EWY': 'pas:EWY'}, profile)


def test_runtime_builder_explicitly_selects_pas_without_constructing_signer():
    import ast
    source = (ROOT / 'algo-trading-bot/exchange/live_runtime.py').read_text()
    tree = ast.parse(source)
    builders = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == 'HyperliquidClient']
    assert len(builders) == 1
    assert any(k.arg == 'venue' and isinstance(k.value, ast.Constant) and k.value.value == 'pas'
               for k in builders[0].keywords)


@pytest.mark.parametrize('leverage_ready', [True, False])
def test_live_launcher_composes_dependencies_without_keys_or_transport(monkeypatch, leverage_ready):
    """Exercise formerly NameError-prone path using only mocked authorization evidence."""
    import exchange.live_runtime as runtime_module
    from exchange.competition_market import SCORING_START_MS
    team = '0x' + '1' * 40
    signer = '0x' + '2' * 40
    for name, value in {
        'TRADING_VENUE': 'HYPERLIQUID_TESTNET', 'HL_NETWORK': 'testnet',
        'HL_COMPETITION_MARKET': 'pas', 'EXECUTION_MODE': 'HYPERLIQUID_TESTNET_LIVE',
        'ALLOW_LIVE_ORDERS': 'true',
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('API_WALLET_PRIVATE_KEY', raising=False)
    monkeypatch.setattr(runner.time, 'time_ns', lambda: (SCORING_START_MS + 1000) * 1000000)
    names = ('configuration', 'pas_btc_ewy_discovery', 'btc_ewy_market_data',
             'network_and_venue', 'account_read_only', 'api_wallet', 'btc_ewy_account_leverage')
    preflight = dict(api_dex='pas', api_market='pas:BTC',
                     api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'},
                     checks={name: {'passed': True} for name in names})
    preflight['checks']['btc_ewy_account_leverage']['passed'] = leverage_ready
    monkeypatch.setattr(runner, 'read_only_preflight', lambda *a, **k: preflight)
    verified = []
    monkeypatch.setattr(runner, 'verify_certification', lambda path, dex, markets, profile: verified.append((dex, markets)))
    monkeypatch.setattr(runner, 'load_reliability_policy',
                        lambda path: (None, {}, SimpleNamespace(enabled=True)))
    built = []
    ran = []
    def fake_build(**kwargs):
        built.append(kwargs)
        return SimpleNamespace(run=lambda: ran.append(True))
    monkeypatch.setattr(runtime_module, 'build_live_runtime', fake_build)
    arguments = [
        '--run-live', '--confirm-live-testnet', '--team-wallet', team,
        '--api-wallet-address', signer, '--approval-id', 'offline-mocked-evidence',
        '--approval-expires-ms', str(SCORING_START_MS + 60000), '--fee-scale-verified', '1',
    ]
    if not leverage_ready:
        with pytest.raises(SystemExit, match='current read-only preflight checks failed'):
            runner.main(arguments)
        assert not built and not ran and not verified
        return
    assert runner.main(arguments) == 0
    assert verified == [('pas', preflight['api_markets'])]
    assert built[0]['approval'].signer_address == signer
    assert built[0]['risk_policy'].max_positions == 1
    assert ran == [True]


def test_unscoped_historical_approval_cannot_authorize_pas():
    from exchange.execution_safety import HumanLiveApproval, LiveAuthorization
    approval = HumanLiveApproval('old-approval', '0x' + '1'*40, '0x' + '2'*40, 9999, True)
    authorization = LiveAuthorization(approval, clock_ms=lambda: 1000)
    assert authorization.venue_identity is None
    with pytest.raises(Exception, match='EXPLICIT_MANUAL_LIVE_AUTHORIZATION_REQUIRED'):
        authorization.require(approval.team_address, approval.signer_address)


@pytest.mark.parametrize('market,assets,network', [
    ('par', ('BTC', 'EWY'), 'testnet'),
    ('pas', ('BTC',), 'testnet'),
    ('pas', ('BTC', 'EWY', 'ETH'), 'testnet'),
    ('pas', ('BTC', 'EWY'), 'mainnet'),
])
def test_wrong_approval_scope_fails_closed(market, assets, network):
    from exchange.execution_safety import HumanLiveApproval, LiveAuthorization
    approval = HumanLiveApproval('offline', '0x'+'1'*40, '0x'+'2'*40, 9999, True,
                                 competition_market=market, active_base_assets=assets, network=network)
    authorization = LiveAuthorization(approval, clock_ms=lambda: 1000)
    assert authorization.venue_identity is None
    with pytest.raises(Exception, match='EXPLICIT_MANUAL_LIVE_AUTHORIZATION_REQUIRED'):
        authorization.require(approval.team_address, approval.signer_address)


def test_pas_approval_still_requires_environment_identity_and_expiry(monkeypatch):
    from exchange.execution_safety import HumanLiveApproval, LiveAuthorization
    import venue_config
    for name, value in {'TRADING_VENUE': 'HYPERLIQUID_TESTNET',
                        'EXECUTION_MODE': 'HYPERLIQUID_TESTNET_LIVE',
                        'ALLOW_LIVE_ORDERS': True}.items():
        monkeypatch.setattr(venue_config, name, value)
    for name, value in {'TRADING_VENUE': 'HYPERLIQUID_TESTNET', 'HL_NETWORK': 'testnet',
                        'HL_DEX': 'pas', 'HL_COMPETITION_MARKET': 'pas',
                        'EXECUTION_MODE': 'HYPERLIQUID_TESTNET_LIVE',
                        'ALLOW_LIVE_ORDERS': 'true'}.items():
        monkeypatch.setenv(name, value)
    approval = HumanLiveApproval('offline', '0x'+'1'*40, '0x'+'2'*40, 9999, True,
                                 competition_market='pas', active_base_assets=('BTC', 'EWY'), network='testnet')
    authorization = LiveAuthorization(approval, clock_ms=lambda: 1000)
    authorization.require(approval.team_address, approval.signer_address)
    monkeypatch.setenv('HL_DEX', 'par')
    with pytest.raises(Exception, match='LIVE_RUNTIME_CONFIGURATION_REQUIRED'):
        authorization.require(approval.team_address, approval.signer_address)
    monkeypatch.setenv('HL_DEX', 'pas')
    authorization.clock_ms = lambda: 9999
    with pytest.raises(Exception, match='EXPLICIT_MANUAL_LIVE_AUTHORIZATION_REQUIRED'):
        authorization.require(approval.team_address, approval.signer_address)


def test_sdk_gate_rejects_fabricated_authorizer_even_with_correct_identity():
    from exchange.sdk_transport import OfficialSDKTransport
    from exchange.venue_profiles import SCORED
    from exchange.hyperliquid_client import RequestsInfoTransport
    from test_pas_active_markets import ready_client
    _, client = ready_client()
    client.transport = object.__new__(RequestsInfoTransport)
    fabricated = SimpleNamespace(venue_identity=SCORED.identity, require=lambda *a: None)
    with pytest.raises(ExchangeError, match='SIGNED_VENUE_PAS_AUTHORIZATION_REQUIRED'):
        OfficialSDKTransport._require_venue(client, fabricated)


def test_preflight_candle_window_keeps_300_and_recalculates_after_budget_wait(monkeypatch):
    now = [1800000000000]
    calls = []
    result = object()
    class Market:
        def get_candles(self, symbol, start, end, **kwargs):
            calls.append((symbol, start, end, kwargs['now_ms']))
            assert (end - start) // 60000 + 1 == 300
            if len(calls) == 1:
                error = ExchangeError('PAS_CANDLE_BUDGET_EXHAUSTED')
                error.retry_after_ms = 60000
                raise error
            return result
    waits = []
    def wait(seconds):
        waits.append(seconds)
        now[0] += round(seconds * 1000)
    monkeypatch.setattr(runner.time, 'sleep', wait)
    assert runner.read_preflight_candles(Market(), 'pas:EWY', 300,
        SimpleNamespace(clock_ms=lambda: now[0])) is result
    assert len(waits) == 1 and len(calls) == 2
    assert calls[1][1] > calls[0][1]


def test_preflight_does_not_wait_forever_on_impossible_budget_or_hide_missing_data(monkeypatch):
    def forbidden(_seconds):
        raise AssertionError('Impossible request must fail, not wait')
    monkeypatch.setattr(runner.time, 'sleep', forbidden)
    class Market:
        def get_candles(self, *_args, **_kwargs):
            error = ExchangeError('PAS_CANDLE_BUDGET_EXHAUSTED')
            error.retry_after_ms = None
            raise error
    with pytest.raises(ExchangeError, match='PAS_CANDLE_BUDGET_EXHAUSTED'):
        runner.read_preflight_candles(Market(), 'pas:BTC', 301,
            SimpleNamespace(clock_ms=lambda: 1800000000000))
