## A. ROOT CAUSE MAP

The PAPER engineering repair is implemented. **382 tests pass. The certified signal file is unchanged. No real orders were submitted. Profitability has not been demonstrated or guaranteed.** Broad performance research remains blocked by incomplete provider data, as detailed in section K.

The main reason October 1 produced zero entries was the live volatility requirement: all 10 potential pre-cutoff patterns in the supplied log failed the unchanged 0.40% ATR floor. The infrastructure defects below impaired initialization, data quality, and visibility; fixing them does not make a below-threshold setup eligible.

| Root cause | Module / function | Previous behavior | Corrected behavior |
|---|---|---|---|
| Missing morning context after a late start | `live_stream.run`, `session_bootstrap.prepare_session_repair` | Indicators started from the first observed afternoon tick | Restore today's completed 09:15-onward candles before entry readiness; keep protection processing available for recovered positions |
| Partial first minute and history overlap | `CandleBuilder.on_tick`, `seed_history` | First observed fragment could be treated as a complete minute | Discard first connection fragment, request authoritative missing completed minutes, replace overlapping rows rather than adding their volume |
| Premature volatility collapse | `SymbolState.record_periodic_atr` | Two immature readings could trigger STANDBY | Separate BOOTSTRAPPING/WARMING_UP/READY from UNKNOWN/ACTIVE/STANDBY; confirmations begin after the configured 15 completed candles |
| Weak history validation | `historical_data.validate_history` | Missing timestamps, duplicates, NaNs and wrong requested days could pass | Validate identity context, timestamp/date/timeframe/session bounds, future/partial bars, chronology, finite OHLCV, price shape and coverage |
| Repeated history requests and local-only throttling | `HistoryService`, `SharedHistoryBudget`, production pipeline and backtest fetcher | Independent runs re-fetched the same sessions; retries consumed quota | Revalidate persistent session cache on each read; serialize request starts across processes; shared cooldown and bounded priority queue |
| Starved or incomplete RVOL baselines | `run_premarket_screener`, `build_volume_profile`, `same_time_rvol` | Fetch many days for one stock before moving to another; missing minutes can understate historical cumulative volume | Round-robin across primary and reserve stocks to the minimum baseline; require all 375 historical minutes for a profile; optional extras wait for every minimum; duplicate dates cannot inflate sample count |
| Fixed prior-day watchlist | `reserve_watchlist.promote_reserves` | No monitored alternative when all primary stocks became quiet | Three primary plus at most three reserves; promote only after current-session confirmations and cooldown, retaining risk state |
| Signals hidden by early permission returns | `observe_signal`, live orchestrator | STANDBY/cutoff could hide the strategy's output behind `SYMBOL_NOT_ACTIVE` | Evaluate signal and independent gates; record every blocker, model economics and available quote/depth even when execution is denied |
| Repeated rejection noise | `OpportunityTelemetry.record` | Repeated identical terminal messages dominated logs | Persist changed decisions and per-bar rejection reasons; suppress unchanged terminal output and provide aggregates |
| Slippage settings coupled to fills/order limits | `PaperExecutionAdapter`, `SafeTrader.execute_trade`, `estimate_trade_economics` | Economic haircut also controlled simulated fill adjustment and submitted limit | Independent fill and order-limit assumptions; model haircut affects economics/sizing only; actual fills remain accounting truth |
| Mixed runs and duplicate regular processes | `RunContext`, `RegularInstanceLock` | Shared log and no regular-process guard | Unique run directories, code/config/strategy hashes, stage timings, and OS-backed single-instance lock |
| Reconnect/restart exposure | live recovery worker and constructor | Missing history and a newly selected watchlist could leave old context/subscriptions incomplete | Repair only missing completed ranges; retain a protection-only subscription for an existing position within the subscription cap |
| Research could be confused with production evidence | research policy/harness and shadow diagnostics | Limited separation and metrics | Explicit named policies, disjoint development/held-out dates, isolated replay journals and shadow excursions with zero credited production P&L |

Baseline before editing: **338 passing tests**. Added defect tests first: **5 failed, 1 passed**, demonstrating the original validation gaps. See `runtime_repair_initial_failures.txt` and `runtime_repair_baseline_2026-10-01.json`.

## B. FILES MODIFIED

Application paths below are relative to `algo-trading-bot/`.

