# Final practice recovery — A–K operator report

Updated 2026-10-17T13:58:56.890000+05:30. **Trading remains blocked. The new UNKNOWN could not be formally resolved from the available evidence. No new approval was requested and no signer or trading worker was launched.**

| Question | Verified answer |
| --- | --- |
| A. New UNKNOWN formally resolved? | **No.** Exact CLOID/nonce/source reviewed; original causal rejection telemetry is missing. Raw UNKNOWN and nonce are preserved. |
| B. Freshness fixed and verified? | **Yes, offline.** Unchanged five-second boundary; 381 targeted checks passed, including 4,900/5,000/5,100 ms and SDK delays. No actual exchange retest. |
| C. Native Stop Limit qualified? | **No.** No genuine accepted/triggered parent-to-child closing chain. |
| D. Subminimum residual protection/closure? | Native protection **unknown**. Only the historical exact one-lot BTC full-position IOC close is verified; it is not a general/native exemption. |
| E. Fresh genuine qualification permitted? | **No**, while the effective UNKNOWN barrier remains. Expired/consumed approval cannot be reused. |
| F. Maximum executable LONG now? | **0 eligible/qualified TEST USDPR.** Observed liquidity-only upper estimates are below; largest par:EWJ ≈50.011773, BTC 48.96240. They are snapshots, not an executable signal or risk allocation. |
| G. Complete regression passed? | Existing source-matched **2,753 passed**, 0 failures/errors/skips; hashes revalidated. **381 targeted tests rerun** in this review passed. No production-source changes, so full suite was not rerun. |
| H. Autonomous session eligible for approval? | **No.** UNKNOWN, native/residual proof and a future exact approval remain prerequisites. Proposed bankroll remains unallocated. |
| I. Exact VS Code launch interface? | Existing authorized CLI shown below. A runnable authorized command cannot be completed until genuine mandate/acceptance/native proof files exist. |
| J. Genuine new orders/P&L? | **No confirmed new orders or fills**, no new fees/funding. No completed qualification round trip. October 15 net remains **+0.050512 TEST USDPR**, separate from today. |
| K. Exact remaining dependency? | Identity-bound causal/terminal evidence for this UNKNOWN, registered-par small-native semantics and genuine native trigger/residual evidence. Then fresh exact human authorization. More software-only tests cannot supply those venue records. |

## Formal UNKNOWN review

`0xac0eea156fcec80986dd67c9057b6ded`, nonce **1792217834069**, mandate `59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea`. The original source was reconstructed exactly as `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f`. The mandatory pre-HTTP claim path and absence of a claim support the pre-HTTP diagnosis; the original native worker saved only a generic exception, without the explicit causal evidence required by the current immutable framework. No certificate or terminal record was fabricated. See [UNKNOWN_INTENT_RESOLUTION_REPORT.md](UNKNOWN_INTENT_RESOLUTION_REPORT.md).

Fresh review completed **63 unsigned /info requests**, zero venue errors. Two authoritative readbacks at 2026-10-17T13:53:58.428000+05:30 and 2026-10-17T13:54:01.260000+05:30 show no positions/orders and unknownOid for the exact CLOID. Four own historical order records contain no matching action. Complete paginated fills/funding show no new activity. These facts establish observed account truth, not nontransmission. An initial sandbox DNS failure was preserved separately; it had no HTTP status or 429.

## Native and residual route

The [venue TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) documents mark triggers, position versus fixed sizing and gap/cancellation risks. It does not provide our missing registered-par subminimum execution proof. No supported exception has been independently established, and no venue-wide prohibition is inferred. See [NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md](NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md) and [VENUE_OPERATOR_REVIEW_PACKET.md](VENUE_OPERATOR_REVIEW_PACKET.md). No messages were sent.

## Current observed liquidity

Books observed 2026-10-17T13:53:51.791000+05:30 through 2026-10-17T13:53:55.640000+05:30. Retain 10% of **both** best levels, finite depth within 5 bps, actual lot rounding and current 1x account maxTradeSz. Estimates are capped at the proposed 10,000 maximum; displayed depth binds far earlier. They exclude unqualified native/residual protection, unresolved-order, frozen-signal and full future risk/allocation gates. No current quote authorizes signing.

