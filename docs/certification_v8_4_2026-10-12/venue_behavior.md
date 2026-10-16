# V8.4 venue evidence: precise conclusions

Reviewed on 12 October 2026. No actual-wallet signature or exchange action was created.

**Two historical sub-$10 full closes are now verified on `par:HYPE`. A safe
one-lot close/protection mechanism for certification remains unverified.** We
cannot safely authorize entry. This investigation does not claim that the
server rejects every possible small full-position close.

## Confirmed local behavior

`MarketSpec.normalize_order` and `HyperliquidOrderValidator.validate` apply the
ordinary $10 minimum to reduce-only orders too. `exact_full_close_size` refuses
a subminimum observed remainder without rounding away dust or increasing size.
`require_safe_partial_path` blocks certification when a single runtime lot at
the reviewed close/protection prices would fall below that minimum. This block
is checked before the actual API key is loaded and again at the SDK boundary.

A $25 entry can fill only one small lot. A nearly complete exit can leave one
small lot. The total requested entry value therefore cannot establish a safe
partial-fill exit path. The new tests exercise the second case explicitly.

## Authoritative venue rules and their limits

- The [participant guide](https://perpetual-alpha26.github.io/docs/#price-and-size-rules)
  specifies the ordinary $10 price-times-size order minimum. It documents IOC
  partial matching and says to reread positions after `market_close`. It does
  not expressly define a small full-close or protective-order exemption.
- [Hyperliquid error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)
  describe `MinTradeNtl` separately from `ReduceOnly` rejection. This establishes
  the published ordinary rule; it does not establish the full-close special case.
- [Position TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
  supports full-position sizing and fixed-size stops. Dynamic sizing does not
  specify minimum-value treatment. Partial-parent cancellation can cancel its
  attached children. Stops still require acceptance and actual-position readback.
  Stop-limit orders can remain unfilled after a gap; market TP/SL uses a documented
  10% tolerance, which is not the existing bounded certification allowance.
- The [exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint)
  includes `reduceOnly`, trigger orders, `positionTpsl`, and GTC/IOC/ALO. Grouping
  is not a documented minimum exemption or an atomic entry/protection/exit guarantee.
  Batch operations can have individual outcomes. No documented FOK execution route
  was established in the inspected order schema.
- [Order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
  documents TWAP with a $100 minimum total size and possible partial execution.
  It is not a supported small-residual rescue. Chase runs in a browser and can
  partially match; neither chase nor trailing stops establish a minimum exemption.
- The [HyperCore writer documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore)
  exposes limit order actions with the same size/reduce-only and ALO/GTC/IOC concepts.
  No separate documented dust-close or protective minimum exemption was found there.
  No contract was deployed and no EVM action was sent.

The installed official Python SDK remains pinned to 0.24.0. The saved V8.3
`market_close`, `order` and `bulk_orders` excerpts show that the helper sends an
opposite-side reduce-only IOC for the observed quantity through the ordinary
order path. An SDK without a local minimum check is not server acceptance evidence.

## Focused read-only exchange observations

The new investigation queried existing public `par:ETH` trades and existing
counterparty order/fill history, using only `/info`. It did not scan markets or
place experimental orders. Raw observations are retained in
`public_history_verified/raw_info.json`.

Ten recent trades supplied the public counterparty sample. Four historical-order
responses and three fill-history responses were obtained. The deliberate
worst-case request-weight cap stopped a fourth fill query before HTTP. That
incomplete attempt is preserved; it is not reported as a complete certificate.
At most 2000 historical records are available per response, so this is a bounded
sample. The [info schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
provides `origSz`, `limitPx`, `reduceOnly`, status, and reducing fill fields.

No sampled `par:ETH` reduce-only original order with positive original
price-times-size below $10 was found. Local analysis of the already retrieved
histories then found two `par:HYPE` order IDs. Their `open` and `filled` event
rows occur twice each: **four event rows represent two orders**, not four closes.
Neither analysis added a market scan or a new trade.

### New confirmed exchange evidence

Both order IDs were independently reread with `orderStatus`, and their fills
were independently fetched in narrow time windows with `userFillsByTime`.
The complete raw readback is saved in
`close_readback_verified/full_close_evidence.json`. The records belong to an
already public counterparty, **not the Team Anchorium wallet**.

| Order ID | Actual event UTC | Genuine starting position | Original close | Original limit value | Actual fill | Result |
| --- | --- | --- | --- | --- | --- | --- |
| 61997055149 | 6 Oct 2026, 15:38:11.928 | HYPE SHORT, -0.03 | BUY 0.03 at 93.218, reduce-only IOC | 2.79654 USDPR | BUY 0.03 at 92.847, `Close Short` | Post-fill quantity 0 |
| 61745948135 | 3 Oct 2026, 14:11:33.873 | HYPE LONG, +0.07 | SELL 0.07 at 87.933, reduce-only IOC | 6.15531 USDPR | SELL 0.07 at 88.202, `Close Long` | Post-fill quantity 0 |

The reread completed at **12 Oct 2026, 10:22:14.751 UTC**. These are historical
execution facts, not orders submitted today. Original size, limit price,
reduce-only, IOC, filled status, genuine starting-position sign and actual fill
size agree. Thus some small full-position closes have actually succeeded on this
venue, in both directions. This improves on V8.3's lack of concrete exchange evidence.

The HYPE runtime lot is 0.01. These examples closed **three and seven lots**.
They do not establish the one-lot case, a general minimum exemption across all
ten markets, or current acceptance rules for every smaller size. There are
**zero par trigger-order records** in the retrieved historical sample. No
subminimum protective acceptance or trigger execution is established.

Small matched fills, current zero remaining size, an `open` status, or a
dynamic-position flag alone would not suffice. Here the matched original and
fill records establish the two particular full closes. They still do not
establish the missing general capability. Missing examples do not prove rejection.

## Decision

No supported **complete** small-entry/protection/residual-close mechanism has
been established. Retain the certification entry block and every ordinary
minimum check. No production exception is inferred from two historical sizes
while one-lot and protective behavior remain unverified. Do not
inflate size, add exposure, change the limit price solely to pass $10, submit a
zero-size stop, manufacture a flat ledger, or use a direct SDK/contract route to
bypass central checks. Protective-order acceptance remains a separate unverified
requirement even if full-close acceptance is later confirmed.

The next evidence needed is an authoritative, `par` testnet-specific answer
covering **both** one-lot exact full-position reduce-only IOC closure and fixed-size or
dynamic full-position protective-stop acceptance below $10, including validation
at placement/trigger and the relevant minimum-price basis. The unsent organizer
question draft is prepared separately. No ready trade proposal exists.
