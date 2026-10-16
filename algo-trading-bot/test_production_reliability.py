"""Failure injection for shared reliability gates and actual-position protection.

All identities and exchange state are synthetic. The signed fixture has no HTTP
sink; real sessions retain PAPER/false. No strategy formula is replaced here.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from exchange.base_exchange import ExchangeError
from exchange.execution_safety import ClockHealthMonitor,NonceManager,HyperliquidRateLimitManager
from exchange.reliability_policy import HyperliquidRatePolicy,RequestPriority as P,RateState,ClockState
from exchange.position_protection import ExchangeProtectionManager,ProtectionPolicy,ProtectionStatus
from exchange.order_lifecycle import OrderRequest
from exchange.stream_first import StreamFirstMarketData
from test_live_exchange_execution import live,permission,response
from test_exchange_migration import NOW,TEAM

POLICY=ProtectionPolicy(True,'SYNTHETIC_TEST_POLICY_ONLY',D(2),D('.01'))


class ProtectionVenue:
    def __init__(self,live,monkeypatch,*,stop_market=True):
        self.live=live
        self.stop_market=stop_market
        self.statuses={}
        self.oid=100
        self.fail=None
        self.wrong_qty=False
        self.reject_cancel=False
        self.internet_lost=False
        self.partial_entry_fraction=D('.63')
        self.close_fraction=D(1)
        live.client.transport=self.read
        monkeypatch.setattr(live.transport,'transmit',self.transmit)

    def read(self,payload):
        if self.internet_lost:
            raise TimeoutError('SYNTHETIC_INTERNET_LOST')
        if payload['type']=='frontendOpenOrders':
            self.live.fixture.calls.append(deepcopy(payload))
            return deepcopy(self.live.fixture.orders)
        if payload['type']=='orderStatus':
            self.live.fixture.calls.append(deepcopy(payload))
            return deepcopy(self.statuses.get(str(payload['oid']),{'status':'unknownOid'}))
        return self.live.fixture(payload)

    def _cancel(self,oid):
        orders=self.live.fixture.orders
        for order in list(orders):
            if str(order['oid'])==str(oid):
                status=self.statuses[str(oid)]
                status['order']['status']='canceled'
                orders.remove(order)

    def transmit(self,payload):
        self.live.transport.check(payload['action'])
        self.live.transport.signed_payloads.append(deepcopy(payload))
        self.live.fixture.budget['nRequestsUsed']+=1
        if self.fail=='reject':
            return response({'error':'Insufficient margin'})
        if self.fail=='nonce':
            return response({'error':'Nonce already used'})
        if self.fail=='timeout_before':
            raise TimeoutError('OFFLINE_ONLY')
        action=payload['action']
        if action['type']=='cancel':
            if self.reject_cancel:
                return response({'error':'Order was never placed'},'cancel')
            self._cancel(action['cancels'][0]['o'])
            result=response('success','cancel')
        else:
            if action['type']=='batchModify':
                change=action['modifies'][0]
                self._cancel(change['oid'])
                wire=change['order']
            else:
                wire=action['orders'][0]
            if 'trigger' not in wire['t']:
                self.oid+=1
                requested=D(wire['s'])
                held=self.live.account.get_position('par:BTC')
                if wire['r']:
                    assert held is not None
                    qty=(requested*self.close_fraction).quantize(D('.0001'))
                    remaining=held.quantity-qty if held.quantity>0 else held.quantity+qty
                    entry=held.entry_price
                    closed=qty*(D(wire['p'])-entry)*(1 if held.quantity>0 else -1)
                else:
                    assert held is None
                    qty=(requested*self.partial_entry_fraction).quantize(D('.0001'))
                    remaining=qty if wire['b'] else -qty
                    entry=D(wire['p'])
                    closed=D(0)
                self.live.fixture.position(remaining,entry=str(entry))
                self.live.fixture.fill(qty,side='B' if wire['b'] else 'A',price=wire['p'],
                    oid=self.oid,tid=self.oid,closed=str(closed))
                detail=dict(coin='par:BTC',side='B' if wire['b'] else 'A',oid=self.oid,cloid=wire['c'],
                    sz='0',origSz=str(requested),isTrigger=False,reduceOnly=wire['r'],limitPx=wire['p'])
                status=dict(status='order',order=dict(order=detail,status='filled',statusTimestamp=NOW))
                self.statuses[str(self.oid)]=status
                self.statuses[wire['c']]=status
                if self.fail=='entry_internet_after_fill':
                    self.internet_lost=True
                    raise TimeoutError('SYNTHETIC_INTERNET_LOST')
                return response({'filled':{'oid':self.oid,'totalSz':str(qty),'avgPx':wire['p']}})
            assert wire['r'] is True
            assert wire['t']['trigger']['tpsl']=='sl'
            assert wire['t']['trigger']['isMarket'] is self.stop_market
            self.oid+=1
            order=dict(coin='par:BTC',side='B' if wire['b'] else 'A',sz=wire['s'],limitPx=wire['p'],
                oid=self.oid,cloid=wire['c'],isTrigger=True,reduceOnly=True,
                triggerPx=wire['t']['trigger']['triggerPx'],orderType='Stop Market' if self.stop_market else 'Stop Limit',timestamp=NOW)
            if self.wrong_qty:
                order['sz']=str(D(order['sz'])/2)
            self.live.fixture.orders.append(order)
            status=dict(status='order',order=dict(order=deepcopy(order),status='open',statusTimestamp=NOW))
            self.statuses[str(self.oid)]=status
            self.statuses[wire['c']]=status
            result=response({'resting':{'oid':self.oid}})
        if self.fail=='timeout_after':
            raise TimeoutError('OFFLINE_ONLY')
        return result

    def fill_protection(self,quantity,*,partial=False):
        order=self.live.fixture.orders[0]
        qty=D(quantity)
        held=self.live.account.get_position('par:BTC').quantity
        new=held-qty if held>0 else held+qty
        self.live.fixture.position(new)
        self.live.fixture.fill(qty,side=order['side'],price=order['triggerPx'],oid=order['oid'])
        if partial:
            order['sz']=str(D(order['sz'])-qty)
            self.statuses[str(order['oid'])]['order']['order']['sz']=order['sz']
        else:
            self.statuses[str(order['oid'])]['order']['status']='filled'
            self.live.fixture.orders=[]


@pytest.fixture
def protected(live,monkeypatch):
    venue=ProtectionVenue(live,monkeypatch)
    managed=SimpleNamespace(_open_position=None)
    manager=ExchangeProtectionManager(live.executor,policy=POLICY,managers={'par:BTC':managed})
    def position(quantity,*,stop=None,atr='2'):
        live.fixture.position(quantity)
        managed._open_position=None if not D(quantity) else dict(side='BUY' if D(quantity)>0 else 'SELL',
            quantity=abs(D(quantity)),stop_loss_price=stop or ('95' if D(quantity)>0 else '105'),atr_14=atr)
    position('.2')
    return SimpleNamespace(live=live,venue=venue,manager=manager,managed=managed,position=position)


def state(p):
    return p.manager.report()['positions']['par:BTC']['status']


@pytest.mark.parametrize('quantity,side,trigger',[('.2','A','91'),('-.2','B','109')])
def test_long_and_short_official_reduce_only_trigger(protected,quantity,side,trigger):
    p=protected
    p.position(quantity)
    before=deepcopy(p.managed._open_position)
    p.manager.ensure_all()
    assert state(p)=='ACTIVE',p.manager.report()
    assert p.managed._open_position==before
    order=p.live.fixture.orders[0]
    assert order['side']==side and D(order['sz'])==abs(D(quantity)) and D(order['triggerPx'])==D(trigger)
    assert order['reduceOnly'] is True
    payload=p.live.transport.signed_payloads[0]
    from hyperliquid.utils.signing import recover_agent_or_user_from_l1_action
    assert recover_agent_or_user_from_l1_action(payload['action'],payload['signature'],None,
        payload['nonce'],None,False).lower()==p.live.signer.address.lower()


def test_flat_never_submits_protection(protected):
    p=protected
    p.position('0')
    p.manager.ensure_all()
    assert state(p)=='NOT_REQUIRED'
    assert not p.live.transport.signed_payloads


def test_policy_disabled_nonzero_position_pauses_entries(protected):
    p=protected
    p.manager.policy=ProtectionPolicy()
    p.manager.ensure_all()
    assert state(p)=='ERROR' and p.live.executor.entries_paused
    assert not p.live.transport.signed_payloads


@pytest.mark.parametrize('policy',[
    ProtectionPolicy(True,None,D(2),D('.01')),
    ProtectionPolicy(True,'approved',None,D('.01')),
    ProtectionPolicy(True,'approved',D(0),D('.01')),
    ProtectionPolicy(True,'approved',D(2),None),
    ProtectionPolicy(True,'approved',D(2),D(0)),
    ProtectionPolicy(True,'approved',D(2),D('.9')),
])
def test_no_unapproved_or_arbitrary_protection_distance(protected,policy):
    p=protected
    p.manager.policy=policy
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads


def test_protection_correct_existing_is_idempotent(protected):
    p=protected
    p.manager.ensure_all()
    first=p.live.transport.signed_payloads[0]
    for _ in range(3):
        p.manager.ensure_all()
    assert state(p)=='ACTIVE' and len(p.live.transport.signed_payloads)==1
    assert p.live.transport.signed_payloads[0]==first


@pytest.mark.parametrize('quantity',['.35','.15'])
def test_incremental_entry_and_partial_exit_resize_atomic(protected,quantity):
    p=protected
    p.manager.ensure_all()
    old=p.live.fixture.orders[0]['oid']
    p.position(quantity)
    p.manager.ensure_all()
    assert state(p)=='ACTIVE',p.manager.report()
    assert len(p.live.fixture.orders)==1 and D(p.live.fixture.orders[0]['sz'])==D(quantity)
    action=p.live.transport.signed_payloads[-1]['action']
    assert action['type']=='batchModify' and action['modifies'][0]['oid']==old
    assert action['modifies'][0]['order']['r'] is True


def test_flat_cancels_obsolete_and_verifies_exchange(protected):
    p=protected
    p.manager.ensure_all()
    p.position('0')
    p.manager.ensure_all()
    assert state(p)=='NOT_REQUIRED',p.manager.report()
    assert not p.live.fixture.orders and p.manager.flat_clear('par:BTC')
    assert [x['action']['type'] for x in p.live.transport.signed_payloads]==['order','cancel']


def test_direction_flip_requires_old_cleared_before_recreate(protected):
    p=protected
    p.manager.ensure_all()
    p.position('0')
    assert p.manager.flat_clear('par:BTC')
    p.position('-.2')
    p.manager.ensure_all()
    assert state(p)=='ACTIVE' and p.live.fixture.orders[0]['side']=='B'
    assert [x['action']['type'] for x in p.live.transport.signed_payloads]==['order','cancel','order']


def test_wrong_direction_existing_cancel_then_verified_new(protected):
    p=protected
    p.manager.ensure_all()
    p.position('-.2')
    p.manager.ensure_all()
    assert state(p)=='ACTIVE',p.manager.report()
    assert [x['action']['type'] for x in p.live.transport.signed_payloads]==['order','cancel','order']


def test_wrong_trigger_resize_preserves_normal_stop(protected):
    p=protected
    p.manager.ensure_all()
    p.live.fixture.orders[0]['triggerPx']='92'
    p.venue.statuses[str(p.live.fixture.orders[0]['oid'])]['order']['order']['triggerPx']='92'
    p.manager.ensure_all()
    assert state(p)=='ACTIVE' and p.managed._open_position['stop_loss_price']=='95'
    assert D(p.live.fixture.orders[0]['triggerPx'])==91


def test_read_only_detects_partial_without_action(protected):
    p=protected
    p.manager.ensure_all()
    p.position('.3')
    p.manager.ensure_all(allow_actions=False)
    assert state(p)=='PARTIAL' and p.live.executor.entries_paused
    assert len(p.live.transport.signed_payloads)==1


def test_missing_read_only_pauses_entries(protected):
    p=protected
    p.manager.ensure_all(allow_actions=False)
    assert state(p)=='MISSING' and p.live.executor.entries_paused and not p.live.transport.signed_payloads


def test_subminimum_remainder_pauses_without_rounding_up(protected):
    p=protected
    p.manager.ensure_all()
    p.position('.1')
    p.manager.ensure_all()
    assert state(p)=='ERROR' and p.live.executor.entries_paused
    assert len(p.live.transport.signed_payloads)==1
    assert any('MIN_ORDER_NOTIONAL' in r[0] for r in p.live.journal.db.execute('SELECT data FROM events'))


def test_restart_discovers_trigger_without_lifecycle_record(protected):
    p=protected
    p.manager.ensure_all()
    with p.live.journal.transaction():
        p.live.journal.db.execute('DELETE FROM protection_intents')
    restarted=ExchangeProtectionManager(p.live.executor,policy=POLICY,managers=p.manager.managers)
    restarted.ensure_all()
    assert restarted.states['par:BTC']['status']=='ACTIVE'
    assert len(p.live.transport.signed_payloads)==1
    p.manager=restarted
    p.position('.3')
    restarted.ensure_all()
    assert state(p)=='ACTIVE' and len(p.live.transport.signed_payloads)==2


def test_rejected_protection_leaves_management_and_pauses(protected):
    p=protected
    p.venue.fail='reject'
    original=deepcopy(p.managed._open_position)
    p.manager.ensure_all()
    assert state(p)=='ERROR' and p.live.executor.entries_paused
    assert p.managed._open_position==original and not p.live.fixture.orders


@pytest.mark.parametrize('failure',['timeout_before','timeout_after'])
def test_uncertain_protection_never_duplicates_after_restart(protected,failure):
    p=protected
    p.venue.fail=failure
    p.manager.ensure_all()
    assert state(p)=='ERROR' and len(p.live.transport.signed_payloads)==1
    p.venue.fail=None
    restarted=ExchangeProtectionManager(p.live.executor,policy=POLICY,managers=p.manager.managers)
    restarted.ensure_all()
    assert len(p.live.transport.signed_payloads)==1
    assert restarted.states['par:BTC']['status']==('ACTIVE' if failure=='timeout_after' else 'ERROR')


def test_post_submission_quantity_mismatch_is_not_active(protected):
    p=protected
    p.venue.wrong_qty=True
    p.manager.ensure_all()
    assert state(p)=='ERROR' and p.live.executor.entries_paused


def test_partial_trigger_fill_uses_remaining_actual_quantity(protected):
    p=protected
    p.manager.ensure_all()
    p.venue.fill_protection('.1',partial=True)
    p.managed._open_position['quantity']=D('.1')
    p.manager.ensure_all()
    assert state(p)=='ACTIVE' and D(p.live.fixture.orders[0]['sz'])==D('.1')
    assert len(p.live.transport.signed_payloads)==1


def test_full_protection_fill_flat_with_exchange_fill_evidence(protected):
    p=protected
    p.manager.ensure_all()
    p.venue.fill_protection('.2')
    p.managed._open_position=None
    p.manager.ensure_all()
    assert state(p)=='NOT_REQUIRED' and len(p.live.transport.signed_payloads)==1


def test_triggered_uncertain_child_blocks_replacement(protected):
    p=protected
    p.manager.ensure_all()
    row=p.live.journal.intents()[0]
    p.venue.statuses[row['cloid']]['order']['status']='triggered'
    p.live.fixture.orders=[]
    p.manager.ensure_all()
    assert state(p)=='ERROR' and len(p.live.transport.signed_payloads)==1


def test_duplicate_trigger_orders_fail_closed(protected):
    p=protected
    p.manager.ensure_all()
    clone=deepcopy(p.live.fixture.orders[0])
    clone['oid']=999
    p.live.fixture.orders.append(clone)
    status=deepcopy(p.venue.statuses[clone['cloid']])
    status['order']['order']['oid']=999
    p.venue.statuses['999']=status
    p.manager.ensure_all()
    assert state(p)=='ERROR' and len(p.live.transport.signed_payloads)==1


def test_unrecognized_manual_trigger_is_not_adopted_or_cancelled(protected):
    p=protected
    p.manager.ensure_all()
    order=p.live.fixture.orders[0]
    p.venue.statuses[str(order['oid'])]['order']['order']['cloid']='0x'+'f'*32
    p.manager.ensure_all()
    assert state(p)=='ERROR' and len(p.live.transport.signed_payloads)==1


def test_missing_management_does_not_invent_geometry(protected):
    p=protected
    p.managed._open_position=None
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads


def test_obsolete_cancel_failure_blocks_flip(protected):
    p=protected
    p.manager.ensure_all()
    p.position('0')
    p.venue.reject_cancel=True
    assert not p.manager.flat_clear('par:BTC')
    assert state(p)=='ERROR' and len(p.live.fixture.orders)==1


def test_no_protection_outside_liquidation_boundary(protected):
    p=protected
    p.live.fixture.state['assetPositions'][0]['position']['liquidationPx']='92'
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads


def test_stale_market_blocks_protection_signature(protected):
    p=protected
    p.live.fixture.book['time']=NOW-6000
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads


def test_nonce_error_on_protection_persistently_degrades_signing(protected):
    p=protected
    p.venue.fail='nonce'
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.nonces.healthy
    with pytest.raises(ExchangeError,match='DEGRADED'):
        p.live.nonces.next()


def test_exchange_rest_unavailable_incident_preserves_manager(protected,monkeypatch):
    p=protected
    original=deepcopy(p.managed._open_position)
    monkeypatch.setattr(p.live.account,'get_positions',lambda:(_ for _ in ()).throw(TimeoutError()))
    p.manager.ensure_all()
    assert not p.manager.healthy and p.live.executor.entries_paused
    assert p.managed._open_position==original and not p.live.transport.signed_payloads


def test_clock_forward_jump_blocks_signing_with_position(protected):
    p=protected
    p.live.clock.observe(NOW,NOW,NOW)
    p.live.clock.monotonic_ms=lambda:NOW
    p.live.fixture.now+=10000
    p.live.fixture.book['time']=p.live.fixture.now
    p.manager.ensure_all()
    assert not p.live.transport.signed_payloads and p.live.executor.entries_paused


def test_safety_action_survives_exhausted_account_budget(protected):
    p=protected
    p.live.fixture.budget=dict(nRequestsUsed=10000,nRequestsCap=10000)
    p.manager.ensure_all()
    assert state(p)=='ACTIVE',p.manager.report()
    assert not p.live.rate.entries_allowed


def test_protection_remains_manageable_during_stream_disconnect_and_backoff(protected):
    p=protected
    p.live.provider.feed_ready=lambda:False
    p.live.rate.error()
    p.manager.ensure_all()
    assert state(p)=='ACTIVE',p.manager.report()
    assert p.live.transport.signed_payloads[0]['action']['orders'][0]['r'] is True


def rate(live,policy=None):
    manager=HyperliquidRateLimitManager(live.journal,clock_ms=lambda:live.fixture.now,
        policy=policy,jitter=lambda:0,wait=lambda ms:setattr(live.fixture,'now',live.fixture.now+ms),
        signer_address=live.signer.address)
    manager.observe_info('userRateLimit',dict(nRequestsUsed=0,nRequestsCap=10000))
    manager.observe_info('openOrders',[])
    return manager


def test_budget_states_and_local_lagging_exchange_snapshot(live):
    r=rate(live)
    assert r.state==RateState.HEALTHY
    r.reserve_action()
    r.observe_info('userRateLimit',dict(nRequestsUsed=0,nRequestsCap=10000))
    assert r.remaining_budget==9999
    r.observe_info('userRateLimit',dict(nRequestsUsed=1,nRequestsCap=10000))
    assert r.remaining_budget==9999
    r.observe_info('userRateLimit',dict(nRequestsUsed=9995,nRequestsCap=10000))
    assert r.state==RateState.CAUTION and not r.entries_allowed
    r.observe_info('userRateLimit',dict(nRequestsUsed=10000,nRequestsCap=10000))
    assert r.state==RateState.EXHAUSTED


def test_unknown_and_stale_budget_restrict_optional(live):
    r=HyperliquidRateLimitManager(live.journal,clock_ms=lambda:live.fixture.now)
    assert r.state==RateState.UNKNOWN
    with pytest.raises(ExchangeError,match='OPTIONAL'):
        r.reserve_info('candleSnapshot',priority=P.OPTIONAL)
    r.reserve_info('clearinghouseState',priority=P.SAFETY)
    r.observe_info('userRateLimit',dict(nRequestsUsed=0,nRequestsCap=10000))
    live.fixture.now+=60001
    assert r.state==RateState.UNKNOWN


def test_rest_reserve_blocks_optional_before_safety(live):
    policy=replace(HyperliquidRatePolicy(),ip_weight_per_minute=100,ip_safety_reserve=20)
    r=rate(live,policy)
    for _ in range(4):
        r.reserve_info('meta')
    assert r.state==RateState.CAUTION
    with pytest.raises(ExchangeError,match='RATE_LIMITED'):
        r.reserve_info('meta')
    r.reserve_info('orderStatus',priority=P.SAFETY)
    assert r.report()['ip_weight']==82


def test_daily_reserve_durable_by_date_process_signer_session(live):
    policy=replace(HyperliquidRatePolicy(),daily_actions=10,daily_safety_reserve=2)
    r=rate(live,policy)
    for _ in range(9):
        r.reserve_action(priority=P.SAFETY,kind='cancel')
    assert not r.entries_allowed
    rows=live.journal.db.execute('SELECT * FROM api_actions').fetchall()
    assert all(x['process']==os.getpid() and x['signer']==live.signer.address and
               x['session']==live.journal.session_id and x['kind']=='cancel' for x in rows)
    restarted=rate(live,policy)
    assert restarted.daily_used()==9 and restarted.remaining_budget==9991
    restarted.reserve_action(priority=P.SAFETY)
    with pytest.raises(ExchangeError,match='DAILY_ACTION_LIMIT'):
        restarted.reserve_action(priority=P.SAFETY)
    live.fixture.now+=86400000
    assert restarted.daily_used()==0


def test_exhausted_single_safety_action_interval_survives_restart(live):
    r=rate(live)
    r.observe_info('userRateLimit',dict(nRequestsUsed=10000,nRequestsCap=10000))
    r.reserve_action(priority=P.SAFETY,kind='close')
    restarted=HyperliquidRateLimitManager(live.journal,clock_ms=lambda:live.fixture.now)
    restarted.observe_info('userRateLimit',dict(nRequestsUsed=10000,nRequestsCap=10000))
    restarted.observe_info('openOrders',[])
    with pytest.raises(ExchangeError,match='RATE_LIMITED'):
        restarted.reserve_action(priority=P.SAFETY)
    live.fixture.now+=10000
    restarted.reserve_action(priority=P.SAFETY)


@pytest.mark.parametrize('query,count,weight',[('userFills',40,22),('userFunding',100,25),('candleSnapshot',180,23)])
def test_historical_response_weight_counts_actual_results(live,query,count,weight):
    r=rate(live)
    r.reserve_info(query,priority=P.SAFETY)
    r.observe_info(query,[{}]*count)
    assert r.report()['ip_weight']==weight


def test_429_read_jitter_backoff_bounded_and_retries_only_reads(live):
    r=rate(live)
    attempts=[]
    def operation():
        attempts.append(live.fixture.now)
        if len(attempts)<3:
            error=ExchangeError('INFO_HTTP_429')
            error.status_code=429
            error.retry_after_ms=1500
            raise error
        return []
    assert r.read('openOrders',operation,priority=P.SAFETY)==[]
    assert len(attempts)==3 and attempts[1]-attempts[0]==1500 and attempts[2]-attempts[1]==1600
    assert r.recent_errors==0
    assert live.journal.db.execute("SELECT COUNT(*) FROM events WHERE kind='REQUEST_BACKOFF'").fetchone()[0]==2


def test_non_transient_read_error_never_retries(live):
    r=rate(live)
    attempts=[]
    def operation():
        attempts.append(1)
        raise ExchangeError('INVALID_PAR_METADATA')
    with pytest.raises(ExchangeError,match='INVALID_PAR_METADATA'):
        r.read('meta',operation)
    assert attempts==[1]


def test_transient_reads_stop_at_retry_budget(live):
    r=rate(live)
    calls=[]
    def operation():
        calls.append(1)
        raise TimeoutError()
    with pytest.raises(ExchangeError,match='RETRY_BUDGET'):
        r.read('openOrders',operation,priority=P.SAFETY)
    assert len(calls)==3


def test_optional_polling_slows_in_caution(live):
    r=rate(live)
    r.observe_info('userRateLimit',dict(nRequestsUsed=9995,nRequestsCap=10000))
    r.reserve_info('recentTrades',priority=P.OPTIONAL)
    live.fixture.now+=5000
    with pytest.raises(ExchangeError,match='OPTIONAL'):
        r.reserve_info('recentTrades',priority=P.OPTIONAL)
    live.fixture.now+=15000
    r.reserve_info('recentTrades',priority=P.OPTIONAL)


def test_ws_duplicate_reconnect_cleanup_and_aggregate_budget(live):
    policy=replace(HyperliquidRatePolicy(),max_ws_connections=2,max_ws_subscriptions=3,
                   max_ws_messages_per_minute=5,ws_reconnects_per_minute=3)
    r=rate(live,policy)
    r.ws_open('market')
    assert r.ws_send('market',{'type':'l2Book','coin':'par:BTC'})
    assert not r.ws_send('market',{'type':'l2Book','coin':'par:BTC'})
    r.ws_open('account')
    with pytest.raises(ExchangeError,match='CONNECTION_LIMIT'):
        r.ws_open('third')
    r.ws_send('account',{'type':'userFills','user':TEAM})
    r.ws_send('account',{'type':'orderUpdates','user':TEAM})
    with pytest.raises(ExchangeError,match='SUBSCRIPTION_LIMIT'):
        r.ws_send('market',{'type':'candle','coin':'par:BTC'})
    r.ws_send('market',heartbeat=True)
    r.ws_send('account',heartbeat=True)
    assert r.report()['websocket']['heartbeats']==2
    with pytest.raises(ExchangeError,match='MESSAGE_LIMIT'):
        r.ws_send('account',heartbeat=True)
    r.ws_close('account')
    assert r.report()['websocket']['subscriptions']==1
    r.ws_close('market')
    r.ws_open('market')
    r.ws_close('market')
    with pytest.raises(ExchangeError,match='RECONNECT_THROTTLED'):
        r.ws_open('market')


@pytest.mark.parametrize('jump',[-3000,3000,60000])
def test_clock_jump_latches_until_two_fresh_stable_references(jump):
    wall=[NOW]
    mono=[NOW]
    c=ClockHealthMonitor(clock_ms=lambda:wall[0],monotonic_ms=lambda:mono[0])
    assert c.observe(NOW,NOW,NOW)
    wall[0]+=jump
    assert c.state==ClockState.UNSAFE
    assert not c.observe(wall[0],wall[0],wall[0])
    wall[0]+=1
    mono[0]+=1
    assert c.observe(wall[0],wall[0],wall[0])
    assert c.state==ClockState.HEALTHY


def test_clock_stale_warning_never_silently_recovers():
    t=[NOW]
    c=ClockHealthMonitor(clock_ms=lambda:t[0],monotonic_ms=lambda:t[0])
    assert c.observe(t[0],t[0],t[0])
    t[0]+=30001
    assert c.state==ClockState.WARNING
    assert not c.healthy
    assert not c.observe(t[0],t[0],t[0])
    assert not c.observe(t[0],t[0],t[0])  # replayed reference is not confirmation
    t[0]+=1
    assert c.observe(t[0],t[0],t[0])


def test_nonce_backward_clock_durable_and_reviewed_recovery(live):
    first=live.nonces.next()
    live.fixture.now-=1000
    assert live.nonces.next()==first+1
    live.nonces.degrade()
    path=live.nonces.path
    live.nonces.close()
    live.nonces=NonceManager(path,live.signer.address,clock_ms=lambda:live.fixture.now)
    assert not live.nonces.healthy
    with pytest.raises(ExchangeError,match='DEGRADED'):
        live.nonces.next()
    live.fixture.now=NOW+2
    clock=ClockHealthMonitor(clock_ms=lambda:live.fixture.now,monotonic_ms=lambda:live.fixture.now)
    assert clock.observe(live.fixture.now,live.fixture.now,live.fixture.now)
    with pytest.raises(ExchangeError,match='MANUAL'):
        live.nonces.recover(clock)
    live.nonces.recover(clock,manually_verified=True)
    assert live.nonces.next()>first


def test_second_process_same_api_wallet_rejected_without_killing(live):
    code="""import sys
