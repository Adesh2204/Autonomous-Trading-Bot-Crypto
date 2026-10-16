# Team Anchorium — V7 native availability and external research report

## A. Executive verdict

**EXTERNAL_RESEARCH_COMPLETE** for permission/provider review, candidate mappings and an isolated price comparison. Volume equivalence, external signal validation and licensing suitability remain unverified.

**NATIVE_FEED_NOT_READY**. Implementation and the full regression are complete. External provider research is complete as a document review; production-equivalent external signals remain unvalidated and disabled.

A candle is one minute of genuine prices and volume. The new monitor explains missing minutes, when they arrive, whether they reach cache and why a market is excluded. It does not manufacture bars or authorize trading.

## B. Files inspected and modified

Discovery was saved before edits: [discovery table](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/discovery.md>). Existing validators, one repair worker, quarantine manager, request budgets and frozen scanner were extended or reused. Original NSE files were untouched.

| Exact file | Change and evidence |
|---|---|
| [scripts/run_crypto_paper.py](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/run_crypto_paper.py>) | Share one native monitor between public clients; save detailed final availability after workers stop. Functions: `main`. |
| [scripts/check_practice_health.py](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/check_practice_health.py>) | Timestamped availability table, exact reasons, queue/restorations, latency/censoring, independent transport flags; existing exit meanings retained. Functions: `describe`. |
| [algo-trading-bot/venue_config.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/venue_config.py>) | Reject external production source mode and self-declared external live approval; keep public-only dotenv bypass. Functions: `require_paper_migration`. |
| [algo-trading-bot/market_stream.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/market_stream.py>) | Throttled availability snapshots alongside existing transport/account/market health. Functions: `MarketStream.__init__, MarketStream.poll`. |
| [algo-trading-bot/exchange/paper_operations.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/paper_operations.py>) | Explicit native/scanner/signal flags while PAPER trading remains locked. Functions: `PaperHealth.write`. |
| [algo-trading-bot/exchange/market_health.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/market_health.py>) | Optional sufficient-sample retry hints only increase bounded backoff; no threshold or health formula edits. Functions: `MarketHealthManager.finish_recovery`. |
| [algo-trading-bot/exchange/hyperliquid_market_data.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/hyperliquid_market_data.py>) | Observe real REST/WS rows; share monitor; report repair outcomes; preserve proven full-window repair and merge guard. Functions: `HyperliquidMarketData.get_candles, ParMarketDataEngine.__init__, ParMarketDataEngine.reconcile_history, ParMarketDataEngine._reconcile_history, ParMarketDataEngine.ingest, ParMarketDataEngine._ingest_validated, ParMarketDataEngine.market_health, ParMarketDataEngine._run_owned`. |
| [algo-trading-bot/exchange/candle_availability.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/candle_availability.py>) | New source-aware observations, live/left/right censoring, bounded interval history, recovery counters, cache/UTC distinction; native monitor tests. Functions: `sequence_lengths, distribution, CandleAvailabilityMonitor.__init__, CandleAvailabilityMonitor._require, CandleAvailabilityMonitor._row, CandleAvailabilityMonitor._prune, CandleAvailabilityMonitor.observe_candle, CandleAvailabilityMonitor.reject, CandleAvailabilityMonitor.observe_rest, CandleAvailabilityMonitor.update_cache, CandleAvailabilityMonitor.recovery_begin, CandleAvailabilityMonitor.recovery_finish, CandleAvailabilityMonitor._latency, CandleAvailabilityMonitor.retry_hint_ms, CandleAvailabilityMonitor.prioritize, CandleAvailabilityMonitor.snapshot`. |
| [algo-trading-bot/research_intelligence/external_data.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/research_intelligence/external_data.py>) | Offline library, immutable research types, strict mapping and UTC/as-of validation; no network/live imports. Functions: `ResearchCandle.__post_init__, AssetMapping.validate, MarketDataSource.get_candles, RecordedMarketDataSource.__init__, RecordedMarketDataSource.get_candles, HyperliquidReferenceSource.__init__, HyperliquidReferenceSource._read, HyperliquidReferenceSource.get_candles, require_feature_history, frozen_features, compare_sources`. |
| [scripts/compare_external_data.py](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/compare_external_data.py>) | Standalone bounded public-only research capture; fixed read endpoint, separate namespace and immutable output. Functions: `main`. |
| [algo-trading-bot/test_candle_availability_v7.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_candle_availability_v7.py>) | OFFLINE_FIXTURE native availability/recovery/freshness/retention tests; cannot certify a venue. |
| [algo-trading-bot/test_external_data_v7.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_external_data_v7.py>) | OFFLINE_FIXTURE isolation, mapping, volume, UTC, source outage and production-gate tests. |
| [configs/external_research.example.json](</Users/adesh/Autonomous Trading Bot - Crypto /configs/external_research.example.json>) | Unloaded false/null placeholders; no API credentials or paid service activated. |

