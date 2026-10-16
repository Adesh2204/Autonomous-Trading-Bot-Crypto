# Team Anchorium — V8.9 qualification workflow

## A. Root-cause verdict

The latest saved three-market rejection was genuine under the retained risk policy. It was not a rounding bug: the legal opening quantity is rounded DOWN after the smaller of the notional, each best-level depth, exchange maximum size and margin limits. A separate latency problem made short-lived valid books harder to use. A separate reporting defect retained obsolete candidate fields after a failed rereview; the global submission gate already remained closed.

Historical evidence: `docs/qualification_stability_v8_8_2026-10-13/operator-20261013T053653Z/readiness.json`, 2026-10-13T05:36:54.078751+00:00 to 2026-10-13T05:38:18.166499+00:00. These were separate timestamped observations, not simultaneous or current books.

| Market | Minimum legal entry quantity | Minimum entry notional | Largest allowed quantity | Largest allowed notional |
|---|---:|---:|---:|---:|
| par:BTC | 0.0002 | 16.7164 | 0.0000 | 0.0000 |
| par:ETH | 0.0040 | 10.09800 | 0.0006 | 1.51470 |
| par:HYPE | 0.13 | 10.75893 | 0.01 | 0.82761 |

BTC was limited by its bid; ETH and HYPE by their asks. Earlier V8.8 BTC initially permitted 0.0002 BTC / 16.6944 USDPR, but its best ask later shrank and correctly invalidated that opportunity. Neither broader Level-2 depth nor wallet funding automatically fixes a strict best-level constraint.

## B. Code changes

- `exchange/qualification_watcher.py`: `inspect_book`, `sweep`, `research_residuals` inspect runtime precision, genuine books and both directions; aggregated-depth calculations are research only. `PublicBookStream` checks exact subscription acknowledgments, two distinct timestamped updates, receiver heartbeat, three-connection bound and cache invalidation. `PublicBookReader` paces REST fallback. `OpportunityGate` limits full checks to two per session, at least 60 seconds apart. `ReadOnlyQualificationSession.validate` reuses one journal/limiter/recovery object, checks the prior execution journal and actual signer, reconciles the selected market and verifies every residual using existing central validators. `durable_readback` checks both retained checkpoints through an independent read-only handle, including account/source/identity/checksum consistency.
- `scripts/watch_testnet_qualification.py`: implemented bounded observation, opportunity-triggered checks, source/policy checks, optional one-time end account audit, clean shutdown, source-bound evidence and operator handoff. No execution mode or signed endpoint is available in this command.
- `scripts/run_testnet_qualification.py`: extracted unchanged proposal-file construction into `publish_proposal`, added `clear_candidate` to remove stale candidate fields before rereview, and extended `preparation_summary` with real file paths, supported next commands and explicit CLI expiry reporting. The old full preparation command remains compatible; the new watcher is the fast operator path.
- `test_qualification_watcher_v8_9.py`: 71 new offline cases. Existing execution, strategy, closing scope and production policy code were unchanged. Source diff and hashes: `v8_9_changes.patch`, `source_changes.json`.

## C. Watcher command and safe stop

Run one bounded, read-only observation with a new evidence directory:

```bash
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python scripts/watch_testnet_qualification.py \
  --duration-seconds 300 \
  --output-directory "docs/qualification_watcher_v8_9_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \
  --test-receipt docs/qualification_watcher_v8_9_2026-10-13/regression_release/test_receipt.json \
  --final-account-audit
```

Press Ctrl+C once to stop. SIGTERM also requests a safe stop. The watcher writes diagnostics and closes its public socket and SQLite journal. Do not use kill -9 unless the process cannot respond. It exits when a proposal is ready or its observation window ends. A current full validation may finish after the observation duration; the hard cancellation bound is duration + 180 seconds. The default command therefore permits up to 480 seconds including ongoing checks. It never schedules itself or automatically restarts.

Public WS uses official `l2Book` with the prefixed market coin, without precision aggregation or fast mode. Default depth is up to 20 levels per side, so the report covers the **observed** L2 book, not unbounded hidden depth. Authoritative sources: [subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), [heartbeats](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats). Actual support is separately evidenced by acknowledgments and repeated updates below. If stream data is missing/stale after a 10-second startup grace, REST is admitted at most once per symbol per five seconds, subject to the unchanged shared public budget and reserve.

## D. Market coverage and close scopes

