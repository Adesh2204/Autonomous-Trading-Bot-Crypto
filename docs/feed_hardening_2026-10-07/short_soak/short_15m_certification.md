Team Anchorium — FEED_NOT_READY

Duration: 18.13 seconds. Actual exchange orders: 0.
PAPER fills: 0. Feed certified: False. Practice ready: false.
This session: 10 market observations; cumulative ledger: 10.

Per-market valid scanner data windows:

| Market | Evaluated | Healthy | Healthy % | Best consecutive windows |
|---|---:|---:|---:|---:|
| par:BRENT | 1 | 0 | 0.00 | 0 |
| par:BTC | 1 | 0 | 0.00 | 0 |
| par:ETH | 1 | 0 | 0.00 | 0 |
| par:EWJ | 1 | 0 | 0.00 | 0 |
| par:EWY | 1 | 0 | 0.00 | 0 |
| par:GOLD | 1 | 0 | 0.00 | 0 |
| par:HYPE | 1 | 1 | 100.00 | 1 |
| par:SP500 | 1 | 1 | 100.00 | 1 |
| par:USDEUR | 1 | 0 | 0.00 | 0 |
| par:USDJPY | 1 | 0 | 0.00 | 0 |

Observed checks (independent; unobserved is excluded from evaluated):

| Stage | Evaluated | Passed | Failed | Pass % | Sequential admitted / evaluated |
|---|---:|---:|---:|---:|---:|
| TOTAL_MARKETS_SEEN | 10 | 10 | 0 | 100.00 | 10 / 10 |
| VALID_MARKET_IDENTITY | 10 | 10 | 0 | 100.00 | 10 / 10 |
| MARKET_DATA_HEALTHY | 10 | 2 | 8 | 20.00 | 2 / 10 |
| ENOUGH_HISTORY | 10 | 10 | 0 | 100.00 | 2 / 2 |
| LIQUIDITY_PASS | 2 | 2 | 0 | 100.00 | 2 / 2 |
| SPREAD_PASS | 2 | 0 | 2 | 0.00 | 0 / 2 |
| ATR_PASS | 2 | 0 | 2 | 0.00 | 0 / 0 |
| SCANNER_QUALIFIED | 10 | 0 | 10 | 0.00 | 0 / 0 |
| TOP3_SELECTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| STRATEGY_EVALUATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| SIGNAL_GENERATED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| BIAS_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| ANTI_SPAM_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FRICTION_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| RISK_PASS | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| EXECUTION_PERMISSION | 10 | 0 | 10 | 0.00 | 0 / 0 |
| ORDER_ATTEMPTED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| FILLED | 0 | 0 | 0 | Not evaluated | 0 / 0 |
| TRADE_COMPLETED | 0 | 0 | 0 | Not evaluated | 0 / 0 |

First blocking reasons by category (each market-cycle counted once):

{
  "INFRASTRUCTURE": {
    "STALE_CANDLE": 8
  },
  "MARKET": {
    "ATR_BELOW_SCANNER_FLOOR": 2
  },
  "STRATEGY": {},
  "RISK_ECONOMICS": {},
  "UNCLASSIFIED": {}
}

Disconnect reasons: {'ExchangeError:UNEXPECTED_SUBSCRIPTION_ACK': 1, 'ExchangeError:INFO_READ_CANCELLED': 3}.
Checkpoint and backup valid: True. Clean shutdown: False. Source unchanged during run: True.
Certification blockers: final_transport_recovered, subscriptions_confirmed_once, sustained_valid_market, final_valid_market, paper_account_reconciled, clean_shutdown.

Close codes and transport timing absent in old runs remain unknown. A past error string alone cannot prove it was unresolved at shutdown. No strategy profitability or funded practice is certified.
