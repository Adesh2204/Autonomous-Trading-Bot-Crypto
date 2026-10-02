# Anchorium Perpetual Alpha: Phases 1–5

This is the historical first checkpoint (499 tests). Subsequent policy lockout
and full paper infrastructure work are recorded in
[the paper migration guide](crypto_paper_migration_2026-10-02.md), with 595 tests.
Statements below about future paper-accounting/partial-fill work describe this
earlier checkpoint, not the current implementation.

The migration now has a frozen strategy, a classified dependency inventory,
generic exchange interfaces, and a credential-free public `par` data engine.
Exchange order submission remains disabled. All changes are in this clone on
`perpetual-alpha-migration`; `nse-working-baseline` preserves the starting source.

## 1. Strategy freeze

`algo-trading-bot/signal_brain.py` is byte-identical to the baseline. The manifest
in `docs/strategy_freeze.json` also checks eight strategy methods from the legacy
execution/observation layers and 32 signal and management parameters. No
strategy exception was necessary; `strategy_exceptions` is empty.

`FrozenStrategy` accepts a generic candle provider. It passes completed,
consecutive one-minute OHLCV bars to the existing brain, using UTC timestamps and
per-candle base volume. The brain already derives its VWAP date groups from
input timestamps. UTC therefore defines the continuous venue's daily boundary
without modifying the indicator formulas. A gap or duplicate aborts evaluation;
no synthetic candle is invented. The complete output DataFrame is compared with
a direct call to the baseline brain on the same input, including a UTC date change.

Before evaluating signals, verification rejects edits to frozen source,
management methods or parameter values. This is a reproducibility check, not
proof that the original strategy is profitable in these markets.

## 2. Legacy dependency classification

`scripts/inventory_legacy_dependencies.py` scans repository text sources,
tests and historical documentation for the requested broker/market terms,
including identifier forms such as `NSEMarketSchedule`. Each occurrence has a
path, line, column, matched term, disposition and proposed replacement in
`docs/legacy_dependency_inventory.csv`; its JSON companion records totals and
exclusions. Secret environment files, ignored runtime/dependency files, binaries
and the inventory itself are excluded. No credential values or source-line
contents are exported.

REMOVE means retired stock defaults, login/session fields or segment coupling
that the new core does not use. REPLACE means legacy provider or execution
plumbing whose new counterpart is listed. KEEP AS LEGACY REFERENCE means frozen
strategy, offline regression fixtures, safety lockouts or historical evidence.
The legacy implementations remain available for comparison where appropriate;
their Angel One constructors and order boundaries are disabled.

The new core has its own `venue_config.py` and shared `safety_errors.py`, so it
does not need the stock configuration or NSE execution stack. Broker SDK, TOTP,
stock calendars and their support packages moved to optional
`requirements-legacy.txt`. Cold-process import verification confirms the public
runner can import its exchange, account, paper and frozen-strategy modules without
importing SmartAPI, pyotp, legacy config or legacy execution modules.

| Existing component | Replacement | Current status |
| --- | --- | --- |
| Angel One login | `HyperliquidClient` public transport | No login or private key |
| Instrument token/lot/tick assumptions | Runtime `MarketSpec` | Ten markets required at startup |
| NSE WebSocket | `ParMarketDataEngine` | Public streaming verified |
| Historical candles | `HyperliquidMarketData.get_candles` | Completed UTC bars only |
| LTP | Separate BBO, mid, mark and oracle | No mark-price fill substitution |
| Order placement/cancellation | `HyperliquidExecution` / `PaperExecution` | Exchange writes blocked; local simulation only |
| Positions | `clearinghouseState` with `dex=par` | Public-address interface fixture-tested |
| Own pending orders (`orderBook`) | `openOrders` with `dex=par` | Public-address interface fixture-tested |
| Public market depth | `l2Book` with `par:` coin | REST and streaming verified |
| Trade fills | `userFills`, explicitly filtered to `par:` | Fixture-tested; composite fill deduplication |
| Market hours | Continuous data engine and UTC timestamps | No NSE opening/closing gate in new runner |
| Indian brokerage model | Explicit paper fee assumption, exchange funding data | Full portfolio fee/funding accounting remains future work |

Angel's own-order list and a public limit-order book have different meanings;
the account and market-data interfaces preserve that distinction.

## 3. Exchange interfaces

The package under `algo-trading-bot/exchange/` contains:

| Module | Responsibility |
| --- | --- |
| `base_exchange.py` | Generic contracts and Decimal-valued data/specification types |
| `hyperliquid_client.py` | Public testnet `/info`, namespace validation and runtime discovery |
| `hyperliquid_market_data.py` | REST validation and public stream/reconnect handling |
| `hyperliquid_execution.py` | Normalized previews and fail-closed write boundaries |
| `hyperliquid_account.py` | Team public-address positions, orders, fills and reported equity |
| `hyperliquid_reconciliation.py` | Read-only comparison of local positions/orders/fill identities |
| `paper_execution.py` | Local fractional order/fill simulation with explicit fees |

