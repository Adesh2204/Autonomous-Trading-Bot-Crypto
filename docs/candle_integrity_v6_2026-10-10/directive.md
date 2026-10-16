# TEAM ANCHORIUM — MASTER ENGINEERING DIRECTIVE V6.0
## Hyperliquid Candle Integrity, Numerical Error Elimination & Practice-Readiness Certification

**Target repository:** Autonomous Trading Bot - Crypto / `algo-trading-bot`

**Competition:** Perpetual Alpha — ICAIF 2026

**Venue:** Hyperliquid Testnet

**Required DEX:** `par`

**Engineering priority:** CRITICAL

**Execution mode:** Strictly PAPER

**Task type:** Evidence-first root-cause investigation → controlled defect repair → regression testing → bounded PAPER certification

---

# 0. MASTER MISSION

Act as a senior quantitative trading infrastructure engineer, market-data systems architect, exchange API specialist, and production reliability auditor.

Your objective is to eliminate every **verified, repairable engineering defect** causing Team Anchorium's current market-data unavailability and numeric calculation failures.

The latest three-hour certification finished with:

**`FEED_NOT_READY`**

Our target is to establish a trustworthy pipeline:

Hyperliquid `par:` data  
↓  
WebSocket + REST ingestion  
↓  
Valid candle reconstruction from genuine exchange records  
↓  
Timestamp and history verification  
↓  
Per-market health assessment  
↓  
Quarantine or restore market  
↓  
Existing scanner  
↓  
Frozen VWAP strategy  
↓  
Existing risk and execution permissions

**Success means the bot processes all genuinely available data correctly. It does not mean manufacturing data or lowering trading standards until orders appear.**

Do not redesign the trading strategy.

Do not perform funded trading.

Do not mark the system ready without evidence.

---

# 1. ABSOLUTE SAFETY AND PROJECT INVARIANTS

## 1.1 Protected strategy

Do not modify `signal_brain.py`.

Preserve:

- VWAP calculation and current UTC anchoring
- EMA9 / EMA21
- ATR calculation
- ATR minimum of 0.40%
- Maximum spread of 15 basis points
- 300 completed-candle requirement
- Top-3 scanner selection
- LONG and SHORT signals
- Pullback, breakout and breakdown logic
- Daily directional bias
- Cooldown and anti-spam
- Existing strategy stops and targets
- Direction-flip logic
- Existing position-management mathematics
- One-global-position restriction
- Fill-as-truth accounting

Changing these parameters to create trades is expressly prohibited.

## 1.2 Trading lock

Maintain:

`EXECUTION_MODE=PAPER`

`ALLOW_LIVE_ORDERS=false`

`PROTECTION_ENABLED=false`

No signed orders, market orders, leverage changes, account-mode changes, wallet approvals, transfers or liquidation tests are authorized.

Do not load or display private keys.

Do not print environment secrets.

No trading activation is permitted by this prompt.

## 1.3 Data authenticity

Never:

- Invent missing candles
- Insert synthetic flat candles
- Backfill using interpolated OHLCV
- Substitute research CSVs for current exchange data
- Substitute ordinary Hyperliquid BTC/ETH markets for `par:BTC` / `par:ETH`
- Silently change timestamps
- Hide genuine data defects
- Suppress numeric exceptions without recording them
- Bypass existing scanner or risk gates

**Missing legitimate exchange data must remain missing.**

## 1.4 Repository isolation

Before making changes:

1. Confirm the active repository identity.
2. Inspect the current Git branch and working tree.
3. Identify the frozen-strategy baseline.
4. Record the current source hashes.
5. Verify whether a PAPER process is already running.
6. Preserve all previous run artifacts.
7. Do not modify the original NSE bot repository.
8. Never overwrite previous evidence directories.

If another PAPER process is active, do not launch a competing process or reuse its state directory.

Do not create recurring Codex tasks or scheduled monitors. This must be a bounded engineering job.

---

# 2. OFFICIAL BASELINE — PRESERVE THESE FACTS

The most recent three-hour PAPER run produced:

| Metric | Result |
|---|---:|
| Market observations | 360 |
| Valid market-data observations | 29 |
| Unusable observations | 331 |
| Healthy-data rate | 8.06% |
| Spread passes | 29 |
| ATR passes | 0 |
| Qualified markets | 0 |
| Strategy evaluations | 0 |
| Simulated fills | 0 |
| Actual exchange orders | 0 |
| Markets usable at shutdown | 0 / 10 |
| Tests passed | 1,339 |
| Failed tests | 0 |

