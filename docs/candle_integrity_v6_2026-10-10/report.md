# Team Anchorium — V6 candle integrity and readiness report

## A. Executive verdict

**FIXES_VALIDATED_FEED_NOT_READY**

The verified numerical and merge defects are repaired and regression-tested. The trading strategy remains frozen. The current PAPER evidence does not establish a usable feed for practice. Missing exchange records have not been invented to make the bot pass.

This report concerns PAPER infrastructure. It does not certify profit, funded execution, emergency-order acceptance, or a hackathon result.

Plain-language guide: a candle is one minute’s opening, highest, lowest and closing prices plus traded volume. A completed candle belongs to a minute that has ended. ATR measures the typical price range; it is not profit. Quarantine means temporarily excluding a market whose inputs fail checks. A source hash fingerprints the exact code tested. PAPER uses real public data with a hypothetical local account.

## B. Root-cause summary

The earlier three-hour run had 360 market-cycle observations. Its first blockers were 328 stale-candle rejections, one recovery-pending rejection, and two generic numeric rejections. Only 29 passed the data gate. Those 29 all failed the unchanged volatility requirement.

Both numeric rejections were code defects: zero ATR was wrongly treated as an invalid number. Offline fixtures also proved a completed-candle overwrite defect and a repair-before-merge defect. The scanner conflict latch and its report classification needed correction. These additional mechanisms are verified code defects, but they cannot be assigned as causes of the old 328 stale cases without the original raw inputs.

The earlier run saved normalized scanner inputs and health counts, but not original raw REST/WS candle payloads or exact cache snapshots. The cause of its missing rows remains **CAUSE_UNDETERMINED**. A current read returned all 1,269 expected bars for each original final UTC window; overlapping values match the saved candles. That proves present retrievability, not original availability.

At the old shutdown every cache failed required history or freshness; even HYPE with a relatively recent candle retained a full-history gap rejection. A fresh last candle alone cannot restore eligibility.

The new bounded capture lets us compare actual wire-derived public rows, normalized rows, cache, and scanner on identical exchange intervals. A row absent from a covered current REST response is **EXCHANGE_DATA_UNAVAILABLE for that response**. Its underlying cause (quiet trading, delayed publication, or another venue behavior) is still unknown. We have not proved permanent exchange sparsity.

## C. Per-market candle investigation

Old final scanner input used the full UTC strategy history; the streaming health buffer required 300 completed bars. These are different windows. The old cache counts below come from recorded health, not reconstructed cache contents.

| Market | Original raw REST/WS | Old normalized full UTC input | Old cache completed | Missing in old full UTC input | Current retrospective raw/normalized | Historical cause |
|---|---|---:|---:|---:|---:|---|
| par:BRENT | Not captured | 1257 | 288 | 12 | 1269/1269 | CAUSE_UNDETERMINED |
| par:BTC | Not captured | 1262 | 291 | 7 | 1269/1269 | CAUSE_UNDETERMINED |
| par:ETH | Not captured | 1218 | 249 | 51 | 1269/1269 | CAUSE_UNDETERMINED |
| par:EWJ | Not captured | 911 | 0 | 358 | 1269/1269 | CAUSE_UNDETERMINED |
| par:EWY | Not captured | 1246 | 277 | 23 | 1269/1269 | CAUSE_UNDETERMINED |
| par:GOLD | Not captured | 1266 | 297 | 3 | 1269/1269 | CAUSE_UNDETERMINED |
| par:HYPE | Not captured | 1216 | 248 | 53 | 1269/1269 | CAUSE_UNDETERMINED |
| par:SP500 | Not captured | 1263 | 291 | 6 | 1269/1269 | CAUSE_UNDETERMINED |
| par:USDEUR | Not captured | 1241 | 272 | 28 | 1269/1269 | CAUSE_UNDETERMINED |
| par:USDJPY | Not captured | 1142 | 173 | 127 | 1269/1269 | CAUSE_UNDETERMINED |

Latest completed validation: all five columns below are filtered to the same 300-minute exchange interval per market, and facts observed by the last scanner decision. Raw REST and normalized rows match the exact full scanner request; cache remains capacity-limited. WS records cover only the observation period, so missing older WS history is **not observed**, not proof of missing exchange history.

