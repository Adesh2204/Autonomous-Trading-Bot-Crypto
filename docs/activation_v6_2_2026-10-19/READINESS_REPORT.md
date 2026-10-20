# Team Anchorium V6.2 readiness report

As of 2026-10-19T19:47:40.882000+05:30. **Engineering implemented and tested; signed PAS qualification remains blocked.**

| Area | Evidence-backed result |
|---|---|
| Funding / configuration | 100000.0 USDP, Unified; fresh BTC and EWY readbacks both 1x CROSS. |
| Live data | Post-close provenance, durable WS admissions and cache/REST lock ordering repaired. Raw REST/WS comparisons retained; no synthetic bars. Corrected public collector is running on the verified frozen V6.2 source. |
| Historical UNKNOWN | Exact original remains UNKNOWN. Two fresh unknownOid/PAR/PAS flat, order-free observations and bounded fills retained. A finite, source/mandate/host-bound isolation implementation now exists and is unaccepted. Original consumed attempt is never reset. |
| Native protection | No genuine PAS entry/stop/trigger/closing fill proof exists. Below-$10 native/IOC behavior remains unproven. Signed entry remains blocked. |
| Session risk | 60 minutes, 20,000 allocation, 1,000 entry / 2,000 cumulative, two attempts, one position, twelve actions. 100 intended trade risk / 200 session loss stop. Original signer/nonce/permit/protection guards remain. |
| Validation | 3251 passed; zero failures/errors/skips; identical source hash before/after. Freeze and PAPER/false lockouts pass. All 54 original databases and nonce/consumed records unchanged. |
| Activation | No PAS qualification signed, no order/fill/native-stop IDs, no accepted isolation/session mandate, no autonomous activation. |

## Actual data findings

The independent all-ten probe captured three REST rounds and two raw WebSocket connections. Both connections acknowledged all ten candle subscriptions and returned heartbeats. BTC/EWY REST bars advanced again; SP500/USDEUR/USDJPY remained older in that bounded sample. The local history matched or lagged by one polling interval. This establishes intermittent upstream availability, not a universal outage or a permanently fresh feed.

A later deployment check found that the old unsigned collector had stopped advancing for over 30 minutes while independent PAS data had advanced. That is an observed local stall. Its original state was retained; normal stop and SIGTERM did not release it, so only that identity-verified public process was terminated. No exact Python stack was sampled. The independently identified cache/REST lock inversion was corrected and tested before replacement.

All 24 raw candle events in that sample arrived while their bars were open. They cannot be promoted to final bars by clock passage. The final-source history review retains raw wire and durable observations separately. WebSocket persistence/late-event/conflict cases have offline coverage; the sample does not certify a post-close WS finalization event.

Final-source history review status: `UNSIGNED_HISTORY_REVIEW_COMPLETE`. Current collector snapshot: `OBSERVING`, updated 2026-10-19T19:47:40.642000+05:30.

- pas:BTC: NO_TRADE; ATR_BELOW_UNCHANGED_0_40_PERCENT_FLOOR, NO_FROZEN_STRATEGY_SETUP. Genuine tail 902; completed close 1792419360000; age 100882 ms. Read-time history gate: FRESH.
- pas:EWY: NO_TRADE; COMPLETED_CANDLE_STALE. Genuine tail 900; completed close 1792419240000; age 220882 ms. Read-time history gate: STALE_OR_MISSING.

## Minimum residual review

| Market | Smallest lot | Reviewed stop limit | Lot notional | Subminimum sizes |
|---|---|---|---|---|
| pas:BTC | 0.00001 | 80568 | 0.80568 USDP | 12 |
| pas:EWY | 0.001 | 155.26 | 0.15526 USDP | 64 |

These are observed unsigned proposal bounds, not accepted stop orders. Refresh them before a new qualification scope. The ordinary $10 rule and SDK reduce-only IOC helper do not prove subminimum acceptance, trigger execution or complete closure. A rejection/partial/unknown close preserves exposure and stops blind retry.

## Remaining blockers and next action

1. Obtain the exact applicable PAS native-stop and full-position minimum rules in [the clarification questions](../activation_v6_1_2026-10-19/PAS_ROUTE_CLARIFICATION.md). This is the next operator action; no organizer message was sent.
2. With those semantics established, implement/review a new bounded PAS qualification scope and obtain its exact interactive approval before signing. The old PAR consumed invocation cannot be reused. Preserve entry/stop/closing IDs, genuine fills, fees/funding and two flat readbacks.
3. The original UNKNOWN still lacks terminal disposition. The implemented finite isolation can only be used after its separate exact acceptance bound to a valid PAS session. It does not itself authorize a qualification or order.
4. After genuine protection/residual qualification, accept the new finite autonomous session and all existing source/account/ownership/risk guards. A current eligible frozen signal is also required; the ranking authorizes no extra markets.

Risk percentages use the 20,000 USDP allocation, not the 100,000 account balance or 1,000 entry cap. Estimated fee/slippage/funding reserves affect sizing and loss-stop decisions; actual PnL uses reported fills/fees/funding only. Sampled peak drawdown survives a close. Loss stops and stop-limit prices cannot guarantee realized loss through gaps or unavailable liquidity.

See [verified commands](OPERATOR_COMMANDS.md), [source-change review](CHANGE_REVIEW.md), [native evidence review](NATIVE_EVIDENCE_REVIEW.md), [regression receipt](regression_release_final/test_receipt.json), [original-record preservation](preservation_final.json), [finite isolation policy](isolation_final/policy.json), [session proposal](session_final/proposal.json), [all-ten ranking](ranking_final/ranking.json), and [machine-readable report](readiness_report.json).

Current verified source: `8bb636e708306673f327384fc451519e5e74d526ff3dbd81c17620973bb13bad`. Fifty-six new tests are offline fixtures; they do not certify exchange behavior. Earlier interrupted test runs are retained separately and are not release evidence.
