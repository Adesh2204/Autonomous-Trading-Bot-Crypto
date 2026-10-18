"""Offline integration: real frozen brain -> existing SDK -> reported fixture fills.

All book/account/order events are synthetic fixtures; this suite cannot qualify
an actual account or native stop. No actual-wallet key or HTTP write is used.
"""
from dataclasses import replace,asdict
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json,socket
import pytest

from exchange.base_exchange import ExchangeError,Candle
from exchange.bounded_daily_session import DailyMandate,DailyLifecycle,TradeState
from exchange.long_session import (LongMandate,LongAuthorization,LongSDKTransport,DailyLongExecution,
    AllocatedLongRisk,OfflineDailyAuthority,LongAccountRecovery,DailyLongSession,DailyLimitProtection,ACKS,require_native_evidence,build_long_runtime,require_release)
from exchange.execution_journal import ExecutionJournal
from exchange.live_recovery import LiveAccountRecovery
from exchange.position_protection import ExchangeProtectionManager,ProtectionPolicy
from exchange.testnet_certification import TEAM,API
from exchange.execution_journal import fingerprint
from test_live_exchange_execution import live
from test_production_reliability import ProtectionVenue
from test_exchange_migration import NOW

ROOT=Path(__file__).resolve().parents[1]

def mandate(**changes):
    d=DailyMandate('oct16:unique',TEAM,API,('par:BTC',),('LONG',),1792120000000,1792175220000,
        'a'*64,socket.gethostname(),'1000','1000','1000','2000')
    m=LongMandate(d,1792130000000,1792130300000,*(['b'*64]*4))
    return replace(m,**changes)

def authority(tmp_path,**changes):
    m=mandate(**changes);clock=[m.created_ms+1]
    acceptance=dict(mandate_hash=m.identity,operator_acceptance='Explicit synthetic approval fixture only',
        accepted_ms=clock[0],expires_ms=m.daily.expires_ms,**{k:True for k in ACKS})
    path=tmp_path/'acceptance.json';path.write_text(json.dumps(acceptance))
    j=ExecutionJournal(tmp_path/'auth.sqlite',session_id='offline:authority',team_address=TEAM)
    a=LongAuthorization(m,path,j,clock_ms=lambda:clock[0],source_hash=lambda:m.daily.source_hash,
        policy_hash=lambda:m.reliability_sha256)
    return a,clock,j


@pytest.mark.parametrize('field,value',[
    ('maximum_signed_actions',13),('maximum_close_attempts_per_cycle',3),('maximum_cancel_actions',3),
    ('maximum_fee_rate','.004'),('execution_slippage_bps','6'),('maximum_spread_bps','16'),
    ('depth_participation','.11'),('allow_loss_making_risk_exits',False),('entry_cutoff_buffer_ms',1000),
    ('release_sha256','x'),('protection_evidence_sha256','true')])
def test_mandate_never_widens_limits(field,value):
    with pytest.raises(ExchangeError):mandate(**{field:value}).require()


@pytest.mark.parametrize('damage',['expired','source','policy','host','deleted','changed','revoked','file_revoked',*ACKS])
def test_exact_approval_is_checked_at_every_boundary(tmp_path,damage):
    a,c,j=authority(tmp_path)
    try:
        if damage=='expired':c[0]=a.m.daily.expires_ms
        elif damage=='source':a.source_hash=lambda:'c'*64
        elif damage=='policy':a.policy_hash=lambda:'c'*64
        elif damage=='host':a.host='another-host'
        elif damage=='deleted':a.path.unlink()
        elif damage=='revoked':a.revoke()
        elif damage=='file_revoked':a.path.with_name('session_revocation.json').write_text('{}')
        else:
            d=json.loads(a.path.read_text());d[damage]=False;a.path.write_text(json.dumps(d))
        with pytest.raises(ExchangeError):a.require(TEAM,API)
    finally:j.close()


def test_restart_cannot_create_a_new_signing_window(tmp_path):
    a,c,j=authority(tmp_path)
    with pytest.raises(ExchangeError,match='RESTART'):
        LongAuthorization(a.m,a.path,j,clock_ms=lambda:c[0],source_hash=a.source_hash,policy_hash=a.policy_hash)
    j.close()


