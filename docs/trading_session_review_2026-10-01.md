# Trading session audit — 1 October 2026

The final paper result was **₹0.00 because the bot made zero trades**. The paper journal confirms zero completed trades, zero fills, zero setup attempts, and no reserved position risk. All three subscribed stocks remained below the configured 0.40% live ATR floor throughout the recorded stream. Fixing startup warmup alone would therefore not have made this session tradeable under the existing rules.

This audit examines all 3,102 logical lines in the supplied file, reconstructs 291 logged candles, checks the paper database read-only, evaluates the unchanged signal brain offline, and probes historical-data validation. It makes no new broker requests or orders and changes no production trading code or thresholds. A profitable future day cannot be guaranteed, including a small profit.

## 1. What actually ran

The file combines seven authentication starts, several code versions, read-only repair checks, and one observed paper stream. Some morning and midday checks were my verification runs during the earlier repair. A completed stock-selection check does not start monitoring or place trades.

| Time, IST | Evidence | Meaning |
|---|---|---|
| 09:02–09:03 | Original NSE timeout; configured fallback; 15 candidates, zero qualifiers | The original startup could not discover the dynamic universe. That fallback behavior was subsequently removed. |
| 09:18–09:23 | Fresh dynamic discovery; 46 screened, seven qualified; top three selected | Read-only repair verification succeeded. It did not start a trading engine. |
| 09:23–09:30 | Historical-data throttling during another verification | This interrupted check is not a completed trading session. |
| 09:30–09:40 | Required screening completed, then optional history exhausted the budget and discarded the watchlist | This earlier failure was subsequently corrected so optional RVOL history cannot cancel completed qualification. |
| 12:43–12:53 | Fresh verification selected RSYSTEMS, RITES, GLASSWALL | Another read-only check; historical responses differed from other runs. |
| 12:59–13:06 | User check selected RSYSTEMS, RITES, ELEVATE | Discovery succeeded; extra history remained incomplete. |
| 13:12–13:22 | Regular bot repeated screening: 46 attempts, 41 usable candidates, five qualifiers | The actual paper startup took about ten minutes. It made 95 historical calls and received 48 rate-limit responses. |
| 13:22:06 | Websocket connected; three tokens subscribed | Observed paper monitoring began. |
| 13:24 | All three moved to STANDBY after their second candle | Early volatility readings were below both relevant gates. |
| 14:30 onward | 90 `ENTRY_CUTOFF_REACHED` messages | The configured entry window had closed. |
| 15:00 | No position to square off; final daily P&L ₹0.00 | Normal shutdown with no trades. |

The fallback message near the start belongs to the original morning version. Later dynamic discovery scans do not revert to that configured list. The latest regular-bot discovery report identifies `DYNAMIC_NSE_DISCOVERY` and records no configured-stock substitution.

## 2. The decisive reason for no trades

The runtime subscribes only to the chosen watchlist. Each of those stocks generated 97 completed candles from the observed 13:22–14:58 candle sequence. Every recorded ATR reading was below 0.40%. Each stock logged one ACTIVE candle followed by 96 STANDBY candles, with no recovery transition.

| Stock | Previous-session screening ATR% | Maximum reconstructed ATR% before entry cutoff | Maximum through recorded stream | Mature bars passing 0.40% |
|---|---:|---:|---:|---:|
| RSYSTEMS | 0.991% | 0.385% | 0.390% | 0 |
| RITES | 0.806% | 0.217% | 0.336% | 0 |
| ELEVATE | 0.782% | 0.309% | 0.368% | 0 |

The maxima above come from recalculating the unchanged rolling ATR over logged OHLCV, which is rounded to two decimals. They are diagnostic approximations. The original firewall telemetry independently contains no recovery above the floor. The differences from the logged rounded ATR amounts are at most ₹0.005.

There are several separate volatility controls: the signal brain's 0.06% minimum, the symbol's 0.35% standby trigger, its 0.40% recovery requirement, the 0.40% immediate entry firewall, and the previous-session screening floor. Changing one value would not necessarily open the remaining gates. These controls are policy choices; a high rejection rate alone does not prove that they are bugs.

The premature standby issue described in the earlier review remains real. The longer log adds decisive evidence: even after warmup, none of the recorded stocks met the current live entry floor. Removing the early transition would not overcome that floor.

## 3. Potential signals were present beneath the execution gates

The live orchestrator checks `SYMBOL_NOT_ACTIVE` before generating the signal brain output. Consequently, the absence of live `[SIGNAL]` events does not establish that the signal formula found no patterns.

Offline evaluation of the unchanged signal brain on the reconstructed candles produced these potential signals before the entry cutoff and after the minimum candle count, with direction permitted by the same daily-bias logic:

| Stock | Potential signals before cutoff | All below live floor? |
|---|---:|---|
| RSYSTEMS | 4 | Yes |
| RITES | 3 | Yes |
| ELEVATE | 3 | Yes |

For example, reconstructed RSYSTEMS had a BUY pattern on the 14:20 candle, known after its close around 14:21, at approximately 0.354% ATR. It did not satisfy the 0.40% live floor. Reconstructed ELEVATE had a BUY pattern on the 14:15 candle, around 0.252% ATR. That likewise did not qualify for live entry.

