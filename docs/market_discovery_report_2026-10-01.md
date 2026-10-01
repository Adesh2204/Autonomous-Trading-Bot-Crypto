# NSE market-wide premarket discovery — implementation and validation

Date: Thursday, 1 October 2026, IST. Baseline commit: `f9f1cf4a940293545acc035afca0cf861449556a`. Branch: `main`.

**Today's readiness: CONFIG_FALLBACK_READY. Today's trading result: NO_TRADE. Execution stays PAPER.** The market-wide implementation passes deterministic validation, but a real full-market discovery scan was unavailable because NSE's equity-reference download timed out. This report does not claim that the synthetic fixture represents today's market.

## A. Repository inspection

Before this change, `live_stream.main()` authenticated through `angel_login()`, loaded/refreshed `InstrumentRegistry`, called `registry.candidates(configured_symbols)`, then passed that already capped set to `run_premarket_screener()`. The registry put configured symbols first and capped the set at `MAX_DISCOVERY_CANDIDATES`. This expanded the old pool alphabetically rather than comparing activity across the market.

The deep screener already accepts `universe`, `session_date` and `top_n`. It fetches completed-session one-minute candles, validates them, computes canonical ATR, evaluates its existing qualification gates, ranks by opportunity score/ATR/symbol and selects Top 3. `AngelOneLiveStream` initializes isolated per-symbol state from that watchlist while retaining one global execution engine.

After this change the same `main()` calls:

```text
Read-only authentication in PAPER
  -> fresh broker master + authoritative broker intraday membership
  -> all canonical NSE EQ instruments, without a candidate cap
  -> NSE equity-share reference membership (exclude ETFs/other cash products)
  -> previous completed session's official bulk bhavcopy
  -> direction-neutral cheap filters and ranking
  -> Top <= 60
  -> existing run_premarket_screener(universe=..., session_date=..., top_n=3)
  -> existing Top <= 3 watchlist
  -> unchanged Phase-5 constructor and frozen signal brain
```

Manual symbol overrides keep a separate explicit branch within the same existing entrypoint; they still require verified registry identity. No competing production executable was added.

## B. Existing reusable infrastructure

Reused `InstrumentIdentity` and its validation, the exact registry identity objects, the existing broker-master/eligibility refresh endpoints, `ReadOnlySmartConnectWrapper`, `NSEMarketSchedule`, `find_previous_completed_market_session`, the existing screener and canonical `signal_brain.compute_atr`, existing opportunity ranking and RVOL history, and the existing Phase-5 watchlist constructor. Existing price, volume, exclusion, freshness, candidate-limit, retry, pacing and Top-N settings remain authoritative.

No new dependency or paid data service was introduced. Optional morning quotes were deliberately omitted because previous-session bulk discovery needs neither quotes nor per-symbol history.

## C. Files added

| File / principal functions | Purpose and before/after behavior | Risk / coverage |
|---|---|---|
| `algo-trading-bot/market_universe.py`: `load_master_envelope`, `build_market_universe`, `MarketUniverse.equity_only`, `configured_fallback` | Adds normalized, uncapped master inspection with rejection reasons; reuses registry identities. Applies NSE stock membership and validates each configured fallback token against current authoritative identity. | Stale/ambiguous identities reduce or block the universe. Covered by freshness, mixed instruments, unresolved tokens, conflicting tokens, deduplication, normalization and fallback tests. |
| `algo-trading-bot/discovery_data.py`: `DiscoveryDataSource`, `parse_equity_reference`, `parse_bhavcopy`, `atomic_json` | Adds two official bulk-file readers, schema/size/date validation, bounded sequential HTTP, request accounting and session-keyed caches. | Upstream outage/schema change produces explicit fallback. Tests cover CSV/ZIP, changed columns, wrong dates, corruption, cache reuse, bounded retries, 404, size caps and future-date rejection. |
| `algo-trading-bot/market_discovery.py`: `MarketSnapshot`, `DiscoveryCandidate`, `MarketDiscoveryResult`, `discover_nse_candidates` | Adds typed coarse selection using prior close/high/low/volume/turnover; caps only after market-wide ranking. | Coarse ranking can omit an eventual opportunity. No trade signals or profit forecasts are generated. Tests cover filters, invalid numbers, ties, 120/17 candidate cases, availability, partial data and classification guards. |
| `algo-trading-bot/premarket_pipeline.py`: `load_startup_universe`, `run_premarket_pipeline`, `PremarketPipelineResult` | Resolves one session and connects discovery to the existing screener. Records lineage and keeps discovery requests separate from deep-history requests. | Source failures must not become filter bypasses. Tests cover fallback, disabled discovery, disabled fallback, zero qualification, shared dates, reports and actual `main()`/Phase-5 handoff. |
| `algo-trading-bot/test_market_discovery.py` | Unit tests plus explicitly labeled `SYNTHETIC_TEST_FIXTURE` data and the 1,000-record fixture. | Tests are not market evidence. |
| `algo-trading-bot/test_discovery_startup.py` | Integration tests run existing `main()`, the real screener and actual Phase-5 constructor; only authentication/data and the websocket-start boundary are replaced in the offline test. | Confirms identity handoff without real orders or streaming. |

