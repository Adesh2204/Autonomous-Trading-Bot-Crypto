"""Pinned official SDK serialization/signing with a guarded testnet-only sink."""
from copy import deepcopy
from importlib.metadata import version
import threading

from .base_exchange import ExchangeError, decimal_string
from .execution_journal import fingerprint
from .hyperliquid_client import TESTNET_API_URL
from .venue_profiles import SCORED
from .competition_market import COMPETITION_ACTIVE_BASE_ASSETS, COMPETITION_COLLATERAL

SDK_VERSION='0.24.0'


def verify_sdk():
    if version('hyperliquid-python-sdk')!=SDK_VERSION:
        raise ExchangeError('PINNED_HYPERLIQUID_SDK_REQUIRED')
    return SDK_VERSION


def sdk_number(value):
    from hyperliquid.utils.signing import float_to_wire
    from .base_exchange import decimal
    number=float(value)
    try:
        if decimal(float_to_wire(number))!=value:
            raise ExchangeError('SDK_NUMERIC_PRECISION_LOSS')
    except (ValueError,OverflowError):
        raise ExchangeError('SDK_NUMERIC_PRECISION_LOSS') from None
    return number


def _require_pas_market_mapping(client):
    """Return the exact verified base->API-name map eligible for the SDK."""
    expected_bases = set(COMPETITION_ACTIVE_BASE_ASSETS)
    mapping = getattr(client, 'api_markets', None)
    if (getattr(client, 'base_url', None) != TESTNET_API_URL
            or getattr(client, 'competition_mode', False) is not True
            or getattr(client, 'dex', None) != 'pas'
            or getattr(client, 'venue_identity', None) != SCORED.identity
            or not getattr(client, 'ready', False)
            or not isinstance(mapping, dict) or set(mapping) != expected_bases
            or set(getattr(client, 'markets', {})) != set(mapping.values())
            or getattr(client, 'api_market', None) != mapping.get('BTC')
            or getattr(client, 'collateral', None) != COMPETITION_COLLATERAL
            or getattr(client, 'collateral_token_name', None) != COMPETITION_COLLATERAL
            or not isinstance(getattr(client, 'api_dex', None), str)
            or not client.api_dex.strip()
            or getattr(client, 'market_mapping', {}).get('verification') !=
                'VERIFIED_FROM_LIVE_PERP_DEX_AND_MARKET_METADATA'
            or getattr(client, 'market_mapping', {}).get('api_markets') != mapping):
        raise ExchangeError('SIGNED_VENUE_PAS_VERIFIED_MAPPING_REQUIRED')
    for base, name in mapping.items():
        if (not isinstance(name, str) or name != f'{client.api_dex}:{base}'
                or client.market(name).symbol != name):
            raise ExchangeError('SIGNED_VENUE_PAS_VERIFIED_MAPPING_REQUIRED')
    return dict(mapping)


def build_exchange(signer,client,nonce_manager,sink,*,offline=False):
    """Construct the official SDK only for the runtime-verified PAS active set.

    Offline construction reproduces inspected SDK fields without a REST request;
    the production branch uses the same exact PAS DEX mapping. Legacy PAR is
    never routed through an SDK instance, even when supplied explicitly.
    """
    api_markets = _require_pas_market_mapping(client)
    verify_sdk()
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.api import API
    from hyperliquid.utils.signing import sign_l1_action

    class GuardedExchange(Exchange):
        def _post_action(self, action, signature, nonce):
            # SDK's generated timestamp is replaced with the leased durable nonce
            # and re-signed using the official testnet-domain signing function.
            sink.check(action)
            nonce=nonce_manager.next()
            expiry=getattr(sink,'action_expiry_ms',None)
            signature=sign_l1_action(self.wallet,action,None,nonce,expiry,False)
            payload=dict(action=action,nonce=nonce,signature=signature,vaultAddress=None,expiresAfter=expiry)
            audit=getattr(sink,'audit_boundary',None)
            if audit is not None:
                audit('SIGNED',payload)
            elif action.get('type')!='updateLeverage':
                # The separately guarded, fixed-action configuration helper
                # has no order intents. Every order sink still requires audit.
                raise ExchangeError('SIGNED_ORDER_AUDIT_REQUIRED')
            return sink.transmit(payload)

        def post(self, path, payload=None):
            raise ExchangeError('RAW_SDK_POST_DISABLED')

    if offline:
        exchange=GuardedExchange.__new__(GuardedExchange)
        API.__init__(exchange,TESTNET_API_URL,timeout=10)
        info=Info.__new__(Info)
        API.__init__(info,TESTNET_API_URL,timeout=10)
        info.ws_manager=None
        info.coin_to_asset={}
        info.name_to_coin={}
        info.asset_to_sz_decimals={}
        info.set_perp_meta(deepcopy(client.metadata),100000+10000*client.dex_index)
        exchange.wallet=signer
        exchange.vault_address=None
        exchange.account_address=sink.team_address
        exchange.info=info
        exchange.expires_after=None
    else:
        exchange=GuardedExchange(signer,TESTNET_API_URL,account_address=sink.team_address,
                                 spot_meta={'universe':[],'tokens':[]},perp_dexs=[client.api_dex],timeout=10)

    for base, name in api_markets.items():
        spec = client.market(name)
        if (exchange.info.name_to_asset(name)!=spec.asset_id or
                exchange.info.asset_to_sz_decimals.get(spec.asset_id)!=spec.size_decimals):
            raise ExchangeError('SDK_MARKET_MAPPING_MISMATCH')
    # Hide every inactive/other SDK market, including native and PAR markets.
    exchange.info.coin_to_asset = {name: client.market(name).asset_id for name in api_markets.values()}
    exchange.info.name_to_coin = {name: name for name in api_markets.values()}
    exchange.info.asset_to_sz_decimals = {
        client.market(name).asset_id: client.market(name).size_decimals for name in api_markets.values()}
    if set(exchange.info.coin_to_asset) != set(api_markets.values()):
        raise ExchangeError('SDK_ACTIVE_MARKET_MAPPING_MISMATCH')
    return exchange

