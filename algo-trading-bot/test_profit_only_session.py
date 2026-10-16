"""Offline full-day lifecycle tests. No actual-wallet signatures or exchange HTTP."""
from dataclasses import asdict,replace
from decimal import Decimal as D
from types import SimpleNamespace as NS
import json
import pytest
from exchange.base_exchange import ExchangeError,MarketSpec,OrderBook,BookLevel
from exchange.exit_recovery import RecoveryMandate,RecoveryApproval,ExitAuthorization,ACKS
from exchange.profit_only_session import (LongSessionMandate,full_day_mandate,profit_observation,
    fee_bound,LongSessionObserver,START_MS,END_MS,LONG_MODE)
from test_exit_recovery import recovered,emergency,live,draft


def base():
    now=START_MS+12*3600000
    return RecoveryMandate('cd'*16,now,now+300000,'offline-source','offline-policy','ab'*32,'81812')


def accepted(m):
    now=m.created_ms+1000
    return RecoveryApproval(m.identity,'OFFLINE_EXPLICIT_FULL_DAY',now,m.expires_at(now),**{k:True for k in ACKS})


def test_full_day_fixed_end_not_rolling_or_ten_minutes():
    m=full_day_mandate(base());a=accepted(m)
    a.require(m,a.accepted_ms+6*3600000)
    assert a.expires_ms==END_MS and m.mode==LONG_MODE
    with pytest.raises(ExchangeError):a.require(m,END_MS)


@pytest.mark.parametrize('field,value',[('mode','PROFIT_ONLY_EXIT'),('session_end_ms',END_MS+1),
    ('reconciliation_reserve_ms',0),('window_ms',600000),('quantity','.0003'),('maximum_exit_fee','.004'),
    ('minimum_net_profit','0'),('minimum_sell','80140'),('created_ms',START_MS-1)])
def test_long_session_scope_cannot_expand(field,value):
    with pytest.raises(ExchangeError):replace(full_day_mandate(base()),**{field:value}).require()


def test_legacy_identity_and_ten_minute_approval_remain_unchanged():
    m=base();a=accepted(m);assert a.expires_ms==a.accepted_ms+600000
    assert set(asdict(m))==set(RecoveryMandate.__dataclass_fields__)
    with pytest.raises(ExchangeError):a.require(full_day_mandate(m),a.accepted_ms)


@pytest.mark.parametrize('ack',ACKS)
def test_full_day_requires_every_exact_risk_acknowledgment(ack):
    m=full_day_mandate(base());a=replace(accepted(m),**{ack:False})
    with pytest.raises(ExchangeError):a.require(m,a.accepted_ms)


@pytest.mark.parametrize('damage',['late_acceptance','extended_expiry','previous_window'])
def test_long_approval_never_backdated_extended_or_reused(damage):
    m=full_day_mandate(base());a=accepted(m)
    changes={'late_acceptance':dict(accepted_ms=m.approval_deadline_ms+1),
        'extended_expiry':dict(expires_ms=END_MS+1),'previous_window':dict(mandate_hash=base().identity)}
    a=replace(a,**changes[damage])
    with pytest.raises(ExchangeError):a.require(m,a.accepted_ms)


def observation(**changes):
    now=START_MS+12*3600000
    spec=MarketSpec('par:BTC',4,40,2670000)
    book=OrderBook('par:BTC',now,(BookLevel(D('83000'),D('.01')),),(BookLevel(D('83020'),D('.01')),),now,now)
    e=NS(quantity=D('.0002'),price=D('81512'),fee=D('.014672'))
    args=dict(now_ms=now,expires_ms=END_MS,reserve_ms=120000,market_context={'markPx':'83010','oraclePx':'83010'},
        account_ms=now,fees_ms=now,funding_ms=now,reference_ms=now)
    other=dict(book=book,entry=e,fee=D('.0027'),funding=D('-.000060'),floor=D('81812'))
    for k,v in changes.items():(other if k in other else args)[k]=v
    return profit_observation(spec,**other,**args)


def test_profitable_actual_depth_candidate_has_positive_net_and_full_log():
    r=observation();assert r['candidate'] and r['estimated_net_at_limit']>0
    assert all(k in r for k in ['bid','ask','book_depth','mark','oracle','funding_cashflow','conservative_exit_fee','break_even','minimum_sell','evidence_ages_ms'])


