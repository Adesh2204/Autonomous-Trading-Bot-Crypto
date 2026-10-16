# Team Anchorium — delegated testnet qualification

Status: implementation/full regression PASS; one genuine human-authorized workflow attempted and halted before HTTP order submission. No qualifying fill. Two subsequent exchange observations confirm the team account flat. Local UNKNOWN order record remains locked.

## What changed

The old route required a human approval for each five-minute proposal. The new isolated `DELEGATED_TESTNET_QUALIFICATION_V1` route asks for acceptance of one immutable session mandate, including its source hash, two public wallet identities, objective price/exit rules, limits and disclosures. It keeps the original fixed-price and V2 per-proposal routes intact. No human price approval is fabricated.

Exactly 0.0002 BTC BUY IOC on Hyperliquid TESTNET `par:BTC`, 1x CROSS, is allowed only after genuine acceptance. The independent opening cap is 20 TEST USDPR, with an absolute maximum BUY price of 100,000 USDPR/BTC. The old 1,000 TEST USDPR outer policy is unchanged and cannot expand this session. Entry quantities never increase or shrink to satisfy an exchange minimum. There is one entry attempt, up to two exact actual-position reduce-only IOC exits, one original-entry cancellation and four signed actions. A rejected or uncertain transmission consumes the entry.

The session ends at 23:59:00 IST on 14 October 2026. New entry needs a 90-second recovery reserve. Each derived envelope also expires within five minutes of observation. Fresh ask plus 10 bps selects the IOC limit, normalized down and capped by the reviewed envelope and the 20-USDPR ceiling. Final signing still requires the immutable wire price to be executable and within the fresh ask-plus-20-bps bound. A legitimate sudden price move can still reject the order.

The floor for SELL exits is the reviewed bid times 0.98505, normalized up. Actual exit requests use fresh bid minus 20 bps, never below that floor, and exactly the freshly reconciled remaining position. Closing and stop protection are distinct: historical one-lot close observations do not prove stop acceptance or guarantee future closing liquidity.

## Safety and recovery

Global PAPER/false settings, disabled protection, the frozen strategy and `signal_brain.py` remain unchanged. Fresh funded/unified account truth, API approval, local signer identity and nonce ownership, 1x CROSS, flat positions/orders, margin, metadata/precision, oracle checks, genuine depth and rate/clock health remain mandatory. This experiment does not require a VWAP strategy signal and is excluded from strategy profitability statistics.

The authority reads the genuine acceptance file again at signing boundaries. Removed/changed acceptance, local revocation, expiry, source/policy changes or wrong identities prohibit signing. A shared durable runtime token prevents a restarted process from resuming writes. The account journal's permanent entry-consumed control prevents another entry even if a new price/proposal is generated. SIGINT/SIGTERM revokes the local mandate; revocation can also be recorded without any exchange action. Revocation may leave an already filled position requiring separately approved/manual recovery.

Before any transmitted or durable attempted order, market-only preflight rejection may lead to further read-only observation within the accepted session window. Account/signing failures halt. A started execution workflow is one-off: it does not automatically restart after failure. Partial or unknown outcomes never authorize a replacement entry. Closing rejection, unknown state or remaining exposure produces `EMERGENCY_EXIT_REQUIRED`. Preserve the journal, original client/order IDs and actual fills; query the registered account before any recovery action. Never infer flat from local state.

## Disclosures the human must accept

No verified protective stop will be submitted. Exposure is unprotected. Exact reduce-only exits can reject, fill partly or become uncertain. Manual recovery may be necessary. Twenty TEST USDPR is an opening-exposure cap, not a guaranteed loss cap; fees, funding and cross collateral remain relevant. Qualification spread is 50 bps, genuine L2 participation is 50%, and entry/exit allowances are 20 bps; production strategy/risk rules remain unchanged, including the 15-bps scanner spread ceiling. Public depth can disappear. A genuine programmatic practice fill is evidence, not organizer whitelist confirmation.

## Files

- `algo-trading-bot/exchange/delegated_qualification.py`: immutable mandate, explicit acceptance, revocation, narrow scope and durable authority.
- `algo-trading-bot/exchange/emergency_qualification.py`: explicit delegated capability at the existing builder/transport/final validator, keeping old exact approvals intact.
- `scripts/run_delegated_qualification.py`: read-only preparation, accepted-session observation/one-off execution, local revocation, truthful fill/flat evidence.
- `algo-trading-bot/test_delegated_qualification.py`: 79 offline scope, expiry, revocation, ownership, stale/moving quotes, composition, partial-fill, rejected-exit, duplicate, restart and orchestration cases.

## Tests and evidence

The 79 new tests and 160 existing qualification/price tests passed. Full regression: **2,194 passed, zero failures, errors or skips**, including the entire 2,115 baseline. Source-bound receipt and XML agree; source hashes match before/after. Phase-0 and frozen strategy checks passed before/after. Offline tests use ephemeral signers and synthetic exchange records with network submission forbidden. They do not verify actual team fills or stop acceptance. Original journals and earlier evidence are preserved.

