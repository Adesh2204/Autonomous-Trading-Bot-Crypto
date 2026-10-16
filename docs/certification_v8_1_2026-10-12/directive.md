# TEAM ANCHORIUM — MASTER DIRECTIVE V8.1
## October 12: First Actual Hyperliquid Testnet Trade & Realized P&L Certification

**Priority:** CRITICAL  
**Repository:** Autonomous Trading Bot - Crypto  
**Exchange:** Hyperliquid TESTNET  
**Required HIP-3 DEX:** `par`  
**Starting practice balance:** 1,000,000 test USDPR, subject to fresh account verification  
**Execution goal:** One safe, real, fully reconciled testnet round trip  
**Strategy:** FROZEN — DO NOT MODIFY

---

# 0. THE MISSION

You are the lead trading infrastructure engineer and execution-risk specialist for Team Anchorium.

The team has already implemented extensive PAPER infrastructure, but it has not demonstrated a funded exchange round trip.

Our new immediate objective is:

**Achieve the first genuine, independently verifiable Hyperliquid testnet realized P&L observation as soon as all execution safety gates pass.**

This must not be another theoretical P&L report.

The certification should establish:

1. Actual order submitted to Hyperliquid testnet.
2. Actual exchange acknowledgment.
3. Actual exchange fill verified.
4. Actual account position verified.
5. Actual exchange-side protective order verified.
6. Actual reduce-only closing fill verified.
7. Actual flat account independently verified.
8. Actual realized P&L, fees and funding recorded.

However, **never guarantee a fill, profit, loss or completion time**. Venue liquidity and safety requirements govern whether an actual trade may proceed.

## Critical distinction

The 1,000,000 USDPR is the available testnet account capital, NOT the required order size.

Do NOT trade the full account.

Do NOT attempt to generate exchange volume to satisfy a target.

Do NOT force trades through unsafe market conditions.

---

# 1. NEW EXECUTION MODES

Preserve existing PAPER mode.

Implement or verify three strictly separated modes:

### MODE A — PAPER

- No signed orders.
- Hypothetical fills/accounting.
- Native feed validation.
- Existing VWAP strategy testing.

### MODE B — TESTNET_CERTIFICATION

- Separate from strategy signal generation.
- Real Hyperliquid testnet orders.
- One strictly limited order sequence.
- Explicit human authorization for the exact test.
- No autonomous repeated entries.
- No strategy threshold bypass in production.

### MODE C — TESTNET_PRACTICE

- Actual funded testnet trading.
- Existing frozen VWAP strategy.
- Real fills and accounting.
- Enabled only after required execution, protection, account, feed and risk certifications pass.
- Requires separate explicit authorization.

Default mode remains PAPER.

An existing environment variable must NOT accidentally enable either funded mode.

---

# 2. ABSOLUTE STRATEGY FREEZE

DO NOT MODIFY:

`signal_brain.py`

Preserve:

- VWAP
- EMA9 / EMA21
- ATR calculation
- ATR floor 0.40%
- Spread limit 15 bps
- 300 completed candles
- Full UTC strategy history
- Top-3 scanner
- LONG/SHORT conditions
- Pullback/breakout/breakdown
- Stops and targets
- Bias and cooldown
- Risk and anti-spam logic
- One global position

The new certification mode is an infrastructure test and must never be treated as a VWAP strategy signal.

It may test execution without a 300-candle strategy signal, but it must independently require fresh tradable prices, account state, margin, liquidity and protection.

---

# 3. REPOSITORY INSPECTION — BEFORE CODING

First verify:

- Correct repository and Git branch
- No conflicting running bot
- Active PAPER owner and checkpoint state
- Actual Hyperliquid execution adapter
- Existing signer and API approval validation
- Current nonce management
- Actual position/order reconciliation
- Existing emergency protection implementation
- Actual-fill accounting
- Existing execution lockouts

Do not duplicate working components.

Do not modify running code while a live position exists.

Do not start scheduled Codex tasks.

Preserve previous evidence and source hashes.

---

# 4. MANDATORY ACCOUNT PREFLIGHT

Use read-only exchange queries first.

Verify:

**Network:** Hyperliquid Testnet  
**DEX:** `par`

**Expected team wallet:**

`0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`

**Expected approved API wallet:**

`0x46c9BED595770150752E7fA3806449F81E0Ec6f9`

Check:

1. Public team-wallet identity.
2. Actual test USDPR balance.
3. Available margin.
4. Unified-account status.
5. Approved API signer and expiry.
6. Signer derived address, without revealing the key.
7. Clock synchronization.
8. Persistent nonce ownership.
9. Existing open orders.
10. Existing positions.
11. Correct `par` market metadata.
12. Actual account-level rate budget.
13. 1x CROSS leverage.
14. Exchange fee assumptions.
15. Current maintenance-margin constraints.

If account state cannot be independently reconciled:

**NO ORDER.**

