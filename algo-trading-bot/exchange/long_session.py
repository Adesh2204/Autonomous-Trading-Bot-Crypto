"""Isolated, exact-approved LONG session using the existing execution stack.

No observer obtains this capability. No key is read during proposal, evidence or
approval validation. An offline fixture is never accepted by the actual builder.
Native protection qualification and partial-lot minimums are independent gates.
"""
from dataclasses import dataclass,asdict,replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,os,socket,time

from .base_exchange import ExchangeError,decimal
from .execution_journal import canonical,fingerprint
from .bounded_daily_session import DailyMandate,DailyLifecycle,TradeState
from .capital_allocation import CapitalLimits,allocate
from .sdk_transport import OfficialSDKTransport,OfflineSDKTransport
from .hyperliquid_execution import HyperliquidExecution
from .testnet_certification import TEAM,API
from .live_recovery import LiveAccountRecovery
from .position_protection import ExchangeProtectionManager

ACKS=('wallets_and_sole_host','exact_long_scope','loss_making_risk_exits',
      'partial_unknown_no_blind_retry','stop_slippage_and_outage_risk','no_extension')


@dataclass(frozen=True)
class LongMandate:
    daily: DailyMandate
    created_ms: int
    approval_deadline_ms: int
    release_sha256: str
    reliability_sha256: str
    protection_evidence_sha256: str
    protection_policy_sha256: str
    maximum_close_attempts_per_cycle: int=2
    maximum_signed_actions: int=12
    maximum_protection_actions_per_cycle: int=2
    maximum_cancel_actions: int=2
    maximum_fee_rate: str='0.003'
    maximum_spread_bps: str='15'
    execution_slippage_bps: str='5'
    depth_participation: str='0.1'
    entry_cutoff_buffer_ms: int=120000
    allow_loss_making_risk_exits: bool=True
    native_order_type: str='Stop Limit'
    mode: str='EXACT_APPROVED_STRATEGY_LONG_TESTNET_V1'

    def require(self):
        d=self.daily.require()
        if type(self) is not LongMandate:
            from .overnight_session import OvernightLongMandate
            from .practice_weekend_session import PracticeWeekendLongMandate
            from .scored_session import ScoredLongMandate
            if type(self) not in {OvernightLongMandate,PracticeWeekendLongMandate,ScoredLongMandate}:raise ExchangeError('EXACT_LONG_CONTRACT_TYPE_REQUIRED')
        self.require_contract(d)
        if (d.directions!=('LONG',)
                or d.team_wallet.lower()!=TEAM.lower() or d.api_wallet.lower()!=API.lower()
                or type(self.created_ms) is not int or type(self.approval_deadline_ms) is not int
                or self.approval_deadline_ms!=self.created_ms+300000
                or not d.starts_ms<=self.created_ms<self.approval_deadline_ms<d.expires_ms
                or self.allow_loss_making_risk_exits is not True
                or self.native_order_type!='Stop Limit'
                or any(type(v) is not int for v in (self.maximum_close_attempts_per_cycle,self.maximum_signed_actions,
                    self.maximum_protection_actions_per_cycle,self.maximum_cancel_actions,self.entry_cutoff_buffer_ms))
                or not 1<=self.maximum_close_attempts_per_cycle<=2 or not 1<=self.maximum_signed_actions<=12
                or not 1<=self.maximum_protection_actions_per_cycle<=2 or not 0<=self.maximum_cancel_actions<=2
                or self.entry_cutoff_buffer_ms<120000
                or not 0<decimal(self.maximum_fee_rate)<=D('.003')
                or not 0<decimal(self.maximum_spread_bps)<=15
                or not 0<=decimal(self.execution_slippage_bps)<=5
                or not 0<decimal(self.depth_participation)<=D('.1')):
            raise ExchangeError('INVALID_EXACT_LONG_MANDATE')
        import re
        if any(not re.fullmatch('[0-9a-f]{64}',v) for v in (self.release_sha256,self.reliability_sha256,
                self.protection_evidence_sha256,self.protection_policy_sha256)):
            raise ExchangeError('LONG_EVIDENCE_HASHES_REQUIRED')
        return self

    def require_contract(self,d):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        end=datetime.fromtimestamp(d.expires_ms/1000,ZoneInfo('Asia/Calcutta'))
        start=datetime.fromtimestamp(d.starts_ms/1000,ZoneInfo('Asia/Calcutta'))
        if (type(d) is not DailyMandate or self.mode!='EXACT_APPROVED_STRATEGY_LONG_TESTNET_V1'
                or start.date()!=end.date() or (end.hour,end.minute,end.second,end.microsecond)>(23,57,0,0)):
            raise ExchangeError('INVALID_EXACT_LONG_MANDATE')

    @property
    def identity(self):self.require();return fingerprint(asdict(self))


def read_mandate(path):
    data=json.loads(Path(path).read_text())
    if data.get('mode')=='EXACT_APPROVED_SCORED_PAS_LONG_TESTNET_V1':
        from .scored_session import ScoredLimits,ScoredLongMandate
        data['daily']=ScoredLimits(**data['daily'])
        return ScoredLongMandate(**data).require()
    if data.get('mode')=='EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1':
        from .practice_weekend_session import PracticeWeekendLimits,PracticeWeekendLongMandate
        data['daily']=PracticeWeekendLimits(**data['daily'])
        return PracticeWeekendLongMandate(**data).require()
    if data.get('mode')=='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1':
        from .overnight_session import OvernightLimits,OvernightLongMandate
        data['daily']=OvernightLimits(**data['daily'])
        return OvernightLongMandate(**data).require()
    data['daily']=DailyMandate(**data['daily'])
    return LongMandate(**data).require()


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_release(root,path,expected_source,expected_sha):
    from .paper_operations import active_source_hash
    p=Path(path);r=json.loads(p.read_text());xml=p.parent/'regression.xml'
    if (sha(p)!=expected_sha or r.get('passed') is not True or r.get('exit_code')!=0
            or r.get('source_hash')!=expected_source or r.get('source_hash_after')!=expected_source
            or active_source_hash(Path(root))!=expected_source or r.get('totals',{}).get('tests',0)<2494
            or any(r['totals'].get(k)!=0 for k in ('failures','errors','skipped'))
            or sha(xml)!=r.get('xml_sha256')
            or any(r.get(stage,{}).get(check,{}).get('result',{}).get('passed') is not True
                for stage in ('checks_before','checks_after') for check in ('strategy_freeze','phase0'))):
        raise ExchangeError('MATCHING_COMPLETE_LONG_RELEASE_REQUIRED')
    if r.get('requirements_sha256') is not None:
        import importlib.metadata
        if sha(Path(root)/'algo-trading-bot/requirements.txt')!=r['requirements_sha256']:
            raise ExchangeError('LONG_RELEASE_DEPENDENCY_FILE_CHANGED')
        if any(importlib.metadata.version(name)!=version for name,version in r.get('runtime_versions',{}).items()):
            raise ExchangeError('LONG_RELEASE_DEPENDENCY_VERSION_CHANGED')


