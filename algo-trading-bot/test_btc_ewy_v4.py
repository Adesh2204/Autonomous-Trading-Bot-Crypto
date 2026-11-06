"""V4 policy and recovery regressions; no network, actual account or acceptance."""
from dataclasses import replace
from types import SimpleNamespace
from decimal import Decimal as D
import json,threading
import pytest
from exchange.base_exchange import ExchangeError
from exchange.entry_scope import PAS_ENTRY_MARKETS,require_entry,signal_markets,require_entry_action
from exchange.hyperliquid_market_data import HyperliquidMarketData,ParMarketDataEngine
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.sdk_transport import OfficialSDKTransport
from exchange.pas_configuration_plan import configuration_plan
from exchange.team_registration import registration_evidence
from exchange.long_session import sha
from exchange.durable_history import DurableHistory
from test_pas_migration import pas,isolated_pas_environment,scored
from test_pas_execution_faults import pas_bridge
from test_scored_opening_release import configuration_observation
from test_activation_v3 import client,bars,NOW


@pytest.mark.parametrize('symbol',['pas:ETH','pas:GOLD','pas:BRENT','pas:EWJ','pas:SP500','pas:USDEUR','pas:USDJPY','par:BTC','BTC','',None])
def test_v4_entry_scope_rejects_every_other_namespace(symbol):
    with pytest.raises(ExchangeError):require_entry(symbol)


@pytest.mark.parametrize('symbol',sorted(PAS_ENTRY_MARKETS))
def test_v4_scope_and_runtime_metadata_not_hardcoded(symbol):
    f,c,a=pas();require_entry(symbol)
    assert set(signal_markets(c))==PAS_ENTRY_MARKETS
    assert c.market(symbol).asset_id not in (2810000,2810004) # synthetic DEX index deliberately differs
    require_entry_action(c,dict(type='order',orders=[dict(a=c.market(symbol).asset_id,r=False)]))
    f.state['assetPositions'][0]['position']['coin']='pas:ETH'
    assert len(c.markets)==10 and 'pas:ETH' in a.get_positions()


@pytest.mark.parametrize('symbol',['pas:ETH','pas:SP500','pas:GOLD','pas:EWJ','pas:BRENT','pas:USDJPY','pas:USDEUR'])
def test_v4_actual_signer_boundary_blocks_unapproved_entries_before_any_signature(symbol):
    _,c,_=pas();t=object.__new__(OfficialSDKTransport);t.client=c
    for action in (dict(type='order',orders=[dict(a=c.market(symbol).asset_id,r=False)]),
            dict(type='batchModify',modifies=[dict(oid=1,order=dict(a=c.market(symbol).asset_id,r=False))])):
        with pytest.raises(ExchangeError,match='BTC_EWY'):t.check(action)
    # Scope alone does not prohibit a separately authorized reduce-only exit.
    require_entry_action(c,dict(type='order',orders=[dict(a=c.market(symbol).asset_id,r=True)]))


def test_v4_no_par_or_unknown_asset_entry_even_with_other_permits():
    _,c,_=pas()
    with pytest.raises(ExchangeError):require_entry_action(c,dict(type='order',orders=[dict(a=999,r=False)]))
    c.dex='par'
    with pytest.raises(ExchangeError):require_entry_action(c,dict(type='order',orders=[dict(a=c.market('pas:BTC').asset_id,r=False)]))


def test_v4_scanner_filters_before_unchanged_ranking_and_stream_history(monkeypatch):
    from market_regime_scanner import MarketRegimeScanner,ScannerPolicy
    _,c,_=pas();market=HyperliquidMarketData(c);calls=[]
    monkeypatch.setattr(market,'get_asset_contexts',lambda:{s:{} for s in c.markets})
    monkeypatch.setattr(market,'get_candles',lambda s,*a,**k:(calls.append(s) or []))
    scanner=MarketRegimeScanner(market,ScannerPolicy(D('.004'),D(15),D(0),D(0)),candidate_symbols=('pas:HYPE','pas:EWY','pas:BTC'))
    result=scanner.scan();assert calls==sorted(PAS_ENTRY_MARKETS) and len(result.diagnostics)==3
    assert scanner.policy.top_n==3 and scanner.policy.history_bars==300
    engine=ParMarketDataEngine(market)
    assert set(engine.symbols)==PAS_ENTRY_MARKETS
    assert {r['subscription']['coin'] for r in engine.subscriptions()}==PAS_ENTRY_MARKETS
    with pytest.raises(ExchangeError):ParMarketDataEngine(market,symbols=['pas:ETH'])


