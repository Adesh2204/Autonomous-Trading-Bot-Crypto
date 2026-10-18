# Anchorium — Perpetual Alpha

## Current Scored Phase target — PAS BTC only (18 October 2026)

The current competition build is separate from the historical PAR multi-market migration notes below. Those notes and their artifacts are not PAS readiness evidence.

- Competition-facing market: \`pas\`. Hyperliquid Testnet API DEX and coin are resolved from current venue metadata at every startup; the production market registry must contain exactly one BTC instrument. Any ambiguous mapping, missing collateral mapping, or stale market metadata means \`SAFE_HALT\`. The implementation does not fall back to \`par\` or native BTC.
- Network: Hyperliquid Testnet only. The collateral token is resolved from the live DEX and spot metadata; no \`USDPR\`/ \`USDP\` assumption is used to select collateral.
- Strategy: the frozen baseline is retained. \`signal_brain.py\` and \`docs/strategy_freeze.json\` are not modified; BTC-only runtime filtering occurs in the input/venue layers.
- Risk: one BTC position at 1x leverage, single candidate, fixed low per-trade risk and a maximum gross exposure of 25% of actual reported equity in the example profile. The competition caps of $10 million per BTC market and $50 million per DEX are hard upper bounds, not objectives.
- Continuous operation: no exchange-session open, entry cutoff, or clock-triggered end-of-day liquidation. Existing account/position/order recovery and protective management must pass before new entries are allowed.
- Scoring: 19 October 2026 12:00 UTC through 6 November 2026 12:00 UTC. New entries are rejected outside that half-open window. The owner loop records an auditable daily snapshot at 12:00 UTC; missing or unreconciled snapshots block new entries rather than substituting estimates.
- The $100,000 value is a target and a paper-profile reference only. Live sizing and readiness use the account's reported equity, available margin, positions, orders, fills, fees and funding.

### PAS BTC preflight

Install core dependencies and verify the frozen baseline:

\`\`\`sh
python -m pip install -r algo-trading-bot/requirements.txt
python scripts/check_strategy_freeze.py
\`\`\`

Run the default read-only startup probe (it never loads the private key or sends orders):

\`\`\`sh
python scripts/run_pas_btc.py --output /tmp/pas-btc-preflight.json
\`\`\`

The probe deliberately returns \`BLOCKED\` until live account reconciliation, API-wallet approval, controlled fill/exit tests, protective-order verification, restart recovery and supervisor tests are certified. \`SAFE_HALT\` means the read-only venue/data probe failed. It never prints wallet secrets.

The live mode requires a separate operator invocation with \`--run-live --confirm-live-testnet\`, explicit Testnet environment settings, a manually verified and unexpired approval, matching current DEX fee-scale evidence, and a certification report for all 20 critical tests whose commit and PAS BTC mapping match the running source. The existing \`configs/reliability_policy.json\` keeps protection disabled by default; the live path refuses to start until a separately controlled protective-order policy is explicitly enabled and verified. No certification artifact is included in this branch, and this PR does not claim \`READY_FOR_SCORED_PHASE\`.

The new offline PAS safety suite can be run with:

\`\`\`sh
cd algo-trading-bot
python -m pytest -q test_pas_btc_competition.py
cd ..
python scripts/check_strategy_freeze.py
\`\`\`

These offline checks do not certify a funded team wallet or substitute for the controlled Testnet lifecycle and protection tests.


This is Team Anchorium's isolated Hyperliquid testnet migration repository.
The existing cloned directory is the project root; the original NSE repository
is not used or modified by this project.

## Historical engineering audit — 4 October 2026 (superseded for the PAS BTC scored phase)

The current verdict is **ACCOUNT_SETUP_REQUIRED**. PAPER/false remains enforced.
Passing unit tests and public-data probes do not certify a funded account,
actual exchange execution, prolonged practice, or a competition-ready release.

See the [A–S engineering report](docs/hackathon_final_engineering_report_2026-10-04.md)
and [readiness matrix](docs/hackathon_certification_2026-10-04/readiness.md).
Regenerate the read-only evidence index with:

```sh
.venv/bin/python scripts/run_hackathon_certification.py \
  --tests-xml docs/hackathon_certification_regression_2026-10-04.xml \
  --tests-receipt docs/hackathon_certification_test_receipt_2026-10-04.json \
  --market-evidence docs/hackathon_public_readiness_2026-10-04.json \
  --session docs/hackathon_public_paper_final_2026-10-04 \
  --session docs/hackathon_public_replay_certified_2026-10-04 \
  --research-evidence docs/research_readiness_release_2026-10-04/readiness.json \
  --output docs/hackathon_certification_2026-10-04
