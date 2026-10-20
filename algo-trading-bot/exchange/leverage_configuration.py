"""Deliberate, separately approved 1x CROSS configuration; no order interface.

This narrow scope implements the latest user's requested account configuration.
PAPER/false stays enforced. It cannot be supplied to the production executor and
does not authorize orders, cancellations, transfers or other administration.
"""
from dataclasses import dataclass
import threading

from .base_exchange import ExchangeError
from .execution_journal import fingerprint
from .hyperliquid_client import EXPECTED_MARKETS, TESTNET_API_URL
from .sdk_transport import build_exchange
from .single_position_guard import AccountExecutionLease


@dataclass(frozen=True)
class LeverageConfigurationApproval:
    approval_reference: str
    team_address: str
    signer_address: str
    expires_ms: int
    manual_wallet_verified: bool = False
    scope: str = 'PAR_1X_CROSS_CONFIGURATION_ONLY'

    def require(self, team, signer, now):
        from .live_readiness import valid_address
        if (self.scope != 'PAR_1X_CROSS_CONFIGURATION_ONLY' or self.manual_wallet_verified is not True or
                not isinstance(self.approval_reference, str) or not self.approval_reference.strip() or
                not valid_address(self.team_address) or not valid_address(self.signer_address) or
                self.team_address.lower() != team.lower() or self.signer_address.lower() != signer.lower() or
                self.team_address.lower() == self.signer_address.lower() or
                type(self.expires_ms) is not int or type(now) is not int or now >= self.expires_ms):
            raise ExchangeError('EXPLICIT_MANUAL_LEVERAGE_CONFIGURATION_APPROVAL_REQUIRED')


def wait_for_configuration_reads(rates, approval, team, signer, *, required_weight=300, max_wait_ms=65000, venue='par'):
    """Pace a whole read group without spending the configured safety reserve.

    Every account/metadata check still runs after waiting. This is not an action
    retry, a budget reset or permission to submit anything. Expiry is checked
    during the bounded wait; individual waits are at most one second.
    """
    from venue_config import require_paper_migration
    if (type(required_weight) is not int or required_weight < 1 or
            type(max_wait_ms) is not int or not 0 < max_wait_ms <= 65000):
        raise ExchangeError('INVALID_CONFIGURATION_READ_BUDGET')
    started = rates.clock_ms()
    with rates.lock:
        limit = rates.ip_weight_limit - rates._reserve('ip')
    if required_weight > limit:
        raise ExchangeError('CONFIGURATION_READ_GROUP_EXCEEDS_BUDGET')
    while True:
        require_paper_migration(venue)
        now = rates.clock_ms()
        if approval is not None:
            approval.require(team, signer, now)
        with rates.lock:
            available = limit - rates._usage()
            backoff = max(0, rates.backoff_until - now)
        if available >= required_weight and backoff == 0:
            if now > started:
                rates.journal.event('CONFIGURATION_READS_PACED', now,
                                    waited_ms=now-started, required_weight=required_weight)
            return
        elapsed = now - started
        if not 0 <= elapsed < max_wait_ms:
            raise ExchangeError('CONFIGURATION_READ_BUDGET_WAIT_EXHAUSTED')
        rates.wait(min(1000, max_wait_ms-elapsed))


def configuration_plan(client, account):
    if not client.ready or set(client.markets) != EXPECTED_MARKETS:
        raise ExchangeError('COMPLETE_PAR_METADATA_REQUIRED')
    if account.get_positions() or account.get_open_orders() or account.get_frontend_open_orders():
        raise ExchangeError('FLAT_ACCOUNT_WITHOUT_ORDERS_REQUIRED')
    rows = []
    for symbol in sorted(EXPECTED_MARKETS):
        spec = client.market(symbol)
        if spec.max_leverage < 1:
            raise ExchangeError('ONE_X_UNSUPPORTED')
        current = account._query('activeAssetData', coin=symbol)
        if (not isinstance(current, dict) or current.get('coin') != symbol or
                str(current.get('user', '')).lower() != account.team_address.lower() or
                not isinstance(current.get('leverage'), dict) or
                set(current['leverage']) != {'type', 'value'} or
                current['leverage']['type'] not in {'cross', 'isolated'} or
                type(current['leverage']['value']) is not int or current['leverage']['value'] < 1):
            raise ExchangeError('INVALID_ACTIVE_ASSET_CONFIGURATION')
        rows.append(dict(symbol=symbol, asset_id=spec.asset_id, observed_leverage=current['leverage'],
                         desired_leverage=dict(type='cross', value=1),
                         action=dict(type='updateLeverage', asset=spec.asset_id, isCross=True, leverage=1),
                         change_required=current['leverage'] != dict(type='cross', value=1)))
    return dict(network='testnet', dex='par', execution_mode='PAPER', allow_live_orders=False,
                scope='PAR_1X_CROSS_CONFIGURATION_ONLY', rows=rows, actual_orders_permitted=False,
                exchange_actions_submitted=0)


