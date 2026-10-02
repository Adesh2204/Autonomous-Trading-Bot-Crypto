# Anchorium: session evidence and offline replay

This checkpoint adds timing, reproducible session manifests, candidate traces and
an offline execution mode to the existing market migration. The VWAP brain,
LONG/SHORT conditions, ATR, EMA, stops, targets and frozen state methods remain
unchanged. There is no strategy optimization or ML addition in this checkpoint.

## 1. Keep the migration lock

Run from this cloned repository. Both `.env.example` files contain placeholders:

```ini
TRADING_VENUE=HYPERLIQUID_TESTNET
HL_NETWORK=testnet
HL_DEX=par
TEAM_WALLET_ADDRESS=
API_WALLET_PRIVATE_KEY=
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

No private key is needed or loaded by an exchange signer. Do not fill the key
placeholder during migration. Environment files, `.key` files, `wallets/`,
`secrets/` and runtime results are ignored; the example files remain trackable.
Wrong network, DEX or execution flags fail before the runner creates a session.
The original NSE repository is untouched.

The run architecture exposes REPLAY, PAPER and a blocked LIVE interface:

| Run | Input | Execution | Safety configuration |
| --- | --- | --- | --- |
| REPLAY | Recorded chronological REST responses, including historical completed OHLCV and quote observations | Same local precision, BBO-fill and portfolio kernel | PAPER / false |
| PAPER | Public Hyperliquid testnet `par` data | Local simulated orders and fills | PAPER / false |
| LIVE | Future exchange account integration | Interface present; every write raises `LiveTradingDisabled` | Disabled |

REPLAY is a run's data/execution context. Keep the environment's safety mode
PAPER. Setting `EXECUTION_MODE=REPLAY` or LIVE does not open another routing path;
it fails the migration policy. Selecting a public address or changing a flag
cannot enable signed actions. Place, submit, cancel, modify, close and leverage
interfaces all fail before client access. Local paper cancellation remains
available after policy revocation to release local reservations.

## 2. Verify the frozen strategy and infrastructure

```sh
.venv/bin/python scripts/check_strategy_freeze.py
.venv/bin/python scripts/phase0_check.py
.venv/bin/python -m pytest -q algo-trading-bot
```

The full suite passed **678 tests**, including **33 new audit/replay checks**.
Freeze verification covers one byte-identical file, eight methods and 32
parameters. Existing tests cover discovery, conversions, direct-brain indicator
and decision parity, precision, spread, fractional sizing, margin/exposure limits,
partial fills, IOC cancellation, rejection, feed stalls, reconnect barriers,
duplicate fills, actual fill-based P&L and funding. The new tests cover all
results files, trace links, timestamp provenance/skew, idempotent report saves,
mark versus oracle valuations, provisional daily returns, placeholders, every
LIVE interface, offline replay without sockets, deterministic replay, tampering
and chronological-request mismatches. Fixture trades remain synthetic evidence.

## 3. Run one public-data paper session

```sh
.venv/bin/python scripts/run_crypto_paper.py --cycles 1
```

The runner prints the output path under
`algo-trading-bot/data/crypto-paper/<session>/`. Every run requires a fresh output
directory. A bounded public session without an account observer also writes
`replay_tape.json`. Continuous paper mode remains available:

```sh
.venv/bin/python scripts/run_crypto_paper.py --cycles 0 --scan-interval-seconds 300
```

Continuous and account-observer runs do not create the bounded REST replay tape.
They still produce the session evidence below. Ctrl-C persists available ledger
facts; stale marks produce an unvalued halt/shutdown record rather than current
P&L. Sessions are not automatically resumed after interruption.

## 4. Inspect the session's results directory

```text
<session>/results/
    orders.jsonl
    fills.jsonl
    signals.jsonl
    rejected_signals.jsonl
    equity.csv
    positions.csv
    funding.csv
    fees.csv
    daily_metrics.csv
    health_events.jsonl
    candidate_traces.jsonl
    session_manifest.json
