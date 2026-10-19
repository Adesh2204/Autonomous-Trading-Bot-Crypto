"""Prepare unsigned by default; execute only an exact separately accepted test."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import signal
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))

from exchange.base_exchange import ExchangeError
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager
from exchange.exchange_rules import HyperliquidOrderValidator
from exchange.hyperliquid_client import HyperliquidClient, RequestsInfoTransport
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.public_quant_operator import ReadOnlyReceipts
from exchange.paper_operations import active_source_hash, atomic_json
from exchange.reliability_policy import load_reliability_policy
from exchange.testnet_certification import TEAM, API, test_permission
from exchange.testnet_qualification import QualificationContextProvider, require_qualification_regression
from exchange.native_qualification import (NativeQualificationProposal, NativeQualificationApproval,
    NativeQualificationRecovery, propose, require_partial_abort_path)
from exchange.native_qualification_runtime import build_native_qualification
from exchange.native_price_corridor import CorridorNativeProposal, CorridorNativeApproval, CORRIDOR_MODE
from exchange.order_lifecycle import OrderRequest


def prepare(output, receipt):
    from strategy_freeze import verify_strategy_freeze
    from venue_config import require_paper_migration
    from decimal import Decimal as D
    require_paper_migration(); verify_strategy_freeze()
    require_qualification_regression(ROOT, receipt)
    report = dict(status='PREPARATION_ONLY', orders_submitted=0, signatures=0,
        production_mode='PAPER', allow_live_orders=False, native_protection_qualified=False,
        unattended_entries_authorized=False, source_hash=active_source_hash(ROOT))
    journal = client = None
    cancel = threading.Event(); timer = threading.Timer(180, cancel.set); timer.start()
    try:
        journal = ExecutionJournal(output/'read_only.sqlite', session_id='public:native-proposal', team_address=TEAM)
        rate, cp, protection = load_reliability_policy(ROOT/'configs/reliability_policy.json')
        if protection.enabled: raise ExchangeError('GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=API)
        rates.read_budget_wait_seconds = 65; rates.read_deadline_seconds = 75
        client = HyperliquidClient(ReadOnlyReceipts(RequestsInfoTransport(), output/'info_receipts.jsonl'),
                                   rate_limits=rates)
        client.read_cancel_event = cancel
        client.startup()
        account, market = HyperliquidAccount(client, TEAM), HyperliquidMarketData(client)
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, journal=journal, **cp)
        recovery = NativeQualificationRecovery(account, journal, initial_start_ms=0)
        provider = QualificationContextProvider(market, account, API, clock, rates,
            reconcile_before_load=recovery.recover,
            reconciliation_ready=lambda:recovery.account_truth_ready, feed_ready=lambda:True)
        context = provider.load(OrderRequest('par:BTC','BUY','.0002','1',tif='Ioc',
                                            strategy_id='TESTNET_CERTIFICATION_ENTRY'))
        report.update(context=asdict(context), clock=clock.report(), rate=rates.report(),
            account=recovery.state.report(), observed_ms=client.clock_ms())
        p = propose(context, client, report['source_hash'],
            hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest(), bounded=True)
        from exchange.native_qualification import check_entry
        selected=check_entry(context,p,client.clock_ms())
        request = OrderRequest(p.symbol,'BUY',p.quantity,selected,tif='Ioc',
                               strategy_id='TESTNET_CERTIFICATION_ENTRY')
        check = HyperliquidOrderValidator(client).validate(request,context,
            test_permission(request,p,client.clock_ms()),client.clock_ms())
        report['central_validation'] = asdict(check)
        if not check.allowed: raise ExchangeError(check.code)
        report.update(status='AWAITING_EXACT_HUMAN_QUALIFICATION_APPROVAL',
            proposal=asdict(p), mandate_id=p.identity, approval_deadline_ms=p.observed_ms+300000,
            authorization_duration_ms=300000, partial_abort=require_partial_abort_path(context.spec,p),
            pricing_mode=p.pricing_mode,minimum_ask=p.minimum_ask,maximum_ask=p.maximum_ask,
            maximum_buy_price=p.maximum_buy_price,preview_selected_price=str(selected),
            maximum_abs_funding_rate=p.maximum_abs_funding_rate,
            adverse_movement_bps=p.maximum_adverse_movement_bps,
            adverse_movement_absolute=p.maximum_adverse_movement_absolute,
            planned_loss_at_approved_floor=str(D(p.quantity)*(D(p.entry_limit)-D(p.exit_bound))
                +D(p.quantity)*(D(p.entry_limit)+D(p.exit_bound))*D(p.taker_fee_rate)),
            expected_immediate_cleanup_net_before_funding=str(D(p.quantity)*(context.quote.bid-D(p.entry_limit))
                -D(p.quantity)*(context.quote.bid+D(p.entry_limit))*D(p.taker_fee_rate)),
            current_selected_cleanup_net_before_funding=str(D(p.quantity)*(context.quote.bid-selected)
                -D(p.quantity)*(context.quote.bid+selected)*D(p.taker_fee_rate)),
            maximum_funding_reserve=str(D(p.quantity)*D(p.maximum_buy_price)*D(p.maximum_abs_funding_rate)),
            risk='Stop Limit can rest through a gap. Loss budget is not a guaranteed cap. Partial, rejected, uncertain or interrupted cleanup can leave exposure. Mac/process/power/internet required.')
        atomic_json(output/'proposal.json',asdict(p))
        atomic_json(output/'required_acknowledgments.json',dict(
            mandate_id=p.identity, purpose='REQUIRE_GENUINE_HUMAN_RESPONSE_BEFORE_CREATING_APPROVAL',
            fields=[f.name for f in __import__('dataclasses').fields(CorridorNativeApproval)],
            acceptance_created=False))
    except Exception as exc:
        report.update(status='PREFLIGHT_BLOCKED', blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        timer.cancel()
        if client is not None:
            report.update(finished_ms=client.clock_ms(), source_hash_after=active_source_hash(ROOT))
            if report['source_hash_after'] != report['source_hash']:
                report.update(status='PREFLIGHT_BLOCKED', blocker='SOURCE_CHANGED_DURING_PREPARATION')
            client.close()
        if journal is not None:
            report['sqlite_integrity']=journal.db.execute('PRAGMA integrity_check').fetchone()[0]
            journal.close()
        atomic_json(output/'preparation.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','execute'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--test-receipt',type=Path,required=True)
    parser.add_argument('--proposal',type=Path)
    parser.add_argument('--approval',type=Path)
    args=parser.parse_args(argv)
    if args.mode=='execute' and (args.proposal is None or args.approval is None):
        parser.error('execute requires exact proposal and genuine human approval files')
    args.output.mkdir(parents=True,exist_ok=False)
    if args.mode=='prepare':
        result=prepare(args.output,args.test_receipt)
    else:
        runtime=None
        previous=signal.getsignal(signal.SIGTERM)
        def interrupted(*_): raise KeyboardInterrupt('OPERATOR_OR_PROCESS_INTERRUPT')
        signal.signal(signal.SIGTERM,interrupted)
        try:
            data=json.loads(args.proposal.read_text())
            bounded=data.get('pricing_mode')==CORRIDOR_MODE
            p=(CorridorNativeProposal if bounded else NativeQualificationProposal)(**data).require()
            a=(CorridorNativeApproval if bounded else NativeQualificationApproval)(**json.loads(args.approval.read_text()))
            runtime=build_native_qualification(ROOT,p,a,test_receipt=args.test_receipt,output=args.output)
            result=runtime.run()
        except BaseException as exc:
            result = dict(runtime.sequence.report) if runtime is not None else {}
            result.update(status='BLOCKED_OR_INTERRUPTED',error=str(exc) if isinstance(exc,ExchangeError)
                else type(exc).__name__,operator_action_required=runtime is not None,
                native_protection_qualified=False)
            atomic_json(args.output/'result.json',result)
        finally:
            if runtime is not None:runtime.close()
            signal.signal(signal.SIGTERM,previous)
    print(json.dumps({k:result.get(k) for k in ('status','mandate_id','blocker','error',
        'native_protection_qualified','operator_action_required')},indent=2))
    return 0 if result.get('status') in {'AWAITING_EXACT_HUMAN_QUALIFICATION_APPROVAL','TRADE_CLOSED_RECONCILED'} else 1


if __name__=='__main__': raise SystemExit(main())