All evidence/report files under `docs/discovery_*` are also new; their purpose is to retain test outcomes, integrity proofs and separate fixture/external-source results.

## D. Files modified

| File | Purpose / before / after | Risk | Test coverage |
|---|---|---|---|---|
| `.gitignore` | Runtime master, bulk caches, journals/reports and new runtime logs are excluded from version control. Existing tracked files are unaffected. | Operators still need an appropriate local backup policy for existing accounting data. No accounting storage behavior changed. | Git-status/diff audit; runtime artifacts remain on disk. |
| `config.py` | Adds only discovery switches, paths, download limits, count sanity floors and official source URLs. All existing assignments are preserved exactly. | Disabling fallback changes source availability policy; changing source URLs requires schema-compatible data. | AST proof for all original assignments; manual/automatic/fallback tests. |
| `live_stream.py` | Replaces pre-ranking `registry.candidates()` startup selection with `run_premarket_pipeline()`. Keeps all existing stream-class methods unchanged. Uses “primary candidate” terminology. | New source availability paths can cause fallback or NO_TRADE. | Existing Phase-5 suite, actual-main dry run, zero-trade startup, identical class AST. |
| `premarket_screener.py` | One log label changes from “Primary Winner” to “Primary Candidate.” There is no other source difference from the baseline. | None to qualification/ranking. | Exact whole-file comparison allowing only that label change; all existing screener tests. |
| `refresh_instruments.py` | Corrects the observed `Exchange` field versus legacy lowercase `exchange`; validates schemas/conflicts and normalizes membership symbols. Reuses canonical universe parsing and atomic cache writes. | Unknown/ambiguous schemas fail safely instead of manufacturing eligibility. | Five new parameterized schema tests plus the real authenticated refresh. |

No threshold tuning, unrelated formatting or downstream trading refactor was performed.

## E. Dynamic universe

The master requires an aware source timestamp no older than `INSTRUMENT_MAX_AGE_HOURS=24`, a fresh file timestamp, a list of records, minimum record-count sanity and explicit intraday membership. The parser normalizes case/outer whitespace, preserves authoritative tokens, enforces NSE/cash/EQ and validates tick/lot metadata. No token is inferred from a symbol.

Identical duplicates are recorded and deduplicated. Conflicting symbol/token/tick/lot identities are excluded. Conflicts against noneligible NSE EQ records also invalidate affected eligible tokens. Every raw rejection retains its record index, symbol and reason in the runtime report.

**NSE EQ does not by itself prove a stock is an equity share.** Dynamic discovery additionally requires membership in NSE's published equity-share reference, which is listed separately from ETF/REIT/INVIT files on the [official securities page](https://www.nseindia.com/static/market-data/securities-available-for-trading). The same canonical identity objects survive classification, discovery, screening and the Phase-5 handoff.

