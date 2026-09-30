# ₹20,000 intraday bot: readiness and capital audit

Prepared 30 September 2026, IST. Tomorrow means Thursday, 1 October 2026.

**Decision: the current checkout does not justify unattended live trading tomorrow.** Run an observed paper session, preserve the signal baseline, repair execution and measurement, and establish positive expectancy after costs before risking capital. A daily evaluation routine is achievable; a profitable trade every day is not something this audit can establish or promise.

This is an analysis, not an implementation. Production Python files and LIVE_MODE were not changed. No broker login, live order, or market-data download was performed. Prices in diagnostic scenarios are examples, not stock recommendations. Current stock selection and tomorrow's market direction remain unknown.

## 1. What was inspected and what was verified

Reviewed the supplied pasted text and config.py, signal_brain.py, execution_engine.py, live_stream.py, symbol_state.py, candle_builder.py, premarket_screener.py, atr_firewall.py, market_schedule.py, backtest_engine.py, the trade CSV, selected logs, and existing accounting tests.

Isolated probes ran through the actual PaperTrader with temporary ledgers and no broker session. Seven existing fill-accounting test functions passed when invoked directly. The pytest command could not run because pytest is absent from this workspace's virtual environment; feed and ATR test modules could not be imported for the same reason. These checks verify limited accounting behavior, not strategy profitability or live readiness.

### Critical findings

| Finding | Evidence | Required correction |
|---|---|---|
| Configured ₹100 risk is not enforced in sizing | A ₹300 entry, ATR ₹5, 11 shares was accepted with projected stop loss including charges of ₹122.94. risk_per_trade is assigned and displayed but not used as an entry sizing constraint. | Find an integer quantity that fits both cash and net loss budgets; otherwise reject. Recheck after fills and additions. |
| Instrument identity is lost before execution | A JIOFIN-EQ paper position stored token 4907 although the configured JIOFIN token is 18143. Execution uses fallback tokens rather than the selected SymbolState identity. | Carry symbol, trading symbol, token, exchange, and product through entry, fill, protection, reconciliation, and exit. Validate the tuple against the current broker master. |
| Paper entries are optimistic | VWAP ₹300 and candle close ₹303 produced paper entry ₹300. Live entry is sent as a market order after the signal. | Use the next executable bid/ask or a conservative next-bar fill model. Do not assume a past VWAP is available. |
| Paper stop fills are optimistic | With stop ₹290 and triggering candle close ₹285, recorded paper exit was ₹290. The ₹55 gross adverse difference for 11 shares disappears from paper accounting. | Separate stop trigger from executable exit price; include adverse fills. |
| Stops depend on software and candle completion | check_exit excludes tick stop checks; notify_candle_close triggers stops. Entry sends stoploss=0, with no protective broker order in the inspected entry path. | Retain the strategy close-based stop only with separate broker-supported disaster protection and clear cancel/replace handling. Price gaps and unavailable liquidity can still exceed planned losses. |
| Daily loss brake is retrospective | Halt is set after a closed trade pushes daily P&L below the limit. | Budget each new trade against the remaining daily allowance, include costs and open exposure, and persist the daily state across restarts. |
| End-of-day timing is late | config.py and NSEMarketSchedule use 15:20; entry cutoff is 15:15. | Stop entries earlier and flatten before broker cash RMS. Use one schedule source for live, paper, and backtest. |
| Simple single-tranche change fails | PaperTrader(max_tranches=1) raises IndexError in startup logging. Allocation also redistributes the unused working budget to the final retained tranche. | Repair constructor/allocation and test explicitly; do not assume this flag safely disables scale-in. |
| Watchlist bypasses scale-in evaluation | Orchestrator returns immediately when a position exists. | Keep scale-in disabled initially, but explicitly identify this behavior rather than relying on advertised three-tranche architecture. |
| Multi-order fees can be understated | Closing P&L calls a one-entry/one-exit friction function on aggregate quantity/average entry. | Sum actual entry-order fees and actual exit-order fees. Minimum brokerage applies per executed order. |
| Performance ledger is not reliable evidence | 615 rows, 512 repeated timestamp/trade-id/symbol combinations, explicit Test Profit/Test Loss rows, and no mode or broker-order identifiers. | Preserve this file as an archive. Separate test, backtest, paper, and live ledgers with run IDs and fill IDs. Do not derive a live win rate from it. |
| Historical testing can silently use synthetic data | Failed history downloads eventually generate synthetic candles; replay consumes Buy_Signal while live also trades breakout and short signals. | Synthetic data is for software checks only. Make research data provenance mandatory and replay the same gates, sides, timing, and fills as live. |
| Logs expose authentication fields | A reviewed failed-login record contains request authentication fields. | Redact broker request logging, protect logs, and replace reusable credentials exposed in records. Do not copy raw logs into reports. |

