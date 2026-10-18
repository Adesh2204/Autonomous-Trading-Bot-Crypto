"""Public testnet /info transport and mandatory PAS BTC venue discovery.

No private keys, signing SDK, or /exchange HTTP transport exists in this module.
"""
from types import MappingProxyType
from copy import deepcopy
import time
import json
import threading
from contextlib import contextmanager

from .base_exchange import ExchangeError, MarketSpec, VenueMismatch
from .competition_market import (COMPETITION_MARKET, COMPETITION_BASE_ASSET, canonical_api_market, resolve_competition_dex, resolve_collateral_token)

TESTNET_API_URL = 'https://api.hyperliquid-testnet.xyz'
TESTNET_WS_URL = 'wss://api.hyperliquid-testnet.xyz/ws'
DEX_QUERIES = frozenset({'meta', 'metaAndAssetCtxs', 'allMids', 'clearinghouseState',
                         'openOrders', 'frontendOpenOrders', 'perpDexLimits'})
COIN_QUERIES = frozenset({'l2Book', 'recentTrades', 'fundingHistory', 'activeAssetData'})
ACCOUNT_QUERIES = frozenset({'spotClearinghouseState', 'userFills', 'userFillsByTime',
                            'userFunding', 'userAbstraction', 'extraAgents', 'userFees', 'userRateLimit',
                            'orderStatus'})


