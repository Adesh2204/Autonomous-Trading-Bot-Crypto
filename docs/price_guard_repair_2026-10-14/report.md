# Team Anchorium — P0 price-guard repair

The repair is implemented and verified offline. **2,115 tests passed; zero failures, errors or skips. No actual order has been submitted by this repair.** The frozen strategy and PAPER/false locks remain intact. Protected execution is still unverified.

## Exact root cause and historical limit

The old approval fixed the IOC limit at the reviewed ask plus 20 bps. The later `check_entry` comparison rejected that fixed value when it exceeded `normalize_price(fresh_ask × 1.002, BUY)`, or could no longer reach the fresh ask. That comparison shared one error code with minimum and notional conditions. A small ask fall could therefore cause a preventable stale-price rejection. Old authorization prohibited changing the price, so repricing it would have violated approval.

For the previous 83,610 limit, a deterministic fresh ask of 83,442 gives a normalized 20-bps maximum of 83,608. The old price fails that comparison. A normalized fresh ask-plus-10-bps price is 83,525, which fits the unchanged 83,610 ceiling and current tolerance. This is a mathematical/offline reproduction, not a recovered historical market observation. The previous failed quote was not persisted, so its exact ask and branch remain unknowable from saved evidence.

## Persistent diagnostics

`P0_ENTRY_PRICE_GUARD` journal events now record bid, ask, mark, oracle, reviewed limit/cap, actual selected limit, current 20-bps ceiling, quantity, minimum/outer/selected notionals, proposal/book/mark/account/evaluation timestamps, exact Boolean price predicates and the returned guard result. They include public proposal/source hashes under supported public-hash fields. No private key, signer object, signature or signed payload is logged.

The existing launcher exports these records to `price_guard_diagnostics.json`, including a build failure before the runtime exists. A failed build also gets a plain execution report. Missing historical values are not reconstructed or invented.

## Corrected authorization

V1 (`FIXED_LIMIT_V1`) retains its original JSON compatibility, proposal identity/hash and exact-limit behavior. Optional new envelope fields must remain empty for fixed proposals. Expired/source-invalid legacy approvals remain blocked.

V2 (`BOUNDED_FRESH_IOC_V2`, policy `ANCHORIUM_P0_BOUNDED_IOC_V2`) applies only to the isolated BTC BUY IOC test. Its proposal commits to an exact quantity, equal quantity ceiling, a maximum BUY price and exact selected opening notional ceiling. The reviewed maximum remains the existing ask-plus-20-bps limit; it is not automatically widened. The policy hash and explicit bounded-price approval acknowledgment differ from V1.

After approval, the executor derives `min(fresh ask × 1.001, approved maximum BUY price, approved notional ceiling / fixed quantity)`, rounded down using runtime exchange precision. The 10-bps buffer leaves room inside the still-enforced 20-bps live tolerance; it does not guarantee a fill. The selected order must reach the current ask, fit every approved cap, satisfy the ordinary minimum, match actual asset/lot metadata and remain valid at signing. It never increases or rounds away the approved quantity.

The request is selected from the existing mandatory fresh validation context before the one durable entry is reserved. The journal stores the actual selected price. The central signing permit binds its callback to that actual request; all final signing/transport checks still validate the immutable signed wire against new public prices. It cannot be edited after reservation/signing. If the market moves outside its remaining live tolerance, the order is blocked. A durable duplicate returns the original stored price/outcome rather than selecting a second order.

## Limits retained

1x CROSS; ordinary $10 minimum; outer 1,000 TEST USDPR cap; exact smaller selected price/quantity/notional bounds; one global exposure; one entry; two bounded reduce-only IOC exit attempts; one original-entry cancellation; maximum four signed actions; five-minute proposal/approval expiry and 90-second entry recovery reserve. Runtime precision, source/regression identity, nonce/account leases, API budgets, account reconciliation, fresh book/mark/oracle checks, 50-bps qualification spread, 50% genuine L2 participation, 50/100/150-bps reference checks, exact one-lot BTC residual scope and approved exit floor remain mandatory.

Production VWAP/EMA/ATR/state logic, 300 completed bars, 0.40% volatility floor, 15-bps production spread and Top-3 are unchanged. No native minimum exemption, leverage/account administration, recurring task or unrestricted trading was added.

## Latency and recovery

Source/receipt checks, market observation, all-ten leverage inventory, signer derivation/lease review and expensive read-only preparation occur before approval. V2 removes one redundant early flat-position/open-order pair: the mandatory provider bundle immediately reads/reconciles those same fields, and both central and signing-boundary flat checks remain. It selects its price late from that fresh context. No account, history, nonce, market, rate or source safety check is disabled to improve speed.