```

The report cannot activate trading. Historical evidence whose source hash differs
from current code is explicitly marked incompatible. Newly exported signed
fixtures use `SYNTHETIC_SIGNED_FIXTURE`; old artifacts retain their historical
labels and must always be interpreted with their execution mode.

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
Signed Hyperliquid execution is implemented through SDK 0.24.0, with a separate
manual approval and verified account gate. It remains blocked under PAPER/false;
an environment flag alone cannot activate it. Paper fills remain local ledger
simulations and never reach an exchange.

The migration probe and crypto paper executor reject contradictory execution
settings. Runtime mode/permission changes stop new local orders and fills before
ledger mutation. Default exchange writes remain blocked. Activation requires
an explicit future instruction after the Team Anchorium wallet is funded,
configured and manually verified; credentials or environment flags do not meet
that requirement. See the [migration policy](docs/migration_policy.md).

The original `signal_brain.py` is preserved byte for byte. A separate public data
runner now feeds completed UTC crypto candles into that unchanged brain. Existing
NSE research modules remain as classified legacy references.

## Historical multi-market migration notes — PAR (not the current production route)

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
and funded-wallet execution remain unverified. Actual exchange submissions are disabled.

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

At the recovery checkpoint, the full suite passed **645 tests**, including 50 new recovery/safety checks.
The [public recovery probe](docs/crypto_public_recovery_probe_2026-10-02.json)
scanned ten markets, observed 180 WebSocket data messages, completed the paper
account barrier, and returned `NO_TRADE` with zero orders. See
[current validation](docs/crypto_recovery_validation_2026-10-02.json). Actual
team-wallet reconciliation is fixture-tested and awaits the public address;
paper fees/funding remain explicitly simulated/estimated.

## Session evidence and offline replay

The [audit and replay guide](docs/crypto_audit_replay_2026-10-02.md) gives the
step-by-step run and wallet/practice sequence. Every session now writes the ten
requested files under its `results/` directory, plus candidate traces and a
manifest with Git/source/configuration/strategy/adapter/risk hashes. Events
carry exchange, receive and processing clocks; unavailable exchange timestamps
stay null. Mark-valued paper equity and oracle-valued estimates remain separate,
and sparse daily metrics are labelled as observed local samples.

A bounded public paper scan without an account observer records a complete
REST/clock tape. Replay uses historical completed bars and their observed quotes
through the same frozen strategy and local execution kernel without HTTP or
sockets. Keep `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` for both runners;
REPLAY is the offline run context. The future testnet executor has an additional
manual authorization, funded-account, agent-approval and reconciliation gate.

```sh
.venv/bin/python scripts/run_crypto_paper.py --cycles 1
.venv/bin/python scripts/run_crypto_replay.py --tape '<session>/replay_tape.json' --output '<new-replay-session>'
```

Blank/zero team addresses report NOT_CONFIGURED; a valid public address remains
unverified. All signed actions, including close/cancel/leverage, stay blocked.
The audit/replay checkpoint passed **678 tests**. A [genuine public audit scan](docs/crypto_public_audit_probe_2026-10-02.json)
found ten markets with stale completed candles and returned NO_TRADE with zero
orders/fills; its offline replay matched diagnostics, decisions and portfolio.
See [validation and limitations](docs/crypto_audit_validation_2026-10-02.json).
The replay runner supports complete single-scan tapes. Continuous-feed replay and
funded-wallet trade verification remain future work. Signed transport is now
implemented and exercised with isolated offline fixtures.

## Signed execution infrastructure: implemented, activation locked

The [production execution engineering report](docs/live_execution_engineering_report_2026-10-02.md)
contains the architecture, exact changed paths, validator, actual-account
accounting, restart/reconnect recovery, tests and future activation procedure.
The earlier complete-project report is a historical snapshot from before this
execution phase.

The executor uses the official Hyperliquid SDK 0.24.0. Account reads use the
team public address; only an approved API wallet signs. Durable CLOIDs prevent
blind resubmission after a timeout. Actual results use reported fills, fees and
funding, with separate mode/source fields from PAPER and REPLAY.

The normal development configuration remains PAPER/false. No exchange order was
submitted during this implementation. The original execution checkpoint passed
**761 tests**, including **83 focused cases**. The reliability upgrade below adds
a full independent catastrophic protection lifecycle; it remains disabled until
an explicit distance policy and separate human activation approval are supplied.
Normal frozen stop/target management is unchanged.

Run the read-only readiness probe:

```sh
.venv/bin/python scripts/check_live_readiness.py --output docs/live_execution_readiness_2026-10-02.json
```

This command cannot load a signer or send `/exchange` actions. To check account
setup, add `--team-wallet PUBLIC_ADDRESS --api-wallet-address PUBLIC_ADDRESS`.
Keep both private keys out of command arguments and shared output. This probe
does not restore strategy management state and cannot authorize activation.

## Production reliability and catastrophic protection

The [reliability engineering report](</Users/adesh/Autonomous Trading Bot - Crypto /docs/production_reliability_report_2026-10-03.md>)
explains the audit, all changed files, API priorities/reserves, durable nonce
faults, clock recovery, process ownership, trigger lifecycle, tests and remaining
account verification. The [public policy file](</Users/adesh/Autonomous Trading Bot - Crypto /configs/reliability_policy.json>)
sets the operational limits. Protection defaults to disabled with no distance or
slippage value. Loading a policy grants no exchange-write permission.

The shared API manager throttles optional work first, reserves capacity for
position safety, tracks WebSocket budgets and retries only safe reads. Signed
orders, cancels and leverage actions retain durable uncertainty barriers. The
protection manager uses verified positions and official SDK reduce-only triggers;
it verifies, resizes, cancels, and recovers them without changing strategy stops.
Results now include protection events and readable/JSON production safety reports.

```sh
.venv/bin/python scripts/check_live_readiness.py --output docs/production_safety_readiness_2026-10-03.json
.venv/bin/python scripts/verify_reliability_strategy_parity.py --output docs/reliability_strategy_parity_2026-10-03.json
.venv/bin/python -m pytest -q
```

The public readiness command never creates a signer. Blank wallets remain
unconfigured, with unknown account/protection state and LIVE readiness false.
The strategy comparison covers 2,050 identical candles from the pre-upgrade source.
See the engineering report for final regression counts and failure-injection evidence.

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

### Crash-safe restart and opportunity diagnostics

The restart phase adds one startup state machine over the existing account
reconciler, atomic combined checkpoints in the same SQLite journal, clean/unclean
shutdown markers and exposed-downtime candle review. New entries remain locked
until a second reconciliation after account-stream acknowledgements. Unknown
positions, unexplained orders, incomplete history and missing strategy state
require review.

Opportunity traces now cover all verified markets and each admission gate.
Session, daily, market, UTC-hour, distribution and Top-3 exclusion reports are
written beside existing results. Diagnostic observations do not change scanner
ATR 0.40%, spread 15 bps, 300-bar history, Top-3 or any frozen strategy parameter.

The isolated research command accepts saved observations only:

```sh
.venv/bin/python scripts/research_crypto_opportunities.py \
  --traces '<session>/results/opportunity_traces.jsonl' \
  --output '<new-research-directory>'
