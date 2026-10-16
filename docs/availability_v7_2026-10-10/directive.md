# TEAM ANCHORIUM — MASTER IMPLEMENTATION DIRECTIVE V7.0
## Hyperliquid Market-Data Availability Intelligence + External Data Research Architecture

**Project:** Anchorium Autonomous Trading Bot  
**Competition:** Perpetual Alpha — ICAIF 2026  
**Exchange:** Hyperliquid Testnet  
**DEX:** `par`  
**Engineering priority:** CRITICAL  
**Objective:** Achieve demonstrably reliable market-data processing before scored trading  
**Execution mode:** PAPER ONLY  
**Implementation approach:** Inspect → Diagnose → Implement → Test → Validate → Report

---

# 0. YOUR MISSION

Act as a principal quantitative systems engineer, exchange market-data specialist, Python backend architect, and production trading reliability auditor.

Team Anchorium has completed multiple infrastructure improvements, but the bot still frequently fails its market-feed readiness checks.

You must now implement TWO independent but complementary systems.

### SYSTEM A — Native Hyperliquid Candle Availability Intelligence

Build a source-aware, continuously measurable Candle Availability Monitor for all ten official `par:` markets.

The system must determine:

- Whether genuine exchange candles exist.
- Which expected one-minute intervals are missing.
- Whether a candle is merely delayed.
- Whether REST or WebSocket supplies an earlier missing candle.
- How many consecutive valid completed candles exist.
- Why a market remains quarantined.
- When a market becomes safe for scanner evaluation.
- Whether the problem belongs to the exchange or our code, when evidence permits.

### SYSTEM B — External Market-Data Research Framework

Research a separate, competition-compliant data-source architecture capable of supplying externally sourced OHLCV data for strategy research and possible future signal generation.

External data must NEVER silently replace:

- Hyperliquid tradable prices
- Bid/ask quotes
- Market depth
- Mark and oracle prices
- Actual exchange fills
- Margin calculations
- Funding payments
- Position reconciliation

External signal-data usage must remain disabled in production until independently validated and expressly approved.

**These are two separate systems. Do not combine their trust boundaries.**

---

# 1. VERIFIED CURRENT BASELINE

Treat the previous report as historical evidence, not proof of present account or exchange health.

Latest recorded engineering state:

| Component | Latest reported result |
|---|---|
| Regression suite | 1,356 passed |
| Strategy freeze | Passed |
| Candle merge integrity | Passed |
| REST data integrity | Passed on captured inputs |
| WebSocket candle handling | Passed on captured inputs |
| Numeric BRENT defect | Resolved |
| Numeric EWY defect | Resolved |
| Quarantine system | Implemented |
| 15-minute PAPER | Failed feed certification |
| Healthy market observations | 1 / 30 |
| Usable markets at shutdown | 0 / 10 |
| ATR-qualified observations | 0 |
| Real orders | 0 |

The most recent captured 300-minute market windows included cases such as:

`par:BTC` — 299 of 300 candles

`par:HYPE` — 292 of 300 candles

`par:SP500` — 289 of 300 candles

`par:USDEUR` — 293 of 300 candles

Other markets had more substantial gaps.

The central unresolved question:

**Why are legitimately required recent candles sometimes unavailable during live operation, even when later REST queries may retrieve more complete historical windows?**

Your implementation must answer this using measured evidence wherever possible.

---

# 2. ABSOLUTE NON-NEGOTIABLE SAFETY RULES

## 2.1 Freeze the strategy

DO NOT MODIFY:

`signal_brain.py`

DO NOT CHANGE:

- VWAP core calculation
- UTC VWAP anchoring
- EMA9 / EMA21
- ATR formula
- ATR minimum of 0.40%
- Maximum spread of 15 bps
- 300 completed-candle requirement
- Full UTC strategy-history contract
- Top-3 scanner policy
- LONG/SHORT conditions
- Pullback, breakout and breakdown setups
- Directional bias
- Cooldown and anti-spam
- Stop-loss and target geometry
- Direction-flip behavior
- One-global-position constraint
- Actual-fill accounting

These components constitute the reproducible baseline.

## 2.2 Enforce execution lock

Throughout the task:

`EXECUTION_MODE=PAPER`

`ALLOW_LIVE_ORDERS=false`

`PROTECTION_ENABLED=false`

Forbidden actions:

