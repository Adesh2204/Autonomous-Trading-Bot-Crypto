# Team Anchorium — V8.3 execution safety investigation

**Verdict: investigation complete; first actual trade remains blocked.** No signed order, actual-wallet signature, cancellation, transfer, leverage change or autonomous activation occurred in this task. PAPER mode and the order lock remain enforced. We did not choose an executable trade because none of the three allowed approaches is supported by the current evidence.

## 1. Verified root cause

The existing code rejects a sub-$10 exact full-position reduce-only close before it reaches Hyperliquid. Both generic normalization and central exchange validation retain that minimum. The exact-residual and protection helpers refuse to enlarge the real position or silently discard dust. This behavior is demonstrated offline and the execution code remains unchanged.

An entry worth more than $10 is insufficient: it can partly fill. An exit can also leave a small remainder. The safety gate therefore reviews **one runtime lot**, not simply the whole requested order. A possible remainder below the minimum needs a verified closing and protection mechanism before entry can be allowed.

The precise missing fact is server acceptance of an exact full-position close and protective stop below the minimum on **testnet par**. We did not establish these exemptions in the authoritative documentation inspected. This is an evidence gap, not proof that every such server request must fail. Details and primary references are in [venue_behavior.md](venue_behavior.md) and [root_cause.md](root_cause.md).

## 2. Chosen safe solution

| Allowed approach | Result |
| --- | --- |
| A: verified subminimum full-position close | Not established; protection treatment also unknown. |
| B: liquid one lot above $10 at entry and reviewed exit bounds | No eligible market among all ten. |
| C: another documented equivalent safe mechanism | No equivalent guarantee established. Ordinary SDK market-close, dynamic TP/SL and batch requests do not prove it. |

The implemented safe action is **retain the certification entry block** and make its all-market reasons reproducible. No minimum exception, oversized reduce-only order, top-up, abnormal order price or exposure increase has been introduced. Existing exact sizing, opposite direction, actual-fill protection, two bounded exits, duplicate prevention, durable uncertainty and operator escalation remain regression-tested infrastructure, not certified actual exchange behavior.

## 3. Source files added

- `algo-trading-bot/exchange/certification_market_review.py`
- `algo-trading-bot/test_certification_market_review_v8_3.py`
- `scripts/inspect_certification_markets.py`

The exchange module reviews one genuine runtime lot at current executable quotes and conservative test exit bounds. The launcher retrieves all ten official market specifications, books, mark/oracle/funding and side-specific account capacity through read-only `/info`. It preserves unavailable prices as unavailable and records independent minimum, liquidity, price and capacity blockers. Its output cannot deserialize as an executable proposal or grant an SDK permit.

Every one of the **212 existing V8.2 source/configuration files is byte-identical**. `signal_brain.py` and all manifest-frozen methods/state rules remain unchanged. The existing certification execution allowlist and transport are unchanged because no newly eligible safe market was found. Evidence/report files were added under this directory; the original NSE repository was untouched.

## 4. Tests and integrity

- **1,522 passed; 0 failures; 0 errors; 0 skipped.** This includes all 1,487 baseline tests plus 35 new tests.
- Focused final run: **117 passed** (V8.1, V8.2 and new V8.3 tests). The first focused attempt had one new test-fixture setup error; corrected fixture and original failed XML are preserved in `test_attempts.json` and `targeted_initial.xml`.
- Phase-0 permanent Angel/exchange lockout checks: PASS. Frozen strategy verification before and after regression: PASS (1 full file, 8 methods, 32 parameters).
- VWAP, EMA, ATR, 0.40% volatility floor, 15 bps spread ceiling, 300 completed UTC bars and Top-3 are unchanged. This read-only test review does not run or certify the strategy feed.
- Reviewed source hash: `f031a8cd481f421179e653581dc05038de66d6ca3223ca2c67712a79e0adafe2`. Before/after regression and final public review source identities match.
- Full regression XML SHA-256: `74f0f8531726ccc9ac9d0449545a4fdfa90f87d7ad867dd4ff99cb96c2f97e4c`. The complete receipt is `regression_release/test_receipt.json`.
- All 4 investigation SQLite files passed integrity checks; each has zero order intents, signed-management records and API actions.

The tests cover independent minimum checks at entry versus protection/exit, all ten runtime-lot examples, empty books, stale/future observations, depth, side capacity, leverage, market identity, price divergence, unchanged notional cap, and real read-only runtime composition. Existing regression tests continue to cover partial fills, rejected exits/protection, unknown status, exact residuals and restart recovery. Synthetic success does not certify par acceptance.

## 5. Safest eligible market

**None.** BTC has the largest observed lot value but still fails the minimum and the unchanged 10%-of-best-level depth test in the final snapshot. SP500 also fails those checks. ETH passes the reviewed spread/depth/capacity conditions but its smallest possible fill is far below the minimum. Neither is an eligible recommendation.

