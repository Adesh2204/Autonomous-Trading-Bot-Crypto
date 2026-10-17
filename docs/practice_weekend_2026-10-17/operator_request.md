# TEAM ANCHORIUM — P0 FINAL PRACTICE-WEEKEND TRADING ACTIVATION
## October 17–18, 2026 | Hyperliquid TESTNET `par`
### Fix Dynamic Entry Pricing · Qualify Native Stops · Activate Autonomous LONG Trading · Run Locally All Day

# PRIMARY MISSION

We have two practice days remaining before the scheduled October 19 scored phase.

The current engineering release has passed 2,675 tests and previously completed a genuine BTC LONG round trip.

The latest native qualification was approved but stopped before signing because:

- Approved maximum BUY price: 81,410
- Fresh executable ask: 81,412
- Difference: 2 USDPR per BTC
- Exact quantity: 0.0002 BTC
- Size, depth, fees and margin checks: passed
- Exchange orders submitted: zero
- Current reported account exposure: zero
- Native protection: unverified

**Do not rerun the consumed mandate.**

The immediate objective is to finish genuine native-protection qualification and activate a bounded, execution-enabled autonomous LONG system as soon as the required evidence and authorization exist.

Do not spend today's development time on unrelated strategies, cosmetic dashboards or general architecture rewrites.

---

# PHASE 1 — REPAIR THE PRICE-MOVEMENT APPROVAL PROBLEM

Investigate the exact order-price construction and final preflight logic in:

`scripts/run_native_qualification.py`

and its existing proposal, mandate, validation and exchange SDK dependencies.

## Problem

The approved fixed BUY limit can become nonmarketable while waiting for human acceptance.

The previous attempt failed because the ask rose from within the proposed limit to 2 USDPR above it.

This must be handled through a new bounded authorization design, not by disabling validation.

## Required engineering change

For a future new proposal:

1. Capture an initial fresh quote.
2. Determine the operator's maximum acceptable BUY limit.
3. Define a maximum approved adverse-price movement in basis points and absolute price terms.
4. Preserve current strategy and route-specific slippage restrictions.
5. Bind the full approved price range into the mandate before the operator accepts.
6. Refresh the ask immediately before the signing boundary.
7. Derive a correctly rounded, executable IOC limit from the current ask and available book.
8. Allow execution only while that limit remains within the operator-approved maximum and all existing risk constraints.
9. Reject if actual market conditions exceed the approved bounds.
10. Do not change the mandate after acceptance.

This is bounded dynamic pricing, not unrestricted automatic repricing.

One mandate may permit one authorized submission within its approved price corridor.

Do not silently permit multiple attempts or repeat an uncertain submission.

Test crossing prices, market deterioration, available depth, rounding, slippage, funding, fees and approval expiry.

## Acceptance criterion

A harmless small market movement within the newly approved price corridor no longer prevents an otherwise valid trade.

An adverse movement outside the corridor still blocks signing.

---

# PHASE 2 — SOLVE THE EXACT NATIVE STOP AND SUBMINIMUM PROBLEM

The registered venue has a normal $10 minimum order notional.

Runtime BTC lot: 0.0001 BTC.

At the previous price, one lot was worth approximately 8 TEST USDPR.

Therefore, an opening 0.0002 BTC IOC could partially fill only 0.0001 BTC.

Do not assume that a two-lot intended order eliminates partial-fill risk.

## Investigate position-associated protective orders

Official Hyperliquid documentation distinguishes:

- TP/SL associated with a position.
- TP/SL associated with a parent order.

Parent-associated TP/SL orders can be canceled after partial parent fills, leaving the resulting position without the expected child protection.

Inspect whether a genuinely supported position-associated, reduce-only native Stop Limit can provide the required behavior after the opening fill is authoritatively reconciled.

Test this possibility against the exact registered `par` DEX.

## Required evidence

Determine:

1. Whether a position-associated stop may cover a 0.0001 BTC residual.
2. Whether the exchange accepts that stop below ordinary minimum notional.
3. Whether a triggered child can close that residual.
4. Whether full-position reduce-only closure has a documented and applicable minimum exception.
5. Whether protective quantity can be associated dynamically with the remaining position.
6. Whether a stopped order can remain unfilled after triggering.
7. How a failed or partial closing child is identified and reconciled.
8. How native protection is safely canceled after independent take-profit closure.

The solution must preserve journal history, order identities, quantity precision, nonce uniqueness and actual account reconciliation.

Do not infer native stop support from the historical successful ordinary IOC close.

Do not disable the partial-fill safety guard.

## Alternative supported route

If position-associated native protection does not solve the issue, examine whether a currently permitted market has a runtime one-lot value above the required minimum at both protective and closing prices.

Use fresh venue metadata and genuine book evidence.

