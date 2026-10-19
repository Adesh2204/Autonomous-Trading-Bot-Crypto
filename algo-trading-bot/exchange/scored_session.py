"""PAS-only finite contract; never an isolation certificate or practice approval."""
from dataclasses import dataclass
from pathlib import Path
import json, re
from .base_exchange import ExchangeError
from .bounded_daily_session import DailyMandate
from .long_session import LongMandate, sha
from .venue_profiles import SCORED
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
        if (self.directions!=('LONG',) or not set(self.markets)<=SCORED.markets
                or not SCORED_START_MS<=self.starts_ms<self.expires_ms<=SCORED_END_MS):
            raise ExchangeError('EXACT_FINITE_PAS_SCORED_WINDOW_REQUIRED')
        return self


@dataclass(frozen=True)
class ScoredLongMandate(LongMandate):
    mode: str='EXACT_APPROVED_SCORED_PAS_LONG_TESTNET_V1'
    collateral: str='USDP'
    venue_identity: str=SCORED.identity
    organizer_evidence_sha256: str=''
    discovery_evidence_sha256: str=''

    def require_contract(self,d):
        if (type(d) is not ScoredLimits or self.collateral!='USDP' or self.venue_identity!=SCORED.identity
                or self.mode!='EXACT_APPROVED_SCORED_PAS_LONG_TESTNET_V1'
                or any(not re.fullmatch('[0-9a-f]{64}',v) for v in
                    (self.organizer_evidence_sha256,self.discovery_evidence_sha256))):
            raise ExchangeError('EXACT_PAS_VENUE_AND_EVIDENCE_CONTRACT_REQUIRED')


def require_scored_evidence(m, directory):
    """Hash-bound operator-reviewed organizer record, never an inferred date exception.

    Retain the original organizer record separately. This checks scope/identity,
    not the truth of arbitrary supplied text; the human must review provenance.
    """
    p=Path(directory);organizer=p/'organizer_confirmation.json';discovery=p/'venue_discovery.json'
    if not organizer.is_file() or not discovery.is_file():
        raise ExchangeError('REVIEWED_PAS_ORGANIZER_AND_DISCOVERY_RECORDS_REQUIRED')
    if sha(organizer)!=m.organizer_evidence_sha256 or sha(discovery)!=m.discovery_evidence_sha256:
        raise ExchangeError('PAS_ORGANIZER_OR_DISCOVERY_RECORD_CHANGED')
    o=json.loads(organizer.read_text());v=json.loads(discovery.read_text())
    relative=Path(o.get('original_record_file','missing'))
    if relative.is_absolute() or '..' in relative.parts or relative.suffix not in {'.eml','.txt','.json'}:
        raise ExchangeError('LOCAL_ORGANIZER_PROVENANCE_RECORD_REQUIRED')
    raw=(p/relative).resolve()
    if not raw.is_relative_to(p.resolve()):
        raise ExchangeError('LOCAL_ORGANIZER_PROVENANCE_RECORD_REQUIRED')
    if (o.get('network')!='testnet' or o.get('dex')!='pas' or o.get('collateral')!='USDP'
            or o.get('team_wallet','').lower()!=m.daily.team_wallet.lower()
            or o.get('operator_reviewed_provenance') is not True
            or not raw.is_file() or sha(raw)!=o.get('original_record_sha256')
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
    return {str(organizer):sha(organizer),str(discovery):sha(discovery),str(raw):sha(raw)}


def require_shared_scope(root,client,*,owned_pas_intents=(),owned_configuration_actions=()):
    """Read every deployed DEX before PAS signing: one global account, no isolation."""
    from .terminal_evidence import local_execution_state
    local=local_execution_state(root)
    permitted=set(owned_pas_intents)
    if (local['status'] not in {'NO_LOCAL_UNRESOLVED_INTENT','BLOCKED_UNRESOLVED_INTENT'}
            or any(not (r.get('journal')=='pas' and r.get('intent_key') in permitted
                and r.get('state') in {'PREPARED','SUBMITTED','OPEN','CANCEL_PENDING','PARTIALLY_FILLED'})
                for r in local['unresolved'] if not (r.get('journal')=='pas-configuration' and r.get('management_id') in set(owned_configuration_actions) and r.get('state')=='UNKNOWN'))):
        raise ExchangeError('PAS_SHARED_ACCOUNT_UNKNOWN_REQUIRES_ADMISSIBLE_RESOLUTION')
    # Explicit /info requests only. The selected PAS client intentionally cannot
    # issue other-DEX queries; no second signer or transport is constructed.
    from .hyperliquid_client import RequestsInfoTransport
    from .testnet_certification import TEAM
    from .base_exchange import decimal
    started=client.clock_ms()
    # Existing par/PAS migration policy has one shared team/signer/nonce domain.
    # This is an additional par read, never a fallback for any PAS market query.
    for kind in ('clearinghouseState','frontendOpenOrders'):
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
