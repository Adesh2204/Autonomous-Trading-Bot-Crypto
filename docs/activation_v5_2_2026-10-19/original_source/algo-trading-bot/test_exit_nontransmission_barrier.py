"""Offline regression for the historical UNKNOWN barrier; HTTP is forbidden.

The imported venue fixture signs only ephemeral test-wallet payloads. Neither
the real journal nor its immutable certificate is modified by these tests.
"""
from dataclasses import asdict, replace
from decimal import Decimal as D
from types import SimpleNamespace
import json
import pytest

from exchange.base_exchange import ExchangeError
from exchange.execution_journal import canonical, fingerprint
from exchange.order_lifecycle import OrderRequest
from exchange.qualification_intent_recovery import append_resolution, ORIGINAL_PROPOSAL
from exchange.qualification_protection import require_settled_exit_orders
from test_qualification_freshness_repair import proof_fixture, journal_with_original
from test_exit_recovery import recovered, draft
from test_emergency_qualification import emergency, live
from test_live_exchange_execution import response


@pytest.fixture
def historical(tmp_path):
    proof = proof_fixture()
    journal = journal_with_original(tmp_path, proof)
    executor = SimpleNamespace(journal=journal,
        account=SimpleNamespace(get_frontend_open_orders=lambda: []),
        client=SimpleNamespace(clock_ms=lambda: proof['account_observations'][-1]['observed_ms']))
    yield executor, proof
    journal.close()


def certify(journal, proof):
    return append_resolution(journal, proof, proof['account_observations'][-1]['observed_ms'])


def test_valid_certificate_settles_only_historical_intent_and_records_identity(historical):
    e, proof = historical
    original = e.journal.intents()
    result = certify(e.journal, proof)
    certificate = tuple(e.journal.db.execute('SELECT * FROM nontransmission_resolutions').fetchone())
    require_settled_exit_orders(e)
    assert e.journal.intents() == original and original[0]['state'] == 'UNKNOWN'
    assert tuple(e.journal.db.execute('SELECT * FROM nontransmission_resolutions').fetchone()) == certificate
    audit = json.loads(e.journal.db.execute("SELECT data FROM events WHERE kind="
        "'QUALIFICATION_EXIT_HISTORICAL_NONTRANSMISSION_VERIFIED'").fetchone()[0])
    assert audit['resolution_hash'] == fingerprint(proof) == result['resolution_hash']
    assert audit['original_state_preserved'] == 'UNKNOWN'
    assert audit['cloid'] == original[0]['cloid'] and audit['reason'] == result['reason']
    assert audit['settlement_scope'] == 'HISTORICAL_INTENT_ONLY'


def test_missing_certificate_still_blocks_historical_unknown(historical):
    e, _ = historical
    with pytest.raises(ExchangeError, match='EXIT_UNRESOLVED_ORDER'):
        require_settled_exit_orders(e)


@pytest.mark.parametrize('damage', ['wrong_identity', 'wrong_team', 'wrong_checksum',
    'tampered_proof', 'tampered_row', 'later_transmission'])
def test_wrong_or_contradicted_certificate_never_settles_exit(historical, damage):
    e, proof = historical
    if damage in {'wrong_identity', 'wrong_team', 'wrong_checksum', 'tampered_proof'}:
        # Deliberately forged table in an ephemeral test DB, never an append or
        # update to the genuine immutable resolution.
        key = proof['local']['original_row']['intent_key']
        original_hash = fingerprint(proof['local']['original_row'])
        if damage == 'wrong_identity': key = 'unrelated:entry'
        if damage == 'wrong_team': proof['team'] = '0x'+'99'*20
        checksum = fingerprint(proof)
        if damage == 'wrong_checksum': checksum = '0'*64
        if damage == 'tampered_proof':
            proof['local']['events'] = []
            checksum = fingerprint(proof)
        e.journal.db.execute('CREATE TABLE nontransmission_resolutions '
            '(intent_key TEXT,original_hash TEXT,proof TEXT,checksum TEXT)')
        e.journal.db.execute('INSERT INTO nontransmission_resolutions VALUES (?,?,?,?)',
            (key, original_hash, canonical(proof), checksum))
    else:
        certify(e.journal, proof)
        if damage == 'tampered_row':
            e.journal.db.execute("UPDATE intents SET oid='999'")
        else:
            e.journal.control('certification_transmissions:'+ORIGINAL_PROPOSAL,
                [dict(source='OFFLINE_CONTRADICTORY_TRANSMISSION')])
    with pytest.raises(ExchangeError, match='NONTRANSMISSION_RESOLUTION_INVALID'):
        require_settled_exit_orders(e)


@pytest.mark.parametrize('state', ['PREPARED', 'SUBMITTED', 'UNKNOWN', 'OPEN', 'CANCEL_PENDING', 'PARTIALLY_FILLED'])
def test_valid_certificate_cannot_suppress_other_unresolved_order(historical, state):
    e, proof = historical
    certify(e.journal, proof)
    request = OrderRequest('par:BTC', 'SELL', '.0002', '83000', reduce_only=True, tif='Ioc')
    row, _ = e.journal.reserve('offline:new-exit', asdict(request), 'offline:new', e.client.clock_ms())
    e.journal.update(row['intent_key'], state, e.client.clock_ms(),
        oid='123' if state == 'SUBMITTED' else None)
    if state == 'SUBMITTED':
        e.journal.event('QUALIFICATION_TRANSPORT_BOUNDARY', e.client.clock_ms(),
            cloid=row['cloid'], stage='HTTP_POST_STARTED')
    with pytest.raises(ExchangeError, match='EXIT_UNRESOLVED_ORDER|EXIT_UNSETTLED_REMAINDER'):
        require_settled_exit_orders(e)


