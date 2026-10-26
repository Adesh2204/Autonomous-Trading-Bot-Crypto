# Team Anchorium — final report for the Perpetual Alpha jury

*Hyperliquid testnet, `pas` dex, account `0x94EA…B12C`. Final version written 26 October 2026. Every number comes from the exchange (fills, orders, positions) or from our own journal. Where we could not measure something, we say so.*

## 0. Summary

We built a fail-closed execution stack and a research process that does not let us trade an idea until it survives out-of-sample testing after real costs.

That process told us something uncomfortable: **none of our strategies has an edge after Hyperliquid's fees.** Our live record shows why. Across 16 `pas` round trips, gross P&L was **+$0.05** and fees were **$1.71**. We were trading for the venue.

So we stopped trading price patterns. The bot went flat on 25 Oct 11:19 UTC (0 positions, 0 orders, read from the exchange). Our last price strategy, a fee-aware maker-only trend-pullback, failed its pre-registered out-of-sample gate: 117 trades, −0.285% per trade net (§6).

What remained was one structural effect: funding. On 25 Oct we chose, as a team and with the odds written down, to hold a **funding-carry basket** until the end of the competition (§6.1); on 26 Oct we raised it from half to full size. It is a sized risk bet, not a discovered edge. Our model gives it a median of +0.91% and a 42.7% chance of finishing below zero, which under this score ranks below every flat team. We took that bet knowingly. We did not add a basket stop, because the model shows it would *raise* the chance of a negative finish (to 48% at half size and 67% at full size).

We also found and fixed two live bugs. One corrupted our trade records; the other forced an exit from a protected position.

## 1. What we built

We moved an intraday agent from Indian equities onto HIP-3 perpetuals without silently changing its strategy. The project has two parts:

- an execution stack where every order fails closed;
- a research process that refuses to trade anything that does not survive out-of-sample testing after costs.

We trade at 1x cross. Every entry has a resting reduce-only stop on the exchange. Its size is bounded by a share of the displayed best level.

## 2. Architecture

```
public REST/WS ─▶ market data + metadata (runtime size/tick/leverage, dex=pas enforced)
                         │
strategy (frozen, hash-verified) ─▶ signal + provenance (setup, signal time, reason)
                         │
risk sizing ─▶ RiskPermission (exact symbol/side/qty/limit, 5 s lifetime)
                         │
FreshReadGate ─▶ guarded context load (book, mark/oracle, account, readiness, fills)
                         │
compliance guard ─▶ order validator ─▶ durable journal (cloid before signing)
                         │
official SDK 0.24.0 transport (exact-action permit, persistent nonces, rate reserve)
                         │
post-action reconciliation ─▶ exchange-side reduce-only stop + resting TP ─▶ per-entry verification
                         │
fill ledger (exchange fills = truth) ─▶ 30 s journal reconcile ─▶ streak / period log
```

- **Separation of truths.** Exchange account truth (fills, fees, funding) is kept apart from any paper or estimated ledger. Reported P&L comes from exchange fills, never from our own estimate.
- **Exchange fills decide what happened** (added 25 Oct, §4.3). A trade exists because the exchange reports its fills. It does not exist because a placement response or one position snapshot says so.
- **One owner, one journal.** A SQLite journal records each intent's client order ID before signing. A timeout leaves the intent UNKNOWN, and it is never blindly re-sent. On restart the bot starts UNKNOWN and only enters after it has reconciled with the exchange.
- **Strategy freeze.** The original strategy methods are hashed (`docs/strategy_freeze.json`) and checked before every release.
- **Releases are bound to evidence.** A live session starts only from a mandate whose source hash matches a full offline regression receipt (about 3,400 tests, no network, ephemeral signing keys). If any file changes, the authority is revoked.

## 3. The safety system

**Before any order is signed:**

- the book, account and readiness snapshots must be under 5 s old, and so must the permission;
- the mark–oracle divergence and the distance from the reference price are bounded;
- no self-cross and no duplicate intent;
- the size is bounded by a share of the best level;
- the position count is bounded per market and globally;
- a shared-account barrier confirms there is no foreign exposure or unresolved intent;
- the nonce, clock and rate reserves are healthy.

