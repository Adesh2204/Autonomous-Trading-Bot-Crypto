"""Offline regressions for competition OI caps and reserved engineering headroom."""
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from exchange.base_exchange import MarketSpec, Quote
from test_pas_account_oi_regressions import NOW, _risk_context, _validate


MARKET_CAP = D('10000000')
DEX_CAP = D('50000000')
HEADROOM = D('0.01')


def _case(symbol='pas:BTC', *, side='BUY', orders=(), current_oi='0', dex_oi='1000',
          market_cap='100000000', dex_cap='100000000', size_cap='100000'):
    client, request, context, permission = _risk_context(symbol, orders=orders, dex_oi=dex_oi)
    request = replace(request, side=side)
    permission = replace(permission, side=side)
    contexts = dict(context.contexts)
    contexts[symbol] = dict(contexts[symbol], openInterest=str(current_oi))
    limits = dict(
        context.limits,
        coinToOiCap=[['pas:BTC', str(market_cap)], ['BTC', str(market_cap)],
                     ['pas:EWY', str(market_cap)], ['EWY', str(market_cap)]],
        oiSzCapPerPerp=str(size_cap),
        totalOiCap=str(dex_cap),
    )
    context = replace(context, limits=limits, contexts=contexts)
    return client, request, context, permission


def _audit_decimal(result, field):
    return D(result.audit[field])


@pytest.mark.parametrize('symbol', ['pas:BTC', 'pas:EWY'])
@pytest.mark.parametrize(('exchange_cap', 'effective_cap'), [
    ('5000000', D('5000000')),
    ('20000000', MARKET_CAP),
])
def test_competition_market_cap_is_minimum_of_authoritative_and_shared_ceiling(
        symbol, exchange_cap, effective_cap):
    client, request, context, permission = _case(
        symbol, market_cap=exchange_cap, dex_cap='100000000', size_cap='100000')
    result = _validate(client, request, context, permission)
    assert result.allowed
    assert _audit_decimal(result, 'symbol_oi_cap') == effective_cap
    assert _audit_decimal(result, 'symbol_oi_entry_limit') == effective_cap * (1 - HEADROOM)
    assert _audit_decimal(result, 'oi_headroom_fraction') == HEADROOM


@pytest.mark.parametrize('symbol', ['pas:BTC', 'pas:EWY'])
@pytest.mark.parametrize(('projected', 'allowed'), [
    ('9899999.99', True),
    ('9900000', False),
    ('10000000', False),
    ('10000000.01', False),
])
def test_higher_exchange_cap_cannot_bypass_published_market_ceiling(symbol, projected, allowed):
    current_oi = (D(projected) - D('10')) / D('100')
    client, request, context, permission = _case(
        symbol, current_oi=str(current_oi), market_cap='20000000',
        size_cap='1000000')
    result = _validate(client, request, context, permission)
    assert result.allowed is allowed
    if not allowed:
        assert result.code == 'OPEN_INTEREST_CAPACITY'


@pytest.mark.parametrize('symbol', ['pas:BTC', 'pas:EWY'])
@pytest.mark.parametrize('side', ['BUY', 'SELL'])
@pytest.mark.parametrize(('projected', 'allowed'), [
    ('989.99', True),
    ('990', False),
    ('990.01', False),
    ('1000', False),  # equality at the published cap is also prohibited
])
def test_market_entry_requires_projected_oi_strictly_below_99_percent(
        symbol, side, projected, allowed):
    # The proposed 0.1 at $100 adds $10; choose existing OI to place the
    # projected total immediately below, at, or above the buffered limit.
    current_oi = (D(projected) - D('10')) / D('100')
    client, request, context, permission = _case(
        symbol, side=side, current_oi=str(current_oi), market_cap='1000',
        dex_cap='100000000', size_cap='100')
    result = _validate(client, request, context, permission)
    assert result.allowed is allowed
    if not allowed:
        assert result.code == 'OPEN_INTEREST_CAPACITY'
    assert _audit_decimal(result, 'symbol_oi_entry_limit') == D('990')


@pytest.mark.parametrize(('exchange_cap', 'effective_cap'), [
    ('40000000', D('40000000')),
    ('100000000', DEX_CAP),
])
def test_competition_dex_cap_is_minimum_of_authoritative_and_shared_ceiling(
        exchange_cap, effective_cap):
    client, request, context, permission = _case(
        dex_cap=exchange_cap, market_cap='100000000', size_cap='100000')
    result = _validate(client, request, context, permission)
    assert result.allowed
    assert _audit_decimal(result, 'dex_oi_cap') == effective_cap
    assert _audit_decimal(result, 'dex_oi_entry_limit') == effective_cap * (1 - HEADROOM)


@pytest.mark.parametrize(('projected', 'allowed'), [
    ('989.99', True),
    ('990', False),
    ('990.01', False),
    ('1000', False),  # equality at the published cap is also prohibited
])
def test_dex_entry_requires_projected_oi_strictly_below_99_percent(projected, allowed):
    current_dex_oi = D(projected) - D('10')
    client, request, context, permission = _case(
        dex_oi=str(current_dex_oi), market_cap='100000000', dex_cap='1000',
        size_cap='100000')
    result = _validate(client, request, context, permission)
    assert result.allowed is allowed
    if not allowed:
        assert result.code == 'OPEN_INTEREST_CAPACITY'
    assert _audit_decimal(result, 'dex_oi_entry_limit') == D('990')


