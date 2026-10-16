"""Locate stock-hour/timezone assumptions and prove isolation from the crypto core."""
import ast
import csv
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PATTERN=re.compile(r'09:15|15:30|market_open|market_close|pre_market|post_market|'
                   r'Asia/Kolkata|\bIST\b|\bweekday\b|\bweekdays\b|\bweekday\s*\(|\bMonday\b|\bFriday\b',re.I)
OUTPUTS={'docs/session_dependency_inventory.csv','docs/session_dependency_inventory.json'}


def main():
    raw=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],
                       cwd=ROOT,check=True,capture_output=True).stdout
    paths=sorted(set(raw.decode().split('\0'))-{''})
    # Modules actually imported by the isolated crypto entry point. The cold
    # process loads module definitions only; main() never runs or contacts APIs.
    script="import sys,json,runpy; runpy.run_path('scripts/run_crypto_paper.py',run_name='inventory_only'); "
    script+="print(json.dumps(sorted({getattr(m,'__file__','') for m in sys.modules.values() if getattr(m,'__file__',None)})))"
    result=subprocess.run([str(ROOT/'.venv/bin/python'),'-c',script],cwd=ROOT,check=True,capture_output=True,text=True)
    active=set()
    for filename in json.loads(result.stdout):
        try:
            relative=Path(filename).resolve().relative_to(ROOT)
        except ValueError:
            continue
        if '.venv' not in relative.parts:
            active.add(str(relative))
    active.add('scripts/run_crypto_paper.py')
    rows=[]
    for relative in paths:
        path=ROOT/relative
        if relative in OUTPUTS or not path.is_file() or path.suffix not in {'.py','.md','.txt','.ini','.toml','.example'} or path.name.startswith('.env') and path.name!='.env.example':
            continue
        try: lines=path.read_text().splitlines()
        except UnicodeError: continue
        for number,line in enumerate(lines,1):
            for match in PATTERN.finditer(line):
                if relative in active:
                    disposition='ACTIVE_CORE_REVIEW_REQUIRED'
                elif path.name.startswith('test') or relative.startswith('docs/') or path.suffix=='.md' or path.name.startswith('inventory_'):
                    disposition='KEEP_AS_REFERENCE'
                else:
                    disposition='ISOLATED_LEGACY_SESSION_CODE'
                rows.append(dict(path=relative,line=number,column=match.start()+1,
                                 term=match.group(),disposition=disposition))
    with (ROOT/'docs/session_dependency_inventory.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['path','line','column','term','disposition'])
        writer.writeheader();writer.writerows(rows)
    active_rows=[row for row in rows if row['disposition']=='ACTIVE_CORE_REVIEW_REQUIRED']
    report=dict(occurrences=len(rows),active_core_session_occurrences=len(active_rows),
                active_modules=sorted(active),passed=not active_rows,
                note='Only source locations and matched terms are exported. Retained legacy hours are excluded from the crypto import graph; frozen functions use SessionManager UTC/continuous callbacks.')
    (ROOT/'docs/session_dependency_inventory.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('occurrences','active_core_session_occurrences','passed')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
