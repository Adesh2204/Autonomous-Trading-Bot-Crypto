# Team Anchorium — LONG execution repair report

Status: **ENGINEERING_VALIDATED_OFFLINE_ACTIVATION_BLOCKED**. Report time: 2026-10-16T15:54:38.928000+05:30.

**No trading started.** The operator asked for repairs, tests and this report, with any trading decision deferred until tonight. No new signing acceptance or executable mandate has been created.

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Old observer | PASS | Stopped cleanly; original worker/supervisor/caffeinate identities and two flat readbacks preserved in cleanup_receipt.json |
| Exchange account | PASS | Two authoritative readbacks at 2026-10-16T15:50:36.934000+05:30; flat/zero-orders verified: True; snapshot ages remain explicit |
| Execution bridge | PASS | Implemented and tested offline through the existing frozen strategy, central validator, SDK, management, native protection and closing reconciliation; actual exchange path NOT VERIFIED |
| Native protective exit | BLOCKED | No genuine native-stop qualification. Every sampled market has one-lot notional below $10; the preserved partial-fill protection guard rejects a new entry |
| LONG signal handoff | PASS | Unchanged frozen brain emits LONG from deterministic fixture candles; central provenance and risk checks receive that output |
| Sequential cycles | PASS | Two complete offline LONG cycles, profitable and loss-making, with owned stop cleanup and two flat readbacks; actual repeated exchange cycles NOT VERIFIED |
| Capital allocation | PASS | Runtime lot rounding, lower realistic sizes and tighter both-side BBO/L2/collateral/risk/approved ceilings enforced. Qualified actual unattended notional remains zero |
| Full regression | PASS | 2545 tests; final source/receipt/XML and Phase-0/freeze checks must match |
| Historical proofs and persistence | PASS | Original BUY/SELL proofs, raw UNKNOWN, verified certificate, nonce history and SQLite/checkpoint hashes checked |
| Trading authorization | BLOCKED | Deferred by operator until tonight; native protection and fresh eligibility are still prerequisites. No acceptance created or old mandate reused |
| Trading worker | NOT VERIFIED | Not launched, per current operator instruction; no signing service or replacement observer started |
| Genuine new trades / today P&L | PASS | This task placed zero orders. Observed today fills: 0; net 0. Historical Oct15 verified net +0.050512 TEST USDPR stays separate |

## Engineering changes

`exchange/long_session.py` supplies a separate exact-approved TESTNET LONG adapter. `scripts/run_long_session.py` is distinct from the public observer command. It keeps global PAPER/false, requires a matching full release, native-stop evidence, an unchanged acceptance file and exact host/source/policy identities before loading the existing API signer. The original SDK transport, nonce and account leases, central compliance permits, risk checks, journal and account streams remain in the path.

The coordinator reserves an entry durably, binds its quantity and action identity, consumes attempts before HTTP, reconciles reported fills into the frozen manager, verifies exact native protection, and records actual closing cashflows/fees/funding. Two independent authoritative flat/zero-order readbacks and stop cleanup precede another cycle. Unknown or partial closing outcomes pause entries and cannot be blindly repeated. A stale cached stop receipt is refreshed before declaring lost coverage; a genuinely missing/rejected stop triggers the authorized recovery state and cannot be automatically rearmed.

The end-to-end offline venue uses a synthetic whole-unit lot worth more than $10 so that a genuinely admissible lifecycle can be tested. Actual par lot sizes are untouched and remain subject to the separate partial-fill minimum blocker. These fixture fills and stops never establish real exchange qualification.

The original recovery service now exposes an intent-view hook whose default preserves raw production UNKNOWN barriers. The isolated LONG recovery uses the existing verified nontransmission certificate view while retaining full strategy callbacks. Historical controlled-test fills remain in account truth and are excluded from the new mandate’s strategy transitions. No historical intent, certificate or nonce is erased.

Stops and targets retain the frozen VWAP/ATR formulas. Research trailing, reversal and holding-period policies remain isolated; synthetic policy comparisons do not promote an exit model. SHORT remains disabled. The session ceiling is two independent setups and one global position. No loss bound is guaranteed through a gap or failed stop.

The isolated adapter uses native **Stop Limit**, with the previously approved one-entry-ATR distance beyond the normal stop and an explicit 0.5% execution limit. Hyperliquid documents 10% tolerance for TP/SL market orders, so a Stop Market is not an approved substitute. A stop-limit can remain unfilled after a gap. Known settled residuals may use the approved reduce-only recovery path; uncertain or unresolved trigger children halt for authoritative review rather than allowing a competing order. The default generic protection manager is unchanged. Only the existing offline venue fixture gained a default-preserving order-type option.

The actual builder requires source-bound native Stop Limit trigger/closing evidence. Acceptance of an untriggered order alone is recorded as untriggered, not as proven trigger execution. The existing Stop Limit qualification infrastructure is reused. Actual fees, funding and reward/risk are recalculated in the fresh central entry preflight; a later funding spike cannot use an older risk approval. Native qualification is still a genuine prerequisite.

## Current recorded market capacity

Bounded audit: 2026-10-16T15:33:40.337000+05:30 to 2026-10-16T15:35:49.957000+05:30; three samples per market. Account snapshot age at report: 242.0 seconds. Quotes must be read again before any later proposal.

