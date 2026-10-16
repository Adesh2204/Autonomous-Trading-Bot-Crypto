# Phase 1/2 findings before production edits

Source is c0f496204be5aedd5acbacb8977cced15944066d12bd62968e7c987241431d1a. Previous evidence is preserved.

Recorded scanner candles reproduce both numeric failures: finite numpy.float64 ATR_14 = 0.0 rejected by market_regime_scanner.py scan(), decimal(..., positive=True), through base_exchange.py decimal() line 26. Close, EMAs and VWAP are finite positive. Genuine flat bars are legal OHLCV. This is a scanner integration defect, not an ATR formula defect. Correct the nonnegative ATR contract and keep the exact 0.004 floor. Negative/nonfinite ATR must still reject with explicit field evidence.

Historical raw REST and WebSocket candle payloads were not archived. Scanner tape stores normalized REST-derived candles, not wire payloads or streaming cache snapshots. Checkpoint contains paper/account state, not candle cache. Thus original missing intervals are CAUSE_UNDETERMINED. Fresh retrospective requests cannot prove the original response. See historical_candle_audit.json for exact missing timestamps per market.

Source inspection identifies additional integration risks requiring deterministic proof before repair: WS completed rows overwrite cached completed facts unconditionally; REST merging updates same-timestamp prior facts without conflict detection; REST response contiguity is checked before joining retained genuine rows, which can reject a repair that the retained cache could complete. These are not yet assigned as causes of the previous 331 rejections.

Raw provenance recording is missing at the public input boundary. Add an optional bounded-run public-only candle audit sink so raw/normalized/cache/scanner stages can be compared on identical intervals. No account/private payloads should be captured.

Two OFFLINE_FIXTURE reproductions now confirm merge defects (verified_merge_defects_before.json): a conflicting completed WS row silently changes 50000 to 50001 and stays healthy; a gapped REST repair containing the missing cached row is rejected before merging with a retained row that fills its response hole. These mechanisms are real code defects; the old-run attribution remains unproven.

Limited LIVE_PUBLIC_READ_ONLY retrospective queries returned all 1269 expected rows on every original final scanner window, raw and normalized. All original missing timestamps are now returned. This proves they are retrievable now, not that they were supplied during the run. No pagination loss or normalizer drop was observed in these retrospective requests.

Safety boundary inspection: venue_config.py parses the whole .env into _defaults, although PAPER requires no wallet credentials. The V6 public-only process will explicitly bypass this parse before importing the runtime. This avoids loading wallet-key settings, while still checking explicit PAPER/false/testnet/par environment. This is config isolation, not activation or strategy editing.

Additional OFFLINE_FIXTURE proof (scanner_conflict_followup.json): scanner cache conflict rejects and preserves data but note_scanner_failure does not latch that conflict, leaving engine health true. reason_code also returns UNCLASSIFIED for a completed-candle conflict. The first V6 PAPER attempt was interrupted cleanly before modifying source; it is preserved and is not a completed 15-minute validation. Add explicit scanner conflict/numeric latches, clear only on a validated full scanner snapshot, and map conflict to INVALID_MARKET_DATA. Threshold rejections must remain unlatched.