- Signing exchange orders
- Placing or cancelling funded orders
- Changing leverage
- Changing account mode
- Modifying approved wallet permissions
- Transferring USDPR
- Loading Team Wallet private keys
- Enabling autonomous funded practice

Do not print or log API private keys or wallet secrets.

## 2.3 Never fake missing information

STRICTLY PROHIBITED:

- Synthetic flat candles
- Invented volume
- Interpolated OHLCV
- Replacing missing live candles with historical research CSVs
- Treating external BTC data as native `par:BTC` data
- Faking exchange liquidity or order-book depth
- Hiding data defects
- Bypassing candle freshness
- Lowering thresholds to manufacture trades

The objective is data integrity, not artificially increasing trade count.

## 2.4 Process ownership

Before running any validation:

1. Inspect currently running PAPER processes.
2. Respect ownership locks.
3. Never terminate an active bot automatically.
4. Never start a duplicate signing or PAPER process.
5. Use a fresh state directory for every new experiment.
6. Preserve previous evidence and source hashes.

Do not create scheduled Codex tasks, background AI monitors, or recurring workflows.

The engineering work must be bounded and credit-efficient.

---

# 3. PHASE A1 — REPOSITORY DISCOVERY

Before changing code, inspect the actual repository.

Locate existing implementations for:

- Market data ingestion
- WebSocket subscriptions
- REST historical candle retrieval
- Candle merging
- Candle completion handling
- Candle normalization
- Market-health assessment
- Missing-candle recovery
- Quarantine/restoration
- Scanner admission
- Rate-limit management
- Health reporting
- Opportunity-funnel reporting
- PAPER orchestration
- Timestamp diagnostics
- Existing public candle capture

Likely files include:

`exchange/hyperliquid_market_data.py`

`exchange/market_health.py`

`exchange/candle_audit.py`

`market_regime_scanner.py`

`market_stream.py`

`exchange/rate_limits.py`

`scripts/run_crypto_paper.py`

`scripts/check_practice_health.py`

These are candidate paths; verify them before editing.

Produce:

| File | Function/class | Current behavior | Existing capability | Required change |

IMPORTANT:

Extend working infrastructure rather than creating duplicate managers.

Do not perform unrelated architecture refactors.

---

# 4. PHASE A2 — BUILD THE CANDLE AVAILABILITY MONITOR

Create or extend a central component:

`CandleAvailabilityMonitor`

Its responsibility is to measure genuine exchange-candle availability for every official competition market.

Expected market universe:

- `par:BTC`
- `par:ETH`
- `par:HYPE`
- `par:SP500`
- `par:EWY`
- `par:EWJ`
- `par:BRENT`
- `par:GOLD`
- `par:USDEUR`
- `par:USDJPY`

Verify the live supported universe using the official `par` DEX metadata.

Do not query the ordinary/default Hyperliquid DEX by mistake.

## 4.1 Required measurements

For each market, track:

1. Current trusted timestamp.
2. Latest expected completed one-minute interval.
3. Exchange publication timestamps where observable.
4. Last observed genuine candle timestamp.
5. Last 300 expected completed intervals.
6. Genuine candles present in that window.
7. Missing intervals.
8. Missing timestamps.
9. Longest uninterrupted completed-candle sequence.
10. Current contiguous valid tail length.
11. Number of valid completed candles held.
12. Historical strategy-input completeness.
13. First observation time per candle.
14. REST observation history.
15. WebSocket observation history.
16. Publication-delay estimate.
17. Duplicate observations.
18. Conflicting duplicates.
19. Malformed candle count.
20. Last successful recovery.
21. Consecutive recovery failures.
22. Current quarantine reason.
23. Next scheduled recovery attempt.
24. Eligibility for frozen scanner evaluation.

Separate the existing 300-completed-bar cache requirement from the full UTC history required by the frozen strategy.

Do not accidentally shorten either.

## 4.2 Expected candle calculation

For one-minute candles:

Use genuine UTC-aligned minute boundaries.

Respect the actual exchange candle fields and documented semantics.

Distinguish:

- Candle start time
- Candle end time
- Current in-progress minute
- Last fully completed minute
- Exchange observation time
- Local reception time
- Processing time

Preserve the existing two-minute freshness policy unless an independent, approved configuration decision changes it.

Never treat the current unfinished minute as a completed candle.

## 4.3 Missing candle classification

A missing candle must have a meaningful reason.

Implement evidence-based classifications:

`CANDLE_NOT_YET_OBSERVED`

