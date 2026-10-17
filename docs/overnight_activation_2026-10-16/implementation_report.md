# Overnight LONG readiness — October 16–17, 2026

**Engineering repairs implemented; actual trading remains BLOCKED.** Native triggered Stop Limit and subminimum residual behavior are not independently exchange-qualified. No new actual order, wallet signature, acceptance or trading worker was created. PAPER/false and the frozen strategy remain in place.

## A. Blockers repaired

- `exchange/terminal_recovery.py`: preserve known history with overlap, quiesce streams, bounded 65-second local rate waits / 75-second individual reads / 180-second shutdown. Caps and safety reserves are unchanged. Require stable positions around the frontend-order snapshot and two distinct authoritative readbacks. UNKNOWN and EXPOSED remain distinct from FLAT_VERIFIED.
- `exchange/live_recovery.py`: retain the original sanitized reason and stack in the journal and chained exception. The earlier historical worker lost its message, so its exact root cause cannot be reconstructed; the short-budget failure was reproduced offline, not asserted to be a historical HTTP429.
- `exchange/live_account_stream.py`, `live_execution_session.py` and the LONG builder: share an independent notification receiver, release receiver locks during REST/protection waits, and compare generation/event sequence before clearing readiness.
- `exchange/live_runtime.py` and `exchange/terminal_app.py`: preserve outer CLI ownership of SIGINT/SIGTERM so process termination cannot stop only the signer then resume observation. Duplicate starts against an owned runtime state are rejected.
- `exchange/overnight_session.py`, `bounded_daily_session.py` and `long_session.py`: separate explicit cross-midnight type and acknowledgments; prior single-day validation remains strict. The actual SDK/protection/coordinator route is reused.

The detailed A–F register is in `blocker_register.json` and `blocker_register.md`. No safety rejection was suppressed.

## B. Native stop status

**UNVERIFIED.** No actual native stop acknowledgement/trigger child/closing SELL was generated in this assignment. The original controlled IOC BTC round trip remains genuine but does not prove native behavior. See `native_qualification_review.md` for the authoritative documentation and source trace. An accepted untriggered order is not a triggered fill. Stop Limit may rest through a gap.

## C. Partial-fill handling

All 30 fresh samples have a possible one-lot stop value below the ordinary minimum. `partial_path_assessment` correctly blocks unattended entry. Increasing the intended BUY does not eliminate possible one-lot partial fills or exit remnants. Existing historically scoped exact IOC closure evidence remains narrowly scoped; it is not a native-stop exemption. No quantity enlargement, hidden dust removal, FOK assumption, grouping workaround, software stop or Stop Market substitution was introduced.

A minimum-compliant runtime market/lot or authoritative, independently qualified native residual handling is required before a legitimate small qualification can be prepared and separately accepted. That qualification must preserve actual order/child identities, closing fills, fees/funding/residuals and two authoritative flat reads. No market manipulation or manufactured trigger is permitted.

## D. Overnight session support

Implemented contract: `EXACT_APPROVED_OVERNIGHT_LONG_TESTNET_V1`. Creation/acceptance must occur October 16. Proposed hard signing and owned risk/recovery expiry: **October 17, 2026 at 12:00 IST**. Maximum duration 18 hours. Stop new entry at 11:45; begin scheduled guarded risk closure at 11:55. After noon all new signatures are blocked, even if an open position remains. Read-only observation/reconciliation can continue. No renewal, restart authority or new day is inferred.

Proposed bankroll 20,000; LONG only; 1x CROSS; one global position; at most two entry attempts TOTAL; nominal maximum 1,000 and cumulative allocation 2,000; maximum 12 signed actions and two owned cancellations. Per-trade risk 0.5%, carried daily/session loss 1% with no reset of attempts, allocation, actual P&L, peak equity or drawdown at midnight. Exact permitted risk exits may realize a loss; entry and management continue to require all central source/account/nonce/rate/protection checks. STOP revokes entries immediately and retains only the already accepted risk/cleanup scope until the hard expiry.

## E. Genuine LONG readiness

