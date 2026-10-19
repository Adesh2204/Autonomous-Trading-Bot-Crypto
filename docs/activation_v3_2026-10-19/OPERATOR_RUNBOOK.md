# Anchorium PAS V3 operator runbook

Preparation and public observation do not authorize exchange actions. Current trading is NO-GO. The official scored window is October 19, 2026 12:00 UTC / 17:30 IST through November 6 12:00 UTC / 17:30 IST. Each signing session remains independently bounded.

Run these commands inside this clone; its directory name ends with a space:

```zsh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false
export HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
RELEASE=docs/activation_v3_2026-10-19/regression_release_final/test_receipt.json
```

## 1. Continuous public observation

The V3 preparation launches a standalone public observer at `runtime/pas-v3-public`; check the attached launch/verification receipts for its actual identity and current status. Do not launch a duplicate of the existing owner. It has no signer and no acceptance. Its process-bound caffeinate exits when that worker exits. Codex can close; the Mac, Python, power, network and exchange must remain available.

The exact command to start a public observer, **only when the prior owner is confirmed stopped**, is:

```zsh
.venv/bin/python scripts/anchorium_cli.py start --venue pas \
  --state runtime/pas-v3-public --scan-seconds 60 \
  --readiness-release "$RELEASE"
```

Omitting `--duration` means continuous unsigned observation. There is no automatic trading promotion, renewal or restart. The persistent `history.sqlite` is shared across public sessions in this state directory, with canonical DEX/token/asset/precision binding. It retains up to 6,000 authentic completed minutes per market. It deduplicates and reports gaps; it never manufactures missing bars. Do not delete the cache to conceal conflicts. An unclean stop requires fresh account reconciliation, not an inferred flat position. Retained snapshot counts include overlapping requests; they are not unique bar counts.

## 2. Fresh funding verification

This command is unsigned and creates a new evidence directory:

```zsh
FUNDING_OUT="docs/pas_funding_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py funding --output "$FUNDING_OUT"
```

Read `funding_evidence.json` with its raw `info_receipts.jsonl`. ZERO, POSITIVE_VERIFIED, STALE and UNAVAILABLE differ. Runtime USDP identity and the team account are required. A positive balance does not identify organizer origin or amount. Unified spot total is counted once; unrealized PnL/per-DEX equity is not added to it. Standard-mode evidence is separately labeled and is not Unified readiness. No transfer or mode change is provided.

## 3. Fresh PAS configuration review

Run after genuine funding and historical-state review so the plan remains fresh enough to approve:

```zsh
CONFIG_OUT="docs/pas_configuration_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py configuration-review --output "$CONFIG_OUT"
```

Review team account `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`, API signer `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` and this Mac as sole signing host. Review all ten canonical asset IDs, current settings and exact `updateLeverage` actions in `account_configuration_plan.json`. The old par approval cannot authorize them. The official guide says account setup follows funding; no supported pre-funding permission was established, so the funding guard remains. The plan is not a configuration permit. Original organizer credit provenance and team eligibility remain separate external evidence.

## 4. Exact configuration-only approval and conditional application

**Currently blocked.** After fresh funded/Unified/flat account evidence, approved agent verification, admissible shared UNKNOWN resolution and source-matched release verification:

```zsh
.venv/bin/python scripts/anchorium_cli.py configuration-approve \
  --plan "$CONFIG_OUT/account_configuration_plan.json" \
  --discovery "$CONFIG_OUT/discovery.json" --release "$RELEASE" \
  --output "$CONFIG_OUT/configuration_acceptance.json"
```

The human reviews both wallet identities, sole signing Mac, all ten actions and the full plan hash, then types the displayed exact `APPROVE PAS CONFIGURATION <full plan hash>` phrase in a real TTY. The plan must still be within five minutes at acceptance. Acceptance lasts at most fifteen minutes and grants configuration-only scope. Do not pipe an answer or construct/copy acknowledgment JSON. This preparation did not invoke that approval or create an actual acceptance.

Only after that separate valid approval:

