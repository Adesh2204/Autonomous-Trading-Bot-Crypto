"""Offline liquidity selection only: no execution, signing or strategy tuning."""
from decimal import Decimal as D
from types import SimpleNamespace

from exchange.base_exchange import Candle, BookLevel, OrderBook
from market_regime_scanner import MarketRegimeScanner, ScannerPolicy

NOW = 1800000000000


class PublicFixture:
    def __init__(self):
        self.client = SimpleNamespace(markets={'pas:BTC': object(), 'pas:EWY': object()},
                                      startup=lambda: None, clock_ms=lambda: NOW)
        self.liquid = 'pas:BTC'
        self.missing = set()

    def get_asset_contexts(self):
        return {s: dict(markPx='100', oraclePx='100', funding='0',
                        openInterest='1', dayNtlVlm='100000') for s in self.client.markets}

    def get_candles(self, symbol, start, end, **_kwargs):
        if symbol in self.missing:
            return []
        return [Candle(symbol, '1m', t, t + 59999, D(100), D(101), D(99), D(100),
                       D(20) if symbol == self.liquid else D(10),
                       received_timestamp_ms=t + 60000)
                for t in range(start, end + 1, 60000)]

    def get_orderbook(self, symbol):
        half = D('.01') if symbol == self.liquid else D('.02')
        size = D(20) if symbol == self.liquid else D(10)
        return OrderBook(symbol, NOW, (BookLevel(D(100) - half, size),),
                         (BookLevel(D(100) + half, size),))


def test_existing_scanner_switches_liquidity_leader_with_one_selected_asset():
    market = PublicFixture()
    scanner = MarketRegimeScanner(market, ScannerPolicy('.004', '15', '0', '10', top_n=1))
    first = scanner.scan()
    assert first.watchlist == ['pas:BTC']
    assert all(d.qualified for d in first.diagnostics)
    # Same unchanged frozen strategy/ATR; only observed liquidity changes.
    market.liquid = 'pas:EWY'
    second = scanner.scan()
    assert second.watchlist == ['pas:EWY']
    assert all(d.qualified for d in second.diagnostics)
    assert {d.metrics['atr'] for d in first.diagnostics + second.diagnostics} == {D(2)}
    assert len(second.watchlist) == scanner.policy.top_n == 1


def test_missing_data_is_not_replaced_by_the_other_market_or_native_history():
    market = PublicFixture()
    market.missing = {'pas:BTC'}
    scanner = MarketRegimeScanner(market, ScannerPolicy('.004', '15', '0', '10', top_n=1))
    assert scanner.scan().watchlist == ['pas:EWY']
    market.missing.add('pas:EWY')
    scan = scanner.scan()
    assert not scan.watchlist
    assert all('INSUFFICIENT_COMPLETED_HISTORY' in d.reasons for d in scan.diagnostics)
