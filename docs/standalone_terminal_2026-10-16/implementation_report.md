# Team Anchorium standalone terminal — release report

Later October 16–17 repair release: [overnight implementation report](</Users/adesh/Autonomous Trading Bot - Crypto /docs/overnight_activation_2026-10-16/implementation_report.md>). This document retains the original 2,574-test single-day release history.

## A. Application readiness

The local CLI is implemented at `scripts/anchorium_cli.py`: doctor, research, simulate, prepare, approve, start, status, report and stop. Default start is public-only. Exact-authorized start reuses the existing frozen manager, central execution/SDK, native Stop Limit adapter and daily coordinator. No new unrestricted submission path was added. No new trading session was started.

## B. Codex independence

Normal runtime is deterministic local Python. It has no paid-model dependency or API call and does not need the Codex app, a chat or a heartbeat. Both historical automations remain PAUSED. The Mac, Python process, power and internet are still dependencies. Public and authorized exchange APIs remain necessary.

## C. LONG readiness

Execution-capable integration exists, but genuine unattended strategy LONG qualification is BLOCKED. The historical controlled BTC round trip is one genuine cycle; it does not qualify a new strategy session. No new exact mandate or acceptance was created. SHORT stays disabled.

## D. Native protection

`exchange.partial_fill_safety.partial_path_assessment` checks the smallest runtime lot at entry, protective stop limit and closing bound. Increasing the proposed opening quantity cannot remove possible one-lot partials. Sampled one-lot bid notionals below are all under $10. The ordinary order minimum is $10. The separately evidenced historical IOC full-position closure is not evidence of a native-stop exception. `DailyLimitProtection` preserves normal stop minus one entry ATR and a 0.5% Stop Limit execution allowance. An accepted untriggered stop does not satisfy the actual linked trigger-fill/two-flat-readback proof gate.

The shortest valid path is authoritative venue clarification/evidence for subminimum native residual handling, or a genuinely minimum-compliant market/lot at the reviewed frozen stop/close prices, then separately approved tiny qualification using unchanged partial guards. The existing qualification and child/identity/cleanup infrastructure must be used; no actual qualification is possible under the sampled guard. Native Stop Market has a different documented 10% tolerance and was not substituted. Stop Limit can rest after a gap. No guard was disabled.

