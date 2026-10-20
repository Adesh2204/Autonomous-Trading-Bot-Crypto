"""Append-only dispatch evidence. This ledger cannot clear or authorize an intent.

DISPATCHED means an HTTP attempt began, not delivery or exchange acceptance.
Legacy SUBMITTED means signing was attempted, not that HTTP was reached.
"""
import json
from .base_exchange import ExchangeError
from .execution_journal import canonical, fingerprint, safe_data

STAGES = {'PERSISTED','SIGNING_ATTEMPT','SIGNED','DISPATCHED','ACKNOWLEDGED',
          'ACCEPTED','REJECTED','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED',
          'UNKNOWN','RECONCILED','PRE_HTTP_REJECTED'}


def install(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS intent_audit
      (seq INTEGER PRIMARY KEY AUTOINCREMENT, intent_key TEXT NOT NULL,
       stage TEXT NOT NULL, timestamp_ms INTEGER NOT NULL, data TEXT NOT NULL,
       previous_checksum TEXT NOT NULL, checksum TEXT NOT NULL);
      CREATE TRIGGER IF NOT EXISTS intent_audit_no_update BEFORE UPDATE ON intent_audit
      BEGIN SELECT RAISE(ABORT,'IMMUTABLE_INTENT_AUDIT'); END;
      CREATE TRIGGER IF NOT EXISTS intent_audit_no_delete BEFORE DELETE ON intent_audit
      BEGIN SELECT RAISE(ABORT,'IMMUTABLE_INTENT_AUDIT'); END;''')


def append(db, key, stage, now_ms, evidence):
    if stage not in STAGES or type(now_ms) is not int or not evidence.get('source'):
        raise ExchangeError('INTENT_AUDIT_EVIDENCE_REQUIRED')
    row=db.execute('SELECT cloid,fingerprint FROM intents WHERE intent_key=?',(key,)).fetchone()
    if row is None:raise ExchangeError('UNKNOWN_DURABLE_INTENT')
    previous=db.execute('SELECT checksum FROM intent_audit ORDER BY seq DESC LIMIT 1').fetchone()
    previous=previous[0] if previous else ''
    data=canonical(safe_data(dict(evidence,cloid=row[0],request_hash=row[1])))
    checksum=fingerprint([key,stage,now_ms,data,previous])
    db.execute('INSERT INTO intent_audit(intent_key,stage,timestamp_ms,data,previous_checksum,checksum) VALUES (?,?,?,?,?,?)',
               (key,stage,now_ms,data,previous,checksum))


def verify(db):
    previous='';count=0
    for key,stage,at,data,prior,checksum in db.execute(
            'SELECT intent_key,stage,timestamp_ms,data,previous_checksum,checksum FROM intent_audit ORDER BY seq'):
        if prior!=previous or checksum!=fingerprint([key,stage,at,data,prior]):
            raise ExchangeError('INTENT_AUDIT_CHECKSUM_INVALID')
        json.loads(data);previous=checksum;count+=1
    return dict(records=count,checksum=previous,history_backfilled=False,grants_resolution=False)
