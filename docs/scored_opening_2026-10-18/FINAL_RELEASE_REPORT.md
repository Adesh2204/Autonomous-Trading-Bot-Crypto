# Anchorium scored-phase release preparation — October 18, 2026

**Final verdict: NO-GO FOR TRADING.** Software-controlled repairs and the final full release are verified offline. Preparation did not load an actual-wallet key, sign, submit/cancel an order, change leverage/account mode, transfer collateral, create an acceptance or launch trading. PAPER/false and all shared safety restrictions remain.

## 1. PAS readiness and release consistency

Started from the exact requested source `40c70c40d4e4b4e30b2bc03af30fda1d928e76fb75df4fc82e4de65c6976c0f1` and its matching 2,889-test receipt/XML. PAS 2,850-test receipts were stale after the preceding par repair. This task made demonstrated production changes, so a new release was necessary: **2927 passed, 0 failures/errors/skips**, source before/after **`5ff45dbbafa905e4eda58d3cd50152df2fe739dd0b41b9853de74315f4a54a6d`**, XML SHA-256 **`f20c2a92db1613031c078bb19660f592adb1492714a1538cb9b3ff36dc6e976f`**. See [final receipt](regression_release_final/test_receipt.json), [XML](regression_release_final/regression.xml), [stale-receipt audit](stale_receipts.json) and [source changes](source_changes.json).

Strategy-freeze and production-policy/phase-0 checks passed before and after full regression. Frozen signal/state formulas, 300-bar warmup, ATR 0.40%, 15-bps scanner spread, Top-3, capital and mandate limits were not changed. All 53 original database logical contents and integrity checks match the baseline. Original proof files and the preceding native-repair modules remain byte-identical. Existing dirty PAS work was retained. See [preservation receipt](preservation_receipt.json).

The initial partial regression was explicitly interrupted, marked uncertified, after genuine public observation exposed the rate-deadline mismatch. Only `regression_release_final` certifies the final source. Historical receipts were not overwritten.

## 2. Current balance and configuration

Fresh public discovery completed at **2026-10-18T23:20:00.181+05:30**, selecting canonical `pas`, DEX index `271`, collateral token `3307` / USDP and exactly ten registered, non-delisted markets. These identities come from runtime discovery, not a native/par fallback. `exchangeStatus`/`perpDexStatus` are separately reported and do not prove an official opening or team eligibility.

Account mode: **unifiedAccount**. Unified USDP balance: **0**. Exact organizer credit/reset amount: **UNKNOWN / not yet established**. No issuer/whitelist/reset claim is inferred from a balance. USDPR is not USDP. Current PAS leverage remains 10x/20x, so **0 of 10 markets are verified 1x CROSS**. No configuration change was submitted.

The fresh unsigned [configuration plan](final_preopening_proposal/fresh_discovery/account_configuration_plan.json) identifies all ten exact runtime asset IDs, observed prior settings and requested 1x CROSS actions. Plan hash: `3c4406a77e48cdb27a602f6fec4cc8f61c5ee70741d287855859567d22f479a0`. It requires funding, prior-state review, fresh account/agent/identity/sole-host/nonce/clock/rate checks and separate exact configuration-only approval. It grants no permit or transfer authority. The old par approval cannot authorize PAS changes.

## 3. Market-by-market capacity and frozen signals

The table uses fresh public books at each recorded market timestamp. Ten-percent BBO is lot-rounded on both sides; five-bps depth is also capped at ten percent on both sides. Displayed notional is only a book upper bound. It excludes funding, 1x readiness, risk, native/residual protection and authorization. **Actual authorized capacity is zero everywhere.** No notional target is enlarged to meet a minimum.

| Market | Runtime asset | Spread bps | 10% BBO qty | 10% five-bps qty | Book-only USDP notional | Current leverage | Max observed completed snapshot bars | Frozen decision | Authorized notional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pas:BRENT | 2810006 | 7.4857 | 0.46 | 0.46 | 49.1786 | 20x CROSS | 0 | NO_TRADE | 0 |
| pas:BTC | 2810000 | 6.0514 | 0.00061 | 0.00061 | 49.408780 | 20x CROSS | 6 | NO_TRADE | 0 |
| pas:ETH | 2810001 | 6.3456 | 0.0211 | 0.1268 | 49.89306 | 20x CROSS | 60 | NO_TRADE | 0 |
| pas:EWJ | 2810005 | 6.0338 | 0.529 | 0.529 | 49.988384 | 20x CROSS | 0 | NO_TRADE | 0 |
| pas:EWY | 2810004 | 6.7696 | 0.338 | 2.030 | 49.94626 | 20x CROSS | 951 | NO_TRADE | 0 |
| pas:GOLD | 2810007 | 6.2545 | 0.0120 | 0.0120 | 49.89960 | 20x CROSS | 0 | NO_TRADE | 0 |
| pas:HYPE | 2810002 | 7.7670 | 0.64 | 0.64 | 49.4592 | 10x CROSS | 6 | NO_TRADE | 0 |
| pas:SP500 | 2810003 | 0.6568 | 0.030 | 0.044 | 228.3780 | 20x CROSS | 1 | NO_TRADE | 0 |
| pas:USDEUR | 2810008 | 5.3438 | 44.5 | 267.1 | 49.97795 | 20x CROSS | 0 | NO_TRADE | 0 |
| pas:USDJPY | 2810009 | 6.3219 | 0.31 | 0.52 | 49.0513 | 20x CROSS | 6 | NO_TRADE | 0 |

