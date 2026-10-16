"""Pinned official SDK serialization/signing with a guarded testnet-only sink."""
from copy import deepcopy
from importlib.metadata import version
import threading

from .base_exchange import ExchangeError, decimal_string
from .execution_journal import fingerprint
from .hyperliquid_client import TESTNET_API_URL

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


def build_exchange(signer,client,nonce_manager,sink,*,offline=False):
    """Offline construction reproduces inspected SDK fields without a REST request.

    The production branch invokes Exchange's official constructor with par only.
    Both branches execute the same official order/cancel/modify/leverage methods.
    """
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
            signature=sign_l1_action(self.wallet,action,None,nonce,None,False)
            payload=dict(action=action,nonce=nonce,signature=signature,vaultAddress=None,expiresAfter=None)
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
                                 spot_meta={'universe':[],'tokens':[]},perp_dexs=['par'],timeout=10)
    for name,spec in client.markets.items():
        if (exchange.info.name_to_asset(name)!=spec.asset_id or
                exchange.info.asset_to_sz_decimals[spec.asset_id]!=spec.size_decimals):
            raise ExchangeError('SDK_MARKET_MAPPING_MISMATCH')
    if any(not name.startswith('par:') for name in exchange.info.coin_to_asset):
        raise ExchangeError('SDK_NATIVE_MARKETS_PROHIBITED')
    return exchange


class OfficialSDKTransport:
    is_offline=False
    def __init__(self,client,signer,team_address,nonce_manager,authorization,*,rate_limits):
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
        return '<OfficialSDKTransport testnet:par signer=[PRIVATE]>'

    def check(self, action):
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
        response=self._sdk.session.post(TESTNET_API_URL+'/exchange',json=payload,timeout=10,allow_redirects=False)
        if response.status_code!=200:
            error=ExchangeError('EXCHANGE_HTTP_RESPONSE_UNCERTAIN')
            error.status_code=response.status_code
            raise error
        return response.json()

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
