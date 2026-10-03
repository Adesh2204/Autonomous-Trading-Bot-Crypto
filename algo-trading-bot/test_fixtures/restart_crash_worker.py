"""Subprocess-only synthetic exchange; SIGKILL bypasses all Python cleanup."""
import json,os,signal,sys
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest,requests
from eth_account import Account
from test_live_exchange_execution import LiveInfoFixture,TEAM,NOW
from test_production_reliability import ProtectionVenue,live_session
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import NonceManager,ClockHealthMonitor,HyperliquidRateLimitManager
from exchange.exchange_rules import LiveContextProvider,HyperliquidOrderValidator
from exchange.hyperliquid_execution import HyperliquidExecution
from exchange.sdk_transport import OfflineSDKTransport


def kill():os.kill(os.getpid(),signal.SIGKILL)

def main():
    phase,journal_path,truth_path=sys.argv[1:]
    path=Path(truth_path)
    truth=json.loads(path.read_text())
    def prohibited(*a,**k):raise AssertionError('NO_EXCHANGE_HTTP')
    requests.Session.post=prohibited
    signer=Account.create()
    fixture=LiveInfoFixture(signer.address)
    for key in ('state','orders','fills','funding','budget'):setattr(fixture,key,truth[key])
    client=HyperliquidClient(fixture,clock_ms=lambda:fixture.now);client.startup()
    journal=ExecutionJournal(journal_path,session_id='offline:test',team_address=TEAM)
    rate=HyperliquidRateLimitManager(journal,clock_ms=lambda:fixture.now)
    clock=ClockHealthMonitor(clock_ms=lambda:fixture.now,monotonic_ms=lambda:fixture.now)
    account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
    provider=LiveContextProvider(market,account,signer.address,clock,rate,reconciliation_ready=lambda:True,feed_ready=lambda:True)
    nonces=NonceManager(Path(journal_path).with_name('child-nonce.sqlite'),signer.address,clock_ms=lambda:fixture.now)
    transport=OfflineSDKTransport(client,signer,TEAM,nonces,[])
    executor=HyperliquidExecution(client,transport=transport,account=account,journal=journal,context_provider=provider,
        validator=HyperliquidOrderValidator(client),recovery=SimpleNamespace(),clock_health=clock,rate_limits=rate)
    live=SimpleNamespace(fixture=fixture,client=client,journal=journal,rate=rate,clock=clock,account=account,
        market=market,provider=provider,nonces=nonces,transport=transport,executor=executor,signer=signer)
    mp=pytest.MonkeyPatch();venue=ProtectionVenue(live,mp)
    venue.statuses=truth['statuses'];venue.oid=truth['oid']
    owner,protection=live_session(live,venue)
    def save_truth():
        value={k:getattr(fixture,k) for k in ('state','orders','fills','funding','budget')}
        value.update(statuses=venue.statuses,oid=venue.oid)
        tmp=path.with_suffix('.tmp')
        with tmp.open('w') as f:json.dump(value,f,default=str);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    if phase in {'entry_fill','ledger_before_checkpoint','checkpoint_before_manager'}:
        original=owner.recovery.on_truth
        def stopped(state):
            if phase=='checkpoint_before_manager':owner.recovery.checkpoint()
            kill()
        owner.recovery.on_truth=stopped
    elif phase=='partial_exit':
        owner._persist=lambda s:kill()
    elif phase=='funding_boundary':
        original=owner.recovery.reconciler.recover
        def stopped(*a,**k):
            result=original(*a,**k);kill()
        owner.recovery.reconciler.recover=stopped
    elif phase in {'exit_before_response','protection_creation'}:
        original=venue.transmit
        def stopped(payload):
            result=original(payload)
            save_truth()
            kill()
        mp.setattr(transport,'transmit',stopped)
    owner.startup()
    if phase=='exit_before_response':
        venue.close_fraction=D('.5')
        owner._close('par:BTC','Target Hit')
    elif phase=='ws_reconnection':
        stream=SimpleNamespace(executor=executor,healthy=False,connected=True,
            subscribed={'userFills'},CHANNELS=('userFills',),generation=2)
        owner.attach_account_stream(stream)
        original=owner.recovery.recover
        def stopped():
            result=original();kill()
        owner.recovery.recover=stopped
        owner.startup_recovery.after_stream(2)
    raise AssertionError('CRASH_POINT_NOT_REACHED')

if __name__=='__main__':main()
