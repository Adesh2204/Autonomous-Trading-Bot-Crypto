"""V6.2 adversarial offline fixtures. No real approval, HTTP or venue certification."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
import json,socket
import pytest
from exchange.base_exchange import ExchangeError,Position,Fill
from exchange.execution_journal import fingerprint
from exchange.long_session import sha
from exchange import trading_isolation as ti
from exchange.scored_risk_budget import budget,marked_loss
from exchange.scored_session import ScoredLimits,ScoredLongMandate,SCORED_START_MS
from exchange.durable_history import DurableHistory
from exchange.hyperliquid_market_data import parse_candle,HyperliquidMarketData,ParMarketDataEngine
from exchange.hyperliquid_client import HyperliquidClient
from exchange.market_health import validate_history
from exchange.testnet_certification import TEAM,API
from test_post_funding_v6 import proof as old_proof,seal,SOURCE
from test_exchange_migration import PublicInfoFixture,candle_row
NOW=SCORED_START_MS+1000


def limits():
    return ScoredLimits('offline:v6.2',TEAM,API,('pas:BTC',),('LONG',),NOW,NOW+3600000,SOURCE,socket.gethostname(),'20000','1000','1000','2000')


def policy_fixture(tmp_path,monkeypatch):
    p=old_proof();p['finished_ms']=NOW;p['funding']['observed_ms']=NOW-1
    for g,at in zip(p['readbacks'],(NOW-1000,NOW-500)):
        g['observed_ms']=at
        for v in g['venues'].values():v['exchange_time_ms']=at-100
    folder=tmp_path/'readbacks';folder.mkdir()
    for dex in ('par','pas'):
        rows=[]
        for g in p['readbacks']:
            when=g['observed_ms'];clock=g['venues'][dex]['exchange_time_ms']
            for kind in ('clearinghouseState','openOrders','frontendOpenOrders'):
                response=dict(time=clock,assetPositions=[]) if kind=='clearinghouseState' else []
                rows.append(dict(request=dict(type=kind,user=TEAM,dex=dex),response=response,received_ms=when-1))
            if dex=='par':rows.append(dict(request=dict(type='orderStatus',user=TEAM,oid=ti.CLOID),response=dict(status='unknownOid'),received_ms=when))
        f=folder/(dex+'_info_receipts.jsonl');f.write_text(''.join(json.dumps(r)+'\n' for r in rows));p['receipt_sha256'][dex]=sha(f)
    seal(p)
    f=tmp_path/'fills.json';f.write_text(json.dumps(dict(request=dict(type='userFillsByTime',user=TEAM,startTime=ti.NONCE-60000,endTime=NOW,aggregateByTime=False),end_ms=NOW,received_ms=NOW,response=[])))
    body=dict(mode=ti.MODE,status='UNACCEPTED_FINITE_POLICY',final_historical_outcome='UNKNOWN',signatures_created=0,exchange_writes=0,
        source_hash=SOURCE,team_wallet=TEAM,api_wallet=API,markets=['pas:BTC','pas:EWY'],
        signing_host=socket.gethostname(),created_ms=NOW,expires_ms=NOW+3600000,approval_deadline_ms=NOW+300000,maximum_duration_ms=3600000,
        original=dict(cloid=ti.CLOID,intent_key=ti.INTENT,nonce=ti.NONCE,state='UNKNOWN'),readbacks=p,fills_sha256=sha(f),
        risk_basis='ALLOCATED_20000_USDP_NOT_ACCOUNT_100000',ceilings=dict(bankroll='20000',entry='1000',cumulative='2000',attempts=2,positions=1,actions=12,trade_loss='100',session_loss='200'),order_authority=False)
    body['policy_hash']=fingerprint(body);path=tmp_path/'policy.json';path.write_text(json.dumps(body))
    # Only the physical original database check is replaced. Raw semantic,
    # temporal, identity and subject verification run without mocks.
    monkeypatch.setattr(ti,'verify_local',lambda *a:None)
    monkeypatch.setattr(ti,'active_source_hash',lambda *a:SOURCE)
    return path,body


def mandate(path):
    return ScoredLongMandate(limits(),NOW,NOW+300000,*(['b'*64]*4),organizer_evidence_sha256='c'*64,
        discovery_evidence_sha256='d'*64,trading_isolation_policy_sha256=sha(path))


def acceptance(path,p,m):
    a=dict(mode=ti.MODE,policy_hash=p['policy_hash'],mandate_hash=m.identity,
        exact_phrase='ISOLATE '+p['policy_hash']+' FOR '+m.identity,accepted_ms=NOW,expires_ms=m.daily.expires_ms,
        **{k:True for k in ti.ACKS})
    path.with_name('acceptance.json').write_text(json.dumps(a));return a


def test_isolation_binds_original_raw_receipts_and_exact_finite_subject(tmp_path,monkeypatch):
    path,p=policy_fixture(tmp_path,monkeypatch);m=mandate(path);acceptance(path,p,m)
    cap=ti.FiniteTradingIsolation(tmp_path,path,m)
    assert cap.require(NOW)['order_authority'] is False
    assert cap.exempt_intent(NS(dex='pas',clock_ms=lambda:NOW))==ti.INTENT
    assert p['original']['state']=='UNKNOWN'
    assert not hasattr(cap,'transmit') and not hasattr(cap,'check_action')


@pytest.mark.parametrize('fault',['hash','expired','future','extended','scope','authority','original','risk_denominator','ceiling','source','nonce','fills_truncated','fills_other_wallet','raw_position','raw_order','raw_status','raw_wrong_dex','raw_deleted'])
def test_isolation_rejects_changed_or_incomplete_evidence(tmp_path,monkeypatch,fault):
    path,p=policy_fixture(tmp_path,monkeypatch);now=NOW
    if fault=='hash':p['policy_hash']='f'*64
    elif fault=='expired':now=p['expires_ms']
    elif fault=='future':now=NOW-1
    elif fault=='extended':p['expires_ms']+=1
    elif fault=='scope':p['markets'].append('pas:ETH')
    elif fault=='authority':p['order_authority']=True
    elif fault=='original':p['original']['state']='CANCELLED'
    elif fault=='risk_denominator':p['risk_basis']='ACCOUNT_100000'
    elif fault=='ceiling':p['ceilings']['actions']=13
    elif fault=='source':p['source_hash']='z'*64
    elif fault=='nonce':p['readbacks']['local']['nonce_high_water']=ti.NONCE-1;seal(p['readbacks'])
    elif fault.startswith('fills'):
        f=tmp_path/'fills.json';v=json.loads(f.read_text())
        if fault=='fills_truncated':v['response']=[{}]*2000
        else:v['request']['user']=API
        f.write_text(json.dumps(v));p['fills_sha256']=sha(f)
    else:
        f=tmp_path/'readbacks/par_info_receipts.jsonl';rows=[json.loads(x) for x in f.read_text().splitlines()]
        for row in rows:
            kind=row['request']['type']
            if fault=='raw_position' and kind=='clearinghouseState':row['response']['assetPositions']=[{}]
            if fault=='raw_order' and kind in {'openOrders','frontendOpenOrders'}:row['response']=[{}]
            if fault=='raw_status' and kind=='orderStatus':row['response']={}
            if fault=='raw_wrong_dex':row['request']['dex']='native'
        if fault=='raw_deleted':rows=[]
        f.write_text(''.join(json.dumps(x)+'\n' for x in rows));p['readbacks']['receipt_sha256']['par']=sha(f);seal(p['readbacks'])
    if fault!='hash':p.pop('policy_hash');p['policy_hash']=fingerprint(p)
    path.write_text(json.dumps(p))
    with pytest.raises(ExchangeError):ti.validate_policy(tmp_path,path,source=SOURCE,reference_ms=now)


@pytest.mark.parametrize('fault',['missing','config_only','other_mandate','phrase','ack','expiry','late','revoked','wrong_host','changed_source'])
def test_isolation_acceptance_cannot_be_inferred_or_reused(tmp_path,monkeypatch,fault):
    path,p=policy_fixture(tmp_path,monkeypatch);m=mandate(path);a=acceptance(path,p,m);f=path.with_name('acceptance.json')
    if fault=='missing':f.unlink()
    elif fault=='config_only':a['mode']='CONFIGURATION_ONLY'
    elif fault=='other_mandate':a['mandate_hash']='e'*64
    elif fault=='phrase':a['exact_phrase']='APPROVE'
    elif fault=='ack':a[ti.ACKS[0]]=False
    elif fault=='expiry':a['expires_ms']+=1
    elif fault=='late':a['accepted_ms']=NOW+300001
    elif fault=='revoked':path.with_name('revoked.json').write_text('{}')
    elif fault=='wrong_host':monkeypatch.setattr(ti.socket,'gethostname',lambda:'other')
    else:monkeypatch.setattr(ti,'active_source_hash',lambda *a:'changed')
    if fault!='missing':f.write_text(json.dumps(a))
    with pytest.raises((ExchangeError,OSError)):ti.FiniteTradingIsolation(tmp_path,path,m).require(NOW)


@pytest.mark.parametrize('field,value',[('expires_ms',NOW+3600001),('bankroll','100000'),('maximum_notional','1001'),('maximum_cumulative_allocation','2001'),('risk_fraction','.006'),('daily_loss_fraction','.011'),('leverage',2),('maximum_concurrent_positions',2)])
def test_scored_session_cannot_expand_v6_2_limits(field,value):
    with pytest.raises(ExchangeError):replace(limits(),**{field:value}).require()


def test_risk_budget_denominator_and_open_loss_include_costs():
    d=limits();b=budget(d)
    assert D(b['intended_trade_loss'])==100 and D(b['session_loss_stop'])==200 and not b['account_balance_is_risk_denominator']
    pos=Position('pas:BTC',D('.01'),D(80000),D(-199),D(800),None)
    fill=Fill('pas:BTC',NOW,'1','2','BUY',D('.01'),D(80000),D('.72'),'USDP',D(0))
    r=marked_loss(d,prior_realized=0,prior_peak=20000,positions={pos.symbol:pos},cycle_fills=[fill],cycle_funding=[],maximum_fee='.003',slippage_bps='5')
    assert r['loss_stop_hit'] and D(r['estimated_exit_reserve'])==D('2.8')
    assert D(r['actual_net_before_unrealized'])==D('-.72')


def test_peak_drawdown_uses_tighter_loss_and_rejects_foreign_accounting():
    d=limits();r=marked_loss(d,prior_realized=50,prior_peak=20300,positions={},cycle_fills=[],cycle_funding=[],maximum_fee='.003',slippage_bps='5')
    assert r['loss_stop_hit'] and D(r['loss_with_exit_reserve'])==250
    f=Fill('par:BTC',NOW,'1','2','BUY',D(1),D(1),D(1),'USDPR',D(0))
    with pytest.raises(ExchangeError):marked_loss(d,prior_realized=0,prior_peak=20000,positions={},cycle_fills=[f],cycle_funding=[],maximum_fee='.003',slippage_bps='5')


def test_open_ws_bar_cannot_become_completed_by_clock_passage(tmp_path):
    f=PublicInfoFixture();c=HyperliquidClient(f,clock_ms=lambda:f.now);c.startup()
    e=ParMarketDataEngine(HyperliquidMarketData(c),['par:BTC']);start=f.now//60000*60000
    e.ingest(dict(channel='candle',data=candle_row(start)))
    f.now=start+60001
    assert e.get_completed_candles('par:BTC')==[]
    with pytest.raises(ExchangeError,match='POST_CLOSE'):validate_history('par:BTC',list(e.candles['par:BTC'].values()),f.now,1)
    e.ingest(dict(channel='candle',data=candle_row(start)))
    assert len(e.get_completed_candles('par:BTC'))==1


def test_completed_ws_rows_persist_deduplicate_and_conflicts_fail_closed(tmp_path):
    f=PublicInfoFixture();c=HyperliquidClient(f,clock_ms=lambda:f.now);c.startup()
    h=DurableHistory(tmp_path/'history.sqlite',c,tmp_path/'raw.jsonl');c.candle_audit=h
    e=ParMarketDataEngine(HyperliquidMarketData(c),['par:BTC']);start=f.now//60000*60000-60000
    row=candle_row(start);e.ingest(dict(channel='candle',data=row));e.ingest(dict(channel='candle',data=row))
    assert len(h.read('par:BTC',f.now))==1
    bad=deepcopy(row);bad['c']=bad['h'];bad['v']='999'
    assert e.ingest(dict(channel='candle',data=bad)) is False
    assert len(h.read('par:BTC',f.now))==1
    h.close()


@pytest.mark.parametrize('fault',['none','new_unknown','par_position','par_open','par_frontend','config_capability'])
def test_shared_guard_isolates_only_the_pinned_history_and_rechecks_live_exposure(tmp_path,monkeypatch,fault):
    from exchange.scored_session import require_shared_scope
    from exchange import terminal_evidence
    path,p=policy_fixture(tmp_path,monkeypatch);m=mandate(path);acceptance(path,p,m)
    cap=ti.FiniteTradingIsolation(tmp_path,path,m)
    unresolved=[dict(journal='qualification',cloid=ti.CLOID,state='UNKNOWN',intent_key=ti.INTENT)]
    if fault=='new_unknown':unresolved.append(dict(journal='pas',cloid='new',state='UNKNOWN',intent_key='new'))
    monkeypatch.setattr(terminal_evidence,'local_execution_state',lambda root:dict(status='BLOCKED_UNRESOLVED_INTENT',unresolved=unresolved))
    calls=[]
    def transport(payload):
        calls.append(payload)
        if payload['type']=='clearinghouseState':return dict(assetPositions=[dict(position=dict(szi='1'))] if fault=='par_position' else [])
        return [{}] if fault=='par_open' and payload['type']=='openOrders' or fault=='par_frontend' and payload['type']=='frontendOpenOrders' else []
    c=NS(dex='pas',clock_ms=lambda:NOW,transport=transport,rate_limits=NS(read=lambda kind,op,**kwargs:op()),read_cancel_event=None)
    if fault=='none':
        require_shared_scope(tmp_path,c,trading_isolation=cap)
        assert [x['type'] for x in calls]==['clearinghouseState','openOrders','frontendOpenOrders']
        assert all(x['dex']=='par' and x['user']==TEAM for x in calls)
    else:
        kwargs=dict(trading_isolation=cap)
        if fault=='config_capability':kwargs['configuration_isolation']=object()
        with pytest.raises(ExchangeError):require_shared_scope(tmp_path,c,**kwargs)


def test_no_approval_writer_works_noninteractively(tmp_path,monkeypatch):
    path,p=policy_fixture(tmp_path,monkeypatch);m=mandate(path)
    import exchange.long_session as long
    monkeypatch.setattr(long,'read_mandate',lambda _:m);monkeypatch.setattr(long,'require_release',lambda *a:None)
    monkeypatch.setattr(ti.time,'time_ns',lambda:NOW*1000000);monkeypatch.setattr(ti.sys.stdin,'isatty',lambda:False)
    with pytest.raises(ExchangeError,match='INTERACTIVE_HUMAN'):ti.approve(tmp_path,path,tmp_path/'mandate.json',tmp_path/'release.json')
    assert not path.with_name('acceptance.json').exists()


from test_pas_execution_faults import pas_bridge
from test_long_session import enter


def test_pas_marked_loss_stop_latches_and_never_blindly_retries(pas_bridge,monkeypatch):
    from live_execution_session import LiveExecutionSession
    b=pas_bridge;enter(b)
    b.live.fixture.state['assetPositions'][0]['position']['unrealizedPnl']='-11'
    calls=[]
    monkeypatch.setattr(b.session,'_close',lambda symbol,reason:calls.append((symbol,reason)))
    monkeypatch.setattr(LiveExecutionSession,'cycle',lambda self,**kwargs:kwargs)
    b.session.cycle(scan=True);b.session.cycle(scan=True)
    assert len(calls)==1 and calls[0][0]=='pas:BTC'
    assert b.daily.data['loss_stop_latched'] and b.daily.data['loss_stop_exit_attempted']
    assert b.live.executor.entries_paused


def test_stream_cache_read_never_holds_rest_lock_but_fallback_is_serialized(tmp_path,monkeypatch):
    from exchange.public_quant_operator import SerializedPublicClient,SerializedPublicMarket,SerializedStreamMarket
    f=PublicInfoFixture();c=SerializedPublicClient(f,clock_ms=lambda:f.now);c.startup()
    e=ParMarketDataEngine(SerializedPublicMarket(c),['par:BTC']);e.connected=e.reconciled=True
    market=SerializedStreamMarket(c,e);start=f.now//60000*60000-60000
    bar=replace(parse_candle(candle_row(start),'par:BTC','1m'),received_timestamp_ms=f.now)
    def cached(symbol):
        assert not c.request_lock._is_owned(), 'CACHE_AND_REST_LOCK_ORDER_INVERSION'
        return [bar]
    monkeypatch.setattr(e,'get_completed_candles',cached)
    assert market.get_candles('par:BTC',start,start,now_ms=f.now)==[bar]
    e.connected=False
    prior=c.transport
    def transport(payload):
        assert c.request_lock._is_owned(), 'REST_FALLBACK_MUST_REMAIN_SERIALIZED'
        return prior(payload)
    c.transport=transport
    assert market.get_candles('par:BTC',start,start,now_ms=f.now)


def test_sampled_intracycle_peak_survives_close_and_blocks_new_entry(pas_bridge):
    b=pas_bridge;enter(b);b.daily.data['sampled_peak']='1025'
    b.session._close('pas:BTC','Stop Loss Hit')
    assert D(b.daily.data['peak_equity'])==1025 and D(b.daily.data['drawdown'])>=25
    before=len(b.live.transport.signed_payloads)
    b.live.fixture.now+=60000  # A distinct real test candidate, not duplicate-ID rejection.
    try:enter(b)
    except ExchangeError:pass
    assert len(b.live.transport.signed_payloads)==before


@pytest.mark.parametrize('fault',['none','new_unknown','report_changed','revoked','report_boolean'])
def test_conditional_dispatch_requires_real_bound_isolation_and_preserves_unknown(tmp_path,monkeypatch,fault):
    from exchange.conditional_activation import WaitingAuthority,readiness_to_dispatch
    from exchange import terminal_evidence
    from test_activation_v5_2 import ready_report,NOW as OLD_NOW
    path,p=policy_fixture(tmp_path,monkeypatch);m=mandate(path);acceptance(path,p,m)
    cap=ti.FiniteTradingIsolation(tmp_path,path,m)
    def shift(value):
        if isinstance(value,dict):return {k:shift(v) for k,v in value.items()}
        if isinstance(value,list):return [shift(v) for v in value]
        return NOW if type(value) is int and value==OLD_NOW else value
    r=shift(ready_report());r['markets']=['pas:BTC']
    expected=[dict(journal='qualification',cloid=ti.CLOID,state='UNKNOWN',intent_key=ti.INTENT)]
    r['local_execution_state']=dict(status='BLOCKED_UNRESOLVED_INTENT',unresolved=deepcopy(expected))
    current=deepcopy(r['local_execution_state'])
    if fault=='new_unknown':current['unresolved'].append(dict(journal='pas',state='UNKNOWN',intent_key='other'))
    if fault=='report_changed':r['local_execution_state']['unresolved']=[]
    if fault=='revoked':path.with_name('revoked.json').write_text('{}')
    monkeypatch.setattr(terminal_evidence,'local_execution_state',lambda root:current)
    a=WaitingAuthority.__new__(WaitingAuthority);a.m=m;a.root=tmp_path;a.historical_isolation=cap;a.require=lambda:cap.require(NOW)
    if fault=='report_boolean':
        r['historical_isolation_verified']=True
        a=NS(m=m,require=lambda:None,historical_isolation=NS(require=lambda _:None))
    if fault=='revoked':
        with pytest.raises(ExchangeError):readiness_to_dispatch(r,a,NOW)
    else:assert readiness_to_dispatch(r,a,NOW)==(fault=='none')
    assert r['local_execution_state']['status']=='BLOCKED_UNRESOLVED_INTENT'
