# ANCHORIUM AUTONOMOUS TRADING BOT — CRITICAL EXECUTION RECOVERY & OVERNIGHT AUTONOMY DIRECTIVE

## ROLE & MISSION

You are the **Principal Quantitative Trading Engineer, Exchange Execution Architect, Risk Systems Engineer, Site Reliability Engineer and Independent Release Auditor** responsible for recovering and hardening Team Anchorium's Hyperliquid testnet autonomous trading system for Perpetual Alpha 2026.

**Primary objective:** Transform the existing repository into a genuinely reliable autonomous trading system that can run continuously during a valid, explicitly authorized session, identify economically viable opportunities, execute trades when qualified signals occur, manage positions safely, and reconcile verified net PnL.

This is an engineering implementation assignment, not a theoretical report. Inspect the actual code, reproduce defects, implement justified fixes, run tests and produce verified operating instructions.

Do not declare success merely because the software starts or tests pass.

**Critical constraint:** Never manufacture exchange evidence, bypass an unresolved order, disable essential risk controls, forge approvals or launch unauthorized trades. If authoritative evidence is unavailable, preserve the block and produce the shortest concrete resolution path.

---

# PHASE 0 — REPOSITORY INSPECTION AND STATE PRESERVATION

First inspect these exact existing files:

- `docs/practice_recovery_2026-10-17/final_report.md`
- `docs/practice_recovery_2026-10-17/VENUE_OPERATOR_REVIEW_PACKET.md`
- `docs/practice_recovery_2026-10-17/UNKNOWN_INTENT_RESOLUTION_REPORT.md`
- `docs/practice_recovery_2026-10-17/NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md`
- `docs/practice_recovery_2026-10-17/FRESHNESS_REPAIR_VERIFICATION_REPORT.md`
- `scripts/anchorium_cli.py`
- Existing release receipts, runtime state, SQLite journal, historical execution artifacts, risk configuration and live execution modules.

Discover all other relevant source files automatically.

Before changing anything:

1. Record the repository commit and relevant source hashes.
2. Preserve the original trading journal and UNKNOWN record.
3. Verify exchange account state using supported unsigned calls.
4. Confirm which registered-par markets are authorized.
5. Identify the exact active risk limits and session mandate.
6. Create a recoverable working branch.
7. Confirm no signer or worker is running.
8. Record existing release-test status.
9. Do not rewrite historical evidence.

Known baseline:

- Original release: 2,753 passing tests.
- Targeted freshness verification: 381 passing tests.
- One unresolved UNKNOWN order and preserved nonce.
- Zero open orders/positions at the last observed readback.
- Native Stop Limit trigger-to-closing-fill proof unavailable.
- Maximum liquidity-only LONG observations approximately 50 TEST USDPR.
- New trading authorization currently absent.
- Original strategy and source release must not be silently modified.

These are historical observations, not proof of current exchange state.

---

# PHASE 1 — ENGINEER A FORMAL SOLUTION TO UNKNOWN ORDERS

## Problem

The system preserved an UNKNOWN state because the original order's causal outcome could not be demonstrated.

Current exchange observations showing no positions or open orders are insufficient to prove that the earlier request was never transmitted.

## Engineering requirements

Inspect:

- Order submission and signing sequence.
- Request construction and transport.
- HTTP request transmission boundaries.
- CLOID and nonce generation.
- SQLite persistence.
- Pre-HTTP intent claims.
- Reconnection and retry behavior.
- Exchange acknowledgements.
- Original exceptions and available transport evidence.
- Order-status, fill-history and relevant authoritative exchange endpoints.

Reconstruct the original event's exact causal timeline.

Implement a durable order-intent state machine:

`CREATED -> PERSISTED -> DISPATCHED -> ACKNOWLEDGED -> ACCEPTED/REJECTED -> FILLED/CANCELED/EXPIRED -> RECONCILED`

Model UNKNOWN explicitly where the outcome cannot be established.

Every state transition must have admissible evidence and be auditable.

### Required improvements

- Persist the intent and unique identifiers before network transmission.
- Preserve original exception classes and relevant transport metadata.
- Prevent duplicate order execution following timeouts.
- Use documented exchange idempotency behavior where supported.
- Reconcile websocket events against authoritative venue queries.
- Distinguish rejection from timeout and unknown transmission.
- Never infer rejection solely from missing open orders.
- Never overwrite an ambiguous state to obtain authorization.

