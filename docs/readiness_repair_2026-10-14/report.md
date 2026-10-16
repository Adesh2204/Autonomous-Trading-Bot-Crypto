# Anchorium — account-freshness repair and persistent qualification observer

Status: engineering repair complete; waiting for a NEW exact session authorization. Generated 2026-10-14T16:22:43.245965+05:30.

## 1. Exact root cause and repaired functions

The old BUY was 0.0002 BTC at 83,513, 16.7026 test USDPR. Price, depth, leverage and notional checks passed. Its retained account-readiness object aged past the unchanged five-second signing requirement while repeated account/book reads ran at SDK callbacks. `P0_FRESH_RECONCILED_FLAT_ACCOUNT_REQUIRED` blocked it before the mandatory transmission claim and HTTP POST. Local signing and nonce allocation had been reached; claiming zero earlier signatures would be wrong. The old readiness timestamp was not retained in the failed diagnostic, so its exact over-age cannot be reconstructed.

The repair is `EmergencyContextProvider.refresh_for_signing`, `QualificationSigningBoundary.refresh_permit` and the narrowly scoped `EmergencyExecution._guard`. The existing fixed-price and bounded-price order rules remain. The boundary never changes the immutable wire price or quantity. It can renew only its registered exact-action capability after genuine account/market/risk/compliance revalidation.

## 2. Genuine signing-boundary evidence

The path is observation → runtime preflight → normalized immutable order → central permission and durable intent → SDK exact-action checks → nonce/signature → final pre-HTTP validation → durable transmission claim → HTTP. When readiness/account/quote/mark evidence is stale, the provider performs actual account recovery, before/after positions and frontend orders, reported recent fills, market capacity/leverage, account mode, USDPR collateral, API-agent approval/expiry, fees, rate budget and fresh metadata/book reads. Nonce ownership and clock health are rechecked. The order is re-evaluated against this actual state; a new position/order, failed read, revoked authority, changed source or outside-envelope price still blocks it.

No observation timestamp is advanced to make it look fresh. Readiness/account/quote/mark ages must remain between zero and 5,000 ms. A repeat check after cryptographic signing can reacquire evidence again before HTTP. A global startup block, degraded entry/rate/protection state, client/feed failure, server backoff and expired agent still block the refreshed path. Timing, original evidence timestamps, callback stage, immutable request, nonce and HTTP-start/response/uncertainty events are durable; private keys and signature material are omitted.

## 3. Original UNKNOWN recovery

Original cloid: `0x3486c3b8e88add1a77175c9c5965350f`.

Result: **PROVEN_NOT_TRANSMITTED**, resolution `a6ea851efdd3c0e90b26b55587bdb60e3ba8449b782d1e39a94a01743acdd058`. This relies on the exact archived original source and its 2,194-test receipt/XML, original immutable request and nonce event, explicit failed final guard, compulsory original pre-HTTP claim path with no claim, two complete authoritative account histories/status reads and expiration of every possibly generated original signature. It is not a general rule that a flat account clears UNKNOWN.

Both account observations returned unknownOid, zero positions/orders and no historical fills. The new certificate is appended in an immutable table. The original row is still UNKNOWN, unchanged byte-for-byte at the row level; earlier event rows and nonce history are retained. Raw intent count is 1; actionable count is 0. Production recovery continues to see raw rows. Only the isolated qualification guard can apply this exact verified certificate. A changed original row, mismatched certificate/source or later contradictory claim fails closed. The finished old mandate is retained and cannot execute again.

Evidence: `certified_unknown_review/recovery_report.json`, `after_recovery_audit.json`, `before_qualification.sqlite`, `before_nonces.sqlite`, `source_before/`.

## 4. Regression and integrity

Full regression: **2,244 passed; zero failures, errors or skips**. Baseline 2,194 plus 50 new cases. Frozen strategy and Phase-0 checks passed before and after; source stayed `94446e6bd2dc911e852292b2809ccf24f898fed17f25c8a03ce5347f0b6829ec`. `signal_brain.py`, production UTC VWAP/EMA/ATR, 0.40% ATR floor, 15-bps production spread limit, 300 completed bars, Top-3, strategy state and PAPER/false configuration were preserved.

The new tests cover expiration during signing, genuine reacquisition, new positions/orders, read failure, no retimestamping, changed price/source/revocation, exact-action duplicate callbacks, a nonce followed by pre-HTTP rejection, IOC zero/partial/full fills, strict age and health gates, insufficient nontransmission evidence, immutable recovery certificates, actual HTTP start/uncertainty distinctions, repeated harmless observations, signer/account faults, appended restart logs, no automatic crash signing and shared-rate/receiver handoff. Existing partial/residual/exit-rejection/restart tests were included in the full suite. Failed intermediate focused logs remain preserved. Unit tests do not certify exchange stop acceptance or actual execution.

Receipt: `regression_release/test_receipt.json`; XML and complete output are alongside it.

Files changed in this task:
- `algo-trading-bot/test_qualification_freshness_repair.py` (new)
- `algo-trading-bot/exchange/certification_runtime.py`
- `algo-trading-bot/exchange/compliance_guard.py`
- `algo-trading-bot/exchange/delegated_qualification.py`
- `algo-trading-bot/exchange/emergency_qualification.py`
- `algo-trading-bot/exchange/execution_journal.py`
- `algo-trading-bot/exchange/persistent_qualification_watcher.py` (new)
- `algo-trading-bot/exchange/qualification_intent_recovery.py` (new)
- `algo-trading-bot/exchange/qualification_signing_boundary.py` (new)
- `algo-trading-bot/exchange/qualification_watcher.py`
- `algo-trading-bot/exchange/sdk_transport.py`
- `algo-trading-bot/exchange/single_position_guard.py`
- `scripts/inspect_qualification_intent.py` (new)
- `scripts/run_delegated_qualification.py`