```

Optional `--holdout-start-ms` and `--outcomes` support chronological, cost-aware
comparisons using explicit recorded outcome evidence. Missing outcomes stay
unknown; research cannot submit orders or promote a policy. See
[the restart/diagnostics handover](docs/restart_opportunity_report_2026-10-03.md)
and [validation evidence](docs/restart_diagnostics_validation_2026-10-03.json).

### Isolated VWAP anchor and candidate-quality ML research

Production keeps `VWAP_BASELINE_UTC`, the frozen strategy, existing state/risk
rules, `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false`. The research package
is never imported into trading permissions and has no exchange transport.

The research brain changes only VWAP and its slope in a separate compiled copy.
EMA, ATR, volume and warmup retain their UTC controls. Configured reference times
are documented in `research/configurations/anchor_policies.json`; they are daily
information-anchor hypotheses, not official `par` trading sessions or calendars.

Candidate models use explicit feature clocks, after-cost outcome lineage,
chronological purged splits, train-only transforms, separate calibration and
threshold windows, immutable JSON versions and a sealed holdout. They recommend
permission only and retain the strategy's direction. Missing required evidence
means `ML_UNAVAILABLE`; inadequate data means `INSUFFICIENT_DATA`.

Read [the fourteen-section engineering report](docs/vwap_ml_engineering_report_2026-10-04.md)
and [saved evidence outputs](docs/strategy_intelligence_research_2026-10-04-final/reports/competition_research_summary.md).

```sh
.venv/bin/python scripts/run_strategy_intelligence_research.py \
  --traces docs/restart_diagnostics_observations_2026-10-03/opportunity_traces.jsonl \
  --candles algo-trading-bot/data/crypto-paper/public-audit-probe-2026-10-02/candles.jsonl \
  --candidate-events algo-trading-bot/data/crypto-paper/restart-diagnostics-final-public-replay-2026-10-03/results/candidate_traces.jsonl \
  --assumptions research/configurations/recorded_public_assumptions_2026-10-02.json \
  --output /tmp/anchorium-new-research-run
