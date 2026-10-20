"""Unsigned PAS operator operations plus explicitly invoked config-only workflow."""
from pathlib import Path
import json,threading,time
from .paper_operations import atomic_json,active_source_hash
from .testnet_certification import TEAM


def funding_snapshot(root,output):
    from .public_quant_operator import SerializedPublicClient,ReadOnlyReceipts
    from .hyperliquid_client import RequestsInfoTransport
    from .hyperliquid_account import HyperliquidAccount
    from .execution_journal import ExecutionJournal
    from .rate_limits import HyperliquidRateLimitManager
    from .pas_funding import read_funding
    p=Path(output);p.mkdir(parents=True,exist_ok=False)
    j=ExecutionJournal(p/'public.sqlite',session_id='pas-funding-read',team_address=TEAM)
    rates=HyperliquidRateLimitManager(j);rates.read_budget_wait_seconds=65;rates.read_deadline_seconds=75
    c=SerializedPublicClient(ReadOnlyReceipts(RequestsInfoTransport(),p/'info_receipts.jsonl'),rate_limits=rates,venue='pas')
    stop=threading.Event();timer=threading.Timer(180,stop.set);c.read_cancel_event=stop;timer.start()
    try:
        c.startup();v=read_funding(c,HyperliquidAccount(c,TEAM),provenance=str(p/'info_receipts.jsonl'))
        v.update(source_hash=active_source_hash(root),journal_integrity=j.db.execute('pragma integrity_check').fetchone()[0])
        atomic_json(p/'funding_evidence.json',v);return v
    finally:timer.cancel();c.close();j.close()


def dispatch(root,args):
    from .terminal_app import validate_safe
    validate_safe('pas')
    if args.command=='trading-isolation-prepare':
        from .trading_isolation import collect
        return collect(root,args.output,minutes=args.minutes)
    if args.command=='trading-isolation-approve':
        from .trading_isolation import approve
        return approve(root,args.policy,args.mandate,args.release)
    if args.command=='pas-ranking':
        from .pas_opportunity_ranking import collect
        return collect(root,args.output)
    if args.command=='trading-isolation-review':
        from .trading_isolation_review import collect
        return collect(root,args.output,minutes=args.minutes)
    if args.command=='history-review':
        from .pas_history_review import review_history
        return review_history(root,args.output)
    if args.command=='funding':return funding_snapshot(root,args.output)
    if args.command=='configuration-review':
        from .venue_discovery import discover
        isolation=None
        if getattr(args,'isolate_original_for_configuration',False):
            from .configuration_isolation import collect
            output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
            isolation=collect(root,output/'configuration_isolation')
            d=discover(root,output/'fresh_discovery',venue='pas')
        else:d=discover(root,args.output,venue='pas')
        if getattr(args,'operator_confirmation',None):
            from .operator_account_confirmation import copy_confirmation
            from .team_registration import registration_evidence
            copy_confirmation(args.operator_confirmation,Path(args.output))
            d['registration_evidence']=registration_evidence(args.output,time.time_ns()//1000000,scope='CONFIGURATION_ONLY')
        if isolation is not None:d['configuration_isolation']=isolation
        if getattr(args,'organizer_confirmation',None):
            from .scored_prepare import copy_organizer_record
            from .team_registration import registration_evidence
            from .pas_configuration_plan import configuration_plan
            copy_organizer_record(args.organizer_confirmation,Path(args.output))
            d.pop('configuration_plan',None)
            d['registration_evidence']=registration_evidence(args.output,time.time_ns()//1000000,scope='CONFIGURATION_ONLY')
            d['configuration_plan']=configuration_plan(d)
            atomic_json(Path(args.output)/'discovery.json',d)
            atomic_json(Path(args.output)/'account_configuration_plan.json',d['configuration_plan'])
        if isolation is not None or getattr(args,'operator_confirmation',None):
            from .pas_configuration_plan import configuration_plan
            d.pop('configuration_plan',None);d['configuration_plan']=configuration_plan(d)
            atomic_json(Path(args.output)/'discovery.json',d)
            atomic_json(Path(args.output)/'account_configuration_plan.json',d['configuration_plan'])
        return d
    if args.command=='configuration-approve':
        from .pas_configuration import approve_configuration
        return approve_configuration(root,args.plan,args.discovery,args.release,args.output)
    if args.command=='configuration-apply':
        from .pas_configuration import execute_configuration
        return execute_configuration(root,args.plan,args.discovery,args.release,args.acceptance,args.output)
    if args.command=='native-prepare':
        from .pas_native_plan import prepare_native_test
        from .venue_discovery import discover
        p=Path(args.output);p.mkdir(parents=True,exist_ok=False)
        d=discover(root,p/'fresh_discovery',venue='pas',final_market=args.market)
        v=prepare_native_test(d,active_source_hash(root),time.time_ns()//1000000,symbol=args.market)
        atomic_json(p/'qualification_proposal.json',v);return v
    raise ValueError('UNKNOWN_PAS_OPERATION')