| Market | Raw REST | Normalized | Cache | Scanner in same window | Missing scanner intervals | Final health at shutdown | Cause/action |
|---|---:|---:|---:|---:|---:|---|---|
| par:BRENT | 255 | 255 | 255 | 255 | 45 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:BTC | 299 | 299 | 299 | 299 | 1 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:ETH | 268 | 268 | 268 | 268 | 32 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:EWJ | 0 | 0 | 0 | 0 | 300 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:EWY | 236 | 236 | 236 | 236 | 64 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:GOLD | 168 | 168 | 168 | 168 | 132 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:HYPE | 292 | 292 | 292 | 292 | 8 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:SP500 | 289 | 289 | 289 | 289 | 11 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:USDEUR | 293 | 293 | 293 | 293 | 7 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |
| par:USDJPY | 2 | 2 | 2 | 2 | 298 | QUARANTINED | EXCHANGE_DATA_UNAVAILABLE in covered response; bounded real-data recovery |

Full UTC input acceptance is a separate scope from the 300-minute comparison. Its required history may start earlier. The existing two-minute freshness allowance also means the most recent expected minute can be absent while an earlier, still-fresh continuous 300+ bar input remains valid. The last scanner decision and the later shutdown are different observations.

| Market | Full UTC scanner input rows | Valid rows admitted to frozen feature calculation at last scan | Last scanner data gate |
|---|---:|---:|---|
| par:BRENT | 465 | 0 | FAIL |
| par:BTC | 509 | 509 | PASS |
| par:ETH | 478 | 0 | FAIL |
| par:EWJ | 207 | 0 | FAIL |
| par:EWY | 446 | 0 | FAIL |
| par:GOLD | 378 | 0 | FAIL |
| par:HYPE | 502 | 0 | FAIL |
| par:SP500 | 499 | 0 | FAIL |
| par:USDEUR | 503 | 0 | FAIL |
| par:USDJPY | 212 | 0 | FAIL |

Exact missing timestamps, first/last timestamps, duplicate/conflict counts, OHLCV validity, contiguous tail, close age, covered request windows, rejection strings, and per-stage traces are in each run’s `candle_stage_audit.json`. Raw decoded payloads are in its segment `public_candle_audit.jsonl`. No timestamps or OHLCV values were shifted or fabricated.

For the old missing BTC minute at 1791492480000 (8 October, 20:48 UTC), the original raw REST/WS acceptance and cache-retention answers remain UNKNOWN; scanner receipt is NO. The same timestamp is present in the later retrospective REST result. A later result cannot settle the original cause.

## D. Both numerical failures

| Market | Decision timestamp ms | Exact failing operand | Reproduced source location | Cause and correction | Status |
|---|---:|---|---|---|---|
| par:BRENT | 1791482698439 | ATR_14 = numpy.float64(0.0); close 102.84 | market_regime_scanner.py scan(), old line 146 → base_exchange.py decimal(), line 26 | positive=True incorrectly excludes valid zero ATR; use nonnegative=True and unchanged 0.004 floor | Resolved in recorded replay |
| par:EWY | 1791489298981 | ATR_14 = numpy.float64(0.0); close 175.15 | Same boundary, independently reproduced with EWY tape | Same valid flat-market ATR; classify as low volatility | Resolved in recorded replay |

The exception type was ExchangeError with INVALID_DECIMAL. Decimal conversion succeeded and the value was finite; the positive-only validation then rejected zero. There was no NaN, infinity, missing close, or division-by-zero failure in either reproduction. The original stack was not recorded; the saved input and original source reproduce the exact failing expression. All other required final indicators were finite and positive.

The frozen brain is untouched. Flat genuine bars produce zero true range and zero ATR, which is legal. It still fails the same 0.40% scanner floor. Invalid/negative/nonfinite outputs receive field name, operand type/value, and a specific SCANNER_NUMERIC_INVALID reason; they quarantine only the affected market and cannot enter the watchlist.

Permanent recorded regressions cover BRENT and EWY. Offline fixtures cover invalid numeric operands, local rejection/isolation, and clearing the integrity latch only through a validated snapshot. The feature replay reproduced all 29 old valid ATR fractions exactly, and correctly processed the two zero-ATR cases. No replay generated quotes, fills, profit, or production eligibility.

## E. Modified files

