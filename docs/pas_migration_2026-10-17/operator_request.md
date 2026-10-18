# TEAM ANCHORIUM — CRITICAL AUTONOMOUS TRADING RECOVERY, PAS MIGRATION & EXECUTION ENGINE REBUILD

**Directive Version:** V2.0 — Full Engineering Implementation  
**Priority:** CRITICAL  
**Environment:** Hyperliquid TESTNET / Perpetual Alpha 2026  
**Target:** Production-quality, independently verified, autonomous scored-phase trading system  
**Competition Start:** October 19, 2026, 12:00 UTC (17:30 IST), subject to current organizer confirmation

---

# 0. ROLE AND ABSOLUTE MISSION

You are Team Anchorium's:

- Principal Quantitative Trading Engineer
- Hyperliquid Exchange Integration Specialist
- Algorithmic Execution Architect
- Financial Risk and Position Protection Engineer
- Distributed Systems Reliability Engineer
- Test Automation and Release Engineer
- Independent Technical Auditor

**You are not being asked to produce another theoretical report. You are being instructed to inspect the entire existing repository, identify the exact root causes, implement all software fixes that can legitimately be made, run extensive tests, and deliver a deployable autonomous trading system.**

## Primary objective

Build an autonomous bot capable of:

1. Discovering active PAS markets.
2. Detecting genuine profitable-opportunity candidates.
3. Evaluating executable order-book liquidity.
4. Estimating round-trip trading friction.
5. Executing BUY orders automatically within an approved mandate.
6. Automatically placing and verifying qualified stop-loss protection.
7. Executing exits and taking profit using approved strategy rules.
8. Closing small residual positions using documented venue behavior.
9. Continuously reconciling exchange state.
10. Displaying genuine PnL in the VS Code terminal.
11. Running unattended for the entire approved session.
12. Recovering from expected software and network failures.
13. Operating without per-trade human approval prompts.
14. Automatically stopping signing whenever authorization or safety conditions fail.

The goal is a functioning trading system, not a falsely reassuring green dashboard.

**Important distinction:** Individual BUY/SELL decisions may be automated after one valid, exact, human-approved session mandate. Never disable the initial authorization process, widen the approved scope, ignore session expiration, or bypass execution safety barriers.

No algorithm can guarantee profits, fill prices, or zero errors. The engineering goal is zero unresolved critical defects before release and deterministic safe behavior when failures occur.

---

# 1. MANDATORY REPOSITORY FORENSICS

Before editing any production code, inspect:

- Existing trading engine.
- CLI and runtime supervisor.
- Order signing implementation.
- Nonce allocation and persistence.
- Historical execution journals.
- SQLite databases.
- UNKNOWN order state.
- Native stop-loss components.
- Risk-management modules.
- Liquidity evaluator.
- Signal generation.
- Websocket market-data system.
- REST reconciliation.
- Account balance and equity calculations.
- Human approval and session-mandate implementation.
- Test receipts and release manifests.
- Emergency stop and recovery procedures.

Read the previous recovery reports under:

`docs/practice_recovery_2026-10-17/`

### Preservation requirements

Record and preserve:

- Current Git HEAD and source hashes.
- Previously verified 2,783-test release.
- Nine signing-boundary tests.
- Original `par:BTC` UNKNOWN CLOID.
- Original nonce.
- Historical fills and PnL.
- Human authorization receipts.
- Previous successful BUY/SELL evidence.
- Full position and order reconciliation records.

Create a separate implementation branch.

Never mutate historical evidence to obtain a passing result.

Every production change must be recorded and freshly tested.

---

# 2. CRITICAL FIX A — ORIGINAL UNKNOWN ORDER

## Original problem

The historical UNKNOWN is associated with:

**DEX:** `par`  
**Market:** `par:BTC`  
**CLOID:** `0xac0eea156fcec80986dd67c9057b6ded`  
**Nonce:** `1792217834069`

This is a practice-phase order, not an established PAS order.

**Do not rename or relabel this order as a PAS order.**

Investigate whether the historical ambiguity affects the new PAS deployment because of shared account, signer, nonce domain, order identity or execution-state coupling.

### Required investigation

1. Inspect the original order's entire execution path.
2. Reconstruct the exact signing and dispatch timeline.
3. Verify durable pre-HTTP intent records.
4. Examine original transport exceptions.
5. Inspect available historical order and fill records.
6. Query supported unsigned venue endpoints.
7. Identify whether any genuine terminal evidence exists.
8. Determine which account and nonce scopes are shared across DEXs.
9. Identify whether late or duplicate execution remains technically possible.
10. Review organizer guidance and existing resolution policies.

