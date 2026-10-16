# V8.3: what is established, and what remains unknown

Reviewed 12 October 2026. This investigation made no signed exchange request.

| Question | Evidence and conclusion |
| --- | --- |
| Does our code reject a sub-$10 full reduce-only close before HTTP? | **Yes.** `MarketSpec.normalize_order` rejects a price-times-size value below 10; `HyperliquidOrderValidator.validate` independently rejects it. V8.2's exact-residual helper also refuses an unverified subminimum remainder. These checks apply even when the order reduces the entire position. |
| Does the published rule expressly exempt full-position closes? | **Not established.** The current participant guide specifies a $10 minimum per order. Hyperliquid documents `MinTradeNtl`, but the inspected material does not describe a full-close exemption. This is not proof that every server-side small close is rejected. |
| Are position-attached protective orders exempt? | **Not established separately.** Position TP/SL and the `positionTpsl` grouping are documented; neither the inspected TP/SL page nor the exchange schema specifies a subminimum exemption. Dynamic full-position sizing is not evidence of minimum-notional treatment. |
| Does SDK `market_close` provide a different dust-closing mechanism? | **No separate mechanism in the installed method.** SDK 0.24.0 reads the genuine position and submits an opposite-side reduce-only IOC through `order`. No local SDK minimum check does not prove exchange acceptance. Saved method excerpts are included. |
| Can an ordinary exact full-position close avoid increasing exposure? | **Yes, generally:** the documented opposite-side reduce-only IOC uses the observed quantity. However, it can fill partially or be rejected. Safe closure of a remainder below the minimum remains unverified. |
| Does IOC guarantee a full fill? | **No.** The unfilled remainder is cancelled. A larger order can still fill one small lot or leave one small lot after an exit. |
| Does an entry with attached children solve partial protection automatically? | **No guarantee.** Hyperliquid documents cases where children are cancelled after partial-parent cancellation. The existing certification checks protection against the actual reconciled position. |
| Is another atomic/full-fill route established? | **No equivalent guarantee found.** The inspected order schema documents ALO, IOC and GTC. Batch requests can have different results for each action. Neither batching nor an SDK market helper supplies verified all-or-none entry, protection and flattening. |

Primary sources:

- [Perpetual Alpha participant guide](https://perpetual-alpha26.github.io/docs/): Price and size rules; Orders and leverage; Markets. Its current market table is context only; the investigation obtains the lot and asset mapping from live `meta(dex=par)`.
- [Hyperliquid error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses): minimum-value and reduce-only failures are separately documented.
- [Hyperliquid tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size): runtime size precision; valid order sizes.
- [Hyperliquid TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl): position sizing, partial-parent child behavior, mark-triggered protection and limit-stop gap risk.
- [Hyperliquid exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint): reduce-only and grouping fields; IOC remainder cancellation; action-level rejection results.
- Installed official Python SDK **0.24.0**: `official_sdk_market_close.py.txt`, `official_sdk_order.py.txt`, `official_sdk_bulk_orders.py.txt`. Inspection does not create a wallet or an Exchange instance.

The API offers no inspected read-only capability query which certifies small close or stop acceptance. Account setup, free collateral, a flat account and a working HTTP connection cannot establish it. Offline fixtures cannot establish it either. Therefore approaches A and C remain unverified. Approach B is evaluated from actual runtime lots and actual public books, independently for all ten official markets. If none qualifies, the existing certification entry block must remain.

No exemption is added. No zero-size stop, inflated reduce-only size, abnormal limit price, top-up or larger exposure is used as a workaround.
