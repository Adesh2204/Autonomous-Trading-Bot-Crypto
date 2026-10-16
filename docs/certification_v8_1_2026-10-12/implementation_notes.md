# V8.1 implementation notes

This is execution infrastructure, not a VWAP strategy change. Defaults stay PAPER/false. The existing emergency protection configuration stays disabled. No actual order, signature, cancellation, transfer, leverage update or account-mode change occurred in this task.

The separate launcher recognizes PAPER (read-only preparation), TESTNET_CERTIFICATION (explicit exact proposal plus short-lived operator approval plus matching full-regression receipt) and TESTNET_PRACTICE (refused here). Setting an environment variable cannot grant an order permit. All legacy live authorization and Angel One lockouts remain enforced.

A proposal binds public identities, testnet/par, runtime asset ID, source and reliability-policy hashes, one direction, exact lot-normalized size and entry limit, 25 USDPR maximum notional, 10 USDPR planned session loss budget, exit bounds, stop-limit geometry, two exit attempts and six total signed actions. A completed, halted or consumed attempt cannot be reused. One approval lasts at most five minutes and includes wallet review and sole signer-host confirmation. An expired proposal must be rebuilt and reviewed. No active operator approval file was created.

The scoped SDK transport preserves official SDK 0.24.0 serialization and testnet-domain signing. It reuses the exact-action central compliance permits, account lease, durable nonce database and journal. Its payload expiry is covered by the signature. Only one market's owned entry/protection/exits/cancellations fit its envelope; administration, leverage, transfers, native coins, batches and a second entry are refused.

The certification account bridge reuses HyperliquidReconciliation, ExchangeTruthState and LiveAccountRecovery checkpoint loading. It omits frozen VWAP manager restoration only in this isolated execution experiment, since its trade has no strategy signal. Account truth readiness is separate from unresolved order lifecycle readiness so a verified position can be reduced after uncertain protection. Completion still requires every uncertainty to be resolved. Restart refuses a new entry and requires read-only recovery/operator review. It does not certify funded restart recovery.

The sequence verifies actual entry fills against exchange position and response, verifies protection through orderStatus and frontendOpenOrders, closes with bounded reduce-only IOC orders, cancels only owned obsolete orders, and independently verifies flat state. Actual event-based gross closed P&L, fill-price arithmetic, fees, funding and before/after flat USDPR equity must agree. A response summary is never an accounting fill. Controlled-test statistics are excluded from strategy results.

The proposed certification stop is a fixed 1% below the observed bid for LONG (above ask for SHORT), with a further 0.5% limit allowance. This is a new proposal for the execution test, not the production strategy stop, not an ATR substitution, and not an approved live protection configuration. It requires exact human review. isMarket=false is deliberate: official TP/SL documentation says market stops have 10% slippage tolerance. Stop limits may not execute through a gap. No $10 guaranteed maximum loss or guaranteed fill is claimed.

An offline partial-fill injection demonstrated a critical current limit: sub-$10 protection and exits are rejected locally. Existing rules were not silently weakened. require_safe_partial_path blocks real entry in both assembly and the final certification transport boundary if a one-lot partial fill could be stranded. This blocker cannot be waived by approval or larger order notional. An authoritative venue rule and a tested narrow closing/protection path are needed first.

SDK payloads/signatures from ephemeral accounts remain only in offline test memory. Actual API-key preflight derives its address without signing; reports contain public data only. Old PAPER ledgers and prior reports were not reset. No scheduled task, duplicate collector or autonomous session was started.

Official sources checked 12 October:
- https://perpetual-alpha26.github.io/docs/ — testnet/par, runtime metadata, minimum $10, fees, IOC and API setup.
- https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl — market versus limit stop behavior.
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint — action expiry, CLOIDs and trigger serialization.
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses — minimum-notional and reduce-only error categories.

These sources do not establish the sub-minimum full-position exception needed by the current adapter. We make no claim that the venue itself rejects every sub-$10 reduce-only close; the demonstrated rejection is in our local code.

The generic ProtectionPlan contract includes a normal_strategy_stop compatibility field. In this certification-only adapter that field carries the fixed test trigger; it is not a VWAP strategy stop or evidence of ATR-based strategy management. The production manager's default geometry and market-stop behavior remain unchanged and are not approved for funded use by this task.

The final check of the first tested source showed a 5,238 ms-old BTC book at the end of serial preflight, exceeding the unchanged 5,000 ms age limit. That failed snapshot is retained under market_preflight_final. CertificationContextProvider now reuses the original full account preflight and then refreshes par metadata/context and the book at the end. It retains the original account timestamp, so aging account truth still blocks signing; it does not manufacture a newer account observation. This change is isolated from the strategy runtime and is covered by a dedicated timing test plus a new full source-bound regression. Earlier reports/tests were preserved rather than relabeled as final.
