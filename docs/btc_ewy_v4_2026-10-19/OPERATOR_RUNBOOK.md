# Anchorium V4 operator runbook

Preparation creates no trading authority. Existing public observer: `runtime/pas-btc-ewy-v4`. It never loads wallet secrets. The original October 15/16 heartbeats remain PAUSED. Neither funding nor the October 19 opening starts signing.

The commands below use the actual CLI verified in `cli_help_verification.json`. Evidence and approval variables in the conditional sections must refer to genuine files produced or reviewed by the operator. No current session mandate, configuration acceptance, trading acceptance or PAS native qualification proof exists. Do not create those files by copying JSON examples.

## Terminal environment and current read-only dashboard

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false
export HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
RELEASE="$PWD/docs/btc_ewy_v4_2026-10-19/regression_release_final/test_receipt.json"
.venv/bin/python scripts/anchorium_cli.py dashboard --state runtime/pas-btc-ewy-v4
```

For a single machine-readable snapshot use `status --state runtime/pas-btc-ewy-v4`; for an accounting report use `report --state runtime/pas-btc-ewy-v4`. Check account/fee/book/history timestamps separately. Reported actual PAS fills, fees, funding and equity are distinct from hypothetical target economics and the October 15 PAR net of +0.050512 TEST USDPR. A zero initial equity gives no meaningful return percentage.

The observer is already running. Only if it has stopped and its terminal record has been inspected, this starts unsigned observation:

```sh
.venv/bin/python scripts/anchorium_cli.py start --venue pas \
  --state runtime/pas-btc-ewy-v4 --markets pas:BTC pas:EWY \
  --scan-seconds 60 --readiness-release "$RELEASE"
```

A duplicate owner is rejected. This command has no `--authorized` flag, acceptance, signer or midnight renewal. The standalone process depends on the Mac, Python, power, internet and exchange availability; Codex and its app may close. Process-bound caffeinate helps prevent sleep while its worker exists, but cannot guarantee operation through power/network/process failure. A failed worker is reported, never silently promoted to signing.

## Fresh funding, history and configuration review

Use a new output directory for each public read. The UTC timestamp below creates names only, never authority:

```sh
ANCHORIUM_V4_READ_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
.venv/bin/python scripts/anchorium_cli.py funding \
  --output "docs/btc_ewy_v4_2026-10-19/funding-$ANCHORIUM_V4_READ_STAMP"
.venv/bin/python scripts/anchorium_cli.py history-review \
  --output "docs/btc_ewy_v4_2026-10-19/history-$ANCHORIUM_V4_READ_STAMP"
```

History review is bounded to 180 seconds, queries genuine PAS candles/recent trades/hourly funding, and samples the eight BTC/EWY stream subscriptions. `recentTrades` does not establish a first-ever trade timestamp. Acknowledged subscriptions do not establish current candles or a strategy signal. Missing upstream bars stay missing; the 300-bar warmup and freshness guards remain in force.

Current exact unsigned configuration plan is `discovery_final/account_configuration_plan.json`, paired with `discovery_final/discovery.json`. It records only BTC asset 2810000 and EWY asset 2810004 to 1x CROSS; these IDs were verified dynamically. The current observations expire for approval after five minutes. Never reuse this stale proposal as an acceptance.

After organizer registration evidence, funded Unified account and admissible historical recovery exist, set `ORGANIZER_RECORD` to the real reviewed confirmation JSON with its retained original record. Then refresh:

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-review \
  --output "$FRESH_CONFIGURATION_DIRECTORY" \
  --organizer-confirmation "$ORGANIZER_RECORD"
```

Set `CONFIG_PLAN` and `CONFIG_DISCOVERY` to the actual paired files returned by that review. Choose `CONFIG_APPROVAL` as a new local acceptance output destination; no current file is implied. Human configuration-only acceptance requires a genuine interactive terminal and the exact displayed phrase `APPROVE PAS CONFIGURATION <plan_hash>`:

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-approve \
  --plan "$CONFIG_PLAN" --discovery "$CONFIG_DISCOVERY" \
  --release "$RELEASE" --output "$CONFIG_APPROVAL"
```

Only after valid separate human approval, and within its maximum 15-minute lifetime:

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-apply \
  --plan "$CONFIG_PLAN" --discovery "$CONFIG_DISCOVERY" \
  --release "$RELEASE" --acceptance "$CONFIG_APPROVAL" \
  --output "$NEW_CONFIGURATION_RESULT_DIRECTORY"
```

The real route rechecks source/release/organizer record, team/API/sole-host identity, funded Unified mode, shared UNKNOWN, all account exposure/orders, runtime asset mappings, clock/rates/nonce and every exact approved action. It journals uncertainty before HTTP, consumes actions once and requires authoritative 1x CROSS readbacks on both selected markets. The API acknowledgement alone is insufficient. No orders, cancellations, transfers or account-mode changes are permitted by this approval. Do not retry an uncertain configuration invocation.