If an unexpected position or order exists:

**NO NEW ENTRY.**

Never assume yesterday's wallet verification is sufficient today.

---

# 5. IMPLEMENT TINY-ORDER CERTIFICATION

Prepare the first real testnet trade using a conservative liquid and currently executable `par:` market.

Candidate markets may include BTC, ETH or HYPE, but selection must be based on fresh venue evidence, not historical assumptions.

## Initial parameters

Proposed maximum order notional:

**25–50 USDPR**

Proposed leverage:

**1x**

Maximum concurrent positions:

**1**

Maximum certification entry attempts:

**1 approved attempt per test**

Proposed total certification session loss budget:

**10 test USDPR**

These are default proposed safety limits. Confirm venue minimums, market precision, liquidity, expected fees and permissible risk before finalizing.

If the market minimum or liquidity requirements cannot be satisfied safely within these limits, do not increase exposure automatically.

## Fresh market checks

Verify:

- Current best bid
- Current best ask
- Spread
- Order-book depth at intended size
- Mark/oracle prices
- Timestamp freshness
- Available margin
- Allowed lot-size precision
- Allowed price ticks
- Maximum acceptable slippage
- No abnormal oracle deviation
- No market halt or trading restriction

Use a bounded limit/IOC-style execution policy where supported and appropriate.

Do not submit an unbounded market order.

Do not route orders to mainnet or a native coin by accident.

---

# 6. REAL ORDER AUTHORIZATION GATE

Codex must STOP before the first actual order.

Display a final approval summary containing:

- Team wallet
- API wallet
- Network
- DEX
- Symbol
- Direction
- Order type
- Maximum notional
- Maximum entry price/slippage
- Maximum permitted loss
- Protection plan
- Exit plan
- Fee estimate
- Expected worst-case risks
- Order expiry/cancellation policy

Require explicit operator approval for this exact certification attempt.

A general request such as "start trading today" must not authorize unlimited trading or subsequent orders.

Authorization must expire after the approved test or a short fixed period.

Never store private signing keys in the report.

---

# 7. EXECUTION LIFECYCLE

After explicit approval and successful preflight:

### STEP 1 — Submit entry

- Generate unique persistent CLOID.
- Persist order intent before submission.
- Use the correct approved API signer.
- Submit exactly the authorized order.
- Inspect the individual exchange response.

Distinguish:

`REJECTED`

`RESTING`

`PARTIALLY_FILLED`

`FILLED`

`UNKNOWN`

Do not assume HTTP 200 means filled.

### STEP 2 — Verify the position

Reconcile using actual exchange information:

- Order status
- Fill records
- Filled size
- Actual average fill price
- Actual fees
- Actual position size
- Margin consumed

If order status is uncertain, query using the original CLOID/order identifier.

Do not blindly resubmit.

### STEP 3 — Protect the position

Before entry, validate that an appropriate protective-order mechanism is supported and correctly configured.

Where native attached protection is supported and demonstrably reliable, use it appropriately.

Otherwise, immediately after a confirmed fill:

- Submit the required exchange-side reduce-only protective stop.
- Confirm exchange acceptance.
- Verify correct protected quantity and direction.
- Verify actual trigger/limit settings.
- Reconcile the order state.

If protection is rejected or uncertain, initiate the pretested emergency reduce-only exit procedure.

Do not open another position.

If exit cannot be verified, halt and alert the operator urgently; never claim the account is flat without exchange proof.

### STEP 4 — Close the trade

Once the authorized test has served its purpose:

- Issue a bounded reduce-only exit.
- Verify the actual closing fill.
- Handle partial closes without reversing the position.
- Reconcile remaining position.
- Cancel obsolete protection orders as appropriate.
- Confirm position quantity is zero.
- Confirm no unwanted open orders remain.

Do not leave the position open just to wait for profit.

### STEP 5 — Verify realized P&L

Read actual exchange records.

Calculate and display:

`Entry notional`

`Actual entry price`

`Actual exit price`

`Actual filled quantity`

`Gross realized P&L`

`Actual entry fee`

`Actual exit fee`

`Funding, if any`

`Net realized P&L`

`Equity before`

`Equity after`

Use exchange-confirmed accounting rather than hypothetical signal prices.

Separate the exchange's closed-P&L field from net profit after fees/funding.

No invented fills.

No theoretical P&L presented as realized P&L.

---

# 8. SECOND TEST — SHORT CERTIFICATION

Only after the first LONG test is completely closed and reconciled:

Prepare an independent SHORT certification.

Do not automatically submit it.

Require a new approval and fresh preflight.

Verify:

- Correct bearish order direction
- Actual short fill
- Correct short-position size
- Reduce-only stop direction
- Actual protection acceptance
- Reduce-only exit
- Verified flat account
- Actual net realized P&L

If the LONG test revealed unresolved defects, block the SHORT certification.

---

