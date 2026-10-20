"""PAS-only finite contract; never an isolation certificate or practice approval."""
from dataclasses import dataclass
from pathlib import Path
import json, re
from .base_exchange import ExchangeError
from .bounded_daily_session import DailyMandate
from .long_session import LongMandate, sha
from .venue_profiles import SCORED
from .entry_scope import PAS_ENTRY_MARKETS
from .competition_windows import SCORED_START_MS,SCORED_END_MS

SCORED_ACKS = ('exact_pas_usdp_venue','shared_account_nonce_and_unknown_review',
               'qualified_pas_native_and_residual_scope','scored_window_confirmed',
               'no_automatic_renewal_or_midnight_reset')


@dataclass(frozen=True)
class ScoredLimits(DailyMandate):
    dex: str='pas'

    def expected_dex(self): return 'pas'

    def require(self):
        self._require_scope()
        if (self.directions!=('LONG',) or not set(self.markets)<=PAS_ENTRY_MARKETS
                or not SCORED_START_MS<=self.starts_ms<self.expires_ms<=SCORED_END_MS):
            raise ExchangeError('EXACT_FINITE_PAS_SCORED_WINDOW_REQUIRED')
        from .base_exchange import decimal
        if (self.expires_ms-self.starts_ms>3600000 or decimal(self.bankroll)>20000
                or decimal(self.maximum_notional)>1000 or decimal(self.maximum_cumulative_allocation)>2000):
            raise ExchangeError('PAS_SIXTY_MINUTE_20K_BANKROLL_1K_ENTRY_2K_CUMULATIVE_CEILINGS')
        return self


@dataclass(frozen=True)
class ScoredLongMandate(LongMandate):
    mode: str='EXACT_APPROVED_SCORED_PAS_LONG_TESTNET_V1'
    collateral: str='USDP'
    venue_identity: str=SCORED.identity
    organizer_evidence_sha256: str=''
    discovery_evidence_sha256: str=''
    trading_isolation_policy_sha256: str=''

    def require_contract(self,d):
        if (type(d) is not ScoredLimits or self.collateral!='USDP' or self.venue_identity!=SCORED.identity
                or self.mode!='EXACT_APPROVED_SCORED_PAS_LONG_TESTNET_V1'
                or any(not re.fullmatch('[0-9a-f]{64}',v) for v in
                    (self.organizer_evidence_sha256,self.discovery_evidence_sha256))):
            raise ExchangeError('EXACT_PAS_VENUE_AND_EVIDENCE_CONTRACT_REQUIRED')
        if self.trading_isolation_policy_sha256 and not re.fullmatch('[0-9a-f]{64}',self.trading_isolation_policy_sha256):
            raise ExchangeError('EXACT_TRADING_ISOLATION_POLICY_HASH_REQUIRED')