def test_missing_bound_release_evidence_revokes_without_crashing_deadline_guard(tmp_path):
    a,c,j=authority(tmp_path);a.bound_evidence={str(tmp_path/'missing-release.json'):'a'*64}
    with pytest.raises(ExchangeError):a.require(TEAM,API)
    j.close()


@pytest.mark.parametrize('kind',['order','updateLeverage','cancel','batchModify','withdraw3'])
def test_unowned_or_admin_action_rejected(tmp_path,kind):
    a,c,j=authority(tmp_path)
    with pytest.raises(ExchangeError):a.check_action(dict(type=kind,orders=[],cancels=[]))
    j.close()


def test_observation_or_ephemeral_capability_cannot_construct_actual_transport(tmp_path):
    with pytest.raises(ExchangeError,match='CAPABILITY'):LongSDKTransport(None,None,None,None,SimpleNamespace())
    m=mandate()
    j=ExecutionJournal(tmp_path/'x.sqlite',session_id='offline:x',team_address=TEAM)
    try:
        with pytest.raises(ExchangeError):DailyLifecycle(j,m.daily,clock_ms=lambda:m.created_ms,
            source_hash=lambda:m.daily.source_hash,mode='AUTHORIZED_TESTNET_LONG',authorization=True)
    finally:j.close()


def test_boolean_native_certificate_cannot_qualify_any_account(tmp_path):
    p=tmp_path/'proof.json';p.write_text(json.dumps(dict(protection_verified=True,passed=True)))
    with pytest.raises((ExchangeError,KeyError)):require_native_evidence(p,mandate().daily)


def frozen_long(now,symbol='par:BTC'):
    """Deterministic input candles; no edited indicator or signal flags."""
    from frozen_strategy import FrozenStrategy
    from signal_brain import detect_daily_bias
    from market_regime_scanner import MarketDiagnostic,ScanResult
    rows=[]
    for i in range(300):
        p=D(100)+D(max(0,i-270))*D('.1');t=now-300*60000+i*60000
        rows.append(Candle(symbol,'1m',t,t+59999,p,p+D('.5'),p-D('.5'),p,D(100)))
    frame=FrozenStrategy(None).evaluate_candles(rows);v=D(str(frame.iloc[-2].VWAP));p=v+D('.01');t=now-60000
    rows[-1]=Candle(symbol,'1m',t,t+59999,p,p+D('.5'),v-D('.2'),p,D(100))
    frame=FrozenStrategy(None).evaluate_candles(rows);last=frame.iloc[-1]
    assert bool(last.Buy_Signal or last.Breakout_Signal) and not bool(last.Sell_Signal or last.Breakdown_Sell_Signal)
    signal=dict(symbol=symbol,timestamp_ms=t,reference=D(str(last.VWAP)),atr=D(str(last.ATR_14)),
        bias=detect_daily_bias(frame),long=bool(last.Buy_Signal or last.Breakout_Signal),
        short=bool(last.Sell_Signal or last.Breakdown_Sell_Signal),signal_type=last.Signal_Type)
    return ScanResult(now,[MarketDiagnostic(symbol,True,signal=signal,candles=rows)],[symbol],'ACTIVE')


