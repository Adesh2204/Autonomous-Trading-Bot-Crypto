# PAS BTC/EWY: 1× review, not live certification

## Decision: NO-GO for live trading

This review keeps trading disabled. It changes the code-side leverage policy to exactly **1× CROSS on BTC and EWY only**. The frozen strategy, liquidity-based candidate selection, one-global-position limit, candle gates, open-interest headroom and approval barriers are unchanged. No account settings, orders, cancellations, signing, deployment, merge or activation are authorized by this review.

The base is main `d629e1bdecfeecfd70f4815dd82c3d1235ec1cd5`. The new workflow prepares unsigned checks for future pushes to main; it cannot retrospectively prove CI ran on the current main commit. Review-branch checks do not certify a deployed release.

## What the account actually showed

Unsigned Hyperliquid Testnet `/info` receipts collected at 17:30 UTC on 19 October 2026 showed the owner-confirmed wallet `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` with 100,000 USDP, `unifiedAccount` mode, BTC and EWY both at 1× CROSS, and no PAS positions or open orders. Both active-market reads reported 100,000 available to trade. The PAS-only clearinghouse summary was zero; unified collateral came from the runtime USDP spot token, not that zero summary and not the separate historical USDPR balance.

The approved-agent list included `0x46c9bed595770150752e7fa3806449f81e0ec6f9`. This is public approval evidence, **not** independent matching of the locally deployed signer or organizer registration. Two returned fills were historical `par:BTC` fills; preserve those records and do not reopen a future PAR route. A balance observation does not prove organizer credit provenance or registration. No wallet connection or account change was needed or performed.

## Market-data gate is still blocked

The bounded completed-candle check finished at 17:31 UTC. BTC returned 294/300 completed bars, with latest close about 430 seconds old. EWY returned 285/300, about 910 seconds old. Both failed the unchanged 300-bar and ≤120-second freshness requirements. These are timestamped observations, not current market guarantees. Missing bars remain missing; no synthetic bars or freshness relaxation are permitted.

## What the new replay tests prove—and do not prove

The unsigned PAS fixtures test runtime-discovered BTC/EWY and USDP startup recording/replay, exact tape-operation consumption, preserving the replay cursor after an operation mismatch, and reading existing position/order state without exchange writes. An existing position's leverage is observed as evidence even when it is not entry-policy-compliant; this does not make it ready for a new entry.

These tests do **not** demonstrate full strategy-cycle deterministic replay, crash/partial-fill recovery, real protection execution, residual closure, or restart recovery on a running deployment. The previously reported `REPLAY_OPERATION_MISMATCH` is not reproduced in the supplied post-merge extended log: its legacy replay fixtures fail earlier during PAS identity discovery. The mismatch is not declared resolved or removed from the readiness requirements.

## Priorities before any live approval

1. **Restore trustworthy PAS coverage.** Classify the main baseline in `baseline-classification.md`; migrate isolated test fixtures and retired-policy assertions deliberately. Do not re-enable production PAR routing to make old tests pass. Add full-cycle PAS replay evidence and determine whether the earlier replay-operation mismatch is reproducible.
2. **Resolve genuine or unresolved runtime concerns.** Keep startup/UNKNOWN locks and protection/residual evidence intact. Reproduce suspected defects with PAS-only unsigned regressions before implementing minimal fixes. No blanket resetting of evidence or weakening of gates.
3. **Obtain real, fresh market inputs.** Require both markets' complete 300-bar histories and fresh books/candles at the decision time, plus unchanged scanner history, liquidity and OI checks. Public data collection is not live certification.
4. **Certify identity and sole ownership separately.** Establish organizer registration, intended wallet, actual deployed signer match, approved agent validity, funded unified-account semantics and one account-controlling process. Do not assume another browser wallet can replace the owner-confirmed address.
5. **Demonstrate the controlled lifecycle on the reviewed release.** Establish both-market native/protection/residual, actual-fill/fee/funding reconciliation, partial-fill/disconnect/restart/UNKNOWN handling, supervisor failure recovery and full autonomous BTC/EWY dry-run evidence. Synthetic unit checks cannot supply actual-account proof.
6. **Only after all gates pass, request explicit activation authorization.** Review/merge/deployment/controlled execution are separate future decisions. This task must not merge, deploy or activate. Never infer the missing continuation of Section 14.

## Verified checks and broad-suite comparison

Code/test commit: `cedf8945e80b4bf5f1f7d0e51454113f60f670b1` (replay regression parent: `675c5b3`). Documentation-only commits may follow; the PR head identifies the final reviewed tree.

| Check | Result |
|---|---|
| Exact final workflow module list, `python3 -m pytest -q -p offline_no_sign ...` | **565 passed**, 16.42 seconds |
| Frozen strategy manifest: `python3 scripts/check_strategy_freeze.py` | **PASS**: 1 file, 8 methods, 32 parameters |
| Static runtime/launcher imports | **PASS** |
| `git diff --check` | **PASS** |
| Main full unsigned suite, audit venv | **1,982 passed; 121 failed; 1,278 setup errors**, 323.58 seconds |
| Review full unsigned suite, same venv/settings | **2,005 passed; 114 failed; 1,278 setup errors**, 327.43 seconds |
| Selected review replay/recovery/fault suite | **96 passed; 12 failed; 44 setup errors**, 59.70 seconds |

Full-suite commands ran in `algo-trading-bot` with `EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false HL_COMPETITION_MARKET=pas HL_DEX=pas HL_NETWORK=testnet`, using `/workspace/anchorium-scored-audit/.venv-audit/bin/python -m pytest -q -p offline_no_sign --junitxml=...`. The first system-Python full-suite attempt stopped with four missing-`pyotp` collection errors; these are separate from the audit-venv totals. Legacy dependencies were already present in that audit venv; no production dependency or gate was changed.

The exhaustive [main classification](baseline-classification.md) and [121-case JSON](baseline-classification.json) were completed before publication. Main's 121 failures comprise 85 legacy fixture/policy mismatches, 7 intentional lockouts, 25 unresolved safety-lock cases, 3 possible PAS runtime regressions and 1 confirmed non-PAS paper-collateral mismatch. All 1,278 setup errors stop at `PAS_DEX_MAPPING_UNVERIFIED` in static fixtures. The classification itself made no live queries; the separate unsigned account/metadata observations above must not be conflated with unit-fixture failures.

The [test-identity comparison](broad-comparison.json) shows **no newly failing testcase identities** and seven previously failed identities now passing. This is not proof that seven runtime defects were fixed. In particular, the three uncertain-entry cases can pass earlier fail-closed branches once the leverage policy changes; no-sign tests cannot certify their intended signed transport/lifecycle. Several other PAS fault failures change from startup locks to absent-position/stop assertions because no signed entry occurs. Their recovery/protection coverage remains unresolved. Keep the suspected uncertain-entry transition issue open until a valid scoped PAS harness demonstrates actual semantics without weakening entry or signing gates.

No frozen method, `signal_brain.py`, freeze manifest, historical PAR evidence or existing protection/UNKNOWN record is modified by this PR. Test-generated PAPER artifacts are retained outside the review tree rather than committed over historical data. No live trading process was started.
