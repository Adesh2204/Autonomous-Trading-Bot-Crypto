# Fee-aware 1h trend-pullback: research results and the Phase 3 gate

*25 October 2026. Research only. Nothing here traded. The bot was flat (0 positions, 0 orders on `pas`, read from the exchange at 17:01 UTC) and stays flat.*

## Verdict: NO-GO

The strategy fails four of the five out-of-sample gates. It is also negative gross, before any fee. It loses even under an optimistic fill model with zero stop slippage. The bot stays flat.

## 1. Cost model (used in every number below)

| Item | Value | Source |
|---|---|---|
| Maker fee | 0.03% | spec |
| Taker fee | 0.09% | spec; our fills average 8.70 bps of notional because 31 of our 33 `pas` fills were taker |
| Stop slippage | **4.55 bps mean** (n = 4: 3.31, 6.09, 1.25, 7.55) | our stop fills vs their triggers, from `userFills` and `historicalOrders` |
| Win cost (maker in, maker TP) | 0.06% | |
| Loss cost (maker in, taker stop) | 0.12% + 0.0455% = **0.1655%** | |
| Cost filter, 3 × loss cost | **ATR(1h) ≥ 0.4965%** | The spec's "≈ 0.36%" leaves out slippage. 0.36% was run as a declared sensitivity. |

## 2. Data and method

- **Why mainnet data.** `pas` testnet has only about 170 one-hour bars per market (opened 16 to 19 Oct). After the 60-bar warm-up and a 70/30 split, it cannot produce 20 out-of-sample trades. `pas` prices track real underlyings through an oracle, so we used Hyperliquid **mainnet** 1h candles for the same underlyings: `BTC` and `xyz:EWY`. That is 5,000 bars each, from 31 Mar to 25 Oct 2026. Mainnet hourly funding was applied to every hour a position was held.
- **Universe.** The spec adds any other `pas` market with ATR ≥ 0.30% and spread ≤ 3 bps. No other market qualifies: measured `pas` spreads were 5.2 to 11.9 bps, and the only market at ≤ 3 bps, USDEUR at 2.7 bps, has an ATR of 0.02%. ETH and HYPE are reported separately for information only; they fail the spread rule.
- **Fills.** A resting limit fills only if price trades *through* it (low < bid, high > ask). A touch never fills. A post-only entry that would cross at placement is counted as an ALO rejection.
- **Bar order (conservative).** Inside a bar, the stop is checked before the target. On the fill bar only the stop is checked. A breakeven move takes effect from the next bar.
- **Split.** One common cut at 70% of the window (2026-08-24 04:18 UTC). Trades are assigned by fill time. **No parameter was tuned:** the spec was fixed before the data was read, so the in-sample period is for reference only.
- **Sizing for drawdown.** Phase 4 sizing: 0.3% equity risk per trade, at most $5,000 notional, at most 2 positions, $100k equity.
- **Code.** `research/fee_aware_backtest.js`, unit-checked by `research/test_fee_aware_backtest.js`. It runs in a browser page on the Mac, so candles never leave the machine.

## 3. Results: spec (BTC + EWY, ATR ≥ 0.4965%)

| | Trades | Win % | Avg net / trade | Avg gross / trade | Profit factor | Max DD (equity, sized) | Return (equity) | Maker fill rate |
|---|---|---|---|---|---|---|---|---|
| BTC in-sample | 130 | 26.9% | −0.190% | −0.084% | 0.58 | 1.32% | −1.23% | 19.3% |
| **BTC out-of-sample** | **52** | 28.8% | **−0.239%** | −0.134% | **0.48** | 0.62% | −0.62% | 19.7% |
| EWY in-sample | 196 | 33.7% | −0.149% | −0.048% | 0.77 | 1.62% | −1.46% | 21.3% |
| **EWY out-of-sample** | **65** | 26.2% | **−0.322%** | −0.219% | **0.43** | 1.09% | −1.05% | 20.4% |
| Combined in-sample | 326 | 31.0% | −0.165% | −0.062% | 0.71 | 2.81% | −2.69% | 20.4% |
| **Combined out-of-sample** | **117** | **27.4%** | **−0.285%** | **−0.181%** | **0.45** | **1.67%** | **−1.67%** | **20.1%** |

Out-of-sample exits: 55 stops, 15 stops on the fill bar, 14 breakeven stops, 30 take-profits, 3 time exits. ALO rejections: 319.

## 4. Phase 3 gate (out-of-sample, combined)

| Requirement | Result | Pass? |
|---|---|---|
| ≥ 20 trades | 117 | ✅ |
| Avg net per trade ≥ +0.05% | −0.285% | ❌ |
| Profit factor ≥ 1.2 | 0.45 | ❌ |
| Max drawdown ≤ 0.5% | 1.67% | ❌ |
| Positive on ≥ 2 markets | 0 (BTC −0.239%, EWY −0.322%) | ❌ |
| **GO** | | **NO-GO** |

## 5. Robustness: pre-declared, none of them selected

| Variant (out-of-sample, combined) | Trades | Avg net | PF | Max DD | Verdict |
|---|---|---|---|---|---|
| Spec without funding | 117 | −0.286% | 0.45 | 1.67% | NO-GO |
| Cost filter at the spec's 0.36% | 160 | −0.238% | 0.49 | 1.93% | NO-GO |
| All four (BTC, EWY, ETH, HYPE) | 310 | −0.186% | 0.65 | 2.67% | NO-GO; HYPE closest at −0.084% |
| **Optimistic bound:** touch fills, target before stop, target allowed on the fill bar | 122 | −0.116% | 0.74 | 0.79% | NO-GO |
| Optimistic bound **and** zero stop slippage | 165 | −0.034% | 0.91 | 0.54% | NO-GO |
| `pas` testnet's own 7 days (BTC, EWY) | 8 (EWY only; BTC never passes the ATR filter) | −0.58% | — | — | far too few trades |

The optimistic in-sample result was positive: +0.095% per trade, PF 1.21. Its out-of-sample result was negative. Without the 70/30 discipline we would have shipped it.

## 6. Why it fails (diagnosis, not a fix)

- **Adverse selection on maker entries.** A bid at EMA20 − 0.25 ATR is filled exactly when price is falling through the pullback level. Out of sample, 70 of 117 trades hit the full stop, 15 of them in the bar that filled the entry, against 30 take-profits. Gross edge is −0.18% per trade before any fee.
- **Cost is still large relative to the move.** BTC's median 1h ATR on mainnet is 0.52% (on `pas` over the last 72 h it was 0.32%, below the 0.4965% floor). The loss cost of 0.1655% is a third of an ATR.
- **`pas` microstructure is worse than the mainnet proxy.** 15 to 33% of `pas` 1h bars have zero volume, and the best level is about $37 to $500. A resting $5,000 entry would be 10 or more times the displayed best level. That is a book-impact and manipulation-monitoring risk, and fills on `pas` would come from MM quotes moving, not from real flow. Phase 4's book-impact question never arises because the gate fails, but it would have needed an answer.

## 7. What this means for the score

Under 0.8·Q + 0.2·jury, any negative return ranks below flat teams. Our current return is −0.00113% (published −0.00023%), essentially flat. With no strategy passing out of sample, the highest-expected-score action is to stay flat to 6 Nov and put the hours into the jury report.
