"""One separately approved SELL-only recovery; no entry/strategy authority.

Reuse the existing exact-close validator, journal, nonce lease, SDK, signing
boundary and account reconciliation. Profit is an executable limit condition,
never a promise. Any actual attempt ends observation, including partial/unknown.
"""
from dataclasses import dataclass,asdict,replace
from decimal import Decimal as D
from pathlib import Path
import hashlib,json,time,uuid

from .base_exchange import ExchangeError,decimal
from .execution_journal import fingerprint
from .emergency_qualification import (EmergencyProposal,EmergencyExecution,EmergencySDKTransport,
    EmergencyContextProvider,permission,FIXED_PRICE,ENVELOPE_FIELDS)
from .sdk_transport import OfficialSDKTransport
from .qualification_intent_recovery import QualificationRecovery
from .reliability_policy import RequestPriority
from .testnet_certification import TEAM,API
from .order_lifecycle import OrderRequest
from .qualification_watcher import sweep

ENTRY_OID='62755970305'
ENTRY_TID='800659111758533'
ENTRY_MS=1792039590641
QUANTITY=D('.0002')
FULL_RECOVERY_BASELINE=2363
ACKS=('identities_and_sole_host','sell_only_exact_position','one_attempt_no_retry',
    'unprotected_partial_or_failed_exit','profit_is_not_guaranteed','bounded_window_no_extension')


def require_recovery_regression(root,receipt):
    from .emergency_qualification import require_emergency_regression
    path=require_emergency_regression(root,receipt)
    if json.loads(Path(path).read_text())['totals']['tests']<FULL_RECOVERY_BASELINE:
        raise ExchangeError('SOURCE_BOUND_FULL_RECOVERY_REGRESSION_REQUIRED')
    return path


def entry_evidence(fills):
    rows=[f for f in fills if f.symbol=='par:BTC']
    if (len(rows)!=1 or rows[0].order_id!=ENTRY_OID or rows[0].trade_id!=ENTRY_TID
            or rows[0].side!='BUY' or rows[0].quantity!=QUANTITY
            or rows[0].price!=D('81512') or rows[0].fee!=D('.014672') or rows[0].fee_token!='USDPR'
            or rows[0].source!='EXCHANGE_REPORTED_FILL' or rows[0].timestamp_ms!=ENTRY_MS):
        raise ExchangeError('RECOVERY_ORIGINAL_FILL_OR_POSITION_CHANGED')
    return rows[0]


def profit_floor(spec,quantity,cost,entry_fee,exit_fee,funding,buffer=D('.001')):
    if quantity<=0 or not 0<=exit_fee<1 or buffer<D('-.50'):
        raise ExchangeError('RECOVERY_INVALID_PROFIT_INPUTS')
    break_even=(cost+entry_fee-funding)/(quantity*(1-exit_fee))
    floor=spec.normalize_price((cost+entry_fee-funding+buffer)/(quantity*(1-exit_fee)),'SELL')
    return break_even,floor


@dataclass(frozen=True)
class RecoveryMandate:
    nonce:str
    created_ms:int
    approval_deadline_ms:int
    source_hash:str
    reliability_policy_hash:str
    envelope_hash:str
    minimum_sell:str
    mode:str='PROFIT_ONLY_EXIT'
    quantity:str='0.0002'
    minimum_net_profit:str='0.001'
    window_ms:int=600000
    maximum_exit_fee:str='0.003'
    team_wallet:str=TEAM
    api_wallet:str=API
    symbol:str='par:BTC'
    original_order_id:str=ENTRY_OID
    original_fill_id:str=ENTRY_TID

    def require(self):
        mode_ok=((self.mode=='PROFIT_ONLY_EXIT' and self.minimum_net_profit=='0.001' and self.window_ms==600000)
            or (self.mode=='BOUNDED_LOSS_EXIT' and self.minimum_net_profit=='-0.50' and self.window_ms==120000))
        if (not mode_ok or self.quantity!='0.0002' or self.symbol!='par:BTC'
                or self.team_wallet.lower()!=TEAM.lower() or self.api_wallet.lower()!=API.lower()
                or self.original_order_id!=ENTRY_OID or self.original_fill_id!=ENTRY_TID
                or self.maximum_exit_fee!='0.003' or decimal(self.minimum_sell)<D('80141')
                or type(self.created_ms) is not int or type(self.approval_deadline_ms) is not int
                or self.approval_deadline_ms!=self.created_ms+300000
                or len(self.nonce)!=32 or any(c not in '0123456789abcdef' for c in self.nonce)
                or len(self.envelope_hash)!=64 or not self.source_hash or not self.reliability_policy_hash):
            raise ExchangeError('INVALID_EXIT_ONLY_MANDATE')
        return self

    @property
    def identity(self):self.require();return fingerprint(asdict(self))

    def expires_at(self,accepted_ms):return accepted_ms+self.window_ms


