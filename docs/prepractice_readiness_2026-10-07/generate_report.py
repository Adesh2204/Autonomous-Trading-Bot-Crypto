"""Summarize saved evidence; never turns a readiness observation into activation."""
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
from exchange.paper_operations import active_source_hash
from exchange.paper_checkpoint import unpack


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []


def local_time(value):
    return datetime.fromtimestamp(value, timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()


def link(path, label):
    return '[' + label + '](<' + str(path.resolve()) + '>)'


account = read(OUT / 'account_check.json')
tests = read(OUT / 'test_receipt.json')
feed = read(OUT / 'market_freshness.json')
reconnect = read(OUT / 'public_reconnect.json')
ops = read(OUT / 'operating_checks.json')
continuous = read(OUT / 'continuous_paper_receipt.json')
restart = read(OUT / 'restart_paper_receipt.json')
receipts = [continuous, restart]
if any('finished_unix' not in r for r in receipts):
    raise RuntimeError('PAPER_OBSERVATION_NOT_COMPLETE')
samples = lines(OUT / 'continuous_health_samples.jsonl') + lines(OUT / 'restart_health_samples.jsonl')
segments = []
for receipt in receipts:
    segment = Path(receipt['final_health']['segment'])
    report = read(segment / 'report.json')
    bars = lines(segment / 'candles.jsonl')
    scan_ids = sorted({r['scan_observed_at_ms'] for r in bars})
    segments.append(dict(path=str(segment), start_ist=local_time(receipt['started_unix']),
        end_ist=local_time(receipt['finished_unix']), requested_duration_seconds=receipt['requested_duration_seconds'],
        exit_code=receipt['exit_code'], source_unchanged=receipt['source_unchanged'], scans=len(scan_ids),
        cumulative_local_orders=report['local_orders'], cumulative_local_fills=report['local_fills'],
        scan_status=report['scan_status'], portfolio=report['portfolio'], accounting_halt=report['accounting_halt'],
        recovery=read(segment / 'paper_recovery.json'),
        rejections={d['symbol']: d['reasons'] for d in report['diagnostics']},
        final_health=receipt['final_health']))
state = Path(continuous['state_directory'])
db = sqlite3.connect((state / 'paper.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
checkpoint_integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
data, expected_hash = db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
checkpoint_checksum = hashlib.sha256(data.encode()).hexdigest() == expected_hash
checkpoint = unpack(json.loads(data))
db.close()
backup = sqlite3.connect((state / 'backups/paper-latest.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
backup_integrity = backup.execute('PRAGMA integrity_check').fetchone()[0]
backup.close()
healthy = [s for s in samples if s['status'] == 'RUNNING' and s['data_healthy'] and s['severity'] == 'OK']
healthy_symbols = sorted({symbol for s in healthy for symbol in s['healthy_markets']})
all_markets_continuously_healthy = bool(healthy) and all(len(s['healthy_markets']) == 10 for s in samples if s['status'] == 'RUNNING')
hash_now = active_source_hash(ROOT)
same_source = (tests['source_hash_before'] == tests['source_hash_after'] == hash_now ==
               account['active_source_hash'] and all(r['source_unchanged'] and
               r['source_hash_before'] == hash_now for r in receipts))
offline_pass = tests['exit_code'] == 0 and tests['totals']['failures'] == tests['totals']['errors'] == 0 and same_source
paper_operational = bool(offline_pass and healthy and all(s['exit_code'] == 0 and
    s['final_health']['status'] == 'STOPPED' and not s['accounting_halt'] for s in segments) and
    segments[1]['recovery'].get('restored') and checkpoint_integrity == backup_integrity == 'ok' and checkpoint_checksum)
flags = dict(MARKET_DATA_READY=all_markets_continuously_healthy,
             ACCOUNT_READY=account['account_ready_read_only'], API_AGENT_READY=account['api_agent_ready_read_only'],
             RECONCILIATION_READY=account['reconciliation_ready_read_only'],
             PROTECTION_READY=False, PAPER_READY=paper_operational, LIVE_READY=False,
             ACCOUNT_RISK_CONFIGURATION_READY=False, API_SIGNER_VERIFIED=False,
             CONTROLLED_EXECUTION_CERTIFIED=False, OVERALL_FUNDED_PRACTICE_READY=False)
result = dict(observed_at_ist=local_time(datetime.now(timezone.utc).timestamp()),
    flags=flags, flag_scope='Read-only snapshot and bounded local PAPER operations; no activation permission',
    git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    git_dirty=True, active_source_hash=hash_now, all_final_checks_use_same_active_source=same_source,
    tests=tests['totals'], strategy_freeze=tests['checks']['strategy_freeze']['result'],
    phase0=tests['checks']['phase0']['result'], exchange_orders_submitted=0, account_actions_submitted=0,
    account_observed_at_ist=account['observed_at_ist'], team_wallet=account['team_address'],
    api_wallet=account['api_wallet_address'], account_equity=account['reported_equity'],
    healthy_paper_heartbeat_samples=len(healthy), total_heartbeat_samples=len(samples),
    heartbeat_severities=dict(Counter(s['severity'] for s in samples if s['status'] == 'RUNNING')),
    markets_healthy_at_least_once=healthy_symbols, paper_segments=segments,
    public_reconnect_passed=reconnect['passed'], operating_checks=ops,
    final_checkpoint_integrity=checkpoint_integrity, final_backup_integrity=backup_integrity,
    checkpoint_checksum_valid=checkpoint_checksum, checkpoint_clean_shutdown=checkpoint['clean'],
    evidence=dict(account='account_check.json', tests='test_receipt.json', market='market_freshness.json',
                  continuous='continuous_paper_receipt.json', restart='restart_paper_receipt.json',
                  reconnect='public_reconnect.json'))
(OUT / 'readiness.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
table = '\n'.join('| ' + k + ' | **' + ('YES' if v else 'NO') + '** |' for k, v in flags.items())
market_rows = []
for symbol, row in feed['markets'].items():
    age = 'Unavailable' if row['completed_age_ms'] is None else f"{row['completed_age_ms'] / 1000:.1f} seconds"
    market_rows.append(f"| `{symbol}` | {row['raw_completed_count']} | {age} | {'YES' if row['completed_fresh'] else 'NO'} |")
leverages = '\n'.join(f"| `{s}` | {v['leverage']['value']}x {v['leverage']['type']} | 1x cross |"
                      for s, v in account['active_asset_data'].items())
expiry = local_time(account['configured_api_approval_matches'][0]['validUntil'] / 1000)
segment_rows = '\n'.join(f"| {'Continuous' if i == 0 else 'Clean restart'} | {s['requested_duration_seconds']} seconds | {s['scans']} | {s['exit_code']} | {s['scan_status']} |"
                         for i, s in enumerate(segments))
report = f'''# Team Anchorium: pre-practice verification — 7 October 2026

The software passed its safety checks and bounded PAPER operating checks. The configured team account is funded and already unified. **Funded automated practice is still blocked:** market freshness is inconsistent, exchange leverage differs from policy, emergency protection is unapproved, and controlled execution certification has not happened. No exchange order or account administration was performed.

## 1. The safety lock and strategy

`EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` remain enforced. The original NSE repository was untouched. Angel One execution stays blocked. No private key was used, no real signer was constructed for the account checks, and no account mode, approval or leverage setting was changed.

The strategy-freeze check passed against `nse-working-baseline`: the protected brain file, 8 protected methods and 32 parameters match. VWAP, EMA, ATR, long/short rules, stops, targets, cooldowns and direction flips were preserved. Phase-0 passed all 12 checks.

The first full test run passed 1,198 tests. The final run after the accounting correction passed **{tests['totals']['tests']:,} tests, zero failures, zero errors, zero skipped**, including 16 new unified-account regressions. Existing recovery, fee/funding, partial-fill, stale-feed, lockout and compliance scenarios were included. These are offline engineering tests, not proof of trading profit or funded execution.

Evidence: {link(OUT / 'test_receipt.json', 'final test receipt')} and {link(OUT / 'regression.xml', 'full test results')}.

## 2. Your actual account

The read-only check completed at **{account['observed_at_ist']}** using your current configured team address, rather than the different address in an earlier conversation.

| Item | Observed result |
| --- | --- |
| Network / venue | Hyperliquid testnet / `par`, runtime DEX index 257 |
| Team wallet | `{account['team_address']}` |
| Account mode | `unifiedAccount` |
| Reported USDPR balance | 1,000,000 |
| USDPR token | 3032, matched to runtime `par` metadata |
| API wallet | `{account['api_wallet_address']}` |
| API approval | Approved as `anchorium-bot-1` |
| Approval expiry | {expiry} |
| `par` positions | 0 |
| Ordinary and trigger-aware open orders | 0 |
| Account action budget | 3 used / 10,000 cap; 9,997 remaining at observation |

You **do not need to switch this observed account to unified mode again**. It is already unified. The API approval check verifies the public approval and expiry; it does not test your private signing key or establish human wallet verification.

`userFees` reported base taker 0.045% and maker 0.015%. The venue's documented undiscounted scaling gives 0.09% taker and 0.03% maker, matching the current PAPER assumptions. Future actual fees must come from each reported fill. See the [official participant guide](https://perpetual-alpha26.github.io/docs/).

The account observer reconciled the explicit window from **5 October 2026 00:00 UTC** to the saved observation. It found no fills, funding payments, positions or orders in that window and did not pause entries. Earlier lifetime history and future changes are not certified. Reconciliation must run again on actual startup and reconnect. Evidence: {link(OUT / 'account_check.json', 'account query audit and responses')}.

## 3. The accounting correction made during this check

The account was genuinely funded, but the old reader used `clearinghouseState.marginSummary.accountValue`. That per-DEX field returned zero, making the bot incorrectly say “not funded.” Hyperliquid documents that unified balances and holds belong in the spot state and that per-DEX balance summaries are not meaningful. See [official account abstraction documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes).

The reader now uses the reported USDPR spot total once, verifies its token against runtime metadata, and reports its source. Position margin comes from reported `par` positions. It does not add per-DEX balance summaries or unrealized P&L to the spot balance. Unknown withdrawable capacity remains `null`; total balance is not invented free margin. Exact coin/side capacity still comes separately from `activeAssetData.availableToTrade` and `maxTradeSzs`.

The real account was flat during this verification. Actual non-flat equity/margin comparisons and real fill/fee/funding accounting still require controlled funded practice. The synthetic regressions do not certify those real-account scenarios.

Metadata changes to the collateral token now invalidate the client. The regression tests cover zero per-DEX summaries, held funds, overlapping P&L, other currencies, wrong/duplicate tokens, invalid balances and unchanged live locks. The Phase-0 environment test was also corrected to accept public account settings while checking the safety controls; failures no longer compare the entire configuration containing unrelated credential values.

## 4. Competition market data

All ten runtime markets use prefixed `par:` names. Market-wide queries explicitly select `dex=par`. There is no fallback to plain BTC, ETH or the native venue.

The REST/45-second WebSocket diagnostic completed at **{feed['observed_at_utc']}**. It received {feed['websocket']['messages']} WebSocket messages with no stream error. Its initial candle observations were:

| Market | Returned completed bars | Age after latest bar closed | Within 120-second freshness limit |
| --- | --- | --- | --- |
{chr(10).join(market_rows)}

All raw candle timestamps matched the adapter. This supports a venue-history limitation in that observation rather than a timestamp conversion error. Some markets had no recent trades or no returned history. A later observation can differ; these are timestamped results.

Books were current in the initial check. Mark, oracle and funding fields were received separately in the public contexts. Their API contexts do not expose an exchange publication clock, so the report preserves local observation time rather than claiming a verified oracle-update timestamp. A fresh book/context alone never makes old candles usable.

The scanner still requires 300 completed bars, the existing ATR floor of 0.40%, spread no greater than 15 bps and the unchanged Top-3 selection. It did not fabricate missing candles, widen limits or force trades. See {link(OUT / 'market_freshness.json', 'raw REST and WebSocket evidence')}.

## 5. Complete PAPER operation, monitoring and recovery

The intended host for these checks was the current Mac. The full launcher started the configured public feed, scanner, frozen strategy, risk controls, simulated execution, local ledger, monitoring and recovery pipeline. It used a separately labeled **20,000 hypothetical USDPR** starting balance. Your actual 1,000,000 USDPR account was observed separately and was not used as simulated starting cash.

| Segment | Requested running time | Completed scans | Exit code | Last scan decision |
| --- | --- | --- | --- | --- |
{segment_rows}

The continuous segment ran from {segments[0]['start_ist']} to {segments[0]['end_ist']}, including startup/shutdown overhead. The restart reused the same source, policy and durable ledger. It did not reset the balance or erase earlier decisions. Recovery reported restored state and a previous clean shutdown. Both processes stopped intentionally at their duration limits.

There were **{len(healthy)} healthy running heartbeat observations** among {len(samples)} total saved samples. Markets healthy at least once: {', '.join(healthy_symbols) or 'none'}. Healthy samples are intermittent; they do not establish 11 minutes of uninterrupted healthy data or all-market readiness. Warning samples and rejection reasons were preserved too.

No simulated orders or fills were generated in these segments. Every scan rejected all markets for insufficient completed history, so the live-public signal calculation and trading path were not exercised beyond that guard. The scanner recorded its actual rejection reasons. PAPER equity remained 20,000 with no trading fees or position funding. This demonstrates a stable zero-exposure ledger; actual entry/exit P&L and funding settlement were not exercised by this public run. Their existing offline test coverage passed. A zero-trade return is not evidence of profitability.

The separate public recovery experiment deliberately closed one actual BTC WebSocket. The existing engine reconnected once, resubscribed and completed REST history/book/context repair, reaching recovery generation 2. A quote was read after repair. This is genuine public-feed recovery, not certification of order recovery on a funded account. See {link(OUT / 'public_reconnect.json', 'controlled public reconnect evidence')}.

The second-owner check correctly rejected a competing process. Checkpoint and backup integrity are `{checkpoint_integrity}` / `{backup_integrity}`, the checkpoint checksum matches, and the final clean-shutdown flag is `{checkpoint['clean']}`. Open exposure or unresolved PAPER orders would require replay review on restart; that guard remains enforced.

The schedule remains scanning every 300 seconds, management every second, and health/export checks every 30 seconds. State is under `{state}`: `paper.sqlite`, `public_requests.sqlite`, `owner.lock`, `health.json`, `alerts.jsonl` and `backups/paper-latest.sqlite`. Evidence segments live separately under this report directory. Health/alerts are local files; external notifications have not been configured. The collector was stopped at the end of these checks and is not running continuously in the background.

## 6. What still blocks funded automated practice

**Leverage configuration:** the bot's reviewed risk policy is 1x cross. Every inspected exchange market differs:

| Market | Observed exchange setting | Bot policy |
| --- | --- | --- |
{leverages}

This is the configured leverage, not a claim that the current empty account already has leveraged exposure. Do not raise the bot's policy merely to match these defaults. A separately authorized, manually verified setup must align intended market leverage and recheck capacity before funded practice. No exchange setting was changed here.

**Emergency protection:** `configs/reliability_policy.json` still has protection disabled, no approval reference, no approved distance and no approved execution allowance. The existing proposed policy is one ATR beyond the normal stop with a 0.5% execution allowance. That proposal is not approved or enabled. Normal strategy stops/targets remain unchanged. See {link(ROOT / 'docs/emergency_protection_policy_2026-10-05.md', 'protection policy explanation')}.

**Market readiness:** keep rejecting stale or insufficient histories. Continue collecting honest PAPER evidence when the feed supports the unchanged history/freshness rules. Do not fill missing minutes with invented prices or lower thresholds to create activity.

**Execution certification and explicit activation:** the public account observations do not authorize signatures. Private signer verification, reviewed protection, fresh reconciliation, healthy feed and controlled account certification remain future work. Only the human's explicit change after manual verification can authorize future testnet execution. Mainnet and Angel One remain outside this migration.

## 7. Readiness flags and their meaning

| Flag | Result |
| --- | --- |
{table}

`ACCOUNT_READY`, `API_AGENT_READY` and `RECONCILIATION_READY` mean the saved **read-only** funded/approval/flat-window checks passed. `PAPER_READY` means the guarded local launcher, bounded run and flat restart passed. It does not mean every feed is healthy, the strategy is profitable, or funded execution is ready. `MARKET_DATA_READY` is strict all-market readiness and stays NO because freshness was inconsistent. `LIVE_READY` stays NO regardless of the public approvals.

## 8. Operating instructions

For another foreground PAPER run on the same unchanged source/policy/ledger, from the project root:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 3600 --state-directory runtime/paper/readiness-2026-10-07 --output-root docs/prepractice_readiness_2026-10-07/paper_segments
```

In another terminal, inspect its heartbeat:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07
```

Exit 0 means healthy, 2 means degraded, 3 means stopped/failed, and 1 means stale/missing/invalid heartbeat. Keep the Mac awake, online and with sufficient disk. Restart with the same state; do not delete a failed checkpoint to bypass its guard. Source/policy changes require separately labeled evidence or reviewed migration, rather than silently reusing performance history.

AWS is not required for these local PAPER checks. Uninterrupted practice needs an always-on reliable host. The repository contains Linux service/health/rotation templates, but no remote server was deployed or tested in this task. The existing runbook proposes 2 vCPUs, 4 GB RAM and roughly 80 GB SSD as a starting estimate; those are engineering estimates, not organizer requirements or current pricing. A 24–48 hour healthy-feed run on the final host remains recommended before activation. See {link(ROOT / 'docs/paper_practice_runbook.md', 'operating runbook')}.

## 9. Reproducibility and limits

Git commit: `{result['git_commit']}`. The working tree contains uncommitted changes, so the active Python source fingerprint is also recorded: `{hash_now}`. The final full suite, corrected account check and both PAPER segments use that same active source. The initial market diagnostic predates the account-reader correction; its candle parser and freshness logic were unchanged.

The audit scripts and original failed-readiness evidence were preserved in this directory. {link(OUT / 'readiness.json', 'machine-readable readiness')} links the receipts and segment details. Healthy and degraded observations remain clearly labeled PAPER evidence. No unvalidated ML model, alternate VWAP anchor, strategy optimization or research promotion was enabled. These checks improve readiness; they do not establish a winning return or guarantee a competition result.
'''
(OUT / 'readiness.md').write_text(report)
print(json.dumps(dict(report=str(OUT / 'readiness.md'), flags=flags,
                     same_active_source=same_source, healthy_samples=len(healthy))))
