# Supervised practice `par:BTC` qualification runbook

Current status: **BLOCKED_EXTERNAL_EVIDENCE**. This runbook grants no signing authority. No qualification or autonomous worker was launched during this repair. `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` remain required.

The original October 17 intent `0xac0eea156fcec80986dd67c9057b6ded`, nonce `1792217834069`, remains UNKNOWN. The previous native invocation is consumed and marked `do_not_restart`. Do not delete controls, edit an intent, reset a nonce, reuse the earlier order's certificate, change state directories, or rename the DEX to evade these barriers. A new exact approval alone cannot clear them.

## 1. Resolve prerequisites

Obtain admissible original-order evidence and apply only the existing immutable recovery process if that evidence satisfies it. Otherwise an independently justified recovery/isolation policy, operator review and separate authorization are required; this release does not implement or authorize an exception. Review the consumed native invocation and its incomplete terminal record. Do not restart it.

Obtain original, applicable organizer permission for the exact practice `par:BTC` supervised qualification interval outside the published practice window. The [published schedule](https://perpetual-alpha26.github.io/schedule) lists practice October 5–16 and scored trading October 19–November 6. Neither current API connectivity nor a later scored date establishes October 18 practice permission. This is a permission/evidence restriction, not a claim that the exchange rejects weekend orders.

The reviewed permission binding must identify `network=testnet`, `dex=par`, `symbol=par:BTC`, the team wallet, `supervised_native_qualification=true`, covering integer `starts_ms`/`expires_ms`, a nonempty `source_reference`, and `operator_reviewed_provenance=true`. It must reference the preserved original `.eml`, `.txt` or `.json` through `original_record_file` and `original_record_sha256`. The relative record must stay inside the permission file's directory. Scope/hash validation does not authenticate arbitrary text; original provenance requires human review. No actual permission record was manufactured in this task.

## 2. Run the existing unsigned preflight

Run from the cloned repository, whose directory name has a trailing space. This uses the precise final-source receipt rather than searching for an arbitrary older receipt. It performs unsigned `/info` reads only and creates a new output directory.

```zsh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
OUT="docs/par_native_check_$(date -u +%Y%m%dT%H%M%SZ)"
ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false \
  HL_DEX=par SIGNAL_DATA_MODE=PAR_NATIVE_ONLY \
  .venv/bin/python scripts/run_native_qualification.py prepare \
  --output "$OUT" \
  --test-receipt docs/par_native_repair_2026-10-18/regression_release/test_receipt.json
.venv/bin/python -m json.tool "$OUT/preparation.json"
```

After a genuine original permission record is available, add `--organizer-permission /absolute/path/to/reviewed_permission.json`. Do not use a synthetic fixture or an email draft. Any subsequent source change requires a new full source-matched regression receipt.

`PREFLIGHT_BLOCKED` means stop. A `candidate_proposal` in a blocked report is diagnostic and grants no authority. Preparation now emits neither `proposal.json` nor required-acknowledgment files while blockers remain. The saved initial preflight from the old `d37a392…` source is historical evidence of the repaired reporting defect; its candidate is stale and must not be executed.

## 3. Review a new exact proposal and genuine human approval

Only after every prior-state, permission, source, configuration and fresh public-account gate passes may the existing workflow emit `proposal.json` and `required_acknowledgments.json`. Present the full mandate identity, current bid/ask/mark/oracle and depth with observation times, selected price/corridor, exact stop trigger/limit/cleanup floor, computed fees/funding reserve, expected cleanup loss, approval deadline, and all required acknowledgments. Obtain a new explicit human response to those exact values through the existing approval workflow. There is no native `approve` CLI; do not fabricate an acceptance or copy an expired approval. This task has not requested a trade approval because the prerequisites remain blocked.

The unchanged bounds are:

- Team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; API wallet `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`; this Mac as sole signing host.
- One TESTNET `par:BTC` LONG BUY IOC, exactly `0.0002 BTC`, 1x CROSS, at most 25 TEST USDPR notional. No enlargement to meet a minimum.
- The bounded fresh-ask corridor remains within the proposal's stored endpoints. Each movement allowance is the smaller of 10 bps and 100 USDPR/BTC. The rounded selected BUY price is at most 5 bps above the fresh ask and never exceeds the exact approved cap.
- Full entry receives one independent fixed-size reduce-only SELL Stop Limit: `grouping='na'`, `r=true`, `isMarket=false`, `tpsl='sl'`. Trigger is the normalized reference bid times 0.99; limit/cleanup floor is the normalized trigger times 0.995. These existing test geometries were not changed. A dynamic whole-position `positionTpsl` response is not accepted as this fixed-size route.
- Exactly `0.0001 BTC` partial entry uses the existing scoped exact-full-position reduce-only IOC abort. It is not assigned an unverified small native stop. Actual native subminimum protection remains unqualified.
- Computed taker fee at most 0.09%; spread at most 15 bps; both best-book participation at most 10%; current funding must stay within the exact proposal ceiling. Source, metadata, ownership, 1x settings, account/margin, book, fees, funding, reconciliation, clock, nonce and rate guards remain mandatory.
- At most six signed actions, one owned cancellation round and at most two resolved cleanup IOC attempts. Cleanup slippage at most 20 bps and every cleanup SELL limit at or above the approved floor. No retry of an uncertain action.
- Authority lasts at most five minutes after genuine acceptance. Natural-trigger wait is at most 120 seconds with cleanup time reserved; execution preflight requires at least 150 seconds remaining. No restart, extension, duplicate entry or price widening.
- The 10 TEST USDPR test budget is not a guaranteed loss cap. This qualification may realize a loss. Stop Limit gaps, partial fills, rejection, uncertainty or interruption can leave exposure. There is no verified native protective stop today.

## 4. Execute once, only if all prerequisites are actually satisfied

The command below is a future interface template, **not an instruction to execute the current blocked candidate**. Substitute only the new reviewable artifacts from the valid workflow. Do not change PAPER/false to use it: the existing separately scoped TESTNET authorization is the only permitted capability.

```zsh
ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false \
  HL_DEX=par SIGNAL_DATA_MODE=PAR_NATIVE_ONLY \
  .venv/bin/python scripts/run_native_qualification.py execute \
  --output /absolute/path/to/new_unique_execution_output \
  --test-receipt /absolute/path/to/final_source_matched_test_receipt.json \
  --proposal /absolute/path/to/new_proposal.json \
  --approval /absolute/path/to/genuine_exact_human_approval.json \
  --organizer-permission /absolute/path/to/reviewed_permission.json
```

Mandatory checks run again before the actual key loader and nonce allocator and on the signed path. A failed guard stops execution. An uncertain signed/submitted action requires read-only reconciliation tied to its original identity; never rerun the command blindly. The current global consumed-attempt barrier still prevents this template from becoming executable without the required prior-invocation recovery review; this repair introduced no reset facility.

## 5. Audit the outcome

Keep raw order-status/parent-child records, actual BUY and SELL fill IDs, sizes, prices, fee currencies/amounts and funding records. Require correct native acceptance, a natural trigger, exact associated closing fills within the approved limit and two fresh authoritative flat/zero-order readbacks before claiming a qualified closed round trip. Mere acceptance is INCOMPLETE. Cleanup by IOC can close exposure but does not demonstrate native-trigger qualification.

Calculate real net P&L only from those actual fills/fees/funding. Preserve original BUY/SELL proofs and distinguish the historical October 15 net `+0.050512 TEST USDPR` from this experiment. Unknown evidence stays UNKNOWN. Do not claim organizer whitelisting, native residual capability, profitability or unattended readiness from synthetic tests.

The Mac, process, app, power and internet are operational dependencies. Interruption can prevent observation or bounded cleanup; this is not a server-side availability guarantee. No automatic next session or autonomous promotion follows a supervised test.
