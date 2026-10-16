# Anchorium — FEED_NOT_READY

Latest user definition: operational transport/account barrier plus genuinely usable market inputs and safe scanner evaluation. Repeated recorded usable-feed samples are required; signal/trade is not required. The older three-scanner-window certificate is retained separately, not rewritten.

Runtime: 902.996s. Actual orders: 0. PAPER fills: 0.
Usable-feed observations: 8; partial-health observations: 8.
Quarantined: par:BRENT, par:BTC, par:ETH, par:EWJ, par:EWY, par:GOLD, par:HYPE, par:SP500, par:USDEUR, par:USDJPY.
Restored after quarantine: par:BTC.
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
| TOTAL_MARKETS_SEEN | 30 | 30 | 0 | 100.00% | 30/30 |
| VALID_MARKET_IDENTITY | 30 | 30 | 0 | 100.00% | 30/30 |
| MARKET_DATA_HEALTHY | 30 | 1 | 29 | 3.33% | 1/30 |
| ENOUGH_HISTORY | 30 | 23 | 7 | 76.67% | 1/1 |
| LIQUIDITY_PASS | 1 | 1 | 0 | 100.00% | 1/1 |
| SPREAD_PASS | 1 | 1 | 0 | 100.00% | 1/1 |
| ATR_PASS | 1 | 0 | 1 | 0.00% | 0/1 |
| SCANNER_QUALIFIED | 30 | 0 | 30 | 0.00% | 0/0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0/0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0/0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0/0 |
| EXECUTION_PERMISSION | 30 | 0 | 30 | 0.00% | 0/0 |
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
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 255; data: INSUFFICIENT_HISTORY
  par:BTC: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 295; data: INSUFFICIENT_HISTORY
  par:ETH: QUARANTINED
    reasons: STRATEGY_CANDLE_GAP_OR_DUPLICATE, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 269; data: INVALID_DATA
  par:EWJ: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 0; data: INSUFFICIENT_HISTORY
  par:EWY: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 236; data: INSUFFICIENT_HISTORY
  par:GOLD: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 168; data: INSUFFICIENT_HISTORY
  par:HYPE: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 292; data: INSUFFICIENT_HISTORY
  par:SP500: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 289; data: INSUFFICIENT_HISTORY
  par:USDEUR: QUARANTINED
    reasons: STRATEGY_CANDLE_GAP_OR_DUPLICATE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 294; data: INVALID_DATA
  par:USDJPY: QUARANTINED
    reasons: INSUFFICIENT_COMPLETED_HISTORY, LAST_CANDLE_TIME_STALE, LAST_ORDERBOOK_TIME_STALE, LAST_TICK_TIME_STALE
    completed bars: 2; data: INSUFFICIENT_HISTORY

FEED_READY: NO
TRADE_READY: NO (PAPER safety lock)
SIGNAL / SCANNER: NO_TRADE
GLOBAL BLOCKER: NO_HEALTHY_PUBLIC_MARKET_FEED
CHECK RESULT: PAPER_DATA_OR_OPERATIONS_DEGRADED; EXIT CODE: 2
ACCOUNT TRUTH: local PAPER ledger; funded execution is not certified.
```

The funded wallet is separate from this hypothetical ledger. Protection, funded LONG/SHORT and funded recovery remain untested. PAPER/false and protection disabled remain enforced.
