"""V4 entry policy, independent of the complete account/metadata universe.

No runtime flag expands this scope. Reduce-only management retains its own
exact authorization and exchange checks; this filter never hides exposure.
"""
from .base_exchange import ExchangeError

PAS_ENTRY_MARKETS = frozenset(('pas:BTC', 'pas:EWY', 'pas:HYPE'))


def require_entry(symbol):
    if symbol not in PAS_ENTRY_MARKETS:
        raise ExchangeError('V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY')


def signal_markets(client, requested=()):
    selected = tuple(requested) or tuple(sorted(
        PAS_ENTRY_MARKETS if getattr(client,'dex','par') == 'pas' else client.markets))
    if (not selected or len(set(selected)) != len(selected)
            or any(s not in client.markets for s in selected)
            or getattr(client,'dex','par') == 'pas' and not set(selected) <= PAS_ENTRY_MARKETS):
        raise ExchangeError('V4_SIGNAL_MARKET_SCOPE_REQUIRED')
    return selected


def require_entry_action(client, action):
    """Final actual SDK boundary; asset IDs always resolve from runtime metadata."""
    rows = action.get('orders', ()) if action.get('type') == 'order' else (
        [r.get('order', {}) for r in action.get('modifies', ())]
        if action.get('type') == 'batchModify' else ())
    for wire in rows:
        if wire.get('r') is True:
            continue
        matches = [s for s, spec in client.markets.items() if spec.asset_id == wire.get('a')]
        if client.dex != 'pas' or len(matches) != 1:
            raise ExchangeError('V4_EXACT_PAS_ENTRY_ASSET_REQUIRED')
        require_entry(matches[0])
