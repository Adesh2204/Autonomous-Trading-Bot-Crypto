"""Auditable daily-session contract and durable lifecycle coordinator.

The existing general LIVE builder is locked by PAPER/false. This coordinator
can drive offline SDK fixtures and public observation. The isolated LONG adapter
also requires an exact LongAuthorization capability; booleans and observation
flags cannot enable it. This module cannot mint a central SDK action permit or
read a key. Genuine native-protection and SHORT qualification remain separate.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal as D
from enum import Enum
from datetime import datetime
from zoneinfo import ZoneInfo
from .base_exchange import ExchangeError, decimal
from .execution_journal import canonical, fingerprint


class TradeState(str,Enum):
    FLAT='FLAT'
    SIGNAL_CANDIDATE='SIGNAL_CANDIDATE'
    PREFLIGHT='PREFLIGHT'
    ENTRY_SUBMITTED='ENTRY_SUBMITTED'
    ENTRY_RECONCILIATION='ENTRY_RECONCILIATION'
    POSITION_PROTECTED='POSITION_PROTECTED'
    POSITION_MANAGED='POSITION_MANAGED'
    EXIT_SUBMITTED='EXIT_SUBMITTED'
    EXIT_RECONCILIATION='EXIT_RECONCILIATION'
    FLAT_VERIFIED='FLAT_VERIFIED'
    REJECTED='REJECTED'
    PARTIAL_FILL='PARTIAL_FILL'
    UNKNOWN='UNKNOWN'
    HALTED='HALTED'
    UNPROTECTED_EXPOSURE='UNPROTECTED_EXPOSURE'
    RECOVERY_REQUIRED='RECOVERY_REQUIRED'


@dataclass(frozen=True)
class DailyMandate:
    session_id: str
    team_wallet: str
    api_wallet: str
    markets: tuple
    directions: tuple
    starts_ms: int
    expires_ms: int
    source_hash: str
    signing_host: str
    bankroll: str
    maximum_notional: str
    maximum_total_exposure: str
    maximum_cumulative_allocation: str
    maximum_entry_attempts: int=2
    maximum_concurrent_positions: int=1
    leverage: int=1
    risk_fraction: str='0.005'
    daily_loss_fraction: str='0.01'
    network: str='testnet'
    dex: str='par'
    protection_required: bool=True

    def __post_init__(self):
        object.__setattr__(self,'markets',tuple(self.markets))
        object.__setattr__(self,'directions',tuple(self.directions))

    def expected_dex(self): return 'par'

    def _require_scope(self):
        import re
        if (self.network!='testnet' or self.dex!=self.expected_dex() or not self.session_id or not self.signing_host
                or not re.fullmatch('[0-9a-f]{64}',self.source_hash)
                or any(not isinstance(x,str) or not re.fullmatch('0x[0-9a-fA-F]{40}',x) or int(x[2:],16)==0 for x in (self.team_wallet,self.api_wallet))
                or self.team_wallet.lower()==self.api_wallet.lower()
                or not self.markets or len(set(self.markets))!=len(self.markets)
                or any(not str(s).startswith(self.expected_dex()+':') for s in self.markets)
                or not self.directions or len(set(self.directions))!=len(self.directions)
                or set(self.directions)-{'LONG','SHORT'}
                or any(type(x) is not int for x in (self.starts_ms,self.expires_ms,self.maximum_entry_attempts,self.maximum_concurrent_positions,self.leverage))
                or not self.starts_ms<self.expires_ms or self.expires_ms-self.starts_ms>86400000
                or self.maximum_concurrent_positions!=1 or self.leverage!=1
                or not 1<=self.maximum_entry_attempts<=2 or self.protection_required is not True):
            raise ExchangeError('INVALID_BOUNDED_DAILY_MANDATE')
        b,n,t,c=(decimal(x,positive=True) for x in (self.bankroll,self.maximum_notional,
            self.maximum_total_exposure,self.maximum_cumulative_allocation))
        if (n>D('10000') or n>t or t>n or c<n or c>n*self.maximum_entry_attempts or n>b
                or not 0<decimal(self.risk_fraction)<=D('.005')
                or not 0<decimal(self.daily_loss_fraction)<=D('.01')):
            raise ExchangeError('DAILY_MANDATE_EXCEEDS_BASELINE_RISK')
        return self

    def require(self):
        self._require_scope()
        start=datetime.fromtimestamp(self.starts_ms/1000,ZoneInfo('Asia/Calcutta'))
        end=datetime.fromtimestamp((self.expires_ms-1)/1000,ZoneInfo('Asia/Calcutta'))
        if start.date()!=end.date():raise ExchangeError('DAILY_MANDATE_CANNOT_CROSS_IST_DAY')
        return self

    @property
    def identity(self):self.require();return fingerprint(asdict(self))


def deployment_readiness(*, protection_verified=False, short_cycle_verified=False,
                         direction='LONG', exact_session_approved=False,
                         source_matches=False, fresh_account=False):
    """A report, never a signed capability. Booleans cannot enable submission."""
    reasons=[]
    if not protection_verified:reasons.append('NATIVE_PROTECTION_NOT_EXCHANGE_VERIFIED')
    if direction=='SHORT' and not short_cycle_verified:reasons.append('SHORT_CYCLE_NOT_EXCHANGE_VERIFIED')
    if not exact_session_approved:reasons.append('NEW_EXACT_DAILY_SESSION_APPROVAL_REQUIRED')
    if not source_matches:reasons.append('SOURCE_MATCHING_RELEASE_REQUIRED')
    if not fresh_account:reasons.append('FRESH_AUTHORITATIVE_ACCOUNT_REQUIRED')
    reasons.append('GENERAL_LIVE_BUILDER_REMAINS_LOCKED_BY_PAPER_FALSE')
    return dict(status='BLOCKED',reasons=reasons,order_submission_enabled=False,
        note='A readiness report does not create SDK/action authorization')


class DailyLifecycle:
    def __init__(self,journal,mandate,*,clock_ms,source_hash,mode='OBSERVATION',authorization=None):
        self.journal=journal;self.m=mandate.require();self.clock_ms=clock_ms;self.source_hash=source_hash
        self.authorization=authorization
        if mode=='AUTHORIZED_TESTNET_LONG':
            from .long_session import LongAuthorization
            if type(authorization) is not LongAuthorization or authorization.m.daily!=mandate:
                raise ExchangeError('EXACT_LONG_SESSION_CAPABILITY_REQUIRED')
            authorization.require(mandate.team_wallet,mandate.api_wallet)
        elif mode not in {'OBSERVATION','OFFLINE_FIXTURE'}:raise ExchangeError('DAILY_NON_SIGNING_MODE_REQUIRED')
        if mode=='OFFLINE_FIXTURE' and not journal.session_id.startswith('offline:'):
            raise ExchangeError('SYNTHETIC_SESSION_CANNOT_AUTHORIZE_ACTUAL_ACCOUNT')
        self.mode=mode;self.key='bounded_daily:'+mandate.identity
        saved=journal.control(self.key)
        self.data=dict(state='UNKNOWN',attempts=0,cycles=0,allocation='0',quantity='0',
            realized_net='0',equity=str(mandate.bankroll),peak_equity=str(mandate.bankroll),
            drawdown='0',seen_candidates=[],entry=None,exit=None,revoked=False,restart_uncertain=False)
        if saved:
            value=saved.get('data')
            if not isinstance(value,dict) or fingerprint(value)!=saved.get('checksum'):
                raise ExchangeError('DAILY_SESSION_CHECKPOINT_CORRUPT')
            self.data=value;self.data.update(state='UNKNOWN',restart_uncertain=True,revoked=True)
        self._save('STARTUP_RECONCILIATION_REQUIRED')

    @property
    def state(self):return TradeState(self.data['state'])

    def _save(self,reason):
        # This schema contains public lifecycle state only. Persist its exact
        # canonical bytes in the existing transactional controls table. Generic
        # diagnostic redaction would alter 64-hex candidate IDs/checksums and
        # break both recovery integrity and durable duplicate detection.
        value=dict(data=self.data,checksum=fingerprint(self.data))
        with self.journal.transaction():
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                (self.key,canonical(value)))
        self.journal.event('BOUNDED_DAILY_STATE',self.clock_ms(),configuration_hash=self.m.identity,
            mode=self.mode,state=self.data['state'],reason=reason,quantity=self.data['quantity'],
            attempts=self.data['attempts'],order_submission_enabled=self.mode=='AUTHORIZED_TESTNET_LONG')

    def _state(self,state,reason):
        self.data['state']=state.value;self._save(reason)

    def require_window(self):
        now=self.clock_ms()
        if (self.data['revoked'] or self.source_hash()!=self.m.source_hash
                or not self.m.starts_ms<=now<self.m.expires_ms):
            self.data['revoked']=True
            unresolved=self.state in {TradeState.UNKNOWN,TradeState.ENTRY_SUBMITTED,TradeState.EXIT_SUBMITTED,TradeState.RECOVERY_REQUIRED}
            self._state(TradeState.RECOVERY_REQUIRED if D(self.data['quantity']) or unresolved else TradeState.HALTED,
                'AUTHORITY_EXPIRED_REVOKED_OR_SOURCE_CHANGED')
            raise ExchangeError('DAILY_SESSION_REVOKED_OR_EXPIRED')

    def confirm_flat(self,readbacks):
        if self.data['restart_uncertain'] or self.state in {TradeState.UNKNOWN,TradeState.RECOVERY_REQUIRED} and self.data['entry']:
            raise ExchangeError('OWNED_ORDER_UNCERTAINTY_REQUIRES_SEPARATE_REVIEW')
        if (self.state not in {TradeState.UNKNOWN,TradeState.EXIT_RECONCILIATION,TradeState.FLAT_VERIFIED,TradeState.REJECTED}
                or D(self.data['quantity']) or len(readbacks)!=2):
            raise ExchangeError('TWO_AUTHORITATIVE_FLAT_READBACKS_REQUIRED')
        previous=-1
        source='OFFLINE_FIXTURE' if self.mode=='OFFLINE_FIXTURE' else ('EXCHANGE_DIRECT_TESTNET_'+getattr(self.m,'dex','par').upper()+'_INFO')
        for r in readbacks:
            if (r.get('source')!=source or r.get('team','').lower()!=self.m.team_wallet.lower()
                    or r.get('positions') or r.get('orders') or r.get('ready') is not True
                    or type(r.get('observed_ms')) is not int or not previous<r['observed_ms']<=self.clock_ms()
                    or self.clock_ms()-r['observed_ms']>5000):
                raise ExchangeError('TWO_AUTHORITATIVE_FLAT_READBACKS_REQUIRED')
            previous=r['observed_ms']
        if self.state==TradeState.EXIT_RECONCILIATION:self.data['cycles']+=1
        self.data.update(entry=None,exit=None)
        self._state(TradeState.FLAT_VERIFIED,'TWO_DISTINCT_FLAT_ZERO_ORDER_RECONCILIATIONS')

    def candidate(self,identity,symbol,direction):
        self.require_window()
        if self.state not in {TradeState.FLAT,TradeState.FLAT_VERIFIED,TradeState.REJECTED}:
            raise ExchangeError('DAILY_GLOBAL_POSITION_BARRIER')
        if (not isinstance(identity,str) or not identity or symbol not in self.m.markets or direction not in self.m.directions
                or identity in self.data['seen_candidates']):raise ExchangeError('DAILY_SCOPE_OR_DUPLICATE_SIGNAL')
        self.data['entry']=dict(candidate=identity,symbol=symbol,direction=direction)
        self._state(TradeState.SIGNAL_CANDIDATE,'EXPLAINED_CANDIDATE_OBSERVED')

    def reserve_entry(self,quantity,price,*,allocation=None,protection_fixture=False):
        self.require_window()
        if self.mode=='AUTHORIZED_TESTNET_LONG':
            self.authorization.require(self.m.team_wallet,self.m.api_wallet)
        elif self.mode!='OFFLINE_FIXTURE':raise ExchangeError('NO_ACTUAL_ORDER_AUTHORITY_IN_OBSERVATION_OPERATOR')
        if self.state!=TradeState.SIGNAL_CANDIDATE:raise ExchangeError('ENTRY_CANDIDATE_REQUIRED')
        q=decimal(quantity,positive=True);p=decimal(price,positive=True);notional=q*p
        plan=allocation
        if (not isinstance(plan,dict) or plan.get('symbol')!=self.data['entry']['symbol']
                or plan.get('side')!=('BUY' if self.data['entry']['direction']=='LONG' else 'SELL')
                or decimal(plan.get('quantity'))!=q or decimal(plan.get('notional'))!=notional
                or type(plan.get('observed_ms')) is not int or not 0<=self.clock_ms()-plan['observed_ms']<=5000
                or decimal(plan.get('intended_loss'),positive=True)>D(self.m.bankroll)*D(self.m.risk_fraction)
                or decimal(plan.get('collateral_reserved'),nonnegative=True)>decimal(plan.get('free_collateral_observed'),nonnegative=True)):
            raise ExchangeError('FRESH_BOUNDED_CAPITAL_ALLOCATION_REQUIRED')
        loss=max(D(0),D(self.m.bankroll)-D(self.data['equity']),D(self.data['drawdown']))
        if (self.data['attempts']>=self.m.maximum_entry_attempts or notional>D(self.m.maximum_notional)
                or D(self.data['allocation'])+notional>D(self.m.maximum_cumulative_allocation)
                or loss>=D(self.m.bankroll)*D(self.m.daily_loss_fraction)
                or decimal(plan['intended_loss'])>D(self.m.bankroll)*D(self.m.daily_loss_fraction)-loss
                or D(self.data['quantity']) or (self.mode=='OFFLINE_FIXTURE' and protection_fixture is not True)):
            raise ExchangeError('DAILY_RISK_ATTEMPT_OR_PROTECTION_BARRIER')
        self._state(TradeState.PREFLIGHT,'SCOPE_RISK_PROTECTION_PREFLIGHT')
        self.data['attempts']+=1;self.data['allocation']=str(D(self.data['allocation'])+notional)
        self.data['seen_candidates'].append(self.data['entry']['candidate'])
        self.data['entry'].update(requested=str(q),price=str(p))
        self._state(TradeState.ENTRY_SUBMITTED,'ONE_DURABLE_ENTRY_ATTEMPT_RESERVED')

    def entry_result(self,quantity,*,order_id=None,fill_id=None,unknown=False,remainder_settled=False):
        if self.state!=TradeState.ENTRY_SUBMITTED:raise ExchangeError('ENTRY_ATTEMPT_REQUIRED')
        if unknown:self._state(TradeState.UNKNOWN,'UNCERTAIN_ENTRY_NEVER_RETRY');return
        q=decimal(quantity,nonnegative=True)
        if q>D(self.data['entry']['requested']):raise ExchangeError('ENTRY_FILL_EXCEEDS_REQUEST')
        if not q:self._state(TradeState.REJECTED,'ZERO_ENTRY_FILL');self.data['entry']=None;self._save('NO_EXPOSURE');return
        if not order_id or not fill_id:raise ExchangeError('ACTUAL_OR_FIXTURE_FILL_IDENTITY_REQUIRED')
        self.data['quantity']=str(q);self.data['entry'].update(order_id=str(order_id),fill_id=str(fill_id))
        if q<D(self.data['entry']['requested']):
            self._state(TradeState.PARTIAL_FILL,'PARTIAL_ENTRY_EXPOSURE')
            if not remainder_settled:self._state(TradeState.UNKNOWN,'UNSETTLED_ENTRY_REMAINDER');return
        self._state(TradeState.ENTRY_RECONCILIATION,'ENTRY_FILL_QUANTITY_RECONCILED')

    def protection_result(self,verified):
        if self.state!=TradeState.ENTRY_RECONCILIATION:raise ExchangeError('ENTRY_RECONCILIATION_REQUIRED')
        if type(verified) is not bool:raise ExchangeError('EXPLICIT_PROTECTION_RESULT_REQUIRED')
        self._state(TradeState.POSITION_PROTECTED if verified else TradeState.UNPROTECTED_EXPOSURE,
            'OWNED_PROTECTION_READBACK' if verified else 'MISSING_OR_REJECTED_PROTECTION')

    def manage(self):
        if self.state!=TradeState.POSITION_PROTECTED:raise ExchangeError('VERIFIED_PROTECTION_REQUIRED')
        self._state(TradeState.POSITION_MANAGED,'POSITION_MANAGEMENT')

    def reserve_exit(self):
        self.require_window()
        if self.mode=='AUTHORIZED_TESTNET_LONG':
            self.authorization.require(self.m.team_wallet,self.m.api_wallet)
        elif self.mode!='OFFLINE_FIXTURE':raise ExchangeError('NO_ACTUAL_ORDER_AUTHORITY_IN_OBSERVATION_OPERATOR')
        if self.state not in {TradeState.POSITION_PROTECTED,TradeState.POSITION_MANAGED,TradeState.UNPROTECTED_EXPOSURE}:
            raise ExchangeError('EXACT_HELD_POSITION_REQUIRED')
        direction=self.data['entry']['direction'];q=D(self.data['quantity'])
        self.data['exit']=dict(side='SELL' if direction=='LONG' else 'BUY',quantity=str(q),reduce_only=True,tif='Ioc')
        self._state(TradeState.EXIT_SUBMITTED,'EXACT_REDUCE_ONLY_EXIT_RESERVED')
        return self.data['exit'].copy()

    def exit_result(self,filled,*,order_id=None,fill_id=None,net_pnl=None,unknown=False):
        if self.state!=TradeState.EXIT_SUBMITTED:raise ExchangeError('EXIT_ATTEMPT_REQUIRED')
        if unknown:self._state(TradeState.UNKNOWN,'UNCERTAIN_EXIT_NEVER_RETRY');return
        filled=decimal(filled,nonnegative=True);held=D(self.data['quantity'])
        if filled>held:raise ExchangeError('REDUCE_ONLY_EXIT_CANNOT_REVERSE_POSITION')
        if filled and (not order_id or not fill_id):
            raise ExchangeError('EXIT_FILL_IDENTITY_REQUIRED')
        if filled==held and net_pnl is None:
            raise ExchangeError('EXIT_FILL_AND_ACCOUNTING_REQUIRED')
        net=decimal(net_pnl) if filled==held else None
        if filled:self.data['exit'].update(order_id=str(order_id),fill_id=str(fill_id),filled=str(filled))
        self.data['quantity']=str(held-filled)
        if filled<held:self._state(TradeState.RECOVERY_REQUIRED,'PARTIAL_OR_REJECTED_EXIT_NO_RETRY');return
        self.data['realized_net']=str(D(self.data['realized_net'])+net)
        equity=D(self.m.bankroll)+D(self.data['realized_net'])
        # Preserve an actually sampled intracycle peak after the position closes.
        # Otherwise a close could conceal drawdown before the next entry check.
        peak=max(D(self.data['peak_equity']),D(self.data.get('sampled_peak',self.data['peak_equity'])),equity)
        self.data.update(equity=str(equity),peak_equity=str(peak),drawdown=str(peak-equity))
        self.data['exit'].update(order_id=str(order_id),fill_id=str(fill_id))
        self._state(TradeState.EXIT_RECONCILIATION,'ACTUAL_OR_FIXTURE_CLOSING_FILL_RECONCILED')

    def shutdown(self,reason='OPERATOR_END'):
        self.data['revoked']=True
        unresolved=self.state in {TradeState.UNKNOWN,TradeState.ENTRY_SUBMITTED,TradeState.EXIT_SUBMITTED,TradeState.RECOVERY_REQUIRED}
        self._state(TradeState.RECOVERY_REQUIRED if D(self.data['quantity']) or unresolved else TradeState.HALTED,reason)
        return dict(self.data,order_submission_enabled=False)
