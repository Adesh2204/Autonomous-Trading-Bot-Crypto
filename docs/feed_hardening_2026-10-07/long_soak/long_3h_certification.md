Team Anchorium — FEED_NOT_READY

Duration: 10801.81 seconds. Actual exchange orders: 0.
PAPER fills: 0. Feed certified: False. Practice ready: false.
This session: 360 market observations; cumulative ledger: 360.

Per-market valid scanner data windows:

| Market | Evaluated | Healthy | Healthy % | Best consecutive windows |
|---|---:|---:|---:|---:|
| par:BRENT | 36 | 11 | 30.56 | 2 |
| par:BTC | 36 | 4 | 11.11 | 2 |
| par:ETH | 36 | 5 | 13.89 | 2 |
| par:EWJ | 36 | 0 | 0.00 | 0 |
| par:EWY | 36 | 3 | 8.33 | 1 |
| par:GOLD | 36 | 1 | 2.78 | 1 |
| par:HYPE | 36 | 2 | 5.56 | 1 |
| par:SP500 | 36 | 6 | 16.67 | 2 |
| par:USDEUR | 36 | 1 | 2.78 | 1 |
| par:USDJPY | 36 | 1 | 2.78 | 1 |

Observed checks (independent; unobserved is excluded from evaluated):

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted / evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 360 | 360 | 0 | 100.00 | 360 / 360 |
| VALID_MARKET_IDENTITY | 360 | 360 | 0 | 100.00 | 360 / 360 |
| MARKET_DATA_HEALTHY | 360 | 34 | 326 | 9.44 | 34 / 360 |
| ENOUGH_HISTORY | 360 | 360 | 0 | 100.00 | 34 / 34 |
| LIQUIDITY_PASS | 34 | 34 | 0 | 100.00 | 34 / 34 |
| SPREAD_PASS | 34 | 6 | 28 | 17.65 | 6 / 34 |
| ATR_PASS | 34 | 0 | 34 | 0.00 | 0 / 6 |
| SCANNER_QUALIFIED | 360 | 0 | 360 | 0.00 | 0 / 0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| EXECUTION_PERMISSION | 360 | 0 | 360 | 0.00 | 0 / 0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0 / 0 |

First blocking reasons by category (each market-cycle counted once):

{
  "INFRASTRUCTURE": {
    "STALE_CANDLE": 318,
    "INVALID_MARKET_DATA": 8
  },
  "MARKET": {
    "ATR_BELOW_SCANNER_FLOOR": 34
  },
  "STRATEGY": {},
  "RISK_ECONOMICS": {},
  "UNCLASSIFIED": {}
}

Disconnect reasons: {'ExchangeError:STREAM_DISCONNECTED': 16}.
Checkpoint and backup valid: True. Clean shutdown: True. Source unchanged during run: True.
Certification blockers: sustained_valid_market, final_valid_market.

Close codes and transport timing absent in old runs remain unknown. A past error string alone cannot prove it was unresolved at shutdown. No strategy profitability or funded practice is certified.
