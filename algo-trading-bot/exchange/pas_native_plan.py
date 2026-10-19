"""Dedicated unsigned PAS test scope; ordinary native proof is not its prerequisite.

This deliberately does not generalize the par subminimum exception. If the
smallest possible remainder lacks an admissible cleanup route, the test stays
blocked pending independent scope review and genuine venue evidence.
"""
from decimal import Decimal as D
from types import SimpleNamespace
from dataclasses import dataclass,field
from .base_exchange import ExchangeError,MarketSpec,decimal
from .capital_allocation import floor_quantity
from .execution_journal import fingerprint
from .partial_fill_safety import partial_path_assessment
from .testnet_certification import TEAM,API
from .competition_windows import SCORED_START_MS,SCORED_END_MS


def prepare_native_test(discovery,source,now_ms,*,symbol='pas:BTC'):
    from .entry_scope import require_entry
    require_entry(symbol)
    from .pas_configuration_plan import configuration_plan
    configuration_plan(discovery)  # Validate complete canonical source-bound observations.
    if discovery['source_hash']!=source or not 0<=now_ms-discovery['finished_ms']<=300000:
        raise ExchangeError('FRESH_PAS_QUALIFICATION_DISCOVERY_REQUIRED')
    rows=[r for r in discovery['markets'] if r['symbol']==symbol]
    if len(rows)!=1:raise ExchangeError('EXACT_PAS_QUALIFICATION_MARKET_REQUIRED')
    row=discovery.get('qualification_market') or rows[0]
    if row.get('symbol')!=symbol or fingerprint(row.get('spec'))!=fingerprint(rows[0]['spec']):
        raise ExchangeError('QUALIFICATION_FINAL_SNAPSHOT_MAPPING_CHANGED')
    spec=MarketSpec(**row['spec']);book=row['book']
    bid=decimal(book['bids'][0]['price'],positive=True);ask=decimal(book['asks'][0]['price'],positive=True)
    entry=spec.normalize_price(ask*D('1.0005'),'BUY');trigger=spec.normalize_price(bid*D('.99'),'SELL')
    floor=spec.normalize_price(trigger*D('.995'),'SELL')
    q=floor_quantity(spec,min(D(25)/entry,decimal(row['displayed_book_only_quantity'],nonnegative=True)))
    blockers=[]
    if q<=0 or q*floor<10:blockers.append('FULL_SIZE_STOP_OR_CLEANUP_BELOW_ORDINARY_MINIMUM')
    partial=None
    if q>0:
        partial=partial_path_assessment(spec,SimpleNamespace(symbol=symbol,asset_id=spec.asset_id,quantity=q,entry_limit=entry,stop_limit=floor,exit_bound=floor))
        if not partial['entry_admissible_under_documented_minimum']:blockers.append('PAS_SUBMINIMUM_CLEANUP_SCOPE_NOT_ESTABLISHED_NO_PAR_EXCEPTION')
    if row['active_asset'].get('leverage')!=dict(type='cross',value=1):blockers.append('PAS_ONE_X_CROSS_REQUIRED')
    if discovery.get('account_mode')!='unifiedAccount':blockers.append('UNIFIED_ACCOUNT_REQUIRED')
    if decimal(discovery.get('account',{}).get('reported_account_equity',{}).get('collateral_balance') or 0)<=0:
        blockers.append('USDP_FUNDING_REQUIRED')
    if discovery.get('terminal_flat') is not True:blockers.append('TWO_AUTHORITATIVE_FLAT_ZERO_ORDER_READBACKS_REQUIRED')
    if discovery.get('local_execution_state',{}).get('status')!='NO_LOCAL_UNRESOLVED_INTENT':blockers.append('SHARED_UNKNOWN_AND_CONSUMED_NATIVE_ATTEMPT_REVIEW_REQUIRED')
    if not SCORED_START_MS<=now_ms<SCORED_END_MS:blockers.append('OFFICIAL_SCORED_WINDOW_REQUIRED')
    if not 0<=now_ms-book['timestamp_ms']<=5000:blockers.append('FRESH_FINAL_BOOK_REQUIRED')
    if any(type(row.get(k)) is not int or not 0<=now_ms-row[k]<=5000 for k in ('context_ms','active_ms')):
        blockers.append('FRESH_FINAL_CONTEXT_AND_ACCOUNT_LIMITS_REQUIRED')
    if ask<=bid or (ask-bid)/((ask+bid)/2)*10000>15:blockers.append('QUALIFICATION_SPREAD_EXCEEDS_15_BPS')
    try:
        mark=decimal(row['context']['markPx'],positive=True);oracle=decimal(row['context']['oraclePx'],positive=True)
        if abs(mark-oracle)/oracle*10000>50 or abs((ask+bid)/2-oracle)/oracle*10000>100:
            blockers.append('QUALIFICATION_MARK_ORACLE_DIVERGENCE')
    except (ExchangeError,KeyError):blockers.append('QUALIFICATION_REFERENCE_PRICES_REQUIRED')
    fee=decimal(discovery['user_fees']['userCrossRate'],nonnegative=True)*6
    if fee>D('.003'):blockers.append('CONSERVATIVE_FEE_BOUND_EXCEEDED')
    funding=abs(decimal(row['context']['funding']))
    loss=q*(entry-floor)+q*(entry+floor)*fee+q*entry*funding*2
    if loss>10:blockers.append('QUALIFICATION_TEST_LOSS_BUDGET_EXCEEDED')
    result=dict(status='BLOCKED_QUALIFICATION_PROPOSAL' if blockers else 'QUALIFICATION_SCOPE_AWAITING_REVIEW_AND_EXACT_APPROVAL',
        purpose='SEPARATELY_AUTHORIZED_PAS_NATIVE_AND_RESIDUAL_EXPERIMENT',network='testnet',dex='pas',collateral='USDP',
        source_hash=source,discovery_hash=fingerprint(discovery),team_wallet=TEAM,api_wallet=API,
        observed_ms=now_ms,market_observed_ms=row['observed_ms'],book_ms=book['timestamp_ms'],context_ms=row.get('context_ms'),active_ms=row.get('active_ms'),symbol=symbol,asset_id=spec.asset_id,size_step=str(spec.size_step),quantity=str(q),
        entry=dict(side='BUY',tif='Ioc',reduce_only=False,maximum_limit=str(entry),maximum_notional='25'),
        stop=dict(side='SELL',reduce_only=True,type='Stop Limit',isMarket=False,tpsl='sl',grouping='na',
            trigger_reference='MARK',trigger=str(trigger),limit=str(floor),fixed_size=str(q)),
        cleanup=dict(side='SELL',reduce_only=True,tif='Ioc',exact_remaining_position_only=True,minimum_limit=str(floor),
            maximum_resolved_attempts=2,maximum_slippage_bps='20',owned_cancellation_rounds=1,
            unsupported_subminimum_dispatch=False,uncertain_retry=False),
        maximum_entries=1,maximum_signed_actions=6,acceptance_window_ms=300000,maximum_authority_ms=300000,
        natural_trigger_wait_seconds=120,minimum_reserved_cleanup_ms=120000,session_loss_budget='10',
        planned_floor_loss_including_fee_and_funding_reserve=str(loss),guaranteed_loss_cap=False,
        partial_assessment=partial,normal_autonomous_native_proof_required_to_prepare=False,
        prior_par_proof_qualifies_pas=False,consumed_attempt_reset_permitted=False,
        risks=['Partial fill may leave an unprotected subminimum residual','Stop Limit gap may trigger without fill',
            'Rejection, ambiguous transmission or interruption requires original-order reconciliation',
            'This Mac, process, power and internet remain dependencies'],
        blockers=blockers+['REVIEWED_APPLICABLE_ORGANIZER_SCOPE_REQUIRED','NEW_EXACT_QUALIFICATION_ONLY_HUMAN_APPROVAL_REQUIRED'],
        signing_authority='NONE',approval_created=False,exchange_writes=0,signatures_created=0,
        execution_status='NO_EXECUTION_CAPABILITY_CREATED; unresolved residual policy cannot be bypassed by an ordinary session approval')
    result['proposal_hash']=fingerprint(result)
    return result


