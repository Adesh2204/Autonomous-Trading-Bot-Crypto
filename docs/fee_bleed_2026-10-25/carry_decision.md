# Funding-carry basket: half size and a −1.5% hard stop (decision support only)

*25 October 2026. Not implemented, and nothing traded. Implementation needs the user's explicit "yes, carry".*

**Basket.** Long BTC, ETH, HYPE and SP500; short USDJPY. All on `pas`, at 1x. Full size is $19,000 per leg ($95k gross on $100k). Half size is $9,500 per leg.

**Horizon.** 281 h, from 25 Oct 18:00 UTC to the 6 Nov 11:30 UTC flatten.

**Model** (`research/carry_risk_mc.js`, 20,000 paths, fixed seed):

- **Prices.** 24 h block bootstrap of joint hourly mainnet returns (BTC, ETH, HYPE, `xyz:SP500`, `xyz:JPY` = USDJPY) from 31 Mar to 25 Oct 2026. This keeps cross-correlation and volatility clustering. Each asset's sample drift is removed, because the sample rallied 27 to 134%/yr and that drift would otherwise count as free "carry".
- **Funding received.** The 8-day mean of `pas` testnet hourly rates per leg: BTC 0.177%/day, ETH 0.164%/day, HYPE 0.153%/day, SP500 0.229%/day, USDJPY short 0.123%/day. This is scaled by 1.20 so that the full-size median reproduces the earlier estimate of +0.96%. With that scaling it also reproduces P(loss) of about 42%.
- **Costs.** 0.09% taker plus 4.55 bps measured slippage per leg per side.
- **Stops.** The existing 8% per-leg stop is always on. The −1.5% basket stop is checked hourly on marked P&L, so it can overshoot on a gap hour.

| Scenario | Median | Mean | P(loss) | 5th pct | 1st pct | Worst | P(stop hit) |
|---|---|---|---|---|---|---|---|
| Full size (earlier estimate: +0.96%, 42%, 5% ≤ −7.7%) | +0.91% | +1.93% | **42.7%** | −4.19% | −4.85% | −6.22% | — |
| **Half size** | +0.46% | +0.96% | **42.7%** | −2.10% | −2.42% | −3.11% | — |
| Full size, −1.5% basket stop | **−1.56%** | +0.93% | **66.9%** | −2.16% | −2.80% | −4.73% | 65.2% |
| **Half size, −1.5% basket stop** | +0.12% | +0.75% | **48.4%** | −1.74% | −1.95% | −2.90% | 36.4% |

Sensitivity, using the unscaled 8-day funding: half size has median +0.28%, P(loss) 45.4% and 5th percentile −2.22%. Half size with the stop has median −0.11%, P(loss) 51.3% and 5th percentile −1.75%.

## Reading it

1. **Half size halves the size of every outcome but leaves P(loss) at 42.7%.** The probability of finishing negative does not depend on scale. Under our formula, a finish below zero ranks below every flat team, whatever its size.
2. **A −1.5% hard stop makes the chance of a negative finish worse.** P(loss) rises from 42.7% to 48% at half size and to 67% at full size. The stop turns ordinary mid-path drawdowns into realised losses that funding has no time to recover. It does cap the tail: at half size the 5th percentile goes from −2.10% to −1.74%.
3. **Our reconstruction has a thinner left tail than the earlier estimate.** At full size we get a 5th percentile of −4.2%, against the earlier −7.7%. We do not know which model produced −7.7%, so read the worse tail as the planning number. That earlier estimate implies a 5th percentile of about −3.9% at half size.
4. **Even the best variant here is a coin flip against being flat.** Half size without a stop has a 43% chance of ranking below flat, for a median gain of +0.46%.

The decision is the user's. On these numbers, no carry variant improves the expected rank over staying flat.
