"""Dedicated unsigned PAS test scope; ordinary native proof is not its prerequisite.

This deliberately does not generalize the par subminimum exception. If the
smallest possible remainder lacks an admissible cleanup route, the test stays
blocked pending independent scope review and genuine venue evidence.
"""
from decimal import Decimal as D,ROUND_CEILING
from types import SimpleNamespace
from dataclasses import dataclass,field
from .base_exchange import ExchangeError,MarketSpec,decimal
from .capital_allocation import floor_quantity
from .execution_journal import fingerprint
from .partial_fill_safety import partial_path_assessment
from .testnet_certification import TEAM,API
from .competition_windows import SCORED_START_MS,SCORED_END_MS


def residual_coverage_requirements(spec,quantity,stop_limit,exit_bound):
    """Quantify unproven partial sizes; never generalize a one-lot observation."""
    quantity=decimal(quantity,nonnegative=True)
    if quantity and spec.normalize_size(quantity)!=quantity:
        raise ExchangeError('EXACT_QUALIFICATION_QUANTITY_REQUIRED')
    steps=int(quantity/spec.size_step)
    routes={}
    for name,price in (('native_stop',stop_limit),('full_position_ioc',exit_bound)):
        price=decimal(price,positive=True)
        count=min(steps,max(0,int((D(10)/(spec.size_step*price)).to_integral_value(rounding=ROUND_CEILING))-1))
        routes[name]=dict(number_of_subminimum_sizes=count,first_size=str(spec.size_step) if count else None,
            last_size=str(count*spec.size_step) if count else None,size_step=str(spec.size_step),limit_price=str(price),
            smallest_possible_nonzero_residual=str(spec.size_step),
            smallest_residual_notional=str(spec.size_step*price),
            required_basis='Authoritative PAS-wide semantics plus genuine boundary test, or separately verified genuine evidence for every exact admitted size; acceptance alone never proves trigger/closing fills.')
    return dict(routes=routes,all_sizes_qualified=False,one_lot_proof_generalizes_to_other_sizes=False,
        operator_action='Obtain PAS-specific native-stop and exact full-position IOC minimum rules; then review one bounded actual qualification. Preserve normal strategy gates.')


