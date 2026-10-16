# Team Anchorium — BTC exit safety report

Engineering work completed. **No order was placed. The BTC residual-close code is tested; actual small-position stop protection is still unverified.** The protected qualification gate remains closed.

## 1. What this work covers

This is a focused execution-infrastructure change. It preserves the existing qualification policy, risk limits and frozen VWAP strategy. It introduces no strategy, server deployment, repeat trading, account administration or schedule. It creates no new trade proposal or approval. `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` remain enforced, and global protection remains disabled.

The previous full-suite baseline was 1,984 tests. It included the earlier emergency qualification changes; the older 1,633/1,893 baselines are not the current starting point.

## 2. A 0.0002 BTC entry and a 0.0001 BTC residual, in simple terms

BTC metadata currently has a 0.0001 BTC size step, so 0.0002 BTC is two lots. An entry can fill one lot and leave the other unfilled. A close of two lots can also fill one lot and leave one lot held.

The bot must use the actual exchange position. It does not infer the position from its entry request or a response summary. The existing workflow first settles the original entry, verifies its fills, and, for a resting partial entry, confirms cancellation of the remaining entry before closing. The new exit barrier also prevents an IOC close while another order or cancellation is unresolved.

| Actual position read from the exchange | Exact exit request | Treatment |
|---|---|---|
| +0.0002 BTC | SELL 0.0002 BTC, reduce-only IOC | Ordinary $10 minimum if the reviewed exit price is at least 50,000 |
| +0.0001 BTC | SELL 0.0001 BTC, reduce-only IOC | Only the existing narrow historical BTC full-position-close scope |
| Position changes before signing | No order | Reconcile again; never send the previous size |
| First close leaves +0.0001 BTC | Second exit requests exactly 0.0001 BTC | At most the existing two bounded exit attempts |
| Price falls below the approved exit floor, account reads fail, or attempts end with exposure | Halt new entries and report the residual | A new explicit recovery decision may be needed |

The system never buys more BTC to reach an order minimum, rounds away a residual, or submits an oversized close hoping the exchange will clamp it. A repeated call to an existing intent returns its durable outcome without re-signing it.

An offline BTC test exercises: BUY 0.0002 → partial SELL 0.0001 → actual remaining position 0.0001 → exact reduce-only SELL 0.0001 → exchange-fixture position zero. Another exercises a native stop's partial execution and the same residual close. These are synthetic test records, not Team Anchorium trades.

## 3. What the historical closing evidence actually proves

The unchanged independent readback contains `par:BTC` order **62228843959**, asset scope 2670000, SELL 0.0001 BTC, reduce-only IOC. Its order limit was 82,075, making the requested notional 8.20750 USDPR. The matching reported fill was 0.0001 BTC at 82,486, with reported starting position +0.0001 BTC. The resulting position derived from the reported start and fill is zero.

This was another public account's historical trade. It demonstrates that exact one-lot shape was accepted and filled. It does not establish a universal documented exemption, a guarantee of a future fill, a historical account-state snapshot, or any protective-stop capability. The evidence file hash remains unchanged: `c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764`.

The full-position IOC exception is not used for opening trades or trigger orders. Runtime symbol, asset ID, lot size, close direction, whole-position quantity, fresh reconciliation, price and authorization checks remain mandatory.

## 4. Verified documentation and its limits

Hyperliquid documents native trigger orders with `isMarket`, `triggerPx`, `tpsl` and reduce-only handling. It documents the ordinary $10 perpetual-order minimum. The pages reviewed do not explicitly establish a below-$10 fixed-size stop exemption on testnet `par`. [Exchange API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint), [error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses).

A stop uses the mark price to trigger. A stop-limit can become an ordinary resting order if the book moves through its limit; triggering does not guarantee execution. Fixed-size stops do not automatically resize with a changed position. The documentation also warns that cancellation of a partially filled parent order can cancel its attached TP/SL children, so this implementation does not assume an attached child protects that partial position. [Official TP/SL behavior](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl).

`open`, `triggered`, `filled`, rejection and cancellation are different exchange statuses. Order identity and actual reported fills must be checked separately. [Order status and fills](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint).

## 5. Issue found: disappearance was weaker than cancellation proof