def require_native_evidence(path,daily):
    """Derive qualification from raw account replies, never a passed/ready flag.

    Trigger execution remains a separate fact from mere stop acceptance. This
    unattended path requires actual closing SELL fills linked to the trigger.
    """
    from .venue_profiles import venue_profile
    profile=venue_profile(daily.dex)
    p=Path(path);proof=json.loads(p.read_text());raw=p.parent/proof['receipt_file']
    if (proof.get('network')!='testnet' or proof.get('dex')!=profile.dex
            or proof.get('team_wallet','').lower()!=daily.team_wallet.lower()
            or proof.get('api_wallet','').lower()!=daily.api_wallet.lower()
            or proof.get('source')!='ACTUAL_NATIVE_PROTECTION_QUALIFICATION'
            or sha(raw)!=proof.get('receipt_sha256')):
        raise ExchangeError('ACTUAL_NATIVE_PROTECTION_EVIDENCE_REQUIRED')
    rows=[json.loads(line) for line in raw.read_text().splitlines()]
    for symbol in daily.markets:
        scope=proof.get('markets',{}).get(symbol,{})
        entry_oid=str(scope.get('entry_order_id'));stop_oid=str(scope.get('stop_order_id'))
        close_oid=str(scope.get('closing_order_id'));fills=[];stop=None;flat=[];funding=False
        for r in rows:
            q=r.get('request',{});response=r.get('response');kind=q.get('type')
            if q.get('user','').lower()!=daily.team_wallet.lower():continue
            if kind=='userFillsByTime' and isinstance(response,list):fills+=response
            if kind=='userFunding' and isinstance(response,list):funding=True
            if kind=='orderStatus' and str(q.get('oid'))==stop_oid and isinstance(response,dict):stop=response
            if kind=='clearinghouseState' and q.get('dex')==profile.dex and not any(
                    D(x['position']['szi']) for x in response['assetPositions']):
                flat.append(r)
        unique={str(f['tid']):f for f in fills if f.get('coin')==symbol}
        buys=[f for f in unique.values() if str(f['oid'])==entry_oid and f.get('side')=='B']
        sells=[f for f in unique.values() if str(f['oid'])==close_oid and f.get('side')=='A']
        if not buys or not sells or sum((D(f['sz']) for f in buys),D(0))!=sum((D(f['sz']) for f in sells),D(0)):
            raise ExchangeError('NATIVE_PROTECTION_ACTUAL_ROUNDTRIP_REQUIRED')
        record=(stop or {}).get('order',{});order=record.get('order',{})
        children=record.get('children',order.get('children',[]))
        linked=close_oid==stop_oid or close_oid in {str(x.get('oid')) for x in children if isinstance(x,dict)}
        if ((stop or {}).get('status')!='order' or record.get('status') not in {'triggered','filled'}
                or not linked or order.get('coin')!=symbol or order.get('side')!='A'
                or order.get('isTrigger') is not True or order.get('reduceOnly') is not True
                or order.get('orderType')!='Stop Limit'
                or D(order.get('origSz','0'))!=sum((D(f['sz']) for f in buys),D(0))
                or any(D(f['px'])<D(order.get('limitPx','0')) for f in sells)
                or not funding or any(f.get('feeToken')!=profile.collateral or f.get('closedPnl') is None for f in buys+sells)):
            raise ExchangeError('NATIVE_TRIGGER_IDENTITY_FILL_ACCOUNTING_REQUIRED')
        after=max(f['time'] for f in sells);verified=[]
        for r in flat:
            at=r.get('received_ms',0)
            if at<=after:continue
            orders=[x for x in rows if x.get('request',{}).get('type')=='frontendOpenOrders'
                and x['request'].get('dex')==profile.dex and x['request'].get('user','').lower()==daily.team_wallet.lower()
                and at<=x.get('received_ms',0)<=at+5000 and x.get('response')==[]]
            if orders:verified.append(at)
        if len(set(verified))<2:raise ExchangeError('NATIVE_TWO_TERMINAL_FLAT_READBACKS_REQUIRED')
    return proof


def require_long_acceptance(m,path,*,now_ms,team,signer,source_hash,policy_hash,host,
        revoked=False,bound_evidence=None,expected_acceptance=None):
    """Validate existing human authority without a journal, key, lease or nonce.

    This never creates authority and does not authorize a signing transport.
    Runtime and conditional waiting share exactly the same acceptance rules.
    """
    from venue_config import require_paper_migration
    d=m.daily;require_paper_migration(d.dex);now=now_ms
    a=json.loads(Path(path).read_text()) if expected_acceptance is None else expected_acceptance
    try:current=json.loads(Path(path).read_text())
    except (ValueError,OSError):raise ExchangeError('LONG_ACCEPTANCE_REMOVED_OR_CHANGED') from None
    try:
        stable=(source_hash()==d.source_hash and policy_hash()==m.reliability_sha256
            and all(sha(path)==expected for path,expected in (bound_evidence or {}).items()))
    except (OSError,ValueError):stable=False
    if (revoked or Path(path).with_name('session_revocation.json').exists() or current!=a
            or a.get('mandate_hash')!=m.identity or not str(a.get('operator_acceptance','')).strip()
            or any(a.get(k) is not True for k in ACKS)
            or type(a.get('accepted_ms')) is not int or a.get('expires_ms')!=d.expires_ms
            or not m.created_ms<=a['accepted_ms']<=m.approval_deadline_ms
            or not a['accepted_ms']<=now<d.expires_ms or now<d.starts_ms
            or team.lower()!=d.team_wallet.lower() or signer.lower()!=d.api_wallet.lower()
            or host!=d.signing_host or not stable):
        raise ExchangeError('EXACT_LONG_APPROVAL_WINDOW_SOURCE_HOST_REQUIRED')
    if d.dex=='pas':
        from .scored_session import SCORED_ACKS,SCORED_START_MS
        if now<SCORED_START_MS or any(a.get(k) is not True for k in SCORED_ACKS):
            raise ExchangeError('EXACT_PAS_SCORED_ACKNOWLEDGMENTS_AND_OPEN_WINDOW_REQUIRED')
    if m.mode=='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1':
        from .overnight_session import OVERNIGHT_ACKS
        if any(a.get(k) is not True for k in OVERNIGHT_ACKS):
            raise ExchangeError('EXACT_OVERNIGHT_CARRYOVER_RECOVERY_ACKNOWLEDGMENTS_REQUIRED')
    if m.mode=='EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1':
        from .practice_weekend_session import PRACTICE_ACKS,IST
        from datetime import datetime
        if (any(a.get(k) is not True for k in PRACTICE_ACKS)
                or datetime.fromtimestamp(a['accepted_ms']/1000,IST).date().isoformat()!='2026-10-17'):
            raise ExchangeError('EXACT_PRACTICE_CARRYOVER_RECOVERY_ACKNOWLEDGMENTS_REQUIRED')
    return a


