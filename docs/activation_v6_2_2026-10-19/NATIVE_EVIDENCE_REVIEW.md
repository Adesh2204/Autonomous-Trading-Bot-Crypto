# PAS native-exit evidence review

The official [Participant Guide](https://perpetual-alpha26.github.io/docs/) was checked on 19 October 2026. It specifies an ordinary $10 per-order minimum, reduce-only TP/SL and IOC closing behavior that can partially fill or reject. It does not establish a PAS exception for fixed-size stops or exact full-position exits below that minimum.

The [Hyperliquid TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) explains mark-triggered execution and the difference between limit and market triggers. A trigger is not evidence of a closing fill. A limit stop can remain unfilled through a gap. These general mechanics do not independently certify the minimum behavior on PAS.

Local inspection of the installed official Python SDK 0.24.0 confirms that `Exchange.market_close` reads the selected DEX position and calls `order` with an IOC limit and reduce-only flag. It contains no independent venue acceptance or residual guarantee. The SDK was inspected, not invoked for an order.

V6.1's bounded public-account sample found no usable PAS native-stop/subminimum route evidence. No new signed experiment has been conducted in V6.2. The new unsigned proposals quantify the runtime lot, its notional at each reviewed exit price, and every representable subminimum residual size. Actual entry, parent/child stop, fill IDs, fees, funding, exact remaining position and two flat/order-free readbacks are still required.

The next external action is the precise clarification in [PAS_ROUTE_CLARIFICATION.md](../activation_v6_1_2026-10-19/PAS_ROUTE_CLARIFICATION.md): obtain PAS-wide authoritative minimum/close-all semantics for both native stops and full-position IOC closes, including partial outcomes. Keep signed entry blocked while this is unproven. A new reviewed qualification implementation and exact finite interactive approval must precede any signed test; the broad request to complete a test round is not a substitute for those prerequisites.

A further check of the official [API error reference](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) distinguishes minimum-notional rejection from reduce-only and IOC-liquidity errors. It supplies no PAS subminimum exception. The [Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) limits time-based fill responses and retention; a bounded empty history response is not a terminal order disposition.
