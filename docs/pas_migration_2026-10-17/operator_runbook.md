# PAS operator runbook — observation available, actual signing blocked

Use the cloned repository with its literal trailing space. Keep `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false`. No command below grants authority through an environment variable. The preserved par UNKNOWN, USDP funding, 1x configuration, organizer scope and genuine PAS native/residual proof must be resolved before an actual trading launch.

## Tested public observation command

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY .venv/bin/python scripts/anchorium_cli.py start --venue pas --state runtime/terminal-pas
```

The bounded verification used the same command with `--duration 180 --scan-seconds 60` and a dedicated test state directory. Without `--duration`, observation continues until stopped; it has no signer or session-trading authority. It needs the Mac, Python process, power and internet. The operator-launched process does not depend on Codex staying open. Its public HTTP transport cannot call `/exchange` and the CLI skips dotenv secrets in public mode.

In another VS Code terminal:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python scripts/anchorium_cli.py dashboard --state runtime/terminal-pas
```

Use `--once` for a single saved-screen inspection. Every displayed account/book value has an observation time or explicit age. A connected account WebSocket is not necessarily reconciled/healthy. A partial scan, stale book, unavailable candle history or local REST budget deadline must remain visible. No signal in this mode is an execution recommendation.

## Inspect actual venue/account state

```sh
.venv/bin/python scripts/anchorium_cli.py doctor --venue pas
.venv/bin/python scripts/anchorium_cli.py status --state runtime/terminal-pas
.venv/bin/python scripts/anchorium_cli.py report --state runtime/terminal-pas
```

A fresh bounded discovery uses a **new output directory**; existing evidence is never overwritten:

```sh
.venv/bin/python scripts/anchorium_cli.py discover --venue pas --output docs/pas-new-public-audit
```

The actual tested audits are in `docs/pas_migration_2026-10-17/pas_discovery_oct18/`, including raw receipts and two authoritative final readbacks. They are timestamped snapshots, not current continuous supervision. Zero per-DEX margin alone is not a funding verdict; this audit separately found no USDP token balance in Unified mode. The approximately one-million USDPR practice balance does not fund PAS USDP trading.

## Graceful stop — verified against real public runs

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/terminal-pas
.venv/bin/python scripts/anchorium_cli.py status --state runtime/terminal-pas
.venv/bin/python scripts/anchorium_cli.py report --state runtime/terminal-pas
```

`GRACEFUL_STOP_REQUESTED` acknowledges a request. Wait for `STOPPED`, `threads_stopped=true` and the final reconciliation result. Two actual, distinct, stable flat/zero-order snapshots are required to claim flatness. A lock that remains held or a stalled status is not completion. Starting twice in one state directory is rejected. Read-only restart creates a new session, compares venue identity, reconciles public truth and records `restored_authority=false`.

The verification sessions were explicitly stopped or bounded; no monitoring automation or overnight trading process was left running by this work.

## Future exact session procedure — blocked until real evidence exists

1. Obtain the original applicable organizer confirmation and preserve its raw provenance. The new contract requires a reviewed JSON scope record with network/testnet, exact pas/USDP, team wallet, finite organizer interval, nonempty source reference, original-record filename/hash and operator provenance review. This checks scope/integrity; arbitrary text is not independently authenticated organizer permission. The prepared addendum is **not sent**. The earlier authorized par request was already sent; do not duplicate it.
2. Resolve the exact original par CLOID through admissible evidence, or obtain an independently reviewed explicitly approved isolation route. Current `unknownOid` and flatness do not resolve it. Do not rename the intent, broaden the historical certificate, reset nonces or add another signer.
3. Verify actual USDP funding and separately authorized/read-back 1x CROSS configuration. Do not automatically transfer funds, change abstraction mode or use the old par-only configuration approval for PAS.
4. Obtain separately approved genuine PAS native/residual qualification. Required native chain: actual entry → correct stop → natural mark trigger → linked closing SELL fill → actual fee/funding accounting → two authoritative flat/zero-order snapshots. Sub-$10 full-position IOC proof does not qualify native stop sizing, partial reductions or arbitrary symbols. The current ordinary-minimum native route excludes unqualified smallest partials. A narrow new route requires reviewed protocol evidence and its own tested implementation; a ready flag does not enable it.
5. Produce a complete current-source release receipt and fresh account/market discovery. Allow the scored phase to open. The user-stated opening is October 19 12:00 UTC / 17:30 IST, **subject to original organizer confirmation**. No weekend exception or next-day renewal is inferred.
6. Prepare a fresh proposal after all prerequisites pass. The PAS `prepare` path collects unsigned discovery, preserves actual blockers, and creates no executable mandate while required evidence is missing. It never creates an acceptance.

The future CLI interface is:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --venue pas --output docs/pas-fresh-session --minutes 60 --maximum-notional 1000 --release docs/pas_migration_2026-10-17/regression_release_v2/test_receipt.json --native-protection-evidence /absolute/path/to/genuine_pas_protection_evidence.json --organizer-confirmation /absolute/path/to/reviewed_original_organizer_confirmation.json
```

