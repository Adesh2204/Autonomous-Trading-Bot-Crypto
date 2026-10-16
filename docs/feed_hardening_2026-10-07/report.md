# Anchorium — completed feed-hardening report

## A — Executive verdict

**FEED_NOT_READY.** The three-hour run finished cleanly. Transport fixes worked, but fresh, valid candle inputs remained inconsistent. There were zero actual orders and zero PAPER fills. This is no evidence of strategy profitability.

## B — Root causes

Proven client problems were synchronous REST work blocking receiving/pings, an open candle reducing the completed-history buffer to 299, discarded close-frame details, and REST failures unnecessarily restarting sockets. The first short run also caught book-acknowledgement default expansion and a stale cancellation flag; both were corrected. Missing or stale venue candles cannot be fabricated. Old generic closes and retry failures have unknown underlying causes.

## C — Files modified

Detailed file/function/before/after mapping is preserved in root_cause.md. Changes cover feed_transport.py, hyperliquid_market_data.py, hyperliquid_client.py, rate_limits.py, market_stream.py, opportunity_funnel.py, feed_certification.py, run_feed_soak.py, feed_certification_report.py, run_crypto_paper.py and associated fixtures/tests. Strategy formulas and thresholds were untouched.

## D — WebSocket fix

One socket owner receives while one bounded REST worker repairs. Generations reject old callbacks. Official JSON ping/pong and the original deadlines remain. Subscription identities account only for observed default fields.

## E — Heartbeat fix

Maximum recorded receiver gap: 1.032 seconds. Heartbeat-stale events: 0. Per-market activity does not substitute for the transport pong. Host gaps are evidence of processing/clock gaps, not proof of venue failure.

## F — REST and rate budget

Zero deferred REST failures and zero retry-budget exhaustion. Maximum sampled local trailing-minute weight: 792; configured cap 1200, safety reserve 120. Maximum read duration: 0.944 seconds. Public single-flight reads coalesced 2 duplicates. The public manager's account-action state UNKNOWN does not mean public reads exhausted their budget. External consumers of this IP are unmeasured.

## G — Per-market health

| Market | Evaluated | Healthy | Failed | Healthy % | Best consecutive |
|---|---:|---:|---:|---:|---:|
| par:BRENT | 36 | 11 | 25 | 30.56% | 2 |
| par:BTC | 36 | 4 | 32 | 11.11% | 2 |
| par:ETH | 36 | 5 | 31 | 13.89% | 2 |
| par:EWJ | 36 | 0 | 36 | 0.00% | 0 |
| par:EWY | 36 | 3 | 33 | 8.33% | 1 |
| par:GOLD | 36 | 1 | 35 | 2.78% | 1 |
| par:HYPE | 36 | 2 | 34 | 5.56% | 1 |
| par:SP500 | 36 | 6 | 30 | 16.67% | 2 |
| par:USDEUR | 36 | 1 | 35 | 2.78% | 1 |
| par:USDJPY | 36 | 1 | 35 | 2.78% | 1 |

## H — Reconnect and resubscribe

16 received closes, all code 1000 / Expired. 16 successful reconnect/account barriers after the initial startup. 17 REST/account reconciliations includes startup and must not be called 17 reconnects. All 40 subscriptions confirmed after recovery; zero duplicates. Median completed connection lifetime 655.175 seconds. Captured socket uptime 10762.922/10801.810 seconds; this is transport uptime, not usable-data uptime. Received peer closes establish Expired for this run; they do not explain uninstrumented old closes.

## I — Strategy integrity

Strategy freeze PASS: one file byte-identical, eight frozen methods and 32 parameters. UTC convention, ATR 0.40%, spread 15 bps, 300 completed bars and Top-3 unchanged. Source stayed identical from receipt start to finish.

## J — Tests

Full source-bound offline regression: 1301 tests, 0 failures, 0 errors, 0 skipped. Phase-0 12 checks PASS and freeze PASS. XML digest verified. Earlier failing fixtures, failed short soak and previous successful source receipts are preserved. Synthetic tests cannot certify a funded wallet.

## K — Short soak

Corrected short soak: 902.015 seconds, 30 observations, 8 healthy windows, 1 spread pass, 0 ATR passes, 0 trades. All non-market engineering gates passed; full feed certificate failed because sustained/current valid markets were absent. One Expired close recovered. The first failed 18-second soak remains separate.

## L — Three-hour results

10801.810 seconds, 36 scans, 360 market observations. 34 healthy windows, 6 spread passes, zero ATR passes or qualified markets. PAPER cash/equity 20000 USDPR; P&L, fees and funding zero because no fills occurred. Both SQLite databases, checksums, source identities and clean shutdown PASS. Health tape digest PASS. This ledger is separate from the funded team wallet.

## M — Before/after funnel

The earlier 370/49 totals include a five-minute segment. Compare actual three-hour 360/48 against this new 360/34; differences in venue conditions and time windows prevent attributing market availability changes to code alone.

| Check | Old evaluated/pass/fail | New evaluated/pass/fail | New pass % | New sequential survivors |
|---|---:|---:|---:|---:|
| MARKET_DATA_HEALTHY | 360/48/312 | 360/34/326 | 9.44% | 34 |
| ENOUGH_HISTORY | 360/360/0 | 360/360/0 | 100.00% | 34 |
| LIQUIDITY_PASS | 48/48/0 | 34/34/0 | 100.00% | 34 |
| SPREAD_PASS | 48/7/41 | 34/6/28 | 17.65% | 6 |
| ATR_PASS | 48/0/48 | 34/0/34 | 0.00% | 0 |
| SCANNER_QUALIFIED | 360/0/360 | 360/0/360 | 0.00% | 0 |

Independent ATR observations number 34; sequentially only six survive spread and none survive ATR. Downstream strategy/risk/economics stages were not reached, not passed.

First-block categories (mutually exclusive): {"INFRASTRUCTURE": {"STALE_CANDLE": 318, "INVALID_MARKET_DATA": 8}, "MARKET": {"ATR_BELOW_SCANNER_FLOOR": 34}, "STRATEGY": {}, "RISK_ECONOMICS": {}, "UNCLASSIFIED": {}}. All observed failures can overlap and are retained in the detailed certificate.

Old: 23 disconnect events (15 generic, 2 heartbeat, 6 REST retries). New: 16 Expired peer closes, 0 heartbeat failures, 0 REST retries. Baseline successful reconnect and duplication timing were not fully instrumented and remain unknown.

## N — Blockers

No market achieved three consecutive valid scheduled scanner data windows, and no market was valid at the final operating sample. Feed remains unapproved. Protection is configured but disabled and untested. LONG/SHORT, funded recovery and controlled execution remain untested.

## O — Next action

Implement the newly requested shared per-market quarantine/recovery and human-readable health upgrade, preserving these completed source-bound receipts.

## P — Flags

```ini
STRATEGY_FREEZE = PASS
TESTS_PASS = TRUE
TRANSPORT_ENGINEERING_PASS = TRUE
FEED_READY = FALSE
PROTECTION_TESTED = FALSE
LONG_TESTED = FALSE
SHORT_TESTED = FALSE
FUNDED_RECOVERY_TESTED = FALSE
CONTROLLED_EXECUTION_READY = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
```

Account observations were read-only at 20:47 IST on 7 October: 1,000,000 USDPR, unified, approved agent, ten 1x CROSS markets and flat. Local signer/nonce checks around 20:48 IST apply only to this host/user, with no signature or allocated nonce. These old observations are not fresh execution preflight. A fresh preflight and explicit human activation are required for future controlled funded testing.
