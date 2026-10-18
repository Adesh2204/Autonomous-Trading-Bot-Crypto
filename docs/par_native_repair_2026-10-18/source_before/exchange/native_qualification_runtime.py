"""Explicit assembly for the tiny native experiment; no read creates consent."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

from .base_exchange import ExchangeError
from .certification_runtime import same_position_exposure
from .execution_journal import ExecutionJournal
from .execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager, NonceManager
from .exchange_rules import HyperliquidOrderValidator
from .hyperliquid_client import HyperliquidClient, RequestsInfoTransport
from .hyperliquid_account import HyperliquidAccount
from .hyperliquid_market_data import HyperliquidMarketData
from .public_quant_operator import ReadOnlyReceipts
from .paper_operations import active_source_hash, atomic_json
from .practice_preflight import read_api_key, api_signer
from .reliability_policy import load_reliability_policy
from .testnet_certification import test_permission
from .testnet_qualification import QualificationContextProvider, require_qualification_regression
from .qualification_intent_recovery import QualificationPositionGuard
from .qualification_protection import require_settled_exit_orders
from .order_lifecycle import OrderRequest
from .native_qualification import (NativeQualificationProposal, NativeQualificationApproval,
    NativeQualificationAuthorization, NativeQualificationTransport, NativeQualificationRecovery,
    NativeQualificationExecution, NativeQualificationSequence, NativeQualificationContextProvider,
    require_partial_abort_path, check_entry)
from .native_price_corridor import CorridorNativeProposal, CorridorNativeApproval


def require_prior_certification_settled(state):
    old = state/'certification.sqlite'
    if not old.exists():
        return
    with sqlite3.connect(old.resolve().as_uri()+'?mode=ro', uri=True) as db:
        if (db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
                or db.execute("SELECT COUNT(*) FROM intents WHERE state NOT IN ('FILLED','CANCELLED','REJECTED')").fetchone()[0]
                or db.execute("SELECT COUNT(*) FROM signed_management WHERE state='UNKNOWN'").fetchone()[0]):
            raise ExchangeError('PRIOR_CERTIFICATION_UNRESOLVED_REVIEW_REQUIRED')


def build_native_qualification(root, proposal, approval, *, test_receipt, output):
    """No private key or nonce allocation until exact consent and all fresh gates."""
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    root, output = Path(root).resolve(), Path(output).resolve()
    require_paper_migration(); verify_strategy_freeze()
    expected = CorridorNativeApproval if type(proposal) is CorridorNativeProposal else NativeQualificationApproval
    if type(proposal) not in {NativeQualificationProposal, CorridorNativeProposal} or type(approval) is not expected:
        raise ExchangeError('EXACT_NATIVE_QUALIFICATION_TYPES_REQUIRED')
    require_qualification_regression(root, test_receipt)
    state = root/'runtime/testnet/anchorium-bot-1'
    require_prior_certification_settled(state)
    journal = ExecutionJournal(state/'qualification.sqlite',
        session_id='anchorium-one-qualification-v1', team_address=proposal.team_wallet)
    client = transport = nonces = key = signer = None
    invocation_key = 'native_qualification_invocation:'+proposal.identity
    invocation_claimed = False
    try:
        auth = NativeQualificationAuthorization(proposal, approval, journal, root=root,
            clock_ms=lambda:time.time_ns()//1000000, source_hash=lambda:active_source_hash(root),
            policy_hash=lambda:hashlib.sha256((root/'configs/reliability_policy.json').read_bytes()).hexdigest())
        auth.require(proposal.team_wallet, proposal.api_wallet)
        if journal.control('native_qualification_attempted'):
            raise ExchangeError('NATIVE_QUALIFICATION_RESTART_REQUIRES_READ_ONLY_REVIEW')
        if type(proposal) is CorridorNativeProposal:
            # Consume the approved invocation even if final public preflight
            # fails. A new output directory cannot restart the same mandate.
            with journal.transaction():
                if journal.db.execute('SELECT 1 FROM controls WHERE name=?',(invocation_key,)).fetchone():
                    raise ExchangeError('NATIVE_CORRIDOR_INVOCATION_ALREADY_CONSUMED')
                journal.db.execute('INSERT INTO controls VALUES (?,?)',(invocation_key,
                    json.dumps(dict(status='PREFLIGHT_STARTED',started_ms=client.clock_ms() if client else time.time_ns()//1000000,
                                    source_hash=proposal.source_hash,do_not_restart=True))))
            invocation_claimed = True
        rate, cp, protection = load_reliability_policy(root/'configs/reliability_policy.json')
        if protection.enabled:
            raise ExchangeError('GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=proposal.api_wallet)
        rates.read_budget_wait_seconds = 65; rates.read_deadline_seconds = 75
        client = HyperliquidClient(ReadOnlyReceipts(RequestsInfoTransport(), output/'info_receipts.jsonl'),
                                   rate_limits=rates)
        client.startup()
        require_partial_abort_path(client.market(proposal.symbol), proposal)
        account, market = HyperliquidAccount(client, proposal.team_wallet), HyperliquidMarketData(client)
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, journal=journal, **cp)
        recovery = NativeQualificationRecovery(account, journal, initial_start_ms=0)
        provider_type = NativeQualificationContextProvider if type(proposal) is CorridorNativeProposal else QualificationContextProvider
        provider = provider_type(market, account, proposal.api_wallet, clock, rates,
            reconcile_before_load=recovery.recover,
            reconciliation_ready=lambda:recovery.account_truth_ready, feed_ready=lambda:True)
        request = OrderRequest(proposal.symbol, 'BUY', proposal.quantity, proposal.entry_limit,
                               tif='Ioc', strategy_id='TESTNET_CERTIFICATION_ENTRY')
        context = provider.load(request)
        selected = check_entry(context, proposal, client.clock_ms())
        if type(proposal) is CorridorNativeProposal:
            from dataclasses import replace
            request = replace(request, price=selected)
        validation = HyperliquidOrderValidator(client).validate(request, context,
            test_permission(request, proposal, client.clock_ms()), client.clock_ms())
        if not validation.allowed:
            raise ExchangeError(validation.code)
        if approval.expires_ms-client.clock_ms() < 150000:
            raise ExchangeError('NATIVE_QUALIFICATION_CLEANUP_TIME_REQUIRED')
        auth.require(proposal.team_wallet, proposal.api_wallet)
        provider.reconcile_before_load = None
        # Actual secrets are deliberately behind source, exact human approval,
        # prior UNKNOWN certificate, regression and genuine account checks.
        key, _ = read_api_key(root)
        signer = api_signer(key, proposal.api_wallet, proposal.team_wallet); key = None
        nonces = NonceManager(state/'nonces.sqlite', signer.address, journal=journal)
        transport = NativeQualificationTransport(client, signer, proposal.team_wallet,
                                                nonces, auth, rate_limits=rates)
        executor = NativeQualificationExecution(client, proposal=proposal, transport=transport,
            account=account, journal=journal, context_provider=provider,
            validator=HyperliquidOrderValidator(client), recovery=recovery,
            clock_health=clock, rate_limits=rates)
        require_settled_exit_orders(executor)
        return NativeQualificationRuntime(root, output,
            NativeQualificationSequence(executor, proposal, auth, wait=lambda:time.sleep(2)),
            client, transport, nonces, journal)
    except BaseException as exc:
        if invocation_claimed:
            journal.control(invocation_key,dict(status='PREFLIGHT_STOPPED',
                stopped_ms=time.time_ns()//1000000,source_hash=proposal.source_hash,
                reason=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,do_not_restart=True))
        if transport is not None: transport.close()
        if nonces is not None: nonces.close()
        if client is not None: client.close()
        journal.close()
        raise
    finally:
        key = signer = None


class NativeQualificationRuntime:
    def __init__(self, root, output, sequence, client, transport, nonces, journal):
        self.root, self.output, self.sequence = root, output, sequence
        self.client, self.transport, self.nonces, self.journal = client, transport, nonces, journal

    def run(self):
        if self.journal.control('native_qualification_attempted'):
            raise ExchangeError('NATIVE_QUALIFICATION_RESTART_REQUIRES_READ_ONLY_REVIEW')
        self.sequence.auth.require(self.sequence.p.team_wallet, self.sequence.p.api_wallet)
        self.journal.control('native_qualification_attempted', self.sequence.p.identity)
        try:
            result = self.sequence.run()
        except BaseException as exc:
            result = self.sequence.report
            result.update(status='INTERRUPTED_REQUIRES_ACCOUNT_REVIEW',
                interruption=type(exc).__name__, native_protection_qualified=False,
                final_flat=False, operator_action_required=True)
        finally:
            self.sequence.auth.revoke()
        # Bounded terminal unsigned reads also run after an interrupt or halt.
        result['terminal_readbacks'] = []
        cancel = threading.Event(); timer = threading.Timer(180, cancel.set)
        self.client.read_cancel_event = cancel; timer.start()
        try:
            for _ in range(2):
                recovery_error = None
                try:
                    self.sequence.e.recovery.recover()
                except Exception as exc:
                    recovery_error = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
                    result['terminal_recovery_error'] = recovery_error
                try:
                    # Unresolved original children do not prevent an honest
                    # direct read of the actual remaining account exposure.
                    before = self.sequence.e.account.get_positions()
                    orders = self.sequence.e.account.get_frontend_open_orders()
                    positions = self.sequence.e.account.get_positions()
                    result['terminal_readbacks'].append(dict(observed_ms=self.client.clock_ms(),
                        positions=[asdict(x) for x in positions.values()], orders=orders,
                        ready=not recovery_error and same_position_exposure(before, positions)
                            and self.sequence.e.recovery.last_report.ready))
                except Exception as exc:
                    result['terminal_read_error'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
                    break
        finally:
            timer.cancel()
        reads = result['terminal_readbacks']
        result['two_terminal_flat_readbacks'] = (len(reads) == 2
            and reads[0]['observed_ms'] < reads[1]['observed_ms']
            and all(x['ready'] and not x['positions'] and not x['orders'] for x in reads))
        if not result['two_terminal_flat_readbacks']:
            result.update(final_flat=False, native_protection_qualified=False, operator_action_required=True)
        if (not cancel.is_set() and type(self.transport) is NativeQualificationTransport and self.sequence.native_fill_complete
                and result['two_terminal_flat_readbacks']):
            self.export_native_proof(result)
        result.update(source_hash_after=active_source_hash(self.root),
            sqlite_integrity=self.journal.db.execute('PRAGMA integrity_check').fetchone()[0],
            dependency='Local Mac, process, power and internet; no remote failover or automatic restart',
            unattended_entries_authorized=False)
        atomic_json(self.output/'result.json', result)
        if type(self.sequence.p) is CorridorNativeProposal:
            self.journal.control('native_qualification_invocation:'+self.sequence.p.identity,
                dict(status='TERMINAL',result_status=result['status'],do_not_restart=True,
                     stopped_ms=self.client.clock_ms(),two_terminal_flat_readbacks=result['two_terminal_flat_readbacks']))
        self.journal.event('NATIVE_QUALIFICATION_RESULT', self.client.clock_ms(), report=result)
        return result

    def export_native_proof(self, result):
        from .long_session import require_native_evidence
        p = self.sequence.p; stop = self.sequence.stop_observation
        entry = self.journal.intent(self.sequence.prefix+'entry')
        ids = {stop['order_id'], *stop['child_order_ids']}
        fills = [f for f in self.sequence.e.recovery.state.fills.values()
                 if f.symbol == p.symbol and f.side == 'SELL' and str(f.order_id) in ids]
        close_ids = {str(f.order_id) for f in fills}
        if len(close_ids) != 1:
            result['native_proof_error'] = 'SINGLE_TRIGGER_LINKED_CLOSING_ORDER_NOT_ESTABLISHED'
            return
        # Manager recovery uses the original CLOID. The independent proof also
        # requires an authoritative read by the numeric parent order ID.
        try:
            self.sequence.e.account._query('orderStatus', oid=int(stop['order_id']))
        except Exception as exc:
            result['native_proof_error'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
            return
        raw = self.output/'info_receipts.jsonl'
        candidate = dict(network='testnet', dex='par', team_wallet=p.team_wallet,
            api_wallet=p.api_wallet, source='ACTUAL_NATIVE_PROTECTION_QUALIFICATION',
            source_hash=p.source_hash, receipt_file=raw.name,
            receipt_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
            markets={p.symbol:dict(entry_order_id=str(entry['oid']), stop_order_id=stop['order_id'],
                closing_order_id=next(iter(close_ids)), qualified_quantity=p.quantity,
                small_native_stop_verified=False)})
        path = self.output/'native_proof_candidate.json'; atomic_json(path, candidate)
        try:
            require_native_evidence(path, SimpleNamespace(team_wallet=p.team_wallet,
                api_wallet=p.api_wallet, markets=(p.symbol,)))
        except Exception as exc:
            result['native_proof_error'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
            return
        atomic_json(self.output/'NATIVE_PROTECTION_PROOF.json', candidate)
        result.update(native_protection_qualified=True,
            native_qualification_status='ACTUAL_FULL_SIZE_TRIGGER_CLOSE_VERIFIED',
            native_protection_scope=dict(symbol=p.symbol, quantity=p.quantity,
                order_type='Stop Limit', small_native_stop_verified=False))

    def close(self):
        self.sequence.auth.revoke()
        # Do not mark an interrupted/exposed account's checkpoint clean.
        self.transport.close(); self.nonces.close(); self.client.close(); self.journal.close()