| File | Purpose / important functions |
|---|---|
| `historical_data.py` — new | `HistoryContext`, `validate_history`, normalized source/completeness metadata |
| `session_bootstrap.py` — new | `missing_ranges`, `prepare_session_repair`, `commit_session_repair` |
| `history_service.py` — new | Validated cache, single-flight session locks, shared priority/pacing budget, bounded retries |
| `runtime_observation.py` — new | `SignalObservation`, `observe_signal`, rejection/quote persistence and funnel counters |
| `reserve_watchlist.py` — new | Current-session confirmation, bounded promotion, hysteresis/cooldown |
| `run_context.py` — new | Run identity, lifecycle timings, regular lock, readiness and session summaries |
| `research_policy.py` — new | Explicit immutable research policies and independent volatility state |
| `research_harness.py` — new | Manifest-driven development/held-out comparisons, metrics and no automatic promotion |
| `shadow_diagnostics.py` — new | Denied-signal observations and post-session excursions, without order access |
| `candle_builder.py` | Strict live session mode, history merge, first-fragment handling, gap flags, source metadata |
| `symbol_state.py` | Maturity, volatility, reserve role and independent completed-bar confirmations |
| `atr_firewall.py` | Reject nonfinite ATR input; reduce repeated low-ATR logging |
| `live_stream.py` | Bootstrap/recovery integration, observation-before-permission, reserves, retained exposure, shared authenticated session and run context |
| `premarket_pipeline.py` | Shared service by default, stage timings, API metrics and reserve reporting |
| `premarket_screener.py` | Strict fetch validation, fair RVOL rounds, bounded reserves |
| `premarket_check.py` | Isolated read-only run identity, shared validated history cache and budget |
| `opportunity_engine.py` | Configured minimum RVOL sessions; unique dated, complete-session samples |
| `execution_safety.py` | Separate modeled entry slippage, adverse tick rounding and already-filled entry accounting |
| `execution_adapters.py` | Independent paper-fill slippage assumption |
| `safe_trader.py` | Independent order-limit allowance, unchanged reference stop/target geometry, actual-fill projections and run-tagged events |
| `replay_engine.py` | Explicit research policy, causal cutoff time, additional performance and slippage-sensitivity metrics |
| `backtest_engine.py` | Shared validated history service for broker downloads; reject unordered replay inputs |
| `config.py` | Infrastructure defaults listed in section D |
| `test_runtime_repair.py` — new | 44 focused regression cases |
| `test_discovery_repair.py` | Explicit injection of the legacy deterministic adapter for its existing pacing test |
| `test_discovery_startup.py` | Assert three primary plus three reserve subscriptions; explicit legacy adapter fixture |
| `test_phase5_multisymbol.py` | Explicit already-restored session and correct dated identity in routing fixtures |

`scripts/runtime_repair_evidence.py` generates offline evidence in `docs/runtime_repair_engineering_evidence.json`. `scripts/runtime_repair_research_check.py` collects read-only research history, preserves the original development/held-out split and reports inadequate coverage without inventing performance results. Its `--evaluate-only` mode uses saved files without broker authentication or networking. The remaining `docs/runtime_repair_*` files contain baseline, regression, provider-scan, bootstrap, research-coverage and replay evidence. Original October 1 candle/log audit artifacts are preserved.

## C. FILES INTENTIONALLY NOT MODIFIED

**`signal_brain.py` remains byte-for-byte unchanged.** Its SHA-256 before and after is:

```text
bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83
```

The VWAP signal rules, LONG/SHORT formulas, daily bias and signal-level ATR threshold remain frozen. `execution_engine.py`, the legacy position-management formulas, `feed_integrity.py`, `safety_journal.py`, `market_schedule.py`, the instrument registry and dynamic NSE universe/discovery logic are unchanged.

Reference stop/target geometry remains `distance = round(2 × ATR, 2)`, stop at VWAP minus/plus that distance, and target at VWAP plus/minus twice that distance. No threshold was lowered to admit October 1 patterns.

The existing PAPER ledger was checked read-only after validation: **0 trades, 0 fills, 0 attempts, 0 loss consumed and 0 open reservations** for the relevant session. Test/research activity did not create production-paper profit.

## D. CONFIGURATION CHANGES