```zsh
.venv/bin/python scripts/anchorium_cli.py configuration-apply \
  --plan "$CONFIG_OUT/account_configuration_plan.json" \
  --discovery "$CONFIG_OUT/discovery.json" --release "$RELEASE" \
  --acceptance "$CONFIG_OUT/configuration_acceptance.json" \
  --output "$CONFIG_OUT/authorized_application"
```

The route repeats public funding/identity/agent/flatness/shared-order/source/mapping/clock/rate checks before accessing the signer. It uses the existing shared nonce database and global account/signer lease, exact hash-bound 1x CROSS actions, signed expiry, intent-before-dispatch management records, and actual acknowledgments/readbacks. The plan invocation and transmitted actions are consumed. Ambiguity stays UNKNOWN and cannot be blindly retried or restarted. No BUY/SELL, transfer, cancellation, wallet-mode change or native activation is included. A changed source, stale/altered evidence, rejected action or wrong readback requires review. All ten values must be read back as 1x CROSS before a successful configuration claim.

## 5. Dedicated native qualification preparation

```zsh
NATIVE_OUT="docs/pas_native_review_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py native-prepare \
  --market pas:BTC --output "$NATIVE_OUT"
```

This is a dedicated **unsigned test proposal**, not an ordinary autonomous mandate and not an execution command. It does not require ordinary native qualification just to prepare the experiment. It describes one LONG entry, a fixed-size reduce-only mark-triggered Stop Limit (`grouping=na`, `isMarket=false`), exact remaining-position cleanup, a six-action ceiling, two resolved cleanup IOC attempts, one owned cancellation round, five-minute authority ceiling and 120-second natural-trigger ceiling with cleanup reserve. No authority is created by those proposed limits.

**The current PAS partial/residual cleanup policy is unresolved.** A one-lot fill can fall below the documented ordinary $10 minimum. The old par exception does not apply. This release deliberately provides no executable PAS subminimum qualification exception; it cannot submit the experiment while that cleanup scope, shared UNKNOWN/consumed-attempt review, funding/configuration, applicable permission and exact test approval are missing. A future independent scope review must establish an admissible cleanup policy and authorize any required narrow integration. Do not use the par-only native execution script against PAS, relaunch the consumed attempt, or supply an ordinary trading approval as a substitute.

Stop submitted, accepted, armed, triggered, child identified, closing fill and two flat readbacks are separate milestones. Telemetry and synthetic tests never qualify the actual venue. Genuine qualification requires original raw order/fill/fee/funding records, parent/child linkage and two authoritative flat/zero-order readbacks. Stop Limit gaps can leave exposure; the loss budget is not a guaranteed cap.

## 6. Fresh scored proposal and exact human trading acceptance

**Currently blocked.** At/after the official opening, first verify organizer USDP provenance, account/signer identity, actual 1x CROSS, admissible shared UNKNOWN disposition, genuine PAS native/residual qualification, authentic warmup, fresh liquidity and the final release. Set `PAS_ORGANIZER_RECORD` and `PAS_NATIVE_PROOF` to actual retained reviewed artifacts; no example evidence files are supplied.

```zsh
SESSION_OUT="docs/pas_session_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py prepare --venue pas \
  --output "$SESSION_OUT" --minutes 60 --maximum-notional 1000 \
  --release "$RELEASE" --organizer-confirmation "$PAS_ORGANIZER_RECORD" \
  --native-protection-evidence "$PAS_NATIVE_PROOF"
```

The 1,000 USDP limit is an example within existing limits, not an approved allocation. Narrow `--markets` only to genuinely qualified markets if appropriate. A blocked proposal creates no executable mandate. Review the full mandate identity, team/API/sole host, PAS/USDP, LONG-only market set, start/expiry, bankroll/allocation/risk/loss limits, two entries, twelve signed actions, one global position, native evidence identity, recovery rights and fees/spread/depth constraints. Then, only if all requirements pass:

```zsh
.venv/bin/python scripts/anchorium_cli.py approve \
  --mandate "$SESSION_OUT/mandate.json" --release "$RELEASE" \
  --native-protection-evidence "$PAS_NATIVE_PROOF"
```

