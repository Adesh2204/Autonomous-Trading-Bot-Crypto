# Compounder research: results after fees, slippage, funding and Indian tax

*25 November 2026. Research and paper trading only. No real order was placed.*

## Verdict: NO-GO for real money under the conservative tax rule

The pre-registered strategy passed four of six gates. It failed two. Its worst after-tax drawdown was 32.3%, above the 30% limit. On Hyperliquid's own candles and funding, it lost 0.6% after tax over 2024 to 2026.

The trend edge is real before tax: profit factor 1.4 to 1.9 on daily bars. India's per-trade VDA tax takes most of it, because 31.2% of every winning trade is due and losing trades cannot offset it. Hyperliquid's funding for longs takes the rest. Under the business-income reading of crypto futures, the same rules made money; the strongest case is CoinDCX-like costs. That reading is your CA's call, not ours.

## 1. Protocol (fixed before any result was read)

| Item | Value |
|---|---|
| Candidates | Classic Turtle rules, nothing tuned: Donchian 20/10 and 55/20 on daily bars, 20/10 on 4h bars; each long/short and long-only (6 candidates) |
| Entry / exit | Close above the prior N-bar high (long) or below the prior N-bar low (short); exit on the opposite M-bar channel; hard stop 2 × ATR(20) from the fill, resting on the exchange |
| Sizing | 1% of **after-tax** equity at risk per trade; ≤ 1× equity per position, ≤ 3× gross. Every realized after-tax profit enlarges the next position. That is the compounding rule. |
| In-sample (selection only) | 2020-01-01 to 2023-12-31, the Jan-2020 top-10 coins with Binance perps: BTC ETH XRP BCH LTC BNB EOS XTZ XLM ADA |
| Selection rule | Best in-sample after-tax Sharpe: **D55_20_L** (daily 55/20, long-only) |
| Out-of-sample (the test) | 2024-01-01 to 2026-11-25, the Jan-2024 top-10 coins: BTC ETH BNB SOL XRP ADA AVAX DOGE TRX LINK |
| Costs | Hyperliquid taker 0.045% per fill; slippage 2 bps (BTC/ETH), 4 bps (SOL/XRP/BNB/DOGE), 8 bps others per side; +5 bps on stop fills; actual funding history |
| Tax (default) | Indian VDA rule (Section 115BBH): 30% + 4% cess = 31.2% of every profitable closed trade; a loss offsets nothing |
| Gate | After-tax return > 0; after-tax profit factor > 1.10; ≥ 30 trades; max after-tax drawdown ≤ 30%; still positive with every cost doubled; positive on Hyperliquid's own data |

Code: `algo-trading-bot/compounder/` (the same functions run the backtest, the paper bot and the live bot), `research/compounder_2026-11-25/run_research.py`, `risk_scan.py`. Raw results: `research/compounder_2026-11-25/results.json`.

## 2. Gate result for the selected strategy (D55_20_L, 1% risk)

| Requirement | Result | Pass? |
|---|---|---|
| After-tax return > 0 (Binance data) | +20.1% | ✅ |
| After-tax profit factor > 1.10 | 1.32 | ✅ |
| ≥ 30 trades | 86 | ✅ |
| Max after-tax drawdown ≤ 30% | 32.3% | ❌ |
| Positive with all costs × 2 | +16.0% | ✅ |
| Positive on Hyperliquid's own candles and funding | **−0.6%** | ❌ |
| **Verdict** | | **NO-GO** |

## 3. Out-of-sample results, 2024-01-01 to 2026-11-25 ($1,000 start, 1% risk)

Returns are for the whole ~2.9-year window, not per year.

| Strategy | Hyperliquid, no tax | Hyperliquid, VDA tax | Hyperliquid, business-income tax | CoinDCX costs*, VDA tax | CoinDCX costs*, business tax | Worst drawdown (HL, VDA) |
|---|---|---|---|---|---|---|
| **D55_20_L** (selected) | +27.6% | **−0.6%** | +19.5% | +17.5% | +39.9% | 39.5% |
| D55_20_LS | +47.5% | +1.1% | +32.2% | +14.9% | +50.0% | 39.8% |
| D20_10_L | +45.5% | −2.0% | +29.2% | +15.0% | +52.4% | 41.6% |
| D20_10_LS | +42.8% | −22.8% | +30.7% | n/a | n/a | 51.6% |
| H4_20_10_L (4-hour) | −6.1% | −76.9% | −15.0% | n/a | n/a | 90.2% |
| H4_20_10_LS (4-hour) | −47.0% | −95.1% | −53.9% | n/a | n/a | 97.8% |

\* CoinDCX USDT-M futures fees (0.02% / 0.05% + 18% GST) on Binance prices and funding; CoinDCX's own funding history was not available.

Benchmarks over the same window: holding BTC +41% (before the 31.2% tax at sale), and an equal-weight hold of the ten coins +5.8%.

