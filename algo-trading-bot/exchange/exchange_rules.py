"""One pre-trade validator shared by every signed entry, replacement and close."""
from dataclasses import dataclass, asdict
from decimal import Decimal

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .order_lifecycle import OrderRequest
from .competition_market import (COMPETITION_MARKET_OI_CAP_USD, COMPETITION_DEX_OI_CAP_USD,
                                INTERNAL_OI_HEADROOM_FRACTION, PAS_TARGET_LEVERAGE,
                                is_scored_phase)


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
    provenance: object | None = None

    @classmethod
    def from_decision(cls, decision, request, candidate_id, now_ms, *, signal_timestamp_ms=None,
                      setup_type=None):
        if decision.allowed is not True or request.quantity > decision.quantity:
            raise ExchangeError('RISK_PERMISSION_DENIED')
        from .compliance_guard import OrderProvenance
        provenance = (OrderProvenance(candidate_id, request.strategy_id, setup_type,
            signal_timestamp_ms, request.symbol, request.side, 'FROZEN_VWAP_SIGNAL_AND_BASELINE_RISK',
            asdict(decision), dict(allowed=True, quantity=str(request.quantity), price=str(request.price),
                                 order_type=request.order_type, tif=request.tif))
            if signal_timestamp_ms is not None and setup_type is not None else None)
        return cls(candidate_id, request.symbol, request.side, decision.quantity, now_ms,
                   limit_price=request.price, provenance=provenance)


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
    fills: tuple = ()
    reconciled: bool = True
    oracle_ms: int | None = None
    dex_total_oi_notional: Decimal | None = None
    dex_oi_observed_ms: int | None = None
    journal_only_entry_pending: bool = False


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    code: str
    reason: str
    checked_ms: int
    normalized: object | None = None
    audit: dict | None = None


