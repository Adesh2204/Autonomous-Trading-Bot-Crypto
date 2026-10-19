"""Read-only logical snapshot checks for all original journals and proofs."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.execution_journal import fingerprint
from exchange.paper_operations import active_source_hash
b=json.loads((R/'docs/btc_ewy_v4_2026-10-19/baseline.json').read_text())
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(R),protected={},databases={})
for relative,expected in b['protected'].items():
    h=hashlib.sha256((R/relative).read_bytes()).hexdigest();r['protected'][relative]=dict(sha256=h,unchanged=h==expected)
for relative,expected in b['databases'].items():
    with sqlite3.connect((R/relative).as_uri()+'?mode=ro',uri=True) as db:
        h=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
        r['databases'][relative]=dict(dump_sha256=h,unchanged=h==expected['dump_sha256'],integrity=db.execute('pragma integrity_check').fetchone()[0])
        if db.execute("select 1 from sqlite_master where name='recovery_snapshots'").fetchone():
            r['databases'][relative]['checkpoint_integrity']=all(fingerprint(json.loads(d))==c
                for d,c in db.execute('select data,checksum from recovery_snapshots'))
current=json.loads((O/'baseline.json').read_text())
r['v4_receipt_unchanged']=hashlib.sha256((R/'docs/btc_ewy_v4_2026-10-19/regression_release_final/test_receipt.json').read_bytes()).hexdigest()==current['previous_receipt_sha256']
r['v4_xml_unchanged']=hashlib.sha256((R/'docs/btc_ewy_v4_2026-10-19/regression_release_final/regression.xml').read_bytes()).hexdigest()==current['previous_xml_sha256']
r['all_53_preserved']=len(r['databases'])==53 and all(v['unchanged'] and v['integrity']=='ok' and v.get('checkpoint_integrity',True) for v in r['databases'].values()) and all(v['unchanged'] for v in r['protected'].values()) and r['v4_receipt_unchanged'] and r['v4_xml_unchanged']
(O/'preservation_receipt.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(dict(all_53_preserved=r['all_53_preserved'],protected=len(r['protected']))))
raise SystemExit(0 if r['all_53_preserved'] else 1)
