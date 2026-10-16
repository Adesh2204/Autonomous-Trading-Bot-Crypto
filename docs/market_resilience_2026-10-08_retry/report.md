# Team Anchorium — market resilience report

## SECTION A — EXECUTIVE VERDICT

The bot collected and checked real public data safely, but the completed three-hour feed certificate is FEED_NOT_READY. The 30-minute stage passed. During three hours, 29 of 360 scanner market checks had usable data; all 29 failed the unchanged ATR floor. There were no qualified markets, no simulated fills and no actual orders. At shutdown, no market had fully usable inputs. The infrastructure evidence does not establish a trading profit or funded-practice readiness.

**FEED_NOT_READY.** The bounded test sequence has finished.
No actual order or funded activation is authorized. The PAPER ledger is separate from the team wallet.

## SECTION B — ROOT CAUSE

The three-hour completion blocker is `final_usable_market`: all ten markets were quarantined at shutdown. Book/context timestamps were fresh at that snapshot, while completed candle history was short/stale or had a full-strategy history gap. Sparse trading, provider delay and adapter effects are not causally distinguished by this run. Two separate `INVALID_DECIMAL` scanner rejections also remain unexplained; they are documented below and must not be blamed on the venue without a raw-input audit.

Per-symbol circuit breakers already existed, so a stale market did not inherently block every healthy market. The recurring global warning often meant zero usable markets in the streaming cache. The independent REST scanner could observe newer inputs while that cache stayed old. Successful but stale/incomplete REST responses were not scheduled for automatic repair, and a narrow tail request could not fill an older missing bar. Malformed data for a known symbol could also unnecessarily disconnect the common socket. The old health command hid these distinctions behind one generic message. Genuine zero-usable-market periods still remain degraded.

## SECTION C — FILES CHANGED

Completion added only documentation and an offline artifact-audit helper (`completion_audit.py/.json`). The runtime source and the hashed supervisor/report writer were not changed. The original supervisor-generated report, summary, stage certificates, failed environment attempt and earlier tests/runs remain preserved. The 1,339-test receipt covers the runtime source; the separate completion helper validates saved artifacts with assertions and does not run an exchange client.

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

Final per-market input evidence (historical shutdown snapshot):

| Market | Completed bars | Completed candle close age, seconds | Reasons |
|---|---:|---:|---|
| par:BRENT | 288 | 1010.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:BTC | 291 | 710.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:ETH | 249 | 3350.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:EWJ | 0 | Unknown | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:EWY | 277 | 1670.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:GOLD | 297 | 470.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:HYPE | 248 | 110.937 | STRATEGY_CANDLE_GAP_OR_DUPLICATE |
| par:SP500 | 291 | 650.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:USDEUR | 272 | 1970.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |
| par:USDJPY | 173 | 7910.937 | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE |

The candle clock is the one-minute bar start plus 60 seconds, so the age is measured from its close. Bar counts come from the bounded streaming cache. The scanner separately validates its unchanged full UTC input. A fresh latest candle alone cannot repair an earlier gap.

Each par market has independent candle, book, context, history and tick clocks, reason codes, quarantine state and retry time. All 300 completed bars, real timestamps, chronology, uniqueness, OHLCV, fresh book/context and numeric spread validity must pass. Fresh prices cannot validate stale history. Wide but structurally valid spread is feed data; the original 15 bps strategy admission limit still rejects that market later. Full UTC-anchored scanner input stays unchanged, including warmup. A hole outside the engine's 300-bar buffer remains blocked until the scanner revalidates its full input.

## SECTION E — REST RECOVERY

One worker requests only actual par exchange candles, validates them, deduplicates identical rows, rejects conflicting/future/malformed facts, orders by timestamp and merges without replacing newer WebSocket facts. A short or gapped buffer requires the bounded full 300-bar window; a valid buffer uses a small overlapping tail. Missing bars stay missing. No historical research CSV or generated bar is a fallback.

## SECTION F — QUARANTINE

The original certificate records only adjacent sampled QUARANTINED-to-HEALTHY transitions (long run: SP500). The completion audit also allows an intervening RECOVERING sample: {"par:EWY": 3, "par:BRENT": 10, "par:BTC": 4, "par:HYPE": 4, "par:SP500": 12, "par:USDEUR": 1, "par:GOLD": 2, "par:ETH": 1}. These are recorded transitions, not distinct sustained recoveries. Large internal manager restoration counters also include ordinary repair state changes and are not used as recovery certification.

An invalid symbol is blocked from the brain and entry path. Other validated symbols continue. Pending repair blocks only its selected symbols. Unsuccessful repairs back off from 30 seconds to at most five minutes; successful real data restores eligibility without restarting the bot. Restored eligibility still passes the unchanged scanner, strategy, economics and risk checks.

## SECTION G — HEALTH CHECK OUTPUT

