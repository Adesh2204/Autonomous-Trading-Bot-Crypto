# Premarket discovery repair — 1 October 2026

The configured-stock fallback has been removed from the automatic startup path. The full broker master is examined, eligible NSE equity shares are identified, official previous-session bulk data narrows the candidates, and the existing detailed stock filters choose the watchlist. The stock-selection process cannot guarantee profits.

## Actual verification result

The latest run released a watchlist of 3 stocks. This was a **read-only stock-selection check**, started at 2026-10-01T12:43:38.621121+05:30 and completed at 2026-10-01T12:53:25.830045+05:30. It analysed the completed session of 2026-09-30. No trading engine or websocket was started, and no broker orders were submitted.

| Stage | Actual count |
|---|---:|
| Broker instrument records examined | 141,994 |
| Initially resolved intraday-eligible NSE EQ instruments | 1,857 |
| Verified eligible equity shares | 1,580 |
| Previous-session bhavcopy records downloaded | 3,696 |
| Stocks passing bulk price/volume checks | 46 |
| Detailed screening attempts | 46 |
| Candidates with usable candle data | 39 |
| Qualified stocks | 6 |
| Final watchlist | 3 |
| Configured stock-list substitutions | 0 |
| Real orders submitted | 0 |

| Rank | Stock | Broker token | Previous-session price | One-minute ATR% | Available volume profiles |
|---|---|---|---:|---:|---:|
| 1 | RSYSTEMS | 13414 | ₹285.71 | 0.991% | 2 |
| 2 | RITES | 3761 | ₹212.34 | 0.806% | 1 |
| 3 | GLASSWALL | 766005 | ₹280.56 | 0.592% | 1 |

These prices describe the historical screening data. Entry decisions require current quotes, a fresh strategy signal, spread/depth validation, and the existing fee, cash, and risk gates. Rank 1 is the highest existing opportunity score among the qualified candidates with available data; it is not a probability of profit.

An earlier fresh external check completed at 2026-10-01T09:23:11.860783+05:30 and selected **RSYSTEMS, RITES, ELEVATE**, also from all 141,994 master records, with zero configured-list substitutions. The later broker responses must be assessed separately from that earlier successful observation.

## Root cause and repair

The original `nsearchives.nseindia.com` requests timed out from this machine. Direct read-only checks of NSE's `archives.nseindia.com` returned HTTP 200 for both the equity-share reference file and the dated bhavcopy. The downloader now uses that working official endpoint first and can retry the same dataset through the alternate official archive endpoint. This changes the data-download endpoint; it does not substitute a different stock universe.

Downloads share one bounded retry budget, retry interrupted bodies from the beginning, close response resources, validate the CSV/ZIP schema and session date, and retain the actual source URL and checksum. Cached datasets must match the session, accepted official source, schema, checksum, and availability checks.

Automatic startup no longer calls the configured-stock-list fallback, including when an old configuration sets its retired flag to true. Missing required discovery data yields `BLOCKED` and exit code 2. A completed scan with no qualifying stock yields `NO_TRADE` and exit code 0.

## Broker-history handling and remaining data limits

Angel One repeatedly returned access-rate errors during the real checks. The historical reader now paces requests, applies increasing cooldowns, aborts after six consecutive rate-limit rejections, and bounds the required historical-data phase to ten minutes plus any request already in progress. This respects provider limits; it cannot make the provider return unavailable data.

The additional RVOL history has a separate maximum of 60 seconds. Missing extra profiles remain unknown and are reported as incomplete. A timeout in that optional enrichment does not discard completed stock qualification and ranking. A fatal failure during required screening still blocks startup.

Latest extra-history warning: **HISTORY_TIME_BUDGET_EXHAUSTED**. Latest rejected candidates with broker candle errors: **ELEVATE, ARMEE, RAILTEL, ASHOKLEY, POWERGRID, LTF, NATIONALUM**. The detailed ranking cannot establish that an unavailable candidate would have scored below a selected candidate.

Previous-session snapshot coverage was **99.873%**. 2 eligible stocks had no matching previous-session row and were excluded explicitly. All master records were accounted for: `True`. The audit reports the exclusions rather than claiming that every instrument can be traded by the current strategy.

The current strategy supports NSE cash-equity intraday trading. The 141,994 master records include other exchanges, derivatives, and non-share instruments. Those records are examined and excluded according to the existing scope and broker eligibility. Adding other markets or derivatives requires separate strategy and execution support.

The premarket spread and depth values retain the existing assumptions. Actual spread and depth must pass the live execution checks before a trade. This verification does not establish live profitability or actual fill quality.

## Tests and core-logic preservation

All **338 collected tests ran: 338 passed, 0 failed, 0 skipped**. Cases cover official-endpoint recovery, interrupted downloads, date/schema/cache validation, no configured-list substitution, full-record accounting, correct broker-token lineage, rate-limit cooldowns, time budgets, optional-history failures, and startup handling. Existing execution, capital, fees, recovery, and multisymbol checks also ran.

The signal brain remains byte-identical with SHA-256 `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`. The detailed qualification function, candle-validation function, and Phase 5 stream class remain unchanged. Execution, sizing, adapters, fees, and the durable trade journal are byte-identical to the preservation baseline.

The calendar also respects NSE's confirmed 2026 closures, including 2 October. The Monday 5 October previous-session lookup now resolves to Thursday 1 October. Sources: [NSE annual holiday circular](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf), [election-day amendment](https://nsearchives.nseindia.com/content/circulars/CMTR72260.pdf).

## Run the checks

For a fresh read-only selection check:

```sh
cd "/Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot"
../.venv/bin/python -u premarket_check.py --fresh
```

Read the final JSON summary. `DYNAMIC_DISCOVERY_READY` with a nonempty watchlist means stock selection completed. `BLOCKED` gives the data-failure reason. `configured_stock_list_used` stays false. The report saves the actual source URLs, session, counts, candidates, and data limits.

To start the regular bot in its currently configured PAPER mode after reviewing a successful check:

```sh
../.venv/bin/python -u live_stream.py
```

Run one bot instance and keep the process open. The regular bot repeats discovery before monitoring its selected stocks. Selection does not open a position immediately. PAPER mode simulates executions and profits; it does not credit the Angel One account.

## Evidence

- [Compact real-data validation](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/discovery_repair_validation_2026-10-01.json>)
- [Full runtime report](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/algo-trading-bot/data/paper/premarket_repair_completed_2026-10-01.json>)
- [All test names, statuses, and preservation checks](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/discovery_repair_test_results_2026-10-01.json>)
- [Pytest output](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/discovery_repair_tests_2026-10-01.txt>)
- [JUnit results](</Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/docs/discovery_repair_tests_2026-10-01.xml>)

Official dataset context: [NSE securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading), [NSE UDiFF formats](https://www.nseindia.in/static/resources/forms-formats-members), [Angel One API documentation and rate limits](https://smartapi.angelone.in/docs).
