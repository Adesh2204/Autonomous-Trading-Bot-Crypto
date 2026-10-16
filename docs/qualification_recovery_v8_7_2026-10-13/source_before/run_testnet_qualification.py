"""Prepare-only by default. Actual qualification requires exact separate risk approval."""
import argparse,json,hashlib,sys,time
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor,HyperliquidRateLimitManager
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.certification_runtime import CertificationRecovery,CertificationContextProvider
from exchange.exchange_rules import HyperliquidOrderValidator
from exchange.order_lifecycle import OrderRequest
from exchange.reliability_policy import load_reliability_policy
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM,API,test_permission
from exchange.testnet_qualification import (QualificationProposal,QualificationApproval,
    propose_qualification,residual_close_assessment,build_qualification,prime_read_only_clock,RULE)
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def prepare(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    r=dict(status='QUALIFICATION_LOCKED',execution_mode='PAPER',prepared_mode='TESTNET_QUALIFICATION',
        allow_live_orders=False,exchange_submissions=0,actual_wallet_signatures=0,
        source_hash=active_source_hash(ROOT),started_utc=datetime.now(timezone.utc).isoformat(),
        entry_rule=RULE,qualification_only_spread_ceiling_bps=50,normal_strategy_spread_ceiling_bps=15,
        maximum_notional='25',normal_protection_certified=False,whitelist_trade_proof=False,
        organizer_whitelisting_confirmed=False,sole_signer_host_confirmed=False,
        candidates=[],approval_requested=False,practice_ready=False,live_ready=False)
    client=journal=None
    try:
        r['safety']=require_paper_migration();r['freeze']=verify_strategy_freeze()
        rate,cp,protection=load_reliability_policy(ROOT/'configs/reliability_policy.json')
        if protection.enabled:raise ExchangeError('QUALIFICATION_GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        journal=ExecutionJournal(directory/'read_only.sqlite',session_id='qualification-proposal',team_address=TEAM)
        rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=API)
        client=HyperliquidClient(rate_limits=rates);client.startup()
        account,market=HyperliquidAccount(client,TEAM),HyperliquidMarketData(client)
        recovery=CertificationRecovery(account,journal,initial_start_ms=0)
        r['initial_reconciliation']=asdict(recovery.recover())
        if not recovery.last_report.ready or account.get_positions() or account.get_frontend_open_orders():
            raise ExchangeError('QUALIFICATION_INITIAL_RECONCILED_FLAT_REQUIRED')
        recovery.checkpoint(clean=True);journal.close()
        journal=ExecutionJournal(directory/'read_only.sqlite',session_id='qualification-proposal',team_address=TEAM)
        rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=API);client.rate_limits=rates
        recovery=CertificationRecovery(account,journal,initial_start_ms=0)
        r['restored_checkpoint']=bool(recovery.saved_snapshot)
        r['reconciliation_after_reopen']=asdict(recovery.recover())
        if not r['restored_checkpoint'] or not recovery.last_report.ready:
            raise ExchangeError('QUALIFICATION_DURABLE_RECONCILIATION_REQUIRED')
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**cp)
        prime_read_only_clock(market,clock,'par:BTC')
        provider=CertificationContextProvider(market,account,API,clock,rates,
            reconciliation_ready=lambda:recovery.account_truth_ready,feed_ready=lambda:True)
        provider.trigger_aware=True
        policyhash=hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest()
        for symbol in ('par:BTC','par:ETH','par:HYPE'):
            row=dict(symbol=symbol,eligible_for_risk_review=False);r['candidates'].append(row)
            # Keep safety reserve for reconciliation; a snapshot may become stale
            # while examining other markets, so execution always revalidates.
            started=time.monotonic()
            while rates._usage()+450>rates.policy.ip_weight_per_minute-rates.policy.ip_safety_reserve:
                if time.monotonic()-started>65:raise ExchangeError('QUALIFICATION_PUBLIC_READ_BUDGET')
                time.sleep(.5)
            try:
                q=market.get_quote(symbol);spec=client.market(symbol)
                seed=OrderRequest(symbol,'BUY',spec.normalize_size(D(25)/q.ask),q.ask,tif='Ioc')
                ctx=provider.load(seed)
                row.update(quote=asdict(ctx.quote),active_asset=ctx.active_asset,readiness=asdict(ctx.readiness),
                           observed_ms=client.clock_ms(),spec=asdict(spec),clock=clock.report())
                p=propose_qualification(ctx,client,r['source_hash'],policyhash)
                req=OrderRequest(p.symbol,'BUY',p.quantity,p.entry_limit,tif='Ioc',strategy_id='TESTNET_CERTIFICATION_ENTRY')
                validation=HyperliquidOrderValidator(client).validate(req,ctx,test_permission(req,p,client.clock_ms()),client.clock_ms())
                row['central_validation']=asdict(validation)
                if not validation.allowed:raise ExchangeError(validation.code)
                row.update(eligible_for_risk_review=True,proposal=asdict(p),proposal_hash=p.identity,
                    spread_bps=str((ctx.quote.ask-ctx.quote.bid)/ctx.quote.mid*10000),
                    residual_close_scope=residual_close_assessment(spec,p.quantity,p.exit_bound))
            except Exception as exc:
                row['blocker']=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__
        eligible=[row for row in r['candidates'] if row['eligible_for_risk_review']]
        if eligible:
            selected=min(eligible,key=lambda row:(D(row['spread_bps']),row['symbol']))
            p=QualificationProposal(**selected['proposal'])
            qty=D(p.quantity);entry=D(p.entry_limit);bid=D(p.reference_bid)
            expected_exit=client.market(p.symbol).normalize_price(bid*D('.998'),'SELL')
            r.update(status='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED',selected_proposal=asdict(p),
                selected_proposal_hash=p.identity,notional=str(qty*entry),
                expected_immediate_exit_limit=str(expected_exit),
                estimated_round_trip_fee_at_reviewed_limits=str(qty*(entry+expected_exit)*D(p.taker_fee_rate)),
                estimated_loss_at_reviewed_immediate_exit=str(qty*(entry-expected_exit)+qty*(entry+expected_exit)*D(p.taker_fee_rate)),
                risk_report=dict(verified=['Funded unified team account, approved agent, durable read-only reconciliation',
                    'Runtime par metadata; central validation; 1x cross, margin, two-sided depth',
                    'All possible lot residuals at the reviewed exit floor map to ordinary or observed narrow full closes'],
                    unverified=['Exchange-side one-lot protection; future exit fills/liquidity',
                        'Manual recovery if connectivity/status/price bounds prevent closure',
                        'Human sole signer host and organizer acceptance of this qualification rule'],
                    no_stop_will_be_submitted=True,possible_unprotected_position=True,
                    principal_at_risk=str(qty*entry),hard_total_loss_cap_guaranteed=False,
                    fees_funding_may_exceed_principal_allowance=True,unknown_order_never_resubmitted=True,
                    entry_attempts=1,exit_attempts=2,maximum_signed_actions=5,automatic_notional_increase=False))
            atomic_json(directory/'proposal.json',asdict(p))
            atomic_json(directory/'approval_REQUIRED_UNFILLED.json',dict(proposal_hash=p.identity,
                operator_approval='',approved_ms=None,expires_ms=None,manually_verified_wallets=False,
                sole_signer_host_confirmed=False,maximum_one_entry=False,unverified_stop_risk_accepted=False,
                qualification_spread_limit_accepted=False,possible_manual_residual_recovery_accepted=False))
        else:r['blocker']='NO_MARKET_PASSES_QUALIFICATION_MARKET_AND_RESIDUAL_RULE'
        r['final_reconciliation']=asdict(recovery.recover())
        r['final_positions']=[asdict(p) for p in account.get_positions().values()]
        r['final_orders']=account.get_frontend_open_orders();r['account_observed_ms']=client.clock_ms()
        if r['final_positions'] or r['final_orders'] or not recovery.last_report.ready:
            r.update(status='QUALIFICATION_LOCKED',blocker='QUALIFICATION_FINAL_ACCOUNT_RECONCILIATION_REQUIRED')
        r['rates']=rates.report()
    except Exception as exc:r.update(status='QUALIFICATION_LOCKED',blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        if client:client.close()
        if journal:
            if 'recovery' in locals():recovery.checkpoint(clean=True)
            r['sqlite_integrity']=journal.db.execute('PRAGMA integrity_check').fetchone()[0]
            r['actual_action_rows']={t:journal.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('intents','api_actions','signed_management')}
            journal.close()
    r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT))
    if r['source_hash']!=r['source_hash_after']:r.update(status='QUALIFICATION_LOCKED',blocker='SOURCE_CHANGED_DURING_PREPARATION')
    atomic_json(directory/'readiness.json',r)
    atomic_json(directory/'WHITELIST_TRADE_PROOF.json',dict(report_type='WHITELIST_TRADE_PROOF',
        status='NO_ACTUAL_PRACTICE_FILL_VERIFIED',registered_wallet=TEAM,approved_api_wallet=API,
        network='testnet',dex='par',market=r.get('selected_proposal',{}).get('symbol'),exchange_order_id=None,
        fill_ids=[],executed_notional=None,timestamps_ms=[],fill_verified=False,final_flat_verified=False,
        preflight_flat_observed=not r.get('final_positions') and not r.get('final_orders') and 'final_reconciliation' in r,
        account_reconciliation=r.get('final_reconciliation'),organizer_whitelisting_confirmed=False))
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-directory',type=Path,required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--proposal-file',type=Path)
    p.add_argument('--operator-approval-file',type=Path);p.add_argument('--test-receipt',type=Path)
    a=p.parse_args();require_paper_migration()
    if not a.execute:
        if a.operator_approval_file:p.error('Prepare mode cannot consume exchange authorization')
        r=prepare(a.output_directory)
    else:
        if not all((a.proposal_file,a.operator_approval_file,a.test_receipt)):
            p.error('Exact proposal, explicit residual-risk approval and source-bound full regression required')
        a.output_directory.mkdir(parents=True,exist_ok=False);runtime=None
        try:
            proposal=QualificationProposal(**json.loads(a.proposal_file.read_text()))
            approval=QualificationApproval(**json.loads(a.operator_approval_file.read_text()))
            runtime=build_qualification(ROOT,proposal,approval,state_directory=ROOT/'runtime/testnet/anchorium-bot-1',test_receipt=a.test_receipt)
            r=runtime.run()
            atomic_json(a.output_directory/'WHITELIST_TRADE_PROOF.json',r['whitelist_trade_proof'])
        except Exception as exc:r=dict(status='QUALIFICATION_LOCKED',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
            whitelist_trade_proof=False,practice_ready=False,live_ready=False)
        finally:
            if runtime:runtime.close()
        atomic_json(a.output_directory/'execution_report.json',r)
    print(json.dumps(dict(status=r['status'],blocker=r.get('blocker'),selected_proposal_hash=r.get('selected_proposal_hash'),
        output_directory=str(a.output_directory.resolve()),actual_order_authorization_supplied=bool(a.operator_approval_file))))
    return 0 if r['status'] not in {'QUALIFICATION_LOCKED','EMERGENCY_EXIT_REQUIRED'} else 1
if __name__=='__main__':raise SystemExit(main())