All ten runtime `par:` markets are inspected in both directions as research. Existing execution scope remains LONG only in BTC/ETH/HYPE, conditional on all gates; no new market or SHORT activation was added. BTC historical BUY and SELL one-lot shapes support direction-specific research, not a promise of future fills. ETH/HYPE one-lot BUY examples do not verify tiny SELL closes for a LONG. A single proven lot also does not certify all two-, three- or more-lot subminimum residuals. BRENT/EWJ historical shapes remain narrowly scoped; the complete residual range and separate execution-scope approval still matter.

Latest recorded research rows below are individually timestamped. They are not an authorization or a simultaneous guarantee of current executable liquidity. Complete bid/ask sizes, 10% limits, sweeps/VWAP estimates, raw observed levels and residual details are in the run `readiness.json` and `observations.jsonl`.

| Market / side | Observations | Potential observations | Last minimum entry qty | Last BBO-bounded qty | Last recorded blocker |
|---|---:|---:|---:|---:|---|
| par:BRENT / BUY | 27 | 0 | 0.10 | 0.04 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:BRENT / SELL | 27 | 0 | 0.10 | 0.04 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:BTC / BUY | 27 | 0 | 0.0002 | 0.0000 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:BTC / SELL | 27 | 0 | 0.0002 | 0.0000 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:ETH / BUY | 25 | 0 | 0.0040 | 0.0014 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:ETH / SELL | 25 | 0 | 0.0040 | 0.0014 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:EWJ / BUY | 21 | 0 | 0.103 | 0.023 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:EWJ / SELL | 21 | 0 | 0.103 | 0.023 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:EWY / BUY | 17 | 0 | 0.061 | 0.012 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:EWY / SELL | 17 | 0 | 0.062 | 0.012 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:GOLD / BUY | 17 | 0 | 0.0024 | 0.0009 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:GOLD / SELL | 17 | 0 | 0.0024 | 0.0009 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:HYPE / BUY | 17 | 0 | 0.13 | 0.04 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:HYPE / SELL | 17 | 0 | 0.13 | 0.04 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:SP500 / BUY | 17 | 0 | 0.002 | 0.003 | QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL |
| par:SP500 / SELL | 17 | 0 | 0.002 | 0.003 | QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL |
| par:USDEUR / BUY | 17 | 0 | 9.0 | 3.3 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:USDEUR / SELL | 17 | 0 | 9.0 | 3.3 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:USDJPY / BUY | 17 | 0 | 0.07 | 0.01 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |
| par:USDJPY / SELL | 17 | 0 | 0.07 | 0.01 | QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS |

| Market | Best bid / ask | Best quantities bid / ask | 10% quantity caps bid / ask | Minimum entry notional | Levels bid / ask | L2-only depth could meet minimum? |
|---|---|---|---|---:|---|---|
| par:BRENT | 101.98 / 102.47 | 0.48 / 47.65 | 0.048 / 4.765 | 10.2520 | 13 / 8 | True |
| par:BTC | 83451.0 / 83552.0 | 0.0604 / 0.0006 | 0.00604 / 0.00006 | 16.7186 | 12 / 12 | False |
| par:ETH | 2514.1 / 2514.2 | 0.014 / 0.0546 | 0.0014 / 0.00546 | 10.06160 | 9 / 8 | True |
| par:EWJ | 97.185 / 97.209 | 25.952 / 0.232 | 2.5952 / 0.0232 | 10.017471 | 14 / 11 | False |
| par:EWY | 163.11 / 164.03 | 30.823 / 0.123 | 3.0823 / 0.0123 | 10.01071 | 9 / 11 | False |
| par:GOLD | 4183.0 / 4188.0 | 3.5931 / 0.0097 | 0.35931 / 0.00097 | 10.05600 | 11 / 13 | True |
| par:HYPE | 82.654 / 82.752 | 1.48 / 0.42 | 0.148 / 0.042 | 10.76309 | 9 / 10 | False |
| par:SP500 | 7783.7 / 7786.7 | 0.589 / 0.579 | 0.0589 / 0.0579 | 15.5810 | 13 / 14 | True |
| par:USDEUR | 1.1181 / 1.1192 | 2125.4 / 33.6 | 212.54 / 3.36 | 10.07730 | 13 / 14 | False |
| par:USDJPY | 158.01 / 158.32 | 0.17 / 31.86 | 0.017 / 3.186 | 11.0873 | 14 / 9 | True |

The L2-only column does not include account readiness, unverified residual closes or new-market approval and does not change execution eligibility. Sweep prices/VWAPs in JSON are estimates for the minimum legal opening quantity, not actual fills.

The counts above are repeated observations, not independent trades or profitability samples. Best-level eligibility is never replaced by aggregated L2 research. Prices, fee estimates and depth can change before approval and again before signing.

