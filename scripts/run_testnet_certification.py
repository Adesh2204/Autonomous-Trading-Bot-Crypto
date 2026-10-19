"""Read-only proposal by default. Execution requires a separate exact human approval."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.par_retirement import reject_retired_par_write
from exchange.execution_journal import ExecutionJournal
from exchange.execution_safety import ClockHealthMonitor, HyperliquidRateLimitManager
from exchange.exchange_rules import LiveContextProvider, HyperliquidOrderValidator
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.order_lifecycle import OrderRequest
from exchange.paper_operations import active_source_hash, atomic_json
from exchange.reliability_policy import load_reliability_policy
from exchange.testnet_certification import (TEAM, API, CertificationProposal, CertificationApproval,
    propose, test_permission, require_safe_partial_path)
from exchange.certification_runtime import CertificationContextProvider
from exchange.partial_fill_safety import partial_path_assessment
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def read_only_preflight(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    r = dict(status='NO_ORDER_AUTHORIZED', production_mode='PAPER', allow_live_orders=False,
             network='testnet', dex='par', team_wallet=TEAM, api_wallet=API,
             observed_at_utc=datetime.now(timezone.utc).isoformat(), source_hash=active_source_hash(ROOT),
             exchange_submissions=0, signature_created=False, candidates=[],
             strategy_feed_ready=False, practice_ready=False, live_ready=False)
    journal = client = None
    try:
        r['safety'] = require_paper_migration(); r['freeze'] = verify_strategy_freeze()
        rate, cp, _ = load_reliability_policy(ROOT/'configs/reliability_policy.json')
        journal = ExecutionJournal(directory/'read_only.sqlite', session_id='certification-preflight', team_address=TEAM)
        rates = HyperliquidRateLimitManager(journal, policy=rate, signer_address=API)
        client = HyperliquidClient(rate_limits=rates); client.startup()
        market, account = HyperliquidMarketData(client), HyperliquidAccount(client, TEAM)
        clock = ClockHealthMonitor(clock_ms=client.clock_ms, journal=journal, **cp)
        r['metadata'] = [asdict(s) for s in client.markets.values()]
        r['initial_positions'] = [asdict(p) for p in account.get_positions().values()]
        r['initial_orders'] = account.get_frontend_open_orders()
        if r['initial_positions'] or r['initial_orders']:
            raise ExchangeError('CERTIFICATION_INITIAL_FLAT_ACCOUNT_REQUIRED')
        r['active_asset_by_market'] = {symbol: account._query('activeAssetData', coin=symbol)
                                     for symbol in client.markets}
        if any(value.get('leverage') != dict(type='cross', value=1)
               for value in r['active_asset_by_market'].values()):
            raise ExchangeError('CERTIFICATION_ONE_X_CROSS_REQUIRED')
        provider = CertificationContextProvider(market, account, API, clock, rates,
            reconciliation_ready=lambda:True, feed_ready=lambda:True)
        provider.trigger_aware = True
        # At most three candidate checks, paced before each full context request.
        for symbol in ('par:BTC', 'par:ETH', 'par:HYPE'):
            row = dict(symbol=symbol, proposed=False)
            r['candidates'].append(row)
            deadline = time.monotonic()+65
            while rates._usage()+400 > rates.policy.ip_weight_per_minute-rates.policy.ip_safety_reserve:
                if time.monotonic() >= deadline:
                    raise ExchangeError('CERTIFICATION_PUBLIC_READ_BUDGET')
                time.sleep(.5)
            try:
                # A seed request only asks for context; no order is submitted.
                quote = market.get_quote(symbol)
                spec = client.market(symbol)
                qty = spec.normalize_size(25/quote.ask)
                req = OrderRequest(symbol, 'BUY', qty, quote.ask, tif='Ioc', strategy_id='TESTNET_CERTIFICATION_ENTRY')
                ctx = provider.load(req)
                row.update(observed_ms=client.clock_ms(), quote=asdict(ctx.quote), active_asset=ctx.active_asset,
                           readiness=asdict(ctx.readiness), clock=clock.report())
                p = propose(ctx, client, r['source_hash'], reliability_policy_hash=
                            hashlib.sha256((ROOT/'configs/reliability_policy.json').read_bytes()).hexdigest())
                exact = OrderRequest(symbol, p.entry_side, p.quantity, p.entry_limit,
                                     tif='Ioc', strategy_id='TESTNET_CERTIFICATION_ENTRY')
                validation = HyperliquidOrderValidator(client).validate(exact, ctx, test_permission(exact, p, client.clock_ms()), client.clock_ms())
                row['central_validation'] = asdict(validation)
                if not validation.allowed:
                    raise ExchangeError(validation.code)
                row.update(proposed=True, proposal=asdict(p), proposal_hash=p.identity,
                    maintenance_margin_at_order=str(spec.maintenance_margin(exact.quantity*exact.price)))
                row['partial_fill_safety'] = partial_path_assessment(spec, p)
                try:
                    require_safe_partial_path(spec, p)
                    row['partial_fill_exit_ready'] = True
                except ExchangeError as exc:
                    row['partial_fill_exit_ready'] = False
                    row['execution_blocker'] = str(exc)
            except Exception as exc:
                row['blocker'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
        usable = [x for x in r['candidates'] if x['proposed'] and x.get('partial_fill_exit_ready')]
        # Choose the narrowest actual spread, never an assumed favorite coin.
        if usable:
            from decimal import Decimal
            selected = min(usable, key=lambda x:(Decimal(x['quote']['ask'])-Decimal(x['quote']['bid']))/Decimal(x['quote']['mid']))
            r['selected_proposal'] = selected['proposal']
            r['selected_proposal_hash'] = selected['proposal_hash']
            atomic_json(directory/'proposal.json', selected['proposal'])
        else:
            r['status'] = 'PREFLIGHT_BLOCKED'
            drafts = [x for x in r['candidates'] if x['proposed']]
            if drafts:
                from decimal import Decimal
                draft = min(drafts, key=lambda x:(Decimal(x['quote']['ask'])-Decimal(x['quote']['bid']))/Decimal(x['quote']['mid']))
                r['review_only_proposal'] = dict(proposal=draft['proposal'], proposal_hash=draft['proposal_hash'],
                    executable=False, order_authorized=False, status='PREFLIGHT_BLOCKED',
                    blocker=draft.get('execution_blocker'), partial_fill_safety=draft['partial_fill_safety'])
                # Wrapper deliberately cannot deserialize as CertificationProposal.
                atomic_json(directory/'blocked_proposal.json', r['review_only_proposal'])
        r['final_positions'] = [asdict(p) for p in account.get_positions().values()]
        r['final_orders'] = account.get_frontend_open_orders()
        if r['final_positions'] or r['final_orders']:
            r['status'] = 'PREFLIGHT_BLOCKED'; r['blocker'] = 'ACCOUNT_CHANGED_DURING_PROPOSAL'
        r['rates'] = rates.report()
    except Exception as exc:
        r['status'] = 'PREFLIGHT_BLOCKED'
        r['blocker'] = str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__
    finally:
        if client: client.transport.close()
        if journal: journal.close()
    atomic_json(directory/'preflight.json', r)
    return r


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('PAPER', 'TESTNET_CERTIFICATION', 'TESTNET_PRACTICE'), default='PAPER')
    p.add_argument('--output-directory', type=Path, required=True)
    p.add_argument('--proposal-file', type=Path)
    p.add_argument('--operator-approval-file', type=Path)
    p.add_argument('--test-receipt', type=Path)
    args = p.parse_args(argv)
    if args.mode != 'PAPER': reject_retired_par_write()
    require_paper_migration()
    if args.mode == 'TESTNET_PRACTICE':
        p.error('Separate autonomous practice authorization and certifications required; not implemented by this launcher')
    if args.mode == 'PAPER':
        if args.operator_approval_file: p.error('PAPER cannot consume order authorization')
        result = read_only_preflight(args.output_directory)
    else:
        if not all((args.proposal_file, args.operator_approval_file, args.test_receipt)):
            p.error('Exact proposal, operator approval and successful source-bound full regression required')
        from exchange.certification_runtime import build_certification
        runtime = None
        args.output_directory.mkdir(parents=True, exist_ok=False)
        try:
            proposal = CertificationProposal(**json.loads(args.proposal_file.read_text()))
            approval = CertificationApproval(**json.loads(args.operator_approval_file.read_text()))
            runtime = build_certification(ROOT, proposal, approval,
                state_directory=ROOT/'runtime/testnet/anchorium-bot-1', test_receipt=args.test_receipt)
            result = runtime.run()
        except Exception as exc:
            result = dict(status='PREFLIGHT_BLOCKED', error=str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__,
                          realized_pnl_status='REALIZED_PNL_NOT_CERTIFIED', practice_ready=False, live_ready=False)
        finally:
            if runtime: runtime.close()
        atomic_json(args.output_directory/'execution_report.json', result)
    print(json.dumps(dict(status=result['status'], output_directory=str(args.output_directory.resolve()),
                          exchange_order_authorization_supplied=bool(args.operator_approval_file))))
    return 0 if result['status'] not in {'PREFLIGHT_BLOCKED', 'EMERGENCY_EXIT_REQUIRED'} else 1


if __name__ == '__main__': raise SystemExit(main())