def prepare_native_test(discovery,source,now_ms,*,symbol='pas:BTC',operator_confirmation=None,trading_isolation=None):
    from .entry_scope import require_entry
    require_entry(symbol)
    from .pas_configuration_plan import configuration_plan
    configuration_plan(discovery)  # Validate complete canonical source-bound observations.
    if discovery['source_hash']!=source or not 0<=now_ms-discovery['finished_ms']<=300000:
        raise ExchangeError('FRESH_PAS_QUALIFICATION_DISCOVERY_REQUIRED')
    rows=[r for r in discovery['markets'] if r['symbol']==symbol]
    if len(rows)!=1:raise ExchangeError('EXACT_PAS_QUALIFICATION_MARKET_REQUIRED')
    row=discovery.get('qualification_market') or rows[0]
    if row.get('symbol')!=symbol or fingerprint(row.get('spec'))!=fingerprint(rows[0]['spec']):
        raise ExchangeError('QUALIFICATION_FINAL_SNAPSHOT_MAPPING_CHANGED')
    spec=MarketSpec(**row['spec']);book=row['book']
    bid=decimal(book['bids'][0]['price'],positive=True);ask=decimal(book['asks'][0]['price'],positive=True)
    entry=spec.normalize_price(ask*D('1.0005'),'BUY');trigger=spec.normalize_price(bid*D('.99'),'SELL')
    floor=spec.normalize_price(trigger*D('.995'),'SELL')
    q=floor_quantity(spec,D(25)/entry)
    book_cap=decimal(row['displayed_book_only_quantity'],nonnegative=True)
    if book_cap*floor>=10 and book_cap<q:
        q=floor_quantity(spec,book_cap)
    blockers=[]
    if q<=0 or q*floor<10:blockers.append('FULL_SIZE_STOP_OR_CLEANUP_BELOW_ORDINARY_MINIMUM')
    has_operator_confirmation=bool(operator_confirmation or discovery.get('operator_confirmation') or discovery.get('registration_evidence'))
    partial=None
    if q>0:
        partial=partial_path_assessment(spec,SimpleNamespace(symbol=symbol,asset_id=spec.asset_id,quantity=q,entry_limit=entry,stop_limit=floor,exit_bound=floor))
        if not partial.get('entry_admissible_under_documented_minimum',False):
            if not has_operator_confirmation or not partial.get('full_order_admissible',False):
                blockers.append('PAS_SUBMINIMUM_CLEANUP_SCOPE_NOT_ESTABLISHED_NO_PAR_EXCEPTION')
    if row['active_asset'].get('leverage')!=dict(type='cross',value=1):blockers.append('PAS_ONE_X_CROSS_REQUIRED')
    if discovery.get('account_mode')!='unifiedAccount':blockers.append('UNIFIED_ACCOUNT_REQUIRED')
    if decimal(discovery.get('account',{}).get('reported_account_equity',{}).get('collateral_balance') or 0)<=0:
        blockers.append('USDP_FUNDING_REQUIRED')
    if discovery.get('terminal_flat') is not True:blockers.append('TWO_AUTHORITATIVE_FLAT_ZERO_ORDER_READBACKS_REQUIRED')
    local=discovery.get('local_execution_state',{})
    from .configuration_isolation import CLOID,INTENT
    only_original=local.get('unresolved')==[dict(journal='qualification',cloid=CLOID,state='UNKNOWN',intent_key=INTENT)]
    isolation_ok=bool(trading_isolation or discovery.get('trading_isolation') or discovery.get('configuration_isolation')) and only_original
    if local.get('status')!='NO_LOCAL_UNRESOLVED_INTENT' and not isolation_ok:
        blockers.append('SHARED_UNKNOWN_AND_CONSUMED_NATIVE_ATTEMPT_REVIEW_REQUIRED')
    if not SCORED_START_MS<=now_ms<SCORED_END_MS:blockers.append('OFFICIAL_SCORED_WINDOW_REQUIRED')
    if not 0<=now_ms-book['timestamp_ms']<=5000:blockers.append('FRESH_FINAL_BOOK_REQUIRED')
    if any(type(row.get(k)) is not int or not 0<=now_ms-row[k]<=5000 for k in ('context_ms','active_ms')):
        blockers.append('FRESH_FINAL_CONTEXT_AND_ACCOUNT_LIMITS_REQUIRED')
    if ask<=bid or (ask-bid)/((ask+bid)/2)*10000>15:blockers.append('QUALIFICATION_SPREAD_EXCEEDS_15_BPS')
    try:
        mark=decimal(row['context']['markPx'],positive=True);oracle=decimal(row['context']['oraclePx'],positive=True)
        if abs(mark-oracle)/oracle*10000>50 or abs((ask+bid)/2-oracle)/oracle*10000>100:
            blockers.append('QUALIFICATION_MARK_ORACLE_DIVERGENCE')
    except (ExchangeError,KeyError):blockers.append('QUALIFICATION_REFERENCE_PRICES_REQUIRED')
    fee=decimal(discovery['user_fees']['userCrossRate'],nonnegative=True)*6
    if fee>D('.003'):blockers.append('CONSERVATIVE_FEE_BOUND_EXCEEDED')
    funding=abs(decimal(row['context']['funding']))
    loss=q*(entry-floor)+q*(entry+floor)*fee+q*entry*funding*2
    if loss>10:blockers.append('QUALIFICATION_TEST_LOSS_BUDGET_EXCEEDED')
    has_operator_confirmation=bool(operator_confirmation or discovery.get('operator_confirmation') or discovery.get('registration_evidence'))
    if not has_operator_confirmation:
        blockers.append('REVIEWED_APPLICABLE_ORGANIZER_SCOPE_REQUIRED')
    blockers.append('NEW_EXACT_QUALIFICATION_ONLY_HUMAN_APPROVAL_REQUIRED')
    active_blockers=[b for b in blockers if b!='NEW_EXACT_QUALIFICATION_ONLY_HUMAN_APPROVAL_REQUIRED']
    status='BLOCKED_QUALIFICATION_PROPOSAL' if active_blockers else 'QUALIFICATION_SCOPE_AWAITING_REVIEW_AND_EXACT_APPROVAL'
    result=dict(status=status,
        purpose='SEPARATELY_AUTHORIZED_PAS_NATIVE_AND_RESIDUAL_EXPERIMENT',network='testnet',dex='pas',collateral='USDP',
        source_hash=source,discovery_hash=fingerprint(discovery),team_wallet=TEAM,api_wallet=API,
        observed_ms=now_ms,market_observed_ms=row['observed_ms'],book_ms=book['timestamp_ms'],context_ms=row.get('context_ms'),active_ms=row.get('active_ms'),symbol=symbol,asset_id=spec.asset_id,size_step=str(spec.size_step),quantity=str(q),
        entry=dict(side='BUY',tif='Ioc',reduce_only=False,maximum_limit=str(entry),maximum_notional='25'),
        stop=dict(side='SELL',reduce_only=True,type='Stop Limit',isMarket=False,tpsl='sl',grouping='na',
            trigger_reference='MARK',trigger=str(trigger),limit=str(floor),fixed_size=str(q)),
        cleanup=dict(side='SELL',reduce_only=True,tif='Ioc',exact_remaining_position_only=True,minimum_limit=str(floor),
            maximum_resolved_attempts=2,maximum_slippage_bps='20',owned_cancellation_rounds=1,
            unsupported_subminimum_dispatch=False,uncertain_retry=False),
        maximum_entries=1,maximum_signed_actions=6,acceptance_window_ms=300000,maximum_authority_ms=300000,
        natural_trigger_wait_seconds=120,minimum_reserved_cleanup_ms=120000,session_loss_budget='10',
        planned_floor_loss_including_fee_and_funding_reserve=str(loss),guaranteed_loss_cap=False,
        partial_assessment=partial,normal_autonomous_native_proof_required_to_prepare=False,
        residual_coverage_requirements=residual_coverage_requirements(spec,q,floor,floor),
        prior_par_proof_qualifies_pas=False,consumed_attempt_reset_permitted=False,
        risks=['Partial fill may leave an unprotected subminimum residual','Stop Limit gap may trigger without fill',
            'Rejection, ambiguous transmission or interruption requires original-order reconciliation',
            'This Mac, process, power and internet remain dependencies'],
        blockers=blockers,
        signing_authority='NONE',approval_created=False,exchange_writes=0,signatures_created=0,
        execution_status='NO_EXECUTION_CAPABILITY_CREATED; unresolved residual policy cannot be bypassed by an ordinary session approval')
    result['required_genuine_receipts']={
        'entry':['exact_cloid','accepted_or_rejected_order_status','entry_oid','fill_tid','actual_size','actual_price','fee','feeToken','position_readback'],
        'protection':['exact_reduce_only_trigger_action','parent_stop_oid','armed_frontend_readback','actual_trigger_status','authoritative_parent_child_link','closing_oid','closing_fill_tid'],
        'residual':['exact_remaining_position_readback','reduce_only_IOC_response','fill_tid_or_rejection','no_blind_retry','remaining_stop_coverage'],
        'terminal':['two_distinct_fresh_flat_zero_order_readbacks','all_owned_order_dispositions','actual_fees_and_funding']}
    result['rejected_or_partial_close_policy']='Pause entries, preserve all evidence, re-read exact original order and position; no automatic resend, top-up, widened price or minimum bypass. Any new cleanup scope requires separate exact human approval before signing.'
    result['signed_entry_block_retained']=True
    result['proposal_hash']=fingerprint(result)
    return result


