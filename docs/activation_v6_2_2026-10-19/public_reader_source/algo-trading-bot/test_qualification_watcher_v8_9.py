"""V8.9 public watcher/qualification integration. Synthetic inputs; no real signing."""
from dataclasses import asdict, replace
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import importlib.util
import json
import sqlite3
import threading
import time
import pytest

from exchange.base_exchange import BookLevel, OrderBook, MarketSpec, ExchangeError
from exchange.qualification_watcher import (inspect_book, sweep, research_residuals, PublicBookStream,
    PublicBookReader, OpportunityGate, ReadOnlyQualificationSession, durable_readback)
from exchange.testnet_qualification import QualificationContextProvider, QualificationProposal, check_entry
from exchange.certification_runtime import CertificationRecovery
from exchange.order_lifecycle import OrderRequest
from test_testnet_qualification import qualification
from test_live_exchange_execution import live
from test_qualification_recovery_v8_7 import launcher
from test_exchange_migration import NOW


SPEC = MarketSpec('par:BTC', 4, 50, 2670000)


def book(bid_quantity='.0041', ask_quantity='.0025', *, symbol='par:BTC', stamp=NOW):
    return OrderBook(symbol, stamp, (BookLevel(D(83314), D(bid_quantity)),),
                     (BookLevel(D(83431), D(ask_quantity)),), NOW, NOW)


@pytest.mark.parametrize('bid,ask,quantity,ready',[
    ('.0041','.0025','.0002',True),('.0041','.0301','.0002',True),
    ('.0003','.03','0.0000',False),('.0041','.0002','0.0000',False),
    ('.0019','.03','.0001',False),('.0041','.0019','.0001',False)])
def test_strict_bbo_depth_and_opening_minimum(bid,ask,quantity,ready):
    r=inspect_book(SPEC,book(bid,ask),NOW)
    assert r['potential'] is ready
    assert D(r['maximum_book_quantity'])==D(quantity)
    assert D(r['minimum_valid_entry_quantity'])==D('.0002')
    assert D(r['minimum_entry_notional'])>=10
    assert D(r['maximum_book_notional'])<=25
    assert not r['account_checks_performed'] and not r['protection_verified']


@pytest.mark.parametrize('age',[-1,5001,60000])
def test_stale_or_future_book_never_potential(age):
    r=inspect_book(SPEC,book(stamp=NOW-age),NOW)
    assert not r['potential'] and r['blocker']=='WRONG_OR_STALE_BOOK'


def test_wrong_symbol_not_accepted():
    assert not inspect_book(SPEC,book(symbol='par:ETH'),NOW)['potential']


@pytest.mark.parametrize('kind',['empty_bid','empty_ask','zero_size','crossed','duplicate','unsorted'])
def test_malformed_book_has_no_candidate(kind):
    b=book()
    if kind=='empty_bid':b=replace(b,bids=())
    if kind=='empty_ask':b=replace(b,asks=())
    if kind=='zero_size':b=book('0')
    if kind=='crossed':b=replace(b,asks=(BookLevel(D(80000),D(1)),))
    if kind=='duplicate':b=replace(b,bids=b.bids*2)
    if kind=='unsorted':b=replace(b,bids=b.bids+(BookLevel(D(84000),D(1)),))
    assert not inspect_book(SPEC,b,NOW)['potential']


def test_multilevel_liquidity_is_research_never_silent_eligibility():
    b=book(ask_quantity='.0002')
    b=replace(b,asks=b.asks+(BookLevel(D(83440),D('.02')),BookLevel(D(83500),D(100))))
    r=inspect_book(SPEC,b,NOW)
    assert not r['potential']
    research=r['l2_research']
    assert research['aggregate_can_meet_minimum'] and not research['affects_eligibility']
    assert D(research['entry']['available_quantity'])==D('.0202')
    assert research['separate_policy_approval_required']
    assert r['blocker']=='QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS'


@pytest.mark.parametrize('side,prices,limit,cost,shortfall',[
    ('BUY',[10,11,12],11,'15.75','.5'),('SELL',[12,11,10],11,'17.25','.5')])