Transport evidence:

- 16 WebSocket `1000 / Expired` closures
- 16 successful corresponding reconnects
- 40/40 subscriptions restored
- Zero duplicate subscriptions
- Source integrity verified
- State/checkpoint integrity verified
- Strategy freeze passed

**Interpretation:** WebSocket recovery appears operational. Market-data completeness and numeric integrity remain unresolved.

Do not reopen proven transport work unless the new audit demonstrates a concrete defect.

---

# 3. PHASE ONE — INVESTIGATE EVERY CANDLE GAP

## 3.1 Inspect the actual repository

Locate the real modules responsible for:

- Public Hyperliquid WebSocket ingestion
- Public Hyperliquid REST requests
- Candle snapshots
- Candle normalization
- OHLCV validation
- Candle merging and deduplication
- Time alignment
- Per-market candle caches
- REST historical recovery
- Scanner input preparation
- Complete-strategy-history preparation
- Market quarantine and automatic restoration
- Read-budget enforcement
- Reconciliation
- Source and timestamp provenance

Known candidate files include:

`exchange/hyperliquid_market_data.py`

`exchange/market_health.py`

`market_regime_scanner.py`

`market_stream.py`

`candle_builder.py`

`candle_normalizer.py`

`exchange/rate_limits.py`

Use actual discovered paths. Do not assume a file exists merely because it is named here.

Produce a private investigation map:

**File → Function → Input → Output → Potential failure → Evidence.**

## 3.2 Analyze the final missing-candle evidence

The previous run ended with:

| Market | Completed bars | Recorded issue |
|---|---:|---|
| `par:BRENT` | 288 | Incomplete/stale |
| `par:BTC` | 291 | Incomplete/stale |
| `par:ETH` | 249 | Incomplete/stale |
| `par:EWJ` | 0 | Missing history |
| `par:EWY` | 277 | Incomplete/stale |
| `par:GOLD` | 297 | Incomplete/stale |
| `par:HYPE` | 248 | Full-history gap/duplicate |
| `par:SP500` | 291 | Incomplete/stale |
| `par:USDEUR` | 272 | Incomplete/stale |
| `par:USDJPY` | 173 | Incomplete/stale |

All markets require valid history according to the unchanged existing strategy contract.

**Do not assume that every short history is a coding bug.**

Determine whether each problem came from:

A. Exchange genuinely supplied no candle.

B. REST request did not cover the necessary time window.

C. Hyperliquid returned fewer candles than requested.

D. Pagination/window boundaries lost records.

E. Adapter discarded legitimate candles.

F. REST/WebSocket merging overwrote valid candles.

G. Duplicate handling rejected valid records incorrectly.

H. In-progress candle was confused with a completed candle.

I. UTC timestamp or interval-boundary miscalculation.

J. Candle cache capacity/eviction behavior.

K. Stale data after reconnect.

L. Sparse market activity resulting in missing trade-generated candles.

M. Market identity or metadata mapping defect.

N. Shared rate-limit pressure prevented completion of recovery.

Other causes must be documented if discovered.

---

# 4. PHASE TWO — RAW EXCHANGE VS INTERNAL DATA AUDIT

This is the most important phase.

For every affected market, compare four stages:

**Stage A — Raw Hyperliquid REST response**

**Stage B — Raw Hyperliquid WebSocket events**

**Stage C — Normalized and merged candle cache**

**Stage D — Final scanner/strategy input**

At every stage, measure:

- Number of records
- Earliest and latest timestamps
- Expected candle interval
- Missing interval count
- Duplicate count
- Conflicting duplicates
- Stale candle age
- Invalid OHLCV count
- Discard/replacement reasons
- Available contiguous completed-bar count

Ensure all stage comparisons refer to the same requested market and time interval.

Never compare records from different time windows and call the difference a bug.

## 4.1 Historical evidence first

Start with saved raw responses, captured traces, run tapes, receipts and checkpoint artifacts.

If original raw payloads were not captured, state this limitation.

Only then make limited, read-only public `par:` API queries, respecting the existing request budget and without interrupting any running process.

Do not claim that a fresh current response proves what the exchange returned during the previous run.

## 4.2 Required candle trace

For a missing BTC candle, the explanation should resemble:

Expected exchange candle timestamp: X

Raw REST returned timestamp X: YES/NO

Raw WS returned timestamp X: YES/NO/UNKNOWN

Normalizer accepted timestamp X: YES/NO

Cache retained timestamp X: YES/NO

