from pathlib import Path
import hashlib,json,sqlite3,sys
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.configuration_isolation import local_evidence
from exchange.long_session import require_release,sha
p=R/'docs/activation_v6_1_2026-10-19/regression_release_final/test_receipt.json'
require_release(R,p,active_source_hash(R),sha(p))
databases={}
prior=json.loads((R/'docs/activation_v6_1_2026-10-19/baseline_after_human_configuration.json').read_text())
for path in sorted(R/relative for relative in prior['databases']):
 with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
  databases[str(path.relative_to(R))]=dict(dump_sha256=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest(),integrity=db.execute('pragma integrity_check').fetchone()[0])
atomic_json(Path(__file__).with_name('baseline.json'),dict(source_hash=active_source_hash(R),databases=databases,original=local_evidence(R)))
print(json.dumps(dict(source_hash=active_source_hash(R),databases=len(databases))))
