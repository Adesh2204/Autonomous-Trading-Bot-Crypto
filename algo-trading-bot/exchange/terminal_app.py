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


def validate_safe(venue='pas'):
    from venue_config import require_paper_migration
    from strategy_freeze import verify_strategy_freeze
    require_paper_migration(venue);verify_strategy_freeze()


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
        value.setdefault('TRADING_AUTHORIZED',False)
        value.setdefault('AUTO_TRADING_ACTIVE',False)
        if value.get('dex')=='pas' and value.get('mode')=='TESTNET OBSERVATION':
            from .pas_controller import assess
            from .long_session import require_release,require_native_evidence
            from types import SimpleNamespace
            release=getattr(self,'readiness_release',None)
            if release:
                try:
                    require_release(self.root,release,value['source_hash'],sha(release))
                    value['release_verification']=dict(verified=True,source_hash=value['source_hash'],receipt_sha256=sha(release))
                except Exception as exc:value['release_verification']=dict(verified=False,reason=str(exc))
            native=getattr(self,'readiness_native_proof',None)
            if native:
                try:
                    proof=read_json(native);markets=tuple(proof.get('markets',{}))
                    from .venue_profiles import SCORED
                    if not markets or not set(markets)<=SCORED.markets:raise ExchangeError('EXACT_PAS_NATIVE_PROOF_MARKETS_REQUIRED')
                    require_native_evidence(native,SimpleNamespace(dex='pas',team_wallet=TEAM,api_wallet=API,markets=markets))
                    ordinary=[s for s in markets if value.get('liquidity',{}).get(s,{}).get('partial_minimum_admissible') is True]
                    value['native_proof_verification']=dict(verified=True,markets=markets,proof_sha256=sha(native),
                        residual_markets=ordinary,residual_scope_verified=bool(ordinary),
                        residual_scope_basis='ORDINARY_MINIMUM_FOR_EVERY_PARTIAL_ONLY',
                        limitation='No PAS subminimum exception is inferred. Each eligible market must meet the ordinary minimum on every possible partial protection/exit path.')
                except Exception as exc:value['native_proof_verification']=dict(verified=False,reason=str(exc))
            value['readiness']=assess(value,now)
        value['restart_context']=getattr(self,'restart_context',None)
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
            value.get('daily_lifecycle'),value.get('funding_event')], default=str, sort_keys=True)
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
            if key != self.previous or now-self.last_event>=30000:
                if sys.stdout.isatty():print('\033[2J\033[H',end='')
                print(render(value), flush=True)
            self.previous, self.last_event = key, now
        (self.output/'report.md').write_text(render(value)+'\n')
        return value


