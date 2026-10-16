"""Evidence for the user's per-market feed definition; never execution approval."""


def evaluate_resilience(base,samples,health):
    checks=dict(base['checks'])
    # Preserve the original certificate as separate evidence. The latest task
    # defines readiness by usable inputs, not three consecutive strategy scans.
    checks.pop('sustained_valid_market',None)
    checks.pop('final_valid_market',None)
    ready=[s for s in samples if s.get('status')=='RUNNING' and s.get('feed_ready') and
           s.get('usable_markets',0)>0 and not s.get('global_blockers')]
    span=max((s['timestamp_ms'] for s in ready),default=0)-min((s['timestamp_ms'] for s in ready),default=0)
    checks['repeated_usable_feed_observations']=len(ready)>=2 and span>=30000
    checks['safe_scanner_data_evaluation']=any(v['healthy']>0 for v in base['per_market'].values())
    checks['final_usable_market']=bool(health.get('healthy_markets') and health.get('last_operating_feed_ready'))
    checks['health_samples_checksum_matches']=base['health_samples_checksum_matches']
    checks['workers_stopped_cleanly']=health.get('public_stream',{}).get('workers_stopped_cleanly') is True
    isolation=[s for s in ready if 0<s['usable_markets']<s.get('total_markets',0)]
    events=health.get('public_stream',{}).get('market_health',{}).get('transitions',[])
    quarantined=set();restored=set()
    for e in events:
        if e['state']=='QUARANTINED':quarantined.add(e['symbol'])
        if e['state']=='HEALTHY' and e['symbol'] in quarantined:restored.add(e['symbol'])
    return dict(verdict='FEED_READY' if all(checks.values()) else 'FEED_NOT_READY',
        checks=checks,blockers=[k for k,v in checks.items() if not v],
        feed_certified=all(checks.values()),controlled_execution_ready=False,practice_ready=False,live_ready=False,
        partial_healthy_samples=len(isolation),ready_samples=len(ready),ready_sample_span_seconds=span/1000,
        quarantine_observed=sorted(quarantined),restored_after_quarantine=sorted(restored),
        final_usable_markets=health.get('healthy_markets',[]),
        note='Latest user definition: operational transport/account barrier plus genuinely usable market inputs and safe scanner evaluation. Repeated recorded usable-feed samples are required; signal/trade is not required. The older three-scanner-window certificate is retained separately, not rewritten.')
