"""Exact PAS configuration-only workflow. Never an order or transfer permit."""
from dataclasses import dataclass
from pathlib import Path
import json,socket,time
from .base_exchange import ExchangeError
from .execution_journal import fingerprint
from .testnet_certification import TEAM,API
from .paper_operations import active_source_hash,atomic_json
from .pas_configuration_plan import configuration_plan


def require_plan(plan, discovery, source, now):
    check=dict(plan);identity=check.pop('plan_hash',None)
    # Discovery embeds the plan after constructing it. Hash the original
    # observation body, excluding exactly that self-reference, and require the
    # embedded copy to agree. All other discovery fields remain bound.
    observation=dict(discovery);embedded=observation.pop('configuration_plan',None)
    if (identity!=fingerprint(check) or plan!=configuration_plan(observation)
            or embedded is not None and embedded!=plan):
        raise ExchangeError('EXACT_PAS_CONFIGURATION_PLAN_REQUIRED')
    if (plan['source_hash']!=source or type(plan['observed_ms']) is not int or not 0<=now-plan['observed_ms']<=300000):
        raise ExchangeError('FRESH_SOURCE_BOUND_CONFIGURATION_PLAN_REQUIRED')
    return plan


@dataclass(frozen=True)
class PasConfigurationApproval:
    plan_hash:str
    source_hash:str
    release_sha256:str
    approved_ms:int
    expires_ms:int
    host:str
    exact_phrase:str
    manual_wallet_verified:bool=False
    sole_signer_host_confirmed:bool=False
    team_address:str=TEAM
    signer_address:str=API
    scope:str='PAS_1X_CROSS_CONFIGURATION_ONLY'

    def require(self,team,signer,now):
        import re
        if (self.scope!='PAS_1X_CROSS_CONFIGURATION_ONLY' or self.manual_wallet_verified is not True
            or self.sole_signer_host_confirmed is not True or self.host!=socket.gethostname()
            or team.lower()!=TEAM.lower() or signer.lower()!=API.lower()
            or self.team_address.lower()!=team.lower() or self.signer_address.lower()!=signer.lower()
            or any(not re.fullmatch('[0-9a-f]{64}',v) for v in (self.plan_hash,self.source_hash,self.release_sha256))
            or self.exact_phrase!='APPROVE PAS CONFIGURATION '+self.plan_hash
            or any(type(v) is not int for v in (self.approved_ms,self.expires_ms,now))
            or not self.approved_ms<=now<self.expires_ms<=self.approved_ms+900000):
            raise ExchangeError('EXACT_PAS_CONFIGURATION_APPROVAL_REQUIRED')


def approval_preflight(root,plan,discovery,release,now):
    from .long_session import require_release,sha
    require_plan(plan,discovery,active_source_hash(root),now)
    if plan.get('configuration_isolation') is not None:
        from .configuration_isolation import verify_local
        verify_local(root,plan['configuration_isolation'],plan['source_hash'],now)
    require_release(root,release,plan['source_hash'],sha(release))
    blocked=[x for x in plan['blockers'] if x!='SEPARATE_EXACT_OPERATOR_CONFIGURATION_APPROVAL_REQUIRED']
    if blocked:raise ExchangeError('CONFIGURATION_PREREQUISITES:'+','.join(blocked))
    if not plan['changes']:raise ExchangeError('NO_CONFIGURATION_ACTION_REQUIRED')
    return sha(release)


def approve_configuration(root,plan_path,discovery_path,release,output):
    """Actual terminal input is the only acceptance writer. No auto-approval flag."""
    # Historical configuration approvals grant no current write authority.
    # Configuration writes remain retired; only unsigned reporting is permitted.
    raise ExchangeError('RETIRED_PAS_1X_CONFIGURATION_WRITE_ROUTE')
    import sys
    from dataclasses import asdict
    plan=json.loads(Path(plan_path).read_text());d=json.loads(Path(discovery_path).read_text())
    now=time.time_ns()//1000000;release_hash=approval_preflight(root,plan,d,release,now)
    from .team_registration import registration_evidence
    if d.get('registration_evidence')!=registration_evidence(Path(discovery_path).parent,now,scope='CONFIGURATION_ONLY'):
        raise ExchangeError('CONFIGURATION_REGISTRATION_RECORD_CHANGED')
    if plan.get('configuration_isolation'):
        from .configuration_isolation import verify_receipts
        verify_receipts(plan['configuration_isolation'],Path(discovery_path).parent/'configuration_isolation')
    if not sys.stdin.isatty():raise ExchangeError('GENUINE_INTERACTIVE_CONFIGURATION_APPROVAL_REQUIRED')
    print(json.dumps(plan,indent=2));print('Confirm team/API identities, sole signing Mac, exact BTC/EWY changes only. No order/transfer authority.')
    if plan.get('configuration_isolation'):
        print('This exact configuration approval also accepts the displayed finite CONFIGURATION-ONLY isolation. Original UNKNOWN and consumed attempt remain unchanged and still block all order/qualification paths.')
    phrase='APPROVE PAS CONFIGURATION '+plan['plan_hash']
    if input(phrase+'\n> ').strip()!=phrase:raise ExchangeError('CONFIGURATION_APPROVAL_NOT_ACCEPTED')
    accepted=time.time_ns()//1000000
    approval_preflight(root,plan,d,release,accepted)
    a=PasConfigurationApproval(plan['plan_hash'],plan['source_hash'],release_hash,accepted,accepted+900000,
        socket.gethostname(),phrase,True,True)
    a.require(TEAM,API,accepted)
    with Path(output).open('x') as f:f.write(json.dumps(asdict(a),indent=2)+'\n')
    return dict(status='EXACT_CONFIGURATION_APPROVAL_ACCEPTED',expires_ms=a.expires_ms,plan_hash=a.plan_hash)


