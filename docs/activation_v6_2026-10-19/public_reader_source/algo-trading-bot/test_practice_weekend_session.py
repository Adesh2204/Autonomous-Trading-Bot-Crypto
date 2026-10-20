"""Finite Oct17–18 scope; no native evidence or exchange capability is invented."""
from dataclasses import asdict,replace
from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace
import json,socket,threading
import pytest
from exchange.base_exchange import ExchangeError
from exchange.practice_weekend_session import (PracticeWeekendLimits,PracticeWeekendLongMandate,
    PRACTICE_MAX_EXPIRY_MS,PRACTICE_ACKS,IST)
from exchange.long_session import LongMandate,LongAuthorization,ACKS,read_mandate
from exchange.overnight_session import OvernightLimits
from exchange.bounded_daily_session import DailyMandate,DailyLifecycle
from exchange.execution_journal import ExecutionJournal
from exchange.testnet_certification import TEAM,API

def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=IST).timestamp()*1000)
START=ms('2026-10-17T12:00:00');END=ms('2026-10-18T12:00:00');MID=ms('2026-10-18T00:00:00')
def limits(**changes):
    return replace(PracticeWeekendLimits('offline:practice',TEAM,API,('par:BTC',),('LONG',),START,END,
        'a'*64,socket.gethostname(),'20000','1000','1000','2000'),**changes)
def contract(**changes):
    return replace(PracticeWeekendLongMandate(limits(),START,START+300000,*(['b'*64]*4)),**changes)


@pytest.mark.parametrize('changes',[{'starts_ms':ms('2026-10-16T12:00:00')},
    {'starts_ms':ms('2026-10-18T00:00:00')},{'expires_ms':END+1},
    {'expires_ms':ms('2026-10-19T00:00:00')},{'expires_ms':START+3600000},
    {'bankroll':'20001'},{'leverage':2},{'directions':('SHORT',)},
    {'maximum_entry_attempts':3},{'maximum_concurrent_positions':2},
    {'session_loss_fraction':'.02'},{'midnight_policy':'RESET'}])
def test_new_dates_do_not_weaken_any_base_cap(changes):
    with pytest.raises(ExchangeError):limits(**changes).require()


def test_original_contracts_still_reject_the_new_dates():
    d=limits();data=asdict(d);data.pop('session_loss_fraction');data.pop('midnight_policy')
    with pytest.raises(ExchangeError):DailyMandate(**data).require()
    with pytest.raises(ExchangeError):OvernightLimits(**asdict(d)).require()
    with pytest.raises(ExchangeError):LongMandate(d,START,START+300000,*(['b'*64]*4)).require()


def test_strict_type_round_trip_and_cutoffs(tmp_path):
    m=contract().require();p=tmp_path/'mandate.json';p.write_text(json.dumps(asdict(m)))
    restored=read_mandate(p)
    assert type(restored) is PracticeWeekendLongMandate and type(restored.daily) is PracticeWeekendLimits
    assert restored.identity==m.identity and restored.daily.expires_ms-restored.daily.starts_ms==86400000
    assert END-m.entry_cutoff_buffer_ms==ms('2026-10-18T11:45:00')
    assert END-m.risk_close_buffer_ms==ms('2026-10-18T11:55:00')
    assert END<=PRACTICE_MAX_EXPIRY_MS


@pytest.mark.parametrize('changes',[{'entry_cutoff_buffer_ms':120000},{'risk_close_buffer_ms':60000},
    {'created_ms':ms('2026-10-18T00:00:00')},{'maximum_signed_actions':13},
    {'allow_loss_making_risk_exits':False},{'mode':'EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1'}])
def test_contract_requires_its_own_reviewed_windows(changes):
    with pytest.raises(ExchangeError):contract(**changes).require()


def test_fresh_extra_acknowledgments_expiry_and_revocation(tmp_path):
    m=contract();at=[START+1];p=tmp_path/'acceptance.json'
    data=dict(mandate_hash=m.identity,accepted_ms=at[0],expires_ms=END,
        operator_acceptance='OFFLINE synthetic exact acceptance',**{k:True for k in ACKS})
    p.write_text(json.dumps(data));j=ExecutionJournal(tmp_path/'j.sqlite',session_id='offline:practice-auth',team_address=TEAM)
    try:
        with pytest.raises(ExchangeError,match='PRACTICE'):LongAuthorization(m,p,j,clock_ms=lambda:at[0],source_hash=lambda:'a'*64,policy_hash=lambda:'b'*64)
        data.update({k:True for k in PRACTICE_ACKS});p.write_text(json.dumps(data))
        a=LongAuthorization(m,p,j,clock_ms=lambda:at[0],source_hash=lambda:'a'*64,policy_hash=lambda:'b'*64)
        at[0]=MID+1;a.require(TEAM,API)
        at[0]=END
        with pytest.raises(ExchangeError):a.require(TEAM,API)
        at[0]=MID+2;p.with_name('session_revocation.json').write_text('{}')
        with pytest.raises(ExchangeError):a.require(TEAM,API)
    finally:j.close()


def test_midnight_never_resets_attempts_loss_peak_or_allocation(tmp_path):
    at=[MID-1];j=ExecutionJournal(tmp_path/'j.sqlite',session_id='offline:practice-loss',team_address=TEAM)
    life=DailyLifecycle(j,limits(),clock_ms=lambda:at[0],source_hash=lambda:'a'*64,mode='OFFLINE_FIXTURE')
    try:
        life.data.update(state='FLAT_VERIFIED',attempts=2,cycles=2,allocation='1900',
            realized_net='-200',equity='19800',peak_equity='20100',drawdown='300')
        life._save('SYNTHETIC_PRE_MIDNIGHT');before=dict(life.data);at[0]=MID+1;life.require_window()
        assert life.data==before
        life.candidate('fresh-signal','par:BTC','LONG')
        with pytest.raises(ExchangeError):life.reserve_entry(1,100,allocation={},protection_fixture=True)
    finally:j.close()


def test_cli_new_contract_stays_blocked_without_native_evidence(tmp_path,monkeypatch):
    import exchange.terminal_app as app
    import exchange.terminal_observer as observer
    from exchange.paper_operations import atomic_json
    def snapshot(root,path,stop,publish,**kwargs):
        report=dict(terminal_flat=True,liquidity={'par:BTC':{'partial_protection_qualified':False}})
        publish(report);return report
    monkeypatch.setattr(observer,'observe',snapshot)
    monkeypatch.setattr(app.time,'time_ns',lambda:START*1000000)
    args=SimpleNamespace(output=tmp_path/'proposal',markets=['par:BTC'],minutes=60,overnight=False,
        practice_weekend=True,maximum_notional='1000',native_protection_evidence=None,release=None)
    assert app.prepare(tmp_path,args)==0
    p=json.loads((args.output/'proposal.json').read_text())
    assert p['status']=='BLOCKED_NOT_AUTHORIZATION'
    assert p['contract']=='EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1'
    assert p['expires_ms']==END and p['maximum_entry_attempts']==2
    assert 'SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED' in p['blockers']
    assert not (args.output/'mandate.json').exists() and not (args.output/'acceptance.json').exists()
