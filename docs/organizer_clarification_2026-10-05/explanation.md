# Organizer clarification: what it means for Anchorium

Date: 5 October 2026. Basis: the two Discord screenshots supplied by the user, the current official Participant Guide, and inspection of the repository. The screenshots explain competition requirements; they do not authorize wallet administration or exchange orders.

## Direct answer

The clarification mostly matches our infrastructure. One real mismatch was found and corrected: the central 80% order-price check used the oracle price. It now uses the mark price, as the organizer requested. This is an exchange validation correction, not a strategy change.

The account-mode gate already requires `unifiedAccount`. The central entry check already reads the team account's `activeAssetData` for the exact `par:` coin and chooses the requested LONG or SHORT capacity. The bot remains PAPER-only under the current configuration. These findings do not prove the actual team account is funded, configured, certified or authorized to trade.

## 1. Funding and unified mode

USDPR is the competition's test collateral. Think of it as the account balance that supports a position and absorbs its losses, fees and funding. It is separate from the hypothetical balance in our PAPER simulation.

The organizer's message says funding will be sent. That is a promise, not a balance receipt. We have not verified a new account balance during this review.

Unified mode tells the venue to use the team's USDPR balance as shared collateral. It is a one-time account setup operation after funding, using `userSetAbstraction` with `unifiedAccount`, signed by the team wallet. Follow that team-signed setup path from the organizer. Keep the team private key outside this bot.

The API wallet is a separate authorized trading signer. Queries for balances, positions, fills, approval and trading capacity must use the team account address. Querying the API wallet's own address would inspect the wrong account. Approving the API wallet and checking its expiry are also necessary before future trading.

Our `verify_live_account_readiness` checks account mode, positive reported collateral/account value, separate approved API wallet and expiry, fees, request budget, reconciliation, clock and rate health. It reads account state; it does not switch modes or approve a wallet. Technical readiness does not replace the explicit human authorization and controlled-account certification required by our project.

