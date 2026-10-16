"""Raw team-account WebSocket notifications; REST remains accounting authority."""
import json
import threading
from .base_exchange import ExchangeError
from .hyperliquid_client import TESTNET_WS_URL
from .live_readiness import valid_address


class LiveAccountStream:
    CHANNELS=('userFills','orderUpdates','userEvents','userFundings')
    def __init__(self, team_address, recovery, executor, *, clock_ms, connector=None):
        if not valid_address(team_address) or team_address.lower()!=recovery.account.team_address.lower():
            raise ExchangeError('TEAM_ACCOUNT_STREAM_IDENTITY_REQUIRED')
        self.team_address=team_address
        self.recovery=recovery
        self.executor=executor
        self.clock_ms=clock_ms
        self.connector=connector
        self.socket=None
        self.connected=False
        self.ready=False
        self.generation=0
        self.reconciled_generation=None
        self.last_received_ms=None
        self.last_ping_ms=None
        self.pong_pending_ms=None
        self.subscribed=set()
        self.pending=True
        self.lock=threading.RLock()
        self.reconnect_failures=0
        self.retry_after_ms=0
        self.rates=getattr(executor,'rate_limits',None)
        self.budget_identity='account:'+str(id(self))

    def _pause(self, reason):
        self.ready=False
        self.executor.entries_paused=True
        self.recovery.revoke(reason)
        coordinator=getattr(self.recovery,'startup_coordinator',None)
        if coordinator is not None:
            coordinator.post_stream_verified=False
            if 'DISCONNECT' in reason or 'RECONNECT' in reason:
                coordinator.before_stream_verified=False
            coordinator.transition('ENTRY_PAUSED',reason)

    def disconnect(self, reason='ACCOUNT_WEBSOCKET_DISCONNECTED'):
        with self.lock:
            self._pause(reason)
            self.connected=False
            self.pending=True
            self.subscribed.clear()
            if self.socket is not None:
                try:
                    self.socket.close()
                except Exception:
                    pass
            self.socket=None
            if self.rates is not None:
                self.rates.ws_close(self.budget_identity)

    def connect(self):
        with self.lock:
            self.disconnect('ACCOUNT_STREAM_RECONNECT_REQUIRES_REST')
            if self.clock_ms()<self.retry_after_ms:
                raise ExchangeError('ACCOUNT_RECONNECT_BACKOFF')
            connector=self.connector
            if connector is None:
                from websocket import create_connection
                connector=create_connection
            try:
                if self.rates is not None:
                    self.rates.ws_open(self.budget_identity)
                self.socket=connector(TESTNET_WS_URL,timeout=1)
                self.generation+=1
                self.connected=True
                self.last_received_ms=self.clock_ms()
                self.last_ping_ms=self.clock_ms()
                self.pong_pending_ms=None
                for channel in self.CHANNELS:
                    subscription=dict(type=channel,user=self.team_address)
                    if self.rates is not None and not self.rates.ws_send(self.budget_identity,subscription):
                        continue
                    self.socket.send(json.dumps(dict(method='subscribe',
                        subscription=subscription)))
                self.reconnect_failures=0
            except Exception:
                self.reconnect_failures+=1
                self.retry_after_ms=self.clock_ms()+min(30000,1000*2**min(self.reconnect_failures-1,5))
                self.disconnect('ACCOUNT_STREAM_CONNECT_FAILED')
                raise ExchangeError('ACCOUNT_STREAM_CONNECT_FAILED') from None

    def handle(self, message):
        with self.lock:
            try:
                value=json.loads(message) if isinstance(message,str) else message
                channel=value['channel']
                data=value.get('data')
                if channel=='pong':
                    self.pong_pending_ms=None
                elif channel=='subscriptionResponse':
                    subscription=data['subscription']
                    if subscription.get('user','').lower()!=self.team_address.lower() or subscription.get('type') not in self.CHANNELS:
                        raise ExchangeError('WRONG_ACCOUNT_SUBSCRIPTION')
                    self.subscribed.add(subscription['type'])
                elif channel in self.CHANNELS:
                    if isinstance(data,dict) and 'user' in data and data['user'].lower()!=self.team_address.lower():
                        raise ExchangeError('WRONG_ACCOUNT_STREAM_USER')
                    # A stream message wakes stable REST reconciliation; it never
                    # invents missing closedPnl, fee or funding fields.
                    self.pending=True
                    self._pause('ACCOUNT_EVENT_REQUIRES_RECONCILIATION')
                    self.recovery.journal.event('ACCOUNT_STREAM_EVENT',self.clock_ms(),
                                                channel=channel,generation=self.generation)
                else:
                    raise ExchangeError('UNEXPECTED_ACCOUNT_CHANNEL')
                self.last_received_ms=self.clock_ms()
            except Exception:
                self.disconnect('INVALID_ACCOUNT_STREAM_EVENT')
                raise ExchangeError('INVALID_ACCOUNT_STREAM_EVENT') from None

    def poll(self):
        if not self.connected:
            raise ExchangeError('ACCOUNT_STREAM_NOT_CONNECTED')
        now=self.clock_ms()
        if (self.last_received_ms is None or now-self.last_received_ms>45000 or
                self.pong_pending_ms is not None and now-self.pong_pending_ms>10000):
            self.disconnect('ACCOUNT_STREAM_HEARTBEAT_EXPIRED')
            raise ExchangeError('ACCOUNT_STREAM_HEARTBEAT_EXPIRED')
        if now-self.last_ping_ms>=30000:
            if self.rates is not None:
                self.rates.ws_send(self.budget_identity,heartbeat=True)
            self.socket.send(json.dumps(dict(method='ping')))
            self.last_ping_ms=now
            self.pong_pending_ms=now
        try:
            message=self.socket.recv()
            if not message:
                raise ExchangeError('ACCOUNT_STREAM_CLOSED')
            self.handle(message)
        except TimeoutError:
            return
        except Exception as exc:
            from websocket import WebSocketTimeoutException
            if isinstance(exc,WebSocketTimeoutException):
                return
            self.disconnect()
            raise ExchangeError('ACCOUNT_WEBSOCKET_DISCONNECTED') from None

    def reconcile(self):
        """Run on the strategy owner thread after every reconnect or account event."""
        with self.lock:
            generation=self.generation
            if not self.connected or self.subscribed!=set(self.CHANNELS):
                self._pause('ACCOUNT_SUBSCRIPTIONS_NOT_ACKNOWLEDGED')
                return False
            coordinator=getattr(self.recovery,'startup_coordinator',None)
            recovered=coordinator.after_stream(generation) if coordinator is not None else self.recovery.recover().ready
            if not self.connected or generation!=self.generation or not recovered:
                self._pause('ACCOUNT_RECONCILIATION_NOT_READY')
                return False
            self.pending=False
            self.ready=True
            self.reconciled_generation=generation
            self.executor.entries_paused=False
            protection=getattr(self.executor,'protection',None)
            if protection is not None:
                protection.ensure_all()
                self.executor.entries_paused=not protection.entries_allowed
            return True

    @property
    def healthy(self):
        return (self.connected and self.ready and not self.pending and
                self.reconciled_generation==self.generation and self.last_received_ms is not None and
                0<=self.clock_ms()-self.last_received_ms<=45000 and
                (self.pong_pending_ms is None or self.clock_ms()-self.pong_pending_ms<=10000))
