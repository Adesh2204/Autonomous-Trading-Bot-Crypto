"""Bounded READ-ONLY qualification watcher. Stops before exact human authorization."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.base_exchange import ExchangeError
from exchange.paper_operations import PaperOwner, active_source_hash, atomic_json
from exchange.qualification_watcher import (inspect_book, PublicBookStream, PublicBookReader,
    OpportunityGate, ReadOnlyQualificationSession, source_unchanged)
from exchange.testnet_certification import TEAM, API
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration
from run_testnet_qualification import current_test_receipt, publish_proposal, preparation_summary

MARKET_REJECTIONS = frozenset({
    'QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS',
    'QUALIFICATION_TWO_SIDED_BOOK_REQUIRED', 'QUALIFICATION_SPREAD_EXCEEDED',
    'QUALIFICATION_REFERENCE_DIVERGENCE', 'QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL',
    'QUALIFICATION_BOTH_SIDES_DEPTH_EXCEEDED', 'QUALIFICATION_FIXED_PRICE_OR_NOTIONAL_CHANGED',
    'QUALIFICATION_CLOCK_NOT_HEALTHY', 'QUALIFICATION_CLOCK_ACCOUNT_QUOTE_PAIR_NOT_READY',
})


def watch(directory, receipt=None, *, duration_seconds=300, transport='auto', final_account_audit=False):
    if not 10 <= duration_seconds <= 3600 or transport not in {'auto', 'rest'}:
        raise ExchangeError('INVALID_BOUNDED_WATCH_ARGUMENTS')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    r = dict(status='MONITORING_LIQUIDITY', qualification_state='MONITORING_LIQUIDITY',
        execution_mode='PAPER', allow_live_orders=False, protection_verified=False,
        exchange_submissions=0, actual_wallet_signatures=0, actual_fill_verified=False,
        organizer_whitelisting_confirmed=False, maximum_notional='25', entry_attempts=1, exit_attempts=2,
        team_wallet=TEAM, api_signer=API, source_hash=active_source_hash(ROOT),
        policy_hash=hashlib.sha256((ROOT / 'configs/reliability_policy.json').read_bytes()).hexdigest(),
        started_utc=datetime.now(timezone.utc).isoformat(), candidates=[], attempts=[],
        stage_a_observations=0, coverage={}, input_transport=transport,
        bounded_observation_seconds=duration_seconds, absolute_deadline_seconds=duration_seconds + 180,
        normal_protection_certified=False, practice_ready=False, live_ready=False)
    cancel = threading.Event()
    started = time.monotonic()
    session = stream = owner = timer = None
    original_handlers = {}

    def progress(event, **details):
        record = dict(event=event, at_ms=time.time_ns() // 1000000,
                      elapsed_seconds=round(time.monotonic() - started, 3), **details)
        with (directory / 'progress.jsonl').open('a') as f:
            f.write(json.dumps(record, default=str) + '\n')
        if event in {'MONITORING_LIQUIDITY', 'POTENTIAL_OPPORTUNITY', 'REFRESHING_ACCOUNT',
                     'CHECKING_RESIDUAL_EXITS', 'QUALIFICATION_PROPOSAL_READY', 'AWAITING_HUMAN_APPROVAL'}:
            r['qualification_state'] = event
            print(json.dumps(record, default=str), flush=True)
            atomic_json(directory / 'watch_state.json', dict(record, source_hash=r['source_hash'],
                mode='READ_ONLY', exchange_submissions=0))
        if cancel.is_set():
            raise ExchangeError('WATCH_INTERRUPTED_OR_DEADLINE')

    def stop(signum, frame):
        r['operator_interrupted'] = True
        cancel.set()

    try:
        require_paper_migration(); r['freeze_before'] = verify_strategy_freeze()
        r['test_receipt'] = str(current_test_receipt(receipt, r['source_hash']))
        owner = PaperOwner(ROOT / 'runtime/paper/qualification-watch.lock')
        for sig in (signal.SIGINT, signal.SIGTERM):
            original_handlers[sig] = signal.signal(sig, stop)
        timer = threading.Timer(duration_seconds + 180, cancel.set)
        timer.daemon = True; timer.start()
        session = ReadOnlyQualificationSession(ROOT, directory, r['source_hash'], r['policy_hash'],
                                               progress=progress, cancel_event=cancel)
        session.start()
        r['runtime_metadata'] = {s: asdict(spec) for s, spec in session.client.markets.items()}
        if transport == 'auto':
            stream = PublicBookStream(session.client.markets, session.rates, clock_ms=session.client.clock_ms)
            stream.start()
        reader = PublicBookReader(session.market, stream)
        gate = OpportunityGate()
        last_metadata = last_source = time.monotonic()
        seen = {}
        progress('MONITORING_LIQUIDITY', message='Public books only; account validation waits for a potential opportunity.')
        while time.monotonic() - started < duration_seconds and not cancel.is_set():
            if time.monotonic() - last_source >= 5:
                source_unchanged(ROOT, r['source_hash'], r['policy_hash'])
                last_source = time.monotonic()
            if time.monotonic() - last_metadata >= 60:
                session.refresh_metadata(); last_metadata = time.monotonic()
            rows = []
            for symbol in session.client.markets:
                book, origin = reader.get(symbol)
                if not book or seen.get(symbol) == (book.timestamp_ms, origin):
                    continue
                seen[symbol] = (book.timestamp_ms, origin)
                for side in ('BUY', 'SELL'):
                    row = inspect_book(session.client.market(symbol), book, session.client.clock_ms(), side)
                    row['transport'] = origin
                    rows.append(row)
                    r['coverage'][symbol + ':' + side] = row
                    r['stage_a_observations'] += 1
                    with (directory / 'observations.jsonl').open('a') as f:
                        f.write(json.dumps(row, default=str) + '\n')
            potential = sorted((x for x in rows if x['potential']),
                               key=lambda x: (float(x['spread_bps']), x['symbol']))
            for row in potential:
                if not gate.claim(row):
                    continue
                source_unchanged(ROOT, r['source_hash'], r['policy_hash'])
                progress('POTENTIAL_OPPORTUNITY', symbol=row['symbol'],
                         note='Not an order or authorization; full account and market checks follow.')
                candidate = session.validate(row['symbol'])
                r['attempts'].append(candidate)
                atomic_json(directory / ('attempt_' + str(gate.attempts) + '.json'), candidate)
                # The public receiver continues while account checks run. Save
                # its other markets for coverage without further REST calls or
                # waiting for unrelated markets before publishing this candidate.
                if stream:
                    for symbol in session.client.markets:
                        current = stream.snapshot(symbol)
                        if current:
                            for side in ('BUY', 'SELL'):
                                evidence = inspect_book(session.client.market(symbol), current, session.client.clock_ms(), side)
                                evidence['transport'] = 'WS_ACKNOWLEDGED_REPEATED'
                                r['coverage'][symbol + ':' + side] = evidence
                                r['stage_a_observations'] += 1
                                with (directory / 'observations.jsonl').open('a') as f:
                                    f.write(json.dumps(evidence, default=str) + '\n')
                if candidate['eligible_for_risk_review']:
                    source_unchanged(ROOT, r['source_hash'], r['policy_hash'])
                    r['candidates'] = [candidate]
                    publish_proposal(r, candidate, session.client, directory)
                    for key in ('final_reconciliation', 'final_positions', 'final_orders', 'account_observed_ms'):
                        r[key] = candidate[key]
                    progress('QUALIFICATION_PROPOSAL_READY', proposal_id=r['selected_proposal_hash'])
                    progress('AWAITING_HUMAN_APPROVAL', no_signatures_created=True)
                    break
                reason = candidate.get('blocker')
                if reason not in MARKET_REJECTIONS:
                    raise ExchangeError(reason or 'FULL_PREFLIGHT_NOT_READY')
                progress('MONITORING_LIQUIDITY', previous_rejection=reason, cooldown_seconds=60)
            if r.get('selected_proposal'):
                break
            cancel.wait(.5)
        r['reader_errors'] = reader.errors
        r['full_opportunity_attempts'] = gate.attempts
        for symbol in session.client.markets:
            for side in ('BUY', 'SELL'):
                key = symbol + ':' + side
                if key not in r['coverage']:
                    r['coverage'][key] = dict(symbol=symbol, entry_side=side, potential=False,
                        blocker='NO_FRESH_TWO_SIDED_BOOK_OBSERVED', account_checks_performed=False)
                row = r['coverage'][key]
                row['age_ms_at_observation_end'] = (session.client.clock_ms()-row['exchange_ms']
                                                    if 'exchange_ms' in row else None)
                row['coverage_scope'] = 'LAST_OBSERVED_BOOK_RESEARCH_NOT_CURRENT_SIGNING_PERMISSION'
        if cancel.is_set():
            raise ExchangeError('WATCH_INTERRUPTED_OR_DEADLINE')
        if not r.get('selected_proposal'):
            r.update(status='NO_CURRENT_QUALIFICATION_PROPOSAL', blocker='NO_SUPPORTED_CURRENT_OPPORTUNITY')
            # Optional one-time end audit, never one per ordinary market update.
            # It cannot publish a proposal: a later watcher must observe anew.
            if final_account_audit and not r['attempts']:
                r['end_account_audit'] = session.validate('par:BTC', audit_only=True)
                audit = r['end_account_audit']
                if audit.get('blocker') and audit['blocker'] not in MARKET_REJECTIONS:
                    raise ExchangeError(audit['blocker'])
        r['signer_check'] = session.identity
        r['reconciliation_calls'] = session.reconciliation_calls
        r['rates'] = session.rates.report()
    except KeyboardInterrupt:
        cancel.set(); r.update(status='WATCH_STOPPED', blocker='OPERATOR_INTERRUPTED')
    except Exception as exc:
        r.update(status='WATCH_STOPPED' if r.get('operator_interrupted') else 'QUALIFICATION_LOCKED',
                 blocker=str(exc) if isinstance(exc, ExchangeError) else type(exc).__name__)
    finally:
        if timer:
            timer.cancel()
        if stream:
            try:
                r['stream_before_shutdown'] = stream.report()
                stream.close(); r['stream_after_shutdown'] = stream.report()
            except Exception as exc:
                r.update(status='QUALIFICATION_LOCKED', cleanup_error=str(exc))
        if session:
            try:
                r['rates'] = session.rates.report()
                r['reconciliation_calls'] = session.reconciliation_calls
                session.close(); r['durable_cleanup'] = getattr(session, 'cleanup', None)
            except Exception as exc:
                r.update(status='QUALIFICATION_LOCKED', cleanup_error=str(exc))
        if owner:
            owner.close()
        for sig, handler in original_handlers.items():
            signal.signal(sig, handler)
        try:
            source_unchanged(ROOT, r['source_hash'], r['policy_hash'])
            r['freeze_after'] = verify_strategy_freeze()
        except Exception as exc:
            r.update(status='QUALIFICATION_LOCKED', blocker=str(exc))
        r.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                 elapsed_seconds=round(time.monotonic() - started, 3), source_hash_after=active_source_hash(ROOT))
        if r['status'] != 'EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED' and r.get('selected_proposal'):
            # Preserve evidence while making a post-publication cleanup failure
            # visibly unapprovable. Signing independently verifies every gate.
            r['proposal_invalidated'] = True
            for name in ('proposal.json', 'approval_REQUIRED_UNFILLED.json'):
                path = directory / name
                if path.exists():
                    path.rename(directory / ('INVALIDATED_' + name))
        # The end audit is diagnostic, not an ongoing account refresh. Expose
        # the terminal state in readiness as well as the operator handoff.
        if not r.get('selected_proposal') or r['status'] == 'QUALIFICATION_LOCKED':
            r['qualification_state'] = r['status']
        atomic_json(directory / 'readiness.json', r)
        summary = preparation_summary(r, directory, now_ms=time.time_ns() // 1000000)
        if not r.get('selected_proposal'):
            summary['qualification_state'] = r['status']
            summary['next_permitted_action'] = 'Review readiness.json; restart only by a deliberate new read-only command.'
        atomic_json(directory / 'operator_handoff.json', summary)
        atomic_json(directory / 'watch_state.json', summary)
        print(json.dumps(summary, indent=2), flush=True)
    return r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--test-receipt', type=Path)
    parser.add_argument('--duration-seconds', type=int, default=300)
    parser.add_argument('--transport', choices=['auto', 'rest'], default='auto')
    parser.add_argument('--final-account-audit', action='store_true',
                        help='One end-of-watch read-only account audit if no full opportunity validation occurred.')
    args = parser.parse_args()
    if not 10 <= args.duration_seconds <= 3600:
        parser.error('duration must be between 10 and 3600 seconds')
    r = watch(args.output_directory, args.test_receipt, duration_seconds=args.duration_seconds,
              transport=args.transport, final_account_audit=args.final_account_audit)
    return 130 if r['status'] == 'WATCH_STOPPED' else 1 if r['status'] == 'QUALIFICATION_LOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
