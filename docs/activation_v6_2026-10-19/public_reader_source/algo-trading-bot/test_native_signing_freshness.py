"""Offline evidence renewal for one native qualification wire; no venue claims."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace
import json
import pytest
from exchange.base_exchange import ExchangeError
from exchange.native_qualification import NativeQualificationTransport
from exchange.order_lifecycle import OrderRequest
from exchange.qualification_signing_boundary import fresh
from test_native_price_corridor import corridor, native, live
from test_exchange_migration import NOW


def expire_after_nonce(c, monkeypatch, *, change=None, delay_ms=6000):
    original=c.live.executor.signing_boundary.refresh_permit;calls=[]
    def refresh(permit,action):
        calls.append(1)
        if len(calls)==3:
            c.live.fixture.now+=delay_ms;c.live.fixture.book['time']=c.live.fixture.now
            if change:change()
        return original(permit,action)
    monkeypatch.setattr(c.live.executor.signing_boundary,'refresh_permit',refresh)
    return calls


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_real_readiness_is_reacquired_after_nonce_without_repricing_or_second_entry(corridor,monkeypatch,fraction):
    c=corridor;old=c.context.readiness.observed_ms;c.venue.partial_entry=D(fraction)
    calls=expire_after_nonce(c,monkeypatch)
    result=c.sequence.run()
    assert result['status']==('NO_FILL_VERIFIED' if fraction=='0' else 'TRADE_CLOSED_RECONCILED'),result.get('error')
    entries=[x['orders'][0] for x in c.venue.calls if x['type']=='order' and not x['orders'][0]['r']]
    assert len(entries)==1 and D(entries[0]['s'])==D('.0002') and len(calls)>=3
    row=c.live.journal.intent(c.sequence.prefix+'entry')
    assert json.loads(row['request'])['price']==entries[0]['p']
    assert c.context.readiness.observed_ms==old
    reacquired=[json.loads(x[0]) for x in c.live.journal.db.execute(
        "SELECT data FROM events WHERE kind='QUALIFICATION_FRESH_ACCOUNT_ACQUIRED'")]
    assert reacquired and all(x['retimestamped'] is False for x in reacquired)
    assert reacquired[0]['readiness']['observed_ms']==NOW+6000
    assert all(0<=age<=5000 for x in reacquired for age in x['ages_ms'].values())
    assert not result['native_protection_qualified'] and not result['small_native_stop_verified']
    if fraction=='.5':assert result['partial_entry_aborted_without_native_stop']


@pytest.mark.parametrize('change',['position','orders','failed_read','fees','funding','depth','price','source','revocation'])
def test_new_evidence_never_overrides_a_changed_account_market_or_authority(corridor,monkeypatch,change):
    c=corridor
    def deteriorate():
        f=c.live.fixture
        if change=='position':f.position('.0001',c.p.reference_ask)
        elif change=='orders':f.orders=[dict(coin='par:BTC',oid=999,side='B',sz='.0001',origSz='.0001',
            limitPx=c.p.reference_ask,isTrigger=False,reduceOnly=False,cloid='0x'+'a'*32,timestamp=f.now)]
        elif change=='failed_read':c.venue.rest_down=True
        elif change=='fees':f.fees['userCrossRate']='.001'
        elif change=='funding':
            for ctx in f.contexts:ctx['funding']=str(D(c.p.maximum_abs_funding_rate)+D('.00001'))
        elif change=='depth':f.book['levels']=[[dict(px=c.p.reference_bid,sz='.0001')],[dict(px=c.p.reference_ask,sz='.0001')]]
        elif change=='price':f.book['levels']=[[dict(px='84980',sz='.1')],[dict(px='85000',sz='.1')]]
        elif change=='source':c.auth.source_hash=lambda:'changed-source'
        else:c.auth.revoke()
    expire_after_nonce(c,monkeypatch,change=deteriorate)
    result=c.sequence.run()
    assert result['status']=='EMERGENCY_EXIT_REQUIRED',result
    assert not c.venue.calls and not c.live.transport.signed_payloads
    row=c.live.journal.intent(c.sequence.prefix+'entry');assert row['state']=='UNKNOWN'
    with pytest.raises(ExchangeError,match='EXACT_RESERVED_INTENT'):
        c.live.executor.recovery.recover_for_signing(row['intent_key'])
    assert c.live.journal.intent(row['intent_key'])==row


@pytest.mark.parametrize('gate',['startup','client','feed','backoff','agent_expired','validation_age','readiness_age'])
def test_native_fresh_frame_retains_every_original_health_and_five_second_gate(corridor,gate):
    c=corridor;e=c.live.executor;context=c.context;checked=c.live.fixture.now
    request=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc')
    if gate=='startup':e.recovery.startup_coordinator=SimpleNamespace(entry_ready=False)
    elif gate=='client':e.client.ready=False
    elif gate=='feed':e.context_provider.feed_ready=lambda:False
    elif gate=='backoff':e.rate_limits.backoff_until=checked+1
    elif gate=='agent_expired':context=replace(context,readiness=replace(context.readiness,agent_expiry_ms=checked))
    elif gate=='validation_age':checked-=5001
    else:context=replace(context,readiness=replace(context.readiness,observed_ms=checked-5001))
    e.signing_boundary.current=dict(request=request,context=context,checked_ms=checked)
    with pytest.raises(ExchangeError):e._guard(context,checked,entry=True,entry_request=request)
    assert not c.venue.calls


def test_exact_five_second_boundary_is_unchanged(corridor):
    assert fresh(corridor.context,NOW+5000)
    assert not fresh(corridor.context,NOW+5001)
    assert corridor.context.readiness.observed_ms==NOW


@pytest.mark.parametrize('change',['position','orders','failed_read','funding','reference','metadata'])
def test_native_reads_account_again_inside_five_second_window(corridor,monkeypatch,change):
    c=corridor
    def changed():
        if change=='position':c.live.fixture.position('.0001',c.p.reference_ask)
        elif change=='orders':c.live.fixture.orders=[dict(coin='par:BTC',oid=999,side='B',sz='.0001',
            origSz='.0001',limitPx=c.p.reference_ask,isTrigger=False,reduceOnly=False,cloid='0x'+'c'*32,timestamp=NOW)]
        elif change=='failed_read':c.venue.rest_down=True
        elif change=='funding':
            for value in c.live.fixture.contexts:value['funding']=str(D(c.p.maximum_abs_funding_rate)+D('.00001'))
        elif change=='reference':
            for value in c.live.fixture.contexts:value['oraclePx']='90000'
        else:c.live.fixture.metadata['universe'][0]['szDecimals']=3
    expire_after_nonce(c,monkeypatch,change=changed,delay_ms=0)
    result=c.sequence.run()
    assert result['status']=='EMERGENCY_EXIT_REQUIRED'
    assert not c.venue.calls and not c.live.transport.signed_payloads
    assert c.live.journal.intent(c.sequence.prefix+'entry')['state']=='UNKNOWN'


def test_pre_http_rejection_records_exact_reason_nonce_and_identity_without_signature(corridor):
    c=corridor;t=NativeQualificationTransport.__new__(NativeQualificationTransport)
    t.authorization=c.auth;t.client=c.live.client;t.action_expiry_ms=c.a.expires_ms
    def reject(action):raise ExchangeError('NATIVE_FUNDING_ABOVE_APPROVED_CEILING')
    t.check=reject
    payload=dict(action={'type':'order','orders':[{'c':'0x'+'b'*32}]},nonce=NOW,expiresAfter=c.a.expires_ms)
    with pytest.raises(ExchangeError,match='FUNDING_ABOVE'):t.transmit(payload)
    records=[json.loads(v) for v, in c.live.journal.db.execute(
        "SELECT data FROM events WHERE kind='QUALIFICATION_TRANSPORT_BOUNDARY'")]
    assert len(records)==1 and records[0]['stage']=='PRE_HTTP_REJECTED'
    assert records[0]['reason']=='NATIVE_FUNDING_ABOVE_APPROVED_CEILING'
    assert records[0]['nonce']==NOW and records[0]['cloid']=='0x'+'b'*32
    assert not any(k in records[0] for k in ('signature','private_key','payload'))
    assert not c.venue.calls
