"""Read-only par startup, candles and BBO verification. No wallet or orders."""
import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient, TESTNET_API_URL
from exchange.hyperliquid_market_data import HyperliquidMarketData, ParMarketDataEngine
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', default='par:BTC')
    parser.add_argument('--bars', type=int, default=60)
    parser.add_argument('--stream-seconds', type=float, default=0)
    parser.add_argument('--signals', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.bars <= 5000 or not 0 <= args.stream_seconds <= 60:
        parser.error('bars must be 1–5000; stream-seconds must be 0–60')
    client = HyperliquidClient()
    report = {'read_only': True, 'private_key_required': False, 'orders_submitted': 0,
              'endpoint': TESTNET_API_URL, 'dex': 'par'}
    try:
        report['migration_policy'] = require_paper_migration()
        report['strategy_freeze'] = verify_strategy_freeze()
        specs = client.startup()
        report['checked_at_ms'] = client.clock_ms()
        report['dex_index'] = client.dex_index
        report['markets'] = [asdict(spec) for spec in specs.values()]
        market = HyperliquidMarketData(client)
        report['quote'] = asdict(market.get_quote(args.symbol))
        end = client.clock_ms() // 60_000 * 60_000 - 1
        candles = market.get_candles(args.symbol, end + 1 - args.bars * 60_000, end)
        report['completed_candle_count'] = len(candles)
        if candles:
            report['latest_completed_candle'] = asdict(candles[-1])
        if args.signals and candles:
            from frozen_strategy import FrozenStrategy
            evaluated = FrozenStrategy(market).evaluate_candles(candles)
            last = evaluated.iloc[-1]
            report['latest_signal'] = {key: (None if last.get(key) is None else str(last.get(key)))
                                      for key in ('Signal_Type', 'Buy_Signal', 'Breakout_Signal',
                                                  'Sell_Signal', 'Breakdown_Sell_Signal')}
        if args.stream_seconds:
            engine = ParMarketDataEngine(market, [args.symbol], history_bars=args.bars)
            stop = threading.Event()
            timer = threading.Timer(args.stream_seconds, stop.set)
            timer.start()
            try:
                engine.run(stop)
            finally:
                timer.cancel()
                stop.set()
            report['stream'] = {'messages': engine.messages, 'reconnections': engine.reconnections,
                                'last_error': engine.last_error,
                                'completed_candles': len(engine.get_completed_candles(args.symbol))}
            if not engine.messages:
                raise ExchangeError('NO_PUBLIC_STREAM_DATA_RECEIVED')
        report['passed'] = True
    except (ExchangeError, ValueError, RuntimeError) as exc:
        report.update(passed=False, error=type(exc).__name__, reason=str(exc))
    finally:
        client.close()
    encoded = json.dumps(report, indent=2, default=lambda value: str(value) if isinstance(value, Decimal) else str(value))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n')
    print(encoded)
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
