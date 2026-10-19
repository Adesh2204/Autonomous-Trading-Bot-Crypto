"""Canonical unsigned collateral evidence. A balance is never signing authority."""
from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from .testnet_certification import TEAM
from .venue_profiles import SCORED


def funding_evidence(*, team, mode, token, spot, state, observed_ms, now_ms, provenance, max_age_ms=360000):
    result = dict(status='USDP_UNAVAILABLE', team_wallet=team, network='testnet', dex='pas', collateral='USDP',
        account_mode=mode, token=token, observed_ms=observed_ms, exchange_time_ms=None,
        balance=None, age_ms=None, organizer_credit_amount=None, organizer_credit_provenance='UNKNOWN',
        signing_authority='NONE', reasons=[], response_hashes={}, provenance=provenance,
        equity_basis='Unified USDP total once; no addition of per-DEX equity or unrealized PnL')
    try:
        if team.lower()!=TEAM.lower():raise ExchangeError('EXACT_TEAM_ACCOUNT_REQUIRED')
        if type(token) is not int or token<0:raise ExchangeError('RUNTIME_USDP_TOKEN_REQUIRED')
        if type(observed_ms) is not int or type(now_ms) is not int:raise ExchangeError('FUNDING_CLOCK_REQUIRED')
        result['age_ms']=now_ms-observed_ms
        if not 0<=result['age_ms']<=max_age_ms:
            result['status']='USDP_STALE';raise ExchangeError('FUNDING_READ_STALE')
        if mode not in {'unifiedAccount','disabled'}:raise ExchangeError('ACCOUNT_MODE_UNAVAILABLE')
        if not isinstance(state,dict):raise ExchangeError('PAS_ACCOUNT_RESPONSE_REQUIRED')
        result['exchange_time_ms']=state.get('time') if type(state.get('time')) is int else None
        if mode=='disabled':
            # Standard mode is measured distinctly, but is not Unified readiness.
            balance=decimal(state['marginSummary']['totalRawUsd'],nonnegative=True)
            result['equity_basis']='STANDARD PAS totalRawUsd; Unified configuration remains required'
            result['reasons'].append('HUMAN_VERIFIED_UNIFIED_MODE_REQUIRED')
        else:
            balances=spot['balances']
            matches=[r for r in balances if r.get('coin')=='USDP' or r.get('token')==token]
            if len(matches)>1 or matches and (matches[0].get('coin')!='USDP' or type(matches[0].get('token')) is not int or matches[0]['token']!=token):
                raise ExchangeError('CANONICAL_USDP_TOKEN_BALANCE_MISMATCH')
            balance=decimal(matches[0]['total'],nonnegative=True) if matches else decimal(0)
        result.update(balance=str(balance),status='USDP_POSITIVE_VERIFIED' if balance>0 else 'USDP_ZERO',
            response_hashes=dict(spot=fingerprint(spot),state=fingerprint(state)))
    except (ExchangeError,ValueError,TypeError,KeyError,AttributeError) as exc:
        result['reasons'].append(str(exc) if isinstance(exc,ExchangeError) else 'INVALID_FUNDING_RESPONSE')
    result['evidence_hash']=fingerprint(result)
    return result


def read_funding(client, account, *, provenance):
    if (client.dex!='pas' or client.collateral!='USDP' or not client.ready
            or set(client.markets)!=SCORED.markets):raise ExchangeError('CANONICAL_PAS_METADATA_REQUIRED')
    started=client.clock_ms()
    mode=account._query('userAbstraction')
    spot=account._query('spotClearinghouseState')
    state=account._query('clearinghouseState')
    # Age from earliest response in the group; a slow final read cannot refresh it.
    return funding_evidence(team=account.team_address,mode=mode,token=client.collateral_token_id,
        spot=spot,state=state,observed_ms=started,now_ms=client.clock_ms(),provenance=provenance)


def current_funding(evidence, now_ms):
    value=dict(evidence or {})
    at=value.get('observed_ms')
    value['age_ms']=now_ms-at if type(at) is int else None
    if type(at) is not int or not 0<=now_ms-at<=360000:
        value.update(status='USDP_STALE' if evidence else 'USDP_UNAVAILABLE',balance=None)
    return value
