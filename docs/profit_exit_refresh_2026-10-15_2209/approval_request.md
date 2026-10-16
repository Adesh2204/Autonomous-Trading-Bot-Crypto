# New exact BTC SELL-only recovery approval

**Awaiting explicit approval; no SELL attempted and no signature created.** Original BUY proofs and the expired mandate remain preserved. Tested source is unchanged: `abc36e4a6eb6b61994b3bdc22ce05700e965afe44be697f6a0345e8c5f98f8c0`. The matching receipt verifies **2385 passed, zero failures/errors/skips**, with Phase-0, frozen strategy and PAPER/false protections intact.

At **15 October 2026 22:09:55 IST**, authoritative TESTNET `par` reads confirmed exactly **0.0002 BTC LONG**, zero open orders, only original BUY order **62755970305** / fill **800659111758533** (0.0002 BTC at 81512, actual entry fee 0.014672 TEST USDPR), and **0.000527 TEST USDPR net funding** across 12 reported events. Account reconciliation, clock and rates were ready; local signer identity and nonce exclusion passed. The historical UNKNOWN still has its original verified immutable certificate; actual raw journal rows remain preserved. Database and retained checkpoint integrity pass.

Snapshot bid/ask: **81970.0 / 82010.0**; book age at preparation 566 ms; spread 4.878643737041102573484571289 bps. Prepared limit **81889** has genuine bid depth **0.0032 BTC**, against an exact 0.0002 BTC order and a maximum 50% participation limit. Conservative exit fee **0.27000%** uses the existing 6x base-fee upper bound because current deployer fee scale is absent. Updated net break-even **81803.59470570540459239947859**. Conditional estimated net **+0.0331912000 TEST USDPR at observed bid**, **+0.017034940 at prepared limit**. These are estimates, not fills or realized profit.

## Exact mandate

**`5395c75090f1aa96a07c31c40e999420c58c5a82d2735536dc7ef22be3d63f05`**

- Team wallet `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; API wallet `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. Approval confirms both identities and this Mac as the sole signing host.
- TESTNET `par:BTC` SELL only, **exactly 0.0002 BTC**, **reduce-only IOC**, and only if mandatory fresh reads still prove that exact remaining LONG. No BUY, enlargement, leverage change or cancellation.
- One authorized closing order attempt; no automatic replacement/retry of a rejected, partial, unfilled or uncertain order, no restart or extension.
- Approved minimum price **81809 USDPR/BTC**, raised if fresh fees/funding require a higher conservative profit floor. Required estimated net **at least +0.001 TEST USDPR**. Initial limit follows fresh bid minus 10 bps, normalized upward; final allowance is capped at 20 bps below the fresh bid, while all approved floors remain mandatory.
- Computed exit fee at most **0.30%**, spread at most **50 bps**, genuine bid-depth participation at most **50%**; current account, book, fee, funding, metadata, nonce, source and signer guards remain mandatory.
- **10-minute window from genuine acceptance**, with no new closing path in the final 15 seconds. If a fresh profitable opportunity is unavailable, monitor read-only only within this approved window and then return the residual-exposure decision to the operator. No automatic loss-making close.
- Genuine exact approval must arrive by **15 October 2026 22:14:55 IST**. Expired mandates are never reused or silently renewed.

There is **no verified protective stop**. Waiting or partial/unfilled/failed/uncertain execution can leave the LONG exposed. Profit and full execution are not guaranteed. Mac/app/power/internet availability is required for supervision, and a local lease cannot verify remote signing ownership. Any actual SELL must be reconciled with exchange order/fill IDs, two authoritative flat/zero-order readbacks and actual exit fees/funding before claiming a completed round trip or real profit. No exit order/fill exists yet.

Your explicit instruction requires approval of this new exact mandate before signing. No acceptance file has been fabricated. After valid approval, routine Terminal and authorization-file operations will be handled here.

[Exact mandate](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/fresh_proposal/mandate.json>) · [Current exchange preparation](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/fresh_proposal/proposal.json>) · [Detailed account evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/fresh_account_and_mandate_summary.json>) · [Matching 2385-test receipt](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_guard_repair_2026-10-15/regression_release/test_receipt.json>)
