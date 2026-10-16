# BTC exit recovery — 15 October 2026

The genuine qualification BUY is verified. A complete round trip and a flat account have not yet been demonstrated. The existing position has no verified protective stop. A new SELL requires its own exact human approval; the consumed entry session is not reused.

## Actual entry and account evidence

- Team account: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`. API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.
- Venue: Hyperliquid TESTNET, DEX `par`, symbol `par:BTC`, collateral TEST USDPR.
- Actual BUY: 0.0002 BTC at 81,512; notional 16.30240 USDPR; reported fee 0.014672 USDPR.
- Exchange order 62755970305; fill 800659111758533; 15 October 2026, 10:16:30.641 IST.
- The original BUY evidence remains in its original files. Organizer whitelisting remains unconfirmed.
- Latest report observation: 2026-10-15T11:00:52.329000+05:30. See the timestamped JSON for positions, orders, funding and book. These observations expire; mandatory fresh checks still precede any signing.

## Why the previous exit stopped

The original BUY was accepted and filled. The following direct account-recovery call halted with RATE_LIMITED before any exit intent or exit HTTP submission. The code uses this error for a local request-budget rejection; an actual /info HTTP 429 has the distinct INFO_HTTP_429 error and HTTP status evidence. There is no evidence here that an exchange outage caused the halt.

The direct recovery bundle ran outside the provider wrapper that paces reads. Repeated serial account/history/metadata checks could consume the local rolling budget or reserved allowance. The historical error did not record its exact query, rolling weight or rejection branch, so those details cannot honestly be reconstructed. The fix paces the recovery bundle and records query, priority, weight, limit, reserve and backoff on any future local rejection. No budget is raised or reset.

Authoritative API limits: [Hyperliquid rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

## Narrow changes

- `algo-trading-bot/exchange/certification_runtime.py` — SHA-256 `72d8ab3dbf11f34fea05dcfa534d72de9fe64204b6a996466b1f04d75dbd4cfb`.
- `algo-trading-bot/exchange/rate_limits.py` — SHA-256 `8e0f049a29eb7d5ed28087da698e85b20ec5b2e79836dd27b2362962daa554e5`.
- `algo-trading-bot/exchange/exit_recovery.py` — SHA-256 `9e62fa6992e8b34820805821a461acad0938bc8137b4513dffb7d9c9e2049256`.
- `algo-trading-bot/test_exit_recovery.py` — SHA-256 `2cad97c0a82a5f98dfcfa5140d54aa3a73a3d070c96d9c2ca392884708a3e8a5`.
- `scripts/run_exit_recovery.py` — SHA-256 `292926e2c4560c39b9644984251c3b0a198785152d61a829dde298743e46cc13`.

- `certification_runtime.py`: compare quantity, entry price and leverage during exposure reconciliation. Mark-valued unrealized P&L or margin changing alone no longer masquerades as a position change; real exposure/order changes still fail closed.
- `rate_limits.py`: persistent local read-budget rejection diagnostics. Existing limits and reserves remain enforced.
- `exit_recovery.py`: separate source-bound SELL-only mandate; exact actual 0.0002 LONG; new approval; one reduce-only IOC; existing validation, five-second signing boundary, nonce lease, durable journal and official SDK transport.
- CLI: read-only preparation is the default. Execution requires the exact new mandate, acceptance and matching full regression receipt.
- Tests: offline full/partial/zero fills, uncertain acknowledgments, changed accounts, fresh-data checks, price/depth bounds, all acknowledgments, expiry, source mutation, duplicate prevention and restart lockouts. Synthetic tests do not establish venue protective-stop support.

## Fees and profitable price

Net completed-roundtrip P&L = actual SELL proceeds − actual BUY cost − entry fee − exit fee + net reported funding. Before a SELL fill this is a conditional estimate, not realized profit.

At an assumed 0.09% exit fee and zero funding, exact break-even is 81,658.85296767090381343208888 USDPR/BTC. A 0.001 USDPR positive buffer gives a valid rounded SELL floor of 81,664. The previous entry fee alone cannot prove the next exit fee.

The actual testnet perpDexs response omits deployerFeeScale. The new path therefore uses the documented maximum all-in HIP-3 multiplier of six times the current userCrossRate when the scale is unavailable. It ignores discounts. At userCrossRate 0.00045 this is a conservative 0.00270 (0.27%) bound, not a claim about the actual next fee. Any rate above the approved 0.003 cap blocks signing. Funding is fetched from actual account history; it is not inferred from the displayed hourly rate.

Fee formula source: [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees).

## Exact separately approvable choices

### profit_proposal

- Mandate hash: `eb5905216c2f2445c8f74a293f08f1a9a700f316c24e498b93a7c037b25b246c`.
- Observation: 2026-10-15T11:00:36.248000+05:30; approval deadline: 2026-10-15T11:05:36.248000+05:30.
- Existing position: 0.0002 BTC; open orders: 0.
- Actual bid / ask: 80941.0 / 81024.0; spread 10.24912789800265489457598864 bps.
- Minimum SELL: 81811; reviewed limit: 81811; executable at observation: False.
- Fee upper bound: 0.00270; reported funding: 0.000141; conservative conditional net at reviewed bid: -0.1724391400 USDPR.
- Scope: PROFIT_ONLY_EXIT; one SELL reduce-only IOC of exactly 0.0002 BTC; window 600 seconds after valid acceptance.
- No lower-price fallback or extension. Dynamic price is fresh bid minus 10 bps, rounded up, bounded by the approved floor and current 20-bps allowance. Profit mode can raise its floor as fees/funding change.

### immediate_close_proposal

- Mandate hash: `bfba5781ae7c028a7cd1572061acd66a1ee488b38e48e7d698b2146a723c9332`.
- Observation: 2026-10-15T11:00:52.329000+05:30; approval deadline: 2026-10-15T11:05:52.329000+05:30.
- Existing position: 0.0002 BTC; open orders: 0.
- Actual bid / ask: 80941.0 / 81024.0; spread 10.24912789800265489457598864 bps.
- Minimum SELL: 80780; reviewed limit: 80861; executable at observation: True.
- Fee upper bound: 0.00270; reported funding: 0.000141; conservative conditional net at reviewed bid: -0.1724391400 USDPR.
- Scope: BOUNDED_LOSS_EXIT; one SELL reduce-only IOC of exactly 0.0002 BTC; window 120 seconds after valid acceptance.
- No lower-price fallback or extension. Dynamic price is fresh bid minus 10 bps, rounded up, bounded by the approved floor and current 20-bps allowance. Profit mode can raise its floor as fees/funding change.

## Attempt, rejection and recovery policy

A changed/closed position, any unexpected order, new fill, unhealthy signer/nonce/account state, stale evidence, insufficient depth, spread above the isolated 50-bps ceiling, or violated price/fee/source/time bound blocks the planned SELL. No BUY or leverage change is authorized. The production 15-bps scanner rule remains unchanged.

One durable exit attempt consumes the recovery mandate. A rejected, zero-filled, partially filled or uncertain exit ends automated orders. There is no second SELL, replacement or exposure enlargement. If a 0.0001 BTC residual remains, this 0.0002 mandate cannot close it: obtain fresh authoritative records and separate exact recovery authority. The full-position subminimum closing evidence does not certify protective stops.

A crash cannot resume writes with the old runtime token. Inspect the original close cloid/order ID, team fills, positions and frontend orders; resolve uncertainty using reads, never by blind resubmission. If a REST/WebSocket check fails, keep the account exposure flagged UNKNOWN until authoritative reconciliation. Revoke signing locally and escalate unresolved exposure to the operator.

Profit-only monitoring lasts at most ten minutes from valid approval, reserving the final 15 seconds for management. If no qualifying profitable exit occurs, it stops and reports the position. The separately approved immediate-close mode lasts at most two minutes and permits a modeled net loss no worse than 0.50 USDPR at the approved limits; this is not a guaranteed maximum loss if an exit fails or exposure remains. Neither choice submits a protective stop.

## Verification and limitations

Early focused test failures and read-only report-formatting errors are preserved in their original logs. The first focused fixture omitted its shared rate manager; the corrected fixture uses the real budget and a deterministic clock. One diagnostic report called health() instead of report(); the corrected read-only v2 report completed. These were not exchange order failures and produced no signed action.

- Full receipt: `regression_release/test_receipt.json`; tests {'tests': 2312, 'failures': 0, 'errors': 0, 'skipped': 0}; passed True.
- Source before/after tests matches current source: True.
- Before/after strategy-freeze and Phase-0 checks are recorded in the receipt. Frozen signal/state logic and PAPER/false defaults are preserved.
- Nonce tables unchanged since this task began: True. Any later approved exit will legitimately append one nonce and must be documented separately.
- No current-task exchange order is established by preparation or tests. Original real BUY evidence remains separate from offline fixtures and proposed SELL terms.
- A flat-account claim requires two fresh authoritative zero-position/zero-order readbacks and ready reconciliation. Realized net P&L requires the actual SELL fills, reported fees and funding.
- Protection VERIFIED = FALSE; normal protected controlled execution = FALSE; PRACTICE_READY = FALSE; LIVE_READY = FALSE.