## E. Performance and budgets

Actual bounded read-only run lasted 98.198 seconds. It saved 404 directional book observations and triggered 0 opportunity validation(s), with 1 actual recovery call(s). An optional end audit is separately labeled and cannot publish a proposal.

Full candidate timings (seconds): []. End account audit: 7.735.

The rate report's entries_allowed flag describes rate-budget capacity only; it grants no trading authorization. Final public rate report:

```json
{
  "state": "HEALTHY",
  "policy": {
    "ip_weight_per_minute": 1200,
    "ip_safety_reserve": 120,
    "daily_actions": 50000,
    "daily_safety_reserve": 500,
    "account_action_reserve": 10,
    "max_open_orders": 1000,
    "max_ws_connections": 10,
    "max_ws_subscriptions": 1000,
    "max_ws_unique_users": 10,
    "venue_ws_connections_per_minute": 30,
    "max_ws_messages_per_minute": 2000,
    "ws_reconnects_per_minute": 5,
    "budget_max_age_ms": 60000,
    "optional_poll_interval_ms": 5000,
    "read_retry_attempts": 3,
    "backoff_base_ms": 1000,
    "backoff_max_ms": 30000,
    "exhausted_safety_action_interval_ms": 10000,
    "caution_fraction": 0.75,
    "throttle_fraction": 0.9
  },
  "ip_weight": 476,
  "public_read_blocked": false,
  "account_requests_used": 13,
  "account_requests_cap": 10000,
  "remaining_budget": 9987,
  "budget_observed_ms": 1791890701488,
  "daily_actions": 0,
  "daily_limit": 50000,
  "entries_allowed": true,
  "open_orders": 0,
  "backoff_until_ms": 0,
  "websocket": {
    "connections": 0,
    "subscriptions": 0,
    "outgoing_messages": 2,
    "heartbeats": 2,
    "reconnects_last_minute": 0
  },
  "public_reads": {
    "upstream_by_operation": {
      "perpDexs": 1,
      "meta": 2,
      "l2Book": 39,
      "clearinghouseState": 8,
      "openOrders": 3,
      "userFillsByTime": 2,
      "userFunding": 1,
      "userAbstraction": 2,
      "spotClearinghouseState": 2,
      "frontendOpenOrders": 4,
      "metaAndAssetCtxs": 2,
      "extraAgents": 1,
      "userFees": 1,
      "userRateLimit": 1,
      "activeAssetData": 1,
      "perpDexLimits": 1
    },
    "failures": {},
    "pending": 0,
    "coalesced": 0,
    "max_seconds": 0.7600882081314921,
    "failure_details": []
  }
}
```

The prior complete three-market preparation took 140.956 seconds in the saved disappearing-BTC example, including long budget waits. This is an observational comparison across different venue conditions, not a controlled benchmark. The new normal path has one selected-market reconciliation; the existing bounded clock-pair retry can require a second. It removes the separate initial reconciliation, network re-reconciliation after journal reopen, unrelated market account checks and final re-ranking pass. Position/order/history reads required for current consistency remain fresh; signing-boundary checks are unchanged. Raw account diagnostics and fee schedules may make readiness.json large; they are evidence, not extra trading operations.

## F. Regression and strategy integrity

Full regression: {'tests': 1893, 'failures': 0, 'errors': 0, 'skipped': 0}; pass=True. Prior baseline 1,822 plus 71 new tests. Focused suites: 260 passed, zero failures. Intermediate failed development fixtures/reports are preserved. The complete run includes partial/no fills, uncertain/rejected closes, restart/duplicate prevention, protection rejection, source-bound release checks and actual-fill proof predicates; synthetic results do not certify exchange stop acceptance.

Full source before: `13113188a1351741a0c93aa2c25b9932c4ce90a6cdad8c8efb1434f8d3c051e3`.
Full source after: `13113188a1351741a0c93aa2c25b9932c4ce90a6cdad8c8efb1434f8d3c051e3`.
XML SHA-256: `4768df0b89b1384be8938c7b6128ea683f9713eeae60d1ce10d93ba8cb7cc0dd`.
Phase-0 and frozen-strategy checks before and after are included in the full regression receipt. `signal_brain.py` remains byte-identical; production UTC VWAP/EMA/ATR, 0.40% volatility, 15 bps spread, 300 bars and Top-3 remain unchanged. Global PAPER/false, protection disabled, ordinary $10 opening minimum, $25 qualification ceiling and 1x CROSS requirements remain.

## G. Actual read-only result

