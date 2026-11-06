"""Post-funding policy tests. Synthetic evidence; never account certification."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
import json
import socket
import pytest
from exchange.base_exchange import ExchangeError
from exchange.execution_journal import fingerprint
from exchange import configuration_isolation as ci
from exchange.testnet_certification import TEAM, API
from exchange.pas_configuration_plan import configuration_plan
from exchange.pas_configuration import PasConfigurationApproval
from exchange.long_session import sha
from exchange.team_registration import registration_evidence
from test_scored_opening_release import configuration_observation
from test_pas_migration import isolated_pas_environment, pas, evidence_files
from test_pas_execution_faults import pas_bridge
from test_live_exchange_execution import permission

SOURCE='a'*64
NOW=ci.NONCE+172800000+1000000


def proof():
    p=dict(mode='ACTUAL_READ_ONLY_CONFIGURATION_ISOLATION_REVIEW',scope=ci.SCOPE,source_hash=SOURCE,
        source_hash_after=SOURCE,team_wallet=TEAM,api_wallet=API,original_cloid=ci.CLOID,original_nonce=ci.NONCE,
        historical_outcome='UNKNOWN',order_authority=False,signatures_created=0,exchange_writes=0,finished_ms=NOW,
        local=dict(row_hash=ci.ROW_HASH,invocation_hash=ci.INVOCATION_HASH,signer=API.lower(),
            nonce_high_water=ci.NONCE,nonce_integrity='ok',qualification_integrity='ok',
            qualification_dump_sha256='c'*64,consumed_marker_hash='d'*64,nonce_database='ORIGINAL_FIXTURE_ONLY'),
        funding=dict(status='USDP_POSITIVE_VERIFIED',account_mode='unifiedAccount',team_wallet=TEAM,
            dex='pas',collateral='USDP',balance='100000',token=3307,observed_ms=NOW-1),
        receipt_sha256=dict(par='e'*64,pas='f'*64),readbacks=[])
    for at in (NOW-1000,NOW-500):
        p['readbacks'].append(dict(observed_ms=at,original_order_status=dict(status='unknownOid'),
            venues={dex:dict(dex=dex,team_wallet=TEAM,positions_before=[],positions_after=[],open_orders=[],
                frontend_orders=[],exchange_time_ms=at-100) for dex in ('par','pas')}))
    return seal(p)


def seal(p):
    p.pop('proof_hash',None);p['proof_hash']=fingerprint(p);return p


def test_isolation_preserves_unknown_and_has_no_order_authority():
    p=proof();before=deepcopy(p);r=ci.assess(p,SOURCE,NOW)
    assert r['admissible'] and r['original_state']=='UNKNOWN' and r['order_authority'] is False and p==before


@pytest.mark.parametrize('fault',['source','mode','scope','cloid','nonce','outcome','authority','signature','write',
    'expired','future','nonce_rollback','nonce_owner','invocation','row','integrity','one_read','same_read',
    'missing_pas','known_order','position_before','position_after','open','frontend','pre_horizon','stale_clock',
    'funds_team','funds_zero','funds_nan','funds_stale','funds_currency','funds_mode','receipt'])
def test_isolation_rejects_unverified_or_changed_facts(fault):
    p=proof();r=p['readbacks'][0];v=r['venues']['par']
    if fault=='source':p['source_hash_after']='b'*64
    elif fault=='mode':p['mode']='OFFLINE_FIXTURE'
    elif fault=='scope':p['scope']='TRADING'
    elif fault=='cloid':p['original_cloid']='another'
    elif fault=='nonce':p['original_nonce']+=1
    elif fault=='outcome':p['historical_outcome']='RESOLVED'
    elif fault=='authority':p['order_authority']=True
    elif fault=='signature':p['signatures_created']=1
    elif fault=='write':p['exchange_writes']=1
    elif fault=='expired':p['finished_ms']=NOW-300001
    elif fault=='future':p['finished_ms']=NOW+1
    elif fault=='nonce_rollback':p['local']['nonce_high_water']=ci.NONCE-1
    elif fault=='nonce_owner':p['local']['signer']=TEAM.lower()
    elif fault=='invocation':p['local']['invocation_hash']='0'*64
    elif fault=='row':p['local']['row_hash']='0'*64
    elif fault=='integrity':p['local']['nonce_integrity']='bad'
    elif fault=='one_read':p['readbacks'].pop()
    elif fault=='same_read':p['readbacks'][1]=deepcopy(r)
    elif fault=='missing_pas':r['venues'].pop('pas')
    elif fault=='known_order':r['original_order_status']=dict(status='order',order={})
    elif fault=='position_before':v['positions_before']=[{}]
    elif fault=='position_after':v['positions_after']=[{}]
    elif fault=='open':v['open_orders']=[{}]
    elif fault=='frontend':v['frontend_orders']=[{}]
    elif fault=='pre_horizon':v['exchange_time_ms']=ci.NONCE+172800000
    elif fault=='stale_clock':v['exchange_time_ms']=r['observed_ms']-10001
    elif fault=='funds_team':p['funding']['team_wallet']=API
    elif fault=='funds_zero':p['funding']['balance']='0'
    elif fault=='funds_nan':p['funding']['balance']='NaN'
    elif fault=='funds_stale':p['funding']['observed_ms']=NOW-300001
    elif fault=='funds_currency':p['funding']['collateral']='USDPR'
    elif fault=='funds_mode':p['funding']['account_mode']='disabled'
    else:p['receipt_sha256']['par']='x'*64
    seal(p);assert not ci.assess(p,SOURCE,NOW)['admissible']


@pytest.mark.parametrize('field',['qualification_dump_sha256','consumed_marker_hash','nonce_database','row_hash'])
def test_local_snapshot_changes_cannot_be_isolated(monkeypatch,tmp_path,field):
    p=proof();current=deepcopy(p['local']);current[field]='changed'
    monkeypatch.setattr(ci,'local_evidence',lambda root:current)
    with pytest.raises(ExchangeError,match='ORIGINAL_EVIDENCE_CHANGED'):ci.verify_local(tmp_path,p,SOURCE,NOW)
    current=deepcopy(p['local']);current['nonce_high_water']+=1
    monkeypatch.setattr(ci,'local_evidence',lambda root:current)
    assert ci.verify_local(tmp_path,p,SOURCE,NOW)['admissible']


def observation():
    o=configuration_observation();o['finished_ms']=NOW;o['account']['reported_account_equity']['collateral_balance']='100000'
    o['local_execution_state']=dict(status='BLOCKED_UNRESOLVED_INTENT',unresolved=[dict(
        journal='qualification',cloid=ci.CLOID,state='UNKNOWN',intent_key=ci.INTENT)])
    o['registration_evidence']=dict(status='DIRECT_OPERATOR_CONFIRMED_ACCOUNT_IDENTITY')
    o['configuration_isolation']=proof();return o


def test_exact_plan_retains_human_approval_and_all_other_history_barriers():
    o=observation();p=configuration_plan(o)
    assert p['blockers']==['SEPARATE_EXACT_OPERATOR_CONFIGURATION_APPROVAL_REQUIRED']
    assert {c['symbol'] for c in p['changes']}=={'pas:BTC','pas:EWY','pas:HYPE'}
    assert all(c['requested_action']['type']=='updateLeverage' for c in p['changes'])
    assert p['signing_authority']=='NONE' and 'UNKNOWN_PRESERVED' in p['historical_disposition']
    o['local_execution_state']['unresolved'].append(dict(journal='pas',state='UNKNOWN'))
    with pytest.raises(ExchangeError):configuration_plan(o)


def test_capability_requires_exact_plan_real_approval_class_source_and_raw_receipts(monkeypatch,tmp_path):
    from exchange import paper_operations
    p=proof()
    for dex in ('par','pas'):
        path=tmp_path/(dex+'_info_receipts.jsonl');path.write_text('SYNTHETIC RECEIPT ONLY '+dex)
        p['receipt_sha256'][dex]=sha(path)
    seal(p);o=observation();o['configuration_isolation']=p;plan=configuration_plan(o)
    a=PasConfigurationApproval(plan['plan_hash'],SOURCE,'b'*64,NOW,NOW+900000,socket.gethostname(),
        'APPROVE PAS CONFIGURATION '+plan['plan_hash'],True,True)
    c=NS(dex='pas',clock_ms=lambda:NOW)
    monkeypatch.setattr(paper_operations,'active_source_hash',lambda root:SOURCE)
    monkeypatch.setattr(ci,'local_evidence',lambda root:deepcopy(p['local']))
    capability=ci.ConfigurationIsolation(tmp_path,p,a,plan,tmp_path)
    assert capability.exempt_intent(c)==ci.INTENT
    with pytest.raises(ExchangeError):replace(capability,approval=NS(require=lambda *a:None)).exempt_intent(c)
    changed=deepcopy(plan);changed['changes'][0]['requested_action']['leverage']=20
    with pytest.raises(ExchangeError):replace(capability,plan=changed).exempt_intent(c)
    monkeypatch.setattr(paper_operations,'active_source_hash',lambda root:'0'*64)
    with pytest.raises(ExchangeError):capability.exempt_intent(c)
    monkeypatch.setattr(paper_operations,'active_source_hash',lambda root:SOURCE)
    (tmp_path/'par_info_receipts.jsonl').write_text('changed')
    with pytest.raises(ExchangeError,match='RAW_RECEIPTS'):capability.exempt_intent(c)


def test_configuration_exception_cannot_be_combined_with_order_scope(monkeypatch,tmp_path):
    from exchange.scored_session import require_shared_scope
    from exchange import terminal_evidence
    monkeypatch.setattr(terminal_evidence,'local_execution_state',lambda root:observation()['local_execution_state'])
    _,c,_=pas()
    with pytest.raises(ExchangeError,match='UNKNOWN'):require_shared_scope(tmp_path,c)
    with pytest.raises(ExchangeError,match='CANNOT_AUTHORIZE_ORDER_SCOPE'):
        require_shared_scope(tmp_path,c,owned_pas_intents=['order'],configuration_isolation=object())
    # Only the non-order configuration executor supplies the capability.
    base=Path(__file__).parent/'exchange'
    import ast
    callers=[p.name for p in base.glob('*.py') if any(isinstance(n,ast.Call)
        and isinstance(n.func,ast.Name) and n.func.id=='require_shared_scope'
        and any(k.arg=='configuration_isolation' for k in n.keywords)
        for n in ast.walk(ast.parse(p.read_text())))]
    assert callers==['pas_configuration.py']


def identity_files(directory,now):
    raw=directory/'request.txt';raw.write_text('OFFLINE named-account fixture; no actual human acceptance')
    o=dict(basis='DIRECT_HUMAN_V6_ACCOUNT_CONFIRMATION',scope='ACCOUNT_IDENTITY_ONLY',
        operator_confirmed_named_wallet=True,team_wallet=TEAM,network='testnet',dex='pas',collateral='USDP',
        original_request_file=raw.name,original_request_sha256=sha(raw),source_reference='OFFLINE ONLY',
        starts_ms=now-1000,expires_ms=now+86400000)
    (directory/'operator_confirmation.json').write_text(json.dumps(o));return o


def test_direct_identity_is_separate_from_organizer_authorship_and_action_consent(tmp_path):
    identity_files(tmp_path,NOW);r=registration_evidence(tmp_path,NOW)
    assert r['status']=='DIRECT_OPERATOR_CONFIRMED_ACCOUNT_IDENTITY' and r['scope']=='ACCOUNT_IDENTITY_ONLY'
    assert not (tmp_path/'acceptance.json').exists()
    (tmp_path/'request.txt').write_text('tampered')
    with pytest.raises(ExchangeError):registration_evidence(tmp_path,NOW)


def test_direct_identity_rejects_symlink_even_with_matching_hash(tmp_path):
    o=identity_files(tmp_path,NOW);(tmp_path/'link.txt').symlink_to(tmp_path/'request.txt')
    o['original_request_file']='link.txt';(tmp_path/'operator_confirmation.json').write_text(json.dumps(o))
    with pytest.raises(ExchangeError):registration_evidence(tmp_path,NOW)


def test_configuration_cli_prepares_direct_identity_without_creating_acceptance(monkeypatch,tmp_path):
    from exchange import pas_operations,venue_discovery,terminal_app
    src=tmp_path/'input';src.mkdir();identity_files(src,NOW)
    out=tmp_path/'output';out.mkdir();o=observation();o.pop('configuration_isolation')
    monkeypatch.setattr(terminal_app,'validate_safe',lambda *a:None)
    monkeypatch.setattr(venue_discovery,'discover',lambda *a,**k:o)
    monkeypatch.setattr(pas_operations.time,'time_ns',lambda:NOW*1000000)
    result=pas_operations.dispatch(tmp_path,NS(command='configuration-review',output=out,
        operator_confirmation=src/'operator_confirmation.json',organizer_confirmation=None))
    assert result['registration_evidence']['status']=='DIRECT_OPERATOR_CONFIRMED_ACCOUNT_IDENTITY'
    assert result['configuration_plan']['signing_authority']=='NONE'
    assert not (out/'acceptance.json').exists()


def test_scored_direct_identity_requires_real_fresh_funding_and_still_no_acceptance(tmp_path):
    from exchange.scored_session import require_scored_evidence
    m=evidence_files(tmp_path);(tmp_path/'organizer_confirmation.json').unlink();o=identity_files(tmp_path,m.created_ms)
    o['starts_ms']=m.daily.starts_ms;o['expires_ms']=m.daily.expires_ms
    (tmp_path/'operator_confirmation.json').write_text(json.dumps(o))
    vp=tmp_path/'venue_discovery.json';v=json.loads(vp.read_text())
    v['funding']=dict(status='USDP_POSITIVE_VERIFIED',account_mode='unifiedAccount',team_wallet=TEAM,
        balance='100000',observed_ms=m.created_ms-1)
    vp.write_text(json.dumps(v));m=replace(m,organizer_evidence_sha256=sha(tmp_path/'operator_confirmation.json'),discovery_evidence_sha256=sha(vp))
    assert len(require_scored_evidence(m,tmp_path))==3
    v['funding']['observed_ms']=m.created_ms-300001;vp.write_text(json.dumps(v));m=replace(m,discovery_evidence_sha256=sha(vp))
    with pytest.raises(ExchangeError,match='FRESH_ACTUAL_PAS_FUNDING'):require_scored_evidence(m,tmp_path)
    assert not (tmp_path/'acceptance.json').exists()


@pytest.mark.parametrize('kind',['market','global','stricter_api'])
def test_pas_announced_oi_ceilings_and_stricter_runtime_limit(pas_bridge,kind):
    from exchange.order_lifecycle import OrderRequest
    v=pas_bridge.live;f=v.fixture;req=OrderRequest('pas:BTC','BUY','1','100');ctx=v.provider.load(req)
    limits=dict(ctx.limits,totalOiCap='100000000',oiSzCapPerPerp='100000000',
        coinToOiCap=[[s,'100000000'] for s in ctx.contexts])
    contexts=deepcopy(ctx.contexts)
    if kind=='market':contexts['pas:BTC']['openInterest']='99999.5'
    elif kind=='global':
        for c in contexts.values():c['openInterest']='50000'
    else:limits['coinToOiCap']=[['pas:BTC','1000']]
    ctx=replace(ctx,limits=limits,contexts=contexts)
    token=replace(permission(req),issued_ms=f.now)
    r=v.validator.validate(req,ctx,token,f.now)
    assert not r.allowed and r.code=='OPEN_INTEREST_CAPACITY'
    assert D(r.audit['open_interest_cap'])==(D(1000) if kind=='stricter_api' else D(10000000))
    assert D(r.audit['total_open_interest_cap'])==50000000
    assert not v.transport.signed_payloads
