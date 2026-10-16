# Verified venue rules and the unresolved exception

Reviewed on 12 October 2026. No exchange write was used to test a hypothesis.

## Primary evidence

- [Perpetual Alpha participant guide](https://perpetual-alpha26.github.io/docs/), Price and size rules, Orders and leverage: the published order minimum is $10. IOC can partly fill, its unfilled remainder is cancelled, and `market_close` uses reduce-only IOC. The guide requires a subsequent position read because that close can also partly fill or be rejected. It supplies no explicit small-position exemption for a full close or a protective stop.
- [Hyperliquid error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses): `MinTradeNtl` reports a minimum-value rejection. `ReduceOnly` separately rejects exposure-increasing orders. These separate errors do not establish an exemption.
- [Hyperliquid TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl): partial parent cancellation can leave child protection cancelled; protection of an actual partial position needs its own checked lifecycle. A limit stop can remain unfilled through a gap. No small-position exception is specified there.
- [Hyperliquid info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint): documents explicit `minTradeNtlRejected`, `reduceOnlyRejected`, `badTriggerPxRejected` and cancellation states. `unknownOid` is not a terminal outcome proving a request was rejected.
- Official Python SDK 0.24.0: the installed `Exchange.market_close` implementation is saved as `official_sdk_market_close.py.txt` with its checksum in `inspection_before.json`. It reads the position, selects the opposite side and calls `order` with reduce-only and IOC. There is no separate dust-close endpoint or exemption capability in that method. Client serialization cannot prove server acceptance.

## Precise conclusion

General reduce-only closing and trigger protection are documented. Acceptance of a full-position reduce-only IOC or stop-limit below $10 on testnet `par` is **NOT ESTABLISHED** by the authoritative material inspected. This is not a verified claim that the server rejects every such order; an undocumented exception may exist. No hypothetical offline success can resolve that uncertainty.

We therefore retain both existing minimum-notional checks. We do not use an oversized reduce-only request, zero-size dynamic TP/SL, a top-up entry, larger exposure, abnormal prices or a market route as an assumed workaround. Current candidate markets have sub-$10 runtime lots, so a smallest partial fill or last exit remainder can fail those retained checks. Entry stays blocked.

The required missing evidence is authoritative confirmation of the exact full-close and stop exception conditions and supported fields, or an alternative supported bounded flattening mechanism. Any subsequent implementation needs new offline boundary tests, a full regression and a fresh preflight before exact human approval.