`WHITELIST_TRADE_PROOF.json` is written only if the existing actual-transport proof classifier verifies reported team-wallet fills. Zero/rejected/uncertain unverified outcomes receive `NO_FILL_VERIFICATION.json`; actual entry fills, final account flatness and organizer whitelisting are independent claims.

Authoritative API references checked on 14 October:
- [Hyperliquid exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint): IOC and signed expiry.
- [Hyperliquid error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses): ordinary minimum and exchange rejections.

## Read-only preparation before acceptance

Session `47fc3e21b13b4081e1c226c7e365d1d42798f206e1e80547c1c909c886511ee7` was prepared for the human acceptance decision. Source: `ed9022e9513832f220786ca9850e49834541607935583c1c5aa0a1a635546825`. Read-only account observation at 2026-10-14T13:20:39.102000+05:30 confirmed 1,000,000 TEST USDPR, unified mode, approved matching API signer, all ten 1x CROSS settings, no positions/orders, ready actual account reconciliation, healthy clock/rates and local exclusive signer lease. The user's sole-host statement remains necessary because a local lease cannot inspect other hosts. Two clean read-only checkpoint snapshots and their checksums were independently verified. No qualification journal actions, actual wallet signatures or exchange submissions occurred.

The current example is **not an exact-price authorisation or an order**: 0.0002 BTC, reviewed max BUY 83,585, exposure 16.7170 TEST USDPR, exit floor 82,073, observed spread 12.1149 bps, taker fee 0.09%, estimated round-trip fee 0.029818440 and conditional floor-close loss 0.332218440 TEST USDPR. Those prices expire and will be replaced by the same objective algorithm only after valid session acceptance. They are not promised future execution prices. The durable mandate's independent 20-USDPR and 100,000-price ceilings remain fixed. Mandatory market/account/signing checks will be rerun before actual execution.

Codex will record acceptance itself only after the human explicitly accepts this exact session and all disclosures. Session expires at 23:59 IST today; new entry cutoff is 23:57:30 IST plus every derived envelope's own reserve/expiry. Without acceptance, signing remains unavailable. No recurring task has been created. No genuine fill proof or organiser confirmation exists.


## Authorized attempt and halt

The human explicitly accepted session `47fc3e21b13b4081e1c226c7e365d1d42798f206e1e80547c1c909c886511ee7` and all nine acknowledgments. Acceptance was recorded at its genuine current time; no per-price human approval was fabricated. One fresh read-only envelope `3b744e33e2de25c1afd6764eac3268ba8d51ac8ef905200e62230bc4a2261ddf` was selected. Its maximum BUY was 83,585 and floor 82,073. The actual locally validated entry request was BUY 0.0002 BTC IOC at **83,513**, notional **16.7026 TEST USDPR**.

The price envelope, ordinary minimum, leverage, market depth and account checks passed. During the repeated final signing checks, the retained readiness snapshot failed `P0_FRESH_RECONCILED_FLAT_ACCOUNT_REQUIRED`. The final diagnostic shows every price-rejection condition false: bid 83,379, ask 83,430, mark 83,419, oracle 83,501 and current 20-bps maximum 83,596. The book, mark and account timestamps remained within five seconds; the immutable readiness snapshot had passed the previous callback. Its readiness-age crossing is the remaining time-varying gate condition. The exact readiness observed_ms was not persisted, so no invented exact age is reported.

Local SDK signing reached durable nonce allocation. It is incorrect to claim zero signature creation; the durable journal does not count cryptographic signatures. The failure occurred before the compulsory durable `claim_transmission` and its downstream HTTP POST. No transmission history or entry-consumed control exists, so **zero exchange HTTP order submissions are established by the tested transport path**. The generic executor conservatively stored the prepared client-order ID as UNKNOWN. This local classification was not cleared or rewritten.

The runtime returned `EMERGENCY_EXIT_REQUIRED`, halted and durably finished the session. Client-order ID: `0x3486c3b8e88add1a77175c9c5965350f`. No exchange order ID exists. There was no retry, cancellation, exit or scope enlargement. The mandate cannot sign another entry, even though its calendar end is later.

Independent read-only recovery then obtained two authoritative account snapshots: zero positions, zero open orders, no fills since acceptance, `orderStatus=unknownOid` for the original client-order ID, and ready observer reconciliation. The account is confirmed flat at those observations; that does not resolve the deliberately retained local UNKNOWN intent or certify the execution route. Their timestamps/raw responses are saved in `post_failure_read_only/report.json`.

No `WHITELIST_TRADE_PROOF.json` was created. `NO_FILL_VERIFICATION.json` preserves the failed attempt evidence. Team qualification/organizer whitelisting remains unconfirmed. No strategy profitability or trade P&L is claimed. Protection remains unverified, production PAPER/false unchanged, and unrestricted trading disabled.

## Next safe action after this halt

Review the original UNKNOWN record and repair the retained readiness snapshot/final-signing latency while keeping every five-second freshness guard. Do not delete/reset the journal, reuse the finished mandate, resubmit the original order or infer authorization for another entry. Any future attempt requires its own explicit valid authorization after that review and source-bound tests.