class LeverageConfigurationTransport:
    """Official SDK with an exact-action, single-use configuration permit.

    There is intentionally no generic perform/order/cancel method. Checks run
    before the SDK allocates a durable nonce and again before HTTP transmission.
    """
    def __init__(self, client, signer, team, nonces, approval, *, rates, readiness_guard, approved_plan=None):
        from .par_retirement import reject_retired_par_write
        reject_retired_par_write()
        from eth_account.signers.local import LocalAccount
        from .pas_configuration import PasConfigurationApproval
        expected = PasConfigurationApproval if getattr(client,'dex','par')=='pas' else LeverageConfigurationApproval
        if type(approval) is not expected or not isinstance(signer, LocalAccount):
            raise ExchangeError('CONFIGURATION_APPROVAL_AND_API_SIGNER_REQUIRED')
        approval.require(team, signer.address, client.clock_ms())
        if nonces.signer_address != signer.address.lower():
            raise ExchangeError('API_WALLET_IDENTITY_MISMATCH')
        self.client, self.signer_address, self.team_address = client, signer.address, team
        self.nonces, self.approval, self.rates = nonces, approval, rates
        self.readiness_guard = readiness_guard
        if expected is PasConfigurationApproval:
            if not isinstance(approved_plan,dict):raise ExchangeError('HASH_BOUND_PAS_CONFIGURATION_PLAN_REQUIRED')
            plan=dict(approved_plan);identity=plan.pop('plan_hash',None)
            if identity!=approval.plan_hash or fingerprint(plan)!=identity or plan.get('source_hash')!=approval.source_hash:
                raise ExchangeError('HASH_BOUND_PAS_CONFIGURATION_PLAN_REQUIRED')
            from .entry_scope import PAS_ENTRY_MARKETS
            allowed_assets={client.market(s).asset_id for s in PAS_ENTRY_MARKETS}
            if any(r['requested_action'] not in [dict(type='updateLeverage',asset=a,isCross=True,leverage=1) for a in allowed_assets] for r in plan['changes']):
                raise ExchangeError('V4_BTC_EWY_CONFIGURATION_ACTIONS_ONLY')
            self._approved_actions=frozenset(fingerprint(r['requested_action']) for r in plan['changes'])
            self.action_expiry_ms=approval.expires_ms
        self.consumed_pas_actions=set()
        self.expected = None
        self.transmitted = False
        self.transmission_attempts = 0
        self.lock = threading.RLock()
        self.account_lease = AccountExecutionLease(team)
        try:
            rates.reserve_info('perpDexs')
            rates.reserve_info('meta')
            self._sdk = build_exchange(signer, client, nonces, self)
        except Exception:
            self.account_lease.close()
            raise

    def __repr__(self):
        return '<LeverageConfigurationTransport testnet:'+getattr(self.client,'dex','par')+' 1x-cross-only signer=[PRIVATE]>'

    def check(self, action):
        from venue_config import require_paper_migration
        require_paper_migration(getattr(self.client,'dex','par'))
        self.approval.require(self.team_address, self.signer_address, self.client.clock_ms())
        self.account_lease.require()
        if (self.expected is None or self.transmitted or not self.nonces.healthy or
                not isinstance(action, dict) or set(action) != {'type', 'asset', 'isCross', 'leverage'} or
                action['type'] != 'updateLeverage' or action['isCross'] is not True or
                type(action['leverage']) is not int or action['leverage'] != 1 or
                type(action['asset']) is not int or fingerprint(action) != self.expected or
                action['asset'] not in {m.asset_id for m in self.client.markets.values()}):
            raise ExchangeError('EXACT_ONE_X_CROSS_ACTION_PERMIT_REQUIRED')
        if getattr(self.client,'dex','par')=='pas' and (fingerprint(action) not in getattr(self,'_approved_actions',frozenset()) or fingerprint(action) in self.consumed_pas_actions):
            raise ExchangeError('EXACT_APPROVED_PAS_CONFIGURATION_ACTION_REQUIRED')
        # Account/clock/rate/approval freshness is rechecked at the signed sink.
        self.readiness_guard()
        self.approval.require(self.team_address, self.signer_address, self.client.clock_ms())

    def transmit(self, payload):
        self.check(payload['action'])
        if (set(payload) != {'action', 'nonce', 'signature', 'vaultAddress', 'expiresAfter'} or
                payload['vaultAddress'] is not None or payload['expiresAfter'] != getattr(self,'action_expiry_ms',None)):
            raise ExchangeError('CONFIGURATION_PAYLOAD_IDENTITY_INVALID')
        if getattr(self.client,'dex','par')=='pas':self.consumed_pas_actions.add(fingerprint(payload['action']))
        self.transmitted = True  # An ambiguous response can never reuse a permit.
        self.transmission_attempts += 1
        try:
            response = self._sdk.session.post(TESTNET_API_URL + '/exchange', json=payload,
                                              timeout=10, allow_redirects=False)
            if response.status_code != 200:
                raise ExchangeError('CONFIGURATION_RESPONSE_UNCERTAIN')
            return response.json()
        except Exception:
            raise ExchangeError('CONFIGURATION_RESPONSE_UNCERTAIN') from None

    def set_one_x_cross(self, symbol):
        with self.lock:
            spec = self.client.market(symbol)
            action = dict(type='updateLeverage', asset=spec.asset_id, isCross=True, leverage=1)
            self.expected, self.transmitted = fingerprint(action), False
            try:
                self.check(action)
                return self._sdk.update_leverage(1, symbol, True)
            finally:
                self.expected = None

    def close(self):
        self.account_lease.close()
        self._sdk.session.close()
        self._sdk.info.session.close()