### Historical UNKNOWN resolution

Attempt formal evidence-based reconciliation.

If the original request's terminal outcome can be authoritatively established, produce a certificate referencing genuine evidence and apply the existing approved resolution procedure.

Otherwise preserve UNKNOWN and generate a complete operator escalation package containing:

- Exact CLOID and nonce.
- Original local event timestamps.
- Original request and correlation evidence.
- Available exchange readbacks.
- Specific missing causal proof.
- Precise organizer/venue questions.
- Proposed sanctioned isolated qualification procedure, requiring separate approval.

**Acceptance:** Previously unresolved orders can be resolved only through admissible evidence or a documented authorized recovery mechanism. The original UNKNOWN must remain blocked if neither is available.

---

# PHASE 2 — FIX FIVE-SECOND REQUEST FRESHNESS

## Objective

Eliminate genuine client-side timing defects without widening the exchange's five-second freshness boundary.

Review:

- Local versus exchange time.
- Timestamp creation.
- Timestamp expiry at signing and dispatch.
- Synchronous SDK delays.
- Asynchronous queueing.
- Network transmission latency.
- Retries and backoff.
- Timestamp precision and clock skew.
- Order creation versus signing timestamps.
- Expired-order rejections.

Implement deterministic deadline-aware signing and dispatch.

Requirements:

1. Do not sign an already expired intent.
2. Do not reuse stale signatures.
3. Revalidate freshness at the actual documented dispatch boundary.
4. Distinguish expiry before transmission from ambiguous post-transmission outcomes.
5. Reject unsafe retries.
6. Measure real execution latency.
7. Preserve existing nonce safety.
8. Never extend the configured five-second exchange limit.

Test specifically at:

- 4,900 ms.
- 5,000 ms.
- 5,100 ms.

Add slow-SDK, delayed-network, reconnect and clock-skew tests.

**Acceptance:** All offline boundaries pass, and eventual real exchange validation is reported separately using genuine authorized execution evidence.

---

# PHASE 3 — QUALIFY GENUINE NATIVE STOP-LOSS PROTECTION

## Objective

Establish dependable native position protection before allowing unattended trading.

Inspect current registered-par venue support for:

- Native Stop Limit orders.
- Trigger-price reference.
- Mark-price triggers.
- Reduce-only behavior.
- Position sizing.
- Parent/child relationships.
- Partial fills.
- Trigger-to-closing-order transition.
- Post-trigger fill behavior.
- Cancellations and protective-order expiry.
- Small residual quantities.

Implement a protective-order state machine:

`ENTRY_FILLED -> STOP_SUBMITTED -> STOP_ACKNOWLEDGED -> ARMED -> TRIGGERED -> CLOSE_ORDER_TRACKED -> POSITION_CLOSED -> RECONCILED`

Distinguish stop acceptance, trigger and actual closing fill.

Do not treat an accepted or triggered stop as proof that the position is closed.

Design recovery handling for:

- Rejected stop.
- Stop cancellation.
- Missing stop acknowledgement.
- Partial stop execution.
- Market gaps through limit prices.
- Orphaned parent/child orders.
- Unexpected position-size changes.
- Websocket disconnect.
- Unable-to-close conditions.

No strategy may open a new position while an earlier position has unverified protection.

If the venue lacks a guarantee of closure, document residual tail risk rather than describing the stop as a guaranteed maximum-loss cap.

A native route is not considered qualified until genuine venue evidence proves its complete execution lifecycle.

If qualification is blocked by the historical UNKNOWN, request an organizer-sanctioned, separately authorized isolated qualification; do not create a secret alternative signer.

---

# PHASE 4 — SOLVE SUBMINIMUM POSITION RESIDUALS

Investigate the registered-par minimum-notional and lot-size rules using authoritative venue specifications.

Test the behavior of remaining positions after:

- Partial take-profit.
- Partial stop execution.
- Price movement.
- Quantity rounding.
- Minimum order size changes.
- Partial market fills.
- Position reconciliation.

Define explicit deterministic behavior for every possible residual category.

Investigate legitimate position-reducing execution methods supported by the registered venue.

A historical full-position IOC closure is evidence for that exact case only.

Do not generalize it into unsupported permissions for arbitrary assets, quantities or native stop orders.

If a particular position size cannot be safely protected and closed, exclude it from executable capacity.

