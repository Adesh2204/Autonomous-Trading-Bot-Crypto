"""Priority-aware shared API budgets; signed actions are never retried here."""
from dataclasses import asdict
import json
import os
import random
import threading
import time
from .base_exchange import ExchangeError
from .reliability_policy import HyperliquidRatePolicy,RequestPriority,RateState


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

    def reserve_info(self,query,*,priority=None):
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
            self._weight(2 if query in self.SMALL_INFO else 60 if query=='userRole' else 20,priority)

    def observe_info(self,query,response):
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
                self._weight(len(response)//(60 if query=='candleSnapshot' else 20),RequestPriority.SAFETY,observed=True)

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
                duration=max(duration,min(self.policy.backoff_max_ms,retry_after_ms))
            self.backoff_until=self.clock_ms()+duration
            self._event('REQUEST_BACKOFF',attempt=self.recent_errors,status=status,delay_ms=duration)
            return duration

    def success(self):
        self.recent_errors=0

    def read(self,query,operation,*,priority=None):
        """Only idempotent /info reads; no signed operation can enter this API."""
        priority=RequestPriority(priority) if priority is not None else (
            RequestPriority.SAFETY if query in self.SAFETY_INFO else RequestPriority.DECISION)
        for attempt in range(self.policy.read_retry_attempts):
            delay=max(0,self.backoff_until-self.clock_ms())
            if delay and priority!=RequestPriority.SAFETY:
                self.wait(delay)
            self.reserve_info(query,priority=priority)
            try:
                value=operation()
            except Exception as exc:
                status=getattr(exc,'status_code',None)
                transient=(isinstance(exc,(TimeoutError,ConnectionError)) or str(exc)=='INFO_REQUEST_FAILED' or
                           status==429 or type(status) is int and 500<=status<600)
                if not transient:
                    raise
                duration=self.error(status=status,retry_after_ms=getattr(exc,'retry_after_ms',None))
                if attempt+1==self.policy.read_retry_attempts:
                    raise ExchangeError('INFO_RETRY_BUDGET_EXHAUSTED') from None
                self.wait(duration)
                continue
            self.observe_info(query,value)
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
        self._usage()
        self.ws_reconnects=[t for t in self.ws_reconnects if t>self.clock_ms()-60000]
        self.ws_messages=[r for r in self.ws_messages if r[0]>self.clock_ms()-60000]
        return dict(state=self.state.value,policy=asdict(self.policy),ip_weight=self._usage(),
            account_requests_used=self.n_requests_used,account_requests_cap=self.n_requests_cap,
            remaining_budget=self.remaining_budget,budget_observed_ms=self.budget_observed_ms,
            daily_actions=self.daily_used(),daily_limit=self.daily_limit,entries_allowed=self.entries_allowed,
            open_orders=self.open_orders,backoff_until_ms=self.backoff_until,
            websocket=dict(connections=len(self.ws_connections),subscriptions=sum(map(len,self.ws_connections.values())),
                outgoing_messages=len(self.ws_messages),heartbeats=sum(r[1] for r in self.ws_messages),
                reconnects_last_minute=len(self.ws_reconnects)))