Offline integration drives the hash-verified frozen strategy, central validation, official SDK with ephemeral fixtures, native adapter, actual-fill reconciliation interface and existing manager. No actual-wallet signer or HTTP exchange transport is used by those tests. Genuine automatic strategy-generated execution remains unverified because venue protection is unresolved. Missing or failed strategy conditions remain NO TRADE.

Production UTC VWAP, frozen indicators/state/geometry, scanner 0.40% ATR, 15 bps spread, 300 bars and Top-3 are preserved. The six isolated exit policies were reviewed as research; none has sufficient genuine forward evidence for promotion. Frozen normal profit-taking and risk exits remain the active design.

## F. Multiple-trade readiness

The new midnight integration completed two independent fixture LONG cycles (a win then a loss), reconciled stop cleanup/flatness, carried budgets across midnight and blocked a third entry. Full CLI simulation separately covers win/loss, rejected entry, uncertain entry, partial entry and partial exit. Synthetic partial faults intentionally retain RECOVERY_REQUIRED/UNKNOWN; they do not qualify actual venue residuals. Genuine historical cycle count: one controlled BTC round trip. Newly approved attempts: zero. Proposed initial limit: two attempts total, one concurrent position.

## G. Capital limits

The unsigned all-market audit obtained three snapshots for each of ten runtime markets and two ready flat/zero-order reads. Collateral was 1000000.050512 TEST USDPR, margin zero, unified mode, approved API identity and all ten active-asset readbacks 1x CROSS. Withdrawable remains null; account balance is not signing authority. Raw L2 levels, best-level volume, runtime lot/maxTradeSz, both-side capacity, spread and conservative fee bound are in `fresh_liquidity/audit.json` and `all_market_capacity.json`.

| Market | Earlier 3-sample notional range | Latest audit notional | One-lot stop notional | Qualified unattended notional |
| --- | ---: | ---: | ---: | ---: |
| par:BRENT | 9.4419–49.3171 | 9.5769 | 1.0328710 | 0 |
| par:BTC | 48.85680–48.87960 | 48.81300 | 8.01622550 | 0 |
| par:ETH | 49.91340–49.94825 | 49.82115 | 0.23977855 | 0 |
| par:EWJ | 49.918781–100.028456 | 49.994175 | 0.093965060 | 0 |
| par:EWY | 19.91470–19.93160 | 49.97214 | 0.15091185 | 0 |
| par:GOLD | 9.58916–49.62419 | 49.97880 | 0.41049875 | 0 |
| par:HYPE | 3.9635–49.9149 | 49.6944 | 0.7797260 | 0 |
| par:SP500 | 7.6855–7.6855 | 0.0000 | 7.5661790 | 0 |
| par:USDEUR | 9.99292–29.31291 | 79.33954 | 0.11053670 | 0 |
| par:USDJPY | 49.042–49.042 | 49.1288 | 1.5581715 | 0 |

These are dated displayed-book calculations, not orders or guaranteed fills. They use 10% participation on both best levels and finite L2 with lot rounding down. All 1,000/2,500/5,000/10,000 targets were unsupported in these snapshots. The latest proposal snapshot and `latest_market_capacity.json` provide a later view with explicit observation ages; its notional is shown separately in the table. The one-lot stop values belong to the earlier reviewed stop plans. Actual permissible unattended size remains zero until protection, strategy, fresh-account and approval gates pass.

## H. Complete regression

**2617 tests; 0 failures; 0 errors; 0 skips.** Full preserved 2,574 baseline plus 43 new checks. Phase-0 and strategy freeze passed before and after. Source remained identical during the final run.

Working tree source SHA-256: `3911d7226a9befe7adfda84222623ee9533a414cb4efd9ed674f3d3041401312`; Git HEAD `a9e222c6549686651c3565155ed555fa7ee04739`. Infrastructure changes are uncommitted and the release is bound to these exact working bytes.

Receipt: `regression_release_final/test_receipt.json` — SHA-256 `999e6b576fa0214a66cf34994f9e5542524600f7fd1f3377025226453d6f4cb7`.

XML SHA-256: `d8cdc4bd20b25d9cf48b4b4b6fabbdbc83c285ece1adee2ab530639c7dff21db`.

