# Anchorium: fill truth, recovery and scoped risk controls

The latest pasted request is implemented in this cloned repository. Execution
remains `PAPER`, `ALLOW_LIVE_ORDERS=false`; every signed action is blocked. The
signal file, eight frozen methods and 32 parameters still match the tagged
baseline. No private key or team-account secret was loaded.

## 1. Verify actual-fill accounting

`PaperExecution` fills at fresh executable bid/ask, within the submitted limit and
displayed size. Its ledger uses the recorded fill price and quantity for entry,
weighted average entry, reductions and realized P&L. Signal/VWAP/stop/target prices
remain requests or triggers. They are never substituted for a fill.

A regression scenario buys two contracts at observed ask **100.18**, despite a
requested limit of **100.50**, then sells at observed bid **101.84**, despite a
requested limit of **101.50**. Gross realized P&L is `2 × (101.84 - 100.18)`;
recorded simulated fees and labelled funding are applied separately. Distinct
mark/oracle values do not change those execution prices.

For actual account observation, `HyperliquidAccount.get_fills()` preserves
exchange-reported `px`, `sz`, `fee`, `feeToken`, `closedPnl` and `startPosition`.
`get_funding()` preserves each signed reported cashflow. The protocol calls that
amount `delta.usdc` for HIP-3 responses; the par observer labels its collateral
USDPR without converting or recomputing the payment. Composite identities prevent
duplicates; invalid or conflicting events fail closed.
[Hyperliquid fills](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint),
[funding history schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals).

Observed-account realized reporting is:

```text
sum(reported closedPnl) - sum(reported fill fees) + sum(reported signed funding)
```

Its scope is the observed event window. It excludes transfers/deposits and unknown
history. A missing `closedPnl` gives an unknown net amount and pauses entries;
expected fees or theoretical entry/exit values cannot fill that gap. The paper
ledger still uses explicitly declared fee assumptions and estimated boundary
funding. Those are separate evidence sources.

## 2. Reconcile local state against its authoritative source

`HyperliquidReconciliation.recover()` reads positions, open orders, fills, funding
and equity, then rereads positions/orders to detect an unstable account view.
Venue-wide queries select `dex=par`; event queries filter prefixed coins explicitly.
No method sends a repair to the exchange.

The exchange mirror adopts actual reported quantities and entries. If local BTC
quantity is 0.05 but the exchange reports 0.04, the mirror becomes 0.04. Entries
stay paused unless the observed fills explain that 0.01 difference. Repeating an
unchanged REST response cannot silently clear the missing-history pause. Unknown
open orders, missing entry/P&L information, conflicting events and history gaps
also keep entries paused. Already observed fees/funding never apply twice.

Successful recurring observation uses an inclusive 60-second overlap, preserving
cumulative observed P&L and the original accounting-window start. Unresolved gaps
retry the initial evidence window. Large/truncated history reads stop at the
observer's conservative budgets and require bounded backfill/review; a complete
wallet-lifetime history is not claimed.

`PaperReconciliation` instead replays this run's recorded simulated fills and
labelled funding. It repairs local quantities/cash from those events, preserves
virtual stop/target concepts, and rereads local positions/orders/fills/funding/
equity. Missing strategy or fill evidence pauses recovery. Its report explicitly
says `exchange_account_verified=false`. No wallet state overwrites the hypothetical
paper portfolio.

## 3. Recover the feed before permitting entries

The public engine sends heartbeats, detects receive/pong stalls, disconnects,
retries within the configured budget and resubscribes. Every recovery follows:

```text
Block new entries
→ connect and resubscribe
→ REST par metadata, contexts, completed candles and order books
→ main-thread account reconciliation
→ verify the feed generation did not change during account reads
→ resume eligible symbols
```

