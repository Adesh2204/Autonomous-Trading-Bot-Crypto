"""Read-only REST and public WebSocket data for the verified par universe."""
from dataclasses import replace
from .event_timing import timing
from collections import defaultdict
from decimal import Decimal
import json
import queue
import threading
import time

from .base_exchange import BookLevel, Candle, ExchangeError, OrderBook, Quote, VenueMismatch, decimal
from .hyperliquid_client import TESTNET_WS_URL
from .feed_transport import FeedTransportHealth
from .market_health import MarketHealthManager, validate_history
from .candle_audit import merge_candle
from .candle_availability import CandleAvailabilityMonitor

INTERVAL_MS = {'1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000,
               '30m': 1_800_000, '1h': 3_600_000, '2h': 7_200_000,
               '4h': 14_400_000, '8h': 28_800_000, '12h': 43_200_000, '1d': 86_400_000}
PAS_RETAINED_COMPLETED_BARS = 5000


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
        book=parse_book(result,symbol)
        if book.timestamp_ms>self.client.clock_ms():raise ExchangeError('FUTURE_ORDERBOOK')
        return replace(book,received_timestamp_ms=self.client.last_received_ms,
                       processed_timestamp_ms=self.client.clock_ms())

    def get_asset_contexts(self):
        if not self.client.ready:
            raise VenueMismatch('PAS_STARTUP_CHECK_REQUIRED' if getattr(self.client, 'competition_mode', False) else self.client.dex.upper()+'_STARTUP_CHECK_REQUIRED')
        result = self.client.post_info('metaAndAssetCtxs')
        if not isinstance(result, list) or len(result) != 2:
            raise ExchangeError('INVALID_ASSET_CONTEXTS')
        metadata, contexts = result
        self.client.validate_metadata(metadata)
        if not isinstance(contexts, list) or len(contexts) != len(metadata['universe']):
            raise ExchangeError('INVALID_ASSET_CONTEXTS')
        if not getattr(self.client, 'competition_mode', False):
            return {row['name']: contexts[i] for i, row in enumerate(metadata['universe'])
                    if isinstance(row, dict) and row.get('name') in self.client.markets}
        # PAS exposes a deliberately small strategy subset. Keep contexts for
        # every selected asset so EWY is scanned and managed just like BTC;
        # the OI total remains a DEX-wide safety calculation.
        api_markets = getattr(self.client, 'api_markets', None)
        if api_markets is None:
            # Compatibility for older isolated BTC-only offline fixtures.
            api_markets = {'BTC': self.client.api_market}
        if (not isinstance(api_markets, dict) or set(api_markets) != {'BTC', 'EWY'}
                or api_markets.get('BTC') != self.client.api_market
                or set(self.client.markets) != set(api_markets.values())):
            # Old fixtures that have not adopted the two-asset contract are
            # allowed only as an offline compatibility path, never production.
            legacy_fixture = (getattr(self.client, 'api_markets', None) is None
                              and set(self.client.markets) == {self.client.api_market})
            if not legacy_fixture:
                raise ExchangeError('PAS_ASSET_MAPPING_UNVERIFIED')
        selected_markets = set(api_markets.values())
        contexts_by_symbol = {}
        dex_total_oi = decimal(0)
        # Only BTC and EWY enter the signal/strategy path. The aggregate OI sum
        # below is a safety calculation for the whole DEX cap, not a scan.
        for i, row in enumerate(metadata['universe']):
            if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not isinstance(contexts[i], dict):
                raise ExchangeError('INVALID_ASSET_CONTEXTS')
            symbol = self.client.canonical_market_name(row['name'])
            try:
                oi = decimal(contexts[i]['openInterest'], nonnegative=True)
                oracle = decimal(contexts[i]['oraclePx'], positive=True)
            except (KeyError, TypeError, ValueError) as exc:
                raise ExchangeError('DEX_OI_AGGREGATE_UNVERIFIABLE') from exc
            if not row.get('isDelisted'):
                dex_total_oi += oi * oracle
            if symbol in selected_markets:
                if symbol in contexts_by_symbol:
                    raise ExchangeError('AMBIGUOUS_PAS_ASSET_CONTEXT')
                if row.get('isDelisted'):
                    raise ExchangeError('PAS_SELECTED_ASSET_DELISTED')
                contexts_by_symbol[symbol] = contexts[i]
        if set(contexts_by_symbol) != selected_markets:
            raise ExchangeError('PAS_SELECTED_ASSET_CONTEXT_UNAVAILABLE')
        self.client.dex_total_oi_notional = dex_total_oi
        self.client.dex_oi_observed_ms = self.client.clock_ms()
        self.client.dex_oi_market_count = len(metadata['universe'])
        return contexts_by_symbol

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
        monitor=getattr(self.client,'availability_monitor',None)
        if monitor is not None and interval=='1m':
            monitor.observe_rest(symbol,start_ms,end_ms,result,parse_candle,
                self.client.last_received_ms or self.client.clock_ms(),as_of,
                role=getattr(self.client,'availability_role',None))
        rows=result
        candles = {}
        for row in result:
            candle = replace(parse_candle(row,symbol,interval),received_timestamp_ms=self.client.last_received_ms,
                             processed_timestamp_ms=self.client.clock_ms())
            if not start_ms <= candle.timestamp_ms <= end_ms:
                raise ExchangeError('CANDLE_OUTSIDE_REQUESTED_RANGE')
            if candle.timestamp_ms > as_of:
                raise ExchangeError('FUTURE_REST_CANDLE')
            if candle.timestamp_ms + INTERVAL_MS[interval] > as_of:
                continue
            # For PAS, clock passage alone cannot finalize a stream/REST fact
            # first observed while its interval was still open. A later real
            # response can supply that bar; unknown receive time stays blocked.
            if (getattr(self.client, 'competition_mode', False) and interval == '1m'
                    and (candle.received_timestamp_ms is None or
                         candle.received_timestamp_ms < candle.timestamp_ms + 60_000)):
                continue
            prior = candles.get(candle.timestamp_ms)
            if prior is not None and replace(prior,received_timestamp_ms=candle.received_timestamp_ms,
                    processed_timestamp_ms=candle.processed_timestamp_ms) != candle:
                raise ExchangeError('CONFLICTING_COMPLETED_CANDLES')
            candles[candle.timestamp_ms] = candle
        result=[candles[key] for key in sorted(candles)]
        if getattr(self.client,'candle_audit',None) is not None:
            self.client.candle_audit.record('NORMALIZED_REST',symbol=symbol,start_ms=start_ms,
                end_ms=end_ms,as_of_ms=as_of,raw_count=len(rows),candles=result,
                discarded_open_count=sum(1 for r in rows if r['t']+INTERVAL_MS[interval]>as_of))
        return result


