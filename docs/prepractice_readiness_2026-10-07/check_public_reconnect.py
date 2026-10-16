"""Deliberately close one public socket and observe real reconnect/REST repair."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData, ParMarketDataEngine
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze

OUT = Path(__file__).resolve().parent / 'public_reconnect.json'
if OUT.exists():
    raise RuntimeError('PRESERVE_EXISTING_PUBLIC_RECONNECT_EVIDENCE')
require_paper_migration()
verify_strategy_freeze()
stop = threading.Event()
events = []
errors = []
connections = []
disconnects = []


class ObservedSocket:
    def __init__(self, socket, number):
        self.socket = socket
        self.number = number
        self.received = 0
        self.subscriptions = []
    def send(self, value):
        self.subscriptions.append(json.loads(value))
        return self.socket.send(value)
    def recv(self):
        if self.number == 1 and self.received == 10:
            disconnects.append(dict(source='INTENTIONAL_LOCAL_PUBLIC_WS_CLOSE',
                                    observed_at_utc=datetime.now(timezone.utc).isoformat()))
            self.socket.close()
            self.received += 1
            return ''
        value = self.socket.recv()
        if value:
            self.received += 1
        return value
    def close(self):
        return self.socket.close()


def connect():
    socket = ObservedSocket(ParMarketDataEngine._connect(), len(connections) + 1)
    connections.append(socket)
    return socket


client = HyperliquidClient()
report = dict(network='testnet', dex='par', execution_mode='PAPER', allow_live_orders=False,
              exchange_orders_submitted=0, account_actions_submitted=0, signer_constructed=False,
              scope='REAL_PUBLIC_SOCKET_RECONNECT_ONLY; no account or order recovery certification')
try:
    client.startup()
    engine = ParMarketDataEngine(HyperliquidMarketData(client), symbols=['par:BTC'],
                                connect=connect, include_trades=True, on_lifecycle=events.append)
    def worker():
        try:
            engine.run(stop, max_reconnects=2)
        except Exception as exc:
            errors.append(type(exc).__name__ + ':' + str(exc))
            stop.set()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not stop.is_set():
        if engine.connected and engine.reconciled:
            engine.acknowledge_recovery(engine.recovery_generation)
            if engine.recovery_generation >= 2 and len(connections) >= 2 and connections[1].received >= 1:
                report['quote_after_reconnect'] = asdict(engine.get_quote('par:BTC'))
                report['observations_after_reconnect'] = engine.get_observations('par:BTC')
                report['completed_bars_after_reconnect'] = len(engine.get_completed_candles('par:BTC'))
                report['recovered_before_shutdown'] = True
                break
        stop.wait(.1)
    report.setdefault('recovered_before_shutdown', False)
    stop.set()
    thread.join(timeout=12)
    report.update(worker_stopped=not thread.is_alive(), lifecycle_events=events,
                  intentional_disconnects=disconnects, errors=errors,
                  reconnections=engine.reconnections, recovery_generation=engine.recovery_generation,
                  connection_subscriptions=[c.subscriptions for c in connections], messages=engine.messages)
    report['passed'] = (report['recovered_before_shutdown'] and not errors and report['worker_stopped']
                        and len(disconnects) == 1 and engine.reconnections == 1)
except Exception as exc:
    report.update(passed=False, error_type=type(exc).__name__)
finally:
    stop.set()
    client.close()
    report['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(report, indent=2, default=str) + '\n')
print(json.dumps(dict(path=str(OUT), passed=report['passed'],
                     reconnections=report.get('reconnections'))))
raise SystemExit(0 if report['passed'] else 1)
