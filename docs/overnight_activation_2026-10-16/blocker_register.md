# Blocker register — October 16–17 readiness

A software defect; B missing implementation; C unverified venue behavior; D valid risk rejection; E stale evidence; F expired or absent exact authorization.

## A1 — REPAIRED_REAL_PUBLIC_SHUTDOWN_VERIFIED

Class: A. Source: `algo-trading-bot/exchange/terminal_recovery.py` → `terminal_reconcile`.

Prior observer shutdown allowed only 5 seconds local budget wait and 40-second outer deadline; disconnect permission revocation caused full-history fallback.

Quiesce streams, allow 65-second budget wait/75-second query/180-second total, use known history with 60-second overlap; unresolved histories remain blocked. Two stable distinct authoritative readbacks required.

Evidence: Previous raw terminal_result retained UNKNOWN/ExchangeError with no message. Offline rolling-window budget reproduction fails old 5-second path; new bounded wait succeeds without changing caps/reserves.

Original old exception message was lost, so its exact cause cannot be retrospectively proved. No HTTP429 inferred.

## A2 — REPAIRED

Class: A. Source: `algo-trading-bot/exchange/live_recovery.py` → `LiveAccountRecovery.recover`.

Exception wrapper discarded original cause; terminal output retained type only.

Persist sanitized original exception and stack, preserve chained cause; observer and authorized shutdown expose evidence.

Evidence: test_live_recovery_retains_original_cause_and_sanitized_trace plus terminal UNKNOWN fault tests

## A3 — REPAIRED

Class: A. Source: `algo-trading-bot/exchange/live_account_stream.py` → `start_receiver/reconcile`.

Owner-thread scans and REST/rate waits delayed account polling; reconcile held receiver lock during network work.

Shared independent notification receiver for observer and authorized route; release lock across REST/protection, compare generation+event_sequence before clearing pending state; bounded receiver shutdown.

Evidence: Concurrent-notification, duplicate-receiver, 60-second heartbeat-gap tests; real soak pending. Final public soak records stream health and zero order intents. Final public soak records stream health and zero order intents. Final public soak records stream health and zero order intents.

## A4 — REPAIRED

Class: A. Source: `algo-trading-bot/exchange/live_runtime.py` → `LiveRuntime.run and terminal_app.run_authorized`.

Inner SIGTERM handler could end signing while the outer CLI continued observation.

Outer CLI owns signals for the whole application; standalone runtime keeps original signal handling by default.

Evidence: Two signal-ownership unit cases plus actual public Ctrl+C/SIGTERM diagnostics; no signer.

## B1 — IMPLEMENTED_REQUIRES_EXACT_APPROVAL

Class: B. Source: `algo-trading-bot/exchange/overnight_session.py` → `OvernightLimits/OvernightLongMandate`.

Original DailyMandate is single IST day; no cross-midnight signing contract.

Dedicated Oct16–17 LONG-only type, Oct17 noon maximum expiry, 18-hour maximum, extra human acknowledgments; no reset of attempts/allocation/P&L/peak/drawdown; original single-day contract remains strict.

Evidence: 43 overnight/shutdown tests including midnight win/loss coordinator+SDK fixture

## C1 — EXTERNAL_UNVERIFIED

Class: C. Source: `algo-trading-bot/exchange/long_session.py` → `require_native_evidence`.

No actual native Stop Limit trigger/linked child SELL/fill/funding/two-flat proof for the proposed markets.

No bypass. Obtain genuine independently evidenced stop qualification under separately accepted, minimum-compliant exact scope.

Evidence: Historical BTC IOC round trip proves controlled IOC closure only. Actual native trigger and child fill remain unverified.

## C2_D1 — BLOCKED_UNCHANGED_GUARD

Class: ['C', 'D']. Source: `algo-trading-bot/exchange/partial_fill_safety.py` → `partial_path_assessment`.

All 30 fresh samples have one-lot protective notional below 10 TEST USDPR; larger entry cannot eliminate possible one-lot fills/residuals.

Retain ordinary and protective minimum. Only historically scoped exact IOC full-close helper permits its observed exception. No documented general native exemption established.

Evidence: fresh_liquidity/audit.json and all_market_capacity.json

No currently minimum-compliant candidate can enter dedicated unattended native qualification under unchanged partial guard.

## C3 — REAL_AUTONOMOUS_CYCLES_UNVERIFIED

Class: C. Source: `algo-trading-bot/exchange/long_session.py` → `DailyLongExecution/DailyLongSession`.

No new real frozen-strategy-driven autonomous multi-cycle run.

Existing route integrated; offline actual SDK fixtures prove two cycles across midnight and block third. Genuine run requires native qualification, fresh eligible setup, exact approval.

Evidence: Original Oct15 controlled BTC round trip remains one genuine cycle; no new actual orders.

## D2 — VALID_RISK_REJECTION

Class: D. Source: `algo-trading-bot/exchange/long_session.py` → `AllocatedLongRisk.assess/_prepare_context_request`.

Fresh displayed both-side liquidity and 10% participation cap sampled capacity about 4–100 TEST USDPR, below 1k/2.5k/5k/10k targets.

No restriction removed, no splitting, no forced notional. Recompute size and both-side capacity before every future signing.

Evidence: 30 all-market snapshots; target flags false; qualified unattended notional zero.

## D3 — VALID_FROZEN_LIMIT

Class: D. Source: `algo-trading-bot/exchange/bounded_daily_session.py` → `DailyLifecycle.reserve_entry`.

Frozen two-entry-attempt and one-global-position limits prevent unlimited cycles.

Keep two attempts TOTAL across midnight, one position including partial/uncertain exposure; loss budget carries.

Evidence: Third-entry fixture rejection; no strategy/source policy tuning.

## E1 — FRESH_CHECK_REQUIRED_FOR_EVERY_ENTRY

Class: E. Source: `algo-trading-bot/exchange/long_session.py` → `_prepare_context_request`.

Stale/absent completed bars, funding/fee/account/metadata data cannot support entry.

Fresh reads and preserved signal rules; record NO TRADE. No synthetic candles/price or stale signal reuse.

Evidence: Fresh sample decisions/reasons preserved in all_market_capacity.json; final wire revalidation unchanged.

## F1 — NO_CURRENT_ACCEPTANCE

Class: F. Source: `algo-trading-bot/exchange/terminal_app.py` → `prepare/approve/start`.

Previous single-day mandates expired; development directive is not exact operator acceptance.

Prepare blocked exact descriptor now; after genuine protection/partial feasibility, generate fresh source-bound mandate and request human acceptance within 5 minutes. No acceptance or signer created.

Evidence: Blocked proposal only, no executable mandate.json/acceptance.json.
