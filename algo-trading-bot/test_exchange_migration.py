"""Venue identity, closed data, fractional precision, lockout and brain parity."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pandas as pd
import pytest

import venue_config
from exchange.base_exchange import ExchangeError, MarketSpec, Quote, VenueMismatch, decimal_string
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_client import EXPECTED_MARKETS, HyperliquidClient
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.hyperliquid_market_data import HyperliquidMarketData, ParMarketDataEngine, parse_candle
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation
from exchange.paper_execution import PaperExecution
from frozen_strategy import FrozenStrategy
from order_guard import OrderRoutingBlocked
from strategy_freeze import StrategyFreezeError, verify_strategy_freeze

ROOT = Path(__file__).resolve().parents[1]
NOW = int(datetime(2026, 10, 2, 12, tzinfo=timezone.utc).timestamp() * 1000)
TEAM = '0x' + '1' * 40  # Synthetic public-address fixture; never queried on a network.


def candle_row(start, symbol='par:BTC', close='50000'):
    return dict(t=start, T=start + 59_999, s=symbol, i='1m', o='50000', h='50002',
                l='49998', c=close, v='1.25', n=4)


class PublicInfoFixture:
    def __init__(self):
        self.calls = []
        self.now = NOW
        self.dexes = [None, {'name': 'par'}]  # Non-production index proves runtime mapping.
        self.metadata = {'collateralToken': 20, 'universe': [
            dict(name=symbol, szDecimals=4, maxLeverage=10) for symbol in sorted(EXPECTED_MARKETS)]}
        self.contexts = [dict(markPx='50000', oraclePx='50010', funding='0.0001')
                         for _ in self.metadata['universe']]
        self.book = dict(coin='par:BTC', time=NOW, levels=[
            [dict(px='49999', sz='1.25')], [dict(px='50001', sz='1.75')]])
        self.history = None
        self.state = dict(assetPositions=[{'position': dict(coin='par:BTC', szi='0.1',
            entryPx='50000', unrealizedPnl='2', marginUsed='10', liquidationPx=None)}],
            marginSummary=dict(accountValue='1000', totalMarginUsed='10'), withdrawable='990')
        self.spot = dict(balances=[dict(coin='USDPR', token=20, total='1000', hold='10')])
        self.mode = 'unifiedAccount'
        self.orders = [dict(coin='par:BTC', oid=1)]
        self.fills = [dict(coin='par:BTC', time=NOW, tid=7, oid=1, side='B',
                           sz='0.1', px='50000', fee='0.5', feeToken='USDPR')]

    def __call__(self, payload):
        self.calls.append(deepcopy(payload))
        query = payload['type']
        responses = {'perpDexs': self.dexes, 'meta': self.metadata,
            'metaAndAssetCtxs': [self.metadata, self.contexts], 'l2Book': self.book,
            'clearinghouseState': self.state, 'spotClearinghouseState': self.spot,
            'userAbstraction': self.mode, 'openOrders': self.orders, 'userFills': self.fills}
        if query == 'candleSnapshot':
            req = payload['req']
            rows = self.history if self.history is not None else [
                candle_row(start, req['coin']) for start in range(req['startTime'], req['endTime']+1, 60_000)]
            return deepcopy(rows)
        if query == 'l2Book':
            return dict(deepcopy(self.book), coin=payload['coin'])
        return deepcopy(responses[query])


@pytest.fixture
def public():
    transport = PublicInfoFixture()
    # Historical PAR tests use an injected callable; never let this fixture
    # inherit the current PAS default or stand in for a production route.
    client = HyperliquidClient(transport, clock_ms=lambda: transport.now, venue='par')
    client.startup()
    return transport, client, HyperliquidMarketData(client)


def test_runtime_dex_index_and_asset_order_determine_ids(public):
    transport, client, _ = public
    assert client.dex_index == 1
    for index, row in enumerate(transport.metadata['universe']):
        assert client.market(row['name']).asset_id == 110000 + index
    assert transport.calls[:2] == [{'type': 'perpDexs'}, {'type': 'meta', 'dex': 'par'}]


@pytest.mark.parametrize('damage', ['missing_dex', 'missing_market', 'native_namespace',
                                    'duplicate_market', 'missing_precision', 'delisted'])
def test_startup_aborts_and_revokes_previous_registry(public, damage):
    transport, client, _ = public
    if damage == 'missing_dex':
        transport.dexes = [None]
    elif damage == 'missing_market':
        transport.metadata['universe'].pop()
    elif damage == 'native_namespace':
        transport.metadata['universe'][0]['name'] = 'BTC'
    elif damage == 'duplicate_market':
        transport.metadata['universe'][1] = deepcopy(transport.metadata['universe'][0])
    elif damage == 'missing_precision':
        del transport.metadata['universe'][0]['szDecimals']
    else:
        transport.metadata['universe'][0]['isDelisted'] = True
    with pytest.raises(VenueMismatch):
        client.startup()
    assert not client.ready and not client.markets
    with pytest.raises(VenueMismatch):
        client.market('par:BTC')


def test_native_endpoint_and_missing_startup_are_rejected():
    with pytest.raises(VenueMismatch):
        HyperliquidClient(base_url='https://api.hyperliquid.xyz')
    client = HyperliquidClient(PublicInfoFixture())
    with pytest.raises(VenueMismatch):
        HyperliquidMarketData(client).get_orderbook('par:BTC')


@pytest.mark.parametrize('query,kwargs', [
    ('meta', {'dex': ''}), ('meta', {'dex': 'native'}), ('l2Book', {'coin': 'BTC'}),
    ('l2Book', {'coin': 'xyz:BTC'}), ('order', {}), ('approveAgent', {}),
    ('candleSnapshot', {'req': {'coin': 'BTC'}}),
    ('meta', {'type': 'order'}), ('meta', {'signature': {}}),
])
def test_raw_info_boundary_cannot_fall_back_or_submit_actions(public, query, kwargs):
    transport, client, _ = public
    before = len(transport.calls)
    with pytest.raises(ExchangeError):
        client.post_info(query, **kwargs)
    assert len(transport.calls) == before


def test_quote_keeps_execution_mark_oracle_and_funding_distinct(public):
    transport, _, market = public
    quote = market.get_quote('par:BTC')
    assert (quote.bid, quote.ask, quote.mid) == (Decimal('49999'), Decimal('50001'), Decimal('50000'))
    assert quote.oracle == Decimal('50010') and quote.mark == Decimal('50000')
    assert quote.hourly_funding == Decimal('0.0001')
    assert transport.calls[-2]['dex'] == 'par'
    assert transport.calls[-1]['coin'] == 'par:BTC'


@pytest.mark.parametrize('damage', ['empty', 'crossed', 'stale', 'nan', 'wrong_coin'])
def test_invalid_execution_quotes_never_fall_back_to_marks(public, damage):
    transport, _, market = public
    if damage == 'empty':
        transport.book['levels'][0] = []
    elif damage == 'crossed':
        transport.book['levels'][0][0]['px'] = '50002'
    elif damage == 'stale':
        transport.book['time'] -= 6_000
    elif damage == 'nan':
        transport.book['levels'][0][0]['px'] = 'nan'
    else:
        original = transport.__class__.__call__
        # Use a transport wrapper because normal fixtures echo the requested coin.
        market.client.transport = lambda payload: (dict(transport.book, coin='BTC')
            if payload['type'] == 'l2Book' else original(transport, payload))
    with pytest.raises(ExchangeError):
        market.get_quote('par:BTC')


def test_metadata_change_invalidates_cached_specs(public):
    transport, client, market = public
    transport.metadata['universe'][0]['szDecimals'] = 2
    with pytest.raises(VenueMismatch):
        market.get_asset_contexts()
    assert not client.ready


def test_rest_excludes_open_candles_and_deduplicates_identical_history(public):
    transport, _, market = public
    row = candle_row(NOW-60_000)
    transport.history = [row, deepcopy(row), candle_row(NOW)]
    bars = market.get_candles('par:BTC', NOW-60_000, NOW+59_999)
    assert len(bars) == 1 and bars[0].volume == Decimal('1.25')
    assert transport.calls[-1]['req']['coin'] == 'par:BTC'


@pytest.mark.parametrize('damage', ['symbol', 'prices', 'volume', 'time', 'conflict'])
def test_corrupt_candle_history_is_rejected(public, damage):
    transport, _, market = public
    row = candle_row(NOW-60_000)
    if damage == 'symbol': row['s'] = 'BTC'
    elif damage == 'prices': row['h'] = '1'
    elif damage == 'volume': row['v'] = '-1'
    elif damage == 'time': row['t'] += 1
    transport.history = [row]
    if damage == 'conflict': transport.history.append(dict(row, c='50001'))
    with pytest.raises(ExchangeError):
        market.get_candles('par:BTC', NOW-60_000, NOW-1)


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', True, '0.00001'])
def test_invalid_or_sub_lot_quantity_never_rounds_up(value):
    with pytest.raises(ExchangeError):
        MarketSpec('par:BTC', 4, 40, 1).normalize_size(value)


@pytest.mark.parametrize('sz,quantity,expected', [(4, '0.123456', '0.1234'),
    (2, '1.9999', '1.99'), (1, '100.19', '100.1'), (0, '2.9', '2')])
def test_size_precision_uses_runtime_market_spec(sz, quantity, expected):
    spec = MarketSpec('par:BTC', sz, 10, 1)
    result = spec.normalize_size(quantity)
    assert result == Decimal(expected) and result <= Decimal(quantity)


@pytest.mark.parametrize('sz,price', [(4, '1234.567'), (1, '0.01234567'),
    (3, '50000.123'), (0, '0.0001234567'), (2, '100000.9'), (1, '9.999999')])
def test_price_precision_is_valid_and_preserves_limit(sz, price):
    spec = MarketSpec('par:BTC', sz, 10, 1)
    for side in ('BUY', 'SELL'):
        result = spec.normalize_price(price, side)
        text = decimal_string(result)
        if '.' in text:
            assert len(text.split('.')[1]) <= 6-sz
            assert len(result.normalize().as_tuple().digits) <= 5
        assert result <= Decimal(price) if side == 'BUY' else result >= Decimal(price)


def test_notional_validation_does_not_increase_risk_to_reach_minimum():
    spec = MarketSpec('par:BTC', 4, 40, 1)
    with pytest.raises(ExchangeError, match='MINIMUM_NOTIONAL'):
        spec.normalize_order('BUY', '0.00019', '50000')
    assert decimal_string(Decimal('100000')) == '100000'


@pytest.mark.parametrize('allow', [False, True])
@pytest.mark.parametrize('operation', ['place_order', 'cancel_order', 'modify_order'])
def test_new_execution_methods_remain_locked_even_with_opt_in(public, monkeypatch, allow, operation):
    transport, client, _ = public
    monkeypatch.setattr(venue_config, 'ALLOW_LIVE_ORDERS', allow)
    execution = HyperliquidExecution(client)
    before = len(transport.calls)
    args = ('par:BTC', 'BUY', '.1', '50000') if operation == 'place_order' else ('par:BTC', '1')
    with pytest.raises(OrderRoutingBlocked):
        getattr(execution, operation)(*args)
    assert len(transport.calls) == before


def test_order_preview_is_fractional_and_read_only(public):
    transport, client, _ = public
    before = len(transport.calls)
    order = HyperliquidExecution(client).preview_order('par:BTC', 'BUY', '.123456', '50000.123')
    assert order.quantity == Decimal('.1234')
    assert order.to_dict()['price'] == '50000'
    assert len(transport.calls) == before


def test_account_queries_use_team_address_and_par_scope(public):
    transport, client, _ = public
    account = HyperliquidAccount(client, TEAM)
    assert account.get_position('par:BTC').quantity == Decimal('.1')
    assert account.get_equity().reported_account_value == Decimal('1000')
    assert account.get_equity().collateral_balance == Decimal('1000')
    for payload in transport.calls[2:]:
        assert payload['user'] == TEAM
        if payload['type'] in {'clearinghouseState', 'openOrders'}:
            assert payload['dex'] == 'par'


def test_fills_filter_other_venues_and_use_composite_identity(public):
    transport, client, _ = public
    row = transport.fills[0]
    transport.fills += [deepcopy(row), dict(row, coin='par:ETH'), {'coin': 'BTC'}]
    fills = HyperliquidAccount(client, TEAM).get_fills()
    assert len(fills) == 2 and fills[0].identity != fills[1].identity


def test_account_rejects_wrong_mode_and_conflicting_fills(public):
    transport, client, _ = public
    account = HyperliquidAccount(client, TEAM)
    transport.mode = 'default'
    with pytest.raises(ExchangeError, match='UNIFIED'):
        account.get_equity()
    transport.fills.append(dict(transport.fills[0], fee='9'))
    with pytest.raises(ExchangeError, match='CONFLICTING'):
        account.get_fills()


def test_reconciliation_identifies_exposure_orders_and_unseen_fills(public):
    _, client, _ = public
    account = HyperliquidAccount(client, TEAM)
    reconciler = HyperliquidReconciliation(account)
    report = reconciler.reconcile({'par:BTC': '.2'}, known_order_ids=['2'])
    assert not report.matched and report.position_differences['par:BTC']['exchange'] == Decimal('.1')
    assert report.unexpected_order_ids == ('1',) and report.missing_order_ids == ('2',)
    matched = reconciler.reconcile({'par:BTC': '.1'}, known_order_ids=['1'],
                                   processed_fill_ids=[report.unseen_fills[0].identity])
    assert matched.matched and not matched.unseen_fills


def test_paper_execution_is_local_and_reduce_only_cannot_flip(public):
    transport, client, market = public
    execution = PaperExecution(client.markets, fee_rate='.0009', clock_ms=lambda: NOW)
    quote = market.get_quote('par:BTC')
    before = len(transport.calls)
    entry = execution.place_order('par:BTC', 'BUY', '.1', '50002')
    fill = execution.simulate_fill(entry.order_id, quote)
    assert fill.simulated and fill.quantity == Decimal('.1')
    with pytest.raises(ExchangeError, match='REDUCE_ONLY'):
        execution.place_order('par:BTC', 'SELL', '.2', '49999', reduce_only=True)
    exit_order = execution.place_order('par:BTC', 'SELL', '.1', '49999', reduce_only=True)
    execution.simulate_fill(exit_order.order_id, quote)
    assert execution.positions['par:BTC'] == 0 and len(transport.calls) == before


def test_stream_filters_open_bars_and_marks_invalid_data_unhealthy(public):
    _, _, market = public
    engine = ParMarketDataEngine(market, ['par:BTC'], history_bars=2)
    engine.connected = engine.reconciled = True
    engine.ingest({'channel': 'candle', 'data': [candle_row(NOW-60_000), candle_row(NOW)]})
    assert len(engine.get_completed_candles('par:BTC')) == 1
    engine.ingest({'channel': 'candle', 'data': candle_row(NOW, close='50001')})
    assert len(engine.candles['par:BTC']) == 2
    with pytest.raises(VenueMismatch):
        engine.ingest({'channel': 'l2Book', 'data': {'coin': 'BTC'}})
    with pytest.raises(ExchangeError, match='HEALTHY'):
        engine.get_quote('par:BTC')


def test_stream_quote_requires_fresh_book_and_context(public):
    transport, _, market = public
    engine = ParMarketDataEngine(market, ['par:BTC'])
    engine.connected = engine.reconciled = True
    engine.ingest({'channel': 'l2Book', 'data': transport.book})
    engine.ingest({'channel': 'activeAssetCtx', 'data': {'coin': 'par:BTC', 'ctx': transport.contexts[0]}})
    assert engine.get_quote('par:BTC').bid == Decimal('49999')
    transport.now += 6_000
    with pytest.raises(ExchangeError, match='STALE'):
        engine.get_quote('par:BTC')


def test_reconnect_rechecks_dex_repairs_history_and_resubscribes(public):
    transport, _, market = public
    class ImmediateStop(threading.Event):
        def wait(self, timeout=None): return self.is_set()
    stop = ImmediateStop()
    connections = []
    class Socket:
        def __init__(self, fail): self.fail=fail; self.sent=[]; self.reads=0; self.closed=False
        def send(self, message): self.sent.append(json.loads(message))
        def recv(self):
            self.reads += 1
            if self.fail: raise OSError('fixture disconnect')
            if self.reads == 1: return json.dumps({'channel':'l2Book','data':transport.book})
            stop.set()
            return json.dumps({'channel':'pong'})
        def close(self): self.closed=True
    def connect():
        socket=Socket(not connections)
        connections.append(socket)
        return socket
    engine=ParMarketDataEngine(market,['par:BTC'],connect=connect,history_bars=2)
    engine.run(stop,max_reconnects=1)
    assert engine.reconnections == 1 and engine.messages == 1
    assert len(connections) == 2 and all(socket.closed for socket in connections)
    assert all(len(socket.sent)==3 for socket in connections)
    assert sum(payload['type']=='perpDexs' for payload in transport.calls)==3
    assert len(engine.get_completed_candles('par:BTC')) == 2
    assert not engine.connected


def test_frozen_brain_parity_on_identical_utc_candle_inputs(public):
    _, _, market = public
    start = int(datetime(2026,10,1,23,50,tzinfo=timezone.utc).timestamp()*1000)
    bars = [parse_candle(candle_row(start+i*60_000),'par:BTC','1m') for i in range(30)]
    adapted = FrozenStrategy(market).evaluate_candles(bars)
    from signal_brain import generate_vwap_signal
    source = pd.DataFrame(dict(Timestamp=pd.to_datetime([b.timestamp_ms for b in bars],unit='ms',utc=True),
        Open=[float(b.open) for b in bars],High=[float(b.high) for b in bars],
        Low=[float(b.low) for b in bars],Close=[float(b.close) for b in bars],Volume=[float(b.volume) for b in bars]))
    pd.testing.assert_frame_equal(adapted,generate_vwap_signal(source))
    with pytest.raises(ValueError,match='GAP'):
        FrozenStrategy(market).evaluate_candles([bars[0],bars[2]])


@pytest.mark.parametrize('damage', ['brain', 'management', 'parameter'])
def test_strategy_freeze_detects_changes_outside_and_inside_brain(tmp_path, damage):
    manifest=json.loads((ROOT/'docs/strategy_freeze.json').read_text())
    paths=set(manifest['files'])|set(manifest['methods'])|set(manifest['parameters'])|{'docs/strategy_freeze.json'}
    for relative in paths:
        destination=tmp_path/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,destination)
    if damage=='brain':
        path=tmp_path/'algo-trading-bot/signal_brain.py'
        path.write_text(path.read_text()+'\n# unauthorized edit\n')
    elif damage=='management':
        path=tmp_path/'algo-trading-bot/execution_engine.py'
        path.write_text(path.read_text().replace('self.candles_held >= 15','self.candles_held >= 16'))
    else:
        path=tmp_path/'algo-trading-bot/config.py'
        path.write_text(path.read_text().replace('SL_ATR_MULT = 2.00','SL_ATR_MULT = 3.00'))
    with pytest.raises(StrategyFreezeError):
        verify_strategy_freeze(tmp_path)


def test_new_exchange_import_graph_has_no_legacy_sdk_or_execution_dependencies():
    result=subprocess.run([sys.executable,'-c',
        'import sys,json; import exchange.hyperliquid_client, exchange.hyperliquid_market_data, '
        'exchange.hyperliquid_execution, exchange.hyperliquid_account, exchange.hyperliquid_reconciliation, '
        'exchange.paper_execution; print(json.dumps(sorted(set(sys.modules)&'
        '{"SmartApi","pyotp","config","execution_engine","execution_safety","safe_trader"})))'],
        cwd=ROOT/'algo-trading-bot',capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==[]


def test_websocket_uses_testnet_and_verified_trust_bundle(monkeypatch):
    import requests
    import ssl
    import websocket
    from exchange.hyperliquid_client import TESTNET_WS_URL
    captured={}
    def connect(url, **options):
        captured.update(url=url, **options)
        return 'fixture-socket'
    monkeypatch.setattr(websocket, 'create_connection', connect)
    assert ParMarketDataEngine._connect() == 'fixture-socket'
    assert captured['url'] == TESTNET_WS_URL
    assert captured['sslopt'] == {'ca_certs': requests.certs.where(),
                                   'cert_reqs': ssl.CERT_REQUIRED, 'check_hostname': True}
