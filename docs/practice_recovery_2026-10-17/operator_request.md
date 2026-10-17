# TEAM ANCHORIUM — P0 FINAL PRACTICE RECOVERY AND AUTONOMOUS TRADING ACTIVATION
## October 17–18, 2026 | Hyperliquid TESTNET
### Critical Engineering, Exchange Qualification and Execution-Readiness Assignment

## PRIMARY OBJECTIVE

The standalone Team Anchorium trading application has passed 2,753 tests.

The dynamic entry-price corridor is working, and the five-second signing-data freshness issue has been repaired offline.

However, autonomous trading remains blocked by:

1. A newly created local UNKNOWN order intent.
2. Unverified native Stop Limit trigger and closing behavior.
3. Unverified subminimum partial-position protection and closure.
4. Missing fresh executable autonomous-session authorization.

**Your objective is to resolve these exact issues in the shortest reliable sequence, preserve all legitimate safety controls and prepare genuine autonomous LONG trading for the remaining practice period.**

Do not spend time rebuilding working modules, changing trading strategies or adding unrelated dashboards.

### Verified historical state

- Venue: Hyperliquid TESTNET `par`.
- Registered team wallet: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`.
- Existing successful BTC round trip: +0.050512 TEST USDPR net on October 15.
- Latest October 17 qualification: no confirmed exchange fill.
- Last authoritative account evidence: flat, zero open orders.
- Latest release: 2,753 tests passed.
- Current autonomous trading authority: NONE.
- Original strategy: FROZEN.
- Production defaults: PAPER / ALLOW_LIVE_ORDERS=false.

## PHASE 1 — FORMAL RESOLUTION OF THE NEW UNKNOWN INTENT

**Priority: Immediate. No additional exchange signing until the unresolved-order barrier is correctly satisfied.**

Investigate original CLOID:

`0xac0eea156fcec80986dd67c9057b6ded`

Investigate allocated nonce:

`1792217834069`

Review:

- Original approved mandate and its validity.
- Exact source identity used during signing.
- Durable journal and nonce records.
- Pre-HTTP and HTTP-boundary telemetry.
- Raw worker exceptions.
- Original SDK transport behavior.
- Exchange frontend orders.
- Exchange order history.
- Exchange fill history.
- Authoritative position history.
- Post-attempt reconciliation snapshots.

Determine whether the original action can be classified as:

- Proven not transmitted.
- Proven exchange-rejected without execution.
- Proven terminal through authoritative exchange evidence.
- Still unresolved/UNKNOWN.

Do not infer nontransmission solely from missing HTTP logs, `unknownOid`, zero positions or zero open orders.

Do not delete the UNKNOWN row, reset nonces or reuse its mandate.

If a verified resolution is possible, append the existing framework's required immutable evidence and validate its exact identity.

If adequate evidence is unavailable, preserve UNKNOWN, identify the missing proof and stop additional signing. Escalate to the venue or operator where needed.

### Deliverable

`UNKNOWN_INTENT_RESOLUTION_REPORT`

Include exact evidence, classification, applicable certificate or terminal record and whether the relevant safety barrier legitimately permits future signing.

## PHASE 2 — VALIDATE THE FIVE-SECOND FRESHNESS REPAIR

The previous failure occurred because readiness data was approximately 5,526 ms old against a 5,000 ms boundary.

The latest repaired release claims to reacquire required account, readiness, metadata and book evidence near the actual signing boundary.

Verify the new behavior thoroughly.

Required:

1. Refresh all mandatory signing data.
2. Bind checks to the same reserved order identity.
3. Revalidate account, fees, funding, spread, depth and approved price corridor.
4. Preserve order quantity, price authorization, CLOID and nonce ownership.
5. Confirm no historical UNKNOWN can enter the freshness-renewal path.
6. Ensure one reserved order cannot result in duplicate submissions.
7. Preserve bounded exchange-rate budgets.
8. Record exact pre-HTTP failures for future diagnosis.

Test freshness at 4,900 ms, 5,000 ms and 5,100 ms, plus realistic SDK delays and changing order books.

Do not increase the five-second limit merely to avoid the rejection.

### Deliverable

A verified freshness-repair report identifying the tests, exact source revision and any remaining race conditions.

## PHASE 3 — SOLVE THE NATIVE STOP LIMIT AND SUBMINIMUM RESIDUAL PROBLEM

The latest report shows that every sampled market's one-lot value remains below the ordinary 10 TEST USDPR minimum.

Determine whether native protective orders or complete reduce-only position closures have supported exceptions on the registered `par` DEX.

Investigate:

- Position-associated TP/SL behavior.
- Native Stop Limit creation.
- Stop ownership and quantity.
- Reduced or partial entries.
- Subminimum residuals.
- Triggered child-order generation.
- Full-position reduce-only closure.
- Stop execution after gaps.
- Residual reconciliation and cleanup.

Read authoritative venue documentation and examine available genuine venue evidence.

Do not use simulated SDK responses as proof of native stop acceptance.

Do not infer Stop Limit trigger execution from a historical IOC full-position close.

Do not weaken the partial-fill guard or modify runtime lot precision.

If an exchange-supported solution exists, implement the minimum isolated correction and prepare its qualification.

If not, clearly identify the missing external evidence and whether the venue itself prevents unattended qualification.

### Deliverable

`NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN`

This must state which assumptions are documented, which are exchange-verified and which remain unknown.

## PHASE 4 — CONDUCT A CONTROLLED GENUINE QUALIFICATION

Only after the unresolved-order barrier permits further signing and a valid venue route is available:

1. Generate a fresh source-bound qualification proposal.
2. Obtain explicit operator authorization.
3. Confirm exact account and signer.
4. Confirm flat account and zero unexpected orders.
5. Confirm current book liquidity and approved bounded price corridor.
6. Use a venue-compliant test quantity.
7. Submit only the approved opening order.
8. Reconcile the genuine entry fill.
9. Place approved native protection when eligible.
10. Verify native protection identity and account association.
11. Reconcile actual trigger and child closing fills if genuine market movement causes execution.
12. Resolve all residual positions using only authorized recovery.
13. Clean up owned protection.
14. Obtain two authoritative flat/zero-order readbacks.
15. Record actual P&L.

Do not manufacture stop triggers, self-trade or force a prohibited execution.

An accepted but untriggered stop is useful partial evidence, not complete trigger/closing qualification.

If the qualification cannot be fully completed, preserve the actual evidence and do not declare unattended trading ready.

## PHASE 5 — COMPLETE FULL SOURCE-BOUND REGRESSION

After engineering changes:

- Run focused UNKNOWN resolution tests.
- Run all freshness tests.
- Run partial-fill tests.
- Run native stop identity and trigger-child tests.
- Run duplicate and nonce safety checks.
- Run complete LONG entry/exit integration tests.
- Run cross-midnight lifecycle tests.
- Run full regression.
- Verify Phase-0.
- Verify frozen strategy integrity.
- Verify source, XML and receipt hashes.
- Verify journal and database integrity.

The 2,753-test result is the baseline. New source changes require a new matching release.

Do not modify already approved source after generating a signing mandate.

## PHASE 6 — PREPARE OCTOBER 17–18 AUTONOMOUS LONG TRADING

Once all mandatory real-exchange requirements are qualified, prepare a new exact executable session.

Proposed scope:

- Hyperliquid TESTNET `par`.
- Registered team wallet only.
- LONG only.
- Existing frozen strategy.
- One concurrent position.
- Up to two independent entry attempts initially.
- 1x CROSS leverage.
- Existing 1% carried session-loss threshold.
- Proposed bankroll 20,000 TEST USDPR.
- Adaptive actual position notional based on genuine liquidity and risk.
- Verified protective exits.
- Authorized profit-taking and loss-making risk exits.
- Explicit cross-midnight October 17–18 expiration.
- No automatic authorization renewal.

The 20,000 TEST USDPR bankroll is only a proposed allocation.

The 1,000–10,000 TEST USDPR position-size targets remain conditional on current market liquidity and approved risk.

Do not force larger orders through insufficient depth.

Present the complete exact mandate for genuine human approval.

## PHASE 7 — ACTIVATE THE STANDALONE VS CODE TRADING ENGINE

After qualification and acceptance:

Run the actual execution-enabled standalone Python worker, not an observation-only process.

Confirm:

- Correct registered wallet.
- Current valid approval.
- Correct signing host.
- Verified source identity.
- Healthy WebSocket market and account streams.
- Fresh market evidence.
- No unresolved order.
- Exact risk limits.
- Verified protection.
- Approved position-size allocation.

Required lifecycle:

`SCAN → LONG SIGNAL → BUY → VERIFY FILL → PROTECT → MANAGE → SELL → VERIFY CLOSE → RECORD P&L → SCAN AGAIN`

Use the existing deterministic Python strategy.

Do not require continuous Codex credits.

Do not fabricate strategy signals to force a test.

The worker may run its observer until manually stopped, but new trading actions must remain within the exact approved session duration and other limits.

## PHASE 8 — ACTUAL TRADING AND MORNING REPORT

When trading becomes eligible:

- Execute only legitimate qualifying LONG entries.
- Manage losses as well as profits.
- Verify native protection.
- Close through authorized reduce-only orders.
- Reconcile every actual exchange fill.
- Record trading fees and funding.
- Update realized net P&L.
- Verify no residual exposure before the next trade.

At session completion, report:

- Genuine entry and exit order IDs.
- Actual quantities and prices.
- Completed trade count.
- Winning and losing trades.
- Total net realized P&L.
- Maximum drawdown.
- Remaining positions.
- Open orders.
- Protection status.
- Trading-session and worker status.
- Outstanding recovery requirements.

Do not present simulated P&L as genuine exchange profit.

## EXECUTION PRIORITY

**First:** Resolve the latest UNKNOWN intent.

**Second:** Validate the repaired five-second signing boundary.

**Third:** Establish native-stop and subminimum residual behavior.

**Fourth:** Complete genuine supervised qualification.

**Fifth:** Obtain a new source-matched passing release.

**Sixth:** Prepare and request exact autonomous LONG authorization.

**Seventh:** Launch the standalone trading engine after approval.

**Eighth:** Verify actual BUY/SELL fills and P&L.

Do not repeat expired trading proposals or attempt new signing while the UNKNOWN record is unresolved.

Do not weaken valid exchange safety controls simply because only two practice days remain.

## REQUIRED RESPONSE

Give me a practical report answering:

A. Is the new UNKNOWN entry formally resolved?

B. Was the signing-data freshness problem fixed and verified?

C. Is native Stop Limit protection genuinely qualified?

D. Can subminimum residual positions be protected and closed?

E. Is a fresh genuine qualification permitted?

F. What is the maximum executable LONG size under current market conditions?

G. Did the complete regression pass?

H. Is a fresh autonomous session eligible for exact approval?

I. What exact VS Code Terminal command launches the actual trading worker?

J. What genuine orders and P&L have occurred?

K. If trading is still blocked, identify the exact remaining external dependency rather than requesting unrelated development.

**START WITH THE UNKNOWN ORDER REVIEW. Preserve all evidence. Resolve the remaining exchange prerequisites and prepare Team Anchorium for authorized autonomous trading as quickly as real evidence permits.**