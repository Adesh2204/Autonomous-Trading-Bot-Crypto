# Pre-edit architecture audit

Previous tested source: `8a02c9daf22cc77a4316d3360bbc8a377c12ba945be68ea3f9eccfa832942b66`. Completed old run and its final A–P report are preserved. No active collector remains in that bounded sequence.

| File | Class/function | Current behavior | Problem/decision |
|---|---|---|---|
| exchange/feed_transport.py | FeedTransportHealth | Separate ping/pong, close frames and subscription identities | Working; preserve |
| exchange/hyperliquid_market_data.py | ParMarketDataEngine._run_owned/reconcile_history | One receiver plus one REST worker; retries exceptions per symbol | No periodic recovery for valid-but-stale/incomplete response; narrow overlap cannot fill older internal gaps |
| exchange/hyperliquid_market_data.py | ingest/get_observations | Independent symbol clocks; malformed candle/context raises globally | Known-symbol invalid data may disconnect healthy markets |
| market_stream.py | health/poll | Independent freshness clocks and symbol circuit breakers | Incomplete integrity validation; no durable runtime quarantine/restoration transitions; stream cache separate from REST scanner |
| market_regime_scanner.py | scan | REST each symbol, existing stale/history checks then frozen brain | Existing normalized candle checks occur only inside brain adapter; data health not shared with streaming health |
| exchange/paper_operations.py | PaperHealth.write | No healthy stream market yields global warning | Missing explicit transport/account/budget gates, per-market details and partial-health state |
| scripts/check_practice_health.py | assess/main | Only JSON exit/reason | No usable-market, subscriptions or quarantine explanation |
| risk/circuit_breakers.py | update_symbols/entry_reasons | Per-symbol entry blocks plus separate global reasons | Working; preserve |
| exchange/rate_limits.py | read/reserve_info/report | Single-flight public requests, weighted budgets, reserves/backoff | Working; reuse, do not interpret account-action UNKNOWN as public failure |
| opportunity_funnel.py | _summary | Independent evaluated counts and sequential admissions/categories | Working; preserve distinct denominators |
| exchange/paper_checkpoint.py | save/load/backup | Checksummed source/config state and backups | Working; preserve |

Plan: extend the existing engine, stream, scanner and local health writer with one shared thread-safe MarketHealthManager. Keep a single repair worker and the existing rate limiter. Preserve full UTC-anchored REST scanner lookback; the engine keeps its existing 300-completed-plus-open buffer. Numeric/structural spread validity belongs to feed health; 15 bps and 0.40% ATR remain unchanged market-admission filters. A fresh BBO/context cannot validate stale candles. No native fallback, research CSV, interpolation or signed action.

The baseline report must show both cumulative 370/49/7/0 and actual comparable three-hour 360/48/7/0. The immediately previous instrumented run was 360/34/6/0 and recovered 16 captured peer Expired closes. A feed fix cannot manufacture venue candles.