class ParMarketDataEngine:
    """Public streams with reconnect verification and REST candle gap repair.

    It records data only. No account subscriptions or order execution are wired.
    A disconnect immediately revokes feed health; metadata and completed history
    must be checked again before a reconnected feed becomes healthy.
    """
    def __init__(self, market, symbols=None, *, connect=None, history_bars=300,include_trades=False,on_lifecycle=None):
        self.market = market
        self.client = market.client
        from .entry_scope import signal_markets
        self.symbols = signal_markets(self.client,symbols or ())
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ExchangeError('INVALID_STREAM_MARKETS')
        for symbol in self.symbols:
            self.client.market(symbol)
        if type(history_bars) is not int or not 1 <= history_bars <= 5000:
            raise ExchangeError('INVALID_HISTORY_WINDOW')
        self.history_bars = history_bars
        # PAS scanner ranges include the complete UTC-anchor lookback, which
        # can be longer than the strategy's 300-bar requirement. Keep up to
        # 5000 completed intervals plus one mutable/open observation; health
        # and strategy requirements remain governed by history_bars.
        self.retention_capacity = (PAS_RETAINED_COMPLETED_BARS + 1
            if getattr(self.client, 'competition_mode', False) else history_bars + 1)
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
        self.rates=self.client.rate_limits
        self.budget_identity='market:'+str(id(self))
        self.transport_health=FeedTransportHealth(wall_ms=self.client.clock_ms)
        self._run_owner=threading.Lock()
        self._recovery_cancel=threading.Event()
        self._recovery_worker=None
        self.recovery_errors={}
        self.recovery_retry_deadlines_ms={}
        self.recovery_status='UNKNOWN'
        self.health_manager=MarketHealthManager(self.symbols,history_bars=history_bars)
        self.input_errors=defaultdict(dict)
        self.scanner_errors={}
        self.availability=getattr(self.client,'availability_monitor',None) or CandleAvailabilityMonitor(
            self.symbols,clock_ms=self.client.clock_ms,history_bars=history_bars)
        self.client.availability_monitor=self.availability

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

    def reconcile_history(self, generation=None, symbols=None):
        selected=self.symbols if symbols is None else tuple(symbols)
        for symbol in selected:self.recovery_retry_deadlines_ms.pop(symbol,None)
        self.health_manager.begin_recovery(selected,self.client.clock_ms())
        for symbol in selected:self.availability.recovery_begin(symbol,self.client.clock_ms())
        failure=None
        try:
            return self._reconcile_history(generation,selected)
        except Exception as exc:
            failure=str(exc)
            raise
        finally:
            delay_hints={s:self.availability.retry_hint_ms(s) for s in selected}
            retry_deadlines={s:self.recovery_retry_deadlines_ms[s] for s in selected
                if s in self.recovery_retry_deadlines_ms}
            self.health_manager.finish_recovery(selected,self.client.clock_ms(),
                delay_hints=delay_hints,retry_deadlines_ms=retry_deadlines)
            health=self.market_health()
            # The successful attempt was counted before health could reset its
            # failure streak. Rebase only healthy, non-quota schedules; otherwise
            # a restored but aging tail inherits the old exponential delay.
            restored=tuple(s for s in selected if health[s]['healthy'] and s not in retry_deadlines)
            if restored:
                self.health_manager.finish_recovery(restored,self.client.clock_ms(),delay_hints=delay_hints)
            for symbol in selected:
                event=self.availability.recovery_finish(symbol,self.client.clock_ms(),failure or self.recovery_errors.get(symbol))
                if getattr(self.client,'candle_audit',None) is not None:
                    self.client.candle_audit.record('AVAILABILITY_RECOVERY',symbol=symbol,**event)

    def _reconcile_history(self, generation=None, symbols=None):
        selected=self.symbols if symbols is None else tuple(symbols)
        now = self.client.clock_ms()
        end = now // 60_000 * 60_000 - 1
        start = end + 1 - self.history_bars * 60_000
        contexts = self.market.get_asset_contexts()
        histories={}
        errors={}
        for symbol in selected:
            if generation is not None and self._recovery_cancel.is_set():
                raise ExchangeError('MARKET_RECOVERY_CANCELLED')
            with self._lock:
                previous=list(self.candles[symbol].values())
            pas=getattr(self.client,'competition_mode',False)
            def is_completed_source(bar):
                return (bar.timestamp_ms+60_000<=now and
                    (not pas or (bar.received_timestamp_ms is not None and
                                 bar.received_timestamp_ms>=bar.timestamp_ms+60_000)))
            # Repair from the last actual completed candle, with a small overlap.
            # Missing venue bars remain missing; no interpolation or CSV fallback.
            repair_start=max(start,max((b.timestamp_ms for b in previous
                if is_completed_source(b)),default=start)-2*60000)
            completed=sorted((b for b in previous if start<=b.timestamp_ms<=end
                and is_completed_source(b)),key=lambda b:b.timestamp_ms)
            # A narrow tail repair cannot fill an older hole or warm up a short buffer.
            if len(completed)<self.history_bars or any(b.timestamp_ms-a.timestamp_ms!=60000
                    for a,b in zip(completed,completed[1:])):
                missing=sorted(set(range(start,end+1,60000))-{b.timestamp_ms for b in completed})
                # Preserve the proven full-window repair when history is short
                # or gapped; identify exact holes without dropping retained scope.
                repair_start=start
                if getattr(self.client,'candle_audit',None) is not None:
                    self.client.candle_audit.record('AVAILABILITY_REPAIR_PLAN',symbol=symbol,
                        missing_timestamps_ms=missing,request_start_ms=repair_start,request_end_ms=end)
            try:
                if pas and getattr(self.client,'fair_candle_scheduling',False):
                    # Equal per-market turns under the unchanged shared 300-slot
                    # budget. Repair genuine holes, retaining progress across turns.
                    present={b.timestamp_ms for b in completed}
                    missing=sorted(set(range(start,end+1,60000))-present)
                    fresh=[]
                    remaining=150
                    while missing and remaining:
                        first=missing[0];last=first
                        take=1
                        while take<min(remaining,len(missing)) and missing[take]==last+60000:
                            last=missing[take];take+=1
                        rows=self.market.get_candles(symbol,first,last+59999,now_ms=now)
                        fresh.extend(rows)
                        # Commit each validated chunk even if the next is deferred.
                        with self._lock:
                            for b in rows:
                                self.candles[symbol][b.timestamp_ms]=merge_candle(
                                    self.candles[symbol].get(b.timestamp_ms),b,now)
                        missing=missing[take:];remaining-=take
                else:
                    fresh=self.market.get_candles(symbol,repair_start,end,now_ms=now)
                # Preserve genuine older stream rows: the scanner may request
                # farther back than the narrower health-recovery REST window.
                combined={b.timestamp_ms:b for b in previous
                    if pas or start<=b.timestamp_ms<=end}
                # Validate each genuine row in get_candles, then merge before
                # checking continuity. Retained rows can complete a sparse REST
                # response; an unresolved hole still fails market_health.
                for b in fresh:
                    combined[b.timestamp_ms]=merge_candle(combined.get(b.timestamp_ms),b,now)
                histories[symbol]=[combined[t] for t in sorted(combined)]
            except VenueMismatch:
                raise
            except ExchangeError as exc:
                errors[symbol]=str(exc)
                retry_after_ms=getattr(exc,'retry_after_ms',None)
                if type(retry_after_ms) is int and retry_after_ms>=0:
                    self.recovery_retry_deadlines_ms[symbol]=self.client.clock_ms()+retry_after_ms
        books={}
        unavailable={}
        for symbol in selected:
            if generation is not None and self._recovery_cancel.is_set():
                raise ExchangeError('MARKET_RECOVERY_CANCELLED')
            try:
                books[symbol]=self.market.get_orderbook(symbol)
            except ExchangeError as exc:
                unavailable[symbol]=str(exc)
                errors.setdefault(symbol,str(exc))
        with self._lock:
            if generation is not None and generation!=self.transport_health.generation:
                raise ExchangeError('OLD_SOCKET_RECOVERY_IGNORED')
            # Do not overwrite newer stream facts received while REST was running.
            for symbol,book in books.items():
                prior=self.books.get(symbol)
                if prior is None or book.timestamp_ms>=prior.timestamp_ms:self.books[symbol]=book
                self.input_errors[symbol].pop('book_health',None)
            for symbol in selected:self.unavailable_books.pop(symbol,None)
            self.unavailable_books.update(unavailable)
            for symbol,book in books.items():
                self.tick_times[symbol]=max(book.timestamp_ms,self.tick_times.get(symbol,0))
            for symbol in self.symbols:
                if self.context_times.get(symbol,-1)<=now:
                    self.contexts[symbol]=contexts[symbol]
                    self.context_times[symbol]=now
                    self.input_errors[symbol].pop('context_health',None)
            for symbol, history in histories.items():
                merged={bar.timestamp_ms:bar for bar in history}
                for t,b in self.candles[symbol].items():
                    prior=merged.get(t)
                    if t>=start:
                        try:merged[t]=merge_candle(prior,b,self.client.clock_ms())
                        except ExchangeError as exc:
                            errors[symbol]=str(exc);merged[t]=b
                self.candles[symbol]=dict(sorted(merged.items())[-self.retention_capacity:])
                self.input_errors[symbol].pop('history_health',None)
                self._audit_cache(symbol,'REST_MERGE',start,end)
            for symbol in selected:self.recovery_errors.pop(symbol,None)
            self.recovery_errors.update(errors)
            previous_reconciled=self.reconciled
            self.reconciled = generation is None or self.transport_health.confirmed==self.transport_health.desired
            self.recovery_status='RECONCILED'
            if symbols==self.symbols and not previous_reconciled or generation is None:
                self.recovery_generation+=1
        self._lifecycle('REST_MARKET_RECONCILED',per_market_errors=errors)

    def ingest(self, message, *, generation=None, _audit_recorded=False):
        audit=getattr(self.client,'candle_audit',None)
        if audit is not None and not _audit_recorded:
            decoded=message
            if isinstance(message,str):
                try:decoded=json.loads(message)
                except ValueError:decoded=None
            if isinstance(decoded,dict) and decoded.get('channel')=='candle':
                audit.record('RAW_WS',message=message,received_ms=self.client.clock_ms(),
                    generation=generation,active_generation=self.transport_health.generation)
        if generation is not None and generation!=self.transport_health.generation:
            return False
        # A malformed fact for one verified symbol is quarantined locally. Unknown
        # venue identities and protocol corruption still fail the connection closed.
        if (isinstance(message,dict) and message.get('channel') in {'candle','trades'} and
                isinstance(message.get('data'),list) and (message['channel']=='candle' or len(message['data'])>1)):
            for row in message['data']:
                self.ingest(dict(message,data=[row] if message['channel']=='trades' else row),generation=generation,
                            _audit_recorded=True)
            return
        try:
            self._ingest_validated(message)
        except VenueMismatch:
            self.connected = False
            self.reconciled = False
            raise
        except ExchangeError as exc:
            data=message.get('data') if isinstance(message,dict) else None
            row=data[0] if isinstance(data,list) and len(data)==1 else data
            symbol=(row.get('s') or row.get('coin')) if isinstance(row,dict) else None
            if symbol not in self.symbols:
                self.connected=self.reconciled=False
                raise
            component={'candle':'history_health','l2Book':'book_health','activeAssetCtx':'context_health',
                       'trades':'trade_health'}.get(message.get('channel'))
            if component is None:
                self.connected=self.reconciled=False
                raise
            with self._lock:self.input_errors[symbol][component]=str(exc)
            if message.get('channel')=='candle' and getattr(self.client,'candle_audit',None) is not None:
                self.client.candle_audit.record('CANDLE_REJECTED',symbol=symbol,reason=str(exc),source='WS')
            if message.get('channel')=='candle':
                self.availability.reject(symbol,str(exc),timestamp_ms=row.get('t'),source='WS')
            self._lifecycle('MARKET_DATA_QUARANTINED',symbol=symbol,reason=str(exc))
            return False

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
                    if book.timestamp_ms>received_ms:raise ExchangeError('FUTURE_ORDERBOOK')
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
                    self.input_errors[symbol].pop('book_health',None)
                    self.tick_times[symbol]=max(book.timestamp_ms,self.tick_times.get(symbol,0))
            elif channel == 'activeAssetCtx':
                symbol = data.get('coin') if isinstance(data, dict) else None
                if symbol not in self.symbols:
                    raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
                if not isinstance(data.get('ctx'),dict):raise ExchangeError('INVALID_ASSET_CONTEXT')
                context = data['ctx']
                for name in ('markPx', 'oraclePx'):
                    decimal(context.get(name), positive=True)
                decimal(context.get('funding'))
                self.contexts[symbol] = context
                self.context_times[symbol] = self.client.clock_ms()
                self.input_errors[symbol].pop('context_health',None)
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
                    self.input_errors[symbol].pop('trade_health',None)
            else:
                for row in data if isinstance(data, list) else [data]:
                    symbol = row.get('s') if isinstance(row, dict) else None
                    if symbol not in self.symbols:
                        raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
                    candle = replace(parse_candle(row,symbol,'1m'),received_timestamp_ms=received_ms,
                                     processed_timestamp_ms=self.client.clock_ms())
                    if candle.timestamp_ms > self.client.clock_ms():
                        raise ExchangeError('FUTURE_STREAM_CANDLE')
                    self.availability.observe_candle(candle,'WS',received_ms)
                    self.candles[symbol][candle.timestamp_ms] = merge_candle(
                        self.candles[symbol].get(candle.timestamp_ms),candle,received_ms)
                    keys = sorted(self.candles[symbol])
                    # A current open bar must not evict the 300th completed bar.
                    for key in keys[:-self.retention_capacity]:
                        del self.candles[symbol][key]
                    if getattr(self.client,'candle_audit',None) is not None:
                        self.client.candle_audit.record('WS_MERGE',symbol=symbol,candle=candle,
                            retained_timestamp_ms=sorted(self.candles[symbol]),
                            evicted_timestamp_ms=keys[:-self.retention_capacity])
            self.messages += 1

    def market_health(self):
        now=self.client.clock_ms()
        with self._lock:
            # Retention may include an older UTC scanner window. General feed
            # health is still judged on the configured recent strategy tail;
            # the scanner independently validates its complete requested range.
            values={s:((self.get_completed_candles(s)[-self.history_bars:]
                        if getattr(self.client,'competition_mode',False)
                        else self.get_completed_candles(s)),self.books.get(s),self.contexts.get(s),
                self.context_times.get(s),dict(self.input_errors[s],**({'scanner_history':self.scanner_errors[s]}
                    if s in self.scanner_errors else {}),**({'recovery':self.recovery_errors[s]}
                    if s in self.recovery_errors else {})),self.get_observations(s)) for s in self.symbols}
        result={s:self.health_manager.evaluate(s,*v[:4],now,errors=v[4],observations=v[5]) for s,v in values.items()}
        for s,v in values.items():self.availability.update_cache(s,v[0],now,result[s])
        return result

    def publish_public_snapshot(self,symbol,candles,book,context,context_ms):
        """Share validated scanner REST facts; keep its full UTC brain lookback intact."""
        validate_history(symbol,candles,self.client.clock_ms(),self.history_bars)
        with self._lock:
            merged=dict(self.candles[symbol])
            for c in candles:
                prior=self.candles[symbol].get(c.timestamp_ms)
                merged[c.timestamp_ms]=merge_candle(prior,c,self.client.clock_ms())
            self.candles[symbol]=dict(sorted(merged.items())[-self.retention_capacity:])
            self._audit_cache(symbol,'SCANNER_SNAPSHOT',candles[0].timestamp_ms,candles[-1].close_timestamp_ms)
            prior=self.books.get(symbol)
            if prior is None or book.timestamp_ms>=prior.timestamp_ms:self.books[symbol]=book
            if context_ms>=self.context_times.get(symbol,0):
                self.contexts[symbol]=context;self.context_times[symbol]=context_ms
            self.input_errors[symbol].clear();self.recovery_errors.pop(symbol,None)
            self.scanner_errors.pop(symbol,None)

    def _audit_cache(self,symbol,operation,start_ms,end_ms):
        if getattr(self.client,'candle_audit',None) is not None:
            self.client.candle_audit.record('CACHE',symbol=symbol,operation=operation,
                requested_start_ms=start_ms,requested_end_ms=end_ms,
                capacity=self.retention_capacity,candles=list(self.candles[symbol].values()))

    def note_scanner_failure(self,symbol,reason):
        if symbol not in self.symbols:raise VenueMismatch('STREAM_MARKET_IDENTITY_MISMATCH')
        # The scanner validates its full UTC lookback, which may exceed the
        # engine's 300-bar buffer. A hole there needs another full scanner check.
        if reason in {'STRATEGY_CANDLE_GAP_OR_DUPLICATE','CONFLICTING_COMPLETED_CANDLES'} or reason.startswith('SCANNER_NUMERIC_INVALID:'):
            with self._lock:self.scanner_errors[symbol]=str(reason)

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
            pas = getattr(self.client, 'competition_mode', False)
            return [bar for _, bar in sorted(self.candles[symbol].items())
                    if (bar.timestamp_ms + 60_000 <= now and
                        (not pas or (bar.received_timestamp_ms is not None and
                                     bar.received_timestamp_ms >= bar.timestamp_ms + 60_000)))]

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

    def _reset_stable_failure_burst(self):
        current=self.transport_health.current or {}
        if (self.connected and self.reconciled
                and self.transport_health.confirmed==self.transport_health.desired
                and self.client.clock_ms()-current.get('connection_started_at_ms',self.client.clock_ms())>=60000):
            self.consecutive_failures=0

    def run(self, stop_event, *, max_reconnects=5):
        import websocket
        if not self._run_owner.acquire(blocking=False):
            raise ExchangeError('STREAM_RECONNECT_OWNER_ALREADY_RUNNING')
        try:
            return self._run_owned(stop_event,max_reconnects=max_reconnects)
        finally:
            self._run_owner.release()

    def _receive(self, connection):
        # websocket-client.recv() discards the received close frame's reason.
        # Preserve it so a server close is distinguishable from a local failure.
        if not hasattr(connection,'recv_data_frame'):
            return connection.recv()
        import websocket
        opcode,frame=connection.recv_data_frame(control_frame=True)
        if opcode==websocket.ABNF.OPCODE_CLOSE:
            value=frame.data
            if isinstance(value,str):value=value.encode()
            self.transport_health.current['close_code']=int.from_bytes(value[:2],'big') if len(value)>=2 else None
            self.transport_health.current['close_reason']=value[2:].decode('utf-8',errors='replace')[:256]
            return ''
        if opcode in {websocket.ABNF.OPCODE_PING,websocket.ABNF.OPCODE_PONG}:
            return None
        return frame.data.decode('utf-8') if isinstance(frame.data,bytes) else frame.data

    def _run_owned(self, stop_event, *, max_reconnects):
        import websocket
        while not stop_event.is_set():
            connection = None
            recovered=queue.Queue(maxsize=1)
            try:
                self.reconciled = False
                self._recovery_cancel.clear()
                self._lifecycle('CONNECTING')
                self.client.startup()
                if self.rates is not None:
                    self.rates.ws_open(self.budget_identity)
                connection = self.connect()
                generation=self.transport_health.begin(self.subscriptions())
                for subscription in self.subscriptions():
                    if not self.transport_health.subscription_sent(subscription['subscription']):continue
                    if self.rates is not None and not self.rates.ws_send(self.budget_identity,subscription['subscription']):
                        continue
                    connection.send(json.dumps(subscription))
                self.connected = True
                self._lifecycle('SUBSCRIBED')
                self._recovery_cancel.clear()
                self.recovery_status='RECOVERING'
                def repair(token=generation, selected=None):
                    try:
                        with self.client.read_cancellation(self._recovery_cancel):
                            self.reconcile_history(token,selected)
                        recovered.put(None)
                    except Exception as exc:recovered.put(exc)
                self._recovery_worker=threading.Thread(target=repair,name='par-public-repair',daemon=True)
                self._recovery_worker.start()
                next_repair=float('inf')
                next_health_check=0
                repair_failures=0
                while not stop_event.is_set():
                    if not recovered.empty():
                        failure=recovered.get_nowait()
                        if isinstance(failure,VenueMismatch):raise failure
                        if failure is not None:
                            self.reconciled=False
                            self.recovery_status='RECOVERY_FAILED'
                            repair_failures+=1
                            self.last_error=type(failure).__name__+':'+str(failure)
                            self._lifecycle('REST_RECOVERY_DEFERRED',reason=self.last_error)
                            next_repair=time.monotonic()+self.transport_health.backoff(repair_failures)*5
                        elif self.recovery_errors:
                            self.last_error=None
                            # Per-symbol retry deadlines own local repair failures.
                            next_repair=float('inf')
                        else:
                            next_repair=float('inf');repair_failures=0
                            self.last_error=None
                    if time.monotonic()>=next_health_check:
                        self.market_health()
                        next_health_check=time.monotonic()+1
                    due=self.availability.prioritize(self.health_manager.due(self.client.clock_ms()),
                        self.health_manager.snapshot())
                    if due and self.reconciled and not self._recovery_worker.is_alive() and recovered.empty():
                        self.recovery_status='RECOVERING'
                        self._recovery_worker=threading.Thread(target=lambda selected=due:repair(selected=selected),
                            name='par-public-repair',daemon=True)
                        self._recovery_worker.start()
                        next_repair=float('inf')
                    if time.monotonic()>=next_repair and not self._recovery_worker.is_alive():
                        selected=tuple(self.recovery_errors) if self.recovery_status=='RECONCILED' else None
                        self.recovery_status='RECOVERING'
                        self._recovery_worker=threading.Thread(target=lambda:repair(selected=selected),name='par-public-repair',daemon=True)
                        self._recovery_worker.start()
                        next_repair=float('inf')
                    if self.transport_health.poll():
                        if self.rates is not None:
                            self.rates.ws_send(self.budget_identity,heartbeat=True)
                        connection.send(json.dumps({'method': 'ping'}))
                        self.transport_health.ping_sent()
                    try:
                        message = self._receive(connection)
                    except (websocket.WebSocketTimeoutException, TimeoutError):
                        continue
                    if message is None:continue
                    if not message:
                        raise ExchangeError('STREAM_DISCONNECTED')
                    self.last_receive_ms=self.client.clock_ms()
                    parsed=json.loads(message) if isinstance(message,str) else message
                    self.transport_health.receive(parsed,generation)
                    self.ingest(parsed,generation=generation)
                    if self.recovery_status=='RECONCILED' and self.transport_health.confirmed==self.transport_health.desired:
                        self.reconciled=True
                    self._reset_stable_failure_burst()
                    if self.reconciled and not self.recovery_errors:
                        self.transport_health.current['transport_state']='CONNECTED'
                        self.last_error=None
            except VenueMismatch:
                self.client.invalidate()
                raise
            except (ExchangeError, OSError, websocket.WebSocketException) as exc:
                self.last_error = type(exc).__name__ + ':' + str(exc)
                self.connected=self.reconciled=False
                self._recovery_cancel.set()
                if connection is not None:connection.close()
                self.consecutive_failures += 1
                self.reconnections += 1
                delay=self.transport_health.backoff(self.consecutive_failures)
                self.transport_health.disconnect(str(exc),pending_rest=int(bool(self._recovery_worker and self._recovery_worker.is_alive())),
                    rate_report=self.rates.report() if self.rates is not None else None,backoff=delay)
                self._lifecycle('DISCONNECTED',reason=self.last_error,consecutive_failures=self.consecutive_failures,
                                transport=self.transport_health.report())
                if self.consecutive_failures > max_reconnects:
                    raise ExchangeError('STREAM_RECONNECT_LIMIT') from exc
                stop_event.wait(delay)
            finally:
                self.connected = False
                self.reconciled = False
                self.recovery_status='DISCONNECTED'
                self._recovery_cancel.set()
                if self.rates is not None:
                    self.rates.ws_close(self.budget_identity)
                if connection is not None:
                    connection.close()
                if self._recovery_worker is not None:
                    self._recovery_worker.join(timeout=12)
                    if self._recovery_worker.is_alive():
                        raise ExchangeError('MARKET_RECOVERY_WORKER_DID_NOT_STOP')


class PasMarketDataEngine(ParMarketDataEngine):
    """PAS market engine name for the two-asset competition runtime.

    The implementation is venue-generic and subscribes exactly to the symbols
    supplied by the verified client registry. Keep ``ParMarketDataEngine`` as a
    backwards-compatible import for isolated historical fixtures.
    """
