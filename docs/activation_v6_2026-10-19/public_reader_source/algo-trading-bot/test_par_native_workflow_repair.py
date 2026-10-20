"""Synthetic practice-only regressions; no actual keys, HTTP or venue certification."""
from dataclasses import asdict,replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import importlib.util,json,hashlib,sqlite3
import pytest
from exchange.base_exchange import ExchangeError
from exchange.native_qualification_runtime import NativeQualificationRuntime
from exchange.native_qualification import NativeQualificationTransport
from test_native_qualification import native,live,synthetic_trigger
from test_qualification_protection import stop,cert,submit_stop,trigger
from test_exchange_migration import NOW,TEAM

ROOT=Path(__file__).resolve().parents[1]


def export_fixture(tmp_path):
    """Complete SYNTHETIC raw chain, local temp files only, no exchange contact."""
    team=TEAM;symbol='par:BTC';rows=[]
    def add(kind,response,at,**params):
        rows.append(dict(request=dict(type=kind,user=team,**params),response=response,received_ms=at))
    fills=[dict(coin=symbol,tid=1,oid=10,side='B',sz='.0002',px='81000',fee='.01',feeToken='USDPR',closedPnl='0',time=100),
           dict(coin=symbol,tid=2,oid=12,side='A',sz='.0002',px='80000',fee='.01',feeToken='USDPR',closedPnl='-.2',time=200)]
    add('userFillsByTime',fills,210)
    add('userFunding',[],211)
    detail=dict(coin=symbol,oid=11,side='A',isTrigger=True,reduceOnly=True,orderType='Stop Limit',origSz='.0002',limitPx='80000',children=[dict(oid=12)])
    add('orderStatus',dict(status='order',order=dict(order=detail,status='triggered')),220,oid=11)
    for at in [230,240]:
        add('clearinghouseState',dict(assetPositions=[]),at,dex='par')
        add('frontendOpenOrders',[],at+1,dex='par')
    raw=tmp_path/'info_receipts.jsonl';raw.write_text(''.join(json.dumps(x)+'\n' for x in rows))
    p=SimpleNamespace(team_wallet=team,api_wallet='0x'+'2'*40,source_hash='a'*64,symbol=symbol,quantity='.0002')
    seq=SimpleNamespace(p=p,prefix='synthetic:',stop_observation=dict(order_id='11',child_order_ids=['12']),
        e=SimpleNamespace(account=SimpleNamespace(_query=lambda *a,**k:None),recovery=SimpleNamespace(state=SimpleNamespace(fills={
            2:SimpleNamespace(symbol=symbol,side='SELL',order_id='12')}))))
    rt=NativeQualificationRuntime.__new__(NativeQualificationRuntime);rt.sequence=seq;rt.output=tmp_path
    rt.journal=SimpleNamespace(intent=lambda key:dict(oid='10'))
    return rt


def test_native_proof_export_supplies_explicit_practice_venue(tmp_path):
    rt=export_fixture(tmp_path);result=dict(native_protection_qualified=False)
    rt.export_native_proof(result)
    assert result['native_protection_qualified'],result
    proof=json.loads((tmp_path/'NATIVE_PROTECTION_PROOF.json').read_text())
    assert proof['dex']=='par' and proof['markets']['par:BTC']['closing_order_id']=='12'


@pytest.mark.parametrize('stage',['prepare','armed','rejected'])
def test_mark_valuation_movement_does_not_change_native_position_identity(stop,monkeypatch,stage):
    c=stop
    if stage=='armed':submit_stop(c)
    if stage=='rejected':c.venue.fail='protection_rejected'
    original=c.live.account.get_positions;count=0
    def positions():
        nonlocal count
        count+=1
        return {s:replace(p,unrealized_pnl=D(count),margin_used=p.margin_used+D(count)/100) for s,p in original().items()}
    monkeypatch.setattr(c.live.account,'get_positions',positions)
    if stage=='prepare':assert c.manager.prepare().quantity==D(c.proposal.quantity)
    elif stage=='armed':assert c.manager.reconcile()['status']=='READBACK_ACCEPTED'
    else:assert c.manager.submit(c.stop_key)['status']=='REJECTED'