def require_scored_evidence(m, directory):
    """Hash-bound operator-reviewed organizer record, never an inferred date exception.

    Retain the original organizer record separately. This checks scope/identity,
    not the truth of arbitrary supplied text; the human must review provenance.
    """
    p=Path(directory);organizer=p/'organizer_confirmation.json';discovery=p/'venue_discovery.json'
    direct=p/'operator_confirmation.json'
    if organizer.exists() and direct.exists():raise ExchangeError('ONE_EXACT_ACCOUNT_IDENTITY_BASIS_REQUIRED')
    if direct.exists():organizer=direct
    if not organizer.is_file() or not discovery.is_file():
        raise ExchangeError('REVIEWED_PAS_ORGANIZER_AND_DISCOVERY_RECORDS_REQUIRED')
    if sha(organizer)!=m.organizer_evidence_sha256 or sha(discovery)!=m.discovery_evidence_sha256:
        raise ExchangeError('PAS_ORGANIZER_OR_DISCOVERY_RECORD_CHANGED')
    o=json.loads(organizer.read_text());v=json.loads(discovery.read_text())
    direct_basis=organizer.name=='operator_confirmation.json'
    relative=Path(o.get('original_request_file' if direct_basis else 'original_record_file','missing'))
    if relative.is_absolute() or '..' in relative.parts or relative.suffix not in {'.eml','.txt','.json'}:
        raise ExchangeError('LOCAL_ORGANIZER_PROVENANCE_RECORD_REQUIRED')
    raw=(p/relative).resolve()
    if not raw.is_relative_to(p.resolve()):
        raise ExchangeError('LOCAL_ORGANIZER_PROVENANCE_RECORD_REQUIRED')
    if direct_basis:
        from .team_registration import registration_evidence
        registration_evidence(p,m.created_ms)
        from .base_exchange import decimal
        funding=v.get('funding') or {}
        if (funding.get('status')!='USDP_POSITIVE_VERIFIED' or funding.get('account_mode')!='unifiedAccount'
                or funding.get('team_wallet','').lower()!=m.daily.team_wallet.lower()
                or type(funding.get('observed_ms')) is not int or not 0<=m.created_ms-funding['observed_ms']<=300000
                or decimal(funding.get('balance'),positive=True)<=0):
            raise ExchangeError('DIRECT_OPERATOR_IDENTITY_REQUIRES_FRESH_ACTUAL_PAS_FUNDING')
    if (o.get('network')!='testnet' or o.get('dex')!='pas' or o.get('collateral')!='USDP'
            or o.get('team_wallet','').lower()!=m.daily.team_wallet.lower()
            or (not direct_basis and o.get('operator_reviewed_provenance') is not True)
            or not raw.is_file() or sha(raw)!=o.get('original_request_sha256' if direct_basis else 'original_record_sha256')
            or not isinstance(o.get('source_reference'),str) or not o['source_reference'].strip()
            or type(o.get('starts_ms')) is not int or type(o.get('expires_ms')) is not int
            or not o['starts_ms']<=m.daily.starts_ms<m.daily.expires_ms<=o['expires_ms']
            or v.get('dex')!='pas' or v.get('collateral')!='USDP'
            or v.get('venue_identity')!=SCORED.identity):
        raise ExchangeError('APPLICABLE_REVIEWED_PAS_ORGANIZER_SCOPE_REQUIRED')
    if (v.get('network')!='testnet' or v.get('status')!='READ_ONLY_DISCOVERY_COMPLETE'
            or v.get('source_hash')!=m.daily.source_hash or v.get('source_hash_after')!=m.daily.source_hash
            or v.get('journal_integrity')!='ok' or v.get('terminal_flat') is not True
            or type(v.get('finished_ms')) is not int or not 0<=m.created_ms-v['finished_ms']<=300000
            or {r.get('symbol') for r in v.get('markets',[])}!=SCORED.markets
            or {r.get('name') for r in v.get('metadata',{}).get('universe',[])}!=SCORED.markets
            or type(v.get('dex_index')) is not int or v['dex_index']<=0
            or v.get('collateral_token')!=v.get('metadata',{}).get('collateralToken')):
        raise ExchangeError('COMPLETE_SOURCE_BOUND_FRESH_PAS_DISCOVERY_REQUIRED')
    bound={str(organizer):sha(organizer),str(discovery):sha(discovery),str(raw):sha(raw)}
    if m.trading_isolation_policy_sha256:
        from .trading_isolation import validate_policy,require_subject
        policy=p/'trading_isolation/policy.json'
        if sha(policy)!=m.trading_isolation_policy_sha256:raise ExchangeError('TRADING_ISOLATION_POLICY_CHANGED')
        body=validate_policy(Path(__file__).resolve().parents[2],policy,
            source=m.daily.source_hash,reference_ms=m.created_ms)
        require_subject(body,m)
        for file in (policy,policy.with_name('fills.json'),policy.parent/'readbacks/par_info_receipts.jsonl',policy.parent/'readbacks/pas_info_receipts.jsonl'):
            bound[str(file)]=sha(file)
        if policy.with_name('acceptance.json').exists():bound[str(policy.with_name('acceptance.json'))]=sha(policy.with_name('acceptance.json'))
    return bound


