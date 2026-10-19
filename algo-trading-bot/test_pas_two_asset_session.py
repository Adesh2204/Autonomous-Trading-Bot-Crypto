"""Offline/no-sign tests for the PAS BTC+EWY single-position session."""
from contextlib import nullcontext
from decimal import Decimal as D
from types import SimpleNamespace
import sqlite3

import pytest

from exchange.base_exchange import ExchangeError, Position
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.live_readiness import verify_live_account_readiness
from exchange.position_states import PositionState, PositionStateJournal
from live_execution_session import LiveExecutionSession


PAS_MARKETS = {'BTC': 'pas:BTC', 'EWY': 'pas:EWY'}


class ContextClient:
    competition_mode = True
    ready = True
    api_market = 'pas:BTC'
    api_markets = PAS_MARKETS
    markets = {'pas:BTC': object(), 'pas:EWY': object()}
    dex_total_oi_notional = None
    dex_oi_observed_ms = None
    dex_oi_market_count = None

    def clock_ms(self):
        return 10_000

    def post_info(self, query):
        assert query == 'metaAndAssetCtxs'
        metadata = {'universe': [{'name': n} for n in ('BTC', 'EWY', 'OTHER')]}
        contexts = [
            {'openInterest': '2', 'oraclePx': '100'},
            {'openInterest': '3', 'oraclePx': '20'},
            {'openInterest': '4', 'oraclePx': '5'},
        ]
        return [metadata, contexts]

    def validate_metadata(self, metadata):
        assert len(metadata['universe']) == 3

    @staticmethod
    def canonical_market_name(name):
        return name if ':' in name else 'pas:' + name


def test_asset_contexts_include_both_selected_assets_and_keep_dex_wide_oi():
    client = ContextClient()
    result = HyperliquidMarketData(client).get_asset_contexts()
    assert set(result) == {'pas:BTC', 'pas:EWY'}
    assert client.dex_total_oi_notional == D(2) * D(100) + D(3) * D(20) + D(4) * D(5)
    assert client.dex_oi_market_count == 3


def test_asset_contexts_fail_closed_if_a_selected_asset_is_missing():
    client = ContextClient()
    client.api_markets = {'BTC': 'pas:BTC', 'EWY': 'pas:EWY'}
    client.post_info = lambda _query: [
        {'universe': [{'name': 'BTC'}]},
        [{'openInterest': '2', 'oraclePx': '100'}],
    ]
    client.validate_metadata = lambda _metadata: None
    with pytest.raises(ExchangeError, match='PAS_SELECTED_ASSET_CONTEXT_UNAVAILABLE'):
        HyperliquidMarketData(client).get_asset_contexts()


def test_readiness_rejects_disabled_mode_even_with_valid_two_asset_mapping():
    now = 1_000
    class Client:
        competition_mode = True
        api_dex = 'pas'
        api_market = 'pas:BTC'
        api_markets = PAS_MARKETS
        markets = {'pas:BTC': object(), 'pas:EWY': object()}
        ready = True
        metadata_timestamp_ms = now
        collateral_token_name = 'USDP'
        def clock_ms(self): return now

    class Journal:
        def __init__(self):
            self.db = sqlite3.connect(':memory:')
            self.db.execute('CREATE TABLE controls (name TEXT PRIMARY KEY, value TEXT)')
        def transaction(self): return nullcontext()

    class Account:
        client = Client()
        team_address = '0x' + '1' * 40
        def _query(self, name):
            return {
                'userAbstraction': 'disabled',
                'extraAgents': [{'address': '0x' + '2' * 40, 'validUntil': 2_000}],
                'userFees': {'userCrossRate': '0.001', 'userAddRate': '0.001'},
                'userRateLimit': {'n': 1},
            }[name]
        def get_equity(self): raise AssertionError('disabled mode must not be treated as funded')
        def get_open_orders(self): return []
        def get_positions(self): return []

    rate_limits = SimpleNamespace(journal=Journal(), healthy=True, safety_ready=True,
        observe_info=lambda *_args: None)
    clock_health = SimpleNamespace(healthy=True)
    result = verify_live_account_readiness(Account(), '0x' + '2' * 40,
        clock_health=clock_health, rate_limits=rate_limits, reconciliation_ready=True)
    assert result.status == 'NOT_READY'
    assert 'UNIFIED_ACCOUNT_REQUIRED' in result.reasons