The shared uncertain-order recovery previously set `remainder_cancelled` from absence in the current open-order list. A disappearing order may have triggered, have an execution child, or be in an unresolved state. A partial fill could therefore be treated as settled too early.

Recovery now requires a recognized terminal status plus absence of a live remainder. A partial fill with an unknown or triggered status stays UNKNOWN in the generic reconciler. Native triggered-stop children are resolved by the isolated stop reconciler. A reported filled status without actual matching fills is not accepted as a fill.

This change strengthens exchange plumbing; it does not alter a signal, stop distance, target or strategy state rule.

## 6. New isolated native-stop manager

`QualificationStopManager` is a fixed-size stop-limit lifecycle using the existing native SDK trigger submission, central validator, journal, nonce, account lock and exact-action authorization. It grants no signing authority and never submits an entry. The module is separate from production strategy logic.

- Plans an opposite-side reduce-only stop for exactly the currently observed held quantity.
- Uses explicit proposal stop prices; it calculates no strategy ATR or replacement VWAP stop.
- Preserves ordinary minimum validation. A one-lot BTC stop below $10 is rejected locally with `SMALL_STOP_VENUE_SUPPORT_UNVERIFIED`.
- Persists the source/proposal-bound attempt before dispatch. A lost response or restart cannot produce a second stop.
- Requires matching original CLOID/OID, asset/coin, side, original quantity, trigger and limit prices, reduce-only flag, frontend open-order row and independent order status.
- Records `coverage_observed` separately from `protection_verified`. The latter remains FALSE. Unit fixtures cannot promote it.
- Performs no automatic rearm, modification, size increase or replacement. A changed position makes the saved stop coverage stale.

The existing emergency proposal explicitly says no stop will be submitted. Its authorization still rejects trigger actions. Its one-entry/two-exit/one-cancel/four-signed-action limits and outer 1,000 USDPR cap are unchanged. The cap is not a target position or a guaranteed loss limit. The normal production spread ceiling remains 15 bps; the separate qualification ceiling remains 50 bps.

The new manager is exercised through existing certification authorization in offline fixtures. It is not installed as an active stop in the emergency launcher. Adding an actual stop to a future qualification requires a new exact proposal and reviewed action budget; an IOC entry + stop + cancellation + two possible exits would need five actions, exceeding the current emergency four-action cap. No such budget expansion is implemented or approved here.

## 7. Acceptance, triggering, partial execution and cancellation

| Observation | Manager behavior |
|---|---|
| SDK reports resting/accepted | Requires independent readback before observing coverage |
| Readback matches and actual position has the exact same size | READBACK_ACCEPTED; capability still unverified |
| Definite placement rejection, with no accepted OID, and consistent account reads | REJECTED; records residual and permits only separately authorized safe exit handling |
| Lost acknowledgment, unknown ID, mismatch or stale account snapshot | UNKNOWN; no duplicate stop or competing exit |
| Stop triggers but fills nothing | TRIGGERED_UNSETTLED; position remains exposed |
| Triggered child stays open after a partial fill | Tracks its remaining order size and actual position; blocks competing exit |
| All explicit children reach verified terminal states | Records actual matching fills and actual residual; never assumes the original stop quantity was filled |
| Parent is triggered with no documented child mapping | Remains unresolved unless complete matching fills and a flat account establish completion |
| Cancel acknowledgment arrives | Reads status and live orders again; success alone does not prove removal |
| Cancel is uncertain | Durable cancellation barrier; no second cancel or new close until read-only recovery resolves it |

Duplicate fill observations are counted once. Conflicting fills, excess filled quantity, wrong side, malformed or duplicate children, unrelated live orders and position growth all prevent acceptance. A residual after a terminal stop is not automatically protected again; if it is below $10, the protection limitation remains explicit.

## 8. Disconnect and restart recovery

A disconnect clears coverage confidence and saved settled-stop proof. The manager never assumes the stop vanished or the position became flat. REST can refresh the original order's status, child IDs, actual fills, frontend orders and current position. REST failure leaves UNKNOWN.