def test_valid_certificate_does_not_override_open_orders_or_management(historical):
    e, proof = historical
    certify(e.journal, proof)
    e.account.get_frontend_open_orders = lambda: [dict(oid=456)]
    with pytest.raises(ExchangeError, match='OPEN_ORDER_RECONCILIATION'):
        require_settled_exit_orders(e)
    e.account.get_frontend_open_orders = lambda: []
    e.journal.db.execute("INSERT INTO signed_management(fingerprint,action,state,created_ms,updated_ms) "
        "VALUES ('fixture','{}','UNKNOWN',1,1)")
    with pytest.raises(ExchangeError, match='UNCERTAIN_MANAGEMENT_ACTION'):
        require_settled_exit_orders(e)


@pytest.fixture
def certified_exit(recovered, monkeypatch):
    c = recovered
    proof = proof_fixture()
    proof['team'] = c.p.team_wallet
    for read in proof['account_observations']: read['user'] = c.p.team_wallet
    # The real archive is verified by the barrier tests above. This composition
    # installs synthetic wallet globals, so use its recorded source descriptor;
    # certificate hashes, row binding and the full assessment still run.
    import exchange.qualification_intent_recovery as recovery_module
    source = dict(proof['source'])
    source.setdefault('signed_action_expiry_ms', proof['local']['original_row']['updated_ms']+300000)
    proof['source'] = source
    monkeypatch.setattr(recovery_module, 'archived_transport_source', lambda: source)
    original = proof['local']['original_row']
    names = [x[1] for x in c.live.journal.db.execute('PRAGMA table_info(intents)')]
    c.live.journal.db.execute('INSERT INTO intents VALUES ('+','.join('?' for _ in names)+')',
        [original[k] for k in names])
    certify(c.live.journal, proof)
    return c, original


@pytest.mark.parametrize('fraction', ['0', '.5', '1'])
def test_certified_history_with_filled_buy_allows_one_exact_sell_and_no_retry(certified_exit, fraction):
    c, original = certified_exit
    c.venue.partial_exit = D(fraction)
    r, p = draft(c)
    result = c.e.close_full_position(r, permission=p)
    assert len(c.venue.calls) == 1
    wire = c.venue.calls[0]['orders'][0]
    assert wire['r'] is True and wire['b'] is False and D(wire['s']) == D('.0002')
    position = c.live.account.get_position('par:BTC')
    assert (position.quantity if position else D(0)) == D('.0002')*(1-D(fraction))
    if fraction == '0': assert result.state.value == 'CANCELLED' and not result.filled_quantity
    if fraction == '1': assert result.filled_quantity == D('.0002')
    with pytest.raises(ExchangeError): c.e.close_full_position(r, permission=p)
    assert len(c.venue.calls) == 1
    assert c.live.journal.intent(original['intent_key']) == original
    assert c.live.journal.intent('offline:original-entry')['state'] == 'FILLED'


def test_certified_history_uncertain_sell_does_not_retransmit(certified_exit, monkeypatch):
    c, original = certified_exit
    transmit = c.live.transport.transmit
    def uncertain(payload):
        transmit(payload)
        raise TimeoutError('OFFLINE_LOST_SELL_ACK')
    monkeypatch.setattr(c.live.transport, 'transmit', uncertain)
    r, p = draft(c)
    c.e.close_full_position(r, permission=p)
    with pytest.raises(ExchangeError): c.e.close_full_position(r, permission=p)
    assert len(c.venue.calls) == 1 and c.live.journal.intent(original['intent_key']) == original


def test_certified_history_rejected_sell_preserves_position_and_no_retry(certified_exit, monkeypatch):
    c, _ = certified_exit
    c.venue.partial_exit = D(0)
    transmit = c.live.transport.transmit
    def rejected(payload):
        transmit(payload)
        return response(dict(error='Invalid order size.'))
    monkeypatch.setattr(c.live.transport, 'transmit', rejected)
    r, p = draft(c)
    result = c.e.close_full_position(r, permission=p)
    assert result.state.value == 'REJECTED'
    assert c.live.account.get_position('par:BTC').quantity == D('.0002')
    with pytest.raises(ExchangeError): c.e.close_full_position(r, permission=p)
    assert len(c.venue.calls) == 1


@pytest.mark.parametrize('damage', ['source', 'stale_account'])
def test_certificate_does_not_override_current_source_or_account_guards(certified_exit, monkeypatch, damage):
    c, _ = certified_exit
    if damage == 'source': c.auth.source_hash = lambda: 'changed-source'
    else:
        load = c.live.provider.load
        def stale(*a, **k):
            ctx = load(*a, **k)
            return replace(ctx, account_ms=c.live.fixture.now-5001)
        monkeypatch.setattr(c.live.provider, 'load', stale)
    r, p = draft(c)
    with pytest.raises(ExchangeError): c.e.close_full_position(r, permission=p)
    assert not c.venue.calls and not c.live.transport.signed_payloads
