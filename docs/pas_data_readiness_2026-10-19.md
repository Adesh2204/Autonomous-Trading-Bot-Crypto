# PAS BTC/EWY: data fixes implemented, live trading blocked

**Decision: NO-GO for live trading on the evidence available in this batch.** Funding is expected on 19 October at 17:30 Asia/Kolkata (12:00 UTC), not verified as received. Passing offline tests, seeing a book, or observing the expected funding time does not authorize activation. PR #2 stays draft; no merge or deployment is part of this work.

## What changed—and what did not

The existing branch `fix/pas-btc-ewy-review-2` was continued from `a73f4181b982b427099480f968718aefe1dc052c`. The damaged primary checkout and main were not used for implementation.

The core strategy, UTC VWAP anchor, ranking formula, indicator periods, ATR/spread/liquidity filters, risk ceilings, exactly one global position, 1x leverage, account checks, human approvals and protection requirements are unchanged. The production profile still selects at most one candidate from exactly BTC and EWY. An offline regression uses the unchanged frozen brain and scanner to show its candidate switching from BTC to EWY when observed spread, depth and notional liquidity change. This does not force a rotation of an existing position or bypass its normal exit/reconciliation rules.

Historical PAR practice trades and fills remain history. There is no future live PAR, USDPR, native-market or mainnet fallback.

## Batch 1: what the actual venue returned

Unsigned Testnet reads resolved the canonical API DEX to `pas`, both active coins to `pas:BTC` and `pas:EWY`, and collateral token 3307 to **USDP / Perpetual Alpha USD**. Runtime limits reported $10m for each active market and $50m for the DEX. These observations do not certify wallet ownership or authorize orders.

| Check | BTC | EWY |
|---|---:|---:|
| First 300-minute completed-window request, 06:03 UTC | 0 bars | 53 bars |
| Later guarded 300-minute request, 06:08–06:09 UTC | 0 bars | 47 bars |
| Latest close in those EWY responses | — | 01:56 UTC on 19 October |
| Age at end of guarded check | unavailable | 15,230,444 ms |
| Completed-history/freshness gate | BLOCKED | BLOCKED |

The reduction from 53 to 47 is a moving request-window effect, not a claim that bars were deleted. The later EWY request was 01:09–06:08:59.999 UTC and returned only the old 01:09–01:55 starts. BTC had no rows in the requested five-hour window.

An earlier expanded, **pre-cap implementation** 5,000-minute probe returned 281 BTC bars, newest close 20:17 UTC on 18 October, and 3,688 EWY bars, newest close 01:56 UTC on 19 October. Extra old bars cannot satisfy freshness. The final code does not issue a single 5,000-slot request under the user's 300-slot budget.

An 85-second public WebSocket probe received six subscription acknowledgements, 34 book messages, two trade messages and **zero candle events**. A subsequent bounded 65-second engine diagnostic stopped cleanly with 147 data messages, no reconnects and zero completed current-window candles for either asset. A live book is not proof of usable candle history, and silence is not permission to synthesize candles.

## Batch 2: safe data access and genuine warmup

`exchange/rate_limits.py` and the public client enforce an internal **300 requested REST candle slots per rolling 60 seconds**, shared across BTC/EWY and all PAS clients in one process, including custom transports. This is a conservative interpretation of the user's cap, not an official venue rule and not 300 HTTP requests. Empty responses and failed attempts are not refunded; retries consume capacity and coalesced reads charge their single upstream attempt. Oversized or invalid reservations fail before HTTP. Account/safety reads retain their independent weighted budget and reserve.

The [official exchange rate documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) separately specifies 1,200 weighted REST units/minute and candle response weight per 60 items. The [official candle documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) describes prefixed HIP-3 coin identifiers and a latest-5,000-candle availability limit. Neither promises that these PAS markets currently have sufficient history.

PAS stream storage now retains up to 5,000 real completed intervals plus one mutable observation. A bar first received while open does not become finalized merely because the local clock advances: it needs a genuine source observation received at or after its close. Unknown receive times remain excluded.

The stream-first adapter merges real retained bars with bounded REST gap repairs. Each successful chunk is committed to the in-memory cache before another chunk can be rate-limited, so later scans resume missing history instead of repeatedly losing the first chunk. A conflict between finalized observations is quarantined; a cache fast path cannot silently clear it. A disconnected cache is not a connected readiness source.