@dataclass(frozen=True)
class RecoveryApproval:
    mandate_hash:str
    operator_acceptance:str
    accepted_ms:int
    expires_ms:int
    identities_and_sole_host:bool=False
    sell_only_exact_position:bool=False
    one_attempt_no_retry:bool=False
    unprotected_partial_or_failed_exit:bool=False
    profit_is_not_guaranteed:bool=False
    bounded_window_no_extension:bool=False

    def require(self,m,now):
        m.require()
        if (self.mandate_hash!=m.identity or not self.operator_acceptance.strip()
                or any(getattr(self,k) is not True for k in ACKS)
                or type(self.accepted_ms) is not int or type(self.expires_ms) is not int
                or not m.created_ms<=self.accepted_ms<=m.approval_deadline_ms
                or self.expires_ms!=m.expires_at(self.accepted_ms)
                or not self.accepted_ms<=now<self.expires_ms):
            raise ExchangeError('EXACT_EXIT_ONLY_APPROVAL_REQUIRED')


class ExitRecovery(QualificationRecovery):
    def recover(self):
        rates=self.account.client.rate_limits
        if rates is None:raise ExchangeError('RECOVERY_SHARED_RATE_BUDGET_REQUIRED')
        # Prior entry failed in an unpaced direct recovery call, outside the
        # context provider's bounded read wrapper. Never reset the rate counter.
        rates.wait_for_read_budget(500,priority=RequestPriority.SAFETY,max_wait_seconds=65,
            cancel_event=self.account.client.read_cancel_event)
        old=rates.read_budget_wait_seconds;rates.read_budget_wait_seconds=65
        try:return super().recover()
        finally:rates.read_budget_wait_seconds=old


class RecoveryProvider(EmergencyContextProvider):
    def fee_scale(self):
        rows=self.client.post_info('perpDexs',priority=RequestPriority.SAFETY)
        rows=[r for r in rows if isinstance(r,dict) and r.get('name')=='par']
        if len(rows)!=1:raise ExchangeError('RECOVERY_CURRENT_DEX_REQUIRED')
        # Some testnet versions omit this field. Do not invent a current scale:
        # use the documented maximum all-in multiplier of six as an upper bound.
        raw=rows[0].get('deployerFeeScale')
        scale=decimal(raw,nonnegative=True) if raw is not None else None
        if scale is not None and scale>10:raise ExchangeError('RECOVERY_FEE_SCALE_OUT_OF_RANGE')
        self.current_fee_scale=scale;self.fee_scale_ms=self.client.last_received_ms

    def load(self,request,*,critical=False):
        self.rate_limits.wait_for_read_budget(800,priority=RequestPriority.DECISION,max_wait_seconds=65,
            cancel_event=self.client.read_cancel_event)
        metadata,_=self.client.post_info('metaAndAssetCtxs',priority=RequestPriority.SAFETY)
        self.client.validate_metadata(metadata)
        if fingerprint(metadata)!=self.metadata_hash:raise ExchangeError('RECOVERY_METADATA_CHANGED')
        self.client.metadata_timestamp_ms=self.client.last_received_ms
        self.fee_scale()
        return super().load(request,critical=True)

    def refresh_for_signing(self,request,recovery,own_intent):
        self.fee_scale()
        return super().refresh_for_signing(request,recovery,own_intent)

    def conservative_fee(self,context):
        if not 0<=self.client.clock_ms()-self.fee_scale_ms<=60000:
            raise ExchangeError('RECOVERY_FEE_SCALE_STALE')
        s=self.current_fee_scale
        # Official HIP-3 fee formula. Ignore fee-reducing growth/referral/aligned
        # discounts: this is an explicit conservative upper bound, not a rebate.
        return decimal(context.readiness.fees['userCrossRate'])*(6 if s is None else 1+s if s<1 else 2*s)


