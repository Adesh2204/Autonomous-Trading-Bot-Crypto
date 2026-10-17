"""Read-only audit: preserve original rows plus the legitimate consumed attempt."""
from pathlib import Path
import json,hashlib,sqlite3,sys,time
OUT=Path(__file__).resolve().parent;P=OUT.parent/'practice_weekend_2026-10-17';ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.execution_journal import fingerprint
from exchange.qualification_intent_recovery import verified_qualification_view
from exchange.paper_operations import active_source_hash
old=json.loads((P/'baseline.json').read_text())
post=json.loads((P/'freshness_repair/post_attempt_database_baseline.json').read_text())
r=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),protected={},databases={})
for name,expected in old['protected'].items():
    digest=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    r['protected'][name]=dict(matching=digest==expected,sha256=digest)
for name,baseline in post['databases'].items():
    path=ROOT/'runtime/testnet/anchorium-bot-1'/(name+'.sqlite')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        digest=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
        x=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],dump_sha256=digest,
            unchanged_since_authorized_worker_stopped=digest==baseline['dump_sha256'])
        if name=='qualification':
            rows=[list(row) for row in db.execute('SELECT * FROM intents ORDER BY intent_key')]
            mapping={row[0]:row for row in rows}
            original=old['databases']['runtime/testnet/anchorium-bot-1/qualification.sqlite']
            certs=[list(v) for v in db.execute('SELECT checksum FROM nontransmission_resolutions')]
            key='certification:59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea:entry'
            x.update(original_raw_intents_unchanged=all(mapping.get(row[0])==row for row in original['raw_intents']),
                all_raw_intents_unchanged_since_stop=rows==baseline['raw_intents'],
                original_certificate_unchanged=certs==original['certificate_checksums'],
                original_resolution_valid=bool(verified_qualification_view(db)['resolutions']),
                new_local_intent=dict(key=key,cloid=mapping[key][1],state=mapping[key][5],oid=mapping[key][6]),
                new_unknown_preserved=mapping[key][5]=='UNKNOWN' and mapping[key][6] is None,
                checkpoint_checksum_integrity=all(fingerprint(json.loads(data))==checksum
                    for data,checksum in db.execute('SELECT data,checksum FROM recovery_snapshots')),
                recorded_transmissions=[json.loads(v[0]) for v in db.execute('SELECT value FROM controls WHERE name=?',
                    ('certification_transmissions:59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea',))])
        if name=='nonces':
            rows=[list(row) for row in db.execute('SELECT * FROM nonces')]
            x.update(nonce_rows=rows,nonce_rows_unchanged_since_stop=rows==baseline['nonces'],
                authorized_nonce_advanced_once_to=1792217834069,
                note='Do not restore the older nonce: one authorized guarded signing attempt legitimately allocated this durable nonce.')
        r['databases'][name]=x
r['passed']=all(x['matching'] for x in r['protected'].values()) and all(
    x['integrity']=='ok' and x['unchanged_since_authorized_worker_stopped'] for x in r['databases'].values())
q=r['databases']['qualification']
r['passed']=r['passed'] and all(q[k] for k in ('original_raw_intents_unchanged','all_raw_intents_unchanged_since_stop',
    'original_certificate_unchanged','original_resolution_valid','new_unknown_preserved','checkpoint_checksum_integrity'))
(OUT/'preservation_receipt.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(dict(passed=r['passed'],source_hash=r['source_hash'],unknown=q['new_local_intent'],
    nonce=r['databases']['nonces']['nonce_rows']),indent=2))
raise SystemExit(0 if r['passed'] else 1)
