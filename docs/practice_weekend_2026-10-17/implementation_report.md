# October 17–18 practice release — final A–I report

Updated 2026-10-17T12:40:08.582000+05:30. **The approved qualification ran once and stopped with a preserved local UNKNOWN entry. No exchange order/fill is confirmed. Independent reads after signing expiry confirm a flat account and zero open orders. The freshness failure is repaired and tested offline; native and subminimum protection remain unqualified, and trading remains locked.**

## A. Dynamic pricing, actual failure and repair

The approved corridor worked: fresh ask **81,478**, selected immutable BUY IOC limit **81,518**, below the approved **81,605** maximum and within the 5 bps route cap. The original 81,410-versus-81,412 fixed-limit obstacle was not the cause of this stop.

The approved source retained its original readiness snapshot through repeated SDK checks. Source and raw receipt chronology put readiness at approximately 1792217829566; final book receipt was 1792217835092, an age of **5,526 ms**, over the unchanged **5,000 ms** limit. Bid/ask and funding remained within the approved limits. The original executor persisted `ExchangeError`, not the exact exception text; `pre_http_diagnosis.json` explicitly distinguishes the source/timestamp reconstruction from a recorded transport rejection or nontransmission certificate.

The isolated native corridor path now reuses the existing typed signing boundary: genuinely reacquire account/readiness/metadata/book data when needed, rerun central risk/compliance and exact authorization for the **same reserved wire**, then validate the five-second evidence without repeating a serial REST bundle that ages it. Quantity, price, CLOID, permit ownership, global entry lease, nonce, source, expiry and cleanup-time limits remain binding. An UNKNOWN or already transmitted intent cannot use this renewal. Ordinary production and legacy fixed-price paths keep their existing gates. Native trigger placement retains its exact stop checks.

Native transport now records explicit pre-HTTP rejection reason, nonce/CLOID and HTTP start/response/uncertainty boundaries without exporting signatures or keys. **163 focused tests passed**, including 27 new after-nonce reacquisition, changed account/orders/fees/funding/depth/price/source/authority, health, five-second-boundary and diagnostic cases. No new actual-wallet signature or exchange retry was performed to test this repair.

## B. Genuine native-stop and residual evidence

There was **no confirmed entry fill and no native stop placement, acceptance, trigger, child or closing fill** in the actual attempt. Native qualification is INCOMPLETE. The successful historical one-lot IOC close still proves only its scoped full-position IOC recovery; it does not establish native Stop Limit acceptance below 10 TEST USDPR.

