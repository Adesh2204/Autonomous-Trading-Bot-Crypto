Team Anchorium — FEED_NOT_READY

Duration: 903.00 seconds. Actual exchange orders: 0.
PAPER fills: 0. Feed certified: False. Practice ready: false.
This session: 30 market observations; cumulative ledger: 30.

Per-market valid scanner data windows:

| Market | Evaluated | Healthy | Healthy % | Best consecutive windows |
|---|---:|---:|---:|---:|
| par:BRENT | 3 | 0 | 0.00 | 0 |
| par:BTC | 3 | 1 | 33.33 | 1 |
| par:ETH | 3 | 0 | 0.00 | 0 |
| par:EWJ | 3 | 0 | 0.00 | 0 |
| par:EWY | 3 | 0 | 0.00 | 0 |
| par:GOLD | 3 | 0 | 0.00 | 0 |
| par:HYPE | 3 | 0 | 0.00 | 0 |
| par:SP500 | 3 | 0 | 0.00 | 0 |
| par:USDEUR | 3 | 0 | 0.00 | 0 |
| par:USDJPY | 3 | 0 | 0.00 | 0 |

Observed checks (independent; unobserved is excluded from evaluated):

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted / evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 30 | 30 | 0 | 100.00 | 30 / 30 |
| VALID_MARKET_IDENTITY | 30 | 30 | 0 | 100.00 | 30 / 30 |
| MARKET_DATA_HEALTHY | 30 | 1 | 29 | 3.33 | 1 / 30 |
| ENOUGH_HISTORY | 30 | 23 | 7 | 76.67 | 1 / 1 |
| LIQUIDITY_PASS | 1 | 1 | 0 | 100.00 | 1 / 1 |
| SPREAD_PASS | 1 | 1 | 0 | 100.00 | 1 / 1 |
| ATR_PASS | 1 | 0 | 1 | 0.00 | 0 / 1 |
| SCANNER_QUALIFIED | 30 | 0 | 30 | 0.00 | 0 / 0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| EXECUTION_PERMISSION | 30 | 0 | 30 | 0.00 | 0 / 0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0 / 0 |

First blocking reasons by category (each market-cycle counted once):

{
  "INFRASTRUCTURE": {
    "STALE_CANDLE": 21,
    "INSUFFICIENT_HISTORY": 7,
    "RECOVERY_PENDING": 1
  },
  "MARKET": {
    "ATR_BELOW_SCANNER_FLOOR": 1
  },
  "STRATEGY": {},
  "RISK_ECONOMICS": {},
  "UNCLASSIFIED": {}
}

Disconnect reasons: {'ExchangeError:STREAM_DISCONNECTED': 1}.
Checkpoint and backup valid: True. Clean shutdown: True. Source unchanged during run: True.
Certification blockers: sustained_valid_market, final_valid_market.

Close codes and transport timing absent in old runs remain unknown. A past error string alone cannot prove it was unresolved at shutdown. No strategy profitability or funded practice is certified.