Detailed prices, ages, fee/funding contexts, account limits, signal reasons and raw-history counts are in [market_capacity.json](market_capacity.json) and the original public receipts. Completed-bar counts are maximum deduplicated completed bars actually returned by observed candle snapshots, not invented candles or a warmup waiver. Strategy decisions remain NO_TRADE/UNKNOWN where canonical data is insufficient or stale. No par history was substituted for PAS.

The seven-minute continuous observer completed **6 distinct full ten-market scans**, then stopped with threads stopped `True` and terminal flat `True`. Its actual terminal readbacks remain under `final_pas_observer/sessions/b494e6a69ae44db4a98deecebe5ad80e`. Two authoritative flat/zero-order readbacks are required; cached status alone is not flatness evidence. The observed stream/account/recovery evidence, public request counts, bounded wait durations and errors are preserved in [final_summary.json](final_summary.json). Supporting account scans occur every 300 seconds; cached ages are explicit and never waive fresh signing checks. The final unsigned proposal also collected its own bounded strategy observation.

Reported `userCrossRate` is `0.00045`. The [official guide](https://perpetual-alpha26.github.io/docs/) describes PAS positive base rates doubled by the venue. Existing software conservatively retains the stricter six-times bound `0.00270`; actual USDP fill fees would govern realized P&L. This task changed no fee/risk limit. Funding is read per market, not assumed zero. The read-only process records real errors; a rate-controlled fallback label is not HTTP429 evidence.

## 4. Remaining exchange and organizer evidence

Actual proposal blockers:

- `ACTUAL_PAS_NATIVE_AND_RESIDUAL_PROTECTION_REQUIRED`
- `ACTUAL_PAS_NATIVE_TRIGGER_CLOSING_FILL_REQUIRED`
- `ENTRY_AND_EXIT_CAPACITY_REQUIRED`
- `ORIGINAL_REVIEWED_PAS_ORGANIZER_CONFIRMATION_REQUIRED`
- `PAS_ONE_X_CROSS_REQUIRED`
- `PAS_USDP_COLLATERAL_REQUIRED`
- `SCORED_PHASE_NOT_OPEN`
- `SHARED_ACCOUNT_UNKNOWN_UNRESOLVED`

In addition to genuine USDP funding and original organizer eligibility/credit provenance, a fresh 1x configuration approval, complete canonical warmup, actual PAS native/residual qualification and a new exact session approval remain required. The published schedule already establishes the scored interval; no October 17–18 special practice exception is imposed on the open scored phase. The original-evidence request is [saved separately](EXTERNAL_EVIDENCE_REQUEST.md) and was not sent.

## 5. Historical UNKNOWN disposition

CLOID `0xac0eea156fcec80986dd67c9057b6ded`, nonce `1792217834069`, mandate `59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea`, source `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f` remains **UNKNOWN**. Original row, nonce and earlier exact certificate remain unchanged. The consumed native attempt remains `do_not_restart`; it was not relaunched or reset.

The fresh [original-order audit](original_order_audit/readback.json) reports actual public responses tied to the original CLOID. Current empty accounts/orders or `unknownOid` do not prove original non-transmission. The earlier certificate concerns a different CLOID and is not reused. Reconstructed stale-readiness timing is not an original causal rejection. No admissible new terminal/causal record was found in the retained local records and this task's public readbacks; no new certificate was manufactured.

No safe independently authorized PAS isolation was established. The same team/API/nonce domain retains shared uncertainty even though the DEX and collateral differ. The existing shared-account barrier continues to reject PAS signing. Any isolation exception needs an independently justified, explicitly authorized policy covering account, signer, nonce, late-action and accounting invariants; this preparation grants none.

## 6. PAS native protection and execution repairs

Software readiness is **OFFLINE VERIFIED FOR TESTED CASES**, not genuine venue qualification. The existing noninteractive lifecycle and official offline SDK stack were exercised with synthetic PAS accounts/USDP fills and ephemeral keys, with sockets/HTTP disabled. Real metadata was never changed. Whole-unit synthetic lots enable lifecycle fault injection; they do not establish actual PAS subminimum behavior.

Demonstrated repairs:

- Exact calendar: shared scored boundaries now use October 19 12:00 UTC and November 6 12:00 UTC. The prior shared IST-midnight window and PAS final-day midnight cutoff were outdated. Start-minus-one, start, end-minus-one, end, invalid intervals and the finite session cap are tested.
- PAS startup: account verification previously requested `par:BTC`, causing `STARTUP_RECOVERY_FAILED:VenueMismatch` for PAS. It now uses the verified selected venue prefix. No strategy callback changed.
- Fixed native stop readback: dynamic position-TP/SL records can no longer be accepted as the approved independent fixed-size route. Order grouping stays `na`.
- Conflicting closing fill: a reported fill outside its fixed Stop Limit is now rejected as a protection evidence conflict. Unresolved closing/protection evidence prevents the lifecycle from declaring a completed flat round trip. Two failing PAS reproductions are retained in [pas_reproduced_conflicts.xml](pas_reproduced_conflicts.xml).
- Unsigned configuration proposal: fresh discovery now writes the ten-market source-bound 1x CROSS plan, explicitly separate from credit provenance, approval and execution.
- Public preflight/reporting: scored preparation observes completed-bar signals even without native proof and bounds the scan to 180 seconds. PAS ordinary-minimum admissibility is separately labeled from genuine native qualification.
- Bounded public reads: a 65-second budget wait was truncated by a 45-second read deadline. Public observer/discovery deadlines now permit 75 seconds while rate limits/reserves remain unchanged. A deterministic rolling-window test and fresh observation validate the wait without expanding the budget. Signing freshness limits were not relaxed.

The 19 PAS fault cases cover frozen-signal entry/protection/close/accounting; rejected/uncertain entries; partial entry/exit behavior; rejected/uncertain/wrong-size stops; partial/full native fills; triggered-unfilled gaps; subminimum partial rejection; disconnects; dynamic-stop and fill-price conflicts; expiry, loss, stale book and disconnected entry barriers. Broader focused checks passed 303 tests before the final additional bounded-wait case. Full final-source regression supersedes all supporting counts. Supplemental offline replay also verified an invalid fractional-lot partial entry remaining in recovery and two sequential frozen-signal cycles without per-trade prompts; its synthetic fills and P&L are retained in [additional_pas_simulation.json](additional_pas_simulation.json), with actual P&L null and venue qualification false.

Actual PAS native acceptance, natural trigger, real associated closing fills and native subminimum residual/full-position routes remain **UNQUALIFIED**. Historical par IOC records do not qualify them. No actual PAS fill, fee or funding was generated. Current PAS reported accounting remains separate from the historical October 15 par net `+0.050512 TEST USDPR`. With zero initial USDP equity, a return percentage is undefined; no official score or expected profit is claimed.

## 7–9. Terminal command, approval procedure and conditional launch

[OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) contains the exact read-only terminal/discovery commands, required evidence and configuration review, fresh scored proposal command using this final receipt, interactive exact-hash approval procedure and conditional authorized launch command. Those commands use explicit PAS_NATIVE_ONLY and preserve PAPER/false.

Routine trades inside one valid mandate use SCAN → SIGNAL → VALIDATE → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE without individual prompts. Only the genuine initial exact-mandate approval is interactive. Existing LONG-only scope, one global position, two entry attempts, twelve signed actions, per-cycle close/protection limits, cancellation cap, bankroll/allocation/risk/loss bounds and expiry remain unchanged. Restart cannot restore/renew authority; duplicate-worker, stale-data, disconnect, stop, loss and expiry guards remain. The public duplicate-owner attempt was rejected with `PAPER_OWNER_ALREADY_RUNNING`.

## 10. Final GO / NO-GO

**NO-GO for actual scored trading.** A passing source release is not trading authority. The next independently verifiable conditions are actual USDP funding/organizer provenance, separate exact PAS 1x configuration approval/readbacks, admissible UNKNOWN/invocation recovery or an independently authorized isolation policy, sufficient canonical history, actual PAS native/residual qualification and a fresh finite exact human-approved mandate at/after opening.

The [official schedule](https://perpetual-alpha26.github.io/schedule) is October 19 12:00 UTC through November 6 12:00 UTC (17:30 IST at both ends). Each session remains separately bounded; there is no automatic renewal, midnight counter reset, next-day promotion or SHORT activation.

The standalone observer can run without an open Codex app, but still depends on this Mac, Python process, power, internet and exchange connectivity. Killing its terminal can interrupt supervision. Native Stop Limit gaps can leave exposure; budgets are not guaranteed loss caps and no profit is guaranteed. All actual residual-state claims require current authoritative evidence.