Anything missing, stale or ambiguous blocks the order.

**Verified halts.** After every entry the bot reads the exchange back and checks the position side and size, exactly one stop and exactly one take-profit. Any mismatch makes it flatten, cancel and halt, with no retry. Other halts:

- three consecutive order errors;
- an account-stream disconnect longer than 3 minutes;
- a −0.30% period loss cap;
- the rank-protection LOCK.

Each run ends with two exchange readings that confirm the account is flat.

**The carry basket adds its own rules** (§6.1), in a profile that only the carry runtime can load. The scalper keeps its committed limits.

- Each leg is checked on the exchange as soon as it is complete: position side and size, the fill ledger and exactly one 8% stop sized to the filled quantity. Any mismatch flattens that leg and halts entries.
- Three consecutive order errors halt **and** flatten. The flatten uses the same small slices; it never sweeps the book.
- Every leg's stop is checked every 60 s and re-placed if missing.
- A −5% account loss halts and flattens everything. This is a catastrophe guard: at half size it sits beyond the per-leg stops.

## 4. Bugs found live, and how we fixed them

Each fix ships with a regression test built from the actual exchange rows.

### 4.1 Stale context made a stop impossible (24 Oct)

The first live short filled, but its exchange stop was refused with `STALE_PRICE_CONTEXT`. A ~25 s wait for read budget happened *after* the order book had been read, inside the 5 s window.

The bot behaved as designed: it verified the entry, found no stop, flattened and halted. The exit filled at 80,541, better than the failed stop's trigger, so the bug cost nothing.

**Fix:** a `FreshReadGate` does every wait (budget, clock, barrier, reconcile) before the permission exists. No rule was loosened.

### 4.2 Smaller runtime fixes (24–25 Oct)

- The account receiver now keeps reconnecting instead of dying after five failures.
- A stale (>60 s) rate-budget snapshot no longer keeps entries paused after every trade.
- An entry refused before signing counts as a skip, not an order error.

### 4.3 Bug #11: a filled trade logged as "filled 0" (25 Oct 10:35 UTC)

A HYPE short filled at 75.38. The exchange stop closed it 55 s later at 75.53, all before the runtime's first position read. The log said `ENTRY_RESULT FILLED, filled 0`, and the trade never reached the journal.

- **Cost:** no money. The exchange-side stop did its job, and the −0.30% loss cap reads exchange equity, so it did count the loss. But the −$0.47 trade was missing from the trade log and the losing streak.
- **Fix:**
  - `exchange/fill_ledger.py` groups exchange fills into round trips by `startPosition`.
  - The entry result is now taken from the order's own fills.
  - A trade filled and closed before the first read is booked from its fills at once.
  - A position the first read missed is adopted, with its entry time taken from the fill, so it gets a stop and a take-profit.
  - Every 30 s, and on every boot, the exchange's round trips since session start are compared with the journal. Any missing round trip is inserted and counted in the streak. Partly recorded trips are flagged as conflicts and never silently merged.
- **Backfill:** the HYPE trade was backfilled into the run's journal (`scripts/backfill_missing_fills.py`, offline, from saved exchange evidence).

### 4.4 Bug #12: "duplicate order" forced an exit from a protected position (25 Oct 00:51 UTC)

After a BTC long filled, the runtime re-planned its stop at the actual fill price. The compliance guard saw our own resting reduce-only take-profit (same side, same size) and rejected the stop modification as `DUPLICATE_ORDER`. It did so four times. The protection state went to ERROR, and the runtime answered ERROR with a flatten (`EXCHANGE_STOP_NOT_ACTIVE`).

All the while, a valid stop for the full size was resting on the exchange. The exit (80,727) was above that stop (80,657), so it added no loss versus a stop-out. It did deny a protected trade its chance at the take-profit.

**Fix:**

