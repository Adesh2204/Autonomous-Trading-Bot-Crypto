# Team Anchorium — V8.2 partial-fill safety report

**Failure handling is improved and tested. Sub-$10 closing support is still unverified, so actual certification entry remains blocked.**

No real order, cancellation, transfer, leverage change or actual-wallet signature was made. The account remains flat at the saved public observations. There is no actual realized trade P&L to certify.

## Root cause and verified venue behavior

An entry request worth 25 USDPR can fill only one lot. A closing order can also leave one lot behind. Both existing local order boundaries enforce the published $10 minimum, including reduce-only exits and protective stops. Full requested entry size therefore cannot prove that every possible partial fill is closable.

The [participant guide](https://perpetual-alpha26.github.io/docs/) documents the minimum, reduce-only IOC closing and possible partial/rejected outcomes. [Hyperliquid error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) lists minimum-notional and reduce-only errors separately. The official SDK 0.24.0 market_close implementation uses an ordinary reduce-only IOC; it supplies no separate dust-close mechanism.

**The material inspected does not establish an exemption for either a complete sub-$10 close or a sub-$10 protective stop on par.** That is not proof of universal server rejection. It means we cannot safely code an exemption as fact. A fake exchange accepting such an order would not verify the venue.

The full evidence review is in [venue_behavior.md](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_2_2026-10-12/venue_behavior.md>). The precise implementation root causes are in [root_cause.md](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_2_2026-10-12/root_cause.md>).

## What changed

- Before entry, examine the smallest possible entry fill and last exit remainder using runtime lot size and reviewed bounded prices. Entry stays blocked if either requires an unverified subminimum exception.
- Closing and protection use the exact observed full position, the opposite side and the approved size ceiling. Refuse unrepresentable dust, oversizing and price rounding that changes the reviewed limit.
- Protection readback must cover the current full position. A previously prepared plan is insufficient if the position changed.
- Save the real remaining exposure durably. A subminimum residual halts for operator review; restarting cannot invent flatness, create another entry or reuse an uncertain attempt.
- Recover documented named terminal rejection/cancellation states using the original market/CLOID and actual fills. A partially filled order followed by cancellation remains partially filled. Missing orders and unknownOid remain unresolved.
- Read-only preflight checks all ten 1x CROSS settings and can save an explicitly non-executable proposal wrapper when ordinary gates pass but partial safety fails.

No minimum validation was removed. No top-up, oversized reduce-only, zero-size stop, abnormal price or market helper was used as an assumed workaround.

| Source file | Change |
|---|---|
| [algo-trading-bot/exchange/testnet_certification.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/testnet_certification.py>) | Integrates exact sizing, current-position protection checks, persistent residual evidence and bounded exit outcomes. |
| [algo-trading-bot/exchange/certification_runtime.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/certification_runtime.py>) | Resolves explicit terminal status with matched fills and retained uncertainty. |
| [scripts/run_testnet_certification.py](</Users/adesh/Autonomous Trading Bot - Crypto /scripts/run_testnet_certification.py>) | All-market leverage readback, partial-safety evidence and non-executable review proposal. |
| [algo-trading-bot/exchange/partial_fill_safety.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/partial_fill_safety.py>) | New runtime-lot assessment, exact close sizing, durable residual observation and documented terminal status lists. |
| [algo-trading-bot/test_partial_fill_safety_v8_2.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_partial_fill_safety_v8_2.py>) | 30 new offline partial-fill, precision, rejection, uncertainty, preflight and restart cases. |

Documentation, source-before copies, a patch, hashes and test/account receipts are saved in this V8.2 directory. The classified legacy inventory CSV/JSON was refreshed; earlier inventories were preserved.

## Tests and strategy integrity

**1,487 full-suite tests passed: 0 failures, 0 errors, 0 skipped.** This is the prior 1,457 baseline plus 30 new cases. The final focused suite passed all 82 cases; the earlier focused 80-case result is also preserved.

Phase-0 safety and frozen strategy verification passed. The full-suite source hash was identical before and after testing and matches the public preflight. All other source/configuration files in the V8.1 manifest remain unchanged. `signal_brain.py` and the frozen methods, VWAP/EMA/ATR, cooldown/direction state, 0.40% ATR floor, 15 bps spread, 300 completed UTC bars and Top-3 are preserved.

Offline cases cover small LONG/SHORT full closes, retained minimums, residuals below a lot, real remaining size, position changes during protection readback, entry/exit partials, rejected exits/protection, unknown acknowledgment, named terminal rejection, partial cancellation with actual fills, no blind retry and restart without another entry. SDK signing fixtures use ephemeral accounts and prohibit actual exchange HTTP.

```text
Source before V8.2: 625329ffb8d2eb2a337fd30ec3eb75abe9137d92f1f20c294784b2a6f8725aa0
Final tested source: fed73ed1cc60af117fb2e36614bdb1447e588ab986431db497e2edf89340b902
Regression XML SHA256: 676b6d2ffe9b185b2ec82281f225f92a04d24fd038867024019c4d3f98795c1b
Frozen brain SHA256: bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83
```

## Fresh read-only account and market observations

The first sandbox read failed with INFO_RETRY_BUDGET_EXHAUSTED; its evidence was preserved. The public read outside that sandbox succeeded, followed by one bounded refresh. Those reads did not exercise the exchange write endpoint.

| Account observation | Result |
|---|---|
| Team wallet | 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C |
| API wallet | 0x46c9BED595770150752E7fA3806449F81E0Ec6f9 |
| Venue | Hyperliquid Testnet / par |
| Capital | 1,000,000 test USDPR; not the proposed order size |
| Mode / approval | unifiedAccount; API approval with valid expiry observed |
| Leverage | All ten par markets 1x CROSS; no setting changed |
| Positions / trigger-aware open orders | 0 / 0 at final saved snapshots |
| Local API derivation / nonce owner | Matching public address; second owner rejected; zero nonce allocations; leases released |
| Ownership scope | Current host/OS user only; sole remote signer ownership requires future human review |
| Rate budget | Healthy; saved actual-account budget 13 used / 10,000 cap; no local signed actions |

Candidate observations are individually timestamped. ETH proposal observation: 2026-10-12T14:04:25.634000+05:30. Every future execution needs a new preflight.

| Market | Book age | Spread | One-lot mark value | Current saved admission |
|---|---:|---:|---:|---|
| par:BTC | 315 ms | 2.748 bps | 8.369400 USDPR | CERTIFICATION_LIQUIDITY_MARGIN_MINIMUM_REQUIRED |
| par:ETH | 599 ms | 6.231 bps | 0.256870 USDPR | SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED |
| par:HYPE | 467 ms | 6.859 bps | 0.874500 USDPR | CERTIFICATION_FRESH_ACCOUNT_BOOK_REQUIRED |

ETH passed ordinary proposal/account/price checks in the refresh. BTC remained below the required depth participation allowance. HYPE account readiness captured CLOCK_HEALTH_REQUIRED before the later fresh clock observations restored HEALTHY; the later clock result does not retroactively change that account-readiness verdict. The earlier ETH oracle-deviation rejection is a preserved earlier observation, not the refresh result.

Book times are exchange timestamps. Mark/oracle freshness in this path uses local REST receipt; upstream publication times are unavailable. These snapshots do not recertify continuous WebSocket operation or 300-candle strategy inputs.

## Exact LONG proposal — review only, blocked

This wrapper is saved in [blocked_proposal.json](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_2_2026-10-12/market_preflight_refresh/blocked_proposal.json>). It cannot deserialize as the executable proposal type. It is not an approval request while the partial safety gate fails, and its prices must not be reused for a later trade without a fresh review.

| Proposed item | Exact saved value |
|---|---|
| Network / DEX / asset | testnet / par / par:ETH; runtime asset ID 2670001 |
| Side / order | LONG / BUY, bounded limit IOC, one entry attempt |
| Quantity | 0.0097 ETH |
| Maximum entry price | 2569.9 USDPR per ETH; at most 5 bps beyond the observed ask |
| Entry notional / cap | 24.92803 / 25 USDPR |
| Leverage / positions | 1x CROSS / one global par position maximum |
| Test-only protection | Reduce-only stop-limit SELL for actual filled size; trigger 2541.5; limit 2528.8 |
| Exit | Immediate bounded reduce-only IOC for exact remaining size; at most two attempts; SELL price at least 2528.8 and at most 20 bps below a fresh bid |
| Fee estimate | 0.0445116510 USDPR for entry plus closing at the bound, using 0.09% taker per fill; actual fees require exchange records |
| Planned loss plus fees at the bound | 0.4431816510 USDPR; this is an estimate, not a guaranteed maximum loss |
| Proposed operational loss budget | 10 test USDPR; no safety override |
| Protection semantics | Fixed plumbing-test stop based on observed bid, independent of frozen strategy/ATR |
| Expiry / cancellation | Future exact human permit at most five minutes; at most six owned actions; clean up owned obsolete protection; no scheduled-cancel reliance |
| Proposal hash | 190c379d8eb10441934bc421b386223e71a0df28f7e96ce1bcd73719cd62b1af |
| Actual order authorization | NONE |

The smallest possible ETH fill/remainder is 0.0001 ETH. At the proposed close limit it is worth 0.25288 USDPR. That is the decisive blocker.

A stop-limit can be accepted yet fail to execute through a gap. Entry/exit can partly fill or be rejected; network/acknowledgment failure and expired permission can require urgent operator review. No order is held open to wait for profit. No approved maximum loss is an exchange guarantee.

## Readiness flags and remaining blockers

```ini
PARTIAL_FILL_EXIT_READY = FALSE
ACTUAL_PROTECTION_READY = FALSE
CONTROLLED_EXECUTION_READY = FALSE
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
GLOBAL_PROTECTION_ENABLED = false
REALIZED_PNL_STATUS = REALIZED_PNL_NOT_CERTIFIED
```

- PARTIAL_FILL_EXIT_READY is false because a safe subminimum close/protection exception has not been verified. Conservative rejection/recovery behavior is tested; venue support is not.
- ACTUAL_PROTECTION_READY is false because there has been no authorized actual stop acceptance/readback test. Configured or simulated protection is not actual proof.
- CONTROLLED_EXECUTION_READY is false because partial safety remains blocked, no exact human order approval exists, and future current price/account/host checks are required.
- Actual LONG/SHORT, funded restart/recovery, controlled execution, PRACTICE_READY and LIVE_READY remain false. The independent V7 strategy-feed blocker remains preserved.
- No actual fills or realized P&L were generated. PAPER and offline-fixture accounting remain distinct from wallet truth.

## Exact next safe action

**Obtain authoritative par confirmation of the full-position reduce-only IOC and protective-stop rules below $10, including exact fields and conditions.** The [unsent question draft](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_2_2026-10-12/organizer_question_draft.md>) is ready. No message was sent.

If support is confirmed, implement and test only that narrow path, then repeat source-bound regression and fresh preflight. Only after those gates pass can the operator approve an exact small test. The current blocker cannot be waived by approval, an environment flag or account funding.
