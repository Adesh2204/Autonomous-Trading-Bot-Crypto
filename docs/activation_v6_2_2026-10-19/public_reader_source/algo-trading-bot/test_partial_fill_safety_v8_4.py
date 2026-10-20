"""Offline containment regressions; no claim of venue minimum exemptions.

Ephemeral SDK fixtures cannot authorize an actual small-position operation.
"""
from dataclasses import replace
from decimal import Decimal as D

import pytest

from exchange.base_exchange import ExchangeError
from exchange.order_lifecycle import OrderRequest
from exchange.testnet_certification import CertificationSequence
from test_live_exchange_execution import live, permission
from test_testnet_certification_v8 import cert


@pytest.mark.parametrize('signed,side', [('.0001','SELL'),('-.0001','BUY'),
                                      ('.0999','SELL'),('-.0999','BUY')])
@pytest.mark.parametrize('tif', ['Gtc','Ioc','Alo'])
def test_central_validator_keeps_minimum_for_exact_full_reduce_only_close(live, signed, side, tif):
    live.fixture.position(signed)
    request=OrderRequest('par:BTC',side,abs(D(signed)),'100',reduce_only=True,tif=tif)
    context=live.provider.load(request)
    held=context.positions['par:BTC']
    assert request.quantity==abs(held.quantity)
    result=live.validator.validate(request,context,
        permission(request,reason='SYNTHETIC_EXACT_FULL_CLOSE'),live.fixture.now)
    assert not result.allowed and result.code=='MIN_ORDER_NOTIONAL'
    assert D(result.audit['notional'])<10
    with pytest.raises(ExchangeError,match='ORDER_BELOW_MINIMUM_NOTIONAL'):
        live.executor.preview_request(request)
    assert not live.transport.signed_payloads
    assert live.journal.db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]==0


@pytest.mark.parametrize('residual', ['.0001','.0999'])
@pytest.mark.parametrize('protection_failure', [None,'protection_rejected'])
def test_partial_exit_dust_survives_recovery_without_oversizing_or_duplicate(cert, residual, protection_failure):
    original_quantity=D(cert.proposal.quantity)
    cert.venue.partial_exit=(original_quantity-D(residual))/original_quantity
    cert.venue.fail=protection_failure
    result=cert.sequence.run()
    held=cert.live.account.get_position('par:BTC')
    assert held is not None and held.quantity==D(residual)
    assert result['status']=='EMERGENCY_EXIT_REQUIRED'
    assert result['operator_action_required']
    assert not result.get('final_flat')
    assert result['realized_pnl_status']=='REALIZED_PNL_NOT_CERTIFIED'
    entries=[a for a in cert.venue.calls if a['type']=='order' and not a['orders'][0]['r']]
    exits=[a for a in cert.venue.calls if a['type']=='order' and a['orders'][0]['r']
           and 'limit' in a['orders'][0]['t']]
    assert len(entries)==len(exits)==1
    assert D(exits[0]['orders'][0]['s'])==original_quantity
    residual_record=cert.live.journal.control('certification_residual:'+cert.proposal.identity)
    assert D(residual_record['quantity'])==D(residual)
    assert residual_record['subminimum_at_reviewed_bounds']
    assert cert.auth.revoked
    calls_before=len(cert.venue.calls)
    signatures_before=len(cert.live.transport.signed_payloads)
    cert.live.executor.recovery.recover()
    assert cert.live.account.get_position('par:BTC').quantity==D(residual)
    # Fault injection permits the offline fixture to enter; actual activation
    # is blocked by require_safe_partial_path before any actual key is loaded.
    cert.auth.revoked=False
    restarted=CertificationSequence(cert.live.executor,cert.proposal,cert.auth).run()
    assert restarted['status']=='PREFLIGHT_BLOCKED'
    assert len(cert.venue.calls)==calls_before
    assert len(cert.live.transport.signed_payloads)==signatures_before
    assert cert.live.account.get_position('par:BTC').quantity==D(residual)
