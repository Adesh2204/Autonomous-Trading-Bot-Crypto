"""Bounded read-only par recorder. No orders, account query, signer or wallet."""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from research_intelligence.common import digest, immutable_json, source_identity, canonical
from research_intelligence.evidence import EvidenceWriter, require_public, PUBLIC_CHANNELS,candle_key
from exchange.hyperliquid_client import HyperliquidClient, RequestsInfoTransport, TESTNET_API_URL
from exchange.hyperliquid_market_data import HyperliquidMarketData, ParMarketDataEngine
from exchange.execution_journal import ExecutionJournal
from exchange.rate_limits import HyperliquidRateLimitManager
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def ms(): return time.time_ns()//1_000_000
def portable(value): return json.loads(json.dumps(value, default=str, allow_nan=False))


class CaptureTransport:
    def __init__(self, writer, transport, stop=None):
        self.writer = writer; self.transport = transport
        self.stop=stop
        self.dexes = None; self.last_context_received = None

    def __call__(self, payload):
        require_public(payload)
        if self.stop is not None and self.stop.is_set():
            from exchange.base_exchange import ExchangeError
            raise ExchangeError('CAPTURE_STOP_REQUESTED')
        sent = ms(); result = self.transport(payload)
        with self.writer.lock:
            received = ms()
            self.writer.append('INFO', dict(request=payload, response=result, sent_ms=sent), received)
        if payload['type'] == 'perpDexs': self.dexes = deepcopy(result)
        if payload['type'] == 'metaAndAssetCtxs': self.last_context_received = received
        return result

    def close(self): self.transport.close()


class CaptureClient(HyperliquidClient):
    def __init__(self,*args,**kwargs):
        self.request_lock=threading.RLock(); super().__init__(*args,**kwargs)
    def startup(self):
        with self.request_lock: return super().startup()
    def post_info(self,*args,**kwargs):
        with self.request_lock: return super().post_info(*args,**kwargs)


class CaptureMarket(HyperliquidMarketData):
    # Preserve the exact response receipt clock while REST repair and streaming
    # reconnect can request concurrently. This adapter is recorder-only.
    def get_candles(self,*args,**kwargs):
        with self.client.request_lock: return super().get_candles(*args,**kwargs)
    def get_asset_contexts(self):
        with self.client.request_lock: return super().get_asset_contexts()
    def get_orderbook(self,*args,**kwargs):
        with self.client.request_lock: return super().get_orderbook(*args,**kwargs)


class CaptureEngine(ParMarketDataEngine):
    def __init__(self, *args, writer, capture_transport, **kwargs):
        super().__init__(*args, **kwargs)
        self.writer = writer; self.capture_transport = capture_transport

    def ingest(self, message):
        value = json.loads(message) if isinstance(message, str) else deepcopy(message)
        if value.get('channel') not in PUBLIC_CHANNELS:
            raise ValueError('PUBLIC_STREAM_CHANNEL_REQUIRED')
        with self.writer.lock: self.writer.append('STREAM', value, ms())
        super().ingest(value)

    def reconcile_history(self):
        super().reconcile_history()
        # Correct receipt evidence locally: the production engine's seed context
        # clock is the start of repair. The recorder proves its actual receipt.
        with self._lock:
            self.context_times = dict.fromkeys(self.symbols, self.capture_transport.last_context_received)

    def get_completed_candles(self,symbol):
        # A pre-close WebSocket update is not a proven final bar. Keep raw
        # messages, but wait for a received completed observation for strategy.
        return [c for c in super().get_completed_candles(symbol)
            if c.received_timestamp_ms is not None and c.received_timestamp_ms>=c.timestamp_ms+60000]

    def finalize_completed(self,stop,now_ms):
        end=now_ms//60000*60000-1; start=end+1-2*60000; updated=0
        with self._lock:
            generation=self.recovery_generation
            if not self.connected or not self.reconciled: return 0
        for symbol in self.symbols:
            if stop.is_set(): break
            bars=self.market.get_candles(symbol,start,end,now_ms=now_ms)
            with self._lock:
                if not self.reconciled or generation!=self.recovery_generation: return updated
                for c in bars:
                    if c.received_timestamp_ms>=c.timestamp_ms+60000:
                        self.candles[symbol][c.timestamp_ms]=c; updated+=1
                for key in sorted(self.candles[symbol])[:-self.history_bars]: del self.candles[symbol][key]
        return updated


