"""One bounded public BTC receiver/account observer; no order submission method.

State and health tapes survive read-only restarts. A separate accepted runtime
owns the one signing attempt; crash/uncertainty never resumes it automatically.
"""
from dataclasses import asdict
import json,threading,time
from pathlib import Path
from .base_exchange import ExchangeError,decimal
from .execution_safety import NonceManager
from .paper_operations import atomic_json
from .qualification_watcher import (ReadOnlyQualificationSession,PublicBookStream,
    PublicBookReader,source_unchanged)
from .emergency_qualification import EmergencyContextProvider,inspect_market,propose,BOUNDED_PRICE
from .delegated_qualification import validate_proposal


class PersistentQualificationObserver:
    def __init__(self,root,directory,source_hash,reliability_hash,*,mandate=None,cancel=None):
        self.root=Path(root);self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.source_hash,self.reliability_hash=source_hash,reliability_hash
        self.mandate=mandate;self.cancel=cancel or threading.Event()
        self.session=self.stream=self.nonces=None;self.closed=False
        self.last_reconcile=self.last_candidate=self.last_source=-float('inf')
        self.started=time.monotonic();self.next_index=1
        self.ws_episodes=0;self.last_ws_restart=-float('inf');self.ws_history=[]
        prior=self.directory/'health.json'
        self.observations=json.loads(prior.read_text()).get('observations',0) if prior.exists() else 0
        self.status='READ_ONLY_STARTING'

    def progress(self,event,**details):
        row=dict(event=event,at_ms=time.time_ns()//1000000,**details)
        with (self.directory/'events.jsonl').open('a') as f:f.write(json.dumps(row,default=str)+'\n')
        if self.cancel.is_set():raise ExchangeError('QUALIFICATION_WATCH_CANCELLED')

    def start(self):
        self.session=ReadOnlyQualificationSession(self.root,self.directory,self.source_hash,
            self.reliability_hash,progress=self.progress,cancel_event=self.cancel)
        self.session._provider_class=EmergencyContextProvider;self.session.start()
        self.session.verify_signer()
        self.nonces=NonceManager(self.root/'runtime/testnet/anchorium-bot-1/nonces.sqlite',self.session.api,
            clock_ms=self.session.client.clock_ms,journal=self.session.journal)
        self.stream=PublicBookStream(['par:BTC'],self.session.rates,clock_ms=self.session.client.clock_ms)
        self.stream.start();self.ws_episodes=1;self.last_ws_restart=time.monotonic()
        self.reader=PublicBookReader(self.session.market,self.stream)
        self.status='READ_ONLY_OBSERVATION';self.publish()

    def publish(self,**details):
        value=dict(status=self.status,heartbeat_ms=time.time_ns()//1000000,
            source_hash=self.source_hash,observations=self.observations,exchange_actions=0,
            evidence_scope='READ_ONLY_OBSERVER_ONLY; SIGNED_EXECUTION_RECORDED_SEPARATELY',
            nonce_allocations=0,signatures_created=0,signer_lease_held=self.nonces is not None and not self.nonces.closed,
            stream=self.stream.report() if self.stream else None,**details)
        value.update(ws_episodes=self.ws_episodes,previous_ws_episodes=self.ws_history)
        atomic_json(self.directory/'health.json',value)
        with (self.directory/'health_samples.jsonl').open('a') as f:f.write(json.dumps(value,default=str)+'\n')

    def poll(self):
        if self.cancel.is_set():raise ExchangeError('QUALIFICATION_WATCH_CANCELLED')
        if self.closed or self.nonces is None or not self.nonces.healthy:
            raise ExchangeError('QUALIFICATION_WATCH_SIGNER_LEASE_UNHEALTHY')
        now=time.monotonic();s=self.session
        if (self.stream.thread is not None and not self.stream.thread.is_alive()
                and now-self.last_ws_restart>=60 and self.ws_episodes<4):
            self.ws_history.append(self.stream.report());self.stream.close()
            self.stream=PublicBookStream(['par:BTC'],s.rates,clock_ms=s.client.clock_ms)
            self.stream.start();self.ws_episodes+=1;self.last_ws_restart=now
            self.reader=PublicBookReader(s.market,self.stream)
            self.progress('BOUNDED_PUBLIC_WS_RECONNECT_EPISODE',episode=self.ws_episodes)
        if now-self.last_source>=5:
            source_unchanged(self.root,self.source_hash,self.reliability_hash);self.last_source=now
        if now-self.last_reconcile>=60:
            from .testnet_qualification import prime_read_only_clock
            from .live_readiness import verify_live_account_readiness
            from .practice_preflight import verify_private_identity
            prime_read_only_clock(s.market,s.clock,'par:BTC')
            report=s._reconcile()
            if not report.ready or s.recovery.state.positions or s.recovery.state.orders:
                raise ExchangeError('QUALIFICATION_WATCH_ACCOUNT_NOT_FLAT_OR_UNRECONCILED')
            identity=verify_private_identity(self.root,s.api,s.team)
            readiness=verify_live_account_readiness(s.account,s.api,clock_health=s.clock,
                rate_limits=s.rates,reconciliation_ready=report.ready)
            if not readiness.account_ready or not self.nonces.healthy:
                raise ExchangeError('QUALIFICATION_WATCH_ACCOUNT_OR_SIGNER_NOT_READY')
            self.contexts=s.market.get_asset_contexts();self.contexts_ms=s.client.clock_ms()
            self.last_reconcile=now
            self.progress('PERIODIC_ACCOUNT_RECONCILED',report=asdict(report),
                readiness=asdict(readiness),signer_identity=identity)
        book,origin=self.reader.get('par:BTC');self.observations+=1
        row=dict(potential=False,blocker='NO_FRESH_BOOK',input_transport=origin)
        if book:
            row=inspect_market(s.client.market('par:BTC'),book,s.client.clock_ms(),tif='Ioc',
                asset_context=self.contexts['par:BTC'])
            row.update(input_transport=origin,reference_snapshot_ms=self.contexts_ms)
            if decimal(row.get('minimum_quantity','0'))!=decimal('0.0002') or decimal(row.get('minimum_entry_notional','0'))>20:
                row.update(potential=False,blocker='EXACT_SESSION_QUANTITY_OR_TWENTY_CAP_INELIGIBLE')
        with (self.directory/'observations.jsonl').open('a') as f:f.write(json.dumps(row,default=str)+'\n')
        self.publish(last_market=row,rates=s.rates.report())
        if not row['potential'] or now-self.last_candidate<60:return None
        self.last_candidate=now
        # Public candidates never constitute exchange authority. Complete real
        # account/market evidence is acquired again for this selected envelope.
        context=s.provider.load(type('ReadRequest',(),dict(symbol='par:BTC',reduce_only=False))())
        p,checks=propose(context,s.client,self.source_hash,self.reliability_hash,s.provider.last_book,
            tif='Ioc',candidate_hash=row['evidence_hash'],price_mode=BOUNDED_PRICE)
        if self.mandate:validate_proposal(self.mandate,p,context.spec)
        self.progress('QUALIFIED_READ_ONLY_ENVELOPE',proposal_id=p.identity,checks=checks)
        return p

    def nonce_owner(self):
        if self.nonces is None or not self.nonces.healthy:raise ExchangeError('QUALIFICATION_NONCE_OWNER_REQUIRED')
        return self.nonces

    def pause_for_execution(self):
        """No concurrent public receiver can write to the handed-off journal."""
        if self.stream:self.stream.close()
        self.status='READ_ONLY_PAUSED_FOR_SINGLE_EXECUTION';self.publish()
        return self.session.rates

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if self.stream:self.stream.close()
            if self.session:self.session.close()
        finally:
            if self.nonces:self.nonces.close()
            self.status='READ_ONLY_STOPPED';self.publish()


def read_only_soak(root,directory,*,duration_seconds=30):
    """Engineering public/account observation only; cannot construct a runtime."""
    if not 1<=duration_seconds<=60:raise ExchangeError('BOUNDED_READ_ONLY_SOAK_REQUIRED')
    import hashlib
    from .paper_operations import active_source_hash
    from venue_config import require_paper_migration
    require_paper_migration()
    root=Path(root);source=active_source_hash(root)
    observer=PersistentQualificationObserver(root,directory,source,
        hashlib.sha256((root/'configs/reliability_policy.json').read_bytes()).hexdigest())
    started=time.monotonic();result=dict(scope='READ_ONLY_ENGINEERING_SOAK',exchange_actions=0,signatures=0)
    try:
        observer.start()
        while time.monotonic()-started<duration_seconds:
            try:observer.poll()
            except ExchangeError as exc:
                if str(exc) not in {'P0_CURRENT_PRICE_OR_CAP_REQUIRED','P0_APPROVED_L2_PARTICIPATION_EXCEEDED',
                    'P0_SPREAD_EXCEEDED','P0_ENTRY_DEPTH_REQUIRED','P0_EXIT_DEPTH_REQUIRED'}:raise
            time.sleep(.5)
        result.update(passed=True,observations=observer.observations,stream=observer.stream.report(),
            signer_lease_healthy=observer.nonces.healthy)
    except Exception as exc:result.update(passed=False,blocker=str(exc))
    finally:
        observer.close();result['shutdown_confirmed']=True
        atomic_json(Path(directory)/'soak_report.json',result)
    return result
