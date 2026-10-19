# V5.3 final opening-day release audit

**NO-GO for autonomous PAS trading, including when funding alone is excluded.**

As of 2026-10-19T16:35:00.927000+05:30. The requested engineering fixes are verified; remaining venue/account evidence has not been fabricated. No exchange write, actual-wallet signature, configuration application or human acceptance was created.

Source `d0b72ec4cbce7d74cdad62b480ac22a8dc336182fc1445612b7666b95747f9f9`; Git `dcccd829670b550a0429213683202f55bf567e28` with the exact dirty-source manifest retained. **3109 tests passed**, zero failures/errors/skips. Frozen signal_brain and all manifested strategy methods/parameters pass against nse-working-baseline. All 53 original journals and 20 protected proof files remain unchanged.

## Software repairs

- Reproduced dead-worker output reporting INTERRUPTED_UNCLEAN while TRADING_AUTHORIZED and AUTO_TRADING_ACTIVE remained true. Status/report/dashboard now invalidate cached authority on dead/stalled/expired/mismatched workers, retain historical fill evidence, and refresh source/account/fee/funding/candle ages at read time without changing stored evidence.
- Incomplete public history and configuration discovery now return a nonzero exit status. Their failure JSON remains available for diagnosis.
- Added opening-check, a read-only 14-status checklist with failed requirements and executable next steps. It cannot create permission or bypass any execution guard. No new execution gate was introduced.
- Existing accepted-session BUY/SELL lifecycle needs no individual order prompts. Source-bound human session activation, risk exits, one-position rule, strict expiry, frozen strategy and PAPER/false migration defaults remain.

## Independent statuses

| Requirement | Value | Supporting evidence |
|---|---|---|
| AUTOMATION_IMPLEMENTED | TRUE | Full current-source offline lifecycle and conditional-activation suites passed; this is software evidence only. |
| RELEASE_VERIFIED | TRUE | 3109 passed, 0 failures/errors/skips; receipt and XML match the current dirty source hash. |
| OBSERVER_HEALTHY | TRUE | Public worker 83079, owner lock, current source, market/account streams and fresh account read; bounded soak and SQLite integrity retained. |
| FUNDING_VERIFIED | FALSE | Fresh public USDP observation: USDP_ZERO, balance 0; automatic detection grants no authority. |
| ACCOUNT_IDENTITY_VERIFIED | FALSE | Configured API address is publicly approved. Official public leaderboard names Team Anchorium but publishes no wallet binding; no retained operator-reviewed scored wallet record was supplied. Local signer ownership is not certified here. |
| BTC_1X_VERIFIED | FALSE | Latest actual BTC leverage: {'type': 'cross', 'value': 20}; no configuration was submitted. |
| EWY_1X_VERIFIED | FALSE | Latest actual EWY leverage: {'type': 'cross', 'value': 20}; no configuration was submitted. |
| HISTORICAL_ORDER_SAFE | FALSE | Original CLOID 0xac0eea156fcec80986dd67c9057b6ded still has two unknownOid replies, no matching historical order, and no admissible isolation. Original journal/nonce/attempt untouched. |
| BTC_NATIVE_AND_RESIDUAL_QUALIFIED | FALSE | No genuine PAS trigger-to-linked-closing-fill proof. Fresh unsigned proposal: minimum lot 0.00001 BTC, about 0.81 USDP at reviewed stop, below ordinary $10 policy; no supported subminimum stop/cleanup exception. |
| EWY_NATIVE_AND_RESIDUAL_QUALIFIED | FALSE | No genuine PAS trigger-to-linked-closing-fill proof. Fresh unsigned proposal: minimum lot 0.001 EWY, about 0.157 USDP at reviewed stop, below ordinary $10 policy; no supported subminimum stop/cleanup exception. |
| MARKET_DATA_FRESH | FALSE | Warmup is sufficient (959 BTC / 4053 EWY contiguous retained bars), but authentic upstream candles/trades remain stale. Detailed current ages and raw REST/stream diagnostics are in opening_status.json and history_review_network/. |
| EXACT_SESSION_ACCEPTED | FALSE | No genuine exact current-source finite PAS acceptance exists or was created. Current user intent does not complete the earlier required post-funding account verification or missing route evidence. |
| TRADING_AUTHORIZED | FALSE | The worker is public-only with no signer or mandate. Funding, a date, a process, and synthetic tests cannot activate it. |
| AUTO_TRADING_ACTIVE | FALSE | No authorized worker or matching owned transmitted PAS order/fill exists in this run. |

