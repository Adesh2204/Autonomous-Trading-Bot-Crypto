"""PAS offline SDK/lifecycle faults; temporary ephemeral signer only, no HTTP.

Synthetic one-unit lots enable exercising protected lifecycles without changing
actual PAS precision. These fixtures NEVER qualify the real venue or residuals.
"""
from copy import deepcopy
from decimal import Decimal as D
from types import SimpleNamespace
from dataclasses import replace
import pytest
from eth_account import Account
from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import NonceManager,ClockHealthMonitor,HyperliquidRateLimitManager
from exchange.exchange_rules import LiveContextProvider,HyperliquidOrderValidator
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.sdk_transport import OfflineSDKTransport
from exchange.scored_session import SCORED_START_MS
from exchange.bounded_daily_session import TradeState
from test_live_exchange_execution import LiveInfoFixture
from test_long_session import bridge,enter
from test_pas_migration import isolated_pas_environment


class PasLiveFixture(LiveInfoFixture):
    def __init__(self,address):
        super().__init__(address)
        self.now=SCORED_START_MS+3600000
        self.dexes=[None,dict(name='par'),dict(name='pas')]
        for row in self.metadata['universe']:row['name']=row['name'].replace('par:','pas:')
        self.metadata['collateralToken']=77
        self.spot=dict(balances=[dict(coin='USDP',token=77,total='1000',hold='0')])
        self.agents=[dict(address=address,validUntil=self.now+86400000)]
        self.active['coin']='pas:BTC';self.book['time']=self.now
        self.limits['coinToOiCap']=[[r['name'],'1000000'] for r in self.metadata['universe']]

    def __call__(self,payload):
        if payload['type']=='spotMeta':return dict(tokens=[dict(name='USDP',index=77)])
        return super().__call__(payload)

    def position(self,size,entry='100'):
        super().position(size,entry)
        for row in self.state['assetPositions']:row['position']['coin']='pas:BTC'

    def fill(self,*args,**kwargs):
        super().fill(*args,**kwargs);self.fills[-1].update(coin='pas:BTC',feeToken='USDP')


@pytest.fixture
def pas_bridge(tmp_path,monkeypatch):
    import requests,socket
    def forbidden(*a,**k):raise AssertionError('NO_NETWORK_IN_PAS_SIGNED_FIXTURES')
    monkeypatch.setattr(requests.Session,'post',forbidden);monkeypatch.setattr(socket.socket,'connect',forbidden)
    signer=Account.create();f=PasLiveFixture(signer.address)
    c=HyperliquidClient(f,clock_ms=lambda:f.now,venue='pas');c.startup()
    j=ExecutionJournal(tmp_path/'offline.sqlite',session_id='offline:pas',team_address=f.active['user'])
    rates=HyperliquidRateLimitManager(j,clock_ms=lambda:f.now)
    clock=ClockHealthMonitor(clock_ms=lambda:f.now,monotonic_ms=lambda:f.now)
    account=HyperliquidAccount(c,f.active['user']);market=HyperliquidMarketData(c)
    provider=LiveContextProvider(market,account,signer.address,clock,rates,reconciliation_ready=lambda:True,feed_ready=lambda:True)
    validator=HyperliquidOrderValidator(c);nonces=NonceManager(tmp_path/'offline_nonces.sqlite',signer.address,clock_ms=lambda:f.now)
    transport=OfflineSDKTransport(c,signer,account.team_address,nonces,[])
    e=HyperliquidExecution(c,transport=transport,account=account,journal=j,context_provider=provider,
        validator=validator,recovery=SimpleNamespace(recover=lambda:SimpleNamespace(ready=True,reasons=())),clock_health=clock,rate_limits=rates)
    e.entries_paused=False
    v=SimpleNamespace(fixture=f,client=c,journal=j,rate=rates,clock=clock,account=account,market=market,
        provider=provider,validator=validator,nonces=nonces,transport=transport,executor=e,signer=signer)
    try:yield bridge.__wrapped__(v,monkeypatch)
    finally:transport.close();nonces.close();j.close();c.close()


def test_pas_frozen_signal_sdk_protection_close_and_realized_accounting(pas_bridge):
    b=pas_bridge;enter(b);v=b.live
    wire=v.transport.signed_payloads[-1]['action'];assert wire['grouping']=='na'
    stop=wire['orders'][0];assert stop['r'] is True and stop['a']==v.client.market('pas:BTC').asset_id
    assert stop['t']['trigger']['isMarket'] is False and b.daily.state in {TradeState.POSITION_PROTECTED,TradeState.POSITION_MANAGED}
    b.session._close('pas:BTC','Stop Loss Hit')
    assert b.daily.state==TradeState.FLAT_VERIFIED and b.daily.data['cycles']==1
    assert not v.account.get_positions() and not v.account.get_frontend_open_orders()
    assert all(f.fee_token=='USDP' and f.symbol=='pas:BTC' for f in b.recovery.state.fills.values())


@pytest.mark.parametrize('fault',['reject','timeout_before','entry_internet_after_fill'])
def test_pas_uncertain_entry_is_never_repeated(pas_bridge,fault):
    b=pas_bridge;b.venue.fail=fault
    try:enter(b)
    except ExchangeError:pass
    n=len(b.live.transport.signed_payloads)
    try:enter(b)
    except ExchangeError:pass
    assert len(b.live.transport.signed_payloads)==n
    assert b.daily.state in {TradeState.REJECTED,TradeState.UNKNOWN,TradeState.RECOVERY_REQUIRED}


