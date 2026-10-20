"""Offline SELL-only recovery tests; ephemeral SDK and synthetic venue only."""
from dataclasses import asdict,replace
from decimal import Decimal as D
from types import SimpleNamespace
import json
import pytest
from exchange.base_exchange import ExchangeError,Fill
from exchange.exit_recovery import (RecoveryMandate,RecoveryApproval,ExitAuthorization,
    ExitExecution,ExitRecovery,profit_floor,entry_evidence,ACKS,ENTRY_OID,ENTRY_TID)
from exchange.certification_runtime import same_position_exposure
from exchange.emergency_qualification import permission
from exchange.order_lifecycle import OrderRequest
from test_emergency_qualification import emergency,live


@pytest.fixture
def recovered(emergency,monkeypatch,tmp_path):
    import exchange.exit_recovery as mod
    c=emergency;l=c.live
    l.client.rate_limits=l.rate
    def advance_wait(ms):
        l.fixture.now+=int(ms);l.fixture.book['time']=l.fixture.now
    l.rate.wait=advance_wait
    monkeypatch.setattr(mod,'TEAM',c.p.team_wallet);monkeypatch.setattr(mod,'API',c.p.api_wallet)
    monkeypatch.setattr(mod,'ENTRY_MS',l.fixture.now)
    l.fixture.position('.0002','81512')
    l.fixture.fill('.0002',price='81512',oid=int(ENTRY_OID),tid=int(ENTRY_TID),fee='.014672')
    l.fixture.book.update(levels=[[dict(px='83000',sz='.1')],[dict(px='83020',sz='.1')]])
    l.fixture.contexts=[dict(markPx='83010',oraclePx='83010',funding='.0001',openInterest='10') for _ in l.fixture.metadata['universe']]
    original=OrderRequest('par:BTC','BUY','.0002','81593',tif='Ioc',strategy_id='TESTNET_CERTIFICATION_ENTRY')
    row,_=l.journal.reserve('offline:original-entry',asdict(original),'offline:original',l.fixture.now)
    l.journal.update(row['intent_key'],'FILLED',l.fixture.now,oid=ENTRY_OID,outcome=dict(filled_quantity='.0002',remaining_quantity='0'))
    recovery=ExitRecovery(l.account,l.journal,initial_start_ms=c.sequence.e.recovery.initial_start_ms)
    l.provider.reconcile_before_load=recovery.recover;l.provider.reconciliation_ready=lambda:recovery.account_truth_ready
    l.provider.conservative_fee=lambda context:D('.0009')
    m=RecoveryMandate('ab'*16,l.fixture.now,l.fixture.now+300000,'fixture-source','fixture-policy',c.p.identity,'81664',
        team_wallet=c.p.team_wallet,api_wallet=c.p.api_wallet).require()
    a=RecoveryApproval(m.identity,'OFFLINE_FIXTURE_ACCEPTANCE',l.fixture.now,l.fixture.now+600000,**{k:True for k in ACKS})
    path=tmp_path/'recovery_approval.json';path.write_text(json.dumps(asdict(a)))
    auth=ExitAuthorization(c.p,m,a,l.journal,path,clock_ms=lambda:l.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy');auth.register()
    e=ExitExecution(l.client,proposal=c.p,transport=l.transport,account=l.account,journal=l.journal,
        context_provider=l.provider,validator=l.validator,recovery=recovery,clock_health=l.clock,rate_limits=l.rate)
    l.executor=e;c.venue.auth=auth;l.transport.authorization=auth
    c.auth=auth;c.m=m;c.a=a;c.path=path;c.e=e;c.recovery=recovery
    return c


def draft(c):
    r=OrderRequest('par:BTC','SELL','.0002',c.m.minimum_sell,reduce_only=True,
        strategy_id='TESTNET_CERTIFICATION_EXIT',tif='Ioc',client_order_id='certification:'+c.p.identity+':exit:0')
    return r,permission(r,c.p,c.live.fixture.now,reason='EXACT_FULL_POSITION_CLOSE')


def test_sell_only_real_composition_closes_without_buy(recovered):
    c=recovered;r,p=draft(c);order=c.e.close_full_position(r,permission=p)
    assert order.filled_quantity==D('.0002') and not c.live.account.get_positions()
    assert len(c.venue.calls)==1
    w=c.venue.calls[0]['orders'][0];assert w['b'] is False and w['r'] is True and D(w['p'])>=D('81664')
    assert len(c.live.transport.signed_payloads)==1


def test_recovery_context_is_fresh_and_reports_existing_long(recovered):
    c=recovered;r,_=draft(c);ctx=c.live.provider.load(r,critical=True)
    assert ctx.reconciled and ctx.positions['par:BTC'].quantity==D('.0002')


@pytest.mark.parametrize('change',['buy','not_reduce','wrong_quantity','wrong_symbol','gtc'])
def test_entry_or_changed_close_is_never_signed(recovered,change):
    c=recovered;r,p=draft(c)
    changes={'buy':dict(side='BUY'),'not_reduce':dict(reduce_only=False),'wrong_quantity':dict(quantity='.0001'),
        'wrong_symbol':dict(symbol='par:ETH'),'gtc':dict(tif='Gtc')}
    with pytest.raises(ExchangeError):c.e.close_full_position(replace(r,**changes[change]),permission=p)
    assert not c.venue.calls


def test_public_submit_method_always_refuses_even_buy(recovered):
    c=recovered;r,p=draft(c)
    with pytest.raises(ExchangeError,match='NO_ENTRY'):c.e.submit(r,permission=p)
    assert not c.venue.calls


@pytest.mark.parametrize('change',['closed','smaller','larger','short','open_order','low_bid','thin_depth'])
def test_account_or_liquidity_change_stops_before_intent(recovered,change):
    c=recovered;l=c.live
    if change in {'closed','smaller','larger','short'}:
        l.fixture.position({'closed':'0','smaller':'.0001','larger':'.0003','short':'-.0002'}[change],'81512')
    elif change=='open_order':l.fixture.orders=[dict(coin='par:BTC',oid=999,side='A',sz='.0002',origSz='.0002',limitPx='83000',isTrigger=False,reduceOnly=True)]
    elif change=='low_bid':l.fixture.book['levels']=[[dict(px='81500',sz='.1')],[dict(px='81520',sz='.1')]]
    else:l.fixture.book['levels'][0]=[dict(px='83000',sz='.0001')]
    r,p=draft(c)
    with pytest.raises(ExchangeError):c.e.close_full_position(r,permission=p)
    assert not c.venue.calls and c.live.journal.intent(r.client_order_id) is None


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_ioc_outcome_never_creates_second_exit(recovered,fraction):
    c=recovered;c.venue.partial_exit=D(fraction);r,p=draft(c)
    c.e.close_full_position(r,permission=p)
    count=len(c.venue.calls)
    with pytest.raises(ExchangeError):c.e.close_full_position(r,permission=p)
    assert len(c.venue.calls)==count==1
    held=c.live.account.get_position('par:BTC')
    assert (held.quantity if held else D(0))==D('.0002')*(1-D(fraction))


@pytest.mark.parametrize('what',['expiry','revoked','source','changed_file'])
def test_new_exact_authority_enforced_before_signing(recovered,what):
    c=recovered
    if what=='expiry':c.live.fixture.now=c.a.expires_ms
    if what=='revoked':c.path.with_name('recovery_revocation.json').write_text('{}')
    if what=='source':c.auth.source_hash=lambda:'wrong'
    if what=='changed_file':c.path.write_text('{}')
    r,p=draft(c)
    with pytest.raises(ExchangeError):c.e.close_full_position(r,permission=p)
    assert not c.venue.calls


def test_restart_does_not_receive_old_runtime_authority(recovered):
    c=recovered
    other=ExitAuthorization(c.p,c.m,c.a,c.live.journal,c.path,clock_ms=lambda:c.live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    with pytest.raises(ExchangeError,match='RESTART_READ_ONLY'):other.require(c.p.team_wallet,c.p.api_wallet)
    assert not c.venue.calls


@pytest.mark.parametrize('ack',ACKS)
def test_all_exit_risk_acknowledgments_are_required(recovered,ack):
    c=recovered;a=replace(c.a,**{ack:False})
    with pytest.raises(ExchangeError):a.require(c.m,c.live.fixture.now)


def test_exact_profit_math_includes_entry_fee_and_negative_funding(recovered):
    spec=recovered.live.client.market('par:BTC')
    be,floor=profit_floor(spec,D('.0002'),D('16.3024'),D('.014672'),D('.0009'),D(0))
    assert D('81658.85')<be<D('81658.86') and floor==D('81664')
    _,higher=profit_floor(spec,D('.0002'),D('16.3024'),D('.014672'),D('.0027'),D('-.001'))
    assert higher>floor


@pytest.mark.parametrize('field',['quantity','entry_price','leverage'])
def test_reconciliation_still_rejects_actual_exposure_changes(field):
    p=SimpleNamespace(quantity=D('.0002'),entry_price=D('81512'),leverage={'type':'cross','value':1},unrealized_pnl=D(0))
    q=SimpleNamespace(**vars(p));setattr(q,field,{'quantity':D('.0001'),'entry_price':D('81513'),'leverage':{'type':'cross','value':2}}[field])
    assert not same_position_exposure({'par:BTC':p},{'par:BTC':q})


def test_mark_pnl_movement_is_not_position_change():
    p=SimpleNamespace(quantity=D('.0002'),entry_price=D('81512'),leverage={'type':'cross','value':1},unrealized_pnl=D(0))
    q=SimpleNamespace(**dict(vars(p),unrealized_pnl=D('.001')))
    assert same_position_exposure({'par:BTC':p},{'par:BTC':q})


def test_rate_rejection_is_local_and_diagnostic(recovered):
    r=recovered.live.rate;r.ip_weight_limit=1200;r.weights=[(r.clock_ms(),1199)]
    with pytest.raises(ExchangeError,match='RATE_LIMITED'):r.reserve_info('userFunding')
    data=json.loads(recovered.live.journal.db.execute("SELECT data FROM events WHERE kind='INFO_RATE_BUDGET_REJECTED' ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert data['query']=='userFunding' and data['source']=='LOCAL_RATE_GUARD; NO_HTTP_SENT'


def test_recovery_waits_for_safety_budget_without_resetting_usage(recovered,monkeypatch):
    c=recovered;r=c.live.rate;calls=[];original=r.wait_for_read_budget
    def wait(weight,**kwargs):calls.append((weight,kwargs.get('priority')));return original(weight,**kwargs)
    monkeypatch.setattr(r,'wait_for_read_budget',wait)
    before=list(r.weights);c.recovery.recover()
    assert calls[0][0]==500 and calls[0][1].name=='SAFETY'
    assert all(row in r.weights for row in before)


def test_freshness_expiration_during_signing_reacquires_without_extra_exit(recovered,monkeypatch):
    c=recovered;boundary=c.e.signing_boundary;original=boundary.refresh_permit;calls=[]
    def refresh(permit,action):
        calls.append(1)
        if len(calls)==3:
            c.live.fixture.now+=6000;c.live.fixture.book['time']=c.live.fixture.now
        return original(permit,action)
    monkeypatch.setattr(boundary,'refresh_permit',refresh)
    r,p=draft(c);order=c.e.close_full_position(r,permission=p)
    assert order.filled_quantity==D('.0002') and len(c.venue.calls)==1


def test_uncertain_exit_does_not_retransmit(recovered,monkeypatch):
    c=recovered;original=c.live.transport.transmit
    def lost_ack(payload):original(payload);raise TimeoutError('OFFLINE_LOST_EXIT_RESPONSE')
    monkeypatch.setattr(c.live.transport,'transmit',lost_ack)
    r,p=draft(c);c.e.close_full_position(r,permission=p)
    count=len(c.venue.calls)
    with pytest.raises(ExchangeError):c.e.close_full_position(r,permission=p)
    assert count==len(c.venue.calls)==1


@pytest.mark.parametrize('field,value',[('mode','BUY'),('quantity','.0003'),('minimum_sell','80140'),
    ('window_ms',600001),('minimum_net_profit','-1'),('maximum_exit_fee','.1')])
def test_recovery_mandate_cannot_enlarge_scope(recovered,field,value):
    with pytest.raises(ExchangeError):replace(recovered.m,**{field:value}).require()


@pytest.mark.parametrize('field,value',[('operator_acceptance',''),('mandate_hash','old'),
    ('accepted_ms',-1),('expires_ms',1)])
def test_recovery_approval_cannot_be_fabricated_or_extended(recovered,field,value):
    c=recovered
    with pytest.raises(ExchangeError):replace(c.a,**{field:value}).require(c.m,c.live.fixture.now)


@pytest.mark.parametrize('damage',['fee','order_id','trade_id','source','timestamp_ms'])
def test_exact_original_entry_evidence_required(recovered,damage):
    c=recovered;c.recovery.recover();fill=next(iter(c.recovery.state.fills.values()))
    values={'fee':D('.001'),'order_id':'1','trade_id':'2','source':'SIMULATED','timestamp_ms':0}
    with pytest.raises(ExchangeError):entry_evidence([replace(fill,**{damage:values[damage]})])


@pytest.mark.parametrize('scale,expected',[(None,'.00270'),(D('0'),'.00045'),(D('.5'),'.000675'),(D('1'),'.00090'),(D('3'),'.00270')])
def test_current_fee_or_documented_conservative_bound(recovered,scale,expected):
    from exchange.exit_recovery import RecoveryProvider
    c=recovered;obj=RecoveryProvider.__new__(RecoveryProvider)
    obj.client=c.live.client;obj.current_fee_scale=scale;obj.fee_scale_ms=c.live.fixture.now
    ctx=SimpleNamespace(readiness=SimpleNamespace(fees={'userCrossRate':'.00045'}))
    assert obj.conservative_fee(ctx)==D(expected)


def test_immediate_loss_is_a_distinct_explicit_mandate(recovered):
    c=recovered;loss=replace(c.m,mode='BOUNDED_LOSS_EXIT',minimum_net_profit='-0.50',window_ms=120000).require()
    assert loss.identity!=c.m.identity
    with pytest.raises(ExchangeError):c.a.require(loss,c.live.fixture.now)


@pytest.mark.parametrize('age',[0,61000])
def test_real_recovery_provider_refreshes_metadata_and_uses_missing_scale_bound(recovered,age):
    from exchange.exit_recovery import RecoveryProvider
    c=recovered;l=c.live;l.fixture.now+=age;l.fixture.book['time']=l.fixture.now
    provider=RecoveryProvider(l.market,l.account,c.p.api_wallet,l.clock,l.rate,
        reconcile_before_load=c.recovery.recover,reconciliation_ready=lambda:c.recovery.account_truth_ready,
        feed_ready=lambda:True,wait=lambda seconds:l.rate.wait(seconds*1000))
    c.e.context_provider=provider;l.provider=provider
    r,p=draft(c);order=c.e.close_full_position(r,permission=p)
    assert order.filled_quantity==D('.0002') and len(c.venue.calls)==1
    assert provider.current_fee_scale is None and provider.fee_scale_ms>=c.a.accepted_ms


def test_loss_exit_runs_only_with_its_separate_explicit_approval(recovered):
    c=recovered;c.auth.revoke()
    c.m=replace(c.m,mode='BOUNDED_LOSS_EXIT',minimum_sell='80141',minimum_net_profit='-0.50',window_ms=120000)
    c.a=RecoveryApproval(c.m.identity,'OFFLINE_EXPLICIT_LOSS_ACCEPTANCE',c.live.fixture.now,c.live.fixture.now+120000,**{k:True for k in ACKS})
    c.path.write_text(json.dumps(asdict(c.a)))
    auth=ExitAuthorization(c.p,c.m,c.a,c.live.journal,c.path,clock_ms=lambda:c.live.fixture.now,
        source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy');auth.register()
    c.auth=auth;c.venue.auth=auth;c.live.transport.authorization=auth
    c.live.fixture.book.update(levels=[[dict(px='81472',sz='.1')],[dict(px='81572',sz='.1')]])
    c.live.fixture.contexts=[dict(markPx='81570',oraclePx='81590',funding='.0001',openInterest='10') for _ in c.live.fixture.metadata['universe']]
    r,p=draft(c);order=c.e.close_full_position(r,permission=p)
    assert order.filled_quantity==D('.0002') and len(c.venue.calls)==1
    assert D('80141')<=D(c.venue.calls[0]['orders'][0]['p'])<D('81512')


@pytest.mark.parametrize('bid,ask',[('83250','83270'),('82750','82770')])
def test_immutable_sell_outside_fresh_price_allowance_is_not_sent(recovered,monkeypatch,bid,ask):
    c=recovered;boundary=c.e.signing_boundary;original=boundary.refresh_permit;calls=[]
    def changed(permit,action):
        calls.append(1)
        if len(calls)==3:c.live.fixture.book['levels']=[[dict(px=bid,sz='.1')],[dict(px=ask,sz='.1')]]
        return original(permit,action)
    monkeypatch.setattr(boundary,'refresh_permit',changed)
    r,p=draft(c);order=c.e.close_full_position(r,permission=p)
    assert not c.venue.calls and order.state.value=='UNKNOWN'
