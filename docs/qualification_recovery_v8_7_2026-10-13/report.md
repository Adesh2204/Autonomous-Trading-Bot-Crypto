# Team Anchorium — V8.7 qualification recovery

**Implemented and tested. Preparation only; no actual signature, exchange order, fill or whitelist confirmation.**

## A. Root causes

- BTC: the old builder fixed the maximum-notional quantity and rejected depth instead of testing a smaller valid lot quantity. That is a reproduced software defect. However the actual saved 03:19–03:20 UTC book had ask size 0.0003 BTC: its 10% allowance was 0.00003, below one 0.0001 lot. That observation genuinely allowed no opening; selecting two lots would not have solved it.
- ETH: the old bid size 0.0173 permitted at most 0.0017 ETH after flooring, about 4.23 USDPR, below the ordinary 10 minimum. The fixed-size behavior was defective, but that book still had no eligible smaller opening. Independently, a LONG can leave one SELL lot whose subminimum close scope is unverified.
- HYPE: readiness recorded CLOCK_HEALTH_REQUIRED before a later book observation supplied the second recovery confirmation. A long budget wait had aged the earlier clock reference. The old snapshot was genuinely not ready at its own time; the later healthy clock did not retroactively fix it. The ordering and bounded complete reassessment are repaired. HYPE one-lot SELL close scope remains independently unverified.
- Further confirmed defects: reopening the read-only journal replaced the public limiter and lost process-local read weights; market selection could return the first, older proposal after scanning; the prior full-regression gate checked declared totals less strictly. All are corrected without weakening exchange minimums or risk gates. Three original bug reproductions fail on preserved original code; failing development outputs are retained.

## B. Actual code changes

1. `algo-trading-bot/exchange/testnet_qualification.py`: `find_largest_safe_qualification_quantity` uses Decimal and floors the minimum of notional, both 10% BBO depth caps, account max size and margin with fee reserve. Descending whole-lot candidates must pass exact qualification, every residual scope and the central validator. `QualificationContextProvider` orders budget wait, genuine timestamped-book clock observations, reconciliation and consistent fresh inputs; at most two complete contexts. `require_qualification_regression` validates current before/after source, actual XML totals/digest and safety results. Entry identity/freshness and truthful lifecycle/recovery stages are tightened.
2. `scripts/run_testnet_qualification.py`: `prepare` preserves the limiter across journal reopen, uses unsigned input descriptors, reviews BTC/ETH/HYPE, rereads the smallest-spread eligible market and generates its final source-bound identity last. `preparation_summary` prints current quantities, risks, deadline and real paths. `preflight_flat_proven` requires explicit position and order reads plus ready reconciliation; missing data cannot imply flat.
3. `algo-trading-bot/test_qualification_recovery_v8_7.py`: 78 additional offline cases exercise dynamic size, real composed preparation, depth/margin/precision, clock recovery and stale pairs, source/XML release validation, full/partial/no fills, residual exits, expiry, identity, proof predicates and preserved lockouts. Existing baseline cases cover uncertainty, exit/stop rejection, duplicate prevention and restart. Ephemeral fixture signatures never certify actual exchange behavior.

No frozen strategy, production threshold, leverage setting, wallet mapping, minimum-order validator or historical closing scope was changed. No journals or consumed attempts were erased.

## C. Dynamic sizing using actual observation-time data

Fresh read-only run: 2026-10-13T04:12:32.103822+00:00 through 2026-10-13T04:13:56.473610+00:00. Each row is its own timestamped observation, not simultaneous liquidity or a future fill guarantee.

| Market | Observation (IST) | Bid / ask | BBO bid / ask sizes | Largest size / notional within bounds | Outcome |
|---|---|---|---|---|---|
| par:BTC | 2026-10-13T09:42:46.020000+05:30 | 83179.0 / 83182.0 | 0.0078 / 0.0003 | 0.0000 / 0.0000 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:ETH | 2026-10-13T09:43:46.848000+05:30 | 2502.7 / 2508.3 | 2.0177 / 0.005 | 0.0005 / 1.25475 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:HYPE | 2026-10-13T09:43:54.005000+05:30 | 82.573 / 82.7 | 9.74 / 0.31 | 0.03 / 2.48223 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |


At these actual snapshots: BTC proposed prices would give three lots 24.9669 and two lots 16.6446 USDPR, but BOTH quantities fail the ask-depth cap; even one lot exceeds that cap and is below the opening minimum. ETH largest depth-permitted 0.0005 is 1.25475 USDPR. HYPE largest depth-permitted 0.03 is 2.48223 USDPR. None passes the opening minimum. These are calculations from rejected inputs, not authorized proposal prices.