def test_linked_fill_below_approved_stop_limit_cannot_settle_or_qualify(stop):
    c=stop;submit_stop(c);trigger(c,quantity=c.proposal.quantity,child_state='filled')
    c.live.fixture.fills[-1]['px']=str(D(c.proposal.stop_limit)-1)
    result=c.manager.reconcile()
    assert result['status']=='UNKNOWN' and not result['protection_verified'],result
    assert 'FILL_PRICE' in result['reason']


def test_position_tpsl_readback_does_not_qualify_fixed_size_native_wire(stop):
    c=stop;submit_stop(c);row=c.live.journal.intent(c.stop_key)
    c.venue.statuses[row['cloid']]['order']['order']['isPositionTpsl']=True
    assert c.manager.reconcile()['status']=='UNKNOWN'


def permission_record(tmp_path,starts,ends):
    raw=tmp_path/'original.txt';raw.write_text('OFFLINE synthetic organizer fixture; no actual permission')
    record=dict(network='testnet',dex='par',symbol='par:BTC',team_wallet=TEAM,
        supervised_native_qualification=True,operator_reviewed_provenance=True,source_reference='OFFLINE_FIXTURE',
        original_record_file=raw.name,original_record_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        starts_ms=starts,expires_ms=ends)
    path=tmp_path/'permission.json';path.write_text(json.dumps(record));return path,raw


def test_practice_permission_does_not_reuse_scored_window():
    from exchange.native_qualification_permissions import practice_permission
    from exchange.competition_windows import ms
    with pytest.raises(ExchangeError,match='ORGANIZER_PRACTICE'):
        practice_permission(TEAM,ms('2026-10-19T18:00:00'),ms('2026-10-19T18:05:00'))
    valid=practice_permission(TEAM,ms('2026-10-15T18:00:00'),ms('2026-10-15T18:05:00'))
    assert not valid['files'] and valid['basis'].startswith('PUBLISHED_PRACTICE')


@pytest.mark.parametrize('damage',['none','team','dex','symbol','purpose','review','source','interval','raw_hash','symlink'])
def test_weekend_permission_requires_exact_original_record(tmp_path,damage):
    from exchange.native_qualification_permissions import practice_permission,require_bound_permission
    from exchange.competition_windows import ms
    start=ms('2026-10-18T18:00:00');end=start+300000
    p,raw=permission_record(tmp_path,start,end);r=json.loads(p.read_text())
    fields={'team':('team_wallet','0x'+'3'*40),'dex':('dex','pas'),'symbol':('symbol','par:ETH'),
        'purpose':('supervised_native_qualification',False),'review':('operator_reviewed_provenance',False),
        'source':('source_reference',''),'interval':('expires_ms',end-1),'raw_hash':('original_record_sha256','a'*64)}
    if damage in fields:r[fields[damage][0]]=fields[damage][1]
    if damage=='symlink':
        outside=tmp_path.parent/(tmp_path.name+'-outside.txt');outside.write_text('outside')
        raw.unlink();raw.symlink_to(outside);r['original_record_sha256']=hashlib.sha256(outside.read_bytes()).hexdigest()
    p.write_text(json.dumps(r))
    if damage=='none':
        binding=practice_permission(TEAM,start,end,path=p);require_bound_permission(binding,start)
        assert len(binding['files'])==2
    else:
        with pytest.raises(ExchangeError):practice_permission(TEAM,start,end,path=p)


@pytest.mark.parametrize('change',['expired','deleted','changed'])
def test_organizer_permission_cannot_change_or_renew_during_native_authority(tmp_path,change):
    from exchange.native_qualification_permissions import practice_permission,require_bound_permission
    p,raw=permission_record(tmp_path,NOW,NOW+300000)
    binding=practice_permission(TEAM,NOW,NOW+300000,path=p)
    at=NOW
    if change=='expired':at=NOW+300000
    elif change=='deleted':raw.unlink()
    else:raw.write_text('modified')
    with pytest.raises(ExchangeError,match='EXPIRED_OR_CHANGED'):require_bound_permission(binding,at)