class OfficialSDKTransport:
    is_offline=False

    @staticmethod
    def _require_venue(client, authorization):
        _require_pas_market_mapping(client)
        from .execution_safety import LiveAuthorization
        from .hyperliquid_client import RequestsInfoTransport
        if (type(authorization) is not LiveAuthorization
                or authorization.venue_identity != SCORED.identity
                or not isinstance(getattr(client, 'transport', None), RequestsInfoTransport)):
            raise ExchangeError('SIGNED_VENUE_PAS_AUTHORIZATION_REQUIRED')
        return True

    def __init__(self,client,signer,team_address,nonce_manager,authorization,*,rate_limits):
        self._require_venue(client,authorization)
        from .live_readiness import valid_address
        from eth_account.signers.local import LocalAccount
        if not isinstance(signer,LocalAccount):
            raise ExchangeError('API_WALLET_LOCAL_SIGNER_REQUIRED')
        if not client.ready or not valid_address(team_address) or not valid_address(getattr(signer,'address',None)):
            raise ExchangeError('VERIFIED_SIGNING_IDENTITIES_REQUIRED')
        if signer.address.lower()==team_address.lower() or nonce_manager.signer_address!=signer.address.lower():
            raise ExchangeError('API_WALLET_IDENTITY_MISMATCH')
        self.client=client
        self.team_address=team_address
        self.signer_address=signer.address
        self.nonces=nonce_manager
        self.authorization=authorization
        self.rate_limits=rate_limits
        self._lock=threading.RLock()
        self._expected=None
        self._guard=None
        # Constructor metadata queries are public reads, not exchange actions.
        rate_limits.reserve_info('perpDexs')
        rate_limits.reserve_info('meta')
        self._sdk=build_exchange(signer,client,nonce_manager,self)
        from .single_position_guard import AccountExecutionLease
        try:
            self.account_lease=AccountExecutionLease(team_address)
        except Exception:
            self._sdk.session.close()
            self._sdk.info.session.close()
            raise

    def __repr__(self):
        return '<OfficialSDKTransport testnet:' + ('verified-PAS-BTC-EWY' if getattr(self.client,'competition_mode',False) else 'BLOCKED') + ' signer=[PRIVATE]>'

    def check(self, action):
        self._require_venue(self.client,self.authorization)
        if self._expected is None or self._guard is None or fingerprint(action)!=self._expected:
            raise ExchangeError('UNVALIDATED_SIGNED_ACTION')
        if action.get('type') not in {'order','cancel','cancelByCloid','batchModify','updateLeverage'}:
            raise ExchangeError('ACCOUNT_ADMINISTRATION_PROHIBITED')
        self.authorization.require(self.team_address,self.signer_address)
        self.account_lease.require()
        from .compliance_guard import ActionPermit
        if type(self._guard) is not ActionPermit:
            raise ExchangeError('COMPLIANCE_ACTION_PERMIT_REQUIRED')
        self._guard.require(self, action)

    def transmit(self, payload):
        self.check(payload['action'])
        # No SDK debug logger and no automatic HTTP retries or redirects.
        record=getattr(self,'record_transport_boundary',None)
        if record:record('HTTP_POST_STARTED',payload)
        self.audit_boundary('DISPATCHED',payload)
        try:
            response=self._sdk.session.post(TESTNET_API_URL+'/exchange',json=payload,timeout=10,allow_redirects=False)
        except Exception as exc:
            if record:record('HTTP_POST_UNCERTAIN',payload,error_type=type(exc).__name__)
            raise
        if record:record('HTTP_POST_RESPONSE',payload,status_code=response.status_code)
        self.audit_boundary('ACKNOWLEDGED',payload,http_status=response.status_code,
                            acceptance_verified=False)
        if response.status_code!=200:
            error=ExchangeError('EXCHANGE_HTTP_RESPONSE_UNCERTAIN')
            error.status_code=response.status_code
            raise error
        return response.json()

    def audit_boundary(self, stage, payload, **details):
        journal=getattr(getattr(self,'authorization',None),'journal',None)
        if journal is None:return
        action=payload.get('action',{})
        wires=action.get('orders',[])+[m['order'] for m in action.get('modifies',[]) if 'order' in m]
        for wire in wires:
            if wire.get('c'):
                journal.audit_stage(wire['c'],stage,self.client.clock_ms(),source='GUARDED_SDK_TRANSPORT',
                    nonce=payload.get('nonce'),action_hash=fingerprint(payload['action']),
                    expires_ms=payload.get('expiresAfter'),**details)

    def perform(self, method, args, kwargs, expected_action, guard):
        with self._lock:
            if type(self) is not OfflineSDKTransport:
                self.authorization.require(self.team_address,self.signer_address)
            from .compliance_guard import ActionPermit
            if type(guard) is not ActionPermit:
                raise ExchangeError('COMPLIANCE_ACTION_PERMIT_REQUIRED')
            if method not in {'order','modify_order','cancel','cancel_by_cloid','update_leverage'}:
                raise ExchangeError('ACCOUNT_ADMINISTRATION_PROHIBITED')
            guard.require(self, expected_action)
            self._expected=fingerprint(expected_action)
            self._guard=guard
            self._current_action=expected_action
            try:
                return getattr(self._sdk,method)(*args,**kwargs)
            finally:
                self._expected=self._guard=None
                self._current_action=None
                guard.active=False
                guard.guard._permits.pop(id(guard),None)

    def order_action(self,request,cloid,*,order_type=None):
        from hyperliquid.utils.types import Cloid
        from hyperliquid.utils.signing import order_request_to_order_wire,order_wires_to_order_action
        row=dict(coin=request.symbol,is_buy=request.side=='BUY',sz=sdk_number(request.quantity),
                 limit_px=sdk_number(request.price),order_type=order_type or {'limit':{'tif':request.tif}},
                 reduce_only=request.reduce_only,cloid=Cloid.from_str(cloid))
        wire=order_request_to_order_wire(row,self.client.market(request.symbol).asset_id)
        return row,order_wires_to_order_action([wire])

    def close(self):
        lease=getattr(self,'account_lease',None)
        if lease is not None:
            lease.close()
        self._sdk.session.close()
        self._sdk.info.session.close()


