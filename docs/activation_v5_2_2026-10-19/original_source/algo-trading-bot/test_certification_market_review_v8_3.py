"""Offline one-lot review and all-market composition; no actual venue writes."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import importlib.util
from pathlib import Path

import pytest

from exchange.base_exchange import ExchangeError, MarketSpec, VenueMismatch
from exchange.certification_market_review import review_one_lot_long
from exchange.hyperliquid_client import EXPECTED_MARKETS, HyperliquidClient
from exchange.partial_fill_safety import partial_path_assessment, VENUE_EXCEPTION_STATUS
from exchange.testnet_certification import CertificationProposal
from test_testnet_certification_v8 import cert, live

NOW=1791797700000


def inputs(symbol='par:BTC', decimals=0, px='20'):
    price=D(px)
    spec=MarketSpec(symbol,decimals,50,2670000)
    book=dict(coin=symbol,time=NOW,levels=[
        [dict(px=str(price),sz='100'),dict(px=str(price-D('.001')),sz='200')],
        [dict(px=str(price+D('.001')),sz='100'),dict(px=str(price+D('.1')),sz='200')]])
    context=dict(markPx=str(price),oraclePx=str(price),funding='0',openInterest='100')
    active=dict(coin=symbol,leverage=dict(type='cross',value=1),
                maxTradeSzs=['100','100'],availableToTrade=['1000','1000'])
    return spec,book,context,active


def review(values,**kwargs):
    return review_one_lot_long(*values,now_ms=NOW,context_observed_ms=NOW,
        taker_fee_rate='.0009',**kwargs)


@pytest.mark.parametrize('symbol,decimals,price',[
    ('BTC',4,'83493'),('ETH',4,'2560.3'),('HYPE',2,'87.089'),('SP500',3,'7820.5'),
    ('EWY',3,'173.85'),('EWJ',3,'98.001'),('BRENT',2,'102.88'),('GOLD',4,'4175.6'),
    ('USDEUR',1,'1.1213'),('USDJPY',2,'158.37')])
def test_snapshot_lot_math_never_uses_full_entry_size(symbol,decimals,price):
    # Synthetic fixture mirrors observed metadata; not exchange acceptance proof.
    values=inputs('par:'+symbol,decimals,price);r=review(values)
    assert D(r['mark_lot_notional'])==values[0].size_step*D(price)<10
    assert D(r['limit_notionals']['entry_limit'])<10
    assert 'ONE_LOT_ENTRY_BELOW_MINIMUM' in r['blockers']
    assert 'ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM' in r['blockers']
    assert not r['eligible_under_reviewed_bounds'] and not r['order_authorized']


def test_synthetic_one_lot_candidate_does_not_grant_execution_permission():
    values=inputs();r=review(values)
    assert r['eligible_under_reviewed_bounds'] and r['reviewed_quantity']=='1'
    assert D(r['limit_notionals']['stop_limit'])>10
    assert not r['executable'] and not r['order_authorized']
    assert not r['exchange_protection_accepted']
    assert r['subminimum_close_evidence']==VENUE_EXCEPTION_STATUS
    assert r['subminimum_protection_evidence']==VENUE_EXCEPTION_STATUS
    with pytest.raises(TypeError):CertificationProposal(**r)


def test_one_lot_entry_above_ten_is_not_enough_at_exit():
    r=review(inputs(px='10.1'))
    assert D(r['limit_notionals']['entry_limit'])>10
    assert D(r['limit_notionals']['stop_limit'])<10
    assert not r['eligible_under_reviewed_bounds']


@pytest.mark.parametrize('damage,code',[
    ('budget','ONE_LOT_EXCEEDS_REVIEWED_NOTIONAL_CAP'),
    ('bid_depth','CERTIFICATION_BBO_DEPTH_FRACTION_EXCEEDED'),
    ('ask_depth','CERTIFICATION_BBO_DEPTH_FRACTION_EXCEEDED'),
    ('spread','CERTIFICATION_SPREAD_EXCEEDED'),
    ('mark','CERTIFICATION_MARK_ORACLE_DIVERGENCE'),
    ('oracle','CERTIFICATION_MID_ORACLE_DIVERGENCE'),
    ('leverage','CERTIFICATION_ONE_X_CROSS_REQUIRED'),
    ('capacity','CERTIFICATION_SIDE_CAPACITY_INSUFFICIENT'),
    ('max_size','CERTIFICATION_SIDE_CAPACITY_INSUFFICIENT'),
    ('capacity_missing','CERTIFICATION_SIDE_CAPACITY_UNAVAILABLE'),
    ('coin','ACTIVE_ASSET_MARKET_IDENTITY_CONFLICT'),
    ('book_time','ORDERBOOK_STALE'),
    ('future_time','ORDERBOOK_STALE'),
    ('locked_book','CERTIFICATION_NONZERO_SPREAD_REQUIRED')])
def test_independent_safety_blockers_are_not_hidden_by_minimum_review(damage,code):
    spec,book,context,active=inputs()
    if damage=='budget':spec,book,context,active=inputs(px='100')
    if damage in {'bid_depth','ask_depth'}:book['levels'][damage=='ask_depth'][0]['sz']='1'
    if damage=='spread':book['levels'][1]=[dict(px='20.1',sz='100')]
    if damage=='mark':context['markPx']='20.2'
    if damage=='oracle':context['oraclePx']='21'
    if damage=='leverage':active['leverage']['value']=20
    if damage=='capacity':active['availableToTrade'][0]='1'
    if damage=='max_size':active['maxTradeSzs'][0]='.5'
    if damage=='capacity_missing':active.pop('availableToTrade')
    if damage=='coin':active['coin']='par:ETH'
    if damage=='book_time':book['time']=NOW-5001
    if damage=='future_time':book['time']=NOW+1
    if damage=='locked_book':book['levels'][1]=[dict(px='20',sz='100')]
    r=review((spec,book,context,active))
    assert code in r['blockers'] and not r['eligible_under_reviewed_bounds']


@pytest.mark.parametrize('side',[0,1])
def test_empty_side_does_not_become_executable_from_mark(side):
    spec,book,context,active=inputs();book['levels'][side]=[]
    r=review((spec,book,context,active))
    assert r['blockers']==['NO_EXECUTABLE_TWO_SIDED_BOOK']
    assert r['prices'] is None and r['limit_notionals'] is None
    assert r['mark_lot_notional']=='20' and not r['eligible_under_reviewed_bounds']


@pytest.mark.parametrize('observed',[NOW-5001,NOW+1,None])
def test_context_receipt_age_is_not_retimed(observed):
    r=review_one_lot_long(*inputs(),now_ms=NOW,context_observed_ms=observed,taker_fee_rate='.0009')
    assert 'ASSET_CONTEXT_OBSERVATION_STALE' in r['blockers']


def test_native_market_and_notional_increase_are_prohibited():
    with pytest.raises(ExchangeError,match='INVALID_MARKET_SPEC'):inputs('BTC')
    values=inputs('xyz:BTC')
    with pytest.raises(VenueMismatch):review(values)
    with pytest.raises(ExchangeError,match='CAP_INCREASE_PROHIBITED'):review(inputs(),max_notional=26)


def test_reviewed_depth_is_actual_visible_depth_within_bounds():
    r=review(inputs())
    assert r['depth']['entry_quantity_within_limit']=='100'
    assert r['depth']['exit_quantity_within_bound']=='300'
    assert r['depth']['scope']=='CURRENT_BOOK_ONLY_NOT_FUTURE_STOP_LIQUIDITY'


def test_increasing_total_order_notional_does_not_fix_smallest_partial(cert):
    p=replace(cert.proposal,quantity='.2498')
    spec=cert.live.client.market(p.symbol)
    assert D(p.quantity)*D(p.entry_limit)>10
    assert not partial_path_assessment(spec,p)['entry_admissible_under_documented_minimum']
    with pytest.raises(ExchangeError,match='ORDER_BELOW_MINIMUM_NOTIONAL'):
        spec.normalize_order('SELL',spec.size_step,D(p.exit_bound),reduce_only=True,tif='Ioc')
    assert not cert.venue.calls


def test_all_ten_real_composition_is_read_only_and_preserves_local_failures(cert,tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[1]/'scripts/inspect_certification_markets.py'
    loading=importlib.util.spec_from_file_location('v8_3_readonly_fixture',path)
    module=importlib.util.module_from_spec(loading);loading.loader.exec_module(module)
    class ReadOnlyFixture:
        def __call__(self,payload):
            value=deepcopy(cert.venue.read(payload))
            if payload['type']=='l2Book' and payload['coin']=='par:HYPE':value['levels']=[[],[]]
            return value
        def close(self):pass
    client=HyperliquidClient(ReadOnlyFixture(),clock_ms=lambda:cert.live.fixture.now)
    monkeypatch.setattr(module,'HyperliquidClient',lambda **_:client)
    monkeypatch.setattr(module,'TEAM',cert.proposal.team_wallet)
    monkeypatch.setattr(module,'API',cert.proposal.api_wallet)
    result=module.inspect_markets(tmp_path/'review')
    assert result['status']=='PREFLIGHT_BLOCKED' and result['blocker']=='NO_ELIGIBLE_ONE_LOT_MARKET'
    assert {row['symbol'] for row in result['markets']}==EXPECTED_MARKETS
    assert len(result['markets'])==10
    hype=next(r for r in result['markets'] if r['symbol']=='par:HYPE')
    assert hype['blockers']==['NO_EXECUTABLE_TWO_SIDED_BOOK']
    assert len([r for r in result['markets'] if r['prices'] is not None])==9
    assert not any(result[x] for x in ('signature_created','exchange_submissions','order_authorized',
        'PARTIAL_FILL_EXIT_READY','ACTUAL_PROTECTION_READY','CONTROLLED_EXECUTION_READY'))
    assert not cert.venue.calls and not (tmp_path/'review/proposal.json').exists()
    assert all(p.get('dex')=='par' for p in cert.live.fixture.calls if p['type']=='metaAndAssetCtxs')
