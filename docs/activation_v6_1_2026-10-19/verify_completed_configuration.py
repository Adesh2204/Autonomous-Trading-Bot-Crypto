"""Historical helper acceptance/result verification plus fresh PAS readbacks."""
from pathlib import Path
import json,sqlite3,sys,time
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.execution_journal import fingerprint
from exchange.pas_configuration import PasConfigurationApproval
from exchange.long_session import sha
from exchange.testnet_certification import TEAM,API
from exchange.paper_operations import atomic_json
run=R/'docs/activation_v6_2026-10-19/human_configuration_1792414356181'
p=json.loads((run/'account_configuration_plan.json').read_text());a=PasConfigurationApproval(**json.loads((run/'acceptance.json').read_text()))
result=json.loads((run/'applied/result.json').read_text());release=R/'docs/activation_v6_2026-10-19/regression_release_final/test_receipt.json'
a.require(TEAM,API,a.approved_ms)
body=dict(p);h=body.pop('plan_hash');assert h==a.plan_hash==fingerprint(body)
reg=json.loads(release.read_text());assert sha(release)==a.release_sha256 and reg['passed'] and reg['source_hash']==reg['source_hash_after']==a.source_hash
assert result['status']=='SELECTED_MARKETS_ONE_X_CROSS_VERIFIED' and result['configuration_actions_submitted']==2 and result['orders_submitted']==0
assert a.approved_ms<=result['verified_ms']<a.expires_ms
fresh_path=R/'docs/activation_v6_2026-10-19/configuration_authoritative_followup/discovery.json';fresh=json.loads(fresh_path.read_text())
leverage={r['symbol']:r['active_asset']['leverage'] for r in fresh['markets'] if r['symbol'] in ('pas:BTC','pas:EWY')}
assert leverage=={'pas:BTC':dict(type='cross',value=1),'pas:EWY':dict(type='cross',value=1)}
for r in result['results']:
 assert r['response']==dict(status='ok',response=dict(type='default'))
 assert r['readback']['leverage']==dict(type='cross',value=1)
 assert r['readback']['user'].lower()==TEAM.lower() and r['readback']['coin']==r['symbol']
r=dict(status='GENUINE_HELPER_RESULT_AND_INDEPENDENT_PAS_CONFIGURATION_VERIFIED',observed_ms=time.time_ns()//1000000,
 approved_ms=a.approved_ms,verified_ms=result['verified_ms'],fresh_readback_ms=fresh['finished_ms'],
 accepted_scope=a.scope,accepted_plan_hash=a.plan_hash,accepted_source_hash=a.source_hash,
 acceptance_sha256=sha(run/'acceptance.json'),plan_sha256=sha(run/'account_configuration_plan.json'),result_sha256=sha(run/'applied/result.json'),
 release_sha256=a.release_sha256,leverage=leverage,funding=fresh['funding'],terminal_flat=fresh['terminal_flat'],
 configuration_actions_submitted=2,orders_submitted=0,configuration_only=True,trading_authorized=False,
 evidence=dict(helper=str(run),independent_readback=str(fresh_path)),
 scope_note='Completed historical action verification. This old acceptance is not authority for another action or for the edited source.')
atomic_json(O/'completed_configuration_verification.json',r)
print(json.dumps({k:r[k] for k in ('status','leverage','configuration_actions_submitted','orders_submitted','trading_authorized')},indent=2))
