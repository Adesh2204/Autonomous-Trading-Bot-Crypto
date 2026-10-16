"""Launch only a genuinely accepted new ten-minute SELL-only mandate, once.

Preparation of this wrapper grants no authority. Missing acceptance/provenance,
source drift, expired approval, an existing run or a consumed mandate all block.
"""
import hashlib, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from exchange.exit_recovery import RecoveryMandate, RecoveryApproval, require_recovery_regression
from exchange.paper_operations import active_source_hash, atomic_json


def main():
    proposal = BASE/'fresh_proposal'
    output = BASE/'authorized_session'
    receipt = ROOT/'docs/profit_exit_guard_repair_2026-10-15/regression_release/test_receipt.json'
    m = RecoveryMandate(**json.loads((proposal/'mandate.json').read_text())).require()
    a = RecoveryApproval(**json.loads((proposal/'recovery_approval.json').read_text()))
    a.require(m, time.time_ns()//1000000)
    provenance = json.loads((proposal/'human_approval_provenance.json').read_text())
    if (provenance.get('authorization_source')!='EXPLICIT_NEW_HUMAN_APPROVAL'
            or provenance.get('mandate_hash')!=m.identity
            or provenance.get('accepted_ms')!=a.accepted_ms
            or not provenance.get('human_reply')
            or hashlib.sha256(provenance['human_reply'].encode()).hexdigest()!=provenance.get('human_reply_sha256')):
        raise RuntimeError('GENUINE_NEW_APPROVAL_PROVENANCE_REQUIRED')
    require_recovery_regression(ROOT, receipt)
    if active_source_hash(ROOT)!=m.source_hash: raise RuntimeError('SOURCE_CHANGED')
    if output.exists() or (BASE/'launch_receipt.json').exists():
        raise RuntimeError('NO_DUPLICATE_OR_RESTART')
    args = [sys.executable,str(ROOT/'scripts/run_exit_recovery.py'),'--execute',
        '--output-directory',str(output),'--mandate',str(proposal/'mandate.json'),
        '--approval',str(proposal/'recovery_approval.json'),'--test-receipt',str(receipt)]
    with (BASE/'session_process.log').open('xb') as log:
        child = subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,
            stderr=subprocess.STDOUT,start_new_session=True)
    awake = subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(child.pid)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    r = dict(status='LAUNCHED_AWAITING_HEALTH',pid=child.pid,awake_helper_pid=awake.pid,
        launched_ms=time.time_ns()//1000000,mandate_id=m.identity,source_hash=m.source_hash,
        expires_ms=a.expires_ms,closing_cutoff_ms=a.expires_ms-15000,
        approved_quantity=m.quantity,minimum_sell=m.minimum_sell,state_directory=str(output),
        auto_restart=False,auto_renewal=False,wrapper_signed_actions=0,command=args)
    atomic_json(BASE/'launch_receipt.json',r)
    print(json.dumps(r,indent=2))


if __name__=='__main__': main()