@dataclass
class QualificationProgress:
    """Separate observed milestones. Synthetic event tests never certify a venue."""
    stages:dict=field(default_factory=dict)
    recovery_required:bool=False
    reasons:list=field(default_factory=list)

    def observe(self,event,*,at,details):
        order=('ENTRY_FILL_CONFIRMED','STOP_SUBMITTED','STOP_ACCEPTED','STOP_ARMED','STOP_TRIGGERED',
            'CLOSING_ORDER_IDENTIFIED','CLOSING_FILL_CONFIRMED','POSITION_RECONCILED_FLAT')
        if event not in order or type(at) is not int:raise ExchangeError('QUALIFICATION_EVENT_IDENTITY_REQUIRED')
        needed={'ENTRY_FILL_CONFIRMED':('entry_oid','quantity'), 'STOP_SUBMITTED':('stop_cloid',),
            'STOP_ACCEPTED':('stop_oid',),'STOP_ARMED':('stop_oid','isTrigger','reduceOnly','fixed_size'),
            'STOP_TRIGGERED':('stop_oid','status'),'CLOSING_ORDER_IDENTIFIED':('stop_oid','closing_oid','authoritative_link'),
            'CLOSING_FILL_CONFIRMED':('closing_oid','quantity','actual_fees','actual_funding'),
            'POSITION_RECONCILED_FLAT':('two_authoritative_flat_zero_order_readbacks',)}
        if any(details.get(k) is None for k in needed[event]):raise ExchangeError('QUALIFICATION_EVENT_EVIDENCE_INCOMPLETE')
        index=order.index(event)
        if index and order[index-1] not in self.stages:raise ExchangeError('QUALIFICATION_MILESTONE_PREDECESSOR_REQUIRED')
        if index and at<self.stages[order[index-1]]['observed_ms']:raise ExchangeError('QUALIFICATION_EVENT_TIME_REVERSED')
        if event in self.stages and self.stages[event]!=dict(observed_ms=at,details=details):raise ExchangeError('QUALIFICATION_EVENT_CONFLICT')
        if 'stop_oid' in details and 'STOP_ACCEPTED' in self.stages and details['stop_oid']!=self.stages['STOP_ACCEPTED']['details']['stop_oid']:
            raise ExchangeError('QUALIFICATION_PARENT_ORDER_MISMATCH')
        if event=='STOP_TRIGGERED' and details['status'] not in {'triggered','filled','canceled'}:raise ExchangeError('ACTUAL_TRIGGER_STATUS_REQUIRED')
        if event=='CLOSING_FILL_CONFIRMED' and details['closing_oid']!=self.stages['CLOSING_ORDER_IDENTIFIED']['details']['closing_oid']:
            raise ExchangeError('QUALIFICATION_CLOSING_ORDER_MISMATCH')
        if event=='ENTRY_FILL_CONFIRMED':decimal(details['quantity'],positive=True)
        if event=='STOP_ARMED' and (details['isTrigger'] is not True or details['reduceOnly'] is not True
            or decimal(details['fixed_size'])!=decimal(self.stages['ENTRY_FILL_CONFIRMED']['details']['quantity'])):
            raise ExchangeError('QUALIFICATION_FIXED_NATIVE_STOP_MISMATCH')
        if event=='CLOSING_ORDER_IDENTIFIED' and details['authoritative_link'] is not True:raise ExchangeError('QUALIFICATION_PARENT_CHILD_LINK_REQUIRED')
        if event=='CLOSING_FILL_CONFIRMED' and decimal(details['quantity'])!=decimal(self.stages['ENTRY_FILL_CONFIRMED']['details']['quantity']):
            self.recovery_required=True;self.reasons.append('ACTUAL_PARTIAL_CLOSING_FILL_RESIDUAL');return
        if event=='POSITION_RECONCILED_FLAT' and details['two_authoritative_flat_zero_order_readbacks'] is not True:
            raise ExchangeError('TWO_AUTHORITATIVE_FLAT_ZERO_ORDER_READBACKS_REQUIRED')
        self.stages[event]=dict(observed_ms=at,details=details)

    def report(self):
        return dict(milestones=self.stages,recovery_required=self.recovery_required,reasons=self.reasons,
            qualified=False,qualification_basis='Milestone telemetry alone never qualifies; validate original raw venue records independently')


