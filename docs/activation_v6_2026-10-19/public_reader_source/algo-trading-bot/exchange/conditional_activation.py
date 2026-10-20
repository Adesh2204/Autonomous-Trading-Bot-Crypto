"""One finite wait for already accepted PAS authority; never creates consent.

Public observation owns no signer. After it stops cleanly, the existing runtime
builder repeats every signing preflight. There is one dispatch and no restart.
"""
from pathlib import Path
import json
import os
import socket
import threading
import time

from .base_exchange import ExchangeError
from .long_session import (read_mandate, require_release, require_native_evidence,
    require_long_acceptance, sha)
from .paper_operations import active_source_hash, atomic_json
from .pas_controller import assess
from .scored_session import require_scored_evidence


class WaitingAuthority:
    def __init__(self, root, args, *, clock_ms=None):
        self.root=Path(root);self.args=args
        self.clock_ms=clock_ms or (lambda:time.time_ns()//1000000)
        self.m=read_mandate(args.mandate)
        if self.m.daily.dex!='pas' or args.venue!='pas':
            raise ExchangeError('CONDITIONAL_ACTIVATION_PAS_ONLY')
        if args.markets and set(args.markets)!=set(self.m.daily.markets):
            raise ExchangeError('CONDITIONAL_MARKETS_MUST_MATCH_ACCEPTED_MANDATE')
        require_release(self.root,args.release,self.m.daily.source_hash,self.m.release_sha256)
        if sha(args.native_protection_evidence)!=self.m.protection_evidence_sha256:
            raise ExchangeError('LONG_PROTECTION_PROOF_CHANGED')
        proof=require_native_evidence(args.native_protection_evidence,self.m.daily)
        self.bound=require_scored_evidence(self.m,Path(args.mandate).parent)
        self.bound.update({str(args.mandate):sha(args.mandate),str(args.acceptance):sha(args.acceptance),
            str(args.release):self.m.release_sha256,
            str(Path(args.release).parent/'regression.xml'):json.loads(Path(args.release).read_text())['xml_sha256'],
            str(args.native_protection_evidence):self.m.protection_evidence_sha256,
            str(Path(args.native_protection_evidence).parent/proof['receipt_file']):proof['receipt_sha256']})
        self.require()

    def require(self):
        return require_long_acceptance(self.m,self.args.acceptance,now_ms=self.clock_ms(),
            team=self.m.daily.team_wallet,signer=self.m.daily.api_wallet,
            source_hash=lambda:active_source_hash(self.root),
            policy_hash=lambda:sha(self.root/'configs/reliability_policy.json'),
            host=socket.gethostname(),bound_evidence=self.bound)

    def consume_wait(self):
        # An interrupted wait is reviewed, never silently resumed in another
        # directory/process. This is a consumption record, NOT an acceptance.
        path=Path(self.args.mandate).parent/'activation_wait_started.json'
        try:
            with path.open('x') as f:
                json.dump(dict(mandate_hash=self.m.identity,pid=os.getpid(),
                    started_ms=self.clock_ms(),expires_ms=self.m.daily.expires_ms,
                    restart_permitted=False,signing_authority='NONE'),f)
                f.flush();os.fsync(f.fileno())
        except FileExistsError:
            raise ExchangeError('CONDITIONAL_WAIT_ALREADY_CONSUMED_REVIEW_REQUIRED') from None


def readiness_to_dispatch(report, authority, now_ms):
    """All gates for the SAME accepted market scope, plus stream/account health."""
    authority.require()
    if set(report.get('markets',[]))!=set(authority.m.daily.markets):return False
    if report.get('source_hash')!=authority.m.daily.source_hash:return False
    gates=assess(report,now_ms)['gates']
    if not all(v for k,v in gates.items() if k!='EXACT_SESSION_APPROVAL_ACCEPTED'):return False
    account=report.get('account') or {}
    return (report.get('status')=='OBSERVING' and report.get('stream_connected') is True
        and report.get('stream_reconciled') is True and report.get('account_stream_healthy') is True
        and account.get('positions')==[] and account.get('open_orders')==[]
        and not account.get('reasons')
        and now_ms<authority.m.daily.expires_ms-authority.m.entry_cutoff_buffer_ms)


def wait_for_readiness(root,args,stop,publish,output,*,observe=None,authority=None):
    authority=authority or WaitingAuthority(root,args)
    authority.consume_wait()
    if observe is None:
        from .terminal_observer import observe
    local_stop=threading.Event();done=threading.Event();candidate=False
    def forward():
        while not done.wait(.1):
            if stop.is_set() or authority.clock_ms()>=authority.m.daily.expires_ms-authority.m.entry_cutoff_buffer_ms:
                local_stop.set();return
    thread=threading.Thread(target=forward,name='conditional-wait-stop',daemon=True);thread.start()
    def update(value):
        nonlocal candidate
        value=dict(value,conditional_activation_wait=True,mandate_hash=authority.m.identity,
            expires_ms=authority.m.daily.expires_ms,signing_authority='NONE',
            TRADING_AUTHORIZED=False,AUTO_TRADING_ACTIVE=False)
        # Reuse the same diagnostic Reporter enrichment before evaluating. The
        # public report itself never reports a signing capability.
        enriched=publish(value)
        try:ready=readiness_to_dispatch(enriched if isinstance(enriched,dict) else value,authority,authority.clock_ms())
        except (ExchangeError,OSError,ValueError):
            local_stop.set();return
        if ready:candidate=True;local_stop.set()
        if stop.is_set() or authority.clock_ms()>=authority.m.daily.expires_ms-authority.m.entry_cutoff_buffer_ms:
            local_stop.set()
    try:
        terminal=observe(Path(root),Path(output)/'activation_observation',local_stop,update,
            venue='pas',markets=authority.m.daily.markets,scan_seconds=args.scan_seconds)
    finally:
        done.set();local_stop.set();thread.join(2)
    atomic_json(Path(output)/'activation_observation_result.json',terminal)
    authority.require()
    # A callback may have seen a setup before cancellation. The mandatory
    # terminal readbacks and original runtime still decide actual safety.
    if (stop.is_set() or not candidate or terminal.get('status')=='HALTED'
            or terminal.get('threads_stopped') is not True or terminal.get('terminal_flat') is not True
            or terminal.get('journal_integrity')!='ok' or terminal.get('history_integrity')!='ok'
            or authority.clock_ms()>=authority.m.daily.expires_ms-authority.m.entry_cutoff_buffer_ms):
        raise ExchangeError('CONDITIONAL_ACTIVATION_STOPPED_WITHOUT_DISPATCH')
    return terminal
