"""Ephemeral OFFLINE SDK fixtures only; no actual wallet or venue qualification."""
from dataclasses import asdict, replace
from decimal import Decimal as D
import json
from pathlib import Path
import pytest

from exchange.base_exchange import ExchangeError
from exchange.native_price_corridor import (CorridorNativeProposal, CorridorNativeApproval,
    corridor_bounds, require_corridor_mapping, select_entry_price, check_selected_price)
from exchange.native_qualification import (propose, NativeQualificationAuthorization,
    NativeQualificationExecution, NativeQualificationSequence, NativeQualificationContextProvider, check_entry)
from exchange.testnet_certification import test_permission as permission
from exchange.order_lifecycle import OrderRequest
from test_native_qualification import native
from test_live_exchange_execution import live
from test_exchange_migration import NOW

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def corridor(native):
    c=native
    p=propose(c.context,c.live.client,'fixture-source','fixture-policy',bounded=True)
    a=CorridorNativeApproval(**{**asdict(c.a),'proposal_hash':p.identity,
        'bounded_price_corridor_accepted':True,'unqualified_native_test_exception_accepted':True})
    auth=NativeQualificationAuthorization(p,a,c.live.journal,root=ROOT,
        clock_ms=lambda:c.live.fixture.now,source_hash=lambda:'fixture-source',policy_hash=lambda:'fixture-policy')
    c.p,c.a,c.auth=p,a,auth;c.venue.auth=auth;c.live.transport.authorization=auth
    c.live.provider=NativeQualificationContextProvider(c.live.provider.market,c.live.account,
        c.live.signer.address,c.live.clock,c.live.rate,
        reconciliation_ready=lambda:c.live.executor.recovery.account_truth_ready,feed_ready=lambda:True)
    e=NativeQualificationExecution(c.live.client,proposal=p,transport=c.live.transport,
        account=c.live.account,journal=c.live.journal,context_provider=c.live.provider,
        validator=c.live.validator,recovery=c.live.executor.recovery,clock_health=c.live.clock,rate_limits=c.live.rate)
    c.live.executor=e
    c.sequence=NativeQualificationSequence(e,p,auth,wait=c.sequence.wait)
    return c


def market(c,ask,*,depth='.1'):
    c.live.fixture.book['levels']=[[dict(px=str(D(ask)-40),sz=depth)],[dict(px=str(ask),sz=depth)]]


def test_previous_two_dollar_crossing_selects_one_executable_wire_inside_approved_corridor(corridor):
    c=corridor;before=asdict(c.p);identity=c.p.identity
    old_fixed=c.live.client.market(c.p.symbol).normalize_price(D(c.p.reference_ask)*D('1.0005'),'BUY')
    ask=old_fixed+2;assert ask<=D(c.p.maximum_ask)
    market(c,ask);c.venue.partial_entry=D('.5')
    r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',r.get('error')
    entry=c.venue.calls[0]['orders'][0]
    assert ask<=D(entry['p'])<=ask*D('1.0005') and D(entry['p'])<=D(c.p.maximum_buy_price)
    assert D(entry['p'])>old_fixed and D(entry['s'])==D('.0002')
    assert len([x for x in c.venue.calls if x['type']=='order' and not x['orders'][0]['r']])==1
    assert asdict(c.p)==before and c.p.identity==identity
    assert not r['native_protection_qualified'] and not r['small_native_stop_verified']


@pytest.mark.parametrize('side',['above','below'])
def test_adverse_or_favourable_move_outside_exact_corridor_blocks_before_signing(corridor,side):
    c=corridor;ask=D(c.p.maximum_ask)+1 if side=='above' else D(c.p.minimum_ask)-1
    market(c,ask);r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' or r['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls and not c.live.transport.signed_payloads
    assert not c.live.account.get_positions()


@pytest.mark.parametrize('edge',['minimum_ask','maximum_ask'])
def test_exact_ask_boundaries_and_rounding_do_not_expand_corridor(corridor,edge):
    c=corridor;spec=c.live.client.market(c.p.symbol);ask=D(getattr(c.p,edge))
    px=select_entry_price(spec,c.p,ask)
    assert ask<=px<=ask*D('1.0005') and px<=D(c.p.maximum_buy_price)
    assert spec.normalize_price(px,'BUY')==px


