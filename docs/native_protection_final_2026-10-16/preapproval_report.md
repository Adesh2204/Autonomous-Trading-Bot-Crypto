# Final native-protection repair and qualification report

Updated UTC milliseconds: 1792207298638. Source `d02d56ddced4d14679963842d4729ab06d51998b43d95dfb330fb4556fa3c5e0`. PAPER/false. No actual new signature, exchange write, acceptance, signer or worker.

## A–J requested results

| Item | Actual result |
|---|---|
| A — $10 residual issue | A narrow controlled test route is implemented and tested: full two-lot BTC receives an ordinary-size stop; exactly one lot is aborted through the existing observed exact reduce-only IOC close. A general subminimum native-stop exemption is not established. |
| B — actual native qualification | No. No new entry/stop has been signed; no actual natural trigger-linked closing proof exists. Acceptance alone cannot pass. |
| C — genuine trades permitted | Currently zero. Proposed small qualification permits one entry only after exact human approval. The unaccepted future session specification allows at most two entry attempts, one concurrent position. |
| D — actual permitted position size | Currently zero. Qualification proposes exactly 0.0002 BTC; no increase, rounding-up, split order or blanket permission to deploy the 20,000 bankroll. Unattended qualified capacity remains zero. |
| E — full regression | PASS: 2675 tests, 0 failures, 0 errors, 0 skips. Source before/after equal. Phase-0 and strategy freeze passed. |
| F — fresh exact session mandate | No trading-session mandate. A separate exact tiny qualification proposal is ready below. |
| G — execution command | Qualification CLI is implemented and tested; its exact command template is in OPERATOR_GUIDE.md. A trading launch command is not currently eligible. Missing exact approval/source/health gates block before key access. |
| H — running / order-capable | No worker or signer launched. Previous named PIDs absent; both old heartbeats PAUSED. |
| I — actual fills / P&L | No new task fills or realized P&L. The preserved Oct15 BUY/SELL round trip net is +0.050512 TEST USDPR, not today’s earnings or synthetic-test P&L. |
| J — exact remaining blocker | Missing actual team Stop Limit trigger/child SELL fill proof; no verified one-lot native-stop support. Any fresh price/depth/approval gate also must pass. The Oct16 overnight creation window has elapsed; it is not silently extended. |

## Exact current proposal state

Fresh **qualification-only** mandate `aac5cd9405582382d7e79d355853211751bef350ffd45e653ae1f487e01437a0` is prepared. It is not accepted. BUY IOC exactly 0.0002 BTC at limit 81410; native SELL Stop Limit trigger 80512, limit/cleanup floor 80110. Approval deadline ms 1792207583640; authorization ends within five minutes of genuine acceptance. Maximum six signed actions, one entry, one stop, one owned cancellation round and at most two definitely resolved exact IOC closes. No uncertain retry, restart, price widening, leverage change or new session. Planned loss at floor plus configured fees: 0.289073600 TEST USDPR; this is not a guaranteed loss cap. Estimated immediate cleanup net before funding: -0.0462923000 TEST USDPR.

The operator must explicitly accept the exact qualification ID, both wallets, this sole signing host, one-entry scope, immediate one-lot abort, unprotected interval/residual risk, loss-making cleanup, incomplete qualification if untriggered, and local Mac/process/power/internet dependency. No acceptance file is created by preparation. A late answer cannot renew an expired proposal.

## Venue findings and evidence limits

The ordinary venue order minimum is $10. Previously independently read original orders and matching fills support exactly 0.0001 BTC reduce-only SELL IOC full-position closure under the preserved V8.5 scope; this is observational evidence, not a documented universal minimum exemption. The exact proof SHA is c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764.

The bounded fresh public-account history audit found 134 native historical rows in one 2,000-row truncated history, all Stop Market, with isPositionTpsl=false. Eight selected historical ETH/BRENT Stop Market orders had displayed original notionals below $10, with recorded open/terminal statuses. These are historical acceptance observations, not eight independent triggered closes. Exact-ID rechecks on Oct17 returned unknownOid for all eight; the cause is UNKNOWN, not proof of rejection, a reset or whitelisting. No Stop Limit or position-linked example was established in this bounded sample. It is not a venue-wide census.