### Build a formal order-state recovery mechanism

Use explicit transitions:

`CREATED → PERSISTED → DISPATCHED → ACKNOWLEDGED → TERMINAL → RECONCILED`

Represent UNKNOWN as an independent state, not as an assumed rejection.

Require unique, durable order identifiers.

Prevent duplicate execution after network timeouts.

If the exchange confirms the original outcome using admissible evidence, apply the documented resolution procedure.

If no conclusive evidence exists, preserve the historical UNKNOWN and nonce.

### Investigate valid isolation

Determine whether the PAS account, execution scope and approved signing rules permit an independently safe new session despite the historical par ambiguity.

Only permit scoped isolation when:

- Venue/account/nonce independence is proven where necessary.
- Historical order state remains preserved.
- Duplicate-transmission and cross-venue risks are excluded.
- Existing immutable safety policy allows the separation.
- An authorized operator explicitly approves that recovery route.

Do not introduce a hidden alternative signer or simply remove UNKNOWN checks.

**Deliverable:** An explicit verdict stating either RESOLVED, SAFELY ISOLATED UNDER APPROVED POLICY, or BLOCKED EXTERNAL EVIDENCE, with supporting records.

---

# 3. CRITICAL FIX B — PAS EXCHANGE MIGRATION

## New organizer information

The scored DEX is **PAS**, not `par` and not `pa`.

The organizer-reported live collateral is USDP.

Keyrock is reported to be quoting PAS markets.

The scored phase is scheduled to open October 19, 2026, 12:00 UTC.

### Implementation

Build an isolated scored-phase configuration.

Do not overwrite the historical practice configuration.

Support:

- Practice venue: par.
- Scored venue: PAS, using the exact canonical identifier returned by exchange discovery.
- Separate collateral configuration.
- Separate market metadata.
- Separate historical trade accounting.
- Separate risk and session mandates.
- Explicit signed-venue identity.

### Live discovery requirements

Use documented unsigned Hyperliquid API requests to inspect:

- `perpDexs`
- `meta`
- `metaAndAssetCtxs`
- `perpDexStatus`, where supported
- `l2Book`
- `clearinghouseState`
- `openOrders`
- `spotClearinghouseState`
- `userAbstraction`
- `activeAssetData`

Verify the request schema and response shape rather than assuming all endpoints share one structure.

Identify:

- Actual PAS deployment identifier.
- Market asset identifiers.
- Available trading pairs.
- Whether each market is active.
- Delisting status.
- Quantity precision.
- Minimum order notional.
- Maximum leverage.
- Market OI caps.
- Trading fees.
- Mark and oracle prices.
- Margin and available trade size.
- Exchange maintenance status.

A market must not be eligible if delisted, halted, unsupported or lacking valid two-sided executable liquidity.

**Deliverable:** A verified PAS exchange discovery and configuration report.

---

# 4. CRITICAL FIX C — LIQUIDITY AND MARKET DEPTH

## Objective

Identify genuine executable opportunities with enough entry and exit liquidity.

The historical practice DEX produced approximately 50 TEST USDPR maximum liquidity-only observations.

These old observations must not be reused as PAS capacity.

### Full market scanner

Inspect all ten authorized markets, using dynamically verified PAS asset identifiers.

Collect:

- Best bid/ask prices.
- Best-level bid/ask quantities.
- Valid order-book depth.
- Spread in basis points.
- Available liquidity within 5 bps.
- Effective lot-rounded quantity.
- Entry feasibility.
- Exit feasibility.
- Actual estimated price impact.
- Maximum account trading capacity.
- Fees and funding rates.
- Market volatility.
- Order-book imbalance.
- Quote freshness and stability.

### Preserve legitimate capacity controls

Retain:

- Maximum 10% of both relevant best-level quantities.
- Existing bounded depth restrictions.
- Valid venue minimums.
- Actual lot precision.
- Account trading caps.
- Approved risk allocation.
- Protection and residual feasibility.

Never combine book levels to bypass the best-level rule.

### Capital optimizer

Build a conservative sizing system.

For each prospective trade, calculate:

`ALLOWABLE_SIZE = MIN(`