Status: **NO_CURRENT_QUALIFICATION_PROPOSAL**. Blocker: `NO_SUPPORTED_CURRENT_OPPORTUNITY`. Observation ran 2026-10-13T11:23:26.031327+00:00 through 2026-10-13T11:25:04.229856+00:00.

Actual WS channel support observed for: par:BRENT, par:BTC, par:ETH, par:EWJ, par:EWY, par:GOLD, par:HYPE, par:SP500, par:USDEUR, par:USDJPY.
Subscriptions confirmed: 10 / 10; connection attempts: 1; receiver gap maximum: 1.001243291888386 seconds.

Account result is a timestamped read, not continuing assurance. Team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` remains the account address; API `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` is the agent. Local identity derives only its public address; local nonce ownership test allocates no nonce and creates no signature. Prior human confirmation of sole host is retained, but no software local lease can inspect another machine. The exact-trade approval remains unfilled.

At 2026-10-13T16:55:03.068000+05:30 IST, account readiness was **READY**, mode **unifiedAccount**, and observed collateral **1000000.0 USDPR**. The approved agent was valid; local key public identity matched and the second local nonce owner was rejected. BTC was **1x CROSS** with **1000000.0 USDPR** available on either side. Actual positions and frontend orders were both empty. These are timestamped observations, not future guarantees.

The final BTC check had bid **83451.0**, ask **83552.0**, best bid size **0.0604 BTC**, and best ask size **0.0006 BTC**. The strict 10% ask allowance was **0.00006 BTC**, below the **0.0001 BTC** lot. A $10-valid entry needed at least **0.0002 BTC** at that reviewed price. The solver therefore selected no quantity. This is a genuine policy-bound depth blocker, not missing wallet funds or a software instruction to force an order.

Account summary:

```json
{
  "account_observed_ms": 1791890703068,
  "final_positions": [],
  "final_orders": [],
  "final_reconciliation": {
    "ready": true,
    "reasons": [],
    "accounting": {
      "source": "EXCHANGE_REPORTED_ACCOUNT_OBSERVER",
      "exchange_orders_submitted": 0,
      "entries_paused": false,
      "reasons": [],
      "positions": [],
      "open_orders": [],
      "fills": [],
      "funding_events": [],
      "reported_account_equity": {
        "reported_account_value": "1000000.0",
        "collateral_balance": "1000000.0",
        "margin_used": "0",
        "withdrawable": null,
        "valuation_source": "spotClearinghouseState.USDPR.total"
      },
      "accounting_window_ms": [
        0,
        1791890697296
      ],
      "latest_query_window_ms": [
        0,
        1791890697296
      ],
      "realized": {
        "gross_closed_pnl": "0",
        "actual_fill_fees": "0",
        "actual_funding_cashflow": "0",
        "net_after_fees_and_funding": "0",
        "scope": "ONLY_OBSERVED_ACCOUNT_EVENTS; excludes deposits/transfers and unknown historical events"
      },
      "corrections": [
        {
          "kind": "EXCHANGE_TRUTH_ADOPTED",
          "timestamp_ms": 1791890699047,
          "differences": {},
          "new_fill_count": 0,
          "reasons": [],
          "exchange_ts": null,
          "received_ts": "2026-10-13T11:24:59.047+00:00",
          "processed_ts": "2026-10-13T11:24:59.047+00:00",
          "timestamp_source": "LOCAL_PROCESS",
          "exchange_to_receive_ms": null,
          "receive_to_process_ms": 0,
          "clock_skew_detected": false
        }
      ]
    }
  },
  "active_asset": {
    "user": "0x94ea16ece139e246a1d84e71aacf7dd1f47cb12c",
    "coin": "par:BTC",
    "leverage": {
      "type": "cross",
      "value": 1
    },
    "maxTradeSzs": [
      "11.983",
      "11.983"
    ],
    "availableToTrade": [
      "1000000.0",
      "1000000.0"
    ],
    "markPx": "83451.0"
  },
  "clock": {
    "state": "HEALTHY",
    "reason": null,
    "offset_ms": -343,
    "last_reference_ms": 1791890703950,
    "fresh_confirmations": 3
  },
  "blocker": "QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS"
}
```

Durable cleanup: `{"integrity": "ok", "snapshots_verified": 2, "checksums_verified": true, "source_identity": {"git_commit": "33c7cfe9ec241ccc0241144a8dccfd9a06df553a", "working_source_hash": "61e9bcedda7a2e597e328cdd99e0c64ce4ebc22f53ebe1807130c480f76e184b", "strategy_source_hash": "bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83"}, "clean": true, "actions": {"intents": 0, "api_actions": 0, "signed_management": 0}}`.

No actual exchange signature, entry, close, cancellation, transfer or configuration change occurred. No actual fill or whitelist confirmation exists. This watcher does not create a fabricated WHITELIST_TRADE_PROOF.json.

## H. One-off authorization, execution and recovery

Operator handoff file: `/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_watcher_v8_9_2026-10-13/read_only_observation/operator_handoff.json`.

```json
{
  "status": "NO_CURRENT_QUALIFICATION_PROPOSAL",
  "qualification_state": "NO_CURRENT_QUALIFICATION_PROPOSAL",
  "actual_order_authorization_supplied": false,
  "blocker": "NO_SUPPORTED_CURRENT_OPPORTUNITY",
  "output_directory": "/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_watcher_v8_9_2026-10-13/read_only_observation",
  "test_receipt": "/Users/adesh/Autonomous Trading Bot - Crypto /docs/qualification_watcher_v8_9_2026-10-13/regression_release/test_receipt.json",
  "production_execution_mode": "PAPER",
  "allow_live_orders": false,
  "protection_verified": false,
  "next_permitted_action": "Review readiness.json; restart only by a deliberate new read-only command."
}
```

If no ready proposal exists, there is no exact order to approve. Use the bounded watcher command again only by a deliberate operator decision. It will print the actual proposal, unfilled approval template, source-bound receipt, copy command and supported execution command if it finds a valid opportunity. Never use a previous proposal or guess a file path.

When a proposal is ready, review its exact hash, quantity, notional, prices, fee estimates, exit floor and IST approval deadline. Copy the unfilled template using the printed copy command, review/edit the copy yourself, and supply a nonempty operator_approval plus actual integer approved_ms/expires_ms. Approval must be within 300,000 ms of proposal observation, expiry must be later than the current time and at most 300,000 ms after approval. Never backdate or extend an expired proposal. The six required true acknowledgments are manually_verified_wallets, sole_signer_host_confirmed, maximum_one_entry, unverified_stop_risk_accepted, qualification_spread_limit_accepted and possible_manual_residual_recovery_accepted. The exact proposal binds the $25 cap, its smaller selected quantity, limits, one-entry/two-exit procedures and separate 50 bps qualification spread policy. No field was filled on your behalf.

Only after that explicit decision may the printed existing `run_testnet_qualification.py --execute` command be used. It revalidates the account, book, source, policy and approval; it may still refuse stale/changed conditions. It cannot resize/reprice the approved order to force a fill. It sends at most one entry and follows only the two bounded exact reduce-only exit attempts. The entry and exit fills must be matched to the registered team account and original cloid/oid. Actual fees/funding and final exchange positions/orders determine realized P&L and flatness; only then can genuine WHITELIST_TRADE_PROOF.json be saved. An actual fill still does not prove organizer acceptance/whitelisting.

For EMERGENCY_EXIT_REQUIRED or any unknown state: (1) stop new entries and preserve runtime/testnet/anchorium-bot-1/qualification.sqlite, nonces and original cloid/oid; (2) read original orderStatus, team userFills, frontendOpenOrders and par clearinghouseState; (3) reconcile the exact residual or label UNKNOWN when records disagree; (4) do not blindly resend the entry, erase the consumed attempt, enlarge a close, bypass the exit floor or resume revoked/expired permissions; (5) obtain a new explicit recovery authorization if the current permitted close cannot finish. There is no invented auto-recovery CLI flag.

## I. Remaining risks

**Small-position protective-stop acceptance is still unverified. No stop will be submitted by this isolated qualification route.** IOC closing is not persistent stop protection. The proposal retains legacy stop_trigger/stop_limit field names for its existing price-bound schema; these values do not create or certify an exchange stop. Historical exact full-close evidence is narrow and does not promise future acceptance or liquidity. A partial fill, disappearing book, delayed order status, network loss, rejection or price moving outside approved bounds can leave unprotected exposure requiring manual intervention. Cross margin shares account collateral; a 25 USDPR entry cap is not a guaranteed total-loss cap. The account contains much more collateral than the bounded entry; no full-balance trade is authorized. Fees and funding remain distinct from principal.

No autonomous strategy trading, recurring task, new closing exception, production-threshold relaxation or scored-DEX switch was added. Normal protection certification, controlled funded LONG/SHORT/recovery certification, PRACTICE_READY and LIVE_READY remain false. For this completed run, no proposal.json or approval template exists because no candidate passed. There is no exact trade to authorize. The single next action is a deliberate bounded read-only watcher run using section C; it will stop with exact approval files if an eligible opportunity is observed. Do not change the 10% depth policy just to force eligibility.
