# Team Anchorium — October 15 qualification preparation

Prepared 2026-10-15T10:13:54.606728+05:30. No new session has been accepted and no exchange order has been submitted in this task.

## 1. Session and authorization

New session ID: `66b034a017f6b460631bba11def79c9d61c50ff7c81d88c251086555e97d4049`.

Source: `2806a21a449f5d18e1a0ce6cf76f194c31604ca647ac6d6db5fb7fa4b43675e7`. Recovery certificate: `a6ea851efdd3c0e90b26b55587bdb60e3ba8449b782d1e39a94a01743acdd058`.

The October 14 session `6b8c95884fbf5fa22cddee4e18289121e4ee5c9b77c39e1de4d6875116217c52` is expired and is not reused. The earlier accepted/finished session is also not reused. Today's mandate requires new explicit acceptance of its exact hash and all nine acknowledgments. The acceptance file has not been created.

Scope: Hyperliquid TESTNET, DEX par, par:BTC only, BUY IOC exactly 0.0002 BTC, 1x CROSS. Opening exposure at most **20 TEST USDPR**; BUY price at most **100,000 USDPR/BTC**. No automatic size/cap enlargement. Exactly one entry attempt, up to two exact actual-position reduce-only SELL IOC exits, at most one original-entry cancellation and four signed actions total. A zero-fill, transmitted or uncertain entry is not automatically replaced.

The watcher selects fresh ask plus 10 bps, normalizes down and caps at the fresh reviewed envelope and session ceilings. The immutable order must still be executable and within the current 20-bps tolerance. Exits use fresh bid minus 20 bps, normalized correctly, never below reviewed bid × 0.98505 normalized up. Each generated envelope expires after five minutes, with 90 seconds reserved for management. Session ends **23:59 IST on October 15**; latest entry **23:57:30 IST**. Revocation, a consumed attempt, an unresolved position or a safety failure can stop it earlier. No writes automatically resume after a crash.

## 2. Regression and minimal implementation change

**2,248 passed; zero failures, errors or skips.** Previous baseline 2,244 plus four renewal/reuse/expiry cases. The source hash before/after testing matches the mandate. XML digest and receipt were verified. Strategy freeze and Phase-0 passed before and after.

Only three production date constants changed in `algo-trading-bot/exchange/delegated_qualification.py`: window start, window end and displayed scope end now pin October 15. `algo-trading-bot/test_delegated_qualification.py` updates the calendar assertion and adds four tests rejecting yesterday's creation time, an extended expiry, tomorrow's scope and the actual saved October 14 mandate. No strategy, safety limit, execution mechanism, wallet setting or architecture changed. `signal_brain.py` and frozen VWAP/EMA/ATR/state behavior remain intact, as do 0.40% ATR, production 15-bps spread, 300 bars and Top-3. Production remains PAPER/false; protection remains disabled.

Receipt: `regression_release/test_receipt.json`; full XML/log alongside it. Source-before copies and exact diffs are preserved in this directory. Historical October 14 source references in the recovery verifier remain unchanged because they authenticate the original failed attempt.

## 3. Fresh account, signer and watcher status

