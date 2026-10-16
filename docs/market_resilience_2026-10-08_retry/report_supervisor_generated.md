# Team Anchorium — market resilience report

## SECTION A — EXECUTIVE VERDICT

**FEED_NOT_READY.** The bounded test sequence has finished.
No actual order or funded activation is authorized. The PAPER ledger is separate from the team wallet.

## SECTION B — ROOT CAUSE

Per-symbol circuit breakers already existed, so a stale market did not inherently block every healthy market. The recurring global warning often meant zero usable markets in the streaming cache. The independent REST scanner could observe newer inputs while that cache stayed old. Successful but stale/incomplete REST responses were not scheduled for automatic repair, and a narrow tail request could not fill an older missing bar. Malformed data for a known symbol could also unnecessarily disconnect the common socket. The old health command hid these distinctions behind one generic message. Genuine zero-usable-market periods still remain degraded.

## SECTION C — FILES CHANGED

| Path | Class/function | Purpose |
|---|---|---|
| algo-trading-bot/exchange/market_health.py | MarketHealthManager / validate_history | One shared quarantine, integrity, retry and restoration state per symbol |
| algo-trading-bot/exchange/hyperliquid_market_data.py | ingest / reconcile_history / market_health / publish_public_snapshot | Symbol-local invalid inputs; bounded real-bar recovery; one worker; share validated REST facts |
| algo-trading-bot/market_regime_scanner.py | scan | Validate inputs before frozen brain; retain full original UTC lookback and ranking |
| algo-trading-bot/market_stream.py | health / poll | Use shared market gates and preserve account reconciliation barrier |
| algo-trading-bot/exchange/paper_operations.py | PaperHealth.write | Partial health plus explicit transport, subscriptions, account, budget and global gates |
| scripts/check_practice_health.py | assess / describe | Human-readable details; 0 healthy/partial, 2 degraded, 1 stale/invalid, 3 stopped |
| algo-trading-bot/exchange/rate_limits.py | report | Public read throttle separate from unobserved account-action budget |
| algo-trading-bot/opportunity_funnel.py | reason_code / observe_scan | Normalize new infrastructure gates; independent and sequential denominators |
| scripts/run_crypto_paper.py | main/finally | Share manager; refresh drained end-state health without changing strategy |
| exchange/market_resilience_certification.py; scripts/market_resilience_report.py | evidence evaluation | New requested usable-feed definition; preserve older three-scan certificate separately |
| scripts/run_feed_soak.py | main | Source-bound resilience report option; original default remains |
| algo-trading-bot/test_market_resilience.py; test_crypto_paper_infrastructure.py | tests/fixtures | New safety/resilience cases and updated fake runtime interface |

## SECTION D — PER-MARKET HEALTH

Each par market has independent candle, book, context, history and tick clocks, reason codes, quarantine state and retry time. All 300 completed bars, real timestamps, chronology, uniqueness, OHLCV, fresh book/context and numeric spread validity must pass. Fresh prices cannot validate stale history. Wide but structurally valid spread is feed data; the original 15 bps strategy admission limit still rejects that market later. Full UTC-anchored scanner input stays unchanged, including warmup. A hole outside the engine's 300-bar buffer remains blocked until the scanner revalidates its full input.

## SECTION E — REST RECOVERY

One worker requests only actual par exchange candles, validates them, deduplicates identical rows, rejects conflicting/future/malformed facts, orders by timestamp and merges without replacing newer WebSocket facts. A short or gapped buffer requires the bounded full 300-bar window; a valid buffer uses a small overlapping tail. Missing bars stay missing. No historical research CSV or generated bar is a fallback.

## SECTION F — QUARANTINE

An invalid symbol is blocked from the brain and entry path. Other validated symbols continue. Pending repair blocks only its selected symbols. Unsuccessful repairs back off from 30 seconds to at most five minutes; successful real data restores eligibility without restarting the bot. Restored eligibility still passes the unchanged scanner, strategy, economics and risk checks.

## SECTION G — HEALTH CHECK OUTPUT

