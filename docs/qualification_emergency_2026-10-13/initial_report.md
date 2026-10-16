# P0 isolated qualification report

## 1. Actual root causes and corrected files

The supplied 300-second V8.9 session recorded 1,414 directional book observations and no Stage A opportunity. The late account refresh was the optional end audit. No eligible trade was demonstrated as missed. The old10%-of-BOTH-best-levels limit prevented the ordinary minimum valid BTC quantity. A larger opening alone does not solve residual closure. The final readiness display incorrectly retained CHECKING_RESIDUAL_EXITS; the terminal display is corrected. The new policy is a separate type/version; old approvals cannot authorize it.

- algo-trading-bot/exchange/emergency_qualification.py
- algo-trading-bot/exchange/compliance_guard.py
- scripts/watch_testnet_qualification.py
- scripts/run_emergency_qualification.py
- algo-trading-bot/test_emergency_qualification.py

## 2. Supported IOC/GTC method

IOC takes at most50% of genuine L2 quantity within a fixed normalized ask+20bps entry limit, with independent exit-depth review within bid-20bps. GTC and optional ALO place one bid-priced limit, monitor actual statuses/team fills for30 seconds from durable transmission, cancel the original remainder once and confirm terminal state before closing. No replacement, enlargement or repeat entry. Local cancellation is not exchange auto expiry. The old10% BBO policy is not falsely labeled as passed.