@pytest.mark.parametrize('symbol',sorted(PAS_ENTRY_MARKETS))
def test_v4_identical_candles_keep_identical_frozen_indicators(symbol):
    from frozen_strategy import FrozenStrategy
    import pandas as pd
    original=bars();adapted=[replace(b,symbol=symbol) for b in original]
    brain=FrozenStrategy(None)
    pd.testing.assert_frame_equal(brain.evaluate_candles(original),brain.evaluate_candles(adapted))


@pytest.mark.parametrize('symbol',['pas:ETH','par:BTC','BTC'])
def test_v4_exact_scored_mandate_rejects_scope_expansion(symbol):
    m=scored()
    with pytest.raises(ExchangeError):replace(m,daily=replace(m.daily,markets=(symbol,))).require()


def test_v4_targeted_configuration_preserves_full_account_evidence():
    o=configuration_observation();p=configuration_plan(o)
    assert set(p['entry_markets'])==PAS_ENTRY_MARKETS
    assert {x['symbol'] for x in p['changes']}==PAS_ENTRY_MARKETS and len(o['markets'])==10
    assert 'REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED' in p['blockers']
    o['markets'][0]['active_asset']['user']='wrong'
    with pytest.raises(ExchangeError):configuration_plan(o)


def test_v4_repair_cancellation_does_not_cancel_other_account_reads():
    from exchange.hyperliquid_client import HyperliquidClient
    c=HyperliquidClient(lambda r:[],venue='pas');global_stop=threading.Event();repair_stop=threading.Event();repair_stop.set()
    c.read_cancel_event=global_stop;entered=threading.Event();release=threading.Event();seen=[]
    def repair():
        with c.read_cancellation(repair_stop):
            seen.append(c.read_cancel_event);entered.set();release.wait(2)
        seen.append(c.read_cancel_event)
    t=threading.Thread(target=repair);t.start();assert entered.wait(2)
    assert c.read_cancel_event is global_stop and not c.read_cancel_event.is_set()
    release.set();t.join(2);assert seen==[repair_stop,global_stop]


@pytest.mark.parametrize('elapsed,reconciled,acks,expected',[(59999,True,True,5),(60000,False,True,5),(60000,True,False,5),(60000,True,True,0)])
def test_v4_reconnect_limit_counts_failures_since_stable_recovery(elapsed,reconciled,acks,expected):
    _,c,_=pas();e=ParMarketDataEngine(HyperliquidMarketData(c));e.consecutive_failures=5
    e.connected=True;e.reconciled=reconciled
    e.transport_health.begin(e.subscriptions());e.transport_health.current['connection_started_at_ms']=c.clock_ms()-elapsed
    if acks:e.transport_health.confirmed=set(e.transport_health.desired)
    e._reset_stable_failure_burst();assert e.consecutive_failures==expected


def test_v4_upstream_absence_requires_actual_normalized_current_reply(tmp_path):
    h=DurableHistory(tmp_path/'history.sqlite',client(),'OFFLINE_ONLY');b=bars(281,start=NOW-60000*600)
    h.ingest('pas:BTC',b,now_ms=NOW)
    assert h.report('pas:BTC',NOW)['failure_classification']=='DATA_NOT_READY_UNCONFIRMED_CAUSE'
    h.record('RAW_REST',request=dict(req=dict(coin='pas:BTC',interval='1m',startTime=NOW-300*60000,endTime=NOW-1)),response=[],received_ms=NOW)
    assert h.report('pas:BTC',NOW)['failure_classification']!='UPSTREAM_DATA_UNAVAILABLE'
    h.record('NORMALIZED_REST',symbol='pas:BTC',candles=[],as_of_ms=NOW,raw_count=0)
    v=h.report('pas:BTC',NOW);assert v['failure_classification']=='UPSTREAM_DATA_UNAVAILABLE'
    assert not v['warmup_satisfied'] and not v['data_freshness_satisfied']
    assert h.report('pas:BTC',NOW+180001)['failure_classification']!='UPSTREAM_DATA_UNAVAILABLE'
    assert len(h.read('pas:BTC',NOW))==281;h.close()


