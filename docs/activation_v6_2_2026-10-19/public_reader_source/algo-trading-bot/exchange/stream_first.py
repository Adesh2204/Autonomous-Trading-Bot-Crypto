"""Trusted public stream reads with explicit REST fallback, never fabricated data."""
from .base_exchange import ExchangeError
from .hyperliquid_market_data import HyperliquidMarketData


class StreamFirstMarketData(HyperliquidMarketData):
    def __init__(self,client,engine):
        super().__init__(client)
        self.engine=engine

    def get_quote(self,symbol):
        try:
            return self.engine.get_quote(symbol)
        except ExchangeError:
            return super().get_quote(symbol)

    def get_orderbook(self,symbol):
        try:
            self.engine.get_quote(symbol)  # independent BBO + context freshness
            with self.engine._lock:
                return self.engine.books[symbol]
        except ExchangeError:
            return super().get_orderbook(symbol)

    def get_candles(self,symbol,start_ms,end_ms,*,interval='1m',now_ms=None):
        if interval=='1m' and self.engine.connected and self.engine.reconciled:
            rows=[c for c in self.engine.get_completed_candles(symbol) if start_ms<=c.timestamp_ms<=end_ms]
            now=self.client.clock_ms() if now_ms is None else now_ms
            first=((start_ms+59999)//60000)*60000
            last=min(end_ms//60000*60000,(now//60000-1)*60000)
            expected=list(range(first,last+1,60000))
            if rows and [c.timestamp_ms for c in rows]==expected:
                return rows
        return super().get_candles(symbol,start_ms,end_ms,interval=interval,now_ms=now_ms)
