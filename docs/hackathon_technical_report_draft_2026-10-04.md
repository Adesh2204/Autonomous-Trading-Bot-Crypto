# Anchorium: safe migration of a deterministic VWAP agent to HIP-3 perpetuals

Engineering draft, 4 October 2026. This prepares the requested four-section report.
It is not the final 2–4 page PDF or a claim of competition readiness. Final measured
practice/scored results, selected release identity and submission formatting remain outstanding.

## 1. Problem, architecture and strategy

Anchorium adapts an existing Indian-market VWAP agent to Hyperliquid testnet's
Perpetual Alpha `par` exchange. Its deterministic direction logic remains intact.
Completed one-minute UTC candles feed the original VWAP, EMA and ATR calculations.
An input adapter supplies market-neutral candles instead of NSE tokens and stock
market sessions. Scanner settings remain ATR ≥0.40%, spread ≤15 bps, 300 completed
bars and Top-3 selection. A qualified scanner market is not automatically a trade:
the unchanged strategy must produce a valid direction, and state, economic and risk
gates must permit it.

The system separates public REST/WebSocket data, market specifications, strategy,
risk, execution and accounting. Public metadata verifies the `par` namespace and
loads size decimals, asset mappings, leverage and margin tiers. PAPER and REPLAY
use local portfolios. A separately gated future runtime uses the official Python
SDK 0.24.0 and queries the Team wallet while signing with an approved API wallet.
Current configuration is PAPER with exchange orders disabled.

## 2. Execution, safety, recovery and compliance

Every future order passes precision, minimum value, reference-price, open-interest,
margin and leverage validation. Traceable candidates carry risk and compliance
decisions. Durable client order IDs connect attempts to accepted order IDs and
reported fills. A timeout creates an unresolved state; retrying does not blindly
create another order. Partial executions update management using executed quantities.

One global position is permitted. Pending entries/exits and unresolved orders
hold the account lock. The runtime starts UNKNOWN and reconciles actual positions,
orders, fills, fees and funding before admitting entries. A separate catastrophic
protection manager can restore a reduce-only stop for actual remaining exposure;
its distance requires documented approval and is disabled during migration.

Central compliance checks block self-crossing, duplicate intent, unexplained
orders and abnormal price/liquidity participation. Transfers and account
administration are outside the trading transport allowlist. These mechanisms are
engineering controls, not a committee verdict or proof about external manual activity.
Rate reserves, persistent nonces, local ownership locks and clock monitoring protect
the same submission path. Journal events preserve known clocks and leave unknown
exchange times null. Runtime result export errors pause entries and end the loop.

## 3. Research method and validation

Production uses UTC-midnight VWAP. Isolated research compares four independent
portfolios: UTC/no ML, session/no ML, UTC/ML and session/ML. Experimental anchors
change only their declared VWAP assignments in a separate hash-verified brain.
The proposed ML model filters deterministic candidates; it does not choose direction.

Receipted public observations preserve decision-time features and costs. Training
transforms use training observations only. Chronological, purged train/calibration/
validation splits and a prospectively sealed holdout prevent lookahead. Repeated
replays and multiple arms do not manufacture independent labels. Current usable
candidate labels are zero; no ML model or alternative anchor is validated or promoted.
The baseline therefore remains the selected candidate. Further scanner/ranking/risk
experiments require sufficient measured evidence and cannot modify production.

## 4. Results, limitations and reproducibility

The final-code bounded public scan discovered ten markets but found all ten latest
completed candle histories stale. It produced zero local orders and fills, and its
recorded replay reproduced that no-trade outcome. Paper starting/ending equity was
20,000 hypothetical USDPR; local P&L, fees and funding were zero because no exposure
was opened. These observations show safe rejection and reproducibility, not profitable
trading or actual account returns. The earlier research capture also yielded no
usable completed labels. Real account/practice measurements remain unavailable.

The source freeze checks one complete signal file, eight management methods and
32 parameters. Six synthetic input sets totalling 2,050 rows reproduce the baseline
indicator outputs. Test counts, failures, source hashes and evidence identities are
provided in the accompanying engineering audit and machine-readable index. Results
carry their PAPER, REPLAY, synthetic or actual source; hypothetical fills never enter
exchange P&L. No real exchange action was submitted in this engineering pass.

Before operation, the team must verify funded USDPR collateral, unified mode and a
separate approved API wallet, explicitly authorize controlled certification, observe
LONG/SHORT and protection/recovery lifecycles, complete prolonged practice, and review
a frozen competition release. The published evaluation uses return, daily equity
volatility and jury methodology. Eligibility includes distinct trading days and a
minimum cumulative volume; legitimate opportunities must satisfy it without artificial
volume. Exact official score weights and volume threshold are not assumed here.

Sources: [competition evaluation](https://perpetual-alpha26.github.io/about),
[API and conduct rules](https://perpetual-alpha26.github.io/docs/),
[submission schedule](https://perpetual-alpha26.github.io/schedule),
[submission FAQ](https://perpetual-alpha26.github.io/faq/).