class OfflineSDKTransport(OfficialSDKTransport):
    """Concrete in-memory signed fixture; its sink has no HTTP exchange method."""
    is_offline=True
    def __init__(self,client,signer,team_address,nonce_manager,responses):
        self.client=client
        self.team_address=team_address
        self.signer_address=signer.address
        self.nonces=nonce_manager
        self.responses=list(deepcopy(responses))
        self.signed_payloads=[]  # Private test memory only, never exported.
        self._lock=threading.RLock()
        self._expected=self._guard=None
        if signer.address.lower()==team_address.lower() or nonce_manager.signer_address!=signer.address.lower():
            raise ExchangeError('API_WALLET_IDENTITY_MISMATCH')
        self._sdk=build_exchange(signer,client,nonce_manager,self,offline=True)

    def check(self,action):
        if self._expected is None or self._guard is None or fingerprint(action)!=self._expected:
            raise ExchangeError('UNVALIDATED_SIGNED_FIXTURE_ACTION')
        from .compliance_guard import ActionPermit
        if type(self._guard) is not ActionPermit or action.get('type') not in {'order','cancel','cancelByCloid','batchModify','updateLeverage'}:
            raise ExchangeError('COMPLIANCE_ACTION_PERMIT_REQUIRED')
        self._guard.require(self, action)

    def transmit(self,payload):
        self.check(payload['action'])
        self.signed_payloads.append(deepcopy(payload))
        if not self.responses:
            raise TimeoutError('OFFLINE_RESPONSE_UNCERTAIN')
        result=self.responses.pop(0)
        if isinstance(result,dict) and result.get('fixture_timeout'):
            raise TimeoutError('OFFLINE_RESPONSE_UNCERTAIN')
        return result

    def __repr__(self):
        return '<OfflineSDKTransport no exchange network sink signer=[PRIVATE]>'
