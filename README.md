# Anchorium — Perpetual Alpha

This is Team Anchorium's isolated Hyperliquid testnet migration repository.
The existing cloned directory is the project root; the original NSE repository
is not used or modified by this project.

## Phase 0: exchange execution locked

`algo-trading-bot/.env.example` contains the development configuration:

```ini
TRADING_VENUE=HYPERLIQUID_TESTNET
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

No wallet or broker credential is needed for public data checks or local paper runs. The clone's inherited
`.env` has been replaced with these non-secret settings. Configuration reads
only this project's file, with process environment overrides.

All production exchange-write paths fail closed. Angel One execution is
permanently disabled, including protective/exit orders and alternate SDK paths.
Legacy login entry points use a disabled client. `LIVE_MODE=True`, old activation
evidence, credentials, or `ALLOW_LIVE_ORDERS=true` cannot enable Angel One.
Signed Hyperliquid execution is not implemented, so it also remains blocked even
if the permission flag is accidentally enabled. Paper fills remain local ledger
simulations and never reach an exchange.

The migration probe and crypto paper executor reject contradictory execution
settings. Runtime mode/permission changes stop new local orders and fills before
ledger mutation. Exchange writes remain blocked in every mode. Activation requires
an explicit future instruction after the Team Anchorium wallet is funded,
configured and manually verified; credentials or environment flags do not meet
that requirement. See the [migration policy](docs/migration_policy.md).

The original `signal_brain.py` is preserved byte for byte. A separate public data
runner now feeds completed UTC crypto candles into that unchanged brain. Existing
NSE research modules remain as classified legacy references.

## Phases 1–5: frozen strategy and public par data

The [strategy manifest](docs/strategy_freeze.json) locks the signal file, eight
strategy methods and 32 parameters to the tagged baseline. Verification runs
before the new input adapter evaluates signals. VWAP, long/short conditions,
EMA, ATR, stops, targets and direction rules have no migration changes.

The new `algo-trading-bot/exchange/` package exposes generic market data,
execution and account interfaces. Its public client is restricted to Hyperliquid
testnet `/info`; it has no signer or signed-action transport. Startup discovers
the `par` DEX index, requires all ten competition markets, and loads each market's
size decimals, maximum leverage and asset ID. Missing or inconsistent metadata
aborts startup. Size rounds down; buy/sell limit prices round conservatively
using the protocol's precision rules. Invalid orders are rejected without
increasing strategy quantities.

REST supplies completed candles, depth, BBO, mid, mark, oracle and funding data.
Public WebSocket subscriptions provide depth, candles and asset context; reconnects
repeat venue verification and restore history. The strategy consumes consecutive
completed one-minute bars with UTC date boundaries and original base volume.

Install the new core dependencies with:

```sh
.venv/bin/python -m pip install -r algo-trading-bot/requirements.txt
```

Run from this repository root:

```sh
.venv/bin/python scripts/check_strategy_freeze.py
.venv/bin/python scripts/par_market_data_check.py --symbol par:BTC --bars 60 --signals --stream-seconds 8
.venv/bin/python scripts/inventory_legacy_dependencies.py
```

The data command uses public network access and needs no wallet. It never
submits an order. To save a report, add `--output /absolute/path/report.json`.
Legacy regression tools need the optional `requirements-legacy.txt`; the new
exchange modules do not import those broker dependencies.

The historical [Phases 1–5 record](docs/phase1_5_migration_2026-10-02.md) explains the
first migration checkpoint. The [occurrence inventory](docs/legacy_dependency_inventory.csv)
classifies retained source references as REMOVE, REPLACE or KEEP AS LEGACY REFERENCE.
These are migration dispositions, not a claim that every legacy file was deleted.

The [live public data report](docs/par_market_data_live_check_2026-10-02.json)
passed on 2026-10-02: ten markets discovered, 58 completed BTC candles returned
in the requested 60-minute window, ten stream data messages, zero orders.
This is connectivity and signal-input evidence; it contains no trading-performance
result. Account reads are fixture-tested and await a team public address for live
verification. The subsequent paper portfolio implementation is described below.

## Crypto paper bot: run and review

The [step-by-step paper migration guide](docs/crypto_paper_migration_2026-10-02.md)
documents the current implementation, necessary stock-unit/session adaptations,
validation and accounting limits. The unchanged brain now connects to an all-par
periodic scanner, UTC daily session adapter, shared USDPR ledger, six perpetual
risk components and generic order lifecycle. Verified baseline management
functions handle targets, completed-candle stops, breakeven and cooldowns without
importing legacy execution plumbing. Continuous mode advances completed feed
candles between scans. No signed actions or wallet secrets are used.

Review [paper_policy.example.json](docs/paper_policy.example.json) before running.
It uses hypothetical 20,000 USDPR collateral, explicit paper fee/funding/slippage
assumptions and leverage 1. Scanner ATR/spread/history floors retain the baseline;
the strategy still permits one global position and two new setups per UTC day.

```sh
.venv/bin/python scripts/check_strategy_freeze.py
.venv/bin/python scripts/phase0_check.py
.venv/bin/python scripts/run_crypto_paper.py --cycles 1
.venv/bin/python scripts/run_crypto_paper.py --cycles 0 --scan-interval-seconds 300
```

Run either paper command from this root. Each needs public network access and
creates a fresh ignored directory under `algo-trading-bot/data/crypto-paper/`.
The runner prints the report path. Review `report.json`, `events.jsonl`,
`equity.jsonl` and `candles.jsonl`; Ctrl-C ends continuous mode. Existing runs are
not automatically resumed. Stale shutdown prices produce `shutdown.json` with
known positions and ledger events, without inventing current equity. A funding
gap or unresolved held-candle gap pauses new entries and requires review/replay.

The [genuine public paper probe](docs/crypto_public_paper_probe_2026-10-02.json)
scanned ten markets and returned `NO_TRADE`, with zero local fills and zero exchange
orders. Six markets had stale completed candles, one lacked sufficient history,
and the remaining three failed the baseline ATR and spread gates. Zero paper P&L
is a connectivity/filter result, not evidence of trading performance.

The full suite passed **595 tests**, including 68 focused paper infrastructure
checks at the first paper checkpoint. See [validation evidence](docs/crypto_paper_validation_2026-10-02.json).
A subsequent [two-scan continuous public probe](docs/crypto_public_continuous_probe_2026-10-02.json)
also passed, with ten markets per scan, two equity snapshots, `NO_TRADE`, and zero
orders. This is short integration evidence; a multi-hour exposed paper run remains
unobserved. Actual wallet fee tiers/account balances, exchange funding settlements
and signed execution remain unverified and disabled.

## Recovery, fill truth and risk controls

The [recovery guide](docs/crypto_recovery_migration_2026-10-02.md) describes the
subsequent safety implementation. Actual entry/exit accounting uses recorded fill
prices and quantities; the read-only exchange observer uses each reported fee and
signed funding payment. It never substitutes signal/VWAP/target prices or paper
fee assumptions for actual exchange fills.

`market_stream.py` blocks entries during recovery, restores REST market snapshots,
then rereads positions, orders, fills, funding and equity before accepting a new
feed generation. Default migration mode reconciles the local paper ledger. An
optional public team address enables a separate exchange-account observer; the
hypothetical paper balance is never overwritten with wallet funds. Unexplained
exchange differences remain paused while local quantities adopt exchange truth.

Each symbol has separate tick/book/candle/mark clocks. A stale or empty GOLD book
does not block a healthy BTC candidate. Snapshots preserve bid/ask, mid, mark,
oracle, funding, open interest, depth, spread and imbalance as separate fields.
Risk reports include gross/net/directional/per-symbol exposure, margin utilization
and NORMAL / CAUTION / ENTRY_PAUSED / EMERGENCY states. State changes do not
automatically flatten positions. Correlation modelling remains outside version 1.

```sh
.venv/bin/python scripts/inventory_session_dependencies.py
.venv/bin/python scripts/run_crypto_paper.py --cycles 2 --scan-interval-seconds 10
```

The full suite now passes **645 tests**, including 50 new recovery/safety checks.
The [public recovery probe](docs/crypto_public_recovery_probe_2026-10-02.json)
scanned ten markets, observed 180 WebSocket data messages, completed the paper
account barrier, and returned `NO_TRADE` with zero orders. See
[current validation](docs/crypto_recovery_validation_2026-10-02.json). Actual
team-wallet reconciliation is fixture-tested and awaits the public address;
paper fees/funding remain explicitly simulated/estimated.

## Baseline and validation

- Baseline tag: `nse-working-baseline` (a source snapshot, not certification of
  profitable or production-ready trading).
- Migration branch: `perpetual-alpha-migration`.
- Credential-free check: `.venv/bin/python scripts/phase0_check.py`.
- Offline regression suite: `.venv/bin/python -m pytest -q algo-trading-bot`.

Legacy broker protocol tests explicitly use local in-memory broker fixtures.
Their permission patch exists only in test support, accepts only those fixture
classes, and cannot authorize a real broker session. Phase 0 guard tests run
with the actual production policy.

Secrets, credentials, and runtime artifacts must remain excluded from Git.
