"""Single human-approved practice experiment; never certifies strategy/protection.

Qualification-only proposed risk policy: $25 cap, 50 bps spread, immediate bounded
close, no protective order. Unprotected residual exposure needs explicit approval.
Normal certification and production policies are untouched. No automatic retry.
"""
from dataclasses import dataclass, asdict, replace
from decimal import Decimal as D
import hashlib, json, sqlite3, time
from pathlib import Path

from . import testnet_certification as certification
from .base_exchange import ExchangeError, decimal
from .full_position_close import observed_scope
from .execution_journal import ExecutionJournal, fingerprint
from .order_lifecycle import OrderRequest
from .testnet_certification import (CertificationProposal, CertificationApproval,
    CertificationAuthorization, CertificationSequence, test_permission)
from .certification_runtime import CertificationContextProvider, CertificationRecovery
from .hyperliquid_execution import HyperliquidExecution
from .sdk_transport import OfficialSDKTransport, OfflineSDKTransport

RULE = 'ONE_BOUNDED_LONG_THEN_IMMEDIATE_CLOSE_V1'


def prime_read_only_clock(market, clock, symbol):
    """Two timestamped public observations before evaluating account readiness."""
    for _ in range(2):
        sent=market.client.clock_ms()
        book=market.get_orderbook(symbol)
        clock.observe(book.timestamp_ms,sent,market.client.clock_ms())
    if not clock.healthy:
        raise ExchangeError('QUALIFICATION_CLOCK_NOT_HEALTHY')


