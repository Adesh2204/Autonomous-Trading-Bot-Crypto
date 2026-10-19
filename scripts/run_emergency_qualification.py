"""P0 preparation is read-only. --execute requires separate exact risk approval."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import hashlib,json,shlex,signal,sys,threading,time,sqlite3
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError,decimal
from exchange.par_retirement import reject_retired_par_write
from exchange.execution_journal import fingerprint
from exchange.paper_operations import active_source_hash,atomic_json,PaperOwner
from exchange.qualification_watcher import (ReadOnlyQualificationSession,PublicBookStream,PublicBookReader,
    OpportunityGate,source_unchanged,prior_execution_check,durable_readback)
from exchange.emergency_qualification import (EmergencyContextProvider,EmergencyProposal,EmergencyApproval,
    POLICY,BOUNDED_POLICY,FIXED_PRICE,BOUNDED_PRICE,proposal_policy,policy_hash,inspect_market,propose,
    build_runtime,RECOVERY_STEPS,require_emergency_regression)
from exchange.testnet_certification import TEAM,API
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration
from run_testnet_qualification import current_test_receipt


def approval_template(p):
    data=asdict(EmergencyApproval(proposal_hash=p.identity,operator_approval='',approved_ms=None,
        expires_ms=None,qualification_policy_hash=policy_hash(p)))
    if p.price_authorization_mode==FIXED_PRICE:data.pop('bounded_price_authorization_accepted')
    return data


def persist_price_diagnostics(directory,p):
    path=ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
    rows=[]
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            for ms,data in db.execute("SELECT timestamp_ms,data FROM events WHERE kind='P0_ENTRY_PRICE_GUARD' ORDER BY seq"):
                row=json.loads(data)
                if row.get('configuration_hash')==p.identity:rows.append(dict(event_ms=ms,**row))
    atomic_json(directory/'price_guard_diagnostics.json',dict(proposal_id=p.identity,observations=rows,
        scope='Exact persisted validation snapshots, not reconstructed market prices'))


def handoff(p,directory,receipt):
    deadline=p.observed_ms+POLICY['approval_window_ms']
    args=['.venv/bin/python','scripts/run_emergency_qualification.py','--execute',
        '--output-directory',str(directory/'authorized_attempt'),
        '--proposal-file',str(directory/'proposal.json'),
        '--operator-approval-file',str(directory/'operator_approval.json'),'--test-receipt',str(receipt)]
    qty=decimal(p.quantity);price=decimal(p.entry_limit);floor=decimal(p.exit_bound)
    fee=decimal(p.taker_fee_rate);maker=decimal(p.maker_fee_rate)
    return dict(status='AWAITING_EXACT_HUMAN_RISK_APPROVAL',proposal_id=p.identity,proposal=asdict(p),
        approval_deadline_ms=deadline,approval_deadline_ist=datetime.fromtimestamp(deadline/1000,
            timezone(timedelta(hours=5,minutes=30))).isoformat(),
        actual_entry_exposure=str(qty*price),maximum_policy_exposure='1000',
        selected_quantity_fixed=True,no_automatic_enlargement=True,entry_attempts=1,exit_attempts=2,cancel_attempts=1,
        price_authorization_mode=p.price_authorization_mode,max_buy_price=p.max_buy_price,
        quantity_ceiling=p.quantity_ceiling,entry_notional_ceiling=p.entry_notional_ceiling,
        execution_price_rule=('Fresh ask plus 10 bps, normalized down and clamped to approved BUY/notional caps; final wire must remain executable and within current 20 bps'
                              if p.price_authorization_mode==BOUNDED_PRICE else 'Exact immutable reviewed limit'),
        estimate_round_trip_taker_fee_at_limits=str(qty*(price+floor)*fee),
        estimate_resting_entry_fee_range=[str(qty*price*maker),str(qty*price*fee)],
        loss_if_fully_closed_at_floor_with_taker_fees=str(qty*(price-floor)+qty*(price+floor)*fee),
        loss_cap_guaranteed=False,protection_verified=False,no_stop_will_be_submitted=True,
        risks=['Public depth can disappear; IOC may fill zero or partly. GTC may never fill.',
            'Small protective stops remain UNVERIFIED. All exposure will be unprotected.',
            'Historical exact one-lot BTC closes do not guarantee future acceptance or liquidity.',
            'Cancellation, exits or reads can fail. Manual recovery may be needed; funding/fees and cross margin prevent a guaranteed total loss cap.',
            '30-second GTC/ALO lifetime is a local monitoring/cancel deadline, not exchange-side auto expiry.',
            'A programmatic practice fill is evidence only; organizer whitelist acceptance remains unconfirmed.'],
        required_acknowledgements=[k for k,v in approval_template(p).items() if v is False],
        approval_procedure=['Explicitly authorize this exact proposal ID and all listed risks in chat.',
            'The operator approval file must contain this exact hash/policy, the human approval text, true acknowledgements and current approved_ms/expires_ms.',
            'expires_ms must be <= approved_ms + 300000 and <= proposal observed_ms + 300000. Entry needs at least 90 seconds remaining.',
            'Preparation never fills approval or constructs an actual signer. Fixed proposals cannot reprice; bounded proposals allow only the explicitly approved fresh-price envelope. Changed source, envelope or expiry requires new approval.'],
        execute_command=shlex.join(args),recovery_steps=RECOVERY_STEPS,exchange_submissions=0,
        actual_wallet_signatures=0,actual_fill_verified=False,organizer_whitelisting_confirmed=False,
        normal_protection_certified=False,practice_ready=False,live_ready=False)


def prepare(directory,receipt=None,*,duration_seconds=60,route='auto',transport='auto',price_mode=FIXED_PRICE):
    if not 10<=duration_seconds<=300 or route not in {'auto','ioc','gtc','alo'} or transport not in {'auto','rest'}:
        raise ExchangeError('P0_INVALID_PREPARATION_ARGUMENTS')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    source=active_source_hash(ROOT)
    if price_mode not in {FIXED_PRICE,BOUNDED_PRICE}:raise ExchangeError('P0_UNKNOWN_PRICE_MODE')
    reliability=hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest()
    r=dict(status='MONITORING_READ_ONLY',source_hash=source,reliability_policy_hash=reliability,
        qualification_policy=BOUNDED_POLICY if price_mode==BOUNDED_PRICE else POLICY,
        qualification_policy_hash=fingerprint(BOUNDED_POLICY if price_mode==BOUNDED_PRICE else POLICY),execution_mode='PAPER',allow_live_orders=False,
        exchange_submissions=0,actual_wallet_signatures=0,actual_fill_verified=False,protection_verified=False,
        started_utc=datetime.now(timezone.utc).isoformat(),markets={},attempts=[],stage_a_observations=0)
    started=time.monotonic();cancel=threading.Event();session=stream=owner=None
    timer=threading.Timer(duration_seconds+180,cancel.set);timer.daemon=True;timer.start()
    handlers={}
    def progress(event,**details):
        row=dict(event=event,elapsed_seconds=round(time.monotonic()-started,3),at_ms=time.time_ns()//1000000,**details)
        with (directory/'progress.jsonl').open('a') as f:f.write(json.dumps(row,default=str)+'\n')
        if event in {'POTENTIAL_OPPORTUNITY','REFRESHING_ACCOUNT','AWAITING_EXACT_HUMAN_RISK_APPROVAL'}:
            print(json.dumps(row),flush=True)
        if cancel.is_set():raise ExchangeError('P0_PREPARATION_CANCELLED_OR_DEADLINE')
    def stop(sig,frame):cancel.set()
    try:
        require_paper_migration();r['freeze_before']=verify_strategy_freeze()
        receipt=require_emergency_regression(ROOT,current_test_receipt(receipt,source));r['test_receipt']=str(receipt)
        owner=PaperOwner(ROOT/'runtime/paper/qualification-watch.lock')
        for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,stop)
        session=ReadOnlyQualificationSession(ROOT,directory,source,reliability,progress=progress,cancel_event=cancel)
        session._provider_class=EmergencyContextProvider;session.start()
        r['metadata']={s:asdict(spec) for s,spec in session.client.markets.items()}
        r['prior_execution']=prior_execution_check(ROOT)
        # One inventory, not account history replay on each book update.
        contexts=session.market.get_asset_contexts();r['contexts_observed_ms']=session.client.clock_ms()
        r['capacity_inventory']={}
        for symbol in session.client.markets:
            active=session.account._query('activeAssetData',coin=symbol)
            r['capacity_inventory'][symbol]=dict(active=active,observed_ms=session.client.clock_ms())
        if transport=='auto':
            stream=PublicBookStream(session.client.markets,session.rates,clock_ms=session.client.clock_ms);stream.start()
        reader=PublicBookReader(session.market,stream);gate=OpportunityGate()
        if price_mode==BOUNDED_PRICE and route not in {'auto','ioc'}:raise ExchangeError('P0_BOUNDED_BTC_IOC_ONLY')
        tifs=['Ioc'] if price_mode==BOUNDED_PRICE else (['Ioc','Gtc'] if route=='auto' else [{'ioc':'Ioc','gtc':'Gtc','alo':'Alo'}[route]])
        seen={};last_source=time.monotonic()
        while time.monotonic()-started<duration_seconds and not cancel.is_set():
            if time.monotonic()-last_source>=5:
                source_unchanged(ROOT,source,reliability);last_source=time.monotonic()
            potentials=[]
            for symbol,spec in session.client.markets.items():
                if price_mode==BOUNDED_PRICE and symbol!='par:BTC':continue
                book,origin=reader.get(symbol)
                if not book or seen.get(symbol)==book.timestamp_ms:continue
                seen[symbol]=book.timestamp_ms
                for tif in tifs:
                    row=inspect_market(spec,book,session.client.clock_ms(),tif=tif,asset_context=contexts[symbol])
                    row['input_transport']=origin
                    r['markets'][symbol+':'+tif]=row;r['stage_a_observations']+=1
                    with (directory/'observations.jsonl').open('a') as f:f.write(json.dumps(row,default=str)+'\n')
                    if row['potential']:potentials.append(row)
            # Freeze exact public candidate identity before the bounded final refresh.
            potentials.sort(key=lambda x:(x['entry_tif']!='Ioc',decimal(x['minimum_entry_notional']),x['symbol']))
            for row in potentials:
                if not gate.claim(row):continue
                candidate=dict(symbol=row['symbol'],tif=row['entry_tif'],candidate_evidence_hash=row['evidence_hash'],
                    candidate_exchange_ms=row['exchange_ms'],public_candidate=row)
                r['attempts'].append(candidate)
                atomic_json(directory/('candidate_'+str(gate.attempts)+'.json'),candidate)
                progress('POTENTIAL_OPPORTUNITY',symbol=row['symbol'],entry_tif=row['entry_tif'])
                try:
                    source_unchanged(ROOT,source,reliability)
                    session.verify_signer();progress('REFRESHING_ACCOUNT',symbol=row['symbol'])
                    req=SimpleNamespace(symbol=row['symbol'],reduce_only=False)
                    session.rates.read_budget_wait_seconds=65
                    context=session.provider.load(req)
                    candidate.update(readiness=asdict(context.readiness),active_asset=context.active_asset,
                        quote=asdict(context.quote),account_ms=context.account_ms,
                        positions=[asdict(p) for p in context.positions.values()],orders=list(context.open_orders),
                        account_reconciliation=asdict(session.recovery.last_report),signer=session.identity,
                        clock=session.clock.report(),
                        checkpoint=durable_readback(directory/'read_only.sqlite',session.recovery.source))
                    p,checks=propose(context,session.client,source,reliability,session.provider.last_book,
                        tif=row['entry_tif'],candidate_hash=row['evidence_hash'],price_mode=price_mode)
                    candidate.update(proposal=asdict(p),checks=checks,eligible=True)
                    source_unchanged(ROOT,source,reliability)
                    atomic_json(directory/'proposal.json',asdict(p))
                    atomic_json(directory/'approval_REQUIRED_UNFILLED.json',approval_template(p))
                    r.update(handoff(p,directory,receipt));r['selected_candidate']=candidate
                    progress('AWAITING_EXACT_HUMAN_RISK_APPROVAL',proposal_id=p.identity)
                    break
                except ExchangeError as exc:
                    candidate.update(eligible=False,blocker=str(exc))
                    if str(exc) not in {'P0_ENTRY_DEPTH_REQUIRED','P0_EXIT_DEPTH_REQUIRED','P0_SPREAD_EXCEEDED',
                            'P0_REFERENCE_DIVERGENCE_OR_CAP','P0_APPROVED_L2_PARTICIPATION_EXCEEDED',
                            'P0_CURRENT_PRICE_OR_CAP_REQUIRED','QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL',
                            'QUALIFICATION_CLOCK_NOT_HEALTHY','QUALIFICATION_CLOCK_ACCOUNT_QUOTE_PAIR_NOT_READY'}:
                        raise
                finally:
                    session.rates.read_budget_wait_seconds=0
                    atomic_json(directory/('candidate_'+str(gate.attempts)+'.json'),candidate)
            if r.get('proposal_id'):break
            cancel.wait(.5)
        if cancel.is_set():raise ExchangeError('P0_PREPARATION_CANCELLED_OR_DEADLINE')
        if not r.get('proposal_id'):r.update(status='NO_CURRENT_QUALIFICATION_PROPOSAL',blocker='NO_SUPPORTED_CURRENT_OPPORTUNITY')
        r['rates']=session.rates.report();r['reconciliation_calls']=session.reconciliation_calls
        r['reader_errors']=reader.errors
    except Exception as exc:
        r.update(status='QUALIFICATION_LOCKED',blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__)
    finally:
        timer.cancel()
        if stream:
            try:r['stream']=stream.report();stream.close();r['stream_after_shutdown']=stream.report()
            except Exception as exc:r.update(status='QUALIFICATION_LOCKED',cleanup_error=str(exc))
        if session:
            try:session.close();r['durable_cleanup']=getattr(session,'cleanup',None)
            except Exception as exc:r.update(status='QUALIFICATION_LOCKED',cleanup_error=str(exc))
        if owner:owner.close()
        for sig,handler in handlers.items():signal.signal(sig,handler)
        try:source_unchanged(ROOT,source,reliability);r['freeze_after']=verify_strategy_freeze()
        except Exception as exc:r.update(status='QUALIFICATION_LOCKED',blocker=str(exc))
        if r['status']=='QUALIFICATION_LOCKED':
            for name in ('proposal.json','approval_REQUIRED_UNFILLED.json'):
                path=directory/name
                if path.exists():path.rename(directory/('INVALIDATED_'+name))
            r.pop('execute_command',None)
        r['qualification_state']=r['status']
        r.update(finished_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=round(time.monotonic()-started,3),
            source_hash_after=active_source_hash(ROOT),actual_order_authorization_supplied=False)
        atomic_json(directory/'readiness.json',r)
        if r.get('proposal_id'):atomic_json(directory/'operator_handoff.json',r)
    return r


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--output-directory',required=True);a.add_argument('--test-receipt')
    a.add_argument('--duration-seconds',type=int,default=60)
    a.add_argument('--route',choices=['auto','ioc','gtc','alo'],default='auto')
    a.add_argument('--transport',choices=['auto','rest'],default='auto')
    a.add_argument('--price-mode',choices=['fixed','bounded'],default='fixed')
    a.add_argument('--execute',action='store_true');a.add_argument('--proposal-file');a.add_argument('--operator-approval-file')
    args=a.parse_args()
    if args.execute: reject_retired_par_write()
    if args.execute:
        if not all((args.proposal_file,args.operator_approval_file,args.test_receipt)):
            a.error('Exact proposal, human operator approval and source-bound test receipt are required.')
        directory=Path(args.output_directory).resolve();directory.mkdir(parents=True,exist_ok=False)
        p=EmergencyProposal(**json.loads(Path(args.proposal_file).read_text()))
        approval=EmergencyApproval(**json.loads(Path(args.operator_approval_file).read_text()))
        try:runtime=build_runtime(ROOT,p,approval,test_receipt=args.test_receipt)
        except ExchangeError as exc:
            persist_price_diagnostics(directory,p)
            atomic_json(directory/'execution_report.json',dict(status='BUILD_PREFLIGHT_BLOCKED',blocker=str(exc),
                proposal_id=p.identity,entry_submission_attempted=False,actual_fill_verified=False))
            raise
        try:
            result=runtime.run();atomic_json(directory/'execution_report.json',result)
            proof=result['whitelist_trade_proof']
            atomic_json(directory/('WHITELIST_TRADE_PROOF.json' if proof.get('fill_verified') else 'NO_FILL_VERIFICATION.json'),proof)
        finally:
            runtime.close();persist_price_diagnostics(directory,p)
        print(json.dumps(result,default=str,indent=2))
        return 0 if result.get('final_flat') is True and result['status'] in {'TRADE_CLOSED_RECONCILED','NO_FILL_VERIFIED'} else 1
    if args.proposal_file or args.operator_approval_file:a.error('Preparation cannot consume an execution authorization.')
    r=prepare(args.output_directory,args.test_receipt,duration_seconds=args.duration_seconds,route=args.route,transport=args.transport,
              price_mode=BOUNDED_PRICE if args.price_mode=='bounded' else FIXED_PRICE)
    print(json.dumps({k:r.get(k) for k in ('status','blocker','proposal_id','proposal','approval_deadline_ist',
        'actual_entry_exposure','estimate_round_trip_taker_fee_at_limits','loss_if_fully_closed_at_floor_with_taker_fees',
        'execute_command','protection_verified','exchange_submissions')},indent=2))
    return 1 if r['status']=='QUALIFICATION_LOCKED' else 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except ExchangeError as exc:print(json.dumps(dict(status='QUALIFICATION_LOCKED',blocker=str(exc))));raise SystemExit(1)