@pytest.fixture
def bridge(live,monkeypatch):
    from live_execution_session import LiveExecutionSession
    from risk.portfolio_risk import PortfolioRisk
    from test_crypto_paper_infrastructure import POLICY,FEES
    symbol=live.fixture.active['coin']
    # A synthetic venue whose ONE runtime lot exceeds $10 at the planned stop.
    # Actual par lot sizes are never modified by the runtime or this fixture.
    for row in live.fixture.metadata['universe']:
        if row['name']==symbol:row['szDecimals']=0
    live.client.startup()
    live.provider.metadata_hash=fingerprint(live.client.metadata)
    live.transport._sdk.info.asset_to_sz_decimals[live.client.market(symbol).asset_id]=0
    venue=ProtectionVenue(live,monkeypatch,stop_market=False,symbol=symbol);venue.partial_entry_fraction=D(1)
    recovery=LongAccountRecovery(live.account,live.journal,initial_start_ms=NOW-60000)
    live.executor.__class__=DailyLongExecution;live.executor.recovery=recovery
    policy=ProtectionPolicy(True,'SYNTHETIC_ONLY',D(1),D('.005'))
    DailyLimitProtection(live.executor,policy=policy,managers=recovery.managers)
    from exchange.scored_session import ScoredLimits
    contract=ScoredLimits if symbol.startswith('pas:') else DailyMandate
    now=live.fixture.now
    d=contract('offline:two-cycles',live.account.team_address,live.signer.address,(symbol,),('LONG',),
        now-1000,now+3600000,'a'*64,'fixture','1000','1000','1000','2000')
    daily=DailyLifecycle(live.journal,d,clock_ms=live.client.clock_ms,source_hash=lambda:'a'*64,mode='OFFLINE_FIXTURE')
    risk=AllocatedLongRisk(PortfolioRisk(POLICY,FEES),live.market,live.account,daily)
    auth=OfflineDailyAuthority(daily);live.executor.attach_daily(daily,auth,risk)
    session=DailyLongSession(live.market,SimpleNamespace(),live.executor,risk,authority=auth)
    session.attach_account_stream(SimpleNamespace(executor=live.executor,healthy=True))
    assert session.startup().ready
    def flat():
        readings=[]
        for _ in range(2):
            live.fixture.now+=1
            readings.append(dict(source='OFFLINE_FIXTURE',team=d.team_wallet,positions=[],orders=[],ready=True,observed_ms=live.fixture.now))
        daily.confirm_flat(readings)
    flat()
    # Distinct timestamps for the coordinator's independent readbacks.
    original_positions=live.account.get_positions
    def positions():
        live.fixture.now+=1;return original_positions()
    monkeypatch.setattr(live.account,'get_positions',positions)
    return SimpleNamespace(symbol=symbol,live=live,venue=venue,recovery=recovery,daily=daily,risk=risk,session=session)