class RequestsInfoTransport:
    """Public reads only, with socket limits and a bounded caller deadline.

    One daemon worker owns this session at a time. A stalled DNS/SSL/body read
    cannot strand the caller or create unlimited workers. After timeout/cancel,
    its slot stays occupied until cleanup; subsequent reads remain bounded.
    The worker never accesses a journal, signer, nonce or /exchange.
    """
    def __init__(self, timeout=None, *, connect_timeout=3.05, read_timeout=5,
                 total_timeout=12, max_response_bytes=8*1024*1024):
        import requests, threading, math
        if timeout is not None:
            if isinstance(timeout,tuple) and len(timeout)==2:connect_timeout,read_timeout=timeout
            else:connect_timeout=read_timeout=timeout
        values=(connect_timeout,read_timeout,total_timeout)
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values):
            raise ExchangeError('INFO_TIMEOUT_POLICY_INVALID')
        if type(max_response_bytes) is not int or max_response_bytes<1:
            raise ExchangeError('INFO_RESPONSE_LIMIT_INVALID')
        self.session=requests.Session();self.timeout=(connect_timeout,read_timeout)
        self.total_timeout=total_timeout;self.max_response_bytes=max_response_bytes
        self._lock=threading.Lock();self._idle=threading.Event();self._idle.set()
        self._active=None;self._closed=False;self.last_diagnostic=None

    @staticmethod
    def _failure(code, *, retryable=False, **attributes):
        error=ExchangeError(code);error.retryable=retryable
        for key,value in attributes.items():setattr(error,key,value)
        return error

    @staticmethod
    def _caused_by(exc, names=(), classes=()):
        pending=[exc];seen=set()
        while pending and len(seen)<40:
            value=pending.pop()
            if id(value) in seen:continue
            seen.add(id(value))
            if isinstance(value,classes) or type(value).__name__ in names:return True
            if isinstance(value,BaseException):
                pending.extend(x for x in (*value.args,value.__cause__,value.__context__) if isinstance(x,BaseException))
        return False

    @staticmethod
    def _retry_after(value):
        import math
        from datetime import datetime,timezone
        from email.utils import parsedate_to_datetime
        if value is None:return None
        try:
            seconds=float(value)
            if not math.isfinite(seconds):return None
            return max(0,int(seconds*1000))
        except (TypeError,ValueError,OverflowError):
            try:
                stamp=parsedate_to_datetime(value)
                if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
                return max(0,int((stamp-datetime.now(timezone.utc)).total_seconds()*1000))
            except (TypeError,ValueError,OverflowError):return None

    def _worker(self, payload, record):
        import requests
        response=None
        try:
            response=self.session.post(TESTNET_API_URL+'/info',json=payload,
                timeout=self.timeout,allow_redirects=False,stream=True)
            if response.status_code!=200:
                raise self._failure('INFO_HTTP_'+str(response.status_code),
                    status_code=response.status_code,retryable=response.status_code==429 or 500<=response.status_code<600,
                    retry_after_ms=self._retry_after(response.headers.get('Retry-After')))
            body=bytearray()
            for chunk in response.iter_content(chunk_size=4096):
                if record['abort'].is_set():raise self._failure('INFO_READ_CANCELLED')
                body.extend(chunk)
                if len(body)>self.max_response_bytes:raise self._failure('INFO_RESPONSE_TOO_LARGE')
            if record['abort'].is_set():raise self._failure('INFO_READ_CANCELLED')
            record['value']=json.loads(body)
        except requests.ConnectTimeout:record['error']=self._failure('INFO_CONNECT_TIMEOUT',retryable=True)
        except requests.ReadTimeout:record['error']=self._failure('INFO_READ_TIMEOUT',retryable=True)
        except requests.exceptions.SSLError:record['error']=self._failure('INFO_TLS_FAILED')
        except requests.ConnectionError as exc:
            import socket
            code=('INFO_DNS_FAILED' if self._caused_by(exc,('NameResolutionError',),(socket.gaierror,)) else
                  'INFO_READ_TIMEOUT' if self._caused_by(exc,('ReadTimeoutError',)) else 'INFO_CONNECTION_FAILED')
            record['error']=self._failure(code,retryable=True)
        except requests.Timeout:record['error']=self._failure('INFO_READ_TIMEOUT',retryable=True)
        except requests.RequestException:record['error']=self._failure('INFO_REQUEST_FAILED')
        except ExchangeError as exc:record['error']=exc
        except (ValueError,UnicodeError):record['error']=self._failure('INFO_INVALID_JSON')
        except BaseException as exc:record['error']=exc
        finally:
            try:
                if response is not None:response.close()
            finally:
                with self._lock:
                    self._active=None;self._idle.set()
                    if self._closed:self.session.close()
                record['done'].set()

    def __call__(self,payload,*,cancel_event=None,progress=None):
        import threading
        started=time.monotonic();record=None;last_update=0
        def check():
            if cancel_event is not None and cancel_event.is_set():raise self._failure('INFO_READ_CANCELLED')
            if time.monotonic()-started>=self.total_timeout:raise self._failure('INFO_TOTAL_TIMEOUT')
        try:
            while record is None:
                check()
                with self._lock:
                    if self._closed:raise self._failure('INFO_TRANSPORT_CLOSED')
                    if self._active is None:
                        record=dict(done=threading.Event(),abort=threading.Event(),value=None,error=None)
                        self._active=record;self._idle.clear()
                        worker=threading.Thread(target=self._worker,args=(deepcopy(payload),record),
                            name='anchorium-public-info',daemon=True)
                        worker.start()
                if record is None:
                    self._idle.wait(.05)
                    if progress and time.monotonic()-last_update>=1:
                        progress('WAITING_FOR_HTTP_SLOT',query=payload.get('type'),
                            reason='PREVIOUS_PUBLIC_READ_CLEANUP',request_elapsed_seconds=round(time.monotonic()-started,3))
                        last_update=time.monotonic()
            while not record['done'].wait(.05):
                check()
                if progress and time.monotonic()-last_update>=1:
                    progress('WAITING_FOR_HTTP_RESPONSE',query=payload.get('type'),
                             request_elapsed_seconds=round(time.monotonic()-started,3),
                             remaining_deadline_seconds=round(max(0,self.total_timeout-(time.monotonic()-started)),3))
                    last_update=time.monotonic()
            check()
            if record['error'] is not None:raise record['error']
            self.last_diagnostic=dict(query=payload.get('type'),result='OK',elapsed_seconds=round(time.monotonic()-started,3))
            return record['value']
        except BaseException as exc:
            if record is not None:record['abort'].set()
            self.last_diagnostic=dict(query=payload.get('type'),result=str(exc) if isinstance(exc,ExchangeError)
                else 'INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else type(exc).__name__,
                elapsed_seconds=round(time.monotonic()-started,3))
            raise

    def close(self):
        with self._lock:
            self._closed=True
            if self._active is not None:self._active['abort'].set()
            else:self.session.close()

