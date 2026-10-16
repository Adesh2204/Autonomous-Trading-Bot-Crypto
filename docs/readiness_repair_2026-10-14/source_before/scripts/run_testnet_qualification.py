"""Prepare-only by default. Actual qualification requires exact separate risk approval."""
import argparse,json,hashlib,sys
import time
import shlex
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from datetime import datetime,timezone
from datetime import timedelta
from types import SimpleNamespace
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor,HyperliquidRateLimitManager
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.certification_runtime import CertificationRecovery
from exchange.reliability_policy import load_reliability_policy
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.testnet_certification import TEAM,API
from exchange.testnet_qualification import (QualificationProposal,QualificationApproval,
    find_largest_safe_qualification_quantity,build_qualification,QualificationContextProvider,
    require_qualification_regression,RULE)
from exchange.testnet_qualification import residual_close_assessment
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def current_test_receipt(requested,source_hash):
    paths=[Path(requested)] if requested else sorted((ROOT/'docs').rglob('test_receipt.json'),
                                                    key=lambda p:p.stat().st_mtime,reverse=True)
    for path in paths:
        try:
            if json.loads(path.read_text()).get('source_hash')!=source_hash:continue
            return require_qualification_regression(ROOT,path)
        except (ExchangeError,OSError,ValueError,AttributeError):continue
    raise ExchangeError('SOURCE_BOUND_FULL_REGRESSION_REQUIRED')


def preflight_flat_proven(r):
    return (r.get('final_reconciliation',{}).get('ready') is True
        and 'final_positions' in r and r['final_positions']==[]
        and 'final_orders' in r and r['final_orders']==[]
        and type(r.get('account_observed_ms')) is int)



