"""V3 adversarial diagnostics and isolated ephemeral configuration protocol tests."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json,socket
import pytest
from exchange.base_exchange import Candle,MarketSpec,ExchangeError
from exchange.pas_funding import funding_evidence,current_funding
from exchange.pas_controller import assess,STATES
from exchange.durable_history import DurableHistory
from exchange.pas_configuration import PasConfigurationApproval,require_plan,approval_preflight
from exchange.pas_native_plan import prepare_native_test,QualificationProgress
from exchange.competition_windows import SCORED_START_MS,SCORED_END_MS
from exchange.testnet_certification import TEAM,API
from exchange.venue_profiles import SCORED
from test_scored_opening_release import configuration_observation
from test_pas_migration import isolated_pas_environment
from exchange.pas_configuration_plan import configuration_plan

NOW=SCORED_START_MS+3600000


def funding(**kw):
    args=dict(team=TEAM,mode='unifiedAccount',token=3307,spot=dict(balances=[dict(coin='USDP',token=3307,total='100')]),
        state=dict(time=NOW,assetPositions=[],marginSummary=dict(totalRawUsd='50')),observed_ms=NOW,now_ms=NOW,provenance='OFFLINE_FIXTURE')
    args.update(kw);return funding_evidence(**args)


@pytest.mark.parametrize('amount,status',[('0','USDP_ZERO'),('100','USDP_POSITIVE_VERIFIED'),('-1','USDP_UNAVAILABLE'),('NaN','USDP_UNAVAILABLE')])
def test_funding_amounts_and_origin(amount,status):
    f=funding(spot=dict(balances=[dict(coin='USDP',token=3307,total=amount)]))
    assert f['status']==status and f['organizer_credit_amount'] is None and f['signing_authority']=='NONE'
    if amount=='100':assert f['balance']=='100' # no addition of margin equity or unrealized PnL


@pytest.mark.parametrize('damage',['wrong_team','signer','wrong_token','duplicate','wrong_coin','unavailable','bad_mode','future','stale'])
def test_funding_cannot_masquerade_as_ready(damage):
    args={}
    if damage in ('wrong_team','signer'):args['team']=API
    if damage=='wrong_token':args['spot']=dict(balances=[dict(coin='USDP',token=11,total='100')])
    if damage=='duplicate':args['spot']=dict(balances=[dict(coin='USDP',token=3307,total='100')]*2)
    if damage=='wrong_coin':args['spot']=dict(balances=[dict(coin='USDPR',token=3307,total='100')])
    if damage=='unavailable':args['spot']=None
    if damage=='bad_mode':args['mode']='portfolioMargin'
    if damage=='future':args['observed_ms']=NOW+1
    if damage=='stale':args['observed_ms']=NOW-360001
    f=funding(**args);assert f['status']!='USDP_POSITIVE_VERIFIED' and f['reasons']


def test_standard_separate_and_cached_funding_expires():
    f=funding(mode='disabled');assert f['balance']=='50' and f['account_mode']=='disabled' and f['reasons']
    assert current_funding(f,NOW+360001)['status']=='USDP_STALE'
    assert current_funding(None,NOW)['status']=='USDP_UNAVAILABLE'
    assert funding(spot=dict(balances=[dict(coin='USDPR',token=5,total='100000')]))['status']=='USDP_ZERO'
    assert funding()['status']=='USDP_POSITIVE_VERIFIED'
    assert funding(spot=dict(balances=[]))['status']=='USDP_ZERO'


@pytest.mark.parametrize('at,opened',[(SCORED_START_MS-1,False),(SCORED_START_MS,True),(SCORED_END_MS-1,True),(SCORED_END_MS,False)])
def test_controller_exact_calendar_never_grants_authority(at,opened):
    r=assess({},at)
    assert r['gates']['SCORING_WINDOW_OPEN']==opened and r['signing_authority']=='NONE' and r['trading_verdict']=='NO_GO'
    assert not r['gates']['EXACT_SESSION_APPROVAL_ACCEPTED']


def test_funding_arrival_does_not_approve_or_sign_and_disappearance_revokes():
    v=dict(funding=funding(),account_observed_ms=NOW,source_hash='a'*64,
        local_execution_state=dict(status='BLOCKED_UNRESOLVED_INTENT'),liquidity={})
    r=assess(v,NOW);assert r['gates']['USDP_FUNDING_VERIFIED'] and r['state']=='USDP_FUNDING_VERIFIED'
    assert not r['ready_for_operator_action'] and not r['gates']['NATIVE_PROTECTION_QUALIFIED']
    v['funding']=funding(spot=dict(balances=[]));assert not assess(v,NOW)['gates']['USDP_FUNDING_VERIFIED']
    v['funding']=funding();assert not assess(v,NOW+360001)['gates']['USDP_FUNDING_VERIFIED']


def client():
    spec=MarketSpec('pas:BTC',5,20,2810000)
    return SimpleNamespace(dex='pas',collateral_token_id=3307,markets={spec.symbol:spec},market=lambda symbol:spec if symbol==spec.symbol else (_ for _ in ()).throw(ExchangeError('NO_FALLBACK')))


def bars(n=300,start=None):
    start=(NOW//60000-n)*60000 if start is None else start
    return [Candle('pas:BTC','1m',start+i*60000,start+(i+1)*60000-1,D(100),D(101),D(99),D(100),D(1)) for i in range(n)]


def test_history_persists_deduplicates_reports_gaps_without_fill(tmp_path):
    p=tmp_path/'history.sqlite';h=DurableHistory(p,client(),'OFFLINE_RAW')
    b=bars();h.ingest('pas:BTC',b,now_ms=NOW,raw_count=301);h.ingest('pas:BTC',b,now_ms=NOW)
    assert len(h.read('pas:BTC',NOW))==300 and h.report('pas:BTC',NOW)['strategy_history_ready']
    h.close();h=DurableHistory(p,client(),'OFFLINE_RAW')
    assert h.report('pas:BTC',NOW)['contiguous_tail_bars']==300
    assert not h.report('pas:BTC',NOW+120001)['strategy_history_ready']
    h.close()
    h=DurableHistory(tmp_path/'gap.sqlite',client(),'OFFLINE_RAW');h.ingest('pas:BTC',b[:100]+b[101:],now_ms=NOW)
    r=h.report('pas:BTC',NOW);assert r['valid_deduplicated_completed']==299 and r['missing_intervals'][0]['count']==1
    assert r['contiguous_tail_bars']==199 and not r['strategy_history_ready'];h.close()


@pytest.mark.parametrize('fault',['conflict','incomplete','future','alignment','ohlc','foreign','volume'])
def test_history_rejects_invented_or_conflicting_bars(tmp_path,fault):
    h=DurableHistory(tmp_path/'h.sqlite',client(),'OFFLINE_RAW');b=bars();h.ingest('pas:BTC',b,now_ms=NOW)
    c=b[-1]
    if fault=='conflict':c=replace(c,close=D('100.1'))
    if fault=='incomplete':c=replace(c,timestamp_ms=NOW//60000*60000,close_timestamp_ms=NOW//60000*60000+59999)
    if fault=='future':c=replace(c,timestamp_ms=NOW//60000*60000+60000,close_timestamp_ms=NOW//60000*60000+119999)
    if fault=='alignment':c=replace(c,timestamp_ms=c.timestamp_ms+1)
    if fault=='ohlc':c=replace(c,high=D(98))
    if fault=='foreign':c=replace(c,symbol='par:BTC')
    if fault=='volume':c=replace(c,volume=D(-1))
    with pytest.raises(ExchangeError):h.ingest('pas:BTC',[c],now_ms=NOW)
    assert len(h.read('pas:BTC',NOW))==300;h.close()


def test_history_no_cross_deployment_cache_or_payload_tamper(tmp_path):
    p=tmp_path/'h.sqlite';h=DurableHistory(p,client(),'OFFLINE_RAW');h.ingest('pas:BTC',bars(1),now_ms=NOW)
    with h.db:h.db.execute("update bars set payload='{}'")
    with pytest.raises(ExchangeError,match='HASH'):h.read('pas:BTC',NOW)
    h.close();c=client();c.collateral_token_id=5
    with pytest.raises(ExchangeError,match='BINDING'):DurableHistory(p,c,'OFFLINE_RAW')


def test_exact_config_approval_and_scope_no_old_par_authority():
    a=PasConfigurationApproval('a'*64,'b'*64,'c'*64,NOW,NOW+900000,socket.gethostname(),
        'APPROVE PAS CONFIGURATION '+'a'*64,True,True)
    a.require(TEAM,API,NOW)
    for change in (dict(expires_ms=NOW),dict(expires_ms=NOW+900001),dict(host='wrong'),dict(scope='PAR_1X_CROSS_CONFIGURATION_ONLY'),
        dict(exact_phrase='APPROVE'),dict(manual_wallet_verified=False),dict(sole_signer_host_confirmed=False),dict(source_hash='bad')):
        with pytest.raises(ExchangeError):replace(a,**change).require(TEAM,API,NOW)


@pytest.mark.parametrize('damage',['source','age','hash','action','unknown'])
def test_configuration_evidence_rejected_before_key_access(damage,monkeypatch):
    d=configuration_observation();d['finished_ms']=NOW;p=configuration_plan(d)
    if damage=='source':source='b'*64
    else:source='a'*64
    if damage=='age':at=NOW+300001
    else:at=NOW
    if damage=='hash':p['plan_hash']='b'*64
    if damage=='action':p['changes'][0]['requested_action']['leverage']=20
    if damage=='unknown':
        from exchange import pas_configuration as m
        monkeypatch.setattr(m,'active_source_hash',lambda root:'a'*64)
        from exchange import long_session
        monkeypatch.setattr(long_session,'require_release',lambda *a:None);monkeypatch.setattr(long_session,'sha',lambda *a:'c'*64)
        with pytest.raises(ExchangeError,match='PREREQUISITES'):approval_preflight('.',p,d,'OFFLINE',NOW)
    else:
        with pytest.raises(ExchangeError):require_plan(p,d,source,at)


def test_milestone_acceptance_does_not_imply_trigger_fill_or_qualification():
    p=QualificationProgress()
    for at,(name,details) in enumerate([
        ('ENTRY_FILL_CONFIRMED',dict(entry_oid=1,quantity='2')),
        ('STOP_SUBMITTED',dict(stop_cloid='0x1')),
        ('STOP_ACCEPTED',dict(stop_oid=2)),
        ('STOP_ARMED',dict(stop_oid=2,isTrigger=True,reduceOnly=True,fixed_size='2')),
        ('STOP_TRIGGERED',dict(stop_oid=2,status='triggered')),
        ('CLOSING_ORDER_IDENTIFIED',dict(stop_oid=2,closing_oid=3,authoritative_link=True))]):p.observe(name,at=at,details=details)
    assert 'CLOSING_FILL_CONFIRMED' not in p.stages and not p.report()['qualified']
    p.observe('CLOSING_FILL_CONFIRMED',at=10,details=dict(closing_oid=3,quantity='1',actual_fees='.01',actual_funding='0'))
    assert p.recovery_required and 'POSITION_RECONCILED_FLAT' not in p.stages
    with pytest.raises(ExchangeError):p.observe('POSITION_RECONCILED_FLAT',at=11,details=dict(two_authoritative_flat_zero_order_readbacks=True))


def test_pas_native_plan_not_gated_by_ordinary_native_proof_and_no_par_residual_exception():
    d=configuration_observation();d['finished_ms']=NOW;d['user_fees']=dict(userCrossRate='.00045')
    for r in d['markets']:
        r.update(spec=dict(symbol=r['symbol'],asset_id=r['spec']['asset_id'],size_decimals=5,max_leverage=20),
            book=dict(timestamp_ms=NOW,bids=[dict(price='80000',quantity='.1')],asks=[dict(price='80001',quantity='.1')]),
            displayed_book_only_quantity='.001',context=dict(funding='.00001'))
    p=prepare_native_test(d,'a'*64,NOW)
    assert p['normal_autonomous_native_proof_required_to_prepare'] is False and not p['approval_created']
    assert p['stop']['grouping']=='na' and p['stop']['reduce_only'] and not p['stop']['isMarket']
    assert 'PAS_SUBMINIMUM_CLEANUP_SCOPE_NOT_ESTABLISHED_NO_PAR_EXCEPTION' in p['blockers']
    assert p['cleanup']['uncertain_retry'] is False and not p['consumed_attempt_reset_permitted']
    assert p['signing_authority']=='NONE' and p['maximum_signed_actions']==6


def test_configuration_transport_offline_pas_exact_action_one_use(tmp_path,monkeypatch):
    from eth_account import Account
    from exchange import leverage_configuration as lc,pas_configuration as pc
    from exchange.sdk_transport import build_exchange
    from exchange.execution_safety import NonceManager,HyperliquidRateLimitManager
    from exchange.execution_journal import ExecutionJournal,fingerprint
    from exchange.hyperliquid_client import HyperliquidClient
    from test_pas_execution_faults import PasLiveFixture
    signer=Account.create();f=PasLiveFixture(signer.address);monkeypatch.setattr(pc,'API',signer.address)
    monkeypatch.setattr(pc,'TEAM',f.active['user']);team=f.active['user']
    c=HyperliquidClient(f,clock_ms=lambda:f.now,venue='pas');c.startup()
    from exchange.execution_journal import fingerprint
    action=dict(type='updateLeverage',asset=c.market('pas:BTC').asset_id,isCross=True,leverage=1)
    plan=dict(source_hash='b'*64,changes=[dict(requested_action=action)])
    plan['plan_hash']=fingerprint(plan)
    a=PasConfigurationApproval(plan['plan_hash'],'b'*64,'c'*64,f.now,f.now+900000,socket.gethostname(),
        'APPROVE PAS CONFIGURATION '+plan['plan_hash'],True,True,team,signer.address)
    j=ExecutionJournal(tmp_path/'off.sqlite',session_id='OFFLINE',team_address=team)
    n=NonceManager(tmp_path/'nonce.sqlite',signer.address,clock_ms=lambda:f.now,journal=j)
    rates=HyperliquidRateLimitManager(j,clock_ms=lambda:f.now)
    wires=[]
    def sdk(wallet,client,nonces,sink):
        s=build_exchange(wallet,client,nonces,sink,offline=True)
        s.session.post=lambda url,**kw:(wires.append(kw['json']) or SimpleNamespace(status_code=200,json=lambda:dict(status='ok',response=dict(type='default'))))
        return s
    monkeypatch.setattr(lc,'build_exchange',sdk)
    t=lc.LeverageConfigurationTransport(c,signer,team,n,a,rates=rates,readiness_guard=lambda:None,approved_plan=plan)
    try:
        action=dict(type='updateLeverage',asset=c.market('pas:BTC').asset_id,isCross=True,leverage=1)
        t.set_one_x_cross('pas:BTC')
        assert len(wires)==1 and wires[0]['expiresAfter']==a.expires_ms and wires[0]['action']==action
        with pytest.raises(ExchangeError):t.set_one_x_cross('pas:BTC')
        with pytest.raises(ExchangeError):t.set_one_x_cross('pas:ETH')
        assert len(wires)==1
    finally:t.close();n.close();j.close();c.close()


def test_history_raw_count_survives_stream_merge_and_runtime_identity_change(tmp_path):
    c=client();h=DurableHistory(tmp_path/'h.sqlite',c,'OFFLINE_RAW')
    h.ingest('pas:BTC',bars(),now_ms=NOW,raw_count=301);h.ingest('pas:BTC',bars(),now_ms=NOW)
    assert h.report('pas:BTC',NOW)['raw_returned_last']==301
    c.collateral_token_id=5
    with pytest.raises(ExchangeError,match='BINDING'):h.read('pas:BTC',NOW)
    h.close()


def test_canonical_completed_end_boundary_and_no_missing_bar_fabrication(tmp_path):
    h=DurableHistory(tmp_path/'h.sqlite',client(),'OFFLINE_RAW');b=bars(1)
    h.ingest('pas:BTC',b,now_ms=NOW)
    h.ingest('pas:BTC',[replace(b[0],close_timestamp_ms=b[0].timestamp_ms+60000)],now_ms=NOW)
    assert len(h.read('pas:BTC',NOW))==1
    h.close()


def test_readiness_reports_history_independently_of_native_gate():
    v=dict(market_history={'pas:BTC':dict(strategy_history_ready=True,latest_completed_ms=NOW)},
        native_proof_verification=dict(verified=True,markets=['pas:BTC'],residual_scope_verified=False))
    r=assess(v,NOW)
    assert r['gates']['MARKET_HISTORY_READY'] and not r['gates']['NATIVE_PROTECTION_QUALIFIED']
    assert not r['ready_for_operator_action'] and r['trading_verdict']=='NO_GO'


@pytest.mark.parametrize('failure',['clock','source','account','nonce','rate','expired','loss','disconnect','stop'])
def test_no_public_report_can_become_session_authorization(failure):
    # Even falsely supplied summary flags cannot manufacture an acceptance.
    v=dict(funding=funding(),account_observed_ms=NOW,source_hash='a'*64,
        release_verification=dict(verified=True,source_hash='a'*64),
        native_proof_verification=dict(verified=True,markets=['pas:BTC'],residual_scope_verified=True),
        local_execution_state=dict(status='NO_LOCAL_UNRESOLVED_INTENT'),
        acceptance=True,authorized=True,critical_failure=failure)
    r=assess(v,NOW)
    assert r['signing_authority']=='NONE' and not r['gates']['EXACT_SESSION_APPROVAL_ACCEPTED']


def test_equivalent_exchange_decimal_strings_are_not_false_conflicts(tmp_path):
    h=DurableHistory(tmp_path/'h.sqlite',client(),'OFFLINE_RAW');b=bars(1)
    h.ingest('pas:BTC',b,now_ms=NOW)
    h.ingest('pas:BTC',[replace(b[0],open=D('100.00'),volume=D('1.0000'))],now_ms=NOW)
    assert len(h.read('pas:BTC',NOW))==1;h.close()


def test_serialized_discovery_embeds_the_original_plan_without_hash_recursion():
    d=configuration_observation();d['finished_ms']=NOW;p=configuration_plan(d)
    d['configuration_plan']=deepcopy(p)
    assert require_plan(p,d,'a'*64,NOW)==p
    d['configuration_plan']['changes'][0]['requested_action']['leverage']=20
    with pytest.raises(ExchangeError,match='EXACT_PAS_CONFIGURATION_PLAN'):require_plan(p,d,'a'*64,NOW)


def test_native_preparation_uses_final_targeted_snapshot_after_broad_scan():
    d=configuration_observation();d['finished_ms']=NOW;d['user_fees']=dict(userCrossRate='.00045')
    for r in d['markets']:
        r.update(spec=dict(symbol=r['symbol'],asset_id=r['spec']['asset_id'],size_decimals=5,max_leverage=20),
            book=dict(timestamp_ms=NOW-60000,bids=[dict(price='80000',quantity='.1')],asks=[dict(price='80001',quantity='.1')]),
            displayed_book_only_quantity='.001',context=dict(funding='.00001',markPx='80000',oraclePx='80000'))
    fresh=deepcopy(next(r for r in d['markets'] if r['symbol']=='pas:BTC'))
    fresh.update(observed_ms=NOW,context_ms=NOW,active_ms=NOW);fresh['book']['timestamp_ms']=NOW
    d['qualification_market']=fresh
    p=prepare_native_test(d,'a'*64,NOW)
    assert 'FRESH_FINAL_BOOK_REQUIRED' not in p['blockers'] and 'FRESH_FINAL_CONTEXT_AND_ACCOUNT_LIMITS_REQUIRED' not in p['blockers']
    assert p['book_ms']==NOW and p['context_ms']==NOW
    d['qualification_market']['spec']['asset_id']+=1
    with pytest.raises(ExchangeError,match='MAPPING'):prepare_native_test(d,'a'*64,NOW)