`APPROVED_CAPITAL_CAP,`  
`RISK_LIMITED_SIZE,`  
`ENTRY_BOOK_CAPACITY,`  
`EXIT_BOOK_CAPACITY,`  
`VENUE_MAX_SIZE,`  
`POSITION_PROTECTION_CAPACITY`  
`)`

Then apply actual exchange lot rounding and minimum-notional checks.

Larger bankrolls may be evaluated, but never treat capital size as a substitute for liquidity.

If $10,000 is allocated but only $50 can be entered and exited within approved constraints, the qualifying executable size cannot exceed the smaller capacity.

### Improve execution economics

Research and implement, where legitimately supported:

- Maker versus taker execution.
- Post-only orders.
- Carefully bounded passive execution.
- Dynamic limit prices.
- Adaptive position sizing.
- Fee-aware trade selection.
- Reduced unnecessary order replacements.
- Spread-quality filters.
- Slippage-aware routing.
- Conservative fill-probability modeling.
- Queue and adverse-selection risks.
- Exit-liquidity reservations.

Passive orders must not be assumed to fill.

Do not use self-trading, wash trading, spoofing or market manipulation to create artificial liquidity.

**Deliverable:** Real PAS liquidity capacity, executable sizes, and reasons each market passes or fails.

---

# 5. CRITICAL FIX D — NATIVE STOP-LOSS SYSTEM

## Objective

Implement reliable automatic position protection.

**This is one of the highest-priority components.**

A stop-loss must never be marked successful merely because an order was accepted.

### Study native protective orders

Verify:

- Native Stop Limit support.
- Any documented native stop-market alternative.
- Trigger-price basis.
- Mark-price triggering.
- Position-linked stop semantics.
- `positionTpsl` grouping.
- Position sizing and automatic resizing.
- Reduce-only behavior.
- Parent/child order lifecycle.
- Partial fills.
- Triggered child-order execution.
- Cancellation semantics.
- Stop expiration.
- Minimum-notional behavior.
- Native protective-order survival after disconnects.

### Build a protection state machine

`ENTRY_FILLED`

↓

`PROTECTION_SUBMITTED`

↓

`PROTECTION_ACKNOWLEDGED`

↓

`PROTECTION_ARMED`

↓

`TRIGGER_OBSERVED`

↓

`CLOSING_ORDER_VERIFIED`

↓

`CLOSING_FILL_CONFIRMED`

↓

`POSITION_FLAT_AND_RECONCILED`

### Failure handling

Implement bounded, deterministic responses for:

- Stop submission rejection.
- Protection acknowledgement timeout.
- Protection cancellation.
- Trigger without execution.
- Partial execution.
- Market gaps.
- Exit liquidity disappearance.
- Network disconnection.
- Stale exchange data.
- Orphaned protective orders.
- Unexpected remaining positions.

Use exchange-supported emergency reduce-only closing procedures when authorized and feasible.

A local watchdog may help detect failed protections, but it cannot guarantee exit execution or replace server-side protection when disconnected.

### Qualification

Create offline integration and fault-injection tests.

Separately require a genuine, approved venue qualification proving:

1. Real entry fill.
2. Protective order acceptance.
3. Correct stop association.
4. Natural trigger.
5. Closing-order execution.
6. Actual closing fill.
7. Final account reconciliation.

Do not manufacture a trigger or accept simulated execution as live proof.

A Stop Limit cannot guarantee a fill through a gap.

If reliable risk control is unsupported for a market, exclude that market rather than disabling the stop-loss requirement.

**Deliverable:** Genuine native-protection qualification evidence or an explicit unqualified verdict.

---

# 6. CRITICAL FIX E — SUB-$10 POSITION CLOSING

## Organizer clarification

The Discord message attributed to Giorgio states:

A reduce-only order that closes the entire remaining position can be accepted even below the normal $10 minimum.

Example: a full-position close of 0.0001 BTC.

### Required changes

Differentiate:

1. New position entry.
2. Partial position reduction.
3. Complete position reduction.

Do not apply the normal opening minimum indiscriminately to valid full-position reduce-only closing orders.

Implement quantity precision checks.

Verify the full remaining position size from current venue state.

Ensure the closing order cannot increase exposure.

Prevent rounding that leaves unmanaged residuals.

Test:

- Residual below $10.
- Partial fills.
- One-lot position.
- Multiple-lot position.
- Full reduce-only close.
- Price changes during closure.
- Rejection or stale position information.

The organizer clarification supports investigation of the full-position reduce-only exit route. It does **not** establish that every native stop-loss route works for subminimum residuals.

