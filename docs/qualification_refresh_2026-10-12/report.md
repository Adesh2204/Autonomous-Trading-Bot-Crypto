# Fresh source-bound qualification proposal

**No signed action or qualification trade has been submitted. Exact human approval is required.** The previous proposal is expired and cannot authorize this order.

## Identity, account and source

- Registered team account / future SDK account_address: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`.
- Approved API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. The local key-derived public address matched; no signature or nonce was created. The local nonce lease rejected a second process and was released.
- The human explicitly confirmed this Mac is the only signing host. This is a human assertion supported by a local lease test; remote machines were not inspected.
- Fresh account reads: 2026-10-12T18:07:12.836387+00:00–2026-10-12T18:07:27.472661+00:00; funded unifiedAccount, 1,000,000 USDPR, approved agent with valid expiry, all ten par markets at 1x CROSS, no positions/orders, healthy clock and account request budget.
- Final preparation: 2026-10-12T18:07:52.776140+00:00–2026-10-12T18:09:06.243383+00:00. It independently restored its checksummed read-only account journal and finished with ready actual-account reconciliation and zero positions/orders. These are pre-trade observations, not a closed-trade certificate.
- Active source: `7dc796d83416fb1f68cf8c32e5d26db403c361d6470e889527bc67f617665339`; reliability policy: `1b8573d07a0f12f3653cf7b92f96c2120e8d61c3f210335ec850ba14ea582455`. No source/configuration change. The unchanged 1,682-pass full regression and XML checksum are verified against this exact source. Fresh Phase-0 and freeze checks pass; one whole file, eight methods and 32 parameters remain frozen. The suite was reused, not claimed as rerun.
- The existing pinned official SDK sets TESTNET URL, par-only market mapping and the team wallet as account_address. Its testnet signing domain and central exact-action permits remain enforced. No actual SDK signer transport was constructed during this read-only preparation. The [participant guide](https://perpetual-alpha26.github.io/docs/) documents approved API-wallet trading on the team account.

## Exact proposed order and limits

Proposal identity: `2047be2789f5ba3433955ca584257243fec1e5fb3cd5f2fb01b9cb19a6f954bb`.

| Item | Exact proposal |
|---|---|
| Venue / leverage | TESTNET par / par:BTC / 1x CROSS |
| One entry only | BUY LIMIT IOC 0.0003 BTC at 82491 USDPR per BTC or better |
| Maximum entry notional | 24.7473 USDPR; workflow ceiling 25 USDPR |
| Reviewed bid / ask | 82350.0 / 82450.0 |
| Reviewed mark / oracle | 82388.0 / 82470.0 |
| Spread / best bid and ask quantities | 12.13592233009708737864077670 bps / 0.0308 BTC each side |
| Actual long-side available margin | 1000000.0 USDPR |
| Immediate exit estimate | SELL actual held quantity, reduce-only IOC; reviewed initial limit 82186 |
| Absolute approved SELL limit floor | 81120; no exit may be submitted below it |
| Fee estimate | 0.09000% taker per fill; entry 0.022272570, immediate exit 0.022190220, combined 0.044462790 USDPR |
| Estimated loss at reviewed immediate limits | 0.135962790 USDPR, excluding funding; not guaranteed |
| Estimated loss if all exposure exits at the floor | 0.455474970 USDPR, excluding funding; not a guaranteed cap |
| Latest time for human approval of this snapshot | 2026-10-12T18:13:04.002000+00:00 / 2026-10-12T23:43:04.002000+05:30 |

Objective rule: require fresh two-sided executable liquidity, 1x CROSS, margin, flat-account reconciliation and every possible lot residual close check. Generate the fixed entry limit from ask × 1.0005 using runtime rounding and size from floor-to-lot(25 / max(limit, mark)). Select the smallest-spread eligible market among BTC/ETH/HYPE. This is the existing algorithmic qualification rule, not a manual price choice or a VWAP strategy signal.
Qualification spread limit is at most 50 bps and needs explicit acceptance. The current BTC observation is within the production 15 bps ceiling, but this isolated proposal still permits up to 50 bps. Production keeps 15 bps, ATR 0.40%, 300 completed UTC bars, Top-3 and all frozen logic.
The single entry is never repeated or enlarged. Immediately reconcile actual team fills, order status and position. Exit the exact actual residual, opposite side and reduce-only IOC, using a fresh bid × 0.998 subject to the fixed exit floor. At most two exit attempts and five signed actions total are permitted. Only cancellation of this workflow’s own orders is allowed; no account administration. Unknown status never earns a blind retry.

## Small positions and unprotected risk

BTC lot is 0.0001. All three possible whole-lot remainders were assessed. One lot is sub-$10 and maps to the V8.6 narrow historical SELL full-close shape (original public order 62228843959); two/three lots exceed $10 at the proposed floor and retain the ordinary minimum checks. That historical close belongs to another account. Its final zero is fill-derived, not an independent historical position snapshot, and cannot guarantee future acceptance or fills.
**No protective stop will be submitted.** Sub-$10 stop acceptance/coverage remains independently unverified. Closing evidence cannot certify a stop. If the exit is rejected, liquidity disappears, connectivity fails, status is uncertain or price crosses the exit floor, a position can remain unprotected. Cross margin is shared collateral; the small entry principal is not a guaranteed total-loss cap, and fees/funding can accumulate. The normal protection and controlled-execution flags remain FALSE.

## Emergency recovery plan

1. Keep all new entries locked. Preserve the consumed-entry marker, durable intent ID, client order ID and account checkpoint; do not delete/reset state or restart to repeat the trade.
2. Read orderStatus by the saved order/client ID, team userFills, frontendOpenOrders and par clearinghouseState. Match the actual fill quantity, direction, fees and remaining position against the journal. If reads fail or disagree, report EMERGENCY_EXIT_REQUIRED and retain UNKNOWN/exposure truth.
3. Only a definite, freshly reconciled residual can use an unconsumed authorized exit attempt while approval is valid and all price/quantity/rate guards pass. Close exactly that residual. No size top-up, no new entry, no reversed position and no blind retry of an uncertain exit.
4. After expiry, exhausted attempts or a breached price floor, stop writes and report the exact residual/order uncertainty for the operator. Obtain a new explicit recovery decision for anything outside the original limits. No claim of flat until fresh exchange positions/orders and accounting confirm it.
5. When fills are verified, record order ID, fill ID, actual notional/time, fees/funding and reconciliation in WHITELIST_TRADE_PROOF.json. Actual fill proof and final-flat proof are separate. Organizer whitelisting is confirmed only by organizer evidence, not inferred from this report.

## Market exclusions

| Market | Result |
|---|---|
| par:BTC | Eligible for this experimental risk decision |
| par:ETH | QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL |
| par:HYPE | QUALIFICATION_FRESH_FLAT_ACCOUNT_BOOK_REQUIRED |

## Approval and later scored checklist

Approve only this proposal identity and exact size/price/exit limits, explicitly accepting no stop, possible unprotected residual/manual recovery and the qualification-only 50 bps spread ceiling. Confirm the shown wallet identities. Sole signing-host confirmation is already recorded and will not be requested again. The approval template remains unfilled, so no trade is authorized.
A changed/expired quote is not automatically substituted or repriced. Fresh readiness and exact-action checks repeat before a future approved order. There is no autonomous or repeated activation.
`scored_pa_usdp_checklist_DRAFT.md` is staged separately for review after the qualification attempt. The pa/USDP announcement is user-reported; the public practice guide still describes par/USDPR. No pa data probe, target switch, collateral transfer, scored state or new architecture was created. Record the attempt outcome first, then follow that read-only checklist.

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
PROTECTION_ENABLED=FALSE
SOLE_SIGNER_HOST_CONFIRMED=TRUE
QUALIFICATION_EXECUTION_AUTHORIZED=FALSE
ACTUAL_PRACTICE_FILL_VERIFIED=FALSE
ACTUAL_PROTECTION_READY=FALSE
CONTROLLED_EXECUTION_READY=FALSE
ORGANIZER_WHITELISTING_CONFIRMED=FALSE
PRACTICE_READY=FALSE
LIVE_READY=FALSE
```