| Market | LONG min–max | Latest LONG | SHORT min–max | One lot at bid | All samples support 1,000? |
|---|---:|---:|---:|---:|---|
| par:BRENT | 9.2727–9.2763 | 9.2763 | 9.2619–9.2673 | 1.0297 | False |
| par:BTC | 98.2236–98.2272 | 98.2272 | 98.1576–98.1588 | 8.1798 | False |
| par:ETH | 9.7860–99.8254 | 49.8780 | 9.7784–99.7438 | 0.2445 | False |
| par:EWJ | 49.9382–49.9382 | 49.9382 | 49.9076–49.9076 | 0.0962 | False |
| par:EWY | 49.9059–100.0186 | 49.9059 | 49.8770–99.9351 | 0.1554 | False |
| par:GOLD | 9.6154–9.6156 | 9.6154 | 9.6089–9.6089 | 0.4178 | False |
| par:HYPE | 99.9756–99.9781 | 99.9781 | 99.8981–99.9068 | 0.8122 | False |
| par:SP500 | 1168.7400–1168.7400 | 1168.7400 | 1168.5135–1168.5135 | 7.7385 | True |
| par:USDEUR | 9.9079–9.9088 | 9.9088 | 9.9018–9.9026 | 0.1125 | False |
| par:USDJPY | 49.0916–500.2596 | 49.0916 | 49.0017–499.2168 | 1.5807 | False |

Values are TEST USDPR bounds from the displayed book under 10% of BOTH best levels and finite L2 limits, runtime max trade size and available collateral. They are neither fills nor safe approved sizes. A fleeting larger quote does not prove persistent entry and closing capacity. Full level data, lot precision, runtime sizes, estimated costs/funding, explicit cache ages and all 1,000/2,500/5,000/10,000/25,000/50,000 tiers are in `liquidity_capacity.json`. Unsupported full-size fill costs, strategy stop risk and liquidation price remain unavailable rather than extrapolated.

Signal explanations describe recorded frames. The audit caches its initially read completed bars and reports their ages; a late stale-bar rejection does not prove that a freshly refetched candle would also be stale. The execution scanner refetches completed bars and retains the original warmup, gap and freshness checks. No live qualifying setup is certified by this report.

Every market in this capture has a smallest runtime lot below the ordinary $10 order minimum. A valid total entry above $10 may still partially fill one lot; the existing guard therefore requires independently established native-protection/remaining-close behavior. No general stop exemption has been established for this registered account and DEX. The ordinary minimum and both-side liquidity guards are unchanged. Approved bankroll and actual qualified unattended notional remain **zero**.

The conservative fee bound is six times the reported base fee when current deployer scale is unavailable; this is an estimate, not the actual charged fee. Actual fees and funding come only from exchange account events. Current funding is not a forecast. The sampled adverse price range does not estimate the worst possible gap or stop loss.

## Actual accounting and preserved evidence

Reported account equity/collateral: 1000000.050512 TEST USDPR, margin used 0. That balance is not an approved bankroll. The final two public readbacks show zero positions and zero open orders as of their recorded times.

Today’s observed fills: 0; actual fees 0; funding 0; realized net 0 TEST USDPR. This task placed no orders. Historical October 15: BUY 62755970305 / fill 800659111758533 at 81,512; SELL 62805581662 / fill 260274449763192 at 81,909; quantity 0.0002 BTC; gross +0.0794; entry fee 0.014672; exit fee 0.014743; actual funding +0.000527; net **+0.050512 TEST USDPR**. This is not today’s trading profit or an organizer score. Original proof files remain untouched.

Preservation passed: True. Both SQLite integrity checks, recovery checksum validation, the repaired historical certificate, raw UNKNOWN preservation and nonce history are recorded in `preservation_verification.json`.

## Release verification

Final source: `b76fc8d59e8521f06b018baa258983f82166cf39f1eddeaaa341ef66c41d918c`.
Full regression: `{'tests': 2545, 'failures': 0, 'errors': 0, 'skipped': 0}`; matching final receipt passed: **True**.
Receipt SHA-256: `4379486a00f467cce2bc8c7f324bea6445d3a04505be6ba8a34046fa290ddf5d`.
XML SHA-256: `f20606a98178c0ba90fd6088952a6db5740497903811d40f020fa41cc2abacd8`.

The earlier 2,539-test run is preserved separately as a valid superseded engineering snapshot. Final release checks cover the later safety review fixes; no actual-wallet signature is generated by these offline tests. Freeze and Phase-0 are checked before and after the full suite. A passing test suite does not certify native venue execution or guarantee that software has no undiscovered defects.

## Conditions for tonight

1. Resolve the exact native-protection minimum/partial-fill prerequisite using authoritative venue evidence or a market satisfying the unchanged guard. Do not open exposure merely to bypass it.
2. Prepare and explicitly approve a separate tiny controlled native test covering opening exposure, stop identity, loss-making emergency recovery and cleanup. Record an untriggered stop honestly if no genuine trigger occurs.
3. After qualification, collect fresh account/market/fee/funding/clock/rate/nonce/source evidence and a valid frozen LONG setup. Recalculate the supported size; do not force a 1,000+ order.
4. Present a new exact LONG-only multi-entry mandate with the verified proof and release hashes, operator bankroll, position/cumulative limits and loss-exit acknowledgments. No approval is requested now.
5. Only after genuine exact approval, launch and verify the execution-enabled process and its supervision. No auto-start, extension or next-day renewal is authorized. Hard day limit in this release: 23:57 IST, October 16.

Both previous heartbeat schedules remain paused. No replacement observer or trading worker has been launched. Local operation and supervision depend on this Mac, the app, power and internet. A native stop does not guarantee a complete fill. Organizer whitelist/reset status is unknown without organizer evidence.

## Primary venue references

- [Participant guide — runtime precision, minimum and IOC/trigger rules](https://perpetual-alpha26.github.io/docs/)
- [Hyperliquid TP/SL semantics](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
- [Hyperliquid order rejection definitions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)