**Deliverable:** Independently tested closing semantics, plus genuine venue proof for any route used in autonomous trading.

---

# 7. CRITICAL FIX F — ACCOUNT EQUITY AND COLLATERAL

Detect whether the team account is operating in Standard or Unified mode.

Do not change account mode automatically.

### Standard mode

Inspect `clearinghouseState` using the verified PAS DEX identifier and its valid margin fields.

### Unified mode

Reconcile applicable `spotClearinghouseState` collateral, USDP balances and unrealized position PnL.

Avoid double-counting equity.

### Validate

- Actual team wallet.
- Approved API signer association.
- Account mode.
- Correct collateral token.
- Available trading capital.
- Existing positions.
- Open orders.
- Unrealized PnL.
- Realized PnL.
- Fees.
- Funding.
- True available trade size.

Never treat a zero margin field in one account mode as definitive proof that the entire account is unfunded.

Do not fabricate organizer funding or transfer funds without separate approval.

---

# 8. CRITICAL FIX G — AUTOMATED BUY/SELL WITHOUT PER-TRADE APPROVAL

## Desired behavior

The operator should not have to approve every individual BUY or SELL in the VS Code terminal.

The trading engine must make independent execution decisions **inside a valid, explicitly preapproved session mandate**.

### Implement one-time session approval

Before trading begins, the operator reviews and approves:

- Exchange and account identity.
- PAS market scope.
- LONG-only or separately authorized direction.
- Maximum allocation.
- Maximum trade size.
- Maximum trade risk.
- Session loss limit.
- Maximum entry attempts or trades.
- Leverage and margin mode.
- Allowed trading times.
- Session expiry.
- Authorized release hash.
- Qualified native protection.
- Recovery rules.

Once exact approval is recorded and validated, no additional human interaction should be required for routine BUY/SELL actions inside those boundaries.

### Noninteractive trading loop

`SCAN → SIGNAL → VALIDATE → SIZE → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE`

Automatically:

1. Monitor PAS market data.
2. Detect valid frozen-strategy signals.
3. Check estimated returns after friction.
4. Check entry and exit liquidity.
5. Calculate risk-limited size.
6. Place the authorized order.
7. Confirm actual fill.
8. Verify qualified protection.
9. Manage the open position.
10. Execute approved exit logic.
11. Reconcile genuine net PnL.
12. Continue scanning if authorization remains valid.

No terminal approval prompt should appear for each ordinary trade.

**Never remove the initial approval requirement.**

Do not silently renew expired mandates.

Do not convert a finite mandate into unlimited signing permission.

If the bot needs broader capital, longer duration, additional markets or additional entries, require a new human-approved mandate.

---

# 9. CRITICAL FIX H — CONTINUOUS OPERATION AND RELIABILITY

Design the system to run unattended within the approved operating window.

### Process lifecycle

Implement:

- Persistent asynchronous market observation.
- Websocket reconnection.
- Stale-price detection.
- Persistent order journal.
- Exchange reconciliation after network recovery.
- Durable process checkpoints.
- Duplicate-worker prevention.
- Bounded retry policies.
- Rate-limit handling.
- Exchange error classification.
- Automatic read-only degradation.
- Graceful manual shutdown.
- Emergency stop.
- Session-expiry enforcement.

### Important

The operator may stop the process manually.

However, manual termination must not be the only trading stop condition.

The bot must automatically stop new entries if:

- The approved session expires.
- Risk limits are reached.
- The exchange is unavailable.
- Order state becomes ambiguous.
- Protection cannot be verified.
- Position accounting disagrees with the venue.
- Market data becomes invalid.
- An emergency stop is triggered.

When safe signed execution is unavailable, the bot may continue in read-only observation mode.

Never automatically extend signing authority after process restart.

---

# 10. CRITICAL FIX I — REAL-TIME TERMINAL DASHBOARD

Create a continuously updating, readable terminal dashboard.

Display:

