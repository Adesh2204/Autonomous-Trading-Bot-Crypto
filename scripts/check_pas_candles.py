"""Unsigned PAS BTC/EWY completed 1m data check; never certifies live activation.

The 300-candle/minute REST budget is shared by both assets, so the second
300-bar request may wait for capacity. No signer, account settings or order
transport is imported. Missing venue bars remain missing.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time

os.environ['ANCHORIUM_PUBLIC_ONLY'] = 'true'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData, PasMarketDataEngine
from exchange.market_health import validate_history
from exchange.candle_audit import PublicCandleAudit
from venue_config import require_paper_migration


REQUIRED_BARS = 300
MAX_CANDLE_AGE_MS = 120000


def candle_status(symbol, candles, now_ms, start_ms, end_ms):
    """Describe real observations; an empty sequence is never 'consecutive'."""
    reasons = []
    try:
        validate_history(symbol, candles, now_ms, REQUIRED_BARS)
    except (ExchangeError, ValueError, TypeError) as exc:
        reasons.append(str(exc))
    last = candles[-1].timestamp_ms if candles else None
    age = None if last is None else now_ms - (last + 60000)
    if age is None or not 0 <= age <= MAX_CANDLE_AGE_MS:
        reasons.append('COMPLETED_CANDLE_STALE_OR_MISSING')
    timestamps = [c.timestamp_ms for c in candles]
    expected = set(range(start_ms, end_ms + 1, 60000))
    missing = sorted(expected - set(timestamps))
    if missing:
        reasons.append('REQUESTED_COMPLETED_WINDOW_INCOMPLETE')
    consecutive = bool(candles) and all(b - a == 60000 for a, b in zip(timestamps, timestamps[1:]))
    tail = 0
    for stamp in reversed(timestamps):
        if tail and timestamps[-1] - stamp != tail * 60000:
            break
        tail += 1
    return dict(symbol=symbol, data_gate_passed=not reasons, reasons=list(dict.fromkeys(reasons)),
                required_completed_bars=REQUIRED_BARS, completed_bars=len(candles),
                consecutive=consecutive, consecutive_tail_bars=tail,
                first_start_ms=timestamps[0] if timestamps else None, last_start_ms=last,
                last_close_age_ms=age, missing_bars=len(missing), missing_timestamps_ms=missing,
                requested_start_ms=start_ms, requested_end_ms=end_ms, evaluated_at_ms=now_ms)


def check(client, *, wait_for_budget=True, sleep=time.sleep):
    require_paper_migration()
    client.startup()
    expected = {base: f'{client.api_dex}:{base}' for base in ('BTC', 'EWY')}
    if (not client.competition_mode or not client.api_dex or client.api_dex == 'par' or
            dict(client.api_markets) != expected or
            client.collateral_token_name != 'USDP'):
        raise ExchangeError('PAS_BTC_EWY_USDP_MAPPING_REQUIRED')
    market = HyperliquidMarketData(client)
    report = dict(status='BLOCKED', live_ready=False, read_only=True, orders_submitted=0,
                  wallet_or_signer_certified=False, funding_verified=False,
                  observed_at_utc=datetime.now(timezone.utc).isoformat(),
                  mapping=dict(client.market_mapping), markets={},
                  note='Data-only gate. A pass cannot authorize or certify live trading.')
    for symbol in expected.values():
        for attempt in range(2):
            now = client.clock_ms()
            end = now // 60000 * 60000 - 1
            start = end + 1 - REQUIRED_BARS * 60000
            try:
                candles = market.get_candles(symbol, start, end, now_ms=now)
                report['markets'][symbol] = candle_status(symbol, candles, client.clock_ms(), start, end)
                break
            except ExchangeError as exc:
                delay = getattr(exc, 'retry_after_ms', None)
                if (wait_for_budget and attempt == 0 and str(exc) == 'PAS_CANDLE_BUDGET_EXHAUSTED'
                        and type(delay) is int and 0 < delay <= 60000):
                    sleep((delay + 1) / 1000)
                    continue
                report['markets'][symbol] = dict(symbol=symbol, data_gate_passed=False,
                    reasons=[str(exc)], completed_bars=None, requested_start_ms=start,
                    requested_end_ms=end, evaluated_at_ms=client.clock_ms())
                break
    # Re-evaluate earlier reads against the end-of-run clock, not their send time.
    final_now = client.clock_ms()
    for observation in report['markets'].values():
        last = observation.get('last_start_ms')
        if last is not None:
            observation['last_close_age_ms'] = final_now - (last + 60000)
            if not 0 <= observation['last_close_age_ms'] <= MAX_CANDLE_AGE_MS:
                observation['data_gate_passed'] = False
                if 'COMPLETED_CANDLE_STALE_OR_MISSING' not in observation['reasons']:
                    observation['reasons'].append('COMPLETED_CANDLE_STALE_OR_MISSING')
    report['completed_at_ms'] = final_now
    report['data_gate_passed'] = all(v['data_gate_passed'] for v in report['markets'].values())
    report['status'] = 'DATA_ONLY_PASS_NOT_LIVE_CERTIFIED' if report['data_gate_passed'] else 'BLOCKED'
    return report


def collect_stream(client, seconds):
    """A finite public-data task, not a deployment or an account owner.

    Warmup is in memory; raw audit evidence is not automatically trusted on
    restart. Stopping this collector never hands an activation permit to live.
    """
    if type(seconds) is not int or not 1 <= seconds <= 21600:
        raise ExchangeError('BOUNDED_PUBLIC_STREAM_DURATION_REQUIRED')
    require_paper_migration()
    engine = PasMarketDataEngine(HyperliquidMarketData(client), history_bars=REQUIRED_BARS)
    stop = threading.Event()
    failures = []
    def run():
        try:
            engine.run(stop)
        except Exception as exc:
            failures.append(str(exc))
    worker = threading.Thread(target=run, name='pas-public-data-only', daemon=True)
    worker.start()
    deadline = time.monotonic() + seconds
    observed = {}
    try:
        while worker.is_alive() and time.monotonic() < deadline:
            now = client.clock_ms()
            end = now // 60000 * 60000 - 1
            for symbol in client.api_markets.values():
                rows = engine.get_completed_candles(symbol)
                window = [c for c in rows if end + 1 - REQUIRED_BARS * 60000 <= c.timestamp_ms <= end]
                observed[symbol] = candle_status(symbol, window, now,
                    end + 1 - REQUIRED_BARS * 60000, end)
            stop.wait(min(1, max(0, deadline - time.monotonic())))
    finally:
        stop.set()
        worker.join(timeout=16)
    return dict(requested_seconds=seconds, stopped=not worker.is_alive(),
        in_memory_only=True, cache_automatically_activates_live=False, live_ready=False,
        messages=engine.messages, reconnections=engine.reconnections,
        errors=failures + (['PUBLIC_STREAM_SHUTDOWN_PENDING'] if worker.is_alive() else []),
        last_observed_markets=observed, last_error=engine.last_error,
        note='Stopped public collector. A 300-bar pass alone is not the full UTC scanner, account, liquidity or activation gate.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--no-budget-wait', action='store_true')
    parser.add_argument('--stream-seconds', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.stream_seconds <= 21600:
        parser.error('stream-seconds must be 0 through 21600 (six hours)')
    # Never turn a caller's live configuration into a silently authorized read.
    require_paper_migration()
    client = HyperliquidClient(venue='pas', candle_audit=PublicCandleAudit(args.audit) if args.audit else None)
    try:
        report = check(client, wait_for_budget=not args.no_budget_wait)
        if args.stream_seconds:
            report['public_stream'] = collect_stream(client, args.stream_seconds)
        if getattr(client, 'candle_budget', None) is not None:
            report['candle_budget'] = client.candle_budget.report()
    except Exception as exc:
        report = dict(status='BLOCKED', live_ready=False, data_gate_passed=False,
                      read_only=True, orders_submitted=0, reasons=[str(exc)])
    finally:
        client.transport.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + '\n')
    os.replace(temporary, args.output)
    print(json.dumps(report, indent=2, default=str, allow_nan=False))
    return 0 if report.get('data_gate_passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
