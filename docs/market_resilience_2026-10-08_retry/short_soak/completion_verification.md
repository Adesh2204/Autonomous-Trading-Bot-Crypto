# Anchorium — FEED_READY

Latest user definition: operational transport/account barrier plus genuinely usable market inputs and safe scanner evaluation. Repeated recorded usable-feed samples are required; signal/trade is not required. The older three-scanner-window certificate is retained separately, not rewritten.

Runtime: 1801.455s. Actual orders: 0. PAPER fills: 0.
Usable-feed observations: 28; partial-health observations: 28.
Quarantined: par:BRENT, par:BTC, par:ETH, par:EWJ, par:EWY, par:GOLD, par:HYPE, par:SP500, par:USDEUR, par:USDJPY.
Restored after quarantine: par:BTC, par:EWY, par:GOLD, par:SP500.
Final usable markets: par:EWY.
Blockers: None.

| Check | Passed |
|---|---|
| transport_diagnostics_available | True |
| final_transport_recovered | True |
| subscriptions_confirmed_once | True |
| no_reconnect_storm | True |
| no_pending_rest | True |
| paper_account_reconciled | True |
| no_accounting_halt | True |
| checkpoint_valid | True |
| clean_shutdown | True |
| source_unchanged | True |
| regression_passed | True |
| paper_lock | True |
| no_exchange_orders | True |
| repeated_usable_feed_observations | True |
| safe_scanner_data_evaluation | True |
| final_usable_market | True |
| health_samples_checksum_matches | True |
| workers_stopped_cleanly | True |

Independent checks and sequential admissions:

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted/evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 60 | 60 | 0 | 100.00% | 60/60 |
| VALID_MARKET_IDENTITY | 60 | 60 | 0 | 100.00% | 60/60 |
| MARKET_DATA_HEALTHY | 60 | 9 | 51 | 15.00% | 9/60 |
| ENOUGH_HISTORY | 60 | 60 | 0 | 100.00% | 9/9 |
| LIQUIDITY_PASS | 9 | 9 | 0 | 100.00% | 9/9 |
| SPREAD_PASS | 9 | 9 | 0 | 100.00% | 9/9 |
| ATR_PASS | 9 | 0 | 9 | 0.00% | 0/9 |
| SCANNER_QUALIFIED | 60 | 0 | 60 | 0.00% | 0/0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| EXECUTION_PERMISSION | 60 | 0 | 60 | 0.00% | 0/0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0/0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0/0 |

Actual saved operating sample (historical, not a live check):

```text
TEAM ANCHORIUM — PAPER HEALTH

OVERALL: PARTIAL_HEALTHY
PROCESS: RUNNING
TRANSPORT: CONNECTED
SUBSCRIPTIONS: 40 / 40
MISSING: 0; DUPLICATES: 0
RECONCILIATION: PASS
USABLE MARKETS: 1 / 10

MARKETS:
  par:BRENT: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 286; data: INSUFFICIENT_HISTORY
  par:BTC: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 290; data: INSUFFICIENT_HISTORY
  par:ETH: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 299; data: INSUFFICIENT_HISTORY
  par:EWJ: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 120; data: INSUFFICIENT_HISTORY
  par:EWY: HEALTHY
    reasons: NONE
    completed bars: 300; data: HEALTHY
  par:GOLD: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 295; data: INSUFFICIENT_HISTORY
  par:HYPE: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 253; data: INSUFFICIENT_HISTORY
  par:SP500: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 289; data: INSUFFICIENT_HISTORY
  par:USDEUR: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 275; data: INSUFFICIENT_HISTORY
  par:USDJPY: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 276; data: INSUFFICIENT_HISTORY

FEED_READY: YES
TRADE_READY: NO (PAPER safety lock)
SIGNAL / SCANNER: NO_TRADE
GLOBAL BLOCKER: NONE
CHECK RESULT: PAPER_PARTIAL_HEALTHY; EXIT CODE: 0
ACCOUNT TRUTH: local PAPER ledger; funded execution is not certified.
```

The funded wallet is separate from this hypothetical ledger. Protection, funded LONG/SHORT and funded recovery remain untested. PAPER/false and protection disabled remain enforced.
