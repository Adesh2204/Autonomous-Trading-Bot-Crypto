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
    lines=['TEAM ANCHORIUM — PAPER HEALTH','',f'OVERALL: {value.get("overall",reason)}',
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
