"""Supplemental OFFLINE verification; ephemeral wallets, no venue qualification."""
import json
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from exchange.order_lifecycle import OrderRequest
from exchange.qualification_signing_boundary import fresh
from exchange.testnet_certification import test_permission as permission
from test_exchange_migration import NOW
from test_native_price_corridor import corridor, native, live
from test_native_signing_freshness import expire_after_nonce


@pytest.mark.parametrize('age,allowed', [(4900, True), (5000, True), (5100, False)])
def test_requested_exact_age_boundaries(corridor, age, allowed):
    original = corridor.context
    assert fresh(original, NOW + age) is allowed
    assert corridor.context == original


@pytest.mark.parametrize('delay', [4900, 5000, 5100, 5526])
def test_sdk_delay_reacquires_same_wire_without_duplicate(corridor, monkeypatch, delay):
    c = corridor
    c.venue.partial_entry = Decimal(0)
    before = asdict(c.p)
    calls = expire_after_nonce(c, monkeypatch, delay_ms=delay)
    nonces = []
    original_next = c.live.nonces.next

    def next_nonce():
        value = original_next()
        nonces.append(value)
        return value

    monkeypatch.setattr(c.live.nonces, 'next', next_nonce)
    result = c.sequence.run()
    assert result['status'] == 'NO_FILL_VERIFIED', result.get('error')
    entries = [a['orders'][0] for a in c.venue.calls if a['type'] == 'order' and not a['orders'][0]['r']]
    assert len(entries) == len(nonces) == 1
    row = c.live.journal.intent(c.sequence.prefix + 'entry')
    saved = OrderRequest(**json.loads(row['request']))
    assert str(saved.price) == entries[0]['p'] and saved.quantity == Decimal('.0002')
    assert asdict(c.p) == before and len(calls) >= 3
    prior_calls = len(c.venue.calls)
    c.live.executor.submit(saved, permission=permission(saved, c.p, c.live.fixture.now))
    assert len(c.venue.calls) == prior_calls and len(nonces) == 1


def test_own_unknown_cannot_renew_after_nonce(corridor, monkeypatch):
    c = corridor

    def change():
        c.live.journal.update(c.sequence.prefix + 'entry', 'UNKNOWN', c.live.fixture.now)

    expire_after_nonce(c, monkeypatch, change=change)
    result = c.sequence.run()
    assert result['status'] == 'EMERGENCY_EXIT_REQUIRED'
    assert c.live.journal.intent(c.sequence.prefix + 'entry')['state'] == 'UNKNOWN'
    assert not c.venue.calls and not c.live.transport.signed_payloads


def test_other_historical_unknown_blocks_entry_without_renewal(corridor):
    c = corridor
    key = 'offline:historical-unknown'
    request = OrderRequest('par:BTC', 'BUY', '.0002', c.p.entry_limit, tif='Ioc',
                           client_order_id=key, strategy_id='TESTNET_CERTIFICATION_ENTRY')
    c.live.journal.reserve(key, asdict(request), 'offline:prior', NOW)
    c.live.journal.update(key, 'UNKNOWN', NOW)
    before = c.live.journal.intent(key)
    result = c.sequence.run()
    assert result['status'] in {'EMERGENCY_EXIT_REQUIRED', 'PREFLIGHT_BLOCKED'}
    assert c.live.journal.intent(key) == before
    assert not c.venue.calls and not c.live.transport.signed_payloads
    assert not c.live.nonces.db.execute('SELECT last FROM nonces').fetchall()
