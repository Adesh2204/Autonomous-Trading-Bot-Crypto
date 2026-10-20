"""Finite historical-isolation design. Review artifact only, never an order permit.

The proposal never reclassifies/deletes the original UNKNOWN, resets a consumed
attempt, bypasses account truth, or becomes a production import/capability.
"""
from pathlib import Path
from .base_exchange import ExchangeError
from .execution_journal import fingerprint
from .paper_operations import active_source_hash,atomic_json
from .testnet_certification import TEAM,API
from .configuration_isolation import assess,verify_local,verify_receipts,CLOID,INTENT,NONCE


def propose(proof,source,now_ms,*,minutes=60):
    if type(minutes) is not int or not 5<=minutes<=60:
        raise ExchangeError('ISOLATION_REVIEW_FINITE_FIVE_TO_SIXTY_MINUTES_REQUIRED')
    if not assess(proof,source,now_ms)['admissible']:
        raise ExchangeError('FRESH_ORIGINAL_HISTORY_AND_FLAT_READBACKS_REQUIRED')
    end=now_ms+minutes*60000
    result=dict(status='DRAFT_FINITE_TRADING_ISOLATION_POLICY_NOT_AUTHORIZATION',
        network='testnet',dex='pas',collateral='USDP',team_wallet=TEAM,api_wallet=API,
        source_hash=source,created_ms=now_ms,proposed_expires_ms=end,
        approval_deadline_ms=now_ms+300000,maximum_duration_ms=3600000,
        markets=['pas:BTC','pas:EWY'],original=dict(cloid=CLOID,intent_key=INTENT,nonce=NONCE,
            original_state='UNKNOWN',final_historical_outcome='UNKNOWN',consumed_attempt_preserved=True),
        read_only_evidence=proof,
        proposed_effect='If independently reviewed, implemented and genuinely accepted, exempt only the exact expired original PAR intent from the PAS shared local-intent precheck for this finite session. Never exempt a new/changed UNKNOWN or live exposure.',
        reconciliation_scope=['par','pas'],
        exposure_basis='Two post-nonce-horizon flat zero-order readbacks in the existing shared PAR/PAS migration scope. No claim of universal other-DEX account certification.',
        nonce_rules=['Original durable database and API signer only','Never reset/rollback nonce or consumed attempt',
            'Require healthy nonce/clock/rate state at each signed boundary','Sole team-account and API signer leases'],
        account_rules=['Fresh complete fill/fee/funding reconciliation from account truth',
            'Keep unresolved historical outcome separate from observed PnL',
            'Require fresh positions and frontend/open-order checks before each signed action',
            'Exactly one global approved position including pending/partial orders',
            'Any new UNKNOWN, disconnect or source/evidence change pauses entries and requires reconciliation'],
        proposed_session_ceilings=dict(bankroll='20000',maximum_notional_per_entry='1000',maximum_session_notional='2000',
            maximum_entry_attempts=2,maximum_concurrent_positions=1,maximum_signed_actions=12,
            risk_fraction='0.005',session_loss_fraction='0.01',session_loss_stop_usdp='200',
            leverage=1,margin_mode='CROSS',maximum_duration_minutes=minutes),
        qualification_is_separate=dict(maximum_entry_notional='25',maximum_entries=1,maximum_signed_actions=6,
            maximum_duration_ms=300000,requires_its_own_exact_human_acceptance=True,
            no_consumed_native_attempt_reset=True,subminimum_behavior_unqualified=True),
        protections=['Independently qualified actual PAS native reduce-only protection and residual route',
            'Approved stop geometry and unchanged production strategy',
            'Loss stop halts entries while mandatory risk exits retain their exact accepted scope',
            'No deadline/authority renewal or midnight reset','No transfer, account administration or extra market authority'],
        required_before_any_use=['Independent review of this narrow historical isolation design',
            'Fresh source-matched regression and raw receipt/source validation',
            'Explicit exact interactive isolation acceptance',
            'Dedicated reviewed runtime integration bound to an exact qualification or finite session mandate',
            'Separate actual PAS native/residual qualification',
            'Genuine finite session acceptance and all normal runtime/signing safeguards'],
        excluded_permissions=['No order/modify/cancel permit','No production shared-state override',
            'No retrospective claim that the original was never transmitted','No signer/key access',
            'No ordinary strategy or protection/minimum gate relaxation'],
        policy_acceptance_created=False,order_authority=False,signing_authority='NONE',
        signatures_created=0,exchange_writes=0,
        limitation='Public observations are evidence only. The existing configuration-only acceptance does not approve this trading policy. This module is not consumed by signed execution.')
    result['policy_hash']=fingerprint(result)
    return result


def collect(root,output,*,minutes=60):
    from .configuration_isolation import collect as collect_readbacks
    from .terminal_evidence import local_execution_state
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    proof=collect_readbacks(root,out/'read_only_observations')
    now=proof['finished_ms'];source=active_source_hash(root)
    verify_local(root,proof,source,now);verify_receipts(proof,out/'read_only_observations')
    local=local_execution_state(root)
    if local.get('unresolved')!=[dict(journal='qualification',cloid=CLOID,state='UNKNOWN',intent_key=INTENT)]:
        raise ExchangeError('NO_OTHER_UNKNOWN_MAY_BE_INCLUDED_IN_ISOLATION_REVIEW')
    policy=propose(proof,source,now,minutes=minutes)
    atomic_json(out/'isolation_policy.json',policy)
    return policy
