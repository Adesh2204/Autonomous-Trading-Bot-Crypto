# Primary API evidence

The official [Info endpoint documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#candle-snapshot), read 10 October 2026, documents the most recent 5,000 candles and HIP-3 prefixed coin requests. The audit windows contain 1,269 expected minute rows, within this bound. All ten retrospective queries returned 1,269 rows: no paging defect was observed for these windows. Generic time-range pagination documentation must not be mistaken for a verified 500-row candle cap.

Current recovery uses one bounded worker, a 300-completed-bar window (with 301 cache slots allowing one open row), widening a tail request to the full 300 when cache history is short or has a hole. The scanner independently requests the full UTC day plus 14 pre-anchor bars when larger than 300; this history is not reduced to stream-cache size. One-minute UTC alignment and completion guards remain unchanged.

The existing central HyperliquidRateLimitManager shares scanner/recovery requests, coalesces identical inflight payloads, reserves expected candle response weight, permits at most three retry attempts, applies backoff, and preserves 120 IP weight/minute for safety under the 1,200 local budget. These are source/config observations, not exchange-wide traffic measurements. Reconciliation is priority SAFETY, decisions priority DECISION; no optional analytics/public API loop has been added. Quarantined market retries back off from 30 seconds to at most five minutes. Missing content remains quarantined despite successful HTTP.

Raw capture writes bounded public candle evidence only; no additional API polling is caused by the capture. It does not record fees, fills, balances, addresses, private settings or signing material.