class HyperliquidOrderValidator:
    def __init__(self, client, *, policy_leverage=None):
        self.client = client
        if policy_leverage is None:
            policy_leverage = (PAS_TARGET_LEVERAGE if getattr(client, 'competition_mode', False) else 1)
        self.policy_leverage = policy_leverage

    def validate(self, request, context, permission, now_ms, *, operation='ORDER'):
        audit = dict(symbol=getattr(request,'symbol',None),requested_size=str(getattr(request,'quantity',None)),
                     requested_price=str(getattr(request,'price',None)),leverage=context.leverage,
                     metadata_hash=context.metadata_hash)
        def reject(code, reason=None):
            return ValidationResult(False, code, reason or code, now_ms, audit=audit)
        try:
            from .full_position_close import FULL_POSITION_CLOSE, normalize_exact_full_close
            if operation not in {'ORDER', FULL_POSITION_CLOSE}:
                return reject('INVALID_EXECUTION_OPERATION')
            if not isinstance(request, OrderRequest):
                return reject('INVALID_MARKET')
            journal_pending = getattr(context, 'journal_only_entry_pending', False)
            if type(journal_pending) is not bool:
                return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
            if not request.reduce_only and journal_pending:
                return reject('UNRESOLVED_JOURNAL_ENTRY_NOT_VISIBLE')
            if getattr(self.client, 'competition_mode', False):
                api_markets=getattr(self.client,'api_markets',None)
                if (not isinstance(api_markets,dict) or set(api_markets)!={'BTC','EWY'} or
                        api_markets.get('BTC')!=self.client.api_market or
                        any(not isinstance(symbol,str) or not symbol.endswith(':'+base)
                            for base,symbol in api_markets.items()) or
                        request.symbol not in set(api_markets.values())):
                    return reject('INVALID_MARKET')
            elif not request.symbol.startswith(getattr(self.client, 'dex', 'par') + ':'):
                return reject('INVALID_MARKET')
            if not self.client.ready or request.symbol not in self.client.markets:
                return reject('INVALID_MARKET')
            spec = self.client.market(request.symbol)
            if spec != context.spec or context.metadata_hash != context.expected_metadata_hash:
                return reject('MARKET_METADATA_CHANGED')
            if not 0 <= now_ms-context.metadata_ms <= 60000:
                return reject('STALE_METADATA')
            if not request.reduce_only and getattr(self.client, 'competition_mode', False) and not is_scored_phase(now_ms):
                return reject('OUTSIDE_SCORED_PHASE')
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
            exact_close = None
            if operation == FULL_POSITION_CLOSE:
                try:
                    exact_close, scope = normalize_exact_full_close(spec, request, context, now_ms)
                except ExchangeError as exc:
                    return reject(str(exc))
                audit.update(exact_full_position_close=True, subminimum_close_scope=scope,
                             closing_exception_applied=scope is not None)
            if notional < 10 and exact_close is None:
                return reject('MIN_ORDER_NOTIONAL')
            q = context.quote
            if q.symbol != request.symbol or not context.feed_ready:
                return reject('DATA_NOT_READY')
            if not 0 <= now_ms-q.timestamp_ms <= 5000 or q.mark_timestamp_ms is None or not 0 <= now_ms-q.mark_timestamp_ms <= 60000:
                return reject('STALE_MARKET_DATA')
            # Organizer clarification: the 80% order band uses markPx. Oracle
            # remains the separate reference for open-interest notional below.
            reference = decimal(q.mark, positive=True)
            oracle_reference = decimal(q.oracle, positive=True)
            deviation = abs(price-reference)/reference
            audit.update(relevant_reference_price=str(reference),reference_price_source='markPx',
                         oracle_price=str(oracle_reference),deviation_percentage=str(deviation*100))
            if deviation > Decimal('0.8'):
                return reject('PRICE_BAND_VIOLATION')
            if request.tif == 'Alo' and (request.side == 'BUY' and price >= q.ask or request.side == 'SELL' and price <= q.bid):
                return reject('POST_ONLY_WOULD_CROSS')
            expected_leverage = (PAS_TARGET_LEVERAGE if getattr(self.client, 'competition_mode', False)
                                 else self.policy_leverage)
            if (self.policy_leverage != expected_leverage or type(context.leverage) is not int or
                    context.leverage < 1 or context.leverage > spec.maximum_leverage_at(notional) or
                    context.leverage != expected_leverage):
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
            # Preserve the independent self-cross rule even for minimal synthetic
            # contexts whose open-order rows omit OI reservation fields.
            for own in context.open_orders:
                if own['coin']!=request.symbol:
                    continue
                if own.get('isTrigger') is True:
                    continue  # dormant conditional orders cannot cross the current book
                opposite = own.get('side') == ('A' if request.side=='BUY' else 'B')
                if opposite:
                    own_price=decimal(own['limitPx'],positive=True)
                    if request.side=='BUY' and price>=own_price or request.side=='SELL' and price<=own_price:
                        return reject('SELF_CROSS_PROHIBITED')
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
                raw_caps=limits['coinToOiCap']
                if isinstance(raw_caps,dict):
                    caps=raw_caps
                elif isinstance(raw_caps,list):
                    caps={}
                    for pair in raw_caps:
                        if (not isinstance(pair,(list,tuple)) or len(pair)!=2 or
                                not isinstance(pair[0],str) or not pair[0] or pair[0] in caps):
                            return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                        caps[pair[0]]=pair[1]
                else:
                    return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                # The raw limits schema names coins with or without the DEX prefix.
                aliases=(request.symbol,request.symbol.split(':',1)[1])
                cap_values=[decimal(caps[name],positive=True) for name in aliases if name in caps]
                if not cap_values or any(value!=cap_values[0] for value in cap_values[1:]):
                    return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                cap=cap_values[0]
                competition_mode=getattr(self.client, 'competition_mode', False)
                if competition_mode:
                    # The identity gate above restricts this path to BTC/EWY.
                    cap=min(cap,Decimal(COMPETITION_MARKET_OI_CAP_USD))
                current=decimal(context.contexts[request.symbol]['openInterest'],nonnegative=True)
                size_cap=decimal(limits['oiSzCapPerPerp'],positive=True)
                api_total_cap=decimal(limits['totalOiCap'],positive=True)
                if getattr(self.client, 'competition_mode', False):
                    total_cap=min(api_total_cap,Decimal(COMPETITION_DEX_OI_CAP_USD))
                    if (context.dex_total_oi_notional is None or context.dex_oi_observed_ms is None or
                            not 0<=now_ms-context.dex_oi_observed_ms<=5000):
                        return reject('DEX_OI_AGGREGATE_STALE_OR_UNVERIFIED')
                    total=decimal(context.dex_total_oi_notional,nonnegative=True)
                else:
                    total_cap=api_total_cap
                    total=sum((decimal(c['openInterest'],nonnegative=True)*
                               decimal(c['oraclePx'],positive=True)
                               for c in context.contexts.values()),Decimal(0))
                # openOrders/frontendOpenOrders are the authoritative current
                # reservations. Count each non-reduce-only order once, even if
                # the same order is repeated under its oid/cloid in a batch view.
                reserved_by_symbol={}
                reserved_dex_notional=Decimal(0)
                seen_order_ids={}
                for own in context.open_orders:
                    coin=own['coin']
                    reduce_only=own.get('reduceOnly',False)
                    if type(reduce_only) is not bool:
                        return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                    if reduce_only:
                        continue
                    side=own['side']
                    if side not in {'B','A'}:
                        return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                    reserved_size=decimal(own['sz'],positive=True)
                    identity=tuple((name,str(own[name])) for name in ('oid','cloid')
                                   if own.get(name) is not None)
                    if not identity:
                        return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                    signature=(coin,side,reserved_size,reduce_only,
                               str(own.get('limitPx')),own.get('isTrigger',False))
                    prior_signatures=[seen_order_ids[name] for name in identity if name in seen_order_ids]
                    if prior_signatures:
                        if any(value!=signature for value in prior_signatures):
                            return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                        continue
                    for name in identity:
                        seen_order_ids[name]=signature
                    if coin not in context.contexts:
                        return reject('EXCHANGE_RULE_DATA_UNAVAILABLE')
                    reserved_by_symbol[coin]=reserved_by_symbol.get(coin,Decimal(0))+reserved_size
                    reserve_oracle=decimal(context.contexts[coin]['oraclePx'],positive=True)
                    reserved_dex_notional+=reserved_size*reserve_oracle
                reserved_symbol=reserved_by_symbol.get(request.symbol,Decimal(0))
                total+=reserved_dex_notional
                headroom=INTERNAL_OI_HEADROOM_FRACTION if competition_mode else Decimal(0)
                available_fraction=Decimal(1)-headroom
                market_entry_limit=cap*available_fraction
                size_entry_limit=size_cap*available_fraction
                dex_entry_limit=total_cap*available_fraction
                projected_size=current+reserved_symbol+increase
                projected_market=projected_size*oracle_reference
                projected_dex=total+increase*oracle_reference
                audit.update(current_open_interest_notional=str(current*oracle_reference),
                             open_interest_cap=str(cap),dex_open_interest_notional=str(total),
                             dex_open_interest_cap=str(total_cap),
                             proposed_exposure_increase=str(increase*oracle_reference),
                             reserved_open_order_quantity=str(reserved_symbol),
                             reserved_open_order_dex_notional=str(reserved_dex_notional),
                             symbol_oi_cap=str(cap),dex_oi_cap=str(total_cap),
                             oi_headroom_fraction=str(headroom),
                             symbol_oi_entry_limit=str(market_entry_limit),
                             symbol_oi_size_entry_limit=str(size_entry_limit),
                             dex_oi_entry_limit=str(dex_entry_limit),
                             projected_symbol_oi_notional=str(projected_market),
                             projected_dex_oi_notional=str(projected_dex))
                # Competition entries must stay STRICTLY below the buffered
                # ceilings. Preserve historical offline protocol semantics.
                exhausted=(projected_size>=size_entry_limit or
                           projected_market>=market_entry_limit or
                           projected_dex>=dex_entry_limit) if competition_mode else (
                           projected_size>size_entry_limit or
                           projected_market>market_entry_limit or
                           projected_dex>dex_entry_limit)
                if increase and exhausted:
                    return reject('OPEN_INTEREST_CAPACITY')
            normalized=exact_close or spec.normalize_order(request.side,quantity,price,reduce_only=request.reduce_only,tif=request.tif)
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

    def load(self, request, *, critical=False):
        from .live_readiness import verify_live_account_readiness
        from .hyperliquid_market_data import make_quote
        if getattr(self.client,'competition_mode',False):
            api_markets=getattr(self.client,'api_markets',None)
            if (not isinstance(api_markets,dict) or set(api_markets)!={'BTC','EWY'} or
                    api_markets.get('BTC')!=self.client.api_market or
                    set(api_markets.values())!=set(self.client.markets) or
                    any(not isinstance(symbol,str) or not symbol.endswith(':'+base)
                        for base,symbol in api_markets.items())):
                raise ExchangeError('PAS_ACTIVE_MARKET_MAPPING_UNVERIFIED')
        sent=self.client.clock_ms()
        book=self.market.get_orderbook(request.symbol)
        received=self.client.clock_ms()
        if not hasattr(self.market,'engine'):
            self.clock_health.observe(book.timestamp_ms,sent,received)
        elif not self.clock_health.healthy:
            from .hyperliquid_market_data import HyperliquidMarketData
            sent=self.client.clock_ms()
            reference=HyperliquidMarketData(self.client).get_orderbook(request.symbol)
            self.clock_health.observe(reference.timestamp_ms,sent,self.client.clock_ms())
        metadata,values=self.client.post_info('metaAndAssetCtxs')
        self.client.validate_metadata(metadata)
        metadata=self.client._canonical_metadata(metadata, self.client.api_dex or getattr(self.client, 'dex', 'par'))
        current_hash=fingerprint(metadata)
        if current_hash!=self.metadata_hash:
            raise ExchangeError('MARKET_METADATA_CHANGED')
        self.client.metadata_timestamp_ms=self.client.clock_ms()
        if len(values)!=len(metadata['universe']):
            raise ExchangeError('ASSET_CONTEXT_COUNT_MISMATCH')
        contexts={}
        dex_total_oi=decimal(0)
        for row,value in zip(metadata['universe'],values):
            if not isinstance(row,dict) or not isinstance(value,dict):
                raise ExchangeError('ASSET_CONTEXT_INVALID')
            symbol=row['name']
            if row.get('isDelisted'):
                if (getattr(self.client, 'competition_mode', False) and
                        symbol in set(self.client.api_markets.values())):
                    raise ExchangeError('PAS_ACTIVE_MARKET_DELISTED')
                if not getattr(self.client, 'competition_mode', False) and symbol==request.symbol:raise ExchangeError('MARKET_DELISTED')
                continue
            try:
                oi=decimal(value['openInterest'],nonnegative=True)
                oracle=decimal(value['oraclePx'],positive=True)
            except (KeyError,TypeError,ValueError) as exc:
                raise ExchangeError('DEX_OI_AGGREGATE_UNVERIFIABLE') from exc
            dex_total_oi+=oi*oracle
            if getattr(self.client, 'competition_mode', False):
                if symbol in set(self.client.api_markets.values()):
                    if symbol in contexts:raise ExchangeError('AMBIGUOUS_BTC_ASSET_CONTEXT')
                    contexts[symbol]=value
            else:
                if symbol in contexts:raise ExchangeError('AMBIGUOUS_ASSET_CONTEXT')
                contexts[symbol]=value
        if getattr(self.client, 'competition_mode', False):
            if set(contexts)!=set(self.client.api_markets.values()):
                raise ExchangeError('PAS_ACTIVE_ASSET_CONTEXT_UNAVAILABLE')
        elif request.symbol not in contexts:
            raise ExchangeError('ASSET_CONTEXT_UNAVAILABLE')
        oi_observed=self.client.clock_ms()
        self.client.dex_total_oi_notional=dex_total_oi
        self.client.dex_oi_observed_ms=oi_observed
        self.client.dex_oi_market_count=len(metadata['universe'])
        quote=make_quote(book,contexts[request.symbol],self.client.clock_ms(),
                         mark_timestamp_ms=self.client.clock_ms())
        readiness=verify_live_account_readiness(self.account,self.signer_address,
            clock_health=self.clock_health,rate_limits=self.rate_limits,
            reconciliation_ready=self.reconciliation_ready(),critical=critical)
        positions=self.account.get_positions()
        orders=tuple(self.account.get_frontend_open_orders() if getattr(self,'trigger_aware',False)
                     else self.account.get_open_orders())
        active=self.account._query('activeAssetData',coin=request.symbol)
        fills=tuple(self.account.get_fills(start_ms=max(0,self.client.clock_ms()-300000),
                                          end_ms=self.client.clock_ms()))
        after_positions=self.account.get_positions()
        after_orders=tuple(self.account.get_frontend_open_orders() if getattr(self,'trigger_aware',False)
                           else self.account.get_open_orders())
        position_signature=lambda values:{s:(p.quantity,p.entry_price) for s,p in values.items()}
        order_signature=lambda values:{str(o['oid']):o for o in values}
        if position_signature(positions)!=position_signature(after_positions) or order_signature(orders)!=order_signature(after_orders):
            raise ExchangeError('ACCOUNT_CHANGED_DURING_PREFLIGHT')
        account_ms=self.client.clock_ms()
        limits={} if request.reduce_only else self.client.post_info('perpDexLimits')
        return ValidationContext(self.client.market(request.symbol),current_hash,self.metadata_hash,
            self.client.metadata_timestamp_ms,quote,readiness,positions,orders,active,account_ms,
            limits,contexts,bool(self.feed_ready()) or critical,self.policy_leverage,fills,
            bool(self.reconciliation_ready()),quote.mark_timestamp_ms,dex_total_oi,oi_observed)
