"""Isolated synthetic PAS protocol, accounting and finite authority tests; no HTTP."""
from copy import deepcopy
from dataclasses import replace,asdict
from decimal import Decimal as D
from types import SimpleNamespace
import json,socket
import pytest
from exchange.base_exchange import ExchangeError,Position
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.venue_profiles import SCORED,venue_profile
from exchange.account_events import AccountFunding
from exchange.order_lifecycle import OrderRequest
from exchange.pas_residuals import classify_reduction
from exchange.pas_readiness import require_pas_market_status
from exchange.scored_session import ScoredLimits,ScoredLongMandate,SCORED_START_MS,SCORED_ACKS,require_scored_evidence
from exchange.long_session import LongAuthorization,ACKS,read_mandate
from exchange.execution_journal import ExecutionJournal
from exchange.sdk_transport import OfficialSDKTransport
from exchange.terminal_evidence import opportunity_capacity
from test_exchange_migration import PublicInfoFixture,NOW,TEAM
from exchange.testnet_certification import TEAM as ACTUAL_TEAM,API

@pytest.fixture(autouse=True)
def isolated_pas_environment(monkeypatch):
    # Other legacy suites intentionally install practice defaults at import.
    # An explicit PAS test must select its own profile; production must keep
    # rejecting a contradictory environment rather than silently override it.
    monkeypatch.setenv('HL_DEX','pas')
    monkeypatch.setenv('SIGNAL_DATA_MODE','PAS_NATIVE_ONLY')

class PasFixture(PublicInfoFixture):
    def __init__(self):
        super().__init__()
        self.dexes=[None,dict(name='par'),dict(name='pa'),dict(name='pas')]
        self.metadata['collateralToken']=77
        for row in self.metadata['universe']:
            row['name']=row['name'].replace('par:','pas:');row['szDecimals']=5
        self.state['assetPositions'][0]['position']['coin']='pas:BTC'
        self.spot['balances']=[dict(coin='USDP',token=77,total='1000',hold='10'),dict(coin='USDPR',token=20,total='999999',hold='0')]
        self.fills[0].update(coin='pas:BTC',feeToken='USDP',closedPnl='0')
        self.tokens=[dict(name='USDP',index=77),dict(name='USDPR',index=20)]
        self.special=None
    def __call__(self,payload):
        q=payload['type']
        if q=='frontendOpenOrders':
            self.calls.append(deepcopy(payload));return deepcopy(self.orders)
        if q in {'spotMeta','exchangeStatus','perpDexStatus','userFunding','userFillsByTime'}:
            self.calls.append(deepcopy(payload))
            return deepcopy(dict(spotMeta=dict(tokens=self.tokens),exchangeStatus=dict(specialStatuses=self.special),
                perpDexStatus=dict(totalNetDeposit='1000'),userFunding=[],userFillsByTime=self.fills)[q])
        return super().__call__(payload)

def pas():
    f=PasFixture();c=HyperliquidClient(f,clock_ms=lambda:f.now,venue='pas');c.startup()
    return f,c,HyperliquidAccount(c,TEAM)

def test_pas_discovery_uses_canonical_index_precision_and_collateral():
    f,c,a=pas();assert c.dex_index==3 and c.collateral_token_id==77 and c.venue_identity==SCORED.identity
    for index,row in enumerate(f.metadata['universe']):
        assert c.market(row['name']).asset_id==130000+index
        assert c.market(row['name']).size_step==D('.00001')
    assert f.calls[:3]==[dict(type='perpDexs'),dict(type='meta',dex='pas'),dict(type='spotMeta')]

@pytest.mark.parametrize('damage',['missing_pas','pa_only','duplicate_pas','wrong_token','duplicate_token','delisted','par_symbol','missing_market'])
def test_pas_discovery_fails_closed_without_native_or_practice_fallback(damage):
    f=PasFixture()
    if damage=='missing_pas':f.dexes.pop()
    elif damage=='pa_only':f.dexes=[None,dict(name='pa')]
    elif damage=='duplicate_pas':f.dexes.append(dict(name='pas'))
    elif damage=='wrong_token':f.tokens[0]['name']='USDPR'
    elif damage=='duplicate_token':f.tokens.append(dict(name='USDP',index=78))
    elif damage=='delisted':f.metadata['universe'][0]['isDelisted']=True
    elif damage=='par_symbol':f.metadata['universe'][0]['name']='par:BTC'
    else:f.metadata['universe'].pop()
    c=HyperliquidClient(f,venue='pas')
    with pytest.raises(ExchangeError):c.startup()
    assert not c.ready and not c.markets