Restart ignores saved active coverage. It reuses the original durable identity and performs read-only reconciliation. If an uncertain cancellation belongs to this exact stop, its original management action is recovered from account evidence without a signature. An unrelated or unresolved management action remains a barrier. No restart automatically submits, replaces or closes an order.

The emergency route's existing one-entry consumption and restart lock remain intact. Actual positions and pending orders continue to occupy the global account lock.

## 9. Operator recovery instructions for a future authorized attempt

1. Stop new entries. Preserve the proposal/source hash, intent, CLOID, OID, nonce evidence and journal.
2. Read the original order status, real fills, frontend open orders and actual team-account position. Never treat `unknownOid` or a missing row as absence proof.
3. Resolve a remaining entry before planning a close. Resolve a triggered stop's children or cancel its exact live order under separately permitted limits before a competing close.
4. If an exact supported BTC residual remains and the existing authorization is valid, use the opposite-side reduce-only IOC for precisely that quantity at a fresh permitted price. Keep the approved floor and two-attempt bound.
5. If liquidity/price/authorization is inadequate, a close is rejected, or state is uncertain, halt and escalate the exact remaining exposure. Do not enlarge it or relax the floor.
6. Completion requires actual fill records, actual zero position and no unresolved or unexpected orders. P&L uses exchange-reported fees, fills and funding. There is no actual round-trip proof from this implementation work.

## 10. Files changed

- [algo-trading-bot/exchange/hyperliquid_execution.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/hyperliquid_execution.py>) — narrow infrastructure change.
- [algo-trading-bot/exchange/emergency_qualification.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/emergency_qualification.py>) — narrow infrastructure change.
- [algo-trading-bot/exchange/qualification_protection.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/qualification_protection.py>) — new.
- [algo-trading-bot/test_qualification_protection.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_qualification_protection.py>) — new.

Only the two listed existing infrastructure files changed relative to this task's source snapshot. All earlier dirty repository changes remain preserved. `signal_brain.py`, the freeze manifest, reliability/protection configuration and both existing qualification launcher/watcher scripts are byte-identical to their pre-task versions. The original NSE repository was untouched.

Documentation/evidence added under this report directory: source snapshot and patch, focused test XML/logs, full regression receipt/XML/log, read-only account/checkpoint evidence, this report, summary and artifact hashes. No new recurring task was created.

## 11. Tests and source verification

**2,046 passed; 0 failures, 0 errors, 0 skips.** This includes the entire 1,984-test baseline and 62 new tests. The full-suite source hash was identical before and after. Full regression duration: 528.76 seconds.

- strategy_freeze: PASS
- phase0: PASS

The freeze verification covers the brain file, eight frozen methods and 32 parameter comparisons. VWAP, EMA, ATR, long/short conditions, stop/target concepts, UTC input convention, 0.40% scanner ATR floor, 15 bps production spread limit, 300 completed bars and Top-3 were preserved.

The new tests cover actual BTC lot/asset SDK wire in an offline composition, partial entries, one-lot residuals, native stop rejection, uncertain acceptance, incorrect readbacks, triggering without execution, open/rejected/canceled execution children, partial stop fills, duplicate observations, cancel races, lost connections, unknown cancellation recovery, restart, damaged provenance, stale snapshots and entry/exit permission boundaries.

Development failures were fixed and preserved, not erased: the first focused run had 39 failures/100 passes while the new manager's durable hash/identity fields were being corrected; diagnostic runs caught fixture formatting/quantity issues. The later broader focused run passed 362 tests. The final native-stop set passed 62 tests. The full source-bound release above is the authoritative final result.

## 12. Fresh read-only team-account observation

Observed **2026-10-13T23:46:19.845000+05:30**. This is a timestamped observation, not a future execution approval or a lasting liquidity guarantee.