Scanner received timestamp X: YES/NO

Exact rejection reason: ...

Responsible file and function: ...

Verified cause: ...

Fix possible: YES/NO

Apply the same methodology to every affected market.

## 4.3 Mandatory classification

Every confirmed gap must be classified:

`EXCHANGE_DATA_UNAVAILABLE`

`REST_WINDOW_INCOMPLETE`

`REST_PAGINATION_DEFECT`

`CANDLE_NORMALIZATION_DEFECT`

`CANDLE_MERGE_DEFECT`

`CACHE_EVICTION_DEFECT`

`TIMESTAMP_ALIGNMENT_DEFECT`

`RECOVERY_SCHEDULING_DEFECT`

`RATE_BUDGET_BLOCKED`

`OTHER_VERIFIED_DEFECT`

`CAUSE_UNDETERMINED`

Do not mislabel an unknown cause as a verified exchange limitation.

---

# 5. PHASE THREE — FIX VERIFIED CANDLE-PROCESSING DEFECTS

Only implement fixes supported by Phase Two evidence.

## 5.1 REST retrieval integrity

Verify that REST queries request the correct:

- Network
- HIP-3 `par` market
- One-minute interval
- Start timestamp
- End timestamp
- Expected completed-bar window

If the venue imposes response limits, retrieve the necessary history through bounded, rate-aware requests.

If a strategy requires a larger input history than the streaming cache, preserve that distinction.

Do not silently reduce the strategy's input length.

## 5.2 Candle merging

Any new candle-merging logic must:

1. Accept genuine exchange records only.
2. Preserve exchange timestamps.
3. Sort chronologically.
4. Deduplicate identical rows deterministically.
5. Detect conflicting duplicate data.
6. Reject future and malformed records.
7. Avoid overwriting newer valid facts with older responses.
8. Preserve enough history for the existing strategy.
9. Leave unresolved holes explicitly recorded.
10. Revalidate complete history before restoring symbol eligibility.

Do not fill holes with invented OHLCV.

## 5.3 Separate current-bar and completed-bar handling

A candle still being formed must not count as completed.

Validate completion against:

- Exchange interval boundaries
- Current trusted time
- Existing strategy freshness policy
- Exchange event semantics

Avoid off-by-one-minute boundary errors.

## 5.4 Safe recovery scheduling

If the server returns incomplete but otherwise valid candles:

- Record missing ranges.
- Schedule bounded retry when permitted.
- Avoid duplicating concurrent requests.
- Use progressive retry/backoff.
- Preserve request-budget safety.
- Restore the symbol only when the entire required history passes validation.

A successful HTTP response with incomplete content is not successful data recovery.

---

# 6. PHASE FOUR — RESOLVE BOTH `INVALID_DECIMAL` FAILURES

Two unexplained numeric rejections were recorded:

**Market 1:** `par:BRENT`

**Decision timestamp:** `1791482698439`

**Market 2:** `par:EWY`

**Decision timestamp:** `1791489298981`

These must be investigated separately from the missing-candle issue.

## 6.1 Trace the exact failure

Reconstruct the saved decision path:

Raw market input  
↓  
Normalization  
↓  
Candle/history preparation  
↓  
Scanner features  
↓  
Frozen-brain evaluation boundary  
↓  
Numerical operation  
↓  
`INVALID_DECIMAL`

Identify:

- Exact exception type
- Exact file and line
- Exact function
- Actual operand types
- Exact invalid/non-finite field, if available
- Whether input was missing or malformed
- Whether division by zero occurred
- Whether NaN or Infinity was introduced
- Whether string/float/Decimal conversion caused the problem
- Whether the data was valid but the calculation failed

The prior report recorded fresh candles and a frozen-brain evaluation near these errors.

**Do not assume the exchange supplied invalid prices.**

## 6.2 Correct only the actual cause

Permitted examples:

- Validate invalid values before arithmetic
- Reject non-finite numeric inputs
- Enforce expected numeric conversions
- Prevent invalid arithmetic at integration boundaries
- Repair erroneous adapter field mappings
- Preserve precise decimal types
- Return a specific rejection reason rather than a generic exception

Do not replace broken data with zero.

Do not catch every exception and pretend the signal failed normally.

Do not alter the frozen strategy's mathematics.

If a defect exists inside a protected strategy component, stop and report the exact issue and proposed change for separate approval.

## 6.3 Add permanent regression tests

Create deterministic reproductions for BRENT and EWY using captured evidence or clearly labeled synthetic fixtures.