def capture(args):
    require_paper_migration(); verify_strategy_freeze()
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    policy = json.loads(Path(args.policy).read_text())
    anchors = json.loads(Path(args.anchor_config).read_text())
    manifest = dict(schema_version=1, source='PUBLIC_TESTNET_PAR_FORWARD_CAPTURE',
        endpoint=TESTNET_API_URL+'/info', network='HYPERLIQUID_TESTNET', dex='par',
        created_ms=ms(), source_identity=source_identity(), parameters=policy, anchor_config=anchors,
        history_bars=args.history_bars, scan_interval_ms=int(args.scan_seconds*1000),
        sample_interval_ms=int(args.sample_seconds*1000), maximum_duration_seconds=args.duration_seconds,
        execution_mode='PAPER', allow_live_orders=False, account_queries=False,
        assumptions='Recorded displayed BBO and mark/context observations only. Paper funding remains an observed boundary estimate.',
        authentication_note='Local checksums establish file consistency, not exchange-signed authenticity.')
    manifest['sha256'] = digest(manifest); immutable_json(output/'capture_manifest.json', manifest)
    writer = EvidenceWriter(output/'evidence.jsonl')
    stop = threading.Event(); failures = []; worker = None; repair_worker=None; client = None; journal = None
    frames = 0; status = 'FAILED'; details = {}
    try:
        transport = CaptureTransport(writer, RequestsInfoTransport(timeout=10),stop)
        # Synthetic journal identity is local rate accounting only; never queried.
        journal = ExecutionJournal(output/'public_rate_budget.sqlite', session_id='public-research-capture', team_address='0x'+'0'*40)
        rates = HyperliquidRateLimitManager(journal, wait=lambda delay: stop.wait(min(delay/1000, 30)))
        client = CaptureClient(transport, rate_limits=rates)
        client.startup()
        def lifecycle(e):
            with writer.lock: writer.append('HEALTH',e,ms())
        engine = CaptureEngine(CaptureMarket(client), history_bars=args.history_bars,
            writer=writer, capture_transport=transport,
            on_lifecycle=lifecycle)
        def run():
            try: engine.run(stop)
            except Exception as exc:
                failures.append(type(exc).__name__+':'+str(exc)); stop.set()
        worker = threading.Thread(target=run, daemon=True); worker.start()
        def repair():
            last_minute=None
            while not stop.is_set():
                now=ms()
                if engine.reconciled and now//60000!=last_minute:
                    # The initial 3,000-bar history consumes most of the minute
                    # budget. Wait for enough weight for all ten finalization
                    # reads instead of issuing a partial burst at midnight/minute.
                    if rates.report()['ip_weight']+20*len(engine.symbols)>rates.ip_weight_limit-rates.policy.ip_safety_reserve:
                        stop.wait(.25); continue
                    last_minute=now//60000
                    try: engine.finalize_completed(stop,now)
                    except Exception as exc:
                        with writer.lock:
                            writer.append('HEALTH',dict(phase='COMPLETED_CANDLE_RECEIPT_READ_FAILED',
                                reason=type(exc).__name__+':'+str(exc)),ms())
                stop.wait(.25)
        repair_worker=threading.Thread(target=repair,daemon=True); repair_worker.start()
        started = time.monotonic(); next_scan = -1; last_history_minute = None; saved_candles={}; previous_generation=None
        while not stop.is_set() and time.monotonic()-started < args.duration_seconds:
            with engine._lock:
                if engine.connected and engine.reconciled and client.ready:
                    now = ms(); minute = now//60000; scan = now >= next_scan
                    histories = {}
                    replace_history=previous_generation!=engine.recovery_generation
                    if scan or minute != last_history_minute or replace_history:
                        for s in engine.symbols:
                            current=engine.get_completed_candles(s)
                            history_keys={c.timestamp_ms:candle_key(c) for c in current}
                            histories[s]=[portable(asdict(c)) for c in current if replace_history or saved_candles.get(s,{}).get(c.timestamp_ms)!=history_keys[c.timestamp_ms]]
                            saved_candles[s]=history_keys
                        last_history_minute = minute
                    frame = dict(decision_ms=ms(), scan=scan, metadata=deepcopy(client.metadata), dexes=deepcopy(transport.dexes),
                        books={s:portable(asdict(b)) for s,b in engine.books.items()}, contexts=deepcopy(engine.contexts),
                        context_times=deepcopy(engine.context_times), histories=histories, connected=True,
                        generation=engine.recovery_generation, unavailable_books=deepcopy(engine.unavailable_books),
                        history_mode='REPLACE' if replace_history else 'APPEND',history_limit=args.history_bars)
                    with writer.lock: writer.append('FRAME', frame, ms())
                    frames += 1
                    previous_generation=engine.recovery_generation
                    if scan: next_scan = frame['decision_ms']+manifest['scan_interval_ms']
            stop.wait(args.sample_seconds)
        if failures: raise ValueError(failures[0])
        status = 'COMPLETE'
        details = dict(frames=frames, rate_state=rates.report(), elapsed_seconds=time.monotonic()-started)
        return output
    except KeyboardInterrupt:
        status = 'INTERRUPTED'; details = dict(frames=frames, reason='USER_INTERRUPTED')
        return output
    except Exception as exc:
        details = dict(frames=frames, reason=type(exc).__name__+':'+str(exc)); raise
    finally:
        stop.set()
        for task in (worker,repair_worker):
            if task: task.join(timeout=12)
        if any(task and task.is_alive() for task in (worker,repair_worker)):
            status='FAILED'; details['reason']='RECORDER_WORKER_DID_NOT_STOP'
        if client: client.close()
        if journal: journal.close()
        writer.close(output/'capture_completion.json', status=status, details=details)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--policy', default=str(ROOT/'docs/paper_policy.example.json'))
    p.add_argument('--anchor-config', default=str(ROOT/'research/configurations/anchor_policies.json'))
    p.add_argument('--duration-seconds', type=float, default=300)
    p.add_argument('--sample-seconds', type=float, default=1)
    p.add_argument('--scan-seconds', type=float, default=300)
    p.add_argument('--history-bars', type=int, default=3000)
    a = p.parse_args()
    if not 1 <= a.duration_seconds <= 7776000 or not .25 <= a.sample_seconds <= 2 or not 60 <= a.scan_seconds <= 3600 or not 1800 <= a.history_bars <= 5000:
        p.error('duration 1–7776000 (90 days); sample .25–2; scan 60–3600 seconds; history 1800–5000 bars')
    try:
        path = capture(a)
        if json.loads((path/'capture_completion.json').read_text())['status']=='FAILED':
            raise ValueError('CAPTURE_CLEANUP_FAILED')
        print(json.dumps(dict(output=str(path.resolve()), exchange_orders_submitted=0)))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print('Public capture stopped: '+str(exc), file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