class QualificationContextProvider(CertificationContextProvider):
    """Qualification-only ordered reads; never relabel an old unhealthy snapshot.

    Clock evidence follows any budget wait. A complete new context is obtained
    after recovery, and inconsistent/stale pairs receive one bounded read retry.
    A recovery callback is used only before assembly of the execution guard:
    revoking that guard inside its preflight would change its generation.
    """
    def __init__(self, *args, reconcile_before_load=None, wait=None, progress=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reconcile_before_load = reconcile_before_load
        self.wait = wait or time.sleep
        self.observations = []
        self.trigger_aware = True
        self.progress=progress

    def load(self, request, *, critical=False):
        for attempt in range(2):
            observed = dict(symbol=request.symbol, attempt=attempt,
                            started_ms=self.client.clock_ms(), clock_before=self.clock_health.report())
            self.observations.append(observed)
            try:
                # Reserve enough room for the serial bundle; retain the central
                # limiter and its safety reserve. No signing or nonce is involved.
                reserve = 600 if self.reconcile_before_load is not None else 450
                # The manager derives a next retry from actual rolling weights
                # and venue guidance. Its waits are bounded and cancellable.
                self.rate_limits.wait_for_read_budget(reserve,max_wait_seconds=65,
                    cancel_event=self.client.read_cancel_event,progress=self.progress,
                    wait_ms=lambda ms:self.wait(ms/1000))
                prime_read_only_clock(self.market, self.clock_health, request.symbol)
                observed['clock_synchronized'] = self.clock_health.report()
                if self.reconcile_before_load is not None:
                    report = self.reconcile_before_load()
                    if not report.ready:
                        raise ExchangeError('QUALIFICATION_DURABLE_RECONCILIATION_REQUIRED')
                    observed['reconciled_ms'] = self.client.clock_ms()
                from contextlib import nullcontext
                # Only preparation can share static account snapshots. Actual
                # execution and all position/order/history/book reads stay fresh.
                scope=self.client.read_snapshot_scope() if self.reconcile_before_load is not None else nullcontext()
                with scope:context = super().load(request, critical=critical)
                now = self.client.clock_ms()
                observed.update(readiness=asdict(context.readiness), account_ms=context.account_ms,
                    quote_ms=context.quote.timestamp_ms, mark_ms=context.quote.mark_timestamp_ms,
                    clock_after=self.clock_health.report(), evaluated_ms=now)
                pair_fresh = all(type(stamp) is int and 0 <= now-stamp <= 5000 for stamp in
                    (context.readiness.observed_ms, context.account_ms, context.quote.timestamp_ms,
                     context.quote.mark_timestamp_ms))
                clock_rejected = 'CLOCK_HEALTH_REQUIRED' in context.readiness.reasons
                if not self.clock_health.healthy or clock_rejected or not pair_fresh:
                    raise ExchangeError('QUALIFICATION_CLOCK_ACCOUNT_QUOTE_PAIR_NOT_READY')
                observed['result'] = 'CONSISTENT_FRESH_CONTEXT'
                return context
            except ExchangeError as exc:
                observed.update(result=str(exc), clock_after=self.clock_health.report(),
                                finished_ms=self.client.clock_ms())
                if attempt == 1 or str(exc) not in {
                        'QUALIFICATION_CLOCK_NOT_HEALTHY',
                        'QUALIFICATION_CLOCK_ACCOUNT_QUOTE_PAIR_NOT_READY'}:
                    raise
                self.wait(.25)
        raise ExchangeError('QUALIFICATION_CLOCK_ACCOUNT_QUOTE_PAIR_NOT_READY')


def residual_close_assessment(spec, quantity, exit_floor):
    """Every possible whole-lot residual at the approved worst exit price."""
    quantity=decimal(quantity,positive=True);floor=decimal(exit_floor,positive=True)
    if quantity % spec.size_step or spec.normalize_size(quantity)!=quantity:
        raise ExchangeError('QUALIFICATION_EXACT_SIZE_REQUIRED')
    count=int(quantity/spec.size_step)
    if count>10000:raise ExchangeError('QUALIFICATION_RESIDUAL_ANALYSIS_BOUND')
    small=[]
    for n in range(1,count+1):
        size=spec.size_step*n
        if size*floor<10:
            try:proof=observed_scope(spec,'SELL',size)
            except ExchangeError:
                return dict(ready=False,blocker='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL',
                            first_unverified_quantity=str(size),notional_at_floor=str(size*floor))
            small.append(dict(quantity=str(size),notional_at_floor=str(size*floor),proof=proof))
    return dict(ready=True,possible_residual_count=count,subminimum_residuals=small,
                scope='HISTORICAL_SHAPES_AND_APPROVED_PRICE_FLOOR_NOT_FUTURE_FILL_GUARANTEE')


@dataclass(frozen=True)
class QualificationProposal(CertificationProposal):
    mode: str = 'TESTNET_QUALIFICATION'
    session_loss_budget: str = '25'  # Principal allowance, NOT a guaranteed loss cap.
    max_signed_actions: int = 5
    entry_rule: str = RULE
    qualification_spread_bps: str = '50'
    protection_status: str = 'UNVERIFIED_NO_STOP_WILL_BE_SUBMITTED'

    def require(self):
        if (self.mode!='TESTNET_QUALIFICATION' or self.network!='testnet' or self.dex!='par'
                or self.symbol not in {'par:BTC','par:ETH','par:HYPE'} or self.entry_side!='BUY'
                or self.team_wallet.lower()!=certification.TEAM.lower()
                or self.api_wallet.lower()!=certification.API.lower()
                or self.entry_rule!=RULE or self.protection_status!='UNVERIFIED_NO_STOP_WILL_BE_SUBMITTED'
                or decimal(self.qualification_spread_bps)!=50 or decimal(self.max_notional)!=25
                or decimal(self.session_loss_budget)!=25 or self.max_exit_attempts!=2
                or type(self.max_exit_attempts) is not int or self.max_signed_actions!=5
                or type(self.max_signed_actions) is not int or type(self.asset_id) is not int or self.asset_id<100000
                or type(self.observed_ms) is not int or self.observed_ms<0
                or not self.source_hash or not self.reliability_policy_hash):
            raise ExchangeError('INVALID_QUALIFICATION_PROPOSAL')
        values={k:decimal(getattr(self,k),positive=True) for k in ('quantity','entry_limit','exit_bound',
            'stop_trigger','stop_limit','reference_bid','reference_ask','reference_mark','reference_oracle',
            'entry_slippage_bps','exit_slippage_bps','taker_fee_rate')}
        if (values['quantity']*max(values['entry_limit'],values['reference_mark'])>25
                or values['quantity']*values['entry_limit']<10
                or values['entry_slippage_bps']>5 or values['exit_slippage_bps']>20
                or not values['stop_limit']==values['exit_bound']<values['stop_trigger']<values['entry_limit']):
            raise ExchangeError('QUALIFICATION_SIZE_OR_BOUNDS_INVALID')
        return self


def check_entry(context, request, proposal, now_ms):
    """Retain central rules; independently enforce the exact local qualification rule."""
    p=proposal.require();q=context.quote;spec=context.spec
    if (request.symbol!=p.symbol or request.side!='BUY' or request.reduce_only
            or request.tif!='Ioc' or request.order_type!='LIMIT'
            or request.quantity!=decimal(p.quantity) or request.price!=decimal(p.entry_limit)
            or spec.symbol!=p.symbol or spec.asset_id!=p.asset_id):
        raise ExchangeError('QUALIFICATION_ENTRY_OUTSIDE_EXACT_PROPOSAL')
    if (not context.readiness.account_ready or not context.reconciled or context.positions or context.open_orders
            or context.readiness.team_address.lower()!=p.team_wallet.lower()
            or context.readiness.signer_address.lower()!=p.api_wallet.lower()
            or not 0<=now_ms-context.readiness.observed_ms<=5000
            or not context.feed_ready or not 0<=now_ms-context.account_ms<=5000
            or not 0<=now_ms-q.timestamp_ms<=5000 or q.mark_timestamp_ms is None
            or not 0<=now_ms-q.mark_timestamp_ms<=5000 or q.bid<=0 or q.ask<=q.bid):
        raise ExchangeError('QUALIFICATION_FRESH_FLAT_ACCOUNT_BOOK_REQUIRED')
    spread=(q.ask-q.bid)/q.mid*10000
    if spread>decimal(p.qualification_spread_bps):raise ExchangeError('QUALIFICATION_SPREAD_EXCEEDED')
    if abs(q.mark-q.oracle)/q.oracle*10000>50 or abs(q.mid-q.oracle)/q.oracle*10000>100:
        raise ExchangeError('QUALIFICATION_REFERENCE_DIVERGENCE')
    if request.quantity>min(q.bid_quantity,q.ask_quantity)*D('.1'):
        raise ExchangeError('QUALIFICATION_BOTH_SIDES_DEPTH_EXCEEDED')
    if (context.active_asset.get('leverage')!=dict(type='cross',value=1)
            or context.active_asset.get('user','').lower()!=p.team_wallet.lower()
            or context.active_asset.get('coin')!=p.symbol):
        raise ExchangeError('QUALIFICATION_ONE_X_ACCOUNT_IDENTITY_REQUIRED')
    if (request.price<q.ask or request.price>spec.normalize_price(q.ask*D('1.0005'),'BUY')
            or request.quantity*max(request.price,q.mark)>25):
        raise ExchangeError('QUALIFICATION_FIXED_PRICE_OR_NOTIONAL_CHANGED')
    fee=decimal(p.taker_fee_rate,nonnegative=True)
    if decimal(context.readiness.fees['userCrossRate'])*2!=fee:
        raise ExchangeError('QUALIFICATION_FEE_OBSERVATION_CHANGED')
    if (request.quantity>decimal(context.active_asset['maxTradeSzs'][0],nonnegative=True)
            or request.quantity*request.price*(1+fee*4)>decimal(context.active_asset['availableToTrade'][0],nonnegative=True)):
        raise ExchangeError('QUALIFICATION_MARGIN_REQUIRED')
    assessment=residual_close_assessment(spec,request.quantity,p.exit_bound)
    if not assessment['ready']:raise ExchangeError(assessment['blocker'])
    return assessment


def find_largest_safe_qualification_quantity(context, client, source_hash, policy_hash):
    """Largest lot-rounded size within every existing entry and residual gate.

    The ordinary $10 opening floor is a venue rule enforced by the central
    validator, not an invented metadata field. Precision/mapping are runtime.
    Neither a smaller size nor historical closes imply verified stop support.
    """
    from .exchange_rules import HyperliquidOrderValidator
    spec,q=context.spec,context.quote
    result=dict(ready=False, symbol=spec.symbol, maximum_notional='25', minimum_opening_notional='10',
                size_step=str(spec.size_step), selected_quantity=None, candidates=[])
    if q.symbol!=spec.symbol or q.bid<=0 or q.ask<=q.bid or q.bid_quantity<=0 or q.ask_quantity<=0:
        return dict(result, rejection='QUALIFICATION_TWO_SIDED_BOOK_REQUIRED')
    price=spec.normalize_price(q.ask*D('1.0005'),'BUY')
    reference=spec.normalize_price(q.bid*D('.99'),'SELL')
    floor=spec.normalize_price(reference*D('.995'),'SELL')
    try:
        fee=decimal(context.readiness.fees['userCrossRate'],nonnegative=True)*2
        active=context.active_asset
        bounds=dict(notional=D(25)/max(price,decimal(q.mark,positive=True)),
            bid_depth=decimal(q.bid_quantity,positive=True)*D('.1'),
            ask_depth=decimal(q.ask_quantity,positive=True)*D('.1'),
            account_size=decimal(active['maxTradeSzs'][0],nonnegative=True),
            margin=decimal(active['availableToTrade'][0],nonnegative=True)/(price*(1+fee*4)))
    except (KeyError,IndexError,TypeError,ExchangeError):
        return dict(result,rejection='QUALIFICATION_ACCOUNT_CAPACITY_REQUIRED')
    largest=(min(bounds.values())//spec.size_step)*spec.size_step
    result.update(quantity_bounds={k:str(v) for k,v in bounds.items()},
        largest_bounded_quantity=str(largest), entry_limit=str(price), exit_floor=str(floor),
        spread_bps=str((q.ask-q.bid)/q.mid*10000), taker_fee_rate=str(fee))
    if largest*price<10:
        return dict(result,rejection='QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS')
    count=int(largest/spec.size_step)
    if count>10000:
        return dict(result,rejection='QUALIFICATION_RESIDUAL_ANALYSIS_BOUND')
    for n in range(count,0,-1):
        quantity=spec.size_step*n
        if quantity*price<10:break
        row=dict(quantity=str(quantity),notional=str(quantity*price));result['candidates'].append(row)
        try:
            p=QualificationProposal(symbol=spec.symbol,asset_id=spec.asset_id,quantity=str(quantity),entry_side='BUY',
                entry_limit=str(price),exit_bound=str(floor),stop_trigger=str(reference),stop_limit=str(floor),
                reference_bid=str(q.bid),reference_ask=str(q.ask),reference_mark=str(q.mark),reference_oracle=str(q.oracle),
                observed_ms=client.clock_ms(),source_hash=source_hash,reliability_policy_hash=policy_hash,
                team_wallet=context.readiness.team_address,api_wallet=context.readiness.signer_address,
                taker_fee_rate=str(fee))
            request=OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif='Ioc',strategy_id='TESTNET_CERTIFICATION_ENTRY')
            residuals=check_entry(context,request,p,client.clock_ms())
            validation=HyperliquidOrderValidator(client).validate(request,context,
                test_permission(request,p,client.clock_ms()),client.clock_ms())
            if not validation.allowed:raise ExchangeError(validation.code)
        except ExchangeError as exc:
            row['rejection']=str(exc)
            continue
        row['allowed']=True
        return dict(result,ready=True,proposal=asdict(p),selected_quantity=str(quantity),
            entry_notional=str(quantity*price),bid_depth_utilization=str(quantity/q.bid_quantity),
            ask_depth_utilization=str(quantity/q.ask_quantity),residual_close_scope=residuals,
            verified_residual_quantities=[str(spec.size_step*i) for i in range(1,n+1)],
            estimated_exit_limit=str(spec.normalize_price(q.bid*D('.998'),'SELL')),
            central_validation=asdict(validation))
    return dict(result,rejection=result['candidates'][0]['rejection'] if result['candidates']
                else 'QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS')


def propose_qualification(context, client, source_hash, policy_hash):
    result=find_largest_safe_qualification_quantity(context,client,source_hash,policy_hash)
    if not result['ready']:raise ExchangeError(result['rejection'])
    return QualificationProposal(**result['proposal'])


@dataclass(frozen=True)
class QualificationApproval(CertificationApproval):
    unverified_stop_risk_accepted: bool = False
    qualification_spread_limit_accepted: bool = False
    possible_manual_residual_recovery_accepted: bool = False


class QualificationAuthorization(CertificationAuthorization):
    def require(self, team, signer):
        a=self.approval
        if (type(self.proposal) is not QualificationProposal or type(a) is not QualificationApproval
                or not all(v is True for v in (a.unverified_stop_risk_accepted,
                    a.qualification_spread_limit_accepted,a.possible_manual_residual_recovery_accepted))):
            raise ExchangeError('EXPLICIT_QUALIFICATION_RESIDUAL_RISK_ACCEPTANCE_REQUIRED')
        super().require(team,signer)

    def check_action(self, action):
        super().check_action(action)
        if action.get('type')=='order' and 'trigger' in action['orders'][0].get('t',{}):
            raise ExchangeError('QUALIFICATION_NO_STOP_ORDER_AUTHORIZED')

    def claim_transmission(self, action):
        self.check_action(action)
        p=self.proposal;key='certification_transmissions:'+p.identity;digest=fingerprint(action)
        with self.journal.transaction():
            history=self.journal.control(key) or []
            entry=action['type']=='order' and action['orders'][0]['r'] is False
            if (len(history)>=p.max_signed_actions or any(h['hash']==digest for h in history)
                    or entry and self.journal.control('qualification_entry_consumed')):
                raise ExchangeError('QUALIFICATION_ENTRY_OR_ACTION_ALREADY_CONSUMED')
            # Consume the one entry before HTTP, even if its result is unknown.
            if entry:self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                                             ('qualification_entry_consumed',json.dumps(p.identity)))
            history.append(dict(hash=digest,entry=entry,timestamp_ms=self.clock_ms()))
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(key,json.dumps(history)))


