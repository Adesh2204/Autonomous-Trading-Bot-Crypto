"""Offline native SDK composition only. Never certifies an actual stop/fill."""
from copy import deepcopy
from dataclasses import asdict, replace, fields
from decimal import Decimal as D
import json
from types import SimpleNamespace
import pytest

from exchange.base_exchange import ExchangeError
from exchange.order_lifecycle import OrderRequest, OrderState
from exchange.qualification_protection import QualificationStopManager, require_settled_exit_orders
from exchange.testnet_certification import (test_permission as cert_permission, CertificationProposal,
    CertificationApproval, CertificationAuthorization)
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.emergency_qualification import permission as emergency_permission, EmergencySequence
from test_testnet_certification_v8 import cert
from test_emergency_qualification import emergency
from test_live_exchange_execution import live, response
from test_exchange_migration import NOW


@pytest.fixture
def stop(cert):
    c = cert
    c.live.executor.recovery.recover()
    c.live.executor.entries_paused = False
    p = c.proposal
    request = OrderRequest(p.symbol,p.entry_side,p.quantity,p.entry_limit,
        strategy_id='TESTNET_CERTIFICATION_ENTRY',tif='Ioc',
        client_order_id=c.sequence.prefix+'entry')
    order = c.live.executor.submit(request,permission=cert_permission(request,p,NOW))
    assert order.state == OrderState.FILLED
    c.manager = QualificationStopManager(c.live.executor,p)
    c.stop_key = c.sequence.prefix+'protection'
    return c


def submit_stop(c):
    result = c.manager.submit(c.stop_key)
    assert result['status']=='READBACK_ACCEPTED',json.dumps(result,default=str)
    assert result['coverage_observed'] and not result['protection_verified']
    return result


def trigger(c, *, quantity='0', child=True, child_state='open'):
    """Synthetic venue evidence of a triggered stop; no implicit fills."""
    saved=c.live.journal.control(c.manager.key)
    intent=c.live.journal.intent(c.manager.intent_key)
    parent=c.venue.statuses[intent['cloid']]
    detail=parent['order']['order'];parent['order']['status']='triggered'
    qty=D(quantity);requested=D(detail['origSz']);remaining=requested-qty
    child_id=999
    detail['children']=[dict(oid=child_id)] if child else []
    if child:
        row=dict(coin=c.proposal.symbol,side='A',oid=child_id,cloid=None,
            sz=str(remaining),origSz=str(requested),limitPx=detail['limitPx'],
            isTrigger=False,reduceOnly=True,orderType='Limit',timestamp=NOW)
        c.venue.statuses[str(child_id)]=dict(status='order',order=dict(order=row,status=child_state))
        c.live.fixture.orders=[row] if child_state=='open' else []
    else:
        c.live.fixture.orders=[]
    if qty:
        oid=child_id if child else detail['oid']
        c.live.fixture.position(remaining,str(c.proposal.entry_limit))
        c.live.fixture.fill(qty,side='A',price=detail['limitPx'],oid=oid,tid=1234,fee='0')
    return parent


def test_native_fixed_size_stop_wire_and_readback_never_capability_certification(stop):
    c=stop;r=submit_stop(c);wire=c.venue.calls[-1]['orders'][0]
    assert wire['r'] is True and wire['b'] is False
    assert wire['s']==c.proposal.quantity
    assert D(wire['t']['trigger']['triggerPx'])==D(c.proposal.stop_trigger)
    assert wire['t']['trigger']['isMarket'] is False and wire['t']['trigger']['tpsl']=='sl'
    assert r['filled_quantity']=='0' and not c.manager.entries_allowed
    assert len(c.venue.calls)==2 and not r['flat_observed']


def test_ack_without_readback_is_unknown_not_protection(stop,monkeypatch):
    c=stop;original=c.venue.read
    def read(payload):
        if payload['type']=='orderStatus':return {'status':'unknownOid'}
        return original(payload)
    c.live.client.transport=read
    r=c.manager.submit(c.stop_key)
    assert r['status']=='UNKNOWN' and not r['coverage_observed']
    count=len(c.venue.calls)
    with pytest.raises(ExchangeError,match='READ_ONLY_RECOVERY'):
        c.manager.submit(c.stop_key+':new')
    assert len(c.venue.calls)==count