The health command now shows overall state, transport, confirmed/desired subscriptions, duplicates, reconciliation, usable/total markets, each symbol's reasons and completed-bar count, feed readiness, trade readiness and genuine global blockers. PARTIAL_HEALTHY can exit 0 only when all global gates pass and at least one market is valid. All-market failure, accounting failure, unknown account state, unrecovered transport, missing subscriptions or real budget throttling still exit degraded.

Actual saved operating example: see the current stage certification Markdown. It is explicitly timestamped historical evidence, not a current running-process claim.

## SECTION H — WEBSOCKET EXPIRY

Received 1000 / Expired closes pause new entries, then one owner reconnects, restores the fixed subscriptions, reconciles public/account state and revalidates each market. Recovered past errors remain evidence; they are cleared from current global status. Unknown/wrong venue identities still fail closed. Old generic close causes remain unknown.

## SECTION I — RATE-LIMIT SAFETY

The existing single-flight and weighted rate manager remains authoritative. There is one repair worker, no unbounded history download, per-symbol retry deadlines and preserved safety reserves. Public-read throttling is a real global blocker; account-action UNKNOWN in a public-only manager is not proof of exhausted public reads. No new SDK/signing path exists.

## SECTION J — STRATEGY INTEGRITY

Strategy freeze: {"baseline": "nse-working-baseline", "file_count": 1, "method_count": 8, "parameter_count": 32, "passed": true}. signal_brain.py and frozen methods/parameters remain unchanged. ATR 0.40%, spread 15 bps, 300 completed bars, Top-3, UTC VWAP and all management concepts remain unchanged. Every run binds before/after source hashes and checkpoint identities.

## SECTION K — TEST RESULTS

Previous total: 1301. New total: 1339. Added: 38. Failures: 0; errors: 0; skipped: 0. Full source-bound regression passed: True. Phase-0 and production order lockouts are included. Fixtures prove behavior offline and do not certify the funded wallet.

## SECTION L — 30-MINUTE PAPER RESULTS

Runtime 1801.455s; captured socket uptime 1793.307s; disconnects 2; successful reconnect barriers 2; duplicate subscriptions 0.
Final usable markets: ['par:EWY']. Quarantined during run: ['par:BRENT', 'par:BTC', 'par:ETH', 'par:EWJ', 'par:EWY', 'par:GOLD', 'par:HYPE', 'par:SP500', 'par:USDEUR', 'par:USDJPY']. Restored after quarantine: ['par:BTC', 'par:EWY', 'par:GOLD', 'par:SP500']. Partial-health samples: 28. Feed certified: True; blockers: [].
Actual orders: 0; PAPER fills: 0; PAPER accounting: {"timestamp_ms": 1791482098979, "cash": "20000", "unrealized_pnl": "0", "equity": "20000", "initial_margin": "0", "maintenance_margin_estimate": "0", "order_reservations": "0", "available_margin": "20000", "gross_notional": "0", "realized_pnl": "0", "fees_paid": "0", "funding_cashflow": "0", "collateral": "USDPR"}.
Both checkpoint checks: {"paper.sqlite": {"integrity": "ok", "checksum_matches": true, "clean_shutdown": true, "source_hash": "c0f496204be5aedd5acbacb8977cced15944066d12bd62968e7c987241431d1a"}, "backups/paper-latest.sqlite": {"integrity": "ok", "checksum_matches": true, "clean_shutdown": true, "source_hash": "c0f496204be5aedd5acbacb8977cced15944066d12bd62968e7c987241431d1a"}}. Health tape digest match: True.
Maximum receiver gap: 1.039s; maximum sampled local IP weight: 909. This is not exchange-wide IP measurement.
Actual close records: [{"connection_id": "public-1", "close_code": 1000, "close_reason": "Expired", "connection_age_seconds": 699.3466071668081, "client_exception": "STREAM_DISCONNECTED"}, {"connection_id": "public-2", "close_code": 1000, "close_reason": "Expired", "connection_age_seconds": 656.3588853748515, "client_exception": "STREAM_DISCONNECTED"}].

Gated three-hour follow-up: 10803.388s, 360 observations, FEED_NOT_READY. 16 closes; 17 successful reconnect barriers; 185 REST reconciliations includes startup. Receiver gap 1.857s; socket uptime 10766.030s. Blockers: ['final_usable_market'].