Today the broker returned **141,994 records**, including **2,692 NSE EQ records**. Its eligibility endpoint returned **1,866 membership rows**; the canonical intersection resolved **1,857 intraday-eligible NSE EQ instruments**. Because the NSE stock-reference download failed, that last count is explicitly *unclassified cash EQ instruments*, potentially including ETFs. It is not reported as 1,857 verified stock equities.

Configured fallback uses the existing 15 entries, with exact fresh registry token/trading-symbol/exchange validation. A missing/stale master cannot be repaired by assigning a new timestamp to configured tokens; if no authoritative identity is available, startup blocks.

## F. Discovery pipeline

Previous close must lie in the existing ₹150–₹350 band. Previous volume must meet the existing 5,000,000-share floor. OHLC must be positive and finite with `low <= close <= high`; volume must be a nonnegative integer and turnover positive/finite. Exclusions remain centralized.

For each coarse qualifier:

```text
range_pct = (previous_high - previous_low) / previous_close
score = (range_pct / max_range + volume / max_volume + turnover / max_turnover) / 3
sort = (-score, -range_pct, -volume, symbol)
```

Normalization uses only the same completed-session coarse-qualified set. Zero maximum range uses a safe denominator; candidate order does not affect the result. This transparent equal-component discovery score measures prior activity, not strategy quality, direction, expected return or win probability. Both bearish and bullish structures can reach the downstream screener.

The production source is NSE's current CM UDiFF final bhavcopy, not discontinued legacy formats. NSE documents the replacement on its [official reports page](https://www.nseindia.com/all-reports) and supplies formats through [Forms & Formats](https://www.nseindia.in/static/resources/forms-formats-members). Column names are validated explicitly; `ClsPric` is the completed session's close, rather than `PrvsClsgPric` from an earlier day. Turnover uses `TtlTrfVal` without inventing an estimate.

The requested session is resolved once, then passed into both stages. Each market row must have the exact session date. Availability must follow that session's close and precede the actual decision. Download metadata records acquisition time, not a claimed exact exchange publication timestamp. Future/today-final files are never requested for this premarket path.

Caches live under `data/cache/discovery/<session>/` and carry source, schema, date, download/source/availability timestamps, count and checksum. Wrong date/source/schema/checksum or unavailable timestamps cause an explicit reload or safe failure. The immutable bhavcopy can be reused; stock-reference freshness remains bounded to 24 hours. Missing eligible-symbol rows are counted with explicit coverage and rejection reasons.

## G. Stage-1 counts

| Stage | Deterministic fixture | Today's external run |
|---|---:|---:|
| Raw broker records | 1,000 | 141,994 |
| Resolved intraday NSE EQ before stock classification | 700 | 1,857 |
| Verified eligible stock equities | 600 | Unavailable |
| Coarse-qualified equities | 180 | Not run |
| Discovery Top N | 60 | Unavailable |
| Deep-screen input | 60 | 15 validated fallback entries |
| Deep qualified | 12 | 0 |
| Final watchlist | 3 | 0 — NO_TRADE |

The fixture's other 400 records deliberately include BSE, bad-series, ETF and noneligible records. No list is padded to reach 60 or 3.

## H. Existing screener integration

`run_premarket_pipeline()` calls the existing function with `universe=discovery.screening_universe()`, `session_date=target_session` and `top_n=config.SCREEN_TOP_N`. The 60 discovery candidates still undergo the existing one-minute history, candle validation, canonical ATR, EMA validity, price/volume/exclusion and opportunity-ranking logic. The deep-screener module is unchanged except for one human-facing log label.

The fixture verifies exactly 60 candidate fetches and 12 deep qualifiers. There are zero one-minute historical API requests in Stage 1. Bearish candidates still qualify; no ATR threshold or direction logic was relaxed.

## I. Final Top-3 handoff

The final `CandidateDiagnostic` objects retain canonical identity and volume profiles, with attached `discovery_lineage`: instrument source/token, discovery session/rank/score, deep rank, opportunity score, qualification and final rank. The original stream constructor receives the same watchlist object. Its class AST is unchanged.

Fixture identities, not real market recommendations:

