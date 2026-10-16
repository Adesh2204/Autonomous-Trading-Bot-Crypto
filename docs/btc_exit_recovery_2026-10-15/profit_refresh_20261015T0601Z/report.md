# Fresh Option B — profit-only BTC exit

Status: awaiting explicit approval of `90505cbc168cda2bbe49f9931f04533808d431c40e7478d77b99df3bb0ebf52e`. This preparation does not authorize or submit a SELL.

At the recorded observation, the original 0.0002 BTC LONG was unchanged, 1x CROSS, with zero open orders. Account readiness was READY; the derived API public address matched; the local signer lease was healthy. Sole-host ownership on other machines still relies on the human's existing attestation. The original BUY fill was checked against fresh reconciled exchange records.

- Team account: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`.
- API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.
- TESTNET DEX `par`, `par:BTC`; exactly one reduce-only IOC SELL of 0.0002 BTC.
- Approval deadline: **11:36:11 IST, 15 October 2026**.
- Monitoring: at most ten minutes from genuine acceptance; final fifteen seconds reserved for management; no renewal or loss-exit fallback.
- Recorded bid / ask: 80411.0 / 80525.0; spread 14.16712233434408709052045534 bps.
- Conservative break-even: 81806.53765165948059761355660 USDPR/BTC.
- Minimum SELL: **81812**. It may rise with fresh fees/funding and never fall below this approved floor.
- Fresh limit: bid minus 10 bps, rounded up and bounded by the floor; at most 20-bps current-bid allowance, 50-bps isolated spread ceiling and 50% genuine depth participation.
- Actual entry cost: 16.30240 USDPR; entry fee: 0.014672 USDPR; net reported funding: -0.000060 USDPR.
- Current conservative exit-fee bound: 0.00270 (0.27%); maximum permitted bound: 0.003 (0.30%). Missing deployerFeeScale means the documented conservative maximum multiplier is used, not a claimed actual next-fill fee.
- Conditional exit fee at the floor: 0.044178480 USDPR; conditional net profit at the floor: **0.001089520 USDPR**. Fresh estimated net must remain at least 0.001 USDPR.

The profit floor was not executable in this snapshot. Waiting does not guarantee an exit or positive realized P&L. There is no verified protective stop. Any partial, rejected or uncertain attempt stops automated orders and requires exact account reconciliation and a separate recovery decision. A changed position blocks this fixed-quantity mandate. No BUY, exposure enlargement, second exit, cancellation or leverage change is permitted.

Source `31efb87290919c495e624dfad41c426f83ec45dc21bf52dc0b4580a1185edd2f` still matches the existing full regression receipt: 2,312 tests passed, zero failures/errors/skips. Strategy freeze and Phase-0 checks passed. No code or production policy was changed for this refresh; PAPER/false remains enforced.

The original BUY proofs are preserved. Realized profit, a closing fill and a flat account remain unverified until actual exchange evidence establishes them. See proposal.json and preparation_receipt.json for timestamps, account/book evidence, source and proof hashes.