Generated legacy inventory was refreshed with the existing script, with the previous inventory saved before regeneration. It records source locations and matched terms, not credentials. The two generated files are [inventory CSV](</Users/adesh/Autonomous Trading Bot - Crypto /docs/legacy_dependency_inventory.csv>) and [inventory summary](</Users/adesh/Autonomous Trading Bot - Crypto /docs/legacy_dependency_inventory.json>).

Full scope and limits: [implementation notes](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/implementation_scope.md>).

## C. Candle availability report

Final observations use the same latest 300 expected completed UTC intervals. Cache counts are separate from full UTC scanner history; 299 in this view can coexist with a still-fresh earlier 300-bar tail under the unchanged two-minute policy. Eligibility is not inferred from this table alone.

| Market | Expected | Present | Missing | Contiguous tail | REST / WS live delay n; median / p95 ms | Quarantine reason | Status |
|---|---:|---:|---:|---:|---|---|---|
| par:BRENT | 300 | 253 | 47 | 257 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:BTC | 300 | 292 | 8 | 293 | REST: 7; 203657.000 / 324375.000; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:ETH | 300 | 284 | 16 | 288 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:EWJ | 300 | 217 | 83 | 221 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:EWY | 300 | 248 | 52 | 252 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:GOLD | 300 | 292 | 8 | 1 | REST: 6; 124510.000 / 252185.000; WS: 0; Unknown / not evaluated / Unknown / not evaluated | STRATEGY_CANDLE_GAP_OR_DUPLICATE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:HYPE | 300 | 281 | 19 | 285 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:SP500 | 300 | 291 | 9 | 295 | REST: 6; 63281.000 / 193467.000; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:USDEUR | 300 | 217 | 83 | 221 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |
| par:USDJPY | 300 | 244 | 56 | 248 | REST: 0; Unknown / not evaluated / Unknown / not evaluated; WS: 0; Unknown / not evaluated / Unknown / not evaluated | INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE | QUARANTINED |

`null` means unobserved/unknown, not zero latency. Detailed REST/WS first/last reception, rejected/conflicting duplicates, longest run, close age, exact missing timestamps, full-history checks, right-censored intervals and next retry are in [availability snapshot](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/short_15m/paper_segments/20261010T175618Z-e5afe943/candle_availability.json>). Startup history is excluded from live percentiles. Small samples do not support stable latency conclusions.

| Source / market | Live completed samples | Median ms | P90 ms | P95 ms | P99 ms | Max ms | Still unobserved live intervals |
|---|---:|---:|---:|---:|---:|---:|---:|
| REST par:BRENT | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:BRENT | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:BTC | 7 | 203657.000 | 306375.000 | 324375.000 | 338775.000 | 342375 | 8 |
| WS par:BTC | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:ETH | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:ETH | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:EWJ | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:EWJ | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:EWY | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:EWY | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:GOLD | 6 | 124510.000 | 237185.000 | 252185.000 | 264185.000 | 267185 | 9 |
| WS par:GOLD | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:HYPE | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:HYPE | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:SP500 | 6 | 63281.000 | 178467.000 | 193467.000 | 205467.000 | 208467 | 9 |
| WS par:SP500 | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:USDEUR | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:USDEUR | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| REST par:USDJPY | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |
| WS par:USDJPY | 0 | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | Unknown / not evaluated | 15 |

![Observed REST arrivals](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/native_rest_delay.png>)

These are local arrival measurements. With fewer than 20 live intervals, adaptive hints remain off. Still-unobserved intervals are censored at shutdown; no zero delay is invented.

| Market | Full UTC requested minutes (last scanner read) | Completed received | Missing | Last validation reason | Still current at shutdown |
|---|---:|---:|---:|---|---|
| par:BRENT | 1100 | 1058 | 42 | COMPLETED_CANDLE_STALE | False |
| par:BTC | 1100 | 1097 | 3 | COMPLETED_CANDLE_STALE | False |
| par:ETH | 1100 | 1089 | 11 | COMPLETED_CANDLE_STALE | False |
| par:EWJ | 1100 | 1022 | 78 | COMPLETED_CANDLE_STALE | False |
| par:EWY | 1100 | 1053 | 47 | COMPLETED_CANDLE_STALE | False |
| par:GOLD | 1100 | 1096 | 4 | COMPLETED_CANDLE_STALE | False |
| par:HYPE | 1100 | 1086 | 14 | COMPLETED_CANDLE_STALE | False |
| par:SP500 | 1100 | 1096 | 4 | COMPLETED_CANDLE_STALE | False |
| par:USDEUR | 1100 | 1022 | 78 | COMPLETED_CANDLE_STALE | False |
| par:USDJPY | 1100 | 1049 | 51 | COMPLETED_CANDLE_STALE | False |