Angel One's newer CAS guidance lists cash MIS square-off at **15:10**, while an older support page still says 15:15. Both are earlier than this bot's 15:20. A conservative bot flatten time of **15:00 IST**, with broker-flat verification, avoids relying on either later time. Confirm the account's applicable broker notice. [Angel One CAS guidance](https://www.angelone.in/knowledge-center/share-market/closing-auction-session-cas-meaning-timings-and-how-it-works), [older square-off support](https://www.angelone.in/support/your-orders/square-off).

The inspected order helpers send MARKET orders. Angel One's April 2026 framework notice says API orders require a registered static IP and prohibits market/IOC algo orders; SmartAPI documentation also describes market protection conversion. These statements require account-specific verification. Use a supported, price-protected order path with fill/partial-fill/cancel recovery rather than assuming current MARKET requests guarantee execution. [Framework notice](https://www.angelone.in/news/market-updates/what-s-changing-in-angel-one-s-smartapi-access-from-april-1-2026), [SmartAPI order documentation](https://smartapi.angelone.in/docs).

## 2. Corrections to the pasted proposal

**Brokerage:** The proposal's 0.03% rate is outdated for the published standard plan. Angel One currently publishes lower of ₹20 or 0.1%, with ₹5 minimum per executed order. This checkout already uses 0.001, ₹5 minimum, and ₹20 cap. At 0.1%, the ₹20 cap is reached at ₹20,000 per order, not roughly ₹66,000. Account promotions or alternative plans must be verified separately. [Brokerage support](https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges).

**ATR is not a daily movement ceiling:** ATR here is the average true range of the last 14 one-minute bars. A 0.40% ATR does not mean the stock can move only 0.40% during a trade or across a day. This engine targets roughly 4 ATR and initially stops at 2 ATR. Negative expectancy cannot be proven simply by comparing one ATR with round-trip charges; it depends on actual win/loss distributions and attainable fills.

**Five-minute candles are an experiment:** They may reduce some signal churn but also delay entry and change stop distances, indicator memory, warmup, cooldown, and time-based breakeven. Fifteen bars become 75 minutes; ten-bar cooldown becomes 50 minutes. Switching the entire pipeline while claiming unchanged strategy behavior is inaccurate.

**The existing long signal already requires a close above VWAP:** It also uses positive VWAP slope, EMA9 ≥ EMA21, and anti-spam logic. Its touch zone is wide (VWAP + 1.5 ATR), so a literal touch/reclaim at VWAP is not guaranteed. Narrowing that zone or moving the stop to a swing low changes the strategy and needs its own replay experiment.

**0.75% per five-minute ATR is not a universal tradeability rule.** At ₹300, this would mean ATR ₹2.25, initial stop ₹4.50, and target ₹9. At 33 shares, gross planned loss is ₹148.50 before fees, already above a ₹100 budget. Use timeframe-specific historical distributions and trade economics to choose gates.

**Previous-session volume above 1.5× average is historical activity, not today's RVOL.** For live participation, compare today's cumulative volume with average cumulative volume at the same clock time over prior valid sessions. Prior-session activity/news can help rank candidates but does not prove a profitable setup or institutional involvement.

**Several config values do not control their advertised behavior:** TRANCHE_1_CAPITAL is used for display but sizing follows working capital times tranche fractions; EMAs use literal spans 9 and 21; the initial target is twice the stop distance; the exchange schedule hardcodes exit times. Follow the actual call path before changing values.

