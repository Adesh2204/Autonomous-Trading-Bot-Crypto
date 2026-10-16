# Team Anchorium feed hardening — audit and evidence

The earlier three-hour run stopped cleanly after 10,801.862 seconds. It created no exchange orders and no PAPER fills. Its source hash stayed unchanged during that run, and both the checkpoint and its backup passed SQLite and checksum checks. The original evidence remains in `docs/practice_followup_2026-10-07/paper_segments/20261007T091107Z-d7de31a6`.

The 370-observation ledger includes ten observations from the preceding five-minute segment. The actual three-hour segment has 360 market-cycle observations: 48 healthy data checks, seven spread passes, zero ATR passes, and zero qualified markets. The spread check was observed on 48 markets: seven passed and 41 failed. ATR was also independently evaluated on 48 markets; all failed. In the diagnostic sequential view, only seven survive the spread check and none survive ATR. Neither denominator should be presented as 370.

## What is proven

* `ParMarketDataEngine.run` performed synchronous metadata/history/book REST recovery before entering its receive/ping loop. Long requests and read retries prevented that same thread from draining the socket or sending application heartbeats. This is an avoidable client-side recovery defect. The baseline does not prove that it caused every disconnect.
* The stream candle buffer retained `history_bars` total rows, including a current unfinished candle. With a 300-bar setting it could leave only 299 completed bars. Keeping one additional unfinished row restores the original requirement; it does not reduce the strategy's history requirement.
* An empty result from `websocket-client.recv()` became the generic `STREAM_DISCONNECTED`. The original code discarded close-frame codes and reasons. Consequently the precise initiator of the 15 generic baseline disconnects is unknown. Their median subscribed lifetime is approximately 632.568 seconds, but timing alone cannot identify the server, proxy, network, or host as the cause.
* Six baseline `INFO_RETRY_BUDGET_EXHAUSTED` events mean transient reads exhausted the three-attempt retry policy. They are distinct from local `RATE_LIMITED` errors. The original recovery loop treated those REST failures as socket failures and opened another socket, multiplying recovery work. The old evidence does not identify the HTTP status or underlying network exception of each failure.
* Two baseline `STREAM_HEARTBEAT_STALE` events cannot be definitively attributed to dead transport, host suspension, delayed receiver processing, or a missing application pong: those timings were not recorded. The new evidence records these facts instead of assigning an unsupported cause.

## Official protocol and installed SDK

The installed official Hyperliquid SDK is 0.24.0. Its `WebsocketManager.send_ping` uses a separate thread and sends the JSON application ping every 50 seconds. Our 30-second application ping already used the same official protocol; no invented protocol or increased timeout was required.

Hyperliquid documents a server close after 60 seconds without a message sent to a client, with JSON `method: ping` and `channel: pong` available to maintain liveness. A quiet individual market is therefore not a global transport heartbeat. [Official timeout/heartbeat documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats).

