# What the evidence establishes

The [participant guide](https://perpetual-alpha26.github.io/docs/) specifies
runtime lot precision and an ordinary $10 order minimum. It describes IOC
partial fills and advises checking the remaining position after `market_close`.
It does not explicitly document the small-position exceptions sought here.

The [official error table](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)
lists minimum-notional and reduce-only rejection as distinct errors. A
reduce-only flag alone is therefore insufficient evidence of acceptance.

The [official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
describes mark-triggered stops, position-wide versus fixed-size protection and
the behavior of children after a partial parent fill. It does not explicitly
promise acceptance of a stop below $10. A default market stop has substantial
slippage tolerance; a limit stop can remain unfilled after a gap. Neither is a
guaranteed bounded loss or a documented minimum-value exemption.

The [exchange API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint)
documents trigger orders and `positionTpsl` grouping. The inspected definition
does not establish a zero-size or subminimum exception. No such assumption has
been implemented. SDK 0.24.0's `market_close` uses the ordinary reduce-only IOC
order path; its construction of a request does not prove server acceptance.

The [public info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
exposes original order fields and reported fill positions. We used these for
independent readback rather than treating a small matched fill as a small
original order. `historicalOrders` is a bounded latest-history view, not a census.

## Confirmed historical observations

Six public one-current-runtime-lot closes had all of: original value below
$10, reduce-only true, opposite side to the reported position, original size
equal to the entire fill's starting position, filled status, zero remaining
order size and matched fills reducing the position to zero. Their raw responses
are preserved in `independent_close_readback`. BTC examples cover LONG and
SHORT; the other sampled directions are stated in the main report.

The final zero quantity is calculated from exchange-reported `startPosition`
and matched size. The API did not supply an independent historical account
snapshot at that instant. A current position query cannot reconstruct that
snapshot because later trades may exist. Lot comparisons use fresh metadata;
historical metadata at order placement was not available in this bounded search.

Two additional one-lot HYPE orders returned `reduceOnlyRejected` with no matched
fills. They are not successful close examples, and their rejection code does
not establish whether they met the full-position condition.

## Unverified behavior

Across eight sampled public counterparties, 15,304 returned `par` history event
rows represented 8,427 unique orders. None was a trigger order. This is
insufficient to verify below-$10 stop placement, readback, coverage of partial
entries or residual behavior after partial stop execution. It also does not
prove that the venue rejects all small stops.

Historical IOC success is narrower evidence than a documented rule for every
market, size, direction and current venue state. The ordinary minimum remains
in every production validator. The evidence classifier has no signing,
execution, permission or readiness-promotion capability.
