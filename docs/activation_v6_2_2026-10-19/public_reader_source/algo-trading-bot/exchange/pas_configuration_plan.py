"""Unsigned, source-bound account configuration proposal. Never an action permit."""
from .base_exchange import ExchangeError,decimal
from .execution_journal import fingerprint
from .venue_profiles import SCORED
from .entry_scope import PAS_ENTRY_MARKETS
from .testnet_certification import TEAM
import re


def configuration_plan(discovery):
    if (discovery.get('dex')!='pas' or discovery.get('collateral')!='USDP'
            or discovery.get('venue_identity')!=SCORED.identity
            or discovery.get('status')!='READ_ONLY_DISCOVERY_COMPLETE'
            or not re.fullmatch('[0-9a-f]{64}',discovery.get('source_hash') or '')
            or discovery.get('source_hash')!=discovery.get('source_hash_after')
            or discovery.get('journal_integrity')!='ok'
            or len(discovery.get('markets',[]))!=10
            or {r.get('symbol') for r in discovery.get('markets',[])}!=SCORED.markets):
        raise ExchangeError('COMPLETE_SOURCE_BOUND_PAS_CONFIGURATION_OBSERVATIONS_REQUIRED')
    changes=[];verified=[]
    for row in discovery['markets']:
        active=row['active_asset'];spec=row['spec'];symbol=row['symbol']
        if (spec['symbol']!=symbol or type(spec['asset_id']) is not int or spec['max_leverage']<1
                or active.get('coin')!=symbol or active.get('user','').lower()!=TEAM.lower()):
            raise ExchangeError('EXACT_PAS_CONFIGURATION_MAPPING_REQUIRED')
        if symbol not in PAS_ENTRY_MARKETS:continue
        if active.get('leverage')==dict(type='cross',value=1):verified.append(symbol)
        else:changes.append(dict(symbol=symbol,observed_ms=row['observed_ms'],before=active.get('leverage'),
            requested_action=dict(type='updateLeverage',asset=spec['asset_id'],isCross=True,leverage=1)))
    account=discovery.get('account',{});equity=account.get('reported_account_equity',{})
    balance=decimal(equity.get('collateral_balance') or '0',nonnegative=True)
    blockers=['SEPARATE_EXACT_OPERATOR_CONFIGURATION_APPROVAL_REQUIRED'] if changes else []
    if balance<=0:blockers.append('PAS_USDP_FUNDING_REQUIRED_BEFORE_CONFIGURATION')
    if discovery.get('account_mode')!='unifiedAccount':blockers.append('HUMAN_VERIFIED_UNIFIED_MODE_REQUIRED')
    if discovery.get('terminal_flat') is not True:blockers.append('TWO_FRESH_FLAT_ZERO_ORDER_READBACKS_REQUIRED')
    local=discovery.get('local_execution_state',{})
    isolation=discovery.get('configuration_isolation')
    if isolation is not None:
        from .configuration_isolation import assess,CLOID,INTENT
        if not assess(isolation,discovery['source_hash'],discovery['finished_ms'])['admissible']:
            raise ExchangeError('INVALID_CONFIGURATION_ONLY_ISOLATION_REVIEW')
        if local.get('unresolved')!=[dict(journal='qualification',cloid=CLOID,state='UNKNOWN',intent_key=INTENT)]:
            raise ExchangeError('ONLY_EXACT_ORIGINAL_UNKNOWN_MAY_BE_ISOLATED_FOR_CONFIGURATION')
    if local.get('status')!='NO_LOCAL_UNRESOLVED_INTENT' and isolation is None:
        blockers.append('SHARED_UNKNOWN_AND_CONSUMED_INVOCATION_REVIEW_REQUIRED')
    if discovery.get('registration_evidence',{}).get('status') not in {
            'OPERATOR_REVIEWED_ORGANIZER_RECORD','DIRECT_OPERATOR_CONFIRMED_ACCOUNT_IDENTITY'}:
        blockers.append('REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED')
    plan=dict(status='UNSIGNED_CONFIGURATION_PLAN_ONLY',network='testnet',dex='pas',collateral='USDP',
        source_hash=discovery['source_hash'],observed_ms=discovery['finished_ms'],
        entry_markets=sorted(PAS_ENTRY_MARKETS),account_reconciliation_scope='ALL_CANONICAL_PAS_MARKETS',
        policy_basis='V4 BTC/EWY entries only; leverage is per market, not an all-ten venue obligation',
        team_wallet=TEAM,
        discovery_hash=fingerprint(discovery),changes=changes,already_one_x_cross=sorted(verified),
        collateral_balance=str(balance),organizer_credit_amount=None,
        organizer_credit_status='ORIGINAL_ORGANIZER_CREDIT_RECORD_REQUIRED; balance is not funding provenance',
        blockers=blockers,signing_authority='NONE',signatures_created=0,exchange_writes=0,
        transfers_allowed=False,configuration_approval_created=False,
        required_before_execution=['Fresh funded Unified account/agent/identity checks','Prior UNKNOWN/invocation review',
            'Exact new configuration-only approval','Shared sole host/signer/nonce ownership','Per-action exact permit and durable uncertainty',
            'Fresh readback of every requested 1x CROSS value'],
        note='Unsigned evidence only. The separate exact PAS configuration-only approval/route is required; existing par approval never authorizes PAS.')
    if isolation is not None:
        plan.update(configuration_isolation=isolation,
            historical_disposition='UNKNOWN_PRESERVED; finite configuration-only isolation. No order, qualification, cancellation or transfer authority.',
            isolation_acceptance='The exact plan approval includes this displayed isolation only for the two 1x CROSS changes; ordinary order barriers remain.')
    plan['plan_hash']=fingerprint(plan)
    return plan
