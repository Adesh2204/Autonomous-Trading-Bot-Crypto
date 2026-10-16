# Team Anchorium: practice setup and one-hour PAPER evidence

Report created: 2026-10-07T11:56:07.389419+05:30.

**The signer check and requested emergency configuration are complete, and the one-hour PAPER run has finished. Funded trading practice is still not ready.** The ten-market change is prepared and offline tested, but **has not been submitted**. The manual wallet-verification reply is still missing. No actual entry, exit, cancellation or protective order was submitted. The strategy is unchanged.

## 1. What changed

The new private-signer preflight derives only the API wallet's public address, compares it with the approved address, and checks the durable local nonce owner. A separate leverage helper prepares or deliberately applies only the user-requested **1x CROSS** setting. It cannot enable orders, cancel orders, transfer funds or switch account mode, and startup does not silently run it.

The emergency policy now records the exact requested configuration: one entry ATR beyond the normal stop, 0.5% execution allowance, reduce-only. It stays **disabled**. Four extra offline checks verify its geometry and refusal behavior. The full repository suite passed **1,276 tests**, with zero failures, errors or skips.

The bot ran for the requested hour on this Mac with real public `par` feeds, a separate simulated ledger, monitoring, a persistent checkpoint and backups. Additional bounded read-only probes compared REST with feed snapshots and passed actual captured responses through the unchanged adapter.

## 2. Safety and frozen strategy

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

These flags are still enforced. Angel One execution remains prohibited. The original NSE repository was untouched. `signal_brain.py`, eight protected strategy methods and 32 protected parameters passed their comparison against `nse-working-baseline`. VWAP, EMA, ATR, long/short conditions, stops, targets, cooldowns and direction flips were not improved or tuned.

Scanner settings remain **300 completed bars**, **0.40% ATR floor**, **15 bps maximum spread**, **Top-3** and the existing completed UTC input convention. Historical CSVs never replace current public candles. An unavailable exchange publication clock remains unavailable rather than being invented.

Evidence: [full-suite and freeze receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/test_receipt.json>), [1,276 offline test results](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/regression.xml>).

## 3. Actual account and API key

At **2026-10-07T11:55:04.945984+05:30**, read-only account queries observed the registered team wallet `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`, **1,000,000 USDPR**, `unifiedAccount`, approved API wallet `anchorium-bot-1`, and no `par` positions or ordinary/trigger-aware open orders. The public API approval expires at 2027-04-04T23:02:04.898000+05:30. The account is already unified; no repeated mode change was needed.

The local API key derives to **`0x46c9BED595770150752E7fA3806449F81E0Ec6f9`**, matching the approved address. The report contains public addresses and source names only. It contains no private key, seed phrase, signature or signed payload. No team-wallet secret was requested or used. Address derivation does not test an actual exchange signature.

A nonce is the unique time-based number attached to a signed request. Saving the last number helps prevent reuse after a restart. The nonce probe used `/Users/adesh/Autonomous Trading Bot - Crypto /runtime/testnet/anchorium-bot-1/nonces.sqlite`. It allocated **zero nonces**, made **zero signatures**, and rejected a second process trying to own that same local signer. The probe released its lease after checking. Keep this nonce database permanently with that API key; do not delete it to bypass a safety failure. Another host or another OS user has not been audited. Run only one future signer host/process.

The observed clock state was `HEALTHY` with offset -661 ms. The public account rate budget was healthy at observation. Both are timestamped observations and must be checked again before any future action.

Evidence: [read-only account response audit](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/account_check_final.json>), [private-key identity and local ownership check](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/signer_preflight_final.json>).

## 4. Leverage: prepared versus actually changed

The ten-market change is prepared and offline tested, but **has not been submitted**. The manual wallet-verification reply is still missing.

| Market | Latest saved exchange setting | Required bot setting |
| --- | --- | --- |
| `par:BRENT` | 20x cross | 1x cross |
| `par:BTC` | 20x cross | 1x cross |
| `par:ETH` | 20x cross | 1x cross |
| `par:EWJ` | 20x cross | 1x cross |
| `par:EWY` | 20x cross | 1x cross |
| `par:GOLD` | 20x cross | 1x cross |
| `par:HYPE` | 10x cross | 1x cross |
| `par:SP500` | 20x cross | 1x cross |
| `par:USDEUR` | 20x cross | 1x cross |
| `par:USDJPY` | 20x cross | 1x cross |