Stop orders trigger on mark price. Stop Market has documented 10% tolerance and is not substituted for the approved 0.5% Stop Limit allowance. A Stop Limit can rest through a gap. Position TP/SL can track full position size by default, but schema/grouping support does not prove a subminimum Stop Limit/child exemption. Parent partial-fill/cancellation rules do not guarantee children remain protective. There is no documented FOK path used here; the opening IOC can partially fill.

Sources: [competition guide](https://perpetual-alpha26.github.io/docs/), [official TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl), [official errors](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses), [official exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint). Saved primary source bytes, observation times and SHA hashes are in primary_rule_sources/manifest.json.

## Minimum repair and release checks

A dedicated typed, finite two-lot BTC capability uses the existing validator, single-position lock, preserved historical UNKNOWN certificate, original qualification journal, original nonce store, exact-action SDK permits and unchanged participation/price/source/rate guards. It cannot authorize autonomous entries, another BUY, a different market, a larger size, a Stop Market substitution or account administration. Ordinary certification and unattended partial-fill guards remain unchanged.

A lost stop placement ACK now resolves the same original journal row to OPEN only after matching fresh status, frontend order, quantity, side, prices, position and CLOID/OID readbacks. No retransmission or replacement occurs. Known trigger children enter isolated account recovery only after exact current parent/child readback. Cleanup cancels one verified owned live order, requires terminal settlement, then closes the exact remaining position. Unknown child/cancellation/IOC outcomes halt. The barrier is also enforced at the direct-close and final signing boundaries.

Qualification waits for a natural trigger for at most 120 seconds, shortened when necessary to reserve cleanup time within the original five-minute authorization. An untriggered accepted stop is canceled and followed by approved bounded cleanup, then reported INCOMPLETE. The raw proof exporter independently checks actual linked SELL fills and two authoritative flat/zero-order readbacks. No automatic promotion occurs, even after full-size qualification. A one-lot native stop remains unverified.

Focused release checks: 243 passed across native protection, certification, terminal shutdown, cross-midnight expiry and two-cycle controls; the final module suite passed 58 tests including an added direct-close bypass check. Full regression reruns every test at the final source. All signatures in these tests use ephemeral offline fixtures with HTTP prohibited; synthetic triggers/fills never qualify the team or venue.

Full XML SHA-256: `0ca82d4a09eb5461039a92f334bf0f2d1fd40440ecb3d6c6ff0b5a842a064ac4`. Baseline 2617-test source was `3911d7226a9befe7adfda84222623ee9533a414cb4efd9ed674f3d3041401312`; that successful receipt remains separately preserved. Requirements/pins were not changed by this repair. Frozen brain, eight frozen methods and 32 parameters remain unchanged.

## Account, persistence and interruption limits

Latest saved account observation ms: 1792207283638. It is a timestamped snapshot, not a continuous account guarantee. Positions: 0; open orders: 0. Oct17 morning audit independently had two ready flat/zero-order readbacks at 1792199548911 and 1792199551176. Final signing requires new full checks.

Original BUY: order 62755970305 / fill 800659111758533, 0.0002 BTC at 81512, fee 0.014672. Original SELL: order 62805581662 / fill 260274449763192, 0.0002 BTC at 81909, fee 0.014743. Gross +0.0794; total fees 0.029415; 12 funding cashflows +0.000527; net +0.050512 TEST USDPR on Oct15. No organizer whitelist/reset conclusion follows from these fills.

Preservation check: True. All ten protected file hashes and all three original SQLite logical dumps match baseline. Integrity checks and saved recovery snapshot checksums pass; original nonce history, original UNKNOWN row/certificate and BUY/SELL proof bytes remain intact. Full details are in preservation_receipt.json. Public /info failures, local rate waits and unknownOid records are distinguished; no HTTP429 is inferred from a fallback label.

This is local operation. Losing this Mac, process, app supervision, power or internet can interrupt management. Native Stop Limit acceptance does not guarantee a fill during an outage or price gap. A failed terminal audit stays UNKNOWN; direct positions/orders are still reported when possible. No restart, next-day renewal, blanket high-position approval or unattended hold is created.
