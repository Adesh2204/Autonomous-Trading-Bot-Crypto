# Exact price-guard diagnosis

The legacy approval fixes a BUY IOC price at the reviewed ask plus 20 bps. The final guard rejects it if that fixed price exceeds a newly read ask plus 20 bps, or is below the newly read ask. It also preserves the $10 minimum and 1,000 test-USDPR outer mark/notional limits.

For the old 83,610 limit, a fresh ask of 83,442 has a runtime-normalized 20-bps maximum of 83,608. The old fixed limit therefore fails. A fresh normalized ask-plus-10-bps limit is 83,525: executable and inside both the live tolerance and the unchanged approved maximum. This is a deterministic reproduction, not the missing historical failed snapshot. The prior launcher did not persist that snapshot, so the exact historical ask and rejected clause cannot honestly be reconstructed.

V2 approves a maximum BUY price, unchanged exact quantity and exact selected notional ceiling. It derives a fresh price only before reserving the one entry, clamps it to those caps, and authenticates the actual request through the central signing permit. Old fixed-price hashes and exact-limit semantics stay fixed. Genuine excess spread, insufficient depth, non-executable cap, minimum/notional violations, stale inputs, source drift, unknown account state or expiry continue to block execution.

Public price diagnostics now persist before validation returns or raises, with bid/ask/mark/oracle, reviewed and actual prices, live tolerance, approved caps, timestamps and all rejected price/cap predicates. Builder failures export those exact records. No private key, signature or signed payload is logged.

Official venue semantics: IOC unfilled quantity is canceled; it does not promise a fill. Native action expiry and the ordinary perpetual-order minimum remain in use. [Exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint), [error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses).