`CANDLE_PUBLICATION_DELAYED`

`CANDLE_ABSENT_IN_COVERED_REST_RESPONSE`

`REST_REQUEST_WINDOW_INCOMPLETE`

`WEBSOCKET_EVENT_NOT_OBSERVED`

`CANDLE_REJECTED_BY_VALIDATOR`

`CANDLE_MERGE_CONFLICT`

`CANDLE_CACHE_MISSING`

`RATE_BUDGET_RECOVERY_DEFERRED`

`INSUFFICIENT_CONTIGUOUS_HISTORY`

`CAUSE_UNDETERMINED`

Be careful with the word **permanent**.

A candle absent now may become available later.

Do not label it permanently missing without authoritative evidence.

---

# 5. PHASE A3 — MEASURE ACTUAL PUBLICATION DELAY

This is a critical feature.

For every expected completed candle interval:

Track when its close time occurs.

Then determine when that exact candle is first observed through each source.

Calculate:

`publication_delay_ms = first_observed_at_ms - expected_close_ms`

Keep separate REST and WebSocket observations.

If the candle never arrives during the observed period, record it as censored/unobserved rather than assigning an invented delay.

Generate a real-data publication latency distribution for every market.

Required statistics where samples are sufficient:

- Observation count
- Median publication delay
- P90 publication delay
- P95 publication delay
- P99 publication delay
- Maximum observed delay
- Number of never-observed intervals
- Number later recovered through REST
- Number first observed through WebSocket

Do not equate local network reception delay with exchange publication delay when those cannot be separated.

Do not assume sparse trading means an exchange API defect.

The purpose is to learn how long actual `par:` candle updates take to become available.

---

# 6. PHASE A4 — ADAPTIVE, BOUNDED REST RECOVERY

Build an intelligent recovery scheduler using the existing REST client and rate manager.

Required behavior:

Missing candle detected  
↓  
Identify the exact missing interval  
↓  
Check whether a recovery request is already pending  
↓  
Check rate budget and backoff  
↓  
Request genuine exchange candles  
↓  
Validate raw response  
↓  
Merge accepted real candles  
↓  
Recalculate history completeness  
↓  
Restore symbol only when genuinely eligible

## 6.1 Adaptive retry scheduling

Allow the retry scheduler to use measured publication-delay statistics as a research input.

Do not blindly retry all markets every second.

Use bounded attempts, exponential backoff and per-market cooldowns.

If latency statistics are insufficient, use conservative existing backoff behavior.

Prioritize repairs that can legitimately complete a near-ready market history, without starving other markets or safety-related requests.

No unlimited polling.

## 6.2 Merge integrity

Only merge genuine exchange-originated candles.

Check:

- Correct market identity
- Correct one-minute interval
- Correct timestamp boundaries
- Valid OHLC relationships
- Numeric volume
- No future completed bars
- No invalid decimals
- No conflicting completed candles without an explicit resolution policy

A valid REST response may merge into an incomplete cache, but it must never overwrite a newer verified completed observation incorrectly.

Record provenance for every accepted change.

## 6.3 Rate-limit safety

Preserve:

- Existing weighted request budgeting
- Public REST quotas
- Request coalescing
- Retry deadlines
- Safety reserves
- WebSocket connection limits
- Single recovery worker where appropriate

No recovery burst may exhaust resources required for account safety.

---

# 7. PHASE A5 — INTELLIGENT MARKET HEALTH

Retain the already implemented per-market quarantine system.

The new monitor must feed evidence into the existing health manager.

Required flow:

`par:BTC` has 299 valid bars  
→ Insufficient history  
→ BTC quarantined  
→ REST recovery scheduled

`par:ETH` has complete valid history  
→ Other required data checks pass  
→ ETH eligible for scanner evaluation

`par:EWJ` has no valid candles  
→ EWJ quarantined  
→ Report exact missing history  
→ Retry safely at bounded intervals

One bad symbol must not automatically block a genuinely healthy symbol.

However, never classify a market HEALTHY simply because it has fresh bid/ask or mark data.

Required market eligibility:

- Genuine complete strategy-required candle data
- Correct market identity
- Valid timestamps and OHLCV
- Fresh executable quote/book
- Fresh context where required
- No unresolved data-integrity conflict
- No active quarantine
- All existing scanner preconditions

Keep transport health separate from market health.

---

# 8. PHASE A6 — BUILD A HUMAN-READABLE DASHBOARD

