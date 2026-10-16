"""Explicit bounded certification assembly; no automatic practice or entry retry."""
from dataclasses import asdict
import json
import hashlib
from pathlib import Path
import time

from .base_exchange import ExchangeError
from .execution_journal import ExecutionJournal
from .execution_journal import fingerprint
from .execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager, NonceManager
from .exchange_rules import LiveContextProvider, HyperliquidOrderValidator
from .hyperliquid_client import HyperliquidClient
from .hyperliquid_account import HyperliquidAccount
from .hyperliquid_market_data import HyperliquidMarketData
from .hyperliquid_execution import HyperliquidExecution
from .live_recovery import LiveAccountRecovery, LiveRecoveryReport
from .order_lifecycle import OrderState
from .paper_operations import active_source_hash
from .practice_preflight import read_api_key, api_signer
from .reliability_policy import load_reliability_policy
from .testnet_certification import (CertificationAuthorization, CertificationSDKTransport,
    CertificationSequence, CertificationProtection, require_safe_partial_path)
from .partial_fill_safety import TERMINAL_REJECTIONS, TERMINAL_CANCELLATIONS
from .base_exchange import decimal


class CertificationContextProvider(LiveContextProvider):
    """Refresh prices after serial account checks; all original age limits remain.

The original provider and strategy runtime are unchanged. This bounded test
uses REST and therefore needs a final book/reference read at its own boundary.
"""
    def load(self, request, *, critical=False):
        from dataclasses import replace
        from .hyperliquid_market_data import make_quote
        context = super().load(request, critical=critical)
        metadata, values = self.client.post_info('metaAndAssetCtxs')
        self.client.validate_metadata(metadata)
        if fingerprint(metadata) != context.metadata_hash or len(values) != len(metadata['universe']):
            raise ExchangeError('CERTIFICATION_MARKET_METADATA_CHANGED')
        contexts = {row['name']: value for row,value in zip(metadata['universe'],values)
                    if not row.get('isDelisted')}
        mark_observed_ms = self.client.clock_ms()
        sent = self.client.clock_ms()
        book = self.market.get_orderbook(request.symbol)
        self.clock_health.observe(book.timestamp_ms, sent, self.client.clock_ms())
        quote = make_quote(book, contexts[request.symbol], self.client.clock_ms(),
                           mark_timestamp_ms=mark_observed_ms)
        return replace(context, quote=quote, contexts=contexts, oracle_ms=mark_observed_ms,
                       metadata_ms=mark_observed_ms)