Tests must prove that:

- Valid data remains accepted.
- Invalid input cannot generate an order.
- Numeric exceptions are correctly classified.
- The process does not crash unnecessarily.
- No fabricated values enter calculations.
- Strategy outputs remain unchanged on valid equivalent inputs.

The previous two failures must be traceable to a clear and defensible resolution or explicitly remain unresolved.

---

# 7. PHASE FIVE — MARKET HEALTH AND QUARANTINE INTEGRITY

Keep per-market isolation already implemented.

Required behavior:

`par:BTC` has invalid history → BTC blocked.

`par:ETH` has fully valid history → ETH may continue evaluation.

One failed symbol must not automatically disable all others.

However:

**A market may be marked HEALTHY only when all mandatory input requirements actually pass.**

Preserve:

- Transport health
- Subscription health
- Reconciliation health
- Per-market health
- Scanner qualification
- Strategy signal availability
- Execution permission

as separate concepts.

`TRANSPORT_READY=true` is not sufficient to establish `FEED_READY=true`.

`FEED_READY=true` is not sufficient to establish `TRADE_READY=true`.

A symbol with a genuinely missing historical bar must remain ineligible if the frozen strategy requires a continuous history.

No automatic promotion based solely on a fresh last candle.

---

# 8. PHASE SIX — VALIDATE MARKET CONDITIONS SEPARATELY

All 29 usable observations in the previous run failed the unchanged ATR floor.

That is **not automatically a coding bug**.

Once genuine data-processing errors are addressed:

Inspect actual ATR distributions for each `par:` market.

Record:

- Market
- Valid observation count
- ATR value
- ATR percentage
- Spread bps
- Candle interval
- Whether the fixed scanner threshold passed

Verify that ATR units and price normalization are correct.

Do not modify the ATR threshold.

Do not change the 15 bps spread ceiling.

Do not lower the 300-bar history requirement.

If the data is valid but the market remains too quiet, classify it:

`VALID_DATA_MARKET_CONDITIONS_UNQUALIFIED`

This means infrastructure is working while the market does not satisfy the current strategy.

Any future ATR or VWAP optimization must be a separate, offline, out-of-sample research task.

---

# 9. PHASE SEVEN — RESOURCE AND RATE-BUDGET SAFETY

Before running recovery-heavy tests, inspect:

- REST request weights
- Per-market repair frequency
- Concurrent requests
- Reconnect-triggered recovery
- Duplicate REST requests
- Cache reuse
- Pagination/request caps
- Retry/backoff behavior
- Safety request reserve

The existing rate-limit manager must remain authoritative.

Safety/account reconciliation retains higher priority than optional analytics or bulk market-data recovery.

Do not solve missing candles by issuing uncontrolled REST requests.

If the exchange cannot return a required history within safe budgets, record the limitation and block affected markets.

---

# 10. PHASE EIGHT — REGRESSION TESTING

After a verified fix, run:

1. Relevant new unit tests.
2. Saved raw-response replay tests.
3. Candle normalization tests.
4. Boundary and pagination tests.
5. Timestamp alignment tests.
6. Merge/deduplication tests.
7. Recovery scheduling tests.
8. Market quarantine tests.
9. Numerical regression tests for BRENT and EWY.
10. Rate-limit and retry tests.
11. Reconnect/subscription tests.
12. PAPER accounting and checkpoint tests.
13. Strategy-freeze verification.
14. Phase-0 safety verification.
15. Complete repository test suite.

Previous baseline:

**1,339 passing tests, zero failures.**

New tests should increase meaningful coverage, not merely inflate the test count.

Every test must be labeled:

`OFFLINE_FIXTURE`

`RECORDED_EXCHANGE_REPLAY`

`LIVE_PUBLIC_READ_ONLY`

or

`ACTUAL_EXCHANGE_EXECUTION`

There must be no actual exchange execution in this task.

---

# 11. PHASE NINE — BOUNDED PAPER VALIDATION

Do not immediately launch another three-hour run.

## Stage A — Short validation

After passing all offline tests:

1. Confirm no conflicting PAPER process is running.
2. Create a fresh state directory.
3. Keep live orders disabled.
4. Run one bounded 15–30-minute PAPER session.
5. Capture market-data funnel and health results.
6. Verify checkpoint and state integrity.
7. Verify no unresolved numeric exceptions.
8. Verify recovery does not cause REST request storms.

If this stage fails because of a confirmed software defect, fix that defect before continuing.

