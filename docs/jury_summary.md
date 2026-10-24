# Team Anchorium — summary for the Perpetual Alpha jury

*Hyperliquid testnet, `pas` dex. Written 24 October 2026, during live trading. Every number below comes from the exchange or from our own logs; anything we could not measure is stated as unknown.*

## 1. What we built

We set out to move an existing, proven intraday agent from Indian equities onto HIP-3 perpetuals without silently changing its strategy. The project has two parts:

- an execution stack where every order fails closed;
- a research programme that refuses to trade anything that does not survive out-of-sample testing after costs.

We trade one position at a time, at 1x cross leverage. Every entry has a resting reduce-only stop on the exchange. Its size is limited to 10% of the displayed best level. Our score so far is small and honest: −$0.18 net on $100,000. We have had no runaway position, no unexplained order and no loss caused by a bug.

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
post-action reconciliation ─▶ exchange-side reduce-only stop ─▶ per-entry verification
```

- **Separation of truths.** Exchange account truth (fills, fees, funding) is kept apart from any paper or estimated ledger. The P&L we report comes from fills the exchange reported, never from our own estimates.
- **One owner, one journal.** A SQLite journal records each intent's client order ID before it is signed. A timeout leaves the intent UNKNOWN, and an UNKNOWN intent is never blindly re-sent. On restart the bot starts UNKNOWN and only enters after it has reconciled with the exchange.
- **Strategy freeze.** The original strategy methods are hashed (`docs/strategy_freeze.json`) and checked before every release (`scripts/check_strategy_freeze.py`). Exchange plumbing may change; the strategy may not.
- **Releases are bound to evidence.** A live session starts only from a mandate whose source hash matches a full offline regression receipt (about 3,380 tests, no network, ephemeral signing keys). If any file changes, the authority is revoked within 60 s.

## 3. The safety system

**Fail-closed checks on every order.** Before an order is signed:

- the book, account and readiness snapshots must be under 5 s old, and so must the permission;
- the mark–oracle divergence and the order's distance from the reference price are bounded;
- no self-cross and no duplicate intent;
- the size is at most 10% of the best level;
- the account holds exactly one global position;
- a shared-account barrier confirms there is no foreign exposure or unresolved intent;
- the nonce and clock must be healthy, and rate reserves must remain.

If any check is missing, stale or ambiguous, the order is blocked; it is never assumed safe.

**Verified halts.** After every entry the bot reads the exchange back. It checks the position side and size, exactly one reduce-only stop and exactly one reduce-only take-profit. Any mismatch makes it flatten, cancel and halt, and it does not retry. Other halts:

- three consecutive order errors;
- an account-stream disconnect longer than 3 minutes;
- a daily loss of −0.30%;
- a rank-protection lock.

Each halt ends with two exchange readings that confirm the account is flat.

**The bug we found live, and what it cost.** On 24 October our first live short filled, but the bot could not place its exchange stop. It verified the entry, found the stop missing, flattened and halted, exactly as designed. We traced the cause from our own journal:

- After the fill, the stop's guarded context load waited about 25 s for read budget inside Hyperliquid's rolling IP-weight limit (1,200/min).
- That wait happened *after* the order book had been read, so the 5 s freshness rules rejected the stop (`STALE_PRICE_CONTEXT`).
- After idle periods, the clock also needed two fresh confirmations.

The position was flattened under the same guards. The exit filled at 80,541, better than the failed stop's 80,600.72 trigger, so the bug added no loss. The whole trade lost $0.128, of which $0.090 was fees.

The fix keeps every rule. A `FreshReadGate` runs immediately before each entry, stop, take-profit, cancel and exit. It does all the waiting *before* the 5 s permission exists:

- reconcile, if needed;
- wait for budget headroom (an entry also reserves room for its stop);
- confirm the clock;
- pass the shared barrier.

A regression test reproduces the live failure on the real signed path, without network access. It shows the stop refused without the gate and signed with it.

## 4. Strategy research: six strategies, all rejected out of sample

We did not want to force trades out of an untested idea, so we tested replacements systematically:

- **Candidates:** z-score mean reversion, Donchian breakout, EMA+ADX trend, funding tilt, VWAP fade and oracle-basis reversion, each in both directions.
- **Timeframes:** 5-minute, 15-minute and 1-hour bars.
- **Method:** a 70/30 chronological split on `pas` testnet data and on 200 days of mainnet data, with taker fees and slippage measured from the books.

**Every candidate failed out of sample after costs.** The best gross edges were about +0.06% to +0.095% per trade. Measured costs are far higher: taker fills are charged 0.09% per side, and slippage at the touch is 3–4 bps. We report this as a negative result rather than tune parameters until something passes.

Facts we measured about the venue:

- `pas` prices follow an oracle that tracks real prices to within about 1–8 bps.
- The book mid deviates from the oracle by −20 to +14 bps.
- The best level is usually a resting quote of about $500, while about $110k sits within 25 bps on each side.
- Funding on BTC, ETH, HYPE and SP500 pays longs about 0.11–0.19% per day.
- Under the frozen scalper's geometry (stop = max(1×ATR, 0.15%), take-profit at 1.5:1) and these fees, the breakeven win rate is 82–88%. A move of one 5-minute ATR (0.05–0.08%) does not even cover the round-trip cost. That is why we keep sizes small.

**ML, built but not promoted.** We built an explainable candidate-quality meta-controller: an L2 logistic regression and a depth-3 probability tree, with Platt calibration, chronological purged splits, transforms fitted on training data only, and a sealed holdout. It filters candidates and never chooses a direction. We have not deployed it because the genuine labelled sample is too small to fit honestly. Showing results from synthetic fixtures would mislead, so we do not.

## 5. Lessons learned

1. **Timing is a safety property.** Each 5 s rule was correct on its own. Together with a shared, rolling rate budget they made it impossible to protect the position. Unit tests that faked the transport missed this. Only the real submit path, with realistic read latency and budget, reproduced it. Every release now includes such a test.
2. **Waits belong before the authority, not inside it.** Moving every wait ahead of the permission fixed the failure without loosening a single rule.
3. **A verified halt is worth more than a clever exit.** The first live failure cost nothing because the bot checked the exchange itself rather than trusting its own state.
4. **Negative results are results.** Six strategies, three timeframes and two datasets produced no edge after costs. That told us more than one backtest that happened to pass.
5. **Know the scoring.** The financial score Q = (max(R,0)+0.005)/(|R|+1.5σ+0.05) rewards small, steady gains. A one-day spike counts fully in σ. So we cap daily losses at −0.30% and lock gains when the target is reached.

## 6. Reproducing our results

```bash
python3 scripts/check_strategy_freeze.py          # frozen strategy unchanged
python3 docs/day_2026-10-24/run_regression.py     # full offline regression + receipt
python3 scripts/run_day.py dry-run --minutes 10   # live public data, no orders
```

All live actions are bound to a mandate file and a matching release receipt. All events go to `runtime/day-session/overnight_events.jsonl` and to the journal at `runtime/testnet/anchorium-bot-1/pas.sqlite`.