def test_absolute_and_bps_caps_both_bind_with_runtime_rounding(corridor):
    spec=corridor.live.client.market('par:BTC')
    high=corridor_bounds(spec,'200000');assert D(high['maximum_ask'])-200000==100
    low=corridor_bounds(spec,'50000');assert D(low['maximum_ask'])-50000==50
    p=corridor.p
    assert D(p.maximum_ask)-D(p.reference_ask)<=D(p.maximum_adverse_movement_absolute)
    assert (D(p.maximum_ask)/D(p.reference_ask)-1)*10000<=D(p.maximum_adverse_movement_bps)


@pytest.mark.parametrize('change', ['depth','fees','funding','missing_funding','stale','leverage'])
def test_market_deterioration_preserves_independent_guards(corridor,change):
    c=corridor;ctx=c.context
    if change=='depth':ctx=replace(ctx,quote=replace(ctx.quote,ask_quantity=D('.0012')))
    elif change=='fees':ctx=replace(ctx,readiness=replace(ctx.readiness,fees={'userCrossRate':'.001'}))
    elif change in {'funding','missing_funding'}:
        values=dict(ctx.contexts);row=dict(values[c.p.symbol])
        if change=='funding':row['funding']=str(D(c.p.maximum_abs_funding_rate)+D('.000001'))
        else:row.pop('funding')
        values[c.p.symbol]=row;ctx=replace(ctx,contexts=values)
    elif change=='stale':ctx=replace(ctx,quote=replace(ctx.quote,mark_timestamp_ms=NOW-5001))
    else:ctx=replace(ctx,active_asset={**ctx.active_asset,'leverage':{'type':'cross','value':2}})
    with pytest.raises(ExchangeError):check_entry(ctx,c.p,NOW)
    assert not c.venue.calls


@pytest.mark.parametrize('field,value',[('maximum_buy_price','999999'),('minimum_ask','1'),
    ('maximum_ask','999999'),('entry_slippage_bps','6'),('maximum_adverse_movement_bps','11'),
    ('maximum_adverse_movement_absolute','101'),('maximum_abs_funding_rate','.002'),('quantity','.0003')])
def test_mandate_cannot_mutate_or_widen_after_approval(corridor,field,value):
    c=corridor
    with pytest.raises(ExchangeError):
        changed=replace(c.p,**{field:value});require_corridor_mapping(c.live.client.market(c.p.symbol),changed)
    assert not c.venue.calls


@pytest.mark.parametrize('field',['bounded_price_corridor_accepted','unqualified_native_test_exception_accepted'])
def test_new_corridor_and_unqualified_buy_exception_need_new_explicit_human_ack(corridor,field):
    c=corridor;c.auth.approval=replace(c.a,**{field:False})
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls and not c.live.transport.signed_payloads


def test_legacy_approval_cannot_authorize_new_corridor(corridor):
    from exchange.native_qualification import NativeQualificationApproval
    from dataclasses import fields
    c=corridor
    c.auth.approval=NativeQualificationApproval(**{f.name:getattr(c.a,f.name) for f in fields(NativeQualificationApproval)})
    with pytest.raises(ExchangeError,match='RISK_APPROVAL'):c.auth.require(c.p.team_wallet,c.p.api_wallet)
    assert not c.venue.calls


def test_duplicate_submit_returns_original_durable_price_and_never_reprices(corridor):
    c=corridor;c.sequence.observe();c.live.executor.entries_paused=False
    req=OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc',
        strategy_id='TESTNET_CERTIFICATION_ENTRY',client_order_id=c.sequence.prefix+'entry')
    first=c.live.executor.submit(req,permission=permission(req,c.p,NOW));count=len(c.venue.calls)
    original=json.loads(c.live.journal.intent(req.client_order_id)['request'])['price']
    market(c,D(c.p.maximum_ask))
    second=c.live.executor.submit(req,permission=permission(req,c.p,NOW))
    assert first.exchange_order_id==second.exchange_order_id and len(c.venue.calls)==count==1
    assert json.loads(c.live.journal.intent(req.client_order_id)['request'])['price']==original