Primary sources: [competition guide](https://perpetual-alpha26.github.io/docs/), [venue errors](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses), [native TP/SL behavior](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl).

## E. Multiple trades

The terminal simulation executes two sequential fixture cycles with a win and a loss, plus rejection, uncertain entry, partial entry and partial exit episodes. Every event is SIMULATION, with no HTTP/socket access and ephemeral SDK keys only. Fault exposure remains visible and the same uncertain candidate is not blindly repeated. The synthetic whole-unit lot fixture is not actual par metadata. Real complete cycles remain one historical BTC cycle; currently approved new entry attempts are zero. A future independently accepted session can permit at most two attempts and one concurrent position.

## F. Capital

Proposed bankroll: 20,000 TEST USDPR. Approved bankroll: none. Qualified unattended notional: zero. Reported current collateral: 1000000.050512. Account balance is not approval. Targets 1,000/2,500/5,000/10,000 and offline stresses 25,000/50,000 remain proposals/research. The allocator uses the minimum of mandate/risk/margin/runtime size limits and both-sided best-level/L2/exit capacity, rounding down without order splitting. SP500 is independently runtime-eligible but that does not establish strategy or protective qualification.

| Market | Last observed route capacity USDPR | One-lot bid notional |
|---|---:|---:|
| par:BRENT | 9.3141 | 1.0343 |
| par:BTC | 48.93120 | 8.15030 |
| par:ETH | 49.78008 | 0.24386 |
| par:EWJ | 49.937329 | 0.095817 |
| par:EWY | 49.94600 | 0.15359 |
| par:GOLD | 19.65258 | 0.41787 |
| par:HYPE | 49.7889 | 0.7898 |
| par:SP500 | 7.6996 | 7.6951 |
| par:USDEUR | 9.89912 | 0.11243 |
| par:USDJPY | 49.0234 | 1.5803 |

Prices/capacities are explicitly time-stamped in the machine report; they are observations, not current executable promises or approved sizes.

## G. Autonomy

The observer runs until STOP/Ctrl+C/fatal interruption. Signing is independently bounded to one explicit IST day ending by 23:57, with a five-minute human acceptance window and no automatic renewal/restart/day rollover. The CLI hands a stopped signer back to a separate public client without a signer. This transition is tested offline; it has not been exercised with new real exchange orders.

## H. Risk, shutdown and repairs

Source/dependency/clock/rate/account/stream/reconciliation/UNKNOWN/protection/persistence and loss-budget gates halt entries. STOP revokes entry permission at the final signing check, while original exact risk recovery and owned cancellation may remain possible until expiry. Unknown or partial outcomes are reconciled by identity, never blindly resubmitted. Expired signing does not block read-only terminal reconciliation. Two authoritative flat/zero-order snapshots are required; unresolved exposure remains EXPOSED/UNKNOWN.

The real public soak found and repaired account WebSocket TLS trust configuration: it now uses the same verified Requests CA bundle and hostname checks as the market stream. The account receiver now runs independently of scanner REST waits, with event sequence checks preventing a concurrent notification from being cleared by reconciliation. Earlier soak attempts were stopped and preserved as diagnostic evidence. An earlier regression candidate changed source during these repairs and is not the release receipt.

The copied virtual-environment activation scripts also selected the original NSE environment; only the clone’s activation paths were repaired and the documented activation command was checked against its own Python prefix. No original-repository file or dependency installation was changed.

Internal logs rotate with documented retention; SQLite/memory/disk guards halt safely. Reports separate observed historical account P&L, current session events and simulation. UI states never turn submitted orders into fills.

## I. Full regression and soak

Full offline regression: **2574 tests, 0 failures, 0 errors, 0 skips**. Phase-0 and strategy freeze passed before and after; source hashes match.

Source SHA-256: `d254b0b1eb6bd7a08312ff5ff40d509a0485bf2b36b74d9e51412dd4ef86902f`. Receipt SHA-256: `ee14e96962a0b1d29208745903a4e048ba3ca92a8b40e9e4e20bbced96574957`. XML SHA-256: `796bf6d1cb303aa51159f7d5479bde976167f1fa6d004a34af7533c72ea2eef4`.

Final public soak: 902.0 seconds, 59 resource samples, 49 samples with both streams healthy; peak memory 139.56 MB; late high-watermark growth 0.0 MB; 723 public requests; recorded REST/HTTP errors {}; account stream last recovery label ACCOUNT_WEBSOCKET_DISCONNECTED; market stream last error None. Journal integrity ok; execution intents 0; background threads stopped True; terminal flat False.

The worker shutdown’s full reconciliation returned ExchangeError before two authoritative terminal readbacks; it retained UNKNOWN. Its guard allows only a 5-second local rate wait within a 40-second terminal read window; the precise exception message was not retained. No HTTP429 was recorded. The separate 90-second bounded public audit after the process stopped obtained two fresh ready/zero-position/zero-order readbacks. The raw worker outcome remains unchanged; final flatness is established by final_account/audit.json and its raw receipts.

This is a bounded development soak, not a multi-day unattended execution certificate. Original policies, source freeze, proofs, certificate and all original testnet database dumps remain unchanged. Requirements were aligned to the already-installed tested versions; no dependency installation was needed.

## J. Exact terminal commands

See [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) for every tested command and explicit future approval/start paths. Safe command checks, real CLI simulations/research, public diagnostics/proposal and STOP/status/report evidence are retained in this directory. The actual authorized start was deliberately not executed without its prerequisites and exact human mandate.

## K. Genuine P&L

Original verified October 15 BTC: BUY 0.0002 at 81,512, order 62755970305 / fill 800659111758533, fee 0.014672; SELL 0.0002 at 81,909, order 62805581662 / fill 260274449763192, fee 0.014743. Gross +0.0794, total fees 0.029415, actual funding +0.000527: **net +0.050512 TEST USDPR**. Original BUY/SELL proofs were preserved byte-for-byte.

October 16 actual observed fills: 0; gross 0; fees 0; funding 0; net 0. New actual exchange submissions by this release: zero. Final positions []; final open orders []. No organizer whitelist/reset claim is made.