class ExitAuthorization:
    def __init__(self,p,m,a,journal,acceptance_path,*,clock_ms,source_hash,policy_hash):
        self.proposal,self.mandate,self.approval,self.journal=p,m,a,journal
        self.path=Path(acceptance_path);self.clock_ms=clock_ms
        self.source_hash,self.policy_hash=source_hash,policy_hash
        self.revoked=False;self.token=uuid.uuid4().hex;self.current=None

    def require(self,team,signer):
        from venue_config import require_paper_migration
        require_paper_migration();m=self.mandate;now=self.clock_ms()
        self.approval.require(m,now)
        try:current=json.loads(self.path.read_text())
        except (OSError,ValueError):raise ExchangeError('RECOVERY_APPROVAL_REVOKED') from None
        if (current!=asdict(self.approval) or self.path.with_name('recovery_revocation.json').exists()
                or self.revoked or team.lower()!=m.team_wallet.lower() or signer.lower()!=m.api_wallet.lower()
                or self.journal.team_address!=m.team_wallet.lower() or self.source_hash()!=m.source_hash
                or self.proposal.identity!=m.envelope_hash
                or self.policy_hash()!=m.reliability_policy_hash
                or self.journal.control('exit_recovery_finished:'+m.identity)):
            raise ExchangeError('RECOVERY_AUTHORITY_OR_SOURCE_REVOKED')
        prior=self.journal.control('exit_recovery_started:'+m.identity)
        if prior and prior!=self.token:raise ExchangeError('RECOVERY_RESTART_READ_ONLY_REQUIRED')

    def register(self):
        self.require(TEAM,API)
        with self.journal.transaction():
            if self.journal.control('exit_recovery_started:'+self.mandate.identity):
                raise ExchangeError('RECOVERY_RESTART_READ_ONLY_REQUIRED')
            self.journal.db.execute('INSERT INTO controls VALUES (?,?)',
                ('exit_recovery_started:'+self.mandate.identity,json.dumps(self.token)))

    def require_context(self,e,context,request,*,select=False):
        self.require(TEAM,API);m=self.mandate;now=self.clock_ms()
        if m.mode=='PROFIT_ONLY_LONG_SESSION' and now+m.reconciliation_reserve_ms>=self.approval.expires_ms:
            raise ExchangeError('LONG_SESSION_SIGNING_CUTOFF')
        held=context.positions.get('par:BTC')
        if (request.symbol!='par:BTC' or request.side!='SELL' or not request.reduce_only or request.tif!='Ioc'
                or request.quantity!=QUANTITY or len(context.positions)!=1 or held is None or held.quantity!=QUANTITY
                or context.open_orders or not context.reconciled or not context.readiness.account_ready
                or context.active_asset.get('leverage')!=dict(type='cross',value=1)):
            raise ExchangeError('RECOVERY_EXACT_LONG_OR_ACCOUNT_CHANGED')
        entry=entry_evidence(e.recovery.state.fills.values())
        if e.recovery.state.last_window is None or not 0<=now-e.recovery.state.last_window[1]<=60000:
            raise ExchangeError('RECOVERY_FRESH_FUNDING_HISTORY_REQUIRED')
        funding=sum((f.cashflow for f in e.recovery.state.funding.values() if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS),D(0))
        fee=e.context_provider.conservative_fee(context)
        if fee>decimal(m.maximum_exit_fee):raise ExchangeError('RECOVERY_FEE_ABOVE_APPROVED_BOUND')
        cost=entry.quantity*entry.price
        be,computed=profit_floor(context.spec,QUANTITY,cost,entry.fee,fee,funding,decimal(m.minimum_net_profit))
        floor=max(decimal(m.minimum_sell),computed)
        if m.mode=='PROFIT_ONLY_LONG_SESSION':
            floor=max(floor,decimal(self.journal.control('exit_long_profit_floor:'+m.identity) or m.minimum_sell))
        q=context.quote
        if not 0<=now-q.timestamp_ms<=5000 or q.ask<=q.bid or (q.ask-q.bid)/q.mid*10000>50:
            raise ExchangeError('RECOVERY_FRESH_SPREAD_REQUIRED')
        book=e.context_provider.books['par:BTC']
        px=context.spec.normalize_price(max(floor,q.bid*D('.999')),'SELL') if select else request.price
        if px<floor:raise ExchangeError('RECOVERY_APPROVED_PROFIT_FLOOR_REQUIRED')
        if px>q.bid:raise ExchangeError('RECOVERY_PROFIT_NOT_EXECUTABLE')
        if px<context.spec.normalize_price(q.bid*D('.998'),'SELL'):
            raise ExchangeError('RECOVERY_CURRENT_BID_TOLERANCE_REQUIRED')
        depth=sweep(book.bids,QUANTITY,px,'SELL')
        if decimal(depth['available_quantity'])*D('.5')<QUANTITY:
            raise ExchangeError('RECOVERY_EXIT_DEPTH_REQUIRED')
        net=QUANTITY*px*(1-fee)-cost-entry.fee+funding
        if net<decimal(m.minimum_net_profit):raise ExchangeError('RECOVERY_APPROVED_NET_BOUND_REQUIRED')
        self.current=dict(price=px,quantity=QUANTITY,checked_ms=now,floor=floor,
            fee_upper_bound=fee,funding=funding,break_even=be,estimated_minimum_net=net)
        e.journal.event('EXIT_RECOVERY_PROFIT_CHECK',now,**self.current)
        return px

    def check_action(self,action):
        self.require(TEAM,API);p=self.proposal
        if (self.mandate.mode=='PROFIT_ONLY_LONG_SESSION'
                and self.clock_ms()+self.mandate.reconciliation_reserve_ms>=self.approval.expires_ms):
            raise ExchangeError('LONG_SESSION_SIGNING_CUTOFF')
        if action.get('type')!='order' or len(action.get('orders',[]))!=1:
            raise ExchangeError('RECOVERY_SELL_ONLY_NO_ADMIN_OR_CANCEL')
        w=action['orders'][0];row=self.journal.db.execute('SELECT * FROM intents WHERE cloid=?',(w.get('c'),)).fetchone()
        if (row is None or row['intent_key']!='certification:'+p.identity+':exit:0'
                or w.get('a')!=p.asset_id or w.get('b') is not False or w.get('r') is not True
                or decimal(w.get('s'))!=QUANTITY or w.get('t')!={'limit':{'tif':'Ioc'}}
                or self.current is None or not 0<=self.clock_ms()-self.current['checked_ms']<=5000
                or decimal(w.get('p'))!=self.current['price'] or decimal(w['p'])<self.current['floor']):
            raise ExchangeError('RECOVERY_EXACT_FRESH_SELL_ONLY_REQUIRED')

    def claim_transmission(self,action):
        self.check_action(action);key='exit_recovery_transmission:'+self.mandate.identity
        with self.journal.transaction():
            if self.journal.control(key):raise ExchangeError('RECOVERY_SINGLE_ATTEMPT_CONSUMED')
            self.journal.db.execute('INSERT INTO controls VALUES (?,?)',
                (key,json.dumps(dict(action_hash=fingerprint(action),timestamp_ms=self.clock_ms()))))

    def revoke(self):
        self.revoked=True
        self.journal.control('exit_recovery_finished:'+self.mandate.identity,self.clock_ms())


