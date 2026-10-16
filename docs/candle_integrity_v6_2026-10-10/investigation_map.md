| File | Function | Input | Output | Potential failure | Evidence |
|---|---|---|---|---|---|
| exchange/hyperliquid_client.py | post_info | public query/parameters | REST result | request/response lacks raw trace | source inspection |
| exchange/hyperliquid_market_data.py | get_candles/parse_candle | raw REST rows | completed sorted Candle rows | range, identity, duplicate, incomplete | source plus scanner tape |
| exchange/hyperliquid_market_data.py | _ingest_validated | WS candle events | 300+1 cache | completed overwrite, delayed facts | source; regression required |
| exchange/hyperliquid_market_data.py | _reconcile_history | REST plus retained cache | merged cache | premerge gap rejection, conflict | source; regression required |
| exchange/hyperliquid_market_data.py | publish_public_snapshot | full UTC scanner facts | bounded stream cache | history distinction/overwrites | source inspection |
| exchange/market_health.py | validate_history/evaluate/due | cache and clocks | isolated quarantine/retry | missing full history, stale clocks | old health tape |
| candle_normalizer.py | candles_to_frame | completed Candle list | UTC float frame | nonfinite float conversion | source inspection |
| frozen_strategy.py | evaluate_candles | UTC frame | unchanged enriched brain | integration boundary | saved replay |
| market_regime_scanner.py | scan | full UTC history plus context/book | diagnostics/watchlist | zero ATR rejected positive | two exact saved replays |
| exchange/rate_limits.py | read | weighted public requests | bounded retry/coalesced result | budget exhaustion | old public_requests.sqlite |
| market_stream.py | snapshot/run | engine health | scoped market/global risk state | global vs local gates | old health tape |
| exchange/paper_checkpoint.py | save/load | fill ledger/account state | SQLite recovery | not a candle archive | checkpoint schema |
| candle_builder.py/history_service.py | legacy only | NSE ticks/history | NSE frame/cache | not active crypto candle input | active import path inspection |