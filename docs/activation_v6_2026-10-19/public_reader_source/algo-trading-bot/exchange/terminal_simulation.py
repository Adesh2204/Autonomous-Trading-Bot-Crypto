"""Explicit offline integration replay of the existing execution test venue.

Only the simulate command imports test fixtures/pytest. They are deliberately
not dependencies of normal public/authorized runtime. No HTTP or socket is
available; ephemeral SDK keys are discarded after each replay episode.
"""
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
import json
import socket

from .base_exchange import ExchangeError
from .paper_operations import active_source_hash, atomic_json


def simulate(root, output):
    import pytest
    from test_live_exchange_execution import live
    from test_long_session import bridge, enter
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    events=output/'events.jsonl';episodes=[]
    def emit(value):
        with events.open('a') as f:f.write(json.dumps(dict(mode='SIMULATION',**value),default=str)+'\n')
        print(f"[SIMULATION] {value.get('scenario')} | {value.get('event')} | {value.get('state')}",flush=True)
    for scenario in ('win_then_loss','rejected_entry','uncertain_entry','partial_entry','partial_exit'):
        path=output/scenario;path.mkdir()
        monkey=pytest.MonkeyPatch()
        def no_network(*a,**k):raise AssertionError('NETWORK_PROHIBITED_IN_TERMINAL_SIMULATION')
        monkey.setattr(socket.socket,'connect',no_network)
        generator=live.__wrapped__(path,monkey)
        v=next(generator)
        try:
            b=bridge.__wrapped__(v,monkey)
            if scenario=='rejected_entry':b.venue.fail='reject'
            if scenario=='uncertain_entry':b.venue.fail='timeout_before'
            if scenario=='partial_entry':b.venue.partial_entry_fraction=D('.5')
            if scenario=='partial_exit':b.venue.close_fraction=D('.5')
            for cycle in range(2 if scenario=='win_then_loss' else 1):
                try:scan=enter(b)
                except ExchangeError:scan=None
                emit(dict(scenario=scenario,event='ENTRY_RECONCILED',state=b.daily.state.value,
                    intents=[dict(r) for r in v.journal.intents()],account=b.recovery.state.report()))
                if v.account.get_positions() and scenario not in {'uncertain_entry','rejected_entry'}:
                    price=D(105) if cycle==0 else D(97)
                    v.fixture.book.update(time=v.fixture.now,levels=[[dict(px=str(price),sz='100')],[dict(px=str(price+D('.02')),sz='100')]])
                    v.fixture.contexts=[dict(markPx=str(price),oraclePx=str(price),funding='.0001',openInterest='10') for _ in v.fixture.contexts]
                    try:b.session._close('par:BTC','Target Hit' if cycle==0 else 'Stop Loss Hit')
                    except ExchangeError as exc:
                        if scenario not in {'partial_entry','partial_exit'}:raise
                        emit(dict(scenario=scenario,event='RESIDUAL_CLOSE_BLOCKED',state=b.daily.state.value,reason=str(exc)))
                    emit(dict(scenario=scenario,event='EXIT_RECONCILED',state=b.daily.state.value,
                        daily=dict(b.daily.data),account=b.recovery.state.report()))
                if scenario=='win_then_loss':v.fixture.now=(v.fixture.now//60000+1)*60000
            before=len(v.transport.signed_payloads)
            if scenario in {'rejected_entry','uncertain_entry','partial_exit'}:
                try:
                    if scan:b.session.consume_scan(scan)
                except ExchangeError:pass
                assert len(v.transport.signed_payloads)==before,'AUTOMATIC_RETRY_FORBIDDEN'
            if scenario=='win_then_loss':assert b.daily.data['cycles']==2
            if scenario=='partial_exit':assert v.account.get_positions() and b.daily.state.value=='RECOVERY_REQUIRED'
            if scenario=='uncertain_entry':assert b.daily.state.value in {'UNKNOWN','RECOVERY_REQUIRED'}
            positions=[asdict(p) for p in v.account.get_positions().values()]
            row=dict(scenario=scenario,state=b.daily.state.value,cycles=b.daily.data['cycles'],
                simulated_net=b.daily.data['realized_net'],positions=positions,open_orders=v.account.get_frontend_open_orders(),
                simulated_fills=b.recovery.state.report()['fills'],synthetic_signed_actions=len(v.transport.signed_payloads),
                integrity=v.journal.db.execute('PRAGMA integrity_check').fetchone()[0])
            episodes.append(row)
        finally:
            try:next(generator)
            except StopIteration:pass
            finally:monkey.undo()
    result=dict(mode='SIMULATION',status='SIMULATION_COMPLETE',source_hash=active_source_hash(Path(root)),
        synthetic_only=True,exchange_writes=0,actual_realized_pnl=None,episodes=episodes,
        native_qualification=False,note='Synthetic whole-unit venue makes one lot minimum-compliant. Actual par metadata is never changed; fixtures cannot qualify a real stop or account.')
    atomic_json(output/'simulation_result.json',result)
    (output/'report.md').write_text('# Anchorium SIMULATION\n\n'+json.dumps(result,indent=2,default=str)+'\n')
    return result
