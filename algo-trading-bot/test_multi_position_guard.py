"""Multi-position account barrier (user directive 2026-10-25): up to 3 positions, one per market."""
from dataclasses import asdict
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from exchange.base_exchange import ExchangeError, Position
from exchange.execution_journal import ExecutionJournal
from exchange.multi_position_guard import MultiPositionGuard
from exchange.order_lifecycle import OrderRequest

NOW = 1_800_000_000_000
TEAM = '0x' + '1' * 40


def journal(tmp_path):
    return ExecutionJournal(tmp_path / 'j.sqlite', session_id='s', team_address=TEAM)


def ctx(positions=(), orders=(), *, fresh=True):
    held = {s: Position(s, D(q), D(100), D(0), D(0), None) for s, q in positions}
    return SimpleNamespace(positions=held, open_orders=list(orders), fills=[], reconciled=fresh, account_ms=NOW,
                           readiness=SimpleNamespace(account_ready=fresh))


def entry(symbol='pas:EWY', key=None):
    return OrderRequest(symbol, 'BUY', D(1), D(100), client_order_id=key)


def tp(coin):
    return dict(coin=coin, oid=7, isTrigger=False, reduceOnly=True, side='A', sz='1')


def guard(tmp_path, n=3):
    return MultiPositionGuard(journal(tmp_path), clock_ms=lambda: NOW, max_positions=n)


@pytest.mark.parametrize('n', [0, 4, True, '2'])
def test_limit_is_one_to_three(tmp_path, n):
    with pytest.raises(ExchangeError, match='INVALID_MAX_CONCURRENT_POSITIONS'):
        guard(tmp_path, n)


def test_restart_starts_unknown_and_blocks_entries(tmp_path):
    g = guard(tmp_path)
    assert g.state.value == 'UNKNOWN' and not g.report()['entry_permission']
    assert not g.evaluate(entry(), ctx(fresh=False), NOW).allowed


def test_flat_account_allows_the_first_entry(tmp_path):
    assert guard(tmp_path).evaluate(entry(), ctx(), NOW).allowed


def test_second_market_may_enter_while_first_is_held_with_its_take_profit(tmp_path):
    d = guard(tmp_path).evaluate(entry('pas:EWY'), ctx([('pas:BTC', '0.01')], [tp('pas:BTC')]), NOW)
    assert d.allowed and d.code == 'MULTI_POSITION_SLOT_PASS'


def test_a_held_market_cannot_be_added_to(tmp_path):
    assert not guard(tmp_path).evaluate(entry('pas:BTC'), ctx([('pas:BTC', '0.01')]), NOW).allowed


def test_limit_reached_blocks(tmp_path):
    held = [('pas:BTC', '0.01'), ('pas:EWY', '-1')]
    assert not guard(tmp_path, 2).evaluate(entry('pas:HYPE'), ctx(held), NOW).allowed
    assert guard(tmp_path, 3).evaluate(entry('pas:HYPE'), ctx(held), NOW).allowed


def test_exposure_over_the_limit_is_recovering(tmp_path):
    g = guard(tmp_path, 2)
    held = [('pas:BTC', '0.01'), ('pas:EWY', '-1'), ('pas:HYPE', '1')]
    assert not g.evaluate(entry('pas:ETH'), ctx(held), NOW).allowed and g.state.value == 'RECOVERING'


def test_resting_order_on_a_flat_market_blocks(tmp_path):
    assert not guard(tmp_path).evaluate(entry('pas:HYPE'), ctx([('pas:BTC', '0.01')], [tp('pas:EWY')]), NOW).allowed


def test_stale_account_blocks_even_with_a_free_slot(tmp_path):
    assert not guard(tmp_path).evaluate(entry(), ctx([('pas:BTC', '0.01')], fresh=False), NOW).allowed


def test_unresolved_entry_blocks_the_next_market(tmp_path):
    g = guard(tmp_path)
    g.reconcile(ctx([('pas:BTC', '0.01')]), NOW)
    g.journal.reserve('pending', asdict(entry('pas:EWY', 'pending')), 'c1', NOW, position_guard=g)
    assert g.journal.control('global_position_lock')['state'] == 'ENTRY_PENDING'
    assert not g.evaluate(entry('pas:HYPE'), ctx([('pas:BTC', '0.01')]), NOW).allowed


def test_reservation_is_refused_for_a_held_market_or_a_closed_slot(tmp_path):
    g = guard(tmp_path)
    g.reconcile(ctx([('pas:BTC', '0.01')]), NOW)
    with pytest.raises(ExchangeError, match='POSITION_LIMIT'):
        g.journal.reserve('k1', asdict(entry('pas:BTC', 'k1')), 'c1', NOW, position_guard=g)
    g.reconcile(ctx([('pas:BTC', '0.01')], [tp('pas:EWY')]), NOW)
    with pytest.raises(ExchangeError, match='POSITION_LIMIT'):
        g.journal.reserve('k2', asdict(entry('pas:HYPE', 'k2')), 'c2', NOW, position_guard=g)


def test_reservation_goes_stale_after_five_seconds(tmp_path):
    g = guard(tmp_path)
    g.reconcile(ctx([('pas:BTC', '0.01')]), NOW)
    with pytest.raises(ExchangeError, match='POSITION_LIMIT'):
        g.journal.reserve('k', asdict(entry('pas:EWY', 'k')), 'c', NOW + 5001, position_guard=g)


def test_revoke_closes_the_slot(tmp_path):
    g = guard(tmp_path)
    g.reconcile(ctx([('pas:BTC', '0.01')]), NOW)
    g.revoke('TEST')
    assert g.state.value == 'UNKNOWN' and not g.report()['entry_permission']


def test_reduce_only_exit_on_a_held_market_is_allowed(tmp_path):
    exit_ = OrderRequest('pas:BTC', 'SELL', D('0.01'), D(99), reduce_only=True)
    assert guard(tmp_path).evaluate(exit_, ctx([('pas:BTC', '0.01'), ('pas:EWY', '1')]), NOW).allowed