Upgrade the current health reporting.

Target output:

TEAM ANCHORIUM — CANDLE AVAILABILITY

Network: Hyperliquid Testnet  
DEX: par

Transport: CONNECTED  
Subscriptions: 40/40  
Duplicates: 0  
Reconciliation: PASS

| Market | Valid bars | Missing | Last close age | Status |
|---|---:|---:|---:|---|
| par:BTC | 299 | 1 | measured | RECOVERING |
| par:ETH | 300 | 0 | measured | HEALTHY |
| par:HYPE | 292 | 8 | measured | QUARANTINED |
| par:EWJ | 0 | 300 | measured/unknown | QUARANTINED |

Values above are illustrative, not hardcoded actual results.

Include:

`TRANSPORT_READY`

`SUBSCRIPTIONS_READY`

`NATIVE_FEED_READY`

`HEALTHY_MARKET_COUNT`

`QUARANTINED_MARKET_COUNT`

`SCANNER_EVALUATION_ALLOWED`

`SIGNAL_AVAILABLE`

`TRADE_READY`

Also show:

- Highest-priority missing intervals
- Current recovery queue
- Recently restored symbols
- Recovery failures
- Data publication latency
- Rate-budget status

The user must never again receive only a vague `PAPER_DATA_OR_OPERATIONS_DEGRADED` without an explanation.

Preserve meaningful nonzero exit codes for real failures.

---

# 9. PHASE B1 — OFFICIAL COMPETITION COMPLIANCE RESEARCH

Now investigate a separately isolated external data option.

The official competition FAQ states that external data sources are permitted during practice and scored trading and should be documented.

Verify current wording directly:

https://perpetual-alpha26.github.io/faq/

Also consult:

https://perpetual-alpha26.github.io/docs/

https://hyperliquid.gitbook.io/hyperliquid-docs/

Document:

1. Whether externally sourced signal data is allowed.
2. Required disclosures.
3. Any available restrictions on data licensing.
4. Whether external data changes reporting obligations.
5. Which execution obligations remain venue-specific.
6. Whether current official rules have changed.

Never assume permission to use external signals implies permission to manipulate venue data or bypass exchange risk requirements.

Do not make changes to wallet/execution code during this research.

---

# 10. PHASE B2 — EXTERNAL DATA PROVIDER DISCOVERY

Investigate credible external sources for:

- Live and historical OHLCV
- One-minute candles
- Reliable timestamps
- Accurate volume semantics
- Low publication latency
- Consistent market coverage
- Reasonable pricing
- Documented API limits
- Stable integration

Research possible sources including official exchanges, market-data providers and public datasets.

Do not assume any provider is automatically suitable.

Evaluate both free and paid options, preferring reliable low-cost sources where comparable.

For each candidate record:

| Provider | Assets covered | 1m OHLCV | Volume valid | Latency | Historical coverage | API limits | Cost | Licensing | Verdict |
|---|---|---|---|---|---|---|---|---|---|

Distinguish:

- Verified documentation
- Current observed capability
- Provider marketing claims
- Unverified assumptions

Do not invent API prices, provider limits or availability.

If an API key is needed, create a placeholder configuration and ask for authorized setup later.

Do not scrape a provider against its terms or request unauthorized access.

---

# 11. PHASE B3 — ASSET-BY-ASSET DATA MAPPING

This phase is critical because Team Anchorium trades ten very different underlying markets.

Create a separate verified mapping for each:

`par:BTC`  
`par:ETH`  
`par:HYPE`  
`par:SP500`  
`par:EWY`  
`par:EWJ`  
`par:BRENT`  
`par:GOLD`  
`par:USDEUR`  
`par:USDJPY`

Verify:

- Underlying instrument
- Base/quote currency
- Price units
- Contract representation
- Market session
- Price adjustment methodology
- Volume meaning
- Corporate-action adjustment if relevant
- Futures contract roll effects if relevant
- Timestamp timezone
- Tradability of the external reference

Important special cases:

### BTC, ETH and HYPE

External spot candles, futures candles and `par` perpetual candles are not automatically identical.

Compare prices, basis, volume and session behavior.

### SP500

Cash index, CFD, ETF and index futures are different instruments.

A cash index may not supply genuine tradable volume suitable for the existing VWAP engine.

### EWJ and EWY

ETF trading sessions and overnight market conditions differ from continuously quoted `par:` markets.

Account for official exchange hours and stale external-session data.