def render(v):
    account = v.get('account') or {}
    eq = account.get('reported_account_equity') or {}
    realized = account.get('realized') or {}
    lines = ['TEAM ANCHORIUM — QUANT ENGINE', f"MODE: {v.get('mode')} | STATUS: {v.get('status')}",
        f"TESTNET {v.get('dex','pas')} | Collateral: {v.get('collateral','USDP')} | Team: {v.get('team_wallet',TEAM)}", f"Source: {v.get('source_hash')}",
        f"Local: {v.get('local_time')} | Exchange time: {v.get('exchange_time_ms')} (null means unavailable)",
        f"Actual collateral: {eq.get('collateral_balance')} | Available/withdrawable: {eq.get('withdrawable')}",
        f"Proposed bankroll: 20000 | Approved bankroll: {v.get('approved_bankroll')} | Approved notional: {v.get('approved_maximum_notional')}",
        f"Positions: {account.get('positions','UNKNOWN')} | Open orders: {account.get('open_orders','UNKNOWN')}",
        f"Observed account net: {realized.get('net_after_fees_and_funding')} | Fees: {realized.get('actual_fill_fees')} | Funding: {realized.get('actual_funding_cashflow')}",
        f"Account age ms: {v.get('account_age_ms')} | Fee age ms: {v.get('fee_age_ms')}",
        f"Market WS: {v.get('stream_connected')} | Account WS: {v.get('account_stream_healthy')} | Authority: {v.get('signing_authority')}",
        f"Risk/remaining attempts: {v.get('risk_remaining')} / {v.get('remaining_attempts')} | Residual: {v.get('residual_status','UNKNOWN')}"]
    if v.get('readiness'):
        r=v['readiness'];funding=r['funding']
        lines += [f"READINESS: {r['state']} | Trading: {r['trading_verdict']} | NEXT ACTION: {r['next_action']}",
            f"USDP FUNDING: {funding.get('status')} | balance {funding.get('balance')} | age ms {funding.get('age_ms')} | organizer credit origin UNKNOWN",
            'READINESS GATES: '+json.dumps(r['gates'])]
    if v.get('expires_ms'):
        lines.append(f"Signing hard expiry ms: {v['expires_ms']} | Entry cutoff ms: {v.get('entry_cutoff_ms')} | Scheduled risk close ms: {v.get('scheduled_risk_close_ms')} | Midnight: {v.get('midnight_policy','SINGLE_DAY')}")
    if v.get('protection_statuses'):lines.append('NATIVE PROTECTION: '+json.dumps(v['protection_statuses'],default=str))
    local=v.get('local_execution_state') or {}
    lines.append(f"Local intent barrier: {local.get('status','UNKNOWN')} | Unresolved: {len(local.get('unresolved',[]))} | Native: {local.get('native_protection','SEE_QUALIFICATION_EVIDENCE')}")
    for intent in local.get('unresolved',[]):
        lines.append(f"[LOCAL_{intent['state']}] cloid {intent.get('cloid')} | journal {intent['journal']}")
    perf=v.get('session_performance') or {}
    if perf:
        lines += [f"Session actual gross / fees / funding / net: {perf.get('actual_gross_realized')} / {perf.get('actual_fees')} / {perf.get('actual_funding')} / {perf.get('actual_net_realized')}",
            f"Initial verified equity / current: {perf.get('initial_equity')} / {perf.get('current_equity')} | Realized net % of initial equity: {perf.get('realized_net_on_initial_equity_pct')}",
            f"Equity change %: {perf.get('equity_change_pct')} | Sampled drawdown %: {perf.get('sampled_maximum_drawdown_pct')} | Official score: UNKNOWN",
            perf['return_basis']]
    for r in v.get('signals', []):
        c = v.get('liquidity', {}).get(r['symbol'], {})
        lines.append(f"[{r['decision']}] {r['symbol']} | {', '.join(r.get('reasons',[]))} | bid/ask {c.get('bid')}/{c.get('ask')} | capacity {c.get('notional')} | SL/TP {r.get('baseline_stop')}/{r.get('baseline_target')} | approved size {r.get('approved_quantity')}")
        h=(v.get('market_history') or {}).get(r['symbol'],{})
        if h:lines.append(f"  Authentic history: {h['valid_deduplicated_completed']} completed | contiguous tail {h['contiguous_tail_bars']}/300 | gaps {len(h['missing_intervals'])} | age ms {h['cache_age_ms']} | last raw count {h['raw_returned_last']}")
        evidence=c.get('evidence_evaluation') or {}
        if evidence:
            lines.append(f"  Liquidity / conditional economic / authorized notional: {evidence['liquidity_only_notional']} / {evidence['economically_viable_notional']} / {evidence['authorized_executable_notional']} | Expected PnL: UNKNOWN | Target-scenario net/stress: {evidence.get('conditional_target_net')}/{evidence.get('stressed_conditional_target_net')}")
            lines.append('  '+', '.join(evidence['reasons']))
    if v.get('base_taker_fee_rate') is not None:
        lines.append(f"Fees: account base {v['base_taker_fee_rate']} | documented PAS estimate {v.get('documented_pas_taker_fee_estimate')} | unchanged 6x stress bound {v.get('fee_rate_bound')} | actual charges require fills")
    if v.get('error'):lines.append('ERROR: '+v['error'])
    for order in v.get('owned_order_statuses',[]):
        lines.append(f"[ORDER_{order['state']}] {order['side']} {order['symbol']} | oid {order['oid']} | quantity {order['quantity']}")
    for fill in account.get('fills',[]):
        lines.append(f"[EXCHANGE_FILL] {fill.get('side')} {fill.get('symbol')} | oid {fill.get('order_id')} | quantity {fill.get('quantity')} | price {fill.get('price')} | fee {fill.get('fee')}")
    lines += [f"Terminal flat: {v.get('terminal_flat','UNKNOWN')} | Simulated net: {v.get('simulated_net','N/A')}",
        'Actual account events and synthetic results are separate. No native stop or SHORT qualification is implied.',
        v.get('local_dependency','Local Mac, Python, power and internet are required.')]
    return '\n'.join(lines)