@pytest.mark.parametrize('failure',['protection_rejected','protection_timeout_before','protection_timeout_after'])
def test_rejected_or_uncertain_stop_not_duplicated(stop,failure):
    c=stop;c.venue.fail=failure;r=c.manager.submit(c.stop_key)
    expected={'protection_timeout_after':'READBACK_ACCEPTED','protection_rejected':'REJECTED'}.get(failure,'UNKNOWN')
    assert r['status']==expected,r
    assert not r['protection_verified']
    with pytest.raises(ExchangeError,match='READ_ONLY_RECOVERY'):
        c.manager.submit(c.stop_key)
    assert len(c.venue.calls)==2 and c.live.account.get_position(c.proposal.symbol)


@pytest.mark.parametrize('size',['.0001','.0002'])
def test_btc_partial_entry_exact_stop_size_ordinary_minimum_preserved(emergency,size):
    c=emergency;c.live.fixture.position(size,c.p.entry_limit)
    manager=QualificationStopManager(c.live.executor,c.p)
    held=c.live.account.get_position(c.p.symbol)
    if size=='.0001':
        with pytest.raises(ExchangeError,match='SMALL_STOP_VENUE_SUPPORT_UNVERIFIED'):
            manager._plan(c.p.symbol,held,None,NOW)
    else:
        plan=manager._plan(c.p.symbol,held,None,NOW)
        assert plan.quantity==D(size) and not plan.is_market
    assert c.live.account.get_position(c.p.symbol).quantity==D(size)
    assert not c.venue.calls


def test_emergency_no_stop_approval_cannot_authorize_native_stop(emergency):
    c=emergency;c.auth.require(c.p.team_wallet,c.p.api_wallet)
    c.live.executor.entries_paused=False
    request=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc',
        strategy_id='TESTNET_CERTIFICATION_ENTRY',client_order_id=c.sequence.prefix+'entry')
    c.live.executor.submit(request,permission=emergency_permission(request,c.p,NOW))
    manager=QualificationStopManager(c.live.executor,c.p)
    result=manager.submit(c.sequence.prefix+'protection')
    assert result['status']=='UNKNOWN' and not result['coverage_observed']
    assert len(c.venue.calls)==1  # Existing authorization rejects trigger action.


@pytest.mark.parametrize('field,value',[('reduceOnly',False),('side','B'),('origSz','1'),
    ('limitPx','1'),('triggerPx','1'),('cloid','other'),('coin','par:ETH'),('orderType','Stop Market'),('oid',-1)])
def test_mismatched_stop_readback_blocks_coverage(stop,field,value):
    c=stop;submit_stop(c)
    c.venue.statuses[c.live.journal.intent(c.stop_key)['cloid']]['order']['order'][field]=value
    r=c.manager.reconcile()
    assert r['status']=='UNKNOWN' and not r['coverage_observed']


def test_frontend_and_order_status_must_agree(stop):
    c=stop;submit_stop(c)
    c.live.fixture.orders=deepcopy(c.live.fixture.orders)
    c.live.fixture.orders[0]['sz']='.1'
    assert c.manager.reconcile()['status']=='UNKNOWN'


def test_changed_position_does_not_oversize_stop_or_auto_replace(stop):
    c=stop;submit_stop(c);count=len(c.venue.calls)
    c.live.fixture.position(D(c.proposal.quantity)/2,c.proposal.entry_limit)
    r=c.manager.reconcile()
    assert r['status']=='STALE_COVERAGE' and not r['coverage_observed']
    assert len(c.venue.calls)==count and not r['protection_verified']


@pytest.mark.parametrize('quantity,child_state,status',[
    ('0','open','TRIGGERED_UNSETTLED'),('.1','open','TRIGGERED_UNSETTLED'),
    ('.1','canceled','PARTIALLY_FILLED'),('FULL','filled','FILLED'),('0','rejected','REJECTED')])
def test_triggered_child_execution_and_residual_are_separate(stop,quantity,child_state,status):
    c=stop;quantity=c.proposal.quantity if quantity=='FULL' else quantity
    submit_stop(c);trigger(c,quantity=quantity,child_state=child_state)
    r=c.manager.reconcile()
    assert r['status']==status,r
    assert D(r['remaining_position_quantity'])==D(c.proposal.quantity)-D(quantity)
    assert not r['coverage_observed'] and not r['protection_verified']
    assert r['remainder_settled']==(child_state!='open')
    assert r['flat_observed']==(quantity==c.proposal.quantity)


@pytest.mark.parametrize('quantity',['0','.1','FULL'])
def test_triggered_parent_without_child_needs_complete_fills_and_flat(stop,quantity):
    c=stop;quantity=c.proposal.quantity if quantity=='FULL' else quantity
    submit_stop(c);trigger(c,quantity=quantity,child=False)
    r=c.manager.reconcile()
    assert r['status']==('FILLED' if quantity==c.proposal.quantity else 'TRIGGERED_UNSETTLED'),r
    assert not r['protection_verified']