class LongAuthorization:
    """Finite capability. Persist consumption before HTTP, never repeat a wire."""
    def __init__(self,mandate,acceptance_path,journal,*,clock_ms,source_hash,policy_hash,host=None):
        self.m=mandate.require();self.path=Path(acceptance_path);self.journal=journal
        from .venue_profiles import venue_profile
        self.venue_identity=venue_profile(mandate.daily.dex).identity
        self.clock_ms=clock_ms;self.source_hash=source_hash;self.policy_hash=policy_hash
        self.entry_stop_event=None
        self.host=host or socket.gethostname();self.revoked=False;self.lifecycle=None
        self.key='long_authority:'+mandate.identity;self.acceptance=json.loads(self.path.read_text())
        self.data=dict(owned={},transmissions=[],closed_attempts={},protection_attempts={},cancels=0)
        self.require(mandate.daily.team_wallet,mandate.daily.api_wallet)
        with journal.transaction():
            if journal.db.execute('SELECT 1 FROM controls WHERE name=?',(self.key,)).fetchone():
                raise ExchangeError('LONG_RESTART_REQUIRES_READ_ONLY_REVIEW')
            journal.db.execute('INSERT INTO controls VALUES (?,?)',(self.key,canonical(self.data)))

    def save(self):
        with self.journal.transaction():
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(self.key,canonical(self.data)))

    def require(self,team,signer):
        return require_long_acceptance(self.m,self.path,now_ms=self.clock_ms(),team=team,signer=signer,
            source_hash=self.source_hash,policy_hash=self.policy_hash,host=self.host,revoked=self.revoked,
            bound_evidence=getattr(self,'bound_evidence',{}),expected_acceptance=self.acceptance)

    def bind(self,key,kind,symbol,quantity):
        self.require(self.m.daily.team_wallet,self.m.daily.api_wallet)
        prior=self.data['owned'].get(key);record=dict(kind=kind,symbol=symbol,quantity=str(quantity),cycle=self.lifecycle.data['attempts'])
        if prior and prior!=record:raise ExchangeError('LONG_INTENT_IDENTITY_CHANGED')
        self.data['owned'][key]=record;self.save()

    def check_action(self,action):
        self.require(self.m.daily.team_wallet,self.m.daily.api_wallet)
        if action.get('type')=='cancel':
            if len(action.get('cancels',[]))!=1:raise ExchangeError('LONG_OWN_STOP_CANCEL_ONLY')
            cancel=action['cancels'][0]
            own=[r for r in self.journal.intents() if str(r['oid'])==str(cancel.get('o'))
                and self.data['owned'].get(r['intent_key'],{}).get('kind')=='protection']
            if len(own)!=1:raise ExchangeError('LONG_OWN_STOP_CANCEL_ONLY')
            return 'cancel',own[0]['intent_key']
        if action.get('type')!='order' or len(action.get('orders',[]))!=1:
            raise ExchangeError('LONG_ADMIN_MODIFY_BATCH_PROHIBITED')
        wire=action['orders'][0];row=self.journal.db.execute('SELECT * FROM intents WHERE cloid=?',(wire.get('c'),)).fetchone()
        if action.get('grouping','na')!='na':raise ExchangeError('LONG_FIXED_ORDER_GROUPING_REQUIRED')
        own=self.data['owned'].get(row['intent_key']) if row else None
        if not own or own['symbol'] not in self.m.daily.markets:raise ExchangeError('LONG_OWN_INTENT_REQUIRED')
        request=json.loads(row['request']);kind=own['kind'];quantity=decimal(wire.get('s'),positive=True)
        if (type(wire.get('b')) is not bool or type(wire.get('r')) is not bool
                or wire['b']!=(request['side']=='BUY') or wire['r']!=request['reduce_only']
                or quantity!=decimal(request['quantity']) or quantity!=decimal(own['quantity'])
                or decimal(wire.get('p'),positive=True)!=decimal(request['price'])):
            raise ExchangeError('LONG_EXACT_VALIDATED_WIRE_REQUIRED')
        if kind=='entry':
            from .entry_scope import require_entry
            require_entry(own['symbol'])
            if (self.entry_stop_event is not None and self.entry_stop_event.is_set()):
                raise ExchangeError('LONG_NEW_ENTRIES_REVOKED_BY_OPERATOR_STOP')
            if (not wire['b'] or wire['r'] or wire['t']!={'limit':{'tif':'Ioc'}}
                    or quantity*decimal(wire['p'])>decimal(self.m.daily.maximum_notional)
                    or self.clock_ms()>=self.m.daily.expires_ms-self.m.entry_cutoff_buffer_ms
                    or self.lifecycle is None or self.lifecycle.state!=TradeState.ENTRY_SUBMITTED):
                raise ExchangeError('LONG_ENTRY_SCOPE_REQUIRED')
        elif kind=='exit':
            if wire['b'] or not wire['r'] or wire['t']!={'limit':{'tif':'Ioc'}}:
                raise ExchangeError('LONG_REDUCE_ONLY_SELL_IOC_REQUIRED')
        elif kind=='protection':
            trigger=wire.get('t',{}).get('trigger',{})
            if wire['b'] or not wire['r'] or trigger.get('tpsl')!='sl' or trigger.get('isMarket') is not False:
                raise ExchangeError('LONG_NATIVE_STOP_LIMIT_REQUIRED')
        else:raise ExchangeError('LONG_ACTION_CLASSIFICATION_REQUIRED')
        return kind,row['intent_key']

    def claim_transmission(self,action):
        kind,key=self.check_action(action);digest=fingerprint(action)
        history=self.data['transmissions'];cycle=str(self.lifecycle.data['attempts'])
        if len(history)>=self.m.maximum_signed_actions or any(h['hash']==digest for h in history):
            raise ExchangeError('LONG_ACTION_ALREADY_CONSUMED_OR_LIMIT')
        if kind in {'exit','protection'}:
            counts=self.data['closed_attempts' if kind=='exit' else 'protection_attempts']
            maximum=self.m.maximum_close_attempts_per_cycle if kind=='exit' else self.m.maximum_protection_actions_per_cycle
            if counts.get(cycle,0)>=maximum:raise ExchangeError('LONG_CYCLE_ACTION_LIMIT')
            counts[cycle]=counts.get(cycle,0)+1
        if kind=='cancel':
            if self.data['cancels']>=self.m.maximum_cancel_actions:raise ExchangeError('LONG_CANCEL_LIMIT')
            self.data['cancels']+=1
        history.append(dict(hash=digest,kind=kind,key=key,observed_ms=self.clock_ms()));self.save()

    def revoke(self):self.revoked=True


class LongSDKTransport(OfficialSDKTransport):
    def __init__(self,*args,**kwargs):
        auth=args[4] if len(args)>4 else kwargs.get('authorization')
        if type(auth) is not LongAuthorization:raise ExchangeError('EXACT_LONG_SESSION_CAPABILITY_REQUIRED')
        auth.require(auth.m.daily.team_wallet,auth.m.daily.api_wallet)
        self.action_expiry_ms=auth.m.daily.expires_ms
        super().__init__(*args,**kwargs)

    def check(self,action):
        super().check(action);self.authorization.check_action(action)
        if action['type']=='order':
            w=action['orders'][0];row=self.authorization.journal.db.execute(
                'SELECT request FROM intents WHERE cloid=?',(w['c'],)).fetchone()
            if w['a']!=self.client.market(json.loads(row[0])['symbol']).asset_id:
                raise ExchangeError('LONG_ASSET_MAPPING_CHANGED')

    def transmit(self,payload):
        self.check(payload['action'])
        if payload.get('expiresAfter')!=self.action_expiry_ms:raise ExchangeError('LONG_SIGNED_EXPIRY_REQUIRED')
        self.authorization.claim_transmission(payload['action'])
        return super().transmit(payload)


