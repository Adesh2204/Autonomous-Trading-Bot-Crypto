# Existing BTC SELL guard repair and new approval request

Status: **AWAITING GENUINE NEW EXACT APPROVAL**. No new SELL attempt, signature, nonce allocation, exit order ID or exit fill ID. Remaining position: **0.0002 BTC LONG** at the authoritative 15 October 2026 21:41:23 IST read; zero open orders. This is TESTNET par, with TEST USDPR accounting.

The isolated `require_settled_exit_orders` barrier now uses the existing verified qualification view. It records the exact certificate checksum and assessment reason. The raw UNKNOWN row and immutable certificate remain intact; missing, wrong, tampered or contradicted certificates and unrelated unresolved orders remain blocked. Production raw journal, current-intent handling, stop settlement, account, nonce, source, signer and duplicate checks retain their existing behavior.

Certificate: `a6ea851efdd3c0e90b26b55587bdb60e3ba8449b782d1e39a94a01743acdd058`. Original cloid: `0x3486c3b8e88add1a77175c9c5965350f`. Reason: Verified original mandatory pre-HTTP claim path, explicit final guard failure, no claim/HTTP record, matching nonce and two complete fresh account histories.

Validation: **2385 passed, 0 failed, 0 errors, 0 skipped** in the complete regression, including 22 new targeted cases. Phase-0 and frozen strategy passed before and after; PAPER/false remains enforced. `signal_brain.py` and both genuine BUY proofs are byte-identical. Source: `abc36e4a6eb6b61994b3bdc22ce05700e965afe44be697f6a0345e8c5f98f8c0`. XML SHA-256: `39e5dc3c8042575d5a401ca4b68655c04908cdbdddd8e2a6ffa76d883ac110c9`. The old source receipt cannot authorize this changed source. Both databases report `ok`; retained checkpoints verify, and the actual nonce history is unchanged. The existing handled halt has not been relabeled a certified clean shutdown.

[Repair diff](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_guard_repair_2026-10-15/repair.diff>) · [Source-bound test receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_guard_repair_2026-10-15/regression_release/test_receipt.json>) · [Detailed evidence summary](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_guard_repair_2026-10-15/final_summary.json>)

## Current authoritative evidence

- Original BUY: 0.0002 BTC at 81512; order 62755970305, fill 800659111758533; cost 16.30240 and entry fee 0.014672 TEST USDPR. Fresh complete history still contains this BUY and no SELL.
- Bid / ask: 82416.0 / 82428.0; spread 1.455921962582805561621897066 bps. Book age at preparation: 692 ms.
- Genuine bid depth at or above the prepared 82334 limit: 0.0047 BTC; required 0.0002 BTC with maximum 50% participation. Prepared limit is normalized fresh bid minus 10 bps, bounded by the approved floor; final allowance cannot exceed 20 bps.
- Actual reported net funding: +0.000527 TEST USDPR across 12 events. Observed account-event net so far: -0.014145 TEST USDPR; this excludes the still-open price exposure and is not round-trip profit.
- Conservative exit fee: 0.27000% (6x base because current deployer scale is absent). Approval rejects a computed fee above 0.30%.
- Updated conservative net break-even: 81803.59470570540459239947859; minimum SELL floor including 0.001 TEST USDPR profit buffer: **81809**.
- Conditional estimate at observed bid: +0.1221503600 TEST USDPR; at prepared limit: +0.105794640. Neither is realized profit. Final signing must refresh all evidence.

## New exact mandate

Identity: **`0cbb944cc527cd46c90ac8c27ef8340058b141c69d8141dc637f9f48050d0f4b`**

[Exact mandate JSON](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_guard_repair_2026-10-15/fresh_proposal/mandate.json>) · [Fresh preparation evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_guard_repair_2026-10-15/fresh_proposal/proposal.json>)

Team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; API wallet `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. TESTNET `par:BTC` **SELL only, exactly 0.0002 BTC, reduce-only IOC**, only while fresh authoritative evidence still proves that exact LONG. One closing order attempt; no BUY, enlargement, leverage change, cancellation, replacement or retry.

Floor **81809 USDPR/BTC or a higher recalculated profit floor**; minimum conservative expected net **+0.001 TEST USDPR**. Maximum computed exit fee **0.30%**, spread **50 bps**, genuine depth participation **50%**. Window: **10 minutes from genuine acceptance**, with no new closing path in the final 15 seconds and no extension. Genuine acceptance must arrive by **15 October 2026 21:46:23 IST**. The prior `fbad5fe9…deb1a5` mandate is consumed, revoked and never reused; its heartbeat remains paused.

Your Phase 4 explicitly requires approval of this new exact mandate before signing. Approval also confirms the two wallet identities and this Mac as sole signing host, exact-position SELL-only scope, one attempt/no retry, unprotected partial/failed-exit risk, no guaranteed profit, and the bounded window/no extension. No acceptance file has been created.

There is **no verified protective stop**. A partial, rejected, unfilled or uncertain SELL may leave exposure requiring a new human decision. Mac/app/power/internet availability is required for supervision. After an actual SELL, completion requires actual closing fills plus two authoritative flat/zero-order readbacks and actual fees/funding/P&L. No exit proof or organizer-whitelisting claim exists. Future profit-exit research stays separate and begins only after this position is resolved.