```text
=====================================================
           TEAM ANCHORIUM AUTONOMOUS TRADER
=====================================================

DEX:                    PAS
COLLATERAL:             USDP
MODE:                   OBSERVE / AUTHORIZED TRADING
SESSION:                VALID / EXPIRED / BLOCKED

MARKET DATA:            HEALTHY / STALE
SIGNING AUTHORITY:      VALID / DISABLED
ORDER RECONCILIATION:   VERIFIED / UNKNOWN
NATIVE PROTECTION:      QUALIFIED / UNQUALIFIED

-----------------------------------------------------
MARKET OPPORTUNITIES
-----------------------------------------------------
MARKET   SIGNAL   SPREAD   NET EDGE   CAPACITY
BTC      ...      ...      ...        ...
ETH      ...      ...      ...        ...
EWJ      ...      ...      ...        ...

-----------------------------------------------------
ACCOUNT PERFORMANCE
-----------------------------------------------------
INITIAL EQUITY          VERIFIED VALUE
CURRENT EQUITY          VERIFIED VALUE
REALIZED GROSS PNL      VERIFIED VALUE
TRADING FEES            VERIFIED VALUE
FUNDING                 VERIFIED VALUE
REALIZED NET PNL        VERIFIED VALUE
UNREALIZED PNL          VERIFIED VALUE
TOTAL RETURN %          VERIFIED VALUE

-----------------------------------------------------
CURRENT TRADING STATUS
-----------------------------------------------------
ACTIVE MARKET           VERIFIED VALUE
OPEN POSITION           VERIFIED VALUE
ENTRY PRICE             VERIFIED VALUE
PROTECTIVE STOP         VERIFIED STATE
TAKE PROFIT             VERIFIED STATE
LAST EXCHANGE UPDATE    TIMESTAMP
NEXT ACTION             EXPLANATION
-----------------------------------------------------
```

All displayed values must originate from actual exchange records, valid calculations or explicitly marked estimates.

Never show hypothetical profit as realized profit.

Persist session reports and terminal logs automatically.

---

# 11. CRITICAL FIX J — REQUEST LIMITS AND TIMING

The Discord discussion specifies an address-based request allowance and additional Unified-mode limits.

Verify current actual venue limits before designing the scheduler.

Implement:

- Weighted request-budget monitoring.
- REST request coalescing where documented.
- Websocket preference for continuous market updates.
- Conservative polling frequencies.
- Rate-limit backoff.
- Timestamp freshness guards.
- Separate order and cancellation handling.
- Circuit breakers.
- Retry classification.

Preserve the existing five-second signing freshness requirement.

Test at:

- 4,900 milliseconds.
- 5,000 milliseconds.
- 5,100 milliseconds.

Never bypass timestamp or nonce safety to improve request throughput.

---

# 12. CRITICAL FIX K — REAL PROFITABILITY AND STRATEGY QUALITY

Protect the existing frozen strategy.

Do not modify its signal logic without separately authorized research and regression verification.

Evaluate whether it remains appropriate for PAS.

For every trade candidate estimate:

`EXPECTED_NET_EDGE = EXPECTED_GROSS_EDGE - FEES - SPREAD - SLIPPAGE - EXPECTED_FUNDING`

Account for uncertainty and adverse market movement.

A candidate may execute only when:

- The strategy signal is valid.
- Order-book capacity exists.
- Conservative expected net edge is positive.
- Both entry and exit feasibility are supported.
- Venue rules are satisfied.
- Risk and protection checks pass.
- Authorization remains active.

Do not force trades because the terminal has been idle.

Report the number of signals evaluated and the reason for every rejected candidate.

Evaluate performance using:

- Net return after costs.
- Drawdown.
- Return volatility.
- Win/loss statistics.
- Average gain versus average loss.
- Slippage.
- Execution success.
- Funding effects.
- Strategy stability.

Align scoring research with current official competition rules.

Do not equate frequent trading with high-quality trading.

---

# 13. EXHAUSTIVE REGRESSION AND FAILURE TESTING

After implementing production changes, rerun the full applicable regression suite on the exact final source.

Preserve the old 2,783-test evidence as historical release evidence only.

Add tests for:

- PAS discovery.
- Incorrect DEX selection.
- Inactive or delisted markets.
- Incorrect collateral mode.
- Shallow liquidity.
- One-sided order books.
- Missing exit depth.
- Inadequate margin.
- Minimum-notional rejection.
- Sub-$10 full-position exits.
- Partial reductions.
- Native protection rejection.
- Stop trigger without closing fill.
- Position residuals.
- Network timeouts.
- UNKNOWN order state.
- Duplicate nonce prevention.
- Wrong account identity.
- Stale request timestamps.
- Order signing delays.
- API rate limits.
- Websocket reconnects.
- Unexpected position changes.
- Stale approvals.
- Expired mandate.
- Restart during execution.
- Crash during entry.
- Crash during protection.
- Kill-switch activation.
- Invalid release hash.
- Session expiry.
- Account reconciliation failure.
- Terminal PnL calculations.

