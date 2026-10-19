"""Unsigned, source-bound account configuration proposal. Never an action permit."""
from .base_exchange import ExchangeError,decimal
from .execution_journal import fingerprint
from .venue_profiles import SCORED
from .competition_market import PAS_TARGET_LEVERAGE
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
            or len(discovery.get('markets',[]))!=len(SCORED.markets)
            or {r.get('symbol') for r in discovery.get('markets',[])}!=SCORED.markets):
        raise ExchangeError('COMPLETE_SOURCE_BOUND_PAS_CONFIGURATION_OBSERVATIONS_REQUIRED')
    changes=[];verified=[];asset_ids=set()
    for row in discovery['markets']:
        active=row['active_asset'];spec=row['spec'];symbol=row['symbol']
        if (spec['symbol']!=symbol or type(spec['asset_id']) is not int
                or spec['asset_id']<0 or spec['asset_id'] in asset_ids
                or type(spec['max_leverage']) is not int or spec['max_leverage']<PAS_TARGET_LEVERAGE
                or active.get('coin')!=symbol or active.get('user','').lower()!=TEAM.lower()):
            raise ExchangeError('EXACT_PAS_CONFIGURATION_MAPPING_REQUIRED')
        asset_ids.add(spec['asset_id'])
        leverage=active.get('leverage')
        if (isinstance(leverage,dict) and leverage.get('type')=='cross'
                and type(leverage.get('value')) is int and leverage['value']==PAS_TARGET_LEVERAGE):
            verified.append(symbol)
        else:
            changes.append(dict(symbol=symbol,observed_ms=row['observed_ms'],before=leverage,
                requested_action=dict(type='updateLeverage',asset=spec['asset_id'],isCross=True,
                    leverage=PAS_TARGET_LEVERAGE)))
    account=discovery.get('account',{});equity=account.get('reported_account_equity',{})
    balance=decimal(equity.get('collateral_balance') or '0',nonnegative=True)
    blockers=['SEPARATE_EXACT_OPERATOR_CONFIGURATION_APPROVAL_REQUIRED'] if changes else []
    if balance<=0:blockers.append('PAS_USDP_FUNDING_REQUIRED_BEFORE_CONFIGURATION')
    if discovery.get('account_mode')!='unifiedAccount':blockers.append('HUMAN_VERIFIED_UNIFIED_MODE_REQUIRED')
    if discovery.get('terminal_flat') is not True:blockers.append('TWO_FRESH_FLAT_ZERO_ORDER_READBACKS_REQUIRED')
    local=discovery.get('local_execution_state',{})
    if local.get('status')!='NO_LOCAL_UNRESOLVED_INTENT':blockers.append('SHARED_UNKNOWN_AND_CONSUMED_INVOCATION_REVIEW_REQUIRED')
    if discovery.get('registration_evidence',{}).get('status')!='OPERATOR_REVIEWED_ORGANIZER_RECORD':
        blockers.append('REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED')
    plan=dict(status='UNSIGNED_CONFIGURATION_PLAN_ONLY',network='testnet',dex='pas',collateral='USDP',
        source_hash=discovery['source_hash'],observed_ms=discovery['finished_ms'],
        entry_markets=sorted(PAS_ENTRY_MARKETS),account_reconciliation_scope='ALL_CANONICAL_PAS_MARKETS',
        policy_basis='PAS BTC/EWY only; exact 20x CROSS per active market',
        team_wallet=TEAM,target_leverage=PAS_TARGET_LEVERAGE,margin_mode='cross',
        discovery_hash=fingerprint(discovery),changes=changes,already_target_cross=sorted(verified),
        collateral_balance=str(balance),organizer_credit_amount=None,
        organizer_credit_status='ORIGINAL_ORGANIZER_CREDIT_RECORD_REQUIRED; balance is not funding provenance',
        blockers=blockers,signing_authority='NONE',signatures_created=0,exchange_writes=0,
        transfers_allowed=False,configuration_approval_created=False,
        required_before_execution=['Fresh funded Unified account/agent/identity checks','Prior UNKNOWN/invocation review',
            'Exact new configuration-only approval','Shared sole host/signer/nonce ownership','Per-action exact permit and durable uncertainty',
            'Fresh readback of every requested 20x CROSS value'],
        note='Unsigned evidence only. Legacy 1x approval/execution routes cannot apply this proposal; no exchange write is authorized.')
    plan['plan_hash']=fingerprint(plan)
    return plan
