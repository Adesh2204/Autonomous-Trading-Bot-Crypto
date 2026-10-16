# Team Anchorium — V8.6 exact full-position close implementation

## 1. Direct verdict

**The narrow closing fix is implemented and tested. The first funded testnet trade remains blocked.**
We can prepare an exact IOC close for the previously verified size/direction/market combinations,
without increasing the position to meet $10. We have not independently verified a one-lot stop
that protects a sub-$10 position. Therefore there is no safe LONG proposal to approve yet.

No actual exchange order, cancel, configuration change or actual-wallet signature was made.
PAPER/false and disabled protection remain enforced. Ephemeral offline signatures are test fixtures.

## 2. Confirmed root cause and venue evidence

Ordinary MarketSpec normalization and the central validator reject orders below $10 before signing.
The existing exact-close sizing helper also rejected small residuals. Those general rules remain;
the new dedicated closing operation can exempt only a verified exact full-position IOC shape.

The V8.5 independent public readbacks established six original reduce-only IOC orders, filled
statuses, exact original sizes and matched fills whose reported starting quantity reduces to zero.
These are other public wallets. They are not Anchorium trades. The zero quantity is fill-derived,
not an independent historical position snapshot. One lot is compared with current runtime metadata;
historical metadata was not separately recovered. Historical acceptance is not a universal or
present-day venue guarantee.

| Market | Closing side | Exact supported sub-$10 size | Original order ID | Original limit notional |
|---|---|---:|---:|---:|
| par:EWJ | BUY | 0.001 | 61956380536 | 0.099731 |
| par:BRENT | SELL | 0.01 | 61912483832 | 1.0163 |
| par:HYPE | BUY | 0.01 | 61878767079 | 0.9165 |
| par:BTC | BUY | 0.0001 | 62391880965 | 8.33680 |
| par:BTC | SELL | 0.0001 | 62228843959 | 8.20750 |
| par:ETH | BUY | 0.0001 | 61841673908 | 0.27172 |

BUY closes a short; SELL closes a long. Thus BTC has one-lot evidence in both directions,
whereas ETH/HYPE/EWJ have BUY-only evidence and BRENT has SELL-only evidence. Other shapes,
including an unverified two-lot BTC residual, remain blocked. Ordinary $10-or-larger full closes
still pass the existing rules. The dedicated subminimum scope additionally requires the original
runtime asset mapping and size decimals; a mapping change fails closed.

The preserved original proof hash is `c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764`.

## 3. What the narrowly scoped path checks

1. Explicit `close_full_position` operation, LIMIT IOC, reduce-only true and a recognized closing identity.
2. One actual `par` position and fresh, reconciled account truth; size equals the entire observed remainder.
3. Opposite direction, exact lot/price representation, no quantity rounding, oversizing or exposure top-up.
4. Observed historical scope for a sub-$10 order; no extrapolation to stops, partial-position closes or another market.
5. Existing account, agent, metadata, quote, mark-price band, risk, compliance, rate, nonce and authorization gates.
6. An exact-action central SDK permit rechecks positions twice at the signing boundary. A changed position
   blocks signing, pauses entries and retains durable uncertainty for review.
7. Existing durable client order identities prevent retransmission. Confirmed partial exits use the new actual
   remainder within the approved two-attempt exit bound; unknown status stops the sequence without a blind retry.

The normal `submit`, replacement, PAPER normalization and protective-order routes retain the minimum.
The actual certification builder is prepared to use this explicit close path, but it still calls
`require_safe_partial_path` before acquiring its signer. That entry gate remains blocked here.

## 4. Independent one-lot protective-stop investigation

A new public read-only inspection ran from **2026-10-12T17:09:34.885098+00:00 to 2026-10-12T17:09:44.365924+00:00**
(UTC; add 5h30 for IST). It used four bounded trade feeds only to find legitimate public counterparties,
then inspected existing orders/positions and two additional histories. It did not run the scanner,
request candle histories, create a wallet signature or submit an exchange action.

| V8.6 observation | Result |
|---|---:|
| Public accounts inspected for existing orders/positions | 12 |
| Current open-order rows | 252 |
| Current trigger orders | 0 |
| Additional par historical event rows | 4000 |
| Unique additional historical orders | 2377 |
| Historical trigger rows in this additional sample | 0 |
| Read-only /info requests | 32 |
| Conservatively charged public weight | 840 |
| Independently accepted one-lot stop covering a position | 0 |