### BRENT

Spot assessments and different Brent futures contracts may not match.

Futures expiry/roll conventions must be considered.

### GOLD

Spot XAU/USD, futures and broker-provided gold quotes may have different volume definitions.

### USDEUR and USDJPY

Verify the actual competition price convention, including whether `par:USDEUR` references EUR/USD.

Never silently invert or rescale FX series.

**If a source lacks real, semantically comparable volume, mark it unsuitable for unchanged VWAP signal generation unless separate validated research establishes otherwise.**

Do not synthesize volume.

---

# 12. PHASE B4 — BUILD AN ISOLATED SOURCE ABSTRACTION

Design a possible future architecture:

External Market Data  
↓  
External Provider Adapter  
↓  
Source-Specific Validation  
↓  
Asset Mapping Validation  
↓  
Timestamp Alignment  
↓  
Basis/Deviation Research  
↓  
Isolated Signal Research Dataset

Separately:

Official Hyperliquid `par:` Feed  
↓  
Executable Bid/Ask  
↓  
Book Depth  
↓  
Mark/Oracle  
↓  
Funding  
↓  
Margin/Risk  
↓  
Official Exchange Execution

Create a strict source interface, such as:

`MarketDataSource`

with explicit provenance:

- source identifier
- symbol
- interval
- timestamp
- OHLCV
- volume units
- observation timestamp
- validation status

Do not claim external candles are exchange-native.

Do not alter the existing live `par` adapter to disguise external inputs.

## 12.1 Source modes

Possible feature flags:

`SIGNAL_DATA_MODE=PAR_NATIVE_ONLY`

`EXTERNAL_RESEARCH_ENABLED=false`

`EXTERNAL_SIGNAL_LIVE_APPROVED=false`

Default remains:

`PAR_NATIVE_ONLY`

A research-only mode may load external data into a separate offline evaluation pipeline.

No new production execution mode may be enabled automatically.

---

# 13. PHASE B5 — EXTERNAL VS PAR VALIDATION

Before considering external data for actual strategy decisions, perform source-comparison research.

For every matched market and overlapping timestamp:

Compare:

- External OHLC
- Native `par` OHLC where available
- Current venue bid/ask
- Venue mark/oracle
- Absolute price difference
- Relative difference in bps
- Difference in realized volatility
- Candle-close timing
- Missing intervals
- Volume comparability
- VWAP differences where volume is meaningful
- EMA differences
- ATR differences
- Spread/slippage implications

Use only timestamps available to a strategy at decision time.

Prevent lookahead.

External data must not be retrospectively substituted to make a failed native-data backtest look successful.

Produce per-asset summaries and plots where appropriate.

Required classifications:

`EXTERNAL_SOURCE_VALIDATED_FOR_RESEARCH`

`EXTERNAL_SOURCE_POTENTIALLY_COMPATIBLE`

`EXTERNAL_SOURCE_INCOMPATIBLE`

`EXTERNAL_SOURCE_UNVERIFIED`

Do not create an automatic production fallback based on a short favorable comparison.

---

# 14. PHASE B6 — PAPER-ONLY COUNTERFACTUAL RESEARCH

Investigate whether external inputs would have improved the bot's ability to evaluate valid strategy opportunities.

Run an isolated comparison:

### Baseline A — Native par data only

Existing production data and strategy behavior.

### Experiment B — External research data

Same frozen calculations applied to the external source, only where its instrument and volume semantics are valid.

### Experiment C — Native and external agreement analysis

Measure whether external signals align with native venue price conditions and risk feasibility.

Required metrics:

- Valid observation count
- Missing-data percentage
- Signal count
- Agreement/disagreement
- VWAP divergence
- ATR divergence
- Signal timing divergence
- Hypothetical trade feasibility at actual observed venue quotes
- Estimated fees/slippage where data supports it
- Risk-adjusted outcomes where defensible

Clearly label assumptions.

Never fabricate historical order-book depth, funding cashflows or actual fills.

Any incomplete comparison must say `NOT ENOUGH EVIDENCE`.

---

# 15. PHASE B7 — STRICT SOURCE-CROSSING SAFETY

Even if external data research looks promising, the following rules are mandatory for any future approval:

External signal  
↓  
Native par market availability  
↓  
Fresh executable venue quote  
↓  
Actual exchange spread/depth  
↓  
Venue mark/oracle risk verification  
↓  
Funding/margin checks  
↓  
Frozen strategy and friction validation  
↓  
Risk and compliance checks  
↓  
Execution authorization

