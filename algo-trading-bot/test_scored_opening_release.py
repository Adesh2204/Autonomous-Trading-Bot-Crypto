"""UTC calendar, unsigned PAS configuration and unchanged authority restrictions."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from exchange.base_exchange import ExchangeError
from exchange.competition_windows import SCORED_START_MS,SCORED_END_MS,require_published_window
from exchange.scored_session import ScoredLimits
from exchange.pas_configuration_plan import configuration_plan
from exchange.venue_profiles import SCORED
from exchange.testnet_certification import TEAM,API


@pytest.mark.parametrize('begin,end,valid',[
    (SCORED_START_MS-1,SCORED_START_MS+1,False),
    (SCORED_START_MS,SCORED_START_MS+1,True),
    (SCORED_START_MS+1,SCORED_START_MS+3600000,True),
    (SCORED_END_MS-3600000,SCORED_END_MS,True),
    (SCORED_END_MS-1,SCORED_END_MS+1,False),
    (SCORED_END_MS,SCORED_END_MS+1,False),
    (SCORED_START_MS,SCORED_START_MS,False),
    (True,SCORED_END_MS,False)])
def test_exact_published_utc_boundary(begin,end,valid):
    if valid:assert require_published_window(begin,end)=='SCORED'
    else:
        with pytest.raises(ExchangeError):require_published_window(begin,end)


def test_calendar_has_one_shared_exact_utc_source():
    from exchange import scored_session as s
    assert s.SCORED_START_MS==SCORED_START_MS==int(datetime(2026,10,19,12,tzinfo=timezone.utc).timestamp()*1000)
    assert s.SCORED_END_MS==SCORED_END_MS==int(datetime(2026,11,6,12,tzinfo=timezone.utc).timestamp()*1000)
    # Final-day trading fits, but each session remains <=24h with two attempts.
    d=ScoredLimits('offline:final',TEAM,API,('pas:BTC',),('LONG',),SCORED_END_MS-3600000,SCORED_END_MS,
        'a'*64,'fixture','20000','1000','1000','2000')
    assert d.require()
    with pytest.raises(ExchangeError):replace(d,expires_ms=SCORED_END_MS+1).require()
    with pytest.raises(ExchangeError):replace(d,starts_ms=SCORED_END_MS-86400001).require()


def configuration_observation():
    rows=[dict(symbol=s,spec=dict(symbol=s,asset_id=2810000+i,max_leverage=20),
        active_asset=dict(user=TEAM,coin=s,leverage=dict(type='cross',value=20)),observed_ms=SCORED_START_MS)
        for i,s in enumerate(sorted(SCORED.markets))]
    return dict(dex='pas',collateral='USDP',venue_identity=SCORED.identity,status='READ_ONLY_DISCOVERY_COMPLETE',
        source_hash='a'*64,source_hash_after='a'*64,journal_integrity='ok',markets=rows,
        account=dict(reported_account_equity=dict(collateral_balance='0')),account_mode='unifiedAccount',
        local_execution_state=dict(status='BLOCKED_UNRESOLVED_INTENT'),terminal_flat=True,finished_ms=SCORED_START_MS)


def test_configuration_is_only_source_bound_unsigned_plan_not_organizer_credit():
    o=configuration_observation();original=deepcopy(o);p=configuration_plan(o)
    assert o==original and p['signing_authority']=='NONE' and p['exchange_writes']==p['signatures_created']==0
    assert len(p['changes'])==len(SCORED.markets)==2 and p['organizer_credit_amount'] is None and not p['transfers_allowed']
    assert {c['symbol'] for c in p['changes']}=={'pas:BTC','pas:EWY'}
    assert 'PAS_USDP_FUNDING_REQUIRED_BEFORE_CONFIGURATION' in p['blockers']
    for c in p['changes']:assert c['requested_action']==dict(type='updateLeverage',asset=c['requested_action']['asset'],isCross=True,leverage=1)


@pytest.mark.parametrize('damage',['source','dex','coin','team','incomplete','duplicate',
    'low_max_leverage','boolean_max_leverage','duplicate_asset_id'])
def test_invalid_configuration_evidence_cannot_propose_actions(damage):
    o=configuration_observation()
    if damage=='source':o['source_hash_after']='b'*64
    elif damage=='dex':o['dex']='par'
    elif damage=='coin':o['markets'][0]['active_asset']['coin']='par:BTC'
    elif damage=='team':o['markets'][0]['active_asset']['user']=API
    elif damage=='incomplete':o['markets'].pop()
    elif damage=='low_max_leverage':o['markets'][0]['spec']['max_leverage']=0
    elif damage=='boolean_max_leverage':o['markets'][0]['spec']['max_leverage']=True
    elif damage=='duplicate_asset_id':o['markets'][1]['spec']['asset_id']=o['markets'][0]['spec']['asset_id']
    else:o['markets'].append(o['markets'][0])
    with pytest.raises(ExchangeError):configuration_plan(o)


def test_existing_one_x_cross_markets_are_not_planned_again():
    o=configuration_observation()
    for r in o['markets']:r['active_asset']['leverage']=dict(type='cross',value=1)
    p=configuration_plan(o)
    assert p['changes']==[] and {r['symbol'] for r in o['markets']}=={'pas:BTC','pas:EWY'}
    assert all(r['active_asset']['leverage']==dict(type='cross',value=1) for r in o['markets'])


def test_scored_preparation_observes_signals_even_before_native_proof(monkeypatch,tmp_path):
    from exchange import scored_prepare as m,terminal_observer
    o=configuration_observation();o['markets']=[];observed=[]
    monkeypatch.setattr(m,'discover',lambda *a,**k:o)
    monkeypatch.setattr(m,'local_execution_state',lambda root:dict(status='BLOCKED_UNRESOLVED_INTENT'))
    monkeypatch.setattr(terminal_observer,'observe',lambda *a,**k:observed.append(k) or dict(status='OFFLINE_FIXTURE',liquidity={}))
    args=SimpleNamespace(output=tmp_path/'proposal',minutes=60,maximum_notional='1000',markets=[],
        native_protection_evidence=None,release=None,organizer_confirmation=None)
    m.prepare_scored(Path(__file__).resolve().parents[1],args)
    p=json.loads((args.output/'proposal.json').read_text())
    assert observed and observed[0]['venue']=='pas' and observed[0]['once'] is True
    assert p['signing_authority']=='NONE' and not (args.output/'mandate.json').exists()
    assert 'ORGANIZER_PRACTICE_QUALIFICATION_PERMISSION_REQUIRED' not in p['blockers']


def test_public_wait_can_cross_rolling_window_without_expanding_rate_budget(tmp_path):
    from exchange.rate_limits import HyperliquidRateLimitManager
    from exchange.execution_journal import ExecutionJournal
    now=[100000];j=ExecutionJournal(tmp_path/'offline.sqlite',session_id='offline:budget',team_address=TEAM)
    try:
        r=HyperliquidRateLimitManager(j,clock_ms=lambda:now[0]);r.weights.append((now[0],1070))
        with pytest.raises(ExchangeError,match='READ_BUDGET_DEADLINE'):
            r.wait_for_read_budget(20,max_wait_seconds=45)
        r.wait_for_read_budget(20,max_wait_seconds=75,wait_ms=lambda ms:now.__setitem__(0,now[0]+ms))
        assert now[0]>=160000 and r._usage()==0 and r.policy.ip_weight_per_minute==1200
    finally:j.close()