def execute_configuration(root,plan_path,discovery_path,release,acceptance,output):
    """Future operator invocation only; public checks precede actual-key access.

    One durable attempt per approved plan; ambiguity consumes it. The shared
    UNKNOWN policy applies even though configuration does not submit an order.
    """
    # Fail before imports, credentials, state directories, or a network client.
    raise ExchangeError('RETIRED_PAS_1X_CONFIGURATION_WRITE_ROUTE')
    from .long_session import sha,require_release
    from .leverage_configuration import LeverageConfigurationTransport,wait_for_configuration_reads
    from .execution_journal import ExecutionJournal
    from .execution_safety import NonceManager,ClockHealthMonitor,HyperliquidRateLimitManager
    from .public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
    from .hyperliquid_client import RequestsInfoTransport
    from .hyperliquid_market_data import HyperliquidMarketData
    from .hyperliquid_account import HyperliquidAccount
    from .live_readiness import verify_live_account_readiness
    from .reliability_policy import load_reliability_policy
    from .scored_session import require_shared_scope
    from .order_lifecycle import parse_exchange_action_result,OrderState
    from .pas_funding import read_funding
    from .paper_operations import PaperOwner
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    p=json.loads(Path(plan_path).read_text());d=json.loads(Path(discovery_path).read_text())
    a=PasConfigurationApproval(**json.loads(Path(acceptance).read_text()));now=time.time_ns()//1000000
    a.require(TEAM,API,now)
    # Plan was fresh at genuine approval; all exchange checks repeat below.
    require_plan(p,d,active_source_hash(root),a.approved_ms)
    if a.plan_hash!=p['plan_hash'] or a.source_hash!=active_source_hash(root) or sha(release)!=a.release_sha256:
        raise ExchangeError('CONFIGURATION_APPROVAL_SOURCE_OR_PLAN_CHANGED')
    require_release(root,release,a.source_hash,a.release_sha256)
    from .team_registration import registration_evidence
    if d.get('registration_evidence')!=registration_evidence(Path(discovery_path).parent,now,scope='CONFIGURATION_ONLY'):
        raise ExchangeError('CONFIGURATION_REGISTRATION_RECORD_CHANGED')
    require_paper_migration('pas');verify_strategy_freeze()
    state=root/'runtime/testnet/anchorium-bot-1'
    # Entry/signer ownership is global; never a new nonce store.
    owner=PaperOwner(state/'pas-configuration-owner.lock')
    journal=client=transport=nonces=None
    result=dict(status='CONFIGURATION_CHECKING',orders_submitted=0,configuration_actions_submitted=0,results=[])
    try:
        journal=ExecutionJournal(state/'pas-configuration.sqlite',session_id='pas-config:'+a.plan_hash,team_address=TEAM)
        rate,clock_policy,_=load_reliability_policy(root/'configs/reliability_policy.json')
        rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=API)
        rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
        client=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),out/'info_receipts.jsonl'),rate_limits=rates,venue='pas')
        client.startup();account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**clock_policy)
        current_action=[None]
        def guard():
            require_paper_migration('pas');a.require(TEAM,API,client.clock_ms())
            if active_source_hash(root)!=a.source_hash or sha(acceptance)!=acceptance_hash:
                raise ExchangeError('CONFIGURATION_SOURCE_OR_ACCEPTANCE_CHANGED')
            require_release(root,release,a.source_hash,a.release_sha256)
            if d.get('registration_evidence')!=registration_evidence(Path(discovery_path).parent,client.clock_ms(),scope='CONFIGURATION_ONLY'):
                raise ExchangeError('CONFIGURATION_REGISTRATION_RECORD_CHANGED')
            wait_for_configuration_reads(rates,a,TEAM,API,venue='pas')
            client.startup()
            isolation=None
            if p.get('configuration_isolation') is not None:
                from .configuration_isolation import ConfigurationIsolation
                isolation=ConfigurationIsolation(root,p['configuration_isolation'],a,p,Path(discovery_path).parent/'configuration_isolation')
            require_shared_scope(root,client,owned_configuration_actions=tuple(x for x in current_action if x is not None),configuration_isolation=isolation)
            if account.get_positions() or account.get_open_orders() or account.get_frontend_open_orders():
                raise ExchangeError('FRESH_FLAT_ACCOUNT_REQUIRED')
            f=read_funding(client,account,provenance=str(out/'info_receipts.jsonl'));result['funding']=f
            if f['status']!='USDP_POSITIVE_VERIFIED' or f['account_mode']!='unifiedAccount':raise ExchangeError('FRESH_PAS_UNIFIED_FUNDING_REQUIRED')
            for _ in range(3):
                sent=client.clock_ms();b=market.get_orderbook('pas:BTC');clock.observe(b.timestamp_ms,sent,client.clock_ms())
                if clock.healthy:break
                rates.wait(250)
            ready=verify_live_account_readiness(account,API,clock_health=clock,rate_limits=rates,reconciliation_ready=True)
            if not ready.account_ready or nonces is not None and not nonces.healthy:raise ExchangeError('CONFIGURATION_ACCOUNT_CLOCK_NONCE_HEALTH_REQUIRED')
            for row in p['changes']:
                if client.market(row['symbol']).asset_id!=row['requested_action']['asset']:raise ExchangeError('CONFIGURATION_RUNTIME_MAPPING_CHANGED')
        acceptance_hash=sha(acceptance);guard()
        key='pas_configuration_attempt:'+a.plan_hash
        with journal.transaction():
            if journal.db.execute('select 1 from controls where name=?',(key,)).fetchone():raise ExchangeError('CONFIGURATION_RESTART_REVIEW_REQUIRED')
            journal.db.execute('insert into controls values(?,?)',(key,'CONSUMED'))
        from .practice_preflight import read_api_key,api_signer
        secret,_=read_api_key(root)
        try:signer=api_signer(secret,API,TEAM)
        finally:secret=None
        nonces=NonceManager(state/'nonces.sqlite',API,journal=journal)
        transport=LeverageConfigurationTransport(client,signer,TEAM,nonces,a,rates=rates,readiness_guard=guard,approved_plan=p)
        for row in p['changes']:
            guard();symbol=row['symbol'];action=row['requested_action']
            if journal.pending_management(action):raise ExchangeError('CONFIGURATION_UNCERTAIN_ACTION_NO_RETRY')
            current=account._query('activeAssetData',coin=symbol)
            if current.get('leverage')==dict(type='cross',value=1):continue
            if current.get('leverage')!=row['before']:raise ExchangeError('CONFIGURATION_BEFORE_VALUE_CHANGED')
            action_id=journal.reserve_management(action,client.clock_ms())
            before=transport.transmission_attempts
            current_action[0]=action_id
            try:
                rates.reserve_action(kind='updateLeverage');response=transport.set_one_x_cross(symbol)
                result['configuration_actions_submitted']+=transport.transmission_attempts-before
                outcome=parse_exchange_action_result(response,[None],action='updateLeverage')[0]
                if outcome.code=='NONCE_ERROR':nonces.degrade()
                if outcome.state!=OrderState.ACKNOWLEDGED:raise ExchangeError('CONFIGURATION_NOT_ACKNOWLEDGED')
                current=account._query('activeAssetData',coin=symbol)
                if current.get('user','').lower()!=TEAM.lower() or current.get('coin')!=symbol or current.get('leverage')!=dict(type='cross',value=1):
                    raise ExchangeError('AUTHORITATIVE_ONE_X_READBACK_REQUIRED')
                journal.update_management(action_id,'ACKNOWLEDGED',client.clock_ms())
                result['results'].append(dict(symbol=symbol,response=response,readback=current,observed_ms=client.clock_ms()))
                atomic_json(out/'result.json',result)
            except Exception:
                if transport.transmission_attempts==before:journal.update_management(action_id,'REJECTED_BEFORE_TRANSMISSION',client.clock_ms())
                raise
            finally:current_action[0]=None
        guard()
        for s in p['entry_markets']:
            r=account._query('activeAssetData',coin=s)
            if r.get('coin')!=s or r.get('user','').lower()!=TEAM.lower() or r.get('leverage')!=dict(type='cross',value=1):
                raise ExchangeError('SELECTED_MARKETS_ONE_X_READBACKS_REQUIRED')
        result.update(status='SELECTED_MARKETS_ONE_X_CROSS_VERIFIED',verified_markets=p['entry_markets'],verified_ms=client.clock_ms())
    except Exception as exc:
        result.update(status='CONFIGURATION_REQUIRES_REVIEW',error=str(exc),blind_retry=False)
    finally:
        if transport:
            result['configuration_actions_submitted']=transport.transmission_attempts
            transport.close()
        if nonces:nonces.close()
        if client:client.close()
        if journal:journal.close()
        owner.close();atomic_json(out/'result.json',result)
    return result