**Acceptance:** No supported entry path can produce an unexplained or unmanaged residual under the modeled scenarios. Real-venue claims require genuine evidence.

---

# PHASE 5 — REBUILD THE LIQUIDITY AND EXECUTION OPPORTUNITY ENGINE

## Critical priority

The bot currently observes extremely limited executable LONG capacity.

Increasing bankroll alone does not solve shallow books.

Build an intelligent execution-capacity evaluator that identifies the largest genuinely feasible position size consistent with the existing venue, liquidity and risk restrictions.

For all ten registered-par markets, inspect:

- Best bid and ask.
- Valid executable top-level quantity.
- Order-book depth.
- Allowed price impact.
- Spread.
- Actual lot rounding.
- Venue minimum order size.
- Account limits.
- Entry capacity.
- Exit capacity.
- Timestamp freshness.
- Fees and funding.
- Expected execution slippage.
- Adverse selection.
- Signal quality.
- Residual closeability.

Retain the existing 10% participation restriction on **both** best levels and the applicable 5-basis-point depth rule.

Do not count multiple order-book levels in a way that bypasses best-level restrictions.

### Implement conservative sizing

For every market, compute:

`MAX_EXECUTABLE_NOTIONAL = MIN(`

- `approved_allocation`
- `remaining_risk_budget`
- `account_permitted_size`
- `entry_depth_capacity`
- `exit_depth_capacity`
- `lot_rounded_capacity`
- `venue_supported_capacity`
- `protection_supported_capacity`

`)`

Capital must never exceed the exact approved session allocation.

A larger approved allocation may be investigated only if exchange depth, fees, risk and venue rules independently permit its effective use.

### Improve opportunity discovery

Build a deterministic ranking model prioritizing:

1. Executable two-sided liquidity.
2. Verified entry and exit feasibility.
3. Spread and estimated transaction costs.
4. Relevant volatility and tradable movement.
5. Valid frozen strategy signals.
6. Expected return after friction.
7. Protection and residual feasibility.
8. Operational freshness and data quality.

Evaluate multiple bounded observation windows using unsigned market-data requests.

Record why each market passes or fails.

Do not manufacture executable opportunities by manipulating price assumptions or relaxing trading controls.

### Legitimate friction reduction

Investigate:

- Documented maker versus taker fee differences.
- Post-only execution where supported.
- Appropriate bounded limit-order execution.
- Reducing unnecessary cancel/replace operations.
- Adaptive order sizing within existing restrictions.
- Opportunity filtering by expected net edge.
- Avoiding poor-spread conditions.
- Executing only while quotes remain fresh.
- Comparing conservative passive versus aggressive fills.
- Minimizing adverse selection and missed fills.
- Exit execution risks.

Passive orders are not automatically cheaper after accounting for selection bias, queue position and missed fills.

Any revised routing logic must pass execution simulations, stress tests and fresh authorization before live deployment.

**Acceptance:** Produce a market-by-market report separating observation, liquidity-only capacity, economically viable capacity and finally authorized executable capacity.

---

# PHASE 6 — BUILD A REALISTIC NET PROFITABILITY ENGINE

Trading activity is not proof of trading profitability.

For each candidate trade, calculate:

`ESTIMATED_NET_PNL = EXPECTED_GROSS_PNL - ENTRY_FEES - EXIT_FEES - SPREAD_COST - SLIPPAGE - EXPECTED_FUNDING`

Express profit expectation in both TEST USDPR and percentage of allocated capital.

Account for estimation uncertainty.

A trade may execute only when:

- A valid strategy signal exists.
- Expected net edge is positive under the approved conservative model.
- The opportunity survives stress assumptions.
- Sufficient entry and exit capacity exists.
- Required protections are qualified.
- The trade meets current risk constraints.
- Trading authorization is active.
- No unresolved order or position hazard exists.

Do not invent expected returns or imply profitable opportunities exist without evidence.

Collect statistical evidence from historical and permitted forward observation to assess whether positive expected edge is actually supported.

Report:

- Number of candidate signals.
- Number passing entry capacity.
- Number passing exit capacity.
- Number passing friction estimates.
- Number passing protection.
- Number finally authorized.
- Actual trades and realized results.

If no positive-edge opportunity exists, waiting is correct behavior.

Do not lower confidence or edge thresholds simply to generate activity.

---

# PHASE 7 — AUTOMATED STRATEGY OPERATION