@pytest.mark.parametrize('damage',['stale','missing','thin','spread','reserve','fees','funding_age','account_age','reference_age'])
def test_unusable_data_never_qualifies_for_signing(damage):
    now=START_MS+12*3600000;book=observation()['book_depth']
    kwargs={}
    if damage=='stale':kwargs['now_ms']=now+5001
    if damage=='missing':kwargs['book']=None
    if damage=='thin':kwargs['book']=OrderBook('par:BTC',now,(BookLevel(D('83000'),D('.0001')),),(BookLevel(D('83020'),D('.01')),))
    if damage=='spread':kwargs['book']=OrderBook('par:BTC',now,(BookLevel(D('83000'),D('.01')),),(BookLevel(D('85000'),D('.01')),))
    if damage=='reserve':kwargs['expires_ms']=now+120000
    if damage=='fees':kwargs['fee']=D('.0031')
    if damage=='funding_age':kwargs['funding_ms']=now-310001
    if damage=='account_age':kwargs['account_ms']=now-90001
    if damage=='reference_age':kwargs['reference_ms']=now-45001
    assert not observation(**kwargs)['candidate']


def test_new_funding_and_fees_raise_floor_without_lowering_prior_floor():
    old=observation(floor=D('81812'))
    worse=observation(funding=D('-.10'),fee=D('.003'),floor=old['minimum_sell'])
    improved=observation(funding=D('.1'),fee=D('.0009'),floor=worse['minimum_sell'])
    assert worse['minimum_sell']>old['minimum_sell'] and improved['minimum_sell']==worse['minimum_sell']


