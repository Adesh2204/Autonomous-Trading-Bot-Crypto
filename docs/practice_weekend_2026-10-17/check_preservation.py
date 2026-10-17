"""Report-only comparison with this task's pre-engineering baseline."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.execution_journal import fingerprint
from exchange.qualification_intent_recovery import verified_qualification_view
from exchange.paper_operations import active_source_hash

base=json.loads((P/'baseline.json').read_text())
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),protected={},databases={})
for name,expected in base['protected'].items():
    actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    r['protected'][name]=dict(expected=expected,actual=actual,matching=actual==expected)
for name,before in base['databases'].items():
    with sqlite3.connect((ROOT/name).resolve().as_uri()+'?mode=ro',uri=True) as db:
        dump=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
        row=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],dump_sha256=dump,
                 logical_dump_unchanged=dump==before['dump_sha256'])
        if 'raw_intents' in before:
            raw=[list(x) for x in db.execute('SELECT * FROM intents ORDER BY intent_key')]
            cert=[list(x) for x in db.execute('SELECT checksum FROM nontransmission_resolutions')]
            row.update(raw_intents_unchanged=raw==before['raw_intents'],raw_intents=raw,
                certificate_checksums_unchanged=cert==before['certificate_checksums'],certificate_checksums=cert,
                verified_unknown_resolutions=verified_qualification_view(db)['resolutions'])
            checks=[fingerprint(json.loads(data))==checksum for data,checksum in
                    db.execute('SELECT data,checksum FROM recovery_snapshots')]
            row.update(checkpoint_count=len(checks),checkpoint_checksum_integrity=all(checks))
        if 'nonces' in before:
            current=[list(x) for x in db.execute('SELECT * FROM nonces')]
            row.update(nonces_unchanged=current==before['nonces'],nonces=current)
        r['databases'][name]=row
r['passed']=all(x['matching'] for x in r['protected'].values()) and all(
    x['integrity']=='ok' and x['logical_dump_unchanged'] and x.get('raw_intents_unchanged',True)
    and x.get('certificate_checksums_unchanged',True) and x.get('checkpoint_checksum_integrity',True)
    and x.get('nonces_unchanged',True) for x in r['databases'].values())
(P/'preservation_receipt.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(dict(passed=r['passed'],source_hash=r['source_hash'],
    databases={k:{key:v for key,v in row.items() if key not in {'raw_intents','verified_unknown_resolutions'}}
               for k,row in r['databases'].items()}),indent=2))
raise SystemExit(0 if r['passed'] else 1)