Configured leverage on a flat account is a setting; it does not mean there is already leveraged exposure. The bot policy remains 1x. The helper reads runtime asset IDs, requires a funded unified flat account, a valid agent, healthy clock/rates/nonce, and separate manual verification. It journals each fixed action, uses the pinned official SDK and rereads `activeAssetData`. An uncertain transmission stops the sequence without blind retry. It cannot approve future orders.

The user's request already authorizes this narrow configuration change. The pending verification is required by [AGENTS.md](</Users/adesh/Autonomous Trading Bot - Crypto /AGENTS.md>): “require human verification of both wallet identities.” Funds and successful public reads do not perform the human check. The latest request and its exact limits are recorded there for future work. The prepared example confirmation is deliberately false/expired.

Configuration HTTP attempts in this task: **0**. Actual orders submitted: **0**.

Evidence: [exact ten-market read-only plan](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/leverage_plan.json>), [configuration scope and checks](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/leverage_configuration_review.md>).

## 5. Emergency protection in easy language

Suppose a LONG's normal stop is 95 and its entry ATR is 2. The independent emergency trigger is **93**. For a SHORT with normal stop 105 and entry ATR 2, it is **107**. The strategy's normal stop remains unchanged. The order must be reduce-only and sized from the actual filled position.

The policy is configured and documented, with protection still disabled until separately authorized controlled certification. An accepted exchange protective order can operate while the bot is connected too, and can remain after a local crash. It must be installed before that crash; it cannot first be created by a bot that is already offline.

The 0.5% execution allowance bounds the execution limit; it is not a guarantee of a fill during a gap or thin book. Offline tests confirmed LONG/SHORT trigger geometry, precision within that allowance, no action with disabled protection, and refusal when the emergency trigger would lie beyond liquidation. These used synthetic exposure and ephemeral signing fixtures with HTTP blocked. Real funded-account protection is **not certified**.

Evidence: [approved configuration and limitations](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/protection_configuration_approval.md>), [four additional offline checks](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/requested_protection_receipt.json>).

## 6. The full hour of PAPER operation

The run started at **2026-10-07T10:54:32.794525+05:30** and stopped at **2026-10-07T11:54:34.747221+05:30**. Requested duration: **3,600 seconds**; wall time including startup/shutdown: **3602.0 seconds**. Exit code: **0**. Active Python source stayed identical throughout.

| Observation | Result |
| --- | --- |
| Distinct completed scanner cycles | 12 |
| Running heartbeat snapshots | 118 |
| Snapshots with at least one healthy market | 54 |
| Scanner-qualified market observations | 0 |
| Final scan decision | `NO_TRADE` |
| Simulated orders / fills | 0 / 0 |
| Actual exchange orders | 0 |
| Public WebSocket reconnections observed | 5 |
| Accounting halt | None |
| Memory high-water mark | 147.3 MB |

The PAPER account starts from **20,000 hypothetical USDPR**. Its ending equity is 20000, realized P&L 0, fees 0 and funding cashflow 0. These are simulated-account figures, separate from the real 1,000,000 USDPR balance. A run with no fills does not demonstrate actual fee/P&L settlement or profitable trading.

Across the full run, scanner rejection counts were: INSUFFICIENT_HISTORY: 33, STALE_CANDLE: 81, ATR_BELOW_SCANNER_FLOOR: 5, INVALID_MARKET_DATA: 1. Each reason remains linked to the recorded opportunity trace.

The standalone PAPER segment reports its own exchange-account status as `NOT_CONFIGURED` because it has no authorized real-account executor. That does not override the separate read-only funded/unified account audit. Its public feed recovery and hypothetical ledger remain separate from actual account truth.

Health is sampled about every 30 seconds. Counts below describe saved observations, not uninterrupted durations or a new rule requiring all ten markets to be healthy simultaneously. Every selected market must satisfy its own existing freshness/history gates.

| Market | Healthy heartbeat observations |
| --- | --- |
| `par:BRENT` | 2 / 118 |
| `par:BTC` | 9 / 118 |
| `par:ETH` | 6 / 118 |
| `par:EWJ` | 0 / 118 |
| `par:EWY` | 13 / 118 |
| `par:GOLD` | 4 / 118 |
| `par:HYPE` | 13 / 118 |
| `par:SP500` | 20 / 118 |
| `par:USDEUR` | 3 / 118 |
| `par:USDJPY` | 4 / 118 |

