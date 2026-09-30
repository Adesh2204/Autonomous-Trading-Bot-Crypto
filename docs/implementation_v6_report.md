# Trading infrastructure v6 — engineering report

Date: 30 September 2026. Intended first observation session: 1 October 2026.

**Recommendation: PAPER_ONLY. Live execution: BLOCKED.** The implementation is complete for local paper observation and offline validation. It is not a profitability certification or an approval to use real money. No real broker order, broker login, instrument refresh or real historical profitability run was performed during this implementation.

The complete suite passed: **244 passed, 0 failed, 0 skipped**. The strategy file is unchanged. A separate, explicit capital protection layer can exit a position when its rupee risk allowance is breached; the original strategy stop remains a candle-close rule.

## A. Repository identity verified

- Workspace: /Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot.
- Origin: [Adesh2204/Autonomous-Trading-Bot](https://github.com/Adesh2204/Autonomous-Trading-Bot).
- Branch: main.
- Baseline commit: 58cf214fc71263da15371d7aed22bc977e21c4f8.
- Implementation is in the working tree. No commit, push, pull request, deployment or live activation was performed.

The earlier assessment remains available in [trading_readiness_2026-09-30.md](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/trading_readiness_2026-09-30.md>). This report supersedes its implementation recommendations with the current code and test results.

## B. Current architecture discovered

The original production path ran from SmartAPI ticks through a queue, per-symbol CandleBuilder, signal_brain, watchlist orchestration and PaperTrader. Execution and bookkeeping were mixed with three-tranche allocation, multiple order helpers and recovery routines. Historical replay separately simulated fills.

The new production path is:

    Verified master + broker intraday eligibility
        → historical screening and top-N selection
        → immutable identity in each SymbolState
        → real timestamp, bid/ask, depth and cumulative-volume ticks
        → unchanged 60-second CandleBuilder
        → unchanged signal_brain and daily bias
        → execution quality, economic sizing and deterministic arbitration
        → SafeTrader reservation and state machine
        → paper adapter or separately gated broker adapter
        → confirmed fills, independent capital protection, reconciliation
        → durable SQLite journal, CSV projection and session report

Public PaperTrader and ExecutionEngine imports resolve to SafeTrader. LegacyPaperTrader supplies the existing management mathematics. Its entry, scaling and accounting methods are retired. A production search found one broker placeOrder call site, in the broker adapter.

## C. Root causes confirmed

1. Downstream token reconstruction could diverge from the symbol chosen by the screener.
2. Theoretical VWAP entry and stop-price fills could misstate execution and profitability.
3. Capital fractions and gross stop distance did not reliably constrain complete net risk.
4. A net daily P&L check could allow profits to hide accumulated losses or unreserved exposure.
5. Partial fills, unconfirmed cancellations and ambiguous transport failures required stronger ownership and recovery rules.
6. Pyramiding and the single-tranche initialization path conflicted with the ₹20,000 pilot policy.
7. Bullish-only pre-selection excluded otherwise valid short opportunities.
8. Several paths relied on obsolete timing, fallback identities, order assumptions or synthetic-history behavior.
9. Restart could erase the cooldown or the candle count used by the 15-bar breakeven rule.
10. A protection order near the strategy stop could interrupt wick immunity. Protection now uses an independently calculated capital-loss boundary.
11. Additional adversarial tests exposed invalid numeric values, duplicate fills, cross-environment CSV reuse, missing journals and persistence failure after a fill.

## D. Files modified and change-management record

In the tables below, “core preserved” means signal_brain and its parameters are untouched. Infrastructure can reject an entry, reduce quantity, halt execution or request a capital emergency exit. Those changes are intentional and visible.

### Existing runtime files

| File / affected functions | Why and before → after | Core impact / new failure modes | Verification |
|---|---|---|---|
| [config.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/config.py>) — policy assignments | Daily allowance ₹400 → ₹200; timing → 14:30/15:00; added execution, fee, freshness and activation settings | Core EMA, ATR, VWAP, signal and economic-floor parameters preserved. Missing or expired evidence blocks live execution | Capital, timing and activation tests |
| [execution_engine.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/execution_engine.py>) — fee helpers, constructor logging, execute_trade, tranche methods, close_position, place_live_order, module __getattr__ | Duplicate financial execution paths → disabled legacy paths and a SafeTrader export; fee calculations → central FeeModel | Five management methods preserved verbatim. Unsupported legacy entry/scaling/accounting calls now raise a clear error | Entire suite; source comparison; direct-order bypass tests |
| [live_stream.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/live_stream.py>) — constructor, timestamp/tick extraction, consumer, orchestrator, reconnect, lifecycle, startup/reporting | Fallback identities and incomplete quote context → registry identities, real depth/volume, causal signals and deterministic selection | Core generation and bias preserved. Opposite signals close before replacement entry gates. Stale data and uncertain broker state block trading | Multi-symbol, tick, arbitration, flip, cutoff and report tests |
| [market_schedule.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/market_schedule.py>) — NSE timing properties | Embedded 15:15/15:20 policy → configured 14:30/15:00 | Lifecycle timing changes only; NYSE provider remains supported | Schedule and cutoff regressions |
| [feed_integrity.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/feed_integrity.py>) — RawTick and enqueue | Tick lacked quantities and cumulative-volume context → carries both | No indicator formula changes. Missing depth cannot be assumed executable | Feed and stream ingestion tests |
| [symbol_state.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/symbol_state.py>) — SymbolState fields | Symbol state lacked authoritative instrument/quote/profile context → carries identity, quote, score and volume history | No signal change. An unverified identity cannot reach execution | Isolation and integration tests |
| [premarket_screener.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/premarket_screener.py>) — evaluate_candidate, run_premarket_screener | Bullish selection and volatility-only ordering → direction-neutral selection, component scores and prior-session profiles for selected symbols | ATR floor preserved. Historical screening is preliminary: executable spread/depth are checked again live. Extra history calls can fail or be paced | Bearish qualification, unchanged ATR rejection and top-N tests |
| [backtest_engine.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/backtest_engine.py>) — run_backtest, historical fetch/run, CLI; removed synthetic fallback generator | Independent optimistic simulation → explicit replay with required mapping/provenance and populated metrics | Production timeframe unchanged. Research aggregation is separately identified. Legacy parameter overrides and missing metadata now fail | Causal replay, provenance, history guard and CLI help checks |

### New runtime and support files

| File / functions | Why and resulting behavior | Core impact / failure modes | Verification |
|---|---|---|---|
| [execution_safety.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/execution_safety.py>) — identity/quote validation, FeeModel, estimate_trade_economics, solve_quantity, capital_protection_prices | Centralizes identity, executable quality, costs, integer sizing and the independent rupee-loss boundary | Execution only. Invalid data, no valid integer quantity or exhausted capital risk reject the action | Risk, cost, gap, numeric and protection tests |
| [execution_adapters.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/execution_adapters.py>) — FillResult, capabilities, execute, read_fill, protect, cancel, snapshot | Distinguishes paper observations from broker-confirmed fills; supports LIMIT and STOPLOSS_LIMIT and terminal cancellation checks | No core math changes. Timeout/unknown response never becomes an assumed fill. Stop-limit orders can remain unfilled through a gap | Broker mock, partial fill, rejection, cancellation, identity and protection tests |
| [safe_trader.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/safe_trader.py>) — execution/state transitions, storage failure handling, persistence, capital protection, close, reconciliation, reporting | Coordinates durable risk approval, actual quantities, fills, recovery and accounting | No scaling. Capital emergency exits are explicitly separate from candle-close strategy stops. Uncertain exposure halts entries and may require an operator | All new safety and integration cases |
| [safety_journal.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/safety_journal.py>) — reserve, finish, record_fill, metadata and report | Persists losses, attempts, reservations, fills, inventory and management state; prevents duplicate accounting | No core math. Environment mismatch, orphaned CSV or conflicting fill fails closed. SQLite remains the authoritative ledger | Restart, atomic attempt limit, duplicate, environment and persistence tests |
| [instrument_registry.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/instrument_registry.py>) — construction, load, resolve, candidates | Resolves a complete identity once from a master and eligible universe | No guessed token. Duplicate, stale, invalid or unavailable mappings block execution | Registry and wrong-token tests |
| [refresh_instruments.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/refresh_instruments.py>) — refresh_registry | Read-only refresh of the published master and broker intraday list, followed by atomic cache replacement | Cannot place orders. Missing authenticated eligibility blocks discovery; additional surveillance restrictions need verification | Integration contract inspection; no real refresh performed |
| [opportunity_engine.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/opportunity_engine.py>) — profile construction, same_time_rvol, scoring, arbitration | Uses prior sessions at the same clock time; exposes component scores and stable tie-breaks | Does not generate signals or lower filters. Insufficient dated history leaves RVOL unknown | RVOL and arbitration tests |
| [replay_engine.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/replay_engine.py>) — replay, ResearchVariant, research_metrics, rejected_opportunity_outcomes | Separates research outputs, queues signals for the next observation and records assumptions/provenance | No production timeframe change. OHLCV cannot establish real bid/ask, depth or intrabar sequencing; results are research only | A fixture with a genuine core signal produces a next-observation trade; future-bar volume is excluded from entry sizing |
| [activation_gate.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/activation_gate.py>) — source_fingerprint, validate_activation | Flags alone cannot activate live execution; dated evidence must match source, P0 tests and broker checks | No strategy effect. Missing, stale, mismatched or incomplete approval evidence blocks live execution | Seven activation tests |
| [security_logging.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/security_logging.py>) — secret filter installation | Redacts sensitive broker login/authentication messages | No trading effect. Critical trading events still use local logs; external alert delivery was not configured | Redaction test |
| [safety_test_support.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/safety_test_support.py>) — ScenarioBroker and paper/live fixture factories | Provides deterministic offline broker states and explicitly marked mock activation evidence | Test-only fixtures never authenticate a real account. Mock approvals are not account verification | Recovery, mode and lifecycle tests |

### Test files

The existing tests remain collected. Financial contracts that asserted forbidden behavior were migrated to explicit identity/quote/fill fixtures and safety assertions. No failing test was skipped or marked as expected to fail.

| File | Contract revised or coverage added |
|---|---|
| [test_capital_sync.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_capital_sync.py>) | One working-capital ceiling and net-risk sizing replace three allocation targets |
| [test_disaster_recovery.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_disaster_recovery.py>) | Confirmed partial fills, rejected orders, unknown submissions/exits, blocked duplicate orders and broker exposure recovery |
| [test_mode_isolation.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_mode_isolation.py>) | Paper cannot call the broker order API; mocked broker quantities/prices drive live-path accounting |
| [test_phase5_multisymbol.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_phase5_multisymbol.py>) | Verified registry fixtures and executable quotes; standby test asserts another symbol is actually selected |
| [test_pipeline.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_pipeline.py>) | One-position policy, original stop/target/management behavior, actual quotes, new ledger and updated lifecycle |
| [test_screener.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_screener.py>) | Valid bearish structure can qualify without changing the ATR floor |
| [test_suite.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_suite.py>) | Replaces blind order and recovery assumptions with explicit confirmed/unknown states |
| [test_safety_v6.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_safety_v6.py>) | The required capital, wrong-token, paper fill, stop gap, daily risk, duplicate and freeze regressions |
| [test_broker_safety_v6.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_broker_safety_v6.py>) | Partial entry/exit, correct protection quantity, rejection, failure unwind and actual flatten behavior |
| [test_integration_v6.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_integration_v6.py>) | Master, fee/management parity, tick depth/volume, replay causality and zero-trade reporting |
| [test_audit_v6.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_audit_v6.py>) | Numeric corruption, durable halts, atomic attempts, drawdown, restart counters, capital protection, ledger isolation and persistence failure |
| [test_orchestration_safety_v6.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_orchestration_safety_v6.py>) | Duplicate/stale bars and direction-flip exits before replacement gates, including after cutoff |
| [test_activation_v6.py](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/test_activation_v6.py>) | Flags-only, expired, changed-source, failed-test, missing-broker-check and PAPER_ONLY approvals cannot activate |

The [function-change inventory](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/validation_v6_function_changes.json>) lists changed, added and removed functions precisely. The documentation and validation artifacts add no runtime behavior.

## E. Exact architectural changes

Entries follow SIGNAL_CREATED → ECONOMICALLY_VALIDATED → RISK_APPROVED → ORDER_SUBMITTED → acknowledgement → FILLED or PARTIALLY_FILLED → PROTECTION_CONFIRMED → POSITION_OPEN.

Exits follow EXIT_REQUESTED → PARTIALLY_EXITED or POSITION_CLOSED → BROKER_RECONCILED → ACCOUNTED. Failure states and reasons are journaled. Known partial exits can continue using the confirmed remainder. Ambiguous orders are quarantined instead of resubmitted blindly.

Broker acknowledgement identifiers are persisted before fill polling. Transport failure without a trustworthy identifier remains unknown. Old direct-order helpers cannot bypass the engine's reservation and economic checks.

A database failure after a confirmed entry immediately halts execution. Known exposure is retained for recovery; protection is attempted only against that confirmed exposure, with a broker quantity check in live mode. No successful accounting row is fabricated.

## F. Risk-engine implementation

| Rule | Enforced policy |
|---|---:|
| Total capital | ₹20,000 |
| Working capital ceiling | ₹10,000 |
| Reserve | ₹10,000 |
| Planned complete setup risk ceiling | ₹100 |
| Daily cumulative realized loss allowance | ₹200 |
| New setup attempts per market day | 2 |
| Concurrent positions | 1 |
| Scale-in | Disabled |
| Entry cutoff | 14:30 IST |
| Flatten begins | 15:00 IST |

Remaining daily allowance is:

    ₹200 − cumulative realized losses − pending reservations − open reservations

The same reservation moves from pending to open; it is counted once. A full approved setup allowance is reserved, conservatively covering the capital protection boundary. The report separately shows pending-order risk and open risk.

Winning trades do not subtract from cumulative losses, replenish the allowance or increase the working ceiling. The attempt limit and one-reservation constraint are enforced within a database transaction, including when a caller's earlier check becomes stale.

These are entry-approval and emergency-control limits. Gaps, liquidity failures, an unfilled protective limit or infrastructure outage can still produce an actual loss exceeding the planned ₹100/₹200 allowance. A realized setup breach causes a durable halt.

## G. Quantity-solving implementation

The solver searches downward through valid integer lots, beginning at the lesser of cash capacity and visible-depth participation capacity. It returns the largest quantity satisfying all checks.

Cash includes entry fees and a ₹20 buffer. Risk includes adverse executable entry, adverse exit slippage, conservative exit spread, tick rounding and fees. Net target profit must be at least ₹5; existing normal/low-volatility R:R floors remain 1.2/0.8.

Bid/ask already includes entry spread. It is not charged again as an entry spread adjustment. Exit spread is separately modeled. Slippage changes execution estimates and cash/risk calculations; it does not change the signal, ATR multiplier or strategy price levels.

After a fill, the actual price, quantity and reported/estimated fees are checked again. A partial fill that violates risk or net economics is a safety event, not permission to weaken the floors.

## H. Instrument-routing fix

InstrumentIdentity carries symbol, exchange, token, trading symbol, series, tick size, lot size, instrument type, source timestamp and intraday eligibility. Production selection, feed subscription, execution and ledger use this object.

Wrong supplied tokens, mismatched trading symbols, duplicate identities, stale masters and unavailable eligibility fail closed. Existing live inventory can be exited using its verified broker tuple without requiring a refreshed master to fabricate a new identity.

Literal identities such as JIOFIN/18143 in tests are deterministic fixtures, not a current broker-master certification. Production obtains its identities from the refreshed source.

## I. Fill-accounting fix

Paper entry uses observed ask for BUY and bid for SELL, with adverse slippage and tick rounding. It cannot fill an earlier ₹300 VWAP when the executable observation is ₹303.

A stop price is a trigger, not an exit fill. A ₹290 stop followed by an executable ₹285 observation records an adverse observed fill when execution succeeds.

Broker quantities and average prices are read from confirmed terminal order reports. Partial entry protection and accounting use the actual filled quantity. Partial exits accumulate their own order fees; the final exit price is quantity-weighted.

Gross P&L uses actual entry and exit fill prices. Net P&L subtracts entry and exit charges. Broker charge fields are identified as BROKER; otherwise fees are explicitly ESTIMATED_STANDARD. Live net P&L remains provisional until the contract note is matched. No contract note was provided or verified here.

SQLite owns the ledger. CSV is an atomic projection. Fill IDs and trade UUIDs prevent duplicate insertion/accounting. TEST, BACKTEST, REPLAY, PAPER, SHADOW and LIVE journals cannot be silently reused across environments. Existing legacy CSV files were not rewritten.

## J. Protection architecture

The strategy stop remains anchored to VWAP and ATR, with the existing candle-close evaluation and 15-bar price-breakeven rule. Price breakeven can still lose fees.

Broker protection is a separate **CAPITAL_LOSS_LIMIT** order. Its trigger/limit are derived from actual entry, actual quantity, entry costs, realized partial exit losses and the reserved rupee allowance. It is not a mechanical conversion of the strategy stop into an intrabar stop.

Paper observes the same separate capital emergency. A wick through the strategy stop can remain open while capital risk is within its allowance; exceeding the capital boundary requests an explicitly labeled Capital Protection Emergency and halts new entries.

Protection must be acknowledged for the correct identity and actual quantity. Failure requests an emergency unwind. A known partial exit restores protection for the remainder where the remaining budget allows it.

Stop-limit orders can fail to fill through a gap. The live quote/lifecycle watchdog requests liquidation and verifies broker state; it cannot guarantee a price or fill. This architecture requires observed broker verification before real-money use.

## K. Reconciliation architecture

Reconciliation runs at startup, reconnect, before entry, after entry, before exit and at EOD. Signed broker quantity, identity, exchange, product and pending orders are compared with local state.

A broker position with no valid local strategy snapshot is preserved as recovered exposure and blocks new entries. The bot does not invent a VWAP, stop, target or fill price for it. Restoration of daily loss/attempt budgets, pending reservations, cooldown and breakeven candle count is tested.

A flat position book alone does not justify invented exit P&L when the exit fill is unknown. Ambiguous submission or closure remains quarantined.

Flattening cancels known obsolete bot orders, attempts the exit, verifies the remainder or zero exposure and produces a report. Unowned open orders are reported rather than silently cancelled. The EOD-complete flag is set only after verified closure/reconciliation. Stale quotes do not produce fake flatten fills.

## L. Opportunity-engine improvements

The discovery set expands from configured preferred symbols into up to 60 broker-eligible NSE EQ candidates. Price, historical volume, data quality and the existing ATR floor still apply. Selected symbols remain top-N, with one global position.

Pre-selection is direction-neutral. The frozen core and daily bias decide direction. Scores expose liquidity, spread, depth, volatility, participation and data reliability. At decision time, valid opportunities are compared by execution quality, net R:R, depth, score and deterministic timestamp/symbol tie-breaks.

Same-time RVOL compares current cumulative volume with cumulative profiles of prior dated sessions at the same clock time. It needs sufficient history; unknown RVOL is reported honestly. Later-session and current/future-session volume are excluded.

ResearchVariant separates alternate research aggregation from the production one-minute timeframe. Replay executes a completed-bar signal at the next observation. Entry depth uses previously completed volume, with assumptions recorded. Real history failure never substitutes a synthetic series.

Research reports include expectancy, win rate, winner/loser size, R statistics, profit factor, drawdown, consecutive losses, side/symbol/setup/day/hour groups, fee ratio and slippage distribution. Rejected-opportunity analysis records later excursions and R where available, explicitly without claiming a filled net trade. Classifying gates as protective or restrictive still needs repeated, cost-aware evidence.

No actual multi-session historical dataset was validated in this task. Dynamic-universe and real spread/depth profitability remain unproven.

## M. Tests executed

Final reproducible command, from the repository root:

    .venv/bin/python -m pytest algo-trading-bot -q --junitxml=docs/validation_v6_tests.xml

Additional checks: git diff --check; git diff --exit-code on signal_brain; SHA-256 comparison; original/current source comparison of five management methods; replay CLI help; searches for direct broker-order and fallback-token paths.

The pytest dependency was installed into the project's existing virtual environment. No runtime broker account was authenticated by these checks.

Evidence:

- [Machine validation record](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/validation_v6.json>)
- [JUnit results](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/validation_v6_tests.xml>)
- [Test output](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/validation_v6_tests.txt>)
- [Function-change inventory](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/validation_v6_function_changes.json>)

## N. Tests passed

**244 passed in 2.98 seconds; 0 skipped.** This comprises 161 existing collected cases and 83 new cases, including parametrized cases.

All nine required scenarios have deterministic coverage: reduced/rejected excessive setup risk, wrong token, non-VWAP paper entry, stop gap, insufficient daily allowance, actual partial entry/protection, restart recovery, duplicate events and flatten/flat confirmation.

Further coverage includes post-cost sizing, side-specific fees, single-position enforcement, no scaling, cancellation, failed protection/unwind, unknown order quarantine, partial exits, stale quotes/bars, source freshness, logging redaction, orphaned/mixed ledgers, persistent halts, restart management counters, database failure and activation evidence.

The LIVE-path tests use only ScenarioBroker and temporary, clearly marked mock approval files. Passing them does not satisfy the real account's broker verification requirements.

## O. Tests failed

**Final failures: 0.**

Earlier test runs deliberately exposed defects before repairs. The first full compatibility run had 60 failures and 127 passes. Obsolete tests asserting three tranches, fallback identities, magic fills or blind order recovery were migrated to the authorized safety contract; actual defects were repaired and given specific regressions. No test failure was hidden using a skip, expected-failure marker or disabled financial guard.

## P. Remaining risks

- Daily profit, a positive expectancy and a minimum daily trade count remain unproven.
- Real gaps and failed limit fills can exceed planned loss allowances; software cannot guarantee execution.
- Account-specific fees and contract-note rounding are unverified. Standard fee estimates can differ from final billed charges.
- Instrument refresh and the authenticated intraday eligibility endpoint were not exercised against this account. Surveillance restrictions, special categories and permission changes need verification.
- Recovery safely blocks unrecognized exposure, but cannot reconstruct missing strategy history or unknown fills from nothing. Some quarantines need operator reconciliation.
- Critical alerts currently go to local logs. External alert delivery and operator response were not verified.
- Database failure can prevent durable accounting. The system halts and preserves/protects known exposure where possible; a complete storage or broker outage can still require urgent manual recovery.
- Candle replay uses assumed spread/depth and a declared open-low-high-close path. It is not tick, order-book or execution-quality evidence.
- Discovery is capped at 60 candidates and top-N; this does not certify comprehensive opportunity capture.
- Some legacy enum names and management telemetry remain for compatibility. They do not enable retired scale-in paths.

## Q. Broker assumptions requiring external verification

All of these remain **UNVERIFIED** for this account: static IP, supported LIMIT/STOPLOSS_LIMIT behavior, partial fill/cancellation semantics, current intraday eligibility and restrictions, account fee plan, RMS flatten deadline, contract-note reconciliation and observed emergency flattening.

The standard cost model uses Angel One's published intraday tariff: 0.1% brokerage with the published ₹5 minimum/₹20 cap, sided STT/stamp duty, NSE transaction charges, SEBI/IPFT and GST. Account-specific billing still takes precedence. [Angel One pricing](https://www.angelone.in/exchange-transaction-charges).

Angel One's April 2026 notice describes static-IP requirements and restrictions on MARKET/IOC requests. This implementation sends supported limit order types and requires account-specific evidence rather than treating an order-type substitution as verified compatibility. [Angel One SmartAPI notice](https://www.angelone.in/news/market-updates/what-s-changing-in-angel-one-s-smartapi-access-from-april-1-2026), [SmartAPI documentation](https://smartapi.angelone.in/docs).

LIVE_MODE and LIVE_VALIDATION_APPROVED remain false. No capability or live activation evidence file is configured. An approval record must be dated, match the current source fingerprint, report passing P0 tests, contain broker evidence and explicitly recommend OBSERVED_LIVE_PILOT_READY. The supplied validation record says PAPER_ONLY and cannot activate live execution.

## R. Git diff summary

Tracked changes: **15 files, 901 insertions and 4,350 deletions** at the verification snapshot. Large deletions remove retired execution/pyramiding paths, the old replay implementation and obsolete financial test bodies. The complete signal module and five management methods remain unchanged.

New source files: 17 — 10 runtime components, one offline support fixture and six test modules. Documentation and validation evidence are additional files. Ordinary git diff --stat omits untracked additions; see the machine record for the explicit file list.

No legacy trade CSV was modified. No source changes were committed or pushed.

## S. Proof that signal_brain.py is untouched

Git diff --exit-code for algo-trading-bot/signal_brain.py returned 0 with no diff.

SHA-256 before and after:

    bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83

The verification script also compared the original and current source text of update_daily_bias, check_exit, notify_candle_close, manage_open_position and square_off_all_positions. **All five match verbatim.**

EMA periods, VWAP/ATR formulas, candle timeframe, signal anti-spam, cooldown, original stop/target geometry and the 15-bar management rule were preserved. New rejection, reservation and capital emergency behavior belongs to the surrounding safety infrastructure and is explicit in this report.

## T. Recommendation and tomorrow's session protocol

**PAPER_ONLY. Real-money execution remains BLOCKED.**

For 1 October 2026:

1. Keep paper mode and both live flags disabled.
2. Before the session, obtain a current broker-master/eligibility snapshot through the read-only startup path and inspect the historical screen. Unavailable data or no qualifying symbol means NO_TRADE.
3. Run the normal stream from the repository root:

       .venv/bin/python algo-trading-bot/live_stream.py

4. Observe real bid/ask/depth and genuine incremental volume. Allow warmup and the existing filters. The bot may take zero, one or two justified setups; one position at a time.
5. Stop fresh entries at 14:30. Begin flattening at 15:00. Resolve any stale quote, unknown exposure or incomplete closure before calling the session complete.
6. Review the PAPER journal, trade projection and report in algo-trading-bot/data/paper. Net results are execution observations with declared fee assumptions, not evidence of future daily income.
7. Use repeated real sessions and cost-aware replay to assess expectancy. Do not lower strategy thresholds because one session was inactive or one rejected signal later moved favorably.

If paper startup fails to obtain verified identity/eligibility or executable data, the correct result is a reported sit-out. The implementation improves the ability to find and safely evaluate opportunities; it does not manufacture profit or activity.