## 6. Minimum-lot notional and trade size

Final public review: **2026-10-12T09:46:52.890867+00:00 to 2026-10-12T09:47:05.696187+00:00** — approximately **15:16:53–15:17:06 IST on 12 October**. Values are test USDPR contract notional under the published price-times-size rule. Metadata and price observations were freshly read per market; quotes are snapshots, not future guarantees.

| Market | Runtime lot | Lot at observed mark | Lot at reviewed LONG entry limit | Lot at conservative stop/exit limit | Blockers |
| --- | ---: | ---: | ---: | ---: | --- |
| par:BRENT | 0.01 | 1.0344 | Unavailable | Unavailable | NO_EXECUTABLE_TWO_SIDED_BOOK |
| par:BTC | 0.0001 | 8.34380 | 8.3512 | 8.2223 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM; CERTIFICATION_BBO_DEPTH_FRACTION_EXCEEDED |
| par:ETH | 0.0001 | 0.25546 | 0.25558 | 0.25148 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM |
| par:EWJ | 0.001 | 0.098012 | 0.098098 | 0.096526 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM |
| par:EWY | 0.001 | 0.17347 | 0.17354 | 0.17077 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM |
| par:GOLD | 0.0001 | 0.41730 | 0.41746 | 0.41077 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM |
| par:HYPE | 0.01 | 0.86858 | Unavailable | Unavailable | NO_EXECUTABLE_TWO_SIDED_BOOK |
| par:SP500 | 0.001 | 7.8208 | 7.8289 | 7.7007 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM; CERTIFICATION_BBO_DEPTH_FRACTION_EXCEEDED |
| par:USDEUR | 0.1 | 0.11212 | 0.11222 | 0.11042 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM |
| par:USDJPY | 0.01 | 1.5848 | 1.5862 | 1.5608 | ONE_LOT_ENTRY_BELOW_MINIMUM; ONE_LOT_PROTECTION_OR_EXIT_BELOW_MINIMUM |

All ten mark-based lot values are below 10. Eight had usable two-sided books; all eight were below 10 at entry and stop/exit limits. BRENT and HYPE had no usable two-sided book, so their entry and protection prices were not invented from marks or candles. **Selected trade size: none; submitted quantity: zero.**

For example, one BTC lot would request about **8.3512** at the reviewed entry limit, and **8.2223** at the conservative exit. Two lots would exceed the minimum at entry, but could still fill just one lot or leave one lot after closing. Increasing notional would not remove that possibility.

Additional actual snapshot details, for inspection only:

| Market | Entry limit | Stop trigger | Stop/exit limit | Spread bps | Best bid/ask quantities | Entry/exit depth within limits | Lots needed merely to exceed entry minimum |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| par:BTC | 83512 | 82636 | 82223 | 0.1198028045836553033706519070 | 0.0005 / 0.0602 | 0.0667 / 1.2964 | 2 |
| par:ETH | 2555.8 | 2527.4 | 2514.8 | 6.656877141458639255996084190 | 0.208 / 0.2019 | 3.1369 / 42.3550 | 40 |
| par:EWJ | 98.098 | 97.011 | 96.526 | 6.019210463224154377445304251 | 5.42 / 5.451 | 83.382 / 1103.436 | 102 |
| par:EWY | 173.54 | 171.62 | 170.77 | 6.343531040050748248320405986 | 2.974 / 2.982 | 17.392 / 623.278 | 58 |
| par:GOLD | 4174.6 | 4128.3 | 4107.7 | 6.472879832184596943362301468 | 0.1281 / 0.1282 | 0.1282 / 25.9268 | 24 |
| par:SP500 | 7828.9 | 7739.3 | 7700.7 | 9.717178949521812509589321332 | 0.305 / 0.005 | 0.905 / 13.525 | 2 |
| par:USDEUR | 1.1222 | 1.1097 | 1.1042 | 7.134575938642646927673236422 | 494.2 / 22782.5 | 29638.5 / 96564.3 | 90 |
| par:USDJPY | 158.62 | 156.86 | 156.08 | 6.940282027824221584277106533 | 3.44 / 3.46 | 50.75 / 714.40 | 7 |

These prices reproduce the existing isolated certification geometry: BUY limit within 5 bps, fixed test trigger about 1% below current bid, and limit about 0.5% below that trigger; a later discretionary close remains within the existing 20 bps allowance and absolute exit bound. They do not change normal strategy stops or the disabled catastrophic protection policy. Book depth is observed now; a future stop may lack liquidity and a stop-limit can remain unfilled after a gap. These are **invalid one-lot order reviews**, not executable proposals.

