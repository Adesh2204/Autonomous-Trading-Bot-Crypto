# Team Anchorium — Fixing UNKNOWN and native stop-loss qualification

Your diagnostics confirm that the Python dependencies match, Hyperliquid's public API is reachable, and all ten `par` markets are discoverable.

But they do not authorize a trade. The doctor output still says:

```
execution_mode: PAPER
allow_live_orders: false
signing_authority: NONE
native_protection: BLOCKED_REQUIRES_ACTUAL_QUALIFICATION
```

I also inspected your accessible GitHub repository and found two important things.

1. A native stop-loss qualification tool already exists. `scripts/run_native_qualification.py` supports a read-only `prepare` step and a separately approved `execute` step. We should repair and use this existing workflow rather than build another trading engine.
2. Your historical UNKNOWN cannot be safely cleared just because the account is currently flat. The older recovery implementation requires evidence tied to an exact order and its original transport history. Your newer October 17 UNKNOWN has different identifiers and still lacks conclusive causal evidence.

The distinction is important: software can repair logging, handling of uncertain orders and protective-order logic. It cannot retroactively produce an exchange rejection or a genuine stop-loss fill that never became available in the records.

Our goal is to get one supervised, controlled `par:BTC` round trip working, without changing PAS or the frozen trading strategy.

## Step 1 — Run the actual native-stop preflight

Your `--help` output confirms this is the correct command interface.

In your existing VS Code terminal, run:

```
RECEIPT=$(find docs -type f \
  -path '*/regression_release_v2/test_receipt.json' \
  -print -quit)

if [ -z "$RECEIPT" ]; then
  echo "Source-matched V2 release receipt not found."
else
  OUT="docs/par_native_check_$(date -u +%Y%m%dT%H%M%SZ)"

  .venv/bin/python scripts/run_native_qualification.py prepare \
    --output "$OUT" \
    --test-receipt "$RECEIPT"

  echo "REPORT: $OUT/preparation.json"

  .venv/bin/python -m json.tool "$OUT/preparation.json"
fi
```

This uses `prepare`, not `execute`. It may perform live, unsigned account and market checks, but it will not sign or submit a trade.

The result should tell us which exact condition currently prevents the controlled native-stop test. It may fail on UNKNOWN recovery, 1x settings, market liquidity, the source-matched release, or another genuine gate.

## Step 2 — Repair the actual source code

I found that the GitHub `main` branch does not contain your newer local PAS migration module, while your current doctor report identifies source hash `d37a392...`.

So I have not modified the older GitHub branch, because doing so could create fixes against the wrong version.

Use your local Codex agent, which has access to the current files, with this focused engineering instruction:

# Anchorium — P0 UNKNOWN and Native Stop Qualification Repair

Operate exclusively on the current local release identified by source hash `d37a392acc0c080400d3bd466d10e3be10bb2c1605e7641a7fc1ef733b9ae8c7`.

**Scope:** Practice `par` only. Do not modify PAS, frozen strategy logic, capital allocation, or authorization limits.

## Task A — UNKNOWN forensic repair

Investigate CLOID `0xac0eea156fcec80986dd67c9057b6ded` and nonce `1792217834069`.

Inspect `qualification_intent_recovery.py`, `execution_journal.py`, `sdk_transport.py`, `long_session.py`, all source-matched original signing logs and recovery receipts.

Separate the earlier certified historical order from this newer unresolved order. Do not reuse the earlier certificate.

Determine whether independently verifiable transport, rejection, expiry or terminal evidence exists.

Repair any demonstrated software defects in evidence recording, transport-boundary logging, state reconciliation and ambiguous-order handling.

If admissible evidence conclusively resolves the original order, apply only the documented immutable recovery process.

Otherwise preserve UNKNOWN and produce a precise recovery/isolation evidence request. Never clear the row, change the nonce, invent a rejection or mark it safe merely because current positions are zero.

## Task B — Native Stop Limit repair

Inspect `native_qualification.py`, `native_qualification_runtime.py`, `qualification_protection.py`, `qualification_signing_boundary.py` and `run_native_qualification.py`.

Determine whether the protected stop route matches current registered-par wire semantics.

Correct demonstrable defects involving:

- Native order encoding and grouping.
- Full-position versus fixed sizing.
- Reduce-only semantics.
- Parent/child association.
- Trigger detection.
- Real closing-fill verification.
- Partial entries and sub-$10 residuals.
- Failed stop orders and cleanup.
- Duplicate submissions and uncertain state.
- Signing freshness and stale account evidence.

Preserve the existing exact small-quantity qualification controls.

Add deterministic regression and fault-injection tests.

Native protection remains UNQUALIFIED until actual authorized venue evidence demonstrates acceptance, natural trigger, closing fill and final reconciliation.

## Task C — Supervised par qualification

Build an unsigned preparation report for one controlled `par:BTC` native-protection qualification.

Do not run autonomous trading.

Use the source-matched release receipt, confirmed wallet identity, current venue configuration, actual executable depth and available USDPR balance.

Identify the exact human approval and any competition-window permission still required.

Do not substitute expired approvals or create synthetic proof.

## Task D — Acceptance

Run the full regression suite on the final changed source.

Preserve the prior 2,850-test receipt as historical evidence, not automatic certification of changed code.

Produce:

1. Exact root cause of every reproduced defect.
2. Implemented code changes and test results.
3. Historical UNKNOWN evidence verdict.
4. Native stop software-readiness verdict.
5. Remaining externally required evidence.
6. Exact read-only preflight command.
7. A supervised execution runbook, executable only after all necessary approvals and controls pass.

Do not force GREEN states or bypass hard restrictions. Finish every software-controlled repair that can be independently verified.

## Step 3 — Understand what approval actually means

There are two separate questions:

| Approval                                                            | Who controls it?                                  |
| ------------------------------------------------------------------- | ------------------------------------------------- |
| Permission to conduct competition-related practice on October 18    | Organizers, according to applicable rules         |
| Approval for the bot to use your API wallet for one particular test | You, through the existing human-approval workflow |

Your instruction in this chat expresses your intent to test, but it does not create the exact accepted mandate required by the trading program.

Also, the publicly published practice window ended October 16. This does not prove that the exchange rejects orders on October 18, but it means weekend competition permission hasn't been established.

## Step 4 — When can we actually perform the manual trade?

The verified workflow is:

USDPR practice funds — confirmed

Public exchange connectivity — confirmed

UNKNOWN resolution — awaiting admissible proof

Supervised native-stop preflight — to run

Exact test scope and approvals — pending

After these are satisfied: one supervised BUY → protect → close → reconcile test

A separately authorized qualification can be used to obtain native-stop evidence; it doesn't need to pretend that evidence already exists. But the unresolved order must first be resolved or covered by an independently justified and authorized recovery procedure.

My next recommendation: Run Step 1 and send me the contents of `preparation.json`. That is the fastest way to see the precise gate being hit by your current local code.

I can help repair a specific software failure once we see it. I cannot truthfully certify the two blockers as fixed from a passing dependency check or a flat balance snapshot alone.