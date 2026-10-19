"""Prepare one session mandate, or execute it only after genuine human acceptance.

No per-price approval is synthesized. Production remains PAPER/false. A failed
or uncertain entry is final; only pre-transmission public observation can repeat.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib, json, signal, sqlite3, sys, time, uuid, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.paper_operations import active_source_hash, atomic_json, PaperOwner
from exchange.qualification_watcher import prior_execution_check, source_unchanged
from exchange.emergency_qualification import (EmergencyProposal, BOUNDED_PRICE,
    build_runtime, require_emergency_regression, RECOVERY_STEPS)
from exchange.delegated_qualification import (SessionMandate, SessionAcceptance, Delegation,
    validate_proposal, ACKNOWLEDGMENTS, MODE, END_MS)
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration
from run_emergency_qualification import prepare, persist_price_diagnostics
from run_testnet_qualification import current_test_receipt

MARKET_BLOCKERS = {'P0_ENTRY_DEPTH_REQUIRED', 'P0_EXIT_DEPTH_REQUIRED', 'P0_SPREAD_EXCEEDED',
    'P0_REFERENCE_DIVERGENCE_OR_CAP', 'P0_APPROVED_L2_PARTICIPATION_EXCEEDED',
    'P0_CURRENT_PRICE_OR_CAP_REQUIRED', 'P0_APPROVED_ENVELOPE_OR_TIME_EXCEEDED',
    'P0_ENTRY_WINDOW_CLOSED', 'P0_MINIMUM_VALID_QUANTITY_RULE_REQUIRED',
    'QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL', 'DELEGATED_PROPOSAL_OUTSIDE_ACCEPTED_SCOPE'}


def now_ms(): return time.time_ns()//1000000


def require_release(receipt):
    require_paper_migration(); verify_strategy_freeze()
    path = require_emergency_regression(ROOT, current_test_receipt(receipt, active_source_hash(ROOT)))
    r = json.loads(path.read_text())
    if r['totals']['tests'] < 2194:
        raise ExchangeError('DELEGATED_FULL_2194_BASELINE_REQUIRED')
    return path


def session_handoff(m, receipt, directory, observation):
    return dict(status='AWAITING_EXPLICIT_SESSION_ACCEPTANCE', session_id=m.identity,
        mandate=asdict(m), scope=m.scope, expiry_ist=m.scope['end_ist'],
        entry_cutoff_ms=m.expires_ms-90000, source_hash=m.source_hash,
        test_receipt=str(receipt), test_receipt_sha256=hashlib.sha256(Path(receipt).read_bytes()).hexdigest(),
        required_acknowledgments=list(ACKNOWLEDGMENTS), protection_verified=False,
        no_stop_will_be_submitted=True, exposure_cap_is_loss_guarantee=False,
        price_updates_need_new_approval=False, scope_or_source_change_needs_new_approval=True,
        actual_wallet_signatures=0, exchange_submissions=0, actual_fill_verified=False,
        organizer_whitelisting_confirmed=False, normal_protection_certified=False,
        practice_ready=False, live_ready=False, initial_read_only_observation=observation,
        approval_procedure='Human accepts this exact session hash and all scope/risk disclosures in chat; Codex records the genuine acceptance and its current timestamp. No per-proposal human approval is invented.',
        execute_args=['.venv/bin/python','scripts/run_delegated_qualification.py','--execute',
            '--output-directory',str(directory/'authorized_session'), '--mandate-file',str(directory/'session_mandate.json'),
            '--session-acceptance-file',str(directory/'session_acceptance.json'),'--test-receipt',str(receipt),'--persistent'],
        recovery_steps=RECOVERY_STEPS)


def prepare_session(directory, receipt=None):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    receipt = require_release(receipt)
    mandate = SessionMandate(uuid.uuid4().hex, now_ms(), active_source_hash(ROOT),
        hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest()).require()
    state=ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
    if state.exists():
        with sqlite3.connect(state.as_uri()+'?mode=ro',uri=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='nontransmission_resolutions'").fetchone():
                from dataclasses import replace
                from exchange.qualification_intent_recovery import effective_rows
                effective_rows(db)
                value=db.execute('SELECT checksum FROM nontransmission_resolutions LIMIT 1').fetchone()
                if value:mandate=replace(mandate,recovery_resolution_hash=value[0]).require()
    atomic_json(directory/'session_mandate.json', asdict(mandate))
    atomic_json(directory/'session_acceptance_REQUIRED_UNFILLED.json', asdict(
        SessionAcceptance(mandate.identity, '', None, None)))
    observation = prepare(directory/'initial_read_only', receipt, duration_seconds=60,
        route='ioc', transport='rest', price_mode=BOUNDED_PRICE)
    # This is only a current example. Its short-lived price approval is unused;
    # future fresh envelopes will instead be validated against the session.
    if observation.get('proposal'):
        try: validate_proposal(mandate, EmergencyProposal(**observation['proposal']))
        except ExchangeError as exc: observation['delegated_scope_blocker'] = str(exc)
    handoff = session_handoff(mandate, receipt, directory, observation)
    if observation['status'] == 'QUALIFICATION_LOCKED' and observation.get('blocker') not in MARKET_BLOCKERS:
        handoff.update(status='SESSION_PREPARATION_BLOCKED', blocker=observation.get('blocker'))
    source_unchanged(ROOT, mandate.source_hash, mandate.reliability_policy_hash)
    atomic_json(directory/'session_handoff.json', handoff)
    return handoff


def require_unused_runtime(mandate):
    prior_execution_check(ROOT)
    path = ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite'
    if not path.exists(): return
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        controls = {n:json.loads(v) for n,v in db.execute('SELECT name,value FROM controls')
            if n.startswith('delegated_')}
        previous=controls.get('delegated_session_active')
        prior_ok=False
        if previous not in {None,mandate.identity}:
            from exchange.qualification_intent_recovery import prior_session_resolved
            if prior_session_resolved(db,previous):
                row=db.execute('SELECT checksum FROM nontransmission_resolutions LIMIT 1').fetchone()
                prior_ok=row is not None and row[0]==mandate.recovery_resolution_hash
    if (previous not in {None, mandate.identity} and not prior_ok
            or any(controls.get(k+mandate.identity) for k in
                ('delegated_runtime:', 'delegated_session_finished:', 'delegated_session_revoked:'))):
        raise ExchangeError('DELEGATED_EXISTING_RUNTIME_READ_ONLY_RECOVERY_REQUIRED')


def execute_session(directory, delegation, receipt):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    result = dict(status='READ_ONLY_OBSERVATION', mode=MODE, session_id=delegation.mandate.identity,
        actual_fill_verified=False, organizer_whitelisting_confirmed=False,
        protection_verified=False, production_mode='PAPER', allow_live_orders=False,
        observations=[], authorized_entry_attempted=False)
    owner = runtime = None; old_handlers = {}
    def stopped(signum, frame):
        atomic_json(Path(delegation.acceptance_path).with_name('session_revocation.json'),
            dict(session_id=delegation.mandate.identity, revoked_ms=now_ms(), reason='OPERATOR_PROCESS_SIGNAL'))
        raise ExchangeError('DELEGATED_SESSION_REVOKED')
    try:
        # Acceptance is checked before any actual-key runtime is constructed.
        delegation.require(now_ms()); receipt = require_release(receipt)
        source_unchanged(ROOT, delegation.mandate.source_hash, delegation.mandate.reliability_policy_hash)
        require_unused_runtime(delegation.mandate)
        owner = PaperOwner(ROOT/'runtime/testnet/anchorium-bot-1/delegated-session.lock')
        for signum in (signal.SIGINT, signal.SIGTERM): old_handlers[signum] = signal.signal(signum, stopped)
        index = 0
        while True:
            delegation.require(now_ms())
            if now_ms()+90000 >= delegation.mandate.expires_ms:
                result['status']='SESSION_ENTRY_WINDOW_CLOSED_NO_SUBMISSION'; break
            source_unchanged(ROOT, delegation.mandate.source_hash, delegation.mandate.reliability_policy_hash)
            require_unused_runtime(delegation.mandate)
            index += 1
            observed = prepare(directory/('observation_'+str(index)), receipt,
                duration_seconds=60, route='ioc', transport='rest', price_mode=BOUNDED_PRICE)
            result['observations'].append(dict(directory='observation_'+str(index),
                status=observed['status'], blocker=observed.get('blocker'), at_ms=now_ms()))
            atomic_json(directory/'session_report.json', result)
            delegation.require(now_ms())
            if observed.get('source_hash_after') != delegation.mandate.source_hash:
                raise ExchangeError('QUALIFICATION_SOURCE_CHANGED')
            if observed['status']=='QUALIFICATION_LOCKED' and observed.get('blocker') not in MARKET_BLOCKERS:
                raise ExchangeError(observed.get('blocker') or 'DELEGATED_READINESS_FAILED')
            if not observed.get('proposal') or observed['status']=='QUALIFICATION_LOCKED':
                time.sleep(1); continue
            p = EmergencyProposal(**observed['proposal'])
            try:
                validate_proposal(delegation.mandate, p)
                runtime = build_runtime(ROOT, p, None, test_receipt=receipt, delegation=delegation)
            except ExchangeError as exc:
                persist_price_diagnostics(directory, p)
                require_unused_runtime(delegation.mandate)
                if str(exc) not in MARKET_BLOCKERS: raise
                result['observations'][-1]['final_preflight_blocker']=str(exc)
                time.sleep(1); continue
            # This consumes the entire one-off workflow, whatever its outcome.
            # Any local durable intent or uncertainty ends observation/repricing.
            result['authorized_entry_attempted']=True
            actual = runtime.run()
            result.update(status=actual['status'], execution=actual, proposal_id=p.identity,
                actual_fill_verified=actual['whitelist_trade_proof']['fill_verified'],
                final_flat_verified=actual['whitelist_trade_proof']['final_flat_verified'])
            proof = dict(actual['whitelist_trade_proof'], delegated_session_id=delegation.mandate.identity,
                session_acceptance_hash=hashlib.sha256(Path(delegation.acceptance_path).read_bytes()).hexdigest())
            atomic_json(directory/('WHITELIST_TRADE_PROOF.json' if proof['fill_verified'] else 'NO_FILL_VERIFICATION.json'), proof)
            runtime.close(); runtime=None
            persist_price_diagnostics(directory, p)
            break
    except Exception as exc:
        result.update(status='SESSION_HALTED', blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
            recovery_steps=RECOVERY_STEPS)
        # A failure after any attempt is unresolved until exchange reconciliation.
        if result['authorized_entry_attempted']:
            try: prior_execution_check(ROOT)
            except ExchangeError:
                result.update(status='EMERGENCY_EXIT_REQUIRED', operator_action_required=True)
    finally:
        if runtime:
            try: runtime.close()
            except Exception as exc: result['cleanup_error']=type(exc).__name__
        if owner: owner.close()
        for signum, handler in old_handlers.items(): signal.signal(signum, handler)
        result.update(finished_ms=now_ms(), practice_ready=False, live_ready=False,
            no_automatic_entry_retry=True, source_hash_after=active_source_hash(ROOT))
        atomic_json(directory/'session_report.json', result)
    return result


def execute_persistent_session(directory,delegation,receipt):
    from exchange.persistent_qualification_watcher import PersistentQualificationObserver
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    observer_dir=directory/'persistent_observer'
    prior=observer_dir/'health.json'
    read_only_restart=prior.exists() and json.loads(prior.read_text()).get('status')!='READ_ONLY_STOPPED'
    result=dict(status='READ_ONLY_OBSERVATION',mode=MODE,session_id=delegation.mandate.identity,
        actual_fill_verified=False,organizer_whitelisting_confirmed=False,protection_verified=False,
        production_mode='PAPER',allow_live_orders=False,authorized_entry_attempted=False,
        restart_is_read_only=read_only_restart,observations=[])
    watcher=runtime=owner=None;handlers={};cancel=threading.Event()
    def stopped(sig,frame):
        cancel.set()
        atomic_json(Path(delegation.acceptance_path).with_name('session_revocation.json'),
            dict(session_id=delegation.mandate.identity,revoked_ms=now_ms(),reason='OPERATOR_PROCESS_SIGNAL'))
        raise ExchangeError('DELEGATED_SESSION_REVOKED')
    try:
        delegation.require(now_ms());receipt=require_release(receipt)
        source_unchanged(ROOT,delegation.mandate.source_hash,delegation.mandate.reliability_policy_hash)
        require_unused_runtime(delegation.mandate)
        owner=PaperOwner(ROOT/'runtime/testnet/anchorium-bot-1/delegated-session.lock')
        for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,stopped)
        watcher=PersistentQualificationObserver(ROOT,observer_dir,delegation.mandate.source_hash,
            delegation.mandate.reliability_policy_hash,mandate=delegation.mandate,cancel=cancel)
        watcher.start()
        while True:
            delegation.require(now_ms());require_unused_runtime(delegation.mandate)
            if now_ms()+90000>=delegation.mandate.expires_ms:
                result['status']='SESSION_ENTRY_WINDOW_CLOSED_NO_SUBMISSION';break
            try:p=watcher.poll()
            except ExchangeError as exc:
                if str(exc) not in MARKET_BLOCKERS:raise
                watcher.progress('READ_ONLY_MARKET_INELIGIBLE',blocker=str(exc));p=None
            atomic_json(directory/'session_report.json',result)
            if p is None or read_only_restart:
                cancel.wait(.5);continue
            atomic_json(directory/'selected_proposal.json',asdict(p))
            shared_rates=watcher.pause_for_execution()
            try:
                runtime=build_runtime(ROOT,p,None,test_receipt=receipt,delegation=delegation,
                    nonce_owner=watcher.nonce_owner(),rate_owner=shared_rates)
            except ExchangeError as exc:
                persist_price_diagnostics(directory,p);require_unused_runtime(delegation.mandate)
                # This can repeat only if no durable runtime/intent/nonce
                # attempt was armed. The exact existing lease must still live.
                if str(exc) not in MARKET_BLOCKERS:raise
                watcher.nonce_owner()
                watcher.status='READ_ONLY_OBSERVATION'
                watcher.progress('READ_ONLY_FINAL_PREFLIGHT_INELIGIBLE',blocker=str(exc));continue
            result['authorized_entry_attempted']=True
            actual=runtime.run();proof=actual['whitelist_trade_proof']
            result.update(status=actual['status'],execution=actual,proposal_id=p.identity,
                actual_fill_verified=proof['fill_verified'],final_flat_verified=proof['final_flat_verified'])
            atomic_json(directory/('WHITELIST_TRADE_PROOF.json' if proof['fill_verified'] else 'NO_FILL_VERIFICATION.json'),
                dict(proof,delegated_session_id=delegation.mandate.identity))
            runtime.close();runtime=None;persist_price_diagnostics(directory,p);break
    except Exception as exc:
        result.update(status='SESSION_HALTED',blocker=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,recovery_steps=RECOVERY_STEPS)
        if result['authorized_entry_attempted']:
            try:prior_execution_check(ROOT)
            except ExchangeError:result.update(status='EMERGENCY_EXIT_REQUIRED',operator_action_required=True)
    finally:
        if runtime:
            try:runtime.close()
            except Exception as exc:result['runtime_cleanup_error']=type(exc).__name__
        if watcher:
            try:watcher.close();result['watcher_health']=json.loads((observer_dir/'health.json').read_text())
            except Exception as exc:result['watcher_cleanup_error']=type(exc).__name__
        if owner:owner.close()
        for sig,h in handlers.items():signal.signal(sig,h)
        result.update(finished_ms=now_ms(),no_automatic_entry_retry=True,practice_ready=False,live_ready=False,
            source_hash_after=active_source_hash(ROOT))
        atomic_json(directory/'session_report.json',result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory'); parser.add_argument('--test-receipt')
    parser.add_argument('--execute', action='store_true'); parser.add_argument('--revoke', action='store_true')
    parser.add_argument('--persistent',action='store_true')
    parser.add_argument('--observe-only-seconds',type=int)
    parser.add_argument('--mandate-file'); parser.add_argument('--session-acceptance-file')
    args = parser.parse_args()
    if args.observe_only_seconds is not None:
        if args.execute or args.revoke or args.mandate_file or args.session_acceptance_file or not args.output_directory:
            parser.error('Engineering observation forbids execution/acceptance and requires an output directory.')
        from exchange.persistent_qualification_watcher import read_only_soak
        receipt=require_release(args.test_receipt)
        result=read_only_soak(ROOT,args.output_directory,duration_seconds=args.observe_only_seconds)
        print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
    if args.revoke:
        if args.execute or not args.mandate_file or not args.session_acceptance_file:
            parser.error('Revocation requires mandate/acceptance paths and forbids execution.')
        m = SessionMandate(**json.loads(Path(args.mandate_file).read_text())).require()
        path=Path(args.session_acceptance_file).with_name('session_revocation.json')
        atomic_json(path, dict(session_id=m.identity, revoked_ms=now_ms(), reason='OPERATOR_REVOCATION'))
        print(json.dumps(dict(status='SESSION_REVOKED', exchange_submissions=0))); return 0
    if not args.output_directory: parser.error('An evidence output directory is required.')
    if args.execute:
        if not all((args.mandate_file,args.session_acceptance_file,args.test_receipt)):
            parser.error('Genuine session acceptance, mandate and source-bound regression receipt required.')
        m=SessionMandate(**json.loads(Path(args.mandate_file).read_text()))
        acceptance=SessionAcceptance(**json.loads(Path(args.session_acceptance_file).read_text()))
        delegation=Delegation(m,acceptance,str(Path(args.session_acceptance_file).resolve()))
        result=(execute_persistent_session if args.persistent else execute_session)(args.output_directory,delegation,args.test_receipt)
    else:
        if args.mandate_file or args.session_acceptance_file: parser.error('Read-only preparation cannot consume acceptance.')
        result=prepare_session(args.output_directory,args.test_receipt)
    print(json.dumps({k:result.get(k) for k in ('status','blocker','session_id','scope','expiry_ist',
        'actual_fill_verified','final_flat_verified','protection_verified')},indent=2))
    return 1 if result['status'] in {'SESSION_HALTED','SESSION_PREPARATION_BLOCKED','EMERGENCY_EXIT_REQUIRED'} else 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except ExchangeError as exc:
        print(json.dumps(dict(status='SESSION_LOCKED',blocker=str(exc)))); raise SystemExit(1)
