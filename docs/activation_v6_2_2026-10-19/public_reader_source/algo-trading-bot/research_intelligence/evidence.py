"""Append-only public evidence with receipt checks and a sealed completion root.

Hashes detect local edits; they do not authenticate the exchange or prove that a
file labelled public is genuine. Raw responses and timestamps remain available
for independent inspection. This module opens files, never a network connection.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import threading
from .common import ResearchError, canonical, digest, immutable_json, stamp
from exchange.hyperliquid_market_data import parse_book, parse_candle
from exchange.base_exchange import ExchangeError

PUBLIC_QUERIES = frozenset({'perpDexs', 'meta', 'metaAndAssetCtxs', 'l2Book', 'candleSnapshot'})
PUBLIC_CHANNELS = frozenset({'subscriptionResponse', 'pong', 'l2Book', 'candle', 'activeAssetCtx'})


def require_public(payload):
    if not isinstance(payload, dict) or payload.get('type') not in PUBLIC_QUERIES:
        raise ResearchError('PUBLIC_RESEARCH_QUERY_REQUIRED')
    allowed = {'type'}
    if payload['type'] in {'meta', 'metaAndAssetCtxs'}:
        allowed.add('dex')
        if payload.get('dex') != 'par': raise ResearchError('PAR_DEX_REQUIRED')
    if payload['type'] == 'l2Book':
        allowed.add('coin')
        if not str(payload.get('coin', '')).startswith('par:'): raise ResearchError('PAR_COIN_REQUIRED')
    if payload['type'] == 'candleSnapshot':
        allowed.add('req')
        req = payload.get('req', {})
        if (set(req) != {'coin', 'interval', 'startTime', 'endTime'} or
                not str(req.get('coin', '')).startswith('par:') or req.get('interval') != '1m'):
            raise ResearchError('PUBLIC_CANDLE_REQUEST_REQUIRED')
    if set(payload) != allowed: raise ResearchError('PUBLIC_RESEARCH_PARAMETERS_FORBIDDEN')


def book_key(book):
    def side(rows): return [[str(x.price.normalize()), str(x.quantity.normalize())] for x in rows]
    return digest(dict(symbol=book.symbol, timestamp_ms=book.timestamp_ms,
                       bids=side(book.bids), asks=side(book.asks)))


def candle_key(c):
    return digest(dict(symbol=c.symbol, timestamp_ms=c.timestamp_ms, close_timestamp_ms=c.close_timestamp_ms,
        values=[str(Decimal(v).normalize()) for v in (c.open, c.high, c.low, c.close, c.volume)]))


class EvidenceWriter:
    def __init__(self, path):
        self.path = Path(path)
        self.file = self.path.open('x')
        self.lock = threading.RLock()
        self.sequence = 0
        self.root = None
        self.previous_ms = -1

    def append(self, kind, payload, observed_ms):
        with self.lock:
            stamp(observed_ms)
            if observed_ms < self.previous_ms: raise ResearchError('EVIDENCE_CLOCK_REGRESSED')
            record = dict(sequence=self.sequence, previous_hash=self.root, kind=kind,
                          observed_ms=observed_ms, payload=deepcopy(payload))
            record['sha256'] = digest(record)
            self.file.write(canonical(record) + '\n'); self.file.flush()
            self.root = record['sha256']; self.sequence += 1; self.previous_ms = observed_ms
            return record['sha256']

    def close(self, completion_path, *, status, details=None):
        with self.lock:
            self.file.close()
            immutable_json(completion_path, dict(records=self.sequence, root_hash=self.root,
                                                status=status, details=details or {}, exchange_orders_submitted=0))


class ReceiptIndex:
    """Every normalized frame value must match a preceding public raw receipt."""
    def __init__(self):
        self.books = {}; self.candles = {}; self.contexts = {}; self.metadata = {}; self.dexes = {}

    @staticmethod
    def remember(index,key,value,limit):
        if key in index:
            value=min(value,index[key]); del index[key]
        index[key]=value
        while len(index)>limit: del index[next(iter(index))]

    def _book(self, value, observed):
        try: self.remember(self.books,book_key(parse_book(value, value['coin'])),observed,5000)
        except (ExchangeError, ValueError, KeyError): pass  # Empty/invalid book remains a diagnostic, never executable.

    def _candle(self, value, observed):
        try: self.remember(self.candles,candle_key(parse_candle(value, value['s'], '1m')),observed,100000)
        except (ExchangeError, ValueError, KeyError): pass

    def add(self, record):
        p = record['payload']; t = record['observed_ms']
        if record['kind'] == 'INFO':
            require_public(p['request']); q = p['request']['type']; value = p['response']
            if q == 'perpDexs': self.dexes[digest(value)] = t
            elif q == 'meta': self.metadata[digest(value)] = t
            elif q == 'l2Book': self._book(value, t)
            elif q == 'candleSnapshot':
                for c in value: self._candle(c, t)
            elif q == 'metaAndAssetCtxs':
                self.metadata[digest(value[0])] = t
                for row, ctx in zip(value[0]['universe'], value[1]):
                    self.remember(self.contexts,digest(dict(symbol=row['name'], context=ctx)),t,5000)
        elif record['kind'] == 'STREAM':
            channel = p.get('channel'); value = p.get('data')
            if channel not in PUBLIC_CHANNELS: raise ResearchError('PUBLIC_STREAM_CHANNEL_REQUIRED')
            if channel == 'l2Book': self._book(value, t)
            elif channel == 'candle':
                for c in value if isinstance(value, list) else [value]: self._candle(c, t)
            elif channel == 'activeAssetCtx':
                self.remember(self.contexts,digest(dict(symbol=value['coin'], context=value['ctx'])),t,5000)

    def verify(self, frame):
        from dataclasses import fields
        from exchange.base_exchange import BookLevel, OrderBook, Candle
        t = stamp(frame['decision_ms'])
        for value, index in ((frame['metadata'], self.metadata), (frame['dexes'], self.dexes)):
            if digest(value) not in index or index[digest(value)] > t: raise ResearchError('METADATA_RECEIPT_UNPROVEN')
        for symbol, value in frame['books'].items():
            book = OrderBook(**dict(value, bids=tuple(BookLevel(Decimal(x['price']), Decimal(x['quantity'])) for x in value['bids']),
                asks=tuple(BookLevel(Decimal(x['price']), Decimal(x['quantity'])) for x in value['asks'])))
            received = stamp(book.received_timestamp_ms)
            if book.symbol != symbol or not book.timestamp_ms <= received <= t:
                raise ResearchError('BOOK_AVAILABILITY_UNPROVEN')
            if book_key(book) not in self.books or self.books[book_key(book)] > received:
                raise ResearchError('BOOK_RAW_RECEIPT_UNPROVEN')
        for symbol, value in frame['contexts'].items():
            received = stamp(frame['context_times'][symbol]); key = digest(dict(symbol=symbol, context=value))
            if received > t or key not in self.contexts or self.contexts[key] > received:
                raise ResearchError('CONTEXT_RAW_RECEIPT_UNPROVEN')
        for symbol, history in frame.get('histories', {}).items():
            for value in history:
                c = Candle(**{k: Decimal(v) if k in {'open','high','low','close','volume'} else v for k,v in value.items()})
                received = stamp(c.received_timestamp_ms)
                if c.symbol != symbol or not c.timestamp_ms + 60000 <= received <= t:
                    raise ResearchError('CANDLE_AVAILABILITY_UNPROVEN')
                if candle_key(c) not in self.candles or self.candles[candle_key(c)] > received:
                    raise ResearchError('CANDLE_RAW_RECEIPT_UNPROVEN')


def read_evidence(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'capture_manifest.json').read_text())
    body = deepcopy(manifest); expected = body.pop('sha256', None)
    if expected != digest(body) or body.get('schema_version') != 1:
        raise ResearchError('CAPTURE_MANIFEST_INVALID')
    completion = json.loads((directory/'capture_completion.json').read_text())
    root = None; count = 0; last = -1; receipts = ReceiptIndex()
    with (directory/'evidence.jsonl').open() as stream:
        for line in stream:
            r = json.loads(line); expected = r.pop('sha256')
            if digest(r) != expected or r['sequence'] != count or r['previous_hash'] != root:
                raise ResearchError('EVIDENCE_CHAIN_INVALID')
            t = stamp(r['observed_ms'])
            if t < last: raise ResearchError('EVIDENCE_CLOCK_REGRESSED')
            r['sha256'] = expected; root = expected; last = t; count += 1
            receipts.add(r)
            if r['kind'] == 'FRAME':
                if r['payload']['decision_ms'] > t: raise ResearchError('FRAME_DECISION_IN_FUTURE')
                receipts.verify(r['payload'])
                yield manifest, r
    if completion['records'] != count or completion['root_hash'] != root:
        raise ResearchError('EVIDENCE_TRUNCATED_OR_ROOT_MISMATCH')
    if completion['status'] not in {'COMPLETE', 'INTERRUPTED'}: raise ResearchError('CAPTURE_FAILED')