Preserve the currently frozen, approved strategy implementation.

Do not silently modify trading signals or `signal_brain.py` if its freeze is applicable to this repository.

Implement or improve the orchestration surrounding the strategy.

The approved bot should operate using the lifecycle:

`SCAN -> SIGNAL -> RISK CHECK -> SIZE -> EXECUTE -> VERIFY -> PROTECT -> MANAGE -> EXIT -> RECONCILE`

### SCAN

Continuously observe approved markets.

### SIGNAL

Use the existing approved strategy to identify legitimate LONG opportunities.

### RISK CHECK

Verify valid session, no unresolved order, supported protection, sufficient liquidity, risk budget, signal freshness and net-edge criteria.

### SIZE

Choose a conservative executable quantity within all restrictions.

### EXECUTE

Submit the authorized entry intent with durable idempotent identity and verified freshness.

### VERIFY

Confirm actual fill quantity, price and status using genuine exchange records.

### PROTECT

Place and verify native protection using the qualified venue procedure.

### MANAGE

Monitor exposure, order state, protection, connectivity and position health.

### EXIT

Execute approved deterministic exit rules. Do not improvise profit targets or ignore protection.

### RECONCILE

Verify final account positions, open orders, fees, funding and net realized PnL.

Only then may the bot consider another opportunity, subject to the approved session's trade-count and risk limits.

Do not assume a signal means guaranteed correct market direction.

---

# PHASE 8 — OVERNIGHT OPERATION, WATCHDOG AND RECOVERY

## Desired operating experience

The operator wants to launch one terminal command and leave the system operating overnight, with clear evidence of what the bot is doing.

Implement two explicitly separate operating states:

**OBSERVE MODE**

Can run unattended to collect market data, classify opportunities, maintain read-only health information, and produce diagnostics.

It must not sign or submit orders.

**AUTHORIZED TRADING MODE**

Can execute eligible trades only when every mandatory prerequisite is verified and a fresh, exact human-approved mandate is active.

### Critical runtime behavior

- Keep observation running while the application is healthy.
- Do not require an LLM or coding agent continuously for deterministic trading decisions.
- Recover safely from transient market-data disconnections.
- Reconcile before resuming execution after ambiguous network events.
- Do not retry unknown order submissions blindly.
- Maintain a persistent journal.
- Restore read-only state after a process restart.
- Require renewed evidence and permission before restoring signing ability.
- Detect exchange outages and stale prices.
- Detect protection failures and position inconsistencies.
- Detect repeated rejection or rate limiting.
- Prevent multiple simultaneous trading workers.
- Prevent duplicate exposure after crashes.

### Mandatory safety boundaries

The operator manually controls normal shutdown, but manual shutdown must **not** be the only stopping mechanism.

Signing must automatically stop upon:

- Session authorization expiry.
- Exchange or organizer trading-window closure.
- Risk-budget exhaustion.
- Session loss-limit breach.
- Invalid or stale exchange state.
- Unresolved intent.
- Missing or unverified protection.
- Critical infrastructure failure.
- Loss of reliable position reconciliation.
- Explicit emergency stop.

A stopped trading session may continue safe read-only monitoring, but it must not automatically renew trading authorization.

Never create a hidden indefinite signing mandate.

Respect the documented session's LONG-only, single-position, 1x CROSS, per-trade/session loss, total entry attempt and absolute expiry constraints.

Any expansion in trade count, capital or operating duration requires new exact human authorization.

### Graceful shutdown

Implement tested SIGINT/SIGTERM handling.

Prevent new entries, preserve active protection, follow the authorized reduce/close policy, reconcile the account and save final evidence.

Do not claim a clean shutdown while unresolved exposure remains.

---

# PHASE 9 — BUILD A PROFESSIONAL LIVE TERMINAL DASHBOARD

Create a readable continuously refreshed terminal interface.

Example presentation:

```text
====================================================
             ANCHORIUM AUTONOMOUS TRADER
====================================================

MODE                 OBSERVE / AUTHORIZED_TRADING
VENUE                HYPERLIQUID TESTNET
SESSION              ACTIVE / BLOCKED / EXPIRED
MARKET CONNECTION    HEALTHY / DEGRADED
ORDER RECONCILIATION VERIFIED / UNKNOWN
NATIVE PROTECTION    VERIFIED / UNQUALIFIED

----------------------------------------------------
MARKET OPPORTUNITIES
----------------------------------------------------
MARKET     SIGNAL   NET EDGE   CAPACITY   DECISION
par:BTC    LONG     estimate   calculated BLOCKED/GO
par:ETH    NONE     --         calculated OBSERVE
par:EWJ    LONG     estimate   calculated BLOCKED/GO

----------------------------------------------------
EXECUTION ACCOUNTING
----------------------------------------------------
INITIAL EQUITY          Exchange verified
CURRENT EQUITY          Exchange verified
REALIZED GROSS PNL      Exchange verified
ENTRY / EXIT FEES       Exchange verified
FUNDING                 Exchange verified
REALIZED NET PNL        Exchange reconciled
UNREALIZED PNL          Marked and labeled
TOTAL RETURN %          Defined equity basis
OPEN POSITIONS          Exchange verified
OPEN ORDERS             Exchange verified

----------------------------------------------------
RISK & OPERATION
----------------------------------------------------
RISK USED               Actual reconciled value
SESSION LOSS LIMIT      Approved value
ORDER STATE             Verified / UNKNOWN
PROTECTIVE ORDER        Verified / Missing
NEXT ACTION             Explicit reason
LAST HEARTBEAT          Actual timestamp
----------------------------------------------------
```

Do not invent live values.

Every displayed PnL amount must have a clearly defined source and accounting basis.

Show actual realized profits, unrealized valuation, fees and funding separately.

Never convert hypothetical profits into verified PnL.

Persist logs and receipts to a timestamped session directory.

Provide concise human-readable reasons whenever a candidate signal is rejected.

---

# PHASE 10 — REGRESSION, FAILURE INJECTION AND RELEASE CERTIFICATION

Any change to production source invalidates the assumption that earlier release tests alone qualify the new code.

Run the full applicable regression suite on the final changed source.

Add targeted tests for:

- Unknown order after network timeout.
- Original HTTP rejection.
- Acknowledged order with delayed fills.
- Duplicate order prevention.
- Reconnect during entry.
- Reconnect during exit.
- Stop order accepted but never triggered.
- Stop triggered but not filled.
- Partial close and residual quantity.
- Invalid lot rounding.
- Liquidity disappearing before submission.
- Fee-adjusted net return turning negative.
- Price slippage beyond limits.
- Timestamp freshness at 4,900/5,000/5,100 ms.
- API rate limiting.
- DNS and transport failures.
- Concurrent worker launch attempts.
- Crash immediately after signing.
- Restart with UNKNOWN state.
- Session expiry with open exposure.
- Session loss-limit breach.
- Manual interruption.
- Missing approval artifacts.
- Invalid native-protection evidence.
- Unauthorized attempt to expand capital or duration.

Include integration, adversarial and property-based tests where appropriate.

Use mocks only for software correctness. Never present mocked order fills as genuine exchange qualification.

Generate fresh source hashes, test receipts, regression summaries and release manifests.

Any failure in an essential authorization, reconciliation, protection or risk invariant blocks trading.

---

# PHASE 11 — HUMAN APPROVAL AND LAUNCH PROCEDURE

Inspect the real CLI and current approval framework.

Identify the exact supported mechanism for preparing, reviewing, accepting and validating a new mandate.

Approval must bind the exact:

- Account and venue.
- Markets and direction.
- Capital allocation.
- Leverage.
- Per-trade risk.
- Session loss limit.
- Maximum entries.
- Start and expiry times.
- Code and release identity.
- Native-protection evidence.
- Recovery policy.

Do not create approval records on behalf of the human operator.

Do not silently reuse expired mandates.

The documented execution interface is:

```bash
.venv/bin/python scripts/anchorium_cli.py start --authorized \
  --mandate "$NEW_VALIDATED_MANDATE_JSON" \
  --acceptance "$GENUINE_ACCEPTANCE_JSON" \
  --release docs/practice_weekend_2026-10-17/freshness_repair_regression_release/test_receipt.json \
  --native-protection-evidence "$QUALIFIED_NATIVE_PROOF_JSON" \
  --state runtime/terminal
```

Treat this as a reference interface only.

Confirm the current implementation, artifact paths, release matching and actual authorization procedure before presenting any launchable command.

Never substitute generated dummy evidence.

The operator should eventually receive:

1. One verified command for safe observation.
2. One verified command or workflow for presenting and recording exact human approval.
3. One verified command for starting an already authorized session.
4. One documented emergency-stop procedure.
5. One procedure for reviewing terminal PnL and final reconciliation.

If genuine authorization inputs are unavailable, provide observation mode only.

---

# PHASE 12 — COMPETITION READINESS

The competition's scored phase is scheduled for October 19–November 6, 2026.

Distinguish practice, gap and scored trading windows.

Verify permitted account activity, venue registration and competition rules.

Optimize for the actual published scoring calculation, which includes risk-adjusted performance rather than raw profit alone.

Build a daily performance report showing:

- Net return.
- Equity changes.
- Daily return volatility.
- Estimated financial score using verified scoring parameters.
- Fees and funding.
- Drawdown.
- Trade count.
- Opportunity conversion rate.
- Operational failures.
- Qualification and authorization status.

Do not claim a leaderboard ranking without current official evidence.

Do not increase leverage, concentrate exposure excessively or override safety controls solely to improve rankings.

---

# FINAL DELIVERY — NON-NEGOTIABLE OUTPUT

Before ending this coding task, deliver the following.

## A. Engineering changes

List every changed source file, why it changed and what defect it fixes.

## B. Blocker resolution table

For each original blocker, show:

- Original failure.
- Root cause.
- Implemented fix.
- Verification evidence.
- Remaining external dependency.
- Status: RESOLVED / PARTIALLY RESOLVED / BLOCKED.

## C. Liquidity and friction report

Show the genuinely supported maximum executable LONG capacity for each registered market, including all constraints and fee-adjusted opportunity criteria.

## D. Testing results

Provide exact test counts, failures, evidence links, source hashes and release validity.

## E. Autonomous operation report

Demonstrate observation-mode operation and tested process recovery.

Only demonstrate genuine exchange trading if separate valid authorization and all prerequisites exist.

## F. Operator runbook

Provide copy-paste VS Code terminal commands for:

- Environment verification.
- Read-only monitoring.
- Human authorization procedure.
- Authorized launch.
- Terminal dashboard.
- Safe shutdown.
- Accounting verification.

Do not invent commands or paths that do not exist in the repository.

## G. Genuine trading evidence

When and only when a valid test or trading session has actually occurred, report:

- Signed order identity.
- Exchange acknowledgement.
- Actual entry fill.
- Actual protective-order event.
- Actual exit fill.
- Actual fees and funding.
- Actual realized net PnL.
- Final reconciled positions and orders.

If these are unavailable, state NOT VERIFIED.

## H. Final go/no-go verdict

Return exactly one classification:

**READY_FOR_AUTHORIZED_TRADING** — All hard prerequisites genuinely verified and exact approval valid.

**READY_FOR_OBSERVATION_ONLY** — System can safely monitor but may not sign.

**BLOCKED_EXTERNAL_EVIDENCE** — Venue/operator evidence is required.

**BLOCKED_ENGINEERING_FAILURE** — Essential tests or invariants are failing.

Do not classify a partially qualified system as ready.

---

# STRICT SUCCESS CRITERIA

Successful engineering means:

1. No unacknowledged or ambiguous order is treated as safely resolved.
2. Every submitted order has durable identity and recovery semantics.
3. Native protection and residual handling are genuinely qualified before autonomous exposure.
4. Executable liquidity is calculated using real venue constraints.
5. Trading friction is estimated conservatively.
6. No trade executes without a valid signal and risk authorization.
7. Terminal accounting reconciles against actual exchange records.
8. The bot handles expected infrastructure failures without losing critical state.
9. Autonomous activity respects exact session expiry and emergency stops.
10. A fresh release passes required tests.
11. Overnight read-only operation works independently of the coding agent.
12. Trading is launched only if evidence, risk gates, competition rules and explicit human approval all permit it.

**FINAL MANDATE**

Treat this as a high-priority engineering recovery assignment.

Implement everything that can genuinely be fixed in software. Investigate and correct false-positive blockages. Improve liquidity discovery, execution economics, diagnostics, reliability and operator experience.

Do not spend the task merely repeating known blockers.

However, do not remove legitimate controls to force transactions, and do not claim successful trading, guaranteed returns or a ready system without actual evidence.

Produce the strongest genuinely qualified autonomous trading release possible from the existing repository, and give the operator an exact, trustworthy path from the current blocked state to authorized continuous operation.