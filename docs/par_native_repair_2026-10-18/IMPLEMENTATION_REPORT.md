# Practice par UNKNOWN and native Stop Limit repair — October 18, 2026

**Overall verdict: BLOCKED_EXTERNAL_EVIDENCE.** Demonstrated software repairs are verified offline. The existing unsigned preflight now reports its actual blockers; no trade, key access, actual-wallet signature, acceptance, exchange write or autonomous worker was created. Native protection remains **VENUE_UNQUALIFIED**.

Starting source: `d37a392acc0c080400d3bd466d10e3be10bb2c1605e7641a7fc1ef733b9ae8c7`. Final source: `40c70c40d4e4b4e30b2bc03af30fda1d928e76fb75df4fc82e4de65c6976c0f1`. Branch: `codex/par-native-qualification-2026-10-18`. Eight Python files changed relative to the requested starting local release, including two new files and two narrowly adapted existing tests. The prior dirty PAS work was preserved, not reverted. The comparison is to the supplied local release, not Git HEAD.

## Reproduced causes and repairs

The pre-repair reproduction retained six failing test cases in [reproduced_defects.xml](reproduced_defects.xml). They represent these four defects:

| Defect | Exact cause | Implemented repair and evidence |
| --- | --- | --- |
| Native proof export always failed after the newer validator | The native caller passed a `SimpleNamespace` without `dex`; the shared raw-evidence validator accessed that attribute and raised `AttributeError`. | Supply explicit `dex='par'` at the native caller. The shared PAS/long-session evidence validator is untouched. A complete synthetic raw chain passes; missing trigger/fill/flatness or wrong collateral still fails. Synthetic proof files exist only inside temporary test fixtures. |
| Harmless valuation changes broke three stop stages | Preparation, armed readback and definite-rejection snapshot checks compared full `Position` objects, including mark-dependent unrealized PnL/margin values. | Use the existing exposure identity comparison for symbol, quantity, entry and leverage. All freshness, ownership, order and reconciliation checks remain. The three independently reproduced stages now pass without treating quantity changes as harmless. |
| An associated closing fill below the stop floor was accepted | Fill association checked identity, side and size but did not enforce the approved Stop Limit price. | Reject SELL fills below the limit or BUY fills above it with `QUALIFICATION_STOP_FILL_PRICE_CONFLICT`; remain UNKNOWN and unqualified. No alternate cleanup or certificate follows a conflicting fill. |
| Dynamic position TP/SL could be mistaken for the approved fixed-size route | Stop detail validation did not reject `isPositionTpsl=true`. | Reject that readback for this independent fixed-size `grouping='na'` route. No dynamic/zero-size position order or larger size was introduced. |

The actual initial preflight on the requested `d37a392…` release incorrectly reported `AWAITING_EXACT_HUMAN_QUALIFICATION_APPROVAL` despite the newer durable UNKNOWN, consumed native attempt and missing weekend practice permission. It is preserved under [initial_preflight](initial_preflight/preparation.json), including its stale, unused candidate. The repaired `prepare` now inspects the actual journals read-only, retains the older certificate's exact scope, checks checkpoint/SQLite integrity, exposes unresolved intents/management and consumed invocation controls, and reports every known blocker while still obtaining fresh unsigned account/market observations. It writes no proposal/acknowledgment artifacts when blocked. Invalid configuration/release failures now also produce `preparation.json`, with precise safety codes.

The execution builder checks durable prior-state blockers before opening the actual journal, creating the public client, loading keys or allocating a nonce. Practice permission is separately validated and hash-bound through the native authorization checks. Outside the published practice interval, scope/date/hash validation requires an original operator-reviewed organizer record; arbitrary text is not authenticated by a boolean. No such actual permission record was created here. Existing exact approval, cleanup timing, action limits and consumed-attempt barriers remain.

Future native transport boundary records now include actual working source, originally authorized source, exact mandate/configuration identity, team/API public identity, action hash, nonce, expiry and CLOID. A genuine pre-HTTP failure additionally appends an immutable matching intent audit row. It stores no signature/key/payload and never clears an UNKNOWN. These forward-only records improve future causal evidence; they do not backfill the missing original October 17 telemetry.

## Original UNKNOWN verdict