| Path | Functions | Old → new behavior | Reason and regression risk |
|---|---|---|---|
| algo-trading-bot/market_regime_scanner.py | scan | Positive-only ATR → finite nonnegative ATR; named numeric evidence | Correct valid zero ATR without moving any filter; boundary behavior covered by recorded tests |
| algo-trading-bot/exchange/scanner_numeric.py | scanner_number (new) | Generic numeric rejection → specific field/operand rejection | Invalid values remain blocked; no zero substitution |
| algo-trading-bot/exchange/hyperliquid_market_data.py | get_candles, _reconcile_history, ingest, _ingest_validated, publish_public_snapshot, _audit_cache, note_scanner_failure | Premerge gap rejection and silent overwrite → retained real-row merge, completed conflict detection, local latching; public stage evidence | Conflicts can reduce eligibility until resolved, intentionally; open/final behavior, cache cap and isolation tested |
| algo-trading-bot/exchange/candle_audit.py | PublicCandleAudit, merge_candle (new) | No raw stage trace → bounded public JSONL; deterministic merge | Extra local disk writes, capped 256 MiB per segment; no new API polling |
| algo-trading-bot/exchange/hyperliquid_client.py | __init__, post_info | Public candle result unrecorded → optional raw capture after rate-managed read | Account queries excluded; normal client behavior unchanged when audit absent |
| scripts/run_crypto_paper.py | main | Public clients uninstrumented → shared audit sink | Preserve fake-client constructor compatibility; capture-only overhead |
| algo-trading-bot/venue_config.py | module defaults | Always parse dotenv → explicit public-only mode skips dotenv | This bounded job loads no wallet settings; normal activation locks still enforced |
| algo-trading-bot/opportunity_funnel.py | reason_code | Completed conflict UNCLASSIFIED → INVALID_MARKET_DATA | Honest diagnostic denominator; no ranking/signal/risk changes |
| algo-trading-bot/test_candle_integrity_v6.py | 17 collected cases | New labeled regression coverage | Two recorded cases and 15 offline fixture cases; network forbidden |

The scoped before/after patch and hashes are `migration_diff.patch` and `modified_source_manifest.json`. Investigation, test receipts, launchers, capture analyzers and this report were added under this new evidence directory. Legacy dependency inventories were regenerated separately. No original NSE repository file was edited.

## F. Safety verification

- Frozen brain bytes, eight protected methods and 32 protected parameters pass baseline verification. UTC anchor, EMA9/21, ATR formula/floor, spread 15 bps, 300 completed bars and Top-3 are unchanged.
- PAPER/false and protection disabled are asserted before collection. The public-only launcher skips dotenv; no actual signer, private-key derivation, wallet administration, order placement/cancellation, transfer, or protection activation is used.
- Earlier default configuration imports retained legacy dotenv parsing; the corrected public-only path bypasses it. No actual wallet-key value was extracted, printed, or used to sign. Offline SDK tests use isolated ephemeral fixtures, not the funded wallet.
- All recorded sample identities and order counters are checked. Actual exchange orders remain zero; this proves the instrumented PAPER run, not unrelated wallet activity.
- The shared rate manager and safety reserve remain authoritative. Raw capture adds disk writes, not REST requests. Retry/backoff/coalescing and quarantine remain bounded.
- Genuine missing records remain missing. Historical replay and current public feed are labeled separately. No candle, quote, fill, or P&L was invented.
- Source was never edited while a collector observed data. The first attempt was cleanly stopped before the final conflict-latch repair. Prior failed/interrupted evidence is preserved. No recurring monitor was created; the old heartbeat is paused.

## G. Test evidence

Previous baseline: 1,339 passing tests. New coverage: 17 cases. Final total: **1356 passed; 0 failures; 0 errors; 0 skipped**.

Final source hash: `57410d407fe1b0ce2bc2a44f1b1fcbbdac03032cfa7e183b65919dae32a7d7b6`. Test XML SHA256: `2b91b299e6123580a9f4ed10a7a747ac36c7144ea5a068464fdcefde85180c14`. Before/after source hashes match. Phase-0 and strategy-freeze checks pass.

The complete suite includes candle identity/normalization, current/completed boundaries, request-range caps, deduplication, open/final merge, sparse repairs, quarantine/restoration, rate budgets/retries/coalescing, reconnect/subscriptions, production-policy lockout, paper ledger/checkpoint recovery and frozen-brain parity. Every collected test has an evidence classification in `final_test_evidence_classes.json`. LIVE_PUBLIC_READ_ONLY evidence is the captured audit and bounded PAPER feed. ACTUAL_EXCHANGE_EXECUTION = 0.

