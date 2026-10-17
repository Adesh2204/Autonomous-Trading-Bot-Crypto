"""Local deterministic operator application. No Codex or paid model runtime."""
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import resource
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

from .base_exchange import ExchangeError
from .paper_operations import PaperOwner, active_source_hash, atomic_json
from .testnet_certification import TEAM, API


def read_json(path):
    for attempt in range(4):
        try:return json.loads(Path(path).read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            if attempt == 3:raise
            time.sleep(.05)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as f:
        try:fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def validate_safe():
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    require_paper_migration();verify_strategy_freeze()


class Reporter:
    def __init__(self, root, state, output, session):
        self.root, self.state, self.output, self.session = root, state, output, session
        self.previous = None;self.last_event = 0;self.event_rotations = 0
        self.started = time.time_ns()//1000000

    def __call__(self, value):
        now = time.time_ns()//1000000
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024*1024 if sys.platform=='darwin' else 1024)
        value = dict(value, updated_ms=now, started_ms=self.started, session_id=self.session, pid=os.getpid(),
            local_time=datetime.now().astimezone().isoformat(), execution_mode='PAPER', allow_live_orders=False,
            rss_high_watermark_mb=rss, strategy='HASH_VERIFIED_FROZEN_UTC_VWAP',
            local_dependency='This Mac, Python process, power and internet. Codex and its app may be closed.',
            log_retention='Eight 16 MB receipt archives plus current; four 8 MB event archives plus current. Reports retain final truth; old receipts can expire.')
        if value.get('account_observed_ms') is not None:value['account_age_ms']=now-value['account_observed_ms']
        if value.get('fees_observed_ms') is not None:value['fee_age_ms']=now-value['fees_observed_ms']
        if rss >= 2048:raise ExchangeError('TERMINAL_MEMORY_LIMIT')
        disk=shutil.disk_usage(self.output)
        if disk.free/disk.total<.1:raise ExchangeError('TERMINAL_DISK_RESERVE_LIMIT')
        if any(p.stat().st_size>512_000_000 for p in self.output.glob('*.sqlite*')):
            raise ExchangeError('TERMINAL_DATABASE_STORAGE_LIMIT_REQUIRES_ARCHIVE')
        atomic_json(self.output/'status.json', value)
        atomic_json(self.state/'current.json', dict(session_id=self.session, output=str(self.output), pid=os.getpid(), updated_ms=now))
        key = json.dumps([value.get('mode'), value.get('status'), value.get('error'),
            [(r['symbol'], r['decision'], r.get('reasons')) for r in value.get('signals', [])],
            value.get('account', {}).get('positions'), value.get('account', {}).get('open_orders'),
            value.get('daily_lifecycle')], default=str, sort_keys=True)
        complete_scan=not value.get('markets') or len(value.get('signals',[]))==len(value['markets'])
        if complete_scan and (key != self.previous or now-self.last_event >= 30000):
            path = self.output/'events.jsonl'
            if path.exists() and path.stat().st_size >= 8_000_000:
                path.with_name('events.jsonl.4').unlink(missing_ok=True)
                for i in range(3,0,-1):
                    p = path.with_name(f'events.jsonl.{i}')
                    if p.exists():p.replace(path.with_name(f'events.jsonl.{i+1}'))
                path.replace(path.with_name('events.jsonl.1'));self.event_rotations += 1
            with path.open('a') as f:
                f.write(json.dumps(value, default=str)+'\n');f.flush();os.fsync(f.fileno())
            if key != self.previous:print(render(value), flush=True)
            self.previous, self.last_event = key, now
        (self.output/'report.md').write_text(render(value)+'\n')
        return value


