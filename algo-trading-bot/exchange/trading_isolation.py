"""Exact, finite historical-intent isolation; never an exchange action permit.

Only the pinned expired PAR intent is excepted from the local PAS precheck.
The original order, consumed attempt and nonce database remain untouched.
Native evidence, session authority, leases and fresh account checks still apply.
"""
from dataclasses import dataclass
from pathlib import Path
import json,os,socket,sys,time
from .base_exchange import ExchangeError
from .execution_journal import fingerprint
from .configuration_isolation import CLOID,INTENT,NONCE,assess,verify_local,verify_receipts
from .testnet_certification import TEAM,API
from .paper_operations import active_source_hash,atomic_json

MODE='EXACT_FINITE_PAS_TRADING_ISOLATION_V6_2'
ACKS=('original_unknown_preserved','consumed_attempt_and_nonce_preserved',
      'flat_is_not_historical_disposition','separate_native_and_session_authority',
      'one_signer_no_renewal','new_uncertainty_revokes_entries')


def identity(policy):
    body=dict(policy);digest=body.pop('policy_hash',None)
    if digest!=fingerprint(body):raise ExchangeError('TRADING_ISOLATION_POLICY_CHANGED')
    return digest


def validate_policy(root,path,*,source,reference_ms):
    """Validate raw observations, local invariants and the finite policy body."""
    path=Path(path)
    if path.is_symlink():raise ExchangeError('LOCAL_TRADING_ISOLATION_FILE_REQUIRED')
    p=json.loads(path.read_text());identity(p)
    try:
        if (p['mode']!=MODE or p['status']!='UNACCEPTED_FINITE_POLICY' or p['final_historical_outcome']!='UNKNOWN'
                or p['signatures_created']!=0 or p['exchange_writes']!=0
                or p['source_hash']!=source or p['team_wallet'].lower()!=TEAM.lower()
                or p['api_wallet'].lower()!=API.lower() or p['markets']!=['pas:BTC','pas:EWY']
                or p['original']!=dict(cloid=CLOID,intent_key=INTENT,nonce=NONCE,state='UNKNOWN')
                or p['order_authority'] is not False or p['maximum_duration_ms']!=3600000
                or type(p['created_ms']) is not int or type(p['expires_ms']) is not int
                or not p['created_ms']<=reference_ms<p['expires_ms']
                or not 300000<p['expires_ms']-p['created_ms']<=3600000
                or p['approval_deadline_ms']!=p['created_ms']+300000
                or p['risk_basis']!='ALLOCATED_20000_USDP_NOT_ACCOUNT_100000'
                or p['ceilings']!=dict(bankroll='20000',entry='1000',cumulative='2000',attempts=2,positions=1,actions=12,trade_loss='100',session_loss='200')):
            raise ValueError()
        proof=p['readbacks'];directory=path.parent/'readbacks'
        if not assess(proof,source,p['created_ms'])['admissible']:raise ValueError()
        verify_local(root,proof,source,p['created_ms']);verify_receipts(proof,directory)
        # Bind the flattened proof to actual successful request/response records.
        for dex in ('par','pas'):
            rows=[json.loads(line) for line in (directory/(dex+'_info_receipts.jsonl')).read_text().splitlines()]
            if any('response' not in r or r['request'].get('type') not in {
                    'perpDexs','meta','spotMeta','clearinghouseState','openOrders','frontendOpenOrders',
                    'orderStatus','spotClearinghouseState','userAbstraction'} for r in rows):raise ValueError()
            for g in proof['readbacks']:
                v=g['venues'][dex];clock=v['exchange_time_ms']
                for kind in ('clearinghouseState','openOrders','frontendOpenOrders'):
                    found=[r for r in rows if r['request']==dict(type=kind,user=TEAM,dex=dex)
                        and 0<=g['observed_ms']-r['received_ms']<=30000]
                    if not found:raise ValueError()
                    if kind=='clearinghouseState':
                        if not any(r['response'].get('time')==clock and r['response'].get('assetPositions')==[] for r in found):raise ValueError()
                    elif not any(r['response']==[] for r in found):raise ValueError()
            if dex=='par' and sum(r['request']==dict(type='orderStatus',user=TEAM,oid=CLOID)
                    and r['response']==dict(status='unknownOid') for r in rows)<2:raise ValueError()
        fill_file=path.parent/'fills.json'
        from .long_session import sha
        if fill_file.is_symlink() or sha(fill_file)!=p['fills_sha256']:raise ValueError()
        f=json.loads(fill_file.read_text())
        if (f['request']!=dict(type='userFillsByTime',user=TEAM,startTime=NONCE-60000,endTime=f['end_ms'],aggregateByTime=False)
                or type(f['end_ms']) is not int or f['end_ms']<NONCE+172860000
                or type(f['received_ms']) is not int or not 0<=p['created_ms']-f['received_ms']<=300000
                or not isinstance(f['response'],list) or len(f['response'])>=2000
                or any(not isinstance(r,dict) or type(r.get('time')) is not int or not NONCE-60000<=r['time']<=f['end_ms'] for r in f['response'])
                or any(r.get('cloid')==CLOID for r in f['response'])):raise ValueError()
    except (KeyError,TypeError,ValueError,AttributeError,OSError) as exc:
        raise ExchangeError('FINITE_TRADING_ISOLATION_EVIDENCE_INVALID') from exc
    return p


