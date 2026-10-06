# Team Anchorium: participant-guide alignment and practice readiness

Assessment date: 5 October 2026. This report compares the supplied participant guide, the current official competition pages, the current repository, and saved verification evidence. It is an assessment, not authorization to deploy, configure a wallet, or submit exchange actions.

## 1. The answer in plain language

Much of the bot's exchange infrastructure matches the competition. The frozen VWAP strategy is still present, and the project has substantial local safety and accounting tests.

**Even setting wallet funding aside, the bot is not yet ready to start unattended funded practice immediately.** This review found a scanner/runtime mode conflict. The emergency protection configuration also still needs a documented approval, a usable practice launcher and server operations need preparation, and today's public-data check rejected every market for stale completed candles.

These are primarily infrastructure and operating-readiness issues. They do not justify rewriting VWAP, EMA, ATR, LONG/SHORT decisions, stops, targets, cooldowns, or direction flips.

| Question | Current answer |
|---|---|
| Does the design broadly match the participant guide? | Yes, with the limitations explained below. |
| Can public market data and paper runs operate without a funded wallet? | Yes. Public reads need no private key. |
| Is fresh, usable data demonstrated across the markets today? | No. The bounded public scan rejected all ten completed-candle histories as stale. |
| Is wallet funding the only remaining step? | No. There is also a concrete mode conflict and operating preparation. |
| Is the bot ready to start funded automated practice as soon as funds arrive? | Not yet. |
| Does the guide require AWS? | No provider-specific hosting requirement was found. |
| Is an always-on server a sensible choice for the multiweek run? | Yes, after the operational gaps are resolved. |
| Have the ML or alternative-session experiments been validated? | No. They remain isolated research. |

## 2. What I checked, and what the checks mean

The latest recorded full repository suite, dated 4 October, contains **1,155 passing tests, zero failures, zero errors, and zero skipped tests**. The source hash checked for this review matches that receipt. I did not rerun the whole suite today.

The strategy-freeze and Phase 0 checks were rerun for this review and passed. The protected signal file, eight frozen methods, and 32 parameters remain consistent with the baseline. The original NSE repository was not modified during this review.

Passing local tests proves only the behaviors those tests exercise. It does not prove funded-account readiness, successful exchange execution, multiweek reliability, profitable crypto trading, or competition ranking. In particular, the scanner/live-mode composition issue below was not covered adequately by the previous suite.

No Python source was changed for this review. No team-wallet secret was loaded, no account was administered, no server was deployed, and no exchange action was submitted. The new evidence is a bounded public PAPER probe and this report.

Evidence files:

