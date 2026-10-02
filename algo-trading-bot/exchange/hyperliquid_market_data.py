"""Read-only REST and public WebSocket data for the verified par universe."""
from dataclasses import replace
from .event_timing import timing
from collections import defaultdict
from decimal import Decimal
import json
import threading
import time

from .base_exchange import BookLevel, Candle, ExchangeError, OrderBook, Quote, VenueMismatch, decimal
from .hyperliquid_client import TESTNET_WS_URL

INTERVAL_MS = {'1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000,
               '30m': 1_800_000, '1h': 3_600_000, '2h': 7_200_000,
               '4h': 14_400_000, '8h': 28_800_000, '12h': 43_200_000, '1d': 86_400_000}


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExchangeError('INVALID_TIMESTAMP')
    return value


def parse_book(data, symbol):
    if (not isinstance(data, dict) or data.get('coin') != symbol
            or not isinstance(data.get('levels'), list) or len(data['levels']) != 2):
        raise ExchangeError('INVALID_ORDERBOOK')
    try:
        sides = [tuple(BookLevel(decimal(row['px'], positive=True),
                                 decimal(row['sz'], positive=True)) for row in side)
                 for side in data['levels']]
        if not sides[0] or not sides[1]:
            raise ExchangeError('NO_EXECUTABLE_TWO_SIDED_BOOK')
        if (list(sides[0]) != sorted(sides[0], key=lambda row: row.price, reverse=True)
                or list(sides[1]) != sorted(sides[1], key=lambda row: row.price)
                or sides[0][0].price > sides[1][0].price):
            raise ExchangeError('INVALID_ORDERBOOK_PRICES')
        return OrderBook(symbol, timestamp(data['time']), sides[0], sides[1])
    except (KeyError, TypeError) as exc:
        raise ExchangeError('INVALID_ORDERBOOK') from exc


def parse_candle(row, symbol, interval):
    if not isinstance(row, dict) or row.get('s') != symbol or row.get('i') != interval:
        raise ExchangeError('CANDLE_IDENTITY_MISMATCH')
    try:
        start, end = timestamp(row['t']), timestamp(row['T'])
        step = INTERVAL_MS[interval]
        if start % step or end not in {start + step - 1, start + step}:
            raise ExchangeError('INVALID_CANDLE_BOUNDARIES')
        o, h, l, c = (decimal(row[key], positive=True) for key in ('o', 'h', 'l', 'c'))
        if h < max(o, c, l) or l > min(o, c, h):
            raise ExchangeError('INVALID_CANDLE_PRICES')
        return Candle(symbol, interval, start, end, o, h, l, c,
                      decimal(row['v'], nonnegative=True))
    except (KeyError, TypeError) as exc:
        raise ExchangeError('INVALID_CANDLE') from exc


def make_quote(book, context, now_ms, max_age_ms=5_000, *, mark_timestamp_ms=None):
    if not 0 <= now_ms - book.timestamp_ms <= max_age_ms:
        raise ExchangeError('ORDERBOOK_STALE')
    try:
        bid, ask = book.bids[0], book.asks[0]
        return Quote(book.symbol, book.timestamp_ms, bid.price, ask.price,
                     bid.quantity, ask.quantity, (bid.price + ask.price) / 2,
                     decimal(context['markPx'], positive=True),
                     decimal(context['oraclePx'], positive=True), decimal(context['funding']),
                     decimal(context['openInterest'],nonnegative=True) if 'openInterest' in context else None,
                     decimal(context['dayNtlVlm'],nonnegative=True) if 'dayNtlVlm' in context else None,
                     mark_timestamp_ms, book.received_timestamp_ms, now_ms)
    except (KeyError, TypeError) as exc:
        raise ExchangeError('INVALID_ASSET_CONTEXT') from exc


