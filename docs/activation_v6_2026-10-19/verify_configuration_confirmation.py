"""Compare reported human completion with actual retained evidence and API reads."""
from pathlib import Path
import json,time
O=Path(__file__).resolve().parent
p=O/'post_confirmation_discovery/discovery.json';d=json.loads(p.read_text())
changes={r['symbol']:r['active_asset']['leverage'] for r in d['markets'] if r['symbol'] in ('pas:BTC','pas:EWY')}
r=dict(observed_ms=time.time_ns()//1000000,source_hash=d['source_hash'],source_hash_after=d['source_hash_after'],
 operator_reported_completion=True,report_scope='Human selected Completed and verified 1x CROSS in the chat question.',
 local_helper_directories=[str(x) for x in O.glob('human_configuration_*')],
 local_cli_acceptance_files=[str(x) for x in O.glob('human_configuration_*/acceptance.json')],
 actual_leverage=changes,exchange_readback_ms=d['finished_ms'],
 configuration_one_x_verified=all(changes.get(s)==dict(type='cross',value=1) for s in ('pas:BTC','pas:EWY')),
 evidence_file=str(p),authority_created=False,
 disposition='No CLI receipt or actual 1x readback found. Keep configuration pending; obtain terminal output. Do not substitute a chat selection for the explicitly required CLI acceptance.')
(O/'configuration_confirmation_verification.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r,indent=2))