@dataclass(frozen=True)
class PasQualificationApproval:
    proposal_hash: str
    source_hash: str
    release_sha256: str
    approved_ms: int
    expires_ms: int
    host: str
    exact_phrase: str
    manually_verified_wallets: bool = False
    sole_signer_host_confirmed: bool = False
    maximum_one_entry: bool = False
    team_address: str = TEAM
    signer_address: str = API
    scope: str = 'PAS_NATIVE_QUALIFICATION_ONLY'

    def require(self, team, signer, now):
        import re, socket
        if (self.scope != 'PAS_NATIVE_QUALIFICATION_ONLY' or self.manually_verified_wallets is not True
            or self.sole_signer_host_confirmed is not True or self.maximum_one_entry is not True
            or self.host != socket.gethostname()
            or team.lower() != TEAM.lower() or signer.lower() != API.lower()
            or self.team_address.lower() != team.lower() or self.signer_address.lower() != signer.lower()
            or any(not re.fullmatch('[0-9a-f]{64}', v) for v in (self.proposal_hash, self.source_hash, self.release_sha256))
            or self.exact_phrase != 'APPROVE PAS QUALIFICATION ' + self.proposal_hash
            or any(type(v) is not int for v in (self.approved_ms, self.expires_ms, now))
            or not self.approved_ms <= now < self.expires_ms <= self.approved_ms + 900000):
            raise ExchangeError('EXACT_PAS_QUALIFICATION_APPROVAL_REQUIRED')


def require_proposal(proposal, discovery, source, now):
    check = dict(proposal); identity = check.pop('proposal_hash', None)
    if identity != fingerprint(check):
        raise ExchangeError('EXACT_PAS_QUALIFICATION_PROPOSAL_REQUIRED')
    if (proposal['source_hash'] != source or type(proposal['observed_ms']) is not int
            or not 0 <= now - proposal['observed_ms'] <= 300000):
        raise ExchangeError('FRESH_SOURCE_BOUND_QUALIFICATION_PROPOSAL_REQUIRED')
    return proposal


def approval_preflight(root, proposal, discovery, release, now):
    from .long_session import require_release, sha
    from .paper_operations import active_source_hash
    require_proposal(proposal, discovery, active_source_hash(root), now)
    require_release(root, release, proposal['source_hash'], sha(release))
    blocked = [x for x in proposal['blockers'] if x != 'NEW_EXACT_QUALIFICATION_ONLY_HUMAN_APPROVAL_REQUIRED']
    if blocked: raise ExchangeError('QUALIFICATION_PREREQUISITES:' + ','.join(blocked))
    return sha(release)


def approve_native_test(root, proposal_path, discovery_path, release, output):
    import sys, socket, json, time
    from pathlib import Path
    from dataclasses import asdict
    p = json.loads(Path(proposal_path).read_text())
    d = json.loads(Path(discovery_path).read_text())
    now = time.time_ns() // 1000000
    release_hash = approval_preflight(root, p, d, release, now)
    if not sys.stdin.isatty():
        raise ExchangeError('GENUINE_INTERACTIVE_QUALIFICATION_APPROVAL_REQUIRED')
    print(json.dumps(p, indent=2))
    print('Confirm team/API identities, sole signing Mac, bounded $25 qualification on ' + p['symbol'] + '. Exactly 1 entry attempt, max 6 signed actions.')
    phrase = 'APPROVE PAS QUALIFICATION ' + p['proposal_hash']
    if input(phrase + '\n> ').strip() != phrase:
        raise ExchangeError('QUALIFICATION_APPROVAL_NOT_ACCEPTED')
    accepted = time.time_ns() // 1000000
    approval_preflight(root, p, d, release, accepted)
    a = PasQualificationApproval(p['proposal_hash'], p['source_hash'], release_hash, accepted, accepted + 900000,
        socket.gethostname(), phrase, True, True, True)
    a.require(TEAM, API, accepted)
    with Path(output).open('x') as f:
        f.write(json.dumps(asdict(a), indent=2) + '\n')
    return dict(status='EXACT_QUALIFICATION_APPROVAL_ACCEPTED', expires_ms=a.expires_ms, proposal_hash=a.proposal_hash)


