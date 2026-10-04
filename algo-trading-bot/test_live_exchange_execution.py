"""Production execution contract tested with synthetic identities and no network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal as D
import json
from types import SimpleNamespace

from eth_account import Account
import pytest

from exchange.base_exchange import ExchangeError, Position, decimal_string
from exchange.execution_journal import ExecutionJournal, fingerprint, safe_reason
from exchange.execution_safety import (NonceManager, ClockHealthMonitor,
    HyperliquidRateLimitManager, LiveAuthorization, HumanLiveApproval)
from exchange.exchange_rules import (RiskPermission, LiveContextProvider,
    HyperliquidOrderValidator)
from exchange.hyperliquid_client import HyperliquidClient, TESTNET_API_URL, TESTNET_WS_URL
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.live_readiness import verify_live_account_readiness
from exchange.live_recovery import LiveAccountRecovery
from exchange.live_account_stream import LiveAccountStream
from exchange.sdk_transport import OfflineSDKTransport, OfficialSDKTransport, sdk_number, verify_sdk
from exchange.order_lifecycle import OrderRequest, OrderState, parse_exchange_action_result, classify_exchange_error
from exchange.protective_orders import ProtectiveOrderPlanner, CatastrophicStopPolicy
from crypto_strategy_state import CryptoStrategyState
from order_guard import OrderRoutingBlocked
from test_exchange_migration import PublicInfoFixture, NOW, TEAM


class LiveInfoFixture(PublicInfoFixture):
    def __init__(self, signer_address):
        super().__init__()
        self.book.update(time=self.now,levels=[[dict(px='99.99',sz='100')],[dict(px='100.01',sz='100')]])
        self.contexts=[dict(markPx='100',oraclePx='100',funding='.0001',openInterest='10') for _ in self.metadata['universe']]
        self.state['assetPositions']=[]
        self.state['marginSummary']['totalMarginUsed']='0'
        self.orders=[]
        self.fills=[]
        self.funding=[]
        self.agents=[dict(address=signer_address,validUntil=NOW+86400000)]
        self.active=dict(user=TEAM,coin='par:BTC',leverage=dict(type='cross',value=1),
                         maxTradeSzs=['10','10'],availableToTrade=['1000','1000'],markPx='100')
        self.limits=dict(totalOiCap='10000000',oiSzCapPerPerp='10000',
                        coinToOiCap=[[r['name'],'1000000'] for r in self.metadata['universe']])
        self.status={'status':'unknownOid'}
        self.fees=dict(userCrossRate='.00045',userAddRate='.00015')
        self.budget=dict(nRequestsUsed=0,nRequestsCap=10000)

    def __call__(self,payload):
        query=payload['type']
        if query=='frontendOpenOrders':
            self.calls.append(deepcopy(payload))
            return [dict(deepcopy(o),isTrigger=o.get('isTrigger',False),reduceOnly=o.get('reduceOnly',False))
                    for o in self.orders]
        extra={'extraAgents':self.agents,'userFees':self.fees,'userRateLimit':self.budget,
               'activeAssetData':dict(self.active,coin=payload.get('coin',self.active['coin'])),
               'perpDexLimits':self.limits,'orderStatus':self.status}
        if query in {'userFillsByTime','userFunding'}:
            self.calls.append(deepcopy(payload))
            rows=self.fills if query=='userFillsByTime' else self.funding
            return deepcopy([r for r in rows if payload['startTime']<=r['time']<=payload['endTime']])
        if query in extra:
            self.calls.append(deepcopy(payload))
            return deepcopy(extra[query])
        return super().__call__(payload)

    def position(self,size,entry='100'):
        self.state['assetPositions']=[] if not D(size) else [dict(position=dict(coin='par:BTC',
            szi=str(size),entryPx=entry,unrealizedPnl='0',marginUsed='10',liquidationPx=None))]

    def fill(self,quantity,side='B',price='100',oid=11,tid=1,closed='0',fee='.1'):
        self.fills.append(dict(coin='par:BTC',time=self.now,tid=tid,oid=oid,side=side,sz=str(quantity),
                               px=price,fee=fee,feeToken='USDPR',closedPnl=closed,startPosition='0'))


def response(row,kind='order'):
    return dict(status='ok',response=dict(type=kind,data=dict(statuses=[row])))


def permission(request,candidate='candidate:1',reason=None):
    from exchange.compliance_guard import OrderProvenance
    provenance=OrderProvenance(candidate,request.strategy_id,
        'POSITION_MANAGEMENT' if request.reduce_only else 'PULLBACK_LONG' if request.side=='BUY' else 'PULLBACK_SHORT',
        NOW-60000,request.symbol,request.side,reason or 'SYNTHETIC_BASELINE_SIGNAL',
        dict(allowed=True,source='SYNTHETIC_RISK_FIXTURE'),
        dict(allowed=True,source='SYNTHETIC_EXECUTION_FIXTURE'),
        classification='STRATEGY_EXIT' if request.reduce_only else 'STRATEGY_ENTRY',
        source_position_id='SYNTHETIC_POSITION:'+candidate if request.reduce_only else None)
    return RiskPermission(candidate,request.symbol,request.side,request.quantity,NOW,
                          request.reduce_only,reason,request.price,provenance)


@pytest.fixture
def live(tmp_path,monkeypatch):
    def no_network(*args,**kwargs):
        raise AssertionError('NETWORK_PROHIBITED_IN_SIGNED_FIXTURES')
    import requests
    monkeypatch.setattr(requests.Session,'post',no_network)
    signer=Account.create()  # Ephemeral secret stays in test memory only.
    fixture=LiveInfoFixture(signer.address)
    client=HyperliquidClient(fixture,clock_ms=lambda:fixture.now)
    client.startup()
    journal=ExecutionJournal(tmp_path/'journal.sqlite',session_id='offline:test',team_address=TEAM)
    rate=HyperliquidRateLimitManager(journal,clock_ms=lambda:fixture.now)
    clock=ClockHealthMonitor(clock_ms=lambda:fixture.now,monotonic_ms=lambda:fixture.now)
    account=HyperliquidAccount(client,TEAM)
    market=HyperliquidMarketData(client)
    provider=LiveContextProvider(market,account,signer.address,clock,rate,
                                reconciliation_ready=lambda:True,feed_ready=lambda:True)
    validator=HyperliquidOrderValidator(client)
    nonces=NonceManager(tmp_path/'nonces.sqlite',signer.address,clock_ms=lambda:fixture.now)
    transport=OfflineSDKTransport(client,signer,TEAM,nonces,[])
    recovery=SimpleNamespace(recover=lambda:SimpleNamespace(ready=True,reasons=()))
    executor=HyperliquidExecution(client,transport=transport,account=account,journal=journal,
        context_provider=provider,validator=validator,recovery=recovery,clock_health=clock,rate_limits=rate)
    executor.entries_paused=False
    value=SimpleNamespace(fixture=fixture,client=client,journal=journal,rate=rate,clock=clock,
        account=account,market=market,provider=provider,validator=validator,nonces=nonces,
        transport=transport,executor=executor,signer=signer)
    yield value
    transport.close()
    nonces.close()
    journal.close()


def valid(live,request=None):
    request=request or OrderRequest('par:BTC','BUY',D('.1'),D('100'))
    context=live.provider.load(request)
    return request,context,live.validator.validate(request,context,permission(request),NOW)


def test_sdk_pin_and_par_market_accepted(live):
    assert verify_sdk()=='0.24.0'
    request,context,result=valid(live)
    assert result.allowed and result.normalized.quantity==D('.1')
    assert result.audit['asset_id']==live.client.market('par:BTC').asset_id
    assert context.readiness.team_address==TEAM


@pytest.mark.parametrize('symbol',['BTC','ETH','GOLD','par:UNKNOWN'])
def test_native_or_unknown_markets_rejected_before_signing(live,symbol):
    with pytest.raises(ExchangeError):
        request=OrderRequest(symbol,'BUY','.1','100')
        live.executor.submit(request,permission=permission(request))
    assert not live.transport.signed_payloads


@pytest.mark.parametrize('quantity,expected',[('.123456','.1234'),('.1','.1000'),('.0001','.0001')])
def test_lot_size_rounds_down(live,quantity,expected):
    spec=live.client.market('par:BTC')
    assert spec.normalize_size(quantity)==D(expected)
    assert spec.normalize_size(quantity)<=D(quantity)


@pytest.mark.parametrize('quantity',['0','-.1','.00001'])
def test_zero_or_sub_lot_rejected(live,quantity):
    with pytest.raises(ExchangeError):
        live.client.market('par:BTC').normalize_size(quantity)


@pytest.mark.parametrize('price,side,expected',[('123.456','BUY','123.45'),('123.456','SELL','123.46'),
                                               ('12345.9','BUY','12345'),('10000','BUY','10000')])
def test_price_significant_figures_decimals_and_integer_zeros(live,price,side,expected):
    result=live.client.market('par:BTC').normalize_price(price,side)
    assert decimal_string(result)==expected
    assert sdk_number(result)==float(expected)


def test_sdk_precision_loss_rejected():
    with pytest.raises(ExchangeError,match='SDK_NUMERIC_PRECISION_LOSS'):
        sdk_number(D('0.123456789123'))


@pytest.mark.parametrize('size,allowed,code',[('.0999',False,'MIN_ORDER_NOTIONAL'),('.1',True,'ALLOWED')])
def test_minimum_notional_after_normalization(live,size,allowed,code):
    _,_,result=valid(live,OrderRequest('par:BTC','BUY',size,'100'))
    assert result.allowed is allowed and result.code==code


@pytest.mark.parametrize('damage,code',[
    ('band','PRICE_BAND_VIOLATION'),('margin','INSUFFICIENT_MARGIN'),
    ('leverage','INVALID_LEVERAGE'),('oi','OPEN_INTEREST_CAPACITY'),
    ('size_oi','OPEN_INTEREST_CAPACITY'),('total_oi','OPEN_INTEREST_CAPACITY'),
    ('stale_metadata','STALE_METADATA'),('changed_metadata','MARKET_METADATA_CHANGED'),
    ('stale_book','STALE_MARKET_DATA'),('stale_account','STALE_ACCOUNT_STATE'),
    ('feed','DATA_NOT_READY'),('self_cross','SELF_CROSS_PROHIBITED'),
    ('alo','POST_ONLY_WOULD_CROSS'),('risk_price','RISK_PRICE_PERMISSION_DENIED')])
def test_central_preflight_rejections(live,damage,code):
    request,context,_=valid(live)
    token=permission(request)
    if damage=='band':
        request=replace(request,price=D('181'))
        token=permission(request)
    elif damage=='margin':
        context=replace(context,active_asset=dict(context.active_asset,availableToTrade=['0','0']))
    elif damage=='leverage':
        context=replace(context,leverage=11)
    elif damage=='oi':
        context=replace(context,limits=dict(context.limits,coinToOiCap=[['par:BTC','1000']]))
    elif damage=='size_oi':
        context=replace(context,limits=dict(context.limits,oiSzCapPerPerp='10'))
    elif damage=='total_oi':
        context=replace(context,limits=dict(context.limits,totalOiCap='10000'))
    elif damage=='stale_metadata':
        context=replace(context,metadata_ms=NOW-60001)
    elif damage=='changed_metadata':
        context=replace(context,metadata_hash='changed')
    elif damage=='stale_book':
        context=replace(context,quote=replace(context.quote,timestamp_ms=NOW-5001))
    elif damage=='stale_account':
        context=replace(context,account_ms=NOW-5001)
    elif damage=='feed':
        context=replace(context,feed_ready=False)
    elif damage=='self_cross':
        context=replace(context,open_orders=({'coin':'par:BTC','side':'A','limitPx':'99'},))
    elif damage=='alo':
        request=replace(request,price=D('100.01'),tif='Alo')
        token=permission(request)
    elif damage=='risk_price':
        token=replace(token,limit_price=D('99'))
    result=live.validator.validate(request,context,token,NOW)
    assert not result.allowed and result.code==code
    assert not live.transport.signed_payloads


@pytest.mark.parametrize('side,size,held,allowed',[('BUY','.1','.2',False),('SELL','.3','.2',False),
    ('SELL','.2','.2',True),('BUY','.2','-.2',True),('SELL','.1','0',False)])
def test_reduce_only_direction_remaining_size_and_oi_bypass(live,side,size,held,allowed):
    live.fixture.position(held)
    live.fixture.limits={}
    request=OrderRequest('par:BTC',side,size,'100',reduce_only=True,tif='Ioc')
    context=live.provider.load(request)
    result=live.validator.validate(request,context,permission(request,reason='Target Hit'),NOW)
    assert result.allowed is allowed
    if not allowed:
        assert result.code=='REDUCE_ONLY_VIOLATION'


@pytest.mark.parametrize('row,state,remaining,cancelled',[
    ({'error':'Order must have minimum value of $10.'},OrderState.REJECTED,'0',False),
    ({'filled':{'oid':11,'totalSz':'.2','avgPx':'99.98'}},OrderState.FILLED,'0',False),
    ({'resting':{'oid':11}},OrderState.OPEN,'.2',False),
    ({'filled':{'oid':11,'totalSz':'.15','avgPx':'99.98'}},OrderState.PARTIALLY_FILLED,'.05',True),
    ({'error':'Order could not immediately match against any resting orders.'},OrderState.CANCELLED,'.2',True)])
def test_individual_response_statuses_and_ioc_remainder(row,state,remaining,cancelled):
    request=OrderRequest('par:BTC','BUY','.2','100',tif='Ioc')
    result=parse_exchange_action_result(response(row),[request])[0]
    assert result.state==state and result.remaining_quantity==D(remaining) and result.remainder_cancelled is cancelled


def test_mixed_batch_individual_errors_are_not_top_level_success():
    request=OrderRequest('par:BTC','BUY','.2','100')
    payload=response({'resting':{'oid':11}})
    payload['response']['data']['statuses'].append({'error':'Invalid size'})
    results=parse_exchange_action_result(payload,[request,request])
    assert [r.state for r in results]==[OrderState.OPEN,OrderState.REJECTED]


@pytest.mark.parametrize('row',[{'filled':{'oid':11,'totalSz':'.3','avgPx':'100'}},
                                {'filled':{'oid':True,'totalSz':'.1','avgPx':'100'}},{}])
def test_malformed_or_oversized_fill_summaries_rejected(row):
    with pytest.raises(ExchangeError):
        parse_exchange_action_result(response(row),[OrderRequest('par:BTC','BUY','.2','100')])


def test_official_signing_uses_api_wallet_testnet_domain_and_team_account(live):
    from hyperliquid.utils.signing import recover_agent_or_user_from_l1_action
    request=OrderRequest('par:BTC','BUY','.2','100',tif='Ioc')
    live.transport.responses=[response({'filled':{'oid':11,'totalSz':'.2','avgPx':'99.98'}})]
    result=live.executor.submit(request,permission=permission(request))
    payload=live.transport.signed_payloads[0]
    recovered=recover_agent_or_user_from_l1_action(payload['action'],payload['signature'],None,
                                                   payload['nonce'],None,False)
    assert recovered.lower()==live.signer.address.lower()!=TEAM.lower()
    assert live.transport._sdk.account_address==TEAM
    assert live.transport._sdk.base_url==TESTNET_API_URL
    assert payload['action']['orders'][0]['a']==live.client.market('par:BTC').asset_id
    assert result.execution_mode=='OFFLINE_SIGNED_FIXTURE'
    assert result.average_price==D('99.98') and result.source.endswith('NOT_ACCOUNTING_FILL')
    assert all(p.get('user')==TEAM for p in live.fixture.calls if p['type'] in {'extraAgents','userFees','userRateLimit',
        'clearinghouseState','openOrders','spotClearinghouseState','userAbstraction','activeAssetData'})


def test_cloid_is_durable_traceable_and_idempotent(live):
    request=OrderRequest('par:BTC','BUY','.2','100',client_order_id='same:intent')
    live.transport.responses=[response({'resting':{'oid':11}})]
    first=live.executor.submit(request,permission=permission(request))
    second=live.executor.submit(request,permission=permission(request))
    assert first==second and len(live.transport.signed_payloads)==1
    assert len(first.cloid)==34 and int(first.cloid[2:],16)>=0
    row=live.journal.intent('same:intent')
    assert row['cloid']==first.cloid and row['state']=='OPEN'
    with pytest.raises(ExchangeError,match='CLOID_INTENT_CONFLICT'):
        live.executor.submit(replace(request,quantity=D('.3')),permission=permission(replace(request,quantity=D('.3'))))


def test_timeout_never_resubmits_and_unknown_oid_does_not_prove_absence(live):
    request=OrderRequest('par:BTC','BUY','.2','100',client_order_id='timeout')
    live.transport.responses=[{'fixture_timeout':True}]
    first=live.executor.submit(request,permission=permission(request))
    assert first.state==OrderState.UNKNOWN and live.executor.entries_paused
    assert live.executor.submit(request,permission=permission(request)).state==OrderState.UNKNOWN
    recovered=live.executor.recover_uncertain('timeout')
    assert recovered.state==OrderState.UNKNOWN and len(live.transport.signed_payloads)==1
    assert any(p['type']=='orderStatus' and p['oid']==first.cloid and p['user']==TEAM for p in live.fixture.calls)


def test_uncertain_request_recovered_from_cloid_and_actual_fills(live):
    request=OrderRequest('par:BTC','BUY','.2','100',client_order_id='recovery')
    live.transport.responses=[{'fixture_timeout':True}]
    first=live.executor.submit(request,permission=permission(request))
    live.fixture.fill('.15',price='99.97')
    live.fixture.status=dict(status='order',order=dict(status='filled',order=dict(
        coin='par:BTC',oid=11,cloid=first.cloid)))
    recovered=live.executor.recover_uncertain('recovery')
    assert recovered.state==OrderState.PARTIALLY_FILLED and recovered.filled_quantity==D('.15')
    assert recovered.average_price==D('99.97') and recovered.remainder_cancelled
    assert len(live.transport.signed_payloads)==1


@pytest.mark.parametrize('damage,reason',[('expired','API_WALLET_EXPIRED'),('missing','API_WALLET_NOT_APPROVED'),
    ('mode','UNIFIED_ACCOUNT_REQUIRED'),('zero','ACCOUNT_NOT_FUNDED')])
def test_live_readiness_requires_approval_mode_and_funding(live,damage,reason):
    valid(live)
    if damage=='expired':
        live.fixture.agents[0]['validUntil']=NOW
    elif damage=='missing':
        live.fixture.agents=[]
    elif damage=='mode':
        live.fixture.mode='standard'
    else:
        live.fixture.spot['balances'][0]['total']='0'
    result=verify_live_account_readiness(live.account,live.signer.address,clock_health=live.clock,
                                        rate_limits=live.rate,reconciliation_ready=True)
    assert not result.account_ready and reason in result.reasons
    assert result.report(market_ready=True)['live_ready'] is False


def test_readiness_never_activates_from_environment_flag_or_public_address(live,monkeypatch):
    _,ctx,_=valid(live)
    monkeypatch.setenv('ALLOW_LIVE_ORDERS','true')
    assert ctx.readiness.report(market_ready=True)['final_status']=='LIVE_TECHNICALLY_READY_BUT_LOCKED'
    assert ctx.readiness.report(market_ready=True,execution=live.executor)['live_ready'] is False
    with pytest.raises(OrderRoutingBlocked):
        LiveAuthorization(clock_ms=lambda:NOW).require(TEAM,live.signer.address)
    approval=HumanLiveApproval('separate-human-test',TEAM,live.signer.address,NOW+1000,True)
    with pytest.raises(OrderRoutingBlocked):
        LiveAuthorization(approval,clock_ms=lambda:NOW).require(TEAM,live.signer.address)


def test_default_executor_and_raw_sdk_remain_locked(live):
    with pytest.raises(OrderRoutingBlocked):
        HyperliquidExecution(live.client).place_order('par:BTC','BUY','.2','100')
    with pytest.raises(ExchangeError,match='UNVALIDATED_SIGNED_FIXTURE_ACTION'):
        live.transport._sdk.order('par:BTC',True,.2,100,{'limit':{'tif':'Ioc'}})
    with pytest.raises(ExchangeError,match='RAW_SDK_POST_DISABLED'):
        live.transport._sdk.post('/exchange',{})
    assert not live.transport.signed_payloads


def test_stale_metadata_pauses_before_signing(live,monkeypatch):
    request,context,_=valid(live)
    monkeypatch.setattr(live.provider,'load',lambda _:replace(context,metadata_ms=NOW-60001))
    with pytest.raises(ExchangeError,match='STALE_METADATA'):
        live.executor.submit(request,permission=permission(request))
    assert live.executor.entries_paused and not live.transport.signed_payloads


def test_nonce_monotonic_concurrent_durable_and_exclusive(live):
    with ThreadPoolExecutor(max_workers=8) as pool:
        values=list(pool.map(lambda _:live.nonces.next(),range(100)))
    assert len(set(values))==100 and sorted(values)==list(range(NOW,NOW+100))
    with pytest.raises(ExchangeError,match='API_WALLET_ALREADY_LEASED'):
        NonceManager(live.nonces.path,live.signer.address,clock_ms=lambda:NOW)
    live.nonces.close()
    live.nonces=NonceManager(live.nonces.path,live.signer.address,clock_ms=lambda:NOW)
    assert live.nonces.next()==NOW+100


def test_clock_skew_and_wall_clock_jump_lockout(live):
    assert live.clock.observe(NOW,NOW,NOW)
    assert not live.clock.observe(NOW+3000,NOW,NOW)
    with pytest.raises(ExchangeError,match='CLOCK_HEALTH_REQUIRED'):
        live.clock.require()
    wall=[NOW]
    health=ClockHealthMonitor(clock_ms=lambda:wall[0],monotonic_ms=lambda:NOW)
    assert health.observe(NOW,NOW,NOW)
    wall[0]+=3000
    assert not health.healthy


def test_rate_budget_ip_weight_backoff_daily_count_and_cancel_at_order_limit(live):
    valid(live)
    live.rate.open_orders=1000
    with pytest.raises(ExchangeError,match='RATE_LIMITED'):
        live.rate.reserve_action(creates_order=True)
    live.rate.reserve_action()  # A cancel can free capacity at the order limit.
    live.rate.error()
    with pytest.raises(ExchangeError,match='RATE_LIMITED'):
        live.rate.reserve_action()
    live.fixture.now+=1000
    live.rate.reserve_action()
    small=HyperliquidRateLimitManager(live.journal,clock_ms=lambda:NOW,ip_weight_limit=2)
    small.reserve_info('l2Book')
    with pytest.raises(ExchangeError):
        small.reserve_info('l2Book')
    live.rate.daily_limit=2
    with pytest.raises(ExchangeError,match='DAILY_ACTION_LIMIT'):
        live.rate.reserve_action()


def test_logs_and_journal_redact_remote_secret_values(live,caplog):
    secret='0x'+'a'*64
    live.journal.event('REMOTE_ERROR',NOW,reason='private_key='+secret,signature={'r':secret},
                       api_wallet_private_key=secret,metadata_hash='a'*64)
    data=live.journal.db.execute('SELECT data FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0]
    assert secret not in data and 'signature' not in data and 'api_wallet_private_key' not in data
    assert json.loads(data)['metadata_hash']=='a'*64
    assert secret not in safe_reason(secret) and secret not in caplog.text


def test_actual_fill_fee_funding_pnl_and_restart_history(live):
    live.fixture.fill('.2',price='99.97',fee='.123')
    live.fixture.fill('.2',side='A',price='101.84',tid=2,oid=12,closed='.374',fee='.124')
    live.fixture.funding=[dict(time=NOW,hash='0xfunding',delta=dict(type='funding',coin='par:BTC',
        usdc='-.013',szi='.2',fundingRate='.0001'))]
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    report=recovery.recover()
    realized=report.accounting['realized']
    assert report.ready and realized['gross_closed_pnl']==D('.374')
    assert realized['actual_fill_fees']==D('.247') and realized['actual_funding_cashflow']==D('-.013')
    assert realized['net_after_fees_and_funding']==D('.114')
    restarted=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    assert restarted.recover().accounting['realized']==realized


def test_restart_open_position_cannot_assume_flat_or_invent_stop(live):
    live.fixture.position('.2')
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    report=recovery.recover()
    assert not report.ready and recovery.state.quantities['par:BTC']==D('.2')
    assert any('MISSING_MANAGEMENT_HISTORY' in reason for reason in report.reasons)


def test_restart_restores_known_partial_position_and_stop_target_cooldown(live):
    live.fixture.position('.15',entry='99.97')
    live.fixture.fill('.15',price='99.97')
    manager=CryptoStrategyState('par:BTC',lambda *args:None,clock_ms=lambda:NOW)
    manager.confirm_entry(live.account.get_fills()[0],SimpleNamespace(stop=D('98'),target=D('104')))
    manager.candles_held=7
    manager.candles_since_last_sl=4
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000,managers={'par:BTC':manager})
    recovery.persist_manager(manager,candidate_id='candidate:1')
    assert recovery.recover().ready
    replacement=CryptoStrategyState('par:BTC',lambda *args:None,clock_ms=lambda:NOW)
    restarted=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000,managers={'par:BTC':replacement})
    assert restarted.restore_manager(replacement)
    assert restarted.recover().ready
    assert replacement._open_position['quantity']==D('.15')
    assert replacement._open_position['stop_loss_price']==98 and replacement._open_position['target_price']==104
    assert replacement.candles_held==7 and replacement.candles_since_last_sl==4


def test_restart_untracked_open_order_remains_paused(live):
    live.fixture.orders=[dict(coin='par:BTC',oid=12,side='B',sz='.2',limitPx='99')]
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    report=recovery.recover()
    assert not report.ready and 'UNTRACKED_EXCHANGE_OPEN_ORDERS' in report.reasons


class FakeSocket:
    def __init__(self):
        self.sent=[]
        self.closed=False
    def send(self,message):
        self.sent.append(json.loads(message))
    def close(self):
        self.closed=True


def test_websocket_disconnect_reconnect_team_subscriptions_rest_barrier(live):
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    socket=FakeSocket()
    urls=[]
    def connect(url,**kwargs):
        urls.append(url)
        return socket
    stream=LiveAccountStream(TEAM,recovery,live.executor,clock_ms=lambda:NOW,connector=connect)
    stream.connect()
    assert live.executor.entries_paused and not stream.healthy
    assert not stream.reconcile()
    assert urls==[TESTNET_WS_URL]
    assert {x['subscription']['type'] for x in socket.sent}==set(stream.CHANNELS)
    assert all(x['subscription']['user']==TEAM for x in socket.sent)
    for channel in stream.CHANNELS:
        stream.handle(dict(channel='subscriptionResponse',data=dict(subscription=dict(type=channel,user=TEAM))))
    assert stream.reconcile() and stream.healthy and not live.executor.entries_paused
    stream.handle(dict(channel='userFills',data=dict(user=TEAM,fills=[])))
    assert not stream.healthy and live.executor.entries_paused
    assert stream.reconcile()
    stream.disconnect()
    assert not stream.healthy and live.executor.entries_paused and socket.closed


def test_close_partial_fill_rechecks_authoritative_position_retains_exit_intent(live,monkeypatch):
    live.fixture.position('.2')
    request=OrderRequest('par:BTC','SELL','.2','100',reduce_only=True,tif='Ioc',strategy_id='VWAP_BASELINE_EXIT')
    live.transport.responses=[response({'filled':{'oid':11,'totalSz':'.15','avgPx':'100.02'}})]
    original=live.transport.transmit
    def transmit(payload):
        result=original(payload)
        live.fixture.position('.05')
        return result
    monkeypatch.setattr(live.transport,'transmit',transmit)
    result=live.executor.close_position('par:BTC',price='100',permission=permission(request,reason='Target Hit'))
    assert result.state==OrderState.PARTIALLY_FILLED
    assert live.account.get_position('par:BTC').quantity==D('.05')
    assert live.executor.exit_intents['par:BTC']['reason']=='Target Hit'
    assert live.transport.signed_payloads[0]['action']['orders'][0]['r'] is True


def test_cancel_and_policy_leverage_use_sdk_but_entry_replacement_requires_flat(live):
    live.fixture.orders=[dict(coin='par:BTC',oid=11,side='B',sz='.2',limitPx='99')]
    live.transport.responses=[response('success','cancel')]
    assert live.executor.cancel_order('par:BTC',11).state==OrderState.CANCELLED
    action=live.transport.signed_payloads[-1]['action']
    assert action==dict(type='cancel',cancels=[dict(a=live.client.market('par:BTC').asset_id,o=11)])
    request=OrderRequest('par:BTC','BUY','.2','99.98')
    live.transport.responses=[response({'resting':{'oid':12}})]
    with pytest.raises(ExchangeError,match='POSITION_LIMIT'):
        live.executor.modify_order('par:BTC',11,request=request,permission=permission(request))
    assert live.transport.signed_payloads[-1]['action']['type']=='cancel'
    live.transport.responses=[dict(status='ok',response={'type':'default'})]
    assert live.executor.set_leverage('par:BTC',1).state==OrderState.ACKNOWLEDGED
    with pytest.raises(ExchangeError,match='INVALID_LEVERAGE'):
        live.executor.set_leverage('par:BTC',2)


def test_cancel_by_cloid_checks_team_order_and_exact_sdk_action(live):
    cloid='0x'+'1'*32
    live.fixture.orders=[dict(coin='par:BTC',oid=11,side='B',sz='.2',limitPx='99')]
    live.fixture.status=dict(status='order',order=dict(status='open',order=dict(
        coin='par:BTC',oid=11,side='B',sz='.2',limitPx='99',cloid=cloid)))
    live.transport.responses=[response('success','cancel')]
    # Official cancelByCloid response uses the common cancel response type.
    result=live.executor.cancel_by_cloid('par:BTC',cloid)
    assert result.state==OrderState.CANCELLED
    assert live.transport.signed_payloads[-1]['action']['cancels'][0]['cloid']==cloid


def test_protective_interface_disabled_and_separate_from_normal_stop(live):
    live.fixture.position('.2')
    request=OrderRequest('par:BTC','SELL','.2','90',reduce_only=True,tif='Ioc')
    context=live.provider.load(request)
    token=permission(request,reason='Explicit catastrophic policy')
    planner=ProtectiveOrderPlanner(live.validator)
    with pytest.raises(ExchangeError,match='POLICY_DISABLED'):
        planner.prepare(request,'90','98',context,token,NOW)
    planner=ProtectiveOrderPlanner(live.validator,CatastrophicStopPolicy(True,'test:explicit-policy'))
    plan=planner.prepare(request,'90','98',context,token,NOW)
    assert plan['wire']['r'] is True and plan['wire']['t']['trigger']['tpsl']=='sl'
    assert plan['normal_strategy_stop_unchanged']=='98' and plan['exchange_submission'] is False
    with pytest.raises(ExchangeError,match='SEPARATE_FUTURE'):
        planner.activate(plan)
    assert not live.transport.signed_payloads


def test_wrong_dex_and_mainnet_fatal(live):
    with pytest.raises(ExchangeError):
        live.client.post_info('meta',dex='')
    with pytest.raises(ExchangeError):
        HyperliquidClient(live.fixture,base_url='https://api.hyperliquid.xyz')


def test_strategy_freeze_unchanged():
    from strategy_freeze import verify_strategy_freeze
    import hashlib
    from pathlib import Path
    assert verify_strategy_freeze()
    assert hashlib.sha256((Path(__file__).parent/'signal_brain.py').read_bytes()).hexdigest()==\
        'bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83'


def test_live_signal_risk_signed_entry_actual_partial_exit_restart_and_results(live,tmp_path,monkeypatch):
    from live_execution_session import LiveExecutionSession
    from live_session_results import LiveSessionResults
    from test_crypto_paper_infrastructure import signal_scan,POLICY,FEES
    from risk.portfolio_risk import PortfolioRisk
    recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    live.executor.recovery=recovery
    session=LiveExecutionSession(live.market,SimpleNamespace(),live.executor,PortfolioRisk(POLICY,FEES))
    session.attach_account_stream(SimpleNamespace(executor=live.executor,healthy=True))
    assert session.startup().ready
    original=live.transport.transmit
    actions=[0]
    def exchange_fixture(payload):
        # The signed payload is observed in memory; no HTTP sink exists.
        live.transport.signed_payloads.append(deepcopy(payload))
        wire=payload['action']['orders'][0]
        quantity=D(wire['s'])
        actions[0]+=1
        if actions[0]==1:
            filled=(quantity*D('.75')).quantize(D('.0001'))
            price='100.01'
            live.fixture.position(filled,entry=price)
            live.fixture.fill(filled,price=price,oid=11)
        elif actions[0]==2:
            filled=(quantity/D(2)).quantize(D('.0001'))
            price='105'
            live.fixture.position(quantity-filled,entry='100.01')
            live.fixture.fill(filled,side='A',price=price,oid=12,tid=2,
                              closed=str(filled*(D(price)-D('100.01'))))
        else:
            filled=quantity
            price='105'
            live.fixture.position('0')
            live.fixture.fill(filled,side='A',price=price,oid=13,tid=3,
                              closed=str(filled*(D(price)-D('100.01'))))
        return response({'filled':{'oid':10+actions[0],'totalSz':str(filled),'avgPx':price}})
    monkeypatch.setattr(live.transport,'transmit',exchange_fixture)
    session.consume_scan(signal_scan(NOW))
    assert actions[0]==1
    manager=session.managers['par:BTC']
    original_quantity=manager._open_position['quantity']
    assert original_quantity==live.account.get_position('par:BTC').quantity
    assert manager._open_position['average_entry_price']==100.01
    assert recovery.last_report.ready and session.daily_setups==1
    # An exit consumes reported fill size, preserves the remaining manager and
    # resumes the SAME target exit intent even if a later quote stops triggering.
    session._close('par:BTC','Target Hit')
    assert manager.has_open_position and manager._open_position['quantity']<original_quantity
    assert session.exit_reasons['par:BTC']=='Target Hit'
    restarted_recovery=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    live.executor.recovery=restarted_recovery
    restarted=LiveExecutionSession(live.market,SimpleNamespace(),live.executor,PortfolioRisk(POLICY,FEES))
    restarted.attach_account_stream(SimpleNamespace(executor=live.executor,healthy=True))
    assert restarted.startup().ready
    assert restarted.exit_reasons['par:BTC']=='Target Hit'
    restarted._close('par:BTC','Target Hit')
    assert not restarted.managers['par:BTC'].has_open_position
    assert live.account.get_position('par:BTC') is None
    assert not restarted.exit_reasons
    writer=LiveSessionResults(tmp_path/'evidence',restarted)
    writer.save()
    again=LiveSessionResults(tmp_path/'evidence',restarted)
    again.save()
    fills=[json.loads(x) for x in (writer.path/'fills.jsonl').read_text().splitlines()]
    assert len(fills)==3 and all(x['execution_mode']=='OFFLINE_SIGNED_FIXTURE' for x in fills)
    assert all(x['source']=='EXCHANGE_REPORTED' for x in fills)
    report=json.loads((writer.path/'actual_account_report.json').read_text())
    assert D(report['realized']['actual_fill_fees'])==D('.3')
    assert report['exchange_orders_submitted']==0 and report['confirmed_order_count']==3
    import csv
    with (writer.path/'fees.csv').open(newline='') as file:
        fee_rows=list(csv.DictReader(file))
    assert len(fee_rows)==3 and all(row['exchange_ts'] for row in fee_rows)
    assert all('private_key' not in file.read_text() and live.signer.key.hex() not in file.read_text()
               for file in writer.path.iterdir())


def test_future_runtime_construction_in_paper_stops_before_key_or_transport(live,monkeypatch,tmp_path):
    from exchange.live_runtime import build_live_runtime
    from test_crypto_paper_infrastructure import POLICY
    from market_regime_scanner import ScannerPolicy
    approval=HumanLiveApproval('separate-future-human',TEAM,live.signer.address,NOW+86400000,True)
    # No valid production approval can bypass PAPER/false configuration.
    with pytest.raises(OrderRoutingBlocked):
        build_live_runtime(team_address=TEAM,approval=approval,session_id='future',initial_start_ms=NOW,
            risk_policy=POLICY,scanner_policy=None,state_directory=tmp_path/'live')
    assert not (tmp_path/'live').exists()


def test_real_transaction_funding_hash_survives_checkpoint_without_double_accounting(live):
    live.fixture.funding=[dict(time=NOW,hash='0x'+'b'*64,delta=dict(type='funding',coin='par:BTC',
        usdc='.123456',szi='.2',fundingRate='.0001'))]
    first=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    assert first.recover().accounting['realized']['actual_funding_cashflow']==D('.123456')
    restarted=LiveAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    assert restarted.recover().accounting['realized']['actual_funding_cashflow']==D('.123456')
    assert len(restarted.state.funding)==1


def test_signer_lease_cannot_be_bypassed_by_another_nonce_database(live,tmp_path):
    with pytest.raises(ExchangeError,match='API_WALLET_ALREADY_LEASED'):
        NonceManager(tmp_path/'different.sqlite',live.signer.address,clock_ms=lambda:NOW)


def test_context_failure_revokes_entry_before_signing(live,monkeypatch):
    def unavailable(_):
        raise ExchangeError('MARKET_METADATA_CHANGED')
    monkeypatch.setattr(live.provider,'load',unavailable)
    request=OrderRequest('par:BTC','BUY','.2','100')
    with pytest.raises(ExchangeError,match='EXCHANGE_CONTEXT_UNAVAILABLE'):
        live.executor.submit(request,permission=permission(request))
    assert live.executor.entries_paused and not live.transport.signed_payloads


def test_official_production_constructor_selects_par_and_keeps_default_authorization_locked(live,monkeypatch):
    import requests
    def public_only(self,url,**kwargs):
        if url!=TESTNET_API_URL+'/info':
            raise AssertionError('NO_EXCHANGE_HTTP_ALLOWED')
        return SimpleNamespace(status_code=200,json=lambda:live.fixture(kwargs['json']),text='fixture')
    monkeypatch.setattr(requests.Session,'post',public_only)
    auth=LiveAuthorization(clock_ms=lambda:NOW)
    with pytest.raises(ExchangeError,match='API_WALLET_LOCAL_SIGNER_REQUIRED'):
        OfficialSDKTransport(live.client,SimpleNamespace(address=live.signer.address),TEAM,
                             live.nonces,auth,rate_limits=live.rate)
    production=OfficialSDKTransport(live.client,live.signer,TEAM,live.nonces,auth,rate_limits=live.rate)
    try:
        assert set(production._sdk.info.coin_to_asset)==set(live.client.markets)
        assert production._sdk.account_address==TEAM
        with pytest.raises(OrderRoutingBlocked):
            production.perform('cancel',('par:BTC',11),{},
                dict(type='cancel',cancels=[dict(a=live.client.market('par:BTC').asset_id,o=11)]),lambda:None)
    finally:
        production.close()


def test_removed_api_wallet_cannot_be_reused_after_reapproval(live):
    assert valid(live)[1].readiness.account_ready
    live.fixture.agents=[]
    removed=verify_live_account_readiness(live.account,live.signer.address,clock_health=live.clock,
        rate_limits=live.rate,reconciliation_ready=True)
    assert not removed.account_ready
    live.fixture.agents=[dict(address=live.signer.address,validUntil=NOW+86400000)]
    reapproved=verify_live_account_readiness(live.account,live.signer.address,clock_health=live.clock,
        rate_limits=live.rate,reconciliation_ready=True)
    assert not reapproved.account_ready and 'API_WALLET_RETIRED_REQUIRES_FRESH_KEY' in reapproved.reasons


def test_fill_summary_never_creates_accounting_fill_without_user_fills(live):
    request=OrderRequest('par:BTC','BUY','.2','100')
    live.transport.responses=[response({'filled':{'oid':11,'totalSz':'.2','avgPx':'99.98'}})]
    order=live.executor.submit(request,permission=permission(request))
    assert order.state==OrderState.FILLED
    assert live.account.get_fills()==[] and live.account.get_positions()=={}
    assert live.journal.checkpoint() is None


def test_metadata_runtime_change_invalidates_and_pauses_before_any_signature(live):
    live.fixture.metadata['universe'][0]['szDecimals']=3
    request=OrderRequest('par:BTC','BUY','.2','100')
    with pytest.raises(ExchangeError):
        live.executor.submit(request,permission=permission(request))
    assert not live.client.ready and live.executor.entries_paused
    assert not live.transport.signed_payloads


def test_rejection_reason_and_rate_limit_pause_retained(live):
    request=OrderRequest('par:BTC','BUY','.2','100')
    live.transport.responses=[response({'error':'Too many cumulative requests sent'})]
    result=live.executor.submit(request,permission=permission(request))
    assert result.state==OrderState.REJECTED and result.code=='RATE_LIMITED'
    assert result.reason=='Too many cumulative requests sent'
    assert live.rate.backoff_until>NOW and live.executor.entries_paused


def test_restarting_signer_with_new_nonce_store_cannot_reuse_nonce(live,tmp_path):
    live.nonces.next()
    live.nonces.close()
    with pytest.raises(ExchangeError,match='NONCE_STORE_CHANGED_FRESH_KEY_REQUIRED'):
        NonceManager(tmp_path/'new-nonces.sqlite',live.signer.address,clock_ms=lambda:NOW)
    live.nonces=NonceManager(live.nonces.path,live.signer.address,clock_ms=lambda:NOW)
    assert live.nonces.next()==NOW+1