class AllocatedLongRisk:
    """Tighten existing risk decisions, retaining baseline stops, targets and RR."""
    def __init__(self,risk,market,account,lifecycle):
        self.base=risk;self.policy=risk.policy;self.parameters=risk.parameters;self.fees=risk.fees
        self.market=market;self.account=account;self.lifecycle=lifecycle;self.last_plan=None;self.last_audit={}

    def assess(self,spec,side,reference,atr,quote,portfolio,quotes,now_ms,**kwargs):
        from risk.models import RiskDecision
        from .perpetual_economics import estimate_trade,FeeSchedule
        self.last_plan=None
        try:
            if self.market.client.dex=='pas':
                from .entry_scope import require_entry
                require_entry(spec.symbol)
            observed=self.account._query('userFees')
            self.fees=FeeSchedule(decimal(observed['userAddRate'])*6,decimal(observed['userCrossRate'])*6,
                'FRESH_CONSERVATIVE_MAXIMUM_PAR_MULTIPLIER')
            self.base.fees=self.fees
        except ExchangeError as exc:return RiskDecision(False,('FRESH_FEES_UNAVAILABLE:'+str(exc),))
        result=self.base.assess(spec,side,reference,atr,quote,portfolio,quotes,now_ms,**kwargs)
        self.last_audit=dict(self.base.last_audit)
        if not result.allowed:return result
        try:
            if side!='BUY':raise ExchangeError('DAILY_SHORT_DISABLED')
            m=self.lifecycle.m;active=self.account._query('activeAssetData',coin=spec.symbol)
            scope=getattr(self.lifecycle.authorization,'m',None)
            participation=decimal(scope.depth_participation) if scope else D('.1')
            slippage=decimal(scope.execution_slippage_bps) if scope else D(5)
            maximum_fee=decimal(scope.maximum_fee_rate) if scope else D('.003')
            if active.get('leverage')!=dict(type='cross',value=1):raise ExchangeError('DAILY_ONE_X_CROSS_REQUIRED')
            book=self.market.get_orderbook(spec.symbol);now=self.market.client.clock_ms()
            if self.fees.taker>maximum_fee:raise ExchangeError('DAILY_FEE_BOUND')
            plan=allocate(spec,book,side,result.stop,CapitalLimits(m.bankroll,m.maximum_notional,m.maximum_total_exposure,
                m.maximum_cumulative_allocation,m.risk_fraction,m.daily_loss_fraction,
                participation=participation,slippage_bps=slippage),now_ms=now,
                free_collateral=min(D(x) for x in active['availableToTrade']),equity=portfolio.snapshot(quotes,now).equity,
                entry_fee=self.fees.taker,exit_fee=self.fees.taker,
                funding_cost_per_unit=abs(quote.hourly_funding)*quote.oracle*self.policy.holding_hours,
                cumulative_allocation=D(self.lifecycle.data['allocation']),
                daily_loss=max(D(0),D(m.bankroll)-D(self.lifecycle.data['equity']),D(self.lifecycle.data['drawdown'])),
                maximum_trade_quantity=active['maxTradeSzs'][0])
            entry=quote.ask
            quantity=min(result.quantity,plan['quantity'],spec.normalize_size(D(m.maximum_notional)/max(quote.mark,entry)))
            if quantity*entry<10:raise ExchangeError('NO_MINIMUM_SIZE_WITHIN_BOTH_SIDE_CAPACITY')
            # No assumed reduce-only minimum exemption: smallest partial must be
            # protectable even at the independent catastrophic stop allowance.
            stop=spec.normalize_price(result.stop-D(str(atr)), 'BUY')
            if spec.size_step*stop*D('.995')<10:
                raise ExchangeError('SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED')
            plan.update(quantity=quantity,notional=quantity*entry,
                intended_loss=plan['intended_loss']*quantity/plan['quantity'],
                collateral_reserved=quantity*entry*(1+2*self.fees.taker))
            self.last_plan=plan;self.last_audit['bounded_capital']=plan
            return replace(result,quantity=quantity,economics=estimate_trade(side,quantity,reference,result.stop,
                result.target,quote,self.fees,slippage_bps=self.policy.slippage_bps,holding_hours=self.policy.holding_hours))
        except ExchangeError as exc:return RiskDecision(False,(str(exc),))