| Final rank | Trading symbol | Token | Discovery rank | Existing opportunity score |
|---|---|---|---|---|
| 1 | STOCK0010-EQ | 10010 | 11 | 3.381134 |
| 2 | STOCK0011-EQ | 10011 | 12 | 3.377258 |
| 3 | STOCK0008-EQ | 10008 | 9 | 3.330372 |

The actual-main integration test initializes three genuine isolated `SymbolState` objects and verifies symbol, trading symbol, token, exchange and identity object continuity. No strategy signal-generation function runs during discovery. The test stops at the websocket-start boundary.

## J. Failure behavior

| Condition | Result |
|---|---|
| Valid dynamic discovery | Feed Top <=60 into existing deep screen. |
| Fresh instrument cache, external master/eligibility source outage | Reuse verified cache; never guess identities. |
| Bulk source outage/schema failure | Prominent warning; validated CONFIG_FALLBACK when enabled. |
| Discovery disabled | Explicit configured-universe mode with current identity validation. |
| Valid discovery with zero coarse qualifiers | NO_TRADE; no padding or fallback. |
| Valid discovery, deep screen qualifies zero | NO_TRADE; no fallback around ATR/volume rejection. |
| Fallback disabled or lacks valid identities | BLOCKED/NO_TRADE. |
| Duplicate/missing/stale identities | Exclude affected instruments; retain reasons. |
| Corrupt/wrong-session cache | Explicit rejection and bounded reload/failure. |
| Cache/report write failure | Explicit diagnostic; valid in-memory selection may continue. |

Today dynamic data failed before a valid scan, so fallback was permitted. The real deep screen rejected all 15: all failed `ATR_BELOW_MIN`; ENGINERSIN and PETRONET also failed `VOLUME_INSUFFICIENT`. No substitute watchlist or trade was created.

## K. Tests

**303 PASS, 0 FAIL, 0 SKIP** in **5.45 seconds**. The 244 existing cases remain; 59 cases were added. No existing test was skipped or weakened.

Every test name, PASS/FAIL/SKIP status and duration is retained in [complete test results](discovery_test_results_2026-10-01.json) and [JUnit](discovery_tests_2026-10-01.xml); [terminal output](discovery_tests_2026-10-01.txt) records the complete run.

Required cases are covered: mixed whole-market input; stale master; unresolved/conflicting identity; exclusions; coarse price/volume gates; Top-60 cap; less-than-60 behavior; deterministic ties; shared session; explicit source-failure fallback; legitimate deep zero; core hash immutability; Top-3 selection; Phase-5 identity handoff; disabled discovery/manual compatibility; and the exact 1,000 -> 600 -> 180 -> 60 -> 12 -> 3 integration fixture.

Additional coverage includes noneligible token collisions, same-session cache reuse, checksum/date/schema rejection, finite-number validation, bounded retries, 404 behavior, oversized downloads, no future-file request, explicit partial availability, exact broker field casing, conflicting eligibility fields, missing-master blocking and separate Stage-2 request accounting.

## L. API usage

| Final real read-only startup request category | Count |
|---|---:|
| Broker instrument master GET | 1 |
| Broker intraday-eligibility GET | 1 |
| NSE equity-reference GET attempts | 3 |
| NSE bhavcopy GET | 0 (reference failed first) |
| Stage-1 quote calls | 0 |
| Stage-1 historical calls | 0 |
| Retry attempts | 2 |
| HTTP failures | 3 |
| Stage-2 one-minute historical calls | 15 |
| Extra RVOL history calls | 0 (no selected watchlist) |
| Broker orders | 0 |

Authentication succeeded in the final run and is outside discovery-request counters. SDK authentication/IP-discovery traffic is not mislabeled as bulk discovery. Earlier diagnostic startup attempts also authenticated/read master and eligibility; the final table represents the successful corrected fallback validation, not cumulative session-wide broker usage.

HTTP is sequential, not threaded: configured 15-second timeout, existing bounded retry count, exponential backoff and existing pacing. 4xx errors other than 429 are not repeatedly retried. Downloads and decompressed ZIP content have configured size limits. No unbounded workers or retry loops were introduced.