Earlier failed XML/harness attempts and the earlier 1,354-pass intermediate source receipt remain preserved. They do not certify the final source. Details are in `test_attempt_notes.md` and the retained logs.

## H. PAPER certification

### short_15m

Duration: 902.996 seconds. State: `/Users/adesh/Autonomous Trading Bot - Crypto /runtime/paper/candle-integrity-v6-2026-10-10-short_15m-v2`. Source: `57410d407fe1b0ce2bc2a44f1b1fcbbdac03032cfa7e183b65919dae32a7d7b6`.

Verdict: **FEED_NOT_READY**. 30 observations; 1 healthy; healthy rate 3.33%. Spread passes 1; ATR passes 0; qualified 0; post-selection strategy evaluations 0; signals 0; hypothetical fills 0; actual orders 0.

Final usable markets: 0/10. First rejections: `{'STALE_CANDLE': 21, 'INSUFFICIENT_HISTORY': 7, 'RECOVERY_PENDING': 1, 'ATR_BELOW_SCANNER_FLOOR': 1}`. Unresolved numeric errors: 0. Certification blockers: `['final_usable_market']`.

WebSocket disconnects: 1; corresponding completed reconnect/account barriers: 1. Generic REST reconciliation count is not called a socket reconnect. Close records: `[{'connection_id': 'public-1', 'close_code': 1000, 'close_reason': 'Expired', 'connection_age_seconds': 626.3291970831342, 'client_exception': 'STREAM_DISCONNECTED'}]`.

Socket uptime: 897.694 seconds; median completed connection lifetime: 626.3291970831342 seconds; maximum receiver gap: 1.0344849997200072 seconds. Sampled local IP weight peak: 761; exact unsampled/exchange-wide peak is unknown.

Clean shutdown, primary/backup SQLite integrity, checksums, source identity, health-tape digest, and worker shutdown: `{'source_bound': True, 'clean_shutdown': True, 'checkpoints': True, 'tape_sha256': True, 'sample_identity': True, 'zero_orders': True, 'stopped_workers': True}`.

Last saved PAPER portfolio (its timestamp is recorded): `{'timestamp_ms': 1791620197972, 'cash': '20000', 'unrealized_pnl': '0', 'equity': '20000', 'initial_margin': '0', 'maintenance_margin_estimate': '0', 'order_reservations': '0', 'available_margin': '20000', 'gross_notional': '0', 'realized_pnl': '0', 'fees_paid': '0', 'funding_cashflow': '0', 'collateral': 'USDPR'}`. This is hypothetical local USDPR accounting, separate from the funded wallet. No fill occurred, so active-trade accounting/protection is not certified.

Independent checks versus sequential admissions:

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted/evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 30 | 30 | 0 | 100.00% | 30/30 |
| VALID_MARKET_IDENTITY | 30 | 30 | 0 | 100.00% | 30/30 |
| MARKET_DATA_HEALTHY | 30 | 1 | 29 | 3.33% | 1/30 |
| ENOUGH_HISTORY | 30 | 23 | 7 | 76.67% | 1/1 |
| LIQUIDITY_PASS | 1 | 1 | 0 | 100.00% | 1/1 |
| SPREAD_PASS | 1 | 1 | 0 | 100.00% | 1/1 |
| ATR_PASS | 1 | 0 | 1 | 0.00% | 0/1 |
| SCANNER_QUALIFIED | 30 | 0 | 30 | 0.00% | 0/0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| EXECUTION_PERMISSION | 30 | 0 | 30 | 0.00% | 0/0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0/0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0/0 |

Rejection categories: `{'INFRASTRUCTURE': {'STALE_CANDLE': 21, 'INSUFFICIENT_HISTORY': 7, 'RECOVERY_PENDING': 1}, 'MARKET': {'ATR_BELOW_SCANNER_FLOOR': 1}, 'STRATEGY': {}, 'RISK_ECONOMICS': {}, 'UNCLASSIFIED': {}}`. Later gates not reached are not counted as measured failures.

The three-hour stage was **not started** because the short gate did not support it. It is NOT_TESTED, not a failed three-hour run.

The earlier V6 attempt lasted 354.906 seconds and was cleanly interrupted for the verified latch repair. Its receipt/checkpoints/source proof are preserved; it is not the completed short validation.