def render(v):
    account = v.get('account') or {}
    eq = account.get('reported_account_equity') or {}
    realized = account.get('realized') or {}
    lines = ['TEAM ANCHORIUM — QUANT ENGINE', f"MODE: {v.get('mode')} | STATUS: {v.get('status')}",
        f"TESTNET par | Team: {v.get('team_wallet',TEAM)}", f"Source: {v.get('source_hash')}",
        f"Local: {v.get('local_time')} | Exchange time: {v.get('exchange_time_ms')} (null means unavailable)",
        f"Actual collateral: {eq.get('collateral_balance')} | Available/withdrawable: {eq.get('withdrawable')}",
        f"Proposed bankroll: 20000 | Approved bankroll: {v.get('approved_bankroll')} | Approved notional: {v.get('approved_maximum_notional')}",
        f"Positions: {account.get('positions','UNKNOWN')} | Open orders: {account.get('open_orders','UNKNOWN')}",
        f"Observed account net: {realized.get('net_after_fees_and_funding')} | Fees: {realized.get('actual_fill_fees')} | Funding: {realized.get('actual_funding_cashflow')}",
        f"Account age ms: {v.get('account_age_ms')} | Fee age ms: {v.get('fee_age_ms')}",
        f"Market WS: {v.get('stream_connected')} | Account WS: {v.get('account_stream_healthy')} | Authority: {v.get('signing_authority')}",
        f"Risk/remaining attempts: {v.get('risk_remaining')} / {v.get('remaining_attempts')} | Residual: {v.get('residual_status','UNKNOWN')}"]
    if v.get('expires_ms'):
        lines.append(f"Signing hard expiry ms: {v['expires_ms']} | Entry cutoff ms: {v.get('entry_cutoff_ms')} | Scheduled risk close ms: {v.get('scheduled_risk_close_ms')} | Midnight: {v.get('midnight_policy','SINGLE_DAY')}")
    if v.get('protection_statuses'):lines.append('NATIVE PROTECTION: '+json.dumps(v['protection_statuses'],default=str))
    for r in v.get('signals', []):
        c = v.get('liquidity', {}).get(r['symbol'], {})
        lines.append(f"[{r['decision']}] {r['symbol']} | {', '.join(r.get('reasons',[]))} | bid/ask {c.get('bid')}/{c.get('ask')} | capacity {c.get('notional')} | SL/TP {r.get('baseline_stop')}/{r.get('baseline_target')} | approved size {r.get('approved_quantity')}")
    if v.get('error'):lines.append('ERROR: '+v['error'])
    for order in v.get('owned_order_statuses',[]):
        lines.append(f"[ORDER_{order['state']}] {order['side']} {order['symbol']} | oid {order['oid']} | quantity {order['quantity']}")
    for fill in account.get('fills',[]):
        lines.append(f"[EXCHANGE_FILL] {fill.get('side')} {fill.get('symbol')} | oid {fill.get('order_id')} | quantity {fill.get('quantity')} | price {fill.get('price')} | fee {fill.get('fee')}")
    lines += [f"Terminal flat: {v.get('terminal_flat','UNKNOWN')} | Simulated net: {v.get('simulated_net','N/A')}",
        'Actual account events and synthetic results are separate. No native stop or SHORT qualification is implied.',
        v.get('local_dependency','Local Mac, Python, power and internet are required.')]
    return '\n'.join(lines)


def doctor(root, online=False):
    validate_safe()
    dependencies = {}
    for line in (root/'algo-trading-bot/requirements.txt').read_text().splitlines():
        if '==' not in line:continue
        name, expected = line.split('==')
        try:actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:actual = None
        dependencies[name] = dict(expected=expected, actual=actual, matching=actual==expected)
    result = dict(status='SAFE_LOCAL_CHECKS', source_hash=active_source_hash(root), dependencies=dependencies,
        execution_mode='PAPER', allow_live_orders=False, signing_authority='NONE',
        native_protection='BLOCKED_REQUIRES_ACTUAL_QUALIFICATION', short='DISABLED',
        llm_runtime_dependencies=[], llm_api_calls=0, exchange_time_ms=None,
        team_wallet=TEAM, api_wallet=API, observer_requires_codex=False)
    from .overnight_session import OVERNIGHT_MAX_EXPIRY_MS
    result['overnight_contract']=dict(implemented=True,requires_new_exact_approval=True,
        hard_expiry_ms=OVERNIGHT_MAX_EXPIRY_MS,midnight_counters_reset=False)
    if online:
        from .hyperliquid_client import HyperliquidClient
        client = HyperliquidClient()
        try:client.startup();result.update(exchange_connectivity='PUBLIC_METADATA_CONFIRMED', markets=sorted(client.markets))
        finally:client.close()
    print(json.dumps(result, indent=2));return 0 if all(x['matching'] for x in dependencies.values()) else 1


