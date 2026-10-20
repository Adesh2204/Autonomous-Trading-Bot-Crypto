"""Versioned bounded pricing, real executor/SDK composition, ephemeral fixtures.

Every HTTP exchange call is forbidden by the live fixture. Unit outcomes never
prove an actual team fill, protection acceptance or committee qualification.
"""
from copy import deepcopy
from dataclasses import asdict,replace
from decimal import Decimal as D
import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from exchange.base_exchange import ExchangeError,BookLevel
from exchange.order_lifecycle import OrderRequest,OrderState
from exchange.execution_journal import fingerprint
from exchange.emergency_qualification import (EmergencyProposal,EmergencyApproval,EmergencyComplianceScope,
    EmergencySequence,BOUNDED_PRICE,FIXED_PRICE,BOUNDED_POLICY,ENVELOPE_FIELDS,RULE,
    calculate_bounded_entry,entry_price_diagnostics,check_entry,propose,permission,policy_hash)
from test_emergency_qualification import emergency
from test_live_exchange_execution import live,response
from test_exchange_migration import NOW


@pytest.fixture
def bounded(emergency):
    c=emergency
    p,_=propose(c.context,c.live.client,'fixture-source','fixture-policy',c.live.provider.last_book,
        tif='Ioc',candidate_hash='synthetic-genuine-l2',price_mode=BOUNDED_PRICE)
    c.p=p;c.a=replace(c.a,proposal_hash=p.identity,qualification_policy_hash=policy_hash(p),
        bounded_price_authorization_accepted=True)
    c.auth.proposal=p;c.auth.approval=c.a
    c.live.executor.proposal=p
    c.live.executor.compliance_guard.qualification_scope=EmergencyComplianceScope(p,c.live.provider)
    c.sequence=EmergencySequence(c.live.executor,p,c.auth)
    return c


def moved(c,bid,ask,*,now=NOW,mark=None,oracle=None):
    bid,ask=D(bid),D(ask);old=c.live.provider.last_book
    book=replace(old,timestamp_ms=now,bids=(BookLevel(bid,D('.1')),BookLevel(bid-50,D('.2'))),
        asks=(BookLevel(ask,D('.006')),BookLevel(ask+50,D('.02'))))
    quote=replace(c.context.quote,bid=bid,ask=ask,mid=(bid+ask)/2,
        mark=D(mark) if mark else c.context.quote.mark,oracle=D(oracle) if oracle else c.context.quote.oracle,
        timestamp_ms=now,mark_timestamp_ms=now)
    ctx=replace(c.context,quote=quote,account_ms=now,
                readiness=replace(c.context.readiness,observed_ms=now))
    return ctx,book


def move_venue(c,bid,ask):
    c.live.fixture.book['levels']=[[dict(px=str(bid),sz='.1'),dict(px=str(D(bid)-50),sz='.2')],
        [dict(px=str(ask),sz='.006'),dict(px=str(D(ask)+50),sz='.02')]]


def draft(c):
    return OrderRequest(c.p.symbol,'BUY',c.p.quantity,c.p.entry_limit,tif='Ioc',
        strategy_id='TESTNET_CERTIFICATION_ENTRY',client_order_id=c.sequence.prefix+'entry')


def test_legacy_identity_is_preserved_byte_for_byte(emergency):
    c=emergency;raw=asdict(c.p)
    for field in ENVELOPE_FIELDS:raw.pop(field)
    assert fingerprint(raw)==c.p.identity
    assert policy_hash(c.p)==policy_hash() and c.p.price_authorization_mode==FIXED_PRICE


def test_old_approval_cannot_authorize_new_bounded_semantics(bounded):
    c=bounded;c.auth.approval=replace(c.a,bounded_price_authorization_accepted=False)
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


@pytest.mark.parametrize('field,value',[('max_buy_price','83607'),('quantity_ceiling','.0003'),
    ('entry_notional_ceiling','1000'),('entry_rule','old-rule'),('mode','TESTNET_QUALIFICATION_P0_1000_V1'),
    ('qualification_policy_hash','old-hash'),('entry_tif','Gtc'),('price_authorization_mode','OTHER')])