Offline tests separately prove that a two-lot BTC opening is selected when three lots breach depth or margin; one lot cannot be used to evade the opening minimum. Those synthetic inputs are labeled tests, not current venue observations. Runtime precision and asset mapping are read from metadata. The ordinary 10 USDPR floor is an exchange rule, not an invented metadata field. See [official precision rules](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size) and [competition API/minimum/fee documentation](https://perpetual-alpha26.github.io/docs/).

## D. Clock repair

Public budget waits happen before two genuine timestamped order-book observations. Existing 2,000 ms skew and 30,000 ms clock-age limits remain. Fresh account reconciliation follows; readiness, account, book and mark observations must all be within 5,000 ms at evaluation. An inconsistent pair receives only one complete read-only retry, with backoff; failed observations remain in `context_observations`. An unrelated later healthy record never rewrites an earlier failed readiness snapshot.

Before executor assembly the provider can reconcile; after assembly this callback is detached because revoking the live guard inside its own preflight would invalidate its generation. Existing executor account recovery and central guards remain responsible during the bounded workflow. This composition passes offline lifecycle tests.

## E. Tests

Full regression: **1760 passed, 0 failures, 0 errors, 0 skipped**. Baseline 1,682 plus 78 new cases. Focused run: 127 passed. Phase-0 and strategy freeze passed before and after the full suite. XML digest and unchanged source before/after are recorded in `regression_release/test_receipt.json`.

Frozen `signal_brain.py` SHA-256: `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`. Byte-identical strategy/state methods and freeze manifest remain intact. Production remains PAPER/false, protection disabled, ATR 0.40%, 15 bps, 300 completed UTC bars and Top-3. Full tests use offline synthetic public/account inputs and ephemeral signing fixtures; actual practice execution is not certified by them.

## F. Current execution readiness

Fresh local key-derived public address and account/nonce exclusion: LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED; no signature or nonce allocated. Saved human sole-host confirmation is reused as a human assertion, not independent remote-host inspection or trade approval.

Team SDK `account_address`: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; approved API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. The approved transport remains SDK 0.24.0, TESTNET and prefixed par asset IDs. No actual signer transport was constructed.

Actual preflight reconciliation ready: True; flat positions/orders observed: True. SQLite integrity: ok; snapshot checksums valid: True. Exchange action journal rows: {'intents': 0, 'api_actions': 0, 'signed_management': 0}. Rate report: CAUTION. Account observations expire and must be refreshed again before future execution.
Each fresh candidate had READY unified-account checks, 1,000,000 USDPR, approved API agent and 1x CROSS. Agent validUntil was 1806859924898. Read weights across journal reopen stayed 212 / 212. The final public budget was 1032 / 1200 (CAUTION, not blocked); account rate budget 13 / 10000 used, 9987 remaining. No read failures were recorded. Clean shutdown and the separately defined core checkpoint source identity also match current files.
Actual clock offsets at final BTC/ETH/HYPE evaluations were -618/-669/-573 ms, within unchanged limits. ETH preserved its first CLOCK_RECOVERY_CONFIRMATION_REQUIRED warning, then obtained a new consistent context on attempt 1; BTC and HYPE completed attempt 0.

**QUALIFICATION_LOCKED. No eligible current proposal exists.** NO_MARKET_PASSES_QUALIFICATION_MARKET_AND_RESIDUAL_RULE. There is no order to approve.

**Protective-stop acceptance remains UNVERIFIED. No stop will be submitted.** The inherited `stop_trigger` / `stop_limit` fields are price bounds only. Normal ACTUAL_PROTECTION_READY, CONTROLLED_EXECUTION_READY, PRACTICE_READY and LIVE_READY remain FALSE. The isolated experimental route, if proposed, still needs an informed human decision about an unprotected position.

## G. Human action

Generate a new read-only proposal from Terminal using the existing launcher and a unique directory. This command prepares only; no execute flag or approval is supplied. The shell timestamp chooses a new evidence directory and cannot refresh an old proposal.

```bash
cd "/Users/adesh/Autonomous Trading Bot - Crypto "
.venv/bin/python scripts/run_testnet_qualification.py \
  --output-directory "docs/qualification_recovery_v8_7_2026-10-13/operator-$(date +%Y%m%d-%H%M%S)" \
  --test-receipt docs/qualification_recovery_v8_7_2026-10-13/regression_release/test_receipt.json
```

Emergency recovery: retain `runtime/testnet/anchorium-bot-1/qualification.sqlite`, original client/exchange order IDs, nonce history and the consumed entry. Read original orderStatus, team userFills, frontendOpenOrders and par positions. Never repeat an uncertain entry or infer flat from a local response. Close only the exact reconciled held quantity with reduce-only SELL IOC from fresh bid × 0.998, at or above the fixed approved floor, inside the original exit/expiry/action budgets. If partial/rejected/unknown exits, expired permission, lost connectivity or exhausted budgets leave exposure, report EMERGENCY_EXIT_REQUIRED and halt writes. A restart performs read-only recovery and requires explicit additional recovery authorization for further action.

## H. Remaining external blockers

- Actual liquidity can leave no lot meeting both depth and the ordinary opening minimum. The solver reports that honestly and never increases the cap or rounds up.
- Below-minimum stop acceptance/coverage remains unverified. Historical exact full-position BTC SELL one-lot order 62228843959 on another account supports only that narrow closing shape; zero residual is fill-derived rather than an independent historical position snapshot. It cannot establish stops or guarantee future acceptance/fills. ETH/HYPE LONG residual SELL paths lack matching evidence.
- Explicit exact-proposal risk approval is still absent. The five-minute proposal and subsequent signed-action expiry are enforced. Principal notional 25 is not a guaranteed loss cap; fees, funding and unresolved cross-margin exposure remain risks.
- Organizer acceptance of the qualification entry rule/API-agent attribution and actual whitelist confirmation require organizer evidence. No fill has occurred; the proof file correctly remains NO_ACTUAL_PRACTICE_FILL_VERIFIED. This workflow neither proves strategy profitability nor enables autonomous trading.