def test_reserved_wire_is_not_repriced_at_signing_even_inside_broader_corridor(corridor,monkeypatch):
    c=corridor;original=c.live.transport.perform
    def moved(*args,**kwargs):
        market(c,D(c.p.maximum_ask))
        return original(*args,**kwargs)
    monkeypatch.setattr(c.live.transport,'perform',moved)
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED'
    assert not c.venue.calls and not c.live.transport.signed_payloads
    row=c.live.journal.intent(c.sequence.prefix+'entry');assert row['state']=='UNKNOWN'
    assert D(json.loads(row['request'])['price'])<D(c.p.maximum_buy_price)


def test_expired_approval_has_no_entry_or_price_selection(corridor):
    c=corridor;c.live.fixture.now=c.a.expires_ms
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED'
    assert not c.venue.calls


def test_current_funding_reserve_is_not_reported_as_actual_pnl(corridor):
    c=corridor;px=select_entry_price(c.context.spec,c.p,c.context.quote.ask)
    r=check_selected_price(c.context,c.p,px)
    assert D(r['funding_reserve'])==D(c.p.quantity)*px*abs(D(c.context.contexts[c.p.symbol]['funding']))
    assert D(r['planned_loss_plus_reserve'])<=D(c.p.session_loss_budget)
    assert not c.live.fixture.funding


def test_failed_fresh_preflight_consumes_corridor_invocation_before_key_and_blocks_restart(corridor,tmp_path,monkeypatch):
    import hashlib
    import sqlite3
    from types import SimpleNamespace
    import exchange.native_qualification_runtime as rt
    from exchange.native_qualification import CLOSE_PROOF
    c=corridor
    config=tmp_path/'configs/reliability_policy.json';config.parent.mkdir()
    config.write_bytes((ROOT/'configs/reliability_policy.json').read_bytes())
    evidence=tmp_path/CLOSE_PROOF;evidence.parent.mkdir(parents=True)
    evidence.write_bytes((ROOT/CLOSE_PROOF).read_bytes())
    state=tmp_path/'runtime/testnet/anchorium-bot-1';state.mkdir(parents=True)
    p=replace(c.p,reliability_policy_hash=hashlib.sha256(config.read_bytes()).hexdigest())
    a=replace(c.a,proposal_hash=p.identity)
    monkeypatch.setattr(rt,'active_source_hash',lambda _:p.source_hash)
    monkeypatch.setattr(rt,'require_qualification_regression',lambda *_:None)
    monkeypatch.setattr(rt,'time',SimpleNamespace(time_ns=lambda:NOW*1000000))
    monkeypatch.setattr(rt,'ReadOnlyReceipts',lambda transport,path:transport)
    clients=[]
    def public_fixture(*_,**__):clients.append(True);return c.live.client
    def forbidden(*_,**__):raise AssertionError('NO_KEY_OR_SIGNER_ON_FAILED_PREFLIGHT')
    monkeypatch.setattr(rt,'HyperliquidClient',public_fixture)
    monkeypatch.setattr(rt,'read_api_key',forbidden)
    monkeypatch.setattr(rt,'api_signer',forbidden)
    market(c,D(p.maximum_ask)+1)
    with pytest.raises(ExchangeError,match='OUTSIDE_APPROVED_CORRIDOR'):
        rt.build_native_qualification(tmp_path,p,a,test_receipt=tmp_path/'unused',output=tmp_path/'first')
    with sqlite3.connect(state/'qualification.sqlite') as db:
        row=db.execute('SELECT value FROM controls WHERE name=?',('native_qualification_invocation:'+p.identity,)).fetchone()
        assert json.loads(row[0])['status']=='PREFLIGHT_STOPPED'
        assert db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]==0
    with pytest.raises(ExchangeError,match='INVOCATION_ALREADY_CONSUMED'):
        rt.build_native_qualification(tmp_path,p,a,test_receipt=tmp_path/'unused',output=tmp_path/'second')
    assert clients==[True] and not c.venue.calls and not c.live.transport.signed_payloads
    assert not (state/'nonces.sqlite').exists()