def make_journal(tmp_path,state='UNKNOWN',*,remainder=False):
    from exchange.execution_journal import ExecutionJournal
    from exchange.order_lifecycle import OrderRequest
    path=tmp_path/'qualification.sqlite'
    j=ExecutionJournal(path,session_id='offline:par-repair',team_address=TEAM)
    req=OrderRequest('par:BTC','BUY','.0002','81000',tif='Ioc')
    row,_=j.reserve('original-newer',asdict(req),'candidate',NOW)
    j.update('original-newer',state,NOW,outcome=dict(remainder_cancelled=remainder))
    j.close();return path


@pytest.mark.parametrize('state,settled,blocked',[('UNKNOWN',False,True),('PREPARED',False,True),
 ('SUBMITTED',False,True),('OPEN',False,True),('PARTIALLY_FILLED',False,True),
 ('PARTIALLY_FILLED',True,False),('FILLED',False,False),('REJECTED',False,False)])
def test_real_prior_qualification_snapshot_is_read_only_and_keeps_unknown(tmp_path,state,settled,blocked):
    from exchange.native_qualification_runtime import prior_qualification_state
    path=make_journal(tmp_path,state,remainder=settled)
    with sqlite3.connect(path) as db:before='\n'.join(db.iterdump())
    result=prior_qualification_state(tmp_path)
    with sqlite3.connect(path) as db:after='\n'.join(db.iterdump())
    assert before==after
    assert bool(result['unresolved']) is blocked
    if blocked:assert result['status']=='PRIOR_QUALIFICATION_UNRESOLVED_REVIEW_REQUIRED'


def test_corrupt_prior_checkpoint_blocks_before_any_signer(tmp_path):
    from exchange.native_qualification_runtime import prior_qualification_state
    path=make_journal(tmp_path,'FILLED')
    with sqlite3.connect(path) as db:db.execute('INSERT INTO recovery_snapshots(data,checksum) VALUES (?,?)',('{}','wrong'))
    r=prior_qualification_state(tmp_path)
    assert r['status']=='PRIOR_QUALIFICATION_EVIDENCE_REVIEW_REQUIRED' and 'CHECKPOINT' in r['error']


def test_builder_unknown_barrier_precedes_client_key_and_nonce(native,tmp_path,monkeypatch):
    import exchange.native_qualification_runtime as rt
    c=native;state=tmp_path/'runtime/testnet/anchorium-bot-1';state.mkdir(parents=True)
    path=make_journal(state)
    monkeypatch.setattr(rt,'require_qualification_regression',lambda *a:None)
    def forbidden(*a,**k):pytest.fail('UNKNOWN barrier did not precede client/key')
    monkeypatch.setattr(rt,'HyperliquidClient',forbidden);monkeypatch.setattr(rt,'read_api_key',forbidden)
    with pytest.raises(ExchangeError,match='PRIOR_QUALIFICATION_UNRESOLVED'):
        rt.build_native_qualification(tmp_path,c.p,c.a,test_receipt='unused',output=tmp_path)
    assert not (state/'nonces.sqlite').exists()


def load_prepare():
    import os
    from unittest.mock import patch
    spec=importlib.util.spec_from_file_location('par_native_cli_fixture',ROOT/'scripts/run_native_qualification.py')
    mod=importlib.util.module_from_spec(spec)
    with patch.dict(os.environ,{}):spec.loader.exec_module(mod)
    return mod


def test_bad_release_still_produces_concrete_unsigned_preparation_report(tmp_path,monkeypatch):
    m=load_prepare()
    def invalid(*a):raise ExchangeError('SOURCE_BOUND_FULL_REGRESSION_REQUIRED')
    monkeypatch.setattr(m,'require_qualification_regression',invalid)
    def forbidden(*a,**k):pytest.fail('No public request is needed for a bad release')
    monkeypatch.setattr(m,'HyperliquidClient',forbidden)
    r=m.prepare(tmp_path,tmp_path/'absent')
    assert r['status']=='PREFLIGHT_BLOCKED' and r['blocker']=='SOURCE_BOUND_FULL_REGRESSION_REQUIRED'
    assert (tmp_path/'preparation.json').exists() and not (tmp_path/'proposal.json').exists()
    assert r['signatures']==r['orders_submitted']==0 and r['signing_authority']=='NONE'