- [Recorded full-suite validation](</Users/adesh/Autonomous Trading Bot - Crypto /docs/hackathon_certification_validation_2026-10-04.json>)
- [Recorded test receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/hackathon_certification_test_receipt_2026-10-04.json>)
- [Today's public PAPER report](</Users/adesh/Autonomous Trading Bot - Crypto /docs/participant_guide_public_paper_2026-10-05/report.json>)
- [Research readiness](</Users/adesh/Autonomous Trading Bot - Crypto /docs/research_readiness_final_2026-10-04/readiness.md>)

## 3. How the bot compares with the participant guide

The supplied guide is reference material. Its account-setup examples do not grant permission to perform those actions in this review.

| Guide area | Current implementation and practical meaning |
|---|---|
| Hyperliquid testnet, HIP-3 DEX `par` | The new core selects testnet and `par`, checks venue metadata, and uses prefixed market names. It does not silently substitute native Hyperliquid markets. |
| Ten listed markets | The scanner covers the ten `par:` markets. This includes crypto, equity references, commodities and FX; it is a broader venue than BTC and ETH alone. |
| Runtime market specifications | Size precision, maximum leverage and asset mappings are obtained from venue metadata. The bot does not reuse NSE instrument tokens or lot sizes. |
| Correct prices and quantities | Decimal normalization and central order validation address quantity steps, price precision, minimum order value, price distance and venue limits. Actual rejection handling remains necessary because exchange state can change after a check. |
| Official Python SDK | The project pins `hyperliquid-python-sdk==0.24.0`, matching the supplied guide. A clean Linux installation still needs verification on the chosen host. |
| USDPR collateral and unified margin | The new account/risk layer uses perpetual-futures accounting rather than Indian brokerage and stock-position accounting. The actual team's unified mode and available margin remain future account checks. |
| Mark, oracle and execution prices | These are separate concepts in the new infrastructure. The price for buying or selling comes from the order book; mark and oracle are not interchangeable execution quotes. |
| Fees | PAPER uses explicit fee assumptions. The future account runtime derives rates with the venue's fee scaling, while actual account accounting uses reported fill fees. The account's real fee tier still needs verification. |
| Hourly funding | Funding cashflows and risk are represented. Actual account history remains separate from estimated PAPER funding. |
| Orders and partial fills | The future execution layer has order validation, individual result parsing, order IDs, partial-fill handling, reduce-only exits and reconciliation. A successful request wrapper is not treated as proof that every order filled. |
| REST and WebSocket recovery | Public and account stream implementations include heartbeats, reconnect/re-subscribe behavior and account reconciliation barriers. A connection alone does not prove fresh candles or healthy account state. |
| Rate limits, nonces and clocks | There are central budgets/reserves, adaptive read backoff, persistent nonces and clock-health checks. The future successful-loop cadence still needs explicit scheduling and sustained verification. |
| Restart recovery and reporting | Durable journals, account recovery and evidence exports exist. A deployed service, retention plan, backups and alerts are not yet demonstrated. |
| Autonomous entries | The preserved strategy generates decisions algorithmically. The practice/scored runtime must run that real decision path; manual entries cannot replace it. |
| Fairness and anti-gaming | The current design includes one global position, provenance, duplicate/self-cross and price/liquidity guards. These help compliance; they cannot certify every future action or replace committee review. |

The guide does not require trading every market, selecting the maximum advertised leverage, reproducing the venue's oracle calculation, or implementing every supported order type. Existing conservative position and leverage limits are not a reason to rewrite the strategy.

Read the exchange's published `oraclePx` and `markPx`; do not build a replacement SEDA oracle or confuse the venue's mark-price EMA with the strategy's EMA. Despite its name, `par:USDEUR` represents EUR/USD. All listed contracts settle in USDPR.

The guide's scheduled cancellation feature has a $1,000,000 account-volume prerequisite. It is not a basic activation requirement and it is not a substitute for an exchange-side protective stop. Do not generate artificial trading to unlock it.

## 4. Changes and preparation still needed before funded practice

### A. Fix the shared scanner's mode conflict first

The problem is concrete:

1. `MarketRegimeScanner.scan()` calls `require_paper_migration()`.
2. That guard accepts PAPER mode with live orders disabled.
3. The future signed runtime uses this same scanner.
4. That signed runtime correctly requires a separately authorized live-testnet mode.
5. Consequently, the runtime and scanner cannot both accept the intended future configuration.

An offline probe reproduced `MIGRATION_PAPER_MODE_REQUIRED` with no client, key or network created. The important sources are:

- `algo-trading-bot/market_regime_scanner.py`, line 68.
- `algo-trading-bot/venue_config.py`, `require_paper_migration()`.
- `algo-trading-bot/exchange/execution_safety.py`, `LiveAuthorization.require()`.
- `algo-trading-bot/exchange/live_runtime.py`, where the shared scanner is composed into the future runtime.

The needed fix is to make scanner authorization appropriate to its runtime context while keeping the PAPER runner locked, keeping every exchange-write gate, and preserving the frozen strategy. Simply deleting safety checks or changing the defaults is not an acceptable fix.

Add an integration test that follows the real runtime/scanner composition with fake exchange transport under the intended future mode. Component tests alone missed this conflict.

### B. Approve the independent emergency-stop policy

`configs/reliability_policy.json` currently has protection disabled, no approval reference, and no configured ATR distance or execution-slippage fraction. The future runtime requires an approved protection policy before it reads an API signer key.

In simple terms, a strategy stop depends on the bot running and observing the market. A separate protective order accepted by the exchange can remain there when the bot loses its connection. Its distance and execution allowance must be deliberately chosen and documented.

This approval requirement belongs to our project safety policy. The participant guide supports reduce-only trigger stops but does not explicitly mandate our particular catastrophic-protection configuration. Preserve the strategy's normal stop/target behavior; do not silently change it while configuring the separate protection layer.

### C. Prepare a usable practice launcher and a bounded operating schedule

The repository has a continuous PAPER command and a future live-runtime builder. I did not find a turnkey live practice launcher, an installed system service, or deployment files.

The future launcher needs to compose verified identity, explicit authorization, approved policies, persistent state, output paths and the runtime's run loop. It must resume the correct state after a restart instead of creating a new empty account history.

The successful future runtime loop has no explicit scan interval; it cycles and exports results repeatedly. Account WebSocket polling and the rate limiter provide some bounds, but that is not a demonstrated long-running schedule. Separate appropriately scheduled strategy scans from more frequent position/account/protection observations, and measure API weight and resource use. This is operating infrastructure, not permission to retune the strategy.

### D. Investigate current completed-candle freshness

Today's public PAPER scan, observed at **10:13 UTC / 15:43 IST on 5 October**, inspected ten markets and returned:

- `NO_TRADE`.
- Ten `COMPLETED_CANDLE_STALE` rejections.
- Zero local orders and zero local fills.
- Zero exchange submissions.

The bot correctly refused to act on old data. This single scan does not establish whether the cause is sparse venue trading, delayed venue data, or a delivery/adapter problem. Establish that distinction using REST and WebSocket observations of the same prefixed markets, candle completion times, book prices, and mark/oracle updates.

Public data does not depend on your wallet balance. Funding will not repair this by itself. Keep the stale-data checks and `par` selection; do not substitute native BTC data or fabricate missing candles to create activity.

### E. Demonstrate continuous operation and recovery

After usable data is available, I recommend a **24–48 hour continuous PAPER run** on the intended host. This duration is an engineering recommendation, not a published competition requirement.

Record fresh data, genuine signals and rejection reasons, funding boundaries, request budgets, CPU/RAM/disk use and result exports. Verify connection recovery and process restart with offline fault tests or PAPER operation. Account/protection scenarios can be tested with fake exchange state before funding; the real account confirmation must follow later.

The intended result is evidence that the deployed process remains healthy and recovers safely. It is not a requirement to force a trade or claim profitability from a short observation period.

## 5. ML, VWAP-session research and scoring

The research readiness record still shows the six flags as FALSE: session-anchor validation, ML data readiness, ML model validation, holdout completion, promotion recommendation and production change.

The research framework exists, but its saved readiness report shows zero genuine labeled candidates in the declared model domains. Its current 500-candidate/20-date admission targets are our research criteria, not competition trading requirements. With only two new reference setups per day, those targets cannot be met from completed unique trades within a few weeks. Repeated replays cannot be counted as new evidence.

There is no need to activate an unvalidated model to connect to `par`. Keep the deterministic strategy as the production baseline. Do not call an untrained or unvalidated system a proven ML trading advantage.

The official evaluation includes net return marked to oracle at the end, lower volatility of daily returns, and a jury assessment of a 2–4 page report including AI/ML depth, originality, rigor, reproducibility and clarity. The AI/ML evidence gap may matter competitively even though it does not block API connectivity.

The official About page also requires at least **10 distinct trading days** and a minimum cumulative notional volume for ranking. The numerical minimum volume is not specified on that page. Verify it with the organizers before the scored phase. The current strategy's opportunity rate may or may not satisfy eligibility; neither two setups per day nor a working connection guarantees it. Monitor genuine algorithmic activity without wash trading, coordinated activity or forced volume.

Local PAPER results use hypothetical collateral and are not on-chain competition returns. Store real fills, fees, funding, equity snapshots, opportunity traces, deployment/source identifiers and outages once practice is authorized. Distinguish mark-based account risk from the organizers' oracle-based final evaluation; local estimates are not official scores.

## 6. Do we need AWS or a server?

The official pages require an autonomous deployed algorithm but name no mandatory hosting provider. A reliably running computer can host it.

Your laptop can support early supervised PAPER checks. For a multiweek run, sleep, reboots, power loss and home-network interruptions make a single always-on cloud computer a practical choice. A VPS is simply a computer rented in a data center that keeps running when your laptop is closed. AWS Lightsail is one possible provider.

### Recommended starting specification

These are engineering starting estimates, not organizer minimums and not certified measurements of this bot's multiweek resource use.

| Item | Recommendation | Meaning |
|---|---|---|
| Server | One Linux VPS/VM | One active bot owner; keep operations simple. |
| Operating system | Ubuntu 24.04 LTS, x86_64 | A stable Linux environment; verify a clean dependency install. |
| Python | 3.12, matching the tested environment | The guide allows 3.10 or later; consistency simplifies verification. |
| CPU | 2 virtual CPUs | Starting allocation for streaming, scanning, reconciliation and exports. |
| RAM | 4 GB | Starting headroom; measure and increase if needed. |
| Storage | About 80 GB SSD | State, journal, results and logs, with retention limits. |
| Internet | Reliable outbound HTTPS and WebSocket access | The bot connects outward to Hyperliquid; it needs DNS and TLS access on port 443. |
| Clock | NTP synchronization enabled | Signed action timestamps depend on an accurate clock. |
| Region | Compare Mumbai and Singapore reliability/latency | Choose from measurements; do not assume the exchange's server location. |
| Process management | A service such as systemd | Start at boot and restart failures with backoff, while preserving authorization and recovery gates. |

AWS currently lists a Linux Lightsail public-IPv4 bundle with **2 vCPUs, 4 GB RAM and 80 GB SSD at $24 USD/month**. Taxes, snapshots and any overages may add cost; confirm the actual regional checkout. Its published transfer allowance is reduced in some regions, including Mumbai. Server billing uses real money; USDPR competition collateral is separate testnet value.

For this baseline bot, no GPU, full blockchain node or large managed database is indicated. Keep model training and heavy backtests off the active trading host unless measurements show they can coexist safely.

### What a reliable installation needs

1. Install the repository's pinned dependencies in a fresh virtual environment. Do not copy the macOS virtual environment to Linux. Run freeze, safety, integration and applicable exchange checks on that host.
2. Use a dedicated non-root bot user. Limit SSH access to the team's permitted IP addresses. An outbound trading client does not need a publicly exposed website or database.
3. Keep the team-wallet private key outside the bot/server. A future authorized server uses only the separately approved API wallet, handled as a restricted credential. Do not put keys in source, shared files or logs.
4. Store journals, nonce state and recovery/evidence files in persistent storage. A proposed Linux location is `/var/lib/anchorium`; this location has not been installed in the current project.
5. Run exactly one active signing bot for the team account. Do not run the laptop and server as concurrent traders. A same-machine lock is not a distributed lock across two computers.
6. Configure restart backoff and health notifications. Restarting the process must still require valid authorization and authoritative account reconciliation; it must not clear unknown positions or expired approvals.
7. Alert on process death, stale data, account reconciliation failures, protection failures, margin problems, clock/rate/nonce faults, export failures, and low disk space. Notifications should report problems rather than submit trades themselves.
8. Rotate logs, cap retained exports and monitor disk/RAM growth. Keep consistent backups of SQLite state with a proper online backup or coordinated checkpoint/snapshot; copying only an open database file may omit WAL transactions.
9. Confirm recovery from an outage on the intended host in PAPER/offline tests before future activation. A server reduces laptop interruption risk but does not guarantee exchange or internet uptime.

## 7. A practical sequence from today to practice

### Before wallet funding

1. Fix the scanner/runtime mode handoff and test the real composition offline. Preserve PAPER/false defaults and all write gates.
2. Prepare the launcher, scan schedule, deployment configuration and persistent-state layout.
3. Investigate public-data freshness without changing strategy thresholds.
4. Define and document the independent protection policy for explicit review.
5. Set up the chosen host in PAPER mode, measure its resources, and test monitoring, backups and restart recovery.
6. Collect a continuous public PAPER run when the feed is healthy. Keep results clearly labeled hypothetical.
7. Confirm the organizers' numerical minimum-volume requirement and how distinct trading days are counted.

### After wallet funding

1. Verify the public team-wallet address, USDPR collateral, unified mode, approved API wallet and expiry, actual fees, leverage and available margin.
2. Complete the project's explicit manual account/activation verification and approved protection configuration. Funding observation alone is not authorization.
3. Perform authorized, bounded testnet certification of real order results, fills, cancellations/exits, account reconciliation, protection and restart behavior. Keep engineering test activity distinct from strategy results and follow the competition rules.
4. Start genuine algorithmic practice with one active process. Monitor healthy data, real account state, costs and all risk gates.
5. Use practice observations to correct evidenced infrastructure faults, preserve the baseline, and build reproducible evidence for the submission.

The published schedule is **practice: 5–18 October; scored trading: 19 October–6 November; report/code submission: 9 November**. This review is on the first scheduled practice date. It does not prove every market's live data is already healthy at the time of the probe.

## 8. Current operating decision

Keep:

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

The next engineering priority is the scanner/runtime composition fix, followed by public-data investigation and a reliable PAPER deployment. Wallet funding and manual verification remain separate future requirements. There is no justified claim of complete funded-practice readiness or a guaranteed competition result today.

## Sources

- [Official participant guide](https://perpetual-alpha26.github.io/docs/), compared with the user-provided copy.
- [Official task, evaluation and eligibility](https://perpetual-alpha26.github.io/about).
- [Official competition schedule](https://perpetual-alpha26.github.io/schedule).
- [AWS Lightsail pricing](https://aws.amazon.com/lightsail/pricing/), checked for the suggested server bundle.

The deployment specifications and 24–48 hour PAPER observation recommendation are engineering judgments, not published competition rules.
