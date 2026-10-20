"""Trusted public stream reads with explicit REST fallback, never fabricated data."""
from .base_exchange import ExchangeError
from .candle_audit import merge_candle
from .hyperliquid_market_data import HyperliquidMarketData, timestamp

MINUTE_MS = 60_000
PAS_REST_CHUNK_BARS = 300
PAS_FAIR_REST_CHUNK_BARS = 150
PAS_MAX_REQUEST_BARS = 5000


class StreamFirstMarketData(HyperliquidMarketData):
    def __init__(self, client, engine, *, require_warmup=False):
        super().__init__(client)
        self.engine = engine
        self.require_warmup = require_warmup

    def get_quote(self, symbol):
        try:
            return self.engine.get_quote(symbol)
        except ExchangeError:
            return super().get_quote(symbol)

    def get_orderbook(self, symbol):
        try:
            self.engine.get_quote(symbol)  # independent BBO + context freshness
            with self.engine._lock:
                return self.engine.books[symbol]
        except ExchangeError:
            return super().get_orderbook(symbol)

    def _cache_pas_rows(self, symbol, rows, now):
        """Commit validated real chunks before the next request can be deferred."""
        with self.engine._lock:
            merged = dict(self.engine.candles[symbol])
            for candle in rows:
                merged[candle.timestamp_ms] = merge_candle(
                    merged.get(candle.timestamp_ms), candle, now)
            self.engine.candles[symbol] = dict(sorted(merged.items())[-self.engine.retention_capacity:])
            if rows:
                self.engine._audit_cache(symbol, 'SCANNER_INCREMENTAL_REPAIR',
                    rows[0].timestamp_ms, rows[-1].close_timestamp_ms)

    @staticmethod
    def _missing_chunks(expected, present, chunk_bars=PAS_REST_CHUNK_BARS):
        """Only contiguous missing starts; no request includes invented bars."""
        chunks = []
        for stamp in expected:
            if stamp in present:
                continue
            if (chunks and len(chunks[-1]) < chunk_bars
                    and stamp == chunks[-1][-1] + MINUTE_MS):
                chunks[-1].append(stamp)
            else:
                chunks.append([stamp])
        return chunks

    def get_candles(self, symbol, start_ms, end_ms, *, interval='1m', now_ms=None):
        self.client.market(symbol)
        start_ms, end_ms = timestamp(start_ms), timestamp(end_ms)
        now = self.client.clock_ms() if now_ms is None else timestamp(now_ms)
        if end_ms < start_ms:
            raise ExchangeError('INVALID_CANDLE_RANGE')
        stream_usable = interval == '1m' and self.engine.connected and self.engine.reconciled
        pas = bool(getattr(self.client, 'competition_mode', False))
        if pas:
            if self.require_warmup:
                # Mandatory current-window recovery owns the scarce candle slots
                # before optional older UTC-anchor history is requested.
                from .market_health import validate_history
                warm=self.engine.get_completed_candles(symbol)
                validate_history(symbol,warm,now,self.engine.history_bars)
                if not 0<=now-(warm[-1].timestamp_ms+MINUTE_MS)<=120000:
                    raise ExchangeError('COMPLETED_CANDLE_STALE')
            integrity_errors = (self.engine.scanner_errors.get(symbol),
                self.engine.input_errors[symbol].get('history_health'),
                self.engine.recovery_errors.get(symbol))
            if 'CONFLICTING_COMPLETED_CANDLES' in integrity_errors:
                raise ExchangeError('CONFLICTING_COMPLETED_CANDLES')
        if interval != '1m':
            return super().get_candles(symbol, start_ms, end_ms, interval=interval, now_ms=now_ms)
        if (end_ms - start_ms) // MINUTE_MS + 1 > PAS_MAX_REQUEST_BARS:
            raise ExchangeError('CANDLE_RANGE_EXCEEDS_API_LIMIT')
        # Caller time cannot finalize a bar the source has not yet completed.
        as_of = min(now, self.client.clock_ms())
        first = ((start_ms + MINUTE_MS - 1) // MINUTE_MS) * MINUTE_MS
        last = min(end_ms // MINUTE_MS * MINUTE_MS, (as_of // MINUTE_MS - 1) * MINUTE_MS)
        expected = list(range(first, last + 1, MINUTE_MS))
        retained = ([c for c in self.engine.get_completed_candles(symbol)
                     if first <= c.timestamp_ms <= last] if stream_usable else [])
        if retained and [c.timestamp_ms for c in retained] == expected:
            return retained
        if not pas:
            # Preserve historical offline PAR behavior, without PAS cache mixing.
            return super().get_candles(symbol, start_ms, end_ms, interval=interval, now_ms=now_ms)
        merged = {c.timestamp_ms: c for c in retained}
        try:
            chunk_bars=(PAS_FAIR_REST_CHUNK_BARS
                if getattr(self.client,'fair_candle_scheduling',False) else PAS_REST_CHUNK_BARS)
            chunks = self._missing_chunks(expected, merged, chunk_bars)
            for chunk in chunks:
                read_first, read_last = chunk[0], chunk[-1]
                # Re-check an adjacent retained source fact when capacity permits.
                if len(chunk) < chunk_bars:
                    if read_last + MINUTE_MS in merged:
                        read_last += MINUTE_MS
                    elif read_first - MINUTE_MS in merged:
                        read_first -= MINUTE_MS
                try:
                    rows = super().get_candles(symbol, read_first,
                        min(end_ms, read_last + MINUTE_MS - 1), interval=interval, now_ms=as_of)
                except ExchangeError as exc:
                    # Local quota refusal happens before HTTP and charges no
                    # candle slots. Optional adjacency must not prevent an
                    # essential missing-only read that still fits both caps.
                    if (str(exc) not in {'PAS_CANDLE_MARKET_SHARE_EXHAUSTED',
                            'PAS_CANDLE_BUDGET_EXHAUSTED'} or
                            (read_first, read_last) == (chunk[0], chunk[-1])):
                        raise
                    rows = super().get_candles(symbol, chunk[0],
                        min(end_ms, chunk[-1] + MINUTE_MS - 1), interval=interval, now_ms=as_of)
                # A cap/backoff on the next chunk must not discard this one.
                self._cache_pas_rows(symbol, rows, self.client.clock_ms())
                for candle in rows:
                    merged[candle.timestamp_ms] = merge_candle(
                        merged.get(candle.timestamp_ms), candle, self.client.clock_ms())
            if sorted(merged) != expected:
                raise ExchangeError('PAS_SCANNER_WINDOW_INCOMPLETE')
            # A disconnect during REST repair cannot turn old cached facts into
            # an accepted connected stream snapshot. Fully REST-sourced windows
            # remain valid data, subject to the scanner/account health gates.
            if retained and not (self.engine.connected and self.engine.reconciled):
                raise ExchangeError('STREAM_CHANGED_DURING_CANDLE_REPAIR')
            return [merged[t] for t in sorted(merged)]
        except ExchangeError as exc:
            if str(exc) == 'CONFLICTING_COMPLETED_CANDLES':
                self.engine.note_scanner_failure(symbol, str(exc))
            raise
