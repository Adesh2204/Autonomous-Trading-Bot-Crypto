"""Evidence-only feed certification; it cannot authorize orders or tune policy."""
from collections import Counter, defaultdict
from statistics import median


class FeedCertificationReport:
    REQUIRED_CONSECUTIVE_WINDOWS=3

    @classmethod
    def evaluate(cls, *, health, traces, started_ms, finished_ms, source_unchanged,
                 checkpoint_ok, clean_shutdown, regression_passed):
        traces=sorted(traces,key=lambda t:(t['decision_ms'],t['symbol']))
        by_market=defaultdict(list)
        for t in traces:by_market[t['symbol']].append(t)
        market={}
        for symbol,rows in by_market.items():
            streak=best=passed=0
            for t in rows:
                # Feed windows use the actual scanner data check, not a forced signal.
                good=t['stages']['MARKET_DATA_HEALTHY']['status']=='PASS' and t['stages']['ENOUGH_HISTORY']['status']=='PASS'
                passed+=int(good);streak=streak+1 if good else 0;best=max(best,streak)
            market[symbol]=dict(evaluated=len(rows),healthy=passed,failed=len(rows)-passed,
                healthy_percent=100*passed/len(rows) if rows else None,
                maximum_consecutive_healthy_windows=best)
        stream=health.get('public_stream',{})
        transport=stream.get('transport',{})
        connections=transport.get('connections',[])
        lifecycle=stream.get('events',[])
        disconnections=[e for e in lifecycle if e['phase']=='DISCONNECTED']
        reason_counts=Counter(e.get('reason','UNKNOWN') for e in disconnections)
        deferred=[e for e in lifecycle if e['phase']=='REST_RECOVERY_DEFERRED']
        recovery=stream.get('account_recovery') or {}
        rate=stream.get('public_rate_budget') or {}
        reads=rate.get('public_reads') or {}
        lifetime=[c['connection_age_seconds'] for c in connections if c.get('connection_age_seconds') is not None]
        durations=[]
        for c in connections:
            durations.append(max(0,c.get('disconnected_at_ms',finished_ms)-c['connection_started_at_ms']))
        current=transport.get('current')
        if current and not current.get('disconnected_at_ms'):
            durations.append(max(0,finished_ms-current['connection_started_at_ms']))
        uptime=min(max(0,finished_ms-started_ms),sum(durations))/1000 if current else None
        subscription_ready=bool(transport and transport.get('desired_count',0)>0 and
            transport.get('confirmed_count')==transport.get('desired_count') and
            transport.get('duplicate_subscriptions')==0)
        failures_per_minute=Counter(e['timestamp_ms']//60000 for e in disconnections)
        accounting_halt='PAPER_ACCOUNTING_HALTED' in health.get('issues',[])
        checks=dict(
            transport_diagnostics_available=bool(transport),
            final_transport_recovered=bool(stream.get('connected') and stream.get('reconciled') and stream.get('last_error') is None),
            subscriptions_confirmed_once=subscription_ready,
            no_reconnect_storm=max(failures_per_minute.values(),default=0)<=5,
            no_pending_rest=reads.get('pending')==0,
            sustained_valid_market=any(v['maximum_consecutive_healthy_windows']>=cls.REQUIRED_CONSECUTIVE_WINDOWS for v in market.values()),
            final_valid_market=bool(health.get('healthy_markets')),
            paper_account_reconciled=bool(recovery and recovery.get('entries_paused') is False),
            no_accounting_halt=not accounting_halt,
            checkpoint_valid=checkpoint_ok,clean_shutdown=clean_shutdown,
            source_unchanged=source_unchanged,regression_passed=regression_passed,
            paper_lock=health.get('execution_mode')=='PAPER' and health.get('allow_live_orders') is False,
            no_exchange_orders=health.get('exchange_orders_submitted')==0)
        certified=all(checks.values())
        return dict(source='PUBLIC_PAR_PAPER_ENGINEERING_CERTIFICATION',
            verdict='FEED_READY' if certified else 'FEED_NOT_READY',
            practice_state='CONTROLLED_EXECUTION_REQUIRED' if certified else 'PRACTICE_FEED_NOT_READY',
            feed_certified=certified,controlled_execution_ready=False,practice_ready=False,live_ready=False,
            duration_seconds=(finished_ms-started_ms)/1000,transport_uptime_seconds=uptime,
            disconnect_count=len(disconnections),disconnect_reasons=dict(reason_counts),
            median_completed_connection_lifetime_seconds=median(lifetime) if lifetime else None,
            heartbeat_stale_events=sum(n for r,n in reason_counts.items() if 'HEARTBEAT_STALE' in r),
            reconnect_attempts=max(0,sum(e['phase']=='CONNECTING' for e in lifecycle)-1),
            successful_recoveries=sum(e['phase']=='REST_MARKET_RECONCILED' for e in lifecycle),
            rest_deferred_count=len(deferred),rest_retry_budget_failures=sum('INFO_RETRY_BUDGET_EXHAUSTED' in e.get('reason','') for e in deferred),
            duplicate_subscriptions=transport.get('duplicate_subscriptions'),
            public_read_budget=rate,per_market=market,checks=checks,
            blockers=[k for k,v in checks.items() if not v],
            required_consecutive_windows=cls.REQUIRED_CONSECUTIVE_WINDOWS,
            account_truth='LOCAL_PAPER_FILL_REPLAY; FUNDED_ACCOUNT_CERTIFICATION_NOT_PERFORMED',
            note='A signal or trade is not required. Historical recovered errors remain in evidence. Missing diagnostics are not a PASS. Feed readiness never grants execution permission.')
