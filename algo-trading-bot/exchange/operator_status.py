"""Read-time status validation. Cached reports never restore signing authority."""
from copy import deepcopy

from .base_exchange import ExchangeError
from .pas_controller import assess, fresh


TERMINAL_STATUSES = frozenset({'STOPPED', 'HALTED', 'HALTED_BEFORE_OR_DURING_START',
    'STOPPED_FLAT_VERIFIED', 'HUMAN_RECOVERY_REVIEW_REQUIRED'})


def current_status(snapshot, current, *, running, now_ms, source_hash):
    """Return a diagnostic copy; never edit journals, receipts or the snapshot.

    A terminal flat readback remains historical evidence. An interrupted worker
    cannot assert current flatness, permission or active trading. All ages use
    the read clock, including while a dashboard displays an unchanged file.
    """
    if not isinstance(snapshot,dict) or not isinstance(current,dict):
        raise ExchangeError('INVALID_PUBLISHED_WORKER_STATUS')
    value = deepcopy(snapshot)
    updated = value.get('updated_ms')
    value.update(process_lock_held=running,
        status_age_ms=now_ms-updated if type(updated) is int else None)
    timely = fresh(updated, now_ms, 180000)
    source_matches = bool(source_hash and value.get('source_hash') == source_hash)
    identity_matches = (value.get('session_id') == current.get('session_id')
        and type(value.get('pid')) is int and value['pid'] == current.get('pid'))
    value.update(current_source_matches=source_matches, current_worker_matches=identity_matches)
    if not running and value.get('status') not in TERMINAL_STATUSES:
        value.update(status='INTERRUPTED_UNCLEAN', terminal_flat=None,
            residual_status='UNKNOWN_REQUIRES_FRESH_PUBLIC_RECONCILIATION')
    elif running and not timely:
        value.update(status='STALLED_OR_BOUNDED_RECOVERY_EXCEEDED', terminal_flat=None,
            residual_status='CACHED_ACCOUNT_TRUTH_REQUIRES_FRESH_READ')
    elif running and not source_matches:
        value.update(status='SOURCE_CHANGED_REQUIRES_RESTART', terminal_flat=None)
    elif running and not identity_matches:
        value.update(status='WORKER_IDENTITY_MISMATCH', terminal_flat=None)

    expiry = value.get('expires_ms')
    within_authority = type(expiry) is int and now_ms < expiry
    operational = (running and timely and source_matches and identity_matches
        and value.get('mode') == 'AUTHORIZED TESTNET TRADING'
        and value.get('authorization_valid') is True and value.get('TRADING_AUTHORIZED') is True
        and value.get('trading_status') == 'TRADING_ACTIVE' and within_authority)
    value['authority_observation_current'] = operational
    value['AUTO_TRADING_ACTIVE'] = (operational and value.get('AUTO_TRADING_ACTIVE') is True
        and value.get('exchange_activity_confirmed') is True)
    if not operational:
        had_authority = (value.get('TRADING_AUTHORIZED') is True or value.get('authorization_valid') is True
            or value.get('signing_authority') == 'EXACT_BOUNDED_LONG_MANDATE')
        value.update(TRADING_AUTHORIZED=False, AUTO_TRADING_ACTIVE=False, authorization_valid=False)
        if had_authority:
            reason = 'TRADING_EXPIRED' if type(expiry) is int and now_ms >= expiry else 'TRADING_BLOCKED'
            value.update(authorization_status=reason, trading_status=reason,
                signing_authority='REVOKED_OR_UNAVAILABLE')
    for field, age_field in (('account_observed_ms', 'account_age_ms'), ('fees_observed_ms', 'fee_age_ms')):
        at = value.get(field)
        value[age_field] = now_ms-at if type(at) is int else None
    for history in value.get('market_history', {}).values():
        at = history.get('latest_completed_ms')
        history['cache_age_ms'] = now_ms-at if type(at) is int else None
        history['data_freshness_satisfied'] = fresh(at, now_ms, 120000)
        history['strategy_history_ready'] = (history.get('strategy_history_ready') is True
            and history['data_freshness_satisfied'])
    if value.get('dex') == 'pas' and value.get('mode') == 'TESTNET OBSERVATION':
        if not source_matches:
            value['release_verification'] = dict(verified=False, reason='CURRENT_SOURCE_CHANGED')
        value['readiness'] = assess(value, now_ms)
        value['funding'] = value['readiness']['funding']
    return value