Public disconnect recovery was observed in this run: the feed resubscribed and repaired public history/context/book state; the local PAPER ledger was reconciled separately. This does not certify funded order/position recovery. Checkpoint/backup integrity: **`ok` / `ok`**. Stored checksums match: **True / True**. Final clean-shutdown records: **True / True**. The competing PAPER owner was refused during the run.

The collector stopped at the end of the bounded hour. No background service, cloud deployment or external notification sender was installed. Local alerts and all degraded samples were retained.

Evidence: [completed hour receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/continuous_paper_receipt.json>), [PAPER decisions, portfolio and feed report](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/paper_segments/20261007T052432Z-bb04b3e2/report.json>), [local health changes](</Users/adesh/Autonomous Trading Bot - Crypto /runtime/paper/readiness-2026-10-07-current-setup/alerts.jsonl>), [why setups were rejected](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/paper_segments/20261007T052432Z-bb04b3e2/results/opportunity_report.txt>).

## 7. Why market-data readiness still needs evidence

Some real feeds became healthy temporarily; others remained stale or incomplete. Fresh mark/book messages do not make stale completed candles valid. The bounded REST probe at 2026-10-07T05:40:49.630982+00:00 returned:

| Market | Completed rows in the probe's 302-minute range | Age of latest completed close |
| --- | --- | --- |
| `par:BRENT` | 239 | 63.8 minutes |
| `par:BTC` | 230 | 72.8 minutes |
| `par:ETH` | 296 | 6.8 minutes |
| `par:EWJ` | 0 | Unavailable |
| `par:EWY` | 293 | 9.8 minutes |
| `par:GOLD` | 294 | 8.8 minutes |
| `par:HYPE` | 302 | 0.8 minutes |
| `par:SP500` | 302 | 0.8 minutes |
| `par:USDEUR` | 276 | 26.8 minutes |
| `par:USDJPY` | 298 | 4.8 minutes |

This probe's range differs from the UTC-anchored scanner range; these counts must not be substituted for scanner admission results. REST and stream snapshots were sequential, not simultaneous. BTC/BRENT staleness and absent EWJ history were also present in raw REST results. HYPE/SP500 observations differed over time. The four captured range-response checks showed exact raw/normalized completed timestamp parity; this does not establish the exchange's internal root cause.

The recorded SP500 snapshot had a zero ATR from flat candles. Its `INVALID_DECIMAL` rejection was reproduced with the frozen brain and traced to the existing positive-ATR guard. Signed or zero VWAP slope itself is valid and was not that rejection's cause. No missing bars were fabricated and no ATR, history or spread threshold was lowered.

Continue clearly labeled PAPER collection. A usable current signal/execution feed and sustained healthy operation still need to be demonstrated before funded certification. History provenance paperwork does not block public-feed collection or the separately requested flat-account leverage setup.

Evidence: [public REST comparison](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/direct_candle_probe.json>), [exact captured-response adapter parity](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/candle_request_range_probe.json>), [recorded SP500/HYPE indicator diagnosis](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/recorded_indicator_diagnostic_corrected.json>).

## 8. State layout and repeatable commands

The current hour uses a new, separately labeled ledger at **`/Users/adesh/Autonomous Trading Bot - Crypto /runtime/paper/readiness-2026-10-07-current-setup`**. The old `runtime/paper/readiness-2026-10-07` belongs to earlier source and was preserved rather than overwritten. Do not reset either ledger to bypass recovery guards.

The current state directory holds the cumulative hypothetical ledger (`paper.sqlite`), shared public budgets (`public_requests.sqlite`), owner lock, heartbeat, local alerts and `backups/paper-latest.sqlite`. Evidence for each launch is saved in a separate timestamped segment. Signer nonce/configuration state is separately under `runtime/testnet/anchorium-bot-1` and is never replaced by a PAPER ledger.

From the project root, another foreground run on the same unchanged source/policy uses:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 3600 --state-directory runtime/paper/readiness-2026-10-07-current-setup --output-root docs/practice_setup_2026-10-07/paper_segments
```

In another terminal:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07-current-setup
```

The schedule remains a scan every **300 seconds**, management every **1 second**, health/export every **30 seconds**, subject to network-call latency. Keep the Mac awake and connected. The health checker distinguishes healthy, degraded, stopped and stale/missing heartbeats. A green snapshot means at least one feed currently meets the local checks, not complete practice certification.

AWS is not required for this local check. A future always-on host still needs its own installation, monitoring, recovery and healthy-feed observation. The existing [operating runbook](</Users/adesh/Autonomous Trading Bot - Crypto /docs/paper_practice_runbook.md>) explains the Linux templates; no remote deployment is claimed here.

