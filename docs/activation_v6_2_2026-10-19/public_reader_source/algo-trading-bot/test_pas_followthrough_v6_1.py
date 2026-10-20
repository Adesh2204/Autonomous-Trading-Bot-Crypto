"""V6.1 read-only ranking and unaccepted isolation design, no HTTP or signer."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from decimal import Decimal as D
import json
import pytest
from exchange.base_exchange import ExchangeError
from exchange.entry_scope import PAS_ENTRY_MARKETS,require_entry
from exchange.public_quant_operator import SerializedPublicClient,ReadOnlyReceipts,SerializedPublicMarket
from exchange.pas_opportunity_ranking import ReadOnlyPasRankingScanner,ranking_report
from exchange.trading_isolation_review import propose
from exchange.venue_profiles import SCORED
from market_regime_scanner import MarketRegimeScanner,ScannerPolicy,MarketDiagnostic,ScanResult
from test_pas_migration import PasFixture,isolated_pas_environment
from test_post_funding_v6 import proof,seal,SOURCE,NOW


def result():
    rows=[MarketDiagnostic(s,qualified=i<3,score=D(i)/10,
        metrics=dict(atr_fraction=D('.005')),signal=dict(long=i==0,short=False),
        evidence=dict(scanner_rank=i+1) if i<3 else {},reasons=[] if i<3 else ['NO_SETUP'])
        for i,s in enumerate(sorted(SCORED.markets))]
    return ScanResult(NOW,rows,[r.symbol for r in rows[:3]],'ACTIVE')


def scanner(tmp_path):
    f=PasFixture();f.close=lambda:None
    c=SerializedPublicClient(ReadOnlyReceipts(f,tmp_path/'raw.jsonl'),clock_ms=lambda:f.now,venue='pas');c.startup()
    s=ReadOnlyPasRankingScanner(SerializedPublicMarket(c),ScannerPolicy(D('.004'),D(15),D(0),D(0)))
    return f,c,s


def test_observation_selects_all_ten_but_production_still_selects_btc_ewy(tmp_path):
    f,c,s=scanner(tmp_path)
    try:
        assert set(s.selected_markets())==SCORED.markets
        production=MarketRegimeScanner(s.market,s.policy)
        assert set(production.selected_markets())==PAS_ENTRY_MARKETS
        assert (s.policy.min_atr_fraction,s.policy.max_spread_bps,s.policy.history_bars,s.policy.top_n)==(D('.004'),D(15),300,3)
        for name in SCORED.markets-PAS_ENTRY_MARKETS:
            with pytest.raises(ExchangeError):require_entry(name)
    finally:c.close()


@pytest.mark.parametrize('fault',['auth','team','signer','client_type','transport','missing','candidate_subset'])
def test_ranking_rejects_authority_and_ambiguous_market_scope(tmp_path,fault):
    f,c,s=scanner(tmp_path)
    try:
        if fault=='auth':s.live_authorization=object()
        elif fault=='team':s.team_address='team'
        elif fault=='signer':s.signer_address='signer'
        elif fault=='client_type':s.client=NS(dex='pas',transport=c.transport)
        elif fault=='transport':c.transport=f
        elif fault=='missing':c.markets={k:v for k,v in c.markets.items() if k!='pas:BTC'}
        else:s.candidate_symbols=('pas:BTC','pas:EWY')
        with pytest.raises(ExchangeError):s.selected_markets()
    finally:
        if hasattr(c.transport,'close'):c.close()


def test_ranking_never_changes_a_signal_or_authorizes_extra_markets():
    scan=result();before=deepcopy(scan);r=ranking_report(scan,SOURCE,SOURCE)
    assert scan==before and len(r['rows'])==10 and r['signing_authority']=='NONE'
    assert r['production_entry_markets']==sorted(PAS_ENTRY_MARKETS)
    assert r['observational_top_three']==scan.watchlist
    assert all(x['signed_entry_authorized'] is False and x['expected_profit'] is None for x in r['rows'])
    assert {x['symbol'] for x in r['rows'] if x['production_entry_market']}==PAS_ENTRY_MARKETS
    assert len(r['observational_top_three'])==3


@pytest.mark.parametrize('fault',['source','missing','duplicate','par','too_many','unqualified','duplicate_rank'])
def test_incomplete_ranking_cannot_report_success(fault):
    scan=result();after=SOURCE
    if fault=='source':after='b'*64
    elif fault=='missing':scan.diagnostics.pop()
    elif fault=='duplicate':scan.diagnostics[0]=deepcopy(scan.diagnostics[1])
    elif fault=='par':scan.diagnostics[0].symbol='par:BTC'
    elif fault=='too_many':scan.watchlist.append(scan.diagnostics[3].symbol)
    elif fault=='unqualified':scan.watchlist=[scan.diagnostics[-1].symbol]
    else:scan.watchlist=[scan.watchlist[0],scan.watchlist[0]]
    with pytest.raises(ExchangeError):ranking_report(scan,SOURCE,after)


def test_isolation_is_explicit_finite_and_has_no_execution_consumer():
    p=proof();before=deepcopy(p);r=propose(p,SOURCE,NOW)
    assert p==before and r['original']['original_state']=='UNKNOWN'
    assert r['original']['consumed_attempt_preserved'] is True
    assert r['proposed_expires_ms']-r['created_ms']==3600000
    assert r['policy_acceptance_created'] is False and r['order_authority'] is False
    assert r['proposed_session_ceilings']['maximum_concurrent_positions']==1
    assert r['proposed_session_ceilings']['session_loss_stop_usdp']=='200'
    assert r['qualification_is_separate']['requires_its_own_exact_human_acceptance'] is True
    # Only its CLI dispatcher imports it. No signed execution imports this draft.
    root=Path(__file__).parent/'exchange'
    consumers=[f.name for f in root.glob('*.py') if 'from .trading_isolation_review import' in f.read_text()]
    assert consumers==['pas_operations.py']


@pytest.mark.parametrize('minutes',[0,1,4,61,720,True,'60',None])
def test_isolation_refuses_unbounded_or_ambiguous_duration(minutes):
    with pytest.raises(ExchangeError):propose(proof(),SOURCE,NOW,minutes=minutes)


@pytest.mark.parametrize('fault',['source','expiry','nonce','positive_status','live_position','scope','signature'])
def test_isolation_design_cannot_be_based_on_changed_or_unsafe_observations(fault):
    p=proof()
    if fault=='source':p['source_hash_after']='b'*64
    elif fault=='expiry':p['finished_ms']=NOW-300001
    elif fault=='nonce':p['local']['nonce_high_water']-=1
    elif fault=='positive_status':p['readbacks'][0]['original_order_status']=dict(status='order')
    elif fault=='live_position':p['readbacks'][1]['venues']['pas']['positions_after']=[{}]
    elif fault=='scope':p['scope']='OTHER'
    else:p['signatures_created']=1
    seal(p)
    with pytest.raises(ExchangeError):propose(p,SOURCE,NOW)


def test_new_cli_entry_points_exist_without_creating_authority():
    from test_terminal_app import command
    for name in ('pas-ranking','trading-isolation-review'):
        p=command(name,'--help');assert p.returncode==0 and '--output' in p.stdout
    p=command('trading-isolation-review','--apply')
    assert p.returncode!=0


def test_real_frozen_scans_preserve_btc_ewy_metrics_and_signals_in_ten_market_observation(tmp_path):
    f,c,s=scanner(tmp_path)
    try:
        observed=s.scan();normal=MarketRegimeScanner(s.market,s.policy).scan()
        assert len(observed.diagnostics)==10 and len(normal.diagnostics)==2
        for baseline in normal.diagnostics:
            broad=next(d for d in observed.diagnostics if d.symbol==baseline.symbol)
            assert broad.metrics and broad.metrics==baseline.metrics
            assert broad.signal==baseline.signal and broad.qualified==baseline.qualified
        assert {q['req']['coin'] for q in f.calls if q['type']=='candleSnapshot'}==SCORED.markets
        assert not any(q['type'] in {'order','updateLeverage','cancel'} for q in f.calls)
    finally:c.close()


@pytest.mark.parametrize('symbol,decimals,price,quantity,count',[
    ('pas:BTC',5,'82500','.00030',12),('pas:EWY',3,'159','.157',62),
    ('pas:BTC',4,'82500','.0002',1),('pas:EWY',3,'100','.250',99)])
def test_partial_coverage_counts_all_unproven_sizes_without_generalizing_one_lot(symbol,decimals,price,quantity,count):
    from exchange.pas_native_plan import residual_coverage_requirements
    from exchange.base_exchange import MarketSpec
    r=residual_coverage_requirements(MarketSpec(symbol,decimals,20,2810000),quantity,price,price)
    assert r['routes']['native_stop']['number_of_subminimum_sizes']==count
    assert r['routes']['full_position_ioc']['number_of_subminimum_sizes']==count
    assert r['one_lot_proof_generalizes_to_other_sizes'] is False and r['all_sizes_qualified'] is False