If native execution data is stale:

NO NEW ENTRY.

If the external source is stale:

NO EXTERNAL SIGNAL.

If instrument mapping is uncertain:

NO EXTERNAL SIGNAL.

If price basis exceeds a separately reviewed limit:

REJECT or QUARANTINE.

If comparable volume is unavailable:

DO NOT CLAIM THE VWAP IS EQUIVALENT.

Never treat external data as the source of truth for actual fills or positions.

External signal mode must require explicit human approval in a separate future task.

---

# 16. TESTING REQUIREMENTS — SYSTEM A

Implement unit/integration tests covering:

- One completed candle arrives on time
- Candle arrives late
- REST supplies missing genuine candle
- REST response is incomplete
- REST response is empty
- Missing interval later becomes available
- Interval never appears during observation
- WS event duplicates REST record
- Conflicting completed candles
- Out-of-order timestamps
- Future timestamp
- Invalid OHLCV
- Zero ATR is valid numeric data
- 299 valid bars does not satisfy 300
- 300 contiguous valid bars pass the history requirement
- Full UTC strategy history remains separately validated
- Last unfinished minute excluded
- Existing freshness allowance preserved
- Rate limit blocks optional retry
- Duplicate recovery requests coalesced
- Quarantine/restoration works
- Invalid market cannot enter scanner
- Healthy market remains independently usable
- Health report includes exact reasons

Do not alter strategy outputs on identical valid inputs.

---

# 17. TESTING REQUIREMENTS — SYSTEM B

Tests must verify:

- External feed disabled by default
- External adapter cannot submit exchange orders
- External adapter cannot overwrite `par` market cache
- Source provenance always present
- Invalid instrument mapping rejected
- Price-unit mismatch rejected
- FX direction mismatch rejected
- Stale external source rejected
- Missing or incompatible volume rejected for VWAP use
- No future-data leakage
- Native quotes remain execution truth
- Native account remains accounting truth
- External provider outage does not corrupt native feed
- Research mode cannot bypass live-order lock
- Research experiment outputs clearly labeled

Do not modify the frozen strategy.

---

# 18. FULL REPOSITORY REGRESSION

Run:

1. Strategy-freeze verification.
2. Phase-0 safety suite.
3. Candle normalization tests.
4. Market-health tests.
5. REST recovery tests.
6. WebSocket tests.
7. Rate-limit tests.
8. Numerical regression tests.
9. Quarantine tests.
10. External-source isolation tests.
11. PAPER accounting tests.
12. Checkpoint integrity tests.
13. Full repository regression.

Previous baseline:

`1356 PASSED`

No unexplained regressions allowed.

Do not hide test failures with broad mocks or skipped tests.

---

# 19. BOUNDED PUBLIC PAPER VALIDATION

After implementation and tests pass:

First verify no conflicting PAPER process exists.

Use a NEW state directory.

Start with one short, bounded read-only/PAPER session.

Duration: approximately 15–30 minutes.

Do not automatically begin a three-hour certification.

Do not create a recurring Codex monitor.

Track:

- Genuine available markets
- Missing completed intervals
- Publication delay
- Successful bounded recoveries
- Failed bounded recoveries
- Quarantine and restoration
- Strategy-history readiness
- REST request weights
- WebSocket health
- Numeric exceptions
- Scanner eligibility
- Source hashes
- Actual orders: MUST BE ZERO

If raw candles are genuinely unavailable, preserve that conclusion.

Do not mark certification PASS simply because the new dashboard works.

Only start a longer certification if the short run provides sufficient evidence under the existing readiness policy.

---

# 20. REQUIRED FINAL REPORT

Deliver a structured report with these sections.

## A. Executive verdict

Choose:

`IMPLEMENTATION_INCOMPLETE`

`IMPLEMENTED_TEST_PENDING`

`NATIVE_FEED_NOT_READY`

`NATIVE_FEED_READY`

`EXTERNAL_RESEARCH_COMPLETE`

`CONTROLLED_EXECUTION_NEXT`

These dimensions may be reported separately where appropriate.

## B. Files inspected and modified

Include exact paths, functions, reasons and test evidence.

## C. Candle availability report

For all ten markets:

| Market | Expected bars | Present | Missing | Contiguous history | Publication latency | Quarantine reason | Status |
|---|---:|---:|---:|---:|---|---|---|

