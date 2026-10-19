"""Offline fault injection; never claims actual par subminimum acceptance."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pytest

from exchange.base_exchange import ExchangeError
from exchange.partial_fill_safety import (
    partial_path_assessment, exact_full_close_size, residual_observation,
    VENUE_EXCEPTION_STATUS, TERMINAL_REJECTIONS)
from exchange.testnet_certification import require_safe_partial_path
from test_testnet_certification_v8 import cert, live
from test_live_exchange_execution import response


def test_one_lot_analysis_does_not_use_full_entry_notional(cert):
    spec = cert.live.client.market(cert.proposal.symbol)
    a = partial_path_assessment(spec, cert.proposal)
    assert D(cert.proposal.quantity)*D(cert.proposal.entry_limit) >= 10
    assert D(a['one_lot_notionals']['stop_limit']) < 10
    assert not a['entry_admissible_under_documented_minimum']
    assert a['subminimum_full_close_exception'] == VENUE_EXCEPTION_STATUS
    with pytest.raises(ExchangeError, match='SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED'):
        require_safe_partial_path(spec, cert.proposal)


@pytest.mark.parametrize('field', ['symbol', 'asset_id', 'quantity'])
def test_mapping_and_exact_entry_lots_cannot_be_bypassed(cert, field):
    values = dict(symbol='par:ETH', asset_id=0, quantity='0.24981')
    p = replace(cert.proposal, **{field: values[field]})
    with pytest.raises(ExchangeError): partial_path_assessment(cert.live.client.market('par:BTC'), p)


@pytest.mark.parametrize('signed,side', [('.2','SELL'), ('-.2','BUY')])
def test_valid_full_close_uses_exact_observed_quantity(cert, signed, side):
    cert.live.fixture.position(signed)
    held = cert.live.account.get_position('par:BTC')
    q = exact_full_close_size(cert.live.client.market('par:BTC'), held, side=side,
                            maximum_quantity='.25', limit_price='100')
    assert q == abs(D(signed))


@pytest.mark.parametrize('signed,side', [('.0001','SELL'), ('-.0001','BUY')])
def test_small_full_close_does_not_oversize_or_waive_minimum(cert, signed, side):
    cert.live.fixture.position(signed)
    held = cert.live.account.get_position('par:BTC'); spec = cert.live.client.market('par:BTC')
    with pytest.raises(ExchangeError, match='SUB_MINIMUM_RESIDUAL_CLOSE_NOT_VERIFIED'):
        exact_full_close_size(spec, held, side=side, maximum_quantity='.25', limit_price='100')
    with pytest.raises(ExchangeError, match='ORDER_BELOW_MINIMUM_NOTIONAL'):
        spec.normalize_order(side, abs(held.quantity), '100', reduce_only=True, tif='Ioc')
    assert not cert.venue.calls


@pytest.mark.parametrize('damage', ['wrong_side','oversize','flat','wrong_coin','dust','price'])
def test_invalid_full_close_is_rejected_without_rounding(cert, damage):
    cert.live.fixture.position('.2'); p = cert.live.account.get_position('par:BTC')
    side, maximum, px = 'SELL', '.25', '100'
    if damage == 'wrong_side': side = 'BUY'
    if damage == 'oversize': maximum = '.1'
    if damage == 'flat': p = replace(p, quantity=D(0))
    if damage == 'wrong_coin': p = replace(p, symbol='par:ETH')
    if damage == 'dust': p = replace(p, quantity=D('.20001'))
    if damage == 'price': px = '100.00001'
    with pytest.raises(ExchangeError):
        exact_full_close_size(cert.live.client.market('par:BTC'), p, side=side,
                             maximum_quantity=maximum, limit_price=px)


def test_tiny_partial_persists_residual_and_operator_action(cert):
    cert.venue.partial_entry = D('.1')
    r = cert.sequence.run()
    assert r['status'] == 'EMERGENCY_EXIT_REQUIRED' and r['operator_action_required']
    residual = r['residual_position']
    assert residual['subminimum_at_reviewed_bounds'] and residual['operator_review_required']
    assert D(residual['signed_quantity']) == cert.live.account.get_position('par:BTC').quantity
    assert cert.live.journal.control('certification_residual:'+cert.proposal.identity) == residual
    assert len(cert.venue.calls) == 1  # no attempted min-size top-up or oversized exit
    assert r['realized_pnl_status'] == 'REALIZED_PNL_NOT_CERTIFIED'


def test_subminimum_protection_is_refused_before_transmission(cert):
    cert.live.fixture.position('.0001')
    with pytest.raises(ExchangeError, match='SUB_MINIMUM_RESIDUAL_CLOSE_NOT_VERIFIED'):
        cert.live.executor.protection._plan('par:BTC', cert.live.account.get_position('par:BTC'),
                                           None, cert.live.fixture.now)
    assert not cert.venue.calls


def test_unrepresentable_residual_is_reported_not_flattened(cert):
    cert.live.fixture.position('.20001')
    obs = residual_observation(cert.live.client.market('par:BTC'),
        cert.live.account.get_position('par:BTC'), cert.proposal, cert.live.fixture.now)
    assert obs['quantity'] == '0.20001' and not obs['lot_representable']
    assert obs['operator_review_required']


def test_protection_readback_requires_current_full_position(cert):
    r = cert.sequence.run(); assert r['status'] == 'TRADE_CLOSED_RECONCILED'
    plan = cert.live.executor.protection._plan
    cert.live.fixture.position('.2')
    p = plan('par:BTC', cert.live.account.get_position('par:BTC'), None, cert.live.fixture.now)
    changed = replace(cert.live.account.get_position('par:BTC'), quantity=D('.15'))
    with pytest.raises(ExchangeError, match='CERTIFICATION_PROTECTION_POSITION_CHANGED'):
        cert.sequence._verify_protection(p, SimpleNamespace(), [], changed)


@pytest.mark.parametrize('terminal', ['minTradeNtlRejected', 'reduceOnlyRejected',
                                    'badTriggerPxRejected', 'marketOrderNoLiquidityRejected'])
def test_known_terminal_rejection_recovers_original_identity_without_retry(cert, terminal):
    req = dict(symbol='par:BTC', side='SELL', quantity='.2', price='100', reduce_only=True)
    row, _ = cert.live.journal.reserve('recovery-exit', req, 'test', cert.live.fixture.now)
    cert.live.journal.update('recovery-exit', 'UNKNOWN', cert.live.fixture.now)
    detail = dict(coin='par:BTC', cloid=row['cloid'], oid=501, side='A')
    cert.venue.statuses[row['cloid']] = dict(status='order', order=dict(order=detail, status=terminal))
    cert.live.executor.recovery.recover()
    recovered = cert.live.journal.intent('recovery-exit')
    assert recovered['state'] == 'REJECTED' and recovered['oid'] == '501'
    assert not cert.venue.calls


@pytest.mark.parametrize('status', ['unknownOid', 'unknown', 'unrecognized'])
def test_uncertain_order_stays_unknown_even_when_open_orders_are_empty(cert, status):
    row, _ = cert.live.journal.reserve('uncertain-exit',
        dict(symbol='par:BTC', side='SELL', quantity='.2', price='100', reduce_only=True),
        'test', cert.live.fixture.now)
    cert.live.journal.update('uncertain-exit', 'UNKNOWN', cert.live.fixture.now)
    cert.venue.statuses[row['cloid']] = dict(status=status)
    result = cert.live.executor.recovery.recover()
    assert not result.ready and cert.live.journal.intent('uncertain-exit')['state'] == 'UNKNOWN'
    assert not cert.venue.calls


def test_partial_cancel_recovery_preserves_actual_filled_size(cert):
    now = cert.live.fixture.now
    req = dict(symbol='par:BTC', side='BUY', quantity='.2', price='100', reduce_only=False)
    row, _ = cert.live.journal.reserve('partial-entry', req, 'test', now)
    cert.live.journal.update('partial-entry', 'UNKNOWN', now)
    cert.live.fixture.position('.12')
    cert.live.fixture.fill('.12', side='B', price='100', oid=502, tid=502, closed='0', fee='.0108')
    cert.venue.statuses[row['cloid']] = dict(status='order', order=dict(
        order=dict(coin='par:BTC', cloid=row['cloid'], oid=502), status='marginCanceled'))
    cert.live.executor.recovery.recover()
    recovered = cert.live.journal.intent('partial-entry'); result = json.loads(recovered['outcome'])
    assert recovered['state'] == 'PARTIALLY_FILLED'
    assert D(result['filled_quantity']) == D('.12') and D(result['remaining_quantity']) == D('.08')
    assert cert.live.account.get_position('par:BTC').quantity == D('.12')
    assert not cert.venue.calls


def test_rejected_exit_never_claims_flat_or_creates_another_entry(cert, monkeypatch):
    original = cert.venue.transmit
    def reject(payload):
        a = payload['action']
        if a['type'] == 'order' and a['orders'][0]['r'] and 'limit' in a['orders'][0]['t']:
            cert.live.transport.check(a); cert.auth.claim_transmission(a)
            cert.venue.calls.append(deepcopy(a))
            return response({'error':'Reduce only order would increase position.'})
        return original(payload)
    monkeypatch.setattr(cert.live.transport, 'transmit', reject)
    r = cert.sequence.run()
    assert r['status'] == 'EMERGENCY_EXIT_REQUIRED' and not r.get('final_flat')
    assert cert.live.account.get_position('par:BTC').quantity > 0
    assert len(r['exit_attempts']) == cert.proposal.max_exit_attempts
    assert sum(a['type']=='order' and not a['orders'][0]['r'] for a in cert.venue.calls) == 1
    assert cert.auth.revoked


def test_restart_after_partial_fill_recovers_exposure_without_new_entry(cert):
    cert.venue.partial_entry = D('.1'); first = cert.sequence.run()
    count = len(cert.venue.calls)
    cert.live.executor.recovery.recover()
    residual = cert.live.journal.control('certification_residual:'+cert.proposal.identity)
    assert D(residual['quantity']) == abs(cert.live.account.get_position('par:BTC').quantity)
    cert.auth.revoked = False
    from exchange.testnet_certification import CertificationSequence
    second = CertificationSequence(cert.live.executor, cert.proposal, cert.auth).run()
    assert second['status'] == 'PREFLIGHT_BLOCKED' and len(cert.venue.calls) == count
    assert first['realized_pnl_status'] == second['realized_pnl_status'] == 'REALIZED_PNL_NOT_CERTIFIED'


@pytest.mark.parametrize('bad_leverage', [False, True])
def test_read_only_proposal_is_explicitly_blocked_and_cannot_be_used_as_approval(cert, tmp_path, monkeypatch,
                                                                           bad_leverage):
    from pathlib import Path
    import importlib.util
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.testnet_certification import CertificationProposal
    path = Path(__file__).resolve().parents[1]/'scripts/run_testnet_certification.py'
    spec = importlib.util.spec_from_file_location('v8_2_preflight_fixture', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    class ReadOnlyFixture:
        def __call__(self, payload):
            value = cert.venue.read(payload)
            if bad_leverage and payload['type'] == 'activeAssetData':
                value['leverage'] = dict(type='cross', value=20)
            return value
        def close(self): pass
    client = HyperliquidClient(ReadOnlyFixture(), clock_ms=lambda:cert.live.fixture.now)
    monkeypatch.setattr(module, 'HyperliquidClient', lambda **_: client)
    monkeypatch.setattr(module, 'TEAM', cert.proposal.team_wallet)
    monkeypatch.setattr(module, 'API', cert.proposal.api_wallet)
    result = module.read_only_preflight(tmp_path/'preflight')
    assert result['status'] == 'PREFLIGHT_BLOCKED' and result['exchange_submissions'] == 0
    assert not result['signature_created'] and not cert.venue.calls
    if bad_leverage:
        assert result['blocker'] == 'CERTIFICATION_ONE_X_CROSS_REQUIRED'
    else:
        draft = result['review_only_proposal']
        assert not draft['executable'] and not draft['order_authorized']
        assert draft['blocker'] == 'SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED'
        assert (tmp_path/'preflight/blocked_proposal.json').is_file()
        assert not (tmp_path/'preflight/proposal.json').exists()
        with pytest.raises(TypeError): CertificationProposal(**draft)