[Official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes default position-sized TP/SL, fixed explicit sizes, parent-child cancellation risks and potentially unfilled triggered limits. [The API schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) exposes `positionTpsl`; the required registered-`par` subminimum exception remains unverified. The earlier bounded audit of six public accounts/three histories found no qualifying native record; two histories were truncated at 2,000 rows. This is not a venue-wide prohibition finding. All eight requested questions remain documented in `native_stop_findings.json`. The partial-fill guard remains enabled.

## C. Latest observed LONG capacity

Refreshed 2026-10-17T12:34:28.463000+05:30. Genuine runtime metadata, finite both-side books and 1x account data were used. Liquidity-only estimates retain 10% participation and are **not executable authority**; they can become stale and exclude unresolved native/partial and strategy gates. Below-minimum estimates cannot support an opening order.

| Market | One-lot mark value, TEST USDPR | Liquidity-only LONG notional | Qualified unattended notional |
| --- | ---: | ---: | ---: |
| par:BRENT | 1.0679 | 49.1372 | 0 |
| par:BTC | 8.14990 | 48.90000 | 0 |
| par:ETH | 0.24293 | 49.80475 | 0 |
| par:EWJ | 0.094832 | 49.988585 | 0 |
| par:EWY | 0.15091 | 49.96445 | 0 |
| par:GOLD | 0.41656 | 10.00056 | 0 |
| par:HYPE | 0.79927 | 49.5752 | 0 |
| par:SP500 | 7.6329 | 99.2641 | 0 |
| par:USDEUR | 0.1124 | 49.91004 | 0 |
| par:USDJPY | 1.5821 | 49.0606 | 0 |

All ten one-lot mark values remain below 10. A correct LONG stop limit below its trigger/current mark is lower still. No permitted market currently avoids the minimum-lot native-stop issue. Qualified unattended capacity remains **0**; the new local UNKNOWN entry is an additional lock. No new market, precision change, liquidity enlargement or leverage change was introduced.

## D. Full regression and integrity

**Latest repaired release: 2753 passed, zero failures/errors/skips.** Full 2,726-test prior release plus 27 new tests. Source before/after: `135734b4269554f98a295bb245fbf79ca5576ee1c07d6aa4049a3d88007c4109` / `135734b4269554f98a295bb245fbf79ca5576ee1c07d6aa4049a3d88007c4109`. XML SHA-256: `7d1a15356230d6adec307de3714032b1c766569213b17489e6aa9a3a89a1573e`. Receipt SHA-256: `e0df19551d9b6695399cbc29416f87b618689709b88c2caa7a1e8eab6af3125b`. Requirements SHA-256: `db76f769d0aae03197e922f579ce6db9aa6aced9587da93e11b4bba409774b4d`. Strategy freeze and Phase-0 passed before and after; SDK 0.24.0 and dependency pins match.

The actual attempt used the separately preserved **2,726-test** release, source `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f`, XML `a8ae85f2d1130124eff7bd986c5287765d46e68d98431211a9feb3b4bf3cd173`. Its approval/source/XML and raw account proof were not replaced by the newer offline release. The modified source has not been retested on the exchange.

Post-attempt preservation passed: original strategy/configs/BUY/SELL proof files, all original raw intent rows and old immutable UNKNOWN certificate remain intact. SQLite integrity and checkpoint checksums pass. The actual nonce legitimately advanced once to **1792217834069** during the approved signing attempt; it was not rolled back. All actual-account database dumps and the new UNKNOWN row remained unchanged throughout the subsequent engineering/tests. See `post_attempt_preservation_receipt.json` and `change_manifest.json`.

## E. Exact approvals and session scope

Mandate `206517755e77aafd6c989f0129b5fd14bd784cafed50c95a48324d150f94e977` expired before execution; the later genuine response was preserved without backdating or execution.

New mandate **`59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea`** was genuinely accepted at **2026-10-17T11:45:27.523000+05:30**, within its decision deadline. Authority expired at **2026-10-17T11:50:27.523000+05:30**. Human-response provenance SHA-256: `0c0963fd7e0bc37b3dd2d8ed1cf001abc9b9acaadee909203149192400242373`. This authorized exactly one 0.0002 BTC LONG test, 1x CROSS, <=25 TEST USDPR, fresh ask 81,403–81,565, maximum BUY 81,605, <=5 bps entry route, fee ceiling 0.09%, funding cap 0.0001989106, <=15 bps spread and <=10% both-best-book participation. Full-size stop trigger/limit were 80,620/80,217; one-lot partial entry would be aborted by the scoped exact-position reduce-only IOC. Cleanup required >=80,217, <=20 bps slippage, <=2 resolved IOC attempts, <=1 owned cancellation round and <=6 signed actions. The 10 TEST USDPR budget was not a guaranteed loss cap. No stop/cleanup was needed or submitted because no exchange entry was established.

That mandate is **consumed and expired**. No new qualification proposal or automatic approval is being generated after the UNKNOWN outcome. The Oct17–18 contract remains implemented but has **no autonomous session ID, accepted mandate, approval deadline, authorized bankroll or running signer**. Its proposed 20,000 bankroll, one global position, two total entry attempts, 1x, 0.5% trade risk, 1% carried session loss, <=24-hour signing duration, October 18 23:57 IST absolute maximum, 15-minute entry cutoff and five-minute scheduled risk-close buffer remain unchanged. No midnight reset or renewal is allowed.

## F. Exact local command and execution evidence

The actual command, verified against PID/source/proposal/approval/output identity, was:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/run_native_qualification.py execute \
  --proposal docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143/proposal.json \
  --approval docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143/qualification_approval.json \
  --test-receipt docs/practice_weekend_2026-10-17/regression_release/test_receipt.json \
  --output docs/practice_weekend_2026-10-17/authorized_qualification_refresh_2026-10-17_1143
```

**Do not rerun this command.** It ran from this cloned repository and consumed its invocation. Autonomous `anchorium_cli.py start --authorized` was not launched; a complete runnable command cannot name a real accepted autonomous session or validated native proof yet. `operator_commands.md` describes the stopped invocation and gated future CLI. The standalone runtime requires no Codex or paid LLM; local Mac/process/power/internet availability remains necessary.

## G. Actual stopped worker and account truth

Worker **20311**, process-bound caffeinate **20312**, both verified stopped. One signed entry attempt allocated nonce **1792217834069** and original CLOID **`0xac0eea156fcec80986dd67c9057b6ded`**. An actual guarded signature was created; exact total signature count was not logged. The durable wire was 0.0002 BTC at 81,518. It became local UNKNOWN with no numeric exchange order ID. There are **zero recorded transmission claims**. The old native transport lacked complete pre-HTTP telemetry; missing records alone are not promoted into a new nontransmission certificate. No blind resubmission, cancel, SELL, restart, limit widening or source change occurred while the worker was alive.

The worker returned `EMERGENCY_EXIT_REQUIRED` / `CERTIFICATION_UNCERTAIN_ORDER_URGENT_REVIEW`. Its own final-flat/completion flags remain false because the local intent was unresolved. Independent unsigned reconciliation separately established account truth twice after the signing expiry: **2026-10-17T11:56:49.899000+05:30** and **2026-10-17T11:56:52.631000+05:30**, each with no positions/orders and `unknownOid` for the exact original CLOID. A later capacity/account audit again recorded two flat/zero-order reads, latest **2026-10-17T12:34:38.133000+05:30**. These are timestamped snapshots, not a completed round trip or permission to clear the entry lock.

Original raw receipt errors: zero; no actual HTTP429 evidence. Local rolling-rate waits/backoff events are not labeled as venue HTTP429. Recovery was bounded and used the original identity; no next-day worker or heartbeat was started. Both old heartbeats remain PAUSED. Caffeinate is not remote failover or an uptime guarantee.

## H. Actual fills, fees, funding and P&L

The approved attempt's actual account window contains **zero new BUY fills, SELL fills, fees or funding events**, and zero completed round trips. Observed account cashflow change is **0 TEST USDPR**. The raw worker's qualification P&L remains null / `REALIZED_PNL_NOT_CERTIFIED`; no successful or profitable qualification is claimed. No native/exit completion proof was created. Maximum session drawdown and remaining autonomous risk budget are null because no autonomous session existed.

The prior **October 15** trade remains separate: BUY 0.0002 @81,512, order 62755970305 / fill 800659111758533 / fee 0.014672; SELL @81,909, order 62805581662 / fill 260274449763192 / fee 0.014743. Gross +0.0794, total fees 0.029415, actual funding +0.000527, **net +0.050512 TEST USDPR**. It is not October 17 income. Original proofs are untouched; no organizer whitelist/reset claim is made.

## I. Specific blocker and next valid action

The freshness failure is repaired and independently tested offline. The actual consumed attempt remains locally UNKNOWN, despite authoritative flat/no-fill account snapshots. The new row must receive formal independent review from the original signed-source, nonce, transmission-claim and raw exchange evidence; it must not be deleted or inferred terminal merely from `unknownOid` or flatness. The original immutable certificate is still valid only for its original historical row.

Native Stop Limit trigger/child/closing and subminimum-residual support are also still unqualified. **Further signing and autonomous activation remain blocked.** A future admissible test requires that lifecycle review, genuine native/residual prerequisites as applicable, a source-matching release and a separately presented exact human decision. The consumed mandate is never resumed. No future profit, native trigger, specified trade count, loss cap or uninterrupted operation is guaranteed.