def test_child_unknown_never_proves_cancellation(stop):
    c=stop;submit_stop(c);trigger(c,child_state='canceled')
    del c.venue.statuses['999']
    r=c.manager.reconcile()
    assert r['status']=='UNKNOWN' and not r.get('remainder_settled',False)


@pytest.mark.parametrize('field,value',[('coin','par:ETH'),('reduceOnly',False),('side','B'),
    ('origSz','1'),('limitPx','1'),('oid',998)])
def test_bad_child_identity_blocks_stop_settlement(stop,field,value):
    c=stop;submit_stop(c);trigger(c,child_state='canceled')
    c.venue.statuses['999']['order']['order'][field]=value
    assert c.manager.reconcile()['status']=='UNKNOWN'


def test_duplicate_child_ids_block_and_duplicate_fills_are_not_double_counted(stop):
    c=stop;submit_stop(c);parent=trigger(c,quantity='.1',child_state='canceled')
    c.live.fixture.fills.append(deepcopy(c.live.fixture.fills[-1]))
    assert D(c.manager.reconcile()['filled_quantity'])==D('.1')
    parent['order']['order']['children'].append(dict(oid=999))
    assert c.manager.reconcile()['status']=='UNKNOWN'


def test_filled_status_without_actual_fills_never_marks_flat(stop):
    c=stop;submit_stop(c)
    c.venue.statuses[c.live.journal.intent(c.stop_key)['cloid']]['order']['status']='filled'
    c.live.fixture.orders=[]
    r=c.manager.reconcile()
    assert r['status']=='UNKNOWN' and not r.get('flat_observed',False)


@pytest.mark.parametrize('uncertain',[False,True])
def test_cancel_requires_readback_and_is_one_bounded_attempt(stop,uncertain):
    c=stop;submit_stop(c);c.venue.cancel_uncertain=uncertain
    r=c.manager.cancel()
    assert r['status']==('UNKNOWN' if uncertain else 'CANCELLED'),r
    assert not r['coverage_observed'] and not r['protection_verified']
    assert c.live.account.get_position(c.proposal.symbol)
    count=len(c.venue.calls)
    with pytest.raises(ExchangeError,match='ALREADY_ATTEMPTED'):
        c.manager.cancel()
    assert len(c.venue.calls)==count


def test_fill_during_cancel_uses_actual_position_not_ack(stop,monkeypatch):
    c=stop;submit_stop(c);original=c.venue.transmit
    def transmit(payload):
        if payload['action']['type']=='cancel':
            trigger(c,quantity=c.proposal.quantity,child=False)
        return original(payload)
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.manager.cancel()
    assert r['status']=='FILLED' and r['flat_observed'] and not r['protection_verified'],r


@pytest.mark.parametrize('rest_up',[False,True])
def test_disconnect_requires_rest_and_never_submits_again(stop,rest_up):
    c=stop;submit_stop(c);count=len(c.venue.calls)
    assert c.manager.on_disconnect()['status']=='UNKNOWN'
    c.venue.rest_down=not rest_up
    r=c.manager.reconcile()
    assert r['status']==('READBACK_ACCEPTED' if rest_up else 'UNKNOWN')
    assert len(c.venue.calls)==count


def test_restart_ignores_saved_active_flag_and_reuses_original_id(stop):
    c=stop;submit_stop(c);count=len(c.venue.calls)
    c.manager=QualificationStopManager(c.live.executor,c.proposal)
    assert c.manager.recover()['status']=='READBACK_ACCEPTED'
    c.venue.rest_down=True
    assert QualificationStopManager(c.live.executor,c.proposal).recover()['status']=='UNKNOWN'
    assert len(c.venue.calls)==count


def test_restart_pending_before_dispatch_no_automatic_retry(stop):
    c=stop
    c.live.journal.control(c.manager.key,dict(intent_key=c.stop_key,working_source_hash=c.proposal.source_hash,
        configuration_hash=c.proposal.identity,plan=asdict(c.manager.prepare())))
    assert c.manager.recover()['status']=='UNKNOWN'
    with pytest.raises(ExchangeError,match='READ_ONLY_RECOVERY'):
        c.manager.submit(c.stop_key)
    assert len(c.venue.calls)==1


def test_restart_source_binding_damage_blocks_readiness(stop):
    c=stop;submit_stop(c)
    saved=c.live.journal.control(c.manager.key);saved['working_source_hash']='changed'
    c.live.journal.control(c.manager.key,saved)
    assert c.manager.recover()['status']=='UNKNOWN'


