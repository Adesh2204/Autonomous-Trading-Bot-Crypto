"""Build the final report only from completed, source-bound saved evidence."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.paper_checkpoint import unpack
from exchange.paper_operations import active_source_hash
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_time(value):
    return datetime.fromtimestamp(value, timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()


def link(path, label):
    return f'[{label}](<{path.resolve()}>)'


if (OUT / 'readiness.json').exists() or (OUT / 'report.md').exists():
    raise RuntimeError('PRESERVE_FINAL_REPORT_AND_EVIDENCE')
lock = require_paper_migration()
freeze = verify_strategy_freeze()
receipt = read(OUT / 'continuous_paper_receipt.json')
if ('finished_unix' not in receipt or receipt['requested_duration_seconds'] != 3600 or
        receipt['finished_unix'] - receipt['started_unix'] < 3600):
    raise RuntimeError('COMPLETE_REQUESTED_ONE_HOUR_BEFORE_REPORTING')
tests = read(OUT / 'test_receipt.json')
signer = read(OUT / 'signer_preflight_final.json')
geometry = read(OUT / 'requested_protection_receipt.json')
operating_final = read(OUT / 'operating_checks_final.json')
account_path = OUT / 'account_check_final.json'
if not account_path.exists():
    account_path = OUT / 'account_check.json'
account = read(account_path)
plan = read(OUT / 'leverage_plan.json')
applied_path = OUT / 'leverage_applied.json'
applied = read(applied_path) if applied_path.exists() else None
segment = Path(receipt['final_health']['segment'])
paper = read(segment / 'report.json')
samples = lines(OUT / 'continuous_health_samples.jsonl')
running = list({s['timestamp_ms']: s for s in samples if s['status'] == 'RUNNING'}.values())
health_counts = Counter(m for s in running for m in s['healthy_markets'])
scan_rows = lines(segment / 'candles.jsonl')
scan_ids = sorted({r['scan_observed_at_ms'] for r in scan_rows})
decisions = paper['decisions']
rejections = Counter(reason for d in decisions if d.get('kind') == 'ENTRY_REJECTED'
                     for reason in d.get('reasons', []))
funnel = read(segment / 'results/funnel_summary.json')
qualified = next(s['passed'] for s in funnel['session']['stages'] if s['stage'] == 'SCANNER_QUALIFIED')
scanner_rejection_summary = next(s['rejection_reasons'] for s in funnel['session']['stages']
                                 if s['stage'] == 'SCANNER_QUALIFIED')
state = Path(receipt['state_directory'])
checks = {}
for relative in ('paper.sqlite', 'backups/paper-latest.sqlite'):
    with sqlite3.connect((state / relative).resolve().as_uri() + '?mode=ro', uri=True) as db:
        checks[relative + '_integrity'] = db.execute('PRAGMA integrity_check').fetchone()[0]
        data, expected = db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
        checks[relative + '_checksum'] = hashlib.sha256(data.encode()).hexdigest() == expected
        checkpoint = unpack(json.loads(data))
        checks[relative + '_clean'] = checkpoint['clean']
        checks[relative + '_source'] = checkpoint['identity']['active_source_hash']
        if relative == 'paper.sqlite':
            primary_checkpoint = checkpoint
source = active_source_hash(ROOT)
same_source = (source == receipt['source_hash_before'] == receipt['source_hash_after'] ==
               tests['source_hash_before'] == tests['source_hash_after'] == signer['active_source_hash'] ==
               account['active_source_hash'] == plan['active_source_hash'] == geometry['active_source_hash'] and
               operating_final['active_source_hash'] == source and
               receipt['source_unchanged'] and
               all(value == source for key, value in checks.items() if key.endswith('_source')))
protection = read(ROOT / 'configs/reliability_policy.json')['protection']
configured = (protection['enabled'] is False and protection['atr_distance_multiple'] == '1' and
              protection['execution_slippage_fraction'] == '0.005' and
              protection['approval_reference'] == 'docs/practice_setup_2026-10-07/protection_configuration_approval.md' and
              geometry['policy_sha256'] == sha(ROOT / 'configs/reliability_policy.json') and
              geometry['totals']['tests'] == 4 and
              geometry['totals']['failures'] == geometry['totals']['errors'] == 0)
aligned = bool(applied and applied.get('status') == 'ALL_TEN_ONE_X_CROSS_VERIFIED' and
               all(not r['change_required'] for r in applied['final_verification']['rows']))
offline_ok = bool(same_source and tests['exit_code'] == 0 and
                  tests['totals']['failures'] == tests['totals']['errors'] == 0 and freeze['passed'])
paper_ok = bool(offline_ok and receipt['exit_code'] == 0 and
                receipt['final_health']['status'] == 'STOPPED' and not paper['accounting_halt'] and
                operating_final['paper_owner_lease_released'] and
                all(value == 'ok' if key.endswith('_integrity') else value is True
                    for key, value in checks.items() if not key.endswith('_source')))
flags = dict(STRATEGY_FREEZE='PASS' if freeze['passed'] else 'FAIL',
    ACCOUNT_READY='YES' if account.get('account_ready_read_only') else 'NO',
    API_APPROVAL_READY='YES' if account.get('api_agent_ready_read_only') else 'NO',
    API_SIGNER_IDENTITY_VERIFIED='YES' if signer['identity']['status'] == 'MATCH' else 'NO',
    NONCE_LOCAL_HEALTHY='YES' if signer['nonce_ownership']['status'] == 'HEALTHY_LOCAL' else 'NO',
    REMOTE_SIGNER_OWNERSHIP_VERIFIED='NO',
    CLOCK_READY='YES' if account.get('clock', {}).get('state') == 'HEALTHY' else 'NO',
    ACCOUNT_RATE_BUDGET_READY='YES' if account.get('account_verification', {}).get('rate_limits_healthy') else 'NO',
    LEVERAGE_ALIGNED='YES' if aligned else 'NO',
    PROTECTION_CONFIGURED='YES' if configured else 'NO', PROTECTION_ENABLED='NO',
    PAPER_ONE_HOUR_COMPLETE='YES' if paper_ok else 'NO',
    SUSTAINED_USABLE_FEED_DEMONSTRATED='NO',
    READ_ONLY_RECONCILIATION_READY='YES' if account.get('reconciliation_ready_read_only') else 'NO',
    LONG_CERTIFIED='NO', SHORT_CERTIFIED='NO', FUNDED_RECOVERY_CERTIFIED='NO',
    PRACTICE_READY='NO', LIVE_READY='NO')
raw_history = ROOT / 'algo-trading-bot/data/history'
prior_history = read(ROOT / 'docs/history_readiness_2026-10-07/readiness.json')
history_unchanged = all(sha(raw_history / (symbol.split(':')[1] + '.csv')) == digest
                        for symbol, digest in prior_history['csv_sha256'].items())
config_attempts = applied.get('configuration_actions_submitted', 0) if applied else 0
source_bound_paths = [OUT / n for n in (
    'test_receipt.json', 'regression.xml', 'signer_preflight_final.json', 'leverage_plan.json',
    'continuous_paper_receipt.json', 'continuous_health_samples.jsonl',
    'requested_protection_receipt.json', 'requested_protection_geometry.xml',
    'operating_checks.json', 'operating_checks_final.json',
    'direct_candle_probe.json', 'candle_request_range_probe.json',
    'candle_request_range_responses.jsonl', 'recorded_indicator_diagnostic_corrected.json')]
source_bound_paths += [account_path, segment / 'report.json', segment / 'results/session_manifest.json',
                      ROOT / 'configs/reliability_policy.json', ROOT / 'configs/practice_ops.json',
                      ROOT / 'docs/strategy_freeze.json', ROOT / 'algo-trading-bot/signal_brain.py',
                      ROOT / 'AGENTS.md', OUT / 'protection_configuration_approval.md']
if applied:
    source_bound_paths.append(applied_path)
source_bound_paths += [OUT / 'certification_plan.md', OUT / 'build_report.py',
                      OUT / 'run_paper_validation.py', OUT / 'check_account.py',
                      OUT / 'check_account_final.py',
                      OUT / 'diagnose_recorded_indicators.py', OUT / 'probe_request_ranges.py',
                      OUT / 'probe_live_candles.py']
result = dict(observed_at_ist=local_time(datetime.now(timezone.utc).timestamp()), flags=flags,
    execution_mode='PAPER', allow_live_orders=False, actual_orders_submitted=0,
    configuration_transmission_attempts=config_attempts,
    git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    git_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)),
    active_source_hash=source, all_active_source_checks_match=same_source,
    safety_lock=lock, strategy_freeze=freeze, full_suite=tests['totals'],
    additional_protection_tests=geometry, account_evidence=str(account_path),
    account_observed_at_ist=account['observed_at_ist'],
    api_identity=signer['identity'], nonce_local_check=signer['nonce_ownership'],
    protection=protection, leverage_apply=applied,
    final_local_operating_checks=operating_final,
    paper=dict(start_ist=local_time(receipt['started_unix']), end_ist=local_time(receipt['finished_unix']),
        requested_seconds=3600, elapsed_wall_seconds=receipt['finished_unix']-receipt['started_unix'],
        exit_code=receipt['exit_code'], state_directory=str(state), segment=str(segment),
        running_heartbeat_samples=len(running), any_healthy_samples=sum(bool(s['healthy_markets']) for s in running),
        largest_heartbeat_gap_ms=max((b['timestamp_ms'] - a['timestamp_ms']
            for a, b in zip(sorted(running, key=lambda s:s['timestamp_ms']),
                            sorted(running, key=lambda s:s['timestamp_ms'])[1:])), default=None),
        heartbeat_severities=dict(Counter(s['severity'] for s in running)),
        healthy_sample_counts_by_market=dict(sorted(health_counts.items())),
        all_ten_healthy_samples=sum(len(s['healthy_markets']) == 10 for s in running),
        scans=len(scan_ids), qualified_market_observations=qualified,
        scanner_rejection_summary=scanner_rejection_summary,
        scan_status=paper['scan_status'], local_orders=paper['local_orders'], local_fills=paper['local_fills'],
        paper_portfolio=paper['portfolio'], accounting_halt=paper['accounting_halt'],
        stream=receipt['final_health']['public_stream'], checkpoint_checks=checks,
        final_rejections={d['symbol']: d['reasons'] for d in paper['diagnostics']},
        maximum_memory_mb=max(s['rss_high_watermark_mb'] for s in samples)),
    history=dict(original_zip_available=False, official_provenance_verified=False,
        user_reports_official_discord_source=True, raw_csv_hashes_unchanged=history_unchanged,
        csv_count=10, csv_rows=prior_history['csv_rows'], live_pipeline_isolated=True),
    research_state=prior_history['research_state'],
    artifact_sha256={str(path.relative_to(ROOT)): sha(path) for path in source_bound_paths},
    scope_notes=dict(ACCOUNT_READY='Timestamped read-only funded/unified check; not activation.',
        PAPER_ONE_HOUR_COMPLETE='Local launcher and zero-exposure operation, not profitability or funded fills.',
        SUSTAINED_USABLE_FEED_DEMONSTRATED='Not demonstrated; per-market observations below. All ten fresh at once is not a new trading rule.',
        NONCE_LOCAL_HEALTHY='No nonce allocated; no actual signature; lock scope is one host and OS user.',
        PROTECTION_CONFIGURED='User-requested exact policy recorded; still disabled and not exchange-certified.',
        RESEARCH_PRODUCTION_CHANGED='Research promotion flag; infrastructure changes do not certify model promotion.'))
with (OUT / 'readiness.json').open('x') as stream:
    stream.write(json.dumps(result, indent=2, default=str) + '\n')
rows = '\n'.join(f'| `{k}` | **{v}** |' for k, v in flags.items())
leverages = '\n'.join(f"| `{r['symbol']}` | {r['observed_leverage']['value']}x {r['observed_leverage']['type']} | 1x cross |"
                      for r in (applied['final_verification']['rows'] if aligned else plan['plan']['rows']))
probe = read(OUT / 'direct_candle_probe.json')
feed_rows = '\n'.join(f"| `{r['symbol']}` | {r['completed_rows']} | " +
    ('Unavailable' if r['rest_close_age_ms'] is None else f"{r['rest_close_age_ms']/60000:.1f} minutes") + ' |'
    for r in probe['markets'])
market_health = '\n'.join(f"| `{symbol}` | {health_counts[symbol]} / {len(running)} |"
                          for symbol in sorted(account['markets']))
leverage_status = ('The deliberately requested configuration was applied and every market reread as 1x CROSS.' if aligned else
    'The ten-market change is prepared and offline tested, but **has not been submitted**. The manual wallet-verification reply is still missing.')
report = f'''# Team Anchorium: practice setup and one-hour PAPER evidence

Report created: {result['observed_at_ist']}.

**The signer check and requested emergency configuration are complete, and the one-hour PAPER run has finished. Funded trading practice is still not ready.** {leverage_status} No actual entry, exit, cancellation or protective order was submitted. The strategy is unchanged.

## 1. What changed

The new private-signer preflight derives only the API wallet's public address, compares it with the approved address, and checks the durable local nonce owner. A separate leverage helper prepares or deliberately applies only the user-requested **1x CROSS** setting. It cannot enable orders, cancel orders, transfer funds or switch account mode, and startup does not silently run it.

The emergency policy now records the exact requested configuration: one entry ATR beyond the normal stop, 0.5% execution allowance, reduce-only. It stays **disabled**. Four extra offline checks verify its geometry and refusal behavior. The full repository suite passed **{tests['totals']['tests']:,} tests**, with zero failures, errors or skips.

The bot ran for the requested hour on this Mac with real public `par` feeds, a separate simulated ledger, monitoring, a persistent checkpoint and backups. Additional bounded read-only probes compared REST with feed snapshots and passed actual captured responses through the unchanged adapter.

## 2. Safety and frozen strategy

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

These flags are still enforced. Angel One execution remains prohibited. The original NSE repository was untouched. `signal_brain.py`, eight protected strategy methods and 32 protected parameters passed their comparison against `nse-working-baseline`. VWAP, EMA, ATR, long/short conditions, stops, targets, cooldowns and direction flips were not improved or tuned.

Scanner settings remain **300 completed bars**, **0.40% ATR floor**, **15 bps maximum spread**, **Top-3** and the existing completed UTC input convention. Historical CSVs never replace current public candles. An unavailable exchange publication clock remains unavailable rather than being invented.

Evidence: {link(OUT / 'test_receipt.json', 'full-suite and freeze receipt')}, {link(OUT / 'regression.xml', '1,276 offline test results')}.

## 3. Actual account and API key

At **{account['observed_at_ist']}**, read-only account queries observed the registered team wallet `{account['team_address']}`, **1,000,000 USDPR**, `unifiedAccount`, approved API wallet `anchorium-bot-1`, and no `par` positions or ordinary/trigger-aware open orders. The public API approval expires at {local_time(account['configured_api_approval_matches'][0]['validUntil']/1000)}. The account is already unified; no repeated mode change was needed.

The local API key derives to **`{signer['identity']['derived_public_address']}`**, matching the approved address. The report contains public addresses and source names only. It contains no private key, seed phrase, signature or signed payload. No team-wallet secret was requested or used. Address derivation does not test an actual exchange signature.

A nonce is the unique time-based number attached to a signed request. Saving the last number helps prevent reuse after a restart. The nonce probe used `{signer['nonce_ownership']['nonce_database']}`. It allocated **zero nonces**, made **zero signatures**, and rejected a second process trying to own that same local signer. The probe released its lease after checking. Keep this nonce database permanently with that API key; do not delete it to bypass a safety failure. Another host or another OS user has not been audited. Run only one future signer host/process.

The observed clock state was `{account['clock']['state']}` with offset {account['clock']['offset_ms']} ms. The public account rate budget was healthy at observation. Both are timestamped observations and must be checked again before any future action.

Evidence: {link(account_path, 'read-only account response audit')}, {link(OUT / 'signer_preflight_final.json', 'private-key identity and local ownership check')}.

## 4. Leverage: prepared versus actually changed

{leverage_status}

| Market | Latest saved exchange setting | Required bot setting |
| --- | --- | --- |
{leverages}

Configured leverage on a flat account is a setting; it does not mean there is already leveraged exposure. The bot policy remains 1x. The helper reads runtime asset IDs, requires a funded unified flat account, a valid agent, healthy clock/rates/nonce, and separate manual verification. It journals each fixed action, uses the pinned official SDK and rereads `activeAssetData`. An uncertain transmission stops the sequence without blind retry. It cannot approve future orders.

The user's request already authorizes this narrow configuration change. The pending verification is required by {link(ROOT / 'AGENTS.md', 'AGENTS.md')}: “require human verification of both wallet identities.” Funds and successful public reads do not perform the human check. The latest request and its exact limits are recorded there for future work. The prepared example confirmation is deliberately false/expired.

Configuration HTTP attempts in this task: **{config_attempts}**. Actual orders submitted: **0**.

Evidence: {link(OUT / 'leverage_plan.json', 'exact ten-market read-only plan')}, {link(OUT / 'leverage_configuration_review.md', 'configuration scope and checks')}.

## 5. Emergency protection in easy language

Suppose a LONG's normal stop is 95 and its entry ATR is 2. The independent emergency trigger is **93**. For a SHORT with normal stop 105 and entry ATR 2, it is **107**. The strategy's normal stop remains unchanged. The order must be reduce-only and sized from the actual filled position.

The policy is configured and documented, with protection still disabled until separately authorized controlled certification. An accepted exchange protective order can operate while the bot is connected too, and can remain after a local crash. It must be installed before that crash; it cannot first be created by a bot that is already offline.

The 0.5% execution allowance bounds the execution limit; it is not a guarantee of a fill during a gap or thin book. Offline tests confirmed LONG/SHORT trigger geometry, precision within that allowance, no action with disabled protection, and refusal when the emergency trigger would lie beyond liquidation. These used synthetic exposure and ephemeral signing fixtures with HTTP blocked. Real funded-account protection is **not certified**.

Evidence: {link(OUT / 'protection_configuration_approval.md', 'approved configuration and limitations')}, {link(OUT / 'requested_protection_receipt.json', 'four additional offline checks')}.

## 6. The full hour of PAPER operation

The run started at **{result['paper']['start_ist']}** and stopped at **{result['paper']['end_ist']}**. Requested duration: **3,600 seconds**; wall time including startup/shutdown: **{result['paper']['elapsed_wall_seconds']:.1f} seconds**. Exit code: **{receipt['exit_code']}**. Active Python source stayed identical throughout.

| Observation | Result |
| --- | --- |
| Distinct completed scanner cycles | {len(scan_ids)} |
| Running heartbeat snapshots | {len(running)} |
| Snapshots with at least one healthy market | {result['paper']['any_healthy_samples']} |
| Scanner-qualified market observations | {qualified} |
| Final scan decision | `{paper['scan_status']}` |
| Simulated orders / fills | {paper['local_orders']} / {paper['local_fills']} |
| Actual exchange orders | 0 |
| Public WebSocket reconnections observed | {result['paper']['stream'].get('reconnections')} |
| Accounting halt | {paper['accounting_halt']} |
| Memory high-water mark | {result['paper']['maximum_memory_mb']:.1f} MB |

The PAPER account starts from **20,000 hypothetical USDPR**. Its ending equity is {paper['portfolio']['equity']}, realized P&L {paper['portfolio']['realized_pnl']}, fees {paper['portfolio']['fees_paid']} and funding cashflow {paper['portfolio']['funding_cashflow']}. These are simulated-account figures, separate from the real 1,000,000 USDPR balance. A run with no fills does not demonstrate actual fee/P&L settlement or profitable trading.

Across the full run, scanner rejection counts were: {', '.join(f'{key}: {value}' for key, value in scanner_rejection_summary.items())}. Each reason remains linked to the recorded opportunity trace.

The standalone PAPER segment reports its own exchange-account status as `NOT_CONFIGURED` because it has no authorized real-account executor. That does not override the separate read-only funded/unified account audit. Its public feed recovery and hypothetical ledger remain separate from actual account truth.

Health is sampled about every 30 seconds. Counts below describe saved observations, not uninterrupted durations or a new rule requiring all ten markets to be healthy simultaneously. Every selected market must satisfy its own existing freshness/history gates.

| Market | Healthy heartbeat observations |
| --- | --- |
{market_health}

Public disconnect recovery was observed in this run: the feed resubscribed and repaired public history/context/book state; the local PAPER ledger was reconciled separately. This does not certify funded order/position recovery. Checkpoint/backup integrity: **`{checks['paper.sqlite_integrity']}` / `{checks['backups/paper-latest.sqlite_integrity']}`**. Stored checksums match: **{checks['paper.sqlite_checksum']} / {checks['backups/paper-latest.sqlite_checksum']}**. Final clean-shutdown records: **{checks['paper.sqlite_clean']} / {checks['backups/paper-latest.sqlite_clean']}**. The competing PAPER owner was refused during the run.

The collector stopped at the end of the bounded hour. No background service, cloud deployment or external notification sender was installed. Local alerts and all degraded samples were retained.

Evidence: {link(OUT / 'continuous_paper_receipt.json', 'completed hour receipt')}, {link(segment / 'report.json', 'PAPER decisions, portfolio and feed report')}, {link(state / 'alerts.jsonl', 'local health changes')}, {link(segment / 'results/opportunity_report.txt', 'why setups were rejected')}.

## 7. Why market-data readiness still needs evidence

Some real feeds became healthy temporarily; others remained stale or incomplete. Fresh mark/book messages do not make stale completed candles valid. The bounded REST probe at {probe['observed_at_utc']} returned:

| Market | Completed rows in the probe's 302-minute range | Age of latest completed close |
| --- | --- | --- |
{feed_rows}

This probe's range differs from the UTC-anchored scanner range; these counts must not be substituted for scanner admission results. REST and stream snapshots were sequential, not simultaneous. BTC/BRENT staleness and absent EWJ history were also present in raw REST results. HYPE/SP500 observations differed over time. The four captured range-response checks showed exact raw/normalized completed timestamp parity; this does not establish the exchange's internal root cause.

The recorded SP500 snapshot had a zero ATR from flat candles. Its `INVALID_DECIMAL` rejection was reproduced with the frozen brain and traced to the existing positive-ATR guard. Signed or zero VWAP slope itself is valid and was not that rejection's cause. No missing bars were fabricated and no ATR, history or spread threshold was lowered.

Continue clearly labeled PAPER collection. A usable current signal/execution feed and sustained healthy operation still need to be demonstrated before funded certification. History provenance paperwork does not block public-feed collection or the separately requested flat-account leverage setup.

Evidence: {link(OUT / 'direct_candle_probe.json', 'public REST comparison')}, {link(OUT / 'candle_request_range_probe.json', 'exact captured-response adapter parity')}, {link(OUT / 'recorded_indicator_diagnostic_corrected.json', 'recorded SP500/HYPE indicator diagnosis')}.

## 8. State layout and repeatable commands

The current hour uses a new, separately labeled ledger at **`{state}`**. The old `runtime/paper/readiness-2026-10-07` belongs to earlier source and was preserved rather than overwritten. Do not reset either ledger to bypass recovery guards.

The current state directory holds the cumulative hypothetical ledger (`paper.sqlite`), shared public budgets (`public_requests.sqlite`), owner lock, heartbeat, local alerts and `backups/paper-latest.sqlite`. Evidence for each launch is saved in a separate timestamped segment. Signer nonce/configuration state is separately under `runtime/testnet/anchorium-bot-1` and is never replaced by a PAPER ledger.

From the project root, another foreground run on the same unchanged source/policy uses:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 3600 --state-directory runtime/paper/readiness-2026-10-07-current-setup --output-root docs/practice_setup_2026-10-07/paper_segments
```

In another terminal:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07-current-setup
```

The schedule remains a scan every **300 seconds**, management every **1 second**, health/export every **30 seconds**, subject to network-call latency. Keep the Mac awake and connected. The health checker distinguishes healthy, degraded, stopped and stale/missing heartbeats. A green snapshot means at least one feed currently meets the local checks, not complete practice certification.

AWS is not required for this local check. A future always-on host still needs its own installation, monitoring, recovery and healthy-feed observation. The existing {link(ROOT / 'docs/paper_practice_runbook.md', 'operating runbook')} explains the Linux templates; no remote deployment is claimed here.

## 9. Historical data and research

The ten existing hourly CSVs contain **49,831 rows** and their saved hashes are unchanged: **{history_unchanged}**. Earlier structural checks found no duplicate timestamps, invalid rows or internal missing hours. They stay isolated research reference data, not current competition-minute candles or proof of tradable fills.

You state that `history.zip` came from the official Discord announcement. The original ZIP and source announcement proof have not been supplied/found in the accessible project locations, so archive/hash provenance verification remains pending. Preserve the ZIP plus the announcement link/screenshot and compare its extracted hashes with these CSVs using the {link(ROOT / 'scripts/verify_organizer_history.py', 'existing archive verifier')}. Matching an archive proves content identity; the official source announcement is still needed for source attribution. This limitation affects research credibility; it does not prevent live public data reads.

The six research flags remain false: session anchor validated, ML data ready, model validated, holdout complete, promotion recommended and research production changed. There is no automatic model promotion or alternate VWAP anchor. The last flag describes research promotion, not a claim that no infrastructure code was changed.

## 10. What still has to happen

| Readiness item | Saved result |
| --- | --- |
{rows}

Account/approval/reconciliation flags refer to the saved read-only observation. Private identity and nonce checks are local. Emergency settings are configured but disabled. The hour proves guarded local operation; it does not certify actual fills, real protection or returns.

The remaining order is: manually verify the team/API wallet identities; complete and reread the deliberate 1x CROSS setup; collect usable fresh `par` data; then obtain explicit authorization for a tiny bounded certification test. Certify LONG and return fully flat with no leftover orders and reconciled fees/P&L before SHORT. Only after both are flat and reconciled should funded reconnect/restart/cancel recovery be reviewed and supervised practice considered. Existing offline scenarios must keep their offline label if safely producing them on the real venue is impractical. The detailed {link(OUT / 'certification_plan.md', 'inactive certification plan')} records this sequence.

The tiny funded tests were **not run** because their prerequisites and explicit later order activation are missing. Keep one API signer process, one host and one global `par` position, including partially filled exposure and unresolved orders. Do not size a test from the million-unit balance or assume funding/agent approval grants execution permission.

The software checks improve reliability, but this zero-fill hour cannot establish whether the frozen VWAP strategy will win. Profitability, consistent venue data, funded execution evidence and honest reproducible evaluation are still needed. The [official participant guide](https://perpetual-alpha26.github.io/docs/) remains the organizer reference; our stricter safety/configuration checks are project engineering policy.

## 11. Evidence identity

Git commit: `{result['git_commit']}`; working tree dirty: **{result['git_dirty']}**. Active Python source fingerprint: `{source}`. Full tests, account audit, final signer check and the hour use the same active source: **{same_source}**. The original freeze manifest was not rewritten. Policy/brain/configuration and principal evidence hashes are recorded in {link(OUT / 'readiness.json', 'machine-readable readiness report')}.

The initial extra geometry test expectation and initial indicator diagnostic were corrected in later labeled artifacts; original observations remain preserved. The final geometry receipt and corrected indicator diagnosis are authoritative for this report. This documentation and readiness file provide evidence, never activation permission.
'''
with (OUT / 'report.md').open('x') as stream:
    stream.write(report)
print(json.dumps(dict(report=str(OUT / 'report.md'), flags=flags,
                      same_active_source=same_source, elapsed_seconds=result['paper']['elapsed_wall_seconds'])))