class QualificationSDKTransport(OfficialSDKTransport):
    def __init__(self,client,signer,team_address,nonces,authorization,*,rate_limits):
        if type(authorization) is not QualificationAuthorization:
            raise ExchangeError('QUALIFICATION_CAPABILITY_REQUIRED')
        authorization.require(team_address,signer.address)
        self.action_expiry_ms=authorization.approval.expires_ms
        super().__init__(client,signer,team_address,nonces,authorization,rate_limits=rate_limits)

    def check(self, action):
        super().check(action);self.authorization.check_action(action)
        if action.get('type')=='order' and action['orders'][0]['r'] is False:
            p=self.authorization.proposal
            if not residual_close_assessment(self.client.market(p.symbol),p.quantity,p.exit_bound)['ready']:
                raise ExchangeError('QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL')

    def transmit(self,payload):
        self.check(payload['action'])
        if payload.get('expiresAfter')!=self.action_expiry_ms:raise ExchangeError('QUALIFICATION_SIGNED_EXPIRY_REQUIRED')
        self.authorization.claim_transmission(payload['action'])
        return super().transmit(payload)


class QualificationExecution(HyperliquidExecution):
    def __init__(self,*args,proposal,**kwargs):
        super().__init__(*args,**kwargs);self.proposal=proposal.require()
    def _validated(self,request,permission,**kwargs):
        request,context,result,decision=super()._validated(request,permission,**kwargs)
        if not request.reduce_only:check_entry(context,request,self.proposal,self.client.clock_ms())
        return request,context,result,decision
    def _guard(self,context,checked_ms,**kwargs):
        super()._guard(context,checked_ms,**kwargs)
        if kwargs.get('entry'):
            p=self.proposal
            request=OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif='Ioc')
            check_entry(context,request,p,self.client.clock_ms())