def test_open_stop_blocks_competing_exit_until_verified_cancellation(stop):
    c=stop;submit_stop(c)
    with pytest.raises(ExchangeError,match='OPEN_ORDER_RECONCILIATION'):
        require_settled_exit_orders(c.live.executor)
    c.manager.cancel();require_settled_exit_orders(c.live.executor)


def test_generic_terminal_stop_row_without_lifecycle_proof_cannot_enable_exit(stop):
    c=stop;submit_stop(c);c.live.fixture.orders=[]
    c.live.journal.update(c.stop_key,'CANCELLED',NOW)
    with pytest.raises(ExchangeError,match='STOP_LIFECYCLE_UNRESOLVED'):
        require_settled_exit_orders(c.live.executor)


def test_generic_partial_status_unknown_does_not_cancel_remainder(emergency):
    c=emergency;c.venue.partial_entry=D('.5');c.live.executor.entries_paused=False
    req=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc',
        strategy_id='TESTNET_CERTIFICATION_ENTRY',client_order_id=c.sequence.prefix+'entry')
    result=c.live.executor.submit(req,permission=emergency_permission(req,c.p,NOW))
    c.venue.statuses[result.cloid]['order']['status']='triggered'
    recovered=c.live.executor.recover_uncertain(result.intent_key)
    assert recovered.state==OrderState.UNKNOWN and not recovered.remainder_cancelled
    with pytest.raises(ExchangeError,match='UNRESOLVED_ORDER'):
        require_settled_exit_orders(c.live.executor)
    assert len(c.venue.calls)==1


def test_btc_partial_exit_and_one_lot_residual_still_close_with_no_upsizing(emergency):
    c=emergency;c.venue.partial_exit=D('.6');r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r
    assert [D(a['orders'][0]['s']) for a in c.venue.calls]==[D('.0002'),D('.0002'),D('.0001')]
    assert all(a['orders'][0]['r'] for a in c.venue.calls[1:])
    assert not r['protection_accepted'] and r['final_flat']


def test_definite_stop_rejection_allows_existing_bounded_exit_after_account_readback(stop):
    c=stop;c.venue.fail='protection_rejected'
    result=c.manager.submit(c.stop_key)
    assert result['status']=='REJECTED' and result['placement_rejection_observed']
    require_settled_exit_orders(c.live.executor)
    c.sequence.close()
    assert not c.live.account.get_positions() and len(c.venue.calls)==3


@pytest.mark.parametrize('mode',['ack_only','rejected'])
def test_cancellation_success_or_rejection_does_not_prove_removed_stop(stop,monkeypatch,mode):
    c=stop;submit_stop(c);original=c.venue.transmit
    def transmit(payload):
        if payload['action']['type']=='cancel':
            return response('success' if mode=='ack_only' else {'error':'Order was never placed, already canceled, or filled.'},'cancel')
        return original(payload)
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    result=c.manager.cancel()
    assert not result['cancel_confirmed'] and result['operator_action_required']
    with pytest.raises(ExchangeError,match='OPEN_ORDER_RECONCILIATION'):
        require_settled_exit_orders(c.live.executor)


def test_resolved_cancellation_can_be_recovered_without_new_signature(stop):
    c=stop;submit_stop(c);c.venue.cancel_uncertain=True
    assert c.manager.cancel()['status']=='UNKNOWN'
    count=len(c.venue.calls)
    intent=c.live.journal.intent(c.stop_key)
    c.venue.statuses[intent['cloid']]['order']['status']='canceled'
    c.live.fixture.orders=[]
    result=c.manager.recover()
    assert result['status']=='CANCELLED',result
    require_settled_exit_orders(c.live.executor)
    assert len(c.venue.calls)==count


def test_old_settled_proof_is_cleared_on_disconnect(stop):
    c=stop;submit_stop(c);c.manager.cancel()
    assert c.live.journal.control('qualification_stop_settled:'+c.stop_key)
    c.manager.on_disconnect()
    assert not c.live.journal.control('qualification_stop_settled:'+c.stop_key)
    with pytest.raises(ExchangeError,match='STOP_LIFECYCLE_UNRESOLVED'):
        require_settled_exit_orders(c.live.executor)
    assert c.manager.recover()['status']=='CANCELLED'


@pytest.mark.parametrize('mode',['stale','fractional_lot','opposite','oversized','flat'])
def test_invalid_actual_btc_stop_position_never_rounds_or_enlarges(emergency,mode):
    c=emergency
    quantities={'stale':'.0002','fractional_lot':'.00015','opposite':'-.0002','oversized':'.0003','flat':'0'}
    c.live.fixture.position(quantities[mode],c.p.entry_limit)
    held=c.live.account.get_position(c.p.symbol)
    manager=QualificationStopManager(c.live.executor,c.p)
    with pytest.raises(ExchangeError):
        if mode=='flat':manager.prepare()
        else:manager._plan(c.p.symbol,held,None,NOW-5001 if mode=='stale' else NOW)
    assert not c.venue.calls


