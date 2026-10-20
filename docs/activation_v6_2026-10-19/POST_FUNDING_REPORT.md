# V6 post-funding activation report

As of 2026-10-19T18:15:03.265000+05:30. **Signed trading is not authorized.**

| Requirement | Evidence / status |
|---|---|
| 1. Actual collateral | 100000.0 USDP; token 3307; observed 2026-10-19T18:14:20.557000+05:30 |
| 2. Identity | Team 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C; API 0x46c9BED595770150752E7fA3806449F81E0Ec6f9. Actual API approval/expiry and local derivation verified; Unified mode. |
| 3. Leverage | BTC and EWY remain 20x CROSS. Exact two-action 1x CROSS plan prepared; genuine human configuration acceptance pending. |
| 4. Original UNKNOWN | 0xac0eea156fcec80986dd67c9057b6ded remains UNKNOWN. Two fresh flat readbacks; no matching original historical order or terminal status. Consumed attempt preserved. Configuration-only isolation is available only in the exact accepted plan; no trading isolation. |
| 5. PAS protection/residuals | Not qualified. Fresh $25-bounded unsigned proposals retained for both markets. Smallest possible residual is below the documented $10 minimum; actual PAS native/protective closure semantics and lifecycle proof are missing. |
| 6. Market readiness | Two-sided books, account limits, OI, fees and funding captured. Warmup/freshness and frozen signals remain conditional; current authentic candle and signal details below. |
| 7. Regression | 3157 tests passed; zero failures/errors/skips. Source c6a61c2059e5c33b0e9e8dcbd94ed8faf4860c22d716e87bed8448dd0014b0a7. Strategy freeze and PAPER/false policy checks pass. |
| 8. Human acceptance | No configuration acceptance or finite trading acceptance was created. Direct named-wallet confirmation is identity evidence only. |
| 9. Launch | Public observer is running. No valid signed launch command exists before real qualification, mandate and acceptance; run the configuration helper below for the next genuine human step. |
| 10. Signed activity | No actual-wallet signatures, exchange writes, PAS orders, protective order IDs or fill IDs in this task. Observed PAS fills/fees/funding/realized PnL are zero; this is not trading success. |
| 11. Remaining actions | Exact configuration approval; trading-specific historical resolution/isolation; genuine PAS native/residual qualification; fresh eligible strategy setup; finite mandate acceptance and conditional launch. |

## Current authentic market status

- pas:BTC: 1266 completed bars, contiguous tail 1266, candle age 183265 ms; history-ready False; NO_TRADE: COMPLETED_CANDLE_STALE.
- pas:EWY: 4336 completed bars, contiguous tail 4336, candle age 63265 ms; history-ready True; NO_TRADE: ATR_BELOW_UNCHANGED_0_40_PERCENT_FLOOR, NO_FROZEN_STRATEGY_SETUP.

## Next genuine human action

Review [the exact two-action configuration plan](configuration_review_final/account_configuration_plan.json) and [the source/safeguard review](CHANGE_REVIEW.md). In your own macOS Terminal:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python docs/activation_v6_2026-10-19/configure_btc_ewy.py
```

The helper validates this release, refreshes evidence, displays the exact plan, and requests the existing exact approval phrase. Accepting immediately applies only BTC/EWY 1x CROSS and verifies both readbacks. No trading approval is created. This human step is required by P2 of your V6 request and the existing approval workflow; chat text cannot substitute for that CLI acceptance.

## Remaining blockers and concrete actions

- **EXACT_BTC_EWY_CONFIGURATION_NOT_ACCEPTED**: Run configure_btc_ewy.py yourself in a real Terminal; review and type the exact plan phrase. The helper refreshes evidence and applies only the two accepted 1x CROSS actions.
- **ORIGINAL_ORDER_HISTORY_UNRESOLVED_FOR_TRADING**: Obtain terminal original-order evidence or independently validate and expressly accept a separate trading-specific isolation policy; preserve original UNKNOWN and consumed attempt.
- **GENUINE_PAS_PROTECTION_AND_RESIDUAL_ROUTE_UNQUALIFIED**: Obtain authoritative PAS subminimum residual/native-stop semantics and review a bounded qualification experiment with genuine acceptance and actual order/fill evidence.
- **MARKET_READINESS_IS_CONDITIONAL**: Continue authentic BTC/EWY collection and wait for complete fresh history plus an eligible frozen setup; no candle fabrication or strategy relaxation.
- **NO_FINITE_TRADING_ACCEPTANCE**: After all prior dependencies pass, prepare the exact finite PAS mandate and accept it interactively using approve. Then use the existing conditional single-controller launch with those real files.

## Preserved evidence

All 53 original execution databases have unchanged logical dumps and pass integrity checks. Original UNKNOWN, consumed attempts and nonce history were not reset. Public collection uses the separate verified frozen V5.3 source; the V6 regression above covers the edited source.

See [machine-readable report](post_funding_report.json), [final regression receipt](regression_release_final/test_receipt.json), [original-state review](original_state_review.json), [current limits](current_limits_final/limits.json), and [operator handoff](README.md).

The [official PAS guide](https://perpetual-alpha26.github.io/docs/) confirms sender-independent funding checks, the ordinary order minimum and partial IOC behavior. [Hyperliquid order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types) describes native stops; neither reference certifies this account’s actual protective fills. Profits are not guaranteed.