class DailyLongExecution(HyperliquidExecution):
    """Lifecycle hooks around the original central validator/permit/SDK path."""
    def attach_daily(self,lifecycle,authorization,risk):
        actual=type(authorization) is LongAuthorization and type(self.transport) is LongSDKTransport and lifecycle.mode=='AUTHORIZED_TESTNET_LONG'
        fixture=type(authorization) is OfflineDailyAuthority and type(self.transport) is OfflineSDKTransport and lifecycle.mode=='OFFLINE_FIXTURE'
        if not (actual or fixture):
            raise ExchangeError('ACTUAL_LONG_TRANSPORT_REQUIRED')
        self.daily=lifecycle;self.daily_auth=authorization;self.daily_risk=risk

    def _prepare_context_request(self,request,permission,context):
        # Additional restrictions on the original fresh central context. None
        # of these checks substitutes for its existing validator or SDK permit.
        quote=context.quote
        if request.reduce_only:
            held=context.positions.get(request.symbol)
            if held is None or held.quantity<=0 or request.side!='SELL' or request.quantity!=held.quantity:
                raise ExchangeError('DAILY_EXACT_CURRENT_LONG_POSITION_REQUIRED')
            if request.strategy_id!='CATASTROPHIC_STOP':
                scope=getattr(self.daily_auth,'m',None)
                slippage=decimal(scope.execution_slippage_bps) if scope else D(5)
                if request.price<context.spec.normalize_price(quote.bid*(1-slippage/10000),'SELL'):
                    raise ExchangeError('DAILY_FRESH_CLOSING_PRICE_LIMIT')
        else:
            if self.client.dex=='pas':
                from .entry_scope import require_entry
                require_entry(request.symbol)
            if request.side!='BUY':raise ExchangeError('DAILY_SHORT_DISABLED')
            scope=getattr(self.daily_auth,'m',None)
            participation=decimal(scope.depth_participation) if scope else D('.1')
            spread=decimal(scope.maximum_spread_bps) if scope else D(15)
            slippage=decimal(scope.execution_slippage_bps) if scope else D(5)
            maximum_fee=decimal(scope.maximum_fee_rate) if scope else D('.003')
            if (request.quantity>min(quote.bid_quantity,quote.ask_quantity)*participation
                    or (quote.ask-quote.bid)/quote.mid*10000>spread
                    or request.price>context.spec.normalize_price(quote.ask*(1+slippage/10000),'BUY')
                    or request.quantity*max(quote.mark,request.price)>D(self.daily.m.maximum_notional)
                    or context.active_asset.get('leverage')!=dict(type='cross',value=1)):
                raise ExchangeError('DAILY_FRESH_BOTH_SIDE_PRICE_LEVERAGE_LIMIT')
            if decimal(context.readiness.fees['userCrossRate'])*6>maximum_fee:
                raise ExchangeError('DAILY_FRESH_FEE_BOUND')
            from .perpetual_economics import estimate_trade,FeeSchedule
            pending=getattr(self.recovery.owner,'pending_entries',{}).get(request.symbol)
            if not pending or pending['candidate_id']!=permission.candidate_id:
                raise ExchangeError('DAILY_FROZEN_MANAGEMENT_PROVENANCE_REQUIRED')
            ref,atr=decimal(pending['reference_vwap']),decimal(pending['atr'])
            fees=FeeSchedule(decimal(context.readiness.fees['userAddRate'])*6,
                decimal(context.readiness.fees['userCrossRate'])*6,'FRESH_CENTRAL_PREFLIGHT_FEES')
            economics=estimate_trade('BUY',request.quantity,ref,pending['stop'],pending['target'],quote,fees,
                slippage_bps=slippage,holding_hours=self.daily_risk.policy.holding_hours)
            p=self.daily_risk.parameters
            threshold=decimal(p['MIN_NET_RR_LOW_VOL'] if atr/ref<decimal(p['LOW_VOL_ATR_PCT']) else p['MIN_NET_RR_NORMAL'])
            loss=max(D(0),D(self.daily.m.bankroll)-D(self.daily.data['equity']),D(self.daily.data['drawdown']))
            remaining=D(self.daily.m.bankroll)*D(self.daily.m.daily_loss_fraction)-loss
            if (economics.net_profit<=0 or economics.net_rr<threshold or economics.stop_risk>remaining
                    or economics.stop_risk>D(self.daily.m.bankroll)*D(self.daily.m.risk_fraction)):
                raise ExchangeError('DAILY_FRESH_FEE_FUNDING_REWARD_RISK_BUDGET_REQUIRED')
            self.journal.event('DAILY_FRESH_ECONOMICS',self.client.clock_ms(),candidate_id=permission.candidate_id,
                economics=asdict(economics),fee_rate=str(fees.taker),hourly_funding=str(quote.hourly_funding))
        return request,permission

    def submit(self,request,*,permission=None):
        if self.journal.intent(request.client_order_id or ''):
            return super().submit(request,permission=permission)
        d=self.daily;auth=self.daily_auth
        auth.require(d.m.team_wallet,d.m.api_wallet)
        if request.reduce_only:
            if request.side!='SELL':raise ExchangeError('DAILY_LONG_CLOSE_ONLY')
            if d.state in {TradeState.POSITION_MANAGED,TradeState.POSITION_PROTECTED,TradeState.UNPROTECTED_EXPOSURE}:
                d.reserve_exit()
            else:raise ExchangeError('DAILY_EXIT_RECONCILIATION_REQUIRED')
            kind='exit'
        else:
            if request.side!='BUY' or not permission or not permission.provenance:
                raise ExchangeError('DAILY_STRATEGY_LONG_PROVENANCE_REQUIRED')
            if permission.provenance.classification!='STRATEGY_ENTRY':raise ExchangeError('DAILY_STRATEGY_ENTRY_REQUIRED')
            d.candidate(request.client_order_id,request.symbol,'LONG')
            d.reserve_entry(request.quantity,request.price,allocation=self.daily_risk.last_plan,
                protection_fixture=d.mode=='OFFLINE_FIXTURE')
            kind='entry'
        key=request.client_order_id
        if not key:raise ExchangeError('DAILY_DURABLE_ORDER_ID_REQUIRED')
        auth.bind(key,kind,request.symbol,request.quantity)
        try:
            result=super().submit(request,permission=permission)
            self.reconcile_daily()
            return result
        except Exception:
            self.entries_paused=True;d._state(TradeState.RECOVERY_REQUIRED,'EXECUTION_OR_PREFLIGHT_REQUIRES_REVIEW');raise

    def submit_protection(self,plan,intent_key,*,modify_oid=None):
        if modify_oid is not None:raise ExchangeError('DAILY_PROTECTION_MODIFICATION_REQUIRES_REVIEW')
        if any(k!=intent_key and v['kind']=='protection' and v['cycle']==self.daily.data['attempts']
                for k,v in self.daily_auth.data['owned'].items()):
            raise ExchangeError('DAILY_FAILED_STOP_REQUIRES_RECOVERY_NOT_REARM')
        self.daily_auth.bind(intent_key,'protection',plan.symbol,plan.quantity)
        return super().submit_protection(plan,intent_key,modify_oid=modify_oid)

    def flat_readbacks(self):
        readings=[]
        for _ in range(2):
            started=self.client.clock_ms();before=self.account.get_positions()
            orders=self.account.get_frontend_open_orders();after=self.account.get_positions()
            now=self.client.clock_ms()
            signature=lambda values:{s:(p.quantity,p.entry_price) for s,p in values.items()}
            readings.append(dict(source='OFFLINE_FIXTURE' if self.daily.mode=='OFFLINE_FIXTURE' else 'EXCHANGE_DIRECT_TESTNET_'+self.daily.m.dex.upper()+'_INFO',
                team=self.daily.m.team_wallet,observed_ms=now,positions=after,orders=orders,
                ready=self.recovery.last_report.ready and signature(before)==signature(after) and 0<=now-started<=5000))
        return readings

    def reconcile_daily(self):
        """Consume reported fills only. SDK acknowledgements cannot clear a cycle."""
        d=self.daily;entry=d.data.get('entry')
        if not entry:return
        owned=self.daily_auth.data['owned'];rows=[r for r in self.journal.intents() if r['intent_key'] in owned
            and owned[r['intent_key']]['cycle']==d.data['attempts']]
        if any(r['state'] in {'UNKNOWN','SUBMITTED','PREPARED','OPEN'} and owned[r['intent_key']]['kind']!='protection' for r in rows):
            d._state(TradeState.UNKNOWN,'UNCERTAIN_OWN_ORDER_NO_RETRY');self.entries_paused=True;return
        e=self.journal.intent(entry['candidate'])
        if e is None:raise ExchangeError('DAILY_ENTRY_JOURNAL_MISSING')
        fills=list(self.recovery.state.fills.values())
        buys=[f for f in fills if f.order_id==str(e['oid']) and f.symbol==entry['symbol'] and f.side=='BUY']
        quantity=sum((f.quantity for f in buys),D(0))
        if d.state==TradeState.ENTRY_SUBMITTED:
            settled=e['state'] in {'FILLED','CANCELLED','REJECTED'} or e['state']=='PARTIALLY_FILLED' and json.loads(e['outcome'] or '{}').get('remainder_cancelled') is True
            d.entry_result(quantity,order_id=e['oid'],fill_id=buys[0].trade_id if buys else None,remainder_settled=settled)
        positions=self.recovery.state.positions
        if quantity and entry['symbol'] in positions and not self.protection.healthy:
            # A stale cached receipt is not proof that a native stop vanished.
            # Re-read coverage without placing, rearming or modifying an order.
            self.protection.ensure_all(allow_actions=False)
        if d.state==TradeState.ENTRY_RECONCILIATION:
            d.protection_result(bool(self.protection and self.protection.healthy))
            if d.state==TradeState.POSITION_PROTECTED:d.manage()
        if entry['symbol'] in positions:
            if d.state in {TradeState.POSITION_PROTECTED,TradeState.POSITION_MANAGED} and not self.protection.healthy:
                d._state(TradeState.UNPROTECTED_EXPOSURE,'OWNED_STOP_COVERAGE_LOST_REQUIRES_AUTHORIZED_RECOVERY')
                self.entries_paused=True
            exits=[r for r in rows if owned[r['intent_key']]['kind']=='exit']
            if exits and exits[-1]['state'] in {'REJECTED','CANCELLED','PARTIALLY_FILLED','FILLED'}:
                d._state(TradeState.RECOVERY_REQUIRED,'RESIDUAL_AFTER_TERMINAL_EXIT_NO_AUTOMATIC_RETRY')
                self.entries_paused=True
            return
        if not quantity:return
        close_rows=[r for r in rows if owned[r['intent_key']]['kind'] in {'exit','protection'}]
        if (any(r['state'] in {'PREPARED','SUBMITTED','UNKNOWN','OPEN','CANCEL_PENDING'} for r in close_rows)
                or self.protection is not None and not self.protection.healthy):
            d._state(TradeState.RECOVERY_REQUIRED,'CLOSING_ORDER_OR_PROTECTION_EVIDENCE_UNRESOLVED')
            self.entries_paused=True;return
        close_ids={str(r['oid']) for r in close_rows if r['oid']}
        close_ids.update(str(oid) for r in close_rows for oid in json.loads(r['outcome'] or '{}').get('child_order_ids',[]))
        sells=[f for f in fills if f.order_id in close_ids and f.symbol==entry['symbol'] and f.side=='SELL'
            and f.timestamp_ms>=min(x.timestamp_ms for x in buys)]
        if sum((f.quantity for f in sells),D(0))!=quantity:
            d._state(TradeState.RECOVERY_REQUIRED,'ACTUAL_CLOSING_FILL_REQUIRED');return
        from .venue_profiles import venue_profile
        if any(f.fee_token!=venue_profile(d.m.dex).collateral or f.closed_pnl is None for f in buys+sells):
            d._state(TradeState.RECOVERY_REQUIRED,'ACTUAL_FILL_ACCOUNTING_REQUIRED');return
        net=sum((f.quantity*f.price for f in sells),D(0))-sum((f.quantity*f.price for f in buys),D(0))
        if abs(net-sum((f.closed_pnl for f in buys+sells),D(0)))>D('.000001'):
            d._state(TradeState.RECOVERY_REQUIRED,'REPORTED_CLOSED_PNL_DISAGREES_WITH_MATCHED_FILL_CASHFLOWS')
            self.entries_paused=True;return
        net-=sum((f.fee for f in buys+sells),D(0))
        net+=sum((f.cashflow for f in self.recovery.state.funding.values() if f.symbol==entry['symbol']
            and min(x.timestamp_ms for x in buys)<=f.timestamp_ms<=max(x.timestamp_ms for x in sells)),D(0))
        if d.state!=TradeState.EXIT_SUBMITTED:
            d.data['exit']=dict(side='SELL',quantity=str(quantity),reduce_only=True,tif='Ioc')
            d._state(TradeState.EXIT_SUBMITTED,'ACTUAL_NATIVE_CLOSING_FILL')
        d.exit_result(quantity,order_id=sells[-1].order_id,fill_id=sells[-1].trade_id,net_pnl=net)
        self.protection.ensure_all(allow_actions=self.recovery.last_report.ready)
        d.confirm_flat(self.flat_readbacks())


