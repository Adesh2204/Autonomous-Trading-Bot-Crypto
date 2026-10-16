# Team Anchorium — fresh qualification approval review

**Preparation only. No signature or exchange order was submitted. Approval is unfilled.**

## Exact current proposal

Proposal ID: `d5141d1e2522557ffe91c1d5143d9247ccfc383bcabf5cd342a3edb8f457e11e`.

Observed 2026-10-12T23:50:27.795000+05:30. Approve by **2026-10-12T23:55:27.795000+05:30**. Expiry or a changed quote never authorizes automatic repricing.

| Item | Exact limit / observation |
|---|---|
| Venue | Hyperliquid TESTNET / par:BTC / 1x CROSS |
| Entry, once only | BUY LIMIT IOC 0.0003 at 82511 USDPR per BTC or better |
| Maximum entry notional | 24.7533 USDPR; hard opening-notional ceiling 25 USDPR |
| Reviewed bid / ask | 82319.0 / 82470.0 |
| Mark / oracle | 82414.0 / 82504.0 |
| Spread | 18.32646596556809010310154197 bps |
| Best bid / ask quantity | 0.0611 / 0.1825 BTC |
| Long-side margin / maxTradeSz | 1000000.0 USDPR / 12.1338 BTC |
| Immediate exit at reviewed bid | SELL actual position quantity, reduce-only IOC, limit 82155 |
| Absolute SELL price floor | 81089; no exit submitted below this floor |
| Fee estimate | 0.09000% per taker fill; entry 0.022277970, immediate exit 0.022181850, total 0.044459820 USDPR |
| Estimated loss at immediate limits | 0.151259820 USDPR, excluding funding |
| Estimated loss at floor | 0.470772000 USDPR, excluding funding; not guaranteed |
| Attempt bounds | One entry, at most 2 exits, at most 5 signed actions including own-order cancellations |

Objective rule: fresh executable book and account; require flat reconciliation, margin, 1x CROSS, two-sided depth and every possible whole-lot residual close assessment. Set BUY limit to runtime-rounded ask × 1.0005; round quantity down to lots from 25 / max(limit, mark). Select the smallest-spread eligible BTC/ETH/HYPE market. This is the tested qualification rule, not a discretionary price or a frozen VWAP signal.

Qualification-only spread ceiling is 50 bps and needs explicit acceptance. Production keeps 15 bps, ATR 0.40%, 300 completed UTC bars, Top-3 and all frozen strategy/state rules.

## Actual account, signer and source

- Registered team account / future SDK account_address: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`.
- Approved API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. Local key-derived address matched without signing or allocating a nonce. Local lease rejected a second process; it was released.
- The human already confirmed this is the sole signing host. Remote machines were not independently inspected; the answer is not trade approval.
- Fresh full account check: 2026-10-12T18:19:53.795446+00:00–2026-10-12T18:20:07.348688+00:00. Unified account, 1000000.0 USDPR, API approval valid until timestamp 1806859924898, all ten markets 1x CROSS, no positions/orders, healthy clock and rate budget.
- Proposal run: 2026-10-12T18:20:16.053023+00:00–2026-10-12T18:21:30.007295+00:00. Final actual-account reconciliation ready and flat observed. Both separate read-only journals reopened successfully; SQLite and checkpoint checksums pass, action rows zero. This is pre-trade flat evidence, not round-trip evidence.
- Source hash `7dc796d83416fb1f68cf8c32e5d26db403c361d6470e889527bc67f617665339`; policy hash `1b8573d07a0f12f3653cf7b92f96c2120e8d61c3f210335ec850ba14ea582455`. No source/configuration changes. The existing 1,682-pass, zero-failure regression XML matches this source. The full suite was reused, not rerun. Fresh Phase-0 and freeze checks pass.
- Existing SDK 0.24.0 transport uses TESTNET endpoint, par-only asset mapping, the team wallet as account_address and approved API signer, with exact permits and source/nonce/account guards. No actual SDK signer transport was constructed in this preparation.

## Verified close scope and unverified protection

Runtime BTC lot: 0.0001. All 3 possible whole-lot residual sizes were assessed at the fixed floor. Below-$10 residuals use only the V8.6 historically observed exact full-position SELL shape; ordinary entry minimums remain $10. One-lot BTC SELL evidence includes order 62228843959 on another account. Its zero residual was derived from matched fills, not an independent historical position snapshot; future acceptance and fills are not guaranteed.

**Protective-stop acceptance and position coverage remain UNVERIFIED. No stop will be submitted.** Inherited proposal fields stop_trigger/stop_limit are compatibility price bounds, not accepted stop orders. Normal ACTUAL_PROTECTION_READY and CONTROLLED_EXECUTION_READY remain FALSE.

If an exit is rejected, partially filled, blocked by its price floor, disconnected or uncertain, some exposure can remain unprotected. Cross margin uses shared account collateral. A 25 USDPR opening-notional cap is not a guaranteed total-loss cap; fees/funding and prolonged unresolved exposure can exceed estimated losses. Closing evidence alone does not validate protection.

## Exit and emergency recovery

1. Consume the one-entry marker durably before transmission; never repeat or enlarge an entry, including after timeout/restart. Reconcile actual team userFills, order status, orders and position.
2. Submit SELL reduce-only IOC for the exact freshly reconciled held quantity. Generate price from fresh bid × 0.998 using runtime precision; keep it at or above the fixed floor. At most two bounded exits; no over-sizing, exposure top-up or reversal.
3. An uncertain order receives bounded read-only status/fill/position reconciliation, never a blind resubmission. Retain client ID, exchange ID if known, consumed attempt and account checkpoint. Lock all new entries.
4. If uncertainty, residual exposure, expired permission, exhausted attempts or breached floor prevents a permitted close, halt writes and report EMERGENCY_EXIT_REQUIRED with exact residual/order uncertainty. A restart is read-only recovery, not permission to resume entry. The operator must explicitly authorize any recovery outside the existing limits; do not erase state.
5. Verify actual entry/exit fills, fees/funding and flat positions/orders. Generate real WHITELIST_TRADE_PROOF only from actual team-account exchange evidence. A fill and a flat position are separate claims; organizer whitelist confirmation needs organizer evidence.

## Market rejections and approval

| Market | Preparation result |
|---|---|
| par:BTC | Eligible for explicit experimental risk review |
| par:ETH | QUALIFICATION_BOTH_SIDES_DEPTH_EXCEEDED |
| par:HYPE | QUALIFICATION_FRESH_FLAT_ACCOUNT_BOOK_REQUIRED |

Approval must name this exact proposal ID and its size/entry/exit/attempt limits, confirm the shown wallet identities, and explicitly accept no protective stop, possible unprotected residual/manual recovery and the isolated 50 bps ceiling. Sole-host confirmation is already recorded. All authorization-template fields remain unfilled; future execution refreshes exact-action market/account/fee/clock checks and refuses changed or expired limits.

No autonomous trading, scheduled task, transfer, leverage change or scored pa/USDP switch was performed.

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
PROTECTION_ENABLED=false
QUALIFICATION_EXECUTION_AUTHORIZED=false
ACTUAL_PRACTICE_FILL_VERIFIED=false
ACTUAL_PROTECTION_READY=false
CONTROLLED_EXECUTION_READY=false
ORGANIZER_WHITELISTING_CONFIRMED=false
PRACTICE_READY=false
LIVE_READY=false
```