def doctor(root, online=False, venue='pas'):
    validate_safe(venue)
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
    from .venue_profiles import venue_profile
    profile=venue_profile(venue)
    result.update(dex=profile.dex,collateral=profile.collateral,venue_identity=profile.identity)
    from .overnight_session import OVERNIGHT_MAX_EXPIRY_MS
    result['overnight_contract']=dict(implemented=True,requires_new_exact_approval=True,
        hard_expiry_ms=OVERNIGHT_MAX_EXPIRY_MS,midnight_counters_reset=False)
    if online:
        from .hyperliquid_client import HyperliquidClient
        client = HyperliquidClient(venue=profile)
        try:client.startup();result.update(exchange_connectivity='PUBLIC_METADATA_CONFIRMED', markets=sorted(client.markets))
        finally:client.close()
    print(json.dumps(result, indent=2));return 0 if all(x['matching'] for x in dependencies.values()) else 1


def prepare(root, args):
    """Fresh public proposal, never an acceptance or signing capability."""
    if getattr(args,'venue','pas')=='pas':
        from .scored_prepare import prepare_scored
        return prepare_scored(root,args)
    from .terminal_observer import observe
    output = Path(args.output).resolve();output.mkdir(parents=True, exist_ok=False)
    report = observe(root, output, threading.Event(), lambda v:atomic_json(output/'snapshot.json', v),
        markets=args.markets, once=True)
    now = time.time_ns()//1000000
    end_day = datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta')).replace(hour=23,minute=57,second=0,microsecond=0)
    overnight=getattr(args,'overnight',False)
    practice=getattr(args,'practice_weekend',False)
    if practice and overnight:raise ExchangeError('ONE_EXPLICIT_TRADING_CONTRACT_REQUIRED')
    if practice:
        from .practice_weekend_session import PRACTICE_MAX_EXPIRY_MS
        if datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta')).date().isoformat()!='2026-10-17':
            raise ExchangeError('PRACTICE_OCT17_APPROVAL_DATE_REQUIRED_NO_AUTOMATIC_ROLLOVER')
        expires=min(now+86400000,PRACTICE_MAX_EXPIRY_MS)
    elif overnight:
        from .overnight_session import OVERNIGHT_MAX_EXPIRY_MS
        if datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta')).date().isoformat()!='2026-10-16':
            raise ExchangeError('OVERNIGHT_OCT16_APPROVAL_DATE_REQUIRED_NO_AUTOMATIC_ROLLOVER')
        expires=OVERNIGHT_MAX_EXPIRY_MS
    else:expires = min(now+args.minutes*60000, int(end_day.timestamp()*1000))
    blockers = ['ACTUAL_NATIVE_TRIGGER_PROTECTION_NOT_QUALIFIED', 'NEW_EXACT_HUMAN_APPROVAL_REQUIRED']
    local_clean=(report.get('local_execution_state') or {}).get('status')=='NO_LOCAL_UNRESOLVED_INTENT'
    if not local_clean:blockers.append('LOCAL_UNRESOLVED_INTENT_OR_JOURNAL_REVIEW_REQUIRED')
    # The currently published schedule ends practice Oct16, resumes scored
    # trading Oct19. A proposed weekend contract is not organizer permission.
    gap=datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Calcutta')).date().isoformat() in {'2026-10-17','2026-10-18'}
    if gap:blockers.append('ORGANIZER_OCT17_18_GAP_PERMISSION_NOT_VERIFIED')
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
    if overnight or practice:
        proposal.update(contract=('EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1' if practice else 'EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1'),starts_ms=now,
            session_loss_fraction='.01',midnight_policy='CARRY_ALL_ATTEMPTS_ALLOCATION_PNL_PEAK_DRAWDOWN_NO_RESET',
            entry_cutoff_ms=expires-900000,scheduled_risk_close_ms=expires-300000,
            signing_hard_expiry_ms=expires,maximum_cumulative_allocation=str(D(args.maximum_notional)*2),
            maximum_signed_actions=12,maximum_owned_cancellations=2,allow_loss_making_risk_exits=True,
            management_and_owned_recovery_expiry_ms=expires,after_expiry='READ_ONLY_NO_RENEWAL_NO_NEW_SIGNATURES')
    # A real executable mandate is generated only when every evidence gate passes.
    if args.native_protection_evidence and args.release and eligible and local_clean and not gap and report.get('terminal_flat') and not report.get('error'):
        from .long_session import LongMandate, require_native_evidence, require_release
        from .bounded_daily_session import DailyMandate
        from .reliability_policy import load_reliability_policy
        from .execution_journal import fingerprint
        limits_type,mandate_type=DailyMandate,LongMandate
        if overnight:
            from .overnight_session import OvernightLimits,OvernightLongMandate
            limits_type,mandate_type=OvernightLimits,OvernightLongMandate
        if practice:
            from .practice_weekend_session import PracticeWeekendLimits,PracticeWeekendLongMandate
            limits_type,mandate_type=PracticeWeekendLimits,PracticeWeekendLongMandate
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
    from .par_retirement import reject_retired_authorized_terminal_route
    reject_retired_authorized_terminal_route()
    from .long_session import build_long_runtime, read_mandate
    from market_regime_scanner import ScannerPolicy
    from risk.models import RiskPolicy
    m = read_mandate(args.mandate)
    if getattr(args,'venue','pas')=='par':raise ExchangeError('RETIRED_PAR_AUTHORIZED_ROUTE')
    if getattr(args,'venue','pas')!=m.daily.dex:raise ExchangeError('CLI_MANDATE_VENUE_MISMATCH')
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
            from .trading_status import authorized_status
            activity=authorized_status(runtime,runtime.session.clock_ms(),stop.is_set())
            publish(dict(**activity,mode='AUTHORIZED TESTNET TRADING', status=d.state.value, team_wallet=TEAM,
                dex=m.daily.dex,collateral=getattr(m,'collateral','USDPR'),venue_identity=runtime.authorization.venue_identity,
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
    m=read_mandate(args.mandate);validate_safe(m.daily.dex)
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
    if m.daily.dex=='pas':
        from .scored_session import SCORED_ACKS,require_scored_evidence
        require_scored_evidence(m,Path(args.mandate).parent)
        extra_acks=SCORED_ACKS
        print('PAS/USDP approval binds reviewed organizer provenance, shared UNKNOWN/nonce checks, actual PAS native/residual qualification, finite scored window and no automatic renewal. Practice evidence cannot qualify PAS.')
    if m.mode=='EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1':
        from .overnight_session import OVERNIGHT_ACKS
        extra_acks=OVERNIGHT_ACKS
        print('Overnight acceptance also confirms: attempts, allocation, P&L and peak drawdown never reset at midnight; stop coverage/gap and cross-midnight position risks are accepted; risk exits/owned recovery are permitted only until the hard expiry. After expiry observation continues without signing.')
    if m.mode=='EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1':
        from .practice_weekend_session import PRACTICE_ACKS
        extra_acks=PRACTICE_ACKS
        print('Practice Oct17–18 acceptance also confirms: one <=24h signing window, total attempts/allocation/P&L/drawdown carried without midnight reset, owned recovery only before hard expiry, position/stop/outage risk, and no automatic next-day authorization. Observation can continue without a signer.')
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
    if args.authorized:
        from .par_retirement import reject_retired_authorized_terminal_route
        reject_retired_authorized_terminal_route()
    venue=getattr(args,'venue','pas')
    validate_safe(venue)
    if venue=='pas' and Path(args.state).resolve()==(root/'runtime/terminal').resolve():
        args.state=str(root/'runtime/terminal-pas')
    state=Path(args.state).resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    binding=state/'venue.json'
    if binding.exists() and read_json(binding).get('dex')!=venue:
        raise ExchangeError('TERMINAL_STATE_VENUE_MISMATCH')
    old=read_json(state/'current.json') if (state/'current.json').exists() else None
    old_status=Path(old['output'])/'status.json' if old and old.get('output') else None
    if old_status and old_status.exists() and read_json(old_status).get('dex','pas')!=venue:
        raise ExchangeError('TERMINAL_STATE_VENUE_MISMATCH')
    # One local application owner across all output directories/modes.
    owner=PaperOwner(state/'owner.lock')
    atomic_json(binding,dict(network='testnet',dex=venue))
    prior=read_json(state/'current.json') if (state/'current.json').exists() else None
    session=uuid.uuid4().hex;output=state/'sessions'/session;output.mkdir(parents=True,mode=0o700)
    publish=Reporter(root,state,output,session)
    publish.readiness_release=getattr(args,'readiness_release',None)
    publish.readiness_native_proof=getattr(args,'readiness_native_proof',None)
    stop=threading.Event();done=threading.Event()
    publish.restart_context=dict(previous_session=prior.get('session_id') if prior else None,
        previous_output=prior.get('output') if prior else None,
        restored_authority=False,policy='Fresh public reconciliation; never restore signing from a prior process')
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
    authorized_builder_attempted=False
    try:
        if args.authorized:
            required=('mandate','acceptance','release','native_protection_evidence')
            if not all(getattr(args,n) for n in required):raise ExchangeError('EXACT_MANDATE_ACCEPTANCE_RELEASE_NATIVE_PROOF_REQUIRED')
            if getattr(args,'wait_for_readiness',False):
                from .conditional_activation import wait_for_readiness
                publish.readiness_release=args.release
                publish.readiness_native_proof=args.native_protection_evidence
                wait_result=wait_for_readiness(root,args,stop,publish,output)
                atomic_json(output/'activation_observation_result.json',wait_result)
                if stop.is_set():raise ExchangeError('CONDITIONAL_ACTIVATION_STOP_REQUESTED')
            authorized_builder_attempted=True
            result=run_authorized(root,args,stop,publish)
            atomic_json(output/'trading_terminal_result.json',result)
            # The bounded signer has closed and released its locks. Observation
            # continues with a separate client, no signer and no renewal.
            if not stop.is_set():
                publish(dict(mode='TESTNET OBSERVATION',status='SIGNING_EXPIRED_OR_HALTED',source_hash=source,
                    signing_authority='REVOKED',previous_trading_result=result))
        if not stop.is_set():
            from .terminal_observer import observe
            scope={'venue':venue}
            result=observe(root,output,stop,publish,markets=args.markets,scan_seconds=args.scan_seconds,**scope)
        elif args.authorized:
            result=dict(result,mode='AUTHORIZED TESTNET TRADING',signing_authority='REVOKED')
            publish(result)
        else:
            result=dict(mode='TESTNET OBSERVATION',status='STOPPED',source_hash=source,signing_authority='NONE',terminal_flat=None,
                dex=venue,collateral='USDP' if venue=='pas' else 'USDPR')
            publish(result)
        atomic_json(output/'terminal_result.json',result)
        return 1 if result.get('status')=='HALTED' or result.get('threads_stopped') is False else 0
    except Exception as exc:
        from .terminal_recovery import exception_evidence
        failure=dict(mode='AUTHORIZED TESTNET REQUEST HALTED' if authorized_builder_attempted else 'TESTNET OBSERVATION',status='HALTED_BEFORE_OR_DURING_START',source_hash=source,
            dex=venue,collateral='USDP' if venue=='pas' else 'USDPR',
            signing_authority='REVOKED_OR_UNAVAILABLE' if authorized_builder_attempted else 'NONE',
            TRADING_AUTHORIZED=False,AUTO_TRADING_ACTIVE=False,
            error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,error_details=exception_evidence(exc),
            terminal_flat=None,residual_status='UNKNOWN_REQUIRES_AUTHORITATIVE_RECONCILIATION',
            authorized_builder_attempted=authorized_builder_attempted)
        atomic_json(output/'terminal_result.json',failure)
        publish(failure)
        return 1
    finally:
        stop.set();done.set();watcher.join(2)
        for sig,handler in previous.items():signal.signal(sig,handler)
        owner.close()


def main(root):
    root=Path(root)
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    doctor_p=sub.add_parser('doctor');doctor_p.add_argument('--online',action='store_true')
    doctor_p.add_argument('--venue',choices=('par','pas'),default='pas')
    discovery=sub.add_parser('discover');discovery.add_argument('--venue',choices=('par','pas'),default='pas');discovery.add_argument('--output',required=True)
    research=sub.add_parser('research');research.add_argument('--snapshot',required=True);research.add_argument('--output',required=True)
    sim=sub.add_parser('simulate');sim.add_argument('--output',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--output',required=True);prep.add_argument('--markets',nargs='*',default=[])
    prep.add_argument('--venue',choices=('par','pas'),default='pas')
    prep.add_argument('--organizer-confirmation',help='Reviewed organizer provenance JSON with retained original record; PAS only')
    prep.add_argument('--minutes',type=int,default=60);prep.add_argument('--maximum-notional',default='1000')
    prep.add_argument('--release');prep.add_argument('--native-protection-evidence')
    contract=prep.add_mutually_exclusive_group()
    contract.add_argument('--overnight',action='store_true',help='Propose Oct 16–17 bounded scope, hard expiry Oct 17 noon IST; no automatic approval')
    contract.add_argument('--practice-weekend',action='store_true',help='Propose Oct17–18 scope, <=24h and no later than Oct18 23:57 IST; native proof and fresh exact approval required')
    accept=sub.add_parser('approve',help='Interactive exact human acceptance; never auto-approve')
    for name in ('mandate','release','native-protection-evidence'):accept.add_argument('--'+name,required=True)
    launch=sub.add_parser('start');launch.add_argument('--authorized',action='store_true');launch.add_argument('--state',default=str(root/'runtime/terminal'))
    launch.add_argument('--venue',choices=('par','pas'),default='pas',help='PAS observation; grants no signing authority')
    launch.add_argument('--readiness-release',help='Public verification only; grants no authority')
    launch.add_argument('--readiness-native-proof',help='Public raw-proof verification only; grants no authority')
    launch.add_argument('--wait-for-readiness',action='store_true',help='PAS only: one finite unsigned wait with an already genuinely accepted mandate; no approval creation or restart')
    launch.add_argument('--markets',nargs='*',default=[]);launch.add_argument('--scan-seconds',type=int,default=60)
    launch.add_argument('--duration',type=int,help='Optional bounded read-only development soak; signing expiry is unchanged')
    for name in ('mandate','acceptance','release','native-protection-evidence'):launch.add_argument('--'+name)
    for name in ('status','stop','report','dashboard','opening-check'):
        q=sub.add_parser(name);q.add_argument('--state',default=str(root/'runtime/terminal'))
        if name=='opening-check':
            for flag in ('release','discovery','organizer-confirmation','native-protection-evidence'):
                q.add_argument('--'+flag)
        if name=='dashboard':
            q.add_argument('--refresh',type=int,default=5);q.add_argument('--once',action='store_true')
    for name in ('funding','configuration-review','native-prepare','history-review'):
        q=sub.add_parser(name);q.add_argument('--output',required=True)
        if name=='native-prepare':q.add_argument('--market',default='pas:BTC')
        if name=='configuration-review':q.add_argument('--organizer-confirmation')
    for name in ('configuration-approve','configuration-apply'):
        q=sub.add_parser(name)
        for flag in ('plan','discovery','release','output'):q.add_argument('--'+flag,required=True)
        if name=='configuration-apply':q.add_argument('--acceptance',required=True)
    args=p.parse_args()
    try:
        if args.command=='opening-check':
            from .opening_audit import opening_check
            result=opening_check(root,args);print(json.dumps(result,indent=2,default=str))
            return 0 if result['statuses']['TRADING_AUTHORIZED'] else 1
        if args.command in {'funding','configuration-review','native-prepare','history-review','configuration-approve','configuration-apply'}:
            from .pas_operations import dispatch
            result=dispatch(root,args);print(json.dumps(result,indent=2,default=str))
            failed = {'CONFIGURATION_REQUIRES_REVIEW', 'HISTORY_REVIEW_INCOMPLETE',
                'DISCOVERY_INCOMPLETE'}
            return 1 if result.get('status') in failed else 0
        if args.command=='doctor':return doctor(root,args.online,args.venue)
        if args.command=='discover':
            from .venue_discovery import discover
            r=discover(root,args.output,venue=args.venue)
            print(json.dumps(r,indent=2,default=str));return 0 if r['status']=='READ_ONLY_DISCOVERY_COMPLETE' else 1
        if args.command=='research':
            validate_safe()
            from research_lab.quant_campaign import run_campaign
            result=run_campaign(args.snapshot,args.output);print(json.dumps(result,default=str));return 0
        if args.command=='simulate':
            validate_safe()
            from .terminal_simulation import simulate
            result=simulate(root,args.output);print(json.dumps(result,indent=2,default=str));return 0
        if args.command=='prepare':
            validate_safe(args.venue)
            if not 10<=args.minutes<=720 or not D(10)<=D(args.maximum_notional)<=10000:raise ExchangeError('BOUNDED_PROPOSAL_LIMITS_REQUIRED')
            return prepare(root,args)
        if args.command=='approve':return approve(root,args)
        if args.command=='start':
            if not 60<=args.scan_seconds<=3600 or args.duration is not None and args.duration<1:raise ExchangeError('BOUNDED_REFRESH_REQUIRED')
            if not args.authorized and any(getattr(args,n) for n in ('mandate','acceptance','release','native_protection_evidence')):
                raise ExchangeError('EXPLICIT_AUTHORIZED_MODE_REQUIRED_FOR_SIGNING_FILES')
            if args.wait_for_readiness and (not args.authorized or args.venue!='pas'):
                raise ExchangeError('CONDITIONAL_WAIT_REQUIRES_EXACT_AUTHORIZED_PAS_MODE')
            return start(root,args)
        state=Path(args.state).resolve();current=read_json(state/'current.json');running=locked(state/'owner.lock')
        if args.command=='stop':
            if running:
                atomic_json(state/'stop.json',dict(session_id=current['session_id'],requested_ms=time.time_ns()//1000000))
            print(json.dumps(dict(status='GRACEFUL_STOP_REQUESTED' if running else 'ALREADY_STOPPED',
                session_id=current['session_id'],note='No automatic cancel or close without original exact authority. Use status/report to verify final truth.')));return 0
        from .operator_status import current_status
        v=current_status(read_json(Path(current['output'])/'status.json'),current,
            running=running,now_ms=time.time_ns()//1000000,source_hash=active_source_hash(root))
        if args.command=='dashboard':
            if not 1<=args.refresh<=60:raise ExchangeError('BOUNDED_DASHBOARD_REFRESH_REQUIRED')
            try:
                while True:
                    current=read_json(state/'current.json')
                    v=current_status(read_json(Path(current['output'])/'status.json'),current,
                        running=locked(state/'owner.lock'),now_ms=time.time_ns()//1000000,
                        source_hash=active_source_hash(root))
                    if sys.stdout.isatty():print('\033[2J\033[H',end='')
                    print(render(v),flush=True)
                    if args.once:return 0
                    time.sleep(args.refresh)
            except KeyboardInterrupt:return 0
        print(json.dumps(v,indent=2,default=str) if args.command=='status' else render(v));return 0
    except (ExchangeError,OSError,ValueError,KeyError) as exc:
        print(json.dumps(dict(status='FAILED_SAFE',error=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
            signing_authority='NONE_CREATED_BY_THIS_COMMAND')),file=sys.stderr);return 1
