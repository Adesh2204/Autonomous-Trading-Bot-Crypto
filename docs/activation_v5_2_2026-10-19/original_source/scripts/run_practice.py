"""Operational PAPER launcher. No live mode, account administration or signer."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from venue_config import require_paper_migration
from exchange.runtime_schedule import RuntimeSchedule
from exchange.base_exchange import ExchangeError


def load_ops(path):
    ops=json.loads(Path(path).read_text())
    expected={'execution_mode','allow_live_orders','network','dex','session_id',
        'scan_interval_seconds','management_interval_seconds','export_interval_seconds','health_interval_seconds'}
    if (set(ops)!=expected or ops['execution_mode']!='PAPER' or ops['allow_live_orders'] is not False or
            ops['network']!='testnet' or ops['dex']!='par' or not isinstance(ops['session_id'],str) or not ops['session_id'].strip()):
        raise ExchangeError('PAPER_OPERATION_CONFIGURATION_REQUIRED')
    RuntimeSchedule(ops['scan_interval_seconds'],ops['management_interval_seconds'],ops['export_interval_seconds'])
    RuntimeSchedule(export_interval_seconds=ops['health_interval_seconds'])
    return ops


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ops-config',type=Path,default=ROOT/'configs/practice_ops.json')
    p.add_argument('--policy',type=Path,default=ROOT/'docs/paper_policy.example.json')
    p.add_argument('--state-directory',type=Path,default=ROOT/'runtime/paper')
    p.add_argument('--output-root',type=Path,default=ROOT/'algo-trading-bot/data/practice')
    p.add_argument('--duration-seconds',type=float,default=0)
    args=p.parse_args()
    try:
        require_paper_migration()
        ops=load_ops(args.ops_config)
    except (ValueError,OSError,RuntimeError) as exc:p.error(str(exc))
    from datetime import datetime,timezone
    from uuid import uuid4
    output=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    command=[sys.executable,str(ROOT/'scripts/run_crypto_paper.py'),'--cycles','0',
        '--config',str(args.policy),'--output',str(output),'--state-directory',str(args.state_directory),
        '--session-id',ops['session_id'],'--scan-interval-seconds',str(ops['scan_interval_seconds']),
        '--management-interval-seconds',str(ops['management_interval_seconds']),
        '--export-interval-seconds',str(ops['export_interval_seconds']),
        '--health-interval-seconds',str(ops['health_interval_seconds']),
        '--duration-seconds',str(args.duration_seconds)]
    # Replace the launcher so supervisors monitor the actual bot, not a parent.
    import os
    os.execv(sys.executable,command)


if __name__=='__main__':raise SystemExit(main())