Small native protective-stop acceptance and lifecycle remain UNVERIFIED. No stop is submitted. Partial fills are reconciled from actual team fills and current positions. Supported exact residual closes retain their price floor and two-attempt limit; they can still be rejected or lack liquidity. A rejected or uncertain exit preserves exposure and requires operator escalation. An uncertain entry is never blindly resubmitted. Restart does not resume an entry automatically.

## Tests and modifications

- [algo-trading-bot/exchange/emergency_qualification.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/emergency_qualification.py>)
- [algo-trading-bot/exchange/hyperliquid_execution.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/hyperliquid_execution.py>)
- [algo-trading-bot/exchange/compliance_guard.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/compliance_guard.py>)
- [scripts/run_emergency_qualification.py](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/run_emergency_qualification.py>)
- [algo-trading-bot/test_qualification_price_guard.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_qualification_price_guard.py>)

Full baseline 2,046 plus 69 new tests = **2,115 passed**. Coverage includes asks moving up/down, maximum-price clamping, out-of-envelope rejection, spread/depth changes, independent mark/order notional limits, quantity caps, precision/mapping, minimum-order failure without enlargement, approval/time/source policy expiry, stale quotes, actual central SDK wire validation, zero/partial/full fills, rejection/uncertainty, partial residual closure, rejected exits, duplicate prevention, restart, complete secret-free diagnostics, explicit V2 approval and no-fill artifact handling. Offline SDK tests use ephemeral fixture keys and forbid exchange HTTP; they do not certify a real fill or stop.

Development failures are preserved separately. They exposed the need to pass the actual selected request through the central permit's own callback, plus fixture formatting/zero-spread expectations. Final focused validation passed 323 tests, and the final new set passed 69. Full regression is the authoritative final receipt, with matching before/after source hashes and successful Phase-0 and strategy-freeze checks before and after.

Full active source: `7476ad9152bb0452fbf24aa3fdeed3822ff0faf3e5bf5c1badf74f55f2eacdf7`. Previous source: `90c913950d7c7f23bfa176612356e0995d9fef5976be54fc449695b8cc1bf882`. Brain remains `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`. The pre-existing failed-build qualification journal was backed up without reset, and its original actions remain zero. Earlier evidence, nonce records and expired approvals were preserved.

## Proposal and remaining decision

Proposal `4e705570d6fc52d3b161cac40c5d99b7ab4bada1580b77b0de535e3a4e80b6ff` is a read-only, source-bound Hyperliquid TESTNET `par:BTC` LONG envelope. Quantity is fixed at 0.0002 BTC; maximum BUY price 83664; selected opening notional ceiling 16.7328 TEST USDPR, inside the unchanged 1,000 outer cap. Exit floor 82246; one entry, up to two exact reduce-only IOC exits, one cancellation and four signed actions. Approval expires 2026-10-14T11:51:32.817000+05:30; entry needs at least 90 seconds remaining, making its latest transmission 2026-10-14T11:50:02.817000+05:30. Final checks can still block it.

The account observation confirmed funded/unified mode, approved API signer, all ten 1x CROSS settings, zero positions/orders, healthy reconciliation/clock/local signer ownership, and two clean read-only checkpoints. Sole-host status includes the user's prior/current assertion; the local lease cannot independently inspect other machines. There is no signed action or fill from preparation.

No stop is verified or submitted. The new bounded-price acknowledgment is required in addition to the existing qualification risk acknowledgments. Codex must populate the approval file only from a genuine timely human response naming/accepting this exact envelope. Never backdate, reuse an expired approval, extend the cap or invent a fill.

`ACTUAL_PROTECTION_READY=FALSE`, normal protected `CONTROLLED_EXECUTION_READY=FALSE`, `ACTUAL_FILL_VERIFIED=FALSE`, organizer whitelist confirmation unverified. Readiness of this explicitly accepted no-stop experiment is separate from production/protected readiness. After genuine exact authorization, Codex may run only the bounded workflow, verify actual team-wallet fills/fees/positions and write `WHITELIST_TRADE_PROOF.json` only for a genuinely verified fill. Zero/rejected fills produce `NO_FILL_VERIFICATION.json`. No automatic repeat is authorized.

## Entry-window closure

At 2026-10-14T11:51:20.283000+05:30, the proposal entry deadline 2026-10-14T11:50:02.817000+05:30 had passed without a human approval. This hash is no longer usable for entry, even if its general authorization-expiry timestamp is later. No approval file, signing runtime, signature, exchange order or whitelist fill proof was created. The saved read-only proposal is historical evidence. No new proposal was substituted automatically. A future attempt requires a fresh bounded envelope and a new exact human decision.
