"""Read-only final release/artifact verification; never trading authority."""
from pathlib import Path
import json,sys,hashlib,time,xml.etree.ElementTree as ET
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
load=lambda p:json.loads(Path(p).read_text())
source=active_source_hash(ROOT);r=load(OUT/'regression_release_v2/test_receipt.json');p=load(OUT/'preservation_receipt.json')
current=load(ROOT/'runtime/pas-migration-oct18/current.json');terminal=load(Path(current['output'])/'terminal_result.json')
d=load(OUT/'pas_discovery_oct18/discovery.json');proposal=load(OUT/'actual_blocked_proposal/proposal.json')
counts={k:sum(int(s.get(k,0)) for s in ET.parse(OUT/'signing_boundaries_v2.xml').getroot().iter('testsuite')) for k in ['tests','failures','errors','skipped']}
checks=dict(full_release=r.get('passed') is True and r.get('source_hash')==source==r.get('source_hash_after') and r.get('totals')==dict(tests=2850,failures=0,errors=0,skipped=0),
 xml_matches=hashlib.sha256((OUT/'regression_release_v2/regression.xml').read_bytes()).hexdigest()==r.get('xml_sha256'),
 nine_signing_boundaries=counts==dict(tests=9,failures=0,errors=0,skipped=0),preservation=p['passed'] and p['source_hash']==source,
 final_source_terminal=terminal['source_hash']==source and terminal.get('threads_stopped') is True and terminal.get('status')=='STOPPED',
 two_terminal_flat=terminal.get('terminal_flat') is True and len(terminal.get('terminal_readbacks',[]))==2 and all(x['ready'] and not x['positions'] and not x['orders'] for x in terminal['terminal_readbacks']),
 no_terminal_signatures=terminal.get('signatures_created')==0 and terminal.get('exchange_writes')==0,
 canonical_pas_discovery=d['status']=='READ_ONLY_DISCOVERY_COMPLETE' and d['source_hash']==source==d['source_hash_after'] and d['dex']=='pas' and d['collateral']=='USDP' and len(d['markets'])==10,
 actual_proposal_blocked=proposal['status']=='BLOCKED_NOT_AUTHORIZATION' and proposal['source_hash']==source and not (OUT/'actual_blocked_proposal/mandate.json').exists() and not (OUT/'actual_blocked_proposal/acceptance.json').exists())
atomic_json(OUT/'final_verification.json',dict(source_hash=source,observed_ms=time.time_ns()//1000000,checks=checks,passed=all(checks.values())))
print(json.dumps(dict(passed=all(checks.values()),checks=checks),indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