class UnverifiedQualificationProtection:
    """Never builds or submits a stop; cannot be mistaken for certified protection."""
    managers={};states={};running=True;entries_allowed=True
    def _plan(self,*args):raise ExchangeError('QUALIFICATION_STOP_UNVERIFIED_EXPLICIT_RISK_ACCEPTANCE')


class QualificationSequence(CertificationSequence):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,verified_full_position_closes=True,**kwargs)
        if type(self.p) is not QualificationProposal:raise ExchangeError('QUALIFICATION_PROPOSAL_REQUIRED')
        self.e.protection=UnverifiedQualificationProtection()
    def run(self):
        r=super().run();r.update(execution_mode='TESTNET_QUALIFICATION',entry_rule=RULE,
            normal_protection_certified=False,certification_passed=False,
            organizer_whitelisting_confirmed=False,practice_ready=False,live_ready=False)
        stages=[]
        if r['status']!='PREFLIGHT_BLOCKED':stages.append('APPROVED_FOR_SINGLE_EXPERIMENT')
        if self.e.journal.control('qualification_entry_consumed')==self.p.identity:
            stages.append('ENTRY_SUBMITTED')  # Transmission attempted, not a fill claim.
        entry=r.get('entry',{})
        actual_quantity=decimal(entry.get('filled_quantity',0),nonnegative=True)
        matching=[f for f in self.e.recovery.state.fills.values()
                  if f.order_id==str(entry.get('exchange_order_id')) and f.symbol==self.p.symbol
                  and f.side=='BUY' and f.source=='EXCHANGE_REPORTED_FILL']
        if actual_quantity and sum((f.quantity for f in matching),D(0))==actual_quantity:
            stages.append('ENTRY_FILLED')
        elif r['status'] in {'NO_FILL_VERIFIED','ORDER_REJECTED'}:stages.append('ENTRY_NOT_FILLED')
        if r['status']=='TRADE_CLOSED_RECONCILED' and r.get('final_flat'):
            stages.append('EXIT_RECONCILED')
        if r['status']=='EMERGENCY_EXIT_REQUIRED':
            stages.append('EMERGENCY_EXIT_REQUIRED')
            r['recovery_steps']=[
                'Keep new entries locked; preserve journal, consumed attempt and original cloid/oid.',
                'Read saved orderStatus, team userFills, frontendOpenOrders and par positions; never blindly resubmit.',
                'Report exact residual or UNKNOWN if reads disagree; do not infer flat from local state.',
                'Halted/revoked/expired permissions cannot resume writes; obtain explicit recovery authorization outside bounds.']
        r['qualification_stages']=stages
        return r


