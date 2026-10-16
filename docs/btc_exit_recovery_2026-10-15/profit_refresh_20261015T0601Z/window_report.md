# Option B result — no profitable SELL observed

The exact approved mandate `90505cbc168cda2bbe49f9931f04533808d431c40e7478d77b99df3bb0ebf52e` completed with status **PROFIT_WINDOW_EXPIRED_NO_SELL**. No SELL was attempted, signed or submitted. The original trade remains open. No completed-round-trip profit or loss is claimed.

## Authorization and timing

Approved at 2026-10-15T11:32:57.097000+05:30; maximum expiry 2026-10-15T11:42:57.097000+05:30. Scope was TESTNET `par:BTC`, exactly one possible reduce-only IOC SELL of 0.0002 BTC, minimum 81,812 USDPR/BTC, with fresh estimated net profit of at least 0.001 USDPR. The ten-minute bound included a final fifteen-second management reserve. Signing authority was revoked before expiry; final runtime account reads completed by 2026-10-15T11:42:53.136000+05:30.

No extension, renewal, loss-exit fallback, BUY, enlargement, cancellation or second exit occurred.

## Actual final account

Independent read-only snapshot: **2026-10-15T11:43:27.231000+05:30**.

- Team account: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`. API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.
- Remaining position: **0.0002 BTC LONG**, entry 81,512, **1x CROSS**.
- Open orders: **0**. Durable reconciliation: READY with no reported reasons.
- Executable bid / ask: **80562.0 / 80656.0**.
- Mark / oracle: 80656.0 / 80688.0; distinct from executable prices.
- No closing order ID or closing fill ID exists for this window.
- Protective-stop acceptance remains unverified. The position remains unprotected.

## Profit math and actual cashflows

Original genuine BUY: order 62755970305, fill 800659111758533; 0.0002 BTC at 81,512; cost 16.30240 TEST USDPR; reported entry fee 0.014672 USDPR.

Net reported funding is **-0.000060 USDPR**: +0.000141 at 10:30 IST and −0.000201 at 11:30 IST. The current hourly rate is not used instead of actual cashflows.

Conservative exit-fee bound is **0.27%**. Because the API omits deployerFeeScale, the documented maximum HIP-3 multiplier is used. This is an estimate bound for a future exit, not an actual paid exit fee. The approved maximum was 0.30%.

- Conservative break-even: **81806.53765165948059761355660 USDPR/BTC**.
- Positive-buffer SELL floor: **81812 USDPR/BTC**.
- Conditional net at the final observed bid: **-0.2482354800 TEST USDPR**, assuming full execution and the reviewed fee bound. This is not realized P&L or authorization for a loss exit.
- Actual entry fee plus reported funding cashflow so far: **-0.014732 USDPR**, excluding open-position valuation. This is not a completed-trade result.
- Reported mark-valued unrealized P&L: **-0.1712 USDPR**.

The floor included a small positive buffer; full execution at 81,812 under the reviewed fee/funding bounds would produce approximately 0.00108952 USDPR net. That outcome did not occur.

## Observation evidence and limits

There were **256** recorded observations, including **251** with a bid. Recorded bids ranged **80368.0–80607.0**, below the approved floor.

Transport counts: `{"WS_STARTUP_GRACE": 5, "WS_ACKNOWLEDGED_REPEATED": 233, "RATE_LIMITED_REST": 18}`. RATE_LIMITED_REST is a rate-controlled REST fallback label, not evidence of an HTTP 429. No persistent local read-budget rejection was found in this window. The longest observation gap was **35.706 seconds**, including serial account checks and pacing. This is not an exhaustive record of every exchange tick; no hypothetical missed fill is invented.

## Integrity and preservation

- Source `31efb87290919c495e624dfad41c426f83ec45dc21bf52dc0b4580a1185edd2f` is unchanged and matches the existing full 2,312-pass receipt. No new full regression run is claimed for this unchanged-source observation. Fresh preparation passed strategy freeze and Phase-0.
- New order intents: 0; signed API actions: 0; generated nonces: 0. Nonce history unchanged: True.
- SQLite integrity: ok. Latest checkpoint checksum and its structured source identity match their canonical verifier. The checkpoint identity and proposal aggregate hash use different hash domains; an initial local report assertion compared those unlike types, and the corrected read-only comparison passes. This was a reporting assertion, not an execution or persistence failure.
- Runtime signing authority is durably revoked. Restart cannot reactivate it.
- Both original BUY proofs retain their pre-window SHA-256 hashes. Organizer whitelisting remains unconfirmed.
- Production remains PAPER / ALLOW_LIVE_ORDERS=false. Strategy, thresholds and protection-certification status were not changed.

Underlying records: `authorized_profit_window/result.json`, `completion_read_only.json`, `window_summary.json`, the observation tape, exact mandate and genuine human acceptance.

## Next decision

No monitoring or signing window is active. A new ten-minute profit-only proposal or a separate bounded close proposal requires a fresh exact approval. No action will renew automatically. Waiting leaves the BTC LONG exposed and does not guarantee profit.