from exchange.execution_safety import NonceManager
from exchange.base_exchange import ExchangeError
try:
    NonceManager(sys.argv[1],sys.argv[2])
except ExchangeError as exc:
    print(str(exc))
    sys.exit(0)
sys.exit(2)
"""
    result=subprocess.run([sys.executable,'-c',code,str(live.nonces.path),live.signer.address],
        cwd=Path(__file__).parent,capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and 'ALREADY_LEASED' in result.stdout
    assert live.nonces.healthy and live.nonces.owner['pid']==os.getpid()
    assert live.signer.address.lower() in json.dumps(live.nonces.owner)


def test_nonce_large_backward_jump_prevents_timestamp_drift(live):
    live.nonces.next()
    live.fixture.now-=6000
    with pytest.raises(ExchangeError,match='DRIFT'):
        live.nonces.next()


def test_stream_first_quote_reuses_verified_data_and_falls_back(live):
    quote=live.market.get_quote('par:BTC')
    calls=len(live.fixture.calls)
    engine=SimpleNamespace(get_quote=lambda _:quote)
    market=StreamFirstMarketData(live.client,engine)
    assert market.get_quote('par:BTC')==quote and len(live.fixture.calls)==calls
    engine.get_quote=lambda _:(_ for _ in ()).throw(ExchangeError('STREAM_NOT_HEALTHY'))
    assert market.get_quote('par:BTC').mid==quote.mid and len(live.fixture.calls)>calls


def test_safety_logs_contain_no_ephemeral_secret_or_signature(protected):
    p=protected
    p.manager.ensure_all()
    logs='\n'.join(r[0] for r in p.live.journal.db.execute('SELECT data FROM events'))
    assert p.live.signer.key.hex() not in logs and '"signature"' not in logs
    assert 'exchange_ts' in logs and 'processed_ts' in logs and 'PROTECTION' in str(
        [r[0] for r in p.live.journal.db.execute('SELECT kind FROM events')])


def test_reliability_circuit_states_global_and_symbol_scope(protected):
    from risk.circuit_breakers import CircuitBreakers,RiskState
    from test_crypto_paper_infrastructure import POLICY as RISK_POLICY
    p=protected
    p.manager.ensure_all()
    breakers=CircuitBreakers(RISK_POLICY)
    breakers.update_reliability(p.live.executor)
    assert breakers.state==RiskState.NORMAL
    breakers.update_symbols({'par:ETH':{'healthy':False,'reasons':['STALE_BOOK']}})
    assert not breakers.entry_reasons('par:BTC') and breakers.entry_reasons('par:ETH')
    p.manager.states['par:BTC']['status']='ERROR'
    breakers.update_reliability(p.live.executor)
    assert breakers.state==RiskState.EMERGENCY and breakers.entry_reasons('par:BTC')


def live_session(live,venue):
    from exchange.live_recovery import LiveAccountRecovery
    from live_execution_session import LiveExecutionSession
    from risk.portfolio_risk import PortfolioRisk
    from test_crypto_paper_infrastructure import POLICY as RISK_POLICY,FEES
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    live.executor.recovery=recovery
    protection=ExchangeProtectionManager(live.executor,policy=POLICY,managers=recovery.managers)
    session=LiveExecutionSession(live.market,SimpleNamespace(),live.executor,PortfolioRisk(RISK_POLICY,FEES))
    session.attach_account_stream(SimpleNamespace(executor=live.executor,healthy=True))
    return session,protection


def test_internet_lost_after_entry_fill_recovers_once_then_protects(live,monkeypatch):
    from test_crypto_paper_infrastructure import signal_scan
    venue=ProtectionVenue(live,monkeypatch)
    session,protection=live_session(live,venue)
    assert session.startup().ready
    venue.fail='entry_internet_after_fill'
    session.consume_scan(signal_scan(NOW))
    assert live.executor.entries_paused and len(live.transport.signed_payloads)==1
    entry=next(r for r in live.journal.intents() if json.loads(r['request'])['strategy_id']!='CATASTROPHIC_STOP')
    assert entry['state']=='UNKNOWN'
    venue.internet_lost=False
    venue.fail=None
    result=live.executor.recover_uncertain(entry['intent_key'])
    assert result.state.value=='PARTIALLY_FILLED'
    assert session.recovery.last_report.ready
    assert protection.states['par:BTC']['status']=='ACTIVE',protection.report()
    actual=live.account.get_position('par:BTC').quantity
    assert actual==session.managers['par:BTC']._open_position['quantity']
    assert D(live.fixture.orders[0]['sz'])==actual
    assert len(live.transport.signed_payloads)==2
    session.consume_scan(signal_scan(NOW))
    assert len(live.transport.signed_payloads)==2  # no duplicate entry


def test_partial_entry_crash_before_protection_restart_exact_quantity(live,monkeypatch):
    from test_crypto_paper_infrastructure import signal_scan
    venue=ProtectionVenue(live,monkeypatch)
    session,protection=live_session(live,venue)
    assert session.startup().ready
    original=protection.ensure_all
    monkeypatch.setattr(protection,'ensure_all',lambda **_:original(allow_actions=False))
    session.consume_scan(signal_scan(NOW))
    actual=live.account.get_position('par:BTC').quantity
    assert actual>0 and len(live.transport.signed_payloads)==1
    geometry=deepcopy(session.managers['par:BTC']._open_position)
    restarted,new_protection=live_session(live,venue)
    assert restarted.startup().ready
    assert restarted.managers['par:BTC']._open_position==geometry
    assert new_protection.states['par:BTC']['status']=='ACTIVE',new_protection.report()
    assert D(live.fixture.orders[0]['sz'])==actual
    assert len(live.transport.signed_payloads)==2


def test_normal_exit_partial_and_full_with_actual_protection_accounting(live,monkeypatch,tmp_path):
    from test_crypto_paper_infrastructure import signal_scan
    from live_session_results import LiveSessionResults
    venue=ProtectionVenue(live,monkeypatch)
    session,protection=live_session(live,venue)
    assert session.startup().ready
    session.consume_scan(signal_scan(NOW))
    assert protection.states['par:BTC']['status']=='ACTIVE'
    before=deepcopy(session.managers['par:BTC']._open_position)
    venue.close_fraction=D('.5')
    session._close('par:BTC','Target Hit')
    actual=live.account.get_position('par:BTC').quantity
    assert actual>0 and D(live.fixture.orders[0]['sz'])==actual
    assert protection.states['par:BTC']['status']=='ACTIVE'
    assert session.managers['par:BTC']._open_position['stop_loss_price']==before['stop_loss_price']
    assert session.managers['par:BTC']._open_position['target_price']==before['target_price']
    venue.close_fraction=D(1)
    session._close('par:BTC','Target Hit')
    assert live.account.get_position('par:BTC') is None and not live.fixture.orders
    assert protection.states['par:BTC']['status']=='NOT_REQUIRED'
    writer=LiveSessionResults(tmp_path/'safety-evidence',session)
    writer.save()
    assert (writer.path/'protection_events.jsonl').read_text()
    report=json.loads((writer.path/'production_safety.json').read_text())
    assert report['position_state']=='FLAT' and report['live_orders_permitted'] is False
    assert report['new_entries']=='PAUSED'
    assert 'New entries: PAUSED' in (writer.path/'production_safety.txt').read_text()
    assert all(live.signer.key.hex() not in p.read_text() for p in writer.path.iterdir())


def test_account_stream_reconnect_verifies_actual_existing_protection(protected):
    from exchange.live_account_stream import LiveAccountStream
    from test_live_exchange_execution import FakeSocket
    p=protected
    p.manager.ensure_all()
    recovery=SimpleNamespace(account=p.live.account,journal=p.live.journal,
        recover=lambda:SimpleNamespace(ready=True),revoke=lambda _:None)
    stream=LiveAccountStream(TEAM,recovery,p.live.executor,clock_ms=lambda:NOW,
                            connector=lambda *a,**k:FakeSocket())
    stream.connect()
    for channel in stream.CHANNELS:
        stream.handle(dict(channel='subscriptionResponse',data=dict(subscription=dict(type=channel,user=TEAM))))
    assert stream.reconcile() and stream.healthy
    stream.disconnect()
    assert p.live.executor.entries_paused
    stream.connect()
    for channel in stream.CHANNELS:
        stream.handle(dict(channel='subscriptionResponse',data=dict(subscription=dict(type=channel,user=TEAM))))
    assert stream.reconcile() and p.manager.states['par:BTC']['status']=='ACTIVE'
    assert len(p.live.transport.signed_payloads)==1
    stream.disconnect()
    assert p.live.rate.report()['websocket']['connections']==0


@pytest.mark.parametrize('run_mode',['PAPER','REPLAY'])
def test_paper_and_replay_cannot_submit_exchange_trigger(protected,run_mode,monkeypatch):
    p=protected
    # REPLAY is a run context; the mandatory runtime lock remains PAPER/false.
    monkeypatch.setenv('EXECUTION_MODE','PAPER')
    monkeypatch.setenv('ALLOW_LIVE_ORDERS','false')
    p.live.executor.transport=None
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads
    assert not p.live.fixture.orders
    from exchange.paper_execution import PaperExecution
    from exchange.replay import ReplayExecution
    executor_type=PaperExecution if run_mode=='PAPER' else ReplayExecution
    local=executor_type(p.live.client.markets,clock_ms=lambda:NOW,fee_rate=D('.001'))
    assert local.execution_mode==run_mode and not local.is_live
    assert not hasattr(local,'submit_protection') and not hasattr(local,'transport')


def test_default_policy_file_disabled_and_values_applied():
    from exchange.reliability_policy import load_reliability_policy
    path=Path(__file__).resolve().parents[1]/'configs/reliability_policy.json'
    rates,clock,protection=load_reliability_policy(path)
    assert rates.ip_safety_reserve==120 and rates.daily_safety_reserve==500
    assert clock==dict(max_skew_ms=2000,max_age_ms=30000)
    assert not protection.enabled
    assert protection.atr_distance_multiple == '1'
    assert protection.execution_slippage_fraction == '0.005'
    assert protection.approval_reference == 'docs/practice_setup_2026-10-07/protection_configuration_approval.md'
    with pytest.raises(ExchangeError):
        protection.require()


def test_public_safety_report_never_assumes_flat_account():
    from exchange.safety_report import production_safety_report,format_safety_report
    report=production_safety_report()
    assert report['position_state']=='UNKNOWN' and not report['live_orders_permitted']
    assert report['api_wallet_ownership']=='NOT_CONFIGURED'
    assert 'Position: UNKNOWN' in format_safety_report(report)


def test_frontend_open_but_status_cancelled_is_never_active(protected):
    p=protected
    p.manager.ensure_all()
    oid=p.live.fixture.orders[0]['oid']
    p.venue.statuses[str(oid)]['order']['status']='canceled'
    p.manager.ensure_all()
    assert state(p)=='ERROR' and len(p.live.transport.signed_payloads)==1


def test_frontend_and_status_quantity_conflict_is_not_active(protected):
    p=protected
    p.manager.ensure_all()
    p.live.fixture.orders[0]['sz']='.3'
    p.manager.ensure_all()
    assert state(p)=='ERROR' and len(p.live.transport.signed_payloads)==1


def test_position_changes_during_verification_block_signature(protected,monkeypatch):
    p=protected
    original=p.live.account.get_position
    def changed(symbol):
        p.live.fixture.position('.3')
        return original(symbol)
    monkeypatch.setattr(p.live.account,'get_position',changed)
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads


def test_ip_reservation_failure_is_durably_not_transmitted_then_safely_recovers(protected):
    p=protected
    # Context reads are an in-memory fixture. Reserve only the action's local
    # IP budget to inject denial just before SUBMITTED/signing.
    p.live.rate.weights=[(NOW,p.live.rate.ip_weight_limit)]
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads
    row=p.live.journal.intents()[0]
    assert row['state']=='REJECTED' and json.loads(row['outcome'])['transmitted'] is False
    p.live.rate.weights=[]
    p.manager.ensure_all()
    assert state(p)=='ACTIVE' and len(p.live.transport.signed_payloads)==1


def test_validation_failure_does_not_reuse_lifecycle_key(protected):
    p=protected
    p.live.fixture.book['time']=NOW-6000
    p.manager.ensure_all()
    assert state(p)=='ERROR'
    p.live.fixture.book['time']=NOW
    p.manager.ensure_all()
    assert state(p)=='ERROR' and not p.live.transport.signed_payloads  # first clock recovery confirmation
    p.live.fixture.now+=1
    p.live.fixture.book['time']=p.live.fixture.now
    p.manager.ensure_all()
    assert state(p)=='ACTIVE' and len(p.manager.records())==3


def test_nonce_process_conflict_logged_without_credentials(live):
    with pytest.raises(ExchangeError,match='ALREADY_LEASED'):
        NonceManager(live.nonces.path,live.signer.address,journal=live.journal)
    row=live.journal.db.execute("SELECT data FROM events WHERE kind='API_WALLET_LOCK_CONFLICT'").fetchone()
    assert row and live.signer.key.hex() not in row[0]


def test_signed_cancel_timeout_requires_durable_read_only_recovery(live):
    # Ordinary cancellation shares the same uncertainty contract as protection.
    live.fixture.orders=[dict(coin='par:BTC',oid=71,side='B',sz='.2',limitPx='99')]
    live.transport.responses=[{'fixture_timeout':True}]
    with pytest.raises(ExchangeError,match='MANAGEMENT_ACTION_UNCERTAIN'):
        live.executor.cancel_order('par:BTC',71)
    row=live.journal.management_actions()[0]
    assert row['state']=='UNKNOWN' and live.executor.entries_paused
    with pytest.raises(ExchangeError,match='RECOVERY_REQUIRED'):
        live.executor.cancel_order('par:BTC',71)
    assert len(live.transport.signed_payloads)==1
    assert live.executor.recover_management_action(row['id'])=='UNKNOWN'
    live.fixture.orders=[]
    live.fixture.status=dict(status='order',order=dict(order=dict(coin='par:BTC',oid=71),status='canceled'))
    assert live.executor.recover_management_action(row['id'])=='CONFIRMED_BY_ACCOUNT'
    assert len(live.transport.signed_payloads)==1


def test_signed_leverage_timeout_verifies_actual_active_asset_without_retry(live):
    live.transport.responses=[{'fixture_timeout':True}]
    with pytest.raises(ExchangeError,match='MANAGEMENT_ACTION_UNCERTAIN'):
        live.executor.set_leverage('par:BTC',1)
    row=live.journal.management_actions()[0]
    assert row['state']=='UNKNOWN'
    assert live.executor.recover_management_action(row['id'])=='CONFIRMED_BY_ACCOUNT'
    assert len(live.transport.signed_payloads)==1


def test_ws_unique_user_budget(live):
    r=rate(live,replace(HyperliquidRatePolicy(),max_ws_unique_users=1))
    r.ws_open('account')
    r.ws_send('account',dict(type='userFills',user=TEAM))
    with pytest.raises(ExchangeError,match='UNIQUE_USER_LIMIT'):
        r.ws_send('account',dict(type='userFills',user='0x'+'2'*40))


def test_trigger_child_partial_fill_reconciles_and_protects_remainder(live,monkeypatch):
    from test_crypto_paper_infrastructure import signal_scan
    venue=ProtectionVenue(live,monkeypatch)
    session,protection=live_session(live,venue)
    assert session.startup().ready
    session.consume_scan(signal_scan(NOW))
    parent=live.fixture.orders[0]
    actual=live.account.get_position('par:BTC').quantity
    partial=(actual/2).quantize(D('.0001'))
    child_oid=800
    live.fixture.fill(partial,side='A',price=parent['triggerPx'],oid=child_oid,tid=child_oid,
                      closed=str(partial*(D(parent['triggerPx'])-D('100.01'))))
    live.fixture.position(actual-partial,entry='100.01')
    live.fixture.orders=[]
    status=venue.statuses[str(parent['oid'])]
    status['order']['status']='triggered'
    status['order']['order']['children']=[dict(oid=child_oid)]
    venue.statuses[str(child_oid)]=dict(status='order',order=dict(status='canceled',order=dict(
        coin='par:BTC',oid=child_oid,side='A',reduceOnly=True)))
    assert session.recovery.recover().ready
    assert session.managers['par:BTC']._open_position['quantity']==actual-partial
    protection.ensure_all()
    assert protection.states['par:BTC']['status']=='ACTIVE',protection.report()
    assert D(live.fixture.orders[0]['sz'])==actual-partial
    assert len(live.transport.signed_payloads)==3
    assert session.recovery.state.report()['realized']['actual_fill_fees']==D('.2')


def test_signer_ownership_cannot_be_bypassed_by_another_tmpdir(live,tmp_path):
    code="""import sys
