"""Reproducible read-only audit. Uses public identities; never constructs a signer."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze
from exchange.hyperliquid_client import HyperliquidClient, RequestsInfoTransport
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_reconciliation import HyperliquidReconciliation, ExchangeTruthState
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager
from exchange.live_readiness import verify_live_account_readiness
from exchange.reliability_policy import load_reliability_policy
from exchange.paper_operations import active_source_hash

TEAM = '0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C'
API = '0x46c9BED595770150752E7fA3806449F81E0Ec6f9'
# Explicit observer window, not a claim of complete pre-competition history.
START = int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp() * 1000)
OUT = Path(__file__).resolve().parent


class AuditTransport(RequestsInfoTransport):
    def __init__(self):
        super().__init__()
        self.calls = []
    def __call__(self, payload):
        self.calls.append(dict(payload))
        return super().__call__(payload)


def main():
    output = OUT / 'account_check.json'
    if output.exists():
        raise RuntimeError('PRESERVE_EXISTING_ACCOUNT_EVIDENCE')
    report = dict(scope='READ_ONLY_TESTNET_ACCOUNT_TECHNICAL_CHECK', network='testnet', dex='par',
        team_address=TEAM, api_wallet_address=API, execution_mode='PAPER', allow_live_orders=False,
        exchange_orders_submitted=0, account_administration_actions=0, signer_constructed=False,
        manual_wallet_verification_performed=False, controlled_execution_certified=False,
        live_ready=False, active_source_hash=active_source_hash(ROOT), accounting_start_ms=START)
    transport = AuditTransport()
    client = HyperliquidClient(transport)
    journal = None
    try:
        report['safety_lock'] = require_paper_migration()
        report['strategy_freeze'] = verify_strategy_freeze()
        rate_policy, clock_policy, protection = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
        report['protection_policy'] = asdict(protection)
        client.startup()
        report['dex_index'] = client.dex_index
        report['metadata'] = client.metadata
        report['markets'] = sorted(client.markets)
        journal = ExecutionJournal(OUT / 'read_only_budget.sqlite', session_id='readiness:2026-10-07', team_address=TEAM)
        rates = HyperliquidRateLimitManager(journal, clock_ms=client.clock_ms, policy=rate_policy)
        client.rate_limits = rates
        account = HyperliquidAccount(client, TEAM)
        report['account_mode'] = account._query('userAbstraction')
        report['spot_clearinghouse_state'] = account._query('spotClearinghouseState')
        agents = account._query('extraAgents')
        report['approved_api_wallets'] = agents
        now = client.clock_ms()
        matches = [a for a in agents if isinstance(a, dict) and
                   str(a.get('address', '')).lower() == API.lower()]
        report['configured_api_approval_matches'] = matches
        report['api_agent_ready_read_only'] = (len(matches) == 1 and
            type(matches[0].get('validUntil')) is int and matches[0]['validUntil'] > now)
        report['user_fees'] = account._query('userFees')
        report['user_rate_limit'] = account._query('userRateLimit')
        report['clearinghouse_state'] = account._query('clearinghouseState')
        report['positions'] = {s: asdict(p) for s, p in account.get_positions().items()}
        report['open_orders'] = account.get_open_orders()
        report['frontend_open_orders'] = account.get_frontend_open_orders()
        report['reported_equity'] = asdict(account.get_equity())
        report['active_asset_data'] = {s: account._query('activeAssetData', coin=s) for s in sorted(client.markets)}
        truth = ExchangeTruthState()
        try:
            report['reconciliation'] = HyperliquidReconciliation(account).recover(truth, start_ms=START)
            report['reconciliation_ready_read_only'] = (not truth.entries_paused and
                not truth.positions and not truth.orders and not report['frontend_open_orders'])
        except Exception as exc:
            report['reconciliation'] = truth.report()
            report['reconciliation_failure_type'] = type(exc).__name__
            report['reconciliation_ready_read_only'] = False
        # Refresh metadata and the venue clock immediately before the readiness call.
        client.startup()
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, **clock_policy)
        market = HyperliquidMarketData(client)
        sent = client.clock_ms()
        book = market.get_orderbook('par:BTC')
        clock.observe(book.timestamp_ms, sent, client.clock_ms())
        ready = verify_live_account_readiness(account, API, clock_health=clock, rate_limits=rates,
            reconciliation_ready=report.get('reconciliation_ready_read_only', False))
        report['account_verification'] = ready.report(market_ready=False)
        report['account_ready_read_only'] = ready.account_ready
        report['clock'] = clock.report()
        report['status'] = 'OBSERVED'
    except Exception as exc:
        report.update(status='CHECK_FAILED', error_type=type(exc).__name__)
    finally:
        report['query_audit'] = transport.calls
        report['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
        report['observed_at_ist'] = datetime.now(timezone.utc).astimezone(
            __import__('zoneinfo').ZoneInfo('Asia/Kolkata')).isoformat()
        client.close()
        if journal is not None:
            journal.close()
        output.write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + '\n')
    print(json.dumps(dict(path=str(output), status=report['status'],
        account_mode=report.get('account_mode'), api_agent_ready=report.get('api_agent_ready_read_only'),
        positions=len(report.get('positions', {})), open_orders=len(report.get('frontend_open_orders', [])),
        account_ready_read_only=report.get('account_ready_read_only'),
        reconciliation_ready_read_only=report.get('reconciliation_ready_read_only'),
        reasons=report.get('account_verification', {}).get('reasons'),
        error_type=report.get('error_type'))))
    return 0 if report['status'] == 'OBSERVED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