def prepare(root, args):
    """Fresh public proposal, never an acceptance or signing capability."""
    from .terminal_observer import observe
    output = Path(args.output).resolve();output.mkdir(parents=True, exist_ok=False)
    report = observe(root, output, threading.Event(), lambda v:atomic_json(output/'snapshot.json', v),
        markets=args.markets, once=True)
    now = time.time_ns()//1000000
    end_day = datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta')).replace(hour=23,minute=57,second=0,microsecond=0)
    overnight=getattr(args,'overnight',False)
    if overnight:
        from .overnight_session import OVERNIGHT_MAX_EXPIRY_MS
        if datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta')).date().isoformat()!='2026-10-16':
            raise ExchangeError('OVERNIGHT_OCT16_APPROVAL_DATE_REQUIRED_NO_AUTOMATIC_ROLLOVER')
        expires=OVERNIGHT_MAX_EXPIRY_MS
    else:expires = min(now+args.minutes*60000, int(end_day.timestamp()*1000))
    blockers = ['ACTUAL_NATIVE_TRIGGER_PROTECTION_NOT_QUALIFIED', 'NEW_EXACT_HUMAN_APPROVAL_REQUIRED']
    if report.get('error') or not report.get('terminal_flat'):blockers.append('FRESH_ACCOUNT_OR_MARKET_AUDIT_FAILED')
    eligible = [s for s,c in report.get('liquidity', {}).items() if c['partial_protection_qualified']]
    if not eligible:blockers.append('SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED')
    proposal = dict(status='BLOCKED_NOT_AUTHORIZATION', created_ms=now, approval_deadline_ms=now+300000,
        expires_ms=expires, source_hash=active_source_hash(root), bankroll='20000', maximum_notional=args.maximum_notional,
        team_wallet=TEAM,api_wallet=API,signing_host=socket.gethostname(),network='testnet',dex='par',
        maximum_entry_attempts=2, maximum_concurrent_positions=1, daily_loss_fraction='.01', risk_fraction='.005', leverage=1,
        long_only=True, depth_participation='.1', execution_slippage_bps='5', maximum_spread_bps='15',
        loss_making_risk_exits_required=True, snapshot_sha256=sha(output/'snapshot.json'), blockers=blockers,
        minimum_compliant_partial_markets=eligible, approval_granted=False,
        note='Proposal only. No executable mandate or acceptance is generated while mandatory protection evidence is missing.')
    if overnight:
        proposal.update(contract='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1',starts_ms=now,
            session_loss_fraction='.01',midnight_policy='CARRY_ALL_ATTEMPTS_ALLOCATION_PNL_PEAK_DRAWDOWN_NO_RESET',
            entry_cutoff_ms=expires-900000,scheduled_risk_close_ms=expires-300000,
            signing_hard_expiry_ms=expires,maximum_cumulative_allocation=str(D(args.maximum_notional)*2),
            maximum_signed_actions=12,maximum_owned_cancellations=2,allow_loss_making_risk_exits=True,
            management_and_owned_recovery_expiry_ms=expires,after_expiry='READ_ONLY_NO_RENEWAL_NO_NEW_SIGNATURES')
    # A real executable mandate is generated only when every evidence gate passes.
    if args.native_protection_evidence and args.release and eligible and report.get('terminal_flat') and not report.get('error'):
        from .long_session import LongMandate, require_native_evidence, require_release
        from .bounded_daily_session import DailyMandate
        from .reliability_policy import load_reliability_policy
        from .execution_journal import fingerprint
        limits_type,mandate_type=DailyMandate,LongMandate
        if overnight:
            from .overnight_session import OvernightLimits,OvernightLongMandate
            limits_type,mandate_type=OvernightLimits,OvernightLongMandate
        d = limits_type('terminal:'+uuid.uuid4().hex, TEAM, API, tuple(eligible), ('LONG',), now, expires,
            active_source_hash(root), socket.gethostname(), '20000', args.maximum_notional,
            args.maximum_notional, str(D(args.maximum_notional)*2))
        require_release(root,args.release,d.source_hash,sha(args.release));require_native_evidence(args.native_protection_evidence,d)
        _,_,policy = load_reliability_policy(root/'configs/reliability_policy.json')
        m = mandate_type(d, now, now+300000, sha(args.release),sha(root/'configs/reliability_policy.json'),
            sha(args.native_protection_evidence),fingerprint(asdict(replace(policy,enabled=True)))).require()
        atomic_json(output/'mandate.json', asdict(m))
        proposal.update(status='EXACT_MANDATE_AWAITING_HUMAN_APPROVAL', mandate_hash=m.identity,
            blockers=['NEW_EXACT_HUMAN_APPROVAL_REQUIRED'])
    from .execution_journal import fingerprint
    proposal['proposal_hash']=fingerprint(proposal)
    atomic_json(output/'proposal.json', proposal);print(json.dumps(proposal, indent=2));return 0