## I. Before vs after comparison

| Metric | Old three-hour run | Latest completed V6 run |
|---|---:|---:|
| Duration seconds | 10803.388 | 902.996 |
| Market observations | 360 | 30 |
| Healthy observations | 29 | 1 |
| Healthy % | 8.06 | 3.33 |
| ATR passes | 0 | 0 |
| Scanner-qualified | 0 | 0 |
| Unexplained numeric errors | 2 | 0 |
| Usable at shutdown | 0 | 0 |
| PAPER fills | 0 | 0 |
| Actual exchange orders | 0 | 0 |
| Matched reconnects | 16/16 | 1/1 |

A shorter run and different market conditions are not a controlled performance comparison. Code causality is established by the deterministic zero-ATR and merge fixtures; changes in live healthy percentages cannot be attributed to code alone. The 29 original ATR fractions are identical under recorded replay, including their original units. All 31 replayed feature cases fail the same 0.40% floor: **VALID_DATA_MARKET_CONDITIONS_UNQUALIFIED**. No volatility/VWAP optimization is implied.

## J. Final readiness flags

| Flag | Status |
|---|---|
| STRATEGY_FREEZE | PASS |
| FULL_TEST_SUITE | PASS |
| RAW_CANDLE_AUDIT | PASS |
| REST_CANDLE_INTEGRITY | PASS |
| CANDLE_MERGE_INTEGRITY | PASS |
| NUMERIC_BRENT_RESOLVED | PASS |
| NUMERIC_EWY_RESOLVED | PASS |
| QUARANTINE_READY | PASS |
| TRANSPORT_READY | PASS |
| RATE_BUDGET_READY | PASS |
| RECONCILIATION_READY | PASS |
| WEBSOCKET_CANDLE_INTEGRITY | PASS |
| MARKET_HEALTH_READY | FAIL |
| REST_RECOVERY_READY | FAIL |
| SHORT_PAPER_PASS | FAIL |
| THREE_HOUR_PAPER_PASS | NOT_TESTED |
| FEED_CERTIFIED | FAIL |
| CONTROLLED_EXECUTION_READY | NOT_TESTED |
| PRACTICE_READY | FAIL |
| LIVE_READY | FAIL |

PASS for raw audit/REST integrity means captured rows are correctly accounted for on the new bounded observations; it does not mean missing rows exist or that the old wire payloads were recovered. Merge/quarantine PASS includes deterministic fixtures; funded recovery remains untested. WS PASS, if observed, applies only to captured candle updates, not a continuous 300-bar WS-only history.

MARKET_HEALTH/REST_RECOVERY readiness requires eligible complete fresh history in actual operating evidence. Transport and PAPER reconciliation can pass independently. The funded wallet, signer ownership, nonce/clock and 1x observations from 7 October remain timestamped historical observations; this task performs no new funded preflight. Protection is configured but disabled and untested on exchange. Controlled execution, practice and LIVE remain unapproved.

## K. THE SINGLE NEXT MOST IMPORTANT ACTION FOR TEAM ANCHORIUM

Send the organizer the captured, timestamped public-data evidence for missing par candles and request clarification about current candle publication/completeness. Keep PAPER locked; rerun a fresh short validation after usable real history is available.

A ready-to-review message is saved in organizer_message_draft.md. It has not been sent. For the current blocker, attach the raw public candle tape, exact timestamp traces and request-window audit. Ask whether missing near-current minute candles are expected and what publication delay participants should allow. Do not lower strategy thresholds or enable funded execution to work around missing input.

The existing verified read-only health command is:

```bash
ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false \
  .venv/bin/python scripts/check_practice_health.py \
  --state-directory "/Users/adesh/Autonomous Trading Bot - Crypto /runtime/paper/candle-integrity-v6-2026-10-10-short_15m-v2" --json
```

After clean completion a stale heartbeat is expected; it is not a failed running collector. Do not restart this state as if it were a new certification. A later validation needs fresh state, fresh source-bound tests if source changes, and sufficient actual exchange history.

Primary API reference: [Hyperliquid official candleSnapshot documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#candle-snapshot). It documents the recent 5,000-candle availability limit and HIP-3 coin prefixes; our retrospective 1,269-row windows were inside that limit. This documentation does not establish why particular live minutes were unavailable.
