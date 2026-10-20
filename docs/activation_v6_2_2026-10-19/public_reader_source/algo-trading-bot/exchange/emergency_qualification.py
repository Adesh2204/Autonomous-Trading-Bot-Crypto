"""Versioned one-order testnet experiment; no strategy signal or production unlock.

The new P0 policy is separate from the old $25/10%-BBO qualification route.
No stop is submitted. Historical exact-close shapes are evidence, not guarantees.
"""
from dataclasses import dataclass, asdict, replace
from decimal import Decimal as D, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint, ExecutionJournal
from .order_lifecycle import OrderRequest, OrderState
from . import testnet_certification as cert
from .testnet_qualification import (residual_close_assessment, QualificationContextProvider,
    UnverifiedQualificationProtection, require_qualification_regression, whitelist_trade_proof)
from .sdk_transport import OfficialSDKTransport, OfflineSDKTransport
from .hyperliquid_execution import HyperliquidExecution
from .exchange_rules import HyperliquidOrderValidator
from .compliance_guard import ComplianceGuard
from .qualification_watcher import sweep, prior_execution_check

POLICY_VERSION = 'ANCHORIUM_P0_1000_V1'
RULE = 'MINIMUM_VALID_LONG_PUBLIC_L2_OR_REST_AT_BID_V1'
POLICY = dict(version=POLICY_VERSION, network='testnet', dex='par', max_notional='1000',
    minimum_entry_notional='10', leverage=1, margin_mode='cross', one_entry=True,
    max_exit_attempts=2, max_cancel_attempts=1, max_signed_actions=4,
    spread_bps='50', entry_slippage_bps='20', exit_slippage_bps='20',
    mark_oracle_bps='50', mid_oracle_bps='100', order_oracle_bps='150',
    l2_participation='0.5', exit_floor_factor='0.98505', resting_lifetime_seconds=30,
    approval_window_ms=300000, entry_minimum_remaining_ms=90000,
    rule=RULE, protection='UNVERIFIED_NO_STOP_WILL_BE_SUBMITTED')
FIXED_PRICE = 'FIXED_LIMIT_V1'
BOUNDED_PRICE = 'BOUNDED_FRESH_IOC_V2'
BOUNDED_RULE = 'MINIMUM_VALID_LONG_FRESH_IOC_WITHIN_APPROVED_ENVELOPE_V2'
BOUNDED_POLICY = dict(POLICY, version='ANCHORIUM_P0_BOUNDED_IOC_V2',
    rule=BOUNDED_RULE, price_authorization=BOUNDED_PRICE, entry_price_buffer_bps='10',
    quantity_expansion=False, price_cap_expansion=False)
ENVELOPE_FIELDS = ('price_authorization_mode','max_buy_price','quantity_ceiling','entry_notional_ceiling')


def proposal_policy(proposal=None):
    return BOUNDED_POLICY if proposal is not None and proposal.price_authorization_mode==BOUNDED_PRICE else POLICY


def policy_hash(proposal=None):
    return fingerprint(proposal_policy(proposal))


@dataclass(frozen=True)
class EmergencyProposal(cert.CertificationProposal):
    mode: str = 'TESTNET_QUALIFICATION_P0_1000_V1'
    max_notional: str = '1000'
    session_loss_budget: str = '1000'  # Principal allowance, never a guaranteed loss cap.
    max_signed_actions: int = 4
    entry_slippage_bps: str = '20'
    exit_slippage_bps: str = '20'
    entry_rule: str = RULE
    qualification_policy_hash: str = ''
    entry_tif: str = 'Ioc'
    order_lifetime_seconds: int = 0
    candidate_evidence_hash: str = ''
    maker_fee_rate: str = '0'
    protection_status: str = 'UNVERIFIED_NO_STOP_WILL_BE_SUBMITTED'
    price_authorization_mode: str = FIXED_PRICE
    max_buy_price: str | None = None
    quantity_ceiling: str | None = None
    entry_notional_ceiling: str | None = None

    def require(self):
        bounded=self.price_authorization_mode==BOUNDED_PRICE
        expected_mode='TESTNET_QUALIFICATION_P0_BOUNDED_IOC_V2' if bounded else 'TESTNET_QUALIFICATION_P0_1000_V1'
        if (self.price_authorization_mode not in {FIXED_PRICE,BOUNDED_PRICE}
                or self.mode!=expected_mode or self.network!='testnet' or self.dex!='par'
                or self.entry_side!='BUY' or not self.symbol.startswith('par:')
                or self.team_wallet.lower()!=cert.TEAM.lower() or self.api_wallet.lower()!=cert.API.lower()
                or self.entry_rule!=(BOUNDED_RULE if bounded else RULE) or self.qualification_policy_hash!=policy_hash(self)
                or self.protection_status!=POLICY['protection'] or not self.candidate_evidence_hash
                or not self.source_hash or not self.reliability_policy_hash
                or type(self.asset_id) is not int or self.asset_id<100000
                or type(self.observed_ms) is not int or self.observed_ms<0
                or decimal(self.max_notional)!=1000 or decimal(self.session_loss_budget)!=1000
                or type(self.max_exit_attempts) is not int or self.max_exit_attempts!=2
                or type(self.max_signed_actions) is not int or self.max_signed_actions!=4
                or decimal(self.entry_slippage_bps)!=20 or decimal(self.exit_slippage_bps)!=20
                or self.entry_tif not in {'Ioc','Gtc','Alo'}
                or type(self.order_lifetime_seconds) is not int
                or self.order_lifetime_seconds!=(0 if self.entry_tif=='Ioc' else 30)):
            raise ExchangeError('INVALID_P0_QUALIFICATION_PROPOSAL')
        n={k:decimal(getattr(self,k),positive=True) for k in ('quantity','entry_limit','exit_bound',
            'stop_trigger','stop_limit','reference_bid','reference_ask','reference_mark','reference_oracle')}
        decimal(self.taker_fee_rate,nonnegative=True);decimal(self.maker_fee_rate)
        if (not 10<=n['quantity']*n['entry_limit']<=1000
                or n['quantity']*n['reference_mark']>1000
                or not n['stop_limit']==n['exit_bound']<n['stop_trigger']<n['entry_limit']
                or n['reference_ask']<=n['reference_bid']):
            raise ExchangeError('P0_QUALIFICATION_SIZE_OR_GEOMETRY_INVALID')
        if bounded:
            if (self.symbol!='par:BTC' or self.entry_tif!='Ioc'
                    or decimal(self.max_buy_price,positive=True)!=n['entry_limit']
                    or decimal(self.quantity_ceiling,positive=True)!=n['quantity']
                    or decimal(self.entry_notional_ceiling,positive=True)!=n['quantity']*n['entry_limit']
                    or decimal(self.entry_notional_ceiling)>1000):
                raise ExchangeError('P0_INVALID_BOUNDED_PRICE_ENVELOPE')
        elif any(getattr(self,k) is not None for k in ENVELOPE_FIELDS[1:]):
            raise ExchangeError('P0_FIXED_PROPOSAL_CANNOT_REPRICE')
        return self

    @property
    def identity(self):
        self.require()
        data=asdict(self)
        if self.price_authorization_mode==FIXED_PRICE:
            for field in ENVELOPE_FIELDS:data.pop(field)
        return fingerprint(data)  # Byte-identical legacy proposal identity.


@dataclass(frozen=True)
class EmergencyApproval(cert.CertificationApproval):
    qualification_policy_hash: str = ''
    unverified_stop_risk_accepted: bool = False
    l2_and_50bps_qualification_policy_accepted: bool = False
    possible_manual_residual_recovery_accepted: bool = False
    maximum_1000_is_not_loss_guarantee_accepted: bool = False
    one_cancel_two_exits_and_lifetime_accepted: bool = False
    bounded_price_authorization_accepted: bool = False