Account evidence at 2026-10-15T10:12:23.185000+05:30: registered team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`, approved API signer `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`, unifiedAccount, 1,000,000 TEST USDPR collateral, 1x CROSS on BTC, sufficient availableToTrade, zero positions and zero open orders. Reconciliation, clock and API-budget checks passed. Account data is read from the registered team account; the SDK uses that address as account_address and the separate approved API signer. These are timestamped observations, not claims that a cached snapshot remains current until execution.

The actual local key derives to the approved API address. Local exclusive nonce ownership passed and a second local process was rejected. No nonce was allocated and no signature created. This cannot inspect other computers; continued sole-host use is one of the human acknowledgments. The execution watcher will acquire/hold the existing nonce lease and recheck source, account state, authority, market data and five-second freshness.

Today's two complete exchange-history observations again found no fills, orders or positions and unknownOid for the old cloid. The original UNKNOWN row, every earlier event, immutable nontransmission certificate and nonce rows are unchanged from today's SQLite backups. One raw historical intent remains, with zero actionable intents. The new read-only assessment does not replace the old certificate. See `account_recovery_audit.json` and `read_only_recovery_review/recovery_report.json`.

The existing persistent watcher is **prepared, not started**. It starts only after new exact session acceptance. Ordinary unarmed market ineligibility may continue read-only; armed, signed, consumed or uncertain attempts halt further entries under the existing tested rules. No recurring task was created.

## 4. Current example and exchange HTTP status

Example snapshot 2026-10-15T10:12:24.306000+05:30: bid 81357.0, ask 81507.0, mark 81507.0, oracle 81546.0; spread 18.4203 bps. Valid two-sided liquidity and depth checks passed.

Example BUY cap 81670, quantity 0.0002, notional ceiling **16.3340 TEST USDPR**, exit floor 80141. Reviewed taker fee 0.00090 = 0.09%; estimated round-trip fees at the reviewed limits/floor 0.029125980 TEST USDPR. Conditional loss if completely closed at the floor 0.334925980 TEST USDPR. These are estimates, not guarantees. The snapshot is not a permanently executable fixed order; the accepted session algorithm creates a fresh bounded envelope before the one attempt.

The underlying generic envelope retains legacy outer-cap fields; those are not extra authority. The delegated proposal and final signing validators enforce the stricter 20 TEST USDPR, 0.0002 BTC and 100,000 price limits.

**Entry reached HTTP: NO.** No new authorization, nonce allocation, signature or order submission occurred during preparation.

## 5. Exchange acceptance/rejection

**NOT SUBMITTED.** There is no new exchange acceptance or rejection to report.

## 6. Actual filled quantity

**0 submitted/verified in this task.** No genuine qualification fill has been obtained. Market-book estimates and offline fixtures are not exchange fills.

## 7. Actual entry and exit IDs

None. No `WHITELIST_TRADE_PROOF.json` is created without genuine registered-team-account fills. The old local cloid is historical recovery evidence, not a fill ID.

## 8. Remaining position and emergency recovery

The account was observed flat with no open orders at the timestamp above. No new exposure has been created in this task. Flatness must be rechecked during execution/recovery; a local status alone is insufficient.

**No verified protective stop will be submitted. Exposure may remain unprotected.** Narrow historical exact-full-position IOC closing evidence includes a 0.0001 BTC residual, but it does not guarantee future acceptance, liquidity, execution or complete closure. Reduce-only exits may reject, partially fill or become uncertain. Manual recovery may be required. The 20 TEST USDPR opening cap is not a guaranteed maximum loss; cross collateral, fees and funding remain relevant.

Recovery: stop entries; query original cloid/oid orderStatus, actual team fills covering the complete attempt, frontendOpenOrders and clearinghouseState with dex=par. Never blindly retransmit. Confirm any original remainder is terminal or authorized cancellation has completed before closing. Within an unexpired mandate only, attempt at most two SELL reduce-only IOC closes for exactly the reconciled actual long quantity, at fresh bid minus 20 bps above the approved floor. Never enlarge exposure to satisfy minimums. If limits/expiry/uncertainty prevent safe authorized closure, halt with EMERGENCY_EXIT_REQUIRED and disclose the exact known exposure; obtain separate exact recovery authorization or inspect/close manually. Claim flat only when exchange positions/orders and durable reconciliation agree.

## 9. Verified realized P&L

**Not available.** There are no actual entry/closing fills. Estimated fees/loss are not realized results. Following an approved attempt, actual fees, fills and funding must support any net P&L claim.

## 10. Organizer whitelisting and next action

**Organizer whitelisting is not confirmed.** A practice fill has not yet been verified. A later genuine fill would provide evidence to the organizer, not automatically prove whitelisting. Protected controlled execution, general practice readiness and live readiness remain false.

Single next action: the human accepts today's exact session hash and all nine acknowledgments. Codex then records genuine current acceptance and operates the existing bounded workflow without price-by-price confirmations inside that scope. There is no authorization to activate general autonomous trading.

### Required nine acknowledgments

1. Both wallet identities are manually verified.
2. This Mac remains the sole host signing with the API key.
3. The complete fixed session scope above is accepted.
4. One entry only, with no retry, replacement or enlargement after an attempted/uncertain entry.
5. Protective stops are unverified, none will be submitted, and exposure is unprotected.
6. Rejected/partial/uncertain exits may leave exposure needing separate or manual recovery.
7. The opening cap is not a guaranteed loss limit; fees, funding and cross collateral matter.
8. Qualification-only spread 50 bps, 50% genuine L2 participation and 20-bps price allowances are accepted; production's 15-bps rule and other protections remain.
9. Automatic bounded entry/exit pricing within this session is accepted without price-by-price approval.