| Setting | Previous | New | Effect |
|---|---|---|---|
| `ATR_RECHECK_INTERVAL_SECONDS` | 1800, misleading comment | 60, documented completed-bar cadence | Describes actual one-minute processing; does not alter the ATR floor |
| `HISTORY_CACHE_DIR` | No historical cache | `None` → `data/cache/history` | Shared validated session cache |
| `HISTORY_REQUEST_INTERVAL_SECONDS` | Per-process 1.1 s | Shared minimum 1.5 s | Conservative pacing across regular/check/research history consumers |
| `HISTORY_REQUESTS_PER_MINUTE` | No shared window | 40 | Additional local safety budget, not a claim about the broker's advertised allowance |
| `HISTORY_REQUESTS_PER_HOUR` | No shared window | 1000 | Shared rolling-hour cap |
| `HISTORY_RECOVERY_RETRY_SECONDS` | No recovery worker | 30 | Bounded retry interval after incomplete session recovery |
| `HISTORY_MAX_REPAIR_RANGES` | No gap bound | 8 | Highly fragmented data blocks instead of causing a request storm |
| `OPPORTUNITY_RVOL_MIN_SESSIONS` | Hardcoded 3 | Configured 3 | Same minimum, unique prior sessions |
| `RESERVE_WATCHLIST_SIZE` | 0 | 3 | At most six monitored stocks including retained exposure |
| `RESERVE_CONFIRMATION_CANDLES` | None | 2 | Require separate qualifying closed bars |
| `RESERVE_PROMOTION_COOLDOWN_SECONDS` | None | 120 | Limit rotation churn |
| `REJECTION_LOG_INTERVAL_SECONDS` | No suppression | 60 | Periodic terminal summaries while durable decisions remain available |
| `PAPER_FILL_SLIPPAGE_PCT` | Reused economic haircut | Independent 0.0005 | Preserve the existing 5 bps paper-fill assumption without coupling it to model experiments |
| `ORDER_LIMIT_ALLOWANCE_PCT` | Derived from modeled entry | Independent 0.0005 | Keep submitted price tolerance independent of the economic haircut |
| `SHADOW_RESEARCH_ENABLED` | No runtime shadow recorder | `True`, PAPER only | Separate observations/excursions, zero credited profit |

Unchanged: PAPER mode, ₹20,000 total capital, ₹10,000 working capital, ₹10,000 backup, ₹100 planned risk per setup, ₹200 daily loss budget, two setup attempts, one open position, 15-bar warmup, 0.40% live ATR floor, 0.35% standby trigger, 0.40% recovery threshold, minimum net profit/net R:R, stop/target formulas, cutoff and EOD safeguards. Planned risk caps cannot guarantee an exact realised loss under every fill or market gap.

The old 1.1-second counter remains only as an explicitly injected compatibility fixture. Production pipeline, read-only check, runtime recovery and broker research downloads use the shared history service. `--fresh` refreshes master/NSE discovery files; valid historical cache entries remain reusable.

## E. TEST RESULTS

Final full suite: **382 total, 382 passed, 0 failed, 0 skipped**, completed in 12.37 seconds.

| Focused group | Passed |
|---|---:|
| New runtime repair regressions | 44 |
| Market discovery, startup, discovery repair and screening | 106 |
| Orchestration, feed integrity, ATR firewall and multiple-symbol isolation | 29 |
| Fill accounting, execution safety, broker safety, recovery and capital synchronization | 63 |
| Pipeline, integration and existing strategy suite | 107 |
| Activation, audit and execution-mode isolation | 33 |

Evidence: `runtime_repair_tests.txt` and machine-readable `runtime_repair_tests.xml`.

The new cases exercise strict bad-data rejection, 13:22 bootstrap, first-minute discard, overlap replacement, reconnect-only gap fetches, day-boundary VWAP, mature ATR transitions, shared cache validation, real subprocess request serialization and instance locking, empty-response handling, retry backoff, fair RVOL, incomplete-volume-profile rejection, reserve confirmation, visible blocked signals, exits during recovery, authenticated-session reuse, retained position subscriptions, research separation, missing-split reporting and fill-ledger accounting.

The tests use temporary TEST/REPLAY journals. Separate read-only checks against Angel One/NSE are described below. A full regular PAPER session with the repaired websocket runtime has **not** yet been observed during an open market.

Re-run from the repository root:

```sh
.venv/bin/python -m pytest -q algo-trading-bot
.venv/bin/python scripts/runtime_repair_evidence.py
```

## F. OCT-01 REPLAY RESULT

**ZERO ELIGIBLE ENTRIES under the unchanged production volatility policy.**

| Recorded symbol | Observed candles | Bias-allowed patterns before cutoff | Maximum observed ATR% | Eligible entries |
|---|---:|---:|---:|---:|
| RSYSTEMS | 97 | 4 | 0.389858% | 0 |
| RITES | 97 | 3 | 0.336171% | 0 |
| ELEVATE | 97 | 3 | 0.367931% | 0 |

Required live ATR remains **0.400000%**. This replay uses the supplied, rounded afternoon OHLCV log and has no original historical bid/ask/depth. It validates the regression; it does not reconstruct missing morning information or prove what a fully initialized bot would have earned.

Evidence: `runtime_repair_oct01_replay.json` and the automated October 1 regression test.

