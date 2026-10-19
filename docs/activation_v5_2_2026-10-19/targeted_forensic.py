"""Read-only targeted review. No recovery certificate or effective-state edit."""
from pathlib import Path
import hashlib,json,sqlite3,sys,time,subprocess
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.qualification_intent_recovery import verified_qualification_view

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads((ROOT/p).read_text())

original=read('docs/practice_recovery_2026-10-17/original_signing_source_manifest.json')
index={}
for folder in ('algo-trading-bot','scripts','docs'):
    for p in (ROOT/folder).rglob('*.py'):
        if not {'.venv','venv','__pycache__'} & set(p.parts):index.setdefault(digest(p),p)
matched={};missing=[]
archive=OUT/'original_source';archive.mkdir(exist_ok=True)
for relative,expected in original['files'].items():
    p=index.get(expected)
    if p is None:
        revisions=subprocess.check_output(['git','rev-list','--all','--',relative],cwd=ROOT,text=True).splitlines()
        for revision in revisions:
            candidate=subprocess.run(['git','show',revision+':'+relative],cwd=ROOT,capture_output=True)
            if candidate.returncode==0 and hashlib.sha256(candidate.stdout).hexdigest()==expected:
                dest=archive/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(candidate.stdout)
                matched[relative]=dict(sha256=expected,original_location='git:'+revision+':'+relative)
                break
        else:missing.append(relative)
        continue
    matched[relative]=dict(sha256=expected,original_location=str(p.relative_to(ROOT)))
    dest=archive/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
reconstructed=active_source_hash(archive) if not missing else None
if not missing:assert reconstructed==original['source_hash']
cloid='0xac0eea156fcec80986dd67c9057b6ded';nonce=1792217834069
state=ROOT/'runtime/testnet/anchorium-bot-1'
with sqlite3.connect((state/'qualification.sqlite').as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    row=dict(db.execute('SELECT * FROM intents WHERE cloid=?',(cloid,)).fetchone())
    events=[dict(seq=r[0],ms=r[1],kind=r[2],data=json.loads(r[3])) for r in db.execute(
        'SELECT seq,timestamp_ms,kind,data FROM events WHERE timestamp_ms>=? AND timestamp_ms<=? ORDER BY seq',
        (row['created_ms']-10000,row['updated_ms']+10000))]
    controls={k:json.loads(v) for k,v in db.execute('SELECT name,value FROM controls')
        if k.startswith(('certification_transmissions:59445','native_qualification_invocation:59445','native_qualification_attempted'))}
    view=verified_qualification_view(db)
    checkpoints=[]
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_snapshots'").fetchone():
        checkpoints=[dict(data=json.loads(d),checksum=c) for d,c in db.execute('SELECT data,checksum FROM recovery_snapshots')]
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
with sqlite3.connect((state/'nonces.sqlite').as_uri()+'?mode=ro',uri=True) as db:
    nonces=[dict(signer=s,last=n) for s,n in db.execute('SELECT signer,last FROM nonces')]
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    leases={t:[list(r) for r in db.execute('SELECT * FROM "'+t+'"')] for t in tables if 'lease' in t or 'health' in t}
    nonce_integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
evidence=read('docs/practice_recovery_2026-10-17/UNKNOWN_INTENT_RESOLUTION_REPORT.json')
components={}
for name in ('sdk_transport','native_qualification','qualification_signing_boundary','native_qualification_runtime','execution_safety'):
    p=archive/'algo-trading-bot/exchange'/(name+'.py');lines=p.read_text().splitlines()
    components[name]=dict(sha256=digest(p),relevant_lines=[dict(line=i,text=l) for i,l in enumerate(lines,1)
        if any(w in l for w in ('expires','expiry','transmi','claim','_post','nonce','lease','sign_l1','action_expiry'))])
result=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),
    outcome='UNKNOWN_REMAINS_EXTERNALLY_BLOCKED',original_cloid=cloid,original_nonce=nonce,
    original_source_hash=original['source_hash'],reconstructed_source_hash=reconstructed,
    complete_original_source_reconstructed=not missing,missing_original_source_files=missing,
    original_source_files=matched,original_intent=row,original_events=events,
    original_controls=controls,original_exchange_telemetry='NO_ORIGINAL_REQUEST_RESPONSE_OR_EXPLICIT_CAUSAL_REJECTION_RECORD',
    original_wire_expiration_ms=evidence['expired_ms'],original_wire_expiration_basis='Source-bound native action expiry and guarded SDK payload check; not a saved original HTTP payload',
    historical_transmission='UNKNOWN; absent durable claim is supporting evidence, not a newly fabricated causal rejection',
    late_action_risk='Source-bound expiration should reject any conforming late replay; original signed payload absent, so this is a conditional source inference, not observed venue rejection',
    nonce_acceptance_latest_ms_exclusive=nonce+172800000,
    nonce_window_basis='Official Hyperliquid nonces must lie within (block time -2 days, block time +1 day); no nonce fast-forward or reuse performed',
    executed_but_unaccounted_risk='UNRESOLVED until original terminal evidence or independently reviewed complete cross-DEX recovery policy',
    shared_domains=dict(team=True,api_signer=True,nonce_tracker=True,position_safety=True,
        collateral_distinct=True,distinct_asset_ids_do_not_isolate_account=True),
    isolation=dict(validated=False,approved=False,implemented_bypass=False,
        missing=['Actual original wire expiry or authoritative late-action invalidation proof',
            'Independent review of complete original order/fill/funding history and current all-DEX account state',
            'Durable shared signer/account owner and nonce continuity, with revocation and contradictory-evidence handling',
            'Exact separately accepted isolation policy bound to source, account, CLOID, nonce, evidence and finite expiry']),
    nonces=nonces,leases_and_health=leases,qualification_integrity=integrity,nonce_integrity=nonce_integrity,
    checkpoints=checkpoints,verified_prior_certificates=view['resolutions'],
    effective_unresolved=[r for r in view['intents'] if r['state']=='UNKNOWN'],
    source_components=components,original_journals_modified=False,nonce_reset=False,
    consumed_attempt_reset=False,new_certificate_created=False,exchange_writes=0,signatures=0)
(OUT/'targeted_forensic.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(outcome=result['outcome'],source_reconstructed=reconstructed,
    original_files=len(matched),events=len(events),nonce_window_latest=result['nonce_acceptance_latest_ms_exclusive'],
    qualification_integrity=integrity,nonce_integrity=nonce_integrity)))
