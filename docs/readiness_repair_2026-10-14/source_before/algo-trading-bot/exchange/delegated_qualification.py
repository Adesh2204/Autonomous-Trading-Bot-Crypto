"""One human-accepted testnet session, never a production trading permission.

A mandate authorizes an algorithm and ceilings, not fabricated per-price human
approvals. Each selected envelope still uses the existing V2 execution checks.
The shared account journal consumes any transmitted entry permanently.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import uuid

from .base_exchange import ExchangeError, decimal
from .execution_journal import fingerprint
from . import testnet_certification as cert
from .emergency_qualification import (EmergencyAuthorization, EmergencyProposal,
    BOUNDED_PRICE, BOUNDED_POLICY, POLICY, propose)

MODE = 'DELEGATED_TESTNET_QUALIFICATION_V1'
IST = timezone(timedelta(hours=5, minutes=30))
START_MS = int(datetime(2026, 10, 14, tzinfo=IST).timestamp()*1000)
END_MS = int(datetime(2026, 10, 14, 23, 59, tzinfo=IST).timestamp()*1000)
SESSION_SCOPE = dict(network='testnet', dex='par', symbol='par:BTC', collateral='USDPR',
    side='BUY', tif='Ioc', quantity='0.0002', maximum_opening_notional='20',
    maximum_buy_price='100000', leverage=1, margin_mode='cross', entry_attempts=1,
    exit_attempts=2, cancel_attempts=1, signed_actions=4, end_ist='2026-10-14T23:59:00+05:30',
    price_rule='FRESH_ASK_PLUS_10_BPS_CAPPED_AND_NORMALIZED_DOWN',
    fresh_entry_tolerance_bps='20', qualification_spread_bps='50', l2_participation='0.5',
    mark_oracle_bps='50', mid_oracle_bps='100', order_oracle_bps='150',
    exit_rule='EXACT_ACTUAL_LONG_REDUCE_ONLY_IOC_FRESH_BID_MINUS_20_BPS',
    exit_floor_rule='REVIEWED_BID_TIMES_0.98505_NORMALIZED_UP',
    entry_reserve_ms=90000, proposal_window_ms=300000, no_scope_enlargement=True,
    no_entry_after_actual_or_uncertain_submission=True,
    protection='UNVERIFIED_NO_STOP_WILL_BE_SUBMITTED', exposure_cap_is_loss_guarantee=False)
ACKNOWLEDGMENTS = ('manually_verified_wallets', 'sole_signer_host_confirmed',
    'exact_delegated_scope_accepted', 'one_entry_no_retry_accepted',
    'unverified_stop_and_unprotected_exposure_accepted',
    'rejected_partial_exits_and_manual_recovery_accepted',
    'exposure_cap_not_guaranteed_loss_accepted',
    'qualification_only_risk_exceptions_accepted', 'dynamic_price_and_exit_rules_accepted')


@dataclass(frozen=True)
class SessionMandate:
    nonce: str
    created_ms: int
    source_hash: str
    reliability_policy_hash: str
    team_wallet: str = cert.TEAM
    api_wallet: str = cert.API
    mode: str = MODE
    expires_ms: int = END_MS
    execution_policy_hash: str = field(default_factory=lambda: fingerprint(BOUNDED_POLICY))
    scope: dict = field(default_factory=lambda: dict(SESSION_SCOPE))

    def require(self):
        if (self.mode != MODE or type(self.created_ms) is not int
                or not START_MS <= self.created_ms < END_MS
                or type(self.expires_ms) is not int or self.expires_ms != END_MS
                or fingerprint(self.scope) != fingerprint(SESSION_SCOPE) or not isinstance(self.nonce, str)
                or len(self.nonce) != 32 or any(c not in '0123456789abcdef' for c in self.nonce)
                or self.execution_policy_hash != fingerprint(BOUNDED_POLICY)
                or not self.source_hash or not self.reliability_policy_hash
                or self.team_wallet.lower() != cert.TEAM.lower()
                or self.api_wallet.lower() != cert.API.lower()):
            raise ExchangeError('INVALID_DELEGATED_TESTNET_SESSION_SCOPE')
        return self

    @property
    def identity(self):
        self.require()
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class SessionAcceptance:
    session_hash: str
    operator_acceptance: str
    accepted_ms: int | None
    expires_ms: int | None
    manually_verified_wallets: bool = False
    sole_signer_host_confirmed: bool = False
    exact_delegated_scope_accepted: bool = False
    one_entry_no_retry_accepted: bool = False
    unverified_stop_and_unprotected_exposure_accepted: bool = False
    rejected_partial_exits_and_manual_recovery_accepted: bool = False
    exposure_cap_not_guaranteed_loss_accepted: bool = False
    qualification_only_risk_exceptions_accepted: bool = False
    dynamic_price_and_exit_rules_accepted: bool = False

    def require(self, mandate, now_ms):
        mandate.require()
        if (self.session_hash != mandate.identity or not self.operator_acceptance.strip()
                or any(getattr(self, k) is not True for k in ACKNOWLEDGMENTS)
                or type(self.accepted_ms) is not int or type(self.expires_ms) is not int
                or not mandate.created_ms <= self.accepted_ms <= now_ms < self.expires_ms
                or self.expires_ms != mandate.expires_ms):
            raise ExchangeError('EXPLICIT_DELEGATED_SESSION_ACCEPTANCE_REQUIRED')
        return self


@dataclass(frozen=True)
class Delegation:
    mandate: SessionMandate
    acceptance: SessionAcceptance
    acceptance_path: str

    def require(self, now_ms):
        if type(self.mandate) is not SessionMandate or type(self.acceptance) is not SessionAcceptance:
            raise ExchangeError('DELEGATED_SESSION_CAPABILITY_REQUIRED')
        self.acceptance.require(self.mandate, now_ms)
        if Path(self.acceptance_path).with_name('session_revocation.json').exists():
            raise ExchangeError('DELEGATED_SESSION_REVOKED')
        # A missing/replaced acceptance is a revocation. Never cache it past a
        # signing boundary. Runtime construction also rechecks source/receipt.
        try:
            current = json.loads(Path(self.acceptance_path).read_text())
        except (OSError, ValueError, TypeError):
            raise ExchangeError('DELEGATED_ACCEPTANCE_MISSING_OR_CHANGED') from None
        if current != asdict(self.acceptance):
            raise ExchangeError('DELEGATED_ACCEPTANCE_MISSING_OR_CHANGED')
        return self


def validate_proposal(mandate, p, spec=None):
    mandate.require(); p.require()
    if (type(p) is not EmergencyProposal or p.price_authorization_mode != BOUNDED_PRICE
            or p.symbol != 'par:BTC' or p.entry_side != 'BUY' or p.entry_tif != 'Ioc'
            or decimal(p.quantity) != D('0.0002') or decimal(p.quantity_ceiling) != D('0.0002')
            or p.team_wallet.lower() != mandate.team_wallet.lower()
            or p.api_wallet.lower() != mandate.api_wallet.lower()
            or p.source_hash != mandate.source_hash or p.reliability_policy_hash != mandate.reliability_policy_hash
            or not mandate.created_ms <= p.observed_ms < mandate.expires_ms
            or not 10 <= decimal(p.entry_notional_ceiling) <= 20
            or decimal(p.max_buy_price) > 100000
            or decimal(p.quantity)*decimal(p.reference_mark) > 20
            or decimal(p.max_buy_price) > decimal(p.reference_ask)*D('1.002')):
        raise ExchangeError('DELEGATED_PROPOSAL_OUTSIDE_ACCEPTED_SCOPE')
    if spec is not None:
        cap = spec.normalize_price(min(decimal(p.reference_ask)*D('1.002'), D(100000)), 'BUY')
        floor = spec.normalize_price(decimal(p.reference_bid)*D(POLICY['exit_floor_factor']), 'SELL')
        if (spec.symbol != p.symbol or spec.asset_id != p.asset_id
                or spec.normalize_size(p.quantity) != decimal(p.quantity)
                or decimal(p.max_buy_price) != cap or decimal(p.exit_bound) != floor):
            raise ExchangeError('DELEGATED_ALGORITHMIC_ENVELOPE_OR_PRECISION_REQUIRED')
    return p


def propose_delegated(context, client, mandate, book, *, candidate_hash):
    """Same objective V2 algorithm; exact quantity and $20 never auto-expand."""
    p, checks = propose(context, client, mandate.source_hash, mandate.reliability_policy_hash,
        book, tif='Ioc', candidate_hash=candidate_hash, price_mode=BOUNDED_PRICE)
    validate_proposal(mandate, p, context.spec)
    return p, checks


class DelegatedAuthorization(EmergencyAuthorization):
    def __init__(self, proposal, delegation, journal, *, clock_ms, source_hash, policy_hash):
        if type(delegation) is not Delegation:
            raise ExchangeError('DELEGATED_SESSION_CAPABILITY_REQUIRED')
        self.delegation = delegation
        self.mandate = delegation.mandate
        self.runtime_token = uuid.uuid4().hex
        super().__init__(proposal, delegation.acceptance, journal, clock_ms=clock_ms,
            source_hash=source_hash, policy_hash=policy_hash)

    def require(self, team, signer):
        from venue_config import require_paper_migration
        require_paper_migration()
        m, p, now = self.mandate, self.proposal, self.clock_ms()
        self.delegation.require(now)
        validate_proposal(m, p)
        if (self.revoked or self.journal.control('delegated_session_revoked:'+m.identity)
                or self.journal.control('delegated_session_finished:'+m.identity)
                or team.lower() != m.team_wallet.lower() or signer.lower() != m.api_wallet.lower()
                or self.journal.team_address != m.team_wallet.lower()
                or self.source_hash() != m.source_hash or self.policy_hash() != m.reliability_policy_hash
                or not p.observed_ms <= now < min(m.expires_ms, p.observed_ms+300000)
                or self.journal.control('certification_halted:'+p.identity)
                or self.journal.control('certification_completed:'+p.identity)):
            raise ExchangeError('DELEGATED_SESSION_REVOKED_EXPIRED_OR_IDENTITY_CHANGED')
        registered = self.journal.control('delegated_session_active')
        if registered and registered != m.identity:
            raise ExchangeError('ANOTHER_DELEGATED_SESSION_REQUIRES_OPERATOR_REVIEW')
        runtime = self.journal.control('delegated_runtime:'+m.identity)
        if runtime and runtime != dict(proposal_id=p.identity, token=self.runtime_token):
            raise ExchangeError('DELEGATED_RESTART_READ_ONLY_RECOVERY_REQUIRED')

    def register_runtime(self):
        self.require(self.mandate.team_wallet, self.mandate.api_wallet)
        with self.journal.transaction():
            # Recheck while holding the shared account transaction lock.
            self.require(self.mandate.team_wallet, self.mandate.api_wallet)
            if self.journal.intents() or self.journal.control('qualification_entry_consumed'):
                raise ExchangeError('DELEGATED_ENTRY_ALREADY_CONSUMED')
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                ('delegated_session_active', json.dumps(self.mandate.identity)))
            self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',
                ('delegated_runtime:'+self.mandate.identity,
                 json.dumps(dict(proposal_id=self.proposal.identity, token=self.runtime_token))))
        self.journal.event('DELEGATED_SESSION_RUNTIME', self.clock_ms(),
            session_id=self.mandate.identity, proposal_id=self.proposal.identity,
            mandate=asdict(self.mandate), acceptance=asdict(self.approval))

    def require_context(self, context, request):
        self.require(self.mandate.team_wallet, self.mandate.api_wallet)
        validate_proposal(self.mandate, self.proposal, context.spec)
        if not request.reduce_only and (request.quantity != D('0.0002')
                or request.price > 100000 or request.quantity*max(request.price, context.quote.mark) > 20):
            raise ExchangeError('DELEGATED_CURRENT_TWENTY_USDPR_CAP_EXCEEDED')

    def check_action(self, action):
        # V2 still binds the selected envelope, asset, direction, IOC, cloid,
        # exact exits, four actions, one cancel and fresh per-envelope expiry.
        super().check_action(action)
        if self.journal.control('delegated_runtime:'+self.mandate.identity) != dict(
                proposal_id=self.proposal.identity, token=self.runtime_token):
            raise ExchangeError('DELEGATED_DURABLE_RUNTIME_REQUIRED')
        if action.get('type') == 'order' and action['orders'][0]['r'] is False:
            wire = action['orders'][0]
            if (decimal(wire['s']) != D('0.0002') or decimal(wire['p']) > 100000
                    or decimal(wire['s'])*decimal(wire['p']) > 20):
                raise ExchangeError('DELEGATED_SIGNED_ENTRY_EXCEEDS_SCOPE')

    def revoke(self):
        self.revoked = True
        self.journal.control('delegated_session_finished:'+self.mandate.identity, self.clock_ms())


def revoke_session(journal, mandate, now_ms, *, reason):
    """Local durable revocation only; never an exchange cancellation or transfer."""
    mandate.require()
    if journal.team_address != mandate.team_wallet.lower() or not reason.strip():
        raise ExchangeError('DELEGATED_REVOCATION_IDENTITY_REQUIRED')
    journal.control('delegated_session_revoked:'+mandate.identity, now_ms)
    journal.event('DELEGATED_SESSION_REVOKED', now_ms, session_id=mandate.identity, reason=reason)