# 9. EMERGENCY SAFETY AND FAILURE HANDLING

Mandatory test cases:

- Entry rejected
- Insufficient liquidity
- IOC partially filled
- Exchange request timeout
- Lost acknowledgment
- Duplicate CLOID
- Restart after fill
- WebSocket disconnect after entry
- REST temporarily unavailable
- Stop placement rejected
- Stop accepted but not triggered
- Exit partially filled
- Cancellation uncertain
- Position exists after restart
- Account reconciliation mismatch
- Fee mismatch
- Rate budget exhausted

Preserve one signer and one nonce owner.

No automatic retries that can create duplicate exposure.

A lost WebSocket connection must not cause an unnecessary blind order.

Do not rely on exchange scheduled-cancel functionality unless the account is actually eligible for it. Verify eligibility from the current venue rules.

No trading to artificially unlock API quotas or scheduled-cancel eligibility.

---

# 10. COMPETITION COMPLIANCE

All certification activity must be genuine and independent.

Forbidden:

- Wash trading
- Self-crossing
- Coordinated offsetting trades
- Artificial volume farming
- Trading at deliberately abnormal prices
- Manipulating thin books
- Transferring value to other teams
- Trading solely to exploit stale quotes

A single bounded infrastructure test must not become a high-frequency artificial-volume generator.

Keep full evidence of order intent and actual exchange outcomes.

---

# 11. EXISTING DATA-FEED PROBLEM

Do not ignore the V7 feed-readiness failure.

The real execution harness and the autonomous strategy must have separate readiness gates.

Certification harness:

Needs genuine fresh executable market data and verified account/risk state.

Autonomous VWAP strategy:

Additionally requires full, valid native or independently approved signal-data history, unchanged scanner filters and valid strategy signals.

Never mark the frozen strategy ready just because one manually authorized execution test succeeded.

Keep external data research isolated.

Do not enable external live signals automatically.

---

# 12. TESTING BEFORE REAL EXECUTION

Before asking the operator for actual-order authorization:

1. Run full existing regression.
2. Verify strategy freeze.
3. Test order serialization.
4. Test nonce and CLOID handling.
5. Test precision and min-notional rules.
6. Test partial fills.
7. Test stop placement and rejection.
8. Test reduce-only exits.
9. Test real-account reconciliation interfaces.
10. Test duplicate prevention.
11. Test restart recovery.
12. Verify production order lock remains active outside the specifically authorized certification path.

Previous baseline:

**1,405 passing tests.**

Record the new count and any failures.

Do not hide test failures.

---

# 13. THE REQUIRED FIRST-TRADE REPORT

After an actual authorized order sequence, generate:

## A. Execution status

`NO_ORDER_AUTHORIZED`

`PREFLIGHT_BLOCKED`

`ORDER_REJECTED`

`ORDER_RESTING`

`PARTIAL_FILL`

`OPEN_PROTECTED_POSITION`

`EMERGENCY_EXIT_REQUIRED`

`TRADE_CLOSED_RECONCILED`

or an equally explicit truthful status.

## B. Actual exchange proof

Include:

- Time
- Symbol
- CLOID
- Order IDs
- Entry and exit fill IDs
- Entry/exit sizes
- Fees
- Protection order evidence
- Exchange position snapshots

No keys or signatures.

## C. Realized P&L

Show net gain/loss in actual test USDPR.

If there was no completed closing fill, say:

`REALIZED_PNL_NOT_CERTIFIED`

Do not invent a number.

## D. Safety proof

Verify:

- Correct account
- Correct DEX
- Approved signer
- 1x leverage policy
- One position maximum
- No duplicate orders
- No unexpected exposure
- No unresolved protection
- Final flat account, if applicable

## E. Source and tests

Show:

- Files changed
- Source hashes
- Full regression result
- Strategy-freeze result
- Actual exchange test result

## F. Next action

Return only the next safe step.

---

# 14. SUCCESS CRITERIA

The immediate certification succeeds only after:

1. An authorized genuine testnet order is filled.
2. The account reflects the actual position.
3. Protection is confirmed or the position is safely closed under the tested contingency.
4. A genuine closing fill occurs.
5. Fees and net realized P&L are computed from exchange records.
6. The account is flat and reconciled.
7. There is no unwanted open exposure.
8. Evidence is saved.

If the venue cannot execute safely, report the exact blocker.

**Do not manufacture trades to satisfy this directive.**

---

# 15. FINAL COMMAND

Begin now with:

**Repository inspection → fresh read-only account preflight → isolated certification implementation → offline testing → human approval gate.**

Stop for explicit authorization before the first signed entry order.

Once authorized, run only the approved bounded sequence, record genuine outcomes, and stop.

Do not activate full autonomous testnet practice automatically.

Do not deploy the full 1,000,000 USDPR.

**Our objective is the first safe, real, fully reconciled testnet trading result—not maximum exposure.**

# END DIRECTIVE