These ten observations are **not ten executable trades or ten missed profits**. The reconstruction lacks full morning history, observed bid/ask/depth at each decision, exact tick order, and actual fills. Costs, position arbitration, stops, targets, stale-data checks, and the daily setup cap would still apply. The observed stocks ending higher is hindsight, not evidence that a causal entry would have earned a positive net return.

## 4. Confirmed repairs and research priorities

| Priority | Finding | Evidence and consequence | Appropriate improvement |
|---|---|---|---|
| High | Midday monitoring start | Streaming began 13:22, four hours and seven minutes after market open. Only 68 minutes remained before the entry cutoff; collecting 15 candles left about 53 minutes. | Complete discovery before open and run one regular bot instance. Keep login, bulk downloads, historical enrichment, and streaming visibly distinct. |
| High | No current-session history initialization | Each CandleBuilder starts with an empty DataFrame. Premarket history is used for selection, not seeded into today's builder. | For late startup or reconnect gaps, load and validate today's completed regular-session candles before allowing entries. Reconcile the history/live boundary to avoid duplicates and volume double counting. If required history is unavailable, explicitly block entries while continuing existing-position protection. |
| High | Volatility state changes during warmup | The callback records ATR on candle one; standby is reached on candle two. ATR-14 uses the available shorter window initially. | Keep the entry warmup gate and only count confirmed volatility readings after sufficient valid candles. Preserve all post-warmup volatility and exit protections. |
| High | Current ATR policy excludes every observed setup | All recorded mature bars are below the live floor. The core signal floor is materially lower. | Treat any alternative execution floor as a separately labelled paper/shadow research variant. Compare fee-aware economics and held-out outcomes; do not change production thresholds to fit this one day. |
| High | Selection is based on yesterday, with a static three-stock watchlist | High previous-session end-of-day ATR did not persist in the afternoon. Other qualifying shares were not streamed. | Research current-session confirmation and a bounded reserve watchlist using verified identities, current quotes, liquidity, and complete candle context. Preserve the one-position and daily risk limits. More subscriptions do not guarantee a valid trade. |
| High | Repeated historical requests and broker throttling | Across the combined file: 245 rate-denial messages, 189 cooldown warnings, and 38 historical-fetch failure messages. The final startup alone had 48 rate-limit responses. | Cache successful validated completed-session candles by exchange, token, timeframe, session, and schema. Reuse them across check/regular startup; share the provider request budget across processes and prevent simultaneous bot instances. Do not cache failure responses as empty market data. |
| High | Historical candle validation gaps | Offline malformed-data probes were accepted, as detailed below. | Add strict historical-reader validation before qualification or bootstrap: finite values, required timestamps, uniqueness, expected date, session bounds, valid prices/volume, and documented completeness. These checks can be added around the frozen signal formulas. |
| Medium | Additional volume history is uneven | Final watchlist profiles: RSYSTEMS three sessions; RITES and ELEVATE one each. RVOL requires at least three historical samples. | Fetch profiles round-robin until each selected stock has the minimum baseline, then enrich further. Cache valid immutable profiles. Preserve unknown RVOL rather than inventing participation data. |
| Medium | Premarket spread/depth are assumptions | Screening defaults to a 0.05% spread and available depth; opportunity scoring supplies zero observed depth. Actual live quotes are checked later. | Label historical qualification separately from current execution readiness. Rank current executable opportunities using observed quotes and depth. The final discovery report already exposes the premarket assumption. |
| Medium | Rejections conceal downstream evidence | STANDBY is tested before the signal brain; generic `SYMBOL_NOT_ACTIVE` hides the measured volatility and potential pattern. | Record signal output separately from permission to execute, with explicit gate reasons and data maturity. Read-only diagnostics must not create orders or claim profitable missed fills. |
| Medium | Shared log contains seven runs and several versions | Old failures and repaired behavior appear together. Authentication/check completion can be mistaken for trading activity. | Include a run ID, command purpose, code revision, start/end status, and separate execution/read-only logs. Report total historical requests separately from bulk HTTP calls. |
| Low | Redundant rejection output | The stream repeats evaluation of all three stocks after each candle close: 591 `SYMBOL_NOT_ACTIVE` messages, 12 WARMUP messages, and 90 cutoff messages. | Retain durable events, but emit concise terminal summaries when the state/reason changes. Show completed/required candle counts and the relevant threshold. |
| Low | Some configuration values are misleading or ignored | The ATR recheck interval is stored as 1,800 seconds but the candle callback updates the firewall every minute; orchestrator warmup is a literal 15. | Choose and document one intended cadence. Use the shared warmup configuration consistently. Changing cadence affects behavior and needs its own regression checks. |

The original NSE download/fallback problem and cancellation of qualification by optional history were repaired earlier. They should remain regression-protected; their historical messages in this accumulated log are not evidence of a fresh fallback in the final run.

## 5. Historical validation probes