[Official order and cancellation semantics](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint), [orderStatus and L2](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [ordinary minimum errors](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses). SDK0.24.0 inspected locally.

## 3. Current eligibility

Fresh read-only preparation finished in13.66 seconds, with one durable actual-account reconciliation. The team reported1,000,000 USDPR, unifiedAccount, the matching approved API agent, healthy local nonce ownership/clock/rates, zero positions and zero orders. All ten capacity observations showed1x CROSS. Remote sole-host ownership remains the user's prior human confirmation, not something local software can independently verify. BTC passed final source/account/margin/fee/price/liquidity/residual checks. Other current markets fail residual closure. Each inventory and final account observation has its own timestamp and is not future signing permission.

| Market | One-lot entry notional | Minimum IOC quantity | Spread bps | Result |
|---|---:|---:|---:|---|
| par:BRENT | 1.0367 | 0.10 | 19.348 | Blocked: unverified residual close |
| par:BTC | 8.3580 | 0.0002 | 14.8767 | Final BTC risk-review proposal ready |
| par:ETH | 0.25175 | 0.0040 | 9.1584 | Blocked: unverified residual close |
| par:EWJ | 0.097555 | 0.103 | 7.6035 | Blocked: unverified residual close |
| par:EWY | 0.16652 | 0.061 | 28.3209 | Blocked: unverified residual close |
| par:GOLD | 0.41684 | 0.0024 | 10.3416 | Blocked: unverified residual close |
| par:HYPE | 0.81392 | 0.13 | 0.7387 | Blocked: unverified residual close |
| par:SP500 | 7.8027 | 0.002 | 4.3671 | Blocked: unverified residual close |
| par:USDEUR | 0.11218 | 9.0 | 7.148 | Blocked: unverified residual close |
| par:USDJPY | 1.5859 | 0.07 | 1.2637 | Blocked: unverified residual close |

Final BTC reviewed L2 contained1.0264 BTC inside the entry limit and0.6932 BTC inside the immediate-exit limit. These are observed books, not fills. Final spread: 14.8767bps. Detailed prices, lot mappings, collateral, fees and residual quantities are in market_review.json/readiness.json.

## 4. Exposure and protection risk

Policy opening ceiling1,000 TEST USDPR, not a target or guaranteed maximum total loss. This fixed proposal is16.7160 USDPR. No actual order is authorized. No protective stop is verified or submitted. The exact one-lot BTC closing path uses independently read historical shape evidence, not a universal exception or future acceptance guarantee. Every possible selected whole-lot residual is checked. Disconnect, failed cancel, rejected/uncertain exit, vanished depth or price gap can leave an unprotected position needing separate manual recovery. Fees/funding and shared cross collateral prevent a guaranteed total loss cap. Normal protection/controlled certification remain FALSE; autonomous practice stays locked.

## 5. Tests and frozen strategy

1,984 passed;0 failures/errors/skips. Previous baseline1,893 plus91 new tests. Focused run211 passed. Intermediate failed reports are preserved. Phase-0 and strategy-freeze checks passed before and after full regression, with matching source hashes. signal_brain.py, freeze manifest and reliability/protection configuration are byte-identical. Production .40% ATR,15bps spread,300 bars,Top-3, UTC and strategy state behavior remain intact.

## 6. Exact preparation command

From the cloned project root, choose a new evidence directory:

```sh
.venv/bin/python scripts/run_emergency_qualification.py \
  --output-directory "docs/qualification_emergency_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \
  --test-receipt docs/qualification_emergency_2026-10-13/regression_release/test_receipt.json \
  --duration-seconds 60 --route auto
```

Explicit --route ioc/gtc/alo chooses that preparation route; --transport rest is read-only fallback. The selected proposal authorizes only its exact route, never automatic fallback.

## 7. Exact current proposal and approval

Proposal ID: `e2285d9d4b4844f7b2a4696afd3d340fd14f9b89ddd70ab762743e650c118fd0`.

- Team: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`. API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.
- Hyperliquid TESTNET `par`, asset2670000; BUY0.0002 `par:BTC`, IOC limit83580. Maximum selected opening notional16.7160 USDPR.
- Reviewed immediate exit limit83124. Actual SELL reduce-only IOC exits use exact current reconciled quantity and fresh bid minus20bps, never below82045. At most two exits.
- Taker fee rate0.00090. Entry/floor round-trip fee estimate0.029812500 USDPR. Conditional full close at the floor loss estimate0.336812500 USDPR including those fees; not a total-loss guarantee. Actual reported fills/fees/funding/P&L must reconcile.
- Approval expiry: 2026-10-13T22:30:55.077000+05:30. Entry needs90 seconds remaining, latest transmission cutoff 2026-10-13T22:29:25.077000+05:30. Fresh preflight can still reject.
- No verified protective stop. Policy hash `7567d48bb19899fc4d164b9a4f375f9a5d5d144debde197ccd4fa41214122701`.

Explicit human approval must name the exact current ID and accept verified-wallet/sole-host assertions, one entry, the separate50bps/50%-L2/20bps policy, NO STOP, possible manual residual recovery, no guaranteed loss cap and one cancel/two exits/lifetime limits. approval_REQUIRED_UNFILLED.json remains blank/false. No operator_approval.json was created. Only a separately approved response may populate it with exact hashes, human text, integer current approval/expiry times and every acknowledgment true. The expiry cannot extend past five minutes from proposal observation. Changed source/policy/prices require revalidation or a new proposal; never silent resizing.

Legacy stop_trigger/stop_limit fields in this inherited schema describe reviewed exit geometry only; no stop is placed.

## 8. Separately approved execution command

Only after valid exact human consent and populated operator_approval.json:

```sh
.venv/bin/python scripts/run_emergency_qualification.py --execute --output-directory '/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_emergency_2026-10-13/fresh_read_only/authorized_attempt' --proposal-file '/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_emergency_2026-10-13/fresh_read_only/proposal.json' --operator-approval-file '/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_emergency_2026-10-13/fresh_read_only/operator_approval.json' --test-receipt '/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_emergency_2026-10-13/regression_release/test_receipt.json'
```

## 9. Fill and position recovery verification

- STOP new entries. Preserve journal, original cloid/oid, consumed attempt and source/approval files.
- Query original orderStatus by cloid, team userFillsByTime, frontendOpenOrders and clearinghouseState with dex=par.
- UNKNOWN is not flat. Reconcile actual fills, original unfilled order and signed-management uncertainty without resubmission.
- An original resting remainder must be canceled and cancellation/terminal state confirmed before a full-position exit.
- Within current exact approval: SELL reduce-only IOC for actual reconciled quantity, at fresh bid less 20 bps, never below the approved floor; at most two exits.
- If halted, expired, disconnected, outside price bounds or cancellation/exits uncertain: no further writes. Obtain separate exact recovery approval or manually inspect the team account.
- Claim flat only after authoritative zero par positions, zero open orders and ready durable account reconciliation.

An authorized attempt writes execution_report.json and WHITELIST_TRADE_PROOF.json from genuine team-account records. Preparation created no fill proof. Verified fill, verified flat account and organizer whitelist confirmation are separate claims. Both SQLite checkpoint checksums/source identities, integrity and clean shutdown were verified, with zero intents/API-action/signed-management rows. No actual-wallet signature or secret was saved.