@pytest.mark.parametrize(('projected_size', 'allowed'), [
    ('0.1979', True),
    ('0.198', False),
    ('0.1981', False),
])
def test_size_entry_requires_projected_oi_strictly_below_99_percent(
        projected_size, allowed):
    # Size cap is 0.2 coins; the proposed 0.1 combines with current OI.
    current_oi = D(projected_size) - D('0.1')
    client, request, context, permission = _case(
        current_oi=str(current_oi), market_cap='100000000', dex_cap='100000000',
        size_cap='0.2')
    result = _validate(client, request, context, permission)
    assert result.allowed is allowed
    if not allowed:
        assert result.code == 'OPEN_INTEREST_CAPACITY'
    assert _audit_decimal(result, 'symbol_oi_size_entry_limit') == D('0.198')


def test_pending_same_symbol_order_consumes_market_and_size_headroom():
    pending = {'coin': 'pas:BTC', 'oid': 41, 'cloid': 'p41', 'side': 'B',
               'sz': '.1', 'limitPx': '100', 'reduceOnly': False}
    client, request, context, permission = _case(
        orders=(pending,), market_cap='100', dex_cap='100000000', size_cap='.2')
    result = _validate(client, request, context, permission)
    assert not result.allowed and result.code == 'OPEN_INTEREST_CAPACITY'
    assert _audit_decimal(result, 'reserved_open_order_quantity') == D('.1')


def test_pending_other_symbol_order_consumes_shared_dex_headroom():
    pending = {'coin': 'pas:EWY', 'oid': 42, 'cloid': 'p42', 'side': 'A',
               'sz': '.1', 'limitPx': '100', 'reduceOnly': False}
    client, request, context, permission = _case(
        'pas:BTC', orders=(pending,), dex_oi='79', market_cap='100000000',
        dex_cap='100', size_cap='100000')
    result = _validate(client, request, context, permission)
    assert not result.allowed and result.code == 'OPEN_INTEREST_CAPACITY'
    assert _audit_decimal(result, 'reserved_open_order_dex_notional') == D('10.0')


def test_reduce_only_close_is_allowed_when_oi_limits_are_exhausted():
    client, request, context, permission = _case(
        side='SELL', current_oi='1000000', dex_oi='1000000000', market_cap='1',
        dex_cap='1', size_cap='.01')
    request = replace(request, reduce_only=True)
    permission = replace(permission, reduce_only=True, reason='reduce exposure')
    positions = dict(context.positions, **{'pas:BTC': SimpleNamespace(quantity=D('.1'))})
    context = replace(context, positions=positions)
    result = _validate(client, request, context, permission)
    assert result.allowed


@pytest.mark.parametrize('malformed_limits', [
    {'coinToOiCap': [['pas:BTC', 'not-a-number'], ['BTC', 'not-a-number']]},
    {'coinToOiCap': [['pas:BTC', '1000'], ['BTC', '1001']]},
    {'oiSzCapPerPerp': 'not-a-number'},
    {'totalOiCap': 'not-a-number'},
])
def test_malformed_competition_caps_fail_closed(malformed_limits):
    client, request, context, permission = _case()
    context = replace(context, limits=dict(context.limits, **malformed_limits))
    result = _validate(client, request, context, permission)
    assert not result.allowed
    assert result.code in {'EXCHANGE_RULE_DATA_INVALID', 'EXCHANGE_RULE_DATA_UNAVAILABLE'}


@pytest.mark.parametrize(('age_ms', 'allowed'), [(5000, True), (5001, False)])
def test_dex_oi_observation_freshness_boundary_is_unchanged(age_ms, allowed):
    client, request, context, permission = _case()
    context = replace(context, dex_oi_observed_ms=NOW - age_ms)
    result = _validate(client, request, context, permission)
    assert result.allowed is allowed
    if not allowed:
        assert result.code == 'DEX_OI_AGGREGATE_STALE_OR_UNVERIFIED'


def test_noncompetition_offline_fixture_keeps_original_strictly_greater_cap_rule():
    client, request, context, permission = _case(
        current_oi='9.9', market_cap='1000', dex_cap='1000000', size_cap='100000')
    old_symbol = request.symbol
    request = replace(request, symbol='par:BTC')
    permission = replace(permission, symbol='par:BTC')
    spec = MarketSpec('par:BTC', 4, 20, 100)
    client = SimpleNamespace(
        competition_mode=False, dex='par', ready=True,
        markets={'par:BTC': spec}, market=lambda key: spec,
    )
    quote = replace(context.quote, symbol='par:BTC')
    contexts = {'par:BTC': dict(context.contexts[old_symbol], openInterest='9.9', oraclePx='100')}
    limits = dict(context.limits,
                  coinToOiCap={'par:BTC': '1000', 'BTC': '1000'},
                  totalOiCap='1000000')
    active_asset = dict(context.active_asset, coin='par:BTC')
    context = replace(context, spec=spec, quote=quote, contexts=contexts, limits=limits,
                      active_asset=dict(active_asset, leverage={'type': 'cross', 'value': 1}),
                      leverage=1, dex_total_oi_notional=None,
                      dex_oi_observed_ms=None)
    at_cap = _validate(client, request, context, permission)
    assert at_cap.allowed  # exactly $1,000 was historically permitted
    above = replace(context, contexts={'par:BTC': dict(contexts['par:BTC'], openInterest='9.91')})
    over_cap = _validate(client, request, above, permission)
    assert not over_cap.allowed and over_cap.code == 'OPEN_INTEREST_CAPACITY'
