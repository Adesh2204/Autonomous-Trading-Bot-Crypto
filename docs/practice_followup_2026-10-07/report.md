# Team Anchorium: completed 1x CROSS configuration and PAPER follow-up

Created: 2026-10-07T14:26:45.825082+05:30.

**All ten competition markets are now verified at 1x CROSS on the actual testnet account. The configuration helper is fixed and all 1,278 repository tests pass. Orders remain locked, and funded trading practice is still not certified.**

## 1. What was completed

You manually verified the registered team wallet and approved API wallet. The separately authorized helper then changed exactly the ten `par:` leverage settings. It used the official SDK, runtime asset IDs, durable nonce/account ownership and exact-action checks. Each setting was read back from the exchange, then checked again in a separate read-only account audit. It submitted **10 leverage configuration actions** and **zero trading orders**. It made no transfer, cancellation or account-mode change.

The first apply attempt stopped safely before any HTTP submission. The full helper flow reproduced this problem offline: its repeated fresh-account checks consumed the local request-weight allowance before the first configuration action. The fix waits for read capacity, preserves the safety reserve, checks approval expiry throughout the wait and repeats the complete account check afterward. A wait can age the previous clock reference, so the helper collects the existing required distinct fresh references before continuing. It does not weaken clock limits or retry an uncertain signed action.

Failures now save reason codes plus clock/rate observations instead of only a generic message. The first failed attempt and intermediate development test results remain saved. The final targeted suite passed 29 tests; the full suite passed **1278 tests with zero failures, errors or skips**. Its ten-market integration uses an ephemeral signer and fake HTTP, and is clearly labeled offline. The actual setting change has separate real exchange evidence.

Evidence: [actual configuration and ten-market readback](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/leverage_applied_paced.json>), [offline full-helper integration](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/configuration_integration_receipt.json>), [full test and freeze receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/test_receipt.json>).

## 2. Actual wallet and exchange settings

Read-only account observation: **2026-10-07T14:19:52.130138+05:30**.

| Check | Observed result |
| --- | --- |
| Network / DEX | Hyperliquid testnet / `par` |
| Registered team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Approved API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| USDPR collateral / reported account value | 1000000.0 / 1000000.0 |
| Account mode | `unifiedAccount` |
| API approval valid | True |
| Actual `par` positions | 0 |
| Ordinary / trigger-aware orders | 0 / 0 |
| Clock | HEALTHY |
| Account technical readiness | True |

| Competition market | Account setting |
| --- | --- |
| `par:BRENT` | 1x CROSS |
| `par:BTC` | 1x CROSS |
| `par:ETH` | 1x CROSS |
| `par:EWJ` | 1x CROSS |
| `par:EWY` | 1x CROSS |
| `par:GOLD` | 1x CROSS |
| `par:HYPE` | 1x CROSS |
| `par:SP500` | 1x CROSS |
| `par:USDEUR` | 1x CROSS |
| `par:USDJPY` | 1x CROSS |

The wallet was already funded and unified. No repeated unified-mode action was required. The local API key matched the manually verified approved address; only this API signer was used for the authorized leverage actions. No team-wallet private key, seed, signature or signed payload appears in these reports.

1x CROSS is a setting for shared collateral. It does not open a position, produce a profit, reserve the whole million-unit balance or authorize the bot to trade. It also does not make future risk disappear. Actual position size, side capacity, fees, funding, liquidity and protection still matter. The bot's one-global-position rule remains enforced.

The account audit includes `userFees`, `userRateLimit`, `activeAssetData`, positions, ordinary/trigger orders and actual fill/funding reconciliation for its explicit recorded window. No-fills accounting is not certification of real trade settlement. Budget observations are snapshots, not a permanent permission. Preserve `runtime/testnet/anchorium-bot-1/nonces.sqlite` and its configuration journal; never reset nonce history to bypass a failure.

