# Anchorium research readiness

These flags are derived from saved evidence. PAPER mode and the live-order lock remain enforced.

| Flag | Value | Meaning |
|---|---|---|
| `BASELINE_PRESERVED` | `TRUE` | Protected baseline and isolated research mechanisms. |
| `VWAP_RESEARCH_READY` | `TRUE` | Protected baseline and isolated research mechanisms. |
| `SESSION_ANCHOR_VALIDATED` | `FALSE` | Documented session hypothesis has adequate prospective, paired after-cost portfolio evidence. |
| `ML_DATA_READY` | `FALSE` | Each model domain has enough genuine audited candidate labels and diversity. |
| `ML_MODEL_VALIDATED` | `FALSE` | Sealed numerical models improve held-out calibration/classification and their independent portfolios pass risk/cost comparisons. |
| `HOLDOUT_COMPLETE` | `FALSE` | The prespecified future window has ended, is fully observed, and has adequate audited labels. |
| `PROMOTION_RECOMMENDED` | `FALSE` | A proposal for human review; it grants no exchange-write permission. |
| `PRODUCTION_CHANGED` | `FALSE` | Must remain FALSE in this research task. |

## Data remaining

| Model domain | Labeled candidates | Labeled dates | Remaining candidates | Remaining dates |
|---|---:|---:|---:|---:|
| VWAP_BASELINE_UTC | 0 | 0 | 500 | 20 |
| SESSION_JAPANESE_EQUITY_REFERENCE | 0 | 0 | 500 | 20 |
| SESSION_KOREAN_EQUITY_REFERENCE | 0 | 0 | 500 | 20 |
| SESSION_US_CASH_REFERENCE | 0 | 0 | 500 | 20 |

## Collection constraint

The 2-setups/day reference portfolio cannot yield 500 completed unique trades in a few weeks. Multiple arms/replays must not inflate the UTC sample. Historical candles alone cannot supply executable outcomes.

## Next steps

1. Collect continuous public par receipts with fresh candles, BBO and mark/context clocks; investigate stale-market diagnostics.
2. Run the four independent paper portfolios; preserve scanner/risk/cooldown limits and audit every completed trade.
3. Accumulate adequate labeled evidence in each declared anchor domain. Never combine repeated replays into new data.
4. Choose explicit earlier train/calibration/validation dates and a future holdout, then seal model artifacts before it begins.
5. Record the complete future holdout; replay all four arms with the sealed models and inspect costs, drawdown and paired days.
6. Accept only evidence-supported improvements; retain the UTC deterministic baseline if alternatives do not beat it.
7. A promotion recommendation is a review proposal. Production activation still requires the existing explicit human verification process.

## Current scan blockers

{
  "COMPLETED_CANDLE_STALE": 8,
  "ATR_BELOW_BASELINE_SCANNER_FLOOR": 2,
  "SPREAD_TOO_WIDE": 2
}

Results describe local paper research. No competition rank or future profit is guaranteed.
