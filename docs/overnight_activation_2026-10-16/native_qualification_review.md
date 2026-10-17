# Native protection qualification review

Reviewed October 16, 2026. Status: UNVERIFIED; no actual order or signature was produced for this assignment.

The [competition guide](https://perpetual-alpha26.github.io/docs/) states a $10 minimum per order, runtime lots, reduce-only TP/SL and partial IOC behavior. A successful IOC full close does not establish a native-trigger exception. Queries used the named team wallet and `dex=par` or prefixed coins.

The [venue TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) specifies mark-price triggers. Fixed-size position stops do not resize automatically. Parent-linked children can be canceled with a partially filled parent. Stop Market uses 10% tolerance, while Stop Limit may rest through a gap. Those alternatives do not establish safe subminimum residual treatment.

The [exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) exposes `normalTpsl` and `positionTpsl` grouping and `isMarket`; its presence alone is not evidence of a minimum-value exception. Installed SDK 0.24.0 has those wire structures; its `market_close` helper submits an IOC. No undocumented alternate grouping or synthetic trigger was introduced.

## Rules by action

| Action | Established evidence | Current treatment |
| --- | --- | --- |
| Open/increase | Ordinary minimum documented | Minimum and partial-path guard enforced |
| Reduce-only ordinary close | Direction limits documented | Exact actual remaining quantity; no enlargement |
| Scoped subminimum full IOC close | Independently read historical exact-market/side/size records | Only existing `full_position_close.observed_scope`; never generalized |
| Native trigger acknowledgement | No new actual proof | Unverified |
| Trigger child and actual SELL fill | No new actual linked proof | Unverified |
| Native subminimum residual stop/child | No authoritative exemption established | Block unattended entry |
| Software callback / Stop Market substitution | No new qualification or acceptance | Not substituted |

## Source trace

1. `long_session.AllocatedLongRisk.assess` and final `DailyLongExecution._prepare_context_request` check fresh both-side liquidity, actual fee/funding bounds, 1x CROSS and frozen stop geometry.
2. `partial_fill_safety.partial_path_assessment` tests one runtime lot at the opening limit, protective execution limit and closing bound. Increasing intended entry size does not remove a possible one-lot fill or remaining position. All 30 fresh all-market samples fail protective minimum feasibility.
3. `DailyLongExecution.submit` consumes genuine reconciled fills before protection. `DailyLimitProtection` retains the normal strategy stop minus one entry ATR and 0.5% execution allowance. Protective direction is SELL, exact actual position, reduce-only, native Stop Limit.
4. `position_protection.ExchangeProtectionManager` discovers and checks original order IDs, account association and trigger details. `_resolve_absent` reads original/child order states and actual linked fills; ambiguous/partial coverage blocks new entries. `_cancel` checks owned cleanup. Acknowledgement is not a closing fill.
5. `qualification_protection.QualificationStopManager._plan` independently rejects a stop below 10 and requires exact representable full position. No one-lot exception was inferred from IOC records.
6. `long_session.require_native_evidence` derives proof from raw receipts: named account/signer, actual BUY and linked native SELL, funding, and two distinct flat/zero-order reads. A ready flag cannot replace these records.

## Dedicated qualification feasibility

No executable tiny qualification mandate can currently pass the unchanged partial guard on the sampled universe. A normal minimum-sized opening order can still partially fill one lot; larger size does not cure that risk. A documented, independently qualified residual-native exception, or a runtime market whose one-lot entry/stop/close all meet the ordinary minimum, is needed first. Thereafter the existing qualification route needs a new exact human acceptance naming the market, quantity, risk prices, action counts and expiry. This development request grants none of those signatures.

A legitimate qualification must retain raw opening/protective order acknowledgements, order ownership, genuine trigger/child identity, actual closing fills, any residual, fees/funding and two authoritative terminal readbacks. Natural market movement must trigger the stop; price manipulation, self-trades and fabricated fills are excluded. Until that evidence exists, native protection and unattended entry remain unqualified. No organizer whitelist or reset claim is made.
