"""Review or deliberately apply 1x CROSS on par; never unlock or place orders."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.par_retirement import reject_retired_par_write
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import NonceManager, ClockHealthMonitor, HyperliquidRateLimitManager
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.leverage_configuration import (configuration_plan, LeverageConfigurationApproval,
    LeverageConfigurationTransport, wait_for_configuration_reads)
from exchange.live_readiness import verify_live_account_readiness
from exchange.order_lifecycle import parse_exchange_action_result, OrderState
from exchange.paper_operations import active_source_hash
from exchange.practice_preflight import read_api_key, api_signer
from exchange.reliability_policy import load_reliability_policy
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--team-address', required=True)
    p.add_argument('--api-wallet-address', required=True)
    p.add_argument('--state-directory', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--apply', action='store_true', help='Only the separately approved 1x CROSS configuration')
    p.add_argument('--manual-confirmation-file', type=Path)
    args = p.parse_args()
    reject_retired_par_write()
    if args.output.exists():
        p.error('preserve previous configuration evidence; choose a new output')
    report = dict(scope='PAR_1X_CROSS_CONFIGURATION_ONLY', execution_mode='PAPER', allow_live_orders=False,
                  orders_submitted=0, configuration_actions_submitted=0, results=[],
                  active_source_hash=active_source_hash(ROOT), team_address=args.team_address,
                  api_wallet_address=args.api_wallet_address, human_wallet_verified=False)
    client = journal = nonces = transport = signer = key = None
    try:
        report['safety_lock'] = require_paper_migration()
        report['strategy_freeze'] = verify_strategy_freeze()
        approval = None
        if args.apply:
            if args.manual_confirmation_file is None:
                raise ExchangeError('MANUAL_WALLET_CONFIRMATION_REQUIRED')
            try:
                approval = LeverageConfigurationApproval(**json.loads(args.manual_confirmation_file.read_text()))
            except Exception:
                raise ExchangeError('INVALID_MANUAL_CONFIGURATION_CONFIRMATION') from None
            import time
            approval.require(args.team_address, args.api_wallet_address, time.time_ns() // 1_000_000)
            report['human_wallet_verified'] = True
            report['approval_reference'] = approval.approval_reference
        args.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        journal = ExecutionJournal(args.state_directory / 'configuration.sqlite',
                                   session_id='par-one-x-configuration', team_address=args.team_address)
        rate_policy, clock_policy, _ = load_reliability_policy(ROOT / 'configs/reliability_policy.json')
        rates = HyperliquidRateLimitManager(journal, policy=rate_policy, signer_address=args.api_wallet_address)
        client = HyperliquidClient(rate_limits=rates, venue='par')
        client.startup()
        account = HyperliquidAccount(client, args.team_address)
        market = HyperliquidMarketData(client)
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, journal=journal, **clock_policy)

        def pace_reads():
            wait_for_configuration_reads(rates, approval, args.team_address, args.api_wallet_address)

        def readiness_guard():
            require_paper_migration()
            pace_reads()
            # Configuration is allowed only when the actual account is flat.
            if account.get_positions() or account.get_open_orders() or account.get_frontend_open_orders():
                raise ExchangeError('FLAT_ACCOUNT_WITHOUT_ORDERS_REQUIRED')
            client.startup()
            # A budget wait can age the prior clock reference. The existing
            # monitor then requires two distinct fresh references to recover.
            # Collect them rather than weakening its recovery requirement.
            for sample in range(3):
                sent = client.clock_ms()
                book = market.get_orderbook('par:BTC')
                clock.observe(book.timestamp_ms, sent, client.clock_ms())
                if clock.healthy or clock.reason != 'CLOCK_RECOVERY_CONFIRMATION_REQUIRED':
                    break
                if sample < 2:
                    rates.wait(250)
            ready = verify_live_account_readiness(account, args.api_wallet_address, clock_health=clock,
                                                   rate_limits=rates, reconciliation_ready=True)
            report['last_readiness_check'] = dict(account_ready=ready.account_ready,
                reasons=list(ready.reasons), observed_ms=ready.observed_ms,
                clock=clock.report(), rate_state=rates.report())
            if not ready.account_ready:
                raise ExchangeError('ACCOUNT_CONFIGURATION_READINESS_REQUIRED')
            if nonces is not None and not nonces.healthy:
                raise ExchangeError('NONCE_CONFIGURATION_HEALTH_REQUIRED')
            # Approval is separate from bot LIVE authorization and cannot unlock it.
            if approval is not None:
                approval.require(args.team_address, args.api_wallet_address, client.clock_ms())
            report['account_check'] = dict(account_ready=True, account_mode=ready.account_mode,
                                            collateral=ready.collateral, approval_expiry_ms=ready.agent_expiry_ms,
                                            clock=clock.report(), rate_state=rates.report(),
                                            positions=0, ordinary_orders=0, frontend_orders=0,
                                            reconciliation_scope='CURRENT_FLAT_CONFIGURATION_SNAPSHOT_ONLY',
                                            actual_execution_certified=False)

        readiness_guard()
        pace_reads()
        report['plan'] = configuration_plan(client, account)
        if args.apply:
            key, _ = read_api_key(ROOT)
            signer = api_signer(key, args.api_wallet_address, args.team_address)
            key = None
            nonces = NonceManager(args.state_directory / 'nonces.sqlite', signer.address, journal=journal)
            pace_reads()
            transport = LeverageConfigurationTransport(client, signer, args.team_address, nonces, approval,
                                                        rates=rates, readiness_guard=readiness_guard)
            for row in report['plan']['rows']:
                if journal.pending_management(row['action']):
                    raise ExchangeError('CONFIGURATION_UNCERTAINTY_REVIEW_REQUIRED')
                if not row['change_required']:
                    report['results'].append(dict(symbol=row['symbol'], status='ALREADY_ONE_X_CROSS', action_submitted=False))
                    continue
                readiness_guard()
                action_id = journal.reserve_management(row['action'], client.clock_ms())
                transmissions_before = transport.transmission_attempts
                try:
                    rates.reserve_action(kind='updateLeverage')
                    response = transport.set_one_x_cross(row['symbol'])
                    outcome = parse_exchange_action_result(response, [None], action='updateLeverage')[0]
                    if outcome.code == 'NONCE_ERROR':
                        nonces.degrade()
                    if outcome.state != OrderState.ACKNOWLEDGED:
                        journal.update_management(action_id, outcome.state.value, client.clock_ms())
                        raise ExchangeError('LEVERAGE_CONFIGURATION_REJECTED')
                    current = account._query('activeAssetData', coin=row['symbol'])
                    if (current.get('coin') != row['symbol'] or
                            str(current.get('user', '')).lower() != args.team_address.lower() or
                            current.get('leverage') != dict(type='cross', value=1)):
                        raise ExchangeError('LEVERAGE_READBACK_NOT_VERIFIED')
                    journal.update_management(action_id, 'ACKNOWLEDGED', client.clock_ms())
                    report['results'].append(dict(symbol=row['symbol'], status='ONE_X_CROSS_VERIFIED',
                                                   action_submitted=True, observed_leverage=current['leverage']))
                    rates.success()
                except Exception:
                    # UNKNOWN remains durable if transmission/readback is ambiguous.
                    # No automatic retry or extra action follows an uncertain result.
                    attempted = transport.transmission_attempts > transmissions_before
                    if not attempted:
                        journal.update_management(action_id, 'REJECTED_BEFORE_TRANSMISSION', client.clock_ms())
                    rates.error()
                    report['uncertain_action'] = dict(symbol=row['symbol'], action_id=action_id,
                                                       transmission_attempted=attempted, blind_retry=False)
                    raise
                finally:
                    report['configuration_actions_submitted'] += transport.transmission_attempts - transmissions_before
            pace_reads()
            report['final_verification'] = configuration_plan(client, account)
            if any(row['change_required'] for row in report['final_verification']['rows']):
                raise ExchangeError('ALL_MARKETS_ONE_X_NOT_VERIFIED')
            report['status'] = 'ALL_TEN_ONE_X_CROSS_VERIFIED'
        else:
            report['status'] = 'READ_ONLY_CONFIGURATION_PLAN'
    except Exception as exc:
        report['status'] = 'FAILED'
        report['error'] = str(exc) if isinstance(exc, ExchangeError) else 'CONFIGURATION_INTERNAL_ERROR'
        if transport is not None:
            report['last_transmission_attempted'] = transport.transmitted
    finally:
        if transport is not None:
            transport.close()
        if nonces is not None:
            nonces.close()
        if journal is not None:
            journal.close()
        if client is not None:
            client.transport.close()
        key = signer = None
    report['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2, default=str) + '\n')
    print(json.dumps(dict(status=report['status'], output=str(args.output.resolve()),
                          orders_submitted=0, configuration_actions_submitted=report['configuration_actions_submitted'],
                          error=report.get('error'))))
    return 1 if report['status'] == 'FAILED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
