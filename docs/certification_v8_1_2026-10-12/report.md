# Team Anchorium — V8.1 certification preparation report

## A. Execution status

**The execution-test infrastructure is prepared and tested. The first real trade is blocked by a verified local partial-fill problem.** No real order was submitted, and there is no actual realized P&L to certify.

```ini
AUTHORIZATION_STATUS = NO_ORDER_AUTHORIZED
EXECUTION_STATUS = PREFLIGHT_BLOCKED
REALIZED_PNL_STATUS = REALIZED_PNL_NOT_CERTIFIED
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
GLOBAL_PROTECTION_ENABLED = false
```

In easy language: asking the exchange to buy about 25 USDPR does not mean it will fill the entire amount. It might fill only a small part. Our existing adapter refuses every order below $10, including protection and closing orders. An offline test left a small position that the adapter could not close. Real entry is now blocked before a key is loaded in assembly and again at the certification signing boundary.

This is a demonstrated limitation of our code. It is **not proof that Hyperliquid itself rejects every small reduce-only close**. The published guide does not establish the exception we need to assume. Increasing the entry size cannot eliminate the possibility of a one-lot partial fill.

The normal VWAP bot remains frozen. A certification trade is a manually approved plumbing test, excluded from strategy performance statistics. This work does not establish profitability or autonomous practice readiness.

## B. Actual exchange proof and proposed test

These are genuine **read-only observations**, not proof of an executed trade.

| Account check | Observed result |
|---|---|
| Network / DEX | Hyperliquid Testnet / `par` |
| Team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| USDPR | 1,000,000; this is account capital, not proposed order size |
| Account mode | `unifiedAccount` |
| API approval | Present; valid expiry observed |
| Leverage | All ten `par:` markets read back as 1x CROSS; no setting was changed |
| Sampled positions / open orders | 0 / 0, including trigger-aware order checks |
| Local signer identity | Derived address matches; no actual-wallet signature created |
| Nonce ownership | Existing durable store reused; second local owner rejected; zero nonce allocations |
| Clock / rate budget | Healthy at saved observations; fresh checks required again for future execution |

Initial ten-market account snapshot: 2026-10-12T06:33:34.626376+00:00. Latest candidate observations: 12 October 2026, 12:37:41 IST. The latest signer ownership observation is recorded in `signer_preflight_release.json`; ownership is only verified on this host and OS user, not on another server. Future approval must confirm a sole signer host.

| Final-source market snapshot | Book age at decision | Spread | One-lot value at mark | Result |
|---|---:|---:|---:|---|
| par:BTC | 614 ms | 0.238 bps | 8.395800 USDPR | CERTIFICATION_LIQUIDITY_MARGIN_MINIMUM_REQUIRED |
| par:ETH | 509 ms | 6.621 bps | 0.256830 USDPR | SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED |
| par:HYPE | 658 ms | 7.853 bps | 0.878300 USDPR | SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED |

BTC also failed the current liquidity/size admission. The other two candidates passed the ordinary price/account/minimum checks, but their small-partial exit path failed. No market was selected for actual execution. Full quote, collateral-capacity arrays, current fees, runtime lot precision, metadata, margin tiers and central-validation results are retained in `market_preflight_refreshed/preflight.json`.

The earlier final check retained a 5,238 ms-old BTC book after serial account queries. The isolated certification provider now refreshes the book and references at the end, while retaining the genuine account observation time. All final-source books were under one second old at their decisions; the five-second rule was not relaxed.

Mark/oracle timestamps in this path identify local receipt of the REST context. Their upstream publication/update timestamps are not supplied. Book timestamps come from the exchange. These snapshots are not a continuous WebSocket or 300-candle strategy-feed certification.

### Approval summary — draft only, not executable

No active approval file exists. V8.1 §6 requires a new exact operator approval after the blocking safety gate is resolved. An old proposal or an environment flag cannot activate the test.