## 5. Persistent observer operation

The bounded read-only soak passed with 30 observations, one confirmed BTC subscription, 7 actual WS book updates, no duplicate subscriptions and clean shutdown. Maximum recorded receiver gap was 1.001 seconds. The signer lease was healthy. It allocated zero nonces, created zero signatures and submitted zero actions. This is a short local engineering observation, not proof of long-running uptime or successful signing.

Before an entry is armed, the watcher can remain read-only through ordinary spread/depth/price ineligibility. It logs reasons, checks source, periodically reconciles the actual account, uses bounded receiver retries and the existing shared rate budget. At the single execution handoff, the public receiver stops, while the same lease and rolling rate/reserve counters are retained. A harmless unarmed build rejection can return to observation only if no durable runtime/intent/nonce attempt was created and the lease remains healthy. Armed, signed, transmitted or uncertain attempts never repeat. A crash restart preserves logs and cannot resume writes automatically. No scheduler or recurring task was created.

## 6. New mandate and current read-only account snapshot

New session: `6b8c95884fbf5fa22cddee4e18289121e4ee5c9b77c39e1de4d6875116217c52`. **Not accepted yet.** It references the above recovery certificate and new tested source. The old accepted session is finished and is not reused.

At 2026-10-14T16:20:14.941000+05:30, readiness was READY, unified mode, 1,000,000 test USDPR, approved API agent and ready reconciliation. Team wallet `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; API wallet `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. Exact par:BTC 1x CROSS/capacity checks passed. The account was observed without positions/orders and complete history had no fills. These are timestamped observations; execution must reacquire current evidence. The lease proves local ownership only; the sole-host assertion remains a human acknowledgment.

Mandate scope: TESTNET par:BTC BUY IOC exactly 0.0002 BTC, 1x CROSS, maximum opening 20 test USDPR, absolute BUY ceiling 100,000. Algorithm: fresh ask plus 10 bps, normalized down and capped by a fresh reviewed envelope, still executable and inside the 20-bps current tolerance. No enlargement. Exactly one entry, at most two exact-position reduce-only SELL IOC exits, one original-entry cancellation and four signed actions. Exits use fresh bid less 20 bps and never below reviewed bid × 0.98505 normalized up. Each fresh envelope expires after five minutes with 90 seconds reserved for management; the session ends **23:59 IST, 14 October 2026**, latest session entry **23:57:30 IST**. Earlier failures/uncertainty/revocation can stop it sooner.

The prepared example at 2026-10-14T16:20:17.017000+05:30 had bid 83343.0, ask 83355.0, mark 83411.0, oracle 83421.0, maximum BUY 83521, quantity 0.0002, ceiling 16.7042 test USDPR and exit floor 82098. This short-lived example is not the session's immutable execution order; the accepted algorithm creates a fresh bounded envelope later. Estimate at reviewed limits/floor: fees 0.029811420 test USDPR; conditional loss if fully closed at the floor 0.314411420 test USDPR. Neither number is a guarantee. Reviewed taker rate 0.00090 (0.09%). Actual fees and funding must come from exchange records.

## 7. Exchange entry received

**No new entry received.** This repair/preparation submitted no exchange orders or other signed actions. No new human acceptance or execution has occurred. The persistent signing watcher is prepared but is not currently running under a new mandate.

## 8. Genuine order/fill IDs

No new order ID or fill ID exists. The local original cloid is not an exchange fill. No `WHITELIST_TRADE_PROOF.json` is generated without actual team-account fills.

## 9. Position, P&L and emergency recovery

Account flat was observed during the fresh reads; it is not a perpetual claim about its future state. No actual qualification entry/closing fills exist, so realized qualification P&L is **not available**, not a fabricated zero.

**Protective-stop acceptance remains UNVERIFIED; no stop will be submitted.** Full-position IOC closure has narrowly scoped historical evidence, including a 0.0001 BTC residual, but future acceptance, execution price, sufficient liquidity and complete closure are not guaranteed. The isolated 50-bps spread/50% genuine L2 participation/20-bps allowances do not alter production's 15-bps scanner rule. The 20 USDPR opening cap is not a guaranteed loss cap; cross collateral, fees and funding remain relevant.

If order state is uncertain: stop entries; use the original cloid/oid to query orderStatus, team fills over the complete attempt interval, frontendOpenOrders and clearinghouseState with dex=par. Never resubmit blindly. Any resting entry remainder requires authorized cancellation and confirmed terminal status before closing. Within the still-valid mandate only: SELL the exact reconciled long quantity reduce-only at fresh bid minus 20 bps above the approved floor, maximum two exits. If expiry, failed exits, disconnect, missing history or residual uncertainty prevents authorized closure, halt with EMERGENCY_EXIT_REQUIRED and obtain separate exact recovery authorization or inspect/close manually. Do not exceed actual exposure to satisfy a minimum. Claim flat only after exchange positions/orders are zero and durable reconciliation agrees.

## 10. Qualification result and single next action

No genuine practice fill has been completed; qualification is **not yet satisfied** and organizer whitelisting is **not confirmed**. Protected controlled execution, practice readiness and live readiness remain false. Production remains PAPER/false and protection disabled.

Next: the human explicitly accepts this exact new session and all nine scope/risk acknowledgments. Only then can Codex start the bounded watcher and one permitted attempt. Scope/source/expiry changes require new approval.