class OfflineDailyAuthority:
    """No action checks, no transmit, no key access; actual transport rejects it."""
    def __init__(self,lifecycle):
        if lifecycle.mode!='OFFLINE_FIXTURE':raise ExchangeError('OFFLINE_FIXTURE_REQUIRED')
        self.lifecycle=lifecycle;self.data=dict(owned={})
    def require(self,*_):self.lifecycle.require_window()
    def bind(self,key,kind,symbol,quantity):
        self.data['owned'][key]=dict(kind=kind,symbol=symbol,quantity=str(quantity),cycle=self.lifecycle.data['attempts'])


class LongAccountRecovery(LiveAccountRecovery):
    """Full strategy-management recovery with the repaired isolated history view.

    CertificationRecovery deliberately omits strategy callbacks, so it cannot
    manage autonomous entries. Default production recovery keeps the raw UNKNOWN.
    """
    def intent_rows(self):
        from .qualification_intent_recovery import qualification_intents
        return qualification_intents(self.journal)


class DailyLimitProtection(ExchangeProtectionManager):
    """Preserve approved geometry and the explicit 0.5% stop-limit allowance.

    Native market TP/SL has a documented 10% tolerance. It is not an approved
    substitute. A limit can rest through a gap: unresolved children halt rather
    than allowing a competing or blind order.
    """
    def _plan(self,*args,**kwargs):
        return replace(super()._plan(*args,**kwargs),is_market=False)

    @staticmethod
    def _matches(order,plan):
        return (plan.is_market is False and order.get('isTrigger') is True and order.get('reduceOnly') is True
            and order.get('isPositionTpsl') is not True
            and order.get('side')==('A' if plan.side=='SELL' else 'B')
            and decimal(order['sz'])==plan.quantity and decimal(order['triggerPx'])==plan.trigger_price
            and decimal(order['limitPx'])==plan.limit_price and order.get('orderType') in {'Stop Limit','StopLimit'})


from live_execution_session import LiveExecutionSession


class DailyLongSession(LiveExecutionSession):
    def __init__(self,*args,authority,**kwargs):
        self.daily_authority=authority
        super().__init__(*args,**kwargs)

    def _consume_actual_fills(self,state):
        # Lifetime account accounting stays intact; historical controlled-test
        # fills cannot be replayed as new strategy entries or given new stops.
        owned=self.daily_authority.data['owned']
        rows=[r for r in self.journal.intents() if r['intent_key'] in owned]
        oids={str(r['oid']) for r in rows if r['oid']}
        oids.update(str(oid) for r in rows for oid in json.loads(r['outcome'] or '{}').get('child_order_ids',[]))
        return super()._consume_actual_fills(SimpleNamespace(fills={k:f for k,f in state.fills.items() if f.order_id in oids}))

    def _protection_barrier(self,*,allow_actions=True):
        daily=self.execution.daily
        if daily.data.get('entry') and daily.state in {TradeState.UNPROTECTED_EXPOSURE,
                TradeState.UNKNOWN,TradeState.RECOVERY_REQUIRED,TradeState.HALTED}:
            allow_actions=False
        return super()._protection_barrier(allow_actions=allow_actions)

    def cycle(self,*,scan=True):
        auth=self.daily_authority;executor=self.execution;daily=executor.daily
        auth.require(daily.m.team_wallet,daily.m.api_wallet);executor.reconcile_daily()
        if self.clock_ms()>=daily.m.expires_ms-getattr(getattr(auth,'m',None),'entry_cutoff_buffer_ms',120000):
            scan=False
        close_buffer=getattr(getattr(auth,'m',None),'risk_close_buffer_ms',60000)
        if self.clock_ms()>=daily.m.expires_ms-close_buffer and self.recovery.state.positions:
            for symbol in list(self.recovery.state.positions):self._close(symbol,'Authorized End Of Session Risk Exit')
            scan=False
        if daily.state in {TradeState.UNKNOWN,TradeState.RECOVERY_REQUIRED,TradeState.HALTED}:
            executor.entries_paused=True;scan=False
        try:return super().cycle(scan=scan)
        finally:
            executor.reconcile_daily()
            if daily.state==TradeState.UNPROTECTED_EXPOSURE:
                self._close(daily.data['entry']['symbol'],'Unverified Protection: Authorized Emergency Risk Exit')


