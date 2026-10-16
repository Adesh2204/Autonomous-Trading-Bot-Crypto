"""Save full offline validation against an unchanged active-source fingerprint."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.paper_operations import active_source_hash

OUT = Path(__file__).resolve().parent
xml = OUT / 'regression.xml'
receipt_path = OUT / 'test_receipt.json'
if xml.exists() or receipt_path.exists():
    raise RuntimeError('PRESERVE_EXISTING_TEST_RECEIPT')
receipt = dict(source_hash_before=active_source_hash(ROOT), started_unix=time.time(),
               scope='Full offline repository suite after unified-account correction')
run = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(ROOT / 'algo-trading-bot'),
                      '--tb=short', '--junitxml', str(xml)], cwd=ROOT)
receipt.update(source_hash_after=active_source_hash(ROOT), finished_unix=time.time(), exit_code=run.returncode)
receipt['checks'] = {}
for name, script in [('strategy_freeze', 'check_strategy_freeze.py'), ('phase0', 'phase0_check.py')]:
    check = subprocess.run([sys.executable, str(ROOT / 'scripts' / script)], cwd=ROOT,
                           capture_output=True, text=True)
    receipt['checks'][name] = dict(exit_code=check.returncode, result=json.loads(check.stdout))
receipt['source_unchanged'] = receipt['source_hash_before'] == receipt['source_hash_after']
if xml.exists():
    receipt['xml_sha256'] = hashlib.sha256(xml.read_bytes()).hexdigest()
    suites = ET.parse(xml).getroot().iter('testsuite')
    rows = [s.attrib for s in suites]
    receipt['totals'] = {key: sum(int(row.get(key, 0)) for row in rows)
                         for key in ('tests', 'failures', 'errors', 'skipped')}
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
raise SystemExit(0 if run.returncode == 0 and receipt['source_unchanged'] and
                 all(r['exit_code'] == 0 for r in receipt['checks'].values()) else 1)