## Independent native qualification preparation

These commands create blocked unsigned test proposals; they do not execute them:

```sh
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:BTC \
  --output "$NEW_BTC_QUALIFICATION_REVIEW_DIRECTORY"
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:EWY \
  --output "$NEW_EWY_QUALIFICATION_REVIEW_DIRECTORY"
```

Current saved proposals: `native_btc/qualification_proposal.json` and `native_ewy/qualification_proposal.json`. Their quantity/trigger/floor are observations at their recorded times, not reusable approved limits. Both are blocked. Each route needs independent actual entry fills, accepted/armed/triggered native Stop Limit, linked closing order, actual SELL fills/fees/funding, residual handling and two later authoritative flat/zero-order readbacks. A stop-limit trigger does not guarantee a fill; BTC proof cannot qualify EWY.

There is currently no admissible PAS subminimum native/residual dispatch capability or execution command. The existing PAR qualification command is not a PAS substitute. An ordinary session acceptance cannot bypass this. Obtain authoritative venue semantics/original evidence and a reviewed narrow implementation plus separately bounded human test approval before any qualification write. Preserve the consumed old attempt; do not restart or reset it.

## Conditional finite scored session

The exact published interval is October 19 12:00 UTC through November 6 12:00 UTC; individual mandates remain at most 24 hours with earlier finite expiry. The October 17–18 practice exception is irrelevant to an open PAS scored session. Official calendar opening, team registration/eligibility and human approval are separate facts.

Only after every external prerequisite and the final source-bound release is verified, set `ORGANIZER_RECORD` and `NATIVE_PROOF` to genuine retained evidence. Propose a fresh bounded session:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --venue pas \
  --markets pas:BTC pas:EWY --minutes 60 --maximum-notional 1000 \
  --release "$RELEASE" --organizer-confirmation "$ORGANIZER_RECORD" \
  --native-protection-evidence "$NATIVE_PROOF" --output "$NEW_SESSION_REVIEW_DIRECTORY"
```

The notional is a requested upper bound, not promised executable capacity; fresh two-sided 10% BBO/5-bps depth, 1x margin, lot precision, fees/funding, frozen signal, risk and native/residual protection can reduce it to zero. If only BTC is independently qualified, explicitly request `--markets pas:BTC`; EWY is not inherited. A blocked proposal does not create `mandate.json`.

Set `MANDATE` only to an actual newly produced executable mandate. Review the full hash, source/release/raw native and organizer hashes, team/API/host, PAS/USDP, BTC/EWY subset, LONG-only 1x CROSS, one global position, at most two entries/twelve signed actions, approved bankroll/notional, 0.5% per-trade risk/1% session loss ceiling, closing/recovery terms and expiry. No loss cap or profit is guaranteed.

Human acceptance is once per exact finite mandate. The CLI prints the complete contract and asks for `APPROVE <full_mandate_id>` in a real TTY:

```sh
.venv/bin/python scripts/anchorium_cli.py approve \
  --mandate "$MANDATE" --release "$RELEASE" \
  --native-protection-evidence "$NATIVE_PROOF"
```

Use the actual acceptance path printed by that successful command as `ACCEPTANCE_FILE`. No such acceptance has been created during preparation. Never manufacture it or reuse expired/consumed approval. Only then is this conditional launch meaningful:

```sh
.venv/bin/python scripts/anchorium_cli.py start --venue pas --authorized \
  --state runtime/pas-btc-ewy-authorized \
  --mandate "$MANDATE" --acceptance "$ACCEPTANCE_FILE" \
  --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
```

Routine SCAN → SIGNAL → VALIDATE → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE actions inside that valid capability do not prompt individually. Existing account ownership, action permits, durable intent/nonce consumption, source checks, freshness, capital/loss guards and finite expiry remain mandatory. Restart never restores signing authority. Unknown submissions are reconciled by original identity and never blindly repeated. No automatic renewal or midnight counter reset exists.

## Safe stop and actual PnL verification

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/pas-btc-ewy-v4
.venv/bin/python scripts/anchorium_cli.py report --state runtime/pas-btc-ewy-v4
```

For an actually authorized worker, use its own state directory in these same commands. An operator stop revokes entries; risk cleanup is attempted only within the original valid authorization. After expiry no new signing is permitted. Do not equate stopping a process with closing a position. Inspect `terminal_result.json`, original order/fill identities, actual fees/funding, remaining positions/orders and two authoritative flat readbacks. Missing evidence stays UNKNOWN. Summaries and hypothetical prices never establish realized profit or terminal flatness.
