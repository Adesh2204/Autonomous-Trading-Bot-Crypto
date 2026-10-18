# PAS scored opening: conditional operator runbook

Current trading verdict is **NO-GO**. Preparation grants no signing authority. PAPER/false, the frozen strategy, all original journals/nonce history and the newer par UNKNOWN remain intact. These are exact command interfaces; future approval/launch commands remain conditional on genuine prerequisites, not executable authorization for today.

## Read-only terminal

From the cloned repository (the directory name ends with a space):

```zsh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false
export HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
.venv/bin/python scripts/anchorium_cli.py start --venue pas \
  --state runtime/terminal-pas --scan-seconds 60 --duration 600
```

All ten registered PAS markets are selected by default. This bounded command has no signer or trading authority and stops after ten minutes plus bounded terminal reconciliation. A running owner rejects a duplicate. To inspect another terminal:

```zsh
.venv/bin/python scripts/anchorium_cli.py status --state runtime/terminal-pas
.venv/bin/python scripts/anchorium_cli.py dashboard --state runtime/terminal-pas --once
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/terminal-pas
```

`stop` requests local graceful shutdown. It does not submit a cancellation or close an exchange position without the original exact authority. Retain terminal_result.json and actual terminal readbacks. Do not call an interrupted observer running or flat from its last cached snapshot.

Fresh standalone unsigned discovery, including the configuration proposal:

```zsh
OUT="docs/pas_discovery_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py discover --venue pas --output "$OUT"
```

The correct signal-data setting is `PAS_NATIVE_ONLY`. A conflicting practice setting fails safely rather than selecting another DEX.

## Before configuration or trading

- Verify actual Unified USDP funding and preserve an original organizer eligibility/credit record. Current zero USDP is not a funded scored account; USDPR cannot be substituted. A balance alone does not identify the organizer credit/reset amount.
- Review `final_discovery/account_configuration_plan.json`. It proposes exactly ten 1x CROSS changes from the current public PAS settings. This is an unsigned plan only; it contains no permit or acceptance. The old par 1x approval does not authorize PAS changes. Obtain a separate exact configuration-only approval after fresh funded/Unified/agent/identity/sole-host/shared-nonce/clock/rate/flatness checks. There is no PAS configuration execution command in this release. No collateral transfer or silent mode change is permitted.
- Resolve or independently justify and explicitly authorize recovery/isolation of the historical par UNKNOWN and consumed native attempt. Current PAS/par flatness, a new DEX name, an expired old mandate or a different collateral ticker cannot clear shared account/signer/nonce uncertainty. No reset helper or policy bypass was added.
- Obtain actual PAS native and residual protection qualification for every market included in a future mandate. Correct fixed-size reduce-only Stop Limit acceptance, natural trigger, associated actual closing fills, USDP fees/funding, and two authoritative flat/zero-order readbacks are required. A synthetic PASS, generic protocol documentation or a historical par IOC is not this evidence. Subminimum full-position IOC behavior and native subminimum stop behavior remain separate qualifications.
- Require fresh canonical PAS metadata, active/non-delisted state, healthy account/rates/clock, 1x CROSS, finite two-sided liquidity, 10% best-level and five-bps depth bounds, valid fees/funding, at least 300 completed UTC bars and an unchanged frozen signal. No warmup or strategy threshold was relaxed.

