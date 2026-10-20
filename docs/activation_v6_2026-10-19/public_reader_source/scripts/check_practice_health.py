"""Read local PAPER heartbeat. Exit 0 healthy, 2 degraded, 3 stopped, 1 stale/missing."""
import argparse
import json
from pathlib import Path
import time


def assess(path,*,now_ms=None,max_age_seconds=90):
    return assess_value(read_heartbeat(path),now_ms=now_ms,max_age_seconds=max_age_seconds)


def read_heartbeat(path):
    for attempt in range(3):
        try:return json.loads(Path(path).read_text())
        except (OSError,json.JSONDecodeError):
            if attempt==2:raise
            time.sleep(.05)


def assess_value(value,*,now_ms=None,max_age_seconds=90):
    now=time.time_ns()//1000000 if now_ms is None else now_ms
    if (value.get('execution_mode')!='PAPER' or value.get('allow_live_orders') is not False or
            value.get('exchange_orders_submitted')!=0):return 1,'PAPER_HEALTH_IDENTITY_INVALID'
    if not 0<=now-value['timestamp_ms']<=max_age_seconds*1000:return 1,'PAPER_HEARTBEAT_STALE'
    if value['status']!='RUNNING':return 3,'PAPER_PROCESS_'+value['status']
    if not value.get('data_healthy') or value['severity']!='OK':return 2,'PAPER_DATA_OR_OPERATIONS_DEGRADED'
    return 0,'PAPER_PARTIAL_HEALTHY' if value.get('overall')=='PARTIAL_HEALTHY' else 'PAPER_HEALTHY'


def describe(value,code,reason):
    stream=value.get('public_stream') or {};transport=stream.get('transport') or {}
    state='CONNECTED' if stream.get('connected') and stream.get('reconciled') else 'RECOVERING' if stream.get('connected') else 'DISCONNECTED'
    lines=['TEAM ANCHORIUM — CANDLE AVAILABILITY','Network: Hyperliquid Testnet; DEX: par','',f'OVERALL: {value.get("overall",reason)}',
        f'PROCESS: {value.get("status","UNKNOWN")}',f'TRANSPORT: {state}',
        f'SUBSCRIPTIONS: {transport.get("confirmed_count",0)} / {transport.get("desired_count",0)}',
        f'MISSING: {len(transport.get("missing_acknowledgements",[]))}; DUPLICATES: {transport.get("duplicate_subscriptions","UNKNOWN")}',
        'RECONCILIATION: '+('PASS' if value.get('reconciliation_ready') else 'NOT_READY'),
        f'USABLE MARKETS: {value.get("usable_markets",len(value.get("healthy_markets",[])))} / {value.get("total_markets","UNKNOWN")}',
        '', 'MARKETS:']
    for symbol,h in sorted(value.get('market_health',{}).items()):
        lines.append(f'  {symbol}: {h.get("state",h.get("data_state","UNKNOWN"))}')
        lines.append('    reasons: '+(', '.join(h.get('reasons',[])) or 'NONE'))
        lines.append(f'    completed bars: {h.get("completed_candles","UNKNOWN")}; data: {h.get("data_state","UNKNOWN")}')
    feed=bool(code==0 and value.get('feed_ready',value.get('data_healthy',False)))
    lines+=['', 'FEED_READY: '+('YES' if feed else 'NO'),'TRADE_READY: NO (PAPER safety lock)',
        'SIGNAL / SCANNER: '+str(value.get('scan_status','UNKNOWN')),
        'GLOBAL BLOCKER: '+(', '.join(value.get('global_blockers',value.get('issues',[]))) or 'NONE'),
        f'CHECK RESULT: {reason}; EXIT CODE: {code}',
        'ACCOUNT TRUTH: local PAPER ledger; funded execution is not certified.']
    availability=stream.get('candle_availability') or {}
    if availability:
        lines.append('CANDLE SNAPSHOT TIMESTAMP MS: '+str(availability.get('observed_at_ms')))
        lines+=['','Market | Valid in latest expected window | Missing | Contiguous tail | Last close age ms | Status']
        for symbol,r in sorted(availability.get('markets',{}).items()):
            lines.append(f'{symbol} | {r["present"]}/{r["expected_bars"]} | {r["missing"]} | {r["contiguous_valid_tail"]} | {r["last_completed_close_age_ms"]} | {r["status"]}')
            lines.append('  missing timestamps (first 5): '+str(r['missing_timestamps_ms'][:5]))
            lines.append('  classifications: '+str({t:r['missing_classifications'][str(t)] for t in r['missing_timestamps_ms'][:5]}))
            lines.append('  full UTC scanner input: '+str(r['strategy_history']))
            rec=r['recovery']
            lines.append(f'  recovery: pending={rec["pending"]}, attempts={rec["attempts"]}, failures={rec["failures"]}, recovered={rec["recovered_missing"]}, next={r["next_recovery_at_ms"]}, deferred={rec["deferred_reason"]}')
            for source,stats in ((s,r['latency'][s]) for s in ('REST','WS')):
                lines.append(f'  {source} live reception delay: n={stats["observation_count"]}, median={stats["median_ms"]}, p95={stats["p95_ms"]}, censored={stats["never_observed_intervals"]}')
        lines.append('Delay includes network/polling; exchange publication clock is unavailable. Startup history excluded from live latency.')
        market_report=stream.get('market_health') or {}
        lines.append('RECOVERY QUEUE: '+str(market_report.get('pending',[])))
        restored=[dict(symbol=e['symbol'],timestamp_ms=e['timestamp_ms']) for e in market_report.get('transitions',[])
            if e.get('state')=='HEALTHY' and e.get('from_state') in {'QUARANTINED','RECOVERING','REST_RECOVERY_PENDING'}]
        lines.append('RECENT RESTORATIONS (historical events): '+str(restored[-10:]))
    lines+=['',f'TRANSPORT_READY: {bool(code in (0,2) and value.get("transport_ready"))}',
        f'SUBSCRIPTIONS_READY: {bool(code in (0,2) and value.get("subscriptions_ready"))}',
        f'NATIVE_FEED_READY: {feed}',
        f'HEALTHY_MARKET_COUNT: {value.get("usable_markets",0)}',
        f'QUARANTINED_MARKET_COUNT: {sum(bool(h.get("quarantined")) for h in value.get("market_health",{}).values())}',
        f'SCANNER_EVALUATION_ALLOWED: {bool(code==0 and value.get("scanner_evaluation_allowed"))}',
        f'SIGNAL_AVAILABLE: {bool(value.get("signal_available"))}',
        'RATE BUDGET: '+str(stream.get('public_rate_budget') or 'UNKNOWN')]
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-directory',type=Path,required=True)
    p.add_argument('--json',action='store_true',help='Machine-readable heartbeat and result')
    args=p.parse_args()
    try:
        value=read_heartbeat(args.state_directory/'health.json');code,reason=assess_value(value)
    except (OSError,ValueError,KeyError,TypeError):value={};code,reason=1,'PAPER_HEARTBEAT_UNAVAILABLE'
    if args.json:print(json.dumps(dict(exit_code=code,reason=reason,health=value)))
    else:print(describe(value,code,reason))
    return code


if __name__=='__main__':raise SystemExit(main())