def run_authorized(root, args, stop, publish):
    from .long_session import build_long_runtime, read_mandate
    from market_regime_scanner import ScannerPolicy
    from risk.models import RiskPolicy
    m = read_mandate(args.mandate)
    scanner = ScannerPolicy(D('.004'), D(m.maximum_spread_bps), D(0), D(10), history_bars=300, top_n=3)
    risk = RiskPolicy(D(m.daily.risk_fraction), D(m.daily.daily_loss_fraction),D(1),D('.5'),D(2),D('.001'),D(50),
        D(m.maximum_spread_bps),D(m.depth_participation),D(m.execution_slippage_bps),D(1),1)
    runtime = build_long_runtime(root,args.mandate,args.acceptance,args.release,args.native_protection_evidence,
        scanner_policy=scanner,risk_policy=risk)
    runtime.authorization.entry_stop_event=stop
    # The outer CLI owns SIGINT/SIGTERM for both signer and observer lifetimes.
    # An inner SIGTERM handler must not stop only the signer then resume scanning.
    runtime.external_signal_owner=True
    original = runtime.session.cycle
    def cycle(*, scan=True):
        if stop.is_set():runtime.session.execution.entries_paused=True;scan=False
        try:return original(scan=scan)
        finally:
            d=runtime.session.execution.daily
            publish(dict(mode='AUTHORIZED TESTNET TRADING', status=d.state.value, team_wallet=TEAM,
                source_hash=m.daily.source_hash, mandate_hash=m.identity, expires_ms=m.daily.expires_ms,
                signing_authority='EXACT_BOUNDED_LONG_MANDATE', approved_bankroll=m.daily.bankroll,
                approved_maximum_notional=m.daily.maximum_notional, daily_lifecycle=dict(d.data),
                remaining_attempts=max(0,m.daily.maximum_entry_attempts-d.data['attempts']),
                risk_remaining=str(max(D(0),D(m.daily.bankroll)*D(m.daily.daily_loss_fraction)-max(D(0),-D(d.data['realized_net'])))),
                account=runtime.session.recovery.state.report(), account_age_ms=(runtime.session.clock_ms()-runtime.session.recovery.state.last_window[1]) if runtime.session.recovery.state.last_window else None,
                entry_cutoff_ms=m.daily.expires_ms-m.entry_cutoff_buffer_ms,
                scheduled_risk_close_ms=m.daily.expires_ms-getattr(m,'risk_close_buffer_ms',60000),
                midnight_policy=getattr(m.daily,'midnight_policy','SINGLE_DAY'),
                protection_statuses=runtime.session.execution.protection.states,
                owned_order_statuses=[dict(state=r['state'],oid=r['oid'],**{k:json.loads(r['request']).get(k) for k in ('side','symbol','quantity')})
                    for r in runtime.journal.intents() if r['intent_key'] in runtime.authorization.data['owned']],
                stream_connected=bool(runtime.market_stream and runtime.market_stream.connected),
                account_stream_healthy=runtime.session.account_stream.healthy, exchange_time_ms=None))
    runtime.session.cycle=cycle
    # The signer stops on its own finite deadline. That event must not stop the
    # longer-lived read-only observer or create a new signing window.
    signing_stop=threading.Event();finished=threading.Event()
    def forward_stop():
        while not finished.wait(.1):
            if stop.is_set():
                runtime.session.execution.entries_paused=True
                signing_stop.set();return
    forward=threading.Thread(target=forward_stop,name='terminal-entry-stop',daemon=True);forward.start()
    try:runtime.run(signing_stop)
    finally:finished.set();forward.join(2)
    return read_json(Path(args.mandate).parent/'terminal_result.json')