def test_envelope_schema_tampering_rejected(bounded,field,value):
    with pytest.raises(ExchangeError):replace(bounded.p,**{field:value}).require()


@pytest.mark.parametrize('bid,ask',[('83380','83420'),('83400','83440'),('83440','83470'),('83560','83600')])
def test_moving_ask_both_directions_selects_only_inside_approved_envelope(bounded,bid,ask):
    c=bounded;ctx,book=moved(c,bid,ask)
    req=calculate_bounded_entry(ctx,c.p,NOW,book)
    assert D(ask)<=req.price<=ctx.spec.normalize_price(D(ask)*D('1.002'),'BUY')
    assert req.price<=D(c.p.max_buy_price) and req.quantity==D('.0002')
    assert req.quantity*req.price<=D(c.p.entry_notional_ceiling)
    assert ctx.spec.normalize_price(req.price,'BUY')==req.price
    assert c.p.identity==c.auth.approval.proposal_hash


def test_exact_old_rejection_now_allows_fresh_lower_price_but_not_old_repricing(bounded):
    old=bounded;legacy=replace(old.p,price_authorization_mode=FIXED_PRICE,max_buy_price=None,
        quantity_ceiling=None,entry_notional_ceiling=None,mode='TESTNET_QUALIFICATION_P0_1000_V1',
        entry_rule=RULE,qualification_policy_hash=policy_hash())
    ctx,book=moved(old,'83380','83420')
    with pytest.raises(ExchangeError,match='P0_CURRENT_PRICE_OR_CAP_REQUIRED'):
        check_entry(ctx,draft(old),legacy,NOW,book,journal=old.live.journal,stage='LEGACY_FIXED_REPRODUCTION')
    rows=[json.loads(r['data']) for r in old.live.journal.db.execute("SELECT data FROM events WHERE kind='P0_ENTRY_PRICE_GUARD'")]
    assert rows[-1]['rejected_conditions']==['limit_above_current_20bps']
    assert rows[-1]['proposed_limit']==old.p.entry_limit
    assert 'ask' in rows[-1] and rows[-1]['stage']=='LEGACY_FIXED_REPRODUCTION'
    c=bounded;ctx,book=moved(c,'83380','83420')
    req=calculate_bounded_entry(ctx,c.p,NOW,book)
    assert req.price<D(c.p.entry_limit)


@pytest.mark.parametrize('ask',['83607','83650'])
def test_ask_above_approved_cap_remains_blocked_without_upsizing(bounded,ask):
    c=bounded;ctx,book=moved(c,str(D(ask)-30),ask)
    with pytest.raises(ExchangeError):calculate_bounded_entry(ctx,c.p,NOW,book)
    assert not c.venue.calls and D(c.p.quantity)==D('.0002')