This snapshot follows the worker stop. Quote/book-age reasons can include aging during shutdown; candle gaps and stale completed history also appear in the earlier operating observations. These post-stop ages are not proof of a transport failure.

Plain meanings: insufficient history means too few consecutive genuine completed minutes; stale means the newest completed close exceeds the unchanged two-minute allowance; a gap means missing minutes inside the input; quarantine means the symbol is excluded until the required checks recover.

![Native availability](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/native_availability.png>)

## D. Root causes

- Verified historical client defects remain documented in V6: zero-ATR validation, repair-before-merge and completed-candle conflict handling. V7 does not reassign old stale cases without original wire evidence.
- A current missing minute absent from a covering decoded REST response is an observed source-response absence. Its underlying venue cause remains unknown; quiet trading and delayed publication are not automatically API defects.
- A previously absent exact minute later observed is classified delayed availability. Its reception-minus-close time includes network, request schedule and processing; an exchange publication timestamp is unavailable.
- Source-observed bars missing from cache, validator rejection, merge conflict, incomplete request coverage, unobserved WS events and rate deferrals are separate reasons.
- Market volatility/spread and strategy/economics rejection remain distinct from missing data. No threshold was reduced to obtain trades.

| Market | Distinct intervals absent in a covered decoded REST response | Those later observed completed through REST | Conflicting observed intervals |
|---|---:|---:|---:|
| par:BRENT | 43 | 0 | 0 |
| par:BTC | 13 | 6 | 0 |
| par:ETH | 12 | 0 | 0 |
| par:EWJ | 79 | 0 | 0 |
| par:EWY | 48 | 0 | 0 |
| par:GOLD | 75 | 70 | 0 |
| par:HYPE | 15 | 0 | 0 |
| par:SP500 | 7 | 2 | 0 |
| par:USDEUR | 79 | 0 | 0 |
| par:USDJPY | 52 | 0 | 0 |

These are distinct intervals across retained observations in this fresh run, not just the final 300-minute view. Source absence and underlying cause are different findings. Exact timestamps and requests remain in the public capture and [organizer evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/organizer_missing_minute_evidence.json>).

## E. Recovery performance

Recovery uses the existing single worker, coalesced reads, 30-second–five-minute exponential cooldown and weighted budget with safety reserves. Twenty live REST completed samples are required for optional delay hints; insufficient samples keep conservative backoff. Old due cohorts lead; near-ready markets break ties without excluding other due markets.

| Market | Attempts | Incomplete/failed input recoveries | First REST arrivals after prior absence | Cache holes filled during recovery (includes warmup) | Last successful input recovery ms | Next retry ms |
|---|---:|---:|---:|---:|---:|---:|
| par:BRENT | 8 | 8 | 268 | 268 | None | 1791655978330 |
| par:BTC | 10 | 9 | 307 | 305 | 1791655366565 | 1791656100683 |
| par:ETH | 8 | 8 | 299 | 299 | None | 1791655978330 |
| par:EWJ | 8 | 8 | 232 | 232 | None | 1791655978330 |
| par:EWY | 8 | 8 | 263 | 263 | None | 1791655978330 |
| par:GOLD | 11 | 10 | 306 | 233 | 1791655366565 | 1791655978330 |
| par:HYPE | 8 | 8 | 296 | 296 | None | 1791655978330 |
| par:SP500 | 16 | 11 | 305 | 301 | 1791655376551 | 1791655978330 |
| par:USDEUR | 8 | 8 | 232 | 232 | None | 1791655978330 |
| par:USDJPY | 8 | 8 | 259 | 259 | None | 1791655978330 |

The first-REST-arrival column includes startup minutes previously marked not-yet-observed. It must not be read as thousands of repaired exchange gaps. The separate covered-response table above is the narrower evidence of later arrivals after decoded response absences.

Cache holes filled are actual admissions during a recovery window; simultaneous WS activity is not assumed to be caused by REST. First REST arrival counters are cumulative within this fresh run, not counts of every duplicate download. Failures include successful HTTP responses that did not restore usable input; they are not all transport errors.

