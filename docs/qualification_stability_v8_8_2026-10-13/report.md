# Team Anchorium — V8.8 qualification stability and readiness

Implementation complete. One read-only preparation was run after the complete offline regression. No actual signature, order, fill or whitelist confirmation was created.

## 1. HTTP delay: confirmed defects and what remains unknown

The old transport already supplied `timeout=10` to Requests; a missing timeout was not the cause. The supplied traceback establishes an interrupted HTTPS response wait but does not establish its elapsed duration, packet behavior or whether the venue, DNS, TLS, proxy or local network caused it. We cannot attribute that delay to the exchange.

A socket timeout is not a total wall-clock deadline: a read timeout measures inactivity between received bytes and connection timing can involve multiple addresses. The old implementation had no independent caller deadline, flattened transport failures, gave no progress while waiting and let Ctrl+C escape without final JSON. These are confirmed code defects. [Requests timeout semantics](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts).

Five original regression checks failed on the saved V8.7 source. Original failures and subsequent failed development runs are preserved. The corrected focused run passed 212 cases.

## 2. Files and functions modified

- `algo-trading-bot/exchange/hyperliquid_client.py`: `RequestsInfoTransport.__init__`, `__call__`, `_worker`, `_failure`, `_caused_by`, `_retry_after`, `close`; `HyperliquidClient.__init__`, `post_info`, `read_snapshot_scope`. Public HTTPS limits, response bounds, safe error codes and narrow preparation snapshot reuse.
- `algo-trading-bot/exchange/rate_limits.py`: `__init__`, `read_budget_delay_ms`, `wait_for_read_budget`, `error`, `read`, `_read_owned`, `_report_owned`. Grounded budget waits, preserved server guidance, public-query whitelist, interruption-safe coalescing and detailed failure records.
- `algo-trading-bot/exchange/testnet_qualification.py`: `QualificationContextProvider.__init__`, `load`. Uses the existing manager for bounded budget waits and short-lived static snapshots only during read-only preparation. Dynamic sizing, exact closing scope and signed execution behavior are preserved.
- `scripts/run_testnet_qualification.py`: `prepare`, `main`. Flushed progress stages and durations, 240-second preparation admission deadline, interruption diagnostics, SQLite cleanup, explicit real-liquidity classification and truthful no-fill proof.
- Added `algo-trading-bot/test_qualification_stability_v8_8.py`: 62 offline cases for hung headers/body, socket failures, HTTP statuses, retry guidance, cancellation, budget forecasts/weights, snapshots, interrupted preparation/recovery and saved real thin books. Existing suites retain exact approval, partial-fill, duplicate, unknown order, stop rejection and restart coverage.

Only those four implementation files changed from the V8.7 source snapshot; one test file was added. The original NSE repo, frozen brain/methods, indicators, UTC convention, 300-bar requirement, ATR 0.40%, production 15 bps spread ceiling, Top-3, production config, signer SDK and closing-evidence scope remain unchanged.

## 3. Timeouts, retries and cancellation

Public `/info` calls now have separately configurable 3.05-second connect and 5-second response inactivity timeouts, plus a 12-second total caller deadline and 8 MiB body limit. Redirects and hidden HTTP-adapter retries are disabled. Deadline/cancellation waits poll at 50 ms; Ctrl+C can reach the calling preparation thread.

There is at most one public HTTP worker per transport. A worker stuck in an OS/DNS call may finish cleanup later; it cannot keep the caller waiting indefinitely or create an unlimited number of workers. The occupied slot blocks subsequent reads within their own deadlines. It has no SQLite, nonce, private-key, signature or exchange-write access.

Public idempotent reads receive at most three attempts with existing exponential jitter and a 45-second admission/wait budget. Each HTTP attempt also has its 12-second caller deadline. The read-loop budget checks admission and waits; it is not an extra socket-level cancellation timer. Preparation stops admission after 240 seconds and saves a lock reason instead of continuing indefinitely. Error codes separately identify connect timeout, read timeout, DNS, TLS, reset/connection failure, 429, 5xx, malformed JSON, body limit, cancellation and total deadline.

