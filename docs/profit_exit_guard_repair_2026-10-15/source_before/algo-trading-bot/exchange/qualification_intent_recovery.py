"""Append-only certification of the one known pre-HTTP qualification failure.

The UNKNOWN row is never edited or deleted. Production uses raw intents. Only
the isolated qualification path may consult this verified historical resolution.
Account flatness alone, or absent HTTP evidence alone, is insufficient.
"""
import hashlib,json,sqlite3
from pathlib import Path
from .base_exchange import ExchangeError
from .execution_journal import fingerprint,canonical
from .single_position_guard import SinglePositionGuard
from .certification_runtime import CertificationRecovery

ORIGINAL_CLOID='0x3486c3b8e88add1a77175c9c5965350f'
ORIGINAL_PROPOSAL='3b744e33e2de25c1afd6764eac3268ba8d51ac8ef905200e62230bc4a2261ddf'
ORIGINAL_SESSION='47fc3e21b13b4081e1c226c7e365d1d42798f206e1e80547c1c909c886511ee7'
ORIGINAL_SOURCE='ed9022e9513832f220786ca9850e49834541607935583c1c5aa0a1a635546825'
ROOT=Path(__file__).resolve().parents[2]


def collect(account,original_journal,observer,nonce_path,*,mode='ACTUAL_READ_ONLY_ACCOUNT'):
    """Bounded actual reads; no signer, signing SDK or nonce allocation."""
    from dataclasses import asdict
    from .hyperliquid_client import RequestsInfoTransport
    if mode=='ACTUAL_READ_ONLY_ACCOUNT' and type(account.client.transport) is not RequestsInfoTransport:
        raise ExchangeError('ACTUAL_INFO_TRANSPORT_REQUIRED_FOR_RECOVERY')
    source=archived_transport_source()
    local=local_evidence(original_journal.db)
    with sqlite3.connect(Path(nonce_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        rows=db.execute('SELECT signer,last FROM nonces').fetchall()
        if len(rows)!=1 or db.execute('SELECT COUNT(*) FROM nonce_health').fetchone()[0]:
            raise ExchangeError('NONCE_RECOVERY_OWNERSHIP_REQUIRED')
        nonce=dict(signer=rows[0][0],last=rows[0][1])
    observations=[]
    for _ in range(2):
        report=observer.recover()
        before=account.get_positions();orders=account.get_frontend_open_orders()
        status=account._query('orderStatus',oid=ORIGINAL_CLOID)
        after=account.get_positions()
        history=observer.state.last_window
        observations.append(dict(source='EXCHANGE_DIRECT_TESTNET_PAR_INFO',user=account.team_address,
            observed_ms=account.client.clock_ms(),positions_before=[asdict(p) for p in before.values()],
            positions_after=[asdict(p) for p in after.values()],orders=orders,original_status=status,
            all_historical_fills=[asdict(f) for f in observer.state.fills.values()],
            history_start_ms=observer.initial_start_ms,history_end_ms=history[1],
            reconciliation_ready=report.ready))
    return dict(mode=mode,team=account.team_address,source=source,local=local,nonce_record=nonce,
        account_observations=observations)


def archived_transport_source(root=ROOT):
    from .paper_operations import active_source_hash
    archive=Path(root)/'docs/readiness_repair_2026-10-14/source_before'
    receipt=Path(root)/'docs/delegated_qualification_2026-10-14/regression_release/test_receipt.json'
    r=json.loads(receipt.read_text());xml=receipt.with_name('regression.xml')
    proposal_path=Path(root)/'docs/delegated_qualification_2026-10-14/session_preparation/authorized_session/observation_1/proposal.json'
    proposal=json.loads(proposal_path.read_text())
    if (active_source_hash(archive)!=ORIGINAL_SOURCE or r.get('source_hash')!=ORIGINAL_SOURCE
            or r.get('source_hash_after')!=ORIGINAL_SOURCE or r.get('passed') is not True
            or r.get('totals')!=dict(tests=2194,failures=0,errors=0,skipped=0)
            or hashlib.sha256(xml.read_bytes()).hexdigest()!=r.get('xml_sha256')):
        raise ExchangeError('ORIGINAL_TRANSPORT_SOURCE_PROOF_REQUIRED')
    from .emergency_qualification import EmergencyProposal
    if EmergencyProposal(**proposal).identity!=ORIGINAL_PROPOSAL:raise ExchangeError('ORIGINAL_PROPOSAL_IDENTITY_REQUIRED')
    return dict(source_hash=ORIGINAL_SOURCE,archive=str(archive),receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        signed_action_expiry_ms=proposal['observed_ms']+300000)


def local_evidence(db):
    row=db.execute('SELECT * FROM intents WHERE cloid=?',(ORIGINAL_CLOID,)).fetchone()
    if row is None:raise ExchangeError('ORIGINAL_UNKNOWN_INTENT_REQUIRED')
    if not isinstance(row,sqlite3.Row):
        names=[x[1] for x in db.execute('PRAGMA table_info(intents)')];row=dict(zip(names,row))
    else:row=dict(row)
    events=[dict(seq=s,ms=t,kind=k,data=json.loads(v)) for s,t,k,v in
        db.execute('SELECT seq,timestamp_ms,kind,data FROM events ORDER BY seq')]
    relevant=[e for e in events if e['data'].get('cloid')==ORIGINAL_CLOID or
        e['data'].get('configuration_hash')==ORIGINAL_PROPOSAL or
        e['kind']=='NONCE_GENERATED' and row['created_ms']<=e['ms']<=row['updated_ms']]
    keys=('certification_transmissions:'+ORIGINAL_PROPOSAL,'qualification_entry_consumed',
        'delegated_session_finished:'+ORIGINAL_SESSION)
    controls={k:json.loads(v) for k,v in db.execute('SELECT name,value FROM controls WHERE name IN (?,?,?)',keys)}
    return dict(original_row=row,events=relevant,
        transmission_claim=controls.get('certification_transmissions:'+ORIGINAL_PROPOSAL),
        original_entry_consumed=controls.get('qualification_entry_consumed')==ORIGINAL_PROPOSAL,
        session_finished=bool(controls.get('delegated_session_finished:'+ORIGINAL_SESSION)))


def assess(proof, *, now_ms=None, check_archive=True):
    try:
        row=proof['local']['original_row'];request=json.loads(row['request']);events=proof['local']['events']
        if proof.get('mode') not in {'ACTUAL_READ_ONLY_ACCOUNT','OFFLINE_FIXTURE'}:raise ValueError()
        failed=[e for e in events if e['kind']=='P0_ENTRY_PRICE_GUARD'
            and e['data'].get('stage')=='FINAL_SIGNING_VALIDATOR' and e['data'].get('allowed') is False]
        nonce=[e for e in events if e['kind']=='NONCE_GENERATED']
        signed=[e for e in events if e['kind']=='SIGNED_ATTEMPT' and e['data'].get('cloid')==ORIGINAL_CLOID]
        if (row['cloid']!=ORIGINAL_CLOID or row['state']!='UNKNOWN' or row['oid'] is not None
                or row['intent_key']!='certification:'+ORIGINAL_PROPOSAL+':entry'
                or fingerprint(request)!=row['fingerprint'] or request['symbol']!='par:BTC'
                or request['side']!='BUY' or request['reduce_only'] is not False
                or request['quantity']!='0.0002' or request['price']!='83513' or request['tif']!='Ioc'
                or proof['local']['transmission_claim'] or proof['local']['original_entry_consumed']
                or not proof['local']['session_finished'] or len(nonce)!=1 or len(signed)!=1
                or not failed or failed[-1]['data'].get('guard_result')!='P0_FRESH_RECONCILED_FLAT_ACCOUNT_REQUIRED'
                or failed[-1]['ms']<nonce[0]['ms'] or signed[0]['ms']>nonce[0]['ms']
                or any(e['kind']=='QUALIFICATION_TRANSPORT_BOUNDARY' and
                    e['data'].get('stage') in {'HTTP_POST_STARTED','HTTP_POST_RESPONSE','HTTP_POST_UNCERTAIN'} for e in events)
                or proof['source']['source_hash']!=ORIGINAL_SOURCE
                or proof['nonce_record']['last']<nonce[0]['data']['nonce']
                or proof['nonce_record']['signer'].lower()!=nonce[0]['data']['api_wallet'].lower()):
            raise ValueError()
        observations=proof['account_observations']
        if len(observations)!=2 or observations[0]['observed_ms']>=observations[1]['observed_ms']:
            raise ValueError()
        for s in observations:
            if (s['source']!='EXCHANGE_DIRECT_TESTNET_PAR_INFO' or s['user'].lower()!=proof['team'].lower()
                    or s['positions_before'] or s['positions_after'] or s['orders'] or s['all_historical_fills']
                    or s['original_status']!={'status':'unknownOid'}
                    or s['history_start_ms']!=0 or s['history_end_ms']<row['updated_ms']
                    or s['reconciliation_ready'] is not True or s['observed_ms']<s['history_end_ms']):
                raise ValueError()
        if now_ms is not None and not 0<=now_ms-observations[-1]['observed_ms']<=5000:raise ValueError()
        actual_source=archived_transport_source() if check_archive else proof['source']
        # All possibly generated original signatures must have expired as well;
        # a currently flat account does not remove a still-valid signed payload.
        if observations[-1]['observed_ms']<=actual_source['signed_action_expiry_ms']:raise ValueError()
        supplied=dict(proof['source'])
        supplied.setdefault('signed_action_expiry_ms',actual_source['signed_action_expiry_ms'])
        if check_archive and actual_source!=supplied:raise ValueError()
        return dict(certified=True,effective_state='PROVEN_NOT_TRANSMITTED',
            original_state_preserved='UNKNOWN',resolution_hash=fingerprint(proof),
            reason='Verified original mandatory pre-HTTP claim path, explicit final guard failure, no claim/HTTP record, matching nonce and two complete fresh account histories')
    except (KeyError,TypeError,ValueError,OSError,ExchangeError):
        return dict(certified=False,effective_state='UNKNOWN',reason='INSUFFICIENT_NONTRANSMISSION_EVIDENCE')


def append_resolution(journal,proof,now_ms):
    result=assess(proof,now_ms=now_ms)
    if not result['certified']:raise ExchangeError('UNKNOWN_INTENT_REMAINS_LOCKED')
    if proof['team'].lower()!=journal.team_address:raise ExchangeError('RECOVERY_TEAM_IDENTITY_MISMATCH')
    mode=proof.get('mode')
    if mode!='ACTUAL_READ_ONLY_ACCOUNT' and not (mode=='OFFLINE_FIXTURE' and journal.session_id.startswith('offline:')):
        raise ExchangeError('ACTUAL_NONTRANSMISSION_RECOVERY_EVIDENCE_REQUIRED')
    journal.db.executescript('''CREATE TABLE IF NOT EXISTS nontransmission_resolutions
      (intent_key TEXT PRIMARY KEY, original_hash TEXT NOT NULL, proof TEXT NOT NULL,
       checksum TEXT NOT NULL, created_ms INTEGER NOT NULL);
      CREATE TRIGGER IF NOT EXISTS resolution_no_update BEFORE UPDATE ON nontransmission_resolutions
      BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECOVERY_RESOLUTION'); END;
      CREATE TRIGGER IF NOT EXISTS resolution_no_delete BEFORE DELETE ON nontransmission_resolutions
      BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RECOVERY_RESOLUTION'); END;''')
    original=proof['local']['original_row'];key=original['intent_key']
    with journal.transaction():
        current=journal.intent(key)
        if current!=original:raise ExchangeError('ORIGINAL_INTENT_CHANGED_DURING_RECOVERY')
        prior=journal.db.execute('SELECT checksum FROM nontransmission_resolutions WHERE intent_key=?',(key,)).fetchone()
        if prior:raise ExchangeError('RECOVERY_RESOLUTION_ALREADY_EXISTS')
        journal.db.execute('INSERT INTO nontransmission_resolutions VALUES (?,?,?,?,?)',
            (key,fingerprint(original),canonical(proof),fingerprint(proof),now_ms))
    journal.event('UNKNOWN_INTENT_NONTRANSMISSION_CERTIFIED',now_ms,cloid=ORIGINAL_CLOID,
        original_state='UNKNOWN',effective_state='PROVEN_NOT_TRANSMITTED',
        resolution_hash=fingerprint(proof),original_row_unchanged=True,nonce_unchanged=True)
    return result


def effective_rows(db):
    names=[x[1] for x in db.execute('PRAGMA table_info(intents)')]
    raw=[dict(zip(names,tuple(r))) for r in db.execute('SELECT * FROM intents ORDER BY created_ms,intent_key')]
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nontransmission_resolutions'").fetchone():return raw
    identity=dict(db.execute('SELECT name,value FROM identity'))
    certified=set()
    for key,original_hash,data,checksum in db.execute('SELECT intent_key,original_hash,proof,checksum FROM nontransmission_resolutions'):
        try:
            proof=json.loads(data);original=next(r for r in raw if r['intent_key']==key)
            if (fingerprint(proof)!=checksum or fingerprint(original)!=original_hash
                    or proof['local']['original_row']!=original or proof['team'].lower()!=identity['team']
                    or proof.get('mode')!='ACTUAL_READ_ONLY_ACCOUNT' and not (proof.get('mode')=='OFFLINE_FIXTURE' and identity['session'].startswith('offline:'))
                    or not assess(proof)['certified']):raise ValueError()
            # A later positive transmission for this SAME original identity
            # invalidates its resolution; never ignore contradictory evidence.
            row=db.execute('SELECT value FROM controls WHERE name=?',('certification_transmissions:'+ORIGINAL_PROPOSAL,)).fetchone()
            if row and json.loads(row[0]):raise ValueError()
            certified.add(key)
        except (ValueError,StopIteration,KeyError,TypeError,ExchangeError):
            raise ExchangeError('NONTRANSMISSION_RESOLUTION_INVALID') from None
    return [r for r in raw if r['intent_key'] not in certified]


def qualification_intents(journal):return effective_rows(journal.db)


def prior_session_resolved(db,previous):
    if previous!=ORIGINAL_SESSION:return False
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nontransmission_resolutions'").fetchone():return False
    controls=dict(db.execute('SELECT name,value FROM controls'))
    return bool(json.loads(controls.get('delegated_session_finished:'+previous,'false'))) and not effective_rows(db) and (
        db.execute('SELECT COUNT(*) FROM nontransmission_resolutions').fetchone()[0]==1)


class QualificationPositionGuard(SinglePositionGuard):
    def intent_rows(self):return qualification_intents(self.journal)


class QualificationRecovery(CertificationRecovery):
    def intent_rows(self):
        rows=qualification_intents(self.journal)
        own=getattr(self,'signing_intent',None)
        return [r for r in rows if r['intent_key']!=own]

    def recover_for_signing(self,own):
        row=self.journal.intent(own)
        if row is None or row['state'] not in {'PREPARED','SUBMITTED'}:
            raise ExchangeError('SIGNING_RECOVERY_EXACT_RESERVED_INTENT_REQUIRED')
        for data, in self.journal.db.execute("SELECT data FROM events WHERE kind='QUALIFICATION_TRANSPORT_BOUNDARY'"):
            event=json.loads(data)
            if event.get('cloid')==row['cloid'] and event.get('stage')=='HTTP_POST_STARTED':
                raise ExchangeError('SIGNING_RECOVERY_TRANSPORT_ALREADY_STARTED')
        self.signing_intent=own
        try:return self.recover()
        finally:self.signing_intent=None
