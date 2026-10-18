"""Bounded account-only shutdown audit. Never submits or cancels an order."""
from dataclasses import asdict
import threading
import traceback
from .base_exchange import ExchangeError
from .execution_journal import safe_reason


def exception_evidence(exc):
    lines=traceback.format_exception(type(exc),exc,exc.__traceback__)
    return dict(type=type(exc).__name__,reason=safe_reason(exc),
        traceback=''.join(safe_reason(line) for line in lines)[:16384])


def terminal_reconcile(account,reconciler,truth,client,rates,clock,*,timeout_seconds=180):
    """Resume known event history with overlap, allowing one rolling rate window.

    Disconnect's permission revocation does not erase already reconciled history.
    Every snapshot is fresh and stable. Missing/uncertain history still fails the
    reconciler and never becomes proof of flatness. All venue budgets/reserves
    are unchanged; only the bounded time allowed to wait is increased.
    """
    cancel=threading.Event();timer=threading.Timer(timeout_seconds,cancel.set)
    old_cancel=client.read_cancel_event
    old_wait,old_deadline,old_progress=rates.read_budget_wait_seconds,rates.read_deadline_seconds,rates.read_progress
    client.read_cancel_event=cancel
    rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
    report=dict(terminal_readbacks=[],terminal_recovery_steps=[],terminal_recovery_started_ms=clock(),
        terminal_recovery_timeout_seconds=timeout_seconds,terminal_recovery_order_actions=0)
    def progress(event,**data):
        if event in {'WAITING_FOR_RATE_BUDGET','WAITING_FOR_READ_BACKOFF','INFO_READ_FAILED'}:
            report['terminal_recovery_steps'].append(dict(event=event,observed_ms=clock(),**data))
        if old_progress:old_progress(event,**data)
    rates.read_progress=progress;timer.start()
    phase='START'
    try:
        for index in range(2):
            phase=f'ACCOUNT_HISTORY_{index+1}'
            if cancel.is_set():raise ExchangeError('TERMINAL_RECONCILIATION_DEADLINE')
            known=truth.initialized and truth.last_window is not None and not truth.reasons
            start=max(0,truth.last_window[1]-60000) if known else 0
            report['terminal_recovery_steps'].append(dict(phase=phase,start_ms=start,known_history_overlap=known,observed_ms=clock()))
            with client.request_lock:
                reconciler.recover(truth,start_ms=start)
                phase=f'FRONTEND_ORDERS_AND_STABLE_POSITIONS_{index+1}'
                before=account.get_positions();orders=account.get_frontend_open_orders();after=account.get_positions()
            signature=lambda p:{s:(v.quantity,v.entry_price) for s,v in p.items()}
            if signature(before)!=signature(after):raise ExchangeError('POSITION_CHANGED_DURING_TERMINAL_READBACK')
            at=clock()
            if report['terminal_readbacks'] and at<=report['terminal_readbacks'][-1]['observed_ms']:
                raise ExchangeError('DISTINCT_TERMINAL_READBACK_CLOCK_REQUIRED')
            report['terminal_readbacks'].append(dict(observed_ms=at,ready=truth.initialized and not truth.reasons,
                positions=[asdict(p) for p in after.values()],orders=orders,team=account.team_address,
                source='EXCHANGE_DIRECT_TESTNET_'+getattr(client,'dex','par').upper()+'_INFO'))
    except Exception as exc:
        report.update(terminal_reconciliation_error=exception_evidence(exc),terminal_reconciliation_failed_phase=phase)
    finally:
        timer.cancel();client.read_cancel_event=old_cancel
        rates.read_budget_wait_seconds, rates.read_deadline_seconds, rates.read_progress=old_wait,old_deadline,old_progress
    rows=report['terminal_readbacks']
    flat=len(rows)==2 and all(r['ready'] and not r['positions'] and not r['orders'] for r in rows)
    last=rows[-1] if rows else None
    exposed=bool(last and (last['positions'] or last['orders']) or truth.positions or truth.orders)
    report.update(terminal_flat=flat,account_status='FLAT_VERIFIED' if flat else 'EXPOSED' if exposed else 'UNKNOWN',
        residual_status='FLAT_VERIFIED' if flat else 'EXPOSED_REQUIRES_OPERATOR' if exposed else 'UNKNOWN_REQUIRES_OPERATOR',
        account=truth.report(),account_observed_ms=last['observed_ms'] if last else None,
        terminal_recovery_finished_ms=clock(),rate_report=rates.report())
    return report