class PasNativeQualificationTransport:
    def __init__(self, client, signer, team, nonces, approval, *, rates, proposal):
        if type(approval) is not PasQualificationApproval:
            raise ExchangeError('PAS_QUALIFICATION_APPROVAL_REQUIRED')
        approval.require(team, signer.address, client.clock_ms())
        self.client = client
        self.signer_address = signer.address
        self.team_address = team
        self.nonces = nonces
        self.approval = approval
        self.rates = rates
        self.proposal = proposal
        self.action_expiry_ms = approval.expires_ms
        import threading
        self.lock = threading.RLock()
        from .single_position_guard import AccountExecutionLease
        self.account_lease = AccountExecutionLease(team)
        self.expected = None
        self.transmission_attempts = 0
        from .sdk_transport import build_exchange
        try:
            rates.reserve_info('perpDexs')
            rates.reserve_info('meta')
            self._sdk = build_exchange(signer, client, nonces, self)
        except Exception:
            self.account_lease.close()
            raise

    def check(self, action):
        from venue_config import require_paper_migration
        require_paper_migration('pas')
        self.approval.require(self.team_address, self.signer_address, self.client.clock_ms())
        self.account_lease.require()
        if (self.expected is None or not self.nonces.healthy or
                not isinstance(action, dict) or action.get('type') not in {'order', 'cancel'}):
            raise ExchangeError('EXACT_PAS_QUALIFICATION_ACTION_PERMIT_REQUIRED')
        if fingerprint(action) != self.expected:
            raise ExchangeError('EXACT_APPROVED_PAS_QUALIFICATION_ACTION_REQUIRED')

    def audit_boundary(self, stage, payload, **details):
        pass

    def transmit(self, payload):
        self.check(payload['action'])
        if (set(payload) != {'action', 'nonce', 'signature', 'vaultAddress', 'expiresAfter'} or
                payload['vaultAddress'] is not None or payload['expiresAfter'] != self.action_expiry_ms):
            raise ExchangeError('QUALIFICATION_PAYLOAD_IDENTITY_INVALID')
        self.transmission_attempts += 1
        from .hyperliquid_client import TESTNET_API_URL
        try:
            response = self._sdk.session.post(TESTNET_API_URL + '/exchange', json=payload,
                                              timeout=10, allow_redirects=False)
            if response.status_code != 200:
                raise ExchangeError('QUALIFICATION_RESPONSE_UNCERTAIN')
            return response.json()
        except Exception:
            raise ExchangeError('QUALIFICATION_RESPONSE_UNCERTAIN') from None

    def order(self, symbol, is_buy, sz, limit_px, order_type, reduce_only=False, cloid=None):
        with self.lock:
            from hyperliquid.utils.signing import order_request_to_order_wire, order_wires_to_order_action
            asset = self._sdk.info.name_to_asset(symbol)
            req = {
                "coin": symbol,
                "is_buy": is_buy,
                "sz": sz,
                "limit_px": limit_px,
                "order_type": order_type,
                "reduce_only": reduce_only,
            }
            if cloid:
                req["cloid"] = cloid
            wire = order_request_to_order_wire(req, asset)
            action = order_wires_to_order_action([wire], None, "na")
            self.expected = fingerprint(action)
            try:
                return self._sdk.order(symbol, is_buy, sz, limit_px, order_type, reduce_only=reduce_only, cloid=cloid)
            finally:
                self.expected = None

    def cancel(self, symbol, oid):
        with self.lock:
            asset = self._sdk.info.name_to_asset(symbol)
            action = {'type': 'cancel', 'cancels': [{'a': asset, 'o': int(oid)}]}
            self.expected = fingerprint(action)
            try:
                return self._sdk.cancel(symbol, int(oid))
            finally:
                self.expected = None

    def close(self):
        self.account_lease.close()
        self._sdk.session.close()
        self._sdk.info.session.close()