def enter(b):
    v=b.live;scan=frozen_long(v.fixture.now//60000*60000,b.symbol)
    price=D(str(scan.diagnostics[0].candles[-1].close))
    v.fixture.book.update(time=v.fixture.now,levels=[[dict(px=str(price-D('.01')),sz='100')],[dict(px=str(price+D('.01')),sz='100')]])
    v.fixture.contexts=[dict(markPx=str(price),oraclePx=str(price),funding='.0001',openInterest='10') for _ in v.fixture.contexts]
    v.fixture.active['markPx']=str(price)
    for _ in range(2):
        v.fixture.now+=1;v.fixture.book['time']=v.fixture.now
        v.clock.observe(v.fixture.now,v.fixture.now,v.fixture.now)
    b.session.consume_scan(scan)
    return scan


def test_real_frozen_signal_reaches_existing_protected_sdk_and_two_complete_cycles(bridge):
    b=bridge;v=b.live
    for cycle in range(2):
        enter(b)
        assert b.daily.state==TradeState.POSITION_MANAGED,(b.daily.data,b.risk.last_audit,
            b.session.daily_setups,b.session.managers['par:BTC'].__dict__,
            [tuple(r) for r in v.journal.db.execute("SELECT kind,data FROM events WHERE kind IN ('LIVE_RISK_DECISION','ENTRY_REJECTED')")])
        assert b.session.managers['par:BTC'].has_open_position
        assert v.fixture.orders, (
            'MISSING_PROTECTIVE_ORDER',
            v.executor.protection.report(),
            [tuple(r) for r in v.journal.db.execute(
                "SELECT kind,data FROM events WHERE kind IN "
                "('RECONCILIATION_FAILED','POST_ACTION_RECONCILIATION',"
                "'PROTECTION_ERROR','PROTECTION_MISSING','PROTECTION_ACTIVE')")],
            [dict((k,row.get(k)) for k in ('symbol','side','quantity','status','reason'))
             for row in v.executor.protection.states.values()])
        assert v.fixture.orders[0]['orderType']=='Stop Limit'
        stop=next(p['action']['orders'][0] for p in v.transport.signed_payloads if p['action'].get('orders')
            and 'trigger' in p['action']['orders'][0]['t'])
        assert stop['t']['trigger']['isMarket'] is False
        entry=[p for p in v.transport.signed_payloads if p['action']['type']=='order' and not p['action']['orders'][0]['r']][-1]
        assert entry['action']['orders'][0]['b'] is True
        previous=D(b.daily.data['realized_net'])
        price=D(105) if cycle==0 else D(97)
        v.fixture.book.update(time=v.fixture.now,levels=[[dict(px=str(price),sz='100')],[dict(px=str(price+D('.02')),sz='100')]])
        v.fixture.contexts=[dict(markPx=str(price),oraclePx=str(price),funding='.0001',openInterest='10') for _ in v.fixture.contexts]
        b.session._close('par:BTC','Target Hit' if cycle==0 else 'Stop Loss Hit')
        assert b.daily.state==TradeState.FLAT_VERIFIED,b.daily.data
        assert not v.account.get_positions() and not v.account.get_frontend_open_orders()
        assert b.daily.data['cycles']==cycle+1
        net=D(b.daily.data['realized_net'])-previous
        assert net>0 if cycle==0 else net<0
        v.fixture.now=(v.fixture.now//60000+1)*60000
    assert b.daily.data['attempts']==2
    enter(b)
    assert b.daily.data['attempts']==2


@pytest.mark.parametrize('failure',['reject','timeout_before','entry_internet_after_fill'])
def test_rejected_or_uncertain_entry_never_automatically_repeats(bridge,failure):
    b=bridge;b.venue.fail=failure
    try:scan=enter(b)
    except ExchangeError:scan=None
    before=len(b.live.transport.signed_payloads)
    if scan:
        try:b.session.consume_scan(scan)
        except ExchangeError:pass
    assert len(b.live.transport.signed_payloads)==before
    assert b.daily.state in {TradeState.REJECTED,TradeState.RECOVERY_REQUIRED,TradeState.UNKNOWN}


def test_partial_close_retains_exposure_and_stops_new_entries(bridge):
    b=bridge;enter(b);b.venue.close_fraction=D('.5')
    b.session._close('par:BTC','Stop Loss Hit')
    assert b.live.account.get_positions()
    assert b.daily.state==TradeState.RECOVERY_REQUIRED


def test_current_subminimum_partial_protection_gate_is_not_relaxed(bridge):
    b=bridge
    for row in b.live.fixture.metadata['universe']:
        if row['name']=='par:BTC':row['szDecimals']=4
    b.live.client.startup()
    b.live.provider.metadata_hash=fingerprint(b.live.client.metadata)
    enter(b)
    assert not b.live.transport.signed_payloads
    assert b.risk.last_plan is None


@pytest.mark.parametrize('failure',['reject','timeout_before','wrong_quantity'])
def test_stop_failure_keeps_exposure_and_blocks_new_entries(bridge,monkeypatch,failure):
    b=bridge;original=b.venue.transmit
    def fail_stop(payload):
        trigger=payload['action'].get('orders',[{}])[0].get('t',{}).get('trigger')
        old=b.venue.fail
        if trigger:
            if failure=='wrong_quantity':b.venue.wrong_qty=True
            else:b.venue.fail=failure
        try:return original(payload)
        finally:b.venue.fail=old
    monkeypatch.setattr(b.live.transport,'transmit',fail_stop)
    enter(b)
    assert b.live.account.get_positions()
    assert b.daily.state in {TradeState.UNPROTECTED_EXPOSURE,TradeState.UNKNOWN,TradeState.RECOVERY_REQUIRED}
    before=len(b.live.transport.signed_payloads)
    try:enter(b)
    except ExchangeError:pass
    assert len(b.live.transport.signed_payloads)==before


def test_actual_native_trigger_fills_reconcile_the_same_daily_cycle(bridge):
    b=bridge;enter(b);held=b.live.account.get_position('par:BTC').quantity
    entry=b.live.account.get_position('par:BTC').entry_price
    trigger=D(b.live.fixture.orders[0]['triggerPx'])
    b.venue.fill_protection(held)
    b.live.fixture.fills[-1]['closedPnl']=str(held*(trigger-entry))
    b.recovery.recover();b.live.executor.protection.ensure_all()
    b.live.executor.reconcile_daily()
    assert b.daily.state==TradeState.FLAT_VERIFIED
    assert D(b.daily.data['realized_net'])<0
    assert not b.live.account.get_frontend_open_orders()


def test_conflicting_reported_pnl_cannot_complete_or_profit_label_a_cycle(bridge,monkeypatch):
    b=bridge;enter(b);original=b.venue.transmit
    def wrong_pnl(payload):
        result=original(payload)
        if payload['action'].get('orders',[{}])[0].get('r'):
            b.live.fixture.fills[-1]['closedPnl']='999'
        return result
    monkeypatch.setattr(b.live.transport,'transmit',wrong_pnl)
    b.session._close('par:BTC','Stop Loss Hit')
    assert b.daily.state==TradeState.RECOVERY_REQUIRED
    assert b.daily.data['cycles']==0 and b.daily.data['realized_net']=='0'


def test_new_fee_observation_changes_allocation_before_entry(bridge):
    b=bridge;b.live.fixture.fees['userCrossRate']='.0006'
    enter(b)
    assert b.risk.fees.taker==D('.0036') and b.risk.last_plan is None
    assert not b.live.transport.signed_payloads


def test_funding_jump_in_final_preflight_cannot_use_the_older_risk_approval(bridge,monkeypatch):
    b=bridge;original=b.live.provider.load
    def changed(request,**kwargs):
        c=original(request,**kwargs)
        return replace(c,quote=replace(c.quote,hourly_funding=D('.1')))
    monkeypatch.setattr(b.live.provider,'load',changed)
    enter(b)
    assert b.risk.last_plan is not None
    assert not b.live.transport.signed_payloads
    assert b.daily.state==TradeState.RECOVERY_REQUIRED


def test_later_lost_stop_coverage_revokes_management_without_rearming(bridge):
    b=bridge;enter(b);before=len(b.live.transport.signed_payloads)
    b.venue._cancel(b.live.fixture.orders[0]['oid'])
    b.live.executor.protection.states['par:BTC']['status']='ERROR'
    b.live.executor.reconcile_daily()
    assert b.daily.state==TradeState.UNPROTECTED_EXPOSURE
    assert b.live.executor.entries_paused
    b.session._protection_barrier()
    assert len(b.live.transport.signed_payloads)==before


def test_stale_cached_stop_receipt_is_refreshed_before_declaring_lost_coverage(bridge):
    b=bridge;enter(b);before=len(b.live.transport.signed_payloads)
    b.live.fixture.now+=6000
    b.live.executor.reconcile_daily()
    assert b.daily.state==TradeState.POSITION_MANAGED
    assert len(b.live.transport.signed_payloads)==before


def test_all_approval_checks_happen_before_key_or_signer_access(tmp_path,monkeypatch):
    # A formerly passing baseline receipt cannot activate modified source.
    m=mandate();p=tmp_path/'mandate.json';p.write_text(json.dumps(asdict(m)))
    import eth_account
    monkeypatch.setattr(eth_account.Account,'from_key',lambda *_:pytest.fail('ACTUAL_KEY_ACCESS_FORBIDDEN'))
    with pytest.raises(ExchangeError,match='RELEASE'):
        build_long_runtime(ROOT,p,tmp_path/'no-acceptance',ROOT/'docs/quant_engine_2026-10-16/regression_release/test_receipt.json',
            tmp_path/'no-native-evidence',scanner_policy=None,risk_policy=None)


def test_actual_history_remains_in_account_truth_and_raw_default_recovery(tmp_path):
    # Isolated qualification view may only remove a cryptographically checked
    # historical nontransmission certificate. A new UNKNOWN is never removed.
    j=ExecutionJournal(tmp_path/'unknown.sqlite',session_id='offline:unknown',team_address=TEAM)
    row,_=j.reserve('new-unknown',dict(symbol='par:BTC',side='BUY',quantity='1',price='100',reduce_only=False),
        'candidate',NOW)
    j.update('new-unknown','UNKNOWN',NOW)
    from exchange.qualification_intent_recovery import qualification_intents
    assert qualification_intents(j)[0]['state']=='UNKNOWN'
    assert j.intents()[0]['state']=='UNKNOWN'
    j.close()