The completed health file is marked STOPPED. Running the CLI after its 120-second age limit returns PAPER_HEARTBEAT_STALE (exit 1); this is expected for a finished collector. Receipt timestamps, exit 0, stopped workers, released ownership locks and clean checksummed checkpoints verify planned completion. The retained final transport snapshot describes the last operating socket, not a socket still running.

The health command now shows overall state, transport, confirmed/desired subscriptions, duplicates, reconciliation, usable/total markets, each symbol's reasons and completed-bar count, feed readiness, trade readiness and genuine global blockers. PARTIAL_HEALTHY can exit 0 only when all global gates pass and at least one market is valid. All-market failure, accounting failure, unknown account state, unrecovered transport, missing subscriptions or real budget throttling still exit degraded.

Actual saved operating example: see the current stage certification Markdown. It is explicitly timestamped historical evidence, not a current running-process claim.

## SECTION H — WEBSOCKET EXPIRY

The audited long run has 16 captured 1000 / Expired closes and 16 corresponding completed reconnect/subscription/account-barrier sequences. There are 18 total PAPER account reconciliations: one startup, 16 after socket reconnects and one further non-socket reconciliation. The original generated reconnect field of 17 counted both kinds of post-startup barriers; its certificate and supervisor report are preserved. 185 REST reconciliation events are reported separately. Median completed socket lifetime: 632.2255349375773 seconds. The cause of the Expired policy itself is unknown.

Received 1000 / Expired closes pause new entries, then one owner reconnects, restores the fixed subscriptions, reconciles public/account state and revalidates each market. Recovered past errors remain evidence; they are cleared from current global status. Unknown/wrong venue identities still fail closed. Old generic close causes remain unknown.

## SECTION I — RATE-LIMIT SAFETY

Long-run public read observations: maximum sampled local IP weight 1079; final pending reads 0; final public_read_blocked false; historical RATE_LIMITED events 18; deferred recovery events 2; retry-budget exhaustion 0. Resolved historical limit/defer events remain in evidence and are not final failures. Samples do not establish the exact peak or exchange-wide shared-IP usage. RATE_LIMITED records alone do not distinguish a local limiter rejection from an upstream response.

The existing single-flight and weighted rate manager remains authoritative. There is one repair worker, no unbounded history download, per-symbol retry deadlines and preserved safety reserves. Public-read throttling is a real global blocker; account-action UNKNOWN in a public-only manager is not proof of exhausted public reads. No new SDK/signing path exists.

## SECTION J — STRATEGY INTEGRITY

Strategy freeze: {"baseline": "nse-working-baseline", "file_count": 1, "method_count": 8, "parameter_count": 32, "passed": true}. signal_brain.py and frozen methods/parameters remain unchanged. ATR 0.40%, spread 15 bps, 300 completed bars, Top-3, UTC VWAP and all management concepts remain unchanged. Every run binds before/after source hashes and checkpoint identities.

## SECTION K — TEST RESULTS

Earlier focused failures and the previous 1,335-test source receipt remain in the original 8 October evidence directory. The final 1,339-test XML digest and before/after source hashes were independently verified again at completion, followed by fresh local Phase-0 and strategy-freeze checks. No broader test rerun or production change was needed.

Previous total: 1301. New total: 1339. Added: 38. Failures: 0; errors: 0; skipped: 0. Full source-bound regression passed: True. Phase-0 and production order lockouts are included. Fixtures prove behavior offline and do not certify the funded wallet.

## SECTION L — 30-MINUTE PAPER RESULTS

Actual receipt times in IST: short run 2026-10-08T22:59:46+05:30 to 2026-10-08T23:29:48+05:30; long run 2026-10-08T23:29:48+05:30 to 2026-10-09T02:29:52+05:30. The long run recorded 98 usable-feed health samples out of 355 saved samples (353 RUNNING, 2 STOPPED), with 360 independent market-cycle scanner observations. These denominators differ. PAPER cash/equity stayed 20,000 USDPR; realized/unrealized P&L, fees, funding, positions, fills and actual orders were zero. Both stages' primary and backup checkpoints, tape digests, source hashes and clean shutdowns passed independent verification. The short run passed the latest feed definition; its older three-scan criterion failed. The long run met the older sustained-window criterion for SP500 (three windows), but both its latest and legacy certificates fail their final-market requirement.