def collect(root,output,*,minutes=60):
    from .configuration_isolation import collect as readbacks
    from .hyperliquid_client import RequestsInfoTransport
    from .long_session import sha
    if type(minutes) is not int or not 6<=minutes<=60:raise ExchangeError('FINITE_TRADING_ISOLATION_SIX_TO_SIXTY_MINUTES_REQUIRED')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    proof=readbacks(root,out/'readbacks');transport=RequestsInfoTransport()
    try:
        # One bounded historical query, not a truncated-history conclusion. A
        # limit hit blocks policy creation and requires existing pagination.
        end=time.time_ns()//1000000
        request=dict(type='userFillsByTime',user=TEAM,startTime=NONCE-60000,endTime=end,aggregateByTime=False)
        # Reserve the worst case 2000-item charge through the existing manager.
        from .execution_journal import ExecutionJournal
        from .rate_limits import HyperliquidRateLimitManager
        journal=ExecutionJournal(out/'history_reads.sqlite',session_id='public:trading-isolation',team_address=TEAM)
        try:
            rates=HyperliquidRateLimitManager(journal);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
            response=rates.read('userFillsByTime',lambda:transport(request),expected_items=2000,request_key=json.dumps(request,sort_keys=True))
        finally:journal.close()
        atomic_json(out/'fills.json',dict(request=request,response=response,end_ms=end,received_ms=time.time_ns()//1000000))
    finally:transport.close()
    now=time.time_ns()//1000000
    p=dict(mode=MODE,status='UNACCEPTED_FINITE_POLICY',source_hash=active_source_hash(Path(root)),
        team_wallet=TEAM,api_wallet=API,markets=['pas:BTC','pas:EWY'],signing_host=socket.gethostname(),
        created_ms=now,approval_deadline_ms=now+300000,expires_ms=now+minutes*60000,maximum_duration_ms=3600000,
        original=dict(cloid=CLOID,intent_key=INTENT,nonce=NONCE,state='UNKNOWN'),readbacks=proof,fills_sha256=sha(out/'fills.json'),
        risk_basis='ALLOCATED_20000_USDP_NOT_ACCOUNT_100000',
        ceilings=dict(bankroll='20000',entry='1000',cumulative='2000',attempts=2,positions=1,actions=12,trade_loss='100',session_loss='200'),
        order_authority=False,final_historical_outcome='UNKNOWN',signatures_created=0,exchange_writes=0,
        scope='Only this exact local historical PAR intent; no configuration capability, no new UNKNOWN, no exemption from live exposure or protective/minimum gates')
    p['policy_hash']=fingerprint(p);atomic_json(out/'policy.json',p)
    validate_policy(root,out/'policy.json',source=p['source_hash'],reference_ms=now)
    return p


def require_subject(policy,mandate):
    from .scored_session import ScoredLongMandate
    from .base_exchange import decimal
    if type(mandate) is not ScoredLongMandate:raise ExchangeError('EXACT_PAS_SESSION_SUBJECT_REQUIRED')
    mandate.require();d=mandate.daily
    if (d.source_hash!=policy['source_hash'] or d.signing_host!=policy['signing_host']
            or not policy['created_ms']<=mandate.created_ms<=policy['approval_deadline_ms']
            or not policy['created_ms']<=d.starts_ms<d.expires_ms<=policy['expires_ms']
            or decimal(d.bankroll)>20000 or decimal(d.maximum_notional)>1000
            or decimal(d.maximum_cumulative_allocation)>2000 or mandate.maximum_signed_actions>12):
        raise ExchangeError('FINITE_ISOLATION_SUBJECT_SCOPE_MISMATCH')


@dataclass(frozen=True)
class FiniteTradingIsolation:
    root: Path
    policy_path: Path
    mandate: object

    def require(self,now_ms):
        from .long_session import sha
        p=validate_policy(self.root,self.policy_path,source=active_source_hash(self.root),reference_ms=now_ms)
        require_subject(p,self.mandate)
        if sha(self.policy_path)!=self.mandate.trading_isolation_policy_sha256:raise ExchangeError('TRADING_ISOLATION_MANDATE_BINDING_CHANGED')
        acceptance=self.policy_path.with_name('acceptance.json')
        if acceptance.is_symlink() or acceptance.with_name('revoked.json').exists():raise ExchangeError('TRADING_ISOLATION_REVOKED')
        a=json.loads(acceptance.read_text())
        if (a.get('mode')!=MODE or a.get('policy_hash')!=identity(p) or a.get('mandate_hash')!=self.mandate.identity
                or a.get('exact_phrase')!='ISOLATE '+identity(p)+' FOR '+self.mandate.identity
                or any(a.get(k) is not True for k in ACKS)
                or type(a.get('accepted_ms')) is not int or not p['created_ms']<=a['accepted_ms']<=p['approval_deadline_ms']
                or not a['accepted_ms']<=now_ms<self.mandate.daily.expires_ms
                or a.get('expires_ms')!=self.mandate.daily.expires_ms or socket.gethostname()!=p['signing_host']):
            raise ExchangeError('EXACT_INTERACTIVE_FINITE_TRADING_ISOLATION_ACCEPTANCE_REQUIRED')
        return p

    def exempt_intent(self,client):
        if client.dex!='pas':raise ExchangeError('PAS_ONLY_TRADING_ISOLATION')
        self.require(client.clock_ms())
        # This class grants no transport permission. require_shared_scope still
        # rejects any new UNKNOWN and repeats independent PAR exposure reads.
        return INTENT


def approve(root,policy_path,mandate_path,release_path):
    from .long_session import read_mandate,require_release,sha
    m=read_mandate(mandate_path);now=time.time_ns()//1000000
    p=validate_policy(root,policy_path,source=active_source_hash(Path(root)),reference_ms=now);require_subject(p,m)
    if sha(policy_path)!=m.trading_isolation_policy_sha256:raise ExchangeError('ISOLATION_MUST_BE_BOUND_TO_MANDATE')
    require_release(root,release_path,m.daily.source_hash,m.release_sha256)
    if socket.gethostname()!=p['signing_host']:raise ExchangeError('EXACT_TRADING_ISOLATION_HOST_REQUIRED')
    if not sys.stdin.isatty():raise ExchangeError('INTERACTIVE_HUMAN_ISOLATION_APPROVAL_REQUIRED')
    print(json.dumps(p,indent=2));print('Original UNKNOWN remains UNKNOWN. This accepts only its finite isolation; it authorizes no orders. Native qualification and a separate session acceptance remain required.')
    phrase='ISOLATE '+identity(p)+' FOR '+m.identity
    answer=input('Type '+phrase+': ');accepted=time.time_ns()//1000000
    if answer!=phrase or not p['created_ms']<=accepted<=p['approval_deadline_ms']:raise ExchangeError('EXACT_UNEXPIRED_HUMAN_ISOLATION_ACCEPTANCE_REQUIRED')
    a=dict(mode=MODE,policy_hash=identity(p),mandate_hash=m.identity,exact_phrase=phrase,accepted_ms=accepted,expires_ms=m.daily.expires_ms,**{k:True for k in ACKS})
    with Path(policy_path).with_name('acceptance.json').open('x') as f:json.dump(a,f,indent=2);f.flush();os.fsync(f.fileno())
    FiniteTradingIsolation(Path(root),Path(policy_path),m).require(accepted)
    return dict(status='ISOLATION_ACCEPTED_NOT_ORDER_AUTHORIZATION',policy_hash=identity(p))