def publish_proposal(r,selected,client,directory):
    p=QualificationProposal(**selected['proposal'])
    qty=D(p.quantity);entry=D(p.entry_limit);bid=D(p.reference_bid)
    expected_exit=client.market(p.symbol).normalize_price(bid*D('.998'),'SELL')
    r.update(status='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED',selected_proposal=asdict(p),
        qualification_state='AWAITING_HUMAN_APPROVAL',
        approval_deadline_ist=datetime.fromtimestamp((p.observed_ms+300000)/1000,
            timezone(timedelta(hours=5,minutes=30))).isoformat(),
        selected_proposal_hash=p.identity,notional=str(qty*entry),
        expected_immediate_exit_limit=str(expected_exit),
        estimated_round_trip_fee_at_reviewed_limits=str(qty*(entry+expected_exit)*D(p.taker_fee_rate)),
        estimated_loss_at_reviewed_immediate_exit=str(qty*(entry-expected_exit)+qty*(entry+expected_exit)*D(p.taker_fee_rate)),
        risk_report=dict(verified=['Funded unified team account, approved agent, durable read-only reconciliation',
            'Runtime par metadata; central validation; 1x cross, margin, two-sided depth',
            'Every possible lot residual at the reviewed floor maps to ordinary or historically observed narrow closes'],
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

def clear_candidate(row):
    """A failed rereview may retain history, never a current executable candidate."""
    for key in ('proposal','proposal_hash','central_validation','residual_close_scope','sizing',
                'quote','active_asset','readiness','observed_ms','clock','spread_bps',
                'one_lot_close_assessment','external_blocker','blocker'):
        row.pop(key,None)
    row['eligible_for_risk_review']=False


def prepare(directory,test_receipt=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    r=dict(status='QUALIFICATION_LOCKED',execution_mode='PAPER',prepared_mode='TESTNET_QUALIFICATION',
        allow_live_orders=False,exchange_submissions=0,actual_wallet_signatures=0,
        source_hash=active_source_hash(ROOT),started_utc=datetime.now(timezone.utc).isoformat(),
        entry_rule=RULE,qualification_only_spread_ceiling_bps=50,normal_strategy_spread_ceiling_bps=15,
        maximum_notional='25',normal_protection_certified=False,whitelist_trade_proof=False,
        organizer_whitelisting_confirmed=False,sole_signer_host_confirmed=False,
        candidates=[],approval_requested=False,practice_ready=False,live_ready=False)
    client=journal=None
    started=time.monotonic();progress_path=directory/'progress.jsonl'
    def progress(event,**details):
        elapsed=time.monotonic()-started
        if elapsed>=240:raise ExchangeError('QUALIFICATION_PREPARATION_DEADLINE')
        if event in {'CHECKING_NETWORK','CHECKING_ACCOUNT','RECONCILING_ACCOUNT','CHECKING_RATE_BUDGET',
                     'CHECKING_BTC_BOOK','CHECKING_ETH_BOOK','CHECKING_HYPE_BOOK','VERIFYING_RESIDUAL_EXITS'}:
            r['stage']=event
        record=dict(event=event,stage=r.get('stage','PREPARATION_ONLY'),elapsed_seconds=round(elapsed,3),**details)
        r['last_progress']=record
        with progress_path.open('a') as stream:stream.write(json.dumps(record)+'\n')
        print(json.dumps(record),flush=True)
    try:
        r['safety']=require_paper_migration();r['freeze']=verify_strategy_freeze()
        r['test_receipt']=str(current_test_receipt(test_receipt,r['source_hash']))
        r['qualification_state']='PREPARATION_ONLY'
        rate,cp,protection=load_reliability_policy(ROOT/'configs/reliability_policy.json')
        if protection.enabled:raise ExchangeError('QUALIFICATION_GLOBAL_PROTECTION_MUST_REMAIN_DISABLED')
        journal=ExecutionJournal(directory/'read_only.sqlite',session_id='qualification-proposal',team_address=TEAM)
        rates=HyperliquidRateLimitManager(journal,policy=rate,signer_address=API)
        rates.read_progress=progress;rates.read_budget_wait_seconds=65
        client=HyperliquidClient(rate_limits=rates,progress=progress)
        progress('CHECKING_NETWORK');client.startup()
        progress('CHECKING_ACCOUNT')
        account,market=HyperliquidAccount(client,TEAM),HyperliquidMarketData(client)
        recovery=CertificationRecovery(account,journal,initial_start_ms=0)
        progress('RECONCILING_ACCOUNT',reason='INITIAL_ACTUAL_ACCOUNT_HISTORY')
        r['initial_reconciliation']=asdict(recovery.recover())
        if not recovery.last_report.ready or account.get_positions() or account.get_frontend_open_orders():
            raise ExchangeError('QUALIFICATION_INITIAL_RECONCILED_FLAT_REQUIRED')
        r['public_read_weight_before_reopen']=rates._usage()
        recovery.checkpoint(clean=True);journal.close()
        journal=ExecutionJournal(directory/'read_only.sqlite',session_id='qualification-proposal',team_address=TEAM)
        # Reopening the same journal must not erase this process's public read
        # weights and safety reserves. The limiter continues on the reopened DB.
        rates.journal=journal;client.rate_limits=rates
        r['public_read_weight_after_reopen']=rates._usage()
        recovery=CertificationRecovery(account,journal,initial_start_ms=0)
        progress('RECONCILING_ACCOUNT',reason='VERIFY_PERSISTENT_CHECKPOINT_AFTER_REOPEN')
        r['restored_checkpoint']=bool(recovery.saved_snapshot)
        r['reconciliation_after_reopen']=asdict(recovery.recover())
        if not r['restored_checkpoint'] or not recovery.last_report.ready:
            raise ExchangeError('QUALIFICATION_DURABLE_RECONCILIATION_REQUIRED')
        clock=ClockHealthMonitor(clock_ms=client.clock_ms,journal=journal,**cp)
        provider=QualificationContextProvider(market,account,API,clock,rates,
            reconcile_before_load=recovery.recover,progress=progress,
            reconciliation_ready=lambda:recovery.account_truth_ready,feed_ready=lambda:True)
        provider.trigger_aware=True
        policyhash=hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest()
        def review(row):
            symbol=row['symbol'];start=len(provider.observations)
            clear_candidate(row)
            try:
                progress('CHECKING_'+symbol.split(':')[1]+'_BOOK',symbol=symbol)
                progress('CHECKING_RATE_BUDGET',symbol=symbol)
                # An unsigned symbol descriptor requests actual inputs. It has
                # no fabricated quantity/price and can never be submitted.
                ctx=provider.load(SimpleNamespace(symbol=symbol,reduce_only=False))
                spec=client.market(symbol)
                row.update(quote=asdict(ctx.quote),active_asset=ctx.active_asset,readiness=asdict(ctx.readiness),
                           observed_ms=client.clock_ms(),spec=asdict(spec),clock=clock.report())
                progress('VERIFYING_RESIDUAL_EXITS',symbol=symbol)
                sizing=find_largest_safe_qualification_quantity(ctx,client,r['source_hash'],policyhash)
                row['sizing']=sizing
                if 'exit_floor' in sizing:
                    row['one_lot_close_assessment']=residual_close_assessment(spec,spec.size_step,sizing['exit_floor'])
                if sizing.get('rejection')=='QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS':
                    bounds=sizing['quantity_bounds']
                    depth=min(D(bounds['bid_depth']),D(bounds['ask_depth']))
                    non_depth=min(D(bounds[k]) for k in ('notional','account_size','margin'))
                    if depth<=non_depth:row['external_blocker']='INSUFFICIENT_REAL_LIQUIDITY'
                if not sizing['ready']:raise ExchangeError(sizing['rejection'])
                p=QualificationProposal(**sizing['proposal'])
                row.pop('blocker',None)
                row.update(eligible_for_risk_review=True,proposal=asdict(p),proposal_hash=p.identity,
                    spread_bps=str((ctx.quote.ask-ctx.quote.bid)/ctx.quote.mid*10000),
                    central_validation=sizing['central_validation'],residual_close_scope=sizing['residual_close_scope'])
                return ctx
            except Exception as exc:
                row['blocker']=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__
            finally:row['context_observations']=deepcopy(provider.observations[start:])
        for symbol in ('par:BTC','par:ETH','par:HYPE'):
            row=dict(symbol=symbol);r['candidates'].append(row);review(row)
        eligible=[row for row in r['candidates'] if row['eligible_for_risk_review']]
        selected=selected_context=None
        for row in sorted(eligible,key=lambda row:(D(row['spread_bps']),row['symbol'])):
            # Generate a new identity from genuinely reread inputs after the
            # multi-market scan, not by extending the first snapshot's expiry.
            initial=deepcopy(row);selected_context=review(row);row['initial_review']=initial
            if row['eligible_for_risk_review']:selected=row;break
        if selected is not None:
            publish_proposal(r,selected,client,directory)
        else:r['blocker']='NO_MARKET_PASSES_QUALIFICATION_MARKET_AND_RESIDUAL_RULE'
        if selected_context is not None and selected is not None:
            r['final_reconciliation']=asdict(recovery.last_report)
            r['final_positions']=[asdict(p) for p in selected_context.positions.values()]
            r['final_orders']=list(selected_context.open_orders);r['account_observed_ms']=selected_context.account_ms
        else:
            r['final_reconciliation']=asdict(recovery.recover())
            r['final_positions']=[asdict(p) for p in account.get_positions().values()]
            r['final_orders']=account.get_frontend_open_orders();r['account_observed_ms']=client.clock_ms()
        if r['final_positions'] or r['final_orders'] or not recovery.last_report.ready:
            r.update(status='QUALIFICATION_LOCKED',blocker='QUALIFICATION_FINAL_ACCOUNT_RECONCILIATION_REQUIRED')
        r['rates']=rates.report()
    except KeyboardInterrupt:r.update(status='QUALIFICATION_LOCKED',blocker='PREPARATION_INTERRUPTED',interrupted=True,
        qualification_state='PREPARATION_ONLY')
    except Exception as exc:r.update(status='QUALIFICATION_LOCKED',blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        if client:
            r['http_diagnostic']=getattr(getattr(client,'transport',None),'last_diagnostic',None)
            r['snapshot_reuse_count']=getattr(client,'snapshot_hits',0)
            transport=getattr(client,'transport',None)
            r['http_timeouts']=dict(connect_read_seconds=getattr(transport,'timeout',None),total_seconds=getattr(transport,'total_timeout',None))
            try:client.close()
            except Exception as exc:r['cleanup_error']=type(exc).__name__
        if journal:
            try:
                if 'rates' in locals():r['rates']=rates.report()
                if 'recovery' in locals():recovery.checkpoint(clean=True)
                r['sqlite_integrity']=journal.db.execute('PRAGMA integrity_check').fetchone()[0]
                r['actual_action_rows']={t:journal.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('intents','api_actions','signed_management')}
            except Exception as exc:r.update(status='QUALIFICATION_LOCKED',cleanup_error=type(exc).__name__,blocker='PREPARATION_CLEANUP_EVIDENCE_FAILED')
            finally:journal.close()
    if r.get('cleanup_error'):r.update(status='QUALIFICATION_LOCKED')
    r.update(finished_utc=datetime.now(timezone.utc).isoformat(),source_hash_after=active_source_hash(ROOT))
    if r['source_hash']!=r['source_hash_after']:r.update(status='QUALIFICATION_LOCKED',blocker='SOURCE_CHANGED_DURING_PREPARATION')
    atomic_json(directory/'readiness.json',r)
    atomic_json(directory/'WHITELIST_TRADE_PROOF.json',dict(report_type='WHITELIST_TRADE_PROOF',
        status='NO_ACTUAL_PRACTICE_FILL_VERIFIED',registered_wallet=TEAM,approved_api_wallet=API,
        network='testnet',dex='par',market=r.get('selected_proposal',{}).get('symbol'),exchange_order_id=None,
        fill_ids=[],executed_notional=None,timestamps_ms=[],fill_verified=False,final_flat_verified=False,
        preflight_flat_observed=preflight_flat_proven(r),
        account_reconciliation=r.get('final_reconciliation'),organizer_whitelisting_confirmed=False))
    print(json.dumps(dict(event='QUALIFICATION_PROPOSAL_READY' if r['status']=='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED' else 'QUALIFICATION_LOCKED',
        stage=r.get('stage'),elapsed_seconds=round(time.monotonic()-started,3),reason=r.get('blocker'))),flush=True)
    return r


def preparation_summary(r,directory,*,now_ms=None):
    directory=Path(directory).resolve()
    ready=r['status']=='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED'
    result=dict(status='QUALIFICATION_PROPOSAL_READY' if ready else r['status'],
        qualification_state='AWAITING_HUMAN_APPROVAL' if ready else 'PREPARATION_ONLY',
        actual_order_authorization_supplied=False,blocker=r.get('blocker'),
        output_directory=str(directory),test_receipt=r.get('test_receipt'),
        production_execution_mode='PAPER',allow_live_orders=False,protection_verified=False,
        next_permitted_action='Explicit exact-proposal and residual-risk approval; never execute automatically.' if ready
            else 'Resolve the recorded constraint; no exchange signature or submission permitted.')
    if ready:
        p=r['selected_proposal'];row=next(x for x in r['candidates'] if x['symbol']==p['symbol']);s=row['sizing']
        result.update(symbol=p['symbol'],direction=p['entry_side'],quantity=p['quantity'],entry_limit=p['entry_limit'],
            entry_notional=r['notional'],maximum_notional=p['max_notional'],spread_bps=row['spread_bps'],
            bid_depth_utilization=s['bid_depth_utilization'],ask_depth_utilization=s['ask_depth_utilization'],
            verified_residual_quantities=s['verified_residual_quantities'],residual_evidence_scope=row['residual_close_scope']['scope'],
            estimated_round_trip_fee=r['estimated_round_trip_fee_at_reviewed_limits'],
            reviewed_immediate_exit_limit=r['expected_immediate_exit_limit'],exit_floor=p['exit_bound'],
            proposal_id=r['selected_proposal_hash'],approval_deadline_ist=r['approval_deadline_ist'],
            proposal_file=str(directory/'proposal.json'),approval_template=str(directory/'approval_REQUIRED_UNFILLED.json'),
            entry_attempts=1,exit_attempts=p['max_exit_attempts'],maximum_signed_actions=p['max_signed_actions'],
            qualification_spread_ceiling_bps=50,production_spread_ceiling_bps=15,
            risk='No verified stop; no stop submitted. Unprotected residual/manual recovery possible. Not a guaranteed loss cap.')
        result.update(team_wallet=p['team_wallet'],api_signer=p['api_wallet'],
            operator_approval_file=str(directory/'operator_approval.json'),
            approval_copy_command=shlex.join(['cp','-n',str(directory/'approval_REQUIRED_UNFILLED.json'),
                str(directory/'operator_approval.json')]),
            execution_command=shlex.join([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_testnet_qualification.py'),
                '--execute','--output-directory',str(directory/'approved-attempt'),
                '--proposal-file',str(directory/'proposal.json'),
                '--operator-approval-file',str(directory/'operator_approval.json'),
                '--test-receipt',str(Path(r['test_receipt']).resolve())]))
        if now_ms is not None and now_ms>p['observed_ms']+300000:
            result.update(status='PROPOSAL_EXPIRED',qualification_state='PROPOSAL_EXPIRED',
                next_permitted_action='Generate a fresh read-only proposal; never authorize this expired proposal.')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-directory',type=Path,required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--proposal-file',type=Path)
    p.add_argument('--operator-approval-file',type=Path);p.add_argument('--test-receipt',type=Path)
    a=p.parse_args();require_paper_migration()
    if not a.execute:
        if a.operator_approval_file:p.error('Prepare mode cannot consume exchange authorization')
        r=prepare(a.output_directory,a.test_receipt)
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
    if not a.execute:print(json.dumps(preparation_summary(r,a.output_directory,now_ms=int(time.time()*1000)),indent=2))
    else:print(json.dumps(dict(status=r['status'],qualification_stages=r.get('qualification_stages',[]),
        blocker=r.get('blocker'),output_directory=str(a.output_directory.resolve()),
        actual_order_authorization_supplied=bool(a.operator_approval_file))))
    if r.get('interrupted'):return 130
    return 0 if r['status'] not in {'QUALIFICATION_LOCKED','EMERGENCY_EXIT_REQUIRED'} else 1
if __name__=='__main__':raise SystemExit(main())
