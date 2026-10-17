# Anchorium local terminal

Later October 16–17 repair release: [overnight operator guide](</Users/adesh/Autonomous Trading Bot - Crypto /docs/overnight_activation_2026-10-16/OPERATOR_GUIDE.md>). This document retains the original 2,574-test single-day release history.

Run from macOS Terminal or the VS Code integrated Terminal. The repository name has a literal trailing space. Keep this terminal process running; Codex and the Codex desktop app can be closed. Network connectivity, power and this Mac remain required. A local process cannot guarantee stop execution during a host outage. The initial release has no new trading approval and native protection qualification remains blocked.

## Setup and diagnostics

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
source .venv/bin/activate
python scripts/anchorium_cli.py doctor
python scripts/anchorium_cli.py doctor --online
```

The cloned activation scripts were repaired to select this repository’s `.venv`; their copied prefix previously selected the original NSE environment. Only this clone was edited. `activation_repair_receipt.json` records the local repair.

All dependencies were already installed at release validation. No installation was necessary. The requirements now describe those tested versions. If a later `doctor` shows missing or mismatched packages, use the existing environment and exact requirements; pip leaves already satisfied packages alone:

```sh
python -m pip install -r algo-trading-bot/requirements.txt
python -m pip check
python scripts/anchorium_cli.py doctor
```

The release checked the installation command with `--dry-run --no-index`, and checked `pip check`. The ordinary install was not run because nothing was missing. The official exchange SDK stays pinned to 0.24.0. Changing dependencies requires a new release validation before signing. Do not set LIVE flags. Diagnostics do not print secrets, load wallet keys, or sign.

## Complete offline simulation and research

Use a new output directory each time; existing evidence is never overwritten.

```sh
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
python scripts/anchorium_cli.py simulate --output "runtime/terminal/simulation-$RUN_ID"
python scripts/anchorium_cli.py research --snapshot docs/quant_engine_2026-10-16/fresh_baseline/snapshot.json --output "runtime/terminal/research-$RUN_ID" > "research-$RUN_ID.log"
```

Simulation drives the preserved frozen strategy, central validation, official SDK with ephemeral fixtures, native Stop Limit adapter, account reconciliation and daily coordinator. Every replay record is SIMULATION; none is a real exchange fill. Fault episodes retain residual/unknown state. The replay's synthetic whole-unit venue is explicitly separate from actual `par:` lot sizes. Research uses the named historical public snapshot, with its recorded time; it is not a fresh proposal. Six isolated exits and $25,000/$50,000 stress tiers cannot promote themselves to the production strategy.

## Start continuous market observation

```sh
python scripts/anchorium_cli.py start
```

This is foreground TESTNET OBSERVATION, without a signer, and runs until STOP, Ctrl+C, fatal persistence/source/host failure or external termination. It observes all ten runtime `par:` markets by default. It prints computed decisions, rejected reasons and independently observed bid/ask capacity. The displayed higher-timeframe veto is research/observation only; the production strategy remains frozen. A candidate or book capacity is not SIGNAL_APPROVED or permission to trade.

Account reads use authoritative REST accounting. Four account WebSocket subscriptions and market subscriptions must be acknowledged; WebSocket notifications invalidate account truth and wake bounded reconciliation. REST fallback labels do not establish HTTP429. Actual errors are recorded separately. Normal account scans are every 300 seconds; events can request a rate-controlled refresh after 30 seconds. Account and fee ages stay explicit. Missing exchange clocks remain null. Stale/gapped candles independently block signals even if a book is fresh.

A bounded development check is available; it does not extend any signing window:

```sh
python scripts/anchorium_cli.py start --duration 780 --scan-seconds 60
```

In another terminal, from the same directory and environment:

```sh
python scripts/anchorium_cli.py status
python scripts/anchorium_cli.py report
python scripts/anchorium_cli.py stop
python scripts/anchorium_cli.py status
python scripts/anchorium_cli.py report
```

`stop` writes a durable request for the exact current session identity. It does not send an OS signal to a possibly reused PID. Status uses the held owner lock and heartbeat age; a dead process is shown as interrupted, and cached flatness is withdrawn. A graceful final report needs two actual distinct authoritative flat/zero-order readbacks. STOP is a request; wait for the terminal result before treating shutdown as complete.

To watch the structured events for the current application:

```sh
RUN_DIR=$(python -c 'import json; print(json.load(open("runtime/terminal/current.json"))["output"])')
tail -f "$RUN_DIR/events.jsonl"
```

`status.json`, `report.md`, `terminal_result.json`, `public.sqlite` and public `info_receipts.jsonl` live in this session directory. Internal event retention is four 8 MB archives plus current; receipt retention is eight 16 MB archives plus current. Old archives expire explicitly, so these files are not an unlimited historical certificate. SQLite files above 512 MB, memory above 2 GB, or disk free space below 10% halt the observer for operator archiving/review. Terminal stdout remains controlled by the operator; an external redirect is a separate log file. Never delete the original qualification journal, nonce database, raw UNKNOWN row/certificate or original trade proofs.

## Fresh proposal, local human approval and authorized start

The default proposed bankroll is 20,000 TEST USDPR, not the full account balance. The default proposed notional ceiling is 1,000; permitted input ceilings are 10 through 10,000. The unchanged controls are LONG only, 1x CROSS, one concurrent position, at most two entry attempts, 0.5% per-trade risk, 1% daily loss and 10% participation on BOTH best levels and finite L2/exit liquidity. Actual available collateral, runtime maxTradeSz/precision, stop economics and every stricter risk check can reduce size to zero. No splitting, leverage escalation or arbitrary minimum-size enlargement is permitted.

```sh
PROPOSAL="runtime/terminal/proposal-$(date -u +%Y%m%dT%H%M%SZ)"
python scripts/anchorium_cli.py prepare --output "$PROPOSAL" --minutes 60 --maximum-notional 1000
```

This performs fresh public account and market reads and writes `proposal.json` plus raw receipts. **Today it reports BLOCKED and does not create an executable mandate or acceptance.** No approval should be requested for an impossible protective/residual path. A valid native qualification must establish the unchanged smallest-lot protection and residual behavior; an untriggered accepted stop does not establish a triggered closing fill. Do not use the historical IOC exception as a native-stop exemption.

Once genuine prerequisites have separately been established, use the actual source-bound release receipt and actual raw native proof file. The following shell variables are intentionally required paths supplied by the operator; there is no claimed native proof file in this release:

```sh
PROPOSAL="runtime/terminal/approved-proposal-$(date -u +%Y%m%dT%H%M%SZ)"
: "${RELEASE:?Set RELEASE to the matching complete test_receipt.json path}"
: "${NATIVE_PROOF:?Set NATIVE_PROOF to the actual qualified native protection proof path}"
python scripts/anchorium_cli.py prepare --output "$PROPOSAL" --minutes 60 --maximum-notional 1000 --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
python scripts/anchorium_cli.py approve --mandate "$PROPOSAL/mandate.json" --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
python scripts/anchorium_cli.py start --authorized --mandate "$PROPOSAL/mandate.json" --acceptance "$PROPOSAL/acceptance.json" --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
```

Use a fresh, empty PROPOSAL directory when repeating preparation. `approve` requires an interactive human terminal and the exact full mandate ID typed after displaying every limit and acknowledgment. It has no automatic acceptance flag. Acceptance expires for approval after five minutes and cannot be overwritten. Starting requires the exact genuine acceptance, matching source/release/XML/dependencies, policy and raw native proof before any key access. A prior session cannot be restarted or renewed. The actual signing command was checked through `--help`, missing-evidence rejection, offline integration and negative tests; no genuine authorized start was executed during release validation.

The bounded signing session cannot cross its specified IST day and ends no later than 23:57. Local observer lifetime is independent: after the signer closes, the application continues public observation with no signer. A new day does not renew permission. STOP immediately blocks new entries at the final signing boundary; only exact already-authorized risk exits and owned-order cleanup remain possible until the original expiry. Partial, rejected, uncertain or unprotected exposure halts entries. If final risk closure is unauthorized or fails, the app reports EXPOSED/UNKNOWN for human review rather than blindly repeating or claiming flatness. Native Stop Limit execution has a gap/nonfill risk. Closing at a loss is allowed only by the exact approved risk mandate, not by observation mode.

## If shutdown reports UNKNOWN

The bounded shutdown reconciliation can fail even when the last observed account was flat. Preserve the raw result and treat it as UNKNOWN until two fresh authoritative position/zero-order readbacks succeed. After rate backoff, perform a new public-only audit with a new output directory:

```sh
python scripts/anchorium_cli.py prepare --output "runtime/terminal/post-stop-$(date -u +%Y%m%dT%H%M%SZ)" --minutes 60 --maximum-notional 1000
```

Inspect that audit’s `snapshot.json` terminal readbacks and raw receipts. A blocked trading proposal can still contain valid public account readbacks; it grants no signing permission. An old audit is historical evidence, not a fresh read. Never restart a stopped signer or infer flatness from absence of submitted orders. This release retained the worker’s failed shutdown reconciliation and separately saved two successful authoritative post-stop readbacks in `final_account/audit.json`.
