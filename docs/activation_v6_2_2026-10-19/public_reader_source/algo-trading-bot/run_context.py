"""Per-run identity, lifecycle timing, regular-process lock and readiness reports."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import uuid
import config
from historical_data import ist_timestamp
from discovery_data import atomic_json


class RegularInstanceLock:
    def __init__(self,path):
        self.path=Path(path)
        self.file=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+')
        try:
            fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError('REGULAR_INSTANCE_ALREADY_RUNNING')
        self.file.seek(0); self.file.truncate()
        self.file.write(json.dumps({'pid':os.getpid(),'started_at':ist_timestamp().isoformat()}))
        self.file.flush()
        return self

    def __exit__(self,*exc):
        fcntl.flock(self.file,fcntl.LOCK_UN)
        self.file.close()


class RunContext:
    def __init__(self,run_type='REGULAR',root=None):
        self.run_type=run_type
        self.run_id=f'{ist_timestamp():%Y%m%dT%H%M%S}-{run_type.lower()}-{uuid.uuid4().hex[:8]}'
        base=Path(__file__).parent
        if root is None and config.EXECUTION_ENVIRONMENT=='TEST':
            root=tempfile.mkdtemp(prefix='bot-run-test-')
        self.base=Path(root or base/'data'/'paper'/'runs')
        self.directory=self.base/self.run_id
        self.directory.mkdir(parents=True,exist_ok=True)
        strategy=hashlib.sha256((base/'signal_brain.py').read_bytes()).hexdigest()
        configuration={k:v for k,v in vars(config).items() if k.isupper()}
        config_hash=hashlib.sha256(json.dumps(configuration,sort_keys=True,default=str).encode()).hexdigest()
        try:
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True,stderr=subprocess.DEVNULL).strip()
        except (OSError,subprocess.CalledProcessError):
            revision='UNAVAILABLE'
        code=hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in sorted(base.glob('*.py')) if not p.name.startswith('test'))).hexdigest()
        self.identity={'run_id':self.run_id,'process_id':os.getpid(),'run_type':run_type,'git_revision':revision,
                       'code_sha256':code,'strategy_sha256':strategy,'config_sha256':config_hash,
                       'started_at':ist_timestamp().isoformat(),'mode':'PAPER'}
        self.stages=[]
        self.active={}
        self._mutex=threading.RLock()
        self.pipeline_report=None
        self.stream=None
        self.handler=None
        self._lock=None
        self.started=time.monotonic()

    def __enter__(self):
        if config.LIVE_MODE or config.EXECUTION_ENVIRONMENT not in {'PAPER','TEST'}:
            raise RuntimeError('PAPER_MODE_REQUIRED_FOR_THIS_RUNNER')
        if self.run_type=='REGULAR':
            self._lock=RegularInstanceLock(self.base.parent/'regular-runtime.lock')
            self._lock.__enter__()
        self.handler=logging.FileHandler(self.directory/'runtime.log')
        self.handler.setFormatter(logging.Formatter(f'%(asctime)s [%(levelname)s] [run={self.run_id}] %(message)s'))
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.INFO)
        from security_logging import install_broker_secret_filter
        install_broker_secret_filter()
        atomic_json(self.directory/'identity.json',self.identity)
        logging.info('[RUN IDENTITY] %s',json.dumps(self.identity))
        return self

    def __exit__(self,kind,error,tb):
        try:
            for stage in list(self.active):
                self.end_stage(stage,False,'RUN_ENDED_BEFORE_STAGE_COMPLETED')
            if self.stream is not None:
                self.write_session_summary(self.stream)
            self.identity.update(completed_at=ist_timestamp().isoformat(),
                                 runtime_seconds=time.monotonic()-self.started,
                                 error=type(error).__name__ if error else None)
            atomic_json(self.directory/'identity.json',self.identity)
        finally:
            if self.handler:
                logging.getLogger().removeHandler(self.handler)
                self.handler.close()
            if self._lock:
                self._lock.__exit__(kind,error,tb)

    def start_stage(self,name):
        with self._mutex:
            if name not in self.active:
                self.active[name]=(ist_timestamp().isoformat(),time.monotonic())
                logging.info('[STARTUP STAGE] %s START',name)

    def end_stage(self,name,success=True,reason=None):
        with self._mutex:
            active=self.active.pop(name,None)
            if active is None:
                return
            entry={'stage':name,'started_at':active[0],'ended_at':ist_timestamp().isoformat(),
                   'duration_seconds':time.monotonic()-active[1],'success':success,'reason':reason}
            self.stages.append(entry)
            atomic_json(self.directory/'lifecycle.json',self.stages)
            logging.info('[STARTUP STAGE] %s END success=%s duration=%.3fs reason=%s',
                         name,success,entry['duration_seconds'],reason)

    @contextmanager
    def stage(self,name):
        self.start_stage(name)
        try:
            yield
        except BaseException as exc:
            self.end_stage(name,False,type(exc).__name__)
            raise
        else:
            self.end_stage(name)

    def write_readiness(self,stream,now):
        with self._mutex:
            states=list(stream.active_symbols.values())
            healthy=any(s.feed_monitor.state.value=='HEALTHY' for s in states)
            if healthy:
                self.end_stage('STREAM_HEALTHY')
                if not any(s['stage']=='MARKET_READY' and s['success'] for s in self.stages):
                    self.start_stage('MARKET_READY')
            symbols=[]
            for s in states:
                s.refresh_maturity()
                symbols.append({'symbol':s.symbol,'role':s.watchlist_role,'data_status':s.data_status,
                    'volatility_status':s.volatility_status,'completed_candles':s.builder.candle_count,
                    'feed_status':s.feed_monitor.state.value,'history_validation':s.history_validation,
                    'historical_last_timestamp':str(s.builder.historical_last_timestamp),
                    'first_live_completed_timestamp':str(s.builder.first_live_completed_timestamp),
                    'rvol_profiles':len(s.volume_profiles),
                    'rvol_status':'AVAILABLE' if len(s.volume_profiles)>=config.OPPORTUNITY_RVOL_MIN_SESSIONS else 'INSUFFICIENT_HISTORY'})
            # Market readiness measures infrastructure, not whether a BUY/SELL exists.
            ready=any(s.data_status=='READY' and s.watchlist_role=='PRIMARY'
                      and s.feed_monitor.state.value=='HEALTHY' for s in states)
            if ready: self.end_stage('MARKET_READY')
            obs=stream.telemetry.summary()
            allowed=any(row['executable'] and row['timestamp']==now.isoformat() for row in stream.telemetry.observations.values())
            report={'identity':self.identity,'timestamp':str(now),'market_ready':ready,'entry_allowed':allowed,
                    'entry_allowed_basis':'MOST_RECENT_OBSERVATION_AT_THIS_TIMESTAMP; ALL GATES RECHECKED AT SUBMISSION',
                    'symbols':symbols,'history_api':dict(getattr(getattr(stream,'history_service',None),'metrics',{})),
                    'daily_remaining_risk':stream.paper_trader.journal.remaining(stream.paper_trader.daily_loss_limit),
                    'setup_attempts':stream.paper_trader.journal.budget()[1],
                    'open_position':stream.paper_trader.has_open_position,'halted':stream.paper_trader._halted,
                    'accounting_source':'CONFIRMED_PAPER_FILLS','opportunities':obs}
            atomic_json(self.directory/'readiness.json',report)
            return report

    def write_session_summary(self,stream):
        if getattr(stream,'shadow',None) is not None:
            stream.shadow.finish(stream.active_symbols)
        report=stream.paper_trader.journal.report()
        opportunities=stream.telemetry.summary()
        pipeline=self.pipeline_report or {}
        discovery=pipeline.get('discovery',{})
        deep=pipeline.get('deep_screen',{})
        net=report['net_pnl']
        summary={'identity':self.identity,'runtime_seconds':time.monotonic()-self.started,
            'lifecycle':self.stages,'historical_api':dict(getattr(getattr(stream,'history_service',None),'metrics',{})),
            'opportunity_funnel':{'nse_equities':pipeline.get('universe_audit',{}).get('eligible_instruments'),
                'historical_valid_candidates':deep.get('candidates_with_valid_data'),
                'previous_session_qualifiers':deep.get('qualified'),'monitored_symbols':len(stream.active_symbols),
                **opportunities,'orders':report['counters']['orders_submitted'],'entry_fills':report['counters']['orders_filled'],
                'profitable_closed_trades':sum(t['net_pnl']>0 for t in stream.paper_trader.journal.trades())},
            'gross_pnl':report['gross_pnl'],'charges':report['fees'],'net_pnl':net,
            'estimated_execution_cost':sum(t.get('entry_slippage',0)*t.get('quantity',0) for t in stream.paper_trader.journal.trades()),
            'execution_cost_note':'Diagnostic only; fill slippage is already in gross P&L and is never subtracted twice.',
            'maximum_realised_drawdown':report['realized_peak_drawdown'],
            'result':'PROFIT' if net>0 else 'LOSS' if net<0 else 'NO_TRADE' if not report['completed_trades'] else 'FLAT',
            'accounting_scope':'DURABLE PAPER DAY LEDGER, INCLUDING EARLIER REGULAR RUNS; telemetry belongs to this run',
            'open_positions':int(stream.paper_trader.has_open_position),'accounting':report}
        atomic_json(self.directory/'session_summary.json',summary)
        return summary

    def record_shutdown(self,reason):
        with self._mutex:
            self.identity.update(completed_at=ist_timestamp().isoformat(),shutdown_reason=reason,
                                 runtime_seconds=time.monotonic()-self.started)
            atomic_json(self.directory/'identity.json',self.identity)