class ExitTransport(EmergencySDKTransport):
    def __init__(self,client,signer,team,nonces,auth,*,rate_limits):
        if type(auth) is not ExitAuthorization:raise ExchangeError('EXACT_EXIT_CAPABILITY_REQUIRED')
        auth.require(team,signer.address);self.action_expiry_ms=auth.approval.expires_ms
        OfficialSDKTransport.__init__(self,client,signer,team,nonces,auth,rate_limits=rate_limits)


class ExitExecution(EmergencyExecution):
    def submit(self,*a,**k):raise ExchangeError('RECOVERY_NO_ENTRY_SUBMISSION')

    def _prepare_context_request(self,request,risk,context):
        px=self.transport.authorization.require_context(self,context,request,select=True)
        request=replace(request,price=px)
        return request,permission(request,self.proposal,self.client.clock_ms(),reason='EXACT_FULL_POSITION_CLOSE')

    def _guard(self,context,checked_ms,**kwargs):
        super()._guard(context,checked_ms,**kwargs)
        request=kwargs.get('exact_full_close')
        if request is None:raise ExchangeError('RECOVERY_EXACT_FULL_CLOSE_ONLY')
        if self.signing_boundary.current is not None:
            context,_=self.signing_boundary.context_for(request)
        self.transport.authorization.require_context(self,context,request)