## M. Performance

On the local fixture, processing the 1,000-record universe took **6.78 ms**; coarse filtering/ranking the 600 eligible stocks took **1.39 ms**. These are local processing timings and exclude network/deep screening. Offline discovery made zero external requests; the deep fixture made 60 synthetic candle fetches.

Today's real master with 141,994 records was parsed successfully and fallback screened only 15 stocks. Real market-wide filtering latency could not be measured because the bulk reference was unavailable. No claim is made that the entire network startup takes milliseconds. Detailed raw rejection records are retained in the ignored runtime JSON; the external evidence artifact summarizes counts to avoid checking a 16 MB runtime report into Git.

## N. Git diff

Five previously tracked files changed: `.gitignore`, `config.py`, `live_stream.py`, `premarket_screener.py`, `refresh_instruments.py`. Tracked diff: **49 insertions, 27 deletions**. Four runtime modules and two test modules were added, plus the new evidence/report artifacts. No commit, push, PR or live activation was performed.

Per-file purpose/before/after/risk/test coverage appears in C and D. No execution/accounting/reconciliation module changed. All original configuration assignments, including capital/risk, position count, scaling, friction, ATR/EMA/VWAP and Top-3 settings, compare identically to the baseline AST.

## O. Core integrity

```text
signal_brain.py
LINES ADDED:    0
LINES REMOVED:  0
LINES MODIFIED: 0
SHA256: bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83
```

`git diff --exit-code -- algo-trading-bot/signal_brain.py` returned 0 with empty output. The exact protected-file list and proof are in [validation evidence](discovery_validation_2026-10-01.json). `AngelOneLiveStream` class AST also matches the baseline exactly. `premarket_screener.py` matches its baseline byte-for-byte after allowing only the “Primary Winner” -> “Primary Candidate” label substitution.

Protected unchanged modules include signal brain, candle builder, execution engine, safe trader, execution safety/adapters, journal, symbol state, ATR firewall, feed integrity, opportunity engine, market schedule, instrument registry and activation gate. LIVE_MODE and LIVE_VALIDATION_APPROVED remain False. The existing source-matched live gate still blocks activation.

## P. Today's readiness and precise limits

**CONFIG_FALLBACK_READY** was observed at **08:27:27 IST on 1 October 2026**. Read-only authentication and authoritative master/eligibility refresh succeeded after fixing the casing defect. Dynamic discovery was unavailable because NSE's bulk stock-reference endpoint timed out after bounded retries. All 15 validated configured candidates were deep-screened for **30 September 2026** and rejected; the correct result is **NO_TRADE**. No real orders, websocket streaming or actual trading were started by validation.

The complete dynamic pipeline and actual Phase-5 construction are separately validated with the explicitly labeled synthetic fixture. This is engineering evidence, not a real successful market-wide scan and not profitability evidence.

An **existing calendar defect** was found: the installed `NSEMarketSchedule`/BSE provider reports 2 October 2026 as open and resolves 5 October's prior session to 2 October. NSE's [official 2026 capital-market holiday circular](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf) lists 2 October as Gandhi Jayanti. The shared calendar implementation was preserved under this directive's certified-logic rule; the weekend/holiday integration test uses an explicit holiday-aware schedule fixture. Today's 1 October -> 30 September alignment is correct, but future holiday readiness must not be inferred from today's validation. The calendar needs a separate focused correction before relying on 2/5 October scheduling.

For normal paper startup, use the existing command from the repository root:

```bash
.venv/bin/python algo-trading-bot/live_stream.py
```

It uses the verified master cache, attempts bounded official discovery, logs the source/fallback reason, and preserves legitimate NO_TRADE. Do not weaken ATR or volume filters to manufacture a watchlist. Full-market readiness requires a valid NSE stock-reference and exact-session bhavcopy; live readiness additionally requires the unchanged separate broker activation evidence.

Evidence: [real read-only attempt](discovery_today_external_2026-10-01.json), [labeled fixture dry run](discovery_fixture_dry_run_2026-10-01.json), [integrity/test manifest](discovery_validation_2026-10-01.json).