## D. Root causes

Separate:

- Verified client defects
- Verified source-response absences
- Publication-delay observations
- Unknown causes
- Market conditions

## E. Recovery performance

Show:

- REST retries
- Recovered missing candles
- Failed recoveries
- Request-budget impact
- Duplicate prevention
- Restoration latency

## F. External provider comparison

Rank candidate providers by:

Coverage, OHLCV suitability, volume accuracy, freshness, reliability, limits, licensing, cost and confidence.

Do not invent verified capabilities.

## G. Ten-asset compatibility matrix

Clearly identify which `par:` assets have suitable potential external references and which do not.

## H. External data legal/compliance findings

Cite current organizer documentation and any unknown licensing issues.

## I. Source-isolation proof

Show why research/external data cannot silently reach live order execution.

## J. Tests

Report:

Previous total  
New tests  
Final total  
Passed  
Failed  
Skipped  
Strategy-freeze result

## K. PAPER results

Show actual run length, health, usable markets, candle availability, recovery and all safety outcomes.

## L. Final readiness flags

`STRATEGY_FREEZE =`

`FULL_TEST_SUITE =`

`CANDLE_MONITOR_IMPLEMENTED =`

`CANDLE_PUBLICATION_TRACKING =`

`REST_RECOVERY_VALIDATED =`

`CANDLE_PROVENANCE_VALIDATED =`

`MARKET_HEALTH_READY =`

`NATIVE_FEED_READY =`

`EXTERNAL_PROVIDER_RESEARCH =`

`EXTERNAL_ASSET_MAPPING =`

`EXTERNAL_SOURCE_COMPARISON =`

`EXTERNAL_SIGNAL_LIVE_APPROVED = FALSE`

`PAPER_READY =`

`CONTROLLED_EXECUTION_READY =`

`PRACTICE_READY =`

`LIVE_READY = FALSE`

`EXECUTION_MODE = PAPER`

`ALLOW_LIVE_ORDERS = false`

## M. Exact next action

Return ONE most important next action with the verified relevant command, if any.

---

# 21. SUCCESS CRITERIA

SYSTEM A succeeds when:

- Genuine candle availability is accurately measured.
- Missing timestamps are visible.
- Publication delays are observed, not guessed.
- REST recovery is bounded and safe.
- Valid candles are merged correctly.
- Invalid markets remain quarantined.
- Recovered markets can automatically regain eligibility.
- No fabricated candles are created.
- The frozen strategy remains unchanged.
- Every health verdict is supported by evidence.

SYSTEM B succeeds when:

- Current competition permissions are verified.
- External providers have been researched.
- Asset mappings are checked.
- Source differences and limitations are documented.
- A research-only comparison path exists where feasible.
- External data cannot contaminate native venue execution.
- No new external-data trading mode has been enabled.
- The jury-report provenance requirements can be satisfied.

Neither system may declare `PRACTICE_READY=true` merely because its own implementation tests passed.

---

# 22. FINAL ENGINEERING RULE

The purpose of this upgrade is to give Team Anchorium two reliable paths forward.

**PLAN A — Preferred**

Native Hyperliquid `par` candles  
→ Availability monitoring  
→ Intelligent bounded recovery  
→ Valid strategy history  
→ Existing scanner  
→ Frozen VWAP engine

**PLAN B — Research only until approved**

Independent credible external candles  
→ Verified asset mapping  
→ Data quality and basis comparison  
→ Isolated strategy research  
→ Explicit approval gate  
→ Potential future signal-data architecture

Both paths retain:

Official `par` order book  
→ Official risk and account state  
→ Official signed execution  
→ Actual fills  
→ Actual fees/funding  
→ Actual P&L

Do not turn the fallback into an unauthorized trading shortcut.

Do not weaken strategy thresholds to make a readiness report look better.

Do not generate repeated AI tasks, consume credits monitoring idle processes, or launch duplicate PAPER sessions.

**Preserve what works. Repair what is demonstrably broken. Research legitimate alternatives. Produce proof.**

# BEGIN EXECUTION

Start by inspecting the actual repository and the most recent V6 report.

Implement System A first.

Research and isolate System B second.

Run targeted tests and the full regression suite.

Perform only a bounded PAPER validation if no existing process is active.

Deliver the complete engineering report and the single highest-priority next action.

**ABSOLUTELY NO LIVE ORDERS OR AUTOMATIC TRADING ACTIVATION.**