The [official setup instructions](https://perpetual-alpha26.github.io/docs/#set-up-the-account) describe the same team/API separation and unified USDPR collateral.

## 2. The 80% rule

The organizer specifies **`markPx` from `metaAndAssetCtxs`** as the reference for this particular order-price band.

The three prices have different jobs:

| Price | Easy meaning | Use in our system |
|---|---|---|
| Mark | Venue's position valuation price | Margin/unrealized valuation and the clarified 80% order band |
| Oracle | External reference delivered to the venue | Separate funding, reference and compliance calculations |
| Best bid/ask | Prices available on the local book | Executable entry/exit price limits and liquidity checks |

If the mark is 100, the 80% band by itself allows a limit price from 20 through 180:

`abs(order_price - mark_price) / mark_price <= 0.80`

This does not make a trade at 180 sensible, permit 80% execution slippage, or define the strategy's stop-loss. Our tighter book/reference, spread, liquidity, risk and permission checks still apply. Passing this one band is only one requirement for an order.

### What changed

`algo-trading-bot/exchange/exchange_rules.py` now reads `q.mark` for that band. `q.mark` is supplied by `markPx` from the `par` asset context. The audit records `reference_price_source=markPx`, the actual reference value, deviation and a separate oracle value.

Open-interest notional continues to use its previous oracle reference; funding and compliance code were not changed. There was no broad replacement of oracle with mark. VWAP, EMA, ATR, LONG/SHORT decisions, stops, targets and strategy state were not changed.

Tests distinguish mark from oracle, cover both exact 80% edges and prices just outside them, reject invalid/missing marks without oracle fallback, and preserve oracle-based open-interest calculations. They make no exchange submissions.

### About the screenshot's “2% to 5%” comment

Treat it as an explanation, not a fixed range to put in code. The current guide lists different market limits, including a 10% EMA basis bound for HYPE at a 10x maximum leverage. It also describes several inputs and clamps in the mark calculation. A cap on one basis input should not become a blanket guarantee about every observed final mark/oracle difference. Read the actual returned mark and runtime metadata. [Official pricing description](https://perpetual-alpha26.github.io/docs/#oracle-and-mark-prices).

## 3. `availableToTrade` and `maxTradeSzs`

For a query such as `activeAssetData(user=TEAM_ADDRESS, coin="par:BTC")`, the organizer describes:

`availableToTrade = [LONG capacity, SHORT capacity]`

These values are in USDPR. They describe collateral capacity for new exposure on each side of that particular coin. They are alternatives backed by the same account, not two independent pots of money.

`maxTradeSzs = [maximum LONG size, maximum SHORT size]`

These values are in the contract's size units; for `par:BTC`, they are BTC units. The organizer's relationship is:

`maximum size = availableToTrade × selected leverage / markPx`

For illustration only, suppose BTC's mark is 50,000, selected leverage is 1x, and available capacity is `[1000, 700]`:

| Direction | Collateral capacity | Illustrative maximum size |
|---|---|---|
| LONG | 1,000 USDPR | 0.0200 BTC |
| SHORT | 700 USDPR | 0.0140 BTC |

That is not 1,700 USDPR of freely spendable money. Do not add the two entries or reuse one coin's capacity for another coin. Re-read capacity when evaluating the actual order, because account state and prices change.

Use the selected leverage returned for that coin, not its maximum permitted leverage. Our current entry policy remains 1x. Higher venue limits are permissions, not a recommendation to use them.

The actual returned `maxTradeSzs` remains a pre-trade limit; the formula explains its units and meaning, rather than replacing exchange data with a locally invented balance. Normalize quantity down to the permitted lot. Risk sizing, executable-price margin checks, fees, liquidity and safety constraints may reduce the order further. The spot balance alone is not free margin. [Official margin description](https://perpetual-alpha26.github.io/docs/#venue-mechanics).

### What our bot already does

The central validator checks team identity, coin identity, selected leverage and cross-margin mode. For BUY it selects array index 0; for SELL it selects index 1. It independently checks the returned maximum size and available collateral. New regressions verify asymmetric LONG/SHORT arrays for both fields, so a funded side cannot hide an unfunded requested side.

Earlier portfolio sizing uses the smaller of the two available-collateral values. In the example it would use 700 USDPR as its conservative margin input, including for a LONG. This can undersize or reject a permitted LONG; it does not combine the arrays or authorize excessive exposure. We retained that conservative policy rather than tuning strategy/risk behavior during this clarification. The project also retains its one-global-position limit.

## 4. Alignment and what still has to happen

| Requirement | Code status | Real-account status |
|---|---|---|
| Hyperliquid testnet and `par` selection | Implemented | Public connectivity observed in earlier PAPER runs |
| USDPR and unified-account gate | Implemented | New funding and actual mode not verified in this review |
| Team account reads, separate approved API signer | Implemented | Actual approval/expiry still must be verified |
| 80% reference is mark | Corrected in this review | No live order used as a test |
| Per-coin, per-side capacity | Implemented and tested | Actual account values still must be verified |
| Frozen strategy and PAPER lock | Retained | No activation occurred |

The proper sequence for future funded practice is:

1. Verify USDPR actually arrived at the exact registered team account using a read-only balance query.
2. Complete the organizer's team-signed unified setup outside the bot, then verify `userAbstraction` returns `unifiedAccount`.
3. Complete and verify approval/expiry of a separate API wallet. Check account state using the team address.
4. Verify fresh `par` data, current per-coin capacity, selected leverage, fees, reconciliation, monitoring and the reviewed emergency-protection policy.
5. Complete the project's controlled-account checks and obtain the human's explicit future activation instruction before enabling any signed testnet orders.

Funding does not repair stale public candles. Earlier short PAPER observations showed intermittent freshness and `NO_TRADE`; they did not establish sustained healthy data or trading profitability. A server is a separate operating decision, not a requirement created by these three clarifications. Continuous-host validation remains pending.

Current configuration remains:

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

The source change also changes the strict PAPER checkpoint identity. Earlier ledgers and evidence remain preserved. The updated operating runbook selects a separately labeled `runtime/paper/markpx-validation` ledger for a future run; no run on that new ledger is claimed by this review. Never overwrite or reset an older ledger to conceal the source change.

## Verification records

The final full suite passed **1,198 tests**, with zero failures, errors or skipped tests. This includes 20 new clarification cases. Source fingerprints match before and after that run. Strategy-freeze verification passed for the protected file, eight methods and 32 parameters; Phase 0 confirmed PAPER mode, disabled exchange writes and the unchanged signal source. The full result and source fingerprints are recorded in the accompanying [test receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/organizer_clarification_2026-10-05/test_receipt.json>) and `regression.xml`. No team-wallet key was required, no account setup action was performed, and no order was sent to the exchange. Offline signed fixtures use ephemeral test identities with exchange-network transport blocked.

The first broad run identified two errors in the newly added invalid-mark test fixture: it changed the first market's context rather than locating BTC by name. The corrected fixture uses the metadata's actual market mapping. All 20 new clarification cases then passed in the focused run. That earlier broad result is preserved in `development_test_receipt.json` and `development_regression.xml`; the separate final receipt reports the corrected-source full run.