Every false requirement has its next step in [opening_status.json](opening_status.json); exact verified CLI commands are in [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md).

## Why the remaining gates stay

The fresh native proposals show that larger entry sizing does not eliminate a possible one-lot partial fill or final exit remainder. The [official order-error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) lists the ordinary $10 minimum. A PAS subminimum fixed native-stop route is not independently established. Removing the guard would assert an exit capability that has not been demonstrated.

The [official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes mark triggers, fixed-size stops and partially filled parent-order behavior. An application watcher does not supply exchange-resident outage protection. Switching to Stop Market would also change the approved execution allowance. No independently validated replacement was found; no synthetic test was relabeled as genuine venue qualification.

The original action is older than the documented nonce horizon and the account is currently flat. Those facts constrain future replay risk but do not establish the original historical outcome or complete accounting. The exact original causal/terminal record or a separately reviewed, expressly accepted finite isolation policy remains necessary. No generic UNKNOWN bypass or reset was introduced.

The official public leaderboard was inspected through its declared data URLs. Team Anchorium is listed, but those rows have no public wallet address. The configured wallet therefore cannot be certified from a team-name match. Retained page/JSON hashes and matching rows are in public_registration_review/.

## Continuous-operation and opening drill

The actual bounded soak lasted 180082 ms with 7 samples: worker liveness/owner lock/source verified, healthy market/account streams, account reconciliation ages and REST timings retained, SQLite integrity ok, local event delivery observed. External alert delivery was not configured or tested. The first sandbox PID probe was unavailable and is retained separately; the independent host probe verified liveness. No overnight uptime or crash-survival guarantee is claimed.

A duplicate worker was actually rejected before client construction. The source-change shutdown of the previous observer completed with two flat readbacks and healthy persistence; its history cache was reused without resetting the original execution state. Crash/restart, expiry, disconnect, partial-fill and signing-barrier behavior is covered by the offline regression, not represented as a destructive production crash experiment.

The 17-scenario pure readiness drill had zero prompts, no network, no signer and zero signatures/writes. Every omitted prerequisite blocked the simulated handoff. Separate PAS offline SDK tests exercised frozen LONG entry, reported fixture fills, protection, partial exits, accounting and expiry with ephemeral keys and no HTTP. They do not qualify an actual account, residual route or profitable edge.

## Opening and operation

The [published scored interval](https://perpetual-alpha26.github.io/schedule) starts October 19 at 12:00 UTC / 17:30 IST and ends November 6 at that same UTC time. Calendar opening and funding do not resolve the other statuses. No unnecessary practice-date permission gate was added.

The standalone public worker is PID 83079, session 16921000ecb741f1a3f506b60acba565, state runtime/pas-btc-ewy-v5-2. It detects funding automatically, normally with up to one 300-second account polling interval of delay. It cannot sign. A real session can operate without per-BUY/SELL prompts only after all prerequisites and its exact finite acceptance pass. The current contract cannot accept missing funding/qualification in advance. No profit, error-free operation or deadline launch is guaranteed.

Review the runbook for funding/history/configuration/qualification preparation, exact session acceptance, conditional launch, stop and actual P&L reconciliation. Read-only monitoring continues; the Mac, process, power, network and exchange remain dependencies.

After the bounded soak, one genuine market WebSocket reconnection was observed. The checklist reported `OBSERVER_HEALTHY=false` during incomplete reconciliation and returned to `true` after recovery. The earlier snapshots are retained as `before_reconnect_*`; the final status uses the actual recovered state.