def test_sweep_honors_limit_prices(side,prices,limit,cost,shortfall):
    levels=tuple(BookLevel(D(p),D('.75')) for p in prices)
    r=sweep(levels,D(2),D(limit),side)
    assert D(r['cost'])==D(cost)
    assert D(r['shortfall'])==D(shortfall)


@pytest.mark.parametrize('symbol,dec,asset,price',[
    ('par:ETH',4,2670001,'2500'),('par:HYPE',2,2670002,'82')])
def test_eth_hype_liquid_long_still_rejected_for_tiny_sell_residual(symbol,dec,asset,price):
    price=D(price)
    b=OrderBook(symbol,NOW,(BookLevel(price,D(100)),),(BookLevel(price*D('1.001'),D(100)),))
    r=inspect_book(MarketSpec(symbol,dec,50,asset),b,NOW)
    assert r['blocker']=='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL'
    assert r['residuals']['close_side']=='SELL' and not r['potential']


def test_btc_short_has_opposite_close_evidence_but_no_execution_permission():
    r=inspect_book(SPEC,book(),NOW,'SELL')
    assert r['residuals']['ready'] and r['residuals']['close_side']=='BUY'
    assert r['blocker']=='SEPARATE_DIRECTION_OR_MARKET_APPROVAL_REQUIRED'
    assert not r['potential']


@pytest.mark.parametrize('side', ['BUY','SELL'])
def test_all_possible_btc_residuals_checked(side):
    r=research_residuals(SPEC,D('.0002'),D(82000),side)
    assert r['ready'] and r['possible_residual_count']==2 and len(r['historical_shapes'])==1
    assert not r['future_acceptance_guaranteed'] and not r['protective_stop_verified']


def test_one_historical_eth_buy_does_not_verify_two_lot_residual():
    spec=MarketSpec('par:ETH',4,50,2670001)
    assert research_residuals(spec,D('.0001'),D(2500),'BUY')['ready']
    r=research_residuals(spec,D('.0002'),D(2500),'BUY')
    assert not r['ready'] and D(r['first_unverified_quantity'])==D('.0002')


@pytest.mark.parametrize('change',[{'asset_id':2670040},{'size_decimals':5}])
def test_metadata_identity_change_cannot_reuse_historical_close(change):
    r=inspect_book(replace(SPEC,**change),book(),NOW)
    assert not r['potential'] and r['blocker']=='QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL'


def test_residual_analysis_is_bounded():
    assert not research_residuals(SPEC,D(2),D(100),'SELL')['ready']


def stream_fixture(live):
    stream=PublicBookStream(['par:BTC','par:ETH'],live.rate,clock_ms=lambda:live.fixture.now)
    generation,subs=stream.begin()
    for sub in subs:
        stream.health.subscription_sent(sub['subscription'])
        stream.ingest(dict(channel='subscriptionResponse',data=sub),generation)
    return stream,generation


def message(symbol='par:BTC',stamp=NOW):
    return dict(channel='l2Book',data=dict(coin=symbol,time=stamp,
        levels=[[dict(px='83314',sz='.0041')],[dict(px='83431',sz='.0025')]]))


def test_ws_needs_ack_and_distinct_repeated_actual_updates(live):
    s=PublicBookStream(['par:BTC'],live.rate,clock_ms=lambda:live.fixture.now)
    gen,subs=s.begin()
    s.ingest(message(),gen);assert s.snapshot('par:BTC') is None
    s.ingest(dict(channel='subscriptionResponse',data=subs[0]),gen)
    s.ingest(message(),gen);s.ingest(message(),gen)
    assert s.snapshot('par:BTC') is None
    live.fixture.now+=1;s.ingest(message(stamp=live.fixture.now),gen)
    assert s.snapshot('par:BTC') is not None
    assert s.report()['confirmed_count']==1


def test_ws_reconnect_invalidates_books_and_requires_new_acks(live):
    s,gen=stream_fixture(live);s.ingest(message(),gen)
    live.fixture.now+=1;s.ingest(message(stamp=live.fixture.now),gen)
    assert s.snapshot('par:BTC')
    s.disconnect('OFFLINE_DISCONNECT');assert s.snapshot('par:BTC') is None
    newgen,subs=s.begin();s.ingest(message(stamp=live.fixture.now),gen)
    assert s.snapshot('par:BTC') is None
    assert not s.report()['confirmed_count'] and newgen!=gen


