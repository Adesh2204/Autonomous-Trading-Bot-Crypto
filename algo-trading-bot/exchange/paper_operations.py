"""Single-host PAPER ownership and local health evidence; no notification sender."""
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys

from .base_exchange import ExchangeError
from .execution_journal import safe_reason


def atomic_json(path,value):
    path=Path(path)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,default=str,allow_nan=False)+'\n')
    temporary.replace(path)


def active_source_hash(root):
    paths=list((root/'scripts').glob('*.py'))+[p for p in (root/'algo-trading-bot').rglob('*.py')
        if not {'venv','.venv','__pycache__'}&set(p.parts)]
    return hashlib.sha256(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)},sort_keys=True).encode()).hexdigest()


class PaperOwner:
    def __init__(self,path):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.file=path.open('a+')
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ExchangeError('PAPER_OWNER_ALREADY_RUNNING') from None
        self.file.seek(0);self.file.truncate();self.file.write(str(os.getpid()));self.file.flush()
    def close(self):
        fcntl.flock(self.file,fcntl.LOCK_UN)
        self.file.close()


class PaperHealth:
    def __init__(self,path,*,session_id,segment):
        self.path=Path(path)
        self.path.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.session_id=session_id
        self.segment=str(segment)
        self.signature=None

    def write(self,bot,*,status='RUNNING',reason=None):
        now=bot.clock_ms()
        scan=bot.latest_scan
        scan_age=now-scan.observed_at_ms if scan else None
        stream=bot.stream_report or {}
        data_healthy=[s for s,v in bot.feed_health.items() if v['healthy']]
        issues=[]
        transport=stream.get('transport') or {}
        subscription_ready=bool(transport.get('desired_count',0)>0 and
            transport.get('confirmed_count')==transport.get('desired_count') and
            not transport.get('missing_acknowledgements') and transport.get('duplicate_subscriptions')==0)
        transport_ready=bool(stream.get('connected') and stream.get('reconciled') and subscription_ready)
        if not transport_ready:issues.append('TRANSPORT_OR_SUBSCRIPTIONS_NOT_READY')
        recovery=stream.get('account_recovery') or {}
        account_ready=bool(recovery.get('entries_paused') is False and
            stream.get('accepted_generation')==stream.get('generation'))
        if not account_ready:issues.append('ACCOUNT_OR_STREAM_UNRECONCILED')
        if stream.get('recovery_status')=='RECOVERY_FAILED':issues.append('REST_RECOVERY_SYSTEM_FAILED')
        public_budget=stream.get('public_rate_budget') or {}
        if public_budget.get('public_read_blocked'):issues.append('PUBLIC_RATE_BUDGET_THROTTLED')
        for key,block in bot.breakers.global_blocks.items():
            if key in {'account','accounting','stream','worker','api_budget'}:
                issues.append(str(block))
        if not data_healthy:issues.append('NO_HEALTHY_PUBLIC_MARKET_FEED')
        if scan_age is None or not 0<=scan_age<=360000:issues.append('SCANNER_HEARTBEAT_STALE')
        if bot.accounting_halt:issues.append('PAPER_ACCOUNTING_HALTED')
        disk=shutil.disk_usage(self.path)
        disk_fraction=(disk.total-disk.free)/disk.total
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb=rss/(1024*1024 if sys.platform=='darwin' else 1024)
        if disk_fraction>=.85:issues.append('DISK_USAGE_HIGH')
        if rss_mb>=2048:issues.append('MEMORY_HIGH_WATERMARK')
        if reason:issues.append(safe_reason(reason))
        issues=list(dict.fromkeys(issues))
        operating_feed_ready=not issues
        overall=('DEGRADED' if issues else 'HEALTHY' if len(data_healthy)==len(bot.feed_health) else 'PARTIAL_HEALTHY')
        signature=(status,tuple(sorted(issues)))
        value=dict(session_id=self.session_id,segment=self.segment,pid=os.getpid(),execution_mode='PAPER',
            allow_live_orders=False,exchange_orders_submitted=0,provenance='LOCAL_PAPER_OPERATION_HEALTH',
            timestamp_ms=now,observed_at_utc=datetime.now(timezone.utc).isoformat(),
            status=status,severity='ERROR' if status=='FAILED' or bot.accounting_halt else 'WARNING' if issues else 'OK',
            issues=issues,healthy_markets=data_healthy,scan_age_ms=scan_age,
            overall=overall if status=='RUNNING' else status,
            market_health=bot.feed_health,usable_markets=len(data_healthy),total_markets=len(bot.feed_health),
            feed_ready=bool(operating_feed_ready and status=='RUNNING'),
            last_operating_feed_ready=operating_feed_ready,trade_ready=False,
            transport_ready=transport_ready,subscriptions_ready=subscription_ready,
            native_feed_ready=bool(operating_feed_ready and status=='RUNNING'),
            scanner_evaluation_allowed=bool(operating_feed_ready and status=='RUNNING'),
            signal_available=bool(scan and any(d.symbol in scan.watchlist and d.signal and
                (d.signal.get('long') or d.signal.get('short')) for d in scan.diagnostics)),
            reconciliation_ready=account_ready,global_blockers=issues,
            scan_status=scan.status if scan else None,rejections={d.symbol:d.reasons for d in scan.diagnostics} if scan else {},
            local_fills=len(bot.execution.fills),local_positions=len(bot.execution.portfolio.positions),
            public_stream=stream,rss_high_watermark_mb=rss_mb,disk_used_fraction=disk_fraction,
            data_healthy=operating_feed_ready)
        atomic_json(self.path/'health.json',value)
        if signature!=self.signature:
            with (self.path/'alerts.jsonl').open('a') as f:f.write(json.dumps(value,default=str,allow_nan=False)+'\n')
            self.signature=signature
        if disk_fraction>=.90:raise ExchangeError('PAPER_DISK_CAPACITY_HALT')
        return value
