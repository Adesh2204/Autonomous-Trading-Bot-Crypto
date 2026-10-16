"""Bounded public REST freshness comparison; no private key or signed actions."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.hyperliquid_client import HyperliquidClient
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import HyperliquidRateLimitManager
from exchange.reliability_policy import load_reliability_policy
from exchange.paper_operations import active_source_hash
from venue_config import require_paper_migration

path = OUT / 'direct_candle_probe.json'
if path.exists():
    raise RuntimeError('PRESERVE_EXISTING_PUBLIC_PROBE')
require_paper_migration()
rates, _, _ = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
journal = ExecutionJournal(OUT / 'public_probe_budget.sqlite', session_id='direct-candle-probe',
                           team_address='0x' + '0' * 40)
client = HyperliquidClient(rate_limits=HyperliquidRateLimitManager(journal, policy=rates))
report = dict(scope='REAL_PUBLIC_PAR_REST_AND_LOCAL_FEED_SNAPSHOT', execution_mode='PAPER',
              allow_live_orders=False, exchange_actions_submitted=0, signer_constructed=False,
              active_source_hash=active_source_hash(ROOT), markets=[])
try:
    client.startup()
    health_path = ROOT / 'runtime/paper/readiness-2026-10-07-current-setup/health.json'
    health = json.loads(health_path.read_text())
    paper = json.loads((Path(health['segment']) / 'report.json').read_text())
    report['paper_observed_at_utc'] = paper['observed_at_utc']
    for symbol in sorted(client.markets):
        now = client.clock_ms()
        request = dict(coin=symbol, interval='1m', startTime=now - 302 * 60000, endTime=now)
        raw = client.post_info('candleSnapshot', req=request)
        completed = [r for r in raw if isinstance(r, dict) and r.get('s') == symbol and
                     r.get('i') == '1m' and type(r.get('T')) is int and r['T'] < now]
        latest = max((r['T'] + 1 for r in completed), default=None)
        stream_latest = paper.get('feed_health', {}).get(symbol, {}).get('clocks', {}).get('last_candle_time')
        report['markets'].append(dict(symbol=symbol, requested_minutes=302, rows_returned=len(raw),
            completed_rows=len(completed), latest_rest_completed_close_ms=latest,
            rest_close_age_ms=now-latest if latest is not None else None,
            paper_stream_completed_close_ms=stream_latest,
            rest_minus_stream_close_ms=latest-stream_latest if latest is not None and stream_latest is not None else None,
            response_sha256=hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            note='Snapshots are not simultaneous; missing bars are never filled or relabeled.'))
    report['status'] = 'OBSERVED'
finally:
    client.transport.close()
    journal.close()
report['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
with path.open('x') as stream:
    stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(status=report['status'], output=str(path), exchange_actions_submitted=0,
                     markets=[dict(symbol=m['symbol'], completed=m['completed_rows'],
                                   age_ms=m['rest_close_age_ms']) for m in report['markets']])))