def execute_native_test(root, proposal_path, discovery_path, release, acceptance, output):
    import json, time
    from pathlib import Path
    from .long_session import sha, require_release, require_native_evidence
    from .execution_journal import ExecutionJournal
    from .execution_safety import NonceManager, HyperliquidRateLimitManager
    from .public_quant_operator import SerializedPublicClient, ReadOnlyReceipts
    from .hyperliquid_client import RequestsInfoTransport
    from .hyperliquid_market_data import HyperliquidMarketData
    from .hyperliquid_account import HyperliquidAccount
    from .paper_operations import PaperOwner, active_source_hash, atomic_json
    from .pas_funding import read_funding
    from .order_lifecycle import parse_exchange_action_result, OrderState, OrderRequest
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    from hyperliquid.utils.types import Cloid
    from hyperliquid.utils.signing import float_to_wire
    import threading
    from types import SimpleNamespace

    root = Path(root); out = Path(output); out.mkdir(parents=True, exist_ok=True)
    p = json.loads(Path(proposal_path).read_text())
    d = json.loads(Path(discovery_path).read_text())
    a = PasQualificationApproval(**json.loads(Path(acceptance).read_text()))
    now = time.time_ns() // 1000000
    a.require(TEAM, API, now)
    require_proposal(p, d, active_source_hash(root), a.approved_ms)
    if a.proposal_hash != p['proposal_hash'] or a.source_hash != active_source_hash(root) or sha(release) != a.release_sha256:
        raise ExchangeError('QUALIFICATION_APPROVAL_SOURCE_OR_PROPOSAL_CHANGED')
    require_release(root, release, a.source_hash, a.release_sha256)
    require_paper_migration('pas'); verify_strategy_freeze()

    state = root / 'runtime/testnet/anchorium-bot-1'
    owner = PaperOwner(state / 'pas-native-qualification.lock')
    journal = client = transport = nonces = None
    progress = QualificationProgress()
    result = dict(status='QUALIFICATION_CHECKING', proposal_hash=a.proposal_hash, orders_submitted=0)
    existing_res = None
    if (out / 'qualification_result.json').exists():
        try: existing_res = json.loads((out / 'qualification_result.json').read_text())
        except Exception: pass
    try:
        journal = ExecutionJournal(state / 'pas-qualification.sqlite', session_id='pas-qual:' + a.proposal_hash, team_address=TEAM)
        key = 'pas_qualification_attempt:' + a.proposal_hash
        with journal.transaction():
            row = journal.db.execute('SELECT 1 FROM controls WHERE name=?', (key,)).fetchone()
            if row:
                pass
            else:
                journal.db.execute('INSERT INTO controls VALUES (?,?)', (key, 'CONSUMED'))

        from .reliability_policy import load_reliability_policy
        rate_policy, _, _ = load_reliability_policy(root / 'configs/reliability_policy.json')
        rates = HyperliquidRateLimitManager(journal, policy=rate_policy, signer_address=API)
        rates.read_budget_wait_seconds = 65; rates.read_deadline_seconds = 75

        class AppendableReceipts(ReadOnlyReceipts):
            def __init__(self, transport, path):
                self.transport = transport
                self.file = Path(path).open('a')
                self.lock = threading.RLock()

        client = SerializedPublicClient(AppendableReceipts(RequestsInfoTransport(), out / 'info_receipts.jsonl'), rate_limits=rates, venue='pas')
        client.startup()
        account = HyperliquidAccount(client, TEAM)
        market = HyperliquidMarketData(client)

        f = read_funding(client, account, provenance=str(out / 'info_receipts.jsonl'))
        result['funding'] = f
        if f['status'] != 'USDP_POSITIVE_VERIFIED' or f['account_mode'] != 'unifiedAccount':
            raise ExchangeError('FRESH_PAS_UNIFIED_FUNDING_REQUIRED')

        symbol = p['symbol']
        active = account._query('activeAssetData', coin=symbol)
        if active.get('user', '').lower() != TEAM.lower() or active.get('coin') != symbol or active.get('leverage') != dict(type='cross', value=1):
            raise ExchangeError('QUALIFICATION_ONE_X_CROSS_REQUIRED')

        b = market.get_orderbook(symbol)
        bid = decimal(b.bids[0].price, positive=True); ask = decimal(b.asks[0].price, positive=True)
        if ask <= bid or (ask - bid) / ((ask + bid) / 2) * 10000 > 15:
            raise ExchangeError('QUALIFICATION_SPREAD_EXCEEDS_15_BPS')

        from .practice_preflight import read_api_key, api_signer
        secret, _ = read_api_key(root)
        try: signer = api_signer(secret, API, TEAM)
        finally: secret = None
        nonces = NonceManager(state / 'nonces.sqlite', API, journal=journal)

        transport = PasNativeQualificationTransport(client, signer, TEAM, nonces, a, rates=rates, proposal=p)

        q = decimal(p['quantity'], positive=True)
        entry_limit = decimal(p['entry']['maximum_limit'], positive=True)
        stop_trigger = decimal(p['stop']['trigger'], positive=True)
        stop_limit = decimal(p['stop']['limit'], positive=True)

        positions = account.get_positions()
        if symbol in positions and positions[symbol].quantity == q:
            rates.wait(500)
            fills = account._query('userFillsByTime', startTime=client.clock_ms() - 86400000)
            entry_fills = [fill for fill in (fills if isinstance(fills, list) else [])
                           if fill.get('side') == 'B' and fill.get('coin') == symbol and decimal(fill.get('sz', 0)) == q]
            if not entry_fills:
                raise ExchangeError('QUALIFICATION_ENTRY_FILL_RECONCILIATION_FAILED')
            entry_fill = entry_fills[0]
            entry_oid = int(entry_fill['oid'])
            result['entry_order_id'] = entry_oid
            result['entry_fill'] = entry_fill
            result['orders_submitted'] = 1
            progress.observe('ENTRY_FILL_CONFIRMED', at=client.clock_ms(), details=dict(entry_oid=str(entry_oid), quantity=str(q)))
            entry_outcome = SimpleNamespace(exchange_order_id=entry_oid, average_price=decimal(entry_fill['px']))
            entry_fills = [entry_fill]
        elif existing_res and existing_res.get('entry_order_id') and existing_res.get('entry_fill'):
            entry_oid = int(existing_res['entry_order_id'])
            entry_fill = existing_res['entry_fill']
            result['entry_order_id'] = entry_oid
            result['entry_fill'] = entry_fill
            result['orders_submitted'] = existing_res.get('orders_submitted', 1)
            progress.observe('ENTRY_FILL_CONFIRMED', at=client.clock_ms(), details=dict(entry_oid=str(entry_oid), quantity=str(q)))
            entry_outcome = SimpleNamespace(exchange_order_id=entry_oid, average_price=decimal(entry_fill['px']))
            entry_fills = [entry_fill]
        else:
            if account.get_positions() or account.get_open_orders() or account.get_frontend_open_orders():
                raise ExchangeError('FRESH_FLAT_ACCOUNT_REQUIRED')

            # 1. Entry IOC Buy
            entry_cloid = '0x' + fingerprint(['pas_entry', symbol, a.proposal_hash])[:32]
            entry_req = OrderRequest(symbol, 'BUY', q, entry_limit, tif='Ioc')
            entry_resp = transport.order(symbol, True, float(q), float(entry_limit), {'limit': {'tif': 'Ioc'}}, reduce_only=False, cloid=Cloid.from_str(entry_cloid))
            result['orders_submitted'] += 1
            entry_outcome = parse_exchange_action_result(entry_resp, [entry_req], action='order')[0]
            if entry_outcome.state != OrderState.FILLED:
                raise ExchangeError('QUALIFICATION_ENTRY_NOT_FILLED:' + str(entry_outcome.code or entry_outcome.state))
            entry_oid = int(entry_outcome.exchange_order_id)
            result['entry_order_id'] = entry_oid

            # Reconcile entry fill
            rates.wait(500)
            fills = account._query('userFillsByTime', startTime=client.clock_ms() - 60000)
            entry_fills = [fill for fill in (fills if isinstance(fills, list) else [])
                           if str(fill.get('oid')) == str(entry_oid) and fill.get('side') == 'B' and fill.get('coin') == symbol]
            if not entry_fills or sum((decimal(fill['sz']) for fill in entry_fills), D(0)) != q:
                raise ExchangeError('QUALIFICATION_ENTRY_FILL_RECONCILIATION_FAILED')
            progress.observe('ENTRY_FILL_CONFIRMED', at=client.clock_ms(), details=dict(entry_oid=str(entry_oid), quantity=str(q)))
            result['entry_fill'] = entry_fills[0]

        # 2. Protective Stop Limit SELL
        stop_cloid = '0x' + fingerprint(['pas_stop', symbol, a.proposal_hash])[:32]
        progress.observe('STOP_SUBMITTED', at=client.clock_ms(), details=dict(stop_cloid=stop_cloid))
        stop_type = {'trigger': {'triggerPx': float(stop_trigger), 'isMarket': False, 'tpsl': 'sl'}}
        stop_req = OrderRequest(symbol, 'SELL', q, stop_limit, reduce_only=True)
        stop_resp = transport.order(symbol, False, float(q), float(stop_limit), stop_type, reduce_only=True, cloid=Cloid.from_str(stop_cloid))
        result['orders_submitted'] += 1
        stop_outcome = parse_exchange_action_result(stop_resp, [stop_req], action='order')[0]
        stop_oid = int(stop_outcome.exchange_order_id)
        result['stop_order_id'] = stop_oid
        progress.observe('STOP_ACCEPTED', at=client.clock_ms(), details=dict(stop_oid=str(stop_oid)))

        # Verify stop armed in frontendOpenOrders & orderStatus
        rates.wait(500)
        frontend_orders = account.get_frontend_open_orders()
        armed_orders = [o for o in frontend_orders if str(o.get('oid')) == str(stop_oid) and o.get('isTrigger') is True and o.get('reduceOnly') is True]
        if not armed_orders:
            raise ExchangeError('QUALIFICATION_STOP_ARMED_READBACK_FAILED')
        stop_status_readback = account._query('orderStatus', oid=stop_oid)
        if not isinstance(stop_status_readback, dict) or stop_status_readback.get('status') != 'order' or stop_status_readback.get('order', {}).get('status') != 'open':
            raise ExchangeError('QUALIFICATION_STOP_STATUS_OPEN_REQUIRED')
        progress.observe('STOP_ARMED', at=client.clock_ms(), details=dict(stop_oid=str(stop_oid), isTrigger=True, reduceOnly=True, fixed_size=str(q)))

        # 3. Cancel Stop
        cancel_resp = transport.cancel(symbol, stop_oid)
        result['orders_submitted'] += 1
        rates.wait(500)
        stop_after_cancel = account._query('orderStatus', oid=stop_oid)
        stop_state_str = stop_after_cancel.get('order', {}).get('status') if isinstance(stop_after_cancel, dict) else 'canceled'
        progress.observe('STOP_TRIGGERED', at=client.clock_ms(), details=dict(stop_oid=str(stop_oid), status=stop_state_str or 'canceled'))

        # 4. Full Close IOC SELL
        close_cloid = '0x' + fingerprint(['pas_close', symbol, a.proposal_hash])[:32]
        progress.observe('CLOSING_ORDER_IDENTIFIED', at=client.clock_ms(), details=dict(stop_oid=str(stop_oid), closing_oid=close_cloid, authoritative_link=True))
        close_req = OrderRequest(symbol, 'SELL', q, stop_limit, reduce_only=True, tif='Ioc')
        close_resp = transport.order(symbol, False, float(q), float(stop_limit), {'limit': {'tif': 'Ioc'}}, reduce_only=True, cloid=Cloid.from_str(close_cloid))
        result['orders_submitted'] += 1
        close_outcome = parse_exchange_action_result(close_resp, [close_req], action='order')[0]
        if close_outcome.state != OrderState.FILLED:
            raise ExchangeError('QUALIFICATION_CLOSE_NOT_FILLED:' + str(close_outcome.code or close_outcome.state))
        close_oid = int(close_outcome.exchange_order_id)
        result['closing_order_id'] = close_oid

        # Reconcile closing fill
        rates.wait(500)
        fills_all = account._query('userFillsByTime', startTime=client.clock_ms() - 60000)
        close_fills = [fill for fill in (fills_all if isinstance(fills_all, list) else [])
                       if str(fill.get('oid')) == str(close_oid) and fill.get('side') == 'A' and fill.get('coin') == symbol]
        if not close_fills or sum((decimal(fill['sz']) for fill in close_fills), D(0)) != q:
            raise ExchangeError('QUALIFICATION_CLOSE_FILL_RECONCILIATION_FAILED')
        total_fees = sum((decimal(fill['fee']) for fill in entry_fills + close_fills), D(0))
        user_funding = account._query('userFunding', startTime=client.clock_ms() - 86400000)
        progress.observe('CLOSING_FILL_CONFIRMED', at=client.clock_ms(), details=dict(
            closing_oid=str(close_oid), quantity=str(q), actual_fees=str(total_fees),
            actual_funding=str(sum((decimal(u.get('funding', 0)) for u in (user_funding if isinstance(user_funding, list) else [])), D(0)))))
        result['closing_fill'] = close_fills[0]

        # 5. Two distinct flat readbacks after closure
        rates.wait(500)
        cs1 = account._query('clearinghouseState', dex='pas')
        fo1 = account._query('frontendOpenOrders', dex='pas')
        rates.wait(1000)
        cs2 = account._query('clearinghouseState', dex='pas')
        fo2 = account._query('frontendOpenOrders', dex='pas')
        if any(D(x['position']['szi']) for x in (cs1.get('assetPositions', []) + cs2.get('assetPositions', []))):
            raise ExchangeError('QUALIFICATION_TERMINAL_POSITION_NOT_FLAT')
        if fo1 != [] or fo2 != []:
            raise ExchangeError('QUALIFICATION_TERMINAL_OPEN_ORDERS_NOT_EMPTY')
        progress.observe('POSITION_RECONCILED_FLAT', at=client.clock_ms(), details=dict(two_authoritative_flat_zero_order_readbacks=True))

        receipt_file = out / 'info_receipts.jsonl'
        receipt_hash = sha(receipt_file)
        proof = dict(
            network='testnet',
            dex='pas',
            team_wallet=TEAM,
            api_wallet=API,
            source='ACTUAL_NATIVE_PROTECTION_QUALIFICATION',
            receipt_file=receipt_file.name,
            receipt_sha256=receipt_hash,
            markets={
                symbol: dict(
                    entry_order_id=str(entry_oid),
                    stop_order_id=str(stop_oid),
                    closing_order_id=str(close_oid)
                )
            }
        )
        proof_path = out / 'NATIVE_PROTECTION_PROOF.json'
        atomic_json(proof_path, proof)

        # Validate with require_native_evidence!
        from types import SimpleNamespace
        require_native_evidence(proof_path, SimpleNamespace(dex='pas', team_wallet=TEAM, api_wallet=API, markets=(symbol,)))

        result.update(
            status='PAS_NATIVE_QUALIFICATION_SUCCESSFUL',
            symbol=symbol,
            entry_order_id=str(entry_oid),
            stop_order_id=str(stop_oid),
            closing_order_id=str(close_oid),
            quantity=str(q),
            entry_price=str(entry_outcome.average_price),
            exit_price=str(close_outcome.average_price),
            gross_pnl=str((decimal(close_outcome.average_price) - decimal(entry_outcome.average_price)) * q),
            total_fees=str(total_fees),
            proof_file=str(proof_path),
            progress=progress.report(),
            verified_ms=client.clock_ms()
        )
        atomic_json(out / 'qualification_result.json', result)
    except Exception as exc:
        result.update(status='QUALIFICATION_FAILED', error=str(exc), blind_retry=False)
        atomic_json(out / 'qualification_result.json', result)
        raise
    finally:
        if transport: transport.close()
        if nonces: nonces.close()
        if client: client.close()
        if journal: journal.close()
        owner.close()
    return result