@pytest.mark.parametrize('query,params', [('meta',{'dex':'par'}),('meta',{'dex':'pa'}),('meta',{'dex':''}),('l2Book',{'coin':'par:BTC'}),('l2Book',{'coin':'BTC'}),('order',{}),('withdraw3',{})])
def test_pas_public_boundary_rejects_wrong_venue_and_signed_queries(query,params):
    f,c,a=pas();before=len(f.calls)
    with pytest.raises(ExchangeError):c.post_info(query,**params)
    assert len(f.calls)==before

def test_practice_client_and_environment_do_not_implicitly_promote():
    f=PasFixture()
    with pytest.raises(ExchangeError):HyperliquidClient(f).startup()
    for name in ['PAS','pa','native','',True]:
        with pytest.raises(ExchangeError):venue_profile(name)

def test_unified_pas_collateral_does_not_use_practice_balance_or_zero_dex_summary():
    f,c,a=pas();f.state['marginSummary']['accountValue']='0';f.state['assetPositions'][0]['position']['unrealizedPnl']='500'
    e=a.get_equity();assert e.reported_account_value==e.collateral_balance==1000 and e.withdrawable is None
    assert e.valuation_source=='spotClearinghouseState.USDP.total'
    f.spot['balances']=[x for x in f.spot['balances'] if x['coin']=='USDPR']
    assert a.get_equity().collateral_balance==0

def test_standard_pas_uses_reported_pas_equity_once():
    f,c,a=pas();f.mode='disabled';f.state['marginSummary']=dict(accountValue='1005',totalRawUsd='1000',totalMarginUsed='10')
    f.state['withdrawable']='995';e=a.get_equity()
    assert (e.reported_account_value,e.collateral_balance,e.margin_used,e.withdrawable)==(1005,1000,10,995)
    assert 'STANDARD' in e.valuation_source

@pytest.mark.parametrize('mode',['portfolioMargin','dexAbstraction','standard','unknown'])
def test_unsupported_account_modes_are_not_silently_reconfigured(mode):
    f,c,a=pas();f.mode=mode
    with pytest.raises(ExchangeError):a.get_equity()
    assert all(x['type'] not in {'userSetAbstraction','agentSetAbstraction'} for x in f.calls)

def test_pas_history_filters_practice_and_uses_actual_usdp_fees():
    f,c,a=pas();f.fills.append(dict(f.fills[0],coin='par:BTC',feeToken='USDPR',tid=999))
    fills=a.get_complete_fills(0,NOW);assert len(fills)==1 and fills[0].symbol=='pas:BTC' and fills[0].fee_token=='USDP'
    f.fills[0]['feeToken']='USDPR'
    with pytest.raises(ExchangeError):a.get_complete_fills(0,NOW)

def test_pas_funding_cannot_be_labeled_usdpr():
    e=AccountFunding('pas:BTC',NOW,'hash','1','.01','.001','USDP');assert e.collateral=='USDP'
    with pytest.raises(ExchangeError):AccountFunding('pas:BTC',NOW,'hash','1','.01','.001')

@pytest.mark.parametrize('special',[['maintenance'],{'pas':'halted'},'unknown'])
def test_special_exchange_status_blocks_eligibility(special):
    f,c,a=pas();f.special=special
    with pytest.raises(ExchangeError,match='SPECIAL_STATUS'):require_pas_market_status(c)

def test_deposit_status_is_not_claimed_to_be_a_trading_open_flag():
    f,c,a=pas();r=require_pas_market_status(c)
    assert 'not a market-open flag' in r['limitation']
    assert f.calls[-1]==dict(type='perpDexStatus',dex='pas')

def test_scored_transport_requires_exact_venue_binding_before_any_key_use():
    f,c,a=pas()
    with pytest.raises(ExchangeError,match='SIGNED_VENUE'):OfficialSDKTransport(c,None,TEAM,None,SimpleNamespace(),rate_limits=None)

def scored(**changes):
    d=ScoredLimits('offline:pas',ACTUAL_TEAM,API,('pas:BTC',),('LONG',),SCORED_START_MS,SCORED_START_MS+3600000,'a'*64,socket.gethostname(),'20000','1000','1000','2000')
    d=replace(d,**changes)
    return ScoredLongMandate(d,SCORED_START_MS+1000,SCORED_START_MS+301000,*(['b'*64]*4),organizer_evidence_sha256='c'*64,discovery_evidence_sha256='d'*64)