def historical_envelope(root,source,policy,observed_ms):
    path=Path(root)/'docs/qualification_2026-10-15/session_preparation/authorized_session/selected_proposal.json'
    original=EmergencyProposal(**json.loads(path.read_text()))
    # Retain the actual original envelope as provenance; it grants no BUY right.
    values=dict(source_hash=source,reliability_policy_hash=policy,observed_ms=observed_ms)
    return replace(original,**values).require()


class Environment:
    def __init__(self,root,*,cancel=None):
        from .execution_journal import ExecutionJournal
        from .execution_safety import HyperliquidRateLimitManager,ClockHealthMonitor
        from .hyperliquid_client import HyperliquidClient
        from .hyperliquid_account import HyperliquidAccount
        from .hyperliquid_market_data import HyperliquidMarketData
        from .reliability_policy import load_reliability_policy
        from .paper_operations import active_source_hash
        self.root=Path(root);self.source=active_source_hash(self.root)
        self.policy_hash=hashlib.sha256((self.root/'configs/reliability_policy.json').read_bytes()).hexdigest()
        self.journal=ExecutionJournal(self.root/'runtime/testnet/anchorium-bot-1/qualification.sqlite',
            session_id='anchorium-one-qualification-v1',team_address=TEAM)
        rate,clock,protection=load_reliability_policy(self.root/'configs/reliability_policy.json')
        if protection.enabled:raise ExchangeError('RECOVERY_PROTECTION_MUST_REMAIN_DISABLED')
        self.rates=HyperliquidRateLimitManager(self.journal,policy=rate,signer_address=API)
        self.rates.read_budget_wait_seconds=65
        self.client=HyperliquidClient(rate_limits=self.rates);self.client.read_cancel_event=cancel
        self.client.startup();self.account=HyperliquidAccount(self.client,TEAM)
        self.market=HyperliquidMarketData(self.client)
        self.clock=ClockHealthMonitor(clock_ms=self.client.clock_ms,journal=self.journal,**clock)
        self.recovery=ExitRecovery(self.account,self.journal,initial_start_ms=0)
        self.provider=RecoveryProvider(self.market,self.account,API,self.clock,self.rates,
            reconcile_before_load=self.recovery.recover,
            reconciliation_ready=lambda:self.recovery.account_truth_ready,feed_ready=lambda:True)

    def context(self):
        request=OrderRequest('par:BTC','SELL',QUANTITY,'81664',reduce_only=True,
            strategy_id='TESTNET_CERTIFICATION_EXIT',tif='Ioc')
        context=self.provider.load(request,critical=True)
        entry=entry_evidence(self.recovery.state.fills.values())
        if (len(context.positions)!=1 or context.positions['par:BTC'].quantity!=QUANTITY or context.open_orders):
            raise ExchangeError('RECOVERY_POSITION_OR_ORDER_CHANGED')
        return context,entry

    def close(self):
        self.client.close();self.journal.close()