Retry-After seconds or HTTP date are honored without shortening them to 30 seconds. If the venue asks for a wait longer than the permitted preparation/read window, preparation terminates; it never retries earlier. Total-deadline, TLS, malformed-response and non-retryable 4xx failures do not receive blind repeats. Signed actions cannot enter the public retry front door. The existing SDK signing/unknown-order procedure is untouched.

Keyboard interruption writes PREPARATION_INTERRUPTED and diagnostic/readiness/no-fill JSON, closes SQLite and exits 130. A valid local checkpoint checksum does not make incomplete account history valid. Restart begins with unknown account truth until fresh reconciliation succeeds; a timed-out request cannot prove flat.

## 4. Rate-budget behavior

Hyperliquid documents 1,200 weighted REST units per minute. The existing weights remain 2 for l2Book/allMids/clearinghouseState/orderStatus/spotClearinghouseState/exchangeStatus, 60 for userRole and 20 for other info requests, with existing additional history/candle-response accounting. The 120-unit safety reserve remains. [Official request limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

Each attempted upstream read is charged, including unsuccessful attempts. Reopening the same read-only SQLite keeps the same limiter and rolling weights. Preparation estimates the next retry from actual recorded weight expiry and server backoff, prints WAITING_FOR_RATE_BUDGET with the cause/required weight/next time, and waits at most 65 seconds for a context bundle. Per-read waits share the read admission budget. Cancellation is responsive. If no early capacity is proven it conservatively defers the whole window.

Identical concurrent public reads share one in-flight result; an interrupted leader now returns an interruption error to followers rather than None-as-success. Only mode, agent list and fees may reuse their original response inside a preparation-only one-second scope, with the original timestamp and defensive copies. Positions, orders, histories, books and mark/oracle prices are always fetched afresh. Incremental account history and overlap for late corrections are retained; essential reconciliation is not skipped. Actual execution does not use this snapshot scope.

The IP budget is this process’s observed accounting; other processes behind the same public IP remain outside that observation. Human sole-host confirmation applies to signing, not independent observation of every HTTP consumer.

## 5. Fresh BTC / ETH / HYPE observations

Final preparation: 2026-10-13T04:57:07.772111+00:00 through 2026-10-13T04:59:28.728117+00:00. Each market is its own actual observation; the rows are not simultaneous or a future fill guarantee.

| Market | Bid / ask | BBO bid / ask size | 10% bid / ask caps | Lot | Largest quantity / entry notional within bounds | Spread bps | Outcome |
|---|---|---|---|---|---|---|---|
| par:BTC | 83314.0 / 83431.0 | 0.0041 / 0.0002 | 0.00041 / 0.00002 | 0.0001 | 0.0000 / 0.0000 | 14.03340429997900986536327926 | INSUFFICIENT_REAL_LIQUIDITY |
| par:ETH | 2512.8 / 2519.4 | 2.0083 / 0.1236 | 0.20083 / 0.01236 | 0.0001 | 0.0099 / 24.95394 | 26.23107189698342673184690593 | QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL |
| par:HYPE | 82.343 / 82.721 | 61.06 / 6.74 | 6.106 / 0.674 | 0.01 | 0.30 / 24.82860 | 45.80041680802597780254931421 | QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL |

**par:BTC** at 2026-10-13T10:29:25.579000+05:30: account READY, leverage {'type': 'cross', 'value': 1}, available long/short margin ['1000000.0', '1000000.0']. Opening minimum remains 10; entry cap 25. Exact blocker: QUALIFICATION_NO_LOT_MEETS_OPENING_MINIMUM_WITHIN_BOUNDS. One-lot close assessment: {'ready': True, 'possible_residual_count': 1, 'subminimum_residuals': [{'quantity': '0.0001', 'notional_at_floor': '8.2069', 'proof': {'scope': 'VERIFIED_EXACT_FULL_POSITION_IOC_CLOSE', 'historical_oid': 62228843959, 'evidence': 'V8.5_ORIGINAL_ORDER_AND_FULL_POSITION_FILL_READBACK', 'evidence_sha256': 'c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764'}}], 'scope': 'HISTORICAL_SHAPES_AND_APPROVED_PRICE_FLOOR_NOT_FUTURE_FILL_GUARANTEE'}. All possible residuals for an opening are certified only when the solver passes the entire entry; rejected books do not establish a ready trade.
Qualification fee assumption from current userFees × 2 HIP-3 convention: 0.09000% per taker fill. It remains a planning estimate; actual net P&L requires reported actual fill fees/funding.

**par:ETH** at 2026-10-13T10:28:19.663000+05:30: account READY, leverage {'type': 'cross', 'value': 1}, available long/short margin ['1000000.0', '1000000.0']. Opening minimum remains 10; entry cap 25. Exact blocker: QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL. One-lot close assessment: {'ready': False, 'blocker': 'QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL', 'first_unverified_quantity': '0.0001', 'notional_at_floor': '0.24753'}. All possible residuals for an opening are certified only when the solver passes the entire entry; rejected books do not establish a ready trade.
Qualification fee assumption from current userFees × 2 HIP-3 convention: 0.09000% per taker fill. It remains a planning estimate; actual net P&L requires reported actual fill fees/funding.

**par:HYPE** at 2026-10-13T10:28:27.932000+05:30: account READY, leverage {'type': 'cross', 'value': 1}, available long/short margin ['1000000.0', '1000000.0']. Opening minimum remains 10; entry cap 25. Exact blocker: QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL. One-lot close assessment: {'ready': False, 'blocker': 'QUALIFICATION_UNVERIFIED_CLOSE_RESIDUAL', 'first_unverified_quantity': '0.01', 'notional_at_floor': '0.81113'}. All possible residuals for an opening are certified only when the solver passes the entire entry; rejected books do not establish a ready trade.
Qualification fee assumption from current userFees × 2 HIP-3 convention: 0.09000% per taker fill. It remains a planning estimate; actual net P&L requires reported actual fill fees/funding.

Actual dynamic sizing initially passed BTC with 0.0002 at 16.6944 USDPR when ask size was 0.0301. It was not submitted or offered as the final current order. The final reread saw ask size 0.0002; its 10% cap was 0.00002, below one lot. The final eligibility check correctly superseded the earlier admission and generated no approvable proposal. This is real book deterioration, not a timeout or sizing defect.

The actual preparation took 140.956 seconds. Budget wait episodes: [{'start_elapsed_seconds': 14.437, 'first_delay_seconds': 50.559, 'resumed_elapsed_seconds': 65.001, 'observed_wait_seconds': 50.564}, {'start_elapsed_seconds': 71.891, 'first_delay_seconds': 1.199, 'resumed_elapsed_seconds': 73.097, 'observed_wait_seconds': 1.206}, {'start_elapsed_seconds': 80.162, 'first_delay_seconds': 50.369, 'resumed_elapsed_seconds': 130.535, 'observed_wait_seconds': 50.373}]. Public read failures: {}; maximum upstream read duration 0.5162094589322805 seconds. These are observations from this bounded run, not guarantees about future network latency.

The solver floors whole lots across the 25 cap, both 10% depth caps, maxTradeSzs and available margin including fee reserve. It tests descending lot quantities without rounding up. Offline cases verify two-lot BTC selection when three lots are too large and the unchanged rejection when no whole lot can satisfy the ordinary minimum. ETH/HYPE do not inherit BTC SELL historical closing evidence.

Current account reconciliation ready: True; actual preflight positions/orders flat observed: True. This is a read observation, not post-trade flat proof. Public weights before/after reopen: [212, 212]; final rate state/weight: HEALTHY / 580 of 1200; snapshot reuse hits: 4.

Signer local status: LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED; no nonce allocated or actual signature. Saved human statement reused: Human confirmation of sole signing host; not trade or risk approval. This does not independently inspect other computers and is not trade/risk approval. Account address remains 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C; API signer remains 0x46c9BED595770150752E7fA3806449F81E0Ec6f9; SDK future account_address is the registered team account.

## 6. Regression, freeze and evidence

Full regression: **1822 passed, zero failures, errors or skips**. Baseline 1760 plus 62 new cases. Focused corrected run: 212 passed. Phase-0 and strategy-freeze checks passed before and after the full suite. Source digest stayed b2ad88fde083120ed3f1502935e1f33946cd1e2509cccb46f25289785cb963a3. Full XML digest and source-bound receipt are saved in regression_release.

SQLite integrity ok; checkpoint count 2; checksum verification True; clean shutdown True; current checkpoint core source identity matches. All exchange intent/action/management counts: {'intents': 0, 'api_actions': 0, 'signed_management': 0}. Progress event count: 648; stages: CHECKING_NETWORK, WAITING_FOR_HTTP_RESPONSE, CHECKING_ACCOUNT, RECONCILING_ACCOUNT, CHECKING_BTC_BOOK, CHECKING_RATE_BUDGET, VERIFYING_RESIDUAL_EXITS, CHECKING_ETH_BOOK, WAITING_FOR_RATE_BUDGET, CHECKING_HYPE_BOOK.

Failed reproductions, failed test attempts and earlier V8.7 evidence are retained. No actual account/order journal was reset. The V8.8 report reads the final evidence only and verifies current full-source equality before writing.

## 7. Proposal verdict

**QUALIFICATION_LOCKED.** NO_MARKET_PASSES_QUALIFICATION_MARKET_AND_RESIDUAL_RULE. No eligible current proposal ID or order exists to approve. This verdict retains the ordinary entry minimum and existing risk gates.

## 8. Exact next Terminal preparation command

This prepares only, chooses a new evidence directory and uses the successful source-bound receipt. It does not sign or consume authorization. Run it once when you want another current observation; do not run simultaneous copies.

```bash
cd "/Users/adesh/Autonomous Trading Bot - Crypto "
.venv/bin/python scripts/run_testnet_qualification.py \
  --output-directory "docs/qualification_stability_v8_8_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \
  --test-receipt docs/qualification_stability_v8_8_2026-10-13/regression_release/test_receipt.json
```

## 9. Existing exact approval procedure

Not actionable now: no eligible fresh proposal was generated. Never approve an old or rejected proposal.

The existing QualificationApproval schema requires the current proposal_hash; nonempty operator_approval; actual integer approved_ms and expires_ms, ordered and no more than 300,000 ms apart; approval within 300,000 ms of the proposal observation. No backdating/extension. Its six acknowledgments are manually_verified_wallets, sole_signer_host_confirmed, maximum_one_entry, unverified_stop_risk_accepted, qualification_spread_limit_accepted and possible_manual_residual_recovery_accepted. All remain empty/false unless explicitly approved by the human.

Only after separately authorized exact review can the same launcher use its existing --execute, --proposal-file, --operator-approval-file and --test-receipt arguments. This task supplied no execute flag and created no trading permission. Later fresh revalidation can still reject an approved proposal without resizing or repricing it.

## 10. Exchange limits and emergency recovery

**ACTUAL_PROTECTION_READY = FALSE; CONTROLLED_EXECUTION_READY = FALSE; PRACTICE_READY = FALSE; LIVE_READY = FALSE.** Small-position stop acceptance/readback/coverage remains unverified. Immediate reduce-only IOC closure is not persistent protection. Historical exact-full-position BTC SELL one-lot evidence supports that narrow shape only, not ETH/HYPE SELL, stops or guaranteed future acceptance/fills. No scope was broadened.

If a later explicitly approved entry fills, verify actual userFills/order ID under the registered team wallet, reconcile exact quantity, then use the already permitted reduce-only exit procedure within the fixed floor, original expiry, at most two exits and five-action budget. Closing size never exceeds the actual reconciled position. A full-position exception cannot increase exposure.

For uncertainty/residual exposure: halt new entries, keep runtime/testnet/anchorium-bot-1/qualification.sqlite, original order/cloid IDs, consumed-entry record and nonce history. Read original orderStatus, team userFills, frontendOpenOrders and par positions. Never resend an uncertain entry. Do not infer flat from a local acknowledgment. Read-only restart recovery must reconcile authoritative account truth. If price, partial fill, failed close, expiry, connectivity or budgets prevent closure, report EMERGENCY_EXIT_REQUIRED and obtain explicit supervised recovery authorization rather than expanding bounds or repeating automatically.

Notional 25 and 1x CROSS are limits on the attempted entry, not a guaranteed account loss cap. Fees/funding and unprotected cross-margin exposure remain material risks. Actual whitelist qualification requires a verified real fill and organizer confirmation. The saved WHITELIST_TRADE_PROOF.json correctly records no actual fill, no trade-derived flat proof and no whitelist confirmation. Software cannot guarantee market liquidity, closure or positive P&L.

