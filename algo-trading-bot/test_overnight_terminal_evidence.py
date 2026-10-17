"""Operator evidence and dispatch diagnostics; no actual-wallet signatures."""
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import json
import sqlite3

import pytest
from exchange.base_exchange import MarketSpec, OrderBook, BookLevel, ExchangeError
from exchange.execution_journal import ExecutionJournal, canonical
from exchange.intent_audit import verify
from exchange.order_lifecycle import OrderRequest
from exchange.terminal_evidence import opportunity_capacity, SessionPerformance, local_execution_state
from exchange.terminal_app import render
from test_exchange_migration import NOW, TEAM


def evidence(**overrides):
    spec=MarketSpec('par:BTC',4,40,2670000)
    book=OrderBook('par:BTC',NOW,(BookLevel(D(100),D(10)),),(BookLevel(D('100.01'),D(20)),))
    active=dict(leverage=dict(type='cross',value=1),maxTradeSzs=['100','100'],availableToTrade=['10000','10000'])
    row=dict(symbol='par:BTC',observed_ms=NOW,decision='LONG',metrics=dict(hourly_funding='.0001',oracle='100'),
        economics_per_unit=dict(gross_profit='10',fees='.2',spread_cost='.01',slippage_cost='.1',funding_cost='.01',net_profit='9.68'))
    return spec,book,active,row,dict(now_ms=NOW,active_ms=NOW,fee_ms=NOW,fee_rate='.001',**overrides)


def test_capacity_retains_both_best_levels_and_does_not_grant_authority():
    spec,book,active,row,kw=evidence();r=opportunity_capacity(spec,book,active,row,**kw)
    assert D(r['liquidity_only_quantity'])==1  # bid level, not all ask depth
    assert D(r['economically_viable_notional'])>0
    assert r['authorized_executable_notional']=='0' and r['expected_net_pnl'] is None
    assert r['expected_return_probability'] is None


@pytest.mark.parametrize('amount',['.00001','.001','.01','.1','1','10','100'])
def test_quantity_is_lot_rounded_and_never_exceeds_any_bound(amount):
    spec,book,active,row,kw=evidence();book=replace(book,bids=(BookLevel(D(100),D(amount)),))
    r=opportunity_capacity(spec,book,active,row,**kw);q=D(r['liquidity_only_quantity'])
    assert q%spec.size_step==0 and q<=D(amount)*D('.1')
    assert all(q<=D(v) for v in r['quantity_bounds'].values())


@pytest.mark.parametrize('which',['book','active','fees','signal','leverage','minimum','negative_edge'])
def test_stale_or_unviable_capacity_never_becomes_an_opportunity(which):
    spec,book,active,row,kw=evidence()
    if which=='book':book=replace(book,timestamp_ms=NOW-5001)
    elif which=='active':kw['active_ms']=NOW-5001
    elif which=='fees':kw['fee_ms']=NOW-360001
    elif which=='signal':row['observed_ms']=NOW-5001
    elif which=='leverage':active['leverage']['value']=2
    elif which=='minimum':book=replace(book,bids=(BookLevel(D(100),D('.0001')),))
    else:row['economics_per_unit']['net_profit']='-.1'
    r=opportunity_capacity(spec,book,active,row,**kw)
    assert r['economically_viable_notional']=='0' and r['authorized_executable_notional']=='0'
    assert r['reasons']


def test_positive_target_but_negative_stress_and_passive_unknown_are_explicit():
    spec,book,active,row,kw=evidence();row['economics_per_unit'].update(gross_profit='1',fees='.6',net_profit='.2')
    r=opportunity_capacity(spec,book,active,row,maker_fee_rate='.0003',**kw)
    assert D(r['conditional_target_net'])>0 and D(r['stressed_conditional_target_net'])<0
    assert r['economically_viable_notional']=='0'
    assert r['passive_comparison']['fill_probability'] is None and not r['passive_comparison']['route_changed']


def test_session_performance_excludes_old_trade_and_defines_return_basis():
    p=SessionPerformance(NOW);a=dict(entries_paused=False,reasons=[],reported_account_equity={'reported_account_value':'1000'},
        fills=[dict(timestamp_ms=NOW-1,closed_pnl='100',fee='1'),dict(timestamp_ms=NOW,closed_pnl='2',fee='.1')],
        funding_events=[dict(timestamp_ms=NOW,cashflow='-.2')])
    r=p.observe(a,NOW)
    assert r['actual_net_realized']=='1.7' and D(r['realized_net_on_initial_equity_pct'])==D('.17')
    assert r['fill_count']==1 and r['official_score'] is None
    a['reported_account_equity']['reported_account_value']='900';r=p.observe(a,NOW+1)
    assert D(r['sampled_maximum_drawdown_pct'])==10
    a['entries_paused']=True;r=p.observe(a,NOW+2)
    assert r['actual_net_realized'] is None and not r['accounting_complete']


def test_missing_equity_never_uses_proposed_bankroll():
    r=SessionPerformance(NOW).observe(dict(entries_paused=False,reasons=[]),NOW)
    assert r['initial_equity'] is None and r['realized_net_on_initial_equity_pct'] is None


def test_local_unknown_is_visible_without_mutation(tmp_path):
    path=tmp_path/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
    j=ExecutionJournal(path,session_id='offline:diagnostic',team_address=TEAM)
    req=dict(symbol='par:BTC',side='BUY',quantity='.0002',price='100',strategy_id='test')
    row,_=j.reserve('x',req,'candidate',NOW);j.update('x','UNKNOWN',NOW);j.close()
    before=path.read_bytes();r=local_execution_state(tmp_path)
    assert r['status']=='BLOCKED_UNRESOLVED_INTENT' and r['unresolved'][0]['cloid']==row['cloid']
    assert path.read_bytes()==before and r['signing_authority']=='NONE'
    text=render(dict(local_execution_state=r))
    assert 'LOCAL_UNKNOWN' in text and row['cloid'] in text