| Market | One-lot mark value | Liquidity-only quantity | Liquidity-only notional, TEST USDPR |
| --- | ---: | ---: | ---: |
| par:BRENT | 1.0686 | 0.09 | 9.6192 |
| par:BTC | 8.16040 | 0.0006 | 48.96240 |
| par:ETH | 0.24308 | 0.0205 | 49.84370 |
| par:EWJ | 0.094855 | 0.527 | 50.011773 |
| par:EWY | 0.15057 | 0.332 | 49.9992 |
| par:GOLD | 0.41656 | 0.0024 | 9.99936 |
| par:HYPE | 0.8008 | 0.62 | 49.6496 |
| par:SP500 | 7.6314 | 0.001 | 7.6343 |
| par:USDEUR | 0.11237 | 44.4 | 49.91004 |
| par:USDJPY | 1.5817 | 0.12 | 18.9912 |

BRENT, GOLD and SP500 estimates are below the normal 10 minimum and cannot support a normal opening order at these observations. All ten one-lot mark values are below 10, so simply increasing initial size does not eliminate a possible subminimum residual. No current evidence supports 1,000–10,000 notional execution through these books.

## Verification and exact launch interface

Current source `135734b4269554f98a295bb245fbf79ca5576ee1c07d6aa4049a3d88007c4109`. Full XML `7d1a15356230d6adec307de3714032b1c766569213b17489e6aa9a3a89a1573e`; receipt `e0df19551d9b6695399cbc29416f87b618689709b88c2caa7a1e8eab6af3125b`. Full release remains valid for this unchanged source. Supplemental tests were kept under docs; no strategy, lot precision, configuration, floor or production source was changed. Fresh Phase-0/strategy-freeze checks pass. Actual SQLite dumps, checkpoint checksums, original BUY/SELL proofs, historical certificate, new UNKNOWN and nonce are preserved. See [FRESHNESS_REPAIR_VERIFICATION_REPORT.md](FRESHNESS_REPAIR_VERIFICATION_REPORT.md).

The real execution-enabled interface, from this cloned repository's VS Code Terminal, is:

```sh
.venv/bin/python scripts/anchorium_cli.py start --authorized \
  --mandate "$NEW_VALIDATED_MANDATE_JSON" \
  --acceptance "$GENUINE_ACCEPTANCE_JSON" \
  --release docs/practice_weekend_2026-10-17/freshness_repair_regression_release/test_receipt.json \
  --native-protection-evidence "$QUALIFIED_NATIVE_PROOF_JSON" \
  --state runtime/terminal
```

**This is an interface template, not a launchable authorization.** Its three named mandate/acceptance/proof inputs do not exist in valid form. Do not substitute old approvals. No command was launched. After future prerequisites and exact approval, the authorized runtime implements the deterministic SCAN → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE lifecycle and can continue observing after its bounded signer closes; it requires no continuous Codex/LLM credits.

The proposed Oct17–18 contract remains LONG-only, one position, two total entry attempts, 1x CROSS, <=24h and no later than Oct18 23:57 IST, carried 1% session loss, 0.5% trade risk, proposed 20,000 allocation, bounded protection/recovery and no midnight reset/renewal. It has no accepted session, signing authority or authorized bankroll. Native Stop Limit does not guarantee a loss cap or fill through a gap.

## Actual accounting and next action

No new BUY/SELL fill, fee or funding occurred in the reconciled October 17 window. Observed new cashflow is 0; qualification P&L remains uncertified. Historical October 15: gross +0.0794, fees 0.029415, funding +0.000527, **net +0.050512 TEST USDPR**. Remaining positions/orders are empty in both timestamped readbacks. No organizer whitelist/reset claim is made.

The immediate next action is the exact causal/terminal evidence review in the packet, followed by registered-par native/residual evidence. Extra approval alone cannot bypass either barrier. No new qualification or autonomous proposal was generated. No next-day session, heartbeat, retry or restart was scheduled. No worker is running; future local operation depends on this Mac, process/app, power and internet.