Year by year for D55_20_L on Hyperliquid after VDA tax: 2024 +23.4%, 2025 −13.0%, 2026 to date −7.4%.

## 4. What leverage does (D55_20_L on Hyperliquid, risk per trade is the leverage knob)

| Risk per trade | VDA tax: return | VDA: worst drawdown | Business tax: return | Business: worst drawdown |
|---|---|---|---|---|
| 0.25% | +0.7% | 14% | +5.4% | 13% |
| 0.5% | +0.8% | 25% | +10.5% | 22% |
| 1% | −0.6% | 40% | +19.5% | 35% |
| 2% | −8.6% | 57% | +32.3% | 50% |
| 3% | −21.7% | 69% | +37.2% | 59% |
| 4% | −46.3% | 80% | +11.0% | 69% |
| 5% | −65.2% | 86% | +3.0% | 74% |

Up to about 3% risk, more leverage raises the return under the business reading. Beyond that it lowers it in every tax mode, because a bigger drawdown takes more to recover than the extra gains add.

## 5. What a short horizon looks like (block bootstrap of the daily after-tax returns, 1% risk, HL)

| Horizon | Chance of being up (VDA) | Median | 5th to 95th percentile | Chance of being up (business) |
|---|---|---|---|---|
| 2 weeks | 42% | −0.2% | −7.4% to +9.7% | 44% |
| 1 month | 44% | −0.6% | −10.5% to +17.3% | 47% |
| 3 months | 46% | −1.2% | −18.4% to +27.2% | 51% |
| 1 year | 48% | −1.2% | −34.2% to +58.4% | 58% |

## 6. Why

- **The tax rule decides it.** Under 115BBH a winning trade pays 31.2% and a losing trade gives back nothing. An after-tax profit factor above 1 therefore needs a pre-tax profit factor above about 1.45. The daily trend rules reach 1.4 to 1.9. The 4-hour long-only rule (pre-tax profit factor 1.21, 985 trades) made +39% before tax on Binance data and −78% after tax. **More trading means more tax**, which is why the bot trades only on daily closes.
- **Funding.** Holding longs on Hyperliquid cost about $262 per $1,000 started over the window. Hyperliquid funding carries an interest component that longs pay. Binance funding over the same window was less than half of that.
- **The market now.** On 25 Nov 2026 every coin in the universe is 30 to 50% below its 55-day high. The long-only rule is flat and stays flat until a coin breaks out; the long/short shadow would short a breakdown.

## 7. What was not tested and why

- Delta-neutral funding carry (spot long + perp short): under the VDA rule the winning leg is taxed and the losing leg is not deductible. Any price move therefore creates a tax bill of 31.2% × the move, larger than a year's funding. Not pursued.
- Scalping and market making: already tested on 25 Oct (`docs/fee_bleed_2026-10-25/research_results.md`), negative before tax.
- Tuning the rules on these results: not done. Choosing parameters after seeing the out-of-sample numbers would make the next test meaningless.

## 8. Your Rs 1,000 with leverage (added 25 Nov 2026, same window 2024-01-01 to 2026-11-25)

The Rs 1,000 practice profile: long+short 55/20 rules; 2% risk, or the venue minimum if its stop risk is ≤ 20%; open risk ≤ 40%; 10x setting. Script: `research/compounder_2026-11-25/small_account.py`. Raw: `small_account_results.json`. CoinDCX and Delta India use Binance prices and funding as the proxy; CoinDCX's published funding rate equals Binance's.

| Venue | Rs 1,000 became (VDA tax) | Lowest point | Highest point | Trades | Rs 1,000 became (business-income tax) |
|---|---|---|---|---|---|
| Hyperliquid | **Rs 340** | Rs 340 | Rs 1,000 | 9 | Rs 304 |
| CoinDCX | **Rs 1,010** | Rs 498 | Rs 2,179 | 57 | Rs 1,561 |
| Delta India | **Rs 957** | Rs 650 | Rs 1,838 | 52 | Rs 1,100 |

- **Hyperliquid's $10 minimum is more than the whole account.** Most entries would have risked over 20% and were refused. The few it took mostly lost.
- **CoinDCX's $6 minimum on seven coins lets the bot trade.** The account more than doubled at one point and halved at another. Under the conservative tax rule it ended where it started.

## 9. "Cheaper" coins and coins "performing well" (scan of the 40 most-traded Hyperliquid coins, 25 Nov 2026)