def whitelist_trade_proof(sequence, result, *, actual_transport):
    """Only reported fills from the bound team-account observer, never SDK summaries."""
    p,e=sequence.p,sequence.e
    rows=[r for r in e.journal.intents() if r['intent_key']==sequence.prefix+'entry']
    oid=rows[0]['oid'] if len(rows)==1 else None
    fills=[f for f in e.recovery.state.fills.values() if f.order_id==str(oid) and f.symbol==p.symbol and f.side=='BUY']
    verified=(actual_transport is True and result.get('evidence_scope')=='ACTUAL_TESTNET_ACCOUNT'
        and e.account.team_address.lower()==p.team_wallet.lower() and len(rows)==1
        and rows[0]['state'] in {'FILLED','PARTIALLY_FILLED'} and bool(fills)
        and all(f.source=='EXCHANGE_REPORTED_FILL' for f in fills)
        and sum((f.quantity for f in fills),D(0))==decimal(json.loads(rows[0]['outcome'] or '{}').get('filled_quantity',0)))
    return dict(report_type='WHITELIST_TRADE_PROOF',status='ACTUAL_PRACTICE_FILL_VERIFIED' if verified else 'NO_ACTUAL_PRACTICE_FILL_VERIFIED',
        registered_wallet=p.team_wallet,approved_api_wallet=p.api_wallet,network='testnet',dex='par',market=p.symbol,
        exchange_order_id=oid,fill_verified=verified,fills=[asdict(f) for f in fills],
        executed_notional=str(sum((f.quantity*f.price for f in fills),D(0))) if verified else None,
        fill_ids=[f.trade_id for f in fills] if verified else [],timestamps_ms=[f.timestamp_ms for f in fills] if verified else [],
        account_reconciliation=e.recovery.state.report(),
        final_flat_verified=(actual_transport is True and result.get('final_flat') is True
                             and result.get('evidence_scope')=='ACTUAL_TESTNET_ACCOUNT'),
        final_flat_observed_in_scope=result.get('final_flat') is True,
        outcome_status=result['status'],evidence_scope=result.get('evidence_scope'),
        normal_protection_certified=False,organizer_whitelisting_confirmed=False,practice_ready=False,live_ready=False)


