# Anchorium practice improvements: what changed and what remains

Date: 5 October 2026. Scope: exchange infrastructure, operations and public PAPER evidence. The original NSE repository and frozen strategy were not changed. No exchange action, wallet administration, server purchase or remote deployment occurred.

This records the practice improvements and public runs **before** the subsequent organizer clarification of the 80% mark-price reference. Its test receipt and PAPER ledgers identify that earlier source version. For the later correction and current validation, see [the organizer clarification review](</Users/adesh/Autonomous Trading Bot - Crypto /docs/organizer_clarification_2026-10-05/explanation.md>). Earlier public-run evidence is preserved and is not relabeled as a run of the changed source.

## Direct answer about winning

I cannot honestly say this strategy will win the hackathon. My assessment is that it is a sensible, explainable baseline whose competitive trading edge on `par` has not yet been demonstrated.

VWAP, EMA and ATR give it understandable decisions and management. The new controls help prevent stale-data entries, accidental extra exposure, incorrect accounting and unsafe restarts. Those are useful engineering strengths, but they do not create proof of profitable signals.

The main remaining performance questions are whether genuine signals occur often enough, whether moves exceed fees/spread/funding, whether the strategy behaves well across the venue's asset classes, and whether it meets ranking eligibility. The current observations contain no trades, so they cannot answer profitability or win-rate questions.

Do not weaken thresholds to manufacture activity or call unvalidated research a proven model. Preserve the baseline, collect genuine executable observations, and use prospective comparisons before proposing a strategy change.

## 1. Scanner/runtime conflict fixed

The default scanner still requires PAPER/false. A future runtime explicitly passes its `LiveAuthorization`, team address and API signer address to the same scanner. Before every scan, that scanner verifies the exact authorization and current testnet configuration.

The execution layer retains its separate order permissions and real-account gates. Public scanning does not grant permission to submit an order. Revoked/expired approval, a wrong team/signer, mainnet selection and an unauthorized mode fail before scanning.

The regression exercises the actual future builder, scanner, account recovery, risk and owner session with a fake exchange and ephemeral agent. Network transport is prohibited in that test. It also verifies that management-only cycles do not run another scanner pass.

## 2. Explicit schedule and launchers prepared

The operational schedule is 300 seconds between strategy scans, approximately one second between owner/management ticks, and 30 seconds between normal exports and health checks. Network calls add latency; these are scheduling targets rather than latency guarantees.

The future runtime continues account and existing-position observation between scans. Current margin/buying-power observations use the safety request reserve. Signal formulas, ranking thresholds, VWAP anchor, stops, targets and risk configuration remain unchanged.

The PAPER launcher validates its configuration and starts the actual bot process. The separate future testnet launcher requires explicit future authorization, public account identities, reviewed policies and verified account setup; it refuses the current PAPER defaults.

## 3. Durable PAPER state, recovery and monitoring implemented

PAPER checkpoints preserve the hypothetical ledger, fill/order facts, funding, daily controls, manager state/cooldowns and opportunity traces. They use transactional SQLite writes, checksums and configuration/source identities. A consistent online backup is taken hourly and at shutdown.

A one-host owner lock prevents a second owner of the same state directory. Flat restart recovery was tested offline and against actual public data. Open PAPER exposure or unresolved orders during downtime blocks restart for replay review: missing prices and funding are never invented.

Health records include heartbeat age, feed health by market, scanner reasons, local positions/fills, stream recovery, memory and disk usage. A checker identifies healthy, degraded, stopped and stale/missing states. Local alert history records health changes.

PAPER active-position exports and repeated identical halt output are throttled. Disk and checkpoint-size limits stop the process rather than silently discarding accounting evidence. Long-run memory/retention behavior still needs measurement. External phone/email/chat alerts have not been configured.

## 4. Emergency policy documented, still disabled

The proposed fallback is **one entry ATR beyond the normal strategy stop**, with a **0.5% bounded execution allowance**. It is reduce-only and based on actual filled exposure. It does not replace the normal stop or guarantee a fill through a gap/empty book.

These are starting engineering choices, not optimized performance settings. The proposal and current production reliability configuration remain disabled. Actual funded-account verification and an explicit future approval reference are still required before activation.

See [the emergency-policy explanation](</Users/adesh/Autonomous Trading Bot - Crypto /docs/emergency_protection_policy_2026-10-05.md>).

## 5. Stale data investigated without weakening safeguards

The dedicated raw REST/WS probe observed stale completed histories in all ten markets. The parsed timestamps matched the raw timestamps. Book observations were recent, while public trades were old. During 45 seconds it received 540 public messages, including subscription responses, books, asset contexts, initial trade-history messages and a pong, but no candle messages.

