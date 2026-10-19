"""Read-only live identity audit; never trusts a PID or cached status alone."""
from pathlib import Path
import json,time,subprocess,sys
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.terminal_app import locked,read_json
l=read_json(O/'public_observer_release_launch.json');c=read_json(R/'runtime/pas-btc-ewy-v5-2/current.json')
v=read_json(Path(c['output'])/'status.json');now=time.time_ns()//1000000
p=subprocess.run(['ps','-p',str(l['worker_pid'])+','+str(l['caffeinate_pid']),'-o','pid=,ppid=,command='],capture_output=True,text=True,check=True)
rows=[dict(pid=int(x[0]),ppid=int(x[1]),command=x[2]) for line in p.stdout.splitlines() if len(x:=line.strip().split(None,2))==3]
worker=next(x for x in rows if x['pid']==l['worker_pid']);power=next(x for x in rows if x['pid']==l['caffeinate_pid'])
source=active_source_hash(R)
identity=dict(pid=c['pid']==v['pid']==l['worker_pid'],
 command=str(R/'scripts/anchorium_cli.py')+' start --venue pas' in worker['command'] and '--state '+str(R/'runtime/pas-btc-ewy-v5-2') in worker['command'],
 caffeinate='/usr/bin/caffeinate -w '+str(l['worker_pid'])==power['command'],
 source=source==v['source_hash']==l['source_hash'],
 session=c['session_id']==v['session_id'] and abs(v['started_ms']-l['created_ms'])<10000,
 output=Path(c['output']).parent.parent==(R/'runtime/pas-btc-ewy-v5-2'),
 entry_scope=set(v.get('markets',[]))=={'pas:BTC','pas:EWY'},owner_lock=locked(R/'runtime/pas-btc-ewy-v5-2/owner.lock'),no_signer=v.get('signing_authority')=='NONE')
assert all(identity.values()),identity
r=dict(observed_ms=now,identity_checks=identity,processes=rows,worker_pid=c['pid'],session_id=c['session_id'],
 output=c['output'],source_hash=source,status=v['status'],status_age_ms=now-v['updated_ms'],
 stream_connected=v.get('stream_connected'),account_stream_healthy=v.get('account_stream_healthy'),
 last_completed_scan_ms=v.get('latest_scan_ms'),account_observed_ms=v.get('account_observed_ms'),
 readiness=v.get('readiness'),release_verification=v.get('release_verification'),
 actual_errors=v.get('actual_errors'),source_verified=True,independent_of_codex_app=worker['ppid']==1,
 health_verified=now-v['updated_ms']<=180000 and v.get('stream_connected') is True and v.get('account_stream_healthy') is True,
 terminal_flat='NOT_CLAIMED_WHILE_RUNNING',exchange_writes=0,signatures_created=0,
 dependency='Mac/Python/power/internet/exchange; process-bound caffeinate cannot guarantee operation through interruptions')
(O/'public_observer_verification.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(dict(identity_checks=identity,health_verified=r['health_verified'],status=r['status'],status_age_ms=r['status_age_ms'],pid=c['pid'],source=source)))