def test_audit_is_append_only_redacted_and_cannot_resolve_unknown(tmp_path):
    j=ExecutionJournal(tmp_path/'j.sqlite',session_id='offline:audit',team_address=TEAM)
    row,_=j.reserve('x',{'symbol':'par:BTC','strategy_id':'test'},'c',NOW)
    j.update('x','UNKNOWN',NOW,outcome={'reason':'private_key='+'a'*64})
    proof=verify(j.db);assert proof['records']==2 and not proof['grants_resolution']
    raw=''.join(r[0] for r in j.db.execute('SELECT data FROM intent_audit'))
    assert 'a'*64 not in raw and j.intent('x')['state']=='UNKNOWN'
    for sql in ['DELETE FROM intent_audit','UPDATE intent_audit SET stage=\'FILLED\'']:
        with pytest.raises(sqlite3.IntegrityError):j.db.execute(sql)
    j.close()


def test_reservation_and_audit_are_one_atomic_transaction(tmp_path,monkeypatch):
    import exchange.intent_audit as module
    j=ExecutionJournal(tmp_path/'j.sqlite',session_id='offline:atomic',team_address=TEAM)
    def fail(*a,**k):raise OSError('disk failed before audit')
    monkeypatch.setattr(module,'append',fail)
    with pytest.raises(OSError):j.reserve('x',{'strategy_id':'test'},'c',NOW)
    assert j.intent('x') is None
    j.close()


@pytest.mark.parametrize('start,end,valid',[
    ('2026-10-16T18:00:00','2026-10-16T23:57:00',True),
    ('2026-10-16T18:00:00','2026-10-17T00:01:00',False),
    ('2026-10-17T18:00:00','2026-10-18T09:00:00',False),
    ('2026-10-19T18:00:00','2026-10-20T09:00:00',True),
    ('2026-11-06T18:00:00','2026-11-07T00:01:00',False)])
def test_published_gap_never_becomes_authority_from_a_weekend_contract(start,end,valid):
    from exchange.competition_windows import ms,require_published_window
    if valid:assert require_published_window(ms(start),ms(end)) in {'PRACTICE','SCORED'}
    else:
        with pytest.raises(ExchangeError,match='PERMISSION_NOT_VERIFIED'):require_published_window(ms(start),ms(end))


def test_dashboard_is_read_only_and_rejects_stale_flat_claim(tmp_path):
    from test_terminal_app import command
    from exchange.paper_operations import atomic_json
    atomic_json(tmp_path/'current.json',dict(session_id='old',output=str(tmp_path),pid=1))
    atomic_json(tmp_path/'status.json',dict(status='OBSERVING',updated_ms=1,terminal_flat=True))
    before=(tmp_path/'status.json').read_bytes()
    p=command('dashboard','--state',tmp_path,'--once')
    assert p.returncode==0 and 'INTERRUPTED_UNCLEAN' in p.stdout
    assert 'Terminal flat: None' in p.stdout and (tmp_path/'status.json').read_bytes()==before


def test_actual_runtime_gap_check_precedes_release_and_key_access(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import exchange.long_session as module
    from exchange.competition_windows import ms
    from test_terminal_app import ROOT
    monkeypatch.setattr(module,'read_mandate',lambda _:SimpleNamespace(daily=SimpleNamespace(
        starts_ms=ms('2026-10-17T18:00:00'),expires_ms=ms('2026-10-18T09:00:00'))))
    def forbidden(*a):raise AssertionError('Release/key path must not be reached')
    monkeypatch.setattr(module,'require_release',forbidden)
    with pytest.raises(ExchangeError,match='TRADING_WINDOW_PERMISSION'):
        module.build_long_runtime(ROOT,'not-loaded','absent','absent','absent',scanner_policy=None,risk_policy=None)


def test_incomplete_shutdown_scan_cannot_advance_full_table_or_funnel():
    from exchange.terminal_evidence import complete_scan_frame
    signals=[dict(symbol='par:BTC',baseline_long=True),dict(symbol='par:ETH',baseline_long=False)]
    rows=[dict(symbol=s['symbol'],liquidity_only_notional='20',economically_viable_notional='0') for s in signals]
    complete=complete_scan_frame(signals,{},rows,market_count=2,at=NOW)
    assert complete['latest_scan_ms']==NOW and complete['opportunity_counts']['candidate_occurrences']==1
    assert complete['opportunity_counts']['candidates_passing_capacity']==1
    assert complete['opportunity_counts']['markets_with_two_sided_capacity']==2
    assert complete_scan_frame(signals[:1],{},rows[:1],market_count=2,at=NOW+1) is None
    assert complete_scan_frame(signals,{},rows,market_count=2,at=NOW+1,cancelled=True) is None
    assert complete['latest_scan_ms']==NOW


def test_late_shutdown_fills_recompute_session_accounting_without_double_counting():
    p=SessionPerformance(NOW)
    account=dict(entries_paused=False,reasons=[],reported_account_equity={'reported_account_value':'1000'},fills=[],funding_events=[])
    assert p.observe(account,NOW)['actual_net_realized']=='0'
    account['fills']=[dict(timestamp_ms=NOW+1,closed_pnl='2',fee='.1')]
    account['funding_events']=[dict(timestamp_ms=NOW+1,cashflow='-.2')]
    final=p.observe(account,NOW+2)
    assert final['actual_net_realized']=='1.7' and final['fill_count']==1
    assert p.observe(account,NOW+2)==final
