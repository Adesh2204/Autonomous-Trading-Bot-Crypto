# C — BTC/EWY market readiness

Report time 2026-10-19T03:25:21.150000+00:00; source `56ee079f7b8403811674d429aff3b9143a1810290bdd9a23f319b7cedd47170c`. Snapshot ages remain explicit. Books and target scenarios are not an execution permit.

| Market | Raw / valid / contiguous (5000-minute request) | Latest completed ms | Age ms at report | Warmup | Fresh | Decision | Book-only cap TEST USDP | Authorized |
|---|---:|---:|---:|---|---|---|---:|---:|
| pas:BTC | 281 / 281 / 281 | 1792354620000 | 25701150 | False | False | NO_TRADE / UPSTREAM_DATA_UNAVAILABLE | 49.522200 | 0 |
| pas:EWY | 3688 / 3688 / 3688 | 1792374960000 | 5361150 | True | False | NO_TRADE / UPSTREAM_DATA_UNAVAILABLE | 49.86558 | 0 |

All eight stream subscriptions were acknowledged; books/context updates were received while current candle messages were absent. Real normalized REST replies independently omit the required recent bars. This proves current upstream insufficiency, not first-ever trade history. The warmup/freshness rules remain unchanged. Durable request/normalization/stream provenance, genuine completed-bar cache and request counts are now exposed. No interpolation or PAR/mainnet history was introduced.

EWY funding and mark/oracle divergence were checked at the final public snapshot. funding_distortion_review.json also records the actual 24-hour rate range, separately from mark/oracle divergence. Exact current rates/divergence and 2x base, unchanged 6x stress, maker-entry/taker-exit fee sensitivity are in market_readiness.json. Funding history has no guaranteed future payoff. No valid fresh frozen LONG exists here, so expected net profit remains null. Actual charged fees require fills. No fee/risk/profit filter was lowered.
