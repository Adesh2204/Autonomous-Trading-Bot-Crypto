# Anchorium PAPER practice: operating instructions

The launcher and deployment templates in this change run public-data PAPER trading. They contain no approved live configuration or wallet credential. The original strategy and PAPER/false defaults remain protected.

## What is available

- [PAPER launcher](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/run_practice.py>) reads [the operating schedule](</Users/adesh/Autonomous Trading Bot - Crypto /configs/practice_ops.json>).
- [Future testnet launcher](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/run_testnet_practice.py>) requires separate future human authorization, approved protection and real account readiness. It refuses the current PAPER settings. It has not submitted exchange actions.
- [Freshness diagnostic](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/diagnose_par_freshness.py>) compares raw REST history, trades and public WebSocket observations without using a wallet.
- [Health checker](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/check_practice_health.py>) distinguishes healthy operation, degraded data, stopped process and a missing/stale heartbeat.
- Linux service, health timer and alert-log rotation templates are in [deploy](</Users/adesh/Autonomous Trading Bot - Crypto /deploy/anchorium-paper.service>).

## Operating schedule

The practice launcher defaults to strategy scanning every 300 seconds, an owner/management tick every second, and health/export checks every 30 seconds. Actual latency also depends on network calls. The future runtime has the same explicit scan/management/export schedule. Safety and account checks continue between strategy scans; no signal periods, volatility filters or stop calculations are changed.

The standalone older PAPER command retains its 0.25-second owner tick for compatibility. The launcher explicitly selects one second. PAPER exports during active positions are throttled independently from management. Repeated identical halt evidence is throttled so a stale feed does not create four full halt reports every second.

The persistent launcher shares public REST/WebSocket request budgets across its clients. Boot metadata reads happen before that shared continuous-run budget is installed; the limiter is an operating safeguard, not an assertion about every other application sharing your IP.

## Run on the current Mac

From the repository, a bounded run uses:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 600 --state-directory runtime/paper/markpx-validation
```

To run continuously until Ctrl-C, omit the duration. This is a foreground process. Keep the Mac awake and connected. This guide does not claim a background service or scheduled follow-up has been installed on the Mac. After the organizer's mark-price clarification, the command explicitly selects a new PAPER validation ledger, `runtime/paper/markpx-validation`. No run on this new ledger is claimed yet. Earlier public observations in `runtime/paper/release-validation` and the development ledger in `runtime/paper` remain preserved; their tested source predates the order-band correction. The strict source guard prevents silently resuming either old ledger under changed code. Treat the new ledger as a separately labeled experiment, not continuation of the old performance history.

Optional `--state-directory` and `--output-root` select durable state and evidence locations. Use the same state directory, session ID, policy and source version when restarting the same paper ledger. Each start creates a new evidence segment.

Inspect the local heartbeat with:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/markpx-validation
```

Exit codes: 0 means healthy PAPER operation; 2 means degraded feed/operations; 3 means the process is stopped/failed; 1 means a stale, missing or invalid heartbeat. A warning is not a trading instruction.

`health.json` and `alerts.jsonl` are local monitoring outputs. No email, Slack or Discord notification transport has been configured. Linux health checks appear in the service journal; connect your chosen notification transport separately if you want phone alerts.

## Persistent state and restart behavior

The state directory contains:

- `owner.lock`: a single-host process lease.
- `paper.sqlite`: the same cumulative hypothetical ledger, local fills/orders, funding, risk/day controls, manager state/cooldowns and opportunity traces.
- `public_requests.sqlite`: request-budget evidence, using a synthetic zero public identity rather than a funded account.
- `health.json` and `alerts.jsonl`: latest heartbeat and changes in health.
- `backups/paper-latest.sqlite`: a consistent SQLite online backup, refreshed hourly and at shutdown.

Checkpoints are transactional, use WAL and full synchronous writes, and are bound to the session, policy and active-source fingerprint. Wrong policy/source, corrupted state or different market specifications block recovery. Keep the original state; do not delete it to bypass a failure.

**A restart with open PAPER exposure or unresolved PAPER orders stops for replay review.** The missed candles and funding cannot safely be reconstructed from the newest quote. This preserves evidence instead of resetting the balance or pretending the missing period never happened. Flat restarts restore fills, cash, setup counts and strategy cooldowns, then require fresh stream recovery before new entries.

New segments belong to the same cumulative session. Do not add their cumulative balances or fills together as independent returns. Preserve segment manifests and fill identities. PAPER collateral remains hypothetical; no on-chain competition account or return is certified by these files.

The single-host owner lock is not a distributed lock. Keep one active owner for the intended session. Never run the future laptop and server traders simultaneously for one team account.

## Resource and evidence limits

Health reports include process memory high-water usage and disk utilization. Memory at 2 GB and disk usage at 85% produce warnings; 90% disk usage halts PAPER operation. Checkpoints have a 128 MB serialized-state limit. Crossing a limit requires review, retention/archival work or measured capacity changes; it does not silently drop accounting evidence.

The logrotate template rotates local alert history. Session evidence and accounting histories are retained. Archive/compress old evidence to a durable backup location before disk limits are reached. Do not delete current journals or reset histories to maintain uptime. A multiweek memory/disk benchmark has not yet been completed, so the limits are guards rather than a claim of bounded RAM use forever.

## Prepare a Linux server

The templates assume code in `/opt/anchorium`, Python in `/opt/anchorium/.venv`, a dedicated non-root user/group `anchorium`, and persistent state/evidence under `/var/lib/anchorium`.

Use a starting allocation of 2 virtual CPUs, 4 GB RAM and about 80 GB SSD, with reliable outbound HTTPS/WSS and synchronized time. This is an engineering estimate. Verify the pinned dependencies in a clean Linux environment rather than copying the Mac environment. Heavy training/backtests should run separately.

Installation requires an actual server host and administrative access. No AWS account, purchase, Linux host or SSH identity was supplied for this task, so these templates have not been installed on a remote server.

On that server, create the dedicated user, install the reviewed source and dependencies, verify the freeze and safety/integration tests, and review the templates. Then install the PAPER service and health timer in systemd and the rotation file in logrotate. Keep inbound SSH restricted and time synchronization enabled. PAPER operation needs no team or API private key.

The service forces PAPER/testnet/par, uses restricted filesystem access and a persistent systemd state directory, and sets a 3 GB process memory ceiling on the proposed 4 GB host. It restarts failures with 30-second backoff and at most three starts in five minutes. It sends SIGINT for a clean stop. If recovery requires review, it repeatedly refuses entry and reaches the supervisor's start limit rather than creating a new empty ledger.

Linux/systemd installation and syntax verification must be performed on the actual target. Running a bounded process on this Mac is not evidence of an AWS deployment or Linux service validation.

## Healthy-feed collection

Before claiming healthy data, examine completed-candle age, BBO/mark freshness, stream recovery and the scanner's reasons. A live WebSocket connection and a fresh order book do not imply recent completed candles.

When the feed is healthy, collect 24–48 hours of continuous PAPER observations on the intended host, including fees/funding, genuine decisions, no-trade reasons, resource growth and outages. Use fake/offline scenarios for failure cases that cannot be safely produced in practice. Do not force trades, fabricate bars, widen freshness thresholds or count repeated replays as new ML labels.

Today the new public diagnostic observed stale raw histories and old public trades with active book/context streams. Therefore, the long healthy-feed validation remains pending venue/data recovery. The collector will continue to record the actual condition and keep stale candidates blocked.