The strategy adapter calls the generic candle provider; it contains no
Hyperliquid call. New exchange modules contain no Angel SDK import. All actual
exchange writes are rejected, even if `ALLOW_LIVE_ORDERS` is accidentally set to
true, because no signed execution implementation is enabled.

Account queries use the team public address rather than an agent signer. Equity
reports the exchange's account-value field and collateral separately, avoiding
addition of overlapping unified-account balances. These account semantics still
require validation against the team's whitelisted/funded address before use in
performance reporting. Reconciliation emits differences and cannot send repairs.

## 4. Verified par data

Only `https://api.hyperliquid-testnet.xyz/info` and
`wss://api.hyperliquid-testnet.xyz/ws` are used. Startup queries `perpDexs`, finds
the `par` index and queries `meta` with `dex=par`. It requires:

`par:BTC`, `par:ETH`, `par:HYPE`, `par:SP500`, `par:EWY`, `par:EWJ`,
`par:BRENT`, `par:GOLD`, `par:USDEUR`, `par:USDJPY`.

Missing, duplicated, delisted or incorrectly prefixed required markets abort
startup. There is no native-universe fallback. Market-wide and position/order
queries select `dex=par`; coin queries require the full prefixed name.
Metadata changes invalidate cached specifications and require fresh discovery.

The stream subscribes to `l2Book`, one-minute `candle` and `activeAssetCtx`.
Disconnects revoke stream health. Each reconnect repeats discovery and restores
completed history through REST before becoming usable. Quotes reject stale BBO
and stale stream context. Candles validate identity, UTC boundaries and OHLCV;
open bars are excluded, exact REST duplicates are deduplicated and conflicting
completed REST bars fail. TLS certificate and hostname verification remain enabled.

The saved live probe on 2026-10-02 discovered index 257 and all ten markets,
returned 58 completed BTC candles in a requested 60-minute window, evaluated the
frozen brain and received ten public stream data messages. The source did not
provide a full 60-bar window; missing bars were not fabricated. There were no
reconnect errors and no submitted orders. These are public-data observations,
not a backtest, paper P&L or competition score.

## 5. Runtime specifications and normalization

`szDecimals`, `maxLeverage` and universe order are retrieved at startup. Asset IDs
use the discovered DEX index and market's runtime position. The observed index
257 and live decimals in the saved report are evidence only; no code hardcodes
those observed values. Offline tests use a different DEX index to check this.

`MarketSpec.normalize_size` rounds positive quantity down to the runtime size
step. Limit prices follow the perpetual protocol's significant-figure and decimal
rules, rounding buys down and sells up to preserve the requested limit. Orders
below the published minimum notional fail rather than increasing the strategy's
quantity. Maximum leverage is exposed as metadata; no leverage-setting action is
implemented.

Examples such as a fractional BTC quantity are supported; integer-share and
Indian lot-size normalization are absent from the new core. Local paper fills
require fresh bid/ask quotes, sufficient displayed depth and reduce-only rules.
That simple fill model has no queue position, partial-fill or portfolio funding
model and must not be reported as live execution.

## Validation and commands

The full offline suite passed: **499 tests**, including the existing regressions,
production order-policy checks, frozen-brain parity, precision rules, bad/wrong
venue responses, account fixtures and stream reconnect scenarios. The JUnit
artifact is `docs/phase1_5_tests_2026-10-02.xml`. Strategy freeze, Phase 0 safeguards
and whitespace checks passed separately. The machine-readable validation summary
and genuine public API report are saved alongside this document.

Run from the repository root:

```sh
.venv/bin/python scripts/check_strategy_freeze.py
.venv/bin/python scripts/phase0_check.py
.venv/bin/python -m pytest -q algo-trading-bot
.venv/bin/python scripts/inventory_legacy_dependencies.py
.venv/bin/python scripts/par_market_data_check.py --symbol par:BTC --bars 60 --signals --stream-seconds 8 --output /absolute/path/new-public-data-report.json
```

The final command needs public network access, not a wallet or private key.
Use a new report path for a fresh observation; preserve the existing dated
artifact as evidence. The command evaluates signals but has no trading loop.

Next migration work is the frozen management logic's integration with the new
position/execution body, validated team-address accounting, a reproducible
portfolio replay with explicit fees/funding, and eventual controlled testnet
execution. This work has not opened signed execution or claimed trading returns.

Protocol references checked during implementation:
[competition guide](https://perpetual-alpha26.github.io/docs/),
[Hyperliquid info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint),
[asset IDs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids),
[tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size),
[WebSocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions).