The requested **full UTC scanner range** must be present. Merely having 300 fresh trailing bars cannot hide a missing requested UTC-anchor prefix. This is important: the existing scanner's range can exceed 300 bars, so five hours of streaming alone is not a guarantee of scanner readiness. Missing, gapped, stale, future or unfinalized bars remain blocked. No interpolation, carry-forward, synthetic no-trade minutes or alternative-venue candles were introduced.

The budget is process-local, not an IP-wide distributed limiter. Do not run competing data collectors or another account owner alongside an approved runtime. Recovery/scan scheduling and startup/reconnect behavior under the real venue's sparse data still require a controlled soak; these unit tests are not that certification.

## Batch 3: diagnostics and integration

New unsigned diagnostic:

```sh
EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false ANCHORIUM_PUBLIC_ONLY=true \
python3 scripts/check_pas_candles.py \
  --output /tmp/pas-candles.json --audit /tmp/pas-public-candles.jsonl
```

An optional `--stream-seconds 300` performs a finite public-only observation. It does not load a signer, query account credentials, own the trading account, sign, submit or deploy anything. The two initial 300-slot requests are staggered by the shared minute budget. The process exits nonzero when its initial data gate is blocked; this is an intentional no-go result, not an order failure.

Streaming warmup is in memory. Stopping this collector does not transfer trusted state or an activation permit to a future live process; raw audit files are not automatically accepted as restart-ready state. Do not mistake a data-only pass for a full UTC scanner, liquidity, account or live-certification pass.

The existing launcher preflight now requests exactly its configured number of completed bars (default remains 300), rather than accidentally requesting more than the new per-request capacity. It can wait once for a finite budget deadline, recalculates the completed window afterward, then reads executable quotes. Larger policies are not silently reduced. All live approvals and certification gates remain intact.

## Validation and remaining work

The existing PR safety workflow now includes non-signing candle-budget, stream-warmup, diagnostic and liquidity-selection tests. All focused results and the final broad-suite comparison are recorded in the PR update for this commit. Strategy-freeze verification passes: one frozen file, eight methods, 32 parameters. The repository-wide historical suite is not green; it must not be represented as fully certified.

The final focused workflow passes **182 tests** with network and signing blocked, including subprocess-wide guards. Static imports, Python syntax checks and `git diff --check` pass. A negative control substitutes the original `a73f418` stream adapter in memory: the new capped-repair regression correctly fails because the original implementation retains zero bars instead of the first 300. The current implementation passes that regression without source substitution.

The broad guarded run finishes with **1,302 passed, 91 failed, 233 errors**. A separate clean archive of the starting HEAD finishes with **1,250 passed, 98 failed, 233 errors**. Every final failed/error node ID is present in the clean baseline: zero new failing IDs and zero new error IDs; seven baseline failed IDs do not fail in this run. These differences are not a claim to have fixed those historical tests. The existing errors are largely legacy fixtures lacking mandatory PAS discovery, and legacy candle/feed/resilience assertions remain unresolved. Thirty-four signed-fixture, manual, long-running or dependency-incompatible modules were deliberately excluded from the broad non-signing selection. A read-only independent review found no confirmed defect in the final incremental-repair rewrite; it did not certify operational readiness.

The supplied public address reported unified account mode, no PAS positions/open orders, and only legacy USDPR collateral at the time queried—not spendable USDP. Two actual historical PAR BTC fills were visible for that address and were not altered. The registered team-wallet identity, relationship to earlier differing address evidence, signer ownership and current approval scope remain uncertified. A listed unexpired API agent is not proof that the intended signer has been verified.

Before any later activation, all of the following are still required:

1. Real, consecutive, completed and fresh PAS candles for **both** BTC and EWY, including the unchanged scanner's requested UTC input range; executable liquidity and live metadata must also pass.
2. Resolve and explicitly verify the registered team wallet and signer, then observe funding and genuinely spendable **USDP** after the funding event. USDPR and paper balances cannot substitute.
3. Reconcile authoritative account positions, orders, fills, fees/funding and durable recovery state on the exact approved commit.
4. Separately authorize and complete controlled two-market execution, partial-fill, exit, reduce-only protection, restart/WebSocket recovery and supervisor certification. Disabled protection was not enabled here.
5. Obtain current human activation approval bound to PAS Testnet, both assets and the exact running commit. No wallet/funding/activation verification claim is made by this work.

Section 14 of the supplied directive ends mid-sentence. No missing leaderboard/scoring instructions were inferred. Until the above gates pass, the safe result remains **NO-GO**, including at 17:30 if funding arrives but any other gate is unresolved.