## 7. Sub-$10 close/protection evidence

The [current participant guide](https://perpetual-alpha26.github.io/docs/) gives the general $10 order minimum and warns that IOC closes can partially fill or be rejected. [Hyperliquid's error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) documents minimum-value rejections. Neither source inspected explicitly establishes the needed exemption.

[Position TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) documents dynamic position sizing and partial-parent behavior, while the [exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) documents grouping and reduce-only fields. Distinct position-attached minimum treatment remains unknown. The installed SDK 0.24.0 `market_close` reads the actual position and submits an ordinary opposite-side reduce-only IOC through `order`. No separate dust mechanism is demonstrated by that client method.

No actual small-close/protection experiment occurred. An undocumented exception may exist, but implementation cannot assume it. A general minimum exemption has not been added.

## 8. PARTIAL_FILL_EXIT_READY

**FALSE.** No current market avoids the subminimum remainder problem, and small-close/protection acceptance remains unverified.

## 9. CONTROLLED_EXECUTION_READY and account checks

**CONTROLLED_EXECUTION_READY = FALSE. ACTUAL_PROTECTION_READY = FALSE.** The normal protection policy remains configured but disabled. A real protective order has never been accepted or verified in this task.

| Fresh read-only check | Observation |
| --- | --- |
| Team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Approved API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`; local key-derived public address matches |
| Testnet/par | Mandatory verified runtime metadata; official ten prefixed markets |
| Unified mode | `unifiedAccount` |
| Reported USDPR collateral | `1000000.0` |
| Available long collateral | `activeAssetData.availableToTrade[0]` reports 1,000,000 for each of the eight priced reviews; all ten raw active-asset responses preserved. Spot total is not substituted for capacity. |
| Leverage | All ten `1x CROSS`; read only, no setting change |
| Positions/orders | Zero before and after review, including frontend trigger-order list |
| API agent expiry | `2027-04-04T23:02:04.898000+05:30`; valid at the observed account check |
| Taker fee estimate | `0.00090` per fill; current positive base user rate doubled per the documented par fee scale. No actual fee or P&L measured. |
| Clock at account check | Healthy; later final offset `-422` ms is separately recorded |
| Account action budget | `13` used of `10000`; no action used by this task |
| Public read budget | Final weight `834` within 1200 with 120 reserve; no public upstream failures in the verified run |
| Local nonce ownership | Correct API binding, second local process rejected, no nonce allocation, lease released |
| Remote signer ownership | Not established by a local lease; sole-host confirmation remains a future approval requirement |
| Durable certification account barrier | Not run/authorized. Public account readiness correctly retains `ACCOUNT_RECONCILIATION_REQUIRED`. A flat snapshot does not grant durable execution readiness. |

The account observation was **2026-10-12T15:16:58.816000+05:30**; local signer check was **2026-10-12T15:16:40.497000+05:30 to 2026-10-12T15:16:40.830000+05:30**. These are timestamped evidence and must be repeated before any future controlled attempt. The public fee/mark/funding values are observations, not actual realized accounting. Net actual P&L remains **unknown/not certified**, rather than being reported as zero or a PAPER result.

The sandbox reads failed with `INFO_RETRY_BUDGET_EXHAUSTED`; those failed attempts are preserved. Separately reviewed, bounded public reads outside that environment succeeded. The environment failure is not a claim that the venue feed was down. The earlier initial all-market probe preserved two unavailable books as raw evidence; the tested final inspector gives the explicit `NO_EXECUTABLE_TWO_SIDED_BOOK` reason without constructing synthetic prices.

## 10. Exact authorization proposal

**No executable proposal is ready.** Market, quantity, approved trade prices and actual-round-trip fee estimate are therefore not selected for authorization. No approval file has been created. The review JSON cannot be used as a `CertificationProposal` or as a permit.

After the missing venue rules are confirmed and any narrow supported implementation is offline-tested, a fresh source-bound account/market preflight must produce an exact bounded trade for explicit human approval. The current review cap stays at 25 USDPR; it is not itself human authorization. No request is being made to approve an unsafe trade.

## 11. The single next action

**Obtain authoritative par confirmation of both the exact full-position sub-$10 close and its protective-order treatment, or an equivalent documented safe mechanism.** The ready-to-copy question is [organizer_question_draft.md](organizer_question_draft.md); it has not been sent. Keep PAPER/false while this evidence is missing.

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
PARTIAL_FILL_EXIT_READY=FALSE
ACTUAL_PROTECTION_READY=FALSE
CONTROLLED_EXECUTION_READY=FALSE
LONG_CERTIFIED=FALSE
SHORT_CERTIFIED=FALSE
FUNDED_RECOVERY_CERTIFIED=FALSE
PRACTICE_READY=FALSE
LIVE_READY=FALSE
```