def test_stale_symbol_does_not_close_other_public_markets(live):
    s,gen=stream_fixture(live)
    s.ingest(message(),gen);live.fixture.now+=1;s.ingest(message(stamp=live.fixture.now),gen)
    bad=message('par:ETH',live.fixture.now);bad['data']['levels'][1]=[]
    s.ingest(bad,gen)
    assert s.snapshot('par:BTC') and s.snapshot('par:ETH') is None
    assert s.report()['current_market_errors']['par:ETH']['reason']=='NO_EXECUTABLE_TWO_SIDED_BOOK'


def test_ws_old_books_expire_even_if_socket_is_connected(live):
    s,gen=stream_fixture(live);s.ingest(message(),gen)
    live.fixture.now+=1;s.ingest(message(stamp=live.fixture.now),gen)
    live.fixture.now+=5001
    assert s.snapshot('par:BTC') is None


def test_unexpected_ws_subscription_is_rejected(live):
    s,gen=stream_fixture(live)
    with pytest.raises(ExchangeError,match='UNEXPECTED_SUBSCRIPTION_ACK'):
        s.ingest(dict(channel='subscriptionResponse',data=dict(method='subscribe',
            subscription=dict(type='l2Book',coin='BTC'))),gen)


def test_no_plain_market_ws_subscription(live):
    with pytest.raises(ExchangeError,match='PAR_PUBLIC'):
        PublicBookStream(['BTC'],live.rate,clock_ms=lambda:NOW)


def test_rest_fallback_is_paced_and_never_reads_account(live):
    live.client.rate_limits=live.rate
    tick=[0];reader=PublicBookReader(live.market,monotonic=lambda:tick[0])
    before=len(live.fixture.calls)
    for _ in range(20):reader.get('par:BTC')
    assert [x['type'] for x in live.fixture.calls[before:]]==['l2Book']
    tick[0]=5;reader.get('par:BTC')
    assert [x['type'] for x in live.fixture.calls[before:]]==['l2Book','l2Book']


def test_ws_startup_grace_then_rest_fallback(live):
    live.client.rate_limits=live.rate
    tick=[0];s,_=stream_fixture(live)
    reader=PublicBookReader(live.market,s,monotonic=lambda:tick[0]);before=len(live.fixture.calls)
    assert reader.get('par:BTC')[1]=='WS_STARTUP_GRACE'
    assert len(live.fixture.calls)==before
    tick[0]=10;assert reader.get('par:BTC')[1]=='RATE_LIMITED_REST'


def test_healthy_ws_avoids_rest(live):
    s,gen=stream_fixture(live);s.ingest(message(),gen)
    live.fixture.now+=1;s.ingest(message(stamp=live.fixture.now),gen)
    before=len(live.fixture.calls)
    reader=PublicBookReader(live.market,s)
    assert reader.get('par:BTC')[1]=='WS_ACKNOWLEDGED_REPEATED'
    assert len(live.fixture.calls)==before


@pytest.mark.parametrize('reason',['INFO_HTTP_429','INFO_PUBLIC_RATE_LIMITED','INFO_READ_TIMEOUT'])
def test_rest_failure_drops_cached_book_and_does_not_spin(live,monkeypatch,reason):
    live.client.rate_limits=live.rate
    tick=[0];reader=PublicBookReader(live.market,monotonic=lambda:tick[0]);reader.get('par:BTC')
    calls=[]
    def fail(symbol):calls.append(symbol);raise ExchangeError(reason)
    monkeypatch.setattr(live.market,'get_orderbook',fail)
    tick[0]=5
    for _ in range(10):assert reader.get('par:BTC')[0] is None
    assert calls==['par:BTC'] and reader.errors[-1]['reason']==reason


def test_public_budget_preserves_safety_reserve(live):
    live.client.rate_limits=live.rate
    live.rate.weights=[(NOW,1080)]
    reader=PublicBookReader(live.market);before=len(live.fixture.calls)
    assert reader.get('par:BTC')[0] is None
    assert len(live.fixture.calls)==before and live.rate._usage()==1080