## 3. Why the bot is often not trading

The 28 September 13:12 screener run rejected all 15 candidates: 12 returned usable metrics but failed ATR_BELOW_MIN, and three returned BROKER_DATA_ERROR. Reported one-minute ATR percentages included JIOFIN 0.07%, NTPC 0.08%, SWIGGY 0.16%, and MEESHO 0.26%, against the 0.40% requirement. After a screener bypass, ENGINERSIN entered STANDBY at 0.072% ATR.

These are historical diagnostics, not current quotes. They show that this session's inactivity had identifiable causes; a 0.75% floor would reject still more candidates on the same timeframe. However, lowering the gate cannot create profitable opportunity. First measure the entire rejection sequence: data availability → candidate qualification → core signal → executable price → costs → risk → broker acceptance.

The premarket ATR is the final ATR reading of the previous completed session, rather than a broad estimate of the next morning's opportunity. The screener also requires bullish EMA alignment despite live support for shorts. Evaluate direction-neutral liquidity selection and side-specific live trend gates in paper research.

## 4. Capital and friction calculations

Assumptions: ₹300 reference price, one buy and one sell, full published standard brokerage, NSE cash intraday statutory fees, nearly unchanged prices. Results use the current friction function. The added slippage column assumes an illustrative 0.05% adverse execution on each leg; it is not measured slippage. Spread/impact must be incorporated without counting the same execution disadvantage twice. Charges vary with fill prices and contract-note rounding.

| Shares | Position value | Round-trip charges | Break-even price move | Charges + illustrative two-leg slippage | Break-even with slippage |
|---:|---:|---:|---:|---:|---:|
| 11 | ₹3,300 | ₹12.97 | 0.393% | ₹16.27 | 0.493% |
| 16 | ₹4,800 | ₹13.50 | 0.281% | ₹18.30 | 0.381% |
| 26 | ₹7,800 | ₹21.18 | 0.272% | ₹28.98 | 0.372% |
| 33 | ₹9,900 | ₹26.88 | 0.272% | ₹36.78 | 0.372% |