The participant guide requires a REST account reread after reconnecting.
[Competition stream instructions](https://perpetual-alpha26.github.io/docs/#streams).

`market_stream.py` supervises that sequence. Worker callbacks only enqueue facts;
the main thread owns ledger/account recovery. A disconnect or account failure
blocks all entries. Account retries back off. A public-address observer also
rereads its account every minute. It grants no signing or activation permission.

Every market retains four independent clocks:

| Clock | Supplied limit | Meaning |
| --- | --- | --- |
| Tick | 5 seconds | Latest valid BBO tick or observed public trade |
| Order book | 5 seconds | Source book timestamp |
| Completed candle | 120 seconds after minute completion | Last actual completed bar, never a fabricated flat candle |
| Mark/context | 60 seconds | Receipt time of published context; not a claim about on-chain update time |

Unknown, future or stale clocks pause that symbol. A stale or empty GOLD book
leaves a healthy BTC candidate eligible. A transport/account/venue failure blocks
all entries. Empty/crossed books are handled locally; identity/schema failures
retain the stricter connection safeguards. Held positions need valid marks for
valuation, so unavailable held data produces an unvalued halt record rather than
invented current equity. Existing positions are not automatically flattened by a
feed-state change.

## 4. Inspect market prices, depth and portfolio exposure

`MarketSnapshot` stores bid, ask, mid, mark, oracle, funding, open interest,
independent timestamps and optional observed last-trade price. It also records
spread/bps, top quantities, cumulative displayed bid/ask notional and book
imbalance `(bid depth - ask depth) / (bid depth + ask depth)`.

Execution uses BBO; candle/VWAP inputs feed the unchanged strategy; mark/oracle and
account information support valuation/risk. A missing last trade remains null.
Imbalance is a diagnostic, not a new strategy condition. Funding remains a cost/
risk input. Leverage constrains margin, while stop-loss risk sets the quantity
ceiling; tests show 10× leverage does not multiply a risk-sized position by ten.

Reports now include gross/net exposure, long/short notionals, directional
concentration, per-symbol exposure, margin utilization and position count. The
ledger can represent multiple contracts, but the frozen strategy still permits
one global position and two new setups per day. Correlation modelling is deferred.

## 5. Understand the scoped circuit breakers

| State | Behavior |
| --- | --- |
| NORMAL | Healthy inputs and portfolio; normal entry checks apply |
| CAUTION | Some symbols are paused or risk approaches a limit; healthy candidates still pass the full gate |
| ENTRY_PAUSED | Global account/recovery/order-error or financial limit prevents new entries |
| EMERGENCY | Equity/maintenance condition requires attention; the existing local protective-exit path remains separate |

New explicit sample assumptions include 5% maximum drawdown, 1× equity gross/net/
symbol/directional caps, three consecutive order errors and five reconnect
failures. Existing daily-loss, margin, position, spread and funding gates remain.
Thresholds are in `docs/paper_policy.example.json`; none optimize the brain.
Order-error circuits latch and do not clear merely because an unrelated order
succeeds. UTC day boundaries reset the daily budget; run drawdown remains measured
against its high-water mark. State transitions themselves never create an order
or flatten a portfolio.

## 6. Run and review

From the repository root:

```sh
.venv/bin/python scripts/check_strategy_freeze.py
.venv/bin/python scripts/phase0_check.py
.venv/bin/python scripts/inventory_session_dependencies.py
.venv/bin/python scripts/run_crypto_paper.py --cycles 2 --scan-interval-seconds 10
```

For continuous paper observation use `--cycles 0 --scan-interval-seconds 300`.
The runner prints its fresh output path. Review `risk_state`, `feed_health`,
`market_snapshots`, `public_stream`, `paper_account_recovery`, `exposure` and each
candidate's `market_snapshot` in `report.json`, alongside the existing source-bar,
event and equity files. Ctrl-C preserves known state; stale valuation stays null
in a shutdown/halt record. There is no automatic process restart/resume.

After obtaining the team public address, a separate read-only observer can be
enabled with `--account-address <TEAM_PUBLIC_ADDRESS>` and
`--account-history-start-ms <UTC_EPOCH_MILLISECONDS>`. Both are explicit inputs;
invalid addresses or a missing history start are rejected before output/network.
Review `exchange_account_observer` in the report. No private key, API signer,
account administration, funding transfer or exchange order is enabled by these
options. No team address was available for this validation, so actual account
reads/recovery are validated with synthetic fixtures only.

## 7. Measured validation

The full suite passes **645 tests**, including **50 new recovery/safety tests**.
The freeze, Phase 0 guards and session audit pass. The audit locates 09:15, 15:30,
opening/closing/premarket terms, IST and weekday assumptions in non-secret source/
documentation. It found zero such dependencies in the cold crypto import graph.
Retained stock code and frozen-method references stay isolated behind the UTC,
continuous adapter; the original NSE repository was not edited.

At **2026-10-02 09:18:45 UTC**, the two-scan public probe observed:

| Measurement | Result |
| --- | --- |
| Markets per scan / equity observations | 10 / 2 |
| WebSocket data messages / reconnects | 180 / 0 |
| Recovery generation accepted | 1; local paper account reread complete |
| State / watchlist | CAUTION / empty |
| Nine markets | Paused for stale completed candles |
| SP500 | Healthy feed, rejected by baseline ATR/spread gates |
| Outcome / local orders / fills / exchange orders | NO_TRADE / 0 / 0 / 0 |
| Ending equity | Hypothetical 20,000 USDPR; no trading-return evidence |

The exact report is `crypto_public_recovery_probe_2026-10-02.json`. JUnit evidence
is `crypto_recovery_tests_2026-10-02.xml`; source/probe hashes and validation are
in `crypto_recovery_validation_2026-10-02.json`. The public probe exercised the
ordinary recovery path. Real disconnects/account mismatches, empty books and
incremental account-history recovery have deterministic offline tests. A prolonged
public run with paper exposure and actual team-account reconciliation remains
unobserved. Exchange signing and live trading remain disabled.