If markets genuinely lack data, preserve the failure and classify it honestly.

## Stage B — Three-hour certification

Run this stage only after Stage A supports it.

Use:

- New state directory
- Explicit source hash
- Unchanged strategy version
- Same relevant scanner policy
- One running PAPER process
- No recurring AI monitor
- No actual orders

Compare with the earlier baseline:

| Metric | Before | After |
|---|---:|---:|
| Market observations | 360 | Measure |
| Healthy observations | 29 | Measure |
| Healthy-data percentage | 8.06% | Measure |
| ATR passes | 0 | Measure |
| Scanner-qualified | 0 | Measure |
| Unexplained numeric errors | 2 | Measure |
| Usable markets at shutdown | 0 | Measure |
| Recovery success | 16/16 | Measure |
| Actual orders | 0 | Must remain 0 |

Different market conditions may affect the result.

Do not claim that a higher healthy percentage was caused by the code without supporting evidence.

---

# 12. FEED CERTIFICATION RULES

Do not require all ten markets to be available at every moment.

Do require:

- Valid transport or successful bounded recovery
- Required subscriptions confirmed
- Correct `par` venue identity
- Healthy reconciliation
- No unresolved global safety failure
- Valid completed candle history for every eligible symbol
- Genuine candle provenance
- Per-market quarantine functioning
- Safe restoration of recovered symbols
- No numeric failures on admitted valid inputs
- No stale data entering strategy evaluation
- No rate-limit storm
- Persistence and accounting integrity
- Sufficient demonstrated usable-feed windows under the current certification policy

Do not weaken the certification criteria merely to produce a PASS.

A valid result may be:

`INFRASTRUCTURE_READY=true`

`FEED_READY=true`

`SCANNER_QUALIFIED=false`

`SIGNAL_AVAILABLE=false`

`PRACTICE_READY=false`

This means the feed can be usable even though there is no suitable market trade.

Alternatively, if the venue does not provide valid required history:

`INFRASTRUCTURE_READY=true`

`FEED_READY=false`

`BLOCKER=EXCHANGE_DATA_UNAVAILABLE`

is an honest result.

---

# 13. STRICT LIVE-TRADING BOUNDARY

Even if this entire task succeeds, keep:

`EXECUTION_MODE=PAPER`

`ALLOW_LIVE_ORDERS=false`

`PROTECTION_ENABLED=false`

Do not submit a certification trade automatically.

The funded testnet certification remains a separate human-authorized phase:

Fresh wallet/account preflight  
↓  
Approved API signer verification  
↓  
Actual fee/margin checks  
↓  
Emergency protection activation and verification  
↓  
One tiny LONG execution test  
↓  
Actual fill and fee reconciliation  
↓  
Reduce-only exit  
↓  
Verified flat account  
↓  
Tiny SHORT execution test  
↓  
Recovery certification  
↓  
Supervised competition practice

**This task is not authorized to cross that boundary.**

---

# 14. FAILURE-HANDLING REQUIREMENTS

Do not silently declare success.

If the root cause remains unknown:

Record exactly:

`CAUSE_UNDETERMINED`

Include evidence limitations and the next diagnostic action.

If Hyperliquid itself has sparse data:

Record:

`EXCHANGE_DATA_LIMITATION`

Only where raw evidence genuinely supports it.

If a software defect is discovered:

Record:

`IMPLEMENTATION_DEFECT_CONFIRMED`

Then document the tested correction.

If a fix introduces strategy drift:

Immediately mark:

`STRATEGY_FREEZE_FAILED`

Do not promote the code.

If a PAPER test encounters a critical accounting or safety problem:

Fail closed.

Never hide problems to satisfy a deadline.

---

# 15. REQUIRED FINAL ENGINEERING REPORT

Generate a structured Markdown report and machine-readable JSON evidence.

## A. Executive verdict

Choose exactly one:

- `AUDIT_INCOMPLETE`
- `ROOT_CAUSE_UNDETERMINED`
- `DEFECTS_IDENTIFIED`
- `FIXES_IMPLEMENTED_TEST_PENDING`
- `FIXES_VALIDATED_FEED_NOT_READY`
- `FEED_CERTIFIED`
- `CONTROLLED_EXECUTION_NEXT`

## B. Root-cause summary

Explain in easy language:

1. Why 331 of 360 observations were unusable.
2. Which failures were caused by our code.
3. Which failures were caused by the exchange.
4. Which remain unknown.
5. Why all ten markets were unavailable at shutdown.

## C. Per-market candle investigation

Include:

