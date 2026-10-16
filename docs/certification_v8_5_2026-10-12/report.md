# Team Anchorium — V8.5 execution validation

Prepared 2026-10-12T11:43:52.348931+00:00. **No actual exchange order was submitted.**

## 1. Direct verdict

**One-lot manual closing has genuine historical evidence. Small-position
protective stops remain unverified, so the first actual trade is still blocked.**
We found six one-lot closes across five `par:` markets. We did not find an
accepted small protective stop in the bounded sample or an explicit official
rule establishing its minimum-value exception. This is an evidence gap, not a
claim that the exchange definitely rejects every small stop.

Your V8.5 directive makes the code exception conditional on establishing both
capabilities. That condition is unmet. No opening, closing or protective-order
minimum validator was relaxed, and no exact trade proposal was presented for
approval.

## 2. Verified one-lot closes

All six original orders were reduce-only, non-trigger limit IOC orders with
status `filled`, zero remaining order size and matched fills equal to the
entire reported starting position. Each quantity equals one lot under fresh
runtime metadata. Two independent reads of each order/fill window agree.

| Market | Order ID | Actual direction | Original size | Original limit value, USDPR | Actual fill price | Fill-derived final quantity |
|---|---:|---|---:|---:|---:|---:|
| par:EWJ | 61956380536 | Close Short | 0.001 | 0.099731 | 99.334 | 0.000 |
| par:BRENT | 61912483832 | Close Long | 0.01 | 1.0163 | 102.04 | 0.00 |
| par:HYPE | 61878767079 | Close Short | 0.01 | 0.9165 | 91.285 | 0.00 |
| par:BTC | 62391880965 | Close Short | 0.0001 | 8.33680 | 82978.0 | 0.0000 |
| par:BTC | 62228843959 | Close Long | 0.0001 | 8.20750 | 82486.0 | 0.0000 |
| par:ETH | 61841673908 | Close Short | 0.0001 | 0.27172 | 2706.4 | 0.0000 |

These are **other public accounts**, not Team Anchorium trades. The zero final
quantity is derived from the API's reported `startPosition` and matched fill,
not from an independent historical account snapshot. Past lot metadata was
not separately recoverable; the exact sizes match the freshly read lot steps.
This proves these historical operations occurred, not a blanket guarantee for
every current market, size or order type. Raw original orders and fills are in
[the independent readback](independent_close_readback/one_lot_readback.json).

Two additional HYPE one-lot attempts returned `reduceOnlyRejected` and no
matched fills. They were excluded from success counts; a rejection with this
code does not prove the submitted order met the full-position condition.

## 3. Protective-stop result and remaining venue question

The two bounded searches sampled **8 public counterparties**, **15,304 `par`
history event rows** and **8,427 unique orders**. Duplicate open/terminal
history events were not counted as separate orders. There were **zero trigger
order records**, hence no small-stop acceptance, readback or partial-fill
protection example to verify. Several latest-history responses hit their
2,000-row cap, so absence in this sample is not proof of venue-wide absence.
The search used six focused public trade feeds only to discover counterparties;
it did not run candles, signals, ranking or a broad market-data redesign.