@pytest.mark.parametrize('fault',['reject','timeout_before','wrong_quantity'])
def test_pas_failed_native_stop_does_not_rearm_or_hide_exposure(pas_bridge,monkeypatch,fault):
    b=pas_bridge;original=b.venue.transmit
    def transmit(payload):
        if payload['action'].get('orders',[{}])[0].get('t',{}).get('trigger'):
            if fault=='wrong_quantity':b.venue.wrong_qty=True
            else:b.venue.fail=fault
        return original(payload)
    monkeypatch.setattr(b.live.transport,'transmit',transmit);enter(b)
    assert b.live.account.get_positions()
    assert b.daily.state in {TradeState.UNPROTECTED_EXPOSURE,TradeState.UNKNOWN,TradeState.RECOVERY_REQUIRED}
    n=len(b.live.transport.signed_payloads)
    try:enter(b)
    except ExchangeError:pass
    assert len(b.live.transport.signed_payloads)==n


@pytest.mark.parametrize('fraction',['.5','1'])
def test_pas_partial_or_full_native_closing_fill_uses_actual_remaining_position(pas_bridge,fraction):
    b=pas_bridge;enter(b);v=b.live;held=v.account.get_position('pas:BTC');q=held.quantity*D(fraction)
    b.venue.fill_protection(q,partial=D(fraction)<1)
    v.fixture.fills[-1]['closedPnl']=str(q*(D(v.fixture.fills[-1]['px'])-held.entry_price))
    b.recovery.recover();v.executor.protection.ensure_all();v.executor.reconcile_daily()
    if D(fraction)==1:assert b.daily.state==TradeState.FLAT_VERIFIED
    else:
        assert v.account.get_position('pas:BTC').quantity==held.quantity-q
        assert b.daily.state!=TradeState.FLAT_VERIFIED


def test_pas_partial_close_retains_global_exposure(pas_bridge):
    b=pas_bridge;enter(b);b.venue.close_fraction=D('.5');b.session._close('pas:BTC','Stop Loss Hit')
    assert b.live.account.get_positions() and b.daily.state==TradeState.RECOVERY_REQUIRED


def test_pas_subminimum_partial_is_blocked_before_entry(pas_bridge):
    b=pas_bridge
    for row in b.live.fixture.metadata['universe']:
        if row['name']=='pas:BTC':row['szDecimals']=4
    from exchange.execution_journal import fingerprint
    b.live.client.startup();b.live.provider.metadata_hash=fingerprint(b.live.client.metadata)
    enter(b);assert not b.live.transport.signed_payloads


def test_pas_gap_with_unfilled_stop_never_reports_flat(pas_bridge):
    b=pas_bridge;enter(b);v=b.live;o=v.fixture.orders[0]
    b.venue.statuses[str(o['oid'])]['order']['status']='triggered'
    v.fixture.book['levels']=[[dict(px='1',sz='100')],[dict(px='1.01',sz='100')]]
    b.recovery.recover();v.executor.reconcile_daily()
    assert v.account.get_positions() and b.daily.state!=TradeState.FLAT_VERIFIED


def test_pas_disconnect_with_stop_keeps_exposure_and_no_retry(pas_bridge):
    b=pas_bridge;enter(b);n=len(b.live.transport.signed_payloads);b.venue.internet_lost=True
    try:b.recovery.recover()
    except Exception:pass
    assert len(b.live.transport.signed_payloads)==n and b.daily.state!=TradeState.FLAT_VERIFIED


def test_pas_dynamic_position_stop_readback_cannot_qualify_fixed_route(pas_bridge):
    b=pas_bridge;enter(b);o=b.live.fixture.orders[0]
    o['isPositionTpsl']=True
    b.venue.statuses[str(o['oid'])]['order']['order']['isPositionTpsl']=True
    b.live.executor.protection.ensure_all()
    assert b.live.executor.protection.states['pas:BTC']['status']!='ACTIVE'


def test_pas_native_fill_outside_fixed_stop_limit_is_a_conflict(pas_bridge):
    b=pas_bridge;enter(b);v=b.live;held=v.account.get_position('pas:BTC');o=v.fixture.orders[0]
    b.venue.fill_protection(held.quantity)
    v.fixture.fills[-1]['px']=str(D(o['limitPx'])-1)
    v.fixture.fills[-1]['closedPnl']=str(held.quantity*(D(v.fixture.fills[-1]['px'])-held.entry_price))
    b.recovery.recover();v.executor.protection.ensure_all();v.executor.reconcile_daily()
    assert b.daily.state!=TradeState.FLAT_VERIFIED


@pytest.mark.parametrize('failure',['expiry','loss','stale_book','operator_disconnect'])
def test_pas_critical_safety_failure_prevents_entry_signatures(pas_bridge,failure):
    b=pas_bridge
    if failure=='expiry':b.live.fixture.now=b.daily.m.expires_ms
    elif failure=='loss':b.daily.data.update(equity='980',drawdown='20')
    elif failure=='operator_disconnect':b.session.account_stream.healthy=False
    else:b.live.fixture.book['time']=b.live.fixture.now-10000
    n=len(b.live.transport.signed_payloads)
    try:
        if failure=='stale_book':
            from test_long_session import frozen_long
            b.session.consume_scan(frozen_long(b.live.fixture.now//60000*60000,'pas:BTC'))
        else:enter(b)
    except ExchangeError:pass
    assert len(b.live.transport.signed_payloads)==n
