"""Public-stream liveness evidence. No strategy rules or exchange actions."""
import json
import random
import time

from .base_exchange import ExchangeError


class FeedTransportHealth:
    PING_SECONDS = 30
    PONG_SECONDS = 10
    SILENCE_SECONDS = 45

    def __init__(self, *, monotonic=None, wall_ms=None, jitter=None):
        self.monotonic = monotonic or time.monotonic
        self.wall_ms = wall_ms or (lambda: time.time_ns() // 1000000)
        self.jitter = jitter or random.random
        self.generation = 0
        self.current = None
        self.events = []
        self.desired = set()
        self.sent = set()
        self.confirmed = set()
        self.duplicates_prevented = 0
        self.max_receiver_gap_seconds = 0

    @staticmethod
    def key(subscription):
        if isinstance(subscription,dict) and subscription.get('type')=='l2Book':
            subscription=dict(subscription)
            # The venue expands these omitted defaults in its acknowledgement.
            # Retain nondefault precision/fast options in the subscription identity.
            for name in ('nSigFigs','mantissa'):
                if subscription.get(name) is None:subscription.pop(name,None)
            if subscription.get('fast') is False:subscription.pop('fast')
        return json.dumps(subscription, sort_keys=True, separators=(',', ':'))

    def begin(self, subscriptions):
        now = self.monotonic()
        self.generation += 1
        self.desired = {self.key(s['subscription']) for s in subscriptions}
        self.sent = set()
        self.confirmed = set()
        self.current = dict(connection_id=f'public-{self.generation}', generation=self.generation,
            connection_started_at_ms=self.wall_ms(), started_monotonic=now,
            last_poll_monotonic=now, last_poll_wall_ms=self.wall_ms(),
            last_any_message_at_ms=None, last_trade_message_at_ms=None,
            last_book_message_at_ms=None, last_candle_message_at_ms=None,
            last_context_message_at_ms=None, outgoing_ping_at_ms=None, pong_at_ms=None,
            last_receive_monotonic=now, last_ping_monotonic=now, pending_ping_monotonic=None,
            transport_state='RECOVERING', close_code=None, close_reason=None)
        return self.generation

    def subscription_sent(self, subscription):
        key = self.key(subscription)
        if key in self.sent:
            self.duplicates_prevented += 1
            return False
        self.sent.add(key)
        return True

    def receive(self, message, generation):
        if generation != self.generation:
            return False
        now = self.monotonic()
        c = self.current
        c['last_receive_monotonic'] = now
        c['last_any_message_at_ms'] = self.wall_ms()
        channel = message.get('channel')
        names = {'trades':'trade', 'l2Book':'book', 'candle':'candle', 'activeAssetCtx':'context'}
        if channel in names:
            c['last_' + names[channel] + '_message_at_ms'] = self.wall_ms()
        if channel == 'pong':
            c['pong_at_ms'] = self.wall_ms()
            c['pending_ping_monotonic'] = None
        if channel == 'subscriptionResponse':
            data = message.get('data', {})
            if isinstance(data, dict) and data.get('method') == 'subscribe':
                key = self.key(data.get('subscription'))
                if key not in self.desired:
                    raise ExchangeError('UNEXPECTED_SUBSCRIPTION_ACK')
                self.confirmed.add(key)
        return True

    def poll(self):
        c = self.current
        now = self.monotonic()
        wall = self.wall_ms()
        gap = max(0, now-c['last_poll_monotonic'])
        self.max_receiver_gap_seconds = max(self.max_receiver_gap_seconds, gap)
        wall_gap = (wall-c['last_poll_wall_ms'])/1000
        c['last_poll_monotonic'], c['last_poll_wall_ms'] = now, wall
        if wall_gap > gap+15:
            raise ExchangeError('HOST_SLEEP_OR_CLOCK_GAP_DETECTED')
        if gap > self.SILENCE_SECONDS:
            # Evidence of suspension/processing delay; not proof of venue failure.
            raise ExchangeError('HOST_PROCESSING_GAP_DETECTED')
        if now-c['last_receive_monotonic'] >= self.SILENCE_SECONDS or (
                c['pending_ping_monotonic'] is not None and
                now-c['pending_ping_monotonic'] >= self.PONG_SECONDS):
            raise ExchangeError('STREAM_HEARTBEAT_STALE')
        return now-c['last_ping_monotonic'] >= self.PING_SECONDS

    def ping_sent(self):
        now = self.monotonic()
        self.current.update(last_ping_monotonic=now, pending_ping_monotonic=now,
                            outgoing_ping_at_ms=self.wall_ms())

    def backoff(self, failures):
        return min(30, 2**min(max(0, failures-1), 5)) * (.8+.2*self.jitter())

    def disconnect(self, reason, *, pending_rest=0, rate_report=None, backoff=0):
        if not self.current:
            return
        c = self.current
        if c.get('disconnected_at_ms') is not None:
            return
        c.update(disconnected_at_ms=self.wall_ms(),
                 connection_age_seconds=max(0, self.monotonic()-c['started_monotonic']),
                 transport_state='DISCONNECTED', client_exception=reason,
                 pending_rest_calls=pending_rest, rate_budget=rate_report,
                 backoff_seconds=backoff, subscription_count=len(self.sent),
                 subscription_identities=sorted(self.sent), confirmed_subscriptions=len(self.confirmed))
        c['attribution'] = ('HOST_OR_CLIENT' if reason.startswith('HOST_') else
                            'SERVER_CLOSE' if c['close_code'] is not None else 'UNCERTAIN')
        self.events.append(dict(c))

    def report(self):
        current = dict(self.current) if self.current else None
        return dict(current=current, desired_count=len(self.desired), sent_count=len(self.sent),
            confirmed_count=len(self.confirmed), missing_acknowledgements=sorted(self.desired-self.confirmed),
            duplicate_subscriptions=0, duplicates_prevented=self.duplicates_prevented,
            max_receiver_gap_seconds=self.max_receiver_gap_seconds, connections=list(self.events))