class HyperliquidMarketData:
    def __init__(self, client):
        self.client = client

    def get_orderbook(self, symbol):
        self.client.market(symbol)
        result=self.client.post_info('l2Book', coin=symbol)
        return replace(parse_book(result,symbol),received_timestamp_ms=self.client.last_received_ms,
                       processed_timestamp_ms=self.client.clock_ms())

    def get_asset_contexts(self):
        if not self.client.ready:
            raise VenueMismatch('PAR_STARTUP_CHECK_REQUIRED')
        result = self.client.post_info('metaAndAssetCtxs')
        if not isinstance(result, list) or len(result) != 2:
            raise ExchangeError('INVALID_ASSET_CONTEXTS')
        metadata, contexts = result
        self.client.validate_metadata(metadata)
        if not isinstance(contexts, list) or len(contexts) != len(metadata['universe']):
            raise ExchangeError('INVALID_ASSET_CONTEXTS')
        return {row['name']: contexts[i] for i, row in enumerate(metadata['universe'])
                if row['name'] in self.client.markets}

    def get_quote(self, symbol):
        self.client.market(symbol)
        context = self.get_asset_contexts()[symbol]
        observed=self.client.clock_ms()
        return make_quote(self.get_orderbook(symbol), context, self.client.clock_ms(),mark_timestamp_ms=observed)

    def get_candles(self, symbol, start_ms, end_ms, *, interval='1m', now_ms=None):
        self.client.market(symbol)
        start_ms, end_ms = timestamp(start_ms), timestamp(end_ms)
        if interval not in INTERVAL_MS or end_ms < start_ms:
            raise ExchangeError('INVALID_CANDLE_RANGE')
        if (end_ms - start_ms) // INTERVAL_MS[interval] + 1 > 5000:
            raise ExchangeError('CANDLE_RANGE_EXCEEDS_API_LIMIT')
        result = self.client.post_info('candleSnapshot', req={
            'coin': symbol, 'interval': interval, 'startTime': start_ms, 'endTime': end_ms})
        if not isinstance(result, list):
            raise ExchangeError('INVALID_CANDLE_RESPONSE')
        as_of = self.client.clock_ms() if now_ms is None else timestamp(now_ms)
        candles = {}
        for row in result:
            candle = replace(parse_candle(row,symbol,interval),received_timestamp_ms=self.client.last_received_ms,
                             processed_timestamp_ms=self.client.clock_ms())
            if not start_ms <= candle.timestamp_ms <= end_ms:
                raise ExchangeError('CANDLE_OUTSIDE_REQUESTED_RANGE')
            if candle.timestamp_ms + INTERVAL_MS[interval] > as_of:
                continue
            prior = candles.get(candle.timestamp_ms)
            if prior is not None and prior != candle:
                raise ExchangeError('CONFLICTING_COMPLETED_CANDLES')
            candles[candle.timestamp_ms] = candle
        return [candles[key] for key in sorted(candles)]


