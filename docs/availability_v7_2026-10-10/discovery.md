# V7 repository discovery before modification

| File | Functions/classes | Existing capability | Required extension |
|---|---|---|---|
| algo-trading-bot/exchange/hyperliquid_market_data.py | get_candles, parse_candle, reconcile_history, ingest, market_health | Native par validation; completed/open boundaries; genuine merge; one repair worker | Observe per-source availability; exact missing timestamps; recovery outcomes |
| algo-trading-bot/exchange/market_health.py | MarketHealthManager, validate_history, due/finish_recovery | Independent quarantine; 300-bar cache; 30s–5m backoff; pending coalescing | Optional measured delay hints and near-ready ordering, same safety bounds |
| algo-trading-bot/exchange/candle_audit.py | PublicCandleAudit, merge_candle | 256 MiB public-only raw/normalized/cache tape; completed conflicts | Reuse tape for monitor recovery provenance |
| algo-trading-bot/exchange/feed_transport.py | FeedTransportHealth | Exact subscription confirmations, heartbeat/receiver/socket metrics | Reuse unchanged |
| algo-trading-bot/exchange/rate_limits.py | HyperliquidRateLimitManager | Shared weighted public reads; reserves, retries, coalescing | Reuse unchanged; expose deferrals |
| algo-trading-bot/market_regime_scanner.py | scan | Full UTC strategy lookback; frozen features; rejection diagnostics | Preserve; observe requested full history through native adapter |
| algo-trading-bot/market_stream.py | poll | Account barrier and per-market health reporting | Include bounded monitor dashboard summary |
| algo-trading-bot/exchange/paper_operations.py | PaperHealth.write | Atomic heartbeat with reasons, account/transport/rate gates | Explicit candle readiness and signal flags |
| scripts/check_practice_health.py | describe, assess_value | Human-readable health and nonzero stopped/degraded exits | Availability table, latency/censoring and exact queue reasons |
| scripts/run_crypto_paper.py | main | Shared public budget, source-bound checkpoint and bounded PAPER | Share native-only monitor and persist independent availability snapshot |
| scripts/run_feed_soak.py | main | Bounded source-bound receipt and tape | Reuse single short run; no 3h auto-launch |
| algo-trading-bot/venue_config.py | require_paper_migration | PAPER/false/testnet/par and public-only dotenv bypass | Explicit production native-source-only gate |

V6 is historical, not present exchange/account proof. Source snapshots precede edits. No wallet file was opened. No process was terminated. No automation is created.