class CertificationRecovery(LiveAccountRecovery):
    """Reuse actual account accounting/checkpoints without VWAP manager state.

Only this isolated execution test omits strategy-management restoration. Its
restarts are read-only and can never resume entries or rebuild strategy stops.
"""
    def recover(self):
        from strategy_freeze import verify_strategy_freeze
        verify_strategy_freeze()
        self.revoke('CERTIFICATION_ACCOUNT_RECONCILIATION_REQUIRED')
        self.state.tracked_order_ids = {str(r['oid']) for r in self.journal.intents() if r['oid']}
        self.reconciler.recover_incremental(self.state, initial_start_ms=self.initial_start_ms)
        reasons = list(self.state.reasons)
        before = self.account.get_frontend_open_orders()
        positions = self.account.get_positions()
        after = self.account.get_frontend_open_orders()
        if before != after or positions != self.state.positions:
            reasons.append('CERTIFICATION_ACCOUNT_CHANGED_DURING_RECOVERY')
        known = {str(r['oid']): r for r in self.journal.intents() if r['oid']}
        if any(str(o['oid']) not in known for o in after):
            reasons.append('UNTRACKED_EXCHANGE_FRONTEND_ORDER')
        self.state.orders = {str(o['oid']): o for o in after}
        if len(positions) > 1:
            reasons.append('UNEXPECTED_CONCURRENT_EXPOSURE')
        if self.checkpoint_error:
            reasons.append(self.checkpoint_error)
        # Safe reduction may still use verified account truth when a tracked
        # reduce-only stop's acknowledgment is uncertain. Entry and completion
        # additionally require every lifecycle uncertainty to be resolved.
        self.account_truth_ready = not reasons
        # Resolve terminal owned orders using original identity, never recreate.
        for row in self.journal.intents():
            if row['state'] not in {'OPEN', 'UNKNOWN', 'SUBMITTED', 'PREPARED'}:
                continue
            status = self.account._query('orderStatus', oid=row['cloid'])
            if status.get('status') == 'order':
                detail = status['order']['order']
                req = json.loads(row['request'])
                if detail.get('cloid') != row['cloid'] or detail.get('coin') != req['symbol']:
                    raise ExchangeError('CERTIFICATION_ORDER_IDENTITY_MISMATCH')
                terminal = status['order']['status']
                if terminal in TERMINAL_REJECTIONS | TERMINAL_CANCELLATIONS:
                    if type(detail.get('oid')) is not int or detail['oid'] < 0:
                        raise ExchangeError('CERTIFICATION_ORDER_IDENTITY_MISMATCH')
                    if any(str(o['oid']) == str(detail['oid']) for o in after):
                        reasons.append('CERTIFICATION_TERMINAL_ORDER_STILL_OPEN')
                    else:
                        matched = [f for f in self.state.fills.values()
                                   if f.order_id == str(detail['oid']) and f.symbol == req['symbol']]
                        quantity = sum((f.quantity for f in matched), decimal(0))
                        requested = decimal(req['quantity'], positive=True)
                        if quantity > requested or any(f.side != req['side'] for f in matched):
                            raise ExchangeError('CERTIFICATION_RECOVERY_FILL_CONFLICT')
                        state = ('FILLED' if quantity == requested else 'PARTIALLY_FILLED' if quantity
                                 else 'REJECTED' if terminal in TERMINAL_REJECTIONS else 'CANCELLED')
                        self.journal.update(row['intent_key'], state, self.account.client.clock_ms(),
                            oid=str(detail['oid']), outcome=dict(filled_quantity=quantity,
                                average_price=sum((f.quantity*f.price for f in matched), decimal(0))/quantity
                                              if quantity else None,
                                remaining_quantity=requested-quantity, remainder_cancelled=True,
                                code='AUTHORITATIVE_TERMINAL_ACCOUNT_EVIDENCE', terminal_status=terminal))
            if self.journal.intent(row['intent_key'])['state'] in {'UNKNOWN', 'SUBMITTED', 'PREPARED'}:
                reasons.append('CERTIFICATION_UNRESOLVED_ORDER')
        if any(r['state'] == 'UNKNOWN' for r in self.journal.management_actions()):
            reasons.append('CERTIFICATION_UNRESOLVED_CANCELLATION')
        self.state.reasons = tuple(dict.fromkeys(reasons))
        self.state.entries_paused = bool(reasons)
        self.checkpoint()
        self.last_report = LiveRecoveryReport(not reasons, self.state.reasons, self.state.report())
        return self.last_report


