# Anchorium — FEED_NOT_READY

Latest user definition: operational transport/account barrier plus genuinely usable market inputs and safe scanner evaluation. Repeated recorded usable-feed samples are required; signal/trade is not required. The older three-scanner-window certificate is retained separately, not rewritten.

Runtime: 354.906s. Actual orders: 0. PAPER fills: 0.
Usable-feed observations: 3; partial-health observations: 3.
Quarantined: par:BRENT, par:BTC, par:ETH, par:EWJ, par:EWY, par:GOLD, par:HYPE, par:SP500, par:USDEUR, par:USDJPY.
Restored after quarantine: par:SP500.
Final usable markets: None.
Blockers: final_usable_market.

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
| final_usable_market | False |
| health_samples_checksum_matches | True |
| workers_stopped_cleanly | True |

Independent checks and sequential admissions:

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted/evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 20 | 20 | 0 | 100.00% | 20/20 |
| VALID_MARKET_IDENTITY | 20 | 20 | 0 | 100.00% | 20/20 |
| MARKET_DATA_HEALTHY | 20 | 1 | 19 | 5.00% | 1/20 |
| ENOUGH_HISTORY | 20 | 14 | 6 | 70.00% | 1/1 |
| LIQUIDITY_PASS | 1 | 1 | 0 | 100.00% | 1/1 |
| SPREAD_PASS | 1 | 1 | 0 | 100.00% | 1/1 |
| ATR_PASS | 1 | 0 | 1 | 0.00% | 0/1 |
| SCANNER_QUALIFIED | 20 | 0 | 20 | 0.00% | 0/0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| EXECUTION_PERMISSION | 20 | 0 | 20 | 0.00% | 0/0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0/0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0/0 |

Actual saved operating sample (historical, not a live check):

```text
TEAM ANCHORIUM — PAPER HEALTH

OVERALL: DEGRADED
PROCESS: RUNNING
TRANSPORT: CONNECTED
SUBSCRIPTIONS: 40 / 40
MISSING: 0; DUPLICATES: 0
RECONCILIATION: PASS
USABLE MARKETS: 0 / 10

MARKETS:
  par:BRENT: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 275; data: INSUFFICIENT_HISTORY
  par:BTC: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 231; data: INSUFFICIENT_HISTORY
  par:ETH: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 288; data: INSUFFICIENT_HISTORY
  par:EWJ: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 17; data: INSUFFICIENT_HISTORY
  par:EWY: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 256; data: INSUFFICIENT_HISTORY
  par:GOLD: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 188; data: INSUFFICIENT_HISTORY
  par:HYPE: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 277; data: INSUFFICIENT_HISTORY
  par:SP500: QUARANTINED
    reasons: LAST_CANDLE_TIME_STALE
    completed bars: 301; data: STALE_CANDLE
  par:USDEUR: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 67; data: INSUFFICIENT_HISTORY
  par:USDJPY: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE
    completed bars: 22; data: INSUFFICIENT_HISTORY

FEED_READY: NO
TRADE_READY: NO (PAPER safety lock)
SIGNAL / SCANNER: NO_TRADE
GLOBAL BLOCKER: NO_HEALTHY_PUBLIC_MARKET_FEED
CHECK RESULT: PAPER_DATA_OR_OPERATIONS_DEGRADED; EXIT CODE: 2
ACCOUNT TRUTH: local PAPER ledger; funded execution is not certified.
```

The funded wallet is separate from this hypothetical ledger. Protection, funded LONG/SHORT and funded recovery remain untested. PAPER/false and protection disabled remain enforced.