def require_shared_scope(root,client,*,owned_pas_intents=(),owned_configuration_actions=(),configuration_isolation=None,trading_isolation=None):
    """Preserve shared PAR/PAS exposure and unresolved-order barriers.

    Only the accepted configuration capability or the independently accepted
    source/mandate-bound finite trading capability can isolate the pinned row.
    Neither substitutes for a central action permit or native qualification.
    """
    from .terminal_evidence import local_execution_state
    from .configuration_isolation import CLOID
    local=local_execution_state(root)
    permitted=set(owned_pas_intents)
    isolated=None
    if trading_isolation is not None:
        from .trading_isolation import FiniteTradingIsolation
        if type(trading_isolation) is not FiniteTradingIsolation or configuration_isolation is not None or owned_configuration_actions:
            raise ExchangeError('EXACT_TRADING_ONLY_ISOLATION_CAPABILITY_REQUIRED')
        isolated=trading_isolation.exempt_intent(client)
    if configuration_isolation is not None:
        from .configuration_isolation import ConfigurationIsolation,CLOID
        if type(configuration_isolation) is not ConfigurationIsolation or permitted:
            raise ExchangeError('CONFIGURATION_ISOLATION_CANNOT_AUTHORIZE_ORDER_SCOPE')
        isolated=configuration_isolation.exempt_intent(client)
    if (local['status'] not in {'NO_LOCAL_UNRESOLVED_INTENT','BLOCKED_UNRESOLVED_INTENT'}
            or any(not (r.get('journal')=='pas' and r.get('intent_key') in permitted
                and r.get('state') in {'PREPARED','SUBMITTED','OPEN','CANCEL_PENDING','PARTIALLY_FILLED'})
                for r in local['unresolved'] if not (
                    isolated is not None and r.get('journal')=='qualification' and r.get('cloid')==CLOID
                    and r.get('intent_key')==isolated and r.get('state')=='UNKNOWN')
                and not (r.get('journal')=='pas-configuration' and r.get('management_id') in set(owned_configuration_actions) and r.get('state')=='UNKNOWN'))):
        raise ExchangeError('PAS_SHARED_ACCOUNT_UNKNOWN_REQUIRES_ADMISSIBLE_RESOLUTION')
    # Explicit /info requests only. The selected PAS client intentionally cannot
    # issue other-DEX queries; no second signer or transport is constructed.
    from .hyperliquid_client import RequestsInfoTransport
    from .testnet_certification import TEAM
    from .base_exchange import decimal
    started=client.clock_ms()
    # Existing par/PAS migration policy has one shared team/signer/nonce domain.
    # This is an additional par read, never a fallback for any PAS market query.
    for kind in ('clearinghouseState','openOrders','frontendOpenOrders'):
        payload=dict(type=kind,user=TEAM,dex='par')
        operation=(lambda:client.transport(payload,cancel_event=client.read_cancel_event,progress=client.progress)) if isinstance(
            client.transport,RequestsInfoTransport) else lambda:client.transport(payload)
        value=client.rate_limits.read(kind,operation,request_key='shared:'+json.dumps(payload,sort_keys=True),
            cancel_event=client.read_cancel_event)
        if kind=='clearinghouseState':
            if not isinstance(value,dict) or not isinstance(value.get('assetPositions'),list):
                raise ExchangeError('SHARED_ACCOUNT_POSITION_READ_REQUIRED')
            occupied=any(decimal(r['position']['szi']) for r in value['assetPositions'])
        else:
            if not isinstance(value,list):raise ExchangeError('SHARED_ACCOUNT_ORDER_READ_REQUIRED')
            occupied=bool(value)
        if occupied:raise ExchangeError('OTHER_DEX_EXPOSURE_OR_ORDERS_BLOCK_PAS_SIGNING')
    if not 0<=client.clock_ms()-started<=5000:
        raise ExchangeError('SHARED_ACCOUNT_PREFLIGHT_STALE')