def prepare(root,directory,receipt,*,immediate_loss=False,full_day=False):
    from .emergency_qualification import require_emergency_regression
    from .paper_operations import atomic_json,active_source_hash
    from .practice_preflight import verify_private_identity,check_local_nonce_ownership
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    require_paper_migration();verify_strategy_freeze();require_recovery_regression(root,receipt)
    if immediate_loss and full_day:raise ExchangeError('DISTINCT_LOSS_OR_PROFIT_MANDATE_REQUIRED')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    env=Environment(root)
    try:
        identity=verify_private_identity(root,API,TEAM)
        lease=check_local_nonce_ownership(Path(root)/'runtime/testnet/anchorium-bot-1/nonces.sqlite',API,TEAM,root=root)
        context,entry=env.context();now=env.client.clock_ms()
        fee=env.provider.conservative_fee(context)
        funding=sum((f.cashflow for f in env.recovery.state.funding.values() if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS),D(0))
        be,floor=profit_floor(context.spec,QUANTITY,entry.quantity*entry.price,entry.fee,fee,funding)
        if immediate_loss:floor=max(D('80141'),context.spec.normalize_price(context.quote.bid*D('.998'),'SELL'))
        proposal=historical_envelope(root,env.source,env.policy_hash,now)
        m=RecoveryMandate(uuid.uuid4().hex,now,now+300000,env.source,env.policy_hash,proposal.identity,str(floor),
            **(dict(mode='BOUNDED_LOSS_EXIT',minimum_net_profit='-0.50',window_ms=120000) if immediate_loss else {})).require()
        if full_day:
            from .profit_only_session import full_day_mandate
            m=full_day_mandate(m)
        atomic_json(directory/'mandate.json',asdict(m));atomic_json(directory/'historical_envelope.json',asdict(proposal))
        q=context.quote;book=env.provider.books['par:BTC']
        planned=context.spec.normalize_price(max(floor,q.bid*D('.999')),'SELL')
        depth=sweep(book.bids,QUANTITY,planned,'SELL')
        executable=(q.bid>=planned and (q.ask-q.bid)/q.mid*10000<=50
            and decimal(depth['available_quantity'])*D('.5')>=QUANTITY)
        report=dict(status='AWAITING_EXACT_RECOVERY_APPROVAL',mandate_id=m.identity,mandate=asdict(m),
            position=asdict(context.positions['par:BTC']),orders=list(context.open_orders),readiness=asdict(context.readiness),
            identity=identity,lease=lease,observed_ms=now,bid=str(q.bid),ask=str(q.ask),
            spread_bps=str((q.ask-q.bid)/q.mid*10000),book=asdict(book),conservative_exit_fee=str(fee),
            fee_scale=str(env.provider.current_fee_scale),fee_model='Official HIP-3 upper bound; absent scale uses maximum 6x; fee-reducing discounts ignored',
            funding=str(funding),break_even=str(be),minimum_sell=str(floor),currently_executable=executable,
            planned_limit=str(planned),exit_price_rule='FRESH_BID_MINUS_10_BPS; FINAL_20_BPS_CEILING_ON_ALLOWANCE',depth=depth,
            estimated_net_at_bid=str(QUANTITY*q.bid*(1-fee)-entry.quantity*entry.price-entry.fee+funding),
            signed_actions=0,protection_verified=False,organizer_whitelisting_confirmed=False)
        assert active_source_hash(Path(root))==m.source_hash
        atomic_json(directory/'proposal.json',report);return report
    finally:env.close()