The following tests use synthetic malformed frames solely to assess validation, not to establish trading results. A valid 300-row baseline was accepted as expected. Each malformed variant was also accepted by the current `validate_candle_data` helper:

- Duplicate candle timestamp.
- A row with NaN OHLC prices.
- NaN volume in one row.
- Missing Timestamp column.
- A valid frame dated a different session from the requested one.

The helper has no expected-session argument, and the historical reader does not independently verify that returned rows match the requested date. That responsibility needs to be made explicit. Existing live tick checks reject invalid individual prices; this audit finding concerns the historical-frame validation path.

There is no evidence in today's supplied file that those malformed cases caused the zero-trade outcome. They are confirmed implementation gaps to repair and cover with regression tests.

## 6. Small profit still needs enough movement to pay costs

The bot's standard fee assumption is consistent with Angel One's published intraday brokerage: lower of ₹20 or 0.1% per executed order, with a ₹5 minimum. Statutory charges and GST are additional. The account's actual plan and contract-note rounding need verification before live execution. [Angel One charges](https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges)

Illustration using 33 shares bought around ₹300, nearly ₹9,900 of cash exposure:

| Reference exit | Gross price gain | Estimated fees | Net after fees | Net with configured 0.05% adverse price haircut on each leg |
|---|---:|---:|---:|---:|
| ₹301 | ₹33.00 | ₹26.93 | ₹6.07 | **−₹3.84** |
| ₹302 | ₹66.00 | ₹26.97 | ₹39.03 | **₹29.09** |

These are calculations from the current fee model, not executed trades or forecasts. Additional spread/impact is excluded. Price haircuts already represent an execution disadvantage and must not be counted twice when modelling actual bid/ask fills.

The desired ₹5/₹10/₹20 net profit is possible only when a real causal entry and exit deliver enough gross profit after all costs and losses. Lowering `MIN_NET_PROFIT` or removing the net risk/reward test does not create that movement. Cash sizing, lot size, available depth, stop distance, and the remaining ₹100/₹200 risk allowances still determine whether an entry is economically valid.

## 7. What worked and should be retained

- The later dynamic scans examined all 141,994 records and identified 1,580 broker-eligible NSE equity shares. The master also includes other exchanges and derivatives; the current strategy intentionally excludes those instruments.
- The repaired official NSE download endpoints worked. Cached-source/date/schema checks and the no-configured-list behavior remain important.
- The live subscriptions resolved the correct tokens: RSYSTEMS 13414, RITES 3761, ELEVATE 766278.
- All three feeds became HEALTHY, and the supplied stream has no stale-feed transition or websocket failure.
- The existing gates prevented entries that did not satisfy the chosen volatility policy. A valid NO_TRADE result remains possible.
- The 14:30 new-entry cutoff and 15:00 shutdown ran normally.
- The daily budget retained zero attempts and zero losses. No open position needed closing.
- PAPER mode remained active. Nothing in this run established live profitability or credited real brokerage-account profits.

## 8. Concrete validation before judging profitability

First repair history initialization, first partial-minute handling, warmup coordination, and strict frame validation. Add regressions for midday startup, reconnect gaps, missing history, duplicate/future/invalid rows, session-boundary resets, and existing-position exits during recovery. Replay this logged interval with the current thresholds: it should still produce zero eligible entries, which is a useful regression against forcing trades.

Then compare the frozen baseline with separately labelled research variants for current-session selection, bounded reserves, and fee-aware execution gating. Evaluate multiple sessions, including declining and flat markets; measure net expectancy, drawdown, fill assumptions, gate counts, and costs. Reserve later sessions for evaluation after parameters are chosen. A change selected because it would have profited on this day is not independent evidence of an edge.

Capture observed quote/depth snapshots and causal decision timestamps for paper opportunities. Without those records, candle-only replay cannot establish real fill quality or exact stop/target ordering. Reconcile each paper result against the durable journal and distinguish gross movement from net realised P&L.

Unit-test success verifies software behavior. The earlier 338-test result and the later 29 focused checks do not prove positive expected trading returns. The unchanged signal brain SHA-256 remains `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`.

For the next full regular NSE paper session, complete startup before 09:15 and retain the current PAPER setting. Friday 2 October is an NSE holiday, making Monday 5 October the next regular session after the weekend under the published calendar. [NSE 2026 holiday circular](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf)

## Evidence files

- [Structured audit and offline results](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/trading_log_audit_2026-10-01.json>)
- [Index covering every supplied log line](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/trading_log_line_index_2026-10-01.csv>)
- [RSYSTEMS reconstructed candles](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/logged_candles_2026-10-01_RSYSTEMS.csv>)
- [RITES reconstructed candles](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/logged_candles_2026-10-01_RITES.csv>)
- [ELEVATE reconstructed candles](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/logged_candles_2026-10-01_ELEVATE.csv>)
- [Actual regular-bot discovery report](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/data/paper/discovery_2026-10-01.json>)
- [Actual paper session report](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/data/paper/trades.report.json>)

Provider context: [Angel One historical API and request limits](https://smartapi.angelone.in/docs). The requested next steps are engineering corrections and measured research; neither can guarantee daily returns.