The earlier candidate passed 2,614 tests but source changed during later diagnostic/signal repairs; its receipt is preserved as superseded and is not the release receipt. Dependencies are bound separately by requirements SHA and exact installed versions. No dependency installation was needed. `doctor_final.json` and `simulation_final/` match the final source.

## I. Exact approval required

Latest blocked proposal digest: `6faf4d04d469ff14a4c8929333bc6a13d75d57f5694d2dab6be9569197487e53`. This is **not an executable mandate ID**. Prepared 2026-10-16T22:26:12.120000+05:30; the displayed five-minute approval window is an audit field and does not grant authority. Hard proposed expiry 2026-10-17T12:00:00+05:30.

An executable approval request cannot be issued while the mandatory native/partial feasibility gate fails. The blocked proposal is saved in `final_proposal/proposal.json`; `blocked_scope_review.json` also records contract defaults, fee/action bounds and required acknowledgments, including wallets, exclusive signing host, source, bankroll, counts, losses, prices/slippage policy and expiry. It creates neither `mandate.json` nor `acceptance.json`. After the external protection evidence exists, fresh preparation must generate a new exact source-bound mandate for explicit human acceptance. No approval is requested to bypass a valid guard.

## J. VS Code commands

Exact commands, parser flags, preparation/approval/start templates, status/report/stop and process-bound caffeinate are in `OPERATOR_GUIDE.md`. The local Python runtime requires no Codex/paid LLM. The actual signing start was not executed; parser, negative gates, offline integration and signal tests were validated.

## K. Runtime proof

Final-source public diagnostic only: worker PID 89541, session `b96205e97d854f77bb5c9ad232e1e73d`, 616.927 seconds, 43 resource samples; 34 samples with both streams healthy. Peak memory 138.562 MB; late high-watermark growth 0.0 MB. Recorded read errors: `{'None:INFO_READ_CANCELLED': 1}` (one read canceled during controlled STOP; no recorded HTTP status error). Public receipts 509; SQLite ok; order intents 0; signatures 0; exchange writes 0. Threads stopped: True. Account status: FLAT_VERIFIED.

The real shutdown waited more than ten seconds for its unchanged rolling rate budget before completing both reads; no HTTP429 was recorded. Its own terminal authoritative readback times: [1792169611188, 1792169613808]. STOP/interrupt tests are recorded in `interrupt_diagnostics.json`; missing evidence is not inferred flat. Final proposal audit obtained later authoritative reads: [1792169769293, 1792169772115].

No authorized trading worker was launched or left running. Both old heartbeat automations remain PAUSED. Runtime still depends on this Mac, local Python/terminal, power, internet and venue. Caffeinate cannot cover forced sleep/power/network outages; actual physical Mac sleep was not induced, while a 60-second gap fault revocation was tested. This bounded diagnostic is not an overnight execution certificate.

## L. Trading outcomes and preservation

October 16 actual observed: 0 fills; fees 0; funding 0; realized net 0 TEST USDPR.

October 16: actual observed fill count/fees/funding/net are recorded from exchange event timestamps in `release_summary.json`; this assignment submitted no orders. Final authoritative account is flat with zero open orders. Original October 15 BUY 0.0002 BTC at 81,512 (order 62755970305/fill 800659111758533, fee 0.014672) and SELL at 81,909 (order 62805581662/fill 260274449763192, fee 0.014743) remain preserved. Gross +0.0794, fees 0.029415, actual funding +0.000527, **net +0.050512 TEST USDPR on October 15**. This is not today's or synthetic P&L.

Preservation receipt: all critical policy/freeze/brain/proof/lock hashes and all three original SQLite logical dumps/integrity unchanged: **True**. Raw UNKNOWN, its nontransmission certificate, nonce history and prior checkpoints remain intact. Offline legacy test artifacts were archived separately. No organizer whitelist/reset or guaranteed profit is claimed.

Next dependency: independently established native residual/protective behavior under a legitimate exact qualification, then fresh executable proposal and human acceptance. Larger unattended trading cannot be safely activated merely by increasing a proposed quantity or weakening a guard.
