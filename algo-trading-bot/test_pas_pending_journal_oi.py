"""Pending journal entry OI safeguards; synthetic provider/journal only, no signing."""
from dataclasses import replace, asdict
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from exchange.execution_journal import ExecutionJournal
from exchange.exchange_rules import HyperliquidOrderValidator
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.order_lifecycle import OrderRequest
from test_pas_account_oi_regressions import NOW, _risk_context, _validate
from test_pas_migration import TEAM


class _SyntheticProvider:
    def __init__(self, context):
        self.context = context

    def load(self, request, *, critical=False):
        return self.context


def _journal(tmp_path, session):
    return ExecutionJournal(tmp_path / f'{session}.sqlite', session_id=session,
                           team_address=TEAM)


def _make_intent(journal, key, state):
    request = OrderRequest('pas:BTC', 'BUY', '.1', '100', client_order_id=key)
    row, fresh = journal.reserve(key, asdict(request), 'synthetic-candidate', NOW)
    assert fresh
    if state != 'PREPARED':
        journal.update(key, state, NOW + 1, oid=41 if state == 'OPEN' else None,
                       outcome={'remainder_cancelled': False}
                       if state == 'PARTIALLY_FILLED' else None)
    return journal.intent(key), request


def _execution_context(journal, context):
    provider = _SyntheticProvider(context)
    execution = HyperliquidExecution(
        SimpleNamespace(clock_ms=lambda: NOW), journal=journal, context_provider=provider)
    # Exercise the production enrichment step at the provider/journal boundary.
    return execution._context_with_journal_pending_entry(provider.load(None))


@pytest.mark.parametrize('state', [
    'PREPARED', 'SUBMITTED', 'UNKNOWN', 'OPEN', 'CANCEL_PENDING', 'PARTIALLY_FILLED',
])
def test_unrepresented_nonterminal_entry_intent_fails_closed_without_frontend_order(tmp_path, state):
    journal = _journal(tmp_path, f'pending-{state.lower()}')
    try:
        _make_intent(journal, f'{state.lower()}-entry', state)
        client, request, context, permission = _risk_context(orders=())
        context = _execution_context(journal, context)
        assert context.journal_only_entry_pending is True
        result = _validate(client, request, context, permission)
        assert not result.allowed
        assert result.code == 'UNRESOLVED_JOURNAL_ENTRY_NOT_VISIBLE'
    finally:
        journal.close()


def test_serial_unresolved_journal_entries_block_next_entry_when_neither_is_visible(tmp_path):
    journal = _journal(tmp_path, 'serial-pending')
    try:
        _make_intent(journal, 'first-entry', 'UNKNOWN')
        _make_intent(journal, 'second-entry', 'SUBMITTED')
        client, request, context, permission = _risk_context(orders=())
        context = _execution_context(journal, context)
        result = _validate(client, request, context, permission)
        assert context.journal_only_entry_pending
        assert not result.allowed and result.code == 'UNRESOLVED_JOURNAL_ENTRY_NOT_VISIBLE'
    finally:
        journal.close()


def test_journal_intent_matching_frontend_oid_cloid_uses_only_open_order_oi_reservation(tmp_path):
    journal = _journal(tmp_path, 'visible-order')
    try:
        row, _ = _make_intent(journal, 'visible-entry', 'OPEN')
        frontend = {'coin': 'pas:BTC', 'oid': 41, 'cloid': row['cloid'], 'side': 'B',
                    'sz': '.1', 'limitPx': '100', 'reduceOnly': False}
        client, request, context, permission = _risk_context(orders=(frontend, dict(frontend)))
        context = _execution_context(journal, context)
        assert context.journal_only_entry_pending is False
        result = _validate(client, request, context, permission)
        assert result.allowed
        # Duplicate provider appearances and the matching journal record do not add
        # another OI reservation; only the deduplicated authoritative order counts.
        assert result.audit['reserved_open_order_quantity'] == '0.1'
        assert result.audit['reserved_open_order_dex_notional'] == '10.0'
    finally:
        journal.close()


def test_conflicting_prefixed_and_unprefixed_oi_caps_fail_closed():
    client, request, context, permission = _risk_context()
    caps = dict(context.limits['coinToOiCap'])
    caps['pas:BTC'] = '10000'
    caps['BTC'] = '10001'
    context = replace(context, limits=dict(context.limits, coinToOiCap=caps))
    result = _validate(client, request, context, permission)
    assert not result.allowed and result.code == 'EXCHANGE_RULE_DATA_UNAVAILABLE'
