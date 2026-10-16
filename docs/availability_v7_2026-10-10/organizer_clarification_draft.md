# Unsent organizer clarification draft

This is a local draft for Team Anchorium to review. It has not been sent.

Hello, we ran a bounded public-data PAPER session on Hyperliquid Testnet DEX `par` from 17:56 to 18:11 UTC on 10 October 2026. We kept our strategy unchanged and submitted zero exchange actions.

The connection recovered with all 40 subscriptions confirmed, but no market had usable required inputs at the end. We recorded exact missing minute starts, request coverage and reception times. Some previously absent minutes later became available through REST:

| Market | Distinct intervals absent in a covering REST response | Those later observed through REST within the PAPER run |
|---|---:|---:|
| par:BRENT | 43 | 0 |
| par:BTC | 13 | 6 |
| par:ETH | 12 | 0 |
| par:EWJ | 79 | 0 |
| par:EWY | 48 | 0 |
| par:GOLD | 75 | 70 |
| par:HYPE | 15 | 0 |
| par:SP500 | 7 | 2 |
| par:USDEUR | 79 | 0 |
| par:USDJPY | 52 | 0 |

These counts include retained historical intervals as well as live minutes; we exclude startup history from live arrival-latency percentiles. For live completed minutes, median observed REST reception delay was about 204 seconds for BTC (7 samples), 125 seconds for GOLD (6 samples), and 63 seconds for SP500 (6 samples). These include polling/network delay; we do not claim exchange-side publication latency. No completed WS reception sample appeared during this run.

Could you clarify:

1. Does the `par` candle feed deliberately omit one-minute intervals with no trades, and can those exact intervals later appear or be backfilled in `candleSnapshot`?
2. Is the candle WebSocket expected to send a final completed candle for each minute, or only updates triggered by trading activity?
3. Is there an official publication timestamp or documented completion/backfill delay that participants should measure?
4. Can you check the attached exact timestamps/covered responses against current testnet candle availability?

We will keep missing bars explicit and our existing freshness/history safeguards enforced. We will not synthesize candles or claim permanent absence/API failure without evidence.

Suggested attachments: `organizer_missing_minute_evidence.json`, `native_source_findings.json`, source-bound PAPER receipt/certification and the corresponding original public candle capture. Review provider licensing before sharing the separate mainnet external capture; it is not needed for this question.