def build_long_runtime(root,mandate_path,acceptance_path,release_path,protection_evidence_path,*,scanner_policy,risk_policy):
    """Only construction gate for actual execution. Never called by public CLI."""
    from .par_retirement import reject_retired_scored_session_route
    reject_retired_scored_session_route()
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    from .paper_operations import active_source_hash
    from .execution_journal import ExecutionJournal
    from .execution_safety import NonceManager,ClockHealthMonitor,HyperliquidRateLimitManager
    from .hyperliquid_client import HyperliquidClient
    from .hyperliquid_account import HyperliquidAccount
    from .hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine
    from .stream_first import StreamFirstMarketData
    from .exchange_rules import LiveContextProvider,HyperliquidOrderValidator
    from .qualification_intent_recovery import QualificationPositionGuard
    from .position_protection import ProtectionPolicy,ExchangeProtectionManager
    from .reliability_policy import load_reliability_policy
    from .live_account_stream import LiveAccountStream
    from .live_runtime import LiveRuntime
    from .perpetual_economics import FeeSchedule
    from market_regime_scanner import MarketRegimeScanner
    from live_execution_session import LiveExecutionSession
    from risk.portfolio_risk import PortfolioRisk
    from live_session_results import LiveSessionResults
    root=Path(root);m=read_mandate(mandate_path)
    from .competition_windows import require_published_window
    require_published_window(m.daily.starts_ms,m.daily.expires_ms)
    from .venue_profiles import venue_profile
    profile=venue_profile(m.daily.dex)
    require_paper_migration(profile);verify_strategy_freeze()
    scored_bound={}
    if profile.dex=='pas':
        from .terminal_evidence import local_execution_state
        from .scored_session import require_scored_evidence
        # Same team and API signer retain shared nonce/account hazards across
        # DEXs. A different collateral/asset ID is not an isolation certificate.
        if local_execution_state(root)['status']!='NO_LOCAL_UNRESOLVED_INTENT':
            raise ExchangeError('PAS_SHARED_ACCOUNT_UNKNOWN_REQUIRES_ADMISSIBLE_RESOLUTION')
        scored_bound=require_scored_evidence(m,Path(mandate_path).parent)
    require_release(root,release_path,m.daily.source_hash,m.release_sha256)
    from .entry_scope import require_entry
    for symbol in m.daily.markets:require_entry(symbol)
    if sha(protection_evidence_path)!=m.protection_evidence_sha256:raise ExchangeError('LONG_PROTECTION_PROOF_CHANGED')
    native_proof=require_native_evidence(protection_evidence_path,m.daily)
    policy_path=root/'configs/reliability_policy.json'
    rate,clock_config,disabled_policy=load_reliability_policy(policy_path)
    protection_policy=replace(disabled_policy,enabled=True)
    if fingerprint(asdict(protection_policy))!=m.protection_policy_sha256:raise ExchangeError('LONG_PROTECTION_POLICY_CHANGED')
    if (risk_policy.leverage!=1 or risk_policy.risk_fraction>D(m.daily.risk_fraction) or risk_policy.max_daily_loss_fraction>D(m.daily.daily_loss_fraction)
            or risk_policy.depth_participation>D(m.depth_participation) or risk_policy.slippage_bps>D(m.execution_slippage_bps) or risk_policy.max_spread_bps>D(m.maximum_spread_bps)
            or scanner_policy.min_atr_fraction<D('.004') or scanner_policy.max_spread_bps>D(m.maximum_spread_bps)
            or scanner_policy.history_bars!=300 or scanner_policy.top_n!=3):
        raise ExchangeError('LONG_BASELINE_POLICIES_REQUIRED')
    state=root/'runtime/testnet/anchorium-bot-1'
    journal=ExecutionJournal(state/('pas.sqlite' if profile.dex=='pas' else 'qualification.sqlite'),
        session_id='anchorium-pas-v1' if profile.dex=='pas' else 'anchorium-one-qualification-v1',team_address=TEAM)
    client=nonces=transport=None
    try:
        auth=LongAuthorization(m,acceptance_path,journal,clock_ms=lambda:time.time_ns()//1000000,
            source_hash=lambda:active_source_hash(root),policy_hash=lambda:sha(policy_path))
        auth.bound_evidence={str(release_path):m.release_sha256,str(protection_evidence_path):m.protection_evidence_sha256}
        auth.bound_evidence.update(scored_bound)
        if json.loads(Path(release_path).read_text()).get('requirements_sha256'):
            auth.bound_evidence[str(root/'algo-trading-bot/requirements.txt')]=json.loads(Path(release_path).read_text())['requirements_sha256']
        auth.bound_evidence[str(Path(release_path).parent/'regression.xml')]=json.loads(Path(release_path).read_text())['xml_sha256']
        auth.bound_evidence[str(Path(protection_evidence_path).parent/native_proof['receipt_file'])]=native_proof['receipt_sha256']
        daily=DailyLifecycle(journal,m.daily,clock_ms=auth.clock_ms,source_hash=auth.source_hash,
            mode='AUTHORIZED_TESTNET_LONG',authorization=auth);auth.lifecycle=daily
        rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=API);rates.read_budget_wait_seconds=65
        if profile.dex=='pas':
            client=HyperliquidClient(rate_limits=rates,venue=profile);client.startup()
            discovery=json.loads((Path(mandate_path).parent/'venue_discovery.json').read_text())
            if (fingerprint(discovery['metadata'])!=fingerprint(client.metadata)
                    or discovery['dex_index']!=client.dex_index
                    or discovery['collateral_token']!=client.collateral_token_id):
                raise ExchangeError('APPROVED_PAS_DEPLOYMENT_CHANGED')
            from .scored_session import require_shared_scope
            require_shared_scope(root,client)
            account=HyperliquidAccount(client,TEAM)
            # Public account checks precede loading a real signer.
            if account.get_positions() or account.get_frontend_open_orders() or account.get_equity().collateral_balance<=0:
                raise ExchangeError('PAS_FRESH_FUNDED_FLAT_ACCOUNT_REQUIRED')
            from .pas_readiness import require_pas_market_status
            require_pas_market_status(client)
        # All evidence and exact genuine acceptance pass before accessing the key.
        from .practice_preflight import read_api_key,api_signer
        key,_=read_api_key(root)
        try:signer=api_signer(key,API,TEAM)
        finally:key=None
        if signer.address.lower()!=API.lower():raise ExchangeError('LONG_SIGNER_IDENTITY_MISMATCH')
        nonces=NonceManager(state/'nonces.sqlite',signer.address,journal=journal)
        if client is None:
            client=HyperliquidClient(rate_limits=rates);client.startup();account=HyperliquidAccount(client,TEAM)
        public=HyperliquidMarketData(client);engine=ParMarketDataEngine(public,symbols=m.daily.markets,include_trades=True)
        market=StreamFirstMarketData(client,engine);clock=ClockHealthMonitor(journal=journal,**clock_config)
        recovery=LongAccountRecovery(account,journal,initial_start_ms=0);holder={}
        provider=LiveContextProvider(market,account,API,clock,rates,reconciliation_ready=lambda:recovery.last_report.ready,
            feed_ready=lambda:bool(holder.get('stream') and holder['stream'].healthy),policy_leverage=1)
        if profile.dex=='pas':
            original_load=provider.load
            def pas_load(request,*,critical=False):
                require_shared_scope(root,client,owned_pas_intents=auth.data['owned'])
                require_pas_market_status(client)
                return original_load(request,critical=critical)
            provider.load=pas_load
        transport=LongSDKTransport(client,signer,TEAM,nonces,auth,rate_limits=rates)
        executor=DailyLongExecution(client,transport=transport,account=account,journal=journal,context_provider=provider,
            validator=HyperliquidOrderValidator(client,policy_leverage=1),recovery=recovery,clock_health=clock,rate_limits=rates)
        executor.position_guard=QualificationPositionGuard(journal,clock_ms=client.clock_ms)
        executor.compliance_guard.position_guard=executor.position_guard
        DailyLimitProtection(executor,policy=protection_policy,managers=recovery.managers)
        fees=account._query('userFees')
        # Conservative maximum par multiplier; do not assume unavailable fee scale.
        fee=decimal(fees['userCrossRate'])*6
        if fee>decimal(m.maximum_fee_rate):raise ExchangeError('LONG_CURRENT_FEE_BOUND_EXCEEDED')
        risk=AllocatedLongRisk(PortfolioRisk(risk_policy,FeeSchedule(decimal(fees['userAddRate'])*6,fee,
            'CONSERVATIVE_MAXIMUM_PAR_MULTIPLIER')),market,account,daily)
        executor.attach_daily(daily,auth,risk)
        class LongScanner(MarketRegimeScanner):
            def scan(self):
                auth.require(TEAM,API)
                result=super().scan()
                result.watchlist=[s for s in result.watchlist if s in m.daily.markets and next(
                    (d.signal and d.signal.get('long') and not d.signal.get('short') for d in result.diagnostics if d.symbol==s),False)]
                return result
        scanner=LongScanner(market,scanner_policy,candidate_symbols=m.daily.markets)
        session=DailyLongSession(market,scanner,executor,risk,authority=auth)
        stream=LiveAccountStream(TEAM,recovery,executor,clock_ms=client.clock_ms);holder['stream']=stream
        session.attach_account_stream(stream);session.startup()
        recovery.recover();daily.confirm_flat(executor.flat_readbacks())
        results=LiveSessionResults(Path(mandate_path).parent/'execution_evidence',session)
        class BoundedLongRuntime(LiveRuntime):
            def run(self,stop_event=None):
                import threading
                stop=stop_event or threading.Event();done=threading.Event()
                def guard():
                    while not done.wait(1):
                        try:auth.require(TEAM,API)
                        except ExchangeError:stop.set();return
                thread=threading.Thread(target=guard,name='long-authority-deadline',daemon=True);thread.start()
                try:return super().run(stop)
                finally:done.set();thread.join(timeout=2)

            def close(self,*,clean=True):
                from .paper_operations import atomic_json
                from .terminal_recovery import exception_evidence
                import threading
                cancel=threading.Event();timer=threading.Timer(180,cancel.set)
                previous_cancel=client.read_cancel_event;client.read_cancel_event=cancel
                rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75;timer.start()
                report=dict(status='STOPPED',observed_ms=client.clock_ms(),mandate_hash=m.identity,
                    source_hash=active_source_hash(root),restarted=False,signing_authority='REVOKED_ON_CLOSE')
                try:
                    # If time and authority remain, request the same guarded risk
                    # exit. UNKNOWN orders or failed checks remain unresolved.
                    executor.entries_paused=True
                    if recovery.state.positions:
                        try:
                            auth.require(TEAM,API)
                            for symbol in list(recovery.state.positions):session._close(symbol,'Authorized Worker Shutdown Risk Exit')
                        except Exception as exc:
                            report['shutdown_risk_exit_error']=str(exc)
                            report['shutdown_risk_exit_error_details']=exception_evidence(exc)
                    # Risk actions have finished. Quiesce public collectors so
                    # they cannot consume the terminal account-read budget.
                    self.market_stop.set()
                    if self.market_stream:self.market_stream._recovery_cancel.set()
                    if self.market_thread:
                        self.market_thread.join(12)
                        if self.market_thread.is_alive():raise ExchangeError('LONG_MARKET_SHUTDOWN_PENDING')
                    stream.stop_receiver()
                    # Expired signing permission never prevents public account
                    # reconciliation or turns cached flatness into fresh proof.
                    readings=[]
                    for _ in range(2):
                        r=recovery.recover()
                        before=account.get_positions();orders=account.get_frontend_open_orders();after=account.get_positions()
                        signature=lambda positions:{s:(p.quantity,p.entry_price) for s,p in positions.items()}
                        if signature(before)!=signature(after):raise ExchangeError('POSITION_CHANGED_DURING_TERMINAL_READBACK')
                        readings.append(dict(observed_ms=client.clock_ms(),team=TEAM,
                            source='EXCHANGE_DIRECT_TESTNET_'+profile.dex.upper()+'_INFO',positions=[asdict(p) for p in after.values()],
                            orders=orders,ready=r.ready))
                    report.update(readbacks=readings,account=recovery.state.report(),
                        terminal_flat=all(r['ready'] and not r['positions'] and not r['orders'] for r in readings)
                            and readings[0]['observed_ms']<readings[1]['observed_ms'])
                    report.update(status='STOPPED_FLAT_VERIFIED' if report['terminal_flat'] else 'HUMAN_RECOVERY_REVIEW_REQUIRED',
                        operator_action_required=not report['terminal_flat'],daily_lifecycle=dict(daily.data),
                        session_realized_net=daily.data['realized_net'])
                except Exception as exc:report.update(status='HUMAN_RECOVERY_REVIEW_REQUIRED',error=str(exc),
                    error_details=exception_evidence(exc),terminal_flat=None)
                finally:
                    timer.cancel();client.read_cancel_event=previous_cancel
                    exposed=bool(recovery.state.positions or recovery.state.orders or any(
                        r['positions'] or r['orders'] for r in report.get('readbacks',[])))
                    report['account_status']='FLAT_VERIFIED' if report.get('terminal_flat') else 'EXPOSED' if exposed else 'UNKNOWN'
                    report['residual_status']=report['account_status'] if report.get('terminal_flat') else report['account_status']+'_REQUIRES_OPERATOR'
                    report['rate_report']=rates.report()
                    report['local_dependency']='This Mac, Python process, power and internet; native trigger is not a guaranteed fill'
                    atomic_json(Path(mandate_path).parent/'terminal_result.json',report)
                    super().close(clean=clean and report.get('terminal_flat') is True)
        runtime=BoundedLongRuntime(session,auth,transport,nonces,journal,client.transport,engine,results)
        runtime.start_market_stream();stream.start_receiver();return runtime
    except Exception:
        if transport:transport.close()
        if nonces:nonces.close()
        if client:client.close()
        journal.close();raise
