Team Anchorium — FEED_NOT_READY

Duration: 901.71 seconds. Actual exchange orders: 0.
PAPER fills: 0. Feed certified: False. Practice ready: false.
This session: 30 market observations; cumulative ledger: 30.

Per-market valid scanner data windows:

| Market | Evaluated | Healthy | Healthy % | Best consecutive windows |
|---|---:|---:|---:|---:|
| par:BRENT | 3 | 0 | 0.00 | 0 |
| par:BTC | 3 | 0 | 0.00 | 0 |
| par:ETH | 3 | 0 | 0.00 | 0 |
| par:EWJ | 3 | 0 | 0.00 | 0 |
| par:EWY | 3 | 0 | 0.00 | 0 |
| par:GOLD | 3 | 1 | 33.33 | 1 |
| par:HYPE | 3 | 0 | 0.00 | 0 |
| par:SP500 | 3 | 2 | 66.67 | 2 |
| par:USDEUR | 3 | 0 | 0.00 | 0 |
| par:USDJPY | 3 | 0 | 0.00 | 0 |

Observed checks (independent; unobserved is excluded from evaluated):

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted / evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 30 | 30 | 0 | 100.00 | 30 / 30 |
| VALID_MARKET_IDENTITY | 30 | 30 | 0 | 100.00 | 30 / 30 |
| MARKET_DATA_HEALTHY | 30 | 3 | 27 | 10.00 | 3 / 30 |
| ENOUGH_HISTORY | 30 | 30 | 0 | 100.00 | 3 / 3 |
| LIQUIDITY_PASS | 3 | 3 | 0 | 100.00 | 3 / 3 |
| SPREAD_PASS | 3 | 3 | 0 | 100.00 | 3 / 3 |
| ATR_PASS | 3 | 0 | 3 | 0.00 | 0 / 3 |
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
    "STALE_CANDLE": 25,
    "RECOVERY_PENDING": 2
  },
  "MARKET": {
    "ATR_BELOW_SCANNER_FLOOR": 3
  },
  "STRATEGY": {},
  "RISK_ECONOMICS": {},
  "UNCLASSIFIED": {}
}

Disconnect reasons: {'ExchangeError:STREAM_DISCONNECTED': 1}.
Checkpoint and backup valid: True. Clean shutdown: True. Source unchanged during run: True.
Certification blockers: sustained_valid_market, final_valid_market.

Close codes and transport timing absent in old runs remain unknown. A past error string alone cannot prove it was unresolved at shutdown. No strategy profitability or funded practice is certified.
