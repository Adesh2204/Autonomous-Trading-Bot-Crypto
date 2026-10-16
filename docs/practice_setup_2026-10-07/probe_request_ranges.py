"""Compare actual public candle responses for rolling and UTC-session ranges."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.reliability_policy import load_reliability_policy
from exchange.paper_operations import active_source_hash
from venue_config import require_paper_migration

output = OUT / 'candle_request_range_probe.json'
raw_path = OUT / 'candle_request_range_responses.jsonl'
if output.exists() or raw_path.exists():
    raise RuntimeError('PRESERVE_PREVIOUS_RANGE_EVIDENCE')
require_paper_migration()
rates, _, _ = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
journal = ExecutionJournal(OUT / 'range_probe_budget.sqlite', session_id='public-range-probe',
                           team_address='0x' + '0' * 40)
client = HyperliquidClient(rate_limits=HyperliquidRateLimitManager(journal, policy=rates))
report = dict(scope='BOUNDED_REAL_PUBLIC_RESPONSE_RANGE_DIAGNOSTIC',
              active_source_hash=active_source_hash(ROOT), execution_mode='PAPER',
              allow_live_orders=False, exchange_actions_submitted=0, rows=[])
try:
    client.startup()
    now = client.clock_ms()
    end = now // 60000 * 60000 - 1
    midnight = now // 86400000 * 86400000
    starts = dict(rolling_300=end + 1 - 300 * 60000,
                  unchanged_scanner_utc_anchor=min(end + 1 - 300 * 60000, midnight - 14 * 60000))
    with raw_path.open('x') as evidence:
        for symbol in ('par:HYPE', 'par:SP500'):
            for label, start in starts.items():
                request = dict(coin=symbol, interval='1m', startTime=start, endTime=end)
                sent = client.clock_ms()
                raw = client.post_info('candleSnapshot', req=request)
                received = client.clock_ms()
                saved = dict(request=dict(type='candleSnapshot', req=request), response=raw,
                             received_at_ms=received, sent_at_ms=sent, label=label)
                evidence.write(json.dumps(saved) + '\n')
                evidence.flush()
                # Replay this exact real response through the unchanged adapter.
                frozen = HyperliquidClient(transport=lambda payload, raw=raw: raw,
                                          clock_ms=lambda: received)
                frozen.ready = True
                frozen.markets = client.markets
                normalized = HyperliquidMarketData(frozen).get_candles(symbol, start, end, now_ms=now)
                raw_times = sorted({row['t'] for row in raw if start <= row['t'] <= end and
                                    row['t'] + 60000 <= now})
                parsed_times = [bar.timestamp_ms for bar in normalized]
                report['rows'].append(dict(symbol=symbol, request_range=label,
                    requested_start_ms=start, requested_end_ms=end, returned_rows=len(raw),
                    normalized_completed_rows=len(normalized),
                    raw_latest_open_ms=raw_times[-1] if raw_times else None,
                    normalized_latest_open_ms=parsed_times[-1] if parsed_times else None,
                    completed_timestamp_parity=raw_times == parsed_times,
                    latest_close_age_ms=received - parsed_times[-1] - 60000 if parsed_times else None,
                    raw_response_sha256=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
                    note='Real sequential snapshots; range-dependent differences are observed, not attributed to an unverified server cause.'))
finally:
    client.close()
    journal.close()
report['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
report['raw_evidence_sha256'] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
with output.open('x') as stream:
    stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(output=str(output), rows=report['rows'], exchange_actions_submitted=0)))