| Proposed test limit | Policy |
|---|---|
| Direction | One LONG first; SHORT requires a separately approved test after reconciled LONG completion |
| Entry | One bounded limit IOC; one approved entry attempt |
| Exposure | At most 25 USDPR notional; one global `par` position; 1x CROSS |
| Entry price | Exact reviewed limit; at most 5 bps beyond the observed executable side |
| Loss budget | Proposed 10 test USDPR operational budget; not a guaranteed maximum loss |
| Protection | Reduce-only stop-limit, 1% below observed bid for LONG, then 0.5% farther limit allowance; test-only proposal |
| Exit | Immediate bounded reduce-only IOC after the test purpose; at most two exit attempts with fresh position reads |
| Exit slippage | At most 20 bps from a fresh executable side and within the approved absolute bound |
| Total actions | At most six; only this attempt’s owned entry, stop, exits and cleanup cancellations |
| Time limit | Exact human permit at most five minutes; completed/consumed permits cannot be reused |
| Fee estimate | Twice current `userCrossRate` for venue scale 1; final snapshots estimated 0.09% taker per fill |
| Scheduled cancel | Not used or relied upon; the guide’s volume eligibility is separate from a 1,000,000 balance |

A future review must display a fresh symbol, quantity, fixed prices, fee estimate, stop/exit details and both wallet identities. The proposed stop is not an ATR or VWAP strategy stop. Global production protection remains disabled. Stop-limit acceptance and filling are not yet demonstrated on this funded account.

Expected risks: partial/no fills, acknowledgment loss, a stop-limit not filling through a gap, connectivity or venue failure, a close requiring a new operator decision after expiry, and unresolved exposure. The proposed loss budget is not an exchange guarantee. No order is left open just to wait for profit.

## C. Realized P&L

| Required genuine trade evidence | Result |
|---|---|
| Entry / exit CLOIDs and order IDs | None — no certification order submitted |
| Entry / exit fill IDs and filled quantity | None |
| Actual entry / exit prices and notional | Not applicable |
| Exchange closed P&L / actual fees / actual funding | Not certified for a round trip |
| Net realized P&L | **Not certified; no number is invented** |
| Before/after trade equity | No completed actual trade comparison exists |
| Exchange-side protection acceptance | Not tested on the actual account |

The 1,000,000 USDPR read is wallet collateral evidence. It is not proof of a zero-profit trade. Offline fixtures use simulated exchange records and ephemeral signing accounts; their P&L is not this wallet’s P&L.

After an authorized real round trip, the harness requires actual `userFills` and `userFunding`, matches fill IDs and sizes, compares fill-price arithmetic with exchange closed P&L, subtracts actual fees, adds actual funding cashflow and reconciles flat-wallet equity. A response marked filled without matching account fills is rejected as incomplete evidence.

## D. Safety proof and remaining gates

The original NSE repository was not touched. The clone remains on `perpetual-alpha-migration`. All checked runtime owner locks were free; the pre-existing Python processes belonged to another project. No collector, duplicate bot, server deployment, scheduled task or autonomous testnet session was launched.

The official SDK is reused. The certification transport requires exact central action permits, a durable account journal, one account lease, the existing API nonce store and a signature-bound expiry. It disallows administration, transfers, leverage changes, native/mainnet routing, batches and another entry. Duplicate/uncertain attempts remain consumed; they do not trigger blind resubmission.

The account bridge reuses actual-fill/account-event reconciliation and crash-safe checkpoints. It does not copy the PAPER ledger or restore VWAP strategy state into a manual test. Unknown protection can coexist with verified account truth for a safe reduce-only contingency, but unresolved order/cancellation state blocks final certification. Restart refuses new entry and requires read-only recovery/operator review. Actual funded restart recovery remains uncertified.

All frozen strategy formulas, state behavior, ATR 0.40%, spread 15 bps, 300 completed candles, full UTC history and Top-3 remain unchanged. The V7 strategy-feed failure was not erased or promoted by fresh BBO observations. External research remains isolated.

Remaining activation blockers: verified sub-$10 full-close/protection handling; exact human approval with current wallet/host review; and a new source-bound, fresh execution preflight after any future correction. Actual fill, protection, LONG/SHORT and funded recovery certifications do not yet exist.

## E. Source, implementation and tests

Final full regression: **1457 passed, 0 failures, 0 errors, 0 skipped**. The prior baseline had 1,405; this change adds 52 tests. Strategy freeze and Phase-0/order lock checks passed. The XML checksum and before/after source identity match.

