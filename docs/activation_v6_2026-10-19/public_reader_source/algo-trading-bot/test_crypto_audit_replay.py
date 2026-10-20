"""Offline audit/replay evidence, distinct from public runs and competition returns."""
from dataclasses import asdict,replace
from decimal import Decimal as D
import csv
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from crypto_paper_bot import CryptoPaperBot
from exchange.base_exchange import ExchangeError
from exchange.event_timing import timing
from exchange.hyperliquid_client import HyperliquidClient,RequestsInfoTransport
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_execution import HyperliquidExecutor,LiveTradingDisabled
from exchange.paper_execution import PaperExecution
from exchange.replay import ReplayTape,ReplayExecution,PublicReplayRecorder,checksum,ExecutionMode
from exchange.readiness import readiness
from market_regime_scanner import MarketRegimeScanner
from risk.portfolio_risk import PortfolioRisk
from test_crypto_paper_infrastructure import universe,make_bot,signal_scan,q,bar,POLICY,FEES,ROOT,load_paper_cli
from test_exchange_migration import NOW


def rows(path):
    return list(csv.DictReader(path.open()))


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def writer(bot,path):
    return load_paper_cli().ReportWriter(path,'SYNTHETIC_OFFLINE_TEST')


def replay_module():
    sys.path.insert(0,str(ROOT/'scripts'))
    spec=importlib.util.spec_from_file_location('replay_cli',ROOT/'scripts/run_crypto_replay.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def record(universe,path):
    fixture,old_market,old_scanner=universe
    recorder=PublicReplayRecorder(old_market.client.transport,clock_ms=lambda:fixture.now)
    client=HyperliquidClient(recorder,clock_ms=recorder.clock_ms)
    client.startup()
    market=HyperliquidMarketData(client)
    scanner=MarketRegimeScanner(market,old_scanner.policy)
    execution=PaperExecution(client.markets,fees=FEES,clock_ms=client.clock_ms,starting_collateral=1000)
    bot=CryptoPaperBot(market,scanner,execution,PortfolioRisk(POLICY,FEES))
    snapshot=bot.cycle()
    report=writer(bot,path/'paper').save(bot,snapshot)
    # serialize Decimal parameters as strings, just as real config JSON.
    parameters=json.loads(json.dumps(dict(starting_collateral=1000,fees=asdict(FEES),scanner=asdict(scanner.policy),risk=asdict(POLICY)),default=str))
    recorder.save(path/'tape.json',parameters,'SYNTHETIC_OFFLINE_TEST')
    return report


def test_exact_required_results_and_no_trade_evidence(universe,tmp_path):
    _,bot=make_bot(universe)
    snap=bot.cycle();w=writer(bot,tmp_path/'run');w.save(bot,snap)
    p=tmp_path/'run/results'
    for name in ('orders.jsonl','fills.jsonl','signals.jsonl','rejected_signals.jsonl','equity.csv',
                 'positions.csv','funding.csv','fees.csv','daily_metrics.csv','health_events.jsonl'):
        assert (p/name).is_file()
    assert not events(p/'fills.jsonl') and not events(p/'orders.jsonl')
    assert len(events(p/'signals.jsonl'))==11 and len(events(p/'rejected_signals.jsonl'))==11
    assert rows(p/'positions.csv')[0]['quantity']=='0'
    assert rows(p/'daily_metrics.csv')[0]['observed_daily_return']==''
    assert rows(p/'daily_metrics.csv')[0]['sample_std_observed_daily_returns']==''
    assert bot.report()['exchange_orders_submitted']==0


def test_session_hashes_and_frozen_indicator_values(universe,tmp_path):
    _,bot=make_bot(universe);snap=bot.cycle();w=writer(bot,tmp_path/'run');w.save(bot,snap)
    p=tmp_path/'run/results'
    m=json.loads((p/'session_manifest.json').read_text())
    assert len(m['git_commit'])==40 and len(m['configuration_hash'])==64
    assert len(m['working_source_hash'])==64 and len(m['exchange_adapter_version'])==64 and len(m['risk_version'])==64
    assert m['parameter_set']['scanner']['min_atr_fraction']=='0.004'
    assert m['configuration']['allow_live_orders'] is False
    signal=events(p/'signals.jsonl')[0]
    assert signal['metrics']['vwap']=='100.0' or D(signal['metrics']['vwap'])==100
    assert D(signal['metrics']['ema9'])==100 and D(signal['metrics']['ema21'])==100
    for entry in events(p/'candidate_traces.jsonl'):
        assert set(('exchange_ts','received_ts','processed_ts'))<=entry.keys()
    assert signal['exchange_ts'] is None
    assert 'input_candle_close_ms' in signal and signal['input_timing']['received_ts'] is not None


def test_repeated_save_does_not_repeat_events_or_equity(universe,tmp_path):
    _,bot=make_bot(universe);snap=bot.cycle();w=writer(bot,tmp_path/'run');w.save(bot,snap)
    p=tmp_path/'run/results'
    before={f.name:f.read_text() for f in p.iterdir()}
    w.save(bot,snap)
    assert before=={f.name:f.read_text() for f in p.iterdir()}


def test_trade_trace_connects_candidates_orders_fills_flat_and_net_pnl(universe,tmp_path):
    fixture,bot=make_bot(universe)
    snap=bot.consume_scan(signal_scan(NOW));w=writer(bot,tmp_path/'run');w.save(bot,snap)
    cid=bot.position_candidates['par:BTC']
    fixture.now+=1000
    quote=q(fixture.now,bid='108.99',ask='109.01',mark='109',oracle='109')
    snap=bot.observe({'par:BTC':quote});w.save(bot,snap)
    p=tmp_path/'run/results'
    fills=events(p/'fills.jsonl');assert len(fills)==2
    assert {f['candidate_id'] for f in fills}=={cid}
    assert all(f['simulated'] and f['exchange_ts'] is None for f in fills)
    assert D(fills[0]['price'])==D('100.01') and D(fills[1]['price'])==D('108.99')
    assert len(rows(p/'fees.csv'))==2 and len(events(p/'orders.jsonl'))>=10
    traces=events(p/'candidate_traces.jsonl')
    assert {'MARKET_DATA','SIGNAL','RISK_DECISION','EXECUTION_DECISION','ORDER','FILL','POSITION_AND_PNL','EXIT_FILL','TRADE_PNL'}<={t['stage'] for t in traces}
    pnl=next(t for t in traces if t['stage']=='TRADE_PNL')
    assert D(pnl['trade']['net_pnl'])==bot.execution.portfolio.cash-D(1000)
    assert pnl['candidate_id']==cid and rows(p/'positions.csv')[-1]['quantity']=='0'


def test_risk_rejection_is_traceable_and_has_no_order(universe,tmp_path):
    _,bot=make_bot(universe)
    bot.breakers.pause('test','SYNTHETIC_BLOCK')
    snap=bot.consume_scan(signal_scan(NOW));writer(bot,tmp_path/'run').save(bot,snap)
    p=tmp_path/'run/results'
    rejects=events(p/'rejected_signals.jsonl')
    assert rejects[-1]['reason']=='SYNTHETIC_BLOCK' and rejects[-1]['candidate_id']
    assert not events(p/'orders.jsonl') and not events(p/'fills.jsonl')


def test_oracle_equity_kept_separate_from_mark(universe,tmp_path):
    _,bot=make_bot(universe);bot.consume_scan(signal_scan(NOW))
    quote=q(bid='100',ask='100.02',mark='100.01',oracle='101')
    snap=bot.observe({'par:BTC':quote});writer(bot,tmp_path/'run').save(bot,snap)
    row=rows(tmp_path/'run/results/equity.csv')[0]
    held=bot.execution.portfolio.positions['par:BTC']
    assert D(row['oracle_equity_estimate'])-D(row['equity'])==held.quantity*(D('101')-D('100.01'))


def test_stale_halt_flushes_fills_without_new_equity(universe,tmp_path):
    fixture,bot=make_bot(universe);bot.consume_scan(signal_scan(NOW))
    w=writer(bot,tmp_path/'run');fixture.now+=6000
    w.save_halt(bot,'SYNTHETIC_STALE')
    p=tmp_path/'run/results'
    assert len(events(p/'fills.jsonl'))==1 and not rows(p/'equity.csv')
    assert json.loads((tmp_path/'run/halt.json').read_text())['equity'] is None


@pytest.mark.parametrize('exchange,received,processed,delta,skew',[
    (None,1000,1002,None,False),(900,1000,1002,100,False),(1100,1000,1002,None,True)])
def test_timestamp_provenance_and_skew(exchange,received,processed,delta,skew):
    t=timing(processed,exchange_ms=exchange,received_ms=received)
    assert t['exchange_to_receive_ms']==delta and t['clock_skew_detected']==skew
    assert t['receive_to_process_ms']==2
    assert (t['exchange_ts'] is None)==(exchange is None)


@pytest.mark.parametrize('address',[None,'','0x'+'0'*40,'bogus'])
def test_placeholder_wallet_reports_not_configured(address):
    r=readiness(address,market_ready=True)
    assert r['account_status']=='NOT_CONFIGURED' and not r['wallet_ready']
    assert r['market_data_ready'] and r['paper_trading_ready'] and not r['live_execution_ready']
    assert r['signed_actions']=='DISABLED'


def test_zero_address_cannot_issue_public_account_query():
    with pytest.raises(ExchangeError,match='NOT_CONFIGURED'):
        HyperliquidAccount(None,'0x'+'0'*40)


def test_real_format_address_is_still_unverified():
    r=readiness('0x'+'1'*40,market_ready=True)
    assert r['account_status']=='CONFIGURED_UNVERIFIED' and not r['wallet_ready'] and not r['live_execution_ready']


@pytest.mark.parametrize('method,args',[
    ('submit',(None,)),('place_order',('par:BTC',)),('cancel_order',('par:BTC','1')),
    ('modify_order',('par:BTC','1')),('close_position',('par:BTC',)),('set_leverage',('par:BTC',1))])
def test_every_live_interface_fails_before_client_access(method,args):
    class Client:
        def __getattr__(self,name):
            raise AssertionError('Client must not be accessed')
    executor=HyperliquidExecutor(Client())
    with pytest.raises(LiveTradingDisabled):
        getattr(executor,method)(*args)


def test_three_mode_architecture_keeps_runtime_paper_guard(monkeypatch):
    assert {x.value for x in ExecutionMode}=={'REPLAY','PAPER','LIVE'}
    from venue_config import require_paper_migration
    monkeypatch.setenv('EXECUTION_MODE','REPLAY')
    from venue_config import MigrationPolicyError
    with pytest.raises(MigrationPolicyError,match='PAPER_MODE_REQUIRED'):
        require_paper_migration()


def test_replay_deterministic_same_brain_no_network(universe,tmp_path,monkeypatch):
    original=record(universe,tmp_path)
    def forbidden(*args,**kwargs):
        raise AssertionError('No public transport or sockets in REPLAY')
    monkeypatch.setattr(RequestsInfoTransport,'__init__',forbidden)
    import socket
    monkeypatch.setattr(socket,'socket',forbidden)
    cli=replay_module()
    a=cli.replay(tmp_path/'tape.json',tmp_path/'replay-a')
    b=cli.replay(tmp_path/'tape.json',tmp_path/'replay-b')
    assert a['execution_mode']=='REPLAY' and a['diagnostics']==original['diagnostics']
    assert a['portfolio']==b['portfolio']==original['portfolio']
    assert a['decisions']==b['decisions']==original['decisions']
    assert a['local_fills']==0 and a['exchange_orders_submitted']==0
    for name in ('signals.jsonl','rejected_signals.jsonl','equity.csv','daily_metrics.csv','orders.jsonl','fills.jsonl'):
        assert (tmp_path/'replay-a/results'/name).read_bytes()==(tmp_path/'replay-b/results'/name).read_bytes()
    assert json.loads((tmp_path/'replay-a/replay_validation.json').read_text())['consumed_operations']>100


def tape(operations):
    value=dict(schema_version=1,cycles=1,clock_model='RECORDED_LOGICAL_CLOCK',parameters={},
               provenance='SYNTHETIC_TEST',operations=operations)
    return dict(value,sha256=checksum(value))


def test_replay_detects_tampering():
    value=tape([]);value['provenance']='MODIFIED'
    with pytest.raises(ExchangeError,match='CHECKSUM'):
        ReplayTape(value)


def test_replay_cannot_read_a_future_request_or_clock():
    t=ReplayTape(tape([dict(kind='clock',value=100),dict(kind='info',payload=dict(type='meta',dex='par'),response={})]))
    with pytest.raises(ExchangeError,match='OPERATION_MISMATCH'):
        t(dict(type='meta',dex='par'))
    assert t.clock_ms()==100
    with pytest.raises(ExchangeError,match='REQUEST_MISMATCH'):
        t(dict(type='l2Book',coin='par:BTC'))


def test_replay_rejects_backwards_clock_and_incomplete_runs():
    t=ReplayTape(tape([dict(kind='clock',value=100),dict(kind='clock',value=99)]))
    t.clock_ms()
    with pytest.raises(ExchangeError,match='NON_CAUSAL'):
        t.clock_ms()
    with pytest.raises(ExchangeError,match='UNCONSUMED'):
        ReplayTape(tape([dict(kind='clock',value=100)])).finish()


def test_replay_fill_kernel_matches_paper_partial_fill_and_fee():
    from test_crypto_paper_infrastructure import SPEC
    from exchange.order_lifecycle import OrderRequest
    systems=[cls({'par:BTC':SPEC},clock_ms=lambda:NOW,fees=FEES,starting_collateral=1000)
             for cls in (PaperExecution,ReplayExecution)]
    for execution in systems:
        quote=q(depth='.15');execution.quotes={'par:BTC':quote}
        order=execution.submit(OrderRequest('par:BTC','BUY','.2','100.02',tif='Ioc'))
        execution.simulate_fill(order.order_id,quote)
        assert execution.orders[order.order_id].status=='CANCELLED'
        assert execution.fills[0].quantity==D('.15') and execution.fills[0].price==D('100.01')
    assert systems[0].portfolio.cash==systems[1].portfolio.cash
    assert systems[0].portfolio.positions==systems[1].portfolio.positions


@pytest.mark.parametrize('key,value,reason',[('HL_NETWORK','mainnet','TESTNET_REQUIRED'),('HL_DEX','xyz','PAR_DEX_REQUIRED')])
def test_explicit_wrong_network_or_dex_revokes_local_execution(monkeypatch,key,value,reason):
    from venue_config import require_paper_migration,MigrationPolicyError
    monkeypatch.setenv(key,value)
    with pytest.raises(MigrationPolicyError,match=reason):
        require_paper_migration()


def test_account_future_aliases_are_read_only_and_preserve_actual_cash():
    from test_crypto_recovery_safety import AccountFixture
    from test_exchange_migration import TEAM
    fixture=AccountFixture();client=HyperliquidClient(fixture,clock_ms=lambda:fixture.now);client.startup()
    account=HyperliquidAccount(client,TEAM)
    assert account.get_balance()==account.get_equity().collateral_balance
    assert account.get_funding_history(NOW-1000)==account.get_funding(NOW-1000)
    assert all('action' not in request and 'signature' not in request for request in fixture.calls)
    funding=account.get_funding_history(NOW-1000)[0]
    assert funding.exchange_ts and funding.received_ts and funding.processed_ts


def test_observed_daily_returns_provisional_and_no_gap_interpolation(universe,tmp_path):
    _,bot=make_bot(universe)
    snap=bot.cycle();w=writer(bot,tmp_path/'run');w.save(bot,snap)
    w.results.save(bot,replace(snap,timestamp_ms=NOW+86400000,equity=D('1010')))
    w.results.save(bot,replace(snap,timestamp_ms=NOW+2*86400000,equity=D('999.9')))
    data=rows(tmp_path/'run/results/daily_metrics.csv')
    assert data[0]['observed_daily_return']==''
    assert D(data[1]['observed_daily_return'])==D('.01')
    assert D(data[2]['observed_daily_return'])==D('-.01')
    assert data[2]['sample_std_observed_daily_returns'] and data[2]['status']=='PROVISIONAL'
    w.results.save(bot,replace(snap,timestamp_ms=NOW+4*86400000,equity=D('1000')))
    data=rows(tmp_path/'run/results/daily_metrics.csv')
    assert len(data)==4 and data[-1]['observed_daily_return']==''


def test_simulated_funding_and_latency_not_claimed_as_exchange_settlement(universe,tmp_path):
    fixture,bot=make_bot(universe)
    boundary=NOW//3600000*3600000+3600000
    fixture.now=boundary-60000
    fixture.book["time"]=fixture.now
    bot._funding_hour=fixture.now//3600000
    bot.consume_scan(signal_scan(fixture.now))
    fixture.now=boundary
    snapshot=bot.observe({'par:BTC':q(boundary)})
    writer(bot,tmp_path/'run').save(bot,snapshot)
    p=tmp_path/'run/results'
    row=rows(p/'funding.csv')[0]
    assert row['source']=='PAPER_SNAPSHOT_ESTIMATE' and row['exchange_ts']==''
    fill=events(p/'fills.jsonl')[0]
    assert fill['simulated_submit_to_fill_ms']==0 and fill['exchange_ts'] is None
    assert fill['source']=='LOCAL_BBO_SIMULATION'
