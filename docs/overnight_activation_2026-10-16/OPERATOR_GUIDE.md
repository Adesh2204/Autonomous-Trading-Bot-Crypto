# Local overnight terminal — October 16–17

The current release has no executable trading approval. Native triggered Stop Limit/partial residual qualification is missing, so `prepare` produces a blocked proposal. The commands below use the real parser. No command or report authorizes signing by itself.

## Environment and diagnostics

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
source .venv/bin/activate
python scripts/anchorium_cli.py doctor
python scripts/anchorium_cli.py doctor --online
python scripts/anchorium_cli.py simulate --output "runtime/terminal/simulation-$(date -u +%Y%m%dT%H%M%SZ)"
```

The clone's activation scripts select its own `.venv`; the original NSE repository is untouched. Dependencies already match the pinned requirements and SDK 0.24.0. No package installation was needed. Keep `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false`; the separate exact TESTNET capability is the only approved signing route. The CLI does not use paid LLM calls or require Codex. Keep the local VS Code/Terminal Python process, this Mac, power and internet running. Closing the terminal, forced sleep, power loss or a network outage can interrupt management.

## Fresh overnight proposal

Use a fresh output directory; never overwrite original evidence:

```sh
PROPOSAL="runtime/terminal/overnight-$(date -u +%Y%m%dT%H%M%SZ)"
python scripts/anchorium_cli.py prepare --overnight --output "$PROPOSAL" --maximum-notional 1000
```

`--overnight` is specifically for creation/approval on October 16, 2026. It proposes a hard signing/management expiry of **October 17 at 12:00 IST**, stops new entry at **11:45**, and requests the existing guarded risk close from **11:55**. There is no new date rollover or automatic renewal. Observation lifetime remains independent. The old single-day mode without `--overnight` remains strict and ends no later than 23:57 of that IST day.

The proposal is LONG only, 1x CROSS, 20,000 TEST USDPR bankroll, maximum two entry attempts TOTAL across midnight, one concurrent global position, 0.5% per-trade risk and 1% daily/session loss. Attempts, allocation, actual P&L, peak equity and drawdown never reset at midnight. A 1,000 nominal ceiling gives at most 2,000 cumulative entry allocation; current liquidity and every safety check can reduce executable size to zero. Maximum 12 signed actions and two owned cancellations remain exact caps. A loss-making risk exit requires the accepted scope and all final checks. A Stop Limit can remain unfilled through a gap; intended stop distance is not a guaranteed loss limit.

Current result: **BLOCKED_NOT_AUTHORIZATION**. There is no `mandate.json`, `acceptance.json` or usable trading ID. A proposal digest is an audit identity only. A valid stop qualification must first establish native linked SELL fills and subminimum residual feasibility; a historical IOC close is insufficient. Do not approve a blocked proposal as a workaround.

## After genuine venue prerequisites exist

These are parser-valid templates, not instructions to execute the currently blocked release. `NATIVE_PROOF` must identify actual independently verified raw native qualification evidence; this release does not contain such a file. Use a fresh proposal and approve within its five-minute acceptance window.

```sh
RELEASE='docs/overnight_activation_2026-10-16/regression_release_final/test_receipt.json'
: "${NATIVE_PROOF:?Set NATIVE_PROOF to genuine independently qualified native proof}"
PROPOSAL="runtime/terminal/overnight-approved-$(date -u +%Y%m%dT%H%M%SZ)"
python scripts/anchorium_cli.py prepare --overnight --output "$PROPOSAL" --maximum-notional 1000 --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
python scripts/anchorium_cli.py approve --mandate "$PROPOSAL/mandate.json" --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
/usr/bin/caffeinate -i python scripts/anchorium_cli.py start --authorized --mandate "$PROPOSAL/mandate.json" --acceptance "$PROPOSAL/acceptance.json" --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
```

Only the human may type the complete `APPROVE <mandate ID>` acceptance after reviewing all fields and risk acknowledgments. The approval must name the team/API wallets, this exclusive signing host and full source/release/protection hashes. The program has no automatic approval flag. Actual start was not run during this development assignment. Missing evidence is rejected before key access. No new BUY/SELL, wallet signature or acceptance was produced.

`caffeinate -i` is the existing macOS process-bound sleep-prevention command; it was checked with a benign Python process. It cannot prevent power failure, forced sleep, loss of internet or a venue outage.

## Status, report and manual stop

In a second terminal, use the same environment and state directory (default `runtime/terminal`):

```sh
python scripts/anchorium_cli.py status
python scripts/anchorium_cli.py report
python scripts/anchorium_cli.py stop
python scripts/anchorium_cli.py status
python scripts/anchorium_cli.py report
```

STOP persists the exact current session request. It immediately revokes new entries at the final signing boundary. Only previously authorized risk closes and owned stop cleanup may occur before the original hard expiry. Ctrl+C and SIGTERM stop the entire application; neither guarantees flattening. Wait for a final result and two actual authoritative flat/zero-order readbacks. Residual/uncertain exposure remains EXPOSED/UNKNOWN and requires a separate decision. Never blindly resubmit an uncertain order or restart a stopped signer.

Shutdown first quiesces collectors, then allows bounded read-only rate recovery for up to 180 seconds. Rate caps/reserves are unchanged. A local rate wait is not HTTP429. Exceptions retain sanitized reasons/stacks; original unresolved order records and certificates remain preserved. Account history resumes with overlap where established; unresolved history is not silently discarded. A terminal failure stays UNKNOWN until authoritative evidence establishes otherwise.

For explicit public-only development diagnostics, `start --state <fresh-state> --duration 900 --scan-seconds 60` creates no signer. Continuous observation uses `start` without a duration. These commands must not be described as trading activation. Structured events, status, receipts, SQLite and terminal reports live under the state's `sessions/<identity>` directory. Receipt/event rotation and memory/disk limits remain enabled; old rotation archives are finite, not an unlimited history certificate.