The final local signer preflight passed after the setting changes: the API address still matches, nonce history is healthy, and a competing local owner was refused. That probe allocated no nonce, created no signature and submitted no action. Its lock scope is this host/OS user; another host has not been audited.

Evidence: [final local signer and nonce probe](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/signer_preflight_after.json>), [fresh post-configuration account audit](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/account_check_after.json>), [durable state and action-count checks](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/operating_checks_after.json>).

## 3. Safety and strategy

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

Both remain enforced. Angel One execution remains blocked. The original NSE repository was untouched. `signal_brain.py`, eight protected strategy methods and 32 protected parameters passed the baseline comparison. VWAP, EMA, ATR, LONG/SHORT decisions, normal stops/targets, cooldowns, direction flips and strategy state behavior were not tuned.

Scanner requirements remain **300 completed bars**, **0.40% ATR floor**, **15 bps maximum spread**, **Top-3** and completed UTC inputs. No historical CSV was substituted for a current feed, no bars were invented and no strategy threshold was relaxed.

## 4. Emergency protection

The configured policy remains: **normal strategy stop + one entry ATR farther away + 0.5% execution allowance + reduce-only**. For a LONG the independent trigger is below the normal stop; for a SHORT it is above it. It protects only actual filled exposure.

**Configured: YES. Enabled: NO.** No protective order was created. A future accepted protective order can trigger during normal operation and remain on the exchange if the bot disconnects. The 0.5% allowance does not guarantee execution. Real acceptance, quantity updates and recovery still need a separately authorized controlled certification. This independent policy does not alter the normal strategy stop.

The prior approved geometry document and offline checks remain valid because the protection-policy file is unchanged: [approved protection policy](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_setup_2026-10-07/protection_configuration_approval.md>).

## 5. More PAPER evidence, with honest source labels

The additional 15-minute run completed before editing the helper. It used real public `par` feeds and the preserved hypothetical ledger. It finished cleanly, had **3 scanner cycles**, **0 qualified markets**, **0 simulated fills**, **1 reconnect**, and **zero real orders**. State and backup integrity/checksums passed. Of 30 running observations, 18 had at least one locally healthy market; this does not mean uninterrupted healthy data or an admitted strategy setup.

Its segment-only scanner rejections were INSUFFICIENT_HISTORY: 3, STALE_CANDLE: 24, ATR_BELOW_SCANNER_FLOOR: 2, INVALID_MARKET_DATA: 1. The persistent funnel also retains earlier runs; the corrected completion summary explicitly separates cumulative counters from this segment's counters.

After the helper change and real configuration, an additional bounded current-source PAPER run completed for **302.7 seconds**. It had **0 scanner-qualified observations**, **0 simulated fills**, **0 reconnects**, and **zero real orders**. Rejections: ATR_BELOW_SCANNER_FLOOR: 1, STALE_CANDLE: 9. It stopped cleanly with verified backups. Its source fingerprint matches the passing full suite and actual configuration helper.

The hypothetical PAPER balance is separate from the actual wallet. Zero fills do not establish profitable trading or actual fee/funding/P&L settlement. Public-feed and local-ledger recovery remain separate from funded position/order recovery.

The first segment retains source `90ebdb94c333f18a6e75f937dd6f574a7e43d1ded4780b2b424fae21a79617fe`. The helper pacing/diagnostics fix and its regression test produce current source `4b24a85f9fbb2ba4ef84eefafe8b847fea893b972aaddcaeb7f765e7c3b9b07c`. The second segment uses a new explicitly named PAPER state directory, preserving the prior ledger and recorded fingerprint. Saved hashes were not rewritten.

Evidence: [15-minute segment and recovery checks](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/paper_completion_corrected.json>), [current-source PAPER completion](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/post_configuration_paper_receipt.json>), [checkpoint and backup integrity](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/operating_checks_after.json>).

## 6. What still prevents funded practice

**The current signal feed still needs usable fresh-candle evidence.** Fresh book/mark messages do not make stale completed candles valid. The earlier raw REST comparisons also showed stale or absent candle histories; the captured-response adapter checks preserved the exchange's actual completed timestamps. The exchange's internal cause is not proven. Funding or leverage changes cannot repair public candle history.