from exchange.execution_safety import NonceManager
from exchange.base_exchange import ExchangeError
try:
    NonceManager(sys.argv[1],sys.argv[2])
except ExchangeError as exc:
    print(str(exc))
    sys.exit(0)
sys.exit(2)
"""
    result=subprocess.run([sys.executable,'-c',code,str(live.nonces.path),live.signer.address],
        cwd=Path(__file__).parent,env=dict(os.environ,TMPDIR=str(tmp_path)),
        capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and 'ALREADY_LEASED' in result.stdout


def test_cached_protection_cannot_authorize_entry_with_changed_actual_position(protected):
    p=protected
    p.manager.ensure_all()
    assert p.manager.entries_allowed
    p.live.fixture.position('.4')  # position change arrives before its stream notification
    p.live.executor.entries_paused=False
    request=OrderRequest('par:BTC','BUY','.2','100',client_order_id='missed-event-entry')
    with pytest.raises(ExchangeError,match='POSITION_LIMIT'):
        p.live.executor.submit(request,permission=permission(request,candidate='missed-event'))
    assert p.live.executor.entries_paused and len(p.live.transport.signed_payloads)==1


def test_restored_checkpoint_is_not_reported_as_fresh_flat(live):
    from exchange.live_recovery import LiveAccountRecovery
    from exchange.safety_report import production_safety_report
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    assert recovery.recover().ready
    restarted=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    assert restarted.state.initialized and restarted.state.equity is None
    live.executor.recovery=restarted
    report=production_safety_report(live.executor)
    assert report['position_state']=='UNKNOWN' and report['reconciliation']=='REQUIRED'
    assert not report['live_orders_permitted']