def require_qualification_regression(root, receipt_path):
    """Reuse only the full, current-source release; no approval is conferred."""
    from .paper_operations import active_source_hash
    import xml.etree.ElementTree as ET
    try:
        path=Path(receipt_path);receipt=json.loads(path.read_text());xml=path.parent/'regression.xml'
        source=active_source_hash(Path(root));totals={k:0 for k in ('tests','failures','errors','skipped')}
        for suite in ET.parse(xml).getroot().iter('testsuite'):
            for key in totals:totals[key]+=int(suite.attrib.get(key,0))
        valid=(receipt.get('passed') is True and receipt.get('source_hash')==source
            and receipt.get('source_hash_after')==source and totals==receipt['totals']
            and totals['tests']>=1682 and not any(totals[k] for k in ('failures','errors','skipped'))
            and hashlib.sha256(xml.read_bytes()).hexdigest()==receipt.get('xml_sha256')
            and set(receipt.get('checks_before',{}))=={'strategy_freeze','phase0'}
            and all(v['exit_code']==0 and v['result'].get('passed') is True
                    for v in receipt['checks_before'].values()))
        if valid:return path.resolve()
    except (OSError,ValueError,KeyError,TypeError,AttributeError,ET.ParseError):pass
    raise ExchangeError('SOURCE_BOUND_FULL_REGRESSION_REQUIRED')