No valid setup is a legitimate `NO_TRADE`. Keep recording genuine observations. Do not lower ATR, remove the 300-bar requirement, widen spread limits, invent bars or load historical CSVs as live data.

The LONG, SHORT and funded recovery sequence is prepared in [the inactive next-step plan](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/next_steps.md>). Those tests were not run: usable current data and separate explicit order/protection activation with a small reviewed budget are still required. Complete LONG, verify flat and reconcile actual fees/P&L before SHORT; then certify cancellation, reconnect, restart, existing-position recovery and duplicate prevention. Do not start autonomous funded practice merely because configuration passed.

## 7. Readiness now

| Item | Evidence-based status |
| --- | --- |
| `STRATEGY_FREEZE` | **PASS** |
| `FULL_TEST_SUITE` | **PASS** |
| `HUMAN_WALLET_IDENTITIES_VERIFIED` | **YES** |
| `ACCOUNT_READY_READ_ONLY` | **YES** |
| `API_AGENT_READY_READ_ONLY` | **YES** |
| `READ_ONLY_RECONCILIATION_READY` | **YES** |
| `API_SIGNER_IDENTITY_VERIFIED` | **YES** |
| `NONCE_LOCAL_HEALTHY` | **YES** |
| `REMOTE_SIGNER_OWNERSHIP_VERIFIED` | **NO** |
| `LEVERAGE_ALIGNED` | **YES** |
| `PROTECTION_CONFIGURED` | **YES** |
| `PROTECTION_ENABLED` | **NO** |
| `PAPER_OPERATION_VERIFIED` | **YES** |
| `SUSTAINED_USABLE_SIGNAL_FEED_DEMONSTRATED` | **NO** |
| `LONG_CERTIFIED` | **NO** |
| `SHORT_CERTIFIED` | **NO** |
| `FUNDED_RECOVERY_CERTIFIED` | **NO** |
| `PRACTICE_READY` | **NO** |
| `LIVE_READY` | **NO** |

Account readiness refers to the saved read-only observation. PAPER operation is verified for the bounded saved runs, not for an always-on remote server. Real funded execution remains uncertified. The six research validation/promotion flags remain false; no ML model or alternate VWAP anchor was promoted. The research `PRODUCTION_CHANGED=false` flag does not mean no infrastructure changed.

## 8. Running again and hosting

The chosen host remains this Mac. No AWS deployment or background server service was installed. AWS is not required for the completed local checks. For longer sessions, keep the host awake, connected, monitored and restricted to one trader/signer owner. A future server needs its own installation, persistent paths, monitoring, backup and recovery checks.

For another PAPER session on the current unchanged source, from the project root:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 3600 --state-directory runtime/paper/readiness-2026-10-07-paced-source --output-root docs/practice_followup_2026-10-07/paper_segments
```

In a second terminal:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07-paced-source
```

The existing schedule is a scan every 300 seconds, management every second, and health/export every 30 seconds, subject to network latency. The completed runs stopped at their bounded deadlines; no unlabeled collector is left running. Source/policy changes require explicit checkpoint handling rather than relabeling an old ledger. Keep signer state separate from hypothetical PAPER state.

## 9. What this means for the hackathon

The infrastructure is stronger and the requested leverage mismatch is resolved. **These checks cannot prove that the frozen VWAP strategy will win.** There is still no real-trade certification or demonstrated trading advantage in these zero-fill runs. The strongest submission will show honest reproducible results, preserved strategy comparisons, real accounting evidence and reliable operation. Do not claim validated ML or winning returns that the evidence does not establish.

This report records results; it cannot unlock trading. Principal evidence hashes, Git commit/dirty state, source identity and flags are in [the machine-readable readiness file](</Users/adesh/Autonomous Trading Bot - Crypto /docs/practice_followup_2026-10-07/readiness.json>).