def test_reconciliation_deadline_does_not_label_slow_snapshots_fresh(stop,monkeypatch):
    c=stop;submit_stop(c);original=c.live.account.get_fills
    def fills(**kwargs):
        values=original(**kwargs);c.live.fixture.now+=5001
        return values
    monkeypatch.setattr(c.live.account,'get_fills',fills)
    result=c.manager.reconcile()
    assert result['status']=='UNKNOWN' and not result['coverage_observed']


def test_unexpected_untracked_order_blocks_stop_coverage_and_cancellation(stop):
    c=stop;submit_stop(c)
    extra=deepcopy(c.live.fixture.orders[0]);extra['oid']=999
    c.live.fixture.orders.append(extra)
    assert c.manager.reconcile()['status']=='UNKNOWN'
    with pytest.raises(ExchangeError,match='IDENTITY_UNCERTAIN'):
        c.manager.cancel()
    assert len(c.venue.calls)==2


@pytest.fixture
def btc_stop(emergency):
    """Actual BTC lot/asset SDK wire with explicitly synthetic stop authority.

    A production builder still rejects one-lot stop uncertainty. This fixture
    supplies no real wallet, HTTP or certification and changes no production policy.
    """
    c=emergency;live=c.live
    live.fixture.book['levels'][1][0]['sz']='.01'
    values={f.name:getattr(c.p,f.name) for f in fields(CertificationProposal)}
    values.update(mode='TESTNET_CERTIFICATION',max_notional='25',session_loss_budget='10',
        entry_slippage_bps='5',entry_limit='83481',stop_trigger='83000',stop_limit='82800',
        exit_bound='82800',max_signed_actions=6)
    p=CertificationProposal(**values).require()
    approval=CertificationApproval(p.identity,'OFFLINE_EPHEMERAL_ONLY',NOW,NOW+300000,True,True,True)
    auth=CertificationAuthorization(p,approval,live.journal,clock_ms=lambda:live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    c.venue.auth=auth
    e=HyperliquidExecution(live.client,transport=live.transport,account=live.account,journal=live.journal,
        context_provider=live.provider,validator=live.validator,recovery=live.executor.recovery,
        clock_health=live.clock,rate_limits=live.rate)
    live.executor=e;e.recovery.recover();e.entries_paused=False
    prefix='certification:'+p.identity+':'
    req=OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif='Ioc',
        strategy_id='TESTNET_CERTIFICATION_ENTRY',client_order_id=prefix+'entry')
    e.submit(req,permission=cert_permission(req,p,NOW))
    return SimpleNamespace(live=live,proposal=p,venue=c.venue,auth=auth,
        manager=QualificationStopManager(e,p),stop_key=prefix+'protection',prefix=prefix)


def test_btc_two_lot_native_sdk_stop_acceptance_is_only_offline_readback(btc_stop):
    c=btc_stop;result=submit_stop(c)
    wire=c.venue.calls[-1]['orders'][0]
    assert wire['a']==2670000 and D(wire['s'])==D('.0002') and wire['r']
    assert not result['protection_verified'] and not result['flat_observed']


def test_btc_stop_partial_execution_one_lot_residual_exact_ioc_then_flat(btc_stop):
    c=btc_stop;submit_stop(c);trigger(c,quantity='.0001',child_state='canceled')
    result=c.manager.reconcile()
    assert result['status']=='PARTIALLY_FILLED' and result['remaining_position_quantity']=='0.0001',result
    require_settled_exit_orders(c.live.executor)
    c.live.executor.recovery.recover()
    held=c.live.account.get_position(c.proposal.symbol)
    with pytest.raises(ExchangeError,match='SMALL_STOP_VENUE_SUPPORT_UNVERIFIED'):
        c.manager._plan(c.proposal.symbol,held,None,NOW)
    req=OrderRequest(c.proposal.symbol,'SELL',held.quantity,'83233',reduce_only=True,tif='Ioc',
        strategy_id='TESTNET_CERTIFICATION_EXIT',client_order_id=c.prefix+'exit:0')
    result=c.live.executor.close_full_position(req,permission=cert_permission(req,c.proposal,NOW,
        reason='CERTIFICATION_REDUCE_ONLY_EXIT'))
    assert result.state==OrderState.FILLED and not c.live.account.get_positions()
    assert D(c.venue.calls[-1]['orders'][0]['s'])==D('.0001')