The human types `APPROVE <full mandate hash>` in the actual TTY within the displayed five-minute window. Never auto-answer, reuse an acceptance, infer consent from this runbook or fabricate a mandate.

## 7. Conditional authorized session launch

**Not authorized by preparation.** After every prerequisite and genuine exact acceptance:

```zsh
.venv/bin/python scripts/anchorium_cli.py start --venue pas --authorized \
  --state runtime/pas-v3-trading --scan-seconds 60 \
  --mandate "$SESSION_OUT/mandate.json" --acceptance "$SESSION_OUT/acceptance.json" \
  --release "$RELEASE" --native-protection-evidence "$PAS_NATIVE_PROOF"
```

PAPER/false stays enforced. The separate TESTNET capability is finite and source-bound. Routine SCAN → SIGNAL → VALIDATE → SIZE → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE decisions inside that valid mandate need no individual prompts. Existing frozen strategy and risk limits remain: LONG only, one global position, 1x CROSS, two entries, twelve actions, 0.5% trade risk, 1% session loss, 5-bps execution limits, 10% participation, 15-bps spread and 0.3% conservative fee ceiling. Counters do not reset at midnight. Expiry, loss or critical failure stops signing; no automatic renewal or restart.

The public observer can remain separate, but exchange rate budgets and machine resources must remain healthy. Do not create a second signer. A new mandate always requires fresh evidence and genuine approval; the renewal procedure is the same prepare → review → approve → launch sequence after the prior worker is terminal and reconciled.

## 8. Dashboard and actual status

```zsh
.venv/bin/python scripts/anchorium_cli.py status --state runtime/pas-v3-public
.venv/bin/python scripts/anchorium_cli.py dashboard --state runtime/pas-v3-public
```

Use `--once` for one dashboard frame. For an authorized worker, select `runtime/pas-v3-trading` instead. The dashboard shows account/funding/fee ages, source, logical readiness gates, authentic bar counts/gaps, signals, capacity, exposure, actual fills and account PnL. The documented PAS 2x base-fee estimate is separate from the unchanged 6x stress/signing guard and actual fees. Target-scenario PnL is not expected or realized profit. No positive empirical edge is inferred from price movement. A zero initial equity denominator leaves returns null. The historical October 15 `+0.050512 TEST USDPR` is not PAS PnL or an official score.

## 9. Graceful shutdown

```zsh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/pas-v3-public
```

For authorized trading use its state directory. Public stop never cancels or closes an exchange order. An authorized worker can attempt only its still-valid scoped shutdown risk exit; expiry does not renew that authority. Wait for terminal_result.json, stopped threads and actual terminal readbacks. Never infer flatness from the stop request, stale status or absent local process. Closing a terminal/killing Python can interrupt supervision.

## 10. Emergency recovery review

After any stopped/stalled/uncertain worker, do not restart or retry the order. Preserve original CLOID, nonce, intent, boundary and result records. Obtain bounded unsigned reconciliation:

```zsh
RECOVERY_OUT="docs/pas_recovery_$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python scripts/anchorium_cli.py discover --venue pas --output "$RECOVERY_OUT"
```

Inspect actual fills, position, frontend orders and both terminal readbacks. This is account review, not a new signed emergency close. A new signed recovery requires independently reviewed exact authority. Current flatness/expiry/unknownOid cannot prove historical nontransmission or establish PAS isolation. Missing evidence stays UNKNOWN.

## 11. PnL reconciliation

Use the fresh discovery in step 10 for authoritative `account.fills`, `funding_events`, `reported_account_equity` and `realized` fields. Preserve its raw receipts. For the worker's session basis and actual terminal report:

```zsh
.venv/bin/python scripts/anchorium_cli.py report --state runtime/pas-v3-public
```

Select the trading worker state for its actual session. This report command renders retained evidence; it does not refresh the exchange. Real net is actual reported closing PnL minus actual fill fees plus signed funding cashflows. Partial/unknown history cannot be reported as a completed trade. Equity change is explicitly not cash-flow-adjusted or an official competition score. No next session is approved by a PnL report.