The unresolved order is **`0xac0eea156fcec80986dd67c9057b6ded`**, nonce **`1792217834069`**, original mandate **`59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea`**, original signing source **`88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f`**. Its exact request is BUY IOC `0.0002 par:BTC` at `81518`. The immutable row is still `UNKNOWN`, OID null, outcome `TRANSMISSION_UNCERTAIN / ExchangeError`.

The older certificate covers **`0x3486c3b8e88add1a77175c9c5965350f`**, a different source/order. Its checksum and original row are preserved; it has not been reused. Original-order logs contain no explicit causal final-guard rejection, original boundary record or recorded transmission claim for the newer order. The reconstructed `5526 ms` readiness age versus the `5000 ms` threshold is an inference, not an original recorded failure. It cannot support a non-transmission certificate on its own.

Two fresh direct public account/order readbacks at 2026-10-18T11:02:56.550+05:30 and 2026-10-18T11:02:57.242+05:30 showed `unknownOid`, no current par position and no current par open orders. These describe current observed account state; they do not resolve the original transmission. The newer row remains in the effective unresolved view. No row, nonce, certificate or global attempt marker was edited. The consumed prior invocation still reports `EMERGENCY_EXIT_REQUIRED`, `do_not_restart=true` and incomplete terminal proof.

Required evidence is precisely listed in [RECOVERY_EVIDENCE_REQUEST.txt](RECOVERY_EVIDENCE_REQUEST.txt): independently verifiable original action/terminal evidence tied to the exact identities, or original explicit pre-HTTP causal evidence with trusted source/transport provenance. Any proposed isolation must independently address shared account/signer/nonce and late-execution risks and be separately authorized. Renaming a DEX or observing flatness is not isolation. The request is a draft and was not sent.

## Final unsigned preflight

Status: **PREFLIGHT_BLOCKED**. Full machine-readable contents: [final_preflight/preparation.json](final_preflight/preparation.json). Actual blockers:

- `PRIOR_QUALIFICATION_UNRESOLVED_REVIEW_REQUIRED`
- `NATIVE_QUALIFICATION_RESTART_REQUIRES_READ_ONLY_REVIEW`
- `ORGANIZER_PRACTICE_QUALIFICATION_PERMISSION_REQUIRED`

| Observation / diagnostic value | Actual value |
| --- | --- |
| Observed (IST) | 2026-10-18T11:11:44.433+05:30 |
| Finished (IST) | 2026-10-18T11:11:44.434+05:30 |
| Venue / account mode | TESTNET par / unifiedAccount |
| Positions / open orders | 0 / 0 |
| USDPR collateral | 1000000.050512 |
| BTC leverage | {'type': 'cross', 'value': 1} |
| Bid / ask | 81583.0 / 81626.0 |
| Best bid / ask BTC depth | 0.0061 / 0.0306 |
| Mark / oracle | 81626.0 / 81706.0 |
| Reported user cross fee | 0.00045 |
| Computed par taker fee bound | 0.00090 |
| Observed hourly funding | -0.0000819128 |
| Candidate funding ceiling | 0.0001638256 |
| Preview BUY / maximum cap | 81666 / 81747 |
| Candidate ask corridor | 81545–81707 |
| Stop trigger / stop-limit and cleanup floor | 80768 / 80365 |
| Selected-price immediate cleanup net, before funding | -0.0459848200 |
| Planned loss at approved floor, before funding | 0.305580160 |
| Maximum funding reserve | 0.00267845026464 |
| Central validation | ALLOWED |
| SQLite integrity | ok |

These are timestamped observations, not current execution authority or a profitable-exit promise. The diagnostic candidate ID is `5e133e4b1129d84fd95a067d3db98cea781695b5b0c3e702ce08f26ecdf8cdf5`. There is no emitted executable `proposal.json`, no genuine new approval and no active authority for it. The maximum-price values and loss estimates are diagnostics for the existing controlled test only. They must be reacquired after prerequisites pass; do not copy the earlier unused candidate or stale prices.

| Supporting evidence | Timestamp ms | Age at context observation ms | Age at report completion ms |
| --- | --- | --- | --- |
| Book timestamp | 1792302103924 | 509 | 510 |
| Mark / funding context | 1792302104250 | 183 | 184 |
| Account snapshot | 1792302103743 | 690 | 691 |
| Readiness including fees | 1792302102312 | 2121 | 2122 |