Both new histories hit the 2,000-row cap. This is a bounded sample, not a census. Absence of a stop
example does **not** establish that the venue rejects small stops. The earlier V8.5 history sample
is preserved separately; its 15,304 event rows/8,427 unique orders must not be mistaken for new rows.
The sandbox DNS failure is preserved under `protection_read_sandbox`; the successful public read
is under `protection_read_verified`. Source hashes match before and after the successful read.

The [official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
explains position protection, fixed-size versus position-following behavior and parent-order handling.
It does not specify the needed sub-$10 admission exception. A child attached to a partly filled
parent is not automatically retained after a manual cancellation. A stop limit can remain unfilled
if a gap passes its limit.

The [official exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint)
documents trigger payloads, `positionTpsl` grouping and ordinary minimum-order rejection, without
establishing a par one-lot exception. The [official error reference](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)
separates minimum-notional errors from reduce-only errors. Neither the SDK serializer nor a
successful IOC closing record establishes small-stop admission.

The new evidence assessor requires an original one-lot subminimum stop, reduce-only/trigger flags,
correct side, exact current position coverage, stable before/after state and matching open-order
status readback. Even an accepted open stop would not by itself prove trigger/residual execution.
No existing record in this bounded check satisfied those conditions. Protection remains unverified.

## 5. Protection rejection cannot earn a LONG certificate

Previously, a rejected stop followed by successful emergency closure could have status
`TRADE_CLOSED_RECONCILED`, and the runtime used that status to mark LONG certification complete.

The accounting status is retained: it correctly says the position closed and its reported P&L
reconciled. A separate `certification_passed` result now requires actual-size protection acceptance.
The runtime additionally requires flat reconciliation and **actual testnet evidence**, so offline
fixtures cannot set an actual account certificate. A rejected/unverified stop never earns a LONG
certificate. The durable `certification_completed:<identity>` marker only consumes the attempt;
it is not proof of qualification and still prevents repeated entry after restart.

## 6. Source files changed

| Source file | Purpose |
|---|---|
| `algo-trading-bot/exchange/full_position_close.py` | New explicit IOC scope, historical proof identity and exact full-position validation. |
| `algo-trading-bot/exchange/partial_fill_safety.py` | Separate scoped closing helper; strict protection sizing is retained. |
| `algo-trading-bot/exchange/exchange_rules.py` | Explicit close operation only; normal order minimum and other central checks remain. |
| `algo-trading-bot/exchange/compliance_guard.py` | Central exact-action permit carries the full-close size check to the SDK boundary. |
| `algo-trading-bot/exchange/hyperliquid_execution.py` | Dedicated close_full_position path, exact precision, double position read, existing durable recovery. |
| `algo-trading-bot/exchange/testnet_certification.py` | Explicit close opt-in, bounded residual exit, independent protection-qualified result. |
| `algo-trading-bot/exchange/certification_runtime.py` | Prepared close composition; actual LONG certificate requires verified protection and actual evidence. |
| `algo-trading-bot/test_exact_full_close_v8_6.py` | 56 offline cases for scope, partial fills, stops, uncertainty, duplicates and restart. |

Six existing infrastructure files changed, two active files were added. The other prior manifest
files, including all four configuration files, remain identical. `production_changes.diff` records
the existing-file comparison against V8.5; pre-edit copies are preserved in `source_before`.
Read-only evidence helpers, raw observations, report generators and the unsent question live in this
documentation directory, outside the production exchange path. There is no new strategy or ML feature.

The legacy occurrence inventory was refreshed with its existing script. It contains
1,103,169 occurrences across 472 files, including pre-existing cached references;
these totals are not new exchange dependencies. Before/after hashes and the refresh
receipt are preserved in this directory.

## 7. Tests and frozen strategy

**Full regression: 1633 passed; 0 failures;
0 errors; 0 skipped.** This includes all
1,577 baseline cases plus 56 new cases. The earlier targeted infrastructure run passed 294 cases;
the final focused new test run passed 56. These runs overlap and are not added together.

New coverage includes exact observed scopes, wrong direction/mapping/size, stale/reconciled account
requirements, normal entry/trigger lockouts, SDK quantity/wire identity, changing position at the
permit boundary, rejected/unknown close outcomes, no duplicate transmission, one-lot partial entry,
unverified two-lot escalation, actual one-lot residual after a partial exit, stop rejection,
restart with both consumed and unresolved attempts, and false-positive public stop evidence.

The initial targeted run had fixture setup/mapping errors (12 failures, six errors); they are
preserved in `targeted_initial`. The next focused run exposed the central permit callback gap
(one failure), which was fixed in the production permit rather than bypassed in the test.
`targeted_retry` is preserved. The final full suite used unchanged active source throughout.

Phase-0: **PASS**, including the Angel and testnet write lockouts and PAPER/false defaults.
Strategy freeze: **PASS** — one whole frozen file, eight frozen methods, 32 parameters.
`signal_brain.py` is byte-identical to `nse-working-baseline`; hash:
`bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`.
VWAP, EMA, ATR, state behavior, UTC input convention, 0.40% ATR floor, 15 bps spread ceiling,
300 completed bars and Top-3 were not changed. Active source hash: `d06cc6ebb16ad2859b317e2a310dfadf8b11310187f4c222b0b62e5baa9dbc75`.
XML hash: `e4469c8ea62567cecaa0b5a228d708fe2f50ac2f36b7fa3ef2045b5d80f664d4`. The documentation evidence-classifier hash is also bound to the receipt.

## 8. Account preflight and trade proposal

The user requested a fresh activation preflight **when both closing and protection are validated**.
That condition is not met, so the activation preflight and LONG proposal are deferred.
No actual wallet key was loaded or used by this V8.6 investigation.

For context only, the prior V8.5 read observed a unified account, 1,000,000 USDPR, all ten markets at
1x CROSS, an approved API agent, no positions/orders and a reconciled separate read-only journal.
Its timestamps were **2026-10-12T11:43:13.138849+00:00–2026-10-12T11:43:27.286717+00:00 UTC**. Those checks were made
against older source, and are not current readiness or permission. Its local signer lease check
also did not establish sole ownership across other hosts. Human sole-signer-host confirmation remains
outstanding. A future proposal requires fresh account, signer/nonce/clock/rate, market/liquidity,
reconciliation, protection-capability and exact risk checks, followed by explicit trade approval.

There is **no eligible trade to authorize now**. BTC is the only investigated crypto with verified
one-lot IOC closes in both directions; this is not a liquidity recommendation or a protection approval.
There is no Anchorium actual round-trip P&L from this work. Test fixtures and other wallets' fills
are not reported as our profits, funded recovery or strategy performance.

## 9. Readiness flags

```ini
ONE_LOT_FULL_CLOSE_EVIDENCE_VERIFIED = TRUE
CLOSING_EXCEPTION_IMPLEMENTED = TRUE
SCOPED_FULL_POSITION_CLOSE_OFFLINE_TESTS_PASSED = TRUE
UNIVERSAL_SUBMINIMUM_CLOSE_VERIFIED = FALSE
ONE_LOT_PROTECTIVE_STOP_ACCEPTANCE_VERIFIED = FALSE
SUBMINIMUM_PROTECTION_CAPABILITY_VERIFIED = FALSE
PROTECTION_PARTIAL_FILL_BEHAVIOR_VERIFIED = FALSE
PARTIAL_FILL_EXIT_READY = FALSE
ACTUAL_PROTECTION_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
LONG_CERTIFIED = FALSE
SHORT_CERTIFIED = FALSE
FUNDED_RECOVERY_CERTIFIED = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
PROTECTION_ENABLED = FALSE
PRODUCTION_INFRASTRUCTURE_CHANGED = TRUE
PRODUCTION_STRATEGY_CHANGED = FALSE
PRODUCTION_TRADING_ACTIVATED = FALSE
SOLE_SIGNER_HOST_CONFIRMED = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
```

`PARTIAL_FILL_EXIT_READY` stays false because the narrow scope does not prove every possible
small residual and its protection. Infrastructure code changed; strategy and trading activation did not.

## 10. Remaining blockers and the single next safe action

Obtain an authoritative **par one-lot protective-stop** rule or an independently verifiable original
stop record with actual position coverage and trigger/residual behavior. The exact questions are
in `organizer_question_draft.md`, explicitly **UNSENT**. No organizer message is authorized or sent.

Keep entry blocked until that evidence supports a narrow stop solution. Do not enlarge exposure,
remove the ordinary minimum, submit a probe stop, activate autonomous trading or manufacture an
approval proposal. If the protection mechanism is unsupported, the correct outcome remains a blocked
certification entry. If supported, implement/test that independently, then refresh the account and
prepare one bounded LONG for explicit human approval.