def test_429_guidance_blocks_fallback_until_retry_after(live):
    live.client.rate_limits=live.rate
    live.rate.error(status=429,retry_after_ms=90000)
    reader=PublicBookReader(live.market);before=len(live.fixture.calls)
    assert reader.get('par:BTC')[0] is None
    assert len(live.fixture.calls)==before and live.rate.backoff_until>=NOW+90000


def test_gate_cooldown_distinct_books_and_attempt_bound():
    clock=[0];gate=OpportunityGate(monotonic=lambda:clock[0])
    row=inspect_book(SPEC,book(),NOW)
    assert gate.claim(row)
    assert not gate.claim(dict(row,exchange_ms=NOW+1))
    clock[0]=60;assert not gate.claim(row)
    assert gate.claim(dict(row,exchange_ms=NOW+1))
    clock[0]=120;assert not gate.claim(dict(row,exchange_ms=NOW+2))


def test_no_opportunity_never_calls_full_validator():
    gate=OpportunityGate();r=inspect_book(SPEC,book(ask_quantity='.0002'),NOW)
    assert all(not gate.claim(r) for _ in range(100)) and gate.attempts==0


def fast_fixture(c,tmp_path,monkeypatch):
    import exchange.qualification_watcher as mod
    live=c.live
    s=ReadOnlyQualificationSession.__new__(ReadOnlyQualificationSession)
    s.root=tmp_path;s.directory=tmp_path
    s.source_hash='fixture-source';s.policy_hash='fixture-policy'
    s.client,s.market,s.account=live.client,live.market,live.account
    s.journal,s.rates,s.clock=live.journal,live.rate,live.clock
    s.recovery=c.live.executor.recovery
    s.reconciliation_calls=0;s.identity=None;s.attempt_reports=[]
    s.progress=lambda *a,**k:None
    s.verify_signer=lambda:None
    s.provider=QualificationContextProvider(s.market,s.account,live.signer.address,s.clock,s.rates,
        reconcile_before_load=s._reconcile,reconciliation_ready=lambda:s.recovery.account_truth_ready,
        feed_ready=lambda:True)
    monkeypatch.setattr(mod,'durable_readback',lambda *a,**k:dict(integrity='ok'))
    live.rate.weights=[]
    return s


def test_fast_validation_reconciles_once_not_three_markets(qualification,tmp_path,monkeypatch):
    c=qualification;s=fast_fixture(c,tmp_path,monkeypatch)
    before=len(c.live.fixture.calls);r=s.validate('par:BTC')
    assert r['eligible_for_risk_review'],r
    assert r['reconciliation_calls']==1
    calls=c.live.fixture.calls[before:]
    assert {q.get('coin') for q in calls if q['type']=='l2Book'}=={'par:BTC'}
    assert len([q for q in calls if q['type']=='userFunding'])==1
    assert not c.live.transport.signed_payloads and r['final_positions']==[]


def test_liquidity_disappearing_after_stage_a_cannot_publish(qualification,tmp_path,monkeypatch):
    c=qualification;s=fast_fixture(c,tmp_path,monkeypatch)
    assert inspect_book(SPEC,book(),NOW)['potential']
    c.live.fixture.book['levels'][1][0]['sz']='.0002'
    r=s.validate('par:BTC')
    assert not r['eligible_for_risk_review'] and 'proposal' not in r
    assert r['blocker']=='QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS'
    assert not c.live.transport.signed_payloads


@pytest.mark.parametrize('kind',['position','order'])
def test_fast_account_reconciliation_rejects_unexpected_exposure(qualification,tmp_path,monkeypatch,kind):
    c=qualification;s=fast_fixture(c,tmp_path,monkeypatch)
    if kind=='position':c.live.fixture.position('.0001','82672')
    else:c.live.fixture.orders=[dict(coin='par:BTC',oid=444,side='B',limitPx='80000',sz='.0001',timestamp=NOW)]
    r=s.validate('par:BTC')
    assert not r['eligible_for_risk_review'] and 'proposal' not in r
    expected='QUALIFICATION_FRESH_FLAT_ACCOUNT_BOOK_REQUIRED' if kind=='position' else 'QUALIFICATION_DURABLE_RECONCILIATION_REQUIRED'
    assert r['blocker']==expected