- Not one of them is up over the last 30 days. The best is VVV at −2%; BTC is −25%, ETH −28%, SOL −31%. The low-priced coins fell the most: FARTCOIN −36%, PUMP −42%, MON −56%, ACE −57%.
- Every one is 16 to 74% below its 55-day high. The only rule signals today are SHORT signals (ZRO, MON), outside the bots' ten coins.
- A coin's price per unit does not make it cheaper to trade. Every venue sells fractions or small contracts, and profit is the percentage move times the money in the position. What a small account needs is a small **minimum order value**. That is why CoinDCX ($6 on seven coins) and Delta India (one contract) can trade Rs 1,000 and Hyperliquid ($10) mostly cannot.

## 10. Intraday (day trading), as requested (pre-registered, 25 Nov 2026)

Rules: `algo-trading-bot/compounder/intraday.py`. Script: `research/compounder_2026-11-25/run_intraday.py`. Raw: `intraday_results.json`.
- Hourly bars on the ten coins, CoinDCX costs (0.05% + GST per fill, slippage), actual funding, 31.2% tax on each winning trade.
- Flat every day by 00:00 UTC (05:30 IST), at most one entry per coin per day.
- In-sample 2022–2023 (selection), out-of-sample 2024 to 25 Nov 2026 (the test).

| Rule | Out-of-sample trades | Pre-tax profit factor | Return before tax | Return after tax | Rs 1,000 became (Rs 1,000 profile, after tax) |
|---|---|---|---|---|---|
| Opening-range breakout, with the day's direction | 2,155 | 0.73 | −99.4% | −99.4% | Rs 209 |
| Hourly breakout, with the day's direction | 2,161 | 0.86 | −98.8% | −99.4% | Rs 186 |
| Hourly breakout, both directions (the in-sample selection) | 2,020 | 0.74 | −99.4% | −99.4% | Rs 201 |

**Verdict: NO-GO.** All three lose money **before** tax: profit factor below 1, so each Rs 1 won costs more than Rs 1 lost. Over 2,000 trades, compounding small losses empties the account. The cause is cost against move size: a round trip costs about 0.2–0.35% (fees + GST + slippage), close to the whole typical hourly move. The daily rules (section 8) trade about 30 times less often, so costs and tax take a much smaller share.

## 11. "Exit at the peak" and "pick the right coins" (pre-registered, 25 Nov 2026)

Script: `research/compounder_2026-11-25/run_exits_rotation.py`. Raw: `exits_rotation_results.json`. Code: `trail_stop`, `momentum_score`, `rotation_sides`, `top_by_volume` in `compounder/strategy.py`; `guard_dd` in `compounder/backtest.py`.
- **Variants:** trailing stops at 3 or 2 ATR from the best price since entry; an account guard (20% below the peak → close everything, pause 30 days); coin rotation over a 61-coin pool (including delisted coins). The rotation keeps the 20 most-traded coins each month, takes longs only in the 5 strongest and shorts only in the 5 weakest by 90-day risk-adjusted momentum, and is tested alone and with each trailing stop.
- **Costs and tax:** CoinDCX costs, 31.2% tax per winning trade.
- **Selection:** in-sample (2020–2023) after-tax Sharpe. The in-sample comparison of rotation against the fixed ten coins is tilted toward the fixed list, which was chosen in 2024. Out of sample (below) is fair.

| Variant (2024-01-01 to 2026-11-25) | $1,000 at 1% risk: return after tax | Worst drawdown | Share of each winner's best open profit kept | **Your Rs 1,000:** highest | **Rs 1,000 today** |
|---|---|---|---|---|---|
| **BASE (current plan)** | **+14.9%** | 33% | 40% | Rs 2,190 (4 Dec 2024) | **Rs 1,011** |
| Trailing stop 3 ATR | −18.4% | 33% | 47% | Rs 1,804 (5 Mar 2024) | Rs 206 |
| Trailing stop 2 ATR | −6.4% | 22% | 58% | Rs 1,679 (5 Mar 2024) | Rs 366 |
| Account guard 20% | +35.4% | 29% | 44% | Rs 2,145 (14 Mar 2024) | Rs 291 |
| Coin rotation | −35.1% | 37% | 33% | Rs 1,009 | Rs 211 |
| Rotation + trail 3 ATR | −33.2% | 35% | 44% | Rs 1,029 | Rs 241 |
| Rotation + trail 2 ATR | −15.9% | 22% | 54% | Rs 1,369 | Rs 731 |

**Decision for the Rs 1,000 live plan: keep BASE.** Every add-on ended lower for Rs 1,000.
- **Trailing stops keep more of each winner's peak** (47–58% vs 40%). But they sell during the normal dips of a big rally: in March 2024 they sold before the account reached Rs 2,000, and the rally went on without them. They also trade more, which brings more fees and more tax.
- **Momentum rotation picked coins that then fell.**
- **The account guard** passed its pre-registered rule for the 1%-risk version (+35%). For Rs 1,000 each trade risks 8–20% of the account, so the 20% guard fired after one or two losses, closed positions at lows and paused through the recoveries. It is recorded as adopted for 1%-risk accounts only, and no live plan uses it yet.