Do not invent additional markets or move trading outside the competition-authorized DEX.

If neither route is supported, report the exact venue limitation and continue with bounded simulation or specifically approved supervised qualification only.

---

# PHASE 3 — COMPLETE THE GENUINE SMALL TESTNET QUALIFICATION

After the new price-policy implementation passes relevant tests, prepare a NEW exact native-qualification mandate.

Use existing protected SDK execution and partial-entry recovery infrastructure.

The operator must explicitly approve:

- Exact team wallet and signer.
- Venue and market.
- Maximum opening position.
- Maximum BUY price and approved price corridor.
- Maximum fees and slippage.
- Margin and liquidity constraints.
- Stop trigger and closing-limit policy.
- Loss-making qualification exit authority.
- Permitted cancellation and recovery behavior.
- Maximum submission count.
- Session expiry.
- Uncertain/partial execution handling.

Do not use a previously consumed mandate.

## Genuine qualification steps

1. Fetch fresh positions and orders.
2. Verify the account is flat.
3. Verify source and regression release identity.
4. Verify actual book liquidity.
5. Verify all applicable order minimums.
6. Verify the approved bounded price corridor.
7. Submit the one permitted IOC BUY, after exact approval.
8. Reconcile actual filled quantity.
9. Establish approved position protection where supported.
10. Verify native order acknowledgement and identity.
11. Observe genuine trigger behavior if it occurs.
12. Obtain actual triggered child and closing fills when available.
13. Verify residual position handling.
14. Clean up owned orders.
15. Obtain two authoritative flat/zero-order readbacks.
16. Calculate actual qualification P&L.

Do not force artificial market movement to trigger stops.

If the native stop never triggers during the qualification window, honestly preserve the acceptance evidence and record that trigger execution is still unverified.

If permitted, use a separately authorized reduce-only close to safely end the supervised test.

Do not promote unverified trigger behavior into unattended protection readiness.

---

# PHASE 4 — VERIFY THE NEW SOURCE RELEASE

Run the necessary focused tests and the entire regression suite.

The previous baseline was 2,675 passing tests.

Any code modifications require a new source-bound release receipt.

Confirm:

- Frozen strategy integrity.
- Phase-0 checks.
- Existing journal and historical certificate.
- Nonce uniqueness.
- Position reconciliation.
- Dynamic price corridor.
- Order rounding and depth checks.
- Exact authorization matching.
- Stop placement and trigger-child reconciliation.
- Subminimum residual behavior.
- Partial and rejected fills.
- Uncertain order states.
- Duplicate prevention.
- Cross-midnight expiry.
- Session drawdown enforcement.
- Graceful shutdown and recovery.

A passing offline regression does not replace the required genuine native-protection evidence.

---

# PHASE 5 — PREPARE A NEW OCTOBER 17–18 AUTONOMOUS SESSION

Once the genuine native-protection prerequisites are qualified, inspect the existing overnight contract.

The previous implementation required creation and acceptance on October 16.

That old creation condition is now obsolete for a new October 17–18 practice session.

Implement a new strictly bounded TESTNET session type, without loosening any existing order-protection or signing checks.

## Proposed operating policy

- Network: Hyperliquid TESTNET only.
- DEX: `par`.
- Direction: LONG only.
- Strategy: current frozen qualified strategy.
- Position count: one global open position.
- Entry attempts: initially two total.
- Maximum leverage: initially 1x.
- Session loss ceiling: preserve existing 1%.
- Proposed bankroll: 20,000 TEST USDPR, not automatically authorized.
- Actual order size: limited by fresh entry/exit liquidity and risk.
- Desired larger notionals: research targets only until supportable.
- Native protection: genuinely qualified.
- Trading session: bounded cross-midnight October 17–18 period, with explicitly reviewed start, cutoff and expiry.
- Observation: may run continuously until manually stopped.
- Session rollover: no automatic new signing authorization.
- Operator approval: one fresh exact mandate after all prerequisites pass.

A session may permit routine repeated trades within its previously approved counts and budget.

It does not grant unlimited exchange signing authority.

## After closing a trade

Verify genuine fills, remaining position, open orders, owned stop cleanup, actual fees, funding and realized P&L.

Only then consider another independent valid signal.

Do not reuse a stale setup.

Do not allow an expired or exhausted mandate to authorize new entries.

---

# PHASE 6 — LAUNCH THE LOCAL EXECUTION-ENABLED WORKER

Use the existing standalone CLI:

`scripts/anchorium_cli.py`

Do not introduce a Codex-dependent runtime.

After genuine qualification and human approval:

1. Run diagnostics.
2. Verify matching source-bound release.
3. Confirm exact accepted mandate.
4. Verify registered account and API signer.
5. Verify account flatness and open orders.
6. Verify native protection readiness.
7. Verify market-data health.
8. Verify capital and loss limits.
9. Start the actual execution-enabled process.
10. Verify process ID, signing ownership and current status.