Runtime 1801.455s; captured socket uptime 1793.307s; disconnects 2; successful reconnect barriers 2; duplicate subscriptions 0.
Final usable markets: ['par:EWY']. Quarantined during run: ['par:BRENT', 'par:BTC', 'par:ETH', 'par:EWJ', 'par:EWY', 'par:GOLD', 'par:HYPE', 'par:SP500', 'par:USDEUR', 'par:USDJPY']. Restored after quarantine: ['par:BTC', 'par:EWY', 'par:GOLD', 'par:SP500']. Partial-health samples: 28. Feed certified: True; blockers: [].
Actual orders: 0; PAPER fills: 0; PAPER accounting: {"timestamp_ms": 1791482098979, "cash": "20000", "unrealized_pnl": "0", "equity": "20000", "initial_margin": "0", "maintenance_margin_estimate": "0", "order_reservations": "0", "available_margin": "20000", "gross_notional": "0", "realized_pnl": "0", "fees_paid": "0", "funding_cashflow": "0", "collateral": "USDPR"}.
Both checkpoint checks: {"paper.sqlite": {"integrity": "ok", "checksum_matches": true, "clean_shutdown": true, "source_hash": "c0f496204be5aedd5acbacb8977cced15944066d12bd62968e7c987241431d1a"}, "backups/paper-latest.sqlite": {"integrity": "ok", "checksum_matches": true, "clean_shutdown": true, "source_hash": "c0f496204be5aedd5acbacb8977cced15944066d12bd62968e7c987241431d1a"}}. Health tape digest match: True.
Maximum receiver gap: 1.039s; maximum sampled local IP weight: 909. This is not exchange-wide IP measurement.
Actual close records: [{"connection_id": "public-1", "close_code": 1000, "close_reason": "Expired", "connection_age_seconds": 699.3466071668081, "client_exception": "STREAM_DISCONNECTED"}, {"connection_id": "public-2", "close_code": 1000, "close_reason": "Expired", "connection_age_seconds": 656.3588853748515, "client_exception": "STREAM_DISCONNECTED"}].

Gated three-hour follow-up: 10803.388s, 360 observations, FEED_NOT_READY. 16 closes; 16 successful socket reconnects with completed PAPER account barriers; one additional non-socket account reconciliation; 185 REST reconciliations includes startup. Receiver gap 1.857s; socket uptime 10766.030s. Blockers: ['final_usable_market'].

## SECTION M — BEFORE VS AFTER

Comparison counts, kept in their original run scopes:

| Scope | Market-cycle observations | Valid data | Valid-data % | Spread passes | ATR passes | Qualified |
|---|---:|---:|---:|---:|---:|---:|
| Old cumulative (includes earlier five minutes) | 370 | 49 | 13.24% | 7 | 0 | 0 |
| Old actual three-hour segment | 360 | 48 | 13.33% | 7 | 0 | 0 |
| Previous instrumented three hours | 360 | 34 | 9.44% | 6 | 0 | 0 |
| Current short run | 60 | 9 | 15.00% | 9 | 0 | 0 |
| Current three hours | 360 | 29 | 8.06% | 29 | 0 | 0 |

This run did not show higher overall scanner data availability. The infrastructure fixes and safe partial-health behavior were exercised, while actual usable input availability remained intermittent. Different times/market conditions prevent a causal performance comparison.

Two infrastructure/numeric rejections: BRENT at decision_ms 1791482698439 and EWY at 1791489298981, both INVALID_DECIMAL. Their traces had fresh candles and an observed frozen-brain evaluation, so this is not proof that the exchange supplied a malformed price. Causes remain UNDETERMINED. See completion_audit.json for exact recorded evidence. These checks failed closed. Strategy, risk and economics stages that were not reached remain unvalidated by this no-trade run.

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

Flags refer to completed PAPER observations, not a currently running process or funded readiness. The health manager was exercised successfully, but zero usable inputs at shutdown makes MARKET_HEALTH_READY and FEED_READY false. The last actual-account read was 2026-10-07T15:17:28.920851+00:00 (7 October, 20:47 IST); the local signer/nonce ownership check began at epoch_ms 1791386276990 (about 20:48 IST), on the current host/OS user only. Neither is a fresh funded preflight. This sequence did not refresh the funded wallet or signer, allocate a nonce, sign, reconfigure leverage or test exchange protection. The heartbeat is PAUSED after bounded completion.

```ini
STRATEGY_FREEZE = PASS
TESTS_PASS = TRUE
TRANSPORT_READY = TRUE
SUBSCRIPTIONS_READY = TRUE
REST_RECOVERY_READY = TRUE
MARKET_HEALTH_SYSTEM_VERIFIED = TRUE
MARKET_HEALTH_READY = FALSE
REPEATED_USABLE_FEED_OBSERVED = TRUE
RUNTIME_RUNNING = FALSE
QUARANTINE_READY = OBSERVED
HEALTH_REPORT_READY = TRUE
FEED_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
PROTECTION_ENABLED = false
PROTECTION_ACCEPTANCE_TESTED = FALSE
FUNDED_LONG_CERTIFIED = FALSE
FUNDED_SHORT_CERTIFIED = FALSE
FUNDED_RECOVERY_CERTIFIED = FALSE
```

Funded LONG/SHORT, exchange protection acceptance, funded recovery and accounting certification are not performed. The 7 October read-only account/signer checks are timestamped local observations, not fresh execution readiness. Future funded testing requires a fresh preflight and separate explicit user activation.

## SECTION O — EXACT NEXT ACTION

Perform one read-only raw-response-versus-adapter audit of the saved candle gaps and INVALID_DECIMAL rejections before another feed certification. Keep PAPER/false, protection disabled and the strategy thresholds unchanged; no new run or funded activation has been started.