| Check | Observed result |
|---|---|
| Network / DEX | Hyperliquid TESTNET / `par` |
| Registered account | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`; locally derived public identity matched |
| Agent | Approved; reported expiry 1806859924898 ms |
| Account mode | unifiedAccount |
| Reported USDPR balance | 1000000.0 |
| BTC leverage | 1x CROSS; other nine settings were not reconfigured or rechecked in this BTC-focused observation |
| Actual positions / orders | 0 / 0 |
| Actual reported fills in reconciliation | 0; no team qualification fill demonstrated |
| Actual account reconciliation | Healthy |
| Local nonce/signer lease | Healthy; no nonce allocated, no signature created |
| Sole signing host | Prior human confirmation plus current local lease; cannot independently inspect remote machines |
| BTC bid / ask / mark / oracle | 83162.0 / 83195.0 / 83138.0 / 83129.0 |
| Observed spread | 3.9674 bps |
| Illustrative one-lot exit-bound notional | 8.1919 USDPR — below $10 |
| Illustrative two-lot exit-bound notional | 16.3838 USDPR |
| Clock | HEALTHY, offset -335 ms |

The illustration uses the existing exit-floor formula for reporting; it is not an approved native stop or trade proposal. Actual stop acceptance could not be demonstrated because no signed action was authorized. There were 36 public `/info` reads, zero exchange submissions and zero actual-wallet signatures. Two checkpoint checksums, SQLite integrity, source identities and clean shutdown were verified; intent, API-action and signed-management tables contain zero actions.

The first local account-report attempt failed before any HTTP call because its progress callback signature needed correction. That failed report is retained separately. The successful second run is clearly labeled `read_only_account_v2`; it is not mixed with the first attempt or previous trade proposals.

## 13. Source identity

- Full active source before this task: `ba40a55df453d4e2e5557bd60c52b3337a0d5b4dde2ae62d4169f54f6ff5dbca`.
- Full active source tested and observed: `90c913950d7c7f23bfa176612356e0995d9fef5976be54fc449695b8cc1bf882`.
- Brain SHA-256, unchanged: `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`.
- Core checkpoint source hash: `27623fd46e7bf36faa5389fc49430eb68bde310ce601fa71cae4a7634c7c8f8d`. This deliberately narrower checkpoint scope differs from the full regression hash, which includes scripts and tests.
- Frozen manifest and protection/reliability configuration hashes are unchanged. Historical close evidence is unchanged.
- Git commit `33c7cfe9ec241ccc0241144a8dccfd9a06df553a` is accompanied by the dirty source hashes; this report does not pretend the pre-existing dirty work is committed.

## 14. Final readiness and remaining limits

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
BTC_EXACT_RESIDUAL_CLOSE_CODE_READY = TRUE
BTC_HISTORICAL_ONE_LOT_IOC_CLOSE_EVIDENCE = TRUE
ISOLATED_NATIVE_STOP_LIFECYCLE_OFFLINE_TESTED = TRUE
ONE_LOT_PROTECTIVE_STOP_ACCEPTANCE_VERIFIED = FALSE
PROTECTION_PARTIAL_FILL_BEHAVIOR_VERIFIED = FALSE
PARTIAL_FILL_EXIT_READY = FALSE
ACTUAL_PROTECTION_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
ACTUAL_TEAM_QUALIFICATION_FILL_VERIFIED = FALSE
LONG_CERTIFIED = FALSE
FUNDED_RECOVERY_CERTIFIED = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
PROTECTION_ENABLED = FALSE
PRODUCTION_STRATEGY_CHANGED = FALSE
PRODUCTION_TRADING_ACTIVATED = FALSE
```

`BTC_EXACT_RESIDUAL_CLOSE_CODE_READY` is narrow engineering readiness under the existing verified IOC scope and approved price bounds. The older broader `PARTIAL_FILL_EXIT_READY` flag stays FALSE because a complete protected partial-fill path has not been validated at the exchange. Actual protection, controlled protected execution, funded recovery, practice readiness, a genuine team fill and organizer whitelisting remain separate unproven claims.

Remaining limits are substantive: small-stop support and trigger/partial/cancel behavior are unverified; no actual bounded execution was authorized; existing proposals are expired and source-invalidated; stop-limit execution is not guaranteed; exact IOC closure can fail if liquidity or the approved price bound is inadequate; unknown children/cancellation/schema/account history must halt execution.

**Next safe action:** obtain authoritative `par` clarification or genuine independently reviewable evidence for a 0.0001 BTC reduce-only stop's placement and lifecycle. Then review a fresh, separately bounded venue-validation proposal with an exact stop/action budget and human authorization. This implementation report authorizes no order and activates no trading.