def approve(root,args):
    """Human terminal acceptance only; no noninteractive auto-approval switch."""
    from .long_session import read_mandate,require_release,require_native_evidence,ACKS
    validate_safe();m=read_mandate(args.mandate)
    require_release(root,args.release,m.daily.source_hash,m.release_sha256)
    if sha(args.native_protection_evidence)!=m.protection_evidence_sha256:
        raise ExchangeError('LONG_PROTECTION_PROOF_CHANGED')
    require_native_evidence(args.native_protection_evidence,m.daily)
    if not sys.stdin.isatty():raise ExchangeError('INTERACTIVE_HUMAN_APPROVAL_REQUIRED')
    if socket.gethostname()!=m.daily.signing_host:raise ExchangeError('EXACT_SIGNING_HOST_REQUIRED')
    print(json.dumps(asdict(m),indent=2))
    print('Mandate ID: '+m.identity)
    print('Approval confirms the named wallets and this sole signing host, LONG-only bounded scope, permitted loss-making risk exits, no blind retries after partial/unknown outcomes, stop-limit gap/outage risk, and no extension. No verified fill is implied. SHORT stays disabled.')
    extra_acks=()
    if m.mode=='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1':
        from .overnight_session import OVERNIGHT_ACKS
        extra_acks=OVERNIGHT_ACKS
        print('Overnight acceptance also confirms: attempts, allocation, P&L and peak drawdown never reset at midnight; stop coverage/gap and cross-midnight position risks are accepted; risk exits/owned recovery are permitted only until the hard expiry. After expiry observation continues without signing.')
    now=time.time_ns()//1000000
    if not m.created_ms<=now<=m.approval_deadline_ms:raise ExchangeError('LONG_APPROVAL_WINDOW_EXPIRED')
    answer=input('Type APPROVE '+m.identity+' to accept every displayed limit and acknowledgment: ')
    accepted=time.time_ns()//1000000
    if answer!='APPROVE '+m.identity:raise ExchangeError('EXACT_HUMAN_APPROVAL_NOT_GIVEN')
    if not m.created_ms<=accepted<=m.approval_deadline_ms:raise ExchangeError('LONG_APPROVAL_WINDOW_EXPIRED')
    acceptance=dict(mandate_hash=m.identity,operator_acceptance='Human typed exact APPROVE mandate ID in local terminal; all displayed acknowledgments accepted',
        accepted_ms=accepted,expires_ms=m.daily.expires_ms,**{name:True for name in ACKS+extra_acks})
    path=Path(args.mandate).parent/'acceptance.json'
    with path.open('x') as f:
        f.write(json.dumps(acceptance,indent=2)+'\n');f.flush();os.fsync(f.fileno())
    print('Genuine local operator acceptance saved: '+str(path));return 0


