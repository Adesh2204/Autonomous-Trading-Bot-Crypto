"""Bounded canonical venue discovery and genuine account/book report. No signer."""
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
import threading,time
from .venue_profiles import venue_profile
from .public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
from .hyperliquid_client import RequestsInfoTransport
from .hyperliquid_market_data import HyperliquidMarketData
from .hyperliquid_account import HyperliquidAccount
from .hyperliquid_reconciliation import HyperliquidReconciliation,ExchangeTruthState
from .execution_journal import ExecutionJournal
from .rate_limits import HyperliquidRateLimitManager
from .paper_operations import active_source_hash,atomic_json
from .terminal_evidence import opportunity_capacity,local_execution_state
from .capital_allocation import validate_book,depth_capacity,floor_quantity
from .terminal_recovery import terminal_reconcile,exception_evidence
from .testnet_certification import TEAM


def discover(root,output,*,venue='pas',timeout_seconds=180):
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    profile=venue_profile(venue);require_paper_migration(profile);verify_strategy_freeze()
    root,output=Path(root),Path(output);output.mkdir(parents=True,exist_ok=False)
    clock=lambda:time.time_ns()//1000000
    journal=ExecutionJournal(output/'public.sqlite',session_id='public:'+profile.dex+':discovery',team_address=TEAM)
    rates=HyperliquidRateLimitManager(journal);rates.read_budget_wait_seconds=65
    rates.read_deadline_seconds=75
    transport=ReadOnlyReceipts(RequestsInfoTransport(),output/'info_receipts.jsonl')
    client=SerializedPublicClient(transport,rate_limits=rates,venue=profile)
    cancel=threading.Event();timer=threading.Timer(timeout_seconds,cancel.set);timer.start();client.read_cancel_event=cancel
    result=dict(status='DISCOVERING',network='testnet',dex=profile.dex,collateral=profile.collateral,
        venue_identity=profile.identity,started_ms=clock(),source_hash=active_source_hash(root),
        signatures_created=0,exchange_writes=0,signing_authority='NONE',markets=[],errors=[])
    try:
        client.startup();account=HyperliquidAccount(client,TEAM);market=HyperliquidMarketData(client)
        result.update(dex_index=client.dex_index,collateral_token=client.collateral_token_id,
            metadata=client.metadata,deployment=client.discovery,account_mode=account._query('userAbstraction'))
        if profile.dex=='pas':
            from .pas_readiness import require_pas_market_status
            result['market_status']=require_pas_market_status(client)
        fees=account._query('userFees');fee_ms=clock()
        fee=D(fees['userCrossRate'])*6
        result.update(user_fees=fees,fee_rate_bound=str(fee),fee_basis='UNCHANGED_CONSERVATIVE_6X_BASE; actual fills govern charges',
            agents=account._query('extraAgents'),account_rate=account._query('userRateLimit'),local_execution_state=local_execution_state(root))
        contexts=market.get_asset_contexts()
        for symbol in sorted(client.markets):
            spec=client.market(symbol);book=market.get_orderbook(symbol)
            active=account._query('activeAssetData',coin=symbol);at=clock()
            assessment=opportunity_capacity(spec,book,active,dict(symbol=symbol,decision='OBSERVE',metrics={}),
                now_ms=at,active_ms=at,fee_rate=fee,fee_ms=fee_ms,maker_fee_rate=D(fees['userAddRate'])*6)
            validate_book(book,at);buy,sell=depth_capacity(book,'BUY'),depth_capacity(book,'SELL')
            book_q=floor_quantity(spec,min(buy['best_quantity'],sell['best_quantity'],buy['raw_l2_quantity'],sell['raw_l2_quantity'])*D('.1'))
            result['markets'].append(dict(symbol=symbol,spec=asdict(spec),book=asdict(book),active_asset=active,
                context=contexts[symbol],observed_ms=at,capacity=assessment,native_protection_qualified=False,
                displayed_book_only_quantity=str(book_q),displayed_book_only_notional=str(book_q*book.asks[0].price),
                book_only_scope='Both BBO and 5 bps caps, lot rounded; excludes account funding/leverage/risk/protection/approval',
                minimum_notional='10',minimum_basis='DOCUMENTED_ORDINARY_ORDER_POLICY; full-position exceptions are separately qualified'))
            atomic_json(output/'discovery.json',result)
        truth=ExchangeTruthState();reconciler=HyperliquidReconciliation(account)
        result.update(terminal_reconcile(account,reconciler,truth,client,rates,clock,timeout_seconds=timeout_seconds))
        result['status']='READ_ONLY_DISCOVERY_COMPLETE'
    except Exception as exc:
        result.update(status='DISCOVERY_INCOMPLETE',error=exception_evidence(exc));result['errors'].append(str(exc))
    finally:
        timer.cancel();result.update(finished_ms=clock(),source_hash_after=active_source_hash(root),
            journal_integrity=journal.db.execute('PRAGMA integrity_check').fetchone()[0],rate_report=rates.report())
        if profile.dex=='pas' and result['status']=='READ_ONLY_DISCOVERY_COMPLETE':
            from .pas_configuration_plan import configuration_plan
            try:
                result['configuration_plan']=configuration_plan(result)
                atomic_json(output/'account_configuration_plan.json',result['configuration_plan'])
            except Exception as exc:result['configuration_plan_error']=exception_evidence(exc)
        atomic_json(output/'discovery.json',result);client.close();journal.close()
    return result