@pytest.mark.parametrize('change',[{'dex':'par'},{'markets':('par:BTC',)},{'starts_ms':SCORED_START_MS-1},{'maximum_entry_attempts':3},{'leverage':2},{'directions':('SHORT',)},{'maximum_notional':'20000'}])
def test_scored_contract_never_reuses_practice_or_expands_risk(change):
    with pytest.raises(ExchangeError):scored(**change).require()

def test_scored_parser_and_approval_bind_venue_expiry_and_extra_acknowledgments(tmp_path):
    m=scored();path=tmp_path/'mandate.json';path.write_text(json.dumps(asdict(m)));assert read_mandate(path).identity==m.identity
    accepted=m.created_ms+1;data=dict(mandate_hash=m.identity,accepted_ms=accepted,expires_ms=m.daily.expires_ms,operator_acceptance='OFFLINE synthetic explicit acceptance',**{k:True for k in ACKS})
    p=tmp_path/'approval.json';p.write_text(json.dumps(data));j=ExecutionJournal(tmp_path/'j.sqlite',session_id='offline:pas',team_address=ACTUAL_TEAM)
    try:
        kw=dict(clock_ms=lambda:accepted,source_hash=lambda:'a'*64,policy_hash=lambda:'b'*64)
        with pytest.raises(ExchangeError,match='PAS_SCORED'):LongAuthorization(m,p,j,**kw)
        data.update({k:True for k in SCORED_ACKS});p.write_text(json.dumps(data));a=LongAuthorization(m,p,j,**kw)
        assert a.venue_identity==SCORED.identity
        a.clock_ms=lambda:m.daily.expires_ms
        with pytest.raises(ExchangeError):a.require(ACTUAL_TEAM,API)
    finally:j.close()

def test_scored_contract_needs_original_organizer_record_not_a_green_flag(tmp_path):
    m=scored()
    with pytest.raises(ExchangeError,match='ORGANIZER'):require_scored_evidence(m,tmp_path)

@pytest.mark.parametrize('lots',[1,2,9])
def test_subminimum_full_residual_planner_keeps_exact_lots_without_claiming_venue_proof(lots):
    f,c,a=pas();s=c.market('pas:BTC');q=s.size_step*lots;p=Position(s.symbol,q,D(100),D(0),D(1),None)
    r=OrderRequest(s.symbol,'SELL',q,D(100),reduce_only=True,tif='Ioc')
    plan=classify_reduction(s,p,r,now_ms=NOW,position_ms=NOW,reconciled=True)
    assert plan['kind']=='FULL_POSITION_CLOSE' and plan['minimum_exception'] and plan['normal_order'].quantity==q
    assert not plan['signing_authority'] and not plan['genuine_venue_route_qualified'] and not plan['native_stop_qualified']

@pytest.mark.parametrize('damage',['partial','wrong_direction','not_reduce_only','dust','stale','native','oversized'])
def test_residual_exception_never_authorizes_entry_partial_rounding_or_native_route(damage):
    f,c,a=pas();s=c.market('pas:BTC');p=Position(s.symbol,D('.00009'),D(100),D(0),D(1),None)
    r=OrderRequest(s.symbol,'SELL',p.quantity,D(100),reduce_only=True,tif='Ioc');at=NOW
    if damage=='partial':r=replace(r,quantity=D('.00001'))
    elif damage=='wrong_direction':r=replace(r,side='BUY')
    elif damage=='not_reduce_only':r=replace(r,reduce_only=False)
    elif damage=='dust':r=replace(r,quantity=D('.000019'))
    elif damage=='stale':at-=5001
    elif damage=='native':r=replace(r,tif='Gtc')
    else:r=replace(r,quantity=D('.00010'))
    with pytest.raises(ExchangeError):classify_reduction(s,p,r,now_ms=NOW,position_ms=at,reconciled=True)


def test_capacity_cannot_mix_pas_spec_and_practice_book():
    f,c,a=pas();spec=c.market('pas:BTC');book=HyperliquidMarketData(c).get_orderbook('pas:BTC')
    book=replace(book,symbol='par:BTC')
    r=opportunity_capacity(spec,book,{},dict(),now_ms=NOW,active_ms=NOW,fee_rate=D('.001'),fee_ms=NOW)
    assert r['authorized_executable_notional']=='0' and 'CAPACITY_VENUE_MARKET_IDENTITY_MISMATCH' in r['reasons']