Market | Raw candles | Normalized candles | Cache candles | Valid strategy candles | Missing intervals | Root cause | Corrective action | Status

## D. Both numerical failures

For BRENT and EWY separately:

- Timestamp
- Exact failing input
- Exact function/line
- Cause
- Fix
- Test evidence
- Resolution status

## E. Modified files

For each file:

- Exact relative path
- Functions modified
- Old behavior
- New behavior
- Reason
- Risk of regression

Do not claim a file was changed if it was not.

## F. Safety verification

Include:

- Strategy freeze
- Order lock
- Signer safety
- Rate-budget safety
- No live-order proof
- No leaked secrets
- No fabricated data

## G. Test evidence

Report:

- Previous test count
- New test count
- Total tests
- Passed
- Failed
- Errors
- Skipped
- Strategy-freeze result

## H. PAPER certification

Include:

- Duration
- Source hash
- State directory
- WebSocket disconnects/recovery
- Healthy markets
- Stale markets
- Missing candles
- ATR passes
- Spread passes
- Qualified candidates
- Signals
- Simulated fills
- Actual orders
- Accounting/checkpoint state

## I. Before vs after comparison

Compare genuine observations against the previous 360/29/0 baseline.

Explain whether changes are attributable to code or different market conditions.

## J. Final readiness flags

Return:

`STRATEGY_FREEZE =`

`FULL_TEST_SUITE =`

`RAW_CANDLE_AUDIT =`

`REST_CANDLE_INTEGRITY =`

`WEBSOCKET_CANDLE_INTEGRITY =`

`CANDLE_MERGE_INTEGRITY =`

`NUMERIC_BRENT_RESOLVED =`

`NUMERIC_EWY_RESOLVED =`

`MARKET_HEALTH_READY =`

`QUARANTINE_READY =`

`REST_RECOVERY_READY =`

`TRANSPORT_READY =`

`RATE_BUDGET_READY =`

`RECONCILIATION_READY =`

`SHORT_PAPER_PASS =`

`THREE_HOUR_PAPER_PASS =`

`FEED_CERTIFIED =`

`CONTROLLED_EXECUTION_READY =`

`PRACTICE_READY =`

`LIVE_READY =`

Use `PASS`, `FAIL`, `NOT_TESTED` or another clearly justified status. Never mark untested components PASS.

## K. Exact next action

Finish with:

**THE SINGLE NEXT MOST IMPORTANT ACTION FOR TEAM ANCHORIUM.**

Provide the exact command only if the repository has been inspected and the command verified to exist.

---

# 16. DEFINITION OF DONE

This engineering assignment is complete when:

- Every previously unexplained gap has been investigated using available evidence.
- All confirmed repairable client defects in scope have been corrected.
- The raw-data-to-scanner pipeline has been verified.
- Both `INVALID_DECIMAL` incidents have been resolved or honestly documented as unresolved with precise blockers.
- Missing candles have not been fabricated.
- Protected strategy code remains unchanged.
- Tests and safety checks pass.
- A bounded PAPER validation has completed.
- Final readiness accurately reflects observed feed availability.
- No funded order or unauthorized account action occurred.
- All final evidence is reproducible and source-bound.

If the exchange itself cannot provide sufficiently complete data, do not claim the issue is fixed.

Instead, document the limitation and propose a separate, evidence-based compatibility research plan without modifying the frozen strategy.

---

# 17. FINAL NON-NEGOTIABLE ENGINEERING PRINCIPLE

**Team Anchorium must become genuinely reliable, not merely appear reliable.**

The ideal pipeline is:

Real Hyperliquid candles  
↓  
Correct REST/WS handling  
↓  
Accurate timestamps  
↓  
No accidental candle loss  
↓  
Full validated history  
↓  
Correct numeric calculations  
↓  
Per-market health check  
↓  
Healthy markets admitted  
↓  
Unhealthy markets quarantined  
↓  
Unchanged scanner and VWAP logic  
↓  
Risk gates remain active  
↓  
Honest `TRADE` or `NO_TRADE` decision

The system must never become more permissive merely because the competition deadline is approaching.

**Fix verified infrastructure defects. Preserve strategy integrity. Demonstrate results. Report remaining blockers precisely.**

## BEGIN EXECUTION

First inspect the repository and preserved run evidence. Produce the Phase One and Phase Two findings before editing production code.

Then implement only verified fixes, perform regression testing, execute bounded PAPER validation and deliver the final report.

**DO NOT ENABLE LIVE ORDERS.**