@pytest.mark.parametrize('fault',['absent','wrong_team','wrong_dex','wrong_hash','not_reviewed','expired','traversal'])
def test_v4_registration_never_inferred_from_funding_or_local_identity(tmp_path,fault):
    from exchange.testnet_certification import TEAM
    raw=tmp_path/'original.txt';raw.write_text('OFFLINE TEST ONLY; not organizer evidence')
    record=dict(original_record_file=raw.name,original_record_sha256=sha(raw),operator_reviewed_provenance=True,
        network='testnet',dex='pas',collateral='USDP',team_wallet=TEAM,source_reference='OFFLINE TEST',starts_ms=NOW-1,expires_ms=NOW+1)
    if fault=='wrong_team':record['team_wallet']='0xe590711084f687d278516f4882c075a862cd73cb'
    if fault=='wrong_dex':record['dex']='par'
    if fault=='wrong_hash':record['original_record_sha256']='a'*64
    if fault=='not_reviewed':record['operator_reviewed_provenance']=False
    if fault=='expired':record['expires_ms']=NOW
    if fault=='traversal':record['original_record_file']='../original.txt'
    if fault!='absent':(tmp_path/'organizer_confirmation.json').write_text(json.dumps(record))
    with pytest.raises(ExchangeError):registration_evidence(tmp_path,NOW)


@pytest.mark.parametrize('fault',['healthy','expired','revoked','unknown','stale_stream','paused'])
def test_v4_active_status_requires_current_capability_and_operational_guards(fault):
    from exchange.trading_status import authorized_status
    limits=SimpleNamespace(team_wallet='team',api_wallet='signer',markets=('pas:BTC',),expires_ms=NOW+1)
    def require(*args):
        if fault=='revoked':raise ExchangeError('REVOKED')
    execution=SimpleNamespace(daily=SimpleNamespace(state=SimpleNamespace(value='UNKNOWN' if fault=='unknown' else 'FLAT')),
        entries_paused=fault=='paused')
    runtime=SimpleNamespace(authorization=SimpleNamespace(m=SimpleNamespace(daily=limits),require=require),
        session=SimpleNamespace(execution=execution,account_stream=SimpleNamespace(healthy=True)),
        market_stream=SimpleNamespace(connected=fault!='stale_stream',reconciled=True))
    v=authorized_status(runtime,NOW+1 if fault=='expired' else NOW)
    assert (v['authorization_status']=='TRADING_AUTHORIZED')==(fault=='healthy')
    assert not v['renewal_permitted']


def test_v4_funding_and_fee_distortion_diagnostics_do_not_lower_policy():
    from exchange.pas_economics import fee_scenarios
    from exchange.base_exchange import OrderBook,BookLevel
    book=OrderBook('pas:EWY',NOW,(BookLevel(D(100),D(10)),),(BookLevel(D(101),D(10)),))
    v=fee_scenarios(book,dict(oraclePx='100',markPx='105',funding='0.1'),{},quantity=D(1),
        base_taker_rate='.00045',base_maker_rate='.00015',now_ms=NOW,context_ms=NOW)
    assert D(v['mark_oracle_divergence_bps'])==500 and D(v['hourly_funding'])==D('.1')
    assert D(v['stress_taker_roundtrip_fee'])==3*D(v['documented_taker_roundtrip_fee'])
    assert D(v['documented_maker_entry_taker_exit_fee'])<D(v['documented_taker_roundtrip_fee'])
    assert v['expected_net_pnl'] is None and not v['production_fee_policy_changed']