def test_pas_authorized_cli_rejects_wrong_profile_before_builder(monkeypatch,tmp_path):
    from exchange import terminal_app,long_session
    m=scored();p=tmp_path/'m.json';p.write_text(json.dumps(asdict(m)))
    monkeypatch.setattr(long_session,'build_long_runtime',lambda *a,**k:pytest.fail('builder reached'))
    with pytest.raises(ExchangeError,match='CLI_MANDATE_VENUE_MISMATCH'):
        terminal_app.run_authorized(tmp_path,SimpleNamespace(mandate=p,venue='par'),None,None)


def test_wrong_native_practice_proof_cannot_qualify_pas(tmp_path):
    from exchange.long_session import require_native_evidence
    p=tmp_path/'proof.json';p.write_text(json.dumps(dict(network='testnet',dex='par',team_wallet=ACTUAL_TEAM,
        api_wallet=API,source='ACTUAL_NATIVE_PROTECTION_QUALIFICATION',receipt_file='raw.jsonl')))
    with pytest.raises(ExchangeError,match='ACTUAL_NATIVE'):require_native_evidence(p,scored().daily)


def evidence_files(tmp_path):
    from exchange.long_session import sha
    m=scored();original=tmp_path/'original.txt';original.write_text('OFFLINE synthetic organizer record; no venue permission')
    o=dict(network='testnet',dex='pas',collateral='USDP',team_wallet=ACTUAL_TEAM,
        operator_reviewed_provenance=True,source_reference='OFFLINE_FIXTURE',original_record_file=original.name,
        original_record_sha256=sha(original),starts_ms=m.daily.starts_ms,expires_ms=m.daily.expires_ms)
    f,c,a=pas()
    v=dict(status='READ_ONLY_DISCOVERY_COMPLETE',network='testnet',dex='pas',collateral='USDP',
        venue_identity=SCORED.identity,source_hash=m.daily.source_hash,source_hash_after=m.daily.source_hash,
        journal_integrity='ok',terminal_flat=True,finished_ms=m.created_ms-1,
        markets=[dict(symbol=x) for x in SCORED.markets],metadata=f.metadata,dex_index=3,collateral_token=77)
    (tmp_path/'organizer_confirmation.json').write_text(json.dumps(o))
    (tmp_path/'venue_discovery.json').write_text(json.dumps(v))
    return replace(m,organizer_evidence_sha256=sha(tmp_path/'organizer_confirmation.json'),
        discovery_evidence_sha256=sha(tmp_path/'venue_discovery.json'))


def test_scored_evidence_checks_raw_scope_source_and_freshness(tmp_path):
    m=evidence_files(tmp_path);assert len(require_scored_evidence(m,tmp_path))==3


@pytest.mark.parametrize('damage',['stale','wrong_source','wrong_token','incomplete','wrong_team','no_provenance','symlink'])
def test_scored_evidence_never_uses_flags_as_external_proof(tmp_path,damage):
    from exchange.long_session import sha
    m=evidence_files(tmp_path);vp=tmp_path/'venue_discovery.json';op=tmp_path/'organizer_confirmation.json'
    v=json.loads(vp.read_text());o=json.loads(op.read_text())
    if damage=='stale':v['finished_ms']=m.created_ms-300001
    elif damage=='wrong_source':v['source_hash_after']='z'*64
    elif damage=='wrong_token':v['collateral_token']=22
    elif damage=='incomplete':v['markets'].pop()
    elif damage=='wrong_team':o['team_wallet']='0x'+'a'*40
    elif damage=='no_provenance':o['operator_reviewed_provenance']=False
    else:
        outside=tmp_path.parent/(tmp_path.name+'outside.txt');outside.write_text('outside')
        link=tmp_path/'escape.txt';link.symlink_to(outside)
        o.update(original_record_file=link.name,original_record_sha256=sha(outside))
    vp.write_text(json.dumps(v));op.write_text(json.dumps(o));m=replace(m,organizer_evidence_sha256=sha(op),discovery_evidence_sha256=sha(vp))
    with pytest.raises(ExchangeError):require_scored_evidence(m,tmp_path)


