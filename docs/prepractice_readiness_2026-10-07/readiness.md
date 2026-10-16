# Team Anchorium: pre-practice verification — 7 October 2026

The software passed its safety checks and bounded PAPER operating checks. The configured team account is funded and already unified. **Funded automated practice is still blocked:** market freshness is inconsistent, exchange leverage differs from policy, emergency protection is unapproved, and controlled execution certification has not happened. No exchange order or account administration was performed.

## 1. The safety lock and strategy

`EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` remain enforced. The original NSE repository was untouched. Angel One execution stays blocked. No private key was used, no real signer was constructed for the account checks, and no account mode, approval or leverage setting was changed.

The strategy-freeze check passed against `nse-working-baseline`: the protected brain file, 8 protected methods and 32 parameters match. VWAP, EMA, ATR, long/short rules, stops, targets, cooldowns and direction flips were preserved. Phase-0 passed all 12 checks.

The first full test run passed 1,198 tests. The final run after the accounting correction passed **1,214 tests, zero failures, zero errors, zero skipped**, including 16 new unified-account regressions. Existing recovery, fee/funding, partial-fill, stale-feed, lockout and compliance scenarios were included. These are offline engineering tests, not proof of trading profit or funded execution.

Evidence: [final test receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/prepractice_readiness_2026-10-07/test_receipt.json>) and [full test results](</Users/adesh/Autonomous Trading Bot - Crypto /docs/prepractice_readiness_2026-10-07/regression.xml>).

## 2. Your actual account

The read-only check completed at **2026-10-07T09:12:32.419847+05:30** using your current configured team address, rather than the different address in an earlier conversation.

| Item | Observed result |
| --- | --- |
| Network / venue | Hyperliquid testnet / `par`, runtime DEX index 257 |
| Team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Account mode | `unifiedAccount` |
| Reported USDPR balance | 1,000,000 |
| USDPR token | 3032, matched to runtime `par` metadata |
| API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| API approval | Approved as `anchorium-bot-1` |
| Approval expiry | 2027-04-04T23:02:04.898000+05:30 |
| `par` positions | 0 |
| Ordinary and trigger-aware open orders | 0 |
| Account action budget | 3 used / 10,000 cap; 9,997 remaining at observation |

You **do not need to switch this observed account to unified mode again**. It is already unified. The API approval check verifies the public approval and expiry; it does not test your private signing key or establish human wallet verification.

`userFees` reported base taker 0.045% and maker 0.015%. The venue's documented undiscounted scaling gives 0.09% taker and 0.03% maker, matching the current PAPER assumptions. Future actual fees must come from each reported fill. See the [official participant guide](https://perpetual-alpha26.github.io/docs/).

The account observer reconciled the explicit window from **5 October 2026 00:00 UTC** to the saved observation. It found no fills, funding payments, positions or orders in that window and did not pause entries. Earlier lifetime history and future changes are not certified. Reconciliation must run again on actual startup and reconnect. Evidence: [account query audit and responses](</Users/adesh/Autonomous Trading Bot - Crypto /docs/prepractice_readiness_2026-10-07/account_check.json>).

## 3. The accounting correction made during this check

The account was genuinely funded, but the old reader used `clearinghouseState.marginSummary.accountValue`. That per-DEX field returned zero, making the bot incorrectly say “not funded.” Hyperliquid documents that unified balances and holds belong in the spot state and that per-DEX balance summaries are not meaningful. See [official account abstraction documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes).

The reader now uses the reported USDPR spot total once, verifies its token against runtime metadata, and reports its source. Position margin comes from reported `par` positions. It does not add per-DEX balance summaries or unrealized P&L to the spot balance. Unknown withdrawable capacity remains `null`; total balance is not invented free margin. Exact coin/side capacity still comes separately from `activeAssetData.availableToTrade` and `maxTradeSzs`.

The real account was flat during this verification. Actual non-flat equity/margin comparisons and real fill/fee/funding accounting still require controlled funded practice. The synthetic regressions do not certify those real-account scenarios.

Metadata changes to the collateral token now invalidate the client. The regression tests cover zero per-DEX summaries, held funds, overlapping P&L, other currencies, wrong/duplicate tokens, invalid balances and unchanged live locks. The Phase-0 environment test was also corrected to accept public account settings while checking the safety controls; failures no longer compare the entire configuration containing unrelated credential values.

## 4. Competition market data

All ten runtime markets use prefixed `par:` names. Market-wide queries explicitly select `dex=par`. There is no fallback to plain BTC, ETH or the native venue.