## G. STARTUP SIMULATION

Both a deterministic fixture and an actual read-only provider-history probe tested a startup as of **2026-10-01 13:22:30 IST**. Each selected stock restored exactly **247 completed bars, 09:15 through 13:21**, with no missing timestamps, before its data status became READY.

| Stock | Actual restored bars | Full-session VWAP at 13:21 | Data status |
|---|---:|---:|---|
| RSYSTEMS | 247 | ₹265.195278 | READY |
| RITES | 247 | ₹210.524303 | READY |
| ELEVATE | 247 | ₹340.007981 | READY |

The provider probe was performed after the session using actual historical data and an explicit as-of cutoff. It made **3 historical requests** and started **no trading engine**. Data readiness does not override signal, feed, volatility, quote, economics, risk or time gates.

The separate boundary regression starts ticks at 13:22:30, discards the partial 13:22 minute, restores its authoritative completed candle, and verifies that repeated history merges neither duplicate rows nor double their volume.

Evidence: `runtime_repair_provider_bootstrap.json` and `runtime_repair_engineering_evidence.json`.

## H. API BUDGET RESULT

These are **observed read-only provider runs**, except the final explicitly synthetic row:

| Run | Historical requests | Rate-limit responses | Cache hits | Outcome |
|---|---:|---:|---:|---|
| Original October 1 regular trading startup | 95 | 48 | No validated historical cache | 41 of 46 candidates had valid data |
| Repaired fresh discovery check | 73 | 0 | 0 | All 46 candidates had valid screening data; optional RVOL time budget expired |
| Repaired repeat check, before final complete-RVOL validation | 9 | 0 | 56 | Screening history reused; nine empty older sessions remained unavailable |
| Final check with complete-RVOL validation | 23 | 0 | 56 | All 46 candidates had valid screening data; incomplete cumulative-volume baselines stayed unknown |
| Actual 13:22 bootstrap verification | 3 | 0 | 0 | All three current-session prefixes complete |
| Synthetic two-client cache regression | 9 cold, 0 additional warm | 0 | 9 warm | Identical validated datasets reused |

The fresh check took approximately **141 seconds**; the earlier repeat check approximately **41 seconds**; the final check approximately **62 seconds**, including pacing and screening overhead. They are not identical workloads to the old run: the repaired system also prepares reserves, and provider availability can change.

The initial repaired cold check still retried empty provider sessions. The final implementation classifies a successful-but-empty session as unavailable, performs no pointless retry for it, and does not cache it as valid data. The final check had **9 empty sessions, 23 total requests, no retries and no rate-limit responses**. Its additional calls sought complete minimum RVOL baselines rather than assuming sparse history was complete.

Actual discovery: **141,994 master records → 1,580 eligible NSE cash shares → 46 deep-screen candidates → 7 qualifiers → 3 primary + 3 reserves**. Snapshot coverage was 99.8734%. Primary: RSYSTEMS, RITES, ELEVATE. Reserves: GLASSWALL, AEQUS, JWL. `configured_stock_list_used=false`; no 12- or 15-stock fallback.

The final check requires every RVOL profile to contain all 375 completed minutes. Complete-profile counts were **RSYSTEMS 3, RITES 1, ELEVATE 0, GLASSWALL 3, AEQUS 3 and JWL 2**. RITES, ELEVATE and JWL therefore report `INSUFFICIENT_HISTORY`. The earlier repeat artifact predates this stricter rule and must not be used as the final RVOL-readiness result. Valid prior-day price/ATR screening data can retain a watchlist while cumulative-volume history remains insufficient; `DYNAMIC_DISCOVERY_READY` does not mean every stock has permission to enter.

Evidence: `runtime_repair_readonly_scan.json`, `runtime_repair_warm_scan.json`, `runtime_repair_final_scan.json`, and their logs. Full per-instrument exclusion audits are preserved under `algo-trading-bot/data/paper/validation_archive/`; the concise reports contain their paths and SHA-256 hashes. The final read-only scan completed successfully after an earlier approval-review usage limit cleared.

## I. OPPORTUNITY FUNNEL DEMONSTRATION

The offline evidence generator processes a real recorded October 1 BUY pattern using an explicitly hypothetical test quote. Its output separates the observed pattern from permission:

```json
{
  "symbol": "RSYSTEMS",
  "side": "BUY",
  "signal_generated": true,
  "executable": false,
  "blocking_reasons": ["VOLATILITY_STANDBY", "ATR_BELOW_LIVE_MINIMUM"],
  "production_orders": 0,
  "production_profit_credited": 0
}
```