REST has a shared IP weight limit of 1,200 per minute; candle response rows add weight. The documented WebSocket caps include 10 connections, 30 new connections per minute, 1,000 subscriptions and 2,000 outgoing messages per minute. The project retains its more conservative reconnect policy and safety reserves. Account action allowance is a separate budget; it is not spent by public `/info` reads. [Official limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

## Scoped code changes

| File | Function/class | Previous behavior | New behavior | Reason |
|---|---|---|---|---|
| `exchange/feed_transport.py` | `FeedTransportHealth` | No per-connection close/ping/subscription ledger | Connection generation, message clocks, pong deadlines, subscription acknowledgements, receiver-gap classification and bounded jittered backoff | Diagnose transport separately from quiet markets |
| `exchange/hyperliquid_market_data.py` | `ParMarketDataEngine.run/_run_owned` | REST repair blocked socket receiving; REST failure also reconnected socket | Single run owner; one repair worker; receiver continues; REST retry deferred on the current socket; cancellation and bounded joins | Keep liveness responsive and stop repair/socket storms |
| same | `_receive/ingest` | Close reasons discarded; no callback generation check | Preserve received close code/reason; reject old-generation callbacks/results | Attribute failures and prevent stale socket writes |
| same | `reconcile_history` | All history redownloaded; REST snapshots overwrote stream facts | Bounded actual-bar overlap repair, per-market errors and retry scope; merge newer stream facts; readiness waits for acknowledgements | Reduce recovery work and retain independent market health |
| same | `_ingest_validated` | Open candle consumed completed-history capacity | 300 completed slots plus one open slot | Preserve the frozen completed-bar input convention |
| `exchange/rate_limits.py` | `read/_read_owned/reserve_info` | Identical concurrent reads duplicated; candle response weight charged after receipt | Single-flight identical reads, cancellation, upstream/error/latency diagnostics, response-size reservation before sending | Protect safety reserve and measure demand |
| `exchange/hyperliquid_client.py` | `post_info` | No read identity/expected response bound passed to manager | Canonical public request key and bounded candle estimate; cancellation carried to manager | Connect public read coalescing and reserve checks |
| `market_stream.py` | `health/poll` | Health reasons only; transport and repair detail limited | Per-market health state, completed-history check and repair reasons; explicit feed-ready versus trade-ready reporting | One stale symbol cannot make another healthy symbol eligible or globally kill transport |
| `opportunity_funnel.py` | `_summary` | Existing independent/reached counters could be misread as sequential | Explicit evaluated/pass/fail/percent and sequential-admission counters; first-rejection categories | Honest denominators and rejection separation |
| `exchange/feed_certification.py` | `FeedCertificationReport` | No formal feed certificate | Evidence gates with three successive valid scheduled windows, a currently valid market, subscriptions/recovery/budget/checkpoint/source checks | A signal or trade is not required; missing evidence fails closed |
| `scripts/run_feed_soak.py` | `main` | Bounded practice launcher without source-bound soak receipt | Fresh state/output, local owner, source-bound full regression, heartbeat tape and terminal certificate | Reproducible independent evidence |
| `scripts/feed_certification_report.py` | `generate` | Cumulative results required manual subtraction | Filter actual segment time, verify checkpoint/backup, emit independent and sequential funnels | Preserve baseline and avoid counting prior segments |

## What happens if a failure recurs

A socket failure revokes connected/reconciled state and causes the existing account/stream barrier to pause entries. One owner closes the old socket and stops its repair worker before reconnecting. The new socket installs the canonical subscriptions once, confirms them, repairs actual history within a bounded interval and then crosses the existing account reconciliation barrier. A late callback or recovery publication from the old generation is rejected.

A REST failure keeps a functional socket receiving and pinging, records a separate deferred recovery event, and waits with bounded backoff. No duplicate repair worker can run. Data with missing, stale, malformed or unverified history stays blocked for its market. Safety-priority reads retain their reserve. Actual exchange actions remain prohibited throughout this work.

A large receiver gap is reported as host/client processing or wall-clock discontinuity evidence. It is not described as a proven venue fault or as proven machine sleep. The system uses threads rather than an asyncio event loop; the relevant responsiveness measure is receiver-loop gap and public read duration. Main-thread accounting/checkpoint work and scanner indicator work do not perform socket receiving.

No synthetic candle, native-market fallback, live historical CSV, threshold change, strategy rewrite or automatic execution activation is introduced. The LONG/SHORT/stop/target strategy and state machine remain under the original freeze verification.

## Certification limitations

Tests prove behavior using controlled fixtures; they do not certify the funded wallet. A short soak and new three-hour run must measure the current source. A feed can be stable while spreads exceed 15 bps or ATR stays below 0.40%. In that case those market rules remain unchanged. Any later scanner research must be offline, chronological and evaluated after fees/funding, with holdout evidence rather than trade-count optimization.

The PAPER ledger's hypothetical 20,000 USDPR remains distinct from the team's reported 1,000,000 USDPR wallet. No actual fill, fee, funded P&L or emergency-protection acceptance has yet been certified. Account/signer/leverage/nonce/clock/rate observations need fresh verification before any separately authorized funded certification. Protection remains configured but disabled. Feed certification never makes `PRACTICE_READY` or `LIVE_READY` true.

## Short-soak protocol failure and correction

The first post-change short soak failed within approximately 18 seconds, safely with zero orders. The newly strict book-subscription identity comparison did not account for the venue expanding omitted defaults in its acknowledgement: `nSigFigs: null`, `mantissa: null`, and `fast: false`. Actual raw acknowledgements for all four public channels were captured in `raw_all_channel_acks.json`; this is observed protocol evidence, not an inferred schema. Canonical identity now removes only those known book defaults. Nondefault precision/fast settings and different markets remain distinct and are rejected when unexpected.

That failure also exposed a cancellation event left set before the next metadata startup. It generated `INFO_READ_CANCELLED` before a new socket was opened. The event is now cleared at the beginning of the next owned connection attempt, after the previous worker has joined. An explicit rate-managed reconnect test protects this path. The failed soak and the preceding successful 1,299-test source receipt are retained; subsequent tests and soaks bind to the corrected source.

The short-soak engineering gate requires recovered transport, confirmed subscriptions, no reconnect storm, drained REST work, healthy PAPER reconciliation, no accounting halt, clean/checksummed checkpoints, unchanged source and passing full regression. Sparse/stale venue windows remain visible as failed feed criteria; they do not require a forced trade or threshold change. If those are the only missing criteria, the three-hour observation may proceed to collect longer evidence. Any unresolved engineering gate prevents the long run. Full feed certification still requires three successive valid scanner data windows and a currently valid market.