@pytest.mark.parametrize('price',['83607','90000'])
def test_final_validator_blocks_above_approved_price_and_selected_notional(bounded,price):
    c=bounded;ctx,book=moved(c,'83400','83440')
    req=replace(draft(c),price=D(price))
    with pytest.raises(ExchangeError):check_entry(ctx,req,c.p,NOW,book,journal=c.live.journal)
    last=json.loads(c.live.journal.db.execute("SELECT data FROM events WHERE kind='P0_ENTRY_PRICE_GUARD' ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert 'above_approved_max_buy' in last['rejected_conditions']
    assert 'above_approved_order_or_mark_notional' in last['rejected_conditions']


def test_mark_notional_ceiling_independent_of_chosen_limit(bounded):
    c=bounded;ctx,book=moved(c,'83400','83440',mark='83607',oracle='83607')
    with pytest.raises(ExchangeError,match='APPROVED_ENVELOPE'):
        calculate_bounded_entry(ctx,c.p,NOW,book)


@pytest.mark.parametrize('qty',['.0001','.0003','.00025'])
def test_fixed_quantity_cannot_shrink_or_expand(bounded,qty):
    c=bounded;ctx,book=moved(c,'83400','83440')
    with pytest.raises(ExchangeError):check_entry(ctx,replace(draft(c),quantity=D(qty)),c.p,NOW,book)
    assert not c.venue.calls


@pytest.mark.parametrize('bid,ask',[('83000','83440'),('83440','83440'),('83450','83440')])
def test_spread_crossed_and_empty_executable_conditions_are_still_enforced(bounded,bid,ask):
    c=bounded
    if D(bid)>D(ask):
        with pytest.raises(ExchangeError):moved(c,bid,ask)
    elif D(bid)==D(ask):
        ctx,book=moved(c,bid,ask)
        with pytest.raises(ExchangeError,match='TWO_SIDED'):calculate_bounded_entry(ctx,c.p,NOW,book)
    else:
        ctx,book=moved(c,bid,ask)
        with pytest.raises(ExchangeError,match='SPREAD'):calculate_bounded_entry(ctx,c.p,NOW,book)


@pytest.mark.parametrize('which',['entry','exit'])
def test_actual_depth_at_selected_limit_required(bounded,which):
    c=bounded;ctx,book=moved(c,'83400','83440')
    levels=(BookLevel(D('83440') if which=='entry' else D('83400'),D('.0001')),)
    book=replace(book,asks=levels) if which=='entry' else replace(book,bids=levels)
    with pytest.raises(ExchangeError):calculate_bounded_entry(ctx,c.p,NOW,book)


@pytest.mark.parametrize('field',['timestamp_ms','mark_timestamp_ms','account_ms','readiness'])
def test_stale_inputs_cannot_select_or_sign(bounded,field):
    c=bounded;ctx,book=moved(c,'83400','83440')
    if field in {'timestamp_ms','mark_timestamp_ms'}:
        ctx=replace(ctx,quote=replace(ctx.quote,**{field:NOW-5001}))
        if field=='timestamp_ms':book=replace(book,timestamp_ms=NOW-5001)
    elif field=='readiness':ctx=replace(ctx,readiness=replace(ctx.readiness,observed_ms=NOW-5001))
    else:ctx=replace(ctx,account_ms=NOW-5001)
    with pytest.raises(ExchangeError):calculate_bounded_entry(ctx,c.p,NOW,book)


@pytest.mark.parametrize('offset',[210001,300000,300001])
def test_entry_time_reserve_and_expiry_cannot_be_repaired_by_pricing(bounded,offset):
    c=bounded;ctx,book=moved(c,'83400','83440',now=NOW+offset)
    with pytest.raises(ExchangeError,match='WINDOW_CLOSED'):
        calculate_bounded_entry(ctx,c.p,NOW+offset,book)


@pytest.mark.parametrize('failure',['approved_ms','expires_ms','source','policy'])
def test_actual_authorization_time_source_and_policy_still_required(bounded,failure):
    c=bounded
    if failure=='approved_ms':c.auth.approval=replace(c.a,approved_ms=NOW+1)
    if failure=='expires_ms':c.auth.approval=replace(c.a,expires_ms=NOW)
    if failure=='source':c.auth.source_hash=lambda:'changed-source'
    if failure=='policy':c.auth.policy_hash=lambda:'changed-policy'
    assert c.sequence.run()['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


@pytest.mark.parametrize('change',['cap','quantity'])
def test_precision_not_silently_rounded_in_approval_envelope(bounded,change):
    c=bounded
    values=({'entry_limit':'83606.5','max_buy_price':'83606.5','entry_notional_ceiling':str(D('.0002')*D('83606.5'))}
        if change=='cap' else {'quantity':'.00025','quantity_ceiling':'.00025','entry_notional_ceiling':str(D('.00025')*D(c.p.max_buy_price))})
    p=replace(c.p,**values).require();ctx,book=moved(c,'83400','83440')
    with pytest.raises(ExchangeError,match='PRECISION'):calculate_bounded_entry(ctx,p,NOW,book)


@pytest.mark.parametrize('price,quantity,reduce,tif',[('83607','.0002',False,'Ioc'),
    ('83523','.0003',False,'Ioc'),('1','.0002',False,'Ioc'),('83523','.0002',False,'Gtc'),
    ('83523','.0002',True,'Ioc')])
def test_signed_action_envelope_and_direction_not_just_proposal_schema(bounded,price,quantity,reduce,tif):
    c=bounded;req=draft(c)
    row,_=c.live.journal.reserve(req.client_order_id,asdict(req),'certification:'+c.p.identity,NOW)
    wire,action=c.live.transport.order_action(replace(req,price=D(price),quantity=D(quantity),reduce_only=reduce,tif=tif),row['cloid'])
    with pytest.raises(ExchangeError):c.auth.check_action(action)
    assert not c.live.transport.signed_payloads


@pytest.mark.parametrize('bid,ask',[('83380','83420'),('83440','83470'),('83560','83600')])
def test_real_runtime_and_ephemeral_sdk_uses_new_selected_price(bounded,monkeypatch,bid,ask):
    c=bounded;move_venue(c,bid,ask);original=c.live.transport.perform
    def perform(*args,**kwargs):
        try:return original(*args,**kwargs)
        except ExchangeError as exc:
            c.transport_error=str(exc);raise
    monkeypatch.setattr(c.live.transport,'perform',perform)
    r=c.sequence.run()
    assert r['status']=='TRADE_CLOSED_RECONCILED',json.dumps(dict(status=r['status'],error=r.get('error'),
        transport_error=getattr(c,'transport_error',None),calls=c.venue.calls,intents=c.live.journal.intents(),events=[dict(x) for x in c.live.journal.db.execute(
        "SELECT kind,data FROM events WHERE kind IN ('P0_ENTRY_PRICE_GUARD','COMPLIANCE_SIGNING_BLOCK','PROTECTION_UNCERTAIN','AMBIGUOUS_ORDER_RESULT','EXCHANGE_ORDER_RESULT')")]),default=str)
    actual=D(c.venue.calls[0]['orders'][0]['p'])
    assert actual==min(c.context.spec.normalize_price(D(ask)*D('1.001'),'BUY'),D(c.p.max_buy_price))
    assert actual<=D(c.p.max_buy_price) and D(c.venue.calls[0]['orders'][0]['s'])==D('.0002')
    assert r['final_flat'] and not r['protection_accepted'] and not r['certification_passed']


@pytest.mark.parametrize('fraction',['0','.5','1'])
def test_new_mode_zero_partial_full_entry_closes_only_actual_exposure(bounded,fraction):
    c=bounded;c.venue.partial_entry=D(fraction);r=c.sequence.run()
    assert r['status']==('NO_FILL_VERIFIED' if fraction=='0' else 'TRADE_CLOSED_RECONCILED'),r
    entries=[a for a in c.venue.calls if not a['orders'][0]['r']]
    assert len(entries)==1 and r['final_flat']
    if fraction!='0':assert D(c.venue.calls[-1]['orders'][0]['s'])==D('.0002')*D(fraction)


@pytest.mark.parametrize('failure',['entry_rejected','timeout_before','timeout_after_fill','disconnect_after_fill'])
def test_new_mode_rejection_uncertainty_never_reprices_a_second_order(bounded,failure):
    c=bounded;c.venue.fail=failure;r=c.sequence.run()
    assert len([a for a in c.venue.calls if a['type']=='order' and not a['orders'][0]['r']])==1
    assert r['status']=={'entry_rejected':'NO_FILL_VERIFIED','timeout_after_fill':'TRADE_CLOSED_RECONCILED'}.get(failure,'EMERGENCY_EXIT_REQUIRED'),r


def test_rejected_exit_preserves_residual_and_attempt_bound(bounded,monkeypatch):
    c=bounded;original=c.venue.transmit
    def transmit(payload):
        if payload['action']['orders'][0]['r']:
            c.auth.claim_transmission(payload['action']);c.venue.calls.append(deepcopy(payload['action']))
            return response({'error':'Order must have minimum value of $10.'})
        return original(payload)
    monkeypatch.setattr(c.live.transport,'transmit',transmit)
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and c.live.account.get_position(c.p.symbol)
    assert len(c.venue.calls)==3 and not r.get('final_flat',False)


def test_duplicate_returns_original_durable_price_not_new_quote(bounded):
    c=bounded;c.live.executor.entries_paused=False;req=draft(c)
    first=c.live.executor.submit(req,permission=permission(req,c.p,NOW))
    count=len(c.venue.calls);move_venue(c,'83380','83420')
    second=c.live.executor.submit(req,permission=permission(req,c.p,NOW))
    assert second.cloid==first.cloid and second.request.price==first.request.price
    assert len(c.venue.calls)==count


def test_final_signing_validator_checks_actual_selected_wire_price(bounded):
    c=bounded;ctx,book=moved(c,'83400','83440');selected=calculate_bounded_entry(ctx,c.p,NOW,book)
    assert selected.price<D(c.p.entry_limit)
    c.live.executor.entries_paused=False
    c.live.executor._guard(ctx,NOW,entry=True,entry_request=selected)
    # A rapid additional fall outside the selected price's live 20-bps range is
    # still a legitimate stop. The signed wire is never edited after validation.
    move_venue(c,'83270','83300')
    with pytest.raises(ExchangeError,match='P0_CURRENT_PRICE_OR_CAP_REQUIRED'):
        c.live.executor._guard(ctx,NOW,entry=True,entry_request=selected)
    assert not c.venue.calls


def test_diagnostics_complete_persistent_and_secret_free(bounded):
    c=bounded;ctx,book=moved(c,'83400','83440');req=calculate_bounded_entry(ctx,c.p,NOW,book,
        journal=c.live.journal,stage='READ_ONLY_DIAGNOSTIC_TEST')
    row=json.loads(c.live.journal.db.execute("SELECT data FROM events WHERE kind='P0_ENTRY_PRICE_GUARD' ORDER BY seq DESC LIMIT 1").fetchone()[0])
    for key in ('bid','ask','mark','oracle','proposed_limit','current_20bps_maximum','entry_tolerance_bps',
        'outer_notional_ceiling','approved_notional_ceiling','quote_ms','book_ms','mark_ms','account_ms',
        'evaluated_ms','conditions','rejected_conditions','configuration_hash'):
        assert key in row
    assert row['configuration_hash']==c.p.identity and row['allowed']
    assert not any(k in row for k in ('private_key','signer','signature','authorization'))


def test_full_round_trip_cannot_repeat_after_restart_or_completed_consumption(bounded):
    c=bounded;assert c.sequence.run()['status']=='TRADE_CLOSED_RECONCILED'
    count=len(c.venue.calls)
    assert EmergencySequence(c.live.executor,c.p,c.auth).run()['status']=='PREFLIGHT_BLOCKED'
    assert len(c.venue.calls)==count


def launcher(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('isolated_price_guard_launcher',root/'scripts/run_emergency_qualification.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_new_approval_template_requires_explicit_bounded_price_ack(bounded,monkeypatch):
    module=launcher(monkeypatch);template=module.approval_template(bounded.p)
    assert template['bounded_price_authorization_accepted'] is False
    assert template['qualification_policy_hash']==policy_hash(bounded.p)!=policy_hash()
    assert template['approved_ms'] is None and template['expires_ms'] is None and template['operator_approval']==''


def test_legacy_template_keeps_original_eight_acknowledgments(emergency,monkeypatch):
    template=launcher(monkeypatch).approval_template(emergency.p)
    assert 'bounded_price_authorization_accepted' not in template
    assert len([k for k,v in template.items() if v is False])==8


def test_handoff_exposes_envelope_not_unlimited_repricing(bounded,monkeypatch,tmp_path):
    handoff=launcher(monkeypatch).handoff(bounded.p,tmp_path,tmp_path/'receipt.json')
    assert handoff['max_buy_price']==bounded.p.max_buy_price
    assert handoff['quantity_ceiling']==bounded.p.quantity
    assert handoff['entry_notional_ceiling']==bounded.p.entry_notional_ceiling
    assert '10 bps' in handoff['execution_price_rule'] and '20 bps' in handoff['execution_price_rule']
    assert not handoff['protection_verified'] and handoff['no_stop_will_be_submitted']


def test_diagnostic_export_survives_failed_preflight(bounded,monkeypatch,tmp_path):
    c=bounded;ctx,book=moved(c,'83380','83420')
    with pytest.raises(ExchangeError):check_entry(ctx,draft(c),c.p,NOW,book,journal=c.live.journal,stage='BUILD_RUNTIME_FRESH_PREFLIGHT')
    module=launcher(monkeypatch);monkeypatch.setattr(module,'ROOT',tmp_path)
    destination=tmp_path/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
    destination.parent.mkdir(parents=True)
    import sqlite3
    db=sqlite3.connect(destination);c.live.journal.db.backup(db);db.close()
    module.persist_price_diagnostics(tmp_path,c.p)
    record=json.loads((tmp_path/'price_guard_diagnostics.json').read_text())
    assert record['proposal_id']==c.p.identity and len(record['observations'])==1
    assert record['observations'][0]['rejected_conditions']==['limit_above_current_20bps']


def test_no_fill_cli_writes_no_whitelist_proof(bounded,monkeypatch,tmp_path):
    module=launcher(monkeypatch);monkeypatch.setattr(module,'ROOT',tmp_path)
    (tmp_path/'proposal.json').write_text(json.dumps(asdict(bounded.p)))
    (tmp_path/'approval.json').write_text(json.dumps(asdict(bounded.a)))
    runtime=SimpleNamespace(run=lambda:dict(status='NO_FILL_VERIFIED',final_flat=True,
        whitelist_trade_proof=dict(fill_verified=False,evidence_scope='OFFLINE_FIXTURE')),
        close=lambda:None)
    calls=[]
    def build(*args,**kwargs):calls.append(1);return runtime
    monkeypatch.setattr(module,'build_runtime',build)
    monkeypatch.setattr(module.sys,'argv',['run_emergency_qualification.py','--execute','--output-directory',str(tmp_path/'result'),
        '--proposal-file',str(tmp_path/'proposal.json'),'--operator-approval-file',str(tmp_path/'approval.json'),
        '--test-receipt',str(tmp_path/'receipt.json')])
    assert module.main()==0 and calls==[1]
    assert (tmp_path/'result/NO_FILL_VERIFICATION.json').exists()
    assert not (tmp_path/'result/WHITELIST_TRADE_PROOF.json').exists()


def test_expired_published_fixed_proposal_identity_not_reinterpreted():
    root=Path(__file__).resolve().parents[1]
    path=root/'docs/qualification_operator_2026-10-14/preparation-20261014T051415Z/proposal.json'
    p=EmergencyProposal(**json.loads(path.read_text()))
    assert p.identity=='876707f1612b45525795ae76ad10caf2cd36f0fb1f1b17389fd9ae63e6b9f218'
    assert p.price_authorization_mode==FIXED_PRICE and p.max_buy_price is None


def test_market_drop_cannot_enlarge_quantity_to_restore_order_minimum(bounded):
    c=bounded;p=replace(c.p,quantity='.0001',quantity_ceiling='.0001',entry_limit='100010',
        max_buy_price='100010',entry_notional_ceiling='10.0010').require()
    ctx,book=moved(c,'83400','83440')
    with pytest.raises(ExchangeError):calculate_bounded_entry(ctx,p,NOW,book)
    assert p.quantity=='.0001' and not c.venue.calls


def test_runtime_asset_mapping_cannot_be_changed_by_price_mode(bounded):
    c=bounded;ctx,book=moved(c,'83400','83440')
    ctx=replace(ctx,spec=replace(ctx.spec,asset_id=2670001))
    with pytest.raises(ExchangeError,match='MAPPING'):calculate_bounded_entry(ctx,c.p,NOW,book)
    assert not c.venue.calls