```

Use a new output directory for each attempt. The available saved sample has no
valid candidates or labeled outcomes, so it cannot validate ML or a new anchor.
Conditional candidate outcomes do not establish a changed portfolio's fills,
mark drawdown or daily equity volatility. No experiment promotes itself.
PAPER/false and disabled catastrophic-policy defaults remain enforced.


### Collecting evidence for the six readiness flags

The next workflow records public receipts, replays four independent paper
portfolios, audits completed-trade labels, and fits/seals models before a future
holdout. It derives readiness from evidence and has no production activation
operation. The original scanner window and all existing strategy/risk/state
sources remain unchanged. Longer session history supplies only the isolated
VWAP and slope assignments.

Read [the structured readiness guide](docs/research_readiness_work_report_2026-10-04.md)
for commands, observed blockers, label lineage, thresholds, and current results.

```sh
.venv/bin/python scripts/collect_research_evidence.py \
  --duration-seconds 3600 \
  --output algo-trading-bot/data/crypto-research/my-hour-01

.venv/bin/python scripts/run_research_readiness.py replay \
  --capture algo-trading-bot/data/crypto-research/my-hour-01 \
  --output algo-trading-bot/data/crypto-research/my-hour-01-lab

.venv/bin/python scripts/run_research_readiness.py status \
  --lab algo-trading-bot/data/crypto-research/my-hour-01-lab \
  --output algo-trading-bot/data/crypto-research/my-hour-01-status
```

Every output directory must be new. The recorder uses a bounded duration,
one-second observations, the unchanged 300-second scan schedule, and a separate
3,000-bar receipt cache. After the initial history, it saves incremental candle
updates. Once each minute it reads completed candles through public REST, so a
pre-close WebSocket update is never relabelled as a final bar.

The preserved maximum of two new setups per day means at least 250 days would
be needed for 500 unique completed reference trades, even before other data
quality requirements. Replaying the same sample or pooling identical UTC
controls does not create additional labels. Keep the deterministic baseline
available while ML remains gated by adequate evidence. These tools do not
change production or permit any exchange submission.

## One-position execution safety and compliance

The signed testnet executor now uses a durable `SinglePositionGuard` and central
`ComplianceGuard` before exchange validation. It reserves one account-wide slot
in the same transaction as the entry intent, reads actual positions and
trigger-aware open orders, and rechecks account truth at the SDK boundary.
Partial entries/exits, unresolved attempts and old protection keep the account
occupied. Restart or disconnect revokes entry permission until reconciliation.

Every order needs classified provenance, risk/execution decisions, current price
references and duplicate/self-cross checks. Exposure-increasing entry replacement
is blocked in this phase. The SDK sink accepts only a guard-issued permit for the
exact validated action; it exposes no autonomous transfer/admin method. A host
account lease prevents separate production processes/signers from trading the
same team account concurrently. A dedicated account and one deployment host
remain prerequisites; unrelated manual activity or other computers are outside
the local lock's control.

Live-session exports include `compliance_events.jsonl`, `compliance_summary.json`,
`compliance_summary.txt` and `strategy_performance.json`. Controlled tests and
unattributed fills are excluded from strategy statistics while remaining actual
account truth. Synthetic runs are labelled and cannot establish compliance or
funded-account readiness. `LIVE_READY` remains false pending real certification.

The [single-position/compliance report](docs/single_position_compliance_report_2026-10-04.md)
explains the audit, policy, tests, limits and future roadmap. `MAX_GLOBAL_POSITIONS=1`,
`EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` remain enforced.