@pytest.mark.parametrize('damage',['no_trigger','missing_fill','no_second_flat','wrong_currency'])
def test_native_raw_export_never_promotes_incomplete_or_mismatched_chain(tmp_path,damage):
    rt=export_fixture(tmp_path);raw=tmp_path/'info_receipts.jsonl'
    rows=[json.loads(x) for x in raw.read_text().splitlines()]
    if damage=='no_trigger':rows[2]['response']['order']['status']='open'
    elif damage=='missing_fill':rows[0]['response'].pop()
    elif damage=='no_second_flat':rows=rows[:-2]
    else:rows[0]['response'][1]['feeToken']='USDP'
    raw.write_text(''.join(json.dumps(x)+'\n' for x in rows))
    result=dict(native_protection_qualified=False);rt.export_native_proof(result)
    assert not result['native_protection_qualified'] and 'native_proof_error' in result
    assert not (tmp_path/'NATIVE_PROTECTION_PROOF.json').exists()


def test_pre_http_causal_audit_binds_actual_source_nonce_action_and_does_not_clear_unknown(native):
    from exchange.execution_journal import fingerprint
    from exchange.order_lifecycle import OrderRequest
    c=native;j=c.live.journal
    req=OrderRequest('par:BTC','BUY','.0002',c.p.entry_limit,tif='Ioc')
    row,_=j.reserve('new-durable',asdict(req),'candidate',NOW);j.update('new-durable','UNKNOWN',NOW)
    t=NativeQualificationTransport.__new__(NativeQualificationTransport);t.client=c.live.client;t.authorization=c.auth
    t.authorization.source_hash=lambda:'b'*64
    payload=dict(action=dict(type='order',orders=[dict(c=row['cloid'])]),nonce=NOW,expiresAfter=NOW+300000)
    t.record_transport_boundary('PRE_HTTP_REJECTED',payload,error_type='ExchangeError',reason='EXACT_FAILURE')
    record=json.loads(j.db.execute("SELECT data FROM events WHERE kind='QUALIFICATION_TRANSPORT_BOUNDARY' ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert record['working_source_hash']=='b'*64 and record['configuration_hash']==c.p.identity
    assert record['nonce']==NOW and record['action_hash']==fingerprint(payload['action'])
    assert record['reason']=='EXACT_FAILURE' and not any(k in record for k in ['signature','payload','private_key'])
    assert j.intent('new-durable')['state']=='UNKNOWN'
    assert j.db.execute("SELECT COUNT(*) FROM intent_audit WHERE stage='PRE_HTTP_REJECTED'").fetchone()[0]==1
    assert not c.venue.calls


def test_unknown_management_action_is_also_a_read_only_barrier(tmp_path):
    from exchange.native_qualification_runtime import prior_qualification_state
    path=make_journal(tmp_path,'FILLED')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO signed_management(fingerprint,action,state,created_ms,updated_ms) VALUES ('hash','{}','UNKNOWN',?,?)",(NOW,NOW))
    r=prior_qualification_state(tmp_path)
    assert r['status']=='PRIOR_QUALIFICATION_UNRESOLVED_REVIEW_REQUIRED'
    assert r['unresolved'][0]['management_id']==1


def test_preparation_reports_exact_configuration_blocker_without_public_reads(tmp_path,monkeypatch):
    from venue_config import MigrationPolicyError
    m=load_prepare()
    def blocked():raise MigrationPolicyError('MIGRATION_LIVE_ORDERS_MUST_BE_FALSE')
    monkeypatch.setattr('venue_config.require_paper_migration',blocked)
    r=m.prepare(tmp_path,'unused')
    assert r['blocker']=='MIGRATION_LIVE_ORDERS_MUST_BE_FALSE'
    assert not (tmp_path/'proposal.json').exists()


def test_preparation_also_exposes_consumed_native_invocation_without_reset(tmp_path):
    from exchange.native_qualification_runtime import prior_qualification_state
    path=make_journal(tmp_path,'FILLED')
    with sqlite3.connect(path) as db:db.execute("INSERT INTO controls VALUES ('native_qualification_attempted','true')")
    r=prior_qualification_state(tmp_path)
    assert r['native_attempt_consumed'] and r['status']=='NATIVE_QUALIFICATION_RESTART_REQUIRES_READ_ONLY_REVIEW'
    with sqlite3.connect(path) as db:assert db.execute("SELECT value FROM controls WHERE name='native_qualification_attempted'").fetchone()[0]=='true'
