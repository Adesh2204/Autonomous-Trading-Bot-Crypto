"""Run the production stock-selection pipeline without constructing a trading engine.

Usage: python premarket_check.py --fresh
Exit codes: 0 = completed scan (including valid NO_TRADE), 2 = data/source failure.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import logging
from pathlib import Path
import tempfile

from discovery_data import DiscoveryDataSource, atomic_json
from market_schedule import get_market_schedule
from premarket_pipeline import run_premarket_pipeline


class ReadOnlyMarketData:
    """Expose only the methods needed to refresh identities and fetch candles."""
    def __init__(self, broker):
        self._broker = broker

    @property
    def api_key(self):
        return self._broker.api_key

    @property
    def access_token(self):
        return self._broker.access_token

    def requestHeaders(self):
        return self._broker.requestHeaders()

    def getCandleData(self, params):
        return self._broker.getCandleData(params)


def run_check(broker, report_path, *, fresh=False):
    schedule = get_market_schedule('NSE')
    started = schedule.localize()
    broker = ReadOnlyMarketData(broker)
    context = tempfile.TemporaryDirectory(prefix='premarket-discovery-') if fresh else nullcontext(None)
    with context as directory:
        source = DiscoveryDataSource(directory)
        master_path = Path(directory)/'instruments.json' if fresh else None
        result = run_premarket_pipeline(broker, data_source=source, master_path=master_path)
        report = result.report()
        report['validation'] = {'mode': 'READ_ONLY_PREMARKET_CHECK', 'fresh_downloads_required': fresh,
            'started_at': started.isoformat(), 'completed_at': schedule.localize().isoformat(),
            'trading_engine_started': False, 'orders_submitted': 0}
        atomic_json(report_path, report)
    summary = {'readiness': result.readiness, 'status': result.screen.trading_day_status,
        'failure_reason': result.screen_failure_reason or result.discovery.failure_reason,
        'source': result.discovery.universe_source, 'session': result.screen.session_date.isoformat(),
        'raw_records': result.discovery.raw_instrument_count,
        'eligible_stocks': result.discovery.eligible_equity_count,
        'snapshot_coverage_pct': result.discovery.snapshot_coverage_pct,
        'coarse_candidates': result.discovery.coarse_qualified_count,
        'deep_screened': result.screen.total_candidates,
        'qualified': len(result.screen.qualified_candidates),
        'history_warning': result.screen.history_warning,
        'watchlist': [c.trading_symbol for c in result.screen.watchlist],
        'configured_stock_list_used': False, 'orders_submitted': 0,
        'report': str(Path(report_path).resolve())}
    return result, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh', action='store_true', help='Download a fresh master and both NSE files in an isolated cache')
    parser.add_argument('--report', type=Path, default=Path(__file__).parent/'data'/'paper'/'premarket_check.json')
    args = parser.parse_args(argv)
    # Reuse credential loading and authentication only; never call live_stream.main().
    from live_stream import angel_login
    try:
        result, summary = run_check(angel_login(), args.report, fresh=args.fresh)
    except Exception as exc:
        logging.error('[PREMARKET CHECK BLOCKED] %s', type(exc).__name__)
        return 2
    print(json.dumps(summary, indent=2))
    return 2 if result.readiness == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
