# Organizer message draft — not sent

Hi, Team Anchorium has completed a strictly PAPER, public-data audit of the Hyperliquid testnet par markets.

Our bounded run on 2026-10-10T08:06:27.195903+00:00 lasted 902.996 seconds. It had 30 scanner market observations: one passed data checks, zero passed the unchanged ATR floor, and no market was usable at shutdown. No exchange orders or account administration occurred.

For the same exchange-time intervals, captured REST response counts, normalized counts and scanner input counts match for all ten markets. Missing current rows were absent in the raw REST response, rather than discarded by our normalizer. WebSocket candle observations cover only the bounded run, not earlier historical intervals.

An example exact public request is:

```json
{
  "type": "candleSnapshot",
  "req": {
    "coin": "par:BTC",
    "interval": "1m",
    "startTime": 1791589560000,
    "endTime": 1791620159999
  }
}
```

In that request's last 300-minute comparison interval, raw REST returned 299 completed rows. Separate full UTC input remains larger than 300 and uses the existing freshness policy; a missing newest minute alone is not automatically a failed scanner input.

We also observed some missing timestamps becoming available in later REST responses. Earlier retrospective queries now return all 1,269 rows for each of the previous run's historical final windows. These later reads do not prove what was originally returned.

Could you clarify the expected current minute-candle publication behavior for par, including whether previously absent minutes can appear later, and whether any venue feed repair is planned? We are keeping genuine missing data missing and preserving our frozen strategy requirements.

The attached evidence would be the raw public candle JSONL, candle_stage_audit.json, historical_gap_traces.json and the V6 report. No wallet key, signature or secret is included.