The [official scored window](https://perpetual-alpha26.github.io/schedule) is October 19, 2026 **12:00 UTC** through November 6 **12:00 UTC** (17:30 IST on each date). Sessions must fit inside it. Signing is forbidden before opening and at/after expiry. This is separate from the October 17–18 practice exception: the par practice-permission gate is not applied to the open PAS phase. Reviewed organizer team eligibility/credit provenance remains an independent requirement.

## Fresh unsigned scored proposal after prerequisites pass

The precise final-source release receipt is:
`docs/scored_opening_2026-10-18/regression_release_final/test_receipt.json`.
Prior PAS 2,850-test and par 2,889-test receipts are retained historical evidence and cannot certify changed source. Any subsequent production/test source change needs another full source-matched release.

In a human terminal, select existing ORIGINAL reviewed organizer and ACTUAL PAS-native proof artifacts; no synthetic/example files are provided or accepted as substitutes. Set their absolute paths in `PAS_ORGANIZER_RECORD` and `PAS_NATIVE_PROOF` through the normal artifact review workflow. Then use the existing preparation interface:

```zsh
OUT="docs/pas_session_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py prepare --venue pas \
  --output "$OUT" --minutes 60 --maximum-notional 1000 \
  --release docs/scored_opening_2026-10-18/regression_release_final/test_receipt.json \
  --organizer-confirmation "$PAS_ORGANIZER_RECORD" \
  --native-protection-evidence "$PAS_NATIVE_PROOF"
```

The 1,000 USDP notional is an example within unchanged existing limits, not an approved amount or guaranteed fill size. The default is all ten markets; explicitly narrow `--markets` only to the markets whose complete native/residual evidence and other gates genuinely pass. Preparation collects current discovery and a bounded completed-bar scan even without native proof, then reports blockers. A `proposal.json` marked blocked is diagnostic; it creates no `mandate.json` or authority. Scored proposals cannot open before the official opening, extend beyond the official final cutoff or renew themselves.

## Exact human approval procedure

Only a fresh unblocked `mandate.json` is eligible. Review its full identity, team/API identities and sole signing host, PAS/USDP market scope, LONG-only direction, exact start/expiry, bankroll/notional/exposure/allocation bounds, two-entry limit, twelve-action limit, one global position, fee/spread/depth bounds, protection policy and loss budget. Verify the original organizer, release XML and raw native-protection evidence hashes. A later market move, removed evidence, failed safety check or expired acceptance window can still block launch.

```zsh
.venv/bin/python scripts/anchorium_cli.py approve \
  --mandate "$OUT/mandate.json" \
  --release docs/scored_opening_2026-10-18/regression_release_final/test_receipt.json \
  --native-protection-evidence "$PAS_NATIVE_PROOF"
```

This command requires a real interactive TTY. The human must type `APPROVE ` followed by the exact full mandate hash displayed by that command within its five-minute acceptance window. It creates acceptance.json exclusively after that genuine response. Do not pipe an answer, copy an old acceptance, construct acknowledgment JSON or infer approval from this runbook. This preparation has neither run `approve` nor created an acceptance.

## Conditional authorized launch

Only after every preceding condition, actual current opening time and exact new approval are satisfied:

```zsh
.venv/bin/python scripts/anchorium_cli.py start --venue pas --authorized \
  --state runtime/terminal-pas --scan-seconds 60 \
  --mandate "$OUT/mandate.json" --acceptance "$OUT/acceptance.json" \
  --release docs/scored_opening_2026-10-18/regression_release_final/test_receipt.json \
  --native-protection-evidence "$PAS_NATIVE_PROOF"
```

Keep PAPER/false. The general LIVE builder stays blocked; only an existing exact scoped TESTNET capability can enable its permitted actions after every independent gate passes. No trade was submitted to test this command. Routine SCAN → SIGNAL → VALIDATE → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE work within one valid finite mandate has no per-trade human prompt. There is one exact approval per mandate, no automatic extension or next session.

Existing limits remain LONG only, one global position, at most two entry attempts, twelve signed actions, two close attempts per cycle, two owned cancellations, 1x leverage, 0.5% trade-risk and 1% session-loss bounds, at most 5 bps execution slippage, 10% depth participation, 15 bps spread and the existing 0.3% conservative fee ceiling. CLI session duration is 10–720 minutes and the contract additionally enforces at most 24 hours. Midnight does not reset allocation, attempts, realized P&L or drawdown.

Expiry, loss limit or critical failure stops signing. New entries are stopped near expiry; bounded risk exits require still-valid authority. A triggered but unfilled Stop Limit, unresolved child, partial residual or uncertain order blocks competing/repeated actions until authoritative reconciliation. Never restart an uncertain mandate, enlarge quantity, widen the approved prices or submit a blind retry. A loss-making risk exit may be necessary within its approved limits; profits and gap-loss caps are not guaranteed.

The standalone process does not depend on an open Codex chat, but it does depend on this Mac, Python process, power, internet and healthy exchange connections. Closing/killing its terminal can interrupt it. A server-side stop can survive local interruption but may rest unfilled through a gap. The app cannot guarantee local supervision or risk cleanup during an outage. Inspect actual residual positions/orders after any interruption; require two authoritative flat/zero-order readbacks before claiming a completed flat session.
