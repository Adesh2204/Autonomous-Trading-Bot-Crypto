"""Audit saved PAPER artifacts and annotate reports; no network or runtime writes."""
import collections
import datetime
import fcntl
import hashlib
import json
import pathlib
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

OUT = pathlib.Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path[:0] = [str(ROOT / 'algo-trading-bot'), str(ROOT / 'scripts')]
from exchange.paper_operations import active_source_hash, atomic_json
from feed_certification_report import checkpoint


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_stage(folder, label, source):
    receipt_path = OUT / folder / (label + '_paper_receipt.json')
    receipt = read(receipt_path)
    original = read(OUT / folder / (label + '_certification.json'))
    independent = read(OUT / folder / 'completion_verification.json')
    health = receipt['final_health']
    tape = pathlib.Path(receipt['health_samples_path'])
    samples = [json.loads(x) for x in tape.read_text().splitlines() if x.strip()]
    samples = [x for x in samples if receipt['started_unix'] * 1000 <= x['timestamp_ms'] <= receipt['finished_unix'] * 1000]
    state = pathlib.Path(receipt['state_directory'])
    checkpoints = {name: checkpoint(state / name) for name in ('paper.sqlite', 'backups/paper-latest.sqlite')}
    checks = dict(source_identity=receipt['source_hash_before'] == receipt['source_hash_after'] == source,
                  health_tape_digest=digest(tape) == receipt['health_samples_sha256'],
                  clean_shutdown=receipt['exit_code'] == 0 and health['status'] == 'STOPPED',
                  checkpoint_integrity=all(v['integrity'] == 'ok' and v['checksum_matches'] and v['clean_shutdown'] and v['source_hash'] == source for v in checkpoints.values()),
                  sample_safety=all(x['execution_mode'] == 'PAPER' and x['allow_live_orders'] is False and x['exchange_orders_submitted'] == 0 for x in samples),
                  actual_orders_zero=receipt['exchange_orders_submitted'] == health['exchange_orders_submitted'] == 0,
                  sample_segment_identity={x['segment'] for x in samples} == {health['segment']},
                  regenerated_certificate_agrees=all(original[k] == independent[k] for k in ('verdict', 'checks', 'blockers', 'funnel', 'checkpoints')),
                  workers_stopped=health['public_stream']['workers_stopped_cleanly'])
    assert all(checks.values()), checks
    with (state / 'owner.lock').open('r') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(owner, fcntl.LOCK_UN)
    events = health['public_stream']['events']
    barriers = [x for x in events if x['phase'] == 'PAPER_ACCOUNT_RECONCILED']
    disconnect_indices = [i for i, x in enumerate(events) if x['phase'] == 'DISCONNECTED']
    matched = []
    for n, i in enumerate(disconnect_indices):
        end = disconnect_indices[n + 1] if n + 1 < len(disconnect_indices) else len(events)
        window = events[i + 1:end]
        phases = ('CONNECTING', 'SUBSCRIBED', 'PAPER_ACCOUNT_RECONCILED')
        selected = []
        cursor = 0
        for phase in phases:
            next_index = next((j for j in range(cursor, len(window)) if window[j]['phase'] == phase), None)
            if next_index is None:
                break
            selected.append(window[next_index])
            cursor = next_index + 1
        if len(selected) == 3:
            matched.append(dict(disconnected_at_ms=events[i]['timestamp_ms'],
                                connected_at_ms=selected[0]['timestamp_ms'],
                                subscribed_at_ms=selected[1]['timestamp_ms'],
                                reconciled_at_ms=selected[2]['timestamp_ms'],
                                generation=selected[2]['generation']))
    other_barriers = [x for x in barriers[1:] if x['timestamp_ms'] not in {v['reconciled_at_ms'] for v in matched}]
    restored = collections.Counter()
    quarantined = set()
    for sample in samples:
        for symbol, value in sample.get('market_health', {}).items():
            if value['state'] == 'QUARANTINED':
                quarantined.add(symbol)
            elif value['state'] == 'HEALTHY' and symbol in quarantined:
                restored[symbol] += 1
                quarantined.remove(symbol)
    traces = [json.loads(x) for x in (pathlib.Path(health['segment']) / 'results/opportunity_traces.jsonl').read_text().splitlines()]
    invalid = [{k: t.get(k) for k in ('symbol', 'decision_ms', 'first_blocking_reason', 'raw_reasons', 'data_evidence')} for t in traces if t.get('first_blocking_reason') == 'INVALID_MARKET_DATA']
    return dict(checks=checks, checkpoints=checkpoints, receipt_sha256=digest(receipt_path),
                certificate_sha256=digest(OUT / folder / (label + '_certification.json')),
                health_samples_sha256=digest(tape), health_samples=len(samples),
                health_sample_statuses=dict(collections.Counter(x['status'] for x in samples)),
                post_initial_paper_account_barriers=len(barriers) - 1,
                socket_reconnects_with_completed_account_barrier=len(matched),
                non_socket_post_initial_account_barriers=other_barriers,
                reconnect_evidence=matched,
                sampled_quarantine_then_healthy_including_intermediate_recovery=dict(restored),
                restoration_scope='Actual ordered health samples, allowing an intervening RECOVERING state. Counts are observed transitions, not distinct sustained recoveries. The original adjacent-sample criterion is preserved.',
                invalid_numeric_rejections=invalid,
                final_market_inputs=health['market_health'])