def test_durable_readback_does_not_reconcile_or_reopen_writer(qualification):
    c=qualification;recovery=c.live.executor.recovery;recovery.recover();recovery.checkpoint(clean=True)
    path=c.live.journal.db.execute('PRAGMA database_list').fetchone()[2]
    before=len(c.live.fixture.calls)
    r=durable_readback(path,recovery.source,clean=True)
    assert r['integrity']=='ok' and r['snapshots_verified']==2 and r['clean']
    assert not any(r['actions'].values()) and len(c.live.fixture.calls)==before


@pytest.mark.parametrize('kind',['checksum','source','unclean'])
def test_durable_readback_fails_on_corruption(qualification,kind):
    c=qualification;r=c.live.executor.recovery;r.recover();r.checkpoint(clean=True)
    path=c.live.journal.db.execute('PRAGMA database_list').fetchone()[2]
    source=r.source
    if kind=='checksum':
        with c.live.journal.db:c.live.journal.db.execute("UPDATE recovery_snapshots SET checksum='bad'")
    if kind=='source':source={'wrong':'source'}
    if kind=='unclean':r.checkpoint(clean=False)
    with pytest.raises(ExchangeError):durable_readback(path,source,clean=True)


def test_failed_rereview_clears_current_candidate_but_preserves_history():
    mod=launcher();row=dict(symbol='par:BTC',eligible_for_risk_review=True,proposal={'old':True},
        proposal_hash='old',central_validation={'allowed':True},sizing={'ready':True},
        residual_close_scope={'ready':True},quote={'old':True},initial_review={'historical':True})
    mod.clear_candidate(row)
    assert row==dict(symbol='par:BTC',eligible_for_risk_review=False,initial_review={'historical':True})


def handoff(c,tmp_path):
    from exchange.testnet_qualification import find_largest_safe_qualification_quantity
    from test_qualification_recovery_v8_7 import context
    mod=launcher();ctx=context(c)
    sizing=find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    row=dict(symbol='par:BTC',proposal=sizing['proposal'],sizing=sizing,spread_bps='48',
             residual_close_scope=sizing['residual_close_scope'])
    report=dict(candidates=[row],test_receipt=str(tmp_path/'test_receipt.json'))
    mod.publish_proposal(report,row,c.live.client,tmp_path)
    return mod,report


def test_proposal_artifacts_leave_all_approval_fields_unfilled(qualification,tmp_path):
    mod,r=handoff(qualification,tmp_path)
    a=json.loads((tmp_path/'approval_REQUIRED_UNFILLED.json').read_text())
    assert a['operator_approval']=='' and a['approved_ms'] is None and a['expires_ms'] is None
    assert all(a[x] is False for x in ['manually_verified_wallets','sole_signer_host_confirmed',
        'maximum_one_entry','unverified_stop_risk_accepted','qualification_spread_limit_accepted',
        'possible_manual_residual_recovery_accepted'])
    summary=mod.preparation_summary(r,tmp_path,now_ms=NOW)
    assert summary['proposal_file']==str(tmp_path/'proposal.json')
    assert '--operator-approval-file' in summary['execution_command']
    assert '--execute' in summary['execution_command'] and not summary['actual_order_authorization_supplied']
    assert not qualification.live.transport.signed_payloads


def test_operator_handoff_expiry_does_not_extend_proposal(qualification,tmp_path):
    mod,r=handoff(qualification,tmp_path)
    before=(tmp_path/'proposal.json').read_bytes()
    summary=mod.preparation_summary(r,tmp_path,now_ms=NOW+300001)
    assert summary['status']=='PROPOSAL_EXPIRED' and (tmp_path/'proposal.json').read_bytes()==before


def test_changed_quote_still_blocks_at_signed_boundary(qualification):
    c=qualification;c.live.fixture.book['levels'][1][0]['sz']='.0002'
    r=c.sequence.run()
    assert r['status']=='EMERGENCY_EXIT_REQUIRED' and not c.venue.calls,r
    assert not r.get('actual_fill_verified',False)
    assert not c.live.transport.signed_payloads


def test_short_research_cannot_become_execution_proposal(qualification):
    with pytest.raises(ExchangeError,match='INVALID_QUALIFICATION_PROPOSAL'):
        replace(qualification.p,entry_side='SELL').require()


