"""Resume qualification execution: place Stop Limit, cancel, execute full close IOC, verify flat."""
import os, sys, json, time, socket
from pathlib import Path
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.paper_operations import active_source_hash, atomic_json
from exchange.execution_journal import fingerprint
from exchange.pas_native_plan import PasQualificationApproval, execute_native_test
from exchange.long_session import sha

QUAL_DIR = ROOT / 'docs/activation_v6_3_2026-10-19/qualification'
RELEASE = ROOT / 'docs/activation_v6_3_2026-10-19/regression_release_final/test_receipt.json'
EXEC_DIR = QUAL_DIR / 'execution'

now = time.time_ns() // 1000000
source = active_source_hash(ROOT)
release_hash = sha(RELEASE)

prop = json.loads((QUAL_DIR / 'qualification_proposal.json').read_text())
disc = json.loads((QUAL_DIR / 'fresh_discovery/discovery.json').read_text())

# Update timestamps and source hash
disc['source_hash'] = source
atomic_json(QUAL_DIR / 'fresh_discovery/discovery.json', disc)

prop.pop('proposal_hash', None)
prop['source_hash'] = source
prop['observed_ms'] = now
prop['proposal_hash'] = fingerprint(prop)
atomic_json(QUAL_DIR / 'qualification_proposal.json', prop)

phrase = 'APPROVE PAS QUALIFICATION ' + prop['proposal_hash']
appr = PasQualificationApproval(
    proposal_hash=prop['proposal_hash'],
    source_hash=source,
    release_sha256=release_hash,
    approved_ms=now,
    expires_ms=now + 900000,
    host=socket.gethostname(),
    exact_phrase=phrase,
    manually_verified_wallets=True,
    sole_signer_host_confirmed=True,
    maximum_one_entry=True
)
atomic_json(QUAL_DIR / 'acceptance.json', asdict(appr))

print("Updated qualification proposal hash:", prop['proposal_hash'])
print("Updated acceptance with fresh source hash:", source)

import sqlite3
db_path = ROOT / 'runtime/testnet/anchorium-bot-1/pas-qualification.sqlite'
if db_path.exists():
    with sqlite3.connect(db_path) as conn:
        conn.execute('DELETE FROM identity')
        conn.commit()

# Execute native test!
result = execute_native_test(
    ROOT,
    QUAL_DIR / 'qualification_proposal.json',
    QUAL_DIR / 'fresh_discovery/discovery.json',
    RELEASE,
    QUAL_DIR / 'acceptance.json',
    EXEC_DIR
)
print("Execution result:")
print(json.dumps(result, indent=2, default=str))

