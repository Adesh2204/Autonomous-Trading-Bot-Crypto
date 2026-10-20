# Team Anchorium V6.1 continuation report

As of 2026-10-19T18:53:07.742000+05:30. **Configuration is verified; signed trading is not authorized.**

| Item | Actual result |
|---|---|
| USDP/account | 100000.0 USDP, Unified; observed 2026-10-19T18:52:27.441000+05:30. Positions and open orders empty in the retained account readbacks. |
| BTC/EWY configuration | Genuine CLI acceptance, two acknowledged leverage actions and helper readbacks verified. Separate actual PAS query and final discovery confirm 1x CROSS for both. No trade was submitted by configuration. |
| Original UNKNOWN | Still UNKNOWN, with two new `unknownOid`/flat/order-free readbacks. Original order and consumed attempt preserved. Original nonce store retained; the prior legitimate configuration advancement is preserved. |
| Finite isolation | Separate 60-minute design saved with source/raw evidence, exact historical row, nonce and session ceilings. Unaccepted and not consumed by execution. |
| Native stops/residuals | Not qualified. General guide does not establish sub-$10 exceptions. The bounded public sample supplied no usable stop/residual proof; it does not certify the team. Unsigned BTC/EWY reviews quantify all unproven sizes. |
| Ten-market ranking | Implemented and run on all ten canonical PAS markets using the unchanged scanner/brain. BTC/EWY remain the only production entry markets. No entry authority or invented signals. |
| Regression | 3195 passed, zero failures/errors/skips; source bdbdfcf68f4e0d0afba8fe3dfb60c9087283897a081425b35e75d664e1e22f95 matches before/after. Frozen strategy and PAPER/false policy pass. |
| Session/trading | Fresh finite session proposal retained with explicit ceilings and blockers. No valid executable mandate/acceptance, PAS stop IDs, trading order IDs or fill IDs. |
| Preservation | All 54 execution databases unchanged since the approved configuration baseline and pass integrity checks. |

## Current observed BTC/EWY readiness

- pas:BTC: NO_TRADE; COMPLETED_CANDLE_STALE. Completed-candle age 907742 ms; contiguous history 1292.
- pas:EWY: NO_TRADE; COMPLETED_CANDLE_STALE. Completed-candle age 1327742 ms; contiguous history 4353.

## All-ten observation snapshot

Observed 2026-10-19T18:49:38.804000+05:30. No row grants order authority.

| Market | Scanner qualification | Entry policy scope |
|---|---|---|
| pas:BRENT | COMPLETED_CANDLE_STALE | Observation only |
| pas:BTC | COMPLETED_CANDLE_STALE | BTC/EWY scope only |
| pas:ETH | COMPLETED_CANDLE_STALE | Observation only |
| pas:EWJ | COMPLETED_CANDLE_STALE | Observation only |
| pas:EWY | COMPLETED_CANDLE_STALE | BTC/EWY scope only |
| pas:GOLD | INSUFFICIENT_COMPLETED_HISTORY | Observation only |
| pas:HYPE | ATR_BELOW_BASELINE_SCANNER_FLOOR | Observation only |
| pas:SP500 | COMPLETED_CANDLE_STALE | Observation only |
| pas:USDEUR | INSUFFICIENT_COMPLETED_HISTORY | Observation only |
| pas:USDJPY | COMPLETED_CANDLE_STALE | Observation only |

## Session ceilings proposed for review

60 minutes; 20,000 USDP allocated bankroll; at most 1,000 USDP per entry / 2,000 cumulative; two entry attempts; one concurrent position including partial/pending exposure; 12 signed actions; 0.5% risk per trade and a 200 USDP session loss stop. These ceilings grant no authority. Fresh account reconciliation, sole account/signer leases, source/evidence binding, native protection and exact acceptance remain mandatory.

## Remaining actions

- **UNRESOLVED_HISTORICAL_ORDER**: Review the finite isolation design or obtain terminal original-order evidence. The draft is not consumed by execution; a separately accepted reviewed implementation is needed before use.
- **UNQUALIFIED_PAS_NATIVE_AND_RESIDUAL_SCOPE**: Obtain the precise PAS rules in PAS_ROUTE_CLARIFICATION.md; then implement/validate and explicitly accept the bounded signed qualification. Do not reuse the PAR executors or a configuration-only acceptance.
- **CONDITIONAL_FROZEN_STRATEGY_READINESS**: Continue genuine market collection until completed history is fresh and the unchanged strategy has an eligible setup.
- **NO_GENUINE_FINITE_SESSION_ACCEPTANCE**: After qualification and history isolation pass, prepare and accept the exact source-bound finite mandate and use the existing conditional single-controller launch.

See [verified operator commands](OPERATOR_COMMANDS.md), [completed configuration verification](completed_configuration_verification.json), [isolation design](isolation_review/isolation_policy.json), [venue clarification questions](PAS_ROUTE_CLARIFICATION.md), [all-ten ranking](ten_market_ranking_refresh/ranking.json), [full regression](regression_release_final/test_receipt.json), and [machine-readable report](continuation_report.json).

The public observer remains on its separate credential-free, verified frozen V5.3 source. Its ongoing collection does not authorize trading. Profits, first place, and an error-free future cannot be guaranteed.