def test_expired_approval_still_blocks_execution(qualification):
    c=qualification;c.live.fixture.now=NOW+300001
    r=c.sequence.run()
    assert r['status']=='PREFLIGHT_BLOCKED' and not c.venue.calls


@pytest.mark.parametrize('partial',['0','.3333333333333333','1'])
def test_watcher_does_not_change_existing_one_entry_and_partial_exit_contract(qualification,partial):
    c=qualification;c.venue.partial_entry=D(partial)
    r=c.sequence.run()
    entries=[a for a in c.venue.calls if not a['orders'][0]['r']]
    assert len(entries)==1
    if D(partial)==0:
        assert not r.get('actual_fill_verified',False)
    else:
        assert r['final_flat'] and not r['protection_accepted']
    from exchange.testnet_qualification import QualificationSequence
    calls=len(c.venue.calls);again=QualificationSequence(c.live.executor,c.p,c.auth).run()
    assert again['status']=='PREFLIGHT_BLOCKED' and len(c.venue.calls)==calls


def test_receiver_can_be_stopped_without_account_or_signatures(live):
    import websocket
    entered=threading.Event()
    class Socket:
        def settimeout(self,x):pass
        def send(self,x):assert json.loads(x)['method'] in {'subscribe','ping'}
        def recv(self):entered.set();time.sleep(.005);raise websocket.WebSocketTimeoutException()
        def close(self):pass
    s=PublicBookStream(['par:BTC'],live.rate,clock_ms=lambda:live.fixture.now,connect=Socket)
    before=len(live.fixture.calls);s.start();assert entered.wait(1);s.close()
    assert not s.thread.is_alive() and not live.rate.ws_connections
    assert len(live.fixture.calls)==before and not live.transport.signed_payloads


def test_real_readonly_session_constructor_and_durable_close(qualification,tmp_path,monkeypatch):
    import exchange.hyperliquid_client as client_module
    real_client=client_module.HyperliquidClient
    c=qualification
    def client(**kwargs):
        return real_client(transport=c.live.fixture,clock_ms=lambda:c.live.fixture.now,**kwargs)
    monkeypatch.setattr(client_module,'HyperliquidClient',client)
    root=Path(__file__).resolve().parents[1];progress=[]
    s=ReadOnlyQualificationSession(root,tmp_path,'fixture-source','fixture-policy',
        progress=lambda event,**kw:progress.append(event),cancel_event=threading.Event())
    try:
        s.start();s.root=tmp_path;monkeypatch.setattr(s,'verify_signer',lambda:None)
        r=s.validate('par:BTC')
        assert r['eligible_for_risk_review'] and s.reconciliation_calls==1,r
        assert r['checkpoint']['snapshots_verified']==1
        assert s.rates.read_counts['userFunding']==1
    finally:s.close()
    assert s.cleanup['snapshots_verified']==2 and s.cleanup['clean']
    assert not any(s.cleanup['actions'].values())
    assert progress.count('REFRESHING_ACCOUNT')==1 and progress.count('CHECKING_RESIDUAL_EXITS')==1


