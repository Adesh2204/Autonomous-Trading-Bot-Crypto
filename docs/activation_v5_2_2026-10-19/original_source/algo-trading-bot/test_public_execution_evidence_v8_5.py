"""Offline evidence anti-false-positive regressions; no venue action capability."""
import copy
import importlib.util
from pathlib import Path
from decimal import Decimal as D

import pytest

PATH = Path(__file__).resolve().parents[1]/'docs/certification_v8_5_2026-10-12/public_evidence.py'
SPEC = importlib.util.spec_from_file_location('v85_public_evidence', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
classify = MODULE.classify


def example(*, short=False, stop=False, split=False):
    side, start, direction = ('B','-.01','Close Short') if short else ('A','.01','Close Long')
    order = dict(coin='par:HYPE', oid=7, origSz='.01', sz='0', limitPx='100',
        reduceOnly=True, side=side, isTrigger=stop, orderType='Stop Limit' if stop else 'Limit',
        triggerPx='101' if short else '99', isPositionTpsl=stop, tif='Gtc' if stop else 'Ioc')
    status = dict(status='order', order=dict(order=order, status='filled'))
    fill = dict(coin='par:HYPE',oid=7,tid=1,side=side,dir=direction,feeToken='USDPR',
        startPosition=start,sz='.01',px='100',time=10)
    fills=[fill]
    if split:
        fill['sz']='.004'
        fills.append(dict(fill,tid=2,sz='.006',time=11,startPosition='-.006' if short else '.006'))
    return status, fills


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('split', [False, True])
def test_verified_one_lot_close_is_separate_from_stop_support(short, split):
    status, fills=example(short=short,split=split)
    result=classify(status,list(reversed(fills)),coin='par:HYPE',lot=D('.01'))
    assert result['one_lot_full_close'] and result['exact_full_close']
    assert D(result['post_fill_position'])==0
    assert not result['subminimum_stop_filled']
    assert not result['stop_acceptance_observed']
    assert not result['protection_partial_fill_behavior_verified']


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('split', [False, True])
def test_filled_stop_observation_does_not_claim_one_lot_manual_close_or_placement_behavior(short, split):
    status,fills=example(short=short,stop=True,split=split)
    result=classify(status,fills,coin='par:HYPE',lot=D('.01'))
    assert result['subminimum_stop_filled'] and result['stop_acceptance_observed']
    assert result['stop_grouping_position_attached']
    assert not result['one_lot_full_close']
    assert not result['protection_partial_fill_behavior_verified']


@pytest.mark.parametrize('terminal', ['reduceOnlyRejected','minTradeNtlRejected','triggered','canceled','open'])
def test_terminal_order_status_cannot_be_replaced_by_a_synthetic_matching_fill(terminal):
    status,fills=example();status['order']['status']=terminal
    result=classify(status,fills,coin='par:HYPE',lot=D('.01'))
    assert not result['exact_full_close'] and not result['one_lot_full_close']


@pytest.mark.parametrize('terminal,accepted', [('open',True),('triggered',True),('canceled',True),
                                             ('minTradeNtlRejected',False),('badTriggerPxRejected',False)])
def test_stop_acceptance_alone_cannot_certify_small_position_protection(terminal, accepted):
    status,fills=example(stop=True);status['order']['status']=terminal
    result=classify(status,fills,coin='par:HYPE',lot=D('.01'))
    assert result['stop_acceptance_observed']==accepted
    assert not result['subminimum_stop_filled']
    assert not result['protection_partial_fill_behavior_verified']


@pytest.mark.parametrize('mutation', [
    'large_original','partial_position','missing_fill','duplicate_fill','gap_in_position_chain',
    'wrong_side','wrong_direction','wrong_fee_token','wrong_oid','wrong_coin',
    'unknown_order','non_reduce_only','remainder','wrong_tif','not_stop_loss','invalid_trigger',
    'invalid_price','oversized_fill','nonfinite_size'])
def test_ambiguous_or_conflicting_public_evidence_never_verifies_an_exception(mutation):
    status,fills=example(split=True,stop=mutation in {'not_stop_loss','invalid_trigger'})
    order=status['order']['order']
    if mutation=='large_original':order['origSz']='.11'
    elif mutation=='partial_position':fills[0]['startPosition']='.02'
    elif mutation=='missing_fill':fills.pop()
    elif mutation=='duplicate_fill':fills.append(copy.deepcopy(fills[0]))
    elif mutation=='gap_in_position_chain':fills[1]['startPosition']='.007'
    elif mutation=='wrong_side':order['side']='B'
    elif mutation=='wrong_direction':fills[0]['dir']='Open Short'
    elif mutation=='wrong_fee_token':fills[0]['feeToken']='USDC'
    elif mutation=='wrong_oid':fills[0]['oid']=8
    elif mutation=='wrong_coin':order['coin']='HYPE'
    elif mutation=='unknown_order':status['status']='unknownOid'
    elif mutation=='non_reduce_only':order['reduceOnly']=False
    elif mutation=='remainder':order['sz']='.0001'
    elif mutation=='wrong_tif':order['tif']='Gtc'
    elif mutation=='not_stop_loss':order['orderType']='Take Profit Limit'
    elif mutation=='invalid_trigger':order['triggerPx']='0'
    elif mutation=='invalid_price':order['limitPx']='0'
    elif mutation=='oversized_fill':fills[0]['sz']='.02'
    elif mutation=='nonfinite_size':order['origSz']='NaN'
    result=classify(status,fills,coin='par:HYPE',lot=D('.01'))
    assert not result['one_lot_full_close'] and not result['exact_full_close']
    assert not result['subminimum_stop_filled']
    assert result['reasons']


def test_three_lot_close_does_not_answer_one_lot_question():
    status,fills=example();status['order']['order']['origSz']='.03'
    fills[0].update(startPosition='.03',sz='.03')
    result=classify(status,fills,coin='par:HYPE',lot=D('.01'))
    assert result['exact_full_close'] and not result['one_lot_full_close']


def test_public_proof_has_no_effect_on_production_minimum_or_partial_fill_gate():
    from exchange.base_exchange import ExchangeError, MarketSpec
    from exchange.partial_fill_safety import exact_full_close_size
    from exchange.base_exchange import Position
    status,fills=example()
    assert classify(status,fills,coin='par:HYPE',lot=D('.01'))['one_lot_full_close']
    spec=MarketSpec('par:HYPE',2,10,2670002)
    with pytest.raises(ExchangeError,match='ORDER_BELOW_MINIMUM_NOTIONAL'):
        spec.normalize_order('SELL','.01','100',reduce_only=True)
    held=Position('par:HYPE',D('.01'),D('100'),D('0'),D('1'),None)
    with pytest.raises(ExchangeError,match='SUB_MINIMUM_RESIDUAL_CLOSE_NOT_VERIFIED'):
        exact_full_close_size(spec,held,side='SELL',limit_price='100',maximum_quantity='.01')
