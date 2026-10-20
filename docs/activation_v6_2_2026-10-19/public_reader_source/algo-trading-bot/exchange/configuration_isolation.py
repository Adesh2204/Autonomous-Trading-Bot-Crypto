"""Finite non-order isolation of one historical UNKNOWN for 1x configuration.

This never resolves history, resets a nonce/attempt, or permits an order. The
only consumer is the separately accepted exact BTC/EWY leverage workflow.
Ordinary trading/qualification retain the original UNKNOWN barrier.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3

from .base_exchange import ExchangeError
from .execution_journal import fingerprint
from .testnet_certification import TEAM, API

SCOPE='PAS_BTC_EWY_1X_CROSS_CONFIGURATION_ONLY'
CLOID='0xac0eea156fcec80986dd67c9057b6ded'
INTENT='certification:59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea:entry'
NONCE=1792217834069
ROW_HASH='16288c0d29941a01891a548c6184a2f76744eae4fc2b9e03d31ae3ef76553520'
INVOCATION='native_qualification_invocation:59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea'
INVOCATION_HASH='76ae82b3df97189e4fef37727be15f581734a0283b287cd34ec8bb820bc172ce'


def local_evidence(root):
    """Read original databases without installing/migrating any table."""
    import hashlib
    state=Path(root)/'runtime/testnet/anchorium-bot-1'
    with sqlite3.connect((state/'qualification.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('select * from intents where cloid=?',(CLOID,)).fetchone()
        if row is None:raise ExchangeError('EXACT_ORIGINAL_UNKNOWN_REQUIRED')
        row=dict(row)
        invocation=db.execute('select value from controls where name=?',(INVOCATION,)).fetchone()
        consumed=db.execute('select value from controls where name=?',('native_qualification_attempted',)).fetchone()
        if not invocation or not consumed:raise ExchangeError('ORIGINAL_CONSUMED_ATTEMPT_PROOF_REQUIRED')
        result=dict(row_hash=fingerprint(row),invocation_hash=fingerprint(json.loads(invocation[0])),
            consumed_marker_hash=fingerprint(json.loads(consumed[0])),
            qualification_dump_sha256=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest(),
            qualification_integrity=db.execute('pragma integrity_check').fetchone()[0])
    nonce_path=(state/'nonces.sqlite').resolve()
    with sqlite3.connect(nonce_path.as_uri()+'?mode=ro',uri=True) as db:
        rows=db.execute('select signer,last from nonces').fetchall()
        if len(rows)!=1 or rows[0][0].lower()!=API.lower() or db.execute('select count(*) from nonce_health').fetchone()[0]:
            raise ExchangeError('ORIGINAL_SHARED_NONCE_OWNERSHIP_REQUIRED')
        result.update(nonce_database=str(nonce_path),signer=rows[0][0].lower(),nonce_high_water=rows[0][1],
            nonce_integrity=db.execute('pragma integrity_check').fetchone()[0])
    if (result['row_hash']!=ROW_HASH or result['invocation_hash']!=INVOCATION_HASH
            or type(result['nonce_high_water']) is not int or result['nonce_high_water']<NONCE
            or result['qualification_integrity']!='ok' or result['nonce_integrity']!='ok'):
        raise ExchangeError('ORIGINAL_CONFIGURATION_ISOLATION_IDENTITY_CHANGED')
    return result


def assess(proof, source, now_ms):
    """An unsigned proposal is admissible only for this non-order operation."""
    try:
        body=dict(proof);identity=body.pop('proof_hash',None)
        if (identity!=fingerprint(body) or body['mode']!='ACTUAL_READ_ONLY_CONFIGURATION_ISOLATION_REVIEW'
                or body['scope']!=SCOPE or body['source_hash']!=source or body['source_hash_after']!=source
                or body['team_wallet'].lower()!=TEAM.lower() or body['api_wallet'].lower()!=API.lower()
                or body['original_cloid']!=CLOID or body['original_nonce']!=NONCE
                or body['historical_outcome']!='UNKNOWN' or body['order_authority'] is not False
                or body['signatures_created']!=0 or body['exchange_writes']!=0
                or type(now_ms) is not int or type(body['finished_ms']) is not int
                or not 0<=now_ms-body['finished_ms']<=300000):raise ValueError()
        local=body['local']
        if (local['row_hash']!=ROW_HASH or local['invocation_hash']!=INVOCATION_HASH
                or local['signer']!=API.lower() or type(local['nonce_high_water']) is not int
                or local['nonce_high_water']<NONCE or local['nonce_integrity']!='ok'
                or local['qualification_integrity']!='ok'):raise ValueError()
        groups=body['readbacks']
        if len(groups)!=2 or groups[0]['observed_ms']>=groups[1]['observed_ms']:raise ValueError()
        for group in groups:
            if (type(group['observed_ms']) is not int or not 0<=body['finished_ms']-group['observed_ms']<=300000
                    or set(group['venues'])!={'par','pas'} or group['original_order_status']!={'status':'unknownOid'}):raise ValueError()
            for dex,read in group['venues'].items():
                if (read['dex']!=dex or read['team_wallet'].lower()!=TEAM.lower()
                        or read['positions_before'] or read['positions_after'] or read['open_orders'] or read['frontend_orders']
                        or type(read['exchange_time_ms']) is not int
                        or read['exchange_time_ms']<=NONCE+172800000+60000
                        or not 0<=group['observed_ms']-read['exchange_time_ms']<=10000):raise ValueError()
        from .base_exchange import decimal
        funding=body['funding']
        if (funding['status']!='USDP_POSITIVE_VERIFIED' or funding['account_mode']!='unifiedAccount'
                or funding['team_wallet'].lower()!=TEAM.lower() or funding['dex']!='pas'
                or funding['collateral']!='USDP' or type(funding['token']) is not int or funding['token']<0
                or decimal(funding['balance'],positive=True)<=0 or type(funding['observed_ms']) is not int
                or not 0<=body['finished_ms']-funding['observed_ms']<=300000):raise ValueError()
        import re
        if set(body['receipt_sha256'])!={'par','pas'} or any(not isinstance(x,str) or not re.fullmatch('[0-9a-f]{64}',x) for x in body['receipt_sha256'].values()):raise ValueError()
        return dict(admissible=True,scope=SCOPE,proof_hash=identity,original_state='UNKNOWN',
            order_authority=False,reason='Two post-horizon PAR/PAS flat order-free readbacks; exact known UNKNOWN preserved. Fixed 1x configuration cannot create an order.')
    except (KeyError,TypeError,ValueError,AttributeError,ExchangeError):
        return dict(admissible=False,scope=SCOPE,original_state='UNKNOWN',order_authority=False,
            reason='EXACT_FRESH_CONFIGURATION_ISOLATION_EVIDENCE_REQUIRED')


def verify_local(root, proof, source, reference_ms):
    result=assess(proof,source,reference_ms)
    if not result['admissible']:raise ExchangeError(result['reason'])
    current=local_evidence(root);bound=proof['local']
    if any(current[k]!=bound[k] for k in current if k!='nonce_high_water') or current['nonce_high_water']<bound['nonce_high_water']:
        raise ExchangeError('CONFIGURATION_ISOLATION_ORIGINAL_EVIDENCE_CHANGED')
    return result


def verify_receipts(proof, directory):
    from .long_session import sha
    for dex in ('par','pas'):
        path=Path(directory)/(dex+'_info_receipts.jsonl')
        if path.is_symlink() or not path.is_file() or sha(path)!=proof['receipt_sha256'][dex]:
            raise ExchangeError('CONFIGURATION_ISOLATION_RAW_RECEIPTS_CHANGED')


@dataclass(frozen=True)
class ConfigurationIsolation:
    root: Path
    proof: dict
    approval: object
    plan: dict
    evidence_directory: Path

    def exempt_intent(self, client):
        """Called only from configuration guard; action permits remain separate."""
        from .pas_configuration import PasConfigurationApproval
        from .paper_operations import active_source_hash
        if type(self.approval) is not PasConfigurationApproval or getattr(client,'dex',None)!='pas':
            raise ExchangeError('CONFIGURATION_ONLY_ISOLATION_CAPABILITY_REQUIRED')
        body=dict(self.plan);identity=body.pop('plan_hash',None)
        if (identity!=self.approval.plan_hash or fingerprint(body)!=identity
                or body.get('configuration_isolation')!=self.proof):
            raise ExchangeError('ISOLATION_MUST_BE_BOUND_TO_EXACT_ACCEPTED_CONFIGURATION_PLAN')
        self.approval.require(TEAM,API,client.clock_ms())
        verify_receipts(self.proof,self.evidence_directory)
        verify_local(self.root,self.proof,active_source_hash(self.root),self.approval.approved_ms)
        return INTENT


def collect(root, output):
    """Genuine unsigned review only; each action repeats fresh account checks."""
    from dataclasses import asdict
    import threading
    from .public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
    from .hyperliquid_client import RequestsInfoTransport
    from .hyperliquid_account import HyperliquidAccount
    from .execution_journal import ExecutionJournal
    from .rate_limits import HyperliquidRateLimitManager
    from .paper_operations import active_source_hash,atomic_json
    from .pas_funding import read_funding
    from .terminal_evidence import local_execution_state
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    source=active_source_hash(root);local=local_evidence(root);state=local_execution_state(root)
    expected=[dict(journal='qualification',cloid=CLOID,state='UNKNOWN',intent_key=INTENT)]
    if state['status']!='BLOCKED_UNRESOLVED_INTENT' or state['unresolved']!=expected:
        raise ExchangeError('ONLY_EXACT_ORIGINAL_UNKNOWN_MAY_BE_ISOLATED_FOR_CONFIGURATION')
    journal=ExecutionJournal(out/'public.sqlite',session_id='public:configuration-isolation',team_address=TEAM)
    rates=HyperliquidRateLimitManager(journal);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
    clients={};stop=threading.Event();timer=threading.Timer(180,stop.set);timer.start()
    proof=dict(mode='ACTUAL_READ_ONLY_CONFIGURATION_ISOLATION_REVIEW',scope=SCOPE,source_hash=source,
        team_wallet=TEAM,api_wallet=API,original_cloid=CLOID,original_nonce=NONCE,local=local,
        readbacks=[],historical_outcome='UNKNOWN',order_authority=False,signatures_created=0,exchange_writes=0)
    try:
        for dex in ('par','pas'):
            c=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),out/(dex+'_info_receipts.jsonl')),rate_limits=rates,venue=dex)
            clients[dex]=c;c.read_cancel_event=stop;c.startup()
        for _ in range(2):
            group=dict(venues={})
            for dex,c in clients.items():
                account=HyperliquidAccount(c,TEAM)
                before=account.get_positions();orders=account.get_open_orders();front=account.get_frontend_open_orders()
                after=account.get_positions();raw=account._query('clearinghouseState')
                group['venues'][dex]=dict(dex=dex,team_wallet=TEAM,positions_before=[asdict(x) for x in before.values()],
                    positions_after=[asdict(x) for x in after.values()],open_orders=orders,frontend_orders=front,exchange_time_ms=raw.get('time'))
            group['original_order_status']=HyperliquidAccount(clients['par'],TEAM)._query('orderStatus',oid=CLOID)
            group['observed_ms']=clients['pas'].clock_ms();proof['readbacks'].append(group)
        proof['funding']=read_funding(clients['pas'],HyperliquidAccount(clients['pas'],TEAM),provenance=str(out/'pas_info_receipts.jsonl'))
        from .long_session import sha
        for c in clients.values():c.transport.file.flush()
        proof['receipt_sha256']={dex:sha(out/(dex+'_info_receipts.jsonl')) for dex in ('par','pas')}
        proof.update(finished_ms=clients['pas'].clock_ms(),source_hash_after=active_source_hash(root))
        proof['proof_hash']=fingerprint(proof)
        atomic_json(out/'configuration_isolation.json',proof)
        proof_result=assess(proof,source,proof['finished_ms'])
        atomic_json(out/'assessment.json',proof_result)
        verify_local(root,proof,source,proof['finished_ms'])
        return proof
    finally:
        stop.set();timer.cancel()
        for c in clients.values():c.close()
        journal.close()