The minimum-fee burden declines toward ₹5,000 per leg; above that and below the brokerage cap, fee percentage is broadly proportional to turnover. Bigger size increases rupee loss and costs even when percentage friction improves. [Published charges](https://www.angelone.in/exchange-transaction-charges).

For gross planned stop loss R, gross target profit 2R, and approximately equal round-trip cost C at win/loss:

`net reward/risk = (2R − C) / (R + C)`

To require net ratio k, `R ≥ C × (1+k)/(2−k)`. For k=1.2, gross risk must be at least 2.75C; for k=1.5, at least 5C.

With net loss limited to ₹100, k=1.5 therefore requires C ≤ ₹16.67. The ₹9,900 position has charges alone of about ₹26.88 and illustrative all-in friction of ₹36.78. It cannot meet ₹100 net risk and 1:1.5 net reward/risk with the unchanged gross 1:2 payoff. Approximate maximum net ratio at ₹100 total loss is `2 − 3C/100`: about 1.19 before slippage, or 0.90 with the illustrative slippage assumption. This is a feasibility calculation, not a strategy performance forecast.

Use integer sizing that jointly satisfies:

1. Entry notional plus charges and cash buffer ≤ permitted working funds.
2. Quantity × stop distance + correctly sided entry/stop-exit charges + adverse fill allowance ≤ per-setup risk and remaining daily allowance.
3. Projected executable target gain after costs / projected stop loss after costs ≥ the validated minimum ratio.
4. If no quantity satisfies all conditions, decline the trade.

For the present 2 ATR stop, solve with `stop distance = 2 × ATR`. Increasing capital is not a substitute for this calculation. A larger price-to-VWAP gap after a confirmed close also consumes the apparent target advantage.

## 5. What can change while preserving the signal baseline

Keep signal_brain.py and its one-minute entry rules unchanged initially. Repair instrument routing, actual-fill handling, order-level fees, quantity sizing, daily risk accounting, protected exits, lifecycle times, restart reconciliation, and ledger separation around it. These fixes preserve indicator/entry formulas but can change execution and measured outcomes; rerun validation.

Then use a paper-only comparison to test a wider broker-eligible, liquid universe, direction-aware selection, live spread/depth, same-time RVOL, and improved opportunity ranking. A broader universe increases the chance of finding a setup; it does not guarantee one or guarantee profit. Use the current broker instrument master and surveillance/intraday eligibility rather than expanding hardcoded tokens.

Maintain the existing one-position limit. Skip scale-in for the pilot through a tested execution gate; the single-tranche constructor bug means a one-line config change is insufficient. Do not lower R:R or override NO_TRADE to meet a daily trade quota.

Only after a reliable baseline, compare one-minute, three-minute, and five-minute versions on held-out real data. A higher-timeframe trend veto, literal VWAP reclaim, or structural stop is a changed selection/management policy even if implemented outside signal_brain.py. Evaluate separately rather than changing all parameters together.

## 6. Tomorrow and the later live pilot

**1 October: observed paper evaluation.** Start early enough for authentication/read-only feed checks and screening. Validate instrument identity, feed, actual bid/ask, volume differences, candle timestamps, and broker eligibility. Capture every rejection and every hypothetical fill. Allow the bot to finish with zero trades. The present audit has not established that live execution is safe or profitable.

Once blockers are repaired and a validated pilot is justified, use the following conservative starting limits as proposals:

| Control | Pilot proposal |
|---|---|
| Capital | ₹20,000 total; ₹10,000 reserve; ₹10,000 working ceiling, not compulsory deployment |
| Setup risk | Maximum ₹100 planned total loss including costs and fill allowance |
| Daily risk | ₹200 planned loss ceiling, with remaining-budget checks and open-exposure monitoring |
| Position count | One |
| Attempts | At most two new setups; stop after two full losses or a safety/accounting failure |
| Scaling/leverage | No scale-in and no leverage expansion during pilot |
| Entries | After complete warmup; proposed final entry cutoff 14:30 IST |
| Closing | Flatten by 15:00 IST; cancel obsolete protection and confirm broker flat |
| Trade requirement | None; a no-trade session is valid |
| Profit requirement | None; assess expectancy over a sample |

These are risk policies, not a tested optimal configuration. Planned loss ceilings are not guaranteed loss caps in a gap, circuit lock, outage, or poor liquidity. Broker protection and operator recovery remain necessary. Do not increase risk solely to make a cost gate pass.

NSE's published 2026 cash calendar lists **2 October as a holiday**; 1 October is a scheduled normal session absent a later exchange notice. [NSE calendar circular](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf).

## 7. What would support confidence

Use real, identified history and an identical replay of live selection, long/short/breakout rules, cooldown, realistic fills, costs, risk, and time gates. Avoid lookahead in watchlist selection. Preserve train/test boundaries and inspect trending, ranging, and volatile sessions. Stress costs using measured high-percentile spread/slippage, not a convenient constant.

As a first research milestone, collect at least 100 realistic completed trades over at least 20 sessions; extend the sample when trades are correlated or the uncertainty is wide. This is a screening milestone, not proof. Measure net expectancy, profit factor, maximum drawdown, cost/gross-profit ratio, adverse excursions, consecutive losses, win/loss sizes by setup and side, and paper-to-live slippage. Use day-level or block resampling to quantify uncertainty rather than treating correlated trades as independent. Prefer positive held-out expectancy with an uncertainty bound above zero and a drawdown within the chosen budget.

Statistical confidence and daily profit are different. An illustrative model with 45% wins, ₹150 average net winner, and ₹100 average net loser has expectancy `0.45×150 − 0.55×100 = ₹12.50/trade`. Two trades would imply ₹25 average for that model, not ₹25 every day, and fixed operating costs can absorb much of it. No such win rate or expectancy has been established for this checkout. ₹200/day is 1% of total capital each session; ₹500/day is 2.5%. Neither should become a compulsory target.

**Recommended sequence:** correct execution and accounting → preserve and measure the current strategy → improve opportunity selection in paper comparison → validate any timeframe changes separately → consider a small observed live pilot only when evidence supports it.