1. **The guard.** A trigger stop next to our resting non-trigger take-profit is no longer called a duplicate. A second stop is still blocked.
2. **Keep a valid existing stop.** On any stop-update error, the protection manager re-reads the position and the open orders. If exactly one owned stop already protects the full size, the position is kept and a warning is logged.
3. **Flatten only as a last resort.** The runtime flattens only if no valid stop exists after two fresh-read retries.

We kept Hyperliquid's native modify-order. Cancel-then-replace would open an unprotected gap.

### 4.5 Measured, not fixed: stop slippage

Our four stop fills landed **1.25 to 7.55 bps** past their triggers (mean **4.55 bps**). Every trade record now stores the expected trigger and the actual stop-fill price, and every cost estimate uses the measured mean.

## 5. Fee analysis: why we stopped trading

All 16 `pas` round trips since 17 Oct (`docs/fee_bleed_2026-10-25/exchange_fills_since_2026-10-15.json`):

| | Value |
|---|---|
| Round trips | 16 (3 net winners, 13 net losers) |
| Gross P&L (exchange `closedPnl`) | **+$0.046** |
| Fees | **$1.712** (8.70 bps of $1,968 notional) |
| Net | **−$1.666** |
| Fills that paid taker | 31 of 33 |
| Trades that were gross winners / net winners | 6 / 3 |

Fees were 37 times the gross edge. The momentum scalper took liquidity on entry and exit (0.09% each side) to capture moves of about one 5-minute ATR (0.05–0.08%). Its breakeven win rate under that geometry is 82–88%.

A maker-only design changes the arithmetic: a win costs 0.06% and a loss costs 0.1655%. So we tested one (§6).

## 6. Research discipline

**The rule.** The specification is fixed before the data is read. We develop on the older 70% of the data and judge on the newest 30%, once. A strategy goes live only if it passes a pre-registered gate out of sample:

- at least 20 trades;
- average net ≥ +0.05% per trade;
- profit factor ≥ 1.2;
- drawdown ≤ 0.5%;
- positive on at least 2 markets.

**Six earlier candidates** (z-score reversion, Donchian breakout, EMA+ADX, funding tilt, VWAP fade, oracle-basis reversion; 5m, 15m and 1h; both directions) all failed out of sample after taker costs.

**The fee-aware 1h trend-pullback** (25 Oct; details in `docs/fee_bleed_2026-10-25/research_results.md`):

- **Design:** maker-only entries at EMA20 ∓ 0.25 ATR; a 1 ATR taker stop and a 1.5 ATR maker target; a breakeven move after +1 ATR; a 12 h maximum hold; trade only when ATR ≥ 3× the loss cost (0.4965%).
- **Fill model:** a limit fills only if price trades *through* it.
- **Data:** 5,000 mainnet 1h bars for BTC and EWY (`pas` has only about 170 bars per market), with hourly funding.
- **Result, out of sample:** 117 trades, win rate 27%, **−0.285% per trade net (−0.181% gross)**, profit factor 0.45, sized drawdown 1.67%, negative on both markets. **NO-GO.**
- **Even an optimistic bound fails.** With touch fills, target before stop and zero stop slippage, out of sample it still loses (−0.034% per trade, PF 0.91). The same optimistic model was *positive* in sample (+0.095% per trade, PF 1.21). That pair of numbers is exactly why we hold the 30% back.
- **Diagnosis:** adverse selection. A resting bid at a pullback level fills exactly when price is breaking through it. Out of sample, 70 of 117 trades hit the full stop.

**Funding carry** is the one structural effect we found. Funding of 0.12–0.23%/day is real. It is not a price edge, so it cannot pass the gate above. We treated it as a separate, explicit risk decision (§6.1).

### 6.1 The carry decision (25 Oct)

**The basket.** Long BTC, ETH, HYPE and SP500, short USDJPY: on each leg, the side that receives funding. We started at $9,500 per leg ("half size") on 25 Oct and moved to $19,000 per leg ("full size", $95k at 1x, 95% of equity) on 26 Oct. The basket is held until 6 Nov; nobody trades around it.

