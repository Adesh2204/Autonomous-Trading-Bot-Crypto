"""Fresh PAS proposal/evidence assembly, never automatic human acceptance."""
from dataclasses import asdict,replace
from decimal import Decimal as D
from pathlib import Path
import json,shutil,socket,time,uuid
from .base_exchange import ExchangeError
from .venue_profiles import SCORED
from .entry_scope import PAS_ENTRY_MARKETS
from .venue_discovery import discover
from .paper_operations import active_source_hash,atomic_json
from .terminal_evidence import local_execution_state
from .long_session import sha,require_release,require_native_evidence
from .scored_session import ScoredLimits,ScoredLongMandate,SCORED_START_MS,SCORED_END_MS,require_scored_evidence
from .testnet_certification import TEAM,API
from .execution_journal import fingerprint


def copy_organizer_record(path,output):
    source=Path(path).resolve();record=json.loads(source.read_text())
    relative=Path(record.get('original_record_file','missing'))
    raw=(source.parent/relative).resolve()
    if (relative.is_absolute() or '..' in relative.parts or relative.suffix not in {'.eml','.txt','.json'}
            or not raw.is_relative_to(source.parent) or not raw.is_file()
            or sha(raw)!=record.get('original_record_sha256')):
        raise ExchangeError('LOCAL_ORGANIZER_PROVENANCE_RECORD_REQUIRED')
    # Fixed evidence names cannot be overwritten by a supplied original filename.
    target=output/('original_organizer_record'+relative.suffix)
    shutil.copyfile(raw,target)
    record['original_record_file']=target.name
    atomic_json(output/'organizer_confirmation.json',record)


