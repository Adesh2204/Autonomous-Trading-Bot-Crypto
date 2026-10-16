"""Read-only verification of preserved source, policies and actual trading state."""
import hashlib,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
from exchange.qualification_intent_recovery import verified_qualification_view

def main():
    out=Path(__file__).resolve().parent
    before=json.loads((out/'baseline_preservation.json').read_text())
    hashes={}
    for category in ('source_sha256','policy_sha256','preserved_evidence_sha256'):
        hashes[category]={name:dict(expected=expected,actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
            for name,expected in before[category].items()}
        for row in hashes[category].values():row['unchanged']=row['expected']==row['actual']
    runtime=ROOT/'runtime/testnet/anchorium-bot-1'
    with sqlite3.connect((runtime/'qualification.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        raw=[dict(r) for r in db.execute('SELECT * FROM intents ORDER BY created_ms,intent_key')]
        certificates=[dict(r) for r in db.execute('SELECT * FROM nontransmission_resolutions')]
        view=verified_qualification_view(db)
        checkpoints=[dict(seq=s,checksum=h,checksum_valid=fingerprint(json.loads(data))==h,
            last_clean_shutdown=json.loads(data).get('last_clean_shutdown'))
            for s,data,h in db.execute('SELECT seq,data,checksum FROM recovery_snapshots ORDER BY seq')]
        qualification=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            raw_intents_unchanged=raw==before['qualification.sqlite']['raw_intents'],
            certificates_unchanged=certificates==before['qualification.sqlite']['certificates'],
            verified_effective_view_unchanged=view==before['qualification.sqlite']['effective_view'],
            recovery_snapshots=checkpoints)
    with sqlite3.connect((runtime/'nonces.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        nonces=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            nonces=[list(r) for r in db.execute('SELECT signer,last FROM nonces')],
            health=[list(r) for r in db.execute('SELECT * FROM nonce_health')])
    result=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),
        preservation=hashes,qualification=qualification,nonces=nonces,
        nonce_history_unchanged=nonces==before['nonces.sqlite'],
        existing_source_files=len(before['source_sha256']),actual_signatures_created=0,
        note='Existing certified clean-shutdown flag remains false; original worker terminal/revocation and later flat reads are separate evidence. Normal public reconciliation may append/rotate recovery checkpoints.')
    result['passed']=all(r['unchanged'] for values in hashes.values() for r in values.values()) and (
        qualification['integrity']=='ok' and qualification['raw_intents_unchanged'] and
        qualification['certificates_unchanged'] and qualification['verified_effective_view_unchanged'] and
        all(r['checksum_valid'] for r in checkpoints) and result['nonce_history_unchanged'])
    atomic_json(out/'preservation_verification.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'preservation','qualification','nonces'}},indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
