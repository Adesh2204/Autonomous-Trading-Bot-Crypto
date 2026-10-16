"""Refresh legacy source classification without re-inventorying raw market dumps.

Uses the repository's existing pattern and classifier. This maintenance artifact
does not modify runtime source or read wallet credentials.
"""
from collections import Counter
import csv
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('legacy_inventory', ROOT / 'scripts/inventory_legacy_dependencies.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

raw = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
paths = sorted(set(raw.decode().split('\0')) - {''})
rows, exclusions = [], []
for relative in paths:
    path = ROOT / relative
    if (relative.startswith(('algo-trading-bot/data/', 'runtime/', 'research/data/')) or
            {'venv', '.venv', '__pycache__', 'node_modules', 'secrets'} & set(path.relative_to(ROOT).parts) or
            relative in inventory.GENERATED or not path.is_file() or
            path.suffix not in inventory.TEXT_SUFFIXES or path.name == '.env' or
            path.name.startswith('.env.') and path.name != '.env.example'):
        exclusions.append(relative)
        continue
    try:
        lines = path.read_text().splitlines()
    except UnicodeError:
        exclusions.append(relative)
        continue
    for line_number, line in enumerate(lines, 1):
        for match in inventory.PATTERN.finditer(line):
            disposition, replacement = inventory.classify(relative, line, match.group())
            rows.append(dict(path=relative, line=line_number, column=match.start() + 1,
                             term=match.group(), disposition=disposition, replacement=replacement,
                             status='reference_retained; excluded from new exchange core'))

with (ROOT / 'docs/legacy_dependency_inventory.csv').open('w', newline='') as stream:
    writer = csv.DictWriter(stream, lineterminator='\n', fieldnames=[
        'path', 'line', 'column', 'term', 'disposition', 'replacement', 'status'])
    writer.writeheader()
    writer.writerows(rows)
summary = dict(occurrences=len(rows), files_with_occurrences=len({r['path'] for r in rows}),
               disposition_counts=dict(Counter(r['disposition'] for r in rows)), exclusions=exclusions,
               note='Source locations and matched terms only; no credential values or line contents.',
               generated_reports_excluded_to_avoid_self_inventory=True,
               additional_source_scope='Excludes raw data, runtime state, secrets and dependency environments.',
               classifier='scripts/inventory_legacy_dependencies.py',
               refresh_script=str(Path(__file__).relative_to(ROOT)))
(ROOT / 'docs/legacy_dependency_inventory.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({key: summary[key] for key in ('occurrences', 'files_with_occurrences', 'disposition_counts')}))
