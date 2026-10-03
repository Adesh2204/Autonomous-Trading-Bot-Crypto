"""One pre-trade validator shared by every signed entry, replacement and close."""
from dataclasses import dataclass, asdict
from decimal import Decimal

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .order_lifecycle import OrderRequest


@dataclass(frozen=True)
class RiskPermission:
    candidate_id: str
    symbol: str
    side: str
    maximum_quantity: Decimal
    issued_ms: int
    reduce_only: bool = False
    reason: str | None = None
    limit_price: Decimal | None = None

    @classmethod
    def from_decision(cls, decision, request, candidate_id, now_ms):
        if decision.allowed is not True or request.quantity > decision.quantity:
            raise ExchangeError('RISK_PERMISSION_DENIED')
        return cls(candidate_id, request.symbol, request.side, decision.quantity, now_ms,
                   limit_price=request.price)


@dataclass(frozen=True)
class ValidationContext:
    spec: object
    metadata_hash: str
    expected_metadata_hash: str
    metadata_ms: int
    quote: object
    readiness: object
    positions: dict
    open_orders: tuple
    active_asset: dict
    account_ms: int
    limits: dict
    contexts: dict
    feed_ready: bool
    leverage: int = 1


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    code: str
    reason: str
    checked_ms: int
    normalized: object | None = None
    audit: dict | None = None


class HyperliquidOrderValidator:
    def __init__(self, client, *, policy_leverage=1):
        self.client = client
        self.policy_leverage = policy_leverage

    def validate(self, request, context, permission, now_ms):
        audit = dict(symbol=getattr(request,'symbol',None),requested_size=str(getattr(request,'quantity',None)),
                     requested_price=str(getattr(request,'price',None)),leverage=context.leverage,
                     metadata_hash=context.metadata_hash)
        def reject(code, reason=None):
            return ValidationResult(False, code, reason or code, now_ms, audit=audit)
        try:
            if not isinstance(request, OrderRequest) or not request.symbol.startswith('par:'):
                return reject('INVALID_MARKET')
            if not self.client.ready or request.symbol not in self.client.markets:
                return reject('INVALID_MARKET')
            spec = self.client.market(request.symbol)
            if spec != context.spec or context.metadata_hash != context.expected_metadata_hash:
                return reject('MARKET_METADATA_CHANGED')
            if not 0 <= now_ms-context.metadata_ms <= 60000:
                return reject('STALE_METADATA')
            if request.side not in {'BUY','SELL'}:
                return reject('INVALID_SIDE')
            if request.order_type != 'LIMIT' or request.tif not in {'Gtc','Ioc','Alo'}:
                return reject('INVALID_ORDER_TYPE')
            quantity = spec.normalize_size(request.quantity)
            price = spec.normalize_price(request.price, request.side)
            if quantity <= 0 or quantity % spec.size_step:
                return reject('INVALID_SIZE')
            notional = quantity*price
            audit.update(normalized_size=str(quantity),normalized_price=str(price),notional=str(notional),
                         asset_id=spec.asset_id)
            if notional < 10:
                return reject('MIN_ORDER_NOTIONAL')
            q = context.quote
            if q.symbol != request.symbol or not context.feed_ready:
                return reject('DATA_NOT_READY')
            if not 0 <= now_ms-q.timestamp_ms <= 5000 or q.mark_timestamp_ms is None or not 0 <= now_ms-q.mark_timestamp_ms <= 60000:
                return reject('STALE_MARKET_DATA')
            reference = decimal(q.oracle, positive=True)
            deviation = abs(price-reference)/reference
            audit.update(relevant_reference_price=str(reference),deviation_percentage=str(deviation*100))
            if deviation > Decimal('0.8'):
                return reject('PRICE_BAND_VIOLATION')
            if request.tif == 'Alo' and (request.side == 'BUY' and price >= q.ask or request.side == 'SELL' and price <= q.bid):
                return reject('POST_ONLY_WOULD_CROSS')
            if (type(context.leverage) is not int or context.leverage < 1 or
                    context.leverage > spec.maximum_leverage_at(notional) or context.leverage != self.policy_leverage):
                return reject('INVALID_LEVERAGE')
            if not context.readiness.account_ready or not 0 <= now_ms-context.readiness.observed_ms <= 5000:
                return reject('ACCOUNT_NOT_READY')
            if context.readiness.agent_expiry_ms is None or context.readiness.agent_expiry_ms <= now_ms:
                return reject('API_WALLET_NOT_APPROVED')
            if not 0 <= now_ms-context.account_ms <= 5000:
                return reject('STALE_ACCOUNT_STATE')
            if (not isinstance(permission,RiskPermission) or not permission.candidate_id or
                    permission.symbol!=request.symbol or permission.side!=request.side or
                    permission.reduce_only!=request.reduce_only or quantity>permission.maximum_quantity or
                    not 0<=now_ms-permission.issued_ms<=5000):
                return reject('RISK_PERMISSION_DENIED')
            audit.update(candidate_id=permission.candidate_id,side=request.side,
                         strategy_setup=request.strategy_id,reduce_only=request.reduce_only)
            if permission.limit_price is None or (request.side=='BUY' and price>permission.limit_price or
                                                 request.side=='SELL' and price<permission.limit_price):
                return reject('RISK_PRICE_PERMISSION_DENIED')
            held = context.positions.get(request.symbol)
            held_size = held.quantity if held else Decimal(0)
            if request.reduce_only:
                if (not held_size or (held_size>0)==(request.side=='BUY') or quantity>abs(held_size) or
                        not permission.reason):
                    return reject('REDUCE_ONLY_VIOLATION')
            else:
                active = context.active_asset
                if active.get('user','').lower()!=context.readiness.team_address.lower() or active.get('coin')!=request.symbol:
                    return reject('ACCOUNT_IDENTITY_MISMATCH')
                lev = active.get('leverage',{})
                if lev.get('type')!='cross' or lev.get('value')!=context.leverage:
                    return reject('INVALID_LEVERAGE')
                idx = 0 if request.side=='BUY' else 1
                try:
                    max_size=decimal(active['maxTradeSzs'][idx],nonnegative=True)
                    buying_power=decimal(active['availableToTrade'][idx],nonnegative=True)
                except (KeyError,IndexError,TypeError):
                    return reject('MARGIN_UNAVAILABLE')
                if quantity>max_size or notional/context.leverage>buying_power:
                    return reject('INSUFFICIENT_MARGIN')
                signed=quantity if request.side=='BUY' else -quantity
                increase=max(Decimal(0),abs(held_size+signed)-abs(held_size))
                limits=context.limits
                caps=dict(limits['coinToOiCap'])
                # The raw limits schema names coins with or without the DEX prefix.
                cap=decimal(caps.get(request.symbol,caps.get(request.symbol.split(':')[1])),positive=True)
                current=decimal(context.contexts[request.symbol]['openInterest'],nonnegative=True)
                size_cap=decimal(limits['oiSzCapPerPerp'],positive=True)
                total_cap=decimal(limits['totalOiCap'],positive=True)
                total=sum((decimal(c['openInterest'],nonnegative=True)*decimal(c['oraclePx'],positive=True)
                           for c in context.contexts.values()),Decimal(0))
                audit.update(current_open_interest_notional=str(current*reference),
                             open_interest_cap=str(cap),proposed_exposure_increase=str(increase*reference))
                if increase and (current+increase>size_cap or (current+increase)*reference>cap or
                                 total+increase*reference>total_cap):
                    return reject('OPEN_INTEREST_CAPACITY')
            for own in context.open_orders:
                if own['coin']!=request.symbol:
                    continue
                opposite = own.get('side') == ('A' if request.side=='BUY' else 'B')
                if opposite:
                    own_price=decimal(own['limitPx'],positive=True)
                    if request.side=='BUY' and price>=own_price or request.side=='SELL' and price<=own_price:
                        return reject('SELF_CROSS_PROHIBITED')
            normalized=spec.normalize_order(request.side,quantity,price,reduce_only=request.reduce_only,tif=request.tif)
            return ValidationResult(True,'ALLOWED','All pre-trade checks passed',now_ms,normalized,audit)
        except ExchangeError as exc:
            message=str(exc)
            return reject('INVALID_SIZE' if message in {'SIZE_BELOW_LOT','INVALID_SIZE'} else
                          'INVALID_PRICE' if message=='PRICE_BELOW_PRECISION' else 'EXCHANGE_RULE_DATA_INVALID')
        except (KeyError,TypeError,ValueError,AttributeError):
            return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')