class HyperliquidClient:
    def __init__(self, transport=None, *, base_url=TESTNET_API_URL, clock_ms=None, rate_limits=None, candle_audit=None, progress=None):
        if base_url != TESTNET_API_URL:
            raise VenueMismatch('TESTNET_ENDPOINT_REQUIRED')
        self.base_url = base_url
        self.transport = transport if transport is not None else RequestsInfoTransport()
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.ready = False
        self.markets = MappingProxyType({})
        self.dex_index = None
        self.collateral_token_id = None
        self.collateral_token_name = None
        self.competition_market = COMPETITION_MARKET
        self.api_dex = None
        self.api_market = None
        self.dex_identity = None
        self.dex_total_oi_notional = None
        self.dex_oi_observed_ms = None
        self.dex_oi_market_count = None
        self.metadata_timestamp_ms = None
        self.last_received_ms = None
        self.metadata = None
        self.rate_limits = rate_limits
        self.read_cancel_event=None
        self.candle_audit=candle_audit
        self.progress=progress
        self._snapshots=threading.local()
        self.snapshot_hits=0

    @contextmanager
    def read_snapshot_scope(self,max_age_ms=1000):
        """Qualification read-only bundle reuse, never quotes/history/positions.

        Only account mode, agent list and fees may share their original response
        within one second. Preserve original receive time; no cache survives the
        scope or crosses a thread. Independent position/order comparisons remain.
        """
        if type(max_age_ms) is not int or not 0<max_age_ms<=1000:
            raise ExchangeError('INVALID_INFO_SNAPSHOT_AGE')
        previous=getattr(self._snapshots,'scope',None)
        self._snapshots.scope=dict(max_age_ms=max_age_ms,values={})
        try:yield
        finally:self._snapshots.scope=previous

    def post_info(self, query, *, priority=None, **parameters):
        if {'type', 'action', 'signature', 'nonce'} & parameters.keys():
            raise ExchangeError('INVALID_PUBLIC_INFO_PARAMETERS')
        if query not in DEX_QUERIES | COIN_QUERIES | ACCOUNT_QUERIES | {'perpDexs', 'candleSnapshot', 'spotMeta'}:
            raise ExchangeError('PUBLIC_INFO_QUERY_NOT_ALLOWED')
        payload = {'type': query, **parameters}
        if query in DEX_QUERIES:
            if self.api_dex is None:
                raise VenueMismatch('PAS_DEX_DISCOVERY_REQUIRED')
            requested = payload.get('dex', self.api_dex)
            if requested != self.api_dex:
                raise VenueMismatch('COMPETITION_DEX_MISMATCH')
            payload['dex'] = self.api_dex
        elif 'dex' in payload:
            raise ExchangeError('UNEXPECTED_DEX_PARAMETER')
        if query in COIN_QUERIES:
            self._validate_coin(payload.get('coin'))
        if query == 'candleSnapshot':
            if not isinstance(payload.get('req'), dict):
                raise ExchangeError('INVALID_CANDLE_REQUEST')
            self._validate_coin(payload['req'].get('coin'))
        started=time.monotonic();key=json.dumps(payload,sort_keys=True)
        if self.progress:self.progress('INFO_READ_STARTED',query=query)
        scope=getattr(self._snapshots,'scope',None)
        reusable=scope is not None and query in {'userAbstraction','extraAgents','userFees'}
        saved=scope['values'].get(key) if reusable else None
        if saved is not None and 0<=self.clock_ms()-saved[0]<=scope['max_age_ms']:
            self.snapshot_hits+=1;self.last_received_ms=saved[0]
            if self.progress:self.progress('INFO_SNAPSHOT_REUSED',query=query,observed_ms=saved[0],age_ms=self.clock_ms()-saved[0])
            return deepcopy(saved[1])
        operation=(lambda:self.transport(payload,cancel_event=self.read_cancel_event,progress=self.progress)) \
            if isinstance(self.transport,RequestsInfoTransport) else (lambda:self.transport(payload))
        if self.rate_limits is not None:
            req=payload.get('req',{})
            from .hyperliquid_market_data import INTERVAL_MS
            expected=(max(0,(req.get('endTime',0)-req.get('startTime',0))//INTERVAL_MS.get(req.get('interval'),60000)+1)
                      if query=='candleSnapshot' else 0)
            result=self.rate_limits.read(query,operation,priority=priority,
                request_key=key,expected_items=expected,cancel_event=self.read_cancel_event)
        else:
            result = operation()
        self.last_received_ms = self.clock_ms()
        if reusable:scope['values'][key]=(self.last_received_ms,deepcopy(result))
        if self.progress:self.progress('INFO_READ_COMPLETED',query=query,request_elapsed_seconds=round(time.monotonic()-started,3))
        if self.candle_audit is not None and query=='candleSnapshot':
            self.candle_audit.record('RAW_REST',request=payload,response=result,
                received_ms=self.last_received_ms,client_id=id(self),network='testnet')
        return result

    def _validate_coin(self, symbol):
        if not isinstance(symbol, str) or self.api_market is None or symbol != self.api_market:
            raise VenueMismatch('PAS_BTC_MARKET_REQUIRED')
        self.market(symbol)

    def canonical_market_name(self, raw_name):
        return canonical_api_market(self.api_dex, raw_name)

    def invalidate(self):
        self.ready = False
        self.markets = MappingProxyType({})
        self.dex_index = None
        self.collateral_token_id = None
        self.collateral_token_name = None
        self.api_dex = None
        self.api_market = None
        self.dex_identity = None
        self.dex_total_oi_notional = None
        self.dex_oi_observed_ms = None
        self.dex_oi_market_count = None
        self.metadata_timestamp_ms = None
        self.last_received_ms = None
        self.metadata = None

    def _parse_specs(self, metadata, dex_index):
        if not isinstance(metadata, dict) or not isinstance(metadata.get('universe'), list):
            raise VenueMismatch('INVALID_PAS_METADATA')
        if not isinstance(self.api_dex, str) or not self.api_dex or type(dex_index) is not int or dex_index < 1:
            raise VenueMismatch('PAS_DEX_MAPPING_UNVERIFIED')
        result = {}
        seen = set()
        try:
            tables = {table_id: table['marginTiers'] for table_id, table in metadata.get('marginTables', [])}
        except (TypeError, KeyError, ValueError) as exc:
            raise VenueMismatch('INVALID_MARGIN_TABLES') from exc
        btc_found = False
        for index, row in enumerate(metadata['universe']):
            if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                raise VenueMismatch('INVALID_PAS_METADATA')
            name = self.canonical_market_name(row['name'])
            if name in seen:
                raise VenueMismatch('DUPLICATE_MARKET_METADATA')
            seen.add(name)
            base = name.split(':', 1)[1]
            if base != COMPETITION_BASE_ASSET:
                # Non-BTC metadata is never admitted to the production market registry.
                continue
            btc_found = True
            if row.get('isDelisted'):
                raise VenueMismatch('PAS_BTC_DELISTED')
            try:
                table_id = row.get('marginTableId')
                if table_id is not None and (type(table_id) is not int or table_id < 1):
                    raise VenueMismatch('INVALID_MARGIN_TABLE_ID')
                if table_id is not None and table_id >= 50 and table_id not in tables:
                    raise VenueMismatch('MISSING_RUNTIME_MARGIN_TABLE')
                tiers = tuple((tier['lowerBound'], tier['maxLeverage']) for tier in tables[table_id]) if table_id in tables else ()
                result[name] = MarketSpec(name, row['szDecimals'], row['maxLeverage'],
                    100000 + 10000 * dex_index + index, tiers)
            except (KeyError, TypeError, ValueError) as exc:
                raise VenueMismatch('INVALID_PAS_BTC_MARKET_SPEC') from exc
        if not btc_found or len(result) != 1:
            raise VenueMismatch('PAS_BTC_MAPPING_UNVERIFIED')
        return result

    @staticmethod
    def _canonical_metadata(metadata, api_dex):
        from copy import deepcopy
        normalized = deepcopy(metadata)
        for row in normalized.get('universe', []):
            if isinstance(row, dict) and isinstance(row.get('name'), str):
                row['name'] = canonical_api_market(api_dex, row['name'])
        return normalized

    def startup(self):
        self.invalidate()
        dexes = self.post_info('perpDexs')
        api_dex, dex_index, identity = resolve_competition_dex(dexes)
        self.api_dex = api_dex
        self.dex_index = dex_index
        self.dex_identity = identity
        metadata = self.post_info('meta', dex=api_dex)
        specifications = self._parse_specs(metadata, dex_index)
        self.api_market = next(iter(specifications))
        self.collateral_token_id = metadata.get('collateralToken')
        spot_metadata = self.post_info('spotMeta')
        self.collateral_token_name = resolve_collateral_token(self.collateral_token_id, spot_metadata)
        if not isinstance(self.collateral_token_name, str) or not self.collateral_token_name:
            raise VenueMismatch('PAS_COLLATERAL_MAPPING_UNVERIFIED')
        self.markets = MappingProxyType(specifications)
        self.metadata = self._canonical_metadata(metadata, api_dex)
        self.metadata_timestamp_ms = self.clock_ms()
        self.ready = True
        return self.markets

    def market(self, symbol):
        if not self.ready:
            raise VenueMismatch('PAS_STARTUP_CHECK_REQUIRED')
        if symbol != self.api_market:
            raise VenueMismatch('PAS_BTC_MARKET_REQUIRED')
        try:
            return self.markets[symbol]
        except KeyError as exc:
            raise VenueMismatch('PAS_BTC_MARKET_REQUIRED') from exc

    def validate_metadata(self, metadata):
        if not self.ready:
            raise VenueMismatch('PAS_STARTUP_CHECK_REQUIRED')
        try:
            incoming = self._parse_specs(metadata, self.dex_index)
            if (incoming != dict(self.markets) or metadata.get('collateralToken') != self.collateral_token_id):
                raise VenueMismatch('PAS_METADATA_CHANGED_RESTART_REQUIRED')
        except ExchangeError:
            self.invalidate()
            raise

    def close(self):
        close = getattr(self.transport, 'close', None)
        if close:
            close()