@dataclass
class QualificationProgress:
    """Separate observed milestones. Synthetic event tests never certify a venue."""
    stages:dict=field(default_factory=dict)
    recovery_required:bool=False
    reasons:list=field(default_factory=list)

    def observe(self,event,*,at,details):
        order=('ENTRY_FILL_CONFIRMED','STOP_SUBMITTED','STOP_ACCEPTED','STOP_ARMED','STOP_TRIGGERED',
            'CLOSING_ORDER_IDENTIFIED','CLOSING_FILL_CONFIRMED','POSITION_RECONCILED_FLAT')
        if event not in order or type(at) is not int:raise ExchangeError('QUALIFICATION_EVENT_IDENTITY_REQUIRED')
        needed={'ENTRY_FILL_CONFIRMED':('entry_oid','quantity'), 'STOP_SUBMITTED':('stop_cloid',),
            'STOP_ACCEPTED':('stop_oid',),'STOP_ARMED':('stop_oid','isTrigger','reduceOnly','fixed_size'),
            'STOP_TRIGGERED':('stop_oid','status'),'CLOSING_ORDER_IDENTIFIED':('stop_oid','closing_oid','authoritative_link'),
            'CLOSING_FILL_CONFIRMED':('closing_oid','quantity','actual_fees','actual_funding'),
            'POSITION_RECONCILED_FLAT':('two_authoritative_flat_zero_order_readbacks',)}
        if any(details.get(k) is None for k in needed[event]):raise ExchangeError('QUALIFICATION_EVENT_EVIDENCE_INCOMPLETE')
        index=order.index(event)
        if index and order[index-1] not in self.stages:raise ExchangeError('QUALIFICATION_MILESTONE_PREDECESSOR_REQUIRED')
        if index and at<self.stages[order[index-1]]['observed_ms']:raise ExchangeError('QUALIFICATION_EVENT_TIME_REVERSED')
        if event in self.stages and self.stages[event]!=dict(observed_ms=at,details=details):raise ExchangeError('QUALIFICATION_EVENT_CONFLICT')
        if 'stop_oid' in details and 'STOP_ACCEPTED' in self.stages and details['stop_oid']!=self.stages['STOP_ACCEPTED']['details']['stop_oid']:
            raise ExchangeError('QUALIFICATION_PARENT_ORDER_MISMATCH')
        if event=='STOP_TRIGGERED' and details['status'] not in {'triggered','filled'}:raise ExchangeError('ACTUAL_TRIGGER_STATUS_REQUIRED')
        if event=='CLOSING_FILL_CONFIRMED' and details['closing_oid']!=self.stages['CLOSING_ORDER_IDENTIFIED']['details']['closing_oid']:
            raise ExchangeError('QUALIFICATION_CLOSING_ORDER_MISMATCH')
        if event=='ENTRY_FILL_CONFIRMED':decimal(details['quantity'],positive=True)
        if event=='STOP_ARMED' and (details['isTrigger'] is not True or details['reduceOnly'] is not True
            or decimal(details['fixed_size'])!=decimal(self.stages['ENTRY_FILL_CONFIRMED']['details']['quantity'])):
            raise ExchangeError('QUALIFICATION_FIXED_NATIVE_STOP_MISMATCH')
        if event=='CLOSING_ORDER_IDENTIFIED' and details['authoritative_link'] is not True:raise ExchangeError('QUALIFICATION_PARENT_CHILD_LINK_REQUIRED')
        if event=='CLOSING_FILL_CONFIRMED' and decimal(details['quantity'])!=decimal(self.stages['ENTRY_FILL_CONFIRMED']['details']['quantity']):
            self.recovery_required=True;self.reasons.append('ACTUAL_PARTIAL_CLOSING_FILL_RESIDUAL');return
        if event=='POSITION_RECONCILED_FLAT' and details['two_authoritative_flat_zero_order_readbacks'] is not True:
            raise ExchangeError('TWO_AUTHORITATIVE_FLAT_ZERO_ORDER_READBACKS_REQUIRED')
        self.stages[event]=dict(observed_ms=at,details=details)

    def report(self):
        return dict(milestones=self.stages,recovery_required=self.recovery_required,reasons=self.reasons,
            qualified=False,qualification_basis='Milestone telemetry alone never qualifies; validate original raw venue records independently')