Do not describe public observation mode as active trading.

## Daily operation

The locally running program must perform:

`SCAN → VALIDATE SIGNAL → SIZE → BUY → RECONCILE → PROTECT → MANAGE → EXIT → RECONCILE → RECORD P&L → SCAN AGAIN`

When a genuine signal qualifies, the bot may act within the approved mandate.

An exit may realize a profit or a loss according to the authorized risk rules.

When no legitimate signal exists, remain FLAT and keep observing.

No forced entries.

No fabricated successful fills.

---

# PHASE 7 — RUN CONTINUOUSLY THROUGH THE APPROVED PRACTICE WINDOW

I want the standalone application operating throughout October 17–18 without ongoing Codex credits.

The observer should keep running until manually stopped or a genuine failure condition requires shutdown.

The execution engine must trade only within its approved session deadline.

Preserve:

- Fresh market-data checks.
- WebSocket recovery.
- REST request budgeting.
- Durable journal.
- Nonce and signing ownership.
- Source integrity.
- Trade and loss limits.
- Native stop verification.
- Partial-fill recovery.
- Uncertain-order handling.
- Operator cancellation.
- Explicit exposure reporting.

If an existing position becomes unprotected, suspend new entries and perform only the separately authorized recovery.

Do not assume local macOS sleep prevention guarantees continuous operation.

Do not leave an unknown position silently unmanaged.

---

# PHASE 8 — COMPLETE MORNING AND END-OF-DAY ACCOUNTING

Produce a terminal and saved report with:

- Genuine exchange BUY fills.
- Genuine exchange SELL fills.
- Completed round trips.
- Market and direction.
- Entry quantity and price.
- Closing quantity and price.
- Actual trading fees.
- Funding cashflows.
- Gross P&L.
- Net realized P&L.
- Remaining positions.
- Remaining open orders.
- Native protection status.
- Maximum drawdown.
- Trade count.
- Remaining risk budget.
- Session expiry and revocation.
- Any unresolved exposure.

Separate offline simulated results from actual TESTNET execution.

Never claim an unexecuted trade or hypothetical profit.

---

# STRICT PRIORITY — DO NOT GET DISTRACTED

Complete work in this order:

**P0.1:** Repair bounded dynamic BUY pricing and new approval composition.

**P0.2:** Investigate genuine position-associated native Stop Limit protection and subminimum residual handling.

**P0.3:** Perform the separately authorized small TESTNET qualification, if admissible.

**P0.4:** Obtain actual triggered closing and residual evidence when genuine venue behavior permits.

**P0.5:** Run full regression and obtain a source-matching receipt.

**P0.6:** Implement the new October 17–18 bounded trading contract.

**P0.7:** Prepare a fresh execution-enabled LONG mandate.

**P0.8:** Obtain exact human approval.

**P0.9:** Launch actual autonomous TESTNET trading from VS Code when every mandatory gate passes.

**P0.10:** Produce real exchange-backed trade and P&L reports.

Do not change the frozen trading strategy, weaken legitimate exchange controls, bypass rate limits, erase historical UNKNOWN records or reuse old approvals.

Do not modify quantity precision or liquidity limits to force large orders.

Do not create new BUYs while actual native protection remains unqualified.

Do not guarantee a profitable trade, successful venue qualification or a specified number of entries.

---

# FINAL COMMAND

Our practice deadline is approaching. Optimize engineering time by focusing on the exact remaining obstacles.

The previous attempt was blocked by a 2 USDPR adverse price movement. Design a new bounded price authorization so ordinary market movement inside the accepted corridor does not unnecessarily prevent execution.

Then prioritize the native Stop Limit and subminimum residual qualification on the genuine registered exchange.

**Do not spend the day repeatedly preparing expired proposals without resolving the root cause.**

Once protection is genuinely proven, activate the existing standalone multi-cycle LONG trading engine with one new exact human authorization.

Use the local VS Code terminal for ordinary monitoring and trade management.

Return a concrete result covering:

A. Dynamic-pricing repair and tests.

B. Genuine native-stop and residual evidence.

C. Current exchange-supported LONG notional.

D. Final passing regression count and hashes.

E. New session ID, full trading scope and approval deadline.

F. Exact verified VS Code execution command.

G. Worker startup and exchange execution evidence.

H. Actual BUY/SELL fills and realized P&L, if any.

I. Specific blocker and next valid action if exchange qualification remains unresolved.

**START THE ENGINEERING AND QUALIFICATION WORK NOW. DO NOT REPRESENT OBSERVATION OR OFFLINE TESTS AS EXECUTED TRADES.**