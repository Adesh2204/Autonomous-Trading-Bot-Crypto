Team Anchorium — FEED_NOT_READY

Duration: 1801.45 seconds. Actual exchange orders: 0.
PAPER fills: 0. Feed certified: False. Practice ready: false.
This session: 60 market observations; cumulative ledger: 60.

Per-market valid scanner data windows:

| Market | Evaluated | Healthy | Healthy % | Best consecutive windows |
|---|---:|---:|---:|---:|
| par:BRENT | 6 | 2 | 33.33 | 2 |
| par:BTC | 6 | 1 | 16.67 | 1 |
| par:ETH | 6 | 2 | 33.33 | 1 |
| par:EWJ | 6 | 0 | 0.00 | 0 |
| par:EWY | 6 | 1 | 16.67 | 1 |
| par:GOLD | 6 | 1 | 16.67 | 1 |
| par:HYPE | 6 | 0 | 0.00 | 0 |
| par:SP500 | 6 | 0 | 0.00 | 0 |
| par:USDEUR | 6 | 1 | 16.67 | 1 |
| par:USDJPY | 6 | 1 | 16.67 | 1 |

Observed checks (independent; unobserved is excluded from evaluated):

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted / evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 60 | 60 | 0 | 100.00 | 60 / 60 |
| VALID_MARKET_IDENTITY | 60 | 60 | 0 | 100.00 | 60 / 60 |
| MARKET_DATA_HEALTHY | 60 | 9 | 51 | 15.00 | 9 / 60 |
| ENOUGH_HISTORY | 60 | 60 | 0 | 100.00 | 9 / 9 |
| LIQUIDITY_PASS | 9 | 9 | 0 | 100.00 | 9 / 9 |
| SPREAD_PASS | 9 | 9 | 0 | 100.00 | 9 / 9 |
| ATR_PASS | 9 | 0 | 9 | 0.00 | 0 / 9 |
| SCANNER_QUALIFIED | 60 | 0 | 60 | 0.00 | 0 / 0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| EXECUTION_PERMISSION | 60 | 0 | 60 | 0.00 | 0 / 0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0 / 0 |

First blocking reasons by category (each market-cycle counted once):

{
  "INFRASTRUCTURE": {
    "STALE_CANDLE": 49,
    "RECOVERY_PENDING": 2
  },
  "MARKET": {
    "ATR_BELOW_SCANNER_FLOOR": 9
  },
  "STRATEGY": {},
  "RISK_ECONOMICS": {},
  "UNCLASSIFIED": {}
}

Disconnect reasons: {'ExchangeError:STREAM_DISCONNECTED': 2}.
Checkpoint and backup valid: True. Clean shutdown: True. Source unchanged during run: True.
Certification blockers: sustained_valid_market.

Close codes and transport timing absent in old runs remain unknown. A past error string alone cannot prove it was unresolved at shutdown. No strategy profitability or funded practice is certified.