class ParMarketDataEngine:
    """Public streams with reconnect verification and REST candle gap repair.

    It records data only. No account subscriptions or order execution are wired.
    A disconnect immediately revokes feed health; metadata and completed history
    must be checked again before a reconnected feed becomes healthy.
    """
    def __init__(self, market, symbols=None, *, connect=None, history_bars=300,include_trades=False,on_lifecycle=None):
        self.market = market
        self.client = market.client
        self.symbols = tuple(symbols) if symbols is not None else tuple(sorted(self.client.markets))
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ExchangeError('INVALID_STREAM_MARKETS')
        for symbol in self.symbols:
            self.client.market(symbol)
        if type(history_bars) is not int or not 1 <= history_bars <= 5000:
            raise ExchangeError('INVALID_HISTORY_WINDOW')
        self.history_bars = history_bars
        self.connect = connect or self._connect
        self.connected = False
        self.reconciled = False
        self.books = {}
        self.contexts = {}
        self.context_times = {}
        self.candles = defaultdict(dict)
        self.messages = 0
        self.reconnections = 0
        self.last_error = None
        self._lock = threading.RLock()
        self.include_trades=include_trades
        self.on_lifecycle=on_lifecycle
        self.last_trades={}
        self.tick_times={}
        self.last_receive_ms=None
        self.recovery_generation=0
        self.consecutive_failures=0
        self.unavailable_books={}

    def _lifecycle(self,phase,**details):
        if self.on_lifecycle:
            self.on_lifecycle(dict(phase=phase,timestamp_ms=self.client.clock_ms(),
                                  generation=self.recovery_generation,**timing(self.client.clock_ms()),**details))

    @staticmethod
    def _connect():
        import ssl
        import requests
        import websocket
        return websocket.create_connection(TESTNET_WS_URL, timeout=1, sslopt={
            'ca_certs': requests.certs.where(), 'cert_reqs': ssl.CERT_REQUIRED,
            'check_hostname': True})

    def subscriptions(self):
        return [{'method': 'subscribe', 'subscription': {'type': channel, 'coin': symbol,
                 **({'interval': '1m'} if channel == 'candle' else {})}}
                for symbol in self.symbols for channel in
                (('l2Book','candle','activeAssetCtx','trades') if self.include_trades else ('l2Book','candle','activeAssetCtx'))]

    def reconcile_history(self):
        now = self.client.clock_ms()
        end = now // 60_000 * 60_000 - 1
        start = end + 1 - self.history_bars * 60_000
        contexts = self.market.get_asset_contexts()
        histories = {symbol: self.market.get_candles(symbol, start, end, now_ms=now)
                     for symbol in self.symbols}
        books={}
        unavailable={}
        for symbol in self.symbols:
            try:
                books[symbol]=self.market.get_orderbook(symbol)
            except ExchangeError as exc:
                if str(exc) not in {'NO_EXECUTABLE_TWO_SIDED_BOOK','INVALID_ORDERBOOK_PRICES'}:
                    raise
                unavailable[symbol]=str(exc)
        # Publish only after every request succeeds; never mark partial repair healthy.
        with self._lock:
            self.books=books
            self.unavailable_books=unavailable
            self.tick_times={symbol:book.timestamp_ms for symbol,book in books.items()}
            self.last_trades.clear()
            self.contexts = {symbol: contexts[symbol] for symbol in self.symbols}
            self.context_times = dict.fromkeys(self.symbols, now)
            for symbol, history in histories.items():
                self.candles[symbol] = {bar.timestamp_ms: bar for bar in history}
            self.reconciled = True
            self.recovery_generation+=1
        self._lifecycle('REST_MARKET_RECONCILED')

    def ingest(self, message):
        try:
            self._ingest_validated(message)
        except ExchangeError:
            self.connected = False
            self.reconciled = False
            raise

    def _ingest_validated(self, message):
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except ValueError as exc:
                raise ExchangeError('INVALID_STREAM_JSON') from exc
        if not isinstance(message, dict):
            raise ExchangeError('INVALID_STREAM_MESSAGE')
        channel, data = message.get('channel'), message.get('data')
        if channel in {'subscriptionResponse', 'pong'}:
            return
        if channel not in {'l2Book', 'candle', 'activeAssetCtx'} and not (channel=='trades' and self.include_trades):
            raise ExchangeError('UNEXPECTED_PUBLIC_STREAM_CHANNEL')
        received_ms=self.client.clock_ms()
        with self._lock:
            if channel == 'l2Book':
                symbol = data.get('coin') if isinstance(data, dict) else None
                if symbol not in self.symbols:
                    raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
                try:
                    book = replace(parse_book(data,symbol),received_timestamp_ms=received_ms,
                                   processed_timestamp_ms=self.client.clock_ms())
                except ExchangeError as exc:
                    if str(exc) not in {'NO_EXECUTABLE_TWO_SIDED_BOOK','INVALID_ORDERBOOK_PRICES'}:
                        raise
                    self.books.pop(symbol,None)
                    self.unavailable_books[symbol]=str(exc)
                    self.messages+=1
                    return
                previous = self.books.get(symbol)
                if previous is None or book.timestamp_ms >= previous.timestamp_ms:
                    self.books[symbol] = book
                    self.unavailable_books.pop(symbol,None)
                    self.tick_times[symbol]=max(book.timestamp_ms,self.tick_times.get(symbol,0))
            elif channel == 'activeAssetCtx':
                symbol = data.get('coin') if isinstance(data, dict) else None
                if symbol not in self.symbols or not isinstance(data.get('ctx'), dict):
                    raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
                context = data['ctx']
                for name in ('markPx', 'oraclePx'):
                    decimal(context.get(name), positive=True)
                decimal(context.get('funding'))
                self.contexts[symbol] = context
                self.context_times[symbol] = self.client.clock_ms()
            elif channel=='trades':
                if not isinstance(data,list):
                    raise ExchangeError('INVALID_PUBLIC_TRADES')
                for trade in data:
                    try:
                        symbol=trade['coin']
                        if symbol not in self.symbols:
                            raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
                        when=timestamp(trade['time'])
                        if when>self.client.clock_ms() or trade['side'] not in {'A','B'}:
                            raise ExchangeError('INVALID_PUBLIC_TRADES')
                        decimal(trade['px'],positive=True)
                        decimal(trade['sz'],positive=True)
                        if type(trade['tid']) is not int or trade['tid']<0:
                            raise ExchangeError('INVALID_PUBLIC_TRADES')
                    except (TypeError,KeyError) as exc:
                        raise ExchangeError('INVALID_PUBLIC_TRADES') from exc
                    prior=self.last_trades.get(symbol)
                    if prior is None or when>=prior['time']:
                        self.last_trades[symbol]=dict(trade,**timing(self.client.clock_ms(),exchange_ms=when,
                            received_ms=received_ms,source="EXCHANGE_PUBLIC_TRADE"))
                    self.tick_times[symbol]=max(when,self.tick_times.get(symbol,0))
            else:
                for row in data if isinstance(data, list) else [data]:
                    symbol = row.get('s') if isinstance(row, dict) else None
                    if symbol not in self.symbols:
                        raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
                    candle = replace(parse_candle(row,symbol,'1m'),received_timestamp_ms=received_ms,
                                     processed_timestamp_ms=self.client.clock_ms())
                    if candle.timestamp_ms > self.client.clock_ms():
                        raise ExchangeError('FUTURE_STREAM_CANDLE')
                    self.candles[symbol][candle.timestamp_ms] = candle
                    keys = sorted(self.candles[symbol])
                    for key in keys[:-self.history_bars]:
                        del self.candles[symbol][key]
            self.messages += 1

    def get_observations(self,symbol):
        if symbol not in self.symbols:
            raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
        with self._lock:
            candles=self.get_completed_candles(symbol)
            book=self.books.get(symbol)
            return dict(last_tick_time=self.tick_times.get(symbol),
                last_candle_time=candles[-1].timestamp_ms+60000 if candles else None,
                last_orderbook_time=book.timestamp_ms if book else None,
                last_mark_time=self.context_times.get(symbol))

    def get_snapshot(self,symbol):
        from .market_snapshot import MarketSnapshot
        self.get_quote(symbol)
        with self._lock:
            return MarketSnapshot.from_book(self.books[symbol],self.contexts[symbol],self.client.clock_ms(),
                mark_observed_at_ms=self.context_times[symbol],last_trade=self.last_trades.get(symbol))

    def acknowledge_recovery(self,generation):
        with self._lock:
            if not self.connected or not self.reconciled or generation!=self.recovery_generation:
                raise ExchangeError('STREAM_CHANGED_DURING_ACCOUNT_RECOVERY')
            self.consecutive_failures=0

    def get_completed_candles(self, symbol):
        if symbol not in self.symbols:
            raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
        with self._lock:
            now = self.client.clock_ms()
            return [bar for _, bar in sorted(self.candles[symbol].items())
                    if bar.timestamp_ms + 60_000 <= now]

    def get_quote(self, symbol):
        if not self.connected or not self.reconciled or not self.client.ready:
            raise ExchangeError('STREAM_NOT_HEALTHY')
        with self._lock:
            now = self.client.clock_ms()
            if symbol not in self.books or symbol not in self.contexts:
                raise ExchangeError('STREAM_WARMUP_REQUIRED')
            if not 0 <= now - self.context_times[symbol] <= 60_000:
                raise ExchangeError('ASSET_CONTEXT_STALE')
            return make_quote(self.books[symbol], self.contexts[symbol], now,mark_timestamp_ms=self.context_times[symbol])

    def run(self, stop_event, *, max_reconnects=5):
        import websocket
        while not stop_event.is_set():
            connection = None
            try:
                self.reconciled = False
                self._lifecycle('CONNECTING')
                self.client.startup()
                connection = self.connect()
                for subscription in self.subscriptions():
                    connection.send(json.dumps(subscription))
                self.connected = True
                self._lifecycle('SUBSCRIBED')
                self.reconcile_history()
                last_ping = time.monotonic()
                last_receive=last_ping
                pending_ping=None
                while not stop_event.is_set():
                    now=time.monotonic()
                    if now-last_receive>=45 or pending_ping is not None and now-pending_ping>=10:
                        raise ExchangeError('STREAM_HEARTBEAT_STALE')
                    if now - last_ping >= 30:
                        connection.send(json.dumps({'method': 'ping'}))
                        last_ping = pending_ping = now
                    try:
                        message = connection.recv()
                    except (websocket.WebSocketTimeoutException, TimeoutError):
                        continue
                    if not message:
                        raise ExchangeError('STREAM_DISCONNECTED')
                    last_receive=time.monotonic()
                    self.last_receive_ms=self.client.clock_ms()
                    self.ingest(message)
                    if (json.loads(message) if isinstance(message,str) else message).get('channel')=='pong':
                        pending_ping=None
            except VenueMismatch:
                self.client.invalidate()
                raise
            except (ExchangeError, OSError, websocket.WebSocketException) as exc:
                self.last_error = type(exc).__name__ + ':' + str(exc)
                self.connected=self.reconciled=False
                self.consecutive_failures += 1
                self.reconnections += 1
                self._lifecycle('DISCONNECTED',reason=self.last_error,consecutive_failures=self.consecutive_failures)
                if self.consecutive_failures > max_reconnects:
                    raise ExchangeError('STREAM_RECONNECT_LIMIT') from exc
                stop_event.wait(min(2 ** (self.consecutive_failures - 1), 5))
            finally:
                self.connected = False
                self.reconciled = False
                if connection is not None:
                    connection.close()
