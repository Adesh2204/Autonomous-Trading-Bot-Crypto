"""Secret-free operational safety snapshot; reporting performs no API request."""
from .execution_journal import safe_data
from .event_timing import timing


def production_safety_report(execution=None,*,rates=None,clock=None):
    import os
    report=dict(network='testnet',dex='par',api_budget='UNKNOWN',account_request_budget=None,
        daily_actions=None,nonce_manager='NOT_CONFIGURED',api_wallet_ownership='NOT_CONFIGURED',
        clock=clock.report() if clock is not None else dict(state='WARNING',reason='REFERENCE_REQUIRED'),
        position_state='UNKNOWN',positions={},catastrophic_protection='NOT_VERIFIED',
        websocket='DEGRADED',reconciliation='REQUIRED',new_entries='PAUSED',live_orders_permitted=False,
        infrastructure_implemented=dict(rate_limits=True,nonces=True,clock=True,protection=True),
        source='READ_ONLY_SAFETY_SNAPSHOT')
    if execution is not None:
        rates=execution.rate_limits
        clock=execution.clock_health
        report.update(timing(execution.client.clock_ms()),clock=clock.report(),
                      nonce_manager=execution.transport.nonces.report()['state'],
                      api_wallet_ownership='RELEASED' if execution.transport.nonces.closed else
                      'EXCLUSIVE' if execution.transport.nonces.pid==os.getpid() and not execution.transport.nonces.lease.closed
                      else 'CONFLICT')
        state=getattr(execution.recovery,'state',None)
        if state is not None and state.initialized and state.equity is not None and state.last_window is not None:
            report['positions']={s:dict(side='LONG' if p.quantity>0 else 'SHORT',quantity=str(p.quantity),
                actual_entry_price=str(p.entry_price) if p.entry_price is not None else None)
                for s,p in state.positions.items()}
            report['position_state']='OPEN' if state.positions else 'FLAT'
            report['account_truth_window']=state.last_window
        if execution.protection is not None:
            report['protection']=execution.protection.report()
            report['catastrophic_protection']='VERIFIED' if execution.protection.healthy else 'REQUIRES_REVIEW'
        feed=bool(execution.context_provider.feed_ready())
        report['websocket']='HEALTHY' if feed else 'DEGRADED'
        recovered=bool(getattr(getattr(execution.recovery,'last_report',None),'ready',False))
        report['reconciliation']='HEALTHY' if recovered else 'REQUIRED'
        from .sdk_transport import OfficialSDKTransport
        allowed=False
        if type(execution.transport) is OfficialSDKTransport:
            try:
                execution._require()
                allowed=(not execution.entries_paused and recovered and feed and clock.healthy and
                    rates.entries_allowed and execution.transport.nonces.healthy and
                    execution.protection is not None and execution.protection.entries_allowed)
            except Exception:
                pass
        report.update(new_entries='ALLOWED' if allowed else 'PAUSED',live_orders_permitted=allowed)
        if execution.position_guard is not None:
            report['single_position_guard']=execution.position_guard.report()
            report['max_global_positions']=1
            if execution.position_guard.state.value!='FLAT':
                report.update(new_entries='PAUSED',live_orders_permitted=False)
        from .compliance_report import compliance_summary
        report['compliance']=compliance_summary(execution.journal,
            mode='OFFLINE_SIGNED_FIXTURE' if type(execution.transport).__name__=='OfflineSDKTransport' else 'LIVE_TESTNET',
            position_guard=execution.position_guard)
    if rates is not None:
        usage=rates.report()
        report.update(api_budget=usage['state'],account_request_budget=dict(
            used=usage['account_requests_used'],cap=usage['account_requests_cap'],
            remaining=usage['remaining_budget'],last_refresh_ms=usage['budget_observed_ms']),
            daily_actions=dict(used=usage['daily_actions'],maximum=usage['daily_limit']),api=usage)
    return safe_data(report)


def format_safety_report(report):
    budget=report['account_request_budget'] or {}
    daily=report['daily_actions'] or {}
    rows=['TEAM ANCHORIUM — PRODUCTION SAFETY',
        'API budget: '+report['api_budget'],
        'Account request budget: '+str(budget.get('used','UNKNOWN'))+' / '+str(budget.get('cap','UNKNOWN')),
        'Daily actions: '+str(daily.get('used','UNKNOWN'))+' / '+str(daily.get('maximum','UNKNOWN')),
        'Nonce manager: '+report['nonce_manager'],'Clock: '+report['clock']['state'],
        'API wallet ownership: '+report['api_wallet_ownership'],'Position: '+report['position_state'],
        'Catastrophic protection: '+report['catastrophic_protection'],
        'WebSocket: '+report['websocket'],'Reconciliation: '+report['reconciliation'],
        'New entries: '+report['new_entries']]
    for symbol,position in report.get('protection',{}).get('positions',{}).items():
        rows.append(symbol+': '+position['status']+'; quantity='+str(position.get('actual_quantity','UNKNOWN'))+
                    '; trigger='+str(position.get('trigger_price','UNKNOWN')))
    return '\n'.join(rows)+'\n'