```

The original `report.json`, `events.jsonl`, `equity.jsonl` and `candles.jsonl` are
also retained. Empty order/fill/funding files mean there were no such events;
CSV headers are still present. A FLAT position snapshot explicitly records zero
positions. Repeated saving does not duplicate events or a snapshot at the same
logical timestamp. On halt, known fills/fees/funding/health facts are flushed
without creating an equity row from stale marks.

`session_manifest.json` records the session start, Git commit and branch, dirty
status, working source hash, configuration hash, parameter set, frozen strategy
hash/check, adapter hash and risk hash. Hashes distinguish dirty working sources
from committed code; a commit alone is not presented as the current adapter's
version. No invented VWAP-v4 or HL-v1.3 version labels are used.

Every candidate, including no-signal and unavailable-data candidates, has a
`candidate_id`. Filter `candidate_traces.jsonl` by this ID to reconstruct:

1. MARKET_DATA: source snapshot, candle reference, scanner metrics and reasons.
2. SIGNAL: frozen VWAP, EMA9/21, ATR and direction output; selection status.
3. RISK_DECISION: allowed/reasons, size, stop/target and estimated net R:R.
4. EXECUTION_DECISION: local intent and observed bid/ask/mark/oracle/funding.
5. ORDER: local normalized request and each lifecycle state.
6. FILL: observed BBO simulation price, quantity and charged local fee.
7. POSITION_AND_PNL: resulting quantity, average entry, realized P&L and cash.
8. EXIT_FILL and TRADE_PNL: reduction, remaining quantity and completed setup
   net P&L after local fees and funding.

Rejected candidates stop at the stage actually reached. There are no invented
orders, fills, exits or P&L for a candidate that was never traded. Later exits
keep the original position's candidate ID, including exits between scans.

## 5. Read timestamps and metrics correctly

Events contain `exchange_ts`, `received_ts` and `processed_ts` as UTC ISO values.
Books, completed candles, public trades, exchange-reported fills and funding
retain their available source clocks. Local decisions, local simulated fills,
estimated funding and timestamp-free API contexts have a null exchange clock.
Mark freshness uses its separate observation clock; it is not a reported oracle
publication time.

The timing helper exposes exchange-to-receive age, receive-to-process duration
and clock-skew detection where clocks are known. A historical candle's age is not
network latency. A signal event carries the candle batch's receive time and the
brain evaluation's processing time. Local fills expose simulated
submit-to-fill duration. Actual wire/order-ack/exchange-fill latency cannot be
measured while signed execution is disabled. Replay timestamps come from its
recorded logical clock, not the speed of the replay process.

`equity.csv` records mark-valued local risk equity and a separate
`oracle_equity_estimate`. Oracle estimates require the same fresh observed quote
context as portfolio valuation. Neither is a funded team-wallet balance.
`daily_metrics.csv` uses the last observed sample of each UTC day, marks the
current day PROVISIONAL, and does not interpolate missing days. Daily returns
are empty without an adjacent prior day. Sample volatility is empty until two
observed daily returns exist. Sparse/incomplete day samples and these estimates
are not official competition scores.

The official evaluation combines final net return valued at oracle prices,
daily equity-return volatility and jury assessment of the technical report.
The local export preserves evidence for that comparison; it cannot reproduce
cross-team normalization or a jury score. [Evaluation protocol](https://perpetual-alpha26.github.io/about)

## 6. Replay a captured session offline

Use the actual output path from step 3:

```sh
.venv/bin/python scripts/run_crypto_replay.py \
  --tape '<session>/replay_tape.json' \
  --output '<new-replay-session>'
```

The runner constructs no HTTP session or socket. It verifies the tape checksum,
uses the tape's explicit policies, revalidates `par` metadata through the same
client/parser, evaluates the same frozen brain and runs the same BBO accounting
kernel. It requires exact chronological request and clock consumption. A
changed request, missing operation, backwards clock, tampered tape or unused
operations fails closed. It never searches forward for a convenient price.
`replay_validation.json` records the source tape hash and consumption result.

This first replay runner supports a complete single-scan REST tape. Historical
bars alone cannot establish executable spreads/depth/mark/funding; supply a
complete recorded tape rather than interpolating quotes from OHLC. It is not a
multi-month optimizer, continuous-feed replay, automatic account recovery or
proof of exchange fill quality. A changed adapter/clock protocol can invalidate
an old tape; use its recorded source revision and session manifest for comparison.

A genuine public session recorded on **2026-10-02 at 12:10 UTC** scanned all ten
markets. Every market had stale completed candles. Result: **NO_TRADE**, ten
signal/rejection records, thirty candidate trace events, one equity snapshot,
zero orders/fills/fees/funding and hypothetical USDPR 20,000 unchanged.
Offline replay matched its diagnostics, decisions and portfolio exactly.
This is connectivity, audit and replay evidence; no profitable return is claimed.
See `crypto_audit_validation_2026-10-02.json` and the saved public report.

## 7. Prepare the wallet boundary without activating it

Blank and zero public addresses report ACCOUNT STATUS: NOT_CONFIGURED. The
zero address cannot construct an account-query client. The default successful
paper session reports wallet ready NO, market data ready YES, paper ready YES,
live ready NO and signed actions DISABLED. A nonzero public address is
CONFIGURED_UNVERIFIED; address format alone does not establish wallet readiness.

Read-only account interfaces now include `get_balance`, `get_positions`,
`get_open_orders`, `get_fills` and `get_funding_history`, alongside existing
`get_equity`/`get_funding`. Balance is reported USDPR collateral, not inferred
free margin. Actual account events remain a separate observer from paper cash.
A future optional observer requires an explicit public address and history start:

```sh
.venv/bin/python scripts/run_crypto_paper.py \
  --account-address '<verified-public-team-address>' \
  --account-history-start-ms '<explicit-epoch-ms>'
```

Do not put the team-wallet seed/private key in the repository or report. The
participant guide requires account setup after organizer funding and separates
team-wallet approval from API-wallet trading. [Account setup guide](https://perpetual-alpha26.github.io/docs/#set-up-the-account)

## 8. Follow the later practice integration sequence

These are future steps, not actions this migration ran. After organizer funding
and the user's explicit later authorization:

1. Manually verify the public team address and USDPR collateral.
2. Create/manage an API wallet outside source and shared logs; approve it through
   the team wallet. Configure unified mode and verify `extraAgents`, account mode
   and collateral through read-only queries.
3. Review and implement the signed testnet adapter in a separate change; a flag
   cannot activate the current skeleton.
4. Run a tiny controlled order, confirm the reported fill, submit a reduce-only
   exit, reread the position to verify flat, and verify reported fees/P&L.
5. Exercise LONG, SHORT, cancellation, reconnect and recovery, including partial
   fills/rejections. Resolve every unexpected position or duplicate.
6. Compare autonomous PAPER observations, then explicitly authorize competition
   execution once the account and adapter are manually verified.

The current official schedule lists practice beginning October 5 and scored
trading beginning October 19. [Competition schedule](https://perpetual-alpha26.github.io/)
Practice acceptance is correct venue/symbol/side/quantity, no phantom positions
or P&L, no duplicate orders, no stale-data entry, reliable recovery and bounded
leverage. Strategy optimization and AI/ML work remain separate later phases.
