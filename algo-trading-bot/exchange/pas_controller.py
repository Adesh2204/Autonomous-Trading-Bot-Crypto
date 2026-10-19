"""Deterministic diagnostic gates. This controller has no execution capability."""
from decimal import Decimal, InvalidOperation
from .competition_windows import SCORED_START_MS, SCORED_END_MS
from .pas_funding import current_funding
from .venue_profiles import SCORED
from .entry_scope import PAS_ENTRY_MARKETS
from .competition_market import PAS_TARGET_LEVERAGE

STATES=('SCORING_WINDOW_OPEN','USDP_FUNDING_VERIFIED','PAS_ACCOUNT_CONFIGURATION_VERIFIED',
    'HISTORICAL_ORDER_SAFETY_VERIFIED','NATIVE_PROTECTION_QUALIFIED','MARKET_HISTORY_READY',
    'EXECUTABLE_OPPORTUNITY_AVAILABLE','SOURCE_RELEASE_VERIFIED','EXACT_SESSION_APPROVAL_ACCEPTED')


def fresh(at, now_ms, maximum):
    return type(at) is int and 0 <= now_ms-at <= maximum


def positive(value):
    try:
        number=Decimal(value)
        return number.is_finite() and number>0
    except (InvalidOperation,ValueError,TypeError):
        return False


def assess(report, now_ms):
    """Fail closed on absent/stale evidence, independently of the calendar/funding.

    Only the authorized worker validates an acceptance and acquires signing
    capabilities. Public observations never assert EXACT_SESSION_APPROVAL_ACCEPTED.
    """
    funding=current_funding(report.get('funding'),now_ms)
    liquidity=report.get('liquidity') or {};signals=report.get('signals') or []
    account_at=report.get('account_observed_ms')
    account_fresh=fresh(account_at,now_ms,360000) and not report.get('account_error')
    selected=set(report.get('markets') or PAS_ENTRY_MARKETS)
    valid_scope=bool(selected) and selected<=PAS_ENTRY_MARKETS
    configured=valid_scope and PAS_ENTRY_MARKETS<=set(liquidity) and all(
        isinstance(c.get('active_asset',{}).get('leverage'),dict)
        and c['active_asset']['leverage'].get('type')=='cross'
        and type(c['active_asset']['leverage'].get('value')) is int
        and c['active_asset']['leverage']['value']==PAS_TARGET_LEVERAGE
        and fresh(c.get('active_asset_ms'),now_ms,360000)
        for s,c in liquidity.items() if s in PAS_ENTRY_MARKETS)
    histories=report.get('market_history') or {}
    ready_symbols={s for s,h in histories.items() if s in selected and h.get('strategy_history_ready') is True
        and type(h.get('latest_completed_ms')) is int and 0<=now_ms-h['latest_completed_ms']<=120000}
    native=report.get('native_proof_verification',{})
    native_markets=set(native.get('markets',[])) if native.get('verified') is True else set()
    residual_markets=set(native.get('residual_markets',native_markets))
    protected_symbols=(native_markets & residual_markets & selected) if native.get('residual_scope_verified') is True else set()
    # Never combine protection on BTC with history/signal/liquidity on EWY.
    eligible_symbols=ready_symbols & protected_symbols
    opportunity_symbols={r.get('symbol') for r in signals if r.get('symbol') in eligible_symbols
        and r.get('decision')=='LONG' and fresh(r.get('observed_ms'),now_ms,5000)
        and fresh(liquidity.get(r['symbol'],{}).get('evidence_evaluation',{}).get('observed_ms'),now_ms,5000)
        and positive(liquidity.get(r['symbol'],{}).get('evidence_evaluation',{}).get('economically_viable_notional','0'))}
    opportunity=bool(opportunity_symbols)
    gates=dict(zip(STATES,(SCORED_START_MS<=now_ms<SCORED_END_MS,
        funding.get('status')=='USDP_POSITIVE_VERIFIED' and funding.get('account_mode')=='unifiedAccount' and account_fresh,
        configured and account_fresh,
        (report.get('local_execution_state') or {}).get('status')=='NO_LOCAL_UNRESOLVED_INTENT' and account_fresh,
        bool(protected_symbols) and native_markets<=PAS_ENTRY_MARKETS, bool(ready_symbols),opportunity,
        report.get('release_verification',{}).get('verified') is True and report.get('release_verification',{}).get('source_hash')==report.get('source_hash'),False)))
    reasons={
        'SCORING_WINDOW_OPEN':'SCORED_PHASE_NOT_OPEN' if now_ms<SCORED_START_MS else 'SCORED_PHASE_CLOSED',
        'USDP_FUNDING_VERIFIED':funding.get('status','USDP_UNAVAILABLE'),
        'PAS_ACCOUNT_CONFIGURATION_VERIFIED':'FRESH_BOTH_BTC_EWY_20X_CROSS_READBACKS_REQUIRED',
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
        entry_markets=sorted(selected),eligible_markets=sorted(eligible_symbols),opportunity_markets=sorted(opportunity_symbols),canonical_account_markets=sorted(SCORED.markets),state=reached,gates=gates,blockers=blockers,funding=funding,observed_ms=now_ms,
        next_action=blockers[0]['reason'],ready_for_operator_action=all(gates[s] for s in STATES[:-1]),
        terminal_status='READY_FOR_OBSERVATION',trading_verdict='NO_GO',signing_authority='NONE',
        native_protection='NATIVE_ROUNDTRIP_PROOF_PRESENT_RESIDUAL_SCOPE_SEPARATE' if native_markets else 'UNQUALIFIED_WITHOUT_VALIDATED_RAW_PROOF',historical_safety='RESOLVED' if gates['HISTORICAL_ORDER_SAFETY_VERIFIED'] else 'BLOCKED',
        note='Diagnostic gates cannot create approval, isolation, protection qualification or a signer')
