"""Deterministic diagnostic gates. This controller has no execution capability."""
from decimal import Decimal
from .competition_windows import SCORED_START_MS, SCORED_END_MS
from .pas_funding import current_funding
from .venue_profiles import SCORED
from .entry_scope import PAS_ENTRY_MARKETS

STATES=('SCORING_WINDOW_OPEN','USDP_FUNDING_VERIFIED','PAS_ACCOUNT_CONFIGURATION_VERIFIED',
    'HISTORICAL_ORDER_SAFETY_VERIFIED','NATIVE_PROTECTION_QUALIFIED','MARKET_HISTORY_READY',
    'EXECUTABLE_OPPORTUNITY_AVAILABLE','SOURCE_RELEASE_VERIFIED','EXACT_SESSION_APPROVAL_ACCEPTED')


def assess(report, now_ms):
    """Fail closed on absent/stale evidence, independently of the calendar/funding.

    Only the authorized worker validates an acceptance and acquires signing
    capabilities. Public observations never assert EXACT_SESSION_APPROVAL_ACCEPTED.
    """
    funding=current_funding(report.get('funding'),now_ms)
    liquidity=report.get('liquidity') or {};signals=report.get('signals') or []
    account_at=report.get('account_observed_ms')
    fresh=type(account_at) is int and 0<=now_ms-account_at<=360000 and not report.get('account_error')
    selected=set(report.get('markets') or PAS_ENTRY_MARKETS)
    valid_scope=bool(selected) and selected<=PAS_ENTRY_MARKETS
    configured=valid_scope and selected<=set(liquidity) and all(
        c.get('active_asset',{}).get('leverage')=={'type':'cross','value':1}
        and type(c.get('active_asset_ms')) is int and 0<=now_ms-c['active_asset_ms']<=360000 for s,c in liquidity.items() if s in selected)
    histories=report.get('market_history') or {}
    ready_symbols={s for s,h in histories.items() if s in selected and h.get('strategy_history_ready') is True
        and type(h.get('latest_completed_ms')) is int and 0<=now_ms-h['latest_completed_ms']<=120000}
    opportunity=any(r.get('symbol') in ready_symbols and r.get('decision')=='LONG'
        and 0<=now_ms-r.get('observed_ms',-1)<=5000 and
        Decimal(liquidity.get(r['symbol'],{}).get('evidence_evaluation',{}).get('economically_viable_notional','0'))>0 for r in signals)
    native=report.get('native_proof_verification',{})
    native_markets=set(native.get('markets',[])) if native.get('verified') is True else set()
    gates=dict(zip(STATES,(SCORED_START_MS<=now_ms<SCORED_END_MS,
        funding.get('status')=='USDP_POSITIVE_VERIFIED' and funding.get('account_mode')=='unifiedAccount' and fresh,
        configured and fresh,
        (report.get('local_execution_state') or {}).get('status')=='NO_LOCAL_UNRESOLVED_INTENT' and fresh,
        bool(native_markets & selected) and native_markets<=PAS_ENTRY_MARKETS and native.get('residual_scope_verified') is True, bool(ready_symbols),opportunity,
        report.get('release_verification',{}).get('verified') is True and report.get('release_verification',{}).get('source_hash')==report.get('source_hash'),False)))
    reasons={
        'SCORING_WINDOW_OPEN':'SCORED_PHASE_NOT_OPEN' if now_ms<SCORED_START_MS else 'SCORED_PHASE_CLOSED',
        'USDP_FUNDING_VERIFIED':funding.get('status','USDP_UNAVAILABLE'),
        'PAS_ACCOUNT_CONFIGURATION_VERIFIED':'FRESH_SELECTED_BTC_EWY_ONE_X_CROSS_READBACKS_REQUIRED',
        'HISTORICAL_ORDER_SAFETY_VERIFIED':'SHARED_UNKNOWN_OR_ACCOUNT_REVIEW_REQUIRED',
        'NATIVE_PROTECTION_QUALIFIED':'GENUINE_PAS_NATIVE_AND_RESIDUAL_PROOF_REQUIRED',
        'MARKET_HISTORY_READY':'AUTHENTIC_CONTIGUOUS_300_BAR_WARMUP_REQUIRED',
        'EXECUTABLE_OPPORTUNITY_AVAILABLE':'NO_FRESH_EXECUTABLE_POSITIVE_CONDITIONAL_LONG_SETUP',
        'SOURCE_RELEASE_VERIFIED':'CURRENT_SOURCE_MATCHED_REGRESSION_REQUIRED',
        'EXACT_SESSION_APPROVAL_ACCEPTED':'NEW_EXACT_HUMAN_SESSION_APPROVAL_REQUIRED'}
    reached='PREOPEN_OBSERVATION'
    for name in STATES:
        if not gates[name]:break
        reached=name
    blockers=[dict(gate=k,reason=reasons[k]) for k in STATES if not gates[k]]
    return dict(automation_status='AUTOMATION_SOFTWARE_READY' if gates['SOURCE_RELEASE_VERIFIED'] else 'TRADING_BLOCKED',
        venue_qualification_status='VENUE_QUALIFICATION_READY' if valid_scope and all(gates[s] for s in STATES[1:7]) else 'TRADING_BLOCKED',
        authorization_status='AWAITING_HUMAN_SESSION_APPROVAL' if all(gates[s] for s in STATES[:-1]) else 'TRADING_BLOCKED',
        entry_markets=sorted(selected),canonical_account_markets=sorted(SCORED.markets),state=reached,gates=gates,blockers=blockers,funding=funding,observed_ms=now_ms,
        next_action=blockers[0]['reason'],ready_for_operator_action=all(gates[s] for s in STATES[:-1]),
        terminal_status='READY_FOR_OBSERVATION',trading_verdict='NO_GO',signing_authority='NONE',
        native_protection='NATIVE_ROUNDTRIP_PROOF_PRESENT_RESIDUAL_SCOPE_SEPARATE' if native_markets else 'UNQUALIFIED_WITHOUT_VALIDATED_RAW_PROOF',historical_safety='RESOLVED' if gates['HISTORICAL_ORDER_SAFETY_VERIFIED'] else 'BLOCKED',
        note='Diagnostic gates cannot create approval, isolation, protection qualification or a signer')