def start(root, args):
    validate_safe()
    state=Path(args.state).resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    # One local application owner across all output directories/modes.
    owner=PaperOwner(state/'owner.lock')
    session=uuid.uuid4().hex;output=state/'sessions'/session;output.mkdir(parents=True,mode=0o700)
    publish=Reporter(root,state,output,session);stop=threading.Event();done=threading.Event()
    source=active_source_hash(root);previous={};started=time.monotonic()
    atomic_json(state/'current.json',dict(session_id=session,output=str(output),pid=os.getpid()))
    def guard():
        while not done.wait(.5):
            try:
                request=read_json(state/'stop.json') if (state/'stop.json').exists() else {}
                if request.get('session_id')==session or args.duration and time.monotonic()-started>=args.duration:
                    stop.set();return
                if active_source_hash(root)!=source:stop.set();return
            except Exception:stop.set();return
    watcher=threading.Thread(target=guard,name='terminal-stop-source-guard',daemon=True);watcher.start()
    for sig in (signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,lambda *_:stop.set())
    try:
        if args.authorized:
            required=('mandate','acceptance','release','native_protection_evidence')
            if not all(getattr(args,n) for n in required):raise ExchangeError('EXACT_MANDATE_ACCEPTANCE_RELEASE_NATIVE_PROOF_REQUIRED')
            result=run_authorized(root,args,stop,publish)
            atomic_json(output/'trading_terminal_result.json',result)
            # The bounded signer has closed and released its locks. Observation
            # continues with a separate client, no signer and no renewal.
            if not stop.is_set():
                publish(dict(mode='TESTNET OBSERVATION',status='SIGNING_EXPIRED_OR_HALTED',source_hash=source,
                    signing_authority='REVOKED',previous_trading_result=result))
        if not stop.is_set():
            from .terminal_observer import observe
            result=observe(root,output,stop,publish,markets=args.markets,scan_seconds=args.scan_seconds)
        elif args.authorized:
            result=dict(result,mode='AUTHORIZED TESTNET TRADING',signing_authority='REVOKED')
            publish(result)
        else:
            result=dict(mode='TESTNET OBSERVATION',status='STOPPED',source_hash=source,signing_authority='NONE',terminal_flat=None)
            publish(result)
        atomic_json(output/'terminal_result.json',result)
        return 1 if result.get('status')=='HALTED' or result.get('threads_stopped') is False else 0
    except Exception as exc:
        publish(dict(mode='TESTNET OBSERVATION',status='HALTED_BEFORE_OR_DURING_START',source_hash=source,
            signing_authority='NONE',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,terminal_flat=None))
        return 1
    finally:
        stop.set();done.set();watcher.join(2)
        for sig,handler in previous.items():signal.signal(sig,handler)
        owner.close()