The two absolute evidence paths above are **interface placeholders**, not existing qualification files. No actual PAS mandate exists in this release. If the source changes, the shown release receipt becomes historical and a new full regression is required. A proposal's named risk limits cannot widen after approval.

When a genuine proposal actually reaches `EXACT_MANDATE_AWAITING_HUMAN_APPROVAL`, approve **once** in a local interactive terminal:

```sh
.venv/bin/python scripts/anchorium_cli.py approve --mandate docs/pas-fresh-session/mandate.json --release docs/pas_migration_2026-10-17/regression_release_v2/test_receipt.json --native-protection-evidence /absolute/path/to/genuine_pas_protection_evidence.json
```

Review the complete mandate and type the exact `APPROVE <full mandate ID>` displayed. Approval expires five minutes after proposal creation; the finite session has its own hard expiry. No unattended auto-approval flag exists. Missing/expired/wrong-venue/source/host evidence fails before key access. Historical approvals are never reusable.

The authorized launch interface is:

```sh
EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY .venv/bin/python scripts/anchorium_cli.py start --venue pas --authorized --state runtime/terminal-pas --mandate docs/pas-fresh-session/mandate.json --acceptance docs/pas-fresh-session/acceptance.json --release docs/pas_migration_2026-10-17/regression_release_v2/test_receipt.json --native-protection-evidence /absolute/path/to/genuine_pas_protection_evidence.json
```

Its parser, finite mandate and failure gates are tested; **a genuine PAS signed launch is not tested or qualified**. This command is not runnable trading authority today. Within a subsequently qualified, genuinely approved session, routine BUY/SELL decisions use the frozen strategy and guarded lifecycle without additional terminal approval prompts. Maximum two entries, one global position, finite risk/action/allocation caps and hard expiry remain. SHORT is disabled. Nothing resets at midnight. A restart never restores signing authority.

## Emergency and uncertainty

For a valid signed session, graceful stop first pauses entries and requests only already-authorized owned recovery before expiry. A failed check or UNKNOWN prohibits blind resubmission. Expired authority cannot sign a new exit. A Stop Limit can remain unfilled through a gap; the planned risk budget is not a guaranteed loss cap.

On process/network/power interruption, do not start another signed worker. Inspect the durable journal/nonce record, exact CLOID/OID and authoritative fills/positions/frontend orders with unsigned reads. Preserve uncertainty. If there is exposure, missing proof or expired recovery authority, obtain a new explicit human recovery decision after preparing a concrete exact proposal. Never manually delete SQLite rows, overwrite original proofs, retry an uncertain order, cancel an unknown exchange order, restore an old nonce or enable unqualified protection.

## Accounting interpretation

PAS source records currently show no fills, no funding events, no position/order and net 0 USDP. Its zero funded equity makes return percentage undefined. The preserved October 15 +0.050512 **TEST USDPR** round trip is separate. Synthetic stress results, conditional target net, displayed-book capacity and proposed bankroll are never actual performance or an official competition score.