def main():
    sequence = read(OUT / 'sequence.json')
    assert sequence['phase'] == 'COMPLETED_FEED_NOT_READY'
    source = active_source_hash(ROOT)
    tests = read(OUT / 'test_receipt.json')
    launch = read(OUT / 'sequence_launch.json')
    totals = {k: sum(int(x.get(k, 0)) for x in ET.parse(OUT / 'regression.xml').getroot().iter('testsuite')) for k in ('tests', 'failures', 'errors', 'skipped')}
    checks = dict(source_identity=source == sequence['source_hash'] == tests['source_hash'] == tests['source_hash_after'],
                  full_regression=tests['passed'] and tests['exit_code'] == 0 and totals == tests['totals'],
                  regression_xml_digest=digest(OUT / 'regression.xml') == tests['xml_sha256'],
                  supervisor_source=digest(OUT / 'run_sequence.py') == launch['supervisor_sha256'],
                  report_writer_source=digest(OUT / 'write_final_report.py') == launch['report_writer_sha256'])
    assert all(checks.values()), checks
    safety = {}
    for name in ('phase0_check.py', 'check_strategy_freeze.py'):
        run = subprocess.run([sys.executable, str(ROOT / 'scripts' / name)], cwd=ROOT, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        safety[name] = json.loads(run.stdout)
    stages = {label: audit_stage(folder, label, source) for folder, label in [('short_soak', 'short_30m'), ('long_soak', 'long_3h')]}
    for name in ('feed-soak-owner.lock', 'market-resilience-sequence-owner.lock'):
        with (ROOT / 'runtime/paper' / name).open('r') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(owner, fcntl.LOCK_UN)
    assert read(ROOT / 'configs/reliability_policy.json')['protection']['enabled'] is False
    automation = tomllib.loads(pathlib.Path('/Users/adesh/.codex/automations/monitor-anchorium-three-hour-paper-run/automation.toml').read_text())
    assert automation['status'] == 'PAUSED'
    old_account = read(ROOT / 'docs/feed_hardening_2026-10-07/account_check.json')
    old_signer = read(ROOT / 'docs/feed_hardening_2026-10-07/signer_preflight.json')
    audit = dict(verified_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), active_source_hash=source,
                 audit_script_sha256=digest(pathlib.Path(__file__)),
                 active_source_unchanged=True, checks=checks, current_local_safety_checks=safety, full_test_totals=totals,
                 stages=stages, ownership_locks_released=True, automation_status=automation['status'],
                 old_account_observed_at_utc=old_account['observed_at_utc'],
                 old_signer_local_nonce_observed_ms=old_signer['nonce_ownership']['owner_during_check']['started_ms'],
                 old_signer_scope=old_signer['nonce_ownership']['ownership_scope'],
                 funded_preflight_refreshed=False, actual_exchange_orders=0, protection_enabled=False)
    atomic_json(OUT / 'completion_audit.json', audit)
    for name in ('final_summary.json', 'report.md'):
        backup = OUT / (pathlib.Path(name).stem + '_supervisor_generated' + pathlib.Path(name).suffix)
        if not backup.exists():
            backup.write_bytes((OUT / name).read_bytes())
    run = subprocess.run([sys.executable, str(OUT / 'write_final_report.py')], cwd=ROOT)
    assert run.returncode == 0
    summary = read(OUT / 'final_summary.json')
    summary['completion_audit'] = audit
    summary['flags']['MARKET_HEALTH_SYSTEM_VERIFIED'] = True
    summary['flags']['MARKET_HEALTH_READY'] = False
    summary['flags']['REPEATED_USABLE_FEED_OBSERVED'] = True
    summary['flags']['RUNTIME_RUNNING'] = False
    summary['flags'].update(PROTECTION_ACCEPTANCE_TESTED=False, FUNDED_LONG_CERTIFIED=False,
                            FUNDED_SHORT_CERTIFIED=False, FUNDED_RECOVERY_CERTIFIED=False)
    for label, value in stages.items():
        result = summary['results'][label]
        result['original_reported_successful_reconnect_account_barriers'] = result['successful_reconnect_account_barriers']
        result['successful_reconnect_account_barriers'] = value['socket_reconnects_with_completed_account_barrier']
        result['post_initial_paper_account_barriers'] = value['post_initial_paper_account_barriers']
        result['non_socket_post_initial_account_barriers'] = len(value['non_socket_post_initial_account_barriers'])
        result['reconnect_count_provenance'] = 'Ordered DISCONNECTED -> CONNECTING -> SUBSCRIBED -> PAPER_ACCOUNT_RECONCILED events; see completion_audit.json. Original certificates retained.'
        result['successful_recoveries_field_scope'] = 'Legacy field counts REST reconciliation events including startup, not socket reconnects.'
    summary['flags_scope'] = 'Completed PAPER evidence. Historical transport/recovery checks passed; no process is running and no market was usable at shutdown. Funded account activation is unapproved.'
    atomic_json(OUT / 'final_summary.json', summary)
    report = (OUT / 'report.md').read_text()
    long = summary['results']['long_3h']
    report = report.replace('16 closes; 17 successful reconnect barriers;', '16 closes; 16 successful socket reconnects with completed PAPER account barriers; one additional non-socket account reconciliation;')
    report = report.replace('MARKET_HEALTH_READY = TRUE', 'MARKET_HEALTH_SYSTEM_VERIFIED = TRUE\nMARKET_HEALTH_READY = FALSE\nREPEATED_USABLE_FEED_OBSERVED = TRUE\nRUNTIME_RUNNING = FALSE')
    report = report.replace('PROTECTION_ENABLED = false\n```', 'PROTECTION_ENABLED = false\nPROTECTION_ACCEPTANCE_TESTED = FALSE\nFUNDED_LONG_CERTIFIED = FALSE\nFUNDED_SHORT_CERTIFIED = FALSE\nFUNDED_RECOVERY_CERTIFIED = FALSE\n```')
    def stage_times(label, folder):
        r = read(OUT / folder / (label + '_paper_receipt.json'))
        zone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        return ' to '.join(datetime.datetime.fromtimestamp(r[k], zone).isoformat(timespec='seconds') for k in ('started_unix', 'finished_unix'))
    insertions = {
        'A': 'The bot collected and checked real public data safely, but the completed three-hour feed certificate is FEED_NOT_READY. The 30-minute stage passed. During three hours, 29 of 360 scanner market checks had usable data; all 29 failed the unchanged ATR floor. There were no qualified markets, no simulated fills and no actual orders. At shutdown, no market had fully usable inputs. The infrastructure evidence does not establish a trading profit or funded-practice readiness.',
        'B': 'The three-hour completion blocker is `final_usable_market`: all ten markets were quarantined at shutdown. Book/context timestamps were fresh at that snapshot, while completed candle history was short/stale or had a full-strategy history gap. Sparse trading, provider delay and adapter effects are not causally distinguished by this run. Two separate `INVALID_DECIMAL` scanner rejections also remain unexplained; they are documented below and must not be blamed on the venue without a raw-input audit.',
        'C': 'Completion added only documentation and an offline artifact-audit helper (`completion_audit.py/.json`). The runtime source and the hashed supervisor/report writer were not changed. The original supervisor-generated report, summary, stage certificates, failed environment attempt and earlier tests/runs remain preserved. The 1,339-test receipt covers the runtime source; the separate completion helper validates saved artifacts with assertions and does not run an exchange client.',
        'D': '\n'.join(['Final per-market input evidence (historical shutdown snapshot):', '', '| Market | Completed bars | Completed candle close age, seconds | Reasons |', '|---|---:|---:|---|'] + [f'| {symbol} | {v["completed_candles"]} | {v["ages_ms"]["last_candle_time"] / 1000 if v["ages_ms"]["last_candle_time"] is not None else "Unknown"} | {", ".join(v["reasons"])} |' for symbol, v in stages['long_3h']['final_market_inputs'].items()] + ['', 'The candle clock is the one-minute bar start plus 60 seconds, so the age is measured from its close. Bar counts come from the bounded streaming cache. The scanner separately validates its unchanged full UTC input. A fresh latest candle alone cannot repair an earlier gap.']),
        'F': 'The original certificate records only adjacent sampled QUARANTINED-to-HEALTHY transitions (long run: SP500). The completion audit also allows an intervening RECOVERING sample: ' + json.dumps(stages['long_3h']['sampled_quarantine_then_healthy_including_intermediate_recovery']) + '. These are recorded transitions, not distinct sustained recoveries. Large internal manager restoration counters also include ordinary repair state changes and are not used as recovery certification.',
        'G': 'The completed health file is marked STOPPED. Running the CLI after its 120-second age limit returns PAPER_HEARTBEAT_STALE (exit 1); this is expected for a finished collector. Receipt timestamps, exit 0, stopped workers, released ownership locks and clean checksummed checkpoints verify planned completion. The retained final transport snapshot describes the last operating socket, not a socket still running.',
        'H': 'The audited long run has 16 captured 1000 / Expired closes and 16 corresponding completed reconnect/subscription/account-barrier sequences. There are 18 total PAPER account reconciliations: one startup, 16 after socket reconnects and one further non-socket reconciliation. The original generated reconnect field of 17 counted both kinds of post-startup barriers; its certificate and supervisor report are preserved. 185 REST reconciliation events are reported separately. Median completed socket lifetime: ' + str(long['median_completed_connection_lifetime_seconds']) + ' seconds. The cause of the Expired policy itself is unknown.',
        'I': 'Long-run public read observations: maximum sampled local IP weight ' + str(long['maximum_sampled_local_ip_weight']) + '; final pending reads 0; final public_read_blocked false; historical RATE_LIMITED events ' + str(long['public_read_budget']['public_reads']['failures'].get('RATE_LIMITED', 0)) + '; deferred recovery events ' + str(long['rest_deferred_count']) + '; retry-budget exhaustion ' + str(long['rest_retry_budget_failures']) + '. Resolved historical limit/defer events remain in evidence and are not final failures. Samples do not establish the exact peak or exchange-wide shared-IP usage. RATE_LIMITED records alone do not distinguish a local limiter rejection from an upstream response.',
        'K': 'Earlier focused failures and the previous 1,335-test source receipt remain in the original 8 October evidence directory. The final 1,339-test XML digest and before/after source hashes were independently verified again at completion, followed by fresh local Phase-0 and strategy-freeze checks. No broader test rerun or production change was needed.',
        'L': f'Actual receipt times in IST: short run {stage_times("short_30m", "short_soak")}; long run {stage_times("long_3h", "long_soak")}. The long run recorded {long["ready_samples"]} usable-feed health samples out of {stages["long_3h"]["health_samples"]} saved samples (353 RUNNING, 2 STOPPED), with {long["this_run_observations"]} independent market-cycle scanner observations. These denominators differ. PAPER cash/equity stayed 20,000 USDPR; realized/unrealized P&L, fees, funding, positions, fills and actual orders were zero. Both stages\' primary and backup checkpoints, tape digests, source hashes and clean shutdowns passed independent verification. The short run passed the latest feed definition; its older three-scan criterion failed. The long run met the older sustained-window criterion for SP500 (three windows), but both its latest and legacy certificates fail their final-market requirement.',
        'M': '\n'.join(['Comparison counts, kept in their original run scopes:', '', '| Scope | Market-cycle observations | Valid data | Valid-data % | Spread passes | ATR passes | Qualified |', '|---|---:|---:|---:|---:|---:|---:|', '| Old cumulative (includes earlier five minutes) | 370 | 49 | 13.24% | 7 | 0 | 0 |', '| Old actual three-hour segment | 360 | 48 | 13.33% | 7 | 0 | 0 |', '| Previous instrumented three hours | 360 | 34 | 9.44% | 6 | 0 | 0 |', '| Current short run | 60 | 9 | 15.00% | 9 | 0 | 0 |', '| Current three hours | 360 | 29 | 8.06% | 29 | 0 | 0 |', '', 'This run did not show higher overall scanner data availability. The infrastructure fixes and safe partial-health behavior were exercised, while actual usable input availability remained intermittent. Different times/market conditions prevent a causal performance comparison.', '', 'Two infrastructure/numeric rejections: BRENT at decision_ms 1791482698439 and EWY at 1791489298981, both INVALID_DECIMAL. Their traces had fresh candles and an observed frozen-brain evaluation, so this is not proof that the exchange supplied a malformed price. Causes remain UNDETERMINED. See completion_audit.json for exact recorded evidence. These checks failed closed. Strategy, risk and economics stages that were not reached remain unvalidated by this no-trade run.']),
        'N': 'Flags refer to completed PAPER observations, not a currently running process or funded readiness. The health manager was exercised successfully, but zero usable inputs at shutdown makes MARKET_HEALTH_READY and FEED_READY false. The last actual-account read was ' + old_account['observed_at_utc'] + ' (7 October, 20:47 IST); the local signer/nonce ownership check began at epoch_ms ' + str(old_signer['nonce_ownership']['owner_during_check']['started_ms']) + ' (about 20:48 IST), on the current host/OS user only. Neither is a fresh funded preflight. This sequence did not refresh the funded wallet or signer, allocate a nonce, sign, reconfigure leverage or test exchange protection. The heartbeat is PAUSED after bounded completion.',
    }
    for letter, content in insertions.items():
        marker = next(line for line in report.splitlines() if line.startswith('## SECTION ' + letter + ' '))
        report = report.replace(marker + '\n', marker + '\n\n' + content + '\n', 1)
    report = report.replace('Review the specific failed market-data gates with the organizer using the saved real timestamps and gaps; retain PAPER and unchanged strategy thresholds.', 'Perform one read-only raw-response-versus-adapter audit of the saved candle gaps and INVALID_DECIMAL rejections before another feed certification. Keep PAPER/false, protection disabled and the strategy thresholds unchanged; no new run or funded activation has been started.')
    (OUT / 'report.md').write_text(report)
    assert active_source_hash(ROOT) == source
    print(json.dumps(dict(verdict=summary['verdict'], audited_reconnects=long['successful_reconnect_account_barriers'],
                          checks_passed=True, monitor_status=automation['status'], active_source_unchanged=True)))


if __name__ == '__main__':
    main()