This is a shortened illustration; the evidence JSON contains the complete gate list, including any additional economic blocker, reference prices, test quote, expected quantity when calculable and gate counters. The original October 1 log did not contain executable order-book history, so the test quote is explicitly labeled hypothetical.

Every regular run now writes `identity.json`, `lifecycle.json`, `runtime.log`, `readiness.json`, and `session_summary.json` to `algo-trading-bot/data/paper/runs/<run-id>/`. The summary includes discovery/qualification/monitoring counts, unique completed-bar observations, potential and executable signals, liquidity/economic/risk gate percentages, orders, entry fills, profitable closed trades, rejections, API/cache statistics, promotions, feed interruptions, exposure and realised drawdown.

Gate counts can overlap; the same opportunity may fail ATR and economics. Symbol counts and signal counts have distinct denominators. Day-ledger financial results are explicitly distinguished from this run's telemetry. Shadow results are saved separately with zero credited P&L. A flat completed-trade session is labeled FLAT rather than falsely called NO_TRADE.

## J. ACCOUNTING INTEGRITY

The synthetic separation example produces:

| Meaning | Value |
|---|---:|
| Strategy VWAP/reference | ₹300.00 |
| Unchanged reference stop / target | ₹290.00 / ₹320.00 |
| Economic model entry with an explicit 15 bps haircut | ₹300.55 |
| Independent paper fill with the configured 5 bps assumption | ₹300.25 |

The regression verifies that changing the economic haircut cannot change the paper adapter's fill or rewrite reference stop/target prices. Submitted limits use their own allowance. Sizing may change, as it should when modeled risk/cost changes.

Confirmed simulated fills drive gross P&L, quantities and fees in the journal. Net P&L is fill-based gross P&L minus recorded charges. A slippage diagnostic is **not subtracted again** after its effect is already included in fill prices. Post-fill projections use the confirmed entry directly, without applying another entry haircut.

Published standard Angel One intraday brokerage remains consistent with the existing model's lower-of-₹20-or-0.1%, minimum-₹5 assumption. Account-specific billed fees are not verified by these tests. [Angel One brokerage support](https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges).

All provider validation was read-only and submitted zero orders. Angel One's FAQ describes SmartAPI, including historical data, as free; this does not speak for unrelated account charges. [SmartAPI FAQ](https://smartapi.angelone.in/faq).

## K. REMAINING RISKS

- **Strategy risk:** no positive expectancy has been proved. A valid signal can lose, and the next session can legitimately contain no trade. Small desired profit does not make an entry certain or cost-free.
- **Market risk:** volatility, liquidity, gaps and price movement can change faster than the bot's next observation. The fixed production thresholds remain enforced.
- **Fill uncertainty:** paper fills and candle-path replay are models. Queue priority, hidden liquidity, real slippage and historical depth are not established by OHLCV alone.
- **Data-provider risk:** missing or revised bars, empty old sessions, authentication failures, downtime and rate limits can still occur. Incomplete current-session history blocks entries; the system retains valid screening results when only optional enrichment is missing.
- **Research data limit:** an actual read-only collection requested **20 trading dates × 2 stocks = 40 stock sessions**. Only **4 cases across 3 dates** contained complete minute data; **36 were incomplete**. All accepted cases fell in the held-out portion, leaving **0 development cases**. The original 12-date development / 8-date held-out allocation was preserved. Evaluation reports `BLOCKED_INCOMPLETE_RESEARCH_COVERAGE`, with no policy performance results. See `runtime_repair_research_evaluation.json`; `--evaluate-only` now reproduces this structured result without crashing or changing the split.
- **Overfitting risk:** the harness supports named policies and disjoint development/held-out sessions, but broad testing across independently classified trending/ranging/high-/low-volatility market regimes still requires complete data. The attempted collection uses an ex-post fixed RSYSTEMS/RITES basket and current instrument metadata; it cannot establish an unbiased stock-picker edge or historical token continuity. No experimental threshold was promoted into production and no multi-session profitability claim is made.
- **Operational validation:** actual provider discovery/cache/bootstrap reads succeeded, and all automated regressions pass. A complete next open-market PAPER run of the repaired streaming integration remains to be observed. The local shared budget cannot coordinate unrelated applications on another machine using the same account.

For the next open-market PAPER session, start one regular process before the open, allowing time for discovery:

```sh
cd "/Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot"
../.venv/bin/python -u live_stream.py
```

The bot selects candidates automatically, restores today's history when needed, subscribes to its bounded watchlist, and reports readiness and blockers. Only a setup passing all gates can become a simulated order. PAPER P&L appears in the existing paper ledger/report and the run's `session_summary.json`; it is not a credit to the live Angel One account.
