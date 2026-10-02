"""Public testnet /info transport and mandatory par venue discovery.

No private keys, signing SDK, or /exchange HTTP transport exists in this module.
"""
from types import MappingProxyType
import time

from .base_exchange import ExchangeError, MarketSpec, VenueMismatch

TESTNET_API_URL = 'https://api.hyperliquid-testnet.xyz'
TESTNET_WS_URL = 'wss://api.hyperliquid-testnet.xyz/ws'
DEX = 'par'
EXPECTED_MARKETS = frozenset('par:' + name for name in (
    'BTC', 'ETH', 'HYPE', 'SP500', 'EWY', 'EWJ', 'BRENT', 'GOLD', 'USDEUR', 'USDJPY'))
DEX_QUERIES = frozenset({'meta', 'metaAndAssetCtxs', 'allMids', 'clearinghouseState',
                         'openOrders', 'perpDexLimits'})
COIN_QUERIES = frozenset({'l2Book', 'recentTrades', 'fundingHistory', 'activeAssetData'})
ACCOUNT_QUERIES = frozenset({'spotClearinghouseState', 'userFills', 'userFillsByTime',
                            'userFunding', 'userAbstraction', 'extraAgents', 'userFees', 'userRateLimit'})


class RequestsInfoTransport:
    def __init__(self, timeout=10):
        import requests
        self.session = requests.Session()
        self.timeout = timeout

    def __call__(self, payload):
        import requests
        try:
            response = self.session.post(TESTNET_API_URL + '/info', json=payload,
                                         timeout=self.timeout, allow_redirects=False)
            if response.status_code != 200:
                raise ExchangeError('INFO_HTTP_' + str(response.status_code))
            return response.json()
        except ExchangeError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise ExchangeError('INFO_REQUEST_FAILED') from exc

    def close(self):
        self.session.close()


class HyperliquidClient:
    def __init__(self, transport=None, *, base_url=TESTNET_API_URL, clock_ms=None):
        if base_url != TESTNET_API_URL:
            raise VenueMismatch('TESTNET_ENDPOINT_REQUIRED')
        self.transport = transport if transport is not None else RequestsInfoTransport()
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.ready = False
        self.markets = MappingProxyType({})
        self.dex_index = None
        self.collateral_token_id = None
        self.metadata_timestamp_ms = None
        self.last_received_ms = None

    def post_info(self, query, **parameters):
        if {'type', 'action', 'signature', 'nonce'} & parameters.keys():
            raise ExchangeError('INVALID_PUBLIC_INFO_PARAMETERS')
        if query not in DEX_QUERIES | COIN_QUERIES | ACCOUNT_QUERIES | {'perpDexs', 'candleSnapshot'}:
            raise ExchangeError('PUBLIC_INFO_QUERY_NOT_ALLOWED')
        payload = {'type': query, **parameters}
        if query in DEX_QUERIES:
            if payload.get('dex', DEX) != DEX:
                raise VenueMismatch('PAR_DEX_REQUIRED')
            payload['dex'] = DEX
        elif 'dex' in payload:
            raise ExchangeError('UNEXPECTED_DEX_PARAMETER')
        if query in COIN_QUERIES:
            self._validate_coin(payload.get('coin'))
        if query == 'candleSnapshot':
            if not isinstance(payload.get('req'), dict):
                raise ExchangeError('INVALID_CANDLE_REQUEST')
            self._validate_coin(payload['req'].get('coin'))
        result = self.transport(payload)
        self.last_received_ms = self.clock_ms()
        return result

    def _validate_coin(self, symbol):
        if not isinstance(symbol, str) or not symbol.startswith('par:'):
            raise VenueMismatch('EXPECTED_PAR_MARKET_REQUIRED')
        self.market(symbol)

    def invalidate(self):
        self.ready = False
        self.markets = MappingProxyType({})
        self.dex_index = None
        self.collateral_token_id = None
        self.metadata_timestamp_ms = None
        self.last_received_ms = None

    def _parse_specs(self, metadata, dex_index):
        if not isinstance(metadata, dict) or not isinstance(metadata.get('universe'), list):
            raise VenueMismatch('INVALID_PAR_METADATA')
        result = {}
        seen=set()
        try:
            tables={table_id:table['marginTiers'] for table_id,table in metadata.get('marginTables',[])}
        except (TypeError,KeyError,ValueError) as exc:
            raise VenueMismatch('INVALID_MARGIN_TABLES') from exc
        for index, row in enumerate(metadata['universe']):
            if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                raise VenueMismatch('INVALID_PAR_METADATA')
            name = row['name']
            if (not name.startswith('par:') or name.count(':')!=1 or len(name)<=4 or
                    name.strip()!=name or name in seen):
                raise VenueMismatch('INVALID_PAR_MARKET_NAMESPACE')
            seen.add(name)
            if row.get('isDelisted') and name in EXPECTED_MARKETS:
                raise VenueMismatch('EXPECTED_PAR_MARKET_DELISTED')
            if row.get('isDelisted'):
                continue
            try:
                table_id=row.get('marginTableId')
                if table_id is not None and (type(table_id) is not int or table_id<1):
                    raise VenueMismatch('INVALID_MARGIN_TABLE_ID')
                if table_id is not None and table_id>=50 and table_id not in tables:
                    raise VenueMismatch('MISSING_RUNTIME_MARGIN_TABLE')
                tiers=tuple((tier['lowerBound'],tier['maxLeverage']) for tier in tables[table_id]) if table_id in tables else ()
                result[name] = MarketSpec(name, row['szDecimals'], row['maxLeverage'],
                                          100000 + 10000 * dex_index + index,tiers)
            except (KeyError, TypeError, ValueError) as exc:
                raise VenueMismatch('INVALID_PAR_MARKET_SPEC') from exc
        if not EXPECTED_MARKETS <= result.keys():
            raise VenueMismatch("FATAL: Expected Perpetual Alpha DEX 'par' not detected. Trading disabled.")
        return {name: result[name] for name in sorted(result)}

    def startup(self):
        self.invalidate()
        dexes = self.post_info('perpDexs')
        if not isinstance(dexes, list):
            raise VenueMismatch('INVALID_DEX_LIST')
        matches = [i for i, row in enumerate(dexes)
                   if isinstance(row, dict) and row.get('name') == DEX]
        if len(matches) != 1 or matches[0] < 1:
            raise VenueMismatch("FATAL: Expected Perpetual Alpha DEX 'par' not detected. Trading disabled.")
        metadata = self.post_info('meta')
        specifications = self._parse_specs(metadata, matches[0])
        self.dex_index = matches[0]
        self.collateral_token_id = metadata.get('collateralToken')
        self.markets = MappingProxyType(specifications)
        self.metadata_timestamp_ms = self.clock_ms()
        self.ready = True
        return self.markets

    def market(self, symbol):
        if not self.ready:
            raise VenueMismatch('PAR_STARTUP_CHECK_REQUIRED')
        try:
            return self.markets[symbol]
        except KeyError as exc:
            raise VenueMismatch('EXPECTED_PAR_MARKET_REQUIRED') from exc

    def validate_metadata(self, metadata):
        if not self.ready:
            raise VenueMismatch('PAR_STARTUP_CHECK_REQUIRED')
        try:
            incoming = self._parse_specs(metadata, self.dex_index)
            if incoming != dict(self.markets):
                raise VenueMismatch('PAR_METADATA_CHANGED_RESTART_REQUIRED')
        except ExchangeError:
            self.invalidate()
            raise

    def close(self):
        close = getattr(self.transport, 'close', None)
        if close:
            close()