The REST/45-second WebSocket diagnostic completed at **2026-10-07T03:41:28.518292+00:00**. It received 528 WebSocket messages with no stream error. Its initial candle observations were:

| Market | Returned completed bars | Age after latest bar closed | Within 120-second freshness limit |
| --- | --- | --- | --- |
| `par:BRENT` | 300 | 34.5 seconds | YES |
| `par:BTC` | 298 | 155.4 seconds | NO |
| `par:ETH` | 236 | 3876.4 seconds | NO |
| `par:EWJ` | 0 | Unavailable | NO |
| `par:EWY` | 178 | 7358.0 seconds | NO |
| `par:GOLD` | 285 | 939.0 seconds | NO |
| `par:HYPE` | 300 | 39.9 seconds | YES |
| `par:SP500` | 300 | 40.6 seconds | YES |
| `par:USDEUR` | 157 | 8621.3 seconds | NO |
| `par:USDJPY` | 223 | 4662.0 seconds | NO |

All raw candle timestamps matched the adapter. This supports a venue-history limitation in that observation rather than a timestamp conversion error. Some markets had no recent trades or no returned history. A later observation can differ; these are timestamped results.

Books were current in the initial check. Mark, oracle and funding fields were received separately in the public contexts. Their API contexts do not expose an exchange publication clock, so the report preserves local observation time rather than claiming a verified oracle-update timestamp. A fresh book/context alone never makes old candles usable.

The scanner still requires 300 completed bars, the existing ATR floor of 0.40%, spread no greater than 15 bps and the unchanged Top-3 selection. It did not fabricate missing candles, widen limits or force trades. See [raw REST and WebSocket evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/prepractice_readiness_2026-10-07/market_freshness.json>).

## 5. Complete PAPER operation, monitoring and recovery

The intended host for these checks was the current Mac. The full launcher started the configured public feed, scanner, frozen strategy, risk controls, simulated execution, local ledger, monitoring and recovery pipeline. It used a separately labeled **20,000 hypothetical USDPR** starting balance. Your actual 1,000,000 USDPR account was observed separately and was not used as simulated starting cash.

| Segment | Requested running time | Completed scans | Exit code | Last scan decision |
| --- | --- | --- | --- | --- |
| Continuous | 660 seconds | 3 | 0 | NO_TRADE |
| Clean restart | 90 seconds | 1 | 0 | NO_TRADE |

The continuous segment ran from 2026-10-07T09:13:19.723590+05:30 to 2026-10-07T09:24:23.473666+05:30, including startup/shutdown overhead. The restart reused the same source, policy and durable ledger. It did not reset the balance or erase earlier decisions. Recovery reported restored state and a previous clean shutdown. Both processes stopped intentionally at their duration limits.

There were **7 healthy running heartbeat observations** among 28 total saved samples. Markets healthy at least once: par:BRENT, par:SP500. Healthy samples are intermittent; they do not establish 11 minutes of uninterrupted healthy data or all-market readiness. Warning samples and rejection reasons were preserved too.

No simulated orders or fills were generated in these segments. Every scan rejected all markets for insufficient completed history, so the live-public signal calculation and trading path were not exercised beyond that guard. The scanner recorded its actual rejection reasons. PAPER equity remained 20,000 with no trading fees or position funding. This demonstrates a stable zero-exposure ledger; actual entry/exit P&L and funding settlement were not exercised by this public run. Their existing offline test coverage passed. A zero-trade return is not evidence of profitability.

The separate public recovery experiment deliberately closed one actual BTC WebSocket. The existing engine reconnected once, resubscribed and completed REST history/book/context repair, reaching recovery generation 2. A quote was read after repair. This is genuine public-feed recovery, not certification of order recovery on a funded account. See [controlled public reconnect evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/prepractice_readiness_2026-10-07/public_reconnect.json>).

The second-owner check correctly rejected a competing process. Checkpoint and backup integrity are `ok` / `ok`, the checkpoint checksum matches, and the final clean-shutdown flag is `True`. Open exposure or unresolved PAPER orders would require replay review on restart; that guard remains enforced.

The schedule remains scanning every 300 seconds, management every second, and health/export checks every 30 seconds. State is under `/Users/adesh/Autonomous Trading Bot - Crypto /runtime/paper/readiness-2026-10-07`: `paper.sqlite`, `public_requests.sqlite`, `owner.lock`, `health.json`, `alerts.jsonl` and `backups/paper-latest.sqlite`. Evidence segments live separately under this report directory. Health/alerts are local files; external notifications have not been configured. The collector was stopped at the end of these checks and is not running continuously in the background.

## 6. What still blocks funded automated practice