def build_qualification(root,proposal,approval,*,state_directory,test_receipt):
    """Exact approval + source-bound regression + fresh read checks BEFORE actual key."""
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    from .paper_operations import active_source_hash
    from .reliability_policy import load_reliability_policy
    from .hyperliquid_client import HyperliquidClient
    from .hyperliquid_account import HyperliquidAccount
    from .hyperliquid_market_data import HyperliquidMarketData
    from .exchange_rules import HyperliquidOrderValidator
    from .execution_safety import ClockHealthMonitor,HyperliquidRateLimitManager,NonceManager
    from .practice_preflight import read_api_key,api_signer
    root,state=Path(root).resolve(),Path(state_directory).resolve()
    require_paper_migration();verify_strategy_freeze();proposal.require()
    if state!=root/'runtime/testnet/anchorium-bot-1':raise ExchangeError('EXISTING_CERTIFICATION_NONCE_DIRECTORY_REQUIRED')
    require_qualification_regression(root,test_receipt)
    old=state/'certification.sqlite'
    if old.exists():
        db=sqlite3.connect('file:'+str(old)+'?mode=ro',uri=True)
        try:
            if db.execute("SELECT COUNT(*) FROM intents WHERE state IN ('PREPARED','SUBMITTED','UNKNOWN','OPEN','PARTIALLY_FILLED')").fetchone()[0]:
                raise ExchangeError('PRIOR_CERTIFICATION_UNRESOLVED_REVIEW_REQUIRED')
        finally:db.close()
    journal=ExecutionJournal(state/'qualification.sqlite',session_id='anchorium-one-qualification-v1',team_address=proposal.team_wallet)
    client=nonces=transport=key=signer=None
    try:
        auth=QualificationAuthorization(proposal,approval,journal,clock_ms=lambda:time.time_ns()//1000000,
            source_hash=lambda:active_source_hash(root),policy_hash=lambda:hashlib.sha256((root/'configs/reliability_policy.json').read_bytes()).hexdigest())
        auth.require(proposal.team_wallet,proposal.api_wallet)
        if journal.control('qualification_entry_consumed') or journal.intents():
            raise ExchangeError('QUALIFICATION_PRIOR_ATTEMPT_READ_ONLY_RECOVERY_REQUIRED')
        rate,cp,protection=load_reliability_policy(root/'configs/reliability_policy.json')
        if protection.enabled:raise ExchangeError('QUALIFICATION_GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=proposal.api_wallet)
        client=HyperliquidClient(rate_limits=rates);client.startup()
        account,market=HyperliquidAccount(client,proposal.team_wallet),HyperliquidMarketData(client)
        if account.get_positions() or account.get_frontend_open_orders():raise ExchangeError('QUALIFICATION_INITIAL_FLAT_REQUIRED')
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**cp)
        recovery=CertificationRecovery(account,journal,initial_start_ms=0)
        provider=QualificationContextProvider(market,account,proposal.api_wallet,clock,rates,
            reconcile_before_load=recovery.recover,
            reconciliation_ready=lambda:recovery.account_truth_ready,feed_ready=lambda:True)
        provider.trigger_aware=True
        request=OrderRequest(proposal.symbol,'BUY',proposal.quantity,proposal.entry_limit,tif='Ioc',strategy_id='TESTNET_CERTIFICATION_ENTRY')
        ctx=provider.load(request);check_entry(ctx,request,proposal,client.clock_ms())
        validation=HyperliquidOrderValidator(client).validate(request,ctx,test_permission(request,proposal,client.clock_ms()),client.clock_ms())
        if not validation.allowed:raise ExchangeError(validation.code)
        # Executor guards have their own recovery sequence. Never revoke their
        # generation inside context loading; preserve central concurrency checks.
        provider.reconcile_before_load=None
        # Sole remote host is a human assertion; actual local nonce/account leases
        # are acquired below. No signer or nonce is constructed before consent.
        key,_=read_api_key(root);signer=api_signer(key,proposal.api_wallet,proposal.team_wallet);key=None
        nonces=NonceManager(state/'nonces.sqlite',signer.address,journal=journal)
        transport=QualificationSDKTransport(client,signer,proposal.team_wallet,nonces,auth,rate_limits=rates)
        executor=QualificationExecution(client,proposal=proposal,transport=transport,account=account,journal=journal,
            context_provider=provider,validator=HyperliquidOrderValidator(client),recovery=recovery,clock_health=clock,rate_limits=rates)
        return QualificationRuntime(QualificationSequence(executor,proposal,auth,wait=lambda:time.sleep(.5)),client,transport,nonces,journal)
    except Exception:
        if transport:transport.close()
        if nonces:nonces.close()
        if client:client.close()
        journal.close();raise
    finally:key=signer=None


class QualificationRuntime:
    def __init__(self,sequence,client,transport,nonces,journal):
        self.sequence,self.client,self.transport,self.nonces,self.journal=sequence,client,transport,nonces,journal
    def run(self):
        result=self.sequence.run()
        result['whitelist_trade_proof']=whitelist_trade_proof(self.sequence,result,
            actual_transport=type(self.transport) is QualificationSDKTransport)
        if result['whitelist_trade_proof']['fill_verified']:
            result['qualification_stages'].append('ACTUAL_PRACTICE_FILL_VERIFIED')
        return result
    def close(self):
        self.sequence.auth.revoke()
        try:self.sequence.e.recovery.checkpoint(clean=True)
        finally:
            self.transport.close();self.nonces.close();self.client.close();self.journal.close()