The shared local public-read limit is 1,200 weight/minute with 120 reserved. The highest sampled usage was 871; shutdown usage was 47. The exact unsampled/exchange-wide peak is unknown. Pending reads at shutdown: 0. Coalesced reads: 2. Recorded read deferrals/errors: {"RATE_LIMITED": 3}. These can be local budget deferrals, not venue HTTP throttling. Account-action capacity is unobserved. Full budgeting and request counts are retained in the receipt.

| Market | Retained quarantine-to-healthy transitions | Median observed restoration time (seconds) | Maximum (seconds) |
|---|---:|---:|---:|
| par:BTC | 25 | 0.900 | 85.828 |
| par:GOLD | 11 | 1.090 | 45.951 |
| par:SP500 | 18 | 0.825 | 9.123 |

These are observed health-state transitions, not exchange publication latency or proof of lasting stability. The retained transition tape can omit earlier cycles; actual timestamps are preserved in [restoration timing](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/restoration_timing.json>).

## F. External provider comparison

Ranking is an engineering judgment for this project's constraints, not a paid subscription recommendation. Cost, licensing and location access must be checked for the actual team before procurement. No paid account, API key or subscription was opened.

| Rank / provider | Coverage and 1m OHLCV | Volume / history / API limits | Cost / licensing | Latency and verdict |
|---|---|---|---|---|
| 1: Hyperliquid mainnet native + xyz references | Crypto perpetuals; candidate xyz counterparts for the other assets. Candle snapshot supports 1m. Live listing is checked before each research request. | Most recent 5,000 bars. Source volume is real reference trading activity, **not par volume**. Shared weight budgeting and metadata validation used. | Public queries need no key. No API subscription payment was made; redistribution rights remain unverified. | Actual capture results reported separately. Same wire format lowers adapter risk; does not establish instrument/volume equivalence. First low-cost price-comparison candidate. [Info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#candle-snapshot), [rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits). |
| 2: Binance Spot | Documented crypto 1m klines; BTC/ETH candidates. HYPE listing not checked. | UTC default; 1,000 maximum/request; request weight 2. Base and quote volume fields are distinct. Historical retention and geographic access not observed. | Public market endpoint; no paid plan verified. Terms and redistribution review outstanding. | No measured latency or SLA evidence. USDT spot prices and volumes require separate basis/unit research before use against USD-denominated par perps. [Official market API](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market). |
| 3: Coinbase Exchange | Crypto trade candles, 60-second interval; BTC/ETH USD references are candidates, current listings untested. | 300 maximum/request; no candle for no-tick intervals; historical API explicitly may be incomplete. Volume is trading activity. | Public interface documented; usage/redistribution terms not reviewed. | Not a guaranteed complete fallback. No live latency measurement. [Official candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles). |
| 4: Kraken | Crypto OHLC; 1-minute option documented. Actual pair availability untested. | Maximum 720 recent entries; last entry is unfinished; older entries cannot be obtained through `since`. Full UTC history can exceed this limit. | Public interface; entitlement and reuse terms unverified. | Useful independent price check, not enough guaranteed UTC history. [Official OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data). |
| 5: Databento | Documented 1m trade bars for equities and futures, potentially ETFs/Brent/gold/index futures. Exact symbols and entitled datasets need discovery. | API metadata supports schema, dataset-condition and cost discovery. Contract volume is instrument-specific; historical coverage depends on dataset. | Usage-based estimates plus exchange licensing; no project-specific quote established. Pricing page advertises extensive coverage, not our entitlement. | Paid specialist option if a justified dataset is needed. Actual freshness, limits and licenses remain untested. [Historical API](https://databento.com/docs/api-reference-historical), [pricing/licensing](https://databento.com/pricing). |
| 6: Twelve Data | Broad equities/ETFs/FX/crypto/commodities time-series documentation; volume only where applicable. Specific instrument coverage untested. | Basic advertises 8 API credits and 800/day. Weighted endpoint credits and asset entitlements must be confirmed. API key needed. | Basic free; pricing page shows paid plans from $29/month with displayed billing qualifications. Team use and data reuse rights are not established by an individual plan. | Broad discovery source; missing/tick volume makes affected series unsuitable for unchanged VWAP. No measured publication latency. [Pricing](https://twelvedata.com/pricing), [official time-series schema](https://twelvedata.com/docs/mcp). |

The providers' advertised reliability/coverage is not treated as an observation. No candidate has been validated as an automatic production fallback. Public access is not a general redistribution license. Before adding a keyed provider, resolve student/team/commercial status, non-display/model usage, stored-data retention, jury sharing, derived outputs and redistribution rights. The placeholder config contains null keys and is not loaded by production.

The ranked six-provider matrix, verified limits/cost qualifications, licensing unknowns and confidence are in [external research](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/external_research.md>). Hyperliquid mainnet references are the first price-comparison candidate; no provider is certified as a production fallback. Paid subscriptions and keys were not activated.

## G. Ten-asset compatibility matrix

The native units and mainnet counterpart identifiers come from the current [organizer reference table](https://perpetual-alpha26.github.io/docs/#asset-references-and-pricing). A counterpart is a candidate, not equivalence. All remain unapproved for live external signals. Native contracts trade continuously; external session and adjustment behavior is a separate validation obligation.

| Native asset | Candidate / native units | Research concerns and current verdict |
|---|---|---|
| par:BTC | BTC; USD/BTC | Crypto spot/perp basis; USD versus stablecoin quote; venue-specific base volume. POTENTIALLY_COMPATIBLE for price study; no VWAP-equivalence certification. |
| par:ETH | ETH; USD/ETH | Same checks; no split adjustment proposed; UTC-align completed candles. POTENTIALLY_COMPATIBLE for price study. |
| par:HYPE | HYPE; USD/HYPE | Verify token/listing, liquidity and quote semantics. Other providers' listing unverified. POTENTIALLY_COMPATIBLE for price study. |
| par:SP500 | xyz:SP500; index points | Cash index is a calculated reference with no directly traded index volume. ETF/futures/CFD proxies change instrument and units. Cash-index volume input INCOMPATIBLE for unchanged VWAP; xyz remains UNVERIFIED for volume. |
| par:EWY | xyz:EWY; USD/share | Actual ETF share volume is meaningful but is a different instrument from a perpetual. Splits/dividends, raw versus adjusted prices and session coverage must be explicit. Native-volume equivalence UNVERIFIED. |
| par:EWJ | xyz:EWJ; USD/share | Same session/corporate-action issues; Japanese underlying stocks are not the US ETF price. Native-volume equivalence UNVERIFIED. |
| par:BRENT | xyz:BRENTOIL; USD/barrel | Specify delivery month, settlement, roll rule and contract multiplier. Spot assessment and continuous futures series are not interchangeable. UNVERIFIED. |
| par:GOLD | xyz:GOLD; USD/troy ounce | XAU spot, COMEX futures and broker tick volume differ. Verify contract month/multiplier and session gaps. Tick-volume VWAP INCOMPATIBLE; other mappings UNVERIFIED. |
| par:USDEUR | xyz:EUR; USD/EUR | Despite its name the competition reference is EUR/USD. Never invert. Decentralized FX/tick volume is not demonstrated comparable trade volume; UNVERIFIED or INCOMPATIBLE for VWAP depending on source. |
| par:USDJPY | xyz:JPY; JPY/USD | Required units are JPY per USD; reject an inverted series, undocumented scaling factors and unsupported volume. UNVERIFIED. |

Issuer evidence separately confirms [EWY](https://www.ishares.com/us/products/239681/ishares-msci-south-korea-capped-etf) and [EWJ](https://www.ishares.com/us/products/239665/ishares-msci-japan-etf) are iShares ETFs listed on NYSE Arca. [NYSE hours](https://www.nyse.com/trade/trading-information?force_isolation=true) list a 9:30–16:00 Eastern core session. Extended-hours changes do not make a weekend ETF series a continuous par series. A session calendar must use exchange timezone and daylight-saving/holiday rules rather than a fixed UTC offset.

[ICE Brent specifications](https://www.ice.com/products/219/Brent-Crude-Futures) describe a 1,000-barrel contract and monthly expiry mechanics. This requires explicit conversion of contract counts if one studies barrel-weighted volume; the implemented research capture performs no such conversion or roll stitching. [CME gold specifications](https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html) are the primary contract source to verify before using a gold futures proxy. [S&P's index page](https://www.spglobal.com/spdji/en/indices/equity/sp-500/) identifies the index benchmark; it does not turn index levels into traded shares.

No provider/source adjustment, corporate-action policy or continuous-futures roll rule has been silently applied. API timestamps are converted only from documented units to UTC minute starts. Price inversion/rescaling and manufactured volume are absent. A schema-valid reference candle is validated **for recording**, not validated for strategy equivalence.

The asset-by-asset matrix in [external research — asset mapping](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/external_research.md>) identifies crypto basis/volume differences, ETF sessions/adjustments, futures roll/multiplier issues, gold tick-volume limits, and FX direction. USDEUR is USD per EUR. Reference identity is not volume or signal equivalence.

| Asset | Empirical comparison outcome |
|---|---|
| par:BRENT | 1058 matched; EXTERNAL_FEATURE_HISTORY_STALE |
| par:BTC | 1097 matched; EXTERNAL_FEATURE_HISTORY_STALE |
| par:ETH | 1089 matched; EXTERNAL_FEATURE_HISTORY_STALE |
| par:EWJ | 1022 matched; EXTERNAL_SOURCE_STALE_OR_UNAVAILABLE_AS_OF_DECISION |
| par:EWY | 1053 matched; EXTERNAL_SOURCE_STALE_OR_UNAVAILABLE_AS_OF_DECISION |
| par:GOLD | 1105 matched; EXTERNAL_VOLUME_NOT_COMPARABLE_FOR_VWAP |
| par:HYPE | 1086 matched; EXTERNAL_FEATURE_HISTORY_STALE |
| par:SP500 | 1105 matched; EXTERNAL_VOLUME_NOT_COMPARABLE_FOR_VWAP |
| par:USDEUR | 1022 matched; EXTERNAL_SOURCE_STALE_OR_UNAVAILABLE_AS_OF_DECISION |
| par:USDJPY | 1049 matched; EXTERNAL_SOURCE_STALE_OR_UNAVAILABLE_AS_OF_DECISION |

| Market | Matched closes | Median / P95 close difference bps | Native / external missing % | Adjacent return pairs | Native / external 1m return SD |
|---|---:|---|---|---:|---|
| par:BRENT | 1058 | 0.000 / 9.836 | 4.253 / 0.000 | 1057 | 0.000144 / 0.000166 |
| par:BTC | 1097 | -1.812 / 12.618 | 0.724 / 0.000 | 1096 | 0.000144 / 0.000164 |
| par:ETH | 1089 | 3.193 / 20.059 | 1.448 / 0.000 | 1088 | 0.000169 / 0.000243 |
| par:EWJ | 1022 | -0.714 / 8.993 | 7.511 / 5.792 | 1021 | 9.34e-05 / 0.000119 |
| par:EWY | 1053 | -6.749 / 9.226 | 4.706 / 0.814 | 1052 | 0.000115 / 0.000116 |
| par:GOLD | 1105 | -9.538 / -2.385 | 0.000 / 0.000 | 1104 | 0.00011 / 4.58e-05 |
| par:HYPE | 1086 | -3.450 / 19.299 | 1.719 / 0.000 | 1085 | 0.000547 / 0.000627 |
| par:SP500 | 1105 | -3.069 / 7.174 | 0.000 / 0.000 | 1104 | 0.000203 / 4.94e-05 |
| par:USDEUR | 1022 | -1.784 / 3.570 | 7.511 / 4.434 | 1021 | 6.28e-05 / 4.37e-05 |
| par:USDJPY | 1049 | -4.421 / 4.426 | 5.068 / 5.068 | 1048 | 6.95e-05 / 5.5e-05 |

All OHLC absolute/relative differences are retained in the comparison CSV. Volatility uses only adjacent matched genuine minutes, with no bridging of missing minutes. External capture is a single current reception: historic publication latency, signal timing advantage and live provider reliability remain unknown.

![External close differences](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/external_close_basis.png>)

Experiment A is the actual native PAPER baseline. Experiment B cannot produce an equivalent VWAP signal until instrument and volume semantics pass review. Experiment C signal agreement, hypothetical execution, fees/slippage and risk-adjusted outcomes remain **NOT ENOUGH EVIDENCE**. A fresh venue quote alone does not supply a missing signal or historical fill.

The standalone comparison occurs after the PAPER collector stopped. Its later native REST snapshot can be more complete (GOLD and SP500 were complete in that later request); it was never inserted into the prior PAPER cache or used to rewrite its failed certificate. Provider capture timing is retained separately.

No inversion, rescaling, split adjustment, volume invention or contract roll was applied. Mapping uncertainty remains visible. Frozen-feature/signal comparisons are blocked when comparable volume and full UTC/as-of evidence are absent. Detailed price differences are in [external comparison](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/external_capture/comparison.json>).

## H. External data legal/compliance findings

The current [official FAQ](https://perpetual-alpha26.github.io/faq/) permits external data in practice and scoring. It encourages disclosure of sources and processing in the submitted code and PDF report. It does not list provider-specific licenses or authorize redistribution. It says detailed reproducibility requirements are still being finalized. These statements match the permission described in V7; the retrieved page provides no revision history proving that all rules are unchanged.

The [participant guide](https://perpetual-alpha26.github.io/docs/) still selects testnet `par`, USDPR collateral, prefixed coin queries and dex-scoped account/market queries. External signals do not replace venue prices, liquidity, account reconciliation, fees or funding. The order book determines execution; external candles cannot make an unavailable native book tradable. Existing production locks remain authoritative.

Current organizer permission and disclosure wording was verified from primary sources on 10 October 2026. Source provenance/processing should accompany the code and report. Provider-specific licenses and jury redistribution permissions remain unverified; public API access is not a redistribution license. No rule-revision history was available to prove every rule unchanged. See the cited primary sources in [compliance research](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/external_research.md>).

## I. Source-isolation proof

Production has no import of the external module. Native cache validation rejects research records because their symbols are explicitly external. The research library imports no HTTP client and exposes no order/account API. Only the standalone collector can issue fixed public `/info` metadata/candle reads; it has no signer or `/exchange` action path. Production rejects external mode/self-approval flags. Existing tests also enforce no network/live imports throughout research.

As-of joins require real reception before the comparison decision. Old downloads cannot be inserted at earlier decisions. External source outages leave native state intact. Native quotes/mark context must be fresh; native account remains accounting truth. Unsupported fees, funding, fills, signal agreement and risk-adjusted outcomes remain null. No automatic promotion exists.

## J. Tests

Previous total: **1356**. New tests: **49**. Final total/passed: **1405**. Failed/errors/skipped: **0/0/0**. Strategy freeze and Phase-0 pass. One frozen file, eight protected methods and 32 protected parameters remain unchanged.

Final active source: `36324cd3891eb931801ddc2ac9d47cf1e9c47cfbbd6a5a6f9aaddbc410a52685`; XML SHA256: `9b7ffd64f49ada8a6421c2854c1fb3f0b6bdc6dcc3f6715f063b462dbebe519b`. Receipt: [release regression](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/regression_release/test_receipt.json>). All earlier failed/intermediate attempts are retained and explained in [test attempts](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/test_attempt_notes.md>). Synthetic tests are OFFLINE_FIXTURE, including ephemeral SDK tests; V6 also retains two RECORDED_EXCHANGE_REPLAY cases. This run is LIVE_PUBLIC_READ_ONLY plus local PAPER simulation, not actual exchange execution.

## K. PAPER results

Actual duration: **901.714 seconds**. Fresh state: `/Users/adesh/Autonomous Trading Bot - Crypto /runtime/paper/availability-v7-2026-10-10-short`. Final usable markets: **0 / 10**. Local fills/positions: **0/0**. Actual orders: **0**. Verdict: **FEED_NOT_READY**; blockers: `['final_usable_market']`.

Frozen UTC strategy, 0.40% ATR floor, 15 bps spread, 300 completed bars, Top-3 and one global position were preserved. Numerical rejections: 0. First rejection categories: `{"STALE_CANDLE": 25, "RECOVERY_PENDING": 2, "ATR_BELOW_SCANNER_FLOOR": 3}`.

| Independent stage | Evaluated | Passed | Failed | Pass % |
|---|---:|---:|---:|---:|
| MARKET_DATA_HEALTHY | 30 | 3 | 27 | 10.000 |
| ENOUGH_HISTORY | 30 | 30 | 0 | 100.000 |
| LIQUIDITY_PASS | 3 | 3 | 0 | 100.000 |
| SPREAD_PASS | 3 | 3 | 0 | 100.000 |
| ATR_PASS | 3 | 0 | 3 | 0.000 |
| SCANNER_QUALIFIED | 30 | 0 | 30 | 0.000 |
| TOP3_SELECTED | 0 | 0 | 0 | Unknown / not evaluated |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Unknown / not evaluated |
| SIGNAL_GENERATED | 0 | 0 | 0 | Unknown / not evaluated |
| FRICTION_PASS | 0 | 0 | 0 | Unknown / not evaluated |
| RISK_PASS | 0 | 0 | 0 | Unknown / not evaluated |

| Sequential stage | Admitted | Evaluated among previous survivors | Failed | Unobserved |
|---|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 30 | 30 | 0 | 0 |
| VALID_MARKET_IDENTITY | 30 | 30 | 0 | 0 |
| MARKET_DATA_HEALTHY | 3 | 30 | 27 | 0 |
| ENOUGH_HISTORY | 3 | 3 | 0 | 0 |
| LIQUIDITY_PASS | 3 | 3 | 0 | 0 |
| SPREAD_PASS | 3 | 3 | 0 | 0 |
| ATR_PASS | 0 | 3 | 3 | 0 |
| SCANNER_QUALIFIED | 0 | 0 | 0 | 0 |
| TOP3_SELECTED | 0 | 0 | 0 | 0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | 0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | 0 |
| BIAS_PASS | 0 | 0 | 0 | 0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | 0 |
| FRICTION_PASS | 0 | 0 | 0 | 0 |
| RISK_PASS | 0 | 0 | 0 | 0 |
| EXECUTION_PERMISSION | 0 | 0 | 0 | 0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | 0 |
| FILLED | 0 | 0 | 0 | 0 |
| TRADE_COMPLETED | 0 | 0 | 0 | 0 |

Rejections by category: `{"INFRASTRUCTURE": {"STALE_CANDLE": 25, "RECOVERY_PENDING": 2}, "MARKET": {"ATR_BELOW_SCANNER_FLOOR": 3}, "STRATEGY": {}, "RISK_ECONOMICS": {}, "UNCLASSIFIED": {}}`. Local PAPER portfolio: `{"timestamp_ms": 1791655590959, "cash": "20000", "unrealized_pnl": "0", "equity": "20000", "initial_margin": "0", "maintenance_margin_estimate": "0", "order_reservations": "0", "available_margin": "20000", "gross_notional": "0", "realized_pnl": "0", "fees_paid": "0", "funding_cashflow": "0", "collateral": "USDPR"}`.

Denominators are independently evaluated stage outcomes. Not-evaluated stages are not failures; sequential admissions and detailed rejection categories remain in the original opportunity traces/report. Cumulative older-run counters are not merged into this fresh session.

Usable-feed samples: 7; observed usable span: 459.057 seconds. Scanner observations: 30.

WS disconnects: 1; completed corresponding reconnect/account barriers: 1. Socket uptime: 896.268 seconds. Completed lifetime median: 688.4208855829202. Close codes/reasons and receiver gaps come from actual transport records, not assumptions.

The preserved inherited certificate reports two post-initial account barriers, including an in-place REST/account recovery. The V7 reconnect count above is one, derived only after an actual disconnect. See [counter scope note](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/counter_scope_note.json>).

Receiver gap maximum: `1.0359976254403591` seconds. Close records: `[{"connection_id": "public-1", "close_code": 1000, "close_reason": "Expired", "connection_age_seconds": 688.4208855829202, "client_exception": "STREAM_DISCONNECTED"}]`. Maximum sampled local IP weight: `871`. Account-action budget remains unobserved; no funded readiness is inferred.

Clean shutdown, worker completion, primary/backup SQLite integrity, checkpoint checksums/source identity, health tape digest and released ownership locks were independently verified. Local PAPER equity/accounting is separate from the funded wallet. No funded LONG/SHORT/protection/recovery test occurred. No wallet key, leverage/account change, cancellation, transfer, automatic three-hour run or recurring Codex task occurred.

## L. Final readiness flags

```ini
STRATEGY_FREEZE = TRUE
FULL_TEST_SUITE = TRUE
CANDLE_MONITOR_IMPLEMENTED = TRUE
CANDLE_PUBLICATION_TRACKING = OBSERVATION_DELAY_TRACKED; EXCHANGE_PUBLICATION_TIME_UNKNOWN
REST_RECOVERY_VALIDATED = OFFLINE_AND_BOUNDED_PUBLIC_EVIDENCE; READINESS_NOT_IMPLIED
CANDLE_PROVENANCE_VALIDATED = TRUE
MARKET_HEALTH_READY = FALSE
NATIVE_FEED_READY = FALSE
EXTERNAL_PROVIDER_RESEARCH = COMPLETE_DOCUMENT_REVIEW
EXTERNAL_ASSET_MAPPING = TEN_REFERENCES_IDENTIFIED; EQUIVALENCE_UNVERIFIED
EXTERNAL_SOURCE_COMPARISON = PRICE_OBSERVATIONS_ONLY; COUNTERFACTUAL_NOT_ENOUGH_EVIDENCE
EXTERNAL_SIGNAL_LIVE_APPROVED = FALSE
PAPER_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
PRACTICE_READY = FALSE
LIVE_READY = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = FALSE
PROTECTION_ENABLED = FALSE
```

These are evidence verdicts for the completed bounded run, not a claim that a feed remains connected after the process stops. A later run needs fresh native checks. SIGNAL_AVAILABLE in the dashboard is a latest-scan diagnostic; entry permission still requires the independent current health and safety gates.

Boolean PAPER_READY here requires the existing feed certificate; it does not authorize funded practice. Protection configuration is still not tested protective-order acceptance. Research/ML promotion flags remain unsupported; production strategy is unchanged.

## M. Exact next action

Ask the organizers to clarify native missing-minute, backfill and candle-WebSocket semantics using [this prepared unsent draft](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/organizer_clarification_draft.md>) and [exact minute evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/availability_v7_2026-10-10/organizer_missing_minute_evidence.json>). This is the single highest-priority next action. No shell command can establish the undocumented venue behavior. The message has **not been sent**.