**The odds we accepted** (`docs/fee_bleed_2026-10-25/carry_decision.md`; 20,000 paths, 24 h block bootstrap of joint hourly returns with each asset's drift removed, measured `pas` funding, taker costs plus measured slippage):

| Variant | Median | P(finish below zero) | 5th percentile |
|---|---|---|---|
| Half size, 8% leg stops only | +0.46% | 42.7% | −2.10% |
| Half size with a −1.5% basket stop | +0.12% | 48.4% | −1.74% |
| **Full size, 8% leg stops only (chosen 26 Oct)** | **+0.91%** | **42.7%** | **−4.19%** |

- **Size does not change the odds.** Size scales every outcome but leaves P(loss) at 42.7%. We started at half size and moved to full size once the execution path was proven, accepting a doubled tail.
- **A basket stop makes things worse.** It turns ordinary drawdowns into realised losses before funding can recover them.
- **Our tail may be too thin.** An earlier estimate had a full-size 5th percentile of −7.7%. We plan with the worse number.

**How the basket is built** (organizer rule: do not move a thin book). The best level on `pas` is often about $500, and median traded volume is only $1.4k–6.4k per hour per market. So no leg is entered with one order:

- **One child order per leg at a time.** For the first 2 hours each child is post-only at the touch, re-priced after 10 minutes if unfilled.
- **Then small IOC children.** Each is limited to the touch price and to at most 25% of the touch quantity, at least 30 s apart on each leg.
- **Sized stops.** Every leg keeps an exchange-side, reduce-only 8% stop, re-sized to the filled quantity after each fill.
- **The unwind uses the same slices.** At full size that is about 760 slices at roughly one per minute (each guarded order reserves most of a minute's read budget), so it starts on 5 Nov at 20:00 UTC and the account is flat before the final 12:00 UTC sample.

**What it costs.** Entry fees and spread make the first days look red. The basket is judged on 6 Nov.

**Two more live bugs, found on the first night and fixed before any exposure was at risk** (26 Oct):

- The basket polled the account stream once per cycle instead of on the receiver thread the scalper uses, so the first entry was refused before signing (`DATA_NOT_READY`). Fixed by reusing the scalper's receiver.
- We had widened the order validator's market scope for the carry, but the final pre-HTTP check in the SDK transport still allowed only BTC/EWY/HYPE. An SP500 child was refused *before sending* and the journal correctly recorded it as UNKNOWN, which froze every order and cancel. A human confirmed non-transmission (exchange `unknownOid`, no fills, no dispatch record) with a checked script; the transport now uses the same scope as the validator.

**Status at writing (27 Oct, 03:50 IST):** fully built and holding. At 01:35 IST on 27 Oct the team moved more weight onto HYPE within 1x (a 2x setting needs a flat account, so it was not used): HYPE $50k (priority leg), SP500 $15k, BTC $13k, ETH $12k, USDJPY $5k; $95k at 1x. Over-target legs were trimmed first with reduce-only IOC children. Every leg was verified on the exchange when complete (side, size equal to the fill ledger, exactly one 8% stop sized to the position). IOC children were capped at 25% of the depth within 5 bps of the touch. Building and rebalancing cost $108 in fees over 228 fills.

**An accounting bug we caught in our own reporting (27 Oct):** the basket computed equity as the USDP balance plus unrealized P&L. On a unified account the USDP balance already includes unrealized P&L, so the loss was counted twice in one direction and reported equity looked better than the truth (verified: 99,456.74 total = 99,945.47 cash − 488.73 uPnL). It affected only the status and the −5% catastrophe-halt arithmetic, not orders or stops. The basket now uses the balance directly. True result at 03:50 IST against a $99,998 start: −$841 (−0.84%) = price −$778, fees −$108, funding +$45. Entry costs land on day one; funding accrues hourly, so the carry is judged on 6 Nov, not overnight.

**Machine learning** was built but not promoted. An explainable candidate-quality filter (L2 logistic regression plus a shallow tree, purged chronological splits) was never deployed: the genuine labelled sample is too small to fit honestly, and we will not show results from synthetic data.

## 7. Facts we measured about the venue

- **Prices.** `pas` prices follow an oracle that tracks real prices to within about 1–8 bps. The book mid deviates from the oracle by −20 to +14 bps.
- **Spreads.** 5.2–11.9 bps on BTC, ETH, HYPE, SP500, EWY, EWJ, BRENT, GOLD and USDJPY (Sunday 25 Oct). The best level is about $37 to $500.
- **Volume.** 15–33% of `pas` 1h bars have zero volume. Any maker strategy here fills mostly against market-maker quote moves, not real flow. A $5,000 resting order would be 10 or more times the displayed best level.
- **Funding.** Longs on BTC, ETH, HYPE and SP500 are paid about 0.15–0.23% per day; shorts on USDJPY about 0.12% per day (8-day means).

## 8. Lessons learned

1. **Fees are a strategy parameter.** Our largest "loss" was a cost structure we never priced in. A gross edge of +$0.05 against $1.71 of fees is not bad luck.
2. **The exchange is the ledger.** A placement response is a claim, a position snapshot is a moment, and fills are facts. Both live bugs came from trusting our own view of an order over the exchange's.
3. **An error is not an absence.** "My stop update failed" is a different state from "I have no stop". Flattening on the first meant leaving the market with a valid stop resting on the exchange.
4. **Timing is a safety property.** Each 5 s rule was correct on its own. Combined with a rolling rate budget, they made a position impossible to protect. Waits belong before the authority, not inside it.
5. **Hold the test set back, and believe it.** An optimistic model that looked good in sample lost out of sample. Six strategies plus one more produced no edge after costs, and that is the result we report.
6. **Know the scoring.** With Q = (max(R,0)+0.005)/(|R|+1.5σ+0.05) and negative returns ranked below flat, the best move without an edge is not to trade.

## 9. What we would do with more time

- **Read budget.** Each guarded entry reserves about 880 of the 1,200/min IP weight. We now log weight per entry cycle (`ENTRY_CYCLE_WEIGHT`); evaluating three markets costs 123 per 5-minute bar. Next we would move book, account and order state to WebSocket subscriptions, keeping one REST freshness read before each order, to target ≤ 200 per entry.
- **Measure maker fills on `pas`.** Before trusting any maker model here, we would measure real maker fill rates and queue position with tiny resting orders.
- **Collect more `pas` history**, so research can run on the venue itself rather than a mainnet proxy.
- **Make the carry market-neutral**, for example by hedging the basket's price exposure with a correlated short, so that it earns funding without a 42% chance of a negative finish.
- **Re-fit the ML filter** once there are a few hundred genuine labelled candidates.
- **Move to an always-on VPS.** The deployment kit is prepared in `deploy/vps/`, with Docker or systemd, reconcile on boot and secrets in the environment. It removes the laptop as a single point of failure.

## 10. Reproducing our results

```bash
python3 scripts/check_strategy_freeze.py                      # frozen strategy unchanged
python3 docs/continuous_2026-10-24/run_regression.py          # full offline regression + receipt
node research/test_fee_aware_backtest.js                      # fill/cost model checks
python3 scripts/backfill_missing_fills.py --fills docs/fee_bleed_2026-10-25/exchange_fills_since_2026-10-15.json \
        --state runtime/continuous --since-ms <session start>  # dry run; --apply to write
python3 docs/carry_2026-10-25/run_regression.py               # carry release receipt
python3 scripts/run_carry.py dry-run --minutes 15             # carry runtime on a simulated venue, no key
python3 -m pytest algo-trading-bot/test_carry_profile.py      # carry limits, slicing, stops, restart, halts
```

Every live action is bound to a mandate file and a matching release receipt. Events go to `runtime/<session>/overnight_events.jsonl` (carry: `runtime/carry-basket/carry_events.jsonl`) and to the journal at `runtime/testnet/anchorium-bot-1/pas.sqlite`.