class EmergencyAuthorization(cert.CertificationAuthorization):
    def require(self, team, signer):
        a=self.approval;p=self.proposal
        if (type(p) is not EmergencyProposal or type(a) is not EmergencyApproval
                or a.qualification_policy_hash!=policy_hash(p)
                or a.bounded_price_authorization_accepted is not (p.price_authorization_mode==BOUNDED_PRICE)
                or not all(getattr(a,k) is True for k in ('unverified_stop_risk_accepted',
                    'l2_and_50bps_qualification_policy_accepted','possible_manual_residual_recovery_accepted',
                    'maximum_1000_is_not_loss_guarantee_accepted','one_cancel_two_exits_and_lifetime_accepted'))):
            raise ExchangeError('EXACT_NEW_P0_POLICY_AND_RESIDUAL_RISK_APPROVAL_REQUIRED')
        super().require(team,signer)
        if self.clock_ms()>=p.observed_ms+POLICY['approval_window_ms']:
            raise ExchangeError('P0_PROPOSAL_EXPIRED')

    def check_action(self, action):
        p=self.proposal;self.require(p.team_wallet,p.api_wallet)
        prefix='certification:'+p.identity+':'
        if action.get('type')=='cancel':
            rows=action.get('cancels',[])
            own=self.journal.intent(prefix+'entry')
            if (len(rows)!=1 or own is None or own['oid'] is None
                    or rows[0].get('a')!=p.asset_id or str(rows[0].get('o'))!=str(own['oid'])):
                raise ExchangeError('P0_CANCEL_ORIGINAL_ENTRY_ONLY')
            return
        if action.get('type')!='order' or len(action.get('orders',[]))!=1:
            raise ExchangeError('P0_ACTION_OUTSIDE_SCOPE')
        w=action['orders'][0]
        row=self.journal.db.execute('SELECT * FROM intents WHERE cloid=?',(w.get('c'),)).fetchone()
        if (row is None or w.get('a')!=p.asset_id or type(w.get('b')) is not bool
                or type(w.get('r')) is not bool or decimal(w.get('s'),positive=True)>decimal(p.quantity)):
            raise ExchangeError('P0_ACTION_OUTSIDE_SCOPE')
        qty,px=decimal(w['s'],positive=True),decimal(w.get('p'),positive=True)
        if not w['r']:
            price_allowed=(px==decimal(p.entry_limit) if p.price_authorization_mode==FIXED_PRICE else
                px<=decimal(p.max_buy_price) and qty<=decimal(p.quantity_ceiling)
                and 10<=qty*px<=decimal(p.entry_notional_ceiling))
            if (row['intent_key']!=prefix+'entry' or w['b'] is not True or qty!=decimal(p.quantity)
                    or not price_allowed or qty*px>1000
                    or w.get('t')!={'limit':{'tif':p.entry_tif}}
                    or self.clock_ms()+POLICY['entry_minimum_remaining_ms']>min(
                        self.approval.expires_ms,p.observed_ms+POLICY['approval_window_ms'])):
                raise ExchangeError('P0_EXACT_ENTRY_OR_RECOVERY_TIME_REQUIRED')
        elif (w['b'] is not False or px<decimal(p.exit_bound)
                or row['intent_key'] not in {prefix+'exit:0',prefix+'exit:1'}
                or w.get('t')!={'limit':{'tif':'Ioc'}}):
            raise ExchangeError('P0_EXACT_REDUCE_ONLY_EXIT_REQUIRED')

    def claim_transmission(self, action):
        self.check_action(action)
        p=self.proposal;key='certification_transmissions:'+p.identity;digest=fingerprint(action)
        entry=action['type']=='order' and action['orders'][0]['r'] is False
        with self.journal.transaction():
            history=self.journal.control(key) or []
            if (len(history)>=4 or any(h['hash']==digest for h in history)
                    or entry and self.journal.control('qualification_entry_consumed')
                    or action['type']=='cancel' and any(h['kind']=='cancel' for h in history)):
                raise ExchangeError('P0_ENTRY_OR_ACTION_ALREADY_CONSUMED')
            if entry:self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                ('qualification_entry_consumed',json.dumps(p.identity)))
            if entry:self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                ('p0_entry_submission_ms',json.dumps(self.clock_ms())))
            history.append(dict(hash=digest,entry=entry,kind=action['type'],timestamp_ms=self.clock_ms()))
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(key,json.dumps(history)))