def _session_for_positions(positions, open_orders=()):
    class Journal:
        def __init__(self): self.controls = {}; self.events = []
        def control(self, key, value): self.controls[key] = value
        def event(self, kind, timestamp, **data): self.events.append((kind, timestamp, data))

    journal = Journal()
    state = SimpleNamespace(positions=positions)
    account = SimpleNamespace(get_frontend_open_orders=lambda: list(open_orders))
    recovery = SimpleNamespace(state=state, last_report=SimpleNamespace(ready=True), account=account)
    session = LiveExecutionSession.__new__(LiveExecutionSession)
    session.competition_mode = True
    session.competition_markets = ('pas:BTC', 'pas:EWY')
    session.recovery = recovery
    session.startup_recovery = SimpleNamespace(state=SimpleNamespace(value='READY'))
    session.execution = SimpleNamespace(entries_paused=False, protection=None)
    session.clock_ms = lambda: 10_000
    session.journal = journal
    session.position_state = PositionStateJournal(journal, session.clock_ms, market='pas:BTC')
    return session


def test_restart_reconciliation_preserves_an_ewy_position_until_authoritatively_flat():
    held = Position('pas:EWY', D('2'), D('20'), D('0'), D('5'), None)
    session = _session_for_positions({'pas:EWY': held})
    session._sync_position_state()
    assert session.position_state.state == PositionState.PROTECTION_PENDING
    assert session.journal.controls['btc_position_state:pas:BTC']['evidence']['symbol'] == 'pas:EWY'

    session.recovery.state.positions = {}
    session._sync_position_state()
    assert session.position_state.state == PositionState.FLAT_RECONCILED


def test_global_position_lock_fails_closed_if_both_pas_assets_are_held():
    held_btc = Position('pas:BTC', D('1'), D('100'), D('0'), D('10'), None)
    held_ewy = Position('pas:EWY', D('1'), D('20'), D('0'), D('2'), None)
    session = _session_for_positions({'pas:BTC': held_btc, 'pas:EWY': held_ewy})
    with pytest.raises(ExchangeError, match='MULTIPLE_PAS_POSITIONS_VIOLATE_GLOBAL_LOCK'):
        session._sync_position_state()
    assert session.execution.entries_paused is True


def test_restart_keeps_unknown_global_state_when_an_ewy_order_is_pending():
    session = _session_for_positions({}, open_orders=[{'coin': 'pas:EWY', 'oid': 7}])
    session._sync_position_state()
    assert session.position_state.state == PositionState.UNKNOWN
    assert session.execution.entries_paused is True
    assert session.journal.events[-1][0] == 'POSITION_STATE_WAITING_FOR_ORDER_RECONCILIATION'


def test_position_state_journal_accepts_ewy_for_the_single_global_position():
    class Journal:
        def control(self, _key, _value): pass
        def event(self, *_args, **_kwargs): pass
    state = PositionStateJournal(Journal(), lambda: 10_000, market='pas:EWY')
    state.transition(PositionState.PROTECTION_PENDING, 'reconciled EWY position',
                     evidence={'symbol': 'pas:EWY'}, reconciled=True)
    assert state.report()['state'] == 'PROTECTION_PENDING'


def test_startup_clock_verification_requests_both_selected_markets(monkeypatch):
    from exchange import startup_recovery

    requested = []
    class MarketData:
        def __init__(self, _client): pass
        def get_orderbook(self, symbol):
            requested.append(symbol)
            return SimpleNamespace(timestamp_ms=10_000)
    monkeypatch.setattr(startup_recovery, 'HyperliquidMarketData', MarketData, raising=False)
    # The method imports HyperliquidMarketData locally; patch its defining module.
    import exchange.hyperliquid_market_data as market_data
    monkeypatch.setattr(market_data, 'HyperliquidMarketData', MarketData)
    monkeypatch.setattr(startup_recovery, 'verify_live_account_readiness', lambda *a, **k: None, raising=False)

    class ClockHealth:
        def observe(self, *_args): pass
    client = SimpleNamespace(competition_mode=True, api_market='pas:BTC', api_markets=PAS_MARKETS)
    execution = SimpleNamespace(clock_health=ClockHealth(), transport=SimpleNamespace(signer_address='offline'),
                                rate_limits=object())
    session = SimpleNamespace(execution=execution, market=SimpleNamespace(client=client))
    recovery = SimpleNamespace(account=object(), last_report=SimpleNamespace(ready=True))
    startup = startup_recovery.StartupRecovery.__new__(startup_recovery.StartupRecovery)
    startup.session, startup.recovery = session, recovery
    startup.clock = lambda: 10_000
    # Stub the imported readiness function so only book selection is exercised.
    import exchange.live_readiness as readiness
    monkeypatch.setattr(readiness, 'verify_live_account_readiness',
                        lambda *a, **k: SimpleNamespace(account_ready=True, reasons=()))
    assert startup._account_verification() == []
    assert requested == ['pas:BTC', 'pas:EWY']