def execute(root,directory,mandate,approval,acceptance_path,receipt):
    """One approved ten-minute observer, at most one durable SELL attempt."""
    from .par_retirement import reject_retired_par_write
    reject_retired_par_write()
    from .emergency_qualification import require_emergency_regression
    from .paper_operations import atomic_json,active_source_hash,PaperOwner
    from .practice_preflight import read_api_key,api_signer,verify_private_identity
    from .execution_safety import NonceManager
    from .exchange_rules import HyperliquidOrderValidator
    from .qualification_watcher import PublicBookStream,PublicBookReader
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    import threading,signal
    require_paper_migration();verify_strategy_freeze();require_recovery_regression(root,receipt)
    now=time.time_ns()//1000000;approval.require(mandate,now)
    if active_source_hash(Path(root))!=mandate.source_hash:raise ExchangeError('RECOVERY_SOURCE_CHANGED')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    result=dict(status='READ_ONLY_PROFIT_OBSERVATION',mandate_id=mandate.identity,
        evidence_scope='ACTUAL_TESTNET_ACCOUNT',entry_orders_submitted=0,exit_attempted=False,
        final_flat=False,realized_pnl=None,protection_verified=False,organizer_whitelisting_confirmed=False)
    env=nonces=transport=stream=owner=auth=None;cancel=threading.Event();observer=None;old_term=None
    try:
        owner=PaperOwner(Path(root)/'runtime/testnet/anchorium-bot-1/exit-recovery.lock')
        env=Environment(root,cancel=cancel);proposal=historical_envelope(root,mandate.source_hash,mandate.reliability_policy_hash,mandate.created_ms)
        if proposal.identity!=mandate.envelope_hash:raise ExchangeError('RECOVERY_HISTORICAL_ENVELOPE_CHANGED')
        auth=ExitAuthorization(proposal,mandate,approval,env.journal,acceptance_path,
            clock_ms=env.client.clock_ms,source_hash=lambda:active_source_hash(Path(root)),
            policy_hash=lambda:hashlib.sha256((Path(root)/'configs/reliability_policy.json').read_bytes()).hexdigest())
        auth.register();verify_private_identity(root,API,TEAM)
        nonces=NonceManager(Path(root)/'runtime/testnet/anchorium-bot-1/nonces.sqlite',API,journal=env.journal)
        context,entry=env.context();last_account=env.client.clock_ms()
        stream=PublicBookStream(['par:BTC'],env.rates,clock_ms=env.client.clock_ms);stream.start()
        reader=PublicBookReader(env.market,stream)
        if mandate.mode=='PROFIT_ONLY_LONG_SESSION':
            from .profit_only_session import LongSessionObserver
            observer=LongSessionObserver(env,mandate,approval,context,entry)
            if threading.current_thread() is threading.main_thread():
                old_term=signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
        e=None
        while True:
            if env.client.clock_ms()>=approval.expires_ms:
                result['status']='PROFIT_WINDOW_EXPIRED_NO_SELL';break
            auth.require(TEAM,API)
            if not nonces.healthy:raise ExchangeError('NONCE_SIGNING_DEGRADED')
            if observer is None and env.client.clock_ms()+15000>=approval.expires_ms:
                result['status']='PROFIT_WINDOW_EXPIRED_NO_SELL';break
            if observer:
                context,entry=observer.refresh_if_due()
            elif env.client.clock_ms()-last_account>=30000:
                context,entry=env.context();last_account=env.client.clock_ms()
            book,origin=reader.get('par:BTC')
            report=dict(at_ms=env.client.clock_ms(),transport=origin,bid=str(book.bids[0].price) if book and book.bids else None,
                minimum_sell=mandate.minimum_sell,expires_ms=approval.expires_ms)
            candidate=False
            if observer:
                report=observer.observation(book,origin,stream.report())
                candidate=report['candidate']
            with (directory/'observations.jsonl').open('a') as f:f.write(json.dumps(report,default=str)+'\n')
            atomic_json(directory/'health.json',dict(report,status=result['status'],lease_healthy=nonces.healthy))
            if observer:
                if not candidate:cancel.wait(1);continue
                # Refresh all authoritative evidence before entering the single
                # closing path. A market-only candidate is never signing evidence.
                context,entry=observer.refresh_candidate()
                book=env.provider.last_book
                report=observer.observation(book,'FRESH_CLOSING_PREFLIGHT',stream.report(),preflight=True)
                if not report['candidate']:cancel.wait(1);continue
                observer.claim_closing_path(auth)
            if not book or not book.bids or book.bids[0].price<decimal(mandate.minimum_sell):
                cancel.wait(1);continue
            if e is None:
                # Actual key and SDK are constructed only under genuine approval
                # and an observed executable candidate; no nonce yet allocated.
                stream.close()
                key,_=read_api_key(root)
                try:signer=api_signer(key,API,TEAM)
                finally:key=None
                transport=ExitTransport(env.client,signer,TEAM,nonces,auth,rate_limits=env.rates);signer=None
                e=ExitExecution(env.client,proposal=proposal,transport=transport,account=env.account,
                    journal=env.journal,context_provider=env.provider,validator=HyperliquidOrderValidator(env.client),
                    recovery=env.recovery,clock_health=env.clock,rate_limits=env.rates)
            request=OrderRequest('par:BTC','SELL',QUANTITY,mandate.minimum_sell,reduce_only=True,
                strategy_id='TESTNET_CERTIFICATION_EXIT',tif='Ioc',
                client_order_id='certification:'+proposal.identity+':exit:0')
            try:
                order=e.close_full_position(request,permission=permission(request,proposal,env.client.clock_ms(),reason='EXACT_FULL_POSITION_CLOSE'))
            except ExchangeError as exc:
                if observer is None and env.journal.intent(request.client_order_id) is None and str(exc) in {
                        'RECOVERY_PROFIT_NOT_EXECUTABLE','RECOVERY_EXIT_DEPTH_REQUIRED','RECOVERY_FRESH_SPREAD_REQUIRED'}:
                    cancel.wait(2);continue
                raise
            result.update(exit_attempted=True,order=asdict(order))
            # No second submission, even after zero/partial/rejected/uncertain.
            if order.state.value in {'UNKNOWN','SUBMITTED'}:
                order=e.recover_uncertain(order.intent_key);result['order']=asdict(order)
            for _ in range(2):
                env.recovery.recover()
                positions=env.account.get_positions();orders=env.account.get_frontend_open_orders()
                result.setdefault('account_readback',[]).append(dict(observed_ms=env.client.clock_ms(),
                    positions=[asdict(p) for p in positions.values()],orders=orders,
                    reconciliation=asdict(env.recovery.last_report)))
            fills=list(env.recovery.state.fills.values());entries=[f for f in fills if f.order_id==ENTRY_OID]
            exits=[f for f in fills if f.order_id==str(order.exchange_order_id) and f.side=='SELL']
            final=result['account_readback'][-1]
            flat=all(not snap['positions'] and not snap['orders'] and snap['reconciliation']['ready']
                for snap in result['account_readback'])
            if flat and sum((f.quantity for f in exits),D(0))==QUANTITY:
                proceeds=sum((f.price*f.quantity for f in exits),D(0));fees=sum((f.fee for f in exits),D(0))+sum((f.fee for f in entries),D(0))
                funding=sum((f.cashflow for f in env.recovery.state.funding.values() if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS),D(0))
                if (any(f.source!='EXCHANGE_REPORTED_FILL' or f.fee_token!='USDPR' or f.closed_pnl is None for f in entries+exits)
                        or len({f.identity for f in entries+exits})!=len(entries+exits)
                        or abs(sum((f.closed_pnl for f in entries+exits),D(0))-(proceeds-D('16.3024')))>D('.000001')):
                    raise ExchangeError('RECOVERY_ACTUAL_ACCOUNTING_MISMATCH')
                result.update(status='CLOSED_EXCHANGE_VERIFIED',final_flat=True,
                    realized_pnl=str(proceeds-D('16.3024')-fees+funding),actual_fees=str(fees),actual_funding=str(funding))
            else:result['status']='EMERGENCY_EXIT_REQUIRED'
            result['fills']=[asdict(f) for f in entries+exits];break
    except (Exception,KeyboardInterrupt) as exc:
        result.update(status='RECOVERY_HALTED',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,operator_action_required=True)
        if env and auth:
            own=env.journal.intent('certification:'+auth.proposal.identity+':exit:0')
            result['exit_attempted']=own is not None
    finally:
        if old_term is not None:signal.signal(signal.SIGTERM,old_term)
        if auth:auth.revoke()
        if stream:
            try:stream.close()
            except Exception as exc:
                result.update(shutdown_error=str(exc),operator_action_required=True)
        if env:
            try:
                env.recovery.recover()
                positions=env.account.get_positions();orders=env.account.get_frontend_open_orders()
                result['final_read_only']=dict(observed_ms=env.client.clock_ms(),
                    positions=[asdict(p) for p in positions.values()],orders=orders,
                    reconciliation=asdict(env.recovery.last_report),
                    fills=[asdict(f) for f in env.recovery.state.fills.values()],
                    funding=[asdict(f) for f in env.recovery.state.funding.values()])
            except Exception as exc:result['final_read_only_error']=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__
        if transport:transport.close()
        if nonces:nonces.close()
        if env:env.close()
        if owner:owner.close()
        result.update(finished_ms=time.time_ns()//1000000,no_automatic_retry=True,
            source_hash_after=active_source_hash(Path(root)),practice_ready=False,live_ready=False)
        if observer:result['long_session_observation']=observer.summary()
        atomic_json(directory/'result.json',result)
    return result