def inspect_market(spec,book,now_ms,*,tif='Ioc',asset_context=None):
    """Public Stage A only. New 50% L2 policy is NOT old 10%-BBO compliance."""
    if tif not in {'Ioc','Gtc','Alo'}:raise ExchangeError('P0_INVALID_TIF')
    r=dict(symbol=spec.symbol,asset_id=spec.asset_id,size_step=str(spec.size_step),entry_tif=tif,
        potential=False,maximum_notional='1000',protection_verified=False,
        depth_policy='P0_50_PERCENT_OF_GENUINE_L2_WITHIN_APPROVED_PRICES',
        old_10_percent_bbo_passed=False,account_checks_performed=False)
    try:
        if book.symbol!=spec.symbol or not 0<=now_ms-book.timestamp_ms<=5000:
            raise ExchangeError('P0_FRESH_BOOK_REQUIRED')
        if not book.bids or not book.asks:raise ExchangeError('P0_TWO_SIDED_BOOK_REQUIRED')
        for levels,reverse in ((book.bids,True),(book.asks,False)):
            if (any(x.price<=0 or x.quantity<=0 for x in levels)
                    or len({x.price for x in levels})!=len(levels)
                    or tuple(sorted(levels,key=lambda x:x.price,reverse=reverse))!=levels):
                raise ExchangeError('P0_INVALID_BOOK_LEVELS')
        bid,ask=book.bids[0].price,book.asks[0].price
        if ask<=bid:raise ExchangeError('P0_TWO_SIDED_BOOK_REQUIRED')
        spread=(ask-bid)/((ask+bid)/2)*10000
        price=spec.normalize_price(ask*D('1.002') if tif=='Ioc' else bid,'BUY')
        floor=spec.normalize_price(bid*D(POLICY['exit_floor_factor']),'SELL')
        immediate=spec.normalize_price(bid*D('.998'),'SELL')
        qty=(D(10)/price/spec.size_step).to_integral_value(rounding=ROUND_CEILING)*spec.size_step
        entry=sweep(book.asks,qty,price,'BUY');exit=sweep(book.bids,qty,immediate,'SELL')
        residual=residual_close_assessment(spec,qty,floor)
        r.update(exchange_ms=book.timestamp_ms,observed_ms=now_ms,spread_bps=str(spread),bid=str(bid),ask=str(ask),
            minimum_quantity=str(qty),minimum_entry_notional=str(qty*price),minimum_lot_notional=str(spec.size_step*price),
            entry_limit=str(price),exit_floor=str(floor),reviewed_exit_limit=str(immediate),
            maximum_lot_rounded_quantity=str((D(1000)/price//spec.size_step)*spec.size_step),
            residuals=residual,entry_depth=entry,exit_depth=exit,raw_book=asdict(book),
            old_10_percent_bbo_passed=qty<=min(book.bids[0].quantity,book.asks[0].quantity)*D('.1'))
        if spread>50:raise ExchangeError('P0_SPREAD_EXCEEDED')
        if not residual['ready']:raise ExchangeError(residual['blocker'])
        if qty*price>1000:raise ExchangeError('P0_MINIMUM_EXCEEDS_CAP')
        if decimal(exit['available_quantity'])*D('.5')<qty:raise ExchangeError('P0_EXIT_DEPTH_REQUIRED')
        if tif=='Ioc' and decimal(entry['available_quantity'])*D('.5')<qty:
            raise ExchangeError('P0_ENTRY_DEPTH_REQUIRED')
        if tif!='Ioc' and price>=ask:raise ExchangeError('P0_RESTING_PRICE_WOULD_CROSS')
        if asset_context is not None:
            mark,oracle=decimal(asset_context['markPx'],positive=True),decimal(asset_context['oraclePx'],positive=True)
            r.update(mark=str(mark),oracle=str(oracle))
            if (abs(mark-oracle)/oracle*10000>50 or abs((bid+ask)/2-oracle)/oracle*10000>100
                    or abs(price-oracle)/oracle*10000>150 or qty*mark>1000):
                raise ExchangeError('P0_REFERENCE_DIVERGENCE_OR_CAP')
        r['potential']=True
    except (ExchangeError,KeyError,TypeError,ArithmeticError) as exc:
        r['blocker']=str(exc) if isinstance(exc,ExchangeError) else 'P0_INVALID_MARKET_DATA'
    r['evidence_hash']=fingerprint(r)
    return r


class EmergencyContextProvider(QualificationContextProvider):
    """Bind actual full L2 to the final quote; no depth fabricated from BBO."""
    def load(self,request,*,critical=False):
        from .hyperliquid_market_data import make_quote
        context=super().load(request,critical=critical)
        sent=self.client.clock_ms();book=self.market.get_orderbook(request.symbol)
        self.clock_health.observe(book.timestamp_ms,sent,self.client.clock_ms())
        quote=make_quote(book,context.contexts[request.symbol],self.client.clock_ms(),
            mark_timestamp_ms=context.quote.mark_timestamp_ms)
        self.last_book=book
        self.books=getattr(self,'books',{});self.books[request.symbol]=book
        return replace(context,quote=quote)

    def refresh_for_signing(self,request,recovery,own_intent):
        """New network observations, ordered with readiness near the boundary."""
        from .exchange_rules import ValidationContext
        from .live_readiness import verify_live_account_readiness
        from .hyperliquid_market_data import make_quote
        started=self.client.clock_ms()
        self.rate_limits.wait_for_read_budget(450,max_wait_seconds=65,
            cancel_event=self.client.read_cancel_event,wait_ms=lambda ms:self.wait(ms/1000))
        from .testnet_qualification import prime_read_only_clock
        prime_read_only_clock(self.market,self.clock_health,request.symbol)
        report=recovery.recover_for_signing(own_intent) if hasattr(recovery,'recover_for_signing') else recovery.recover()
        if not getattr(recovery,'account_truth_ready',report.ready):
            raise ExchangeError('QUALIFICATION_DURABLE_RECONCILIATION_REQUIRED')
        before=self.account.get_positions();orders=tuple(self.account.get_frontend_open_orders())
        active=self.account._query('activeAssetData',coin=request.symbol)
        fills=tuple(self.account.get_fills(start_ms=max(0,self.client.clock_ms()-300000),end_ms=self.client.clock_ms()))
        limits={} if request.reduce_only else self.client.post_info('perpDexLimits')
        after=self.account.get_positions();after_orders=tuple(self.account.get_frontend_open_orders())
        if before!=after or orders!=after_orders:raise ExchangeError('ACCOUNT_CHANGED_DURING_PREFLIGHT')
        account_ms=self.client.clock_ms()
        readiness=verify_live_account_readiness(self.account,self.signer_address,
            clock_health=self.clock_health,rate_limits=self.rate_limits,
            reconciliation_ready=recovery.account_truth_ready,critical=request.reduce_only)
        metadata,values=self.client.post_info('metaAndAssetCtxs');metadata_ms=self.client.last_received_ms
        self.client.validate_metadata(metadata)
        if fingerprint(metadata)!=self.metadata_hash or len(values)!=len(metadata['universe']):
            raise ExchangeError('MARKET_METADATA_CHANGED')
        self.client.metadata_timestamp_ms=metadata_ms
        contexts={row['name']:v for row,v in zip(metadata['universe'],values) if not row.get('isDelisted')}
        sent=self.client.clock_ms();book=self.market.get_orderbook(request.symbol)
        self.clock_health.observe(book.timestamp_ms,sent,self.client.clock_ms())
        quote=make_quote(book,contexts[request.symbol],self.client.clock_ms(),mark_timestamp_ms=metadata_ms)
        self.last_book=book;self.books[request.symbol]=book
        context=ValidationContext(self.client.market(request.symbol),self.metadata_hash,self.metadata_hash,
            metadata_ms,quote,readiness,after,after_orders,active,account_ms,limits,contexts,
            bool(self.feed_ready()) or request.reduce_only,self.policy_leverage,fills,
            recovery.account_truth_ready,metadata_ms)
        from .qualification_signing_boundary import fresh,context_ages
        self.rate_limits.journal.event('QUALIFICATION_FRESH_ACCOUNT_ACQUIRED',self.client.clock_ms(),
            started_ms=started,readiness=asdict(readiness),account_ms=account_ms,
            quote_ms=quote.timestamp_ms,mark_ms=metadata_ms,ages_ms=context_ages(context,self.client.clock_ms()),
            actual_positions=[asdict(p) for p in after.values()],open_orders=list(after_orders),
            actual_recent_fills=[asdict(f) for f in fills],retimestamped=False)
        if not fresh(context,self.client.clock_ms()):raise ExchangeError('QUALIFICATION_FRESH_BOUNDARY_UNAVAILABLE')
        return context


def entry_price_diagnostics(context,request,proposal,now_ms,book):
    """Only public numeric/account-observation fields; no signer or payload."""
    p=proposal;q=context.quote;spec=context.spec
    px,qty=decimal(request.price),decimal(request.quantity)
    upper=spec.normalize_price(q.ask*D('1.002'),'BUY')
    selected=decimal(p.entry_notional_ceiling) if p.price_authorization_mode==BOUNDED_PRICE else D(1000)
    conditions=dict(order_or_mark_notional_above_1000=qty*max(px,q.mark)>1000,
        order_notional_below_10=qty*px<10,limit_above_current_20bps=px>upper,
        ioc_limit_below_ask=p.entry_tif=='Ioc' and px<q.ask,
        resting_limit_crosses_ask=p.entry_tif!='Ioc' and px>=q.ask,
        resting_limit_below_bid_tolerance=p.entry_tif!='Ioc' and px<spec.normalize_price(q.bid*D('.998'),'BUY'),
        above_approved_max_buy=p.price_authorization_mode==BOUNDED_PRICE and px>decimal(p.max_buy_price),
        above_approved_quantity=p.price_authorization_mode==BOUNDED_PRICE and qty>decimal(p.quantity_ceiling),
        above_approved_order_or_mark_notional=qty*max(px,q.mark)>selected)
    return dict(symbol=request.symbol,price_authorization_mode=p.price_authorization_mode,
        bid=str(q.bid),ask=str(q.ask),mark=str(q.mark),oracle=str(q.oracle),
        proposed_limit=str(px),reviewed_limit_or_cap=p.entry_limit,max_buy_price=p.max_buy_price,
        current_ioc_minimum=str(q.ask),current_20bps_maximum=str(upper),entry_tolerance_bps='20',
        entry_buffer_bps=proposal_policy(p).get('entry_price_buffer_bps'),quantity=str(qty),
        quantity_ceiling=p.quantity_ceiling,order_notional=str(qty*px),mark_notional=str(qty*q.mark),
        minimum_notional='10',outer_notional_ceiling='1000',approved_notional_ceiling=str(selected),
        evaluated_ms=now_ms,proposal_observed_ms=p.observed_ms,quote_ms=q.timestamp_ms,
        mark_ms=q.mark_timestamp_ms,book_ms=book.timestamp_ms,account_ms=context.account_ms,
        readiness_ms=context.readiness.observed_ms,readiness_age_ms=now_ms-context.readiness.observed_ms,
        entry_deadline_ms=p.observed_ms+210000,conditions=conditions,
        rejected_conditions=[k for k,v in conditions.items() if v],configuration_hash=p.identity,
        working_source_hash=p.source_hash)


def check_entry(context,request,proposal,now_ms,book,*,journal=None,stage='ENTRY_VALIDATION'):
    diagnostic=entry_price_diagnostics(context,request,proposal,now_ms,book)
    try:
        result=_check_entry(context,request,proposal,now_ms,book)
        diagnostic.update(allowed=True,guard_result='ALLOWED')
        return result
    except ExchangeError as exc:
        diagnostic.update(allowed=False,guard_result=str(exc))
        raise
    finally:
        if journal is not None:journal.event('P0_ENTRY_PRICE_GUARD',now_ms,stage=stage,**diagnostic)


def calculate_bounded_entry(context,proposal,now_ms,book,*,client_order_id=None,journal=None,stage='PRICE_SELECTION'):
    p=proposal.require()
    if p.price_authorization_mode!=BOUNDED_PRICE:raise ExchangeError('P0_BOUNDED_APPROVAL_MODE_REQUIRED')
    if now_ms+90000>p.observed_ms+300000:raise ExchangeError('P0_ENTRY_WINDOW_CLOSED')
    qty=decimal(p.quantity);spec=context.spec
    if (spec.asset_id!=p.asset_id or spec.symbol!=p.symbol or spec.normalize_size(qty)!=qty
            or spec.normalize_price(p.max_buy_price,'BUY')!=decimal(p.max_buy_price)):
        raise ExchangeError('P0_BOUNDED_RUNTIME_PRECISION_OR_MAPPING')
    price=spec.normalize_price(min(context.quote.ask*D('1.001'),decimal(p.max_buy_price),
                                  decimal(p.entry_notional_ceiling)/qty),'BUY')
    request=OrderRequest(p.symbol,'BUY',qty,price,tif='Ioc',strategy_id='TESTNET_CERTIFICATION_ENTRY',
                         client_order_id=client_order_id)
    check_entry(context,request,p,now_ms,book,journal=journal,stage=stage)
    return request


def _check_entry(context,request,proposal,now_ms,book):
    p=proposal.require();q=context.quote;spec=context.spec
    if (request.symbol!=p.symbol or request.side!='BUY' or request.reduce_only
            or request.order_type!='LIMIT' or request.tif!=p.entry_tif
            or request.quantity!=decimal(p.quantity)
            or p.price_authorization_mode==FIXED_PRICE and request.price!=decimal(p.entry_limit)
            or spec.asset_id!=p.asset_id or spec.symbol!=p.symbol
            or spec.normalize_size(request.quantity)!=request.quantity
            or spec.normalize_price(request.price,'BUY')!=request.price):
        raise ExchangeError('P0_EXACT_ENTRY_REQUIRED')
    minimum=(D(10)/request.price/spec.size_step).to_integral_value(rounding=ROUND_CEILING)*spec.size_step
    if request.quantity!=minimum:
        raise ExchangeError('P0_MINIMUM_VALID_QUANTITY_RULE_REQUIRED')
    if (not context.readiness.account_ready or not context.reconciled or context.positions or context.open_orders
            or context.readiness.team_address.lower()!=p.team_wallet.lower()
            or context.readiness.signer_address.lower()!=p.api_wallet.lower()
            or not context.feed_ready or q.mark_timestamp_ms is None
            or any(not 0<=now_ms-s<=5000 for s in (context.account_ms,context.readiness.observed_ms,
                q.timestamp_ms,q.mark_timestamp_ms,book.timestamp_ms))):
        raise ExchangeError('P0_FRESH_RECONCILED_FLAT_ACCOUNT_REQUIRED')
    if (book.symbol!=p.symbol or book.timestamp_ms!=q.timestamp_ms
            or book.bids[0].price!=q.bid or book.asks[0].price!=q.ask):
        raise ExchangeError('P0_BOOK_QUOTE_IDENTITY_REQUIRED')
    public=inspect_market(spec,book,now_ms,tif=p.entry_tif,
        asset_context=dict(markPx=str(q.mark),oraclePx=str(q.oracle)))
    if not public['potential']:raise ExchangeError(public['blocker'])
    if p.price_authorization_mode==BOUNDED_PRICE:
        if spec.normalize_price(p.max_buy_price,'BUY')!=decimal(p.max_buy_price):
            raise ExchangeError('P0_BOUNDED_RUNTIME_PRECISION_OR_MAPPING')
        if (now_ms+90000>p.observed_ms+300000
                or request.price>decimal(p.max_buy_price) or request.quantity>decimal(p.quantity_ceiling)
                or request.quantity*max(request.price,q.mark)>decimal(p.entry_notional_ceiling)):
            raise ExchangeError('P0_APPROVED_ENVELOPE_OR_TIME_EXCEEDED')
    if (request.quantity*max(request.price,q.mark)>1000 or request.quantity*request.price<10
            or request.price>spec.normalize_price(q.ask*D('1.002'),'BUY')
            or p.entry_tif=='Ioc' and request.price<q.ask
            or p.entry_tif!='Ioc' and (request.price>=q.ask or request.price<spec.normalize_price(q.bid*D('.998'),'BUY'))):
        raise ExchangeError('P0_CURRENT_PRICE_OR_CAP_REQUIRED')
    if abs(request.price-q.oracle)/q.oracle*10000>150:raise ExchangeError('P0_ORDER_ORACLE_DEVIATION')
    ent=sweep(book.asks,request.quantity,request.price,'BUY')
    exit=sweep(book.bids,request.quantity,spec.normalize_price(q.bid*D('.998'),'SELL'),'SELL')
    if (decimal(exit['available_quantity'])*D('.5')<request.quantity
            or p.entry_tif=='Ioc' and decimal(ent['available_quantity'])*D('.5')<request.quantity):
        raise ExchangeError('P0_APPROVED_L2_PARTICIPATION_EXCEEDED')
    active=context.active_asset
    if (active.get('coin')!=p.symbol or active.get('user','').lower()!=p.team_wallet.lower()
            or active.get('leverage')!=dict(type='cross',value=1) or context.leverage!=1):
        raise ExchangeError('P0_ONE_X_CROSS_IDENTITY_REQUIRED')
    fee=decimal(p.taker_fee_rate,nonnegative=True)
    if (decimal(context.readiness.fees['userCrossRate'])*2!=fee
            or decimal(context.readiness.fees['userAddRate'])*2!=decimal(p.maker_fee_rate)):
        raise ExchangeError('P0_FEE_SCHEDULE_CHANGED')
    if (request.quantity>decimal(active['maxTradeSzs'][0],nonnegative=True)
            or request.quantity*request.price*(1+max(fee,decimal(p.maker_fee_rate))*4)
                >decimal(active['availableToTrade'][0],nonnegative=True)):
        raise ExchangeError('P0_MARGIN_REQUIRED')
    residual=residual_close_assessment(spec,request.quantity,p.exit_bound)
    if not residual['ready']:raise ExchangeError(residual['blocker'])
    return dict(policy=proposal_policy(p),entry_depth=ent,exit_depth=exit,residuals=residual,
                old_10_percent_bbo_passed=request.quantity<=min(q.bid_quantity,q.ask_quantity)*D('.1'))


class EmergencyComplianceScope:
    """Narrow controlled-test capability. Production never constructs this class."""
    def __init__(self,proposal,provider):
        if type(proposal) is not EmergencyProposal:raise ExchangeError('P0_SCOPE_REQUIRED')
        self.proposal=proposal.require();self.provider=provider
    def validate(self,request,context,permission,now_ms):
        p=self.proposal
        if (permission.candidate_id!='certification:'+p.identity
                or permission.provenance.classification!='CONTROLLED_TEST_ORDER'
                or permission.provenance.test_authorization.get('qualification_policy_hash')!=policy_hash(p)):
            raise ExchangeError('P0_EXACT_POLICY_PROVENANCE_REQUIRED')
        if request.reduce_only:
            if request.symbol!=p.symbol or request.quantity>decimal(p.quantity):
                raise ExchangeError('P0_EXIT_SCOPE_REQUIRED')
            return dict(policy_hash=policy_hash(p),max_notional='1000',reduce_only=True)
        return check_entry(context,request,p,now_ms,self.provider.books[request.symbol],
                           journal=getattr(self.provider,'diagnostic_journal',None),stage='CENTRAL_VALIDATION')


def permission(request,proposal,now_ms,*,reason=None):
    result=cert.test_permission(request,proposal,now_ms,reason=reason)
    a=dict(result.provenance.test_authorization,qualification_policy_hash=policy_hash(proposal))
    return replace(result,provenance=replace(result.provenance,test_authorization=a))


class EmergencyExecution(HyperliquidExecution):
    def __init__(self,*args,proposal,**kwargs):
        self.proposal=proposal.require()
        super().__init__(*args,**kwargs)
        from .qualification_intent_recovery import QualificationPositionGuard
        self.position_guard=QualificationPositionGuard(self.journal,clock_ms=self.client.clock_ms)
        scope=EmergencyComplianceScope(proposal,self.context_provider)
        self.compliance_guard=ComplianceGuard(self.journal,self.position_guard,
            clock_ms=self.client.clock_ms,transport=self.transport,execution_owner=self,qualification_scope=scope)
        self.transport._compliance_guard=self.compliance_guard
        self.context_provider.diagnostic_journal=self.journal
        from .qualification_signing_boundary import QualificationSigningBoundary
        self.signing_boundary=QualificationSigningBoundary(self)

    def _validated(self,request,permission,**kwargs):
        result=super()._validated(request,permission,**kwargs)
        req,context,_,decision=result
        self.signing_boundary.bind(req,permission,context,decision,full_close=kwargs.get('full_position_close',False))
        return result
    def _prepare_context_request(self,request,risk,context):
        p=self.proposal
        if request.reduce_only or p.price_authorization_mode==FIXED_PRICE:return request,risk
        if (request.symbol!=p.symbol or request.side!='BUY' or request.quantity!=decimal(p.quantity)
                or request.price!=decimal(p.entry_limit) or request.tif!='Ioc'
                or request.strategy_id!='TESTNET_CERTIFICATION_ENTRY' or request.order_type!='LIMIT'
                or request.client_order_id!='certification:'+p.identity+':entry'
                or risk.candidate_id!='certification:'+p.identity):
            raise ExchangeError('P0_BOUNDED_ENTRY_DRAFT_REQUIRED')
        selected=calculate_bounded_entry(context,p,self.client.clock_ms(),self.context_provider.books[p.symbol],
            client_order_id=request.client_order_id,journal=self.journal,stage='FRESH_CONTEXT_PRICE_SELECTION')
        return selected,permission(selected,p,self.client.clock_ms())
    def submit(self,request,*,permission=None):
        # Restore the actual durable price, never select a second price/order.
        if self.proposal.price_authorization_mode==BOUNDED_PRICE and not request.reduce_only:
            prior=self.journal.intent(request.client_order_id) if request.client_order_id else None
            if prior:
                saved=OrderRequest(**json.loads(prior['request']))
                if (request.price!=decimal(self.proposal.entry_limit)
                        or replace(request,price=saved.price)!=saved
                        or saved.price>decimal(self.proposal.max_buy_price)):
                    raise ExchangeError('P0_BOUNDED_DUPLICATE_INTENT_CONFLICT')
                request=saved
        return super().submit(request,permission=permission)
    def close_full_position(self,request,*,permission=None):
        if (permission is None or permission.candidate_id!='certification:'+self.proposal.identity
                or request.client_order_id not in {'certification:'+self.proposal.identity+':exit:0',
                    'certification:'+self.proposal.identity+':exit:1'}):
            raise ExchangeError('P0_EXACT_EXIT_PERMISSION_REQUIRED')
        if self.journal.intent(request.client_order_id) is None:
            from .qualification_protection import require_settled_exit_orders
            require_settled_exit_orders(self)
        a=dict(permission.provenance.test_authorization,qualification_policy_hash=policy_hash(self.proposal))
        scoped=replace(permission,provenance=replace(permission.provenance,test_authorization=a))
        return super().close_full_position(request,permission=scoped)
    def _guard(self,context,checked_ms,**kwargs):
        request=kwargs.get('entry_request') or kwargs.get('exact_full_close')
        if request is not None and self.signing_boundary.current is not None:
            context,checked_ms=self.signing_boundary.context_for(request)
            # The typed boundary has already performed genuine current account,
            # central risk/compliance and exact-position checks. Avoid duplicate
            # account and book reads that aged the old readiness evidence.
            self._require();self.clock_health.require()
            if not self.transport.nonces.healthy:raise ExchangeError('NONCE_SIGNING_DEGRADED')
            if kwargs.get('entry') and (self.entries_paused or not self.rate_limits.entries_allowed
                    or self.protection is not None and not self.protection.entries_allowed):
                raise ExchangeError('ENTRY_RELIABILITY_GATE_REQUIRED')
            startup=getattr(self.recovery,'startup_coordinator',None)
            if kwargs.get('entry') and startup is not None and not startup.entry_ready:
                raise ExchangeError('STARTUP_ENTRY_LOCK_REQUIRED')
            now=self.client.clock_ms()
            if (not self.client.ready or not 0<=now-checked_ms<=5000
                    or not context.readiness.account_ready
                    or context.readiness.agent_expiry_ms is None or context.readiness.agent_expiry_ms<=now
                    or not kwargs.get('critical',False) and
                       (not self.context_provider.feed_ready() or now<self.rate_limits.backoff_until)):
                raise ExchangeError('SIGNING_READINESS_REVOKED')
            from .qualification_signing_boundary import fresh
            if not fresh(context,self.client.clock_ms()):raise ExchangeError('QUALIFICATION_FRESH_BOUNDARY_UNAVAILABLE')
            from .delegated_qualification import DelegatedAuthorization
            if type(getattr(self.transport,'authorization',None)) is DelegatedAuthorization:
                self.transport.authorization.require_context(context,request)
            if kwargs.get('exact_full_close') is not None:
                from .qualification_protection import require_settled_exit_orders
                require_settled_exit_orders(self,current_intent=request.client_order_id)
            return
        super()._guard(context,checked_ms,**kwargs)
        from .delegated_qualification import DelegatedAuthorization
        if type(getattr(self.transport,'authorization',None)) is DelegatedAuthorization:
            request=kwargs.get('entry_request') or kwargs.get('exact_full_close')
            if request is not None:self.transport.authorization.require_context(context,request)
        if kwargs.get('exact_full_close') is not None:
            from .qualification_protection import require_settled_exit_orders
            require_settled_exit_orders(self, current_intent=kwargs['exact_full_close'].client_order_id)
        if kwargs.get('entry'):
            p=self.proposal
            # The original identity is immutable. One extra current public L2
            # read at each signing boundary, never a stale prepared depth estimate.
            book=self.context_provider.market.get_orderbook(p.symbol)
            from .hyperliquid_market_data import make_quote
            q=make_quote(book,context.contexts[p.symbol],self.client.clock_ms(),
                mark_timestamp_ms=context.quote.mark_timestamp_ms)
            current=replace(context,quote=q)
            request=kwargs.get('entry_request') or OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif=p.entry_tif)
            check_entry(current,request,p,self.client.clock_ms(),book,journal=self.journal,stage='FINAL_SIGNING_VALIDATOR')


class EmergencySDKTransport(OfficialSDKTransport):
    def __init__(self,client,signer,team_address,nonces,authorization,*,rate_limits):
        from .delegated_qualification import DelegatedAuthorization
        if type(authorization) not in {EmergencyAuthorization,DelegatedAuthorization}:raise ExchangeError('P0_CAPABILITY_REQUIRED')
        authorization.require(team_address,signer.address)
        self.action_expiry_ms=min(authorization.approval.expires_ms,
            authorization.proposal.observed_ms+POLICY['approval_window_ms'])
        super().__init__(client,signer,team_address,nonces,authorization,rate_limits=rate_limits)
    def check(self,action):
        super().check(action);self.authorization.check_action(action)
        if action.get('type')=='order' and action['orders'][0]['r'] is False:
            p=self.authorization.proposal
            if not residual_close_assessment(self.client.market(p.symbol),p.quantity,p.exit_bound)['ready']:
                raise ExchangeError('QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL')
    def transmit(self,payload):
        self.boundary_phase='PRE_HTTP'
        try:self.check(payload['action'])
        except Exception as exc:
            self.record_transport_boundary('PRE_HTTP_REJECTED',payload,
                error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
            raise
        if payload.get('expiresAfter')!=self.action_expiry_ms:raise ExchangeError('P0_SIGNED_EXPIRY_REQUIRED')
        self.authorization.claim_transmission(payload['action'])
        return super().transmit(payload)

    def record_transport_boundary(self,stage,payload,**details):
        action=payload['action'];orders=action.get('orders',[])
        self.authorization.journal.event('QUALIFICATION_TRANSPORT_BOUNDARY',self.client.clock_ms(),
            stage=stage,cloid=orders[0].get('c') if len(orders)==1 else None,
            action_hash=fingerprint(action),nonce=payload.get('nonce'),
            expires_ms=payload.get('expiresAfter'),network='testnet',dex='par',**details)


def propose(context,client,source_hash,reliability_hash,book,*,tif='Ioc',candidate_hash,price_mode=FIXED_PRICE):
    spec,q=context.spec,context.quote
    row=inspect_market(spec,book,client.clock_ms(),tif=tif,
        asset_context=dict(markPx=str(q.mark),oraclePx=str(q.oracle)))
    if not row['potential']:raise ExchangeError(row['blocker'])
    # Choose minimum valid whole-lot order; NEVER automatically size toward $1000.
    if price_mode not in {FIXED_PRICE,BOUNDED_PRICE}:raise ExchangeError('P0_UNKNOWN_PRICE_MODE')
    if price_mode==BOUNDED_PRICE and (spec.symbol!='par:BTC' or tif!='Ioc'):
        raise ExchangeError('P0_BOUNDED_BTC_IOC_ONLY')
    envelope=(dict(price_authorization_mode=BOUNDED_PRICE,max_buy_price=row['entry_limit'],
        quantity_ceiling=row['minimum_quantity'],
        entry_notional_ceiling=str(decimal(row['minimum_quantity'])*decimal(row['entry_limit'])),
        mode='TESTNET_QUALIFICATION_P0_BOUNDED_IOC_V2',entry_rule=BOUNDED_RULE,
        qualification_policy_hash=fingerprint(BOUNDED_POLICY)) if price_mode==BOUNDED_PRICE else
        dict(qualification_policy_hash=policy_hash()))
    p=EmergencyProposal(symbol=spec.symbol,asset_id=spec.asset_id,quantity=row['minimum_quantity'],
        entry_side='BUY',entry_limit=row['entry_limit'],exit_bound=row['exit_floor'],
        stop_trigger=str(spec.normalize_price(q.bid*D('.99'),'SELL')),stop_limit=row['exit_floor'],
        reference_bid=str(q.bid),reference_ask=str(q.ask),reference_mark=str(q.mark),reference_oracle=str(q.oracle),
        observed_ms=client.clock_ms(),source_hash=source_hash,reliability_policy_hash=reliability_hash,
        team_wallet=cert.TEAM,api_wallet=cert.API,**envelope,
        entry_tif=tif,order_lifetime_seconds=0 if tif=='Ioc' else 30,candidate_evidence_hash=candidate_hash,
        taker_fee_rate=str(decimal(context.readiness.fees['userCrossRate'])*2),
        maker_fee_rate=str(decimal(context.readiness.fees['userAddRate'])*2)).require()
    req=(calculate_bounded_entry(context,p,client.clock_ms(),book) if price_mode==BOUNDED_PRICE else
         OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif=tif,strategy_id='TESTNET_CERTIFICATION_ENTRY'))
    local=check_entry(context,req,p,client.clock_ms(),book)
    checked=HyperliquidOrderValidator(client).validate(req,context,permission(req,p,client.clock_ms()),client.clock_ms())
    if not checked.allowed:raise ExchangeError(checked.code)
    return p,dict(local=local,central=asdict(checked),final_evidence_hash=fingerprint(dict(
        book=asdict(book),quote=asdict(q),account_ms=context.account_ms,proposal_id=p.identity)))


class EmergencySequence(cert.CertificationSequence):
    def __init__(self,*args,monotonic=None,**kwargs):
        super().__init__(*args,verified_full_position_closes=True,**kwargs)
        if type(self.p) is not EmergencyProposal:raise ExchangeError('P0_PROPOSAL_REQUIRED')
        self.e.protection=UnverifiedQualificationProtection();self.monotonic=monotonic or time.monotonic
        self.report.update(execution_mode=self.p.mode,normal_protection_certified=False,
            protection_accepted=False,organizer_whitelisting_confirmed=False)

    def _entry_settled(self,order):
        submitted=self.e.journal.control('p0_entry_submission_ms')
        if type(submitted) is not int:raise ExchangeError('P0_DURABLE_ENTRY_TIME_REQUIRED')
        remaining=max(0,self.p.order_lifetime_seconds-(self.e.client.clock_ms()-submitted)/1000)
        deadline=self.monotonic()+remaining
        while True:
            order=self.resolved(self.e.recover_uncertain(order.intent_key))
            positions,orders=self.observe()
            if any(str(o['oid'])!=str(order.exchange_order_id) for o in orders):
                raise ExchangeError('P0_UNEXPECTED_OPEN_ORDER')
            self.report.setdefault('entry_monitor',[]).append(dict(at_ms=self.e.client.clock_ms(),
                state=order.state.value,filled_quantity=str(order.filled_quantity),orders=orders,
                positions=[asdict(x) for x in positions.values()]))
            if not orders:break
            if order.filled_quantity or self.p.entry_tif=='Ioc' or self.monotonic()>=deadline:
                # One cancellation, only the original entry; no reprice/replacement.
                result=self.e.cancel_order(self.p.symbol,order.exchange_order_id,critical=True)
                self.report['original_entry_cancel']=asdict(result)
                order=self.resolved(self.e.recover_uncertain(order.intent_key))
                positions,orders=self.observe()
                status=self.e.account._query('orderStatus',oid=order.cloid)
                if (orders or status.get('status')!='order' or status['order'].get('status') not in
                        {'canceled','cancelled','filled'} and not status['order'].get('status','').endswith('Canceled')):
                    raise ExchangeError('P0_ENTRY_CANCEL_NOT_AUTHORITATIVELY_CONFIRMED')
                break
            self.wait()
        if not self.e.recovery.last_report.ready:raise ExchangeError('P0_ORDER_RECONCILIATION_REQUIRED')
        return order,positions

    def run(self):
        try:
            self.auth.require(self.p.team_wallet,self.p.api_wallet)
            if (self.e.journal.control('certification_started:'+self.p.identity)
                    or self.e.journal.control('qualification_entry_consumed') or self.e.position_guard.intent_rows()):
                raise ExchangeError('P0_RESTART_READ_ONLY_RECOVERY_REQUIRED')
            positions,orders=self.observe()
            if positions or orders or not self.e.recovery.last_report.ready:
                raise ExchangeError('P0_INITIAL_FLAT_REQUIRED')
            self.report['equity_before']=str(self.e.recovery.state.equity.reported_account_value)
            before_fills=set(self.e.recovery.state.fills);before_funding=set(self.e.recovery.state.funding)
            self.e.journal.control('certification_started:'+self.p.identity,True)
            self.e.entries_paused=False
            req=OrderRequest(self.p.symbol,'BUY',self.p.quantity,self.p.entry_limit,
                strategy_id='TESTNET_CERTIFICATION_ENTRY',tif=self.p.entry_tif,client_order_id=self.prefix+'entry')
            self.report['status']='ENTRY_SUBMISSION_PENDING'
            order=self.resolved(self.e.submit(req,permission=permission(req,self.p,self.e.client.clock_ms())))
            order,positions=self._entry_settled(order);self.report['entry']=asdict(order)
            entries=[f for k,f in self.e.recovery.state.fills.items() if k not in before_fills
                and f.order_id==str(order.exchange_order_id) and f.symbol==self.p.symbol]
            qty=sum((f.quantity for f in entries),D(0))
            if (qty!=order.filled_quantity or any(f.side!='BUY' for f in entries)
                    or positions and (positions[self.p.symbol].quantity!=qty or qty<=0)
                    or qty and not positions):
                raise ExchangeError('P0_ACTUAL_ENTRY_FILL_POSITION_MISMATCH')
            if not positions:self.report['status']='NO_FILL_VERIFIED'
            else:
                self.report['status']='UNPROTECTED_FILLED_POSITION'
                self.close()
            positions,orders=self.observe()
            if positions or orders or not self.e.recovery.last_report.ready:
                raise ExchangeError('P0_FINAL_FLAT_RECONCILIATION_REQUIRED')
            self.report['final_flat']=True
            fills=[f for k,f in self.e.recovery.state.fills.items() if k not in before_fills]
            known={str(r['oid']) for r in self.e.journal.intents() if r['oid'] is not None}
            if any(f.order_id not in known or f.symbol!=self.p.symbol for f in fills):
                raise ExchangeError('P0_UNEXPECTED_FILL')
            if entries:
                self.report.update(realized(entries,[f for f in fills if f.side=='SELL'],
                    [f for k,f in self.e.recovery.state.funding.items() if k not in before_funding],self.p))
                after=self.e.recovery.state.equity.reported_account_value
                delta=after-decimal(self.report['equity_before'])
                self.report.update(equity_after=str(after),equity_delta=str(delta))
                if abs(delta-decimal(self.report['realized_pnl']['net_realized_pnl']))>D('.000001'):
                    raise ExchangeError('P0_EQUITY_ACCOUNTING_MISMATCH')
                self.report['status']='TRADE_CLOSED_RECONCILED'
            self.e.journal.control('certification_completed:'+self.p.identity,True)
        except Exception as exc:
            attempted=self.e.journal.control('qualification_entry_consumed')==self.p.identity
            # A PREPARED/SUBMITTED durable attempt also needs read-only recovery.
            attempted=attempted or bool(self.e.position_guard.intent_rows())
            if self.report['status']=='NO_ORDER_AUTHORIZED' and self.e.journal.control('certification_completed:'+self.p.identity):
                attempted=False
            self.report.update(status='EMERGENCY_EXIT_REQUIRED' if attempted else 'PREFLIGHT_BLOCKED',
                error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
                operator_action_required=attempted,realized_pnl_status='REALIZED_PNL_NOT_CERTIFIED',
                recovery_steps=RECOVERY_STEPS)
            self.e.journal.control('certification_halted:'+self.p.identity,True)
        finally:
            self.e.entries_paused=True;self.auth.revoke()
            self.report['evidence_scope']='OFFLINE_SIGNED_FIXTURE' if type(self.e.transport) is OfflineSDKTransport else 'ACTUAL_TESTNET_ACCOUNT'
            self.report.update(certification_passed=False,practice_ready=False,live_ready=False)
            self.e.journal.event('P0_QUALIFICATION_RESULT',self.e.client.clock_ms(),report=self.report)
        return self.report


RECOVERY_STEPS=[
    'STOP new entries. Preserve journal, original cloid/oid, consumed attempt and source/approval files.',
    'Query original orderStatus by cloid, team userFillsByTime, frontendOpenOrders and clearinghouseState with dex=par.',
    'UNKNOWN is not flat. Reconcile actual fills, original unfilled order and signed-management uncertainty without resubmission.',
    'An original resting remainder must be canceled and cancellation/terminal state confirmed before a full-position exit.',
    'Within current exact approval: SELL reduce-only IOC for actual reconciled quantity, at fresh bid less 20 bps, never below the approved floor; at most two exits.',
    'If halted, expired, disconnected, outside price bounds or cancellation/exits uncertain: no further writes. Obtain separate exact recovery approval or manually inspect the team account.',
    'Claim flat only after authoritative zero par positions, zero open orders and ready durable account reconciliation.']


def realized(entries,exits,funding,p):
    """Actual reported P&L; GTC may pay maker or taker fees, never assume a rebate."""
    if (not entries or not exits or any(f.source!='EXCHANGE_REPORTED_FILL' or f.closed_pnl is None
            or f.fee_token!='USDPR' or f.symbol!=p.symbol for f in entries+exits)
            or any(f.source!='EXCHANGE_REPORTED_USER_FUNDING' or f.symbol!=p.symbol for f in funding)
            or len({f.identity for f in entries+exits})!=len(entries+exits)):
        raise ExchangeError('P0_REPORTED_ACCOUNTING_EVENTS_REQUIRED')
    qty=sum((f.quantity for f in entries),D(0))
    if qty!=sum((f.quantity for f in exits),D(0)) or qty>decimal(p.quantity):
        raise ExchangeError('P0_FILL_SIZE_MISMATCH')
    en=sum((f.quantity*f.price for f in entries),D(0));ex=sum((f.quantity*f.price for f in exits),D(0))
    gross=sum((f.closed_pnl for f in entries+exits),D(0))
    if abs(ex-en-gross)>D('.000001'):raise ExchangeError('P0_CLOSED_PNL_MISMATCH')
    fees=sum((f.fee for f in entries+exits),D(0));cash=sum((f.cashflow for f in funding),D(0))
    rates=(decimal(p.maker_fee_rate),decimal(p.taker_fee_rate))
    if not (en*min(rates)+ex*rates[1]-D('.000002')<=fees<=(en+ex)*max(rates)*D('1.02')+D('.000002')):
        raise ExchangeError('P0_REPORTED_FEE_OUTSIDE_REVIEWED_SCHEDULE')
    return dict(realized_pnl_status='EXCHANGE_REALIZED_PNL_CERTIFIED',realized_pnl={k:str(v) for k,v in
        dict(quantity=qty,entry_notional=en,exit_notional=ex,gross_closed_pnl=gross,
            actual_entry_fee=sum((f.fee for f in entries),D(0)),actual_exit_fee=sum((f.fee for f in exits),D(0)),
            actual_funding=cash,net_realized_pnl=gross-fees+cash).items()},fill_proof=[asdict(f) for f in entries+exits],
            funding_proof=[asdict(f) for f in funding],fee_liquidity_type='REPORTED_FEES; NORMALIZED_FILL_HAS_NO_MAKER_TAKER_TAG')


def build_runtime(root,proposal,approval,*,test_receipt,delegation=None,nonce_owner=None,rate_owner=None):
    """Construct actual SDK only AFTER exact current approval and fresh read gates."""
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    from .paper_operations import active_source_hash
    from .reliability_policy import load_reliability_policy
    from .hyperliquid_client import HyperliquidClient
    from .hyperliquid_account import HyperliquidAccount
    from .hyperliquid_market_data import HyperliquidMarketData
    from .execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager, NonceManager
    from .practice_preflight import read_api_key, api_signer
    from .qualification_intent_recovery import QualificationRecovery,qualification_intents
    root=Path(root).resolve();state=root/'runtime/testnet/anchorium-bot-1'
    require_paper_migration();verify_strategy_freeze();proposal.require()
    require_emergency_regression(root,test_receipt);prior_execution_check(root)
    journal=ExecutionJournal(state/'qualification.sqlite',session_id='anchorium-one-qualification-v1',team_address=proposal.team_wallet)
    client=transport=nonces=None
    previous_rate_journal=getattr(rate_owner,'journal',None)
    try:
        auth_kwargs=dict(clock_ms=lambda:time.time_ns()//1000000,source_hash=lambda:active_source_hash(root),
            policy_hash=lambda:hashlib.sha256((root/'configs/reliability_policy.json').read_bytes()).hexdigest())
        if delegation is not None:
            from .delegated_qualification import Delegation,DelegatedAuthorization
            if type(delegation) is not Delegation or approval is not None:
                raise ExchangeError('DELEGATED_CAPABILITY_CANNOT_SYNTHESIZE_PROPOSAL_APPROVAL')
            if json.loads(Path(test_receipt).read_text())['totals']['tests']<2194:
                raise ExchangeError('DELEGATED_FULL_2194_BASELINE_REQUIRED')
            auth=DelegatedAuthorization(proposal,delegation,journal,**auth_kwargs)
        else:auth=EmergencyAuthorization(proposal,approval,journal,**auth_kwargs)
        auth.require(proposal.team_wallet,proposal.api_wallet)
        if qualification_intents(journal) or journal.control('qualification_entry_consumed'):
            raise ExchangeError('P0_PRIOR_ATTEMPT_READ_ONLY_RECOVERY_REQUIRED')
        rate,cp,protection=load_reliability_policy(root/'configs/reliability_policy.json')
        if protection.enabled:raise ExchangeError('P0_GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        if rate_owner is not None:
            if (type(rate_owner) is not HyperliquidRateLimitManager or rate_owner.policy!=rate
                    or rate_owner.signer_address.lower()!=proposal.api_wallet.lower()):
                raise ExchangeError('QUALIFICATION_SHARED_RATE_OWNER_REQUIRED')
            rates=rate_owner
            rates.journal=journal  # Preserve rolling usage/reserves across the paused observer handoff.
        else:rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=proposal.api_wallet)
        client=HyperliquidClient(rate_limits=rates);client.startup()
        account=HyperliquidAccount(client,proposal.team_wallet);market=HyperliquidMarketData(client)
        # V2's mandatory provider bundle already reads/reconciles positions and
        # frontend orders, and check_entry requires flat. Avoid only this extra
        # duplicate pair; retain all validation and final signing-boundary reads.
        if proposal.price_authorization_mode==FIXED_PRICE and (account.get_positions() or account.get_frontend_open_orders()):
            raise ExchangeError('P0_INITIAL_FLAT_REQUIRED')
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**cp)
        recovery=QualificationRecovery(account,journal,initial_start_ms=0)
        provider=EmergencyContextProvider(market,account,proposal.api_wallet,clock,rates,
            reconcile_before_load=recovery.recover,reconciliation_ready=lambda:recovery.account_truth_ready,feed_ready=lambda:True)
        req=OrderRequest(proposal.symbol,'BUY',proposal.quantity,proposal.entry_limit,tif=proposal.entry_tif,
            strategy_id='TESTNET_CERTIFICATION_ENTRY')
        context=provider.load(req)
        if proposal.price_authorization_mode==BOUNDED_PRICE:
            req=calculate_bounded_entry(context,proposal,client.clock_ms(),provider.last_book,
                journal=journal,stage='BUILD_RUNTIME_FRESH_PREFLIGHT')
        else:
            check_entry(context,req,proposal,client.clock_ms(),provider.last_book,
                journal=journal,stage='BUILD_RUNTIME_FRESH_PREFLIGHT')
        validation=HyperliquidOrderValidator(client).validate(req,context,permission(req,proposal,client.clock_ms()),client.clock_ms())
        if not validation.allowed:raise ExchangeError(validation.code)
        if delegation is not None:
            auth.require_context(context,req)
            auth.register_runtime()
        provider.reconcile_before_load=None
        key,_=read_api_key(root)
        try:signer=api_signer(key,proposal.api_wallet,proposal.team_wallet)
        finally:key=None
        if nonce_owner is not None:
            if (type(nonce_owner) is not NonceManager or nonce_owner.closed or not nonce_owner.healthy
                    or nonce_owner.path.resolve()!=(state/'nonces.sqlite').resolve()
                    or nonce_owner.signer_address!=signer.address.lower()):
                raise ExchangeError('EXCLUSIVE_EXISTING_NONCE_OWNER_REQUIRED')
            nonces=nonce_owner
            nonces.journal=journal  # Actual nonce evidence belongs to the execution journal.
        else:nonces=NonceManager(state/'nonces.sqlite',signer.address,journal=journal)
        transport=EmergencySDKTransport(client,signer,proposal.team_wallet,nonces,auth,rate_limits=rates)
        signer=None
        executor=EmergencyExecution(client,proposal=proposal,transport=transport,account=account,journal=journal,
            context_provider=provider,validator=HyperliquidOrderValidator(client),recovery=recovery,
            clock_health=clock,rate_limits=rates)
        return EmergencyRuntime(EmergencySequence(executor,proposal,auth,wait=lambda:time.sleep(1)),
                                client,transport,nonces,journal)
    except Exception:
        if transport:transport.close()
        if nonces:nonces.close()
        if client:client.close()
        if rate_owner is not None and previous_rate_journal is not None:
            rate_owner.journal=previous_rate_journal
        journal.close();raise


class EmergencyRuntime:
    def __init__(self,sequence,client,transport,nonces,journal):
        self.sequence,self.client,self.transport,self.nonces,self.journal=sequence,client,transport,nonces,journal
    def run(self):
        result=self.sequence.run()
        result['whitelist_trade_proof']=whitelist_trade_proof(self.sequence,result,
            actual_transport=type(self.transport) is EmergencySDKTransport)
        return result
    def close(self):
        self.sequence.auth.revoke()
        try:self.sequence.e.recovery.checkpoint(clean=True)
        finally:
            self.transport.close();self.nonces.close();self.client.close();self.journal.close()


def require_emergency_regression(root,receipt):
    path=require_qualification_regression(root,receipt)
    r=json.loads(path.read_text())
    after=r.get('checks_after',{})
    if (r['totals']['tests']<2046 or set(after)!={'strategy_freeze','phase0'}
            or any(v.get('exit_code')!=0 or v.get('result',{}).get('passed') is not True for v in after.values())):
        raise ExchangeError('P0_FULL_BASELINE_AND_AFTER_CHECKS_REQUIRED')
    return path