def prepare_scored(root,args):
    if getattr(args,'overnight',False) or getattr(args,'practice_weekend',False):
        raise ExchangeError('PAS_CANNOT_REUSE_PRACTICE_CONTRACT')
    root=Path(root);output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    observation=discover(root,output/'fresh_discovery',venue='pas')
    atomic_json(output/'venue_discovery.json',observation)
    now=time.time_ns()//1000000;expires=min(now+args.minutes*60000,SCORED_END_MS)
    blockers=[]
    isolation_path=getattr(args,'trading_isolation_policy',None)
    isolation=None
    if isolation_path:
        from .trading_isolation import validate_policy
        isolation=validate_policy(root,isolation_path,source=active_source_hash(root),reference_ms=now)
        target=output/'trading_isolation'
        shutil.copytree(Path(isolation_path).parent,target)
        if Path(isolation_path).name!='policy.json':raise ExchangeError('CANONICAL_TRADING_ISOLATION_POLICY_FILE_REQUIRED')
        # A copied old acceptance must never be treated as acceptance of the new
        # mandate. This command only assembles an unsigned proposal.
        if (target/'acceptance.json').exists():raise ExchangeError('NEW_UNACCEPTED_ISOLATION_POLICY_REQUIRED')
        expires=min(expires,isolation['expires_ms'])
    if not SCORED_START_MS<=now<expires<=SCORED_END_MS:blockers.append('SCORED_PHASE_NOT_OPEN')
    local=local_execution_state(root)
    from .configuration_isolation import CLOID,INTENT
    only_original=local.get('unresolved')==[dict(journal='qualification',cloid=CLOID,state='UNKNOWN',intent_key=INTENT)]
    if local['status']!='NO_LOCAL_UNRESOLVED_INTENT' and not (isolation and only_original):blockers.append('SHARED_ACCOUNT_UNKNOWN_UNRESOLVED')
    if observation['status']!='READ_ONLY_DISCOVERY_COMPLETE' or observation.get('terminal_flat') is not True:
        blockers.append('COMPLETE_FRESH_ACCOUNT_DISCOVERY_REQUIRED')
    equity=observation.get('account',{}).get('reported_account_equity',{})
    if D(equity.get('collateral_balance') or '0')<=0:blockers.append('PAS_USDP_COLLATERAL_REQUIRED')
    requested=set(args.markets) if args.markets else PAS_ENTRY_MARKETS
    if not requested or not requested<=PAS_ENTRY_MARKETS:raise ExchangeError('EXPLICIT_PAS_MARKET_SCOPE_REQUIRED')
    snapshot={}
    timer=None
    try:
        import threading
        from .terminal_observer import observe
        stop=threading.Event();timer=threading.Timer(180,stop.set);timer.start()
        snapshot=observe(root,output/'strategy_observation',stop,
            lambda v:atomic_json(output/'strategy_snapshot.json',v),venue='pas',markets=sorted(requested),once=True)
    except Exception as exc:blockers.append('PAS_STRATEGY_OBSERVATION_FAILED:'+type(exc).__name__)
    finally:
        if timer:timer.cancel()
    if snapshot.get('latest_scan_ms') is None:blockers.append('COMPLETE_PAS_STRATEGY_SCAN_REQUIRED')
    eligible=[]
    for row in observation.get('markets',[]):
        if row['symbol'] not in requested:continue
        reasons=[]
        if row['active_asset'].get('leverage')!={'type':'cross','value':1}:reasons.append('PAS_ONE_X_CROSS_REQUIRED')
        if D(row['capacity'].get('liquidity_only_notional','0'))<10:reasons.append('ENTRY_AND_EXIT_CAPACITY_REQUIRED')
        # No full-close IOC exception is extrapolated to native trigger stops.
        # The existing conservative entry path requires every smallest partial
        # to meet the ordinary native minimum at the approved stop geometry.
        partial=snapshot.get('liquidity',{}).get(row['symbol'],{})
        if not partial.get('partial_minimum_admissible'):
            reasons.append('ACTUAL_PAS_NATIVE_AND_RESIDUAL_PROTECTION_REQUIRED')
        row['proposal_exclusions']=reasons
        if not reasons:eligible.append(row['symbol'])
    blockers.extend(sorted({r for row in observation.get('markets',[]) for r in row.get('proposal_exclusions',[])}))
    # Evidence is reviewed even when other prerequisites fail, so every remaining
    # issue is visible in a single concrete proposal. No dummy mandate is saved.
    organizer=getattr(args,'operator_confirmation',None) or getattr(args,'organizer_confirmation',None)
    if organizer:
        try:
            if getattr(args,'operator_confirmation',None):
                from .operator_account_confirmation import copy_confirmation
                copy_confirmation(organizer,output)
            else:copy_organizer_record(organizer,output)
        except (OSError,ValueError,ExchangeError) as exc:blockers.append(str(exc))
    else:blockers.append('ORIGINAL_REVIEWED_PAS_ORGANIZER_CONFIRMATION_REQUIRED')
    if not args.release:blockers.append('FINAL_SOURCE_MATCHED_REGRESSION_REQUIRED')
    else:
        try:require_release(root,args.release,active_source_hash(root),sha(args.release))
        except (OSError,ValueError,ExchangeError) as exc:blockers.append(str(exc))
    if not args.native_protection_evidence:blockers.append('ACTUAL_PAS_NATIVE_TRIGGER_CLOSING_FILL_REQUIRED')
    mandate=None
    if args.native_protection_evidence and args.release and eligible and not blockers:
        from .reliability_policy import load_reliability_policy
        limits=ScoredLimits('terminal:pas:'+uuid.uuid4().hex,TEAM,API,tuple(sorted(eligible)),('LONG',),
            now,expires,active_source_hash(root),socket.gethostname(),'20000',args.maximum_notional,
            args.maximum_notional,str(D(args.maximum_notional)*2))
        try:
            require_native_evidence(args.native_protection_evidence,limits)
            _,_,policy=load_reliability_policy(root/'configs/reliability_policy.json')
            identity_record=output/('operator_confirmation.json' if getattr(args,'operator_confirmation',None) else 'organizer_confirmation.json')
            mandate=ScoredLongMandate(limits,now,now+300000,sha(args.release),sha(root/'configs/reliability_policy.json'),
                sha(args.native_protection_evidence),fingerprint(asdict(replace(policy,enabled=True))),
                organizer_evidence_sha256=sha(identity_record),
                discovery_evidence_sha256=sha(output/'venue_discovery.json'),
                trading_isolation_policy_sha256=sha(output/'trading_isolation/policy.json') if isolation else '').require()
            require_scored_evidence(mandate,output)
        except (OSError,ValueError,ExchangeError) as exc:
            mandate=None;blockers.append(str(exc))
    proposal=dict(status='BLOCKED_NOT_AUTHORIZATION',network='testnet',dex='pas',collateral='USDP',
        venue_identity=SCORED.identity,created_ms=now,starts_ms=now,expires_ms=expires,
        source_hash=active_source_hash(root),team_wallet=TEAM,api_wallet=API,signing_host=socket.gethostname(),
        markets=sorted(requested),bankroll='20000',maximum_notional=args.maximum_notional,
        leverage=1,margin_mode='CROSS',directions=['LONG'],maximum_entry_attempts=2,
        maximum_concurrent_positions=1,maximum_signed_actions=12,maximum_owned_cancellations=2,
        risk_fraction='.005',session_loss_fraction='.01',execution_slippage_bps='5',depth_participation='.1',
        maximum_spread_bps='15',maximum_fee_rate='.003',approval_granted=False,
        maximum_cumulative_notional=str(D(args.maximum_notional)*2),
        risk_denominator='ALLOCATED_BANKROLL_20000_USDP; NOT_ACCOUNT_BALANCE_OR_ENTRY_NOTIONAL',
        maximum_intended_trade_loss_usdp='100',session_loss_stop_usdp='200',
        loss_basis='RECONCILED_REALIZED_PLUS_REPORTED_UNREALIZED_MINUS_FEES_PLUS_FUNDING; conservative exit-cost reserve; peak drawdown and initial-bankroll loss use the tighter bound',
        trading_isolation_status='POLICY_BOUND_NOT_ACCEPTED' if isolation else 'NONE',
        midnight_policy='CARRY_ATTEMPTS_ALLOCATION_PNL_DRAWDOWN_NO_RESET',
        blockers=sorted(set(blockers)),market_assessments=observation.get('markets',[]),
        signing_authority='NONE',native_protection_qualified=False,
        configuration_plan=observation.get('configuration_plan'),strategy_observation_status=snapshot.get('status'),
        note='No executable mandate while native/residual qualification is absent. Qualification needs its own exact approval. No per-trade prompt exists inside a subsequently qualified finite mandate.')
    if mandate:
        atomic_json(output/'mandate.json',asdict(mandate))
        proposal.update(status='EXACT_MANDATE_AWAITING_HUMAN_APPROVAL',mandate_hash=mandate.identity,
            blockers=['NEW_EXACT_HUMAN_APPROVAL_REQUIRED'],native_protection_qualified=True)
    atomic_json(output/'proposal.json',proposal);print(json.dumps(proposal,indent=2,default=str));return 0