def build_certification(root, proposal, approval, *, state_directory, test_receipt):
    """No key, SDK signature or HTTP exchange sink exists before authorization.

Must share the real signer's existing nonce store. Source-bound successful full
regression is mandatory; its hash includes scripts as well as core sources.
"""
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    root, state = Path(root).resolve(), Path(state_directory).resolve()
    require_paper_migration(); verify_strategy_freeze()
    if state != root/'runtime/testnet/anchorium-bot-1':
        raise ExchangeError('EXISTING_CERTIFICATION_NONCE_DIRECTORY_REQUIRED')
    receipt = json.loads(Path(test_receipt).read_text())
    current = active_source_hash(root)
    xml = Path(test_receipt).parent/'regression.xml'
    if (not receipt.get('passed') or receipt.get('source_hash') != current
            or receipt.get('source_hash_after') != current
            or receipt['totals']['failures'] or receipt['totals']['errors'] or receipt['totals']['skipped']
            or receipt['totals']['tests'] < 1405 or not xml.is_file()
            or hashlib.sha256(xml.read_bytes()).hexdigest() != receipt.get('xml_sha256')
            or any(c['exit_code'] != 0 for c in receipt.get('checks_before', {}).values())
            or set(receipt.get('checks_before', {})) != {'strategy_freeze','phase0'}):
        raise ExchangeError('SOURCE_BOUND_FULL_REGRESSION_REQUIRED')
    # One durable account journal across all approved attempts, including SHORT.
    journal = ExecutionJournal(state/'certification.sqlite', session_id='anchorium-certification-v8-1',
                               team_address=proposal.team_wallet)
    client = nonces = transport = key = signer = None
    try:
        auth = CertificationAuthorization(proposal, approval, journal, clock_ms=lambda:time.time_ns()//1000000,
            source_hash=lambda:active_source_hash(root),
            policy_hash=lambda:hashlib.sha256((root/'configs/reliability_policy.json').read_bytes()).hexdigest())
        auth.require(proposal.team_wallet, proposal.api_wallet)
        if proposal.entry_side == 'SELL':
            longs = journal.control('long_certification_complete')
            if not longs:
                raise ExchangeError('RECONCILED_LONG_REQUIRED_BEFORE_SHORT')
        if journal.control('certification_active_identity') not in {None, False, proposal.identity}:
            raise ExchangeError('CERTIFICATION_PRIOR_ATTEMPT_REVIEW_REQUIRED')
        if journal.control('certification_started:'+proposal.identity):
            raise ExchangeError('CERTIFICATION_RESTART_READ_ONLY_RECOVERY_REQUIRED')
        rate, cp, _ = load_reliability_policy(root/'configs/reliability_policy.json')
        rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=proposal.api_wallet)
        client = HyperliquidClient(rate_limits=rates); client.startup()
        if client.market(proposal.symbol).asset_id != proposal.asset_id:
            raise ExchangeError('CERTIFICATION_MARKET_MAPPING_CHANGED')
        require_safe_partial_path(client.market(proposal.symbol), proposal)
        account, market = HyperliquidAccount(client, proposal.team_wallet), HyperliquidMarketData(client)
        if account.get_positions() or account.get_open_orders() or account.get_frontend_open_orders():
            raise ExchangeError('CERTIFICATION_INITIAL_FLAT_ACCOUNT_REQUIRED')
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, journal=journal, **cp)
        origin = client.clock_ms()
        # New account windows are only permitted after an independently flat
        # completed prior certification. History is never reset during exposure.
        history_key = 'certification_accounting_origin'
        saved = journal.control(history_key)
        if saved is not None: origin = saved
        else: journal.control(history_key, origin)
        recovery = CertificationRecovery(account, journal, initial_start_ms=origin)
        if recovery.saved_snapshot and recovery.saved_snapshot['account']['initial_start_ms'] != origin:
            raise ExchangeError('CERTIFICATION_ACCOUNTING_ORIGIN_MISMATCH')
        provider = CertificationContextProvider(market, account, proposal.api_wallet, clock, rates,
            reconciliation_ready=lambda:getattr(recovery,'account_truth_ready',False), feed_ready=lambda:True)
        recovery.recover()
        # Real key only derived after all explicit authorization checks.
        key, _ = read_api_key(root); signer = api_signer(key, proposal.api_wallet, proposal.team_wallet); key = None
        nonces = NonceManager(state/'nonces.sqlite', signer.address, journal=journal)
        transport = CertificationSDKTransport(client, signer, proposal.team_wallet, nonces, auth, rate_limits=rates)
        executor = HyperliquidExecution(client, transport=transport, account=account, journal=journal,
            context_provider=provider, validator=HyperliquidOrderValidator(client), recovery=recovery,
            clock_health=clock, rate_limits=rates)
        CertificationProtection(executor, proposal)
        journal.control('certification_active_identity', proposal.identity)
        return CertificationRuntime(CertificationSequence(executor, proposal, auth,
                                    wait=lambda:time.sleep(.5)), client, transport, nonces, journal)
    except Exception:
        if transport is not None: transport.close()
        if nonces is not None: nonces.close()
        if client is not None: client.transport.close()
        journal.close()
        raise
    finally:
        key = signer = None


class CertificationRuntime:
    def __init__(self, sequence, client, transport, nonces, journal):
        self.sequence, self.client, self.transport = sequence, client, transport
        self.nonces, self.journal = nonces, journal

    def run(self):
        result = self.sequence.run()
        if result['status'] == 'TRADE_CLOSED_RECONCILED':
            if self.sequence.p.entry_side == 'BUY':
                self.journal.control('long_certification_complete', self.sequence.p.identity)
            self.journal.control('certification_active_identity', False)
        return result

    def close(self):
        self.sequence.auth.revoke()
        self.transport.close(); self.nonces.close(); self.client.transport.close(); self.journal.close()