def watch_launcher():
    import sys
    root=Path(__file__).resolve().parents[1]
    if str(root/'scripts') not in sys.path:sys.path.insert(0,str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('offline_watcher_cli',root/'scripts/watch_testnet_qualification.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def test_watch_stops_at_unfilled_proposal_with_current_paths(qualification,tmp_path,monkeypatch):
    from exchange.testnet_qualification import find_largest_safe_qualification_quantity
    from test_qualification_recovery_v8_7 import context
    c=qualification;mod=watch_launcher();ctx=context(c)
    sizing=find_largest_safe_qualification_quantity(ctx,c.live.client,'fixture-source','fixture-policy')
    row=dict(symbol='par:BTC',eligible_for_risk_review=True,sizing=sizing,proposal=sizing['proposal'],
        spread_bps='48',residual_close_scope=sizing['residual_close_scope'],final_positions=[],final_orders=[],
        final_reconciliation={'ready':True},account_observed_ms=NOW)
    class Session:
        def __init__(self,*args,**kwargs):
            self.client=SimpleNamespace(markets={'par:BTC':SPEC},clock_ms=lambda:NOW,market=lambda s:SPEC)
            self.market=None;self.identity={'offline':True};self.reconciliation_calls=0
            self.rates=SimpleNamespace(report=lambda:{})
        def start(self):pass
        def validate(self,symbol):self.reconciliation_calls+=1;return row
        def close(self):self.cleanup={'clean':True}
    class Reader:
        errors=[]
        def __init__(self,*args):pass
        def get(self,symbol):return book(),'SYNTHETIC_TEST_ONLY'
    monkeypatch.setattr(mod,'ReadOnlyQualificationSession',Session)
    monkeypatch.setattr(mod,'PublicBookReader',Reader)
    monkeypatch.setattr(mod,'source_unchanged',lambda *a:None)
    monkeypatch.setattr(mod,'current_test_receipt',lambda *a:tmp_path/'offline_receipt.json')
    monkeypatch.setattr(mod,'PaperOwner',lambda *a:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(mod.time,'time_ns',lambda:NOW*1000000)
    out=tmp_path/'watch'
    r=mod.watch(out,duration_seconds=10,transport='rest')
    assert r['status']=='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED',r
    assert r['full_opportunity_attempts']==1 and r['reconciliation_calls']==1
    handoff=json.loads((out/'operator_handoff.json').read_text())
    assert handoff['qualification_state']=='AWAITING_HUMAN_APPROVAL'
    assert Path(handoff['proposal_file']).exists() and Path(handoff['approval_template']).exists()
    assert not handoff['actual_order_authorization_supplied'] and not c.venue.calls
    assert not (out/'WHITELIST_TRADE_PROOF.json').exists()


def test_cli_rejects_unbounded_duration_before_network(tmp_path):
    mod=watch_launcher()
    with pytest.raises(ExchangeError,match='INVALID_BOUNDED_WATCH_ARGUMENTS'):
        mod.watch(tmp_path/'out',duration_seconds=3601)
    assert not (tmp_path/'out').exists()


def test_watcher_restart_requires_fresh_output_directory(tmp_path):
    mod=watch_launcher();out=tmp_path/'existing';out.mkdir();(out/'prior.json').write_text('proof')
    with pytest.raises(FileExistsError):mod.watch(out,duration_seconds=10)
    assert (out/'prior.json').read_text()=='proof'


def test_durable_readback_detects_detached_account_checkpoint(qualification):
    c=qualification;recovery=c.live.executor.recovery;recovery.recover()
    with c.live.journal.db:c.live.journal.db.execute("UPDATE account_checkpoint SET data='{}'")
    with pytest.raises(ExchangeError,match='CHECKPOINT_ACCOUNT_MISMATCH'):
        durable_readback(c.live.journal.path,recovery.source)


@pytest.mark.parametrize('name,kind,expected',[
    ('certification.sqlite','UNKNOWN','PRIOR_CERTIFICATION_UNRESOLVED_REVIEW_REQUIRED'),
    ('qualification.sqlite','REJECTED','QUALIFICATION_PRIOR_ATTEMPT_READ_ONLY_RECOVERY_REQUIRED'),
    ('qualification.sqlite','CONSUMED','QUALIFICATION_PRIOR_ATTEMPT_READ_ONLY_RECOVERY_REQUIRED')])
def test_restart_history_cannot_authorize_new_candidate(tmp_path,name,kind,expected):
    from exchange.qualification_watcher import prior_execution_check
    from exchange.execution_journal import ExecutionJournal
    from test_exchange_migration import TEAM
    path=tmp_path/'runtime/testnet/anchorium-bot-1'/name
    journal=ExecutionJournal(path,session_id='offline',team_address=TEAM)
    try:
        if kind=='CONSUMED':journal.control('qualification_entry_consumed','old-hash')
        else:
            with journal.db:
                journal.db.execute('INSERT INTO intents VALUES (?,?,?,?,?,?,?,?,?,?)',
                    ('one','cloid','fingerprint','{}','candidate',kind,None,None,NOW,NOW,))
        with pytest.raises(ExchangeError,match=expected):prior_execution_check(tmp_path)
    finally:journal.close()


def test_empty_prior_execution_files_are_not_created_by_read_check(tmp_path):
    from exchange.qualification_watcher import prior_execution_check
    assert prior_execution_check(tmp_path)=={'certification.sqlite':{'exists':False},'qualification.sqlite':{'exists':False}}
    assert not (tmp_path/'runtime').exists()