def test_shared_scope_preserves_unknown_but_allows_owned_known_protection(monkeypatch,tmp_path):
    from exchange.scored_session import require_shared_scope
    from exchange import terminal_evidence
    f,c,a=pas();f.state['assetPositions']=[];f.orders=[]
    class Rates:
        def read(self,q,operation,**kwargs):return operation()
    c.rate_limits=Rates()
    state=dict(status='BLOCKED_UNRESOLVED_INTENT',unresolved=[dict(journal='qualification',state='UNKNOWN',intent_key='old')])
    monkeypatch.setattr(terminal_evidence,'local_execution_state',lambda root:state)
    with pytest.raises(ExchangeError,match='UNKNOWN'):require_shared_scope(tmp_path,c,owned_pas_intents=['old'])
    state['unresolved']=[dict(journal='pas',state='OPEN',intent_key='owned')]
    require_shared_scope(tmp_path,c,owned_pas_intents=['owned'])
    state['unresolved'][0]['state']='UNKNOWN'
    with pytest.raises(ExchangeError,match='UNKNOWN'):require_shared_scope(tmp_path,c,owned_pas_intents=['owned'])


def test_shared_scope_rejects_real_practice_exposure(monkeypatch,tmp_path):
    from exchange.scored_session import require_shared_scope
    from exchange import terminal_evidence
    f,c,a=pas()
    class Rates:
        def read(self,q,operation,**kwargs):return operation()
    c.rate_limits=Rates();monkeypatch.setattr(terminal_evidence,'local_execution_state',lambda root:dict(status='NO_LOCAL_UNRESOLVED_INTENT',unresolved=[]))
    with pytest.raises(ExchangeError,match='OTHER_DEX_EXPOSURE'):require_shared_scope(tmp_path,c)


def test_pas_proposal_saves_all_blockers_without_mandate_or_acceptance(monkeypatch,tmp_path):
    from exchange import scored_prepare
    from exchange import terminal_observer
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    output=tmp_path/'proposal'
    observation=dict(status='READ_ONLY_DISCOVERY_COMPLETE',terminal_flat=True,account=dict(reported_account_equity=dict(collateral_balance='0')),markets=[])
    monkeypatch.setattr(scored_prepare,'discover',lambda *a,**k:observation)
    monkeypatch.setattr(scored_prepare,'local_execution_state',lambda root:dict(status='BLOCKED_UNRESOLVED_INTENT'))
    monkeypatch.setattr(terminal_observer,'observe',lambda *a,**k:dict(status='OFFLINE_FIXTURE',liquidity={}))
    args=SimpleNamespace(output=output,minutes=60,maximum_notional='1000',markets=[],native_protection_evidence=None,release=None,organizer_confirmation=None)
    assert scored_prepare.prepare_scored(root,args)==0
    report=json.loads((output/'proposal.json').read_text())
    assert report['dex']=='pas' and report['collateral']=='USDP' and report['signing_authority']=='NONE'
    assert 'PAS_USDP_COLLATERAL_REQUIRED' in report['blockers'] and 'SHARED_ACCOUNT_UNKNOWN_UNRESOLVED' in report['blockers']
    assert not (output/'mandate.json').exists() and not (output/'acceptance.json').exists()


def test_pas_state_directory_cannot_reuse_practice_state(tmp_path):
    from exchange.terminal_app import start
    (tmp_path/'venue.json').write_text(json.dumps(dict(dex='par')))
    with pytest.raises(ExchangeError,match='STATE_VENUE_MISMATCH'):
        start(__import__('pathlib').Path(__file__).resolve().parents[1],SimpleNamespace(venue='pas',state=str(tmp_path)))


def test_sdk_rechecks_canonical_pas_identity_even_if_both_missing():
    with pytest.raises(ExchangeError,match='SIGNED_VENUE'):
        OfficialSDKTransport(SimpleNamespace(dex='pas'),None,TEAM,None,SimpleNamespace(),rate_limits=None)


@pytest.mark.parametrize('setting,value',[('HL_DEX','par'),('SIGNAL_DATA_MODE','PAR_NATIVE_ONLY')])
def test_explicit_pas_profile_rejects_conflicting_practice_environment(monkeypatch,setting,value):
    from venue_config import require_paper_migration,MigrationPolicyError
    monkeypatch.setenv(setting,value)
    with pytest.raises(MigrationPolicyError):require_paper_migration('pas')