**Leverage configuration:** the bot's reviewed risk policy is 1x cross. Every inspected exchange market differs:

| Market | Observed exchange setting | Bot policy |
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

This is the configured leverage, not a claim that the current empty account already has leveraged exposure. Do not raise the bot's policy merely to match these defaults. A separately authorized, manually verified setup must align intended market leverage and recheck capacity before funded practice. No exchange setting was changed here.

**Emergency protection:** `configs/reliability_policy.json` still has protection disabled, no approval reference, no approved distance and no approved execution allowance. The existing proposed policy is one ATR beyond the normal stop with a 0.5% execution allowance. That proposal is not approved or enabled. Normal strategy stops/targets remain unchanged. See [protection policy explanation](</Users/adesh/Autonomous Trading Bot - Crypto /docs/emergency_protection_policy_2026-10-05.md>).

**Market readiness:** keep rejecting stale or insufficient histories. Continue collecting honest PAPER evidence when the feed supports the unchanged history/freshness rules. Do not fill missing minutes with invented prices or lower thresholds to create activity.

**Execution certification and explicit activation:** the public account observations do not authorize signatures. Private signer verification, reviewed protection, fresh reconciliation, healthy feed and controlled account certification remain future work. Only the human's explicit change after manual verification can authorize future testnet execution. Mainnet and Angel One remain outside this migration.

## 7. Readiness flags and their meaning

| Flag | Result |
| --- | --- |
| MARKET_DATA_READY | **NO** |
| ACCOUNT_READY | **YES** |
| API_AGENT_READY | **YES** |
| RECONCILIATION_READY | **YES** |
| PROTECTION_READY | **NO** |
| PAPER_READY | **YES** |
| LIVE_READY | **NO** |
| ACCOUNT_RISK_CONFIGURATION_READY | **NO** |
| API_SIGNER_VERIFIED | **NO** |
| CONTROLLED_EXECUTION_CERTIFIED | **NO** |
| OVERALL_FUNDED_PRACTICE_READY | **NO** |

`ACCOUNT_READY`, `API_AGENT_READY` and `RECONCILIATION_READY` mean the saved **read-only** funded/approval/flat-window checks passed. `PAPER_READY` means the guarded local launcher, bounded run and flat restart passed. It does not mean every feed is healthy, the strategy is profitable, or funded execution is ready. `MARKET_DATA_READY` is strict all-market readiness and stays NO because freshness was inconsistent. `LIVE_READY` stays NO regardless of the public approvals.

## 8. Operating instructions

For another foreground PAPER run on the same unchanged source/policy/ledger, from the project root:

```sh
.venv/bin/python scripts/run_practice.py --duration-seconds 3600 --state-directory runtime/paper/readiness-2026-10-07 --output-root docs/prepractice_readiness_2026-10-07/paper_segments
```

In another terminal, inspect its heartbeat:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07
```

Exit 0 means healthy, 2 means degraded, 3 means stopped/failed, and 1 means stale/missing/invalid heartbeat. Keep the Mac awake, online and with sufficient disk. Restart with the same state; do not delete a failed checkpoint to bypass its guard. Source/policy changes require separately labeled evidence or reviewed migration, rather than silently reusing performance history.

AWS is not required for these local PAPER checks. Uninterrupted practice needs an always-on reliable host. The repository contains Linux service/health/rotation templates, but no remote server was deployed or tested in this task. The existing runbook proposes 2 vCPUs, 4 GB RAM and roughly 80 GB SSD as a starting estimate; those are engineering estimates, not organizer requirements or current pricing. A 24–48 hour healthy-feed run on the final host remains recommended before activation. See [operating runbook](</Users/adesh/Autonomous Trading Bot - Crypto /docs/paper_practice_runbook.md>).

## 9. Reproducibility and limits

Git commit: `6e4e520892b91b613bce237195ea67f5f69846b4`. The working tree contains uncommitted changes, so the active Python source fingerprint is also recorded: `642742053703b471436ae6cfc7cb5cc5958d7bc59e1780e4f47636947526388b`. The final full suite, corrected account check and both PAPER segments use that same active source. The initial market diagnostic predates the account-reader correction; its candle parser and freshness logic were unchanged.

The audit scripts and original failed-readiness evidence were preserved in this directory. [machine-readable readiness](</Users/adesh/Autonomous Trading Bot - Crypto /docs/prepractice_readiness_2026-10-07/readiness.json>) links the receipts and segment details. Healthy and degraded observations remain clearly labeled PAPER evidence. No unvalidated ML model, alternate VWAP anchor, strategy optimization or research promotion was enabled. These checks improve readiness; they do not establish a winning return or guarantee a competition result.