## SECTION M — BEFORE VS AFTER

Requested cumulative old baseline: 370 observations / 49 healthy / 7 spread / 0 ATR / 0 qualified. Its actual three-hour segment: 360 / 48 / 7 / 0 / 0. Previous instrumented source: 360 / 34 / 6 / 0 / 0. These denominators are separate. Public conditions occur at different times; changes in market availability cannot be attributed to code alone.

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted/evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 360 | 360 | 0 | 100.00% | 360/360 |
| VALID_MARKET_IDENTITY | 360 | 360 | 0 | 100.00% | 360/360 |
| MARKET_DATA_HEALTHY | 360 | 29 | 331 | 8.06% | 29/360 |
| ENOUGH_HISTORY | 360 | 360 | 0 | 100.00% | 29/29 |
| LIQUIDITY_PASS | 29 | 29 | 0 | 100.00% | 29/29 |
| SPREAD_PASS | 29 | 29 | 0 | 100.00% | 29/29 |
| ATR_PASS | 29 | 0 | 29 | 0.00% | 0/29 |
| SCANNER_QUALIFIED | 360 | 0 | 360 | 0.00% | 0/0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| EXECUTION_PERMISSION | 360 | 0 | 360 | 0.00% | 0/0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0/0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0/0 |

First rejection categories (one first rejection per market-cycle): {"INFRASTRUCTURE": {"STALE_CANDLE": 328, "RECOVERY_PENDING": 1, "INVALID_MARKET_DATA": 2}, "MARKET": {"ATR_BELOW_SCANNER_FLOOR": 29}, "STRATEGY": {}, "RISK_ECONOMICS": {}, "UNCLASSIFIED": {}}. All observed failures can overlap and are retained in the certificate. Strategy/risk stages not reached are not counted as passed.

| Market | Scanner windows | Healthy | Failed | Healthy % | Final state |
|---|---:|---:|---:|---:|---|
| par:BRENT | 36 | 5 | 31 | 13.89% | QUARANTINED |
| par:BTC | 36 | 3 | 33 | 8.33% | QUARANTINED |
| par:ETH | 36 | 1 | 35 | 2.78% | QUARANTINED |
| par:EWJ | 36 | 0 | 36 | 0.00% | QUARANTINED |
| par:EWY | 36 | 1 | 35 | 2.78% | QUARANTINED |
| par:GOLD | 36 | 3 | 33 | 8.33% | QUARANTINED |
| par:HYPE | 36 | 5 | 31 | 13.89% | QUARANTINED |
| par:SP500 | 36 | 9 | 27 | 25.00% | QUARANTINED |
| par:USDEUR | 36 | 1 | 35 | 2.78% | QUARANTINED |
| par:USDJPY | 36 | 1 | 35 | 2.78% | QUARANTINED |

Transport/source and quarantine details are in the stage JSON. Old baseline reconnect successes, duplicate subscriptions and unrecorded close codes remain unknown. Baseline 23 disconnect events included 2 heartbeat and 6 REST retry failures. Instrumented previous run had 16 captured Expired closes, zero heartbeat/REST failures. A trade increase is not the success criterion.

## SECTION N — FINAL FLAGS

```ini
STRATEGY_FREEZE = PASS
TESTS_PASS = TRUE
TRANSPORT_READY = TRUE
SUBSCRIPTIONS_READY = TRUE
REST_RECOVERY_READY = TRUE
MARKET_HEALTH_READY = TRUE
QUARANTINE_READY = OBSERVED
HEALTH_REPORT_READY = TRUE
FEED_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
PROTECTION_ENABLED = false
```

Funded LONG/SHORT, exchange protection acceptance, funded recovery and accounting certification are not performed. The 7 October read-only account/signer checks are timestamped local observations, not fresh execution readiness. Future funded testing requires a fresh preflight and separate explicit user activation.

## SECTION O — EXACT NEXT ACTION

Review the specific failed market-data gates with the organizer using the saved real timestamps and gaps; retain PAPER and unchanged strategy thresholds.