This is evidence that the venue returned stale candle/trade data during that window; it is not evidence that the adapter changed fresh timestamps into stale ones. It does not prove every possible upstream cause or rule out a separate later delivery issue.

Later PAPER runs showed intermittent fresh feed observations in ETH/HYPE and SP500. They also showed stale candles, low ATR and wide spreads. Replaying the exact 675 recorded USDEUR candles reproduced `ATR_14=0.0`, explaining its earlier `INVALID_DECIMAL`: the scanner requires positive ATR for valid risk geometry. A later new candle produced a small positive ATR. The zero-ATR rejection is a data/indicator condition, not evidence that fresh candles were timestamped incorrectly. No fake volatility or altered ATR formula was introduced.

At the end of the final-source run, no market was feed-healthy. A fully healthy sustained feed has not been demonstrated. Native Hyperliquid data was never substituted, missing candles were not fabricated, and freshness/spread/ATR thresholds were not relaxed.

## 6. Actual verification performed

| Check | Result |
|---|---|
| Final full repository suite | **1,178 passed; zero failures, errors or skipped tests** |
| New focused practice tests | 23 passed |
| Broader integration/recovery/export checks | 136 passed |
| Source unchanged during final suite | Yes; receipt records before/after hashes |
| Frozen strategy | Passed: protected file, eight methods and 32 parameters |
| Phase 0 order lockouts | Passed |
| Actual public PAPER runs | Bounded runs of 150, 330 and 90 seconds completed |
| Same-ledger public restart | Restored the earlier development session correctly |
| Exchange orders submitted | **0** |
| Local simulated fills in these runs | **0** |
| Long healthy-feed run | Not completed |
| Linux/AWS installation | Not performed; no remote host supplied |

The development runs received 1,726 and 3,784 public-stream messages. The final-source run received 1,005. They all reported `NO_TRADE`. This is connectivity and operating evidence, not profit evidence.

The final-source run used a separately labeled validation ledger after a small runtime compatibility correction. The earlier development ledger and evidence remain preserved. Do not combine their cumulative balances as independent strategy returns. The tested current-source ledger is in `runtime/paper/release-validation`.

Short observed process memory peaks ranged from approximately 120 to 146 MB across separate processes. They do not establish multiweek memory use or a performance guarantee for a 4 GB server.

The first broad run identified compatibility failures in older zero-argument cycle callers. The runtime now preserves that call for scheduled scans and uses the optional management mode between them. The final full suite passed after the correction; the earlier failing XML is retained as development history.

## 7. Server preparation and remaining requirements

Linux service, health timer and log-rotation templates are ready for review/installation. They force PAPER/testnet/par, run as a dedicated non-root user, use persistent storage, restart with backoff and retain all authorization/recovery barriers.

No server credentials or host were supplied. Local verification therefore ran on this Mac. No AWS instance was bought, and no Linux service installation or systemd syntax check is claimed. All bounded local sessions have stopped; no background collector was left running.

The remaining work is:

1. Obtain sustained usable venue data and collect 24–48 hours of PAPER evidence on the intended host.
2. Measure memory, disk, request budgets, recovery and retention under that run.
3. Install and verify the prepared Linux services when the server is available, and connect the chosen notification transport if wanted.
4. After funding, verify the actual account/agent/margin/fees, approve protection and complete controlled testnet certification before explicit activation.
5. Build enough genuine after-cost performance and research evidence to assess competitiveness.

The official evaluation values net return, lower daily-return volatility and the technical report. Ranking also requires at least ten distinct trading days and a minimum cumulative notional volume; the numerical threshold needs confirmation. Current conservative opportunity limits do not guarantee eligibility. [Official evaluation and rules](https://perpetual-alpha26.github.io/about).

## Files to use

- [Operating runbook and commands](</Users/adesh/Autonomous Trading Bot - Crypto /docs/paper_practice_runbook.md>)
- [Final validation evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_improvements_2026-10-05/validation.json>)
- [Final test receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_improvements_2026-10-05/test_receipt.json>)
- [Raw public freshness evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_improvements_2026-10-05/freshness_public_network.json>)
- [Final PAPER health snapshot](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_improvements_2026-10-05/final_source_paper_health.json>)
- [Exact recorded-candle FX replay](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_improvements_2026-10-05/fx_recorded_indicator_replay.json>)

Current state remains `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false`. ML/session-validation flags remain evidence-driven and are not promoted by these infrastructure improvements.
