"""Confirmed PAS account, snapshot, and OI regressions; synthetic reads only."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from exchange.base_exchange import ExchangeError, MarketSpec, Quote
from exchange.competition_market import SCORING_START_MS
from exchange.competition_snapshot import CompetitionSnapshotRecorder
from exchange.exchange_rules import HyperliquidOrderValidator, RiskPermission, ValidationContext
from exchange.order_lifecycle import OrderRequest
from test_pas_migration import PasFixture, TEAM

NOW = SCORING_START_MS + 10_000


def test_unified_usdp_nav_uses_spot_balance_once_and_requires_exact_collateral():
    fixture = PasFixture()
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.hyperliquid_account import HyperliquidAccount

    client = HyperliquidClient(fixture, clock_ms=lambda: fixture.now, venue='pas')
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    fixture.state['marginSummary']['accountValue'] = '123456'
    fixture.state['assetPositions'][0]['position']['unrealizedPnl'] = '450'

    equity = account.get_equity()
    assert equity.reported_account_value == D('1000')
    assert equity.collateral_balance == D('1000')
    assert equity.valuation_source == 'spotClearinghouseState.USDP.total'

    # USDPR is not interchangeable with the runtime-mapped PAS USDP token. A
    # missing balance is zero (and cannot fund an order); a mismapped token ID
    # is malformed evidence and must fail closed.
    fixture.spot['balances'] = [row for row in fixture.spot['balances'] if row['coin'] == 'USDPR']
    assert account.get_equity().reported_account_value == 0
    fixture.spot['balances'] = [dict(coin='USDPR', token=77, total='999999', hold='0')]
    with pytest.raises(ExchangeError, match='COLLATERAL_TOKEN_MISMATCH'):
        account.get_equity()


class _Journal:
    def __init__(self):
        self.values = {}
        self.events = []

    def control(self, key, value=None):
        if value is None:
            return self.values.get(key)
        self.values[key] = value

    def event(self, kind, ts, **values):
        self.events.append((kind, ts, values))


class _SnapshotSession:
    def __init__(self, *, quote_time_offset=0):
        self.journal = _Journal()
        self.execution = SimpleNamespace(entries_paused=False)
        self.peak_equity = None
        self.reference_ms = NOW + 2_000
        self.quote_time_offset = quote_time_offset
        self.quote_call_reference = None
        self.client = SimpleNamespace(
            api_dex='pas', api_market='pas:BTC',
            api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'},
            markets={'pas:BTC': object(), 'pas:EWY': object()},
            collateral_token_name='USDP',
        )
        self.state = SimpleNamespace(
            equity=SimpleNamespace(reported_account_value=D('1000')),
            positions={}, fills={}, funding={},
        )
        self.recovery = SimpleNamespace(
            recover=lambda: SimpleNamespace(ready=True), state=self.state,
        )
        self.market = SimpleNamespace(client=self.client, get_quote=self._quote)

    def clock_ms(self):
        return self.reference_ms

    def _quote(self, symbol):
        self.quote_call_reference = self.reference_ms
        return SimpleNamespace(
            symbol=symbol,
            timestamp_ms=self.reference_ms + self.quote_time_offset,
            mark_timestamp_ms=self.reference_ms,
            mark=D('100'), oracle=D('100'),
        )


def test_snapshot_uses_current_clock_after_recovery():
    session = _SnapshotSession()
    record = CompetitionSnapshotRecorder(session).observe(now_ms=NOW)
    assert session.quote_call_reference == NOW + 2_000
    assert record['status'] == 'RECORDED'
    assert record['observed_at_utc'].endswith('12:00:12+00:00')


def test_snapshot_still_rejects_quote_newer_than_post_read_reference():
    session = _SnapshotSession(quote_time_offset=1)
    record = CompetitionSnapshotRecorder(session).observe(now_ms=NOW)
    assert record['status'] == 'SKIPPED'
    assert record['reason'] == 'SNAPSHOT_BLOCKED:ExchangeError'
    assert session.execution.entries_paused


def _risk_context(symbol='pas:BTC', *, orders=(), dex_oi='1000'):
    specs = {
        'pas:BTC': MarketSpec('pas:BTC', 4, 20, 100),
        'pas:EWY': MarketSpec('pas:EWY', 3, 20, 101),
    }
    client = SimpleNamespace(
        competition_mode=True, api_market='pas:BTC',
        api_markets={'BTC': 'pas:BTC', 'EWY': 'pas:EWY'},
        ready=True, markets=specs, market=lambda key: specs[key],
    )
    contexts = {
        'pas:BTC': {'openInterest': '10' if symbol == 'pas:BTC' else '0', 'oraclePx': '100'},
        'pas:EWY': {'openInterest': '0', 'oraclePx': '100'},
    }
    request = OrderRequest(symbol, 'BUY', '.1', '100')
    quote = Quote(symbol, NOW, D('99.99'), D('100.01'), D('100'), D('100'),
                  D('100'), D('100'), D('100'), D('0'), mark_timestamp_ms=NOW)
    readiness = SimpleNamespace(account_ready=True, observed_ms=NOW,
                                agent_expiry_ms=NOW + 60_000, team_address=TEAM)
    context = ValidationContext(
        specs[symbol], 'metadata', 'metadata', NOW, quote, readiness, {}, tuple(orders),
        {'user': TEAM, 'coin': symbol, 'leverage': {'type': 'cross', 'value': 20},
         'maxTradeSzs': ['100', '100'], 'availableToTrade': ['100000', '100000']},
        NOW,
        {'coinToOiCap': [['pas:BTC', '10000000'], ['BTC', '10000000'],
                         ['pas:EWY', '5000000'], ['EWY', '5000000']],
         'oiSzCapPerPerp': '100000', 'totalOiCap': '100000000'},
        contexts, True, leverage=20, fills=(), reconciled=True, oracle_ms=NOW,
        dex_total_oi_notional=D(dex_oi), dex_oi_observed_ms=NOW,
    )
    permission = RiskPermission('regression', symbol, 'BUY', D('.1'), NOW,
                                limit_price=D('100'))
    return client, request, context, permission


def _validate(client, request, context, permission):
    return HyperliquidOrderValidator(client).validate(request, context, permission, NOW)


@pytest.mark.parametrize('wrong_target', [1, 19, 21])
def test_pas_entry_rejects_non_target_cross_leverage(wrong_target):
    client, request, context, permission = _risk_context()
    active = dict(context.active_asset, leverage={'type': 'cross', 'value': wrong_target})
    result = _validate(client, request, replace(context, leverage=wrong_target, active_asset=active), permission)
    assert not result.allowed and result.code == 'INVALID_LEVERAGE'


def test_pas_entry_rejects_isolated_and_accepts_exact_20x_cross():
    client, request, context, permission = _risk_context()
    assert _validate(client, request, context, permission).allowed
    isolated = dict(context.active_asset, leverage={'type': 'isolated', 'value': 20})
    result = _validate(client, request, replace(context, active_asset=isolated), permission)
    assert not result.allowed and result.code == 'INVALID_LEVERAGE'


def test_pas_entry_rejects_target_above_runtime_metadata_maximum():
    client, request, context, permission = _risk_context()
    insufficient = MarketSpec('pas:BTC', 4, 19, 100)
    client.markets['pas:BTC'] = insufficient
    result = _validate(client, request, replace(context, spec=insufficient), permission)
    assert not result.allowed and result.code == 'INVALID_LEVERAGE'


def test_pas_active_btc_pending_orders_reserve_symbol_cap_from_list_pair_limits():
    pending = {'coin': 'pas:BTC', 'oid': 11, 'cloid': 'c11', 'side': 'B',
               'sz': '.1', 'limitPx': '100', 'reduceOnly': False}
    client, request, context, permission = _risk_context(orders=(pending,))
    limits = dict(context.limits, coinToOiCap=[['pas:BTC', '1015'], ['BTC', '1015'],
                                              ['pas:EWY', '5000000'], ['EWY', '5000000']])
    context = replace(context, limits=limits)
    result = _validate(client, request, context, permission)
    assert not result.allowed and result.code == 'OPEN_INTEREST_CAPACITY'


def test_batch_and_sequential_pending_orders_are_reserved_once_and_accumulate():
    first = {'coin': 'pas:BTC', 'oid': 10, 'cloid': 'c10', 'side': 'B',
             'sz': '.04', 'limitPx': '100', 'reduceOnly': False}
    second = {'coin': 'pas:BTC', 'oid': 12, 'cloid': 'c12', 'side': 'B',
              'sz': '.04', 'limitPx': '100', 'reduceOnly': False}
    # Duplicate transport rows for oid/cloid 10 must not reserve the same order twice.
    client, request, context, permission = _risk_context(orders=(first, second, dict(first)))
    # 99% of 1030 is 1019.7: 1018 fits only if the duplicate is counted once;
    # the later sequential projection of 1024 still exceeds that entry ceiling.
    limits = dict(context.limits, coinToOiCap=[['pas:BTC', '1030'], ['BTC', '1030'],
                                              ['pas:EWY', '5000000'], ['EWY', '5000000']])
    context = replace(context, limits=limits)
    result = _validate(client, request, context, permission)
    assert result.allowed and result.audit['reserved_open_order_quantity'] == '0.08'

    # A later preflight sees both the older unresolved order and the prior
    # sequential entry still open, so the next entry cannot reuse their capacity.
    sequential_client, sequential_request, sequential_context, sequential_permission = _risk_context(
        orders=(first,))
    sequential_context = replace(sequential_context, limits=limits)
    assert _validate(sequential_client, sequential_request, sequential_context,
                     sequential_permission).allowed
    prior_entry = {'coin': 'pas:BTC', 'oid': 13, 'cloid': 'c13', 'side': 'B',
                   'sz': '.1', 'limitPx': '100', 'reduceOnly': False}
    sequential_context = replace(sequential_context, open_orders=(first, prior_entry))
    blocked = _validate(sequential_client, sequential_request, sequential_context,
                        sequential_permission)
    assert not blocked.allowed and blocked.code == 'OPEN_INTEREST_CAPACITY'


def test_pas_pending_ewy_entry_reserves_shared_dex_cap_and_ewy_is_active():
    pending_ewy = {'coin': 'pas:EWY', 'oid': 20, 'cloid': 'e20', 'side': 'A',
                   'sz': '.2', 'limitPx': '100', 'reduceOnly': False}
    client, request, context, permission = _risk_context(orders=(pending_ewy,), dex_oi='49999980')
    limits = dict(context.limits, totalOiCap='100000000')
    context = replace(context, limits=limits)
    result = _validate(client, request, context, permission)
    assert not result.allowed and result.code == 'OPEN_INTEREST_CAPACITY'
    assert result.audit['reserved_open_order_dex_notional'] == '20.0'

    ewy_client, ewy_request, ewy_context, ewy_permission = _risk_context('pas:EWY')
    allowed = _validate(ewy_client, ewy_request, ewy_context, ewy_permission)
    assert allowed.allowed
    unsupported = replace(ewy_request, symbol='pas:ETH')
    denied = _validate(ewy_client, unsupported, ewy_context, ewy_permission)
    assert denied.code == 'INVALID_MARKET'


def test_snapshot_accepts_fresh_quotes_received_after_request_started():
    session = _SnapshotSession()
    calls = []
    def advancing_quote(symbol):
        session.reference_ms += 100
        calls.append(symbol)
        return SimpleNamespace(symbol=symbol, timestamp_ms=session.reference_ms,
                               mark_timestamp_ms=session.reference_ms,
                               mark=D('100'), oracle=D('100'))
    session.market.get_quote = advancing_quote
    record = CompetitionSnapshotRecorder(session).observe(now_ms=NOW)
    assert record['status'] == 'RECORDED'
    assert calls == ['pas:BTC', 'pas:EWY']
    assert set(record['mark_prices']) == {'pas:BTC', 'pas:EWY'}


def test_snapshot_includes_ewy_position_and_rejects_outside_completion_window():
    session = _SnapshotSession()
    session.state.positions = {'pas:EWY': SimpleNamespace(quantity=D('3'), unrealized_pnl=D('7'))}
    record = CompetitionSnapshotRecorder(session).observe(now_ms=NOW)
    assert record['status'] == 'RECORDED'
    assert record['exposure_notional'] == D('300')
    assert record['unrealized_pnl'] == D('7')
    assert record['active_positions']['pas:EWY']['quantity'] == D('3')
    late = _SnapshotSession()
    late.reference_ms = SCORING_START_MS + 60_000
    assert CompetitionSnapshotRecorder(late).observe(now_ms=NOW)['status'] == 'SKIPPED'


def test_ewy_fills_are_reconciled_while_historical_par_is_excluded():
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.hyperliquid_account import HyperliquidAccount
    fixture = PasFixture()
    fixture.fills.append(dict(fixture.fills[0], coin='pas:EWY', tid=999))
    fixture.fills.append(dict(fixture.fills[0], coin='par:BTC', feeToken='USDPR', tid=1000))
    fixture.fills.append(dict(fixture.fills[0], coin='pas:ETH', tid=1001))
    client = HyperliquidClient(fixture, clock_ms=lambda: fixture.now)
    client.startup()
    fills = HyperliquidAccount(client, TEAM).get_complete_fills(0, fixture.now)
    assert {fill.symbol for fill in fills} == {'pas:BTC', 'pas:EWY'}
    assert len(fills) == 2


def test_ewy_funding_is_not_discarded_as_non_btc():
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.hyperliquid_account import HyperliquidAccount
    fixture = PasFixture()
    def transport(payload):
        if payload['type'] == 'userFunding':
            return [{'time': fixture.now, 'hash': 'ewy-funding',
                     'delta': {'type': 'funding', 'coin': 'pas:EWY', 'usdc': '2', 'szi': '3', 'fundingRate': '.001'}}]
        return fixture(payload)
    client = HyperliquidClient(transport, clock_ms=lambda: fixture.now)
    client.startup()
    events = HyperliquidAccount(client, TEAM).get_funding(0, fixture.now)
    assert len(events) == 1 and events[0].symbol == 'pas:EWY'
    assert events[0].collateral == 'USDP'