| File | Purpose |
|---|---|
| [exchange/testnet_certification.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/testnet_certification.py>) | Proposal/approval envelope, one-attempt durable scope, scoped transport, fixed test protection, bounded sequence, actual-event P&L checks and small-partial entry block |
| [exchange/certification_runtime.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/certification_runtime.py>) | Existing reconciliation/checkpoint reuse, isolated final price refresh and explicit assembly |
| [scripts/run_testnet_certification.py](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/run_testnet_certification.py>) | Read-only proposal default; exact approved certification branch; autonomous practice refused |
| [test_testnet_certification_v8.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_testnet_certification_v8.py>) | 52 offline cases; actual exchange HTTP prohibited; ephemeral SDK signing only |
| [exchange/sdk_transport.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/sdk_transport.py>) | Optional signed action expiry; existing default remains unchanged |
| [exchange/position_protection.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/position_protection.py>) | Explicit market/limit option in a protection plan; old default preserved |
| [exchange/hyperliquid_execution.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/hyperliquid_execution.py>) | Serializes the plan’s stop type; allows owned cleanup to use safety priority while preserving signing/account gates |

Covered cases include serialization, nonce/CLOID uniqueness, duplicate attempts, precision/minimums, stale prices, spread/depth/margin restrictions, entry rejection, small/ordinary partial fills, lost entry acknowledgment, disconnect after fill, REST unavailability, rejected/uncertain protection, accepted but untriggered stop cleanup, partial exits, uncertain cancellation, startup with exposure, source/config changes, approval expiry, fee/P&L mismatch and exhausted account budget. Existing account/clock/nonce/restart lockout tests also ran in the full suite.

Earlier failed development runs were retained: first fixture setup errors; three issues in the second attempt; and one SHORT fixture setup failure before the latest successful runs. Intermediate passing suites and the prior 1,456-test full regression are also retained. The final result is not presented as if development had no failures. See `test_attempts.json`, the targeted logs and both full regression receipts.

```text
Source before V8.1: 36324cd3891eb931801ddc2ac9d47cf1e9c47cfbbd6a5a6f9aaddbc410a52685
Final tested source: 625329ffb8d2eb2a337fd30ec3eb75abe9137d92f1f20c294784b2a6f8725aa0
Regression XML SHA256: adbe85e9c7736997d5df43cf2c85a3f107d8610953862131a1ca551e75b95839
Frozen signal_brain.py SHA256: bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83
```

Full file/config hashes are in `source_manifest.json`; the seven changed/new file hashes are in `modified_files.json`; `v8_changes.patch` and `source_before/` preserve the narrow changes. No key or signature is stored in this report.

The generated legacy-dependency CSV/JSON inventory was also refreshed, with the previous reports preserved in `legacy_inventory_before/`. It records 1103096 matched occurrences across 423 files, classified as REMOVE, REPLACE or KEEP AS LEGACY REFERENCE. These are inventory matches, not active exchange calls. The new report hashes are retained in `final_summary.json`.

```ini
EXECUTION_INFRASTRUCTURE_OFFLINE_TESTED = TRUE
PARTIAL_FILL_EXIT_READY = FALSE
CONTROLLED_EXECUTION_CERTIFIED = FALSE
ACTUAL_PROTECTION_CERTIFIED = FALSE
LONG_CERTIFIED = FALSE
SHORT_CERTIFIED = FALSE
FUNDED_RECOVERY_CERTIFIED = FALSE
STRATEGY_FEED_RECERTIFIED = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
```

Official rules used: [participant guide](https://perpetual-alpha26.github.io/docs/) for venue/minimums/fees/IOC; [TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) for stop-limit versus market-stop behavior; and [exchange API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) for signed expiry and actions. Provider documentation supports mechanisms, not successful funded-account acceptance.

## F. Next safe action

**Obtain authoritative confirmation of the safe full-position reduce-only closing and protection rules below $10 on `par`.** The question is prepared in [the unsent draft](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_1_2026-10-12/organizer_small_position_question_draft.md>). No message was sent.