Run deterministic integration and adversarial tests.

Include stress cases involving spread widening, disappearing liquidity, market gaps, extreme funding and exchange outages.

Do not label simulated results as genuine trading evidence.

Any critical failed invariant blocks autonomous signing.

---

# 14. QUALIFICATION AND RELEASE READINESS

Before permitting autonomous signed execution, verify:

1. The scored DEX is active and tradable.
2. Correct account and collateral are available.
3. Applicable historical order risks are resolved or independently isolated under approved policy.
4. Native position protection has genuine evidence.
5. Supported small-position closure behavior is verified.
6. Sufficient entry/exit liquidity exists.
7. Expected trade economics survive friction.
8. The complete source-matched regression passes.
9. The scored phase is open.
10. Fresh session authorization exists.
11. The operator has reviewed exact risk and expiry terms.
12. The terminal displays reconciled account status.

Do not initiate trades merely to create validation evidence without separate authorization.

If qualification requires organizer intervention, produce the exact evidence request and continue non-signing development.

---

# 15. FINAL ENGINEERING DELIVERABLES

Produce a complete implementation report and working operator runbook.

## Deliverable A — Source modifications

List every changed file, root cause and fix.

## Deliverable B — Blocker status

| Blocker | Required proof |
|---|---|
| Wrong scored DEX | Verified PAS integration |
| Liquidity | Actual PAS executable-capacity evidence |
| Sub-$10 residual | Qualified closing semantics |
| Account equity | Accurate verified mode-specific accounting |
| Historical UNKNOWN | Admissible resolution or approved safe isolation |
| Native stop-loss | Genuine trigger-to-closing-fill evidence |
| Trading authorization | Fresh, exact, valid session mandate |

Every row must be independently verified.

## Deliverable C — Read-only readiness

Provide one tested VS Code command that starts continuous PAS observation without signing.

## Deliverable D — Human approval

Provide the existing validated procedure for granting one exact session authorization.

Do not fabricate mandates, files or approvals.

## Deliverable E — Authorized autonomous launch

Provide one tested VS Code launch command.

After a valid initial mandate, routine BUY and SELL decisions must not require additional terminal approval.

## Deliverable F — Shutdown

Provide a verified graceful-stop command and emergency recovery procedure.

## Deliverable G — Verified accounting

Provide actual exchange-derived entry, exit, fees, funding, net PnL, open orders and positions.

## Deliverable H — Qualification evidence

Include genuine native-order chain, residual-closure proof, release checksums and timestamps.

## Deliverable I — Final verdict

Return exactly one:

- READY_FOR_AUTHORIZED_TRADING
- READY_FOR_OBSERVATION_ONLY
- BLOCKED_EXTERNAL_EVIDENCE
- BLOCKED_ENGINEERING_FAILURE

Never mark a component GREEN unless its acceptance criteria have passed.

---

# 16. REQUIRED EXECUTION STYLE

Work through all phases systematically.

Do not stop after preparing a report if implementation work remains possible.

Do not silently alter frozen strategies, eliminate critical checks, relabel order history or manufacture evidence.

For every issue:

**REPRODUCE → ROOT CAUSE → IMPLEMENT → TEST → VERIFY → DOCUMENT**

Fix real software defects immediately where practical.

When blocked by venue-controlled records, independently identify exactly what evidence is missing and how to obtain it.

Use the minimum safe number of external exchange actions.

Preserve the distinction between offline tests, read-only venue observations and genuine signed qualification.

Do not claim absolute reliability or guaranteed profit.

---

# FINAL DIRECTIVE

Team Anchorium requires an autonomous, reliable and competition-ready algorithmic trading system.

Resolve every software-controlled blocker that can be genuinely fixed.

Rebuild PAS market discovery, execution sizing, friction estimation, stop-loss handling, residual closure, account-mode reconciliation, and runtime reliability as required.

Enable autonomous BUY/SELL execution **without per-trade human approval prompts once a valid, bounded, exact session mandate has been granted**.

Maintain mandatory session limits, risk controls, order-state safety and organizer rules.

Do not represent unresolved issues as fixed.

The final outcome must be an independently verifiable software release, exact operating instructions and a truthful GO/NO-GO verdict—not a cosmetic dashboard showing artificial success.

**BEGIN IMPLEMENTATION WITH PHASE 1 REPOSITORY FORENSICS AND CONTINUE THROUGH EVERY IMPLEMENTABLE PHASE.**