@pytest.fixture
def long_recovered(recovered,monkeypatch):
    import exchange.profit_only_session as mod
    c=recovered;now=c.live.fixture.now
    monkeypatch.setattr(mod,'START_MS',now-12*3600000);monkeypatch.setattr(mod,'END_MS',now+12*3600000)
    m=LongSessionMandate(**dict(asdict(c.m),mode=LONG_MODE,window_ms=12*3600000),session_end_ms=now+12*3600000).require()
    a=accepted(m);c.live.fixture.now=a.accepted_ms;c.live.fixture.book['time']=a.accepted_ms
    c.path.write_text(json.dumps(asdict(a)));c.auth.revoke()
    auth=ExitAuthorization(c.p,m,a,c.live.journal,c.path,clock_ms=lambda:c.live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy');auth.register()
    c.m,c.a,c.auth=m,a,auth;c.venue.auth=auth;c.live.transport.authorization=auth
    return c


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_full_day_existing_sell_pipeline_zero_partial_full_and_no_repeat(long_recovered,fraction):
    c=long_recovered;c.venue.partial_exit=D(fraction);r,p=draft(c)
    order=c.e.close_full_position(r,permission=p);assert len(c.venue.calls)==1
    with pytest.raises(ExchangeError):c.e.close_full_position(r,permission=p)
    assert len(c.venue.calls)==1


@pytest.mark.parametrize('damage',['revoked','lease','cutoff','restart','unknown'])
def test_revocation_disconnect_interruption_or_uncertainty_prevents_new_write(long_recovered,monkeypatch,damage):
    c=long_recovered;r,p=draft(c)
    if damage=='revoked':c.path.with_name('recovery_revocation.json').write_text('{}')
    if damage=='lease':
        c.live.transport.nonces.degrade('OFFLINE_LEASE_LOSS')
        order=c.e.close_full_position(r,permission=p)
        assert order.state.value=='UNKNOWN' and not c.venue.calls
    if damage=='cutoff':c.live.fixture.now=c.a.expires_ms-120000
    if damage=='restart':c.auth.token='new-process-token'
    if damage=='unknown':
        original=c.live.transport.transmit
        def lost(payload):original(payload);raise TimeoutError('OFFLINE_LOST_ACK')
        monkeypatch.setattr(c.live.transport,'transmit',lost)
        c.e.close_full_position(r,permission=p)
    before=len(c.venue.calls)
    with pytest.raises(ExchangeError):c.e.close_full_position(r,permission=p)
    assert len(c.venue.calls)==before


def test_one_closing_path_is_durable_even_without_order_intent(long_recovered):
    c=long_recovered;observer=LongSessionObserver.__new__(LongSessionObserver)
    observer.m,observer.a,observer.env,observer.claimed=c.m,c.a,NS(client=c.live.client,journal=c.live.journal),False
    observer.claim_closing_path(c.auth)
    other=LongSessionObserver.__new__(LongSessionObserver)
    other.m,other.a,other.env,other.claimed=observer.m,observer.a,observer.env,False
    with pytest.raises(ExchangeError):other.claim_closing_path(c.auth)
    assert not c.venue.calls


def test_observer_stops_after_two_minutes_without_fresh_book(long_recovered):
    c=long_recovered;l=c.live;r,_=draft(c);ctx=l.provider.load(r,critical=True)
    env=NS(client=l.client,journal=l.journal,recovery=c.recovery,provider=NS(current_fee_scale=None))
    observer=LongSessionObserver(env,c.m,c.a,ctx,next(iter(c.recovery.state.fills.values())))
    observer.observation(None,'NO_FRESH_BOOK',{'connected':False})
    l.fixture.now+=120000
    with pytest.raises(ExchangeError,match='NO_FRESH_BOOK'):observer.observation(None,'NO_FRESH_BOOK',{})

@pytest.fixture
def observed(long_recovered):
    from exchange.execution_journal import fingerprint
    c=long_recovered;l=c.live;r,_=draft(c);ctx=l.provider.load(r,critical=True)
    calls=dict(full=0,positions=0,orders=0,fees=0,scale=0,reference=0)
    metadata={'universe':[{'name':'par:BTC'}]}
    def pos():calls['positions']+=1;return {'par:BTC':NS(quantity=D('.0002'),entry_price=D('81512'),leverage={'type':'cross','value':1})}
    def orders():calls['orders']+=1;return []
    def query(kind):assert kind=='userFees';calls['fees']+=1;return {'userCrossRate':'.00045'}
    def scale():calls['scale']+=1
    def refs(kind):assert kind=='metaAndAssetCtxs';calls['reference']+=1;client.last_received_ms=l.fixture.now;return metadata,[dict(markPx='83010',oraclePx='83010')]
    client=NS(clock_ms=lambda:l.fixture.now,post_info=refs,validate_metadata=lambda _:None,last_received_ms=l.fixture.now)
    provider=NS(current_fee_scale=None,fee_scale=scale,metadata_hash=fingerprint(metadata))
    env=NS(client=client,journal=l.journal,recovery=c.recovery,provider=provider,account=NS(get_positions=pos,get_frontend_open_orders=orders,_query=query))
    def context():
        calls['full']+=1;c.recovery.state.last_window=(0,l.fixture.now)
        return ctx,next(iter(c.recovery.state.fills.values()))
    env.context=context
    observer=LongSessionObserver(env,c.m,c.a,*context());calls['full']=0
    return NS(c=c,observer=observer,env=env,calls=calls)


def test_light_account_fee_reference_polls_do_not_repeat_full_history(observed):
    o=observed;o.c.live.fixture.now+=61000;o.observer.refresh_if_due()
    assert o.calls==dict(full=0,positions=1,orders=1,fees=1,scale=1,reference=1)


def test_full_history_refresh_is_bounded_to_five_minute_schedule(observed):
    o=observed;o.c.live.fixture.now+=300001;o.observer.refresh_if_due()
    assert o.calls['full']==1 and o.calls['positions']==0


@pytest.mark.parametrize('damage',['quantity','direction','leverage','orders'])
def test_light_poll_detects_changed_exposure_and_stops(observed,damage):
    o=observed;o.c.live.fixture.now+=61000
    if damage=='orders':o.env.account.get_frontend_open_orders=lambda:[{'oid':99}]
    else:
        p=NS(quantity=D('.0002'),entry_price=D('81512'),leverage={'type':'cross','value':1})
        if damage=='quantity':p.quantity=D('.0001')
        if damage=='direction':p.quantity=D('-.0002')
        if damage=='leverage':p.leverage={'type':'cross','value':2}
        o.env.account.get_positions=lambda:{'par:BTC':p}
    with pytest.raises(ExchangeError):o.observer.refresh_if_due()
    assert not o.c.venue.calls


def test_fee_above_approved_ceiling_stops_even_during_read_only_observation(observed):
    o=observed;o.c.live.fixture.now+=61000;o.env.account._query=lambda _:dict(userCrossRate='.001')
    with pytest.raises(ExchangeError,match='FEE_ABOVE'):o.observer.refresh_if_due()


def test_funding_rollover_triggers_early_authoritative_refresh(observed):
    o=observed;now=o.c.live.fixture.now
    o.observer.funding_ms=(now//3600000)*3600000-1
    o.c.live.fixture.now+=2000;o.observer.refresh_if_due()
    assert o.calls['full']==1


def test_full_preflight_cooldown_does_not_repeatedly_query_history(observed):
    o=observed;o.observer.last_candidate=o.c.live.fixture.now
    r,_=draft(o.c);book=o.c.live.market.get_orderbook('par:BTC')
    assert not o.observer.observation(book,'OFFLINE_WS',{})['candidate']
    assert o.observer.observation(book,'OFFLINE_PREFLIGHT',{},preflight=True)['candidate']


def test_native_limit_does_not_require_a_market_top_forecast():
    r=observation();assert r['candidate'] and r['proposed_limit']<=r['bid']