Independent unavailable fee/funding exchange clocks remain null rather than invented; the table names their local readiness/context observation coverage. Raw request/response receive times remain in [info_receipts.jsonl](final_preflight/info_receipts.jsonl). The worker would still require fresh complete signing checks; a diagnostic read does not waive them. Public rate waits are bounded; a fallback label is not proof of HTTP429. Actual recorded request/error records are retained.

## Native route and readiness limits

The retained wire is an independent fixed-size reduce-only Stop Limit (`grouping='na'`, `isMarket=false`, `tpsl='sl'`), not a position-sized replacement. This is consistent with the [official exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint). Official documentation describes mark-price triggering, fixed versus full-position sizing, and a stop-limit gap that can leave the order resting; see [TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl). These protocol documents do not prove the registered par route has completed a real natural-trigger lifecycle.

The exact `0.0002 BTC` full-entry native experiment and `0.0001 BTC` immediate IOC partial-abort route remain unchanged. Native subminimum residual protection is unqualified. Existing parent/child association, actual fill IDs, partial/remainder accounting, settled-order checks, owned cancellation, source/nonce/clock/rate/account barriers and uncertain-no-retry semantics remain. There is no verified protective stop today.

Offline software readiness is **VERIFIED_ONLY_FOR_TESTED_CASES**. Actual venue capability still requires a separately approved entry, correct stop acceptance, natural trigger, linked actual closing fill within limits, real fees/funding and two authoritative flat/zero-order readbacks. Acceptance alone or IOC cleanup is not native qualification. No autonomous trading promotion follows this repair.

## Validation and preservation

- Full final-source regression: **2889 passed, 0 failures, 0 errors, 0 skipped**. Source stayed identical before/after. [Source-bound receipt](regression_release/test_receipt.json), [XML](regression_release/regression.xml), [log](regression_release/regression.log).
- Six original failures reproduced, then repaired; **39 new deterministic tests pass**. A broader focused run passed **263**; separate signing-boundary tests passed **9**. These supporting counts are not added to or substituted for the full-suite count.
- Production-policy/phase-0 and strategy-freeze checks passed before and after full regression. PAS modules, signal brain/frozen methods/parameters, capital allocation, shared SDK/recovery/journal modules and authorization limits are unchanged relative to the starting release. Two existing synthetic builder tests now explicitly mock calendar permission so their original ordering assertions remain meaningful; no production permission fixture is installed.
- Original 2,850-test receipt and XML remain byte-identical historical evidence. They do not certify changed source. Qualification, nonce and configuration database logical contents are unchanged, SQLite checks report `ok`, recovery checkpoint checksums pass, and original trade proof files remain unchanged. See [preservation_receipt.json](preservation_receipt.json).
- Final XML SHA-256: `d52cf708e8d626105e8c47008a8c00cdfa32fefc018b8f1e198bb69414186163`. Source, report/input evidence and key artifact hashes are recorded in [final_summary.json](final_summary.json) and [release_summary.json](release_summary.json).

The observed historical account events remain the October 15 BUY `0.0002 @ 81512` (order `62755970305`, fill `800659111758533`, fee `0.014672 USDPR`) and SELL `0.0002 @ 81909` (order `62805581662`, fill `260274449763192`, fee `0.014743 USDPR`). Gross `0.0794`, fees `0.029415`, actual funding `+0.000527`, net **`+0.050512 TEST USDPR`**. Those are preserved historical results, not today's native qualification performance or official competition score. No new qualification fill/P&L was produced.

## Required next decision

Use the exact read-only command and the conditional execution interface in [SUPERVISED_RUNBOOK.md](SUPERVISED_RUNBOOK.md). First obtain admissible UNKNOWN evidence or an independently justified authorized recovery policy, review the consumed native invocation, and establish applicable original organizer permission. Only then prepare new current values and request a fresh exact human approval. This repair neither asks for nor creates an approval while hard blockers remain. No restart/reset, broader scope, extended authorization, loss fallback, PAS change or autonomous activation was made.

Mac/process/app/power/internet remain dependencies. A local interruption can prevent observation and bounded cleanup; the stop-limit itself cannot guarantee a fill or cap a gap loss. The original frozen strategy and PAPER/false lockouts remain in force.