def test_v4_actual_pas_protection_clock_refresh_never_queries_par(pas_bridge,monkeypatch):
    from live_execution_session import LiveExecutionSession
    import exchange.live_readiness as readiness
    b=pas_bridge;calls=[];b.live.clock.observe(0,b.live.fixture.now,b.live.fixture.now)
    monkeypatch.setattr(readiness,'verify_live_account_readiness',lambda *a,**k:SimpleNamespace(account_ready=True))
    original=b.live.market.client.post_info
    def query(kind,**kw):
        calls.append((kind,kw));return original(kind,**kw)
    monkeypatch.setattr(b.live.market.client,'post_info',query)
    b.session._protection_barrier(allow_actions=True)
    assert any(kind=='l2Book' and kw.get('coin')=='pas:BTC' for kind,kw in calls)
    assert not any(str(kw.get('coin','')).startswith('par:') for _,kw in calls)


def test_v4_idle_pas_buying_power_refresh_never_queries_par():
    from live_execution_session import LiveExecutionSession
    calls=[];s=object.__new__(LiveExecutionSession)
    s.account_stream=None;s._account_barrier=lambda:None;s.observe=lambda q:None;s._performance=lambda value:None
    s.market=SimpleNamespace(client=SimpleNamespace(dex='pas'));s.clock_ms=lambda:NOW;s.quotes={}
    s.recovery=SimpleNamespace(state=SimpleNamespace(positions={}),account=SimpleNamespace(_query=lambda kind,**kw:(calls.append((kind,kw)) or {})))
    s.portfolio=SimpleNamespace(account_observed_ms=None,observe_buying_power=lambda *a:None,snapshot=lambda *a:None)
    s.cycle(scan=False)
    assert calls[0][1]['coin']=='pas:BTC'


def test_v4_actual_pas_result_manifest_uses_pas_usdp_and_two_market_scope(pas_bridge,tmp_path,monkeypatch):
    from live_session_results import LiveSessionResults
    for key,value in {'GIT_CONFIG_COUNT':'3','GIT_CONFIG_KEY_0':'filter.lfs.process','GIT_CONFIG_VALUE_0':'',
        'GIT_CONFIG_KEY_1':'filter.lfs.clean','GIT_CONFIG_VALUE_1':'cat','GIT_CONFIG_KEY_2':'filter.lfs.required','GIT_CONFIG_VALUE_2':'false'}.items():monkeypatch.setenv(key,value)
    w=LiveSessionResults(tmp_path/'pas-results',pas_bridge.session)
    v=json.loads((w.path/'session_manifest.json').read_text())
    assert v['dex']=='pas' and v['collateral']=='USDP'
    from exchange.execution_journal import fingerprint,safe_data
    from exchange.venue_profiles import SCORED
    assert v['venue_identity']==v['configuration']['venue_identity']==SCORED.identity
    assert v['configuration_hash']==fingerprint(v['configuration'])
    assert safe_data(dict(venue_identity=SCORED.identity,private_key='a'*64,signature='b'*64))==dict(venue_identity=SCORED.identity)
    assert v['configuration']['dex']=='pas' and set(v['configuration']['entry_markets'])==PAS_ENTRY_MARKETS
    assert len(v['configuration']['account_reconciliation_markets'])==10 and v['execution_mode']=='OFFLINE_SIGNED_FIXTURE'


def test_v4_pas_opportunity_trace_does_not_claim_invalid_market():
    from opportunity_funnel import OpportunityFunnel
    from market_regime_scanner import ScanResult,MarketDiagnostic,ScannerPolicy
    p=ScannerPolicy(D('.004'),D(15),D(0),D(0));f=OpportunityFunnel()
    d=MarketDiagnostic('pas:BTC',reasons=['INSUFFICIENT_COMPLETED_HISTORY'])
    f.observe_scan(ScanResult(NOW,[d],[],'FAILED_SAFE'),p)
    t=next(iter(f.traces.values()))
    assert t['stages']['VALID_MARKET_IDENTITY']['status']=='PASS' and t['session_context']=='CONTINUOUS_CRYPTO'