The [participant guide](https://perpetual-alpha26.github.io/docs/) states the
ordinary $10 minimum and describes partial IOC fills. The [official TP/SL
page](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
describes position-based and parent-order stops but does not explicitly promise
sub-$10 acceptance. Parent-linked children also do not automatically solve
protection of every partial fill. See [venue_behavior.md](venue_behavior.md)
for the precise source/evidence distinction.

The installed official SDK is **0.24.0**. Its `market_close` constructs an
ordinary reduce-only IOC. Trigger and `positionTpsl` payload support does not,
by itself, prove the server accepts a tiny stop. No zero-size, oversized close,
larger entry or other undocumented workaround was implemented.

The [organizer question](organizer_question_draft.md) asks specifically about
placement versus trigger-time minimum checks, fixed-size versus position-wide
grouping and protection of actual partial fills/residuals. It is **unsent**;
no organizer/support message was sent by this task.

## 4. Exact root cause in the repository

The central validator still rejects a normalized size × price below 10
(`exchange_rules.py`, `MIN_ORDER_NOTIONAL`). `MarketSpec.normalize_order`
independently applies the same minimum to every order, including reduce-only.
`exact_full_close_size` rejects a genuine residual below 10 rather than rounding
it away or increasing the close quantity. Certification's partial-path gate
tests the smallest possible fill and residual — one runtime lot — at reviewed
exit/protection prices. Thus a $25 opening request does not eliminate the gap.

The six historical manual closes resolve the previous lack of one-lot
observations. They do not resolve the shared protection gate or authorize a
global exception in closing and trigger validation. An implemented exception
must eventually have separate close/protection scope and retain exact
position identity, opposite-side direction, fresh account truth, bounded exits,
duplicate prevention and durable unresolved-exposure escalation.

## 5. Files and code changes

**No existing production source or configuration file changed.** All 216 files
in the V8.4 source manifest still match. `signal_brain.py` is byte-identical.
The ordinary $10 opening minimum, order locks and protection-disabled setting
remain enforced.

Added [test_public_execution_evidence_v8_5.py](../../algo-trading-bot/test_public_execution_evidence_v8_5.py):
39 offline anti-false-positive regressions. The new bounded readers and evidence
classifier are confined to this report directory. They use `/info` only, have
no SDK signer or exchange-action path and do not expand production query
allowlists. The classifier's separate hash is bound to the full regression
receipt because this documentation helper is outside the active source hash.

The required legacy occurrence inventory was refreshed. Its large existing
legacy reference/cache population is not a new production dependency.

## 6. Verification

| Check | Result |
|---|---|
| Full baseline plus new regressions | **1,577 passed; 0 failures, 0 errors, 0 skipped** |
| Focused certification/partial-fill/evidence tests | **137 passed** |
| Phase-0 order lockouts | PASS |
| Frozen strategy: file, 8 methods, 32 parameters | PASS |
| Before/after regression active source hash | Identical |
| Before/after classifier hash | Identical |
| Read-only SQLite integrity and checkpoint checksums | PASS |
| New actual signatures/orders/cancels/transfers | **0** |

The new tests reject larger original orders with tiny fills, incomplete or
interleaved fill chains, duplicates, incorrect direction/token/order identity,
rejected stops, ambiguous statuses and misleading acceptance-only evidence.
They keep manual-close evidence separate from stop evidence and verify that
observational proof cannot unlock the production minimum checks. The full
suite retains partial-entry/exit, protection rejection, uncertain-order,
duplicate prevention and restart-containment regressions.

An initial new test had a fixture-construction error (38 passed, 1 failed).
Its receipt is preserved; the fixture was corrected before the successful
137-test and full runs. Sandbox-only network failures are also preserved
separately from successful external public reads. No failure was relabeled a
pass or overwritten.

## 7. Fresh read-only account and signer preflight

Account observation: **12 October 2026, 11:43:13–11:43:27 UTC
(17:13:13–17:13:27 IST), after the full regression completed**.

| Item | Observed result |
|---|---|
| Team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Approved API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| Network / venue | Hyperliquid testnet / `par` |
| Collateral | 1,000,000 USDPR; this total is not substituted for free margin |
| Account mode | unifiedAccount |
| Exchange leverage | All 10 runtime markets: 1x CROSS |
| Positions / frontend orders, before and after | 0 / 0 |
| Returned actual `par` fills / funding | 0 / 0 in the observer's queried history |
| API approval | Valid; expiry `1806859924898` ms |
| Reported account action budget | 13 used of 10,000 |
| Public read budget | Healthy; 608 of 1,200 weight with 120 reserved |
| Clock | Healthy; 3 fresh confirmations; final estimated offset -447 ms |
| Local key derivation / nonce exclusion | MATCH / HEALTHY_LOCAL; no signature or nonce allocation |
| Sole signer across other computers | Not confirmed; the informational question remains unanswered in this evidence |

Reconciliation used the existing `CertificationRecovery` and actual reported
fills/funding from time zero through the observation. It saved a durable
checkpoint, closed/reopened its SQLite journal and reconciled again. Both
retained snapshots have valid checksums, matching source identities and a clean
final shutdown. This is a **separate read-only observer journal**. It grants no
execution permit and does not certify funded recovery of an actual position.
Future certification must independently refresh its own live account barrier.
The nonce lease check only proves exclusion on this host/OS user at that moment;
the lease was released afterward.

## 8. Fresh executable liquidity, with honest scope

| Market | Bid | Ask | Spread, bps | One lot at ask, USDPR |
|---|---:|---:|---:|---:|
| par:BTC | 83236.0 | 83252.0 | 1.922 | 8.32520 |
| par:ETH | 2542.0 | 2543.2 | 4.720 | 0.25432 |
| par:HYPE | 85.67 | 85.69 | 2.334 | 0.8569 |

Each book was fresh and two-sided at its recorded read. These snapshots expire
and are not standing trade offers. All three still have sub-$10 lot values.
BTC had a thin best bid and HYPE a thin best ask relative to the existing 10%-of-BBO
certification depth limit; two-sided liquidity alone is not a sizing pass.
ETH had better displayed depth for a future small test, but it is **not
currently execution-eligible** while small-stop handling remains unverified.
No strategy signal or 300-candle admission was claimed from these book reads.

## 9. Readiness and account truth

```ini
ONE_LOT_FULL_CLOSE_EVIDENCE_VERIFIED = TRUE
SUBMINIMUM_PROTECTION_CAPABILITY_VERIFIED = FALSE
PROTECTION_PARTIAL_FILL_BEHAVIOR_VERIFIED = FALSE
CLOSING_EXCEPTION_IMPLEMENTED = FALSE
PARTIAL_FILL_EXIT_READY = FALSE
ACTUAL_PROTECTION_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
LONG_CERTIFIED = FALSE
SHORT_CERTIFIED = FALSE
FUNDED_RECOVERY_CERTIFIED = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
PRODUCTION_CHANGED = FALSE
READ_ONLY_ACCOUNT_RECONCILED = TRUE
LOCAL_SIGNER_OWNERSHIP_VERIFIED = TRUE
SOLE_SIGNER_HOST_CONFIRMED = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
PROTECTION_ENABLED = false
```

`PARTIAL_FILL_EXIT_READY` stays false because the production-safe residual
close/protection path has not been established and implemented. Configured
protection is not accepted or tested exchange-side protection. Public wallets'
PnL is not Anchorium PnL. There is no certified actual Anchorium round-trip
profit or loss, and no funded LONG, SHORT or exposed-position recovery result.

VWAP, EMA, ATR, the 0.40% volatility floor, 15 bps spread ceiling, 300 completed
UTC candles and Top-3 were preserved. No strategy tuning, autonomous activation,
full-wallet trade, repeated-order attempt or recurring task was introduced.

## 10. Single next safe action

**Obtain authoritative `par` clarification or an independently verifiable
accepted below-$10 protective-stop record using the unsent organizer question.**
Keep entry blocked until its placement, exact actual-position coverage and
residual behavior are supported. Then implement only the verified scoped
exception, rerun safety tests and fresh account/liquidity checks, and present
one exact bounded LONG proposal for human approval. No signed order may precede
that approval.

Active source hash: `baead47bac360dfc06da2c4db83565330d8dd58ac01e607a5c3e4a76cdd5c398`.
Regression XML SHA-256: `79d9c3b9e94aeeb003dfed5b2d6cb9028ee3937440e08f0109b6d9114b8e3726`.
Brain SHA-256: `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`.
