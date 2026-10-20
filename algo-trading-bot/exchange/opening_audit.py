"""Independent opening-day verdicts from retained evidence; no action capability."""
from pathlib import Path
from types import SimpleNamespace
import time

from .base_exchange import ExchangeError
from .entry_scope import PAS_ENTRY_MARKETS
from .competition_market import PAS_TARGET_LEVERAGE
from .operator_status import current_status
from .paper_operations import active_source_hash
from .pas_controller import assess, fresh
from .terminal_evidence import local_execution_state
from .testnet_certification import TEAM, API


def opening_check(root, args):
    from .terminal_app import locked, read_json, sha
    from .long_session import require_release, require_native_evidence
    from .team_registration import registration_evidence
    from .venue_profiles import SCORED

    root=Path(root);state=Path(args.state).resolve();now=time.time_ns()//1000000
    source=active_source_hash(root);current=read_json(state/'current.json')
    value=current_status(read_json(Path(current['output'])/'status.json'),current,
        running=locked(state/'owner.lock'),now_ms=now,source_hash=source)
    errors={};release_verified=False;registered=False;agent_verified=False;native_markets=set()
    release=getattr(args,'release',None)
    if release:
        try:
            require_release(root,release,source,sha(release));release_verified=True
        except (OSError,ValueError,ExchangeError,KeyError) as exc:errors['release']=str(exc)
    organizer=getattr(args,'organizer_confirmation',None)
    if organizer:
        try:
            # The validator deliberately uses the fixed file name and retained
            # original record, rather than trusting a supplied summary flag.
            p=Path(organizer).resolve()
            if p.name!='organizer_confirmation.json':raise ExchangeError('EXACT_ORGANIZER_RECORD_FILE_REQUIRED')
            registration_evidence(p.parent,now);registered=True
        except (OSError,ValueError,ExchangeError,KeyError) as exc:errors['registration']=str(exc)
    discovery=getattr(args,'discovery',None)
    if discovery:
        try:
            d=read_json(discovery)
            if (d.get('status')!='READ_ONLY_DISCOVERY_COMPLETE' or d.get('network')!='testnet'
                or d.get('dex')!='pas' or d.get('collateral')!='USDP' or d.get('venue_identity')!=SCORED.identity
                or d.get('source_hash')!=source or d.get('source_hash_after')!=source
                or not fresh(d.get('started_ms'),now,300000) or not fresh(d.get('finished_ms'),now,300000)
                or d.get('funding',{}).get('team_wallet','').lower()!=TEAM.lower()):
                raise ExchangeError('FRESH_SOURCE_BOUND_PAS_ACCOUNT_DISCOVERY_REQUIRED')
            matches=[a for a in d.get('agents',[]) if isinstance(a,dict) and a.get('address','').lower()==API.lower()]
            agent_verified=len(matches)==1 and type(matches[0].get('validUntil')) is int and matches[0]['validUntil']>now
        except (OSError,ValueError,ExchangeError,KeyError,TypeError,AttributeError) as exc:errors['agent']=str(exc)
    native=getattr(args,'native_protection_evidence',None)
    if native:
        try:
            proof=read_json(native);markets=tuple(proof.get('markets',{}))
            if not markets or not set(markets)<=PAS_ENTRY_MARKETS:raise ExchangeError('BTC_EWY_PAS_PROOF_REQUIRED')
            require_native_evidence(native,SimpleNamespace(dex='pas',team_wallet=TEAM,api_wallet=API,markets=markets))
            native_markets=set(markets)
        except (OSError,ValueError,ExchangeError,KeyError,TypeError) as exc:errors['native']=str(exc)
    value['local_execution_state']=local_execution_state(root)
    value['release_verification']=dict(verified=release_verified,source_hash=source)
    readiness=assess(value,now);account=value.get('account') or {}
    account_current=(fresh(value.get('account_observed_ms'),now,360000) and not value.get('account_error')
        and account.get('source')=='EXCHANGE_REPORTED_ACCOUNT_OBSERVER'
        and account.get('entries_paused') is False and isinstance(account.get('positions'),list)
        and isinstance(account.get('open_orders'),list))
    healthy=(value.get('process_lock_held') is True and value.get('current_source_matches') is True
        and value.get('current_worker_matches') is True and fresh(value.get('updated_ms'),now,180000)
        and value.get('stream_connected') is True and value.get('stream_reconciled') is True
        and value.get('account_stream_healthy') is True and account_current
        and value.get('dex')=='pas' and value.get('collateral')=='USDP'
        and value.get('status') not in {'HALTED','STOPPED','HALTED_BEFORE_OR_DURING_START'}
        and not value.get('error') and not account.get('reasons'))
    liquidity=value.get('liquidity') or {};histories=value.get('market_history') or {}
    configured={s:account_current and liquidity.get(s,{}).get('active_asset',{}).get('leverage')==dict(type='cross',value=PAS_TARGET_LEVERAGE)
        and fresh(liquidity.get(s,{}).get('active_asset_ms'),now,360000) for s in PAS_ENTRY_MARKETS}
    qualified={s:s in native_markets and liquidity.get(s,{}).get('partial_minimum_admissible') is True
        and fresh(liquidity.get(s,{}).get('book_ms'),now,5000) for s in PAS_ENTRY_MARKETS}
    data_fresh=all(histories.get(s,{}).get('strategy_history_ready') is True
        and fresh(histories.get(s,{}).get('latest_completed_ms'),now,120000) for s in PAS_ENTRY_MARKETS)
    statuses=dict(AUTOMATION_IMPLEMENTED=release_verified,RELEASE_VERIFIED=release_verified,
        OBSERVER_HEALTHY=healthy,FUNDING_VERIFIED=readiness['gates']['USDP_FUNDING_VERIFIED'],
        ACCOUNT_IDENTITY_VERIFIED=registered and agent_verified and value.get('team_wallet','').lower()==TEAM.lower(),
        BTC_1X_CROSS_VERIFIED=configured['pas:BTC'],EWY_1X_CROSS_VERIFIED=configured['pas:EWY'],
        HISTORICAL_ORDER_SAFE=(account_current and not account.get('reasons')
            and value['local_execution_state']['status']=='NO_LOCAL_UNRESOLVED_INTENT'),
        BTC_NATIVE_AND_RESIDUAL_QUALIFIED=qualified['pas:BTC'],EWY_NATIVE_AND_RESIDUAL_QUALIFIED=qualified['pas:EWY'],
        MARKET_DATA_FRESH=data_fresh,EXACT_SESSION_ACCEPTED=value.get('authorization_valid') is True,
        TRADING_AUTHORIZED=value.get('TRADING_AUTHORIZED') is True,AUTO_TRADING_ACTIVE=value.get('AUTO_TRADING_ACTIVE') is True)
    steps=dict(
        AUTOMATION_IMPLEMENTED='Supply the passing current-source regression test_receipt.json with --release.',
        RELEASE_VERIFIED='Run the full regression after changes; supply its test_receipt.json with --release.',
        OBSERVER_HEALTHY='Review status/report and terminal reconciliation before a new public-only start.',
        FUNDING_VERIFIED='Run funding --output NEW_DIRECTORY after actual USDP arrives; no activation is inferred.',
        ACCOUNT_IDENTITY_VERIFIED='Supply --organizer-confirmation organizer_confirmation.json with retained original provenance and --discovery a fresh discover result.',
        BTC_1X_CROSS_VERIFIED='Require a fresh exact 1x CROSS readback; missing, malformed, or mismatched data blocks readiness. This code review authorizes no account change.',
        EWY_1X_CROSS_VERIFIED='Require a fresh exact 1x CROSS readback; missing, malformed, or mismatched data blocks readiness. This code review authorizes no account change.',
        HISTORICAL_ORDER_SAFE='Inspect the original qualification intent; obtain its terminal/rejection evidence or an independently validated and expressly authorized isolation policy. Never reset it.',
        BTC_NATIVE_AND_RESIDUAL_QUALIFIED='Run native-prepare --market pas:BTC --output NEW_DIRECTORY. Genuine PAS native/residual route qualification remains required; no executable PAS qualification route is currently admitted.',
        EWY_NATIVE_AND_RESIDUAL_QUALIFIED='Run native-prepare --market pas:EWY --output NEW_DIRECTORY. Genuine PAS native/residual route qualification remains required; no executable PAS qualification route is currently admitted.',
        MARKET_DATA_FRESH='Run history-review --output NEW_DIRECTORY; await authentic current completed PAS candles. No OHLC, PAR or mainnet substitution.',
        EXACT_SESSION_ACCEPTED='After prerequisites pass, prepare a finite mandate, review and accept it once with approve. No individual BUY/SELL prompts exist inside that scope.',
        TRADING_AUTHORIZED='Only after prerequisites and genuine acceptance, use start --venue pas --authorized with the exact mandate, acceptance, release and native proof.',
        AUTO_TRADING_ACTIVE='Wait for a current eligible frozen signal and an owned transmitted order with an actual matching fill during the accepted session.')
    verdict=('TRADING_ACTIVE' if statuses['TRADING_AUTHORIZED'] and statuses['AUTO_TRADING_ACTIVE']
        else 'AUTHORIZED_AWAITING_ACTIVITY' if statuses['TRADING_AUTHORIZED'] else 'NO_GO')
    return dict(observed_ms=now,source_hash=source,verdict=verdict,
        statuses=statuses,failed_requirements={k:dict(requirement=k,next_step=steps[k]) for k,v in statuses.items() if not v},
        evidence=dict(state=str(state),snapshot_source=value.get('source_hash'),process_lock_held=value.get('process_lock_held'),
            worker_status=value.get('status'),status_age_ms=value.get('status_age_ms'),funding=readiness['funding'],
            account_age_ms=value.get('account_age_ms'),local_execution_state=value['local_execution_state'],
            leverage={s:liquidity.get(s,{}).get('active_asset',{}).get('leverage') for s in sorted(PAS_ENTRY_MARKETS)},
            histories={s:histories.get(s,{}) for s in sorted(PAS_ENTRY_MARKETS)},validation_errors=errors),
        signing_authority='NONE_CREATED_BY_THIS_COMMAND',exchange_writes=0,signatures_created=0,
        scope='Local diagnostic only. Registration provenance is operator-reviewed. Public agent approval does not certify local signer ownership. Synthetic tests never qualify a venue or funded account.')
