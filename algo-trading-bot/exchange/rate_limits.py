"""Priority-aware shared API budgets; signed actions are never retried here."""
from dataclasses import asdict
import json
import os
import random
import threading
import time
from .base_exchange import ExchangeError
from .reliability_policy import HyperliquidRatePolicy,RequestPriority,RateState


class PasCandleBudget:
    """Internal aggregate PAS candle-slot guard (not an exchange rate limit)."""
    CAP=300
    WINDOW_MS=60_000

    def __init__(self,*,clock_ms=None):
        self.clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)
        self.lock=threading.RLock()
        self._reservations=[]
        self._market_reservations=[]

    def _prune(self,now):
        self._reservations=[(stamp,count) for stamp,count in self._reservations
                            if stamp>now-self.WINDOW_MS]

    def _retry_after(self,now,needed):
        if needed>self.CAP:return None
        released=0
        for stamp,count in sorted(self._reservations):
            released+=count
            if released>=needed:return max(0,stamp+self.WINDOW_MS-now)
        return self.WINDOW_MS

    def reserve(self,slots,*,symbol=None):
        """Charge a request before HTTP; reservations are never refunded."""
        with self.lock:
            now=self.clock_ms();self._prune(now)
            self._market_reservations=[r for r in self._market_reservations
                if r[0]>now-self.WINDOW_MS]
            if symbol is not None:
                if symbol not in {'pas:BTC','pas:EWY'}:
                    raise ExchangeError('PAS_CANDLE_MARKET_REQUIRED')
                own=[(t,n) for t,s,n in self._market_reservations if s==symbol]
                own_used=sum(n for _,n in own)
                if type(slots) is int and slots>0 and own_used+slots>self.CAP//2:
                    error=ExchangeError('PAS_CANDLE_MARKET_SHARE_EXHAUSTED')
                    error.retry_after_ms=(max(0,min(t for t,_ in own)+self.WINDOW_MS-now)
                        if own and slots<=self.CAP//2 else None)
                    error.requested_slots=slots;error.used_slots=own_used;error.cap=self.CAP//2
                    raise error
            used=sum(count for _,count in self._reservations)
            valid=type(slots) is int and 1<=slots<=self.CAP
            if not valid or used+slots>self.CAP:
                needed=max(1,used+slots-self.CAP) if type(slots) is int and slots>0 else self.CAP+1
                error=ExchangeError('PAS_CANDLE_BUDGET_EXHAUSTED')
                error.retry_after_ms=self._retry_after(now,needed) if valid else None
                error.requested_slots=slots
                error.used_slots=used
                error.cap=self.CAP
                raise error
            self._reservations.append((now,slots))
            if symbol is not None:self._market_reservations.append((now,symbol,slots))
            return self.report()

    def report(self):
        with self.lock:
            now=self.clock_ms();self._prune(now)
            used=sum(count for _,count in self._reservations)
            retry_after=(max(0,min(stamp for stamp,_ in self._reservations)+self.WINDOW_MS-now)
                         if used else 0)
            return dict(used=used,cap=self.CAP,remaining=self.CAP-used,
                        window_ms=self.WINDOW_MS,observed_ms=now,
                        retry_after_ms=retry_after,reservations=len(self._reservations))


# PAS BTC and EWY share this budget across default clients and rate managers.
PAS_CANDLE_BUDGET=PasCandleBudget()


class HyperliquidRateLimitManager:
    SMALL_INFO={'l2Book','allMids','clearinghouseState','orderStatus','spotClearinghouseState','exchangeStatus'}
    SAFETY_INFO={'orderStatus','clearinghouseState','openOrders','frontendOpenOrders',
                 'userFills','userFillsByTime','userFunding','userRateLimit'}
    HISTORY={'recentTrades','userFills','userFillsByTime','fundingHistory','userFunding','candleSnapshot'}

    def __init__(self,journal,*,clock_ms=None,policy=None,ip_weight_limit=None,daily_limit=None,
                 jitter=None,wait=None,signer_address=None):
        self.journal=journal
        self.clock_ms=clock_ms or (lambda:time.time_ns()//1000000)
        self.policy=policy or HyperliquidRatePolicy()
        self.ip_weight_limit=ip_weight_limit if ip_weight_limit is not None else self.policy.ip_weight_per_minute
        self.daily_limit=daily_limit if daily_limit is not None else self.policy.daily_actions
        self.signer_address=signer_address
        self.jitter=jitter or random.random
        self.wait=wait or (lambda ms:time.sleep(ms/1000))
        self.lock=threading.RLock()
        self.weights=[]
        self.budget=None
        self.n_requests_used=None
        self.n_requests_cap=None
        self.budget_observed_ms=None
        self.reserved_since_snapshot=0
        self.open_orders=None
        self.recent_errors=0
        self.backoff_until=0
        self.optional_times={}
        self.ws_connections={}
        self.ws_messages=[]
        self.ws_reconnects=[]
        self.last_state=None
        self.last_safety_action_ms=None
        self.inflight_reads={}
        self.read_counts={}
        self.read_failures={}
        self.coalesced_reads=0
        self.max_read_seconds=0
        self.read_deadline_seconds=45
        self.read_budget_wait_seconds=0  # Qualification opts in; live feed remains fail-fast.
        self.read_progress=None
        self.read_failure_details=[]
        with journal.transaction():
            journal.db.execute('CREATE TABLE IF NOT EXISTS api_actions ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT,utc_day INTEGER,process INTEGER,'
                'signer TEXT,session TEXT,kind TEXT,operations INTEGER,timestamp_ms INTEGER)')
        row=journal.db.execute("SELECT value FROM controls WHERE name='api_budget_local'").fetchone()
        if row:
            previous=json.loads(row[0])
            self.n_requests_used=previous['used']
            self.reserved_since_snapshot=previous['reserved']
            self.last_safety_action_ms=previous['last_safety_action_ms']

    def _persist_budget(self):
        self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',('api_budget_local',
            json.dumps(dict(used=self.n_requests_used,reserved=self.reserved_since_snapshot,
                            last_safety_action_ms=self.last_safety_action_ms))))

    def _event(self,kind,**values):
        self.journal.event(kind,self.clock_ms(),**values)

    def _usage(self):
        now=self.clock_ms()
        self.weights=[(t,w) for t,w in self.weights if t>now-60000]
        return sum(w for _,w in self.weights)

    def read_budget_delay_ms(self,weight,priority=RequestPriority.DECISION):
        """Grounded rolling-window estimate, including server backoff guidance."""
        with self.lock:
            now=self.clock_ms();usage=self._usage()
            limit=self.ip_weight_limit-(0 if priority==RequestPriority.SAFETY else self._reserve('ip'))
            if weight>limit:raise ExchangeError('INFO_PUBLIC_BUDGET_TOO_SMALL')
            delay=max(0,self.backoff_until-now)
            if usage+weight>limit:
                for stamp,cost in sorted(self.weights):
                    usage-=cost
                    if usage+weight<=limit:
                        delay=max(delay,stamp+60000-now);break
                if usage+weight>limit:
                    # No earlier capacity is proven: conservatively defer the
                    # whole rolling window rather than granting admission.
                    delay=max(delay,60000)
            return delay

    def wait_for_read_budget(self,weight,*,priority=RequestPriority.DECISION,max_wait_seconds=65,
                             cancel_event=None,progress=None,wait_ms=None):
        started=time.monotonic();last_notice=-1
        while True:
            if cancel_event is not None and cancel_event.is_set():raise ExchangeError('INFO_READ_CANCELLED')
            delay=self.read_budget_delay_ms(weight,priority)
            if not delay:return
            elapsed=time.monotonic()-started
            if progress and elapsed-last_notice>=1:
                progress('WAITING_FOR_RATE_BUDGET',reason='ROLLING_IP_WINDOW_OR_SERVER_BACKOFF',
                    ip_weight=self._usage(),required_weight=weight,next_retry_ms=self.clock_ms()+delay,
                    retry_in_seconds=round(delay/1000,3),wait_elapsed_seconds=round(elapsed,3))
                last_notice=elapsed
            if elapsed>=max_wait_seconds or delay>(max_wait_seconds-elapsed)*1000:
                raise ExchangeError('INFO_PUBLIC_READ_BUDGET_DEADLINE')
            duration=min(250,delay)
            if cancel_event is None:(wait_ms or self.wait)(duration)
            elif cancel_event.wait(duration/1000):raise ExchangeError('INFO_READ_CANCELLED')

    @property
    def remaining_budget(self):
        return None if self.budget is None else max(0,self.budget-self.reserved_since_snapshot)

    def daily_used(self):
        row=self.journal.db.execute('SELECT value FROM controls WHERE name=?',
            ('daily_actions:'+str(self.clock_ms()//86400000),)).fetchone()
        return int(row[0]) if row else 0

    def _reserve(self,kind):
        configured=getattr(self.policy,kind+'_safety_reserve')
        limit=self.ip_weight_limit if kind=='ip' else self.daily_limit
        policy_limit=self.policy.ip_weight_per_minute if kind=='ip' else self.policy.daily_actions
        # Compatibility-only tiny legacy test limits; explicit policy reserves
        # are otherwise honored exactly, including reserves greater than 10%.
        return configured if limit==policy_limit else min(configured,limit//10)

    @property
    def state(self):
        with self.lock:
            usage=self._usage()
            daily=self.daily_used()
            reserve=self._reserve('daily')
            if self.remaining_budget==0 or daily>=self.daily_limit-reserve:
                result=RateState.EXHAUSTED
            elif self.clock_ms()<self.backoff_until or usage>=self.ip_weight_limit*self.policy.throttle_fraction:
                result=RateState.THROTTLED
            elif self.budget_observed_ms is None or not 0<=self.clock_ms()-self.budget_observed_ms<=self.policy.budget_max_age_ms:
                result=RateState.UNKNOWN
            elif (usage>=self.ip_weight_limit*self.policy.caution_fraction or
                  self.remaining_budget<=self.policy.account_action_reserve or
                  daily>=self.daily_limit*self.policy.caution_fraction):
                result=RateState.CAUTION
            else:
                result=RateState.HEALTHY
            if result!=self.last_state:
                self.last_state=result
                self._event({RateState.CAUTION:'RATE_LIMIT_WARNING',RateState.THROTTLED:'RATE_LIMIT_THROTTLED',
                    RateState.EXHAUSTED:'ACCOUNT_BUDGET_LOW'}.get(result,'RATE_STATE_CHANGE'),state=result.value)
            return result

    @property
    def safety_ready(self):
        # Read/account health differs from permission to spend the entry reserve.
        return (self.budget_observed_ms is not None and
                0<=self.clock_ms()-self.budget_observed_ms<=self.policy.budget_max_age_ms and
                self.remaining_budget is not None and self.open_orders is not None)

    @property
    def healthy(self):
        return self.safety_ready and self.clock_ms()>=self.backoff_until

    @property
    def entries_allowed(self):
        return (self.healthy and self.state in {RateState.HEALTHY,RateState.CAUTION} and
                self.remaining_budget>self.policy.account_action_reserve and
                self.daily_used()<self.daily_limit-self._reserve('daily'))

    def _weight(self,weight,priority=RequestPriority.EXECUTION,*,observed=False):
        usage=self._usage()
        reserve=self._reserve('ip')
        limit=self.ip_weight_limit if priority==RequestPriority.SAFETY else self.ip_weight_limit-reserve
        if not observed and (usage+weight>limit or self.clock_ms()<self.backoff_until and priority!=RequestPriority.SAFETY):
            raise ExchangeError('RATE_LIMITED')
        self.weights.append((self.clock_ms(),weight))
        if observed and usage+weight>self.ip_weight_limit:
            self._event('RATE_LIMIT_THROTTLED',reason='HISTORY_RESPONSE_EXCEEDED_RESERVED_WEIGHT')

    def reserve_info(self,query,*,priority=None,response_weight=0):
        priority=RequestPriority(priority) if priority is not None else (
            RequestPriority.SAFETY if query in self.SAFETY_INFO else RequestPriority.DECISION)
        with self.lock:
            if priority==RequestPriority.OPTIONAL:
                state=self.state
                if state in {RateState.THROTTLED,RateState.EXHAUSTED,RateState.UNKNOWN}:
                    raise ExchangeError('OPTIONAL_API_THROTTLED')
                interval=self.policy.optional_poll_interval_ms*(4 if state==RateState.CAUTION else 1)
                if self.clock_ms()-self.optional_times.get(query,-interval)<interval:
                    raise ExchangeError('OPTIONAL_API_THROTTLED')
                self.optional_times[query]=self.clock_ms()
            weight=(2 if query in self.SMALL_INFO else 60 if query=='userRole' else 20)+response_weight
            try:self._weight(weight,priority)
            except ExchangeError as exc:
                if str(exc)=='RATE_LIMITED':
                    self._event('INFO_RATE_BUDGET_REJECTED',query=query,weight=weight,
                        priority=priority.value,rolling_weight=self._usage(),
                        ip_limit=self.ip_weight_limit,reserve=self._reserve('ip'),
                        backoff_until=self.backoff_until,source='LOCAL_RATE_GUARD; NO_HTTP_SENT')
                raise

    def observe_info(self,query,response,*,reserved_response_weight=0):
        with self.lock:
            if query=='userRateLimit':
                try:
                    used,cap=response['nRequestsUsed'],response['nRequestsCap']
                    if type(used) is not int or type(cap) is not int or used<0 or cap<0:
                        raise ValueError
                except (KeyError,TypeError,ValueError):
                    raise ExchangeError('INVALID_ACCOUNT_REQUEST_BUDGET') from None
                # A lagging exchange snapshot cannot replenish locally reserved
                # actions until its used count advances past their baseline.
                if self.n_requests_used is not None and used<self.n_requests_used:
                    raise ExchangeError('ACCOUNT_BUDGET_COUNTER_REGRESSED')
                consumed=max(0,used-(self.n_requests_used if self.n_requests_used is not None else used))
                self.reserved_since_snapshot=max(0,self.reserved_since_snapshot-consumed)
                self.n_requests_used,self.n_requests_cap=used,cap
                self.budget=max(0,cap-used)
                self.budget_observed_ms=self.clock_ms()
                with self.journal.transaction():
                    self._persist_budget()
            if query in {'openOrders','frontendOpenOrders'} and isinstance(response,list):
                self.open_orders=len(response)
            if isinstance(response,list) and query in self.HISTORY:
                extra=max(0,len(response)//(60 if query=='candleSnapshot' else 20)-reserved_response_weight)
                if extra:self._weight(extra,RequestPriority.SAFETY,observed=True)

    def reserve_action(self,*,operations=1,creates_order=False,priority=None,kind='order'):
        priority=RequestPriority(priority) if priority is not None else RequestPriority.EXECUTION
        with self.lock:
            fresh=(self.budget_observed_ms is not None and self.remaining_budget is not None and
                   0<=self.clock_ms()-self.budget_observed_ms<=self.policy.budget_max_age_ms and self.open_orders is not None)
            if type(operations) is not int or operations<1 or not fresh or (
                    priority!=RequestPriority.SAFETY and self.clock_ms()<self.backoff_until):
                raise ExchangeError('RATE_LIMITED')
            if creates_order and priority!=RequestPriority.SAFETY and not self.entries_allowed:
                self._event('DAILY_ACTION_RESERVE',remaining=self.remaining_budget)
                raise ExchangeError('ENTRY_API_RESERVE_REQUIRED')
            remaining=self.remaining_budget
            if creates_order and self.open_orders+operations>self.policy.max_open_orders:
                raise ExchangeError('RATE_LIMITED')
            if remaining<operations:
                # Venue's exhausted-budget safety allowance is deliberately
                # restricted to one critical action every ten seconds.
                if (priority!=RequestPriority.SAFETY or operations!=1 or self.last_safety_action_ms is not None and
                        self.clock_ms()-self.last_safety_action_ms<self.policy.exhausted_safety_action_interval_ms):
                    raise ExchangeError('RATE_LIMITED')
            key='daily_actions:'+str(self.clock_ms()//86400000)
            with self.journal.transaction():
                row=self.journal.db.execute('SELECT value FROM controls WHERE name=?',(key,)).fetchone()
                used=int(row[0]) if row else 0
                if used+operations>self.daily_limit:
                    raise ExchangeError('DAILY_ACTION_LIMIT')
                self._weight(1+operations//40,priority)
                self.journal.db.execute('INSERT OR REPLACE INTO controls VALUES (?,?)',(key,str(used+operations)))
                self.journal.db.execute('INSERT INTO api_actions(utc_day,process,signer,session,kind,operations,timestamp_ms) '
                    'VALUES (?,?,?,?,?,?,?)',(self.clock_ms()//86400000,os.getpid(),self.signer_address,
                                            self.journal.session_id,kind,operations,self.clock_ms()))
                self.reserved_since_snapshot+=operations
                if remaining<operations:
                    self.last_safety_action_ms=self.clock_ms()
                self._persist_budget()
            if creates_order:
                self.open_orders+=operations

    def error(self,*,status=None,retry_after_ms=None):
        with self.lock:
            self.recent_errors+=1
            duration=min(self.policy.backoff_max_ms,self.policy.backoff_base_ms*2**min(self.recent_errors-1,10))
            duration=int(duration*(.8+.2*self.jitter()))
            if retry_after_ms is not None:
                # Never shorten venue guidance. The caller's independent wait
                # deadline can terminate instead of retrying before this time.
                duration=max(duration,retry_after_ms)
            self.backoff_until=self.clock_ms()+duration
            self._event('REQUEST_BACKOFF',attempt=self.recent_errors,status=status,delay_ms=duration)
            return duration

    def success(self):
        self.recent_errors=0

    def read(self,query,operation,*,priority=None,request_key=None,expected_items=0,cancel_event=None,
             candle_budget=None,candle_symbol=None):
        """Share identical concurrent public reads; never cache a stale result."""
        from .hyperliquid_client import DEX_QUERIES,COIN_QUERIES,ACCOUNT_QUERIES
        if query not in DEX_QUERIES|COIN_QUERIES|ACCOUNT_QUERIES|{'perpDexs','candleSnapshot','userRole','exchangeStatus','spotMeta','allPerpMetas'}:
            raise ExchangeError('PUBLIC_INFO_QUERY_NOT_ALLOWED')
        entry=None
        if request_key is not None:
            with self.lock:
                entry=self.inflight_reads.get(request_key)
                leader=entry is None
                if leader:
                    entry=dict(done=threading.Event(),value=None,error=None)
                    self.inflight_reads[request_key]=entry
                else:self.coalesced_reads+=1
            if not leader:
                follower_started=time.monotonic()
                while not entry['done'].wait(.1):
                    if cancel_event is not None and cancel_event.is_set():
                        raise ExchangeError('INFO_READ_CANCELLED')
                    if time.monotonic()-follower_started>=self.read_deadline_seconds:
                        raise ExchangeError('INFO_COALESCED_READ_DEADLINE')
                if entry['error'] is not None:raise entry['error']
                return entry['value']
        started=time.monotonic()
        try:
            value=self._read_owned(query,operation,priority=priority,expected_items=expected_items,
                cancel_event=cancel_event,candle_budget=candle_budget,candle_symbol=candle_symbol)
            if entry is not None:entry['value']=value
            return value
        except BaseException as exc:
            code=str(exc) if isinstance(exc,ExchangeError) else 'INFO_READ_INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else type(exc).__name__
            with self.lock:self.read_failures[code]=self.read_failures.get(code,0)+1
            if entry is not None:entry['error']=ExchangeError('INFO_READ_INTERRUPTED') if isinstance(exc,KeyboardInterrupt) else exc
            raise
        finally:
            with self.lock:
                self.max_read_seconds=max(self.max_read_seconds,time.monotonic()-started)
                if entry is not None:
                    self.inflight_reads.pop(request_key,None)
                    entry['done'].set()

    def _read_owned(self,query,operation,*,priority=None,expected_items=0,cancel_event=None,
                    candle_budget=None,candle_symbol=None):
        """Only idempotent /info reads; no signed operation can enter this API."""
        priority=RequestPriority(priority) if priority is not None else (
            RequestPriority.SAFETY if query in self.SAFETY_INFO else RequestPriority.DECISION)
        started=time.monotonic()
        def wait_delay(duration):
            if self.read_progress:self.read_progress('WAITING_FOR_READ_BACKOFF',query=query,
                retry_in_seconds=round(duration/1000,3),next_retry_ms=self.clock_ms()+duration)
            if duration>(self.read_deadline_seconds-(time.monotonic()-started))*1000:
                raise ExchangeError('INFO_READ_WAIT_DEADLINE')
            if cancel_event is None:self.wait(duration)
            elif cancel_event.wait(duration/1000):raise ExchangeError('INFO_READ_CANCELLED')
        for attempt in range(self.policy.read_retry_attempts):
            if cancel_event is not None and cancel_event.is_set():raise ExchangeError('INFO_READ_CANCELLED')
            if time.monotonic()-started>=self.read_deadline_seconds:raise ExchangeError('INFO_READ_DEADLINE')
            delay=max(0,self.backoff_until-self.clock_ms())
            if delay:wait_delay(delay)
            response_weight=expected_items//60 if query=='candleSnapshot' else 0
            if self.read_budget_wait_seconds:
                weight=(2 if query in self.SMALL_INFO else 60 if query=='userRole' else 20)+response_weight
                self.wait_for_read_budget(weight,priority=priority,
                    max_wait_seconds=min(self.read_budget_wait_seconds,self.read_deadline_seconds-(time.monotonic()-started)),
                    cancel_event=cancel_event,progress=self.read_progress)
            if query=='candleSnapshot' and candle_budget is not None:
                candle_budget.reserve(expected_items,**({'symbol':candle_symbol} if candle_symbol else {}))
            self.reserve_info(query,priority=priority,response_weight=response_weight)
            with self.lock:self.read_counts[query]=self.read_counts.get(query,0)+1
            try:
                value=operation()
            except Exception as exc:
                status=getattr(exc,'status_code',None)
                transient=(getattr(exc,'retryable',None) is not False and (getattr(exc,'retryable',False) or
                           isinstance(exc,(TimeoutError,ConnectionError)) or str(exc)=='INFO_REQUEST_FAILED' or
                           status==429 or type(status) is int and 500<=status<600)
                           )
                detail=dict(query=query,attempt=attempt+1,code=str(exc) if isinstance(exc,ExchangeError) else type(exc).__name__,
                    status_code=status,retry_after_ms=getattr(exc,'retry_after_ms',None),retryable=bool(transient))
                self.read_failure_details.append(detail)
                if self.read_progress:self.read_progress('INFO_READ_FAILED',**detail)
                if not transient:
                    raise
                duration=self.error(status=status,retry_after_ms=getattr(exc,'retry_after_ms',None))
                if attempt+1==self.policy.read_retry_attempts:
                    error=ExchangeError('INFO_RETRY_BUDGET_EXHAUSTED');error.last_failure=detail
                    raise error from None
                wait_delay(duration)
                continue
            self.observe_info(query,value,reserved_response_weight=response_weight)
            self.success()
            return value

    def ws_open(self,identity):
        with self.lock:
            now=self.clock_ms()
            self.ws_reconnects=[t for t in self.ws_reconnects if t>now-60000]
            if identity in self.ws_connections or len(self.ws_connections)>=self.policy.max_ws_connections:
                raise ExchangeError('WS_CONNECTION_LIMIT')
            if len(self.ws_reconnects)>=self.policy.ws_reconnects_per_minute:
                raise ExchangeError('WS_RECONNECT_THROTTLED')
            self.ws_reconnects.append(now)
            self.ws_connections[identity]=set()

    def ws_close(self,identity):
        with self.lock:
            self.ws_connections.pop(identity,None)

    def ws_send(self,identity,subscription=None,*,heartbeat=False):
        with self.lock:
            if identity not in self.ws_connections:
                raise ExchangeError('WS_CONNECTION_REQUIRED')
            subscriptions=self.ws_connections[identity]
            key=json.dumps(subscription,sort_keys=True) if subscription is not None else None
            if key in subscriptions:
                return False
            if key is not None and sum(map(len,self.ws_connections.values()))>=self.policy.max_ws_subscriptions:
                raise ExchangeError('WS_SUBSCRIPTION_LIMIT')
            if subscription is not None and 'user' in subscription:
                users={json.loads(s)['user'].lower() for connection in self.ws_connections.values()
                       for s in connection if 'user' in json.loads(s)}
                users.add(subscription['user'].lower())
                if len(users)>self.policy.max_ws_unique_users:
                    raise ExchangeError('WS_UNIQUE_USER_LIMIT')
            self.ws_messages=[row for row in self.ws_messages if row[0]>self.clock_ms()-60000]
            if len(self.ws_messages)>=self.policy.max_ws_messages_per_minute:
                raise ExchangeError('WS_MESSAGE_LIMIT')
            self.ws_messages.append((self.clock_ms(),bool(heartbeat)))
            if key is not None:
                subscriptions.add(key)
            return True

    def report(self):
        with self.lock:
            return self._report_owned()

    def _report_owned(self):
        self._usage()
        self.ws_reconnects=[t for t in self.ws_reconnects if t>self.clock_ms()-60000]
        self.ws_messages=[r for r in self.ws_messages if r[0]>self.clock_ms()-60000]
        return dict(state=self.state.value,policy=asdict(self.policy),ip_weight=self._usage(),
            public_read_blocked=bool(self.clock_ms()<self.backoff_until or
                self._usage()>=self.ip_weight_limit-self.policy.ip_safety_reserve),
            account_requests_used=self.n_requests_used,account_requests_cap=self.n_requests_cap,
            remaining_budget=self.remaining_budget,budget_observed_ms=self.budget_observed_ms,
            daily_actions=self.daily_used(),daily_limit=self.daily_limit,entries_allowed=self.entries_allowed,
            open_orders=self.open_orders,backoff_until_ms=self.backoff_until,
            websocket=dict(connections=len(self.ws_connections),subscriptions=sum(map(len,self.ws_connections.values())),
                outgoing_messages=len(self.ws_messages),heartbeats=sum(r[1] for r in self.ws_messages),
                reconnects_last_minute=len(self.ws_reconnects)),
            public_reads=dict(upstream_by_operation=dict(self.read_counts),failures=dict(self.read_failures),
                pending=len(self.inflight_reads),coalesced=self.coalesced_reads,max_seconds=self.max_read_seconds,
                failure_details=list(self.read_failure_details)))