def main(root):
    root=Path(root)
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    doctor_p=sub.add_parser('doctor');doctor_p.add_argument('--online',action='store_true')
    research=sub.add_parser('research');research.add_argument('--snapshot',required=True);research.add_argument('--output',required=True)
    sim=sub.add_parser('simulate');sim.add_argument('--output',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--output',required=True);prep.add_argument('--markets',nargs='*',default=[])
    prep.add_argument('--minutes',type=int,default=60);prep.add_argument('--maximum-notional',default='1000')
    prep.add_argument('--release');prep.add_argument('--native-protection-evidence')
    prep.add_argument('--overnight',action='store_true',help='Propose Oct 16–17 bounded scope, hard expiry Oct 17 noon IST; no automatic approval')
    accept=sub.add_parser('approve',help='Interactive exact human acceptance; never auto-approve')
    for name in ('mandate','release','native-protection-evidence'):accept.add_argument('--'+name,required=True)
    launch=sub.add_parser('start');launch.add_argument('--authorized',action='store_true');launch.add_argument('--state',default=str(root/'runtime/terminal'))
    launch.add_argument('--markets',nargs='*',default=[]);launch.add_argument('--scan-seconds',type=int,default=60)
    launch.add_argument('--duration',type=int,help='Optional bounded read-only development soak; signing expiry is unchanged')
    for name in ('mandate','acceptance','release','native-protection-evidence'):launch.add_argument('--'+name)
    for name in ('status','stop','report'):
        q=sub.add_parser(name);q.add_argument('--state',default=str(root/'runtime/terminal'))
    args=p.parse_args()
    try:
        if args.command=='doctor':return doctor(root,args.online)
        if args.command=='research':
            validate_safe()
            from research_lab.quant_campaign import run_campaign
            result=run_campaign(args.snapshot,args.output);print(json.dumps(result,default=str));return 0
        if args.command=='simulate':
            validate_safe()
            from .terminal_simulation import simulate
            result=simulate(root,args.output);print(json.dumps(result,indent=2,default=str));return 0
        if args.command=='prepare':
            validate_safe()
            if not 10<=args.minutes<=720 or not D(10)<=D(args.maximum_notional)<=10000:raise ExchangeError('BOUNDED_PROPOSAL_LIMITS_REQUIRED')
            return prepare(root,args)
        if args.command=='approve':return approve(root,args)
        if args.command=='start':
            if not 60<=args.scan_seconds<=3600 or args.duration is not None and args.duration<1:raise ExchangeError('BOUNDED_REFRESH_REQUIRED')
            if not args.authorized and any(getattr(args,n) for n in ('mandate','acceptance','release','native_protection_evidence')):
                raise ExchangeError('EXPLICIT_AUTHORIZED_MODE_REQUIRED_FOR_SIGNING_FILES')
            return start(root,args)
        state=Path(args.state).resolve();current=read_json(state/'current.json');running=locked(state/'owner.lock')
        if args.command=='stop':
            if running:
                atomic_json(state/'stop.json',dict(session_id=current['session_id'],requested_ms=time.time_ns()//1000000))
            print(json.dumps(dict(status='GRACEFUL_STOP_REQUESTED' if running else 'ALREADY_STOPPED',
                session_id=current['session_id'],note='No automatic cancel or close without original exact authority. Use status/report to verify final truth.')));return 0
        v=read_json(Path(current['output'])/'status.json')
        v.update(process_lock_held=running,status_age_ms=time.time_ns()//1000000-v['updated_ms'])
        if running and v['status_age_ms']>180000:
            v.update(status='STALLED_OR_BOUNDED_RECOVERY_EXCEEDED',terminal_flat=None,
                residual_status='CACHED_ACCOUNT_TRUTH_REQUIRES_FRESH_READ')
        if not running and v['status'] not in {'STOPPED','HALTED','HALTED_BEFORE_OR_DURING_START',
                'STOPPED_FLAT_VERIFIED','HUMAN_RECOVERY_REVIEW_REQUIRED'}:
            v.update(status='INTERRUPTED_UNCLEAN',terminal_flat=None,residual_status='UNKNOWN_REQUIRES_FRESH_PUBLIC_RECONCILIATION')
        print(json.dumps(v,indent=2,default=str) if args.command=='status' else render(v));return 0
    except (ExchangeError,OSError,ValueError,KeyError) as exc:
        print(json.dumps(dict(status='FAILED_SAFE',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
            signing_authority='NONE_CREATED_BY_THIS_COMMAND')),file=sys.stderr);return 1