class LiveContextProvider:
    """Fresh public/team-address inputs; no account buying-power estimate from spot total."""
    def __init__(self, market, account, signer_address, clock_health, rate_limits, *,
                 reconciliation_ready, feed_ready, policy_leverage=1):
        self.market=market
        self.account=account
        self.client=account.client
        self.signer_address=signer_address
        self.clock_health=clock_health
        self.rate_limits=rate_limits
        self.reconciliation_ready=reconciliation_ready
        self.feed_ready=feed_ready
        self.policy_leverage=policy_leverage
        self.metadata_hash=fingerprint(self.client.metadata)

    def load(self, request):
        from .live_readiness import verify_live_account_readiness
        from .hyperliquid_market_data import make_quote
        sent=self.client.clock_ms()
        book=self.market.get_orderbook(request.symbol)
        received=self.client.clock_ms()
        self.clock_health.observe(book.timestamp_ms,sent,received)
        metadata,values=self.client.post_info('metaAndAssetCtxs')
        self.client.validate_metadata(metadata)
        current_hash=fingerprint(metadata)
        if current_hash!=self.metadata_hash:
            raise ExchangeError('MARKET_METADATA_CHANGED')
        self.client.metadata_timestamp_ms=self.client.clock_ms()
        if len(values)!=len(metadata['universe']):
            raise ExchangeError('ASSET_CONTEXT_COUNT_MISMATCH')
        contexts={row['name']:value for row,value in zip(metadata['universe'],values)
                  if not row.get('isDelisted')}
        quote=make_quote(book,contexts[request.symbol],self.client.clock_ms(),
                         mark_timestamp_ms=self.client.clock_ms())
        readiness=verify_live_account_readiness(self.account,self.signer_address,
            clock_health=self.clock_health,rate_limits=self.rate_limits,
            reconciliation_ready=self.reconciliation_ready())
        positions=self.account.get_positions()
        orders=tuple(self.account.get_open_orders())
        active=self.account._query('activeAssetData',coin=request.symbol)
        account_ms=self.client.clock_ms()
        limits={} if request.reduce_only else self.client.post_info('perpDexLimits')
        return ValidationContext(self.client.market(request.symbol),current_hash,self.metadata_hash,
            self.client.metadata_timestamp_ms,quote,readiness,positions,orders,active,account_ms,
            limits,contexts,bool(self.feed_ready()),self.policy_leverage)
