"""Read local PAPER heartbeat. Exit 0 healthy, 2 degraded, 3 stopped, 1 stale/missing."""
import argparse
import json
from pathlib import Path
import time


def assess(path,*,now_ms=None,max_age_seconds=90):
    value=json.loads(Path(path).read_text())
    now=time.time_ns()//1000000 if now_ms is None else now_ms
    if (value.get('execution_mode')!='PAPER' or value.get('allow_live_orders') is not False or
            value.get('exchange_orders_submitted')!=0):return 1,'PAPER_HEALTH_IDENTITY_INVALID'
    if not 0<=now-value['timestamp_ms']<=max_age_seconds*1000:return 1,'PAPER_HEARTBEAT_STALE'
    if value['status']!='RUNNING':return 3,'PAPER_PROCESS_'+value['status']
    if not value.get('data_healthy') or value['severity']!='OK':return 2,'PAPER_DATA_OR_OPERATIONS_DEGRADED'
    return 0,'PAPER_HEALTHY'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-directory',type=Path,required=True)
    args=p.parse_args()
    try:code,reason=assess(args.state_directory/'health.json')
    except (OSError,ValueError,KeyError,TypeError):code,reason=1,'PAPER_HEARTBEAT_UNAVAILABLE'
    print(json.dumps(dict(exit_code=code,reason=reason)))
    return code


if __name__=='__main__':raise SystemExit(main())