## 9. Historical data and research

The ten existing hourly CSVs contain **49,831 rows** and their saved hashes are unchanged: **True**. Earlier structural checks found no duplicate timestamps, invalid rows or internal missing hours. They stay isolated research reference data, not current competition-minute candles or proof of tradable fills.

You state that `history.zip` came from the official Discord announcement. The original ZIP and source announcement proof have not been supplied/found in the accessible project locations, so archive/hash provenance verification remains pending. Preserve the ZIP plus the announcement link/screenshot and compare its extracted hashes with these CSVs using the [existing archive verifier](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/verify_organizer_history.py>). Matching an archive proves content identity; the official source announcement is still needed for source attribution. This limitation affects research credibility; it does not prevent live public data reads.

The six research flags remain false: session anchor validated, ML data ready, model validated, holdout complete, promotion recommended and research production changed. There is no automatic model promotion or alternate VWAP anchor. The last flag describes research promotion, not a claim that no infrastructure code was changed.

## 10. What still has to happen

| Readiness item | Saved result |
| --- | --- |
| `STRATEGY_FREEZE` | **PASS** |
| `ACCOUNT_READY` | **YES** |
| `API_APPROVAL_READY` | **YES** |
| `API_SIGNER_IDENTITY_VERIFIED` | **YES** |
| `NONCE_LOCAL_HEALTHY` | **YES** |
| `REMOTE_SIGNER_OWNERSHIP_VERIFIED` | **NO** |
| `CLOCK_READY` | **YES** |
| `ACCOUNT_RATE_BUDGET_READY` | **YES** |
| `LEVERAGE_ALIGNED` | **NO** |
| `PROTECTION_CONFIGURED` | **YES** |
| `PROTECTION_ENABLED` | **NO** |
| `PAPER_ONE_HOUR_COMPLETE` | **YES** |
| `SUSTAINED_USABLE_FEED_DEMONSTRATED` | **NO** |
| `READ_ONLY_RECONCILIATION_READY` | **YES** |
| `LONG_CERTIFIED` | **NO** |
| `SHORT_CERTIFIED` | **NO** |
| `FUNDED_RECOVERY_CERTIFIED` | **NO** |
| `PRACTICE_READY` | **NO** |
| `LIVE_READY` | **NO** |

Account/approval/reconciliation flags refer to the saved read-only observation. Private identity and nonce checks are local. Emergency settings are configured but disabled. The hour proves guarded local operation; it does not certify actual fills, real protection or returns.

The remaining order is: manually verify the team/API wallet identities; complete and reread the deliberate 1x CROSS setup; collect usable fresh `par` data; then obtain explicit authorization for a tiny bounded certification test. Certify LONG and return fully flat with no leftover orders and reconciled fees/P&L before SHORT. Only after both are flat and reconciled should funded reconnect/restart/cancel recovery be reviewed and supervised practice considered. Existing offline scenarios must keep their offline label if safely producing them on the real venue is impractical. The detailed [inactive certification plan](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/certification_plan.md>) records this sequence.

The tiny funded tests were **not run** because their prerequisites and explicit later order activation are missing. Keep one API signer process, one host and one global `par` position, including partially filled exposure and unresolved orders. Do not size a test from the million-unit balance or assume funding/agent approval grants execution permission.

The software checks improve reliability, but this zero-fill hour cannot establish whether the frozen VWAP strategy will win. Profitability, consistent venue data, funded execution evidence and honest reproducible evaluation are still needed. The [official participant guide](https://perpetual-alpha26.github.io/docs/) remains the organizer reference; our stricter safety/configuration checks are project engineering policy.

## 11. Evidence identity

Git commit: `6e4e520892b91b613bce237195ea67f5f69846b4`; working tree dirty: **True**. Active Python source fingerprint: `90ebdb94c333f18a6e75f937dd6f574a7e43d1ded4780b2b424fae21a79617fe`. Full tests, account audit, final signer check and the hour use the same active source: **True**. The original freeze manifest was not rewritten. Policy/brain/configuration and principal evidence hashes are recorded in [machine-readable readiness report](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/readiness.json>).

The initial extra geometry test expectation and initial indicator diagnostic were corrected in later labeled artifacts; original observations remain preserved. The final geometry receipt and corrected indicator diagnosis are authoritative for this report. This documentation and readiness file provide evidence, never activation permission.
