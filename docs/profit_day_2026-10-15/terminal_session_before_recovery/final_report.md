# Team Anchorium — full-day BTC profit-only session outcome

**The session halted before any SELL was signed or submitted. The existing 0.0002 BTC LONG was still open at the final exchange read. No profit-taking exit or completed round trip is established.**

## What happened

- Approved session: `fbad5fe98614a88acfdd3ac079e2644f46371265cf6600a2b04f604a63deb1a5`.
- Human acceptance: 15 October 2026 12:48:52 IST; the acceptance was within its original deadline.
- First logged observation: 15 October 2026 12:49:02 IST; final market candidate: 15 October 2026 20:26:35 IST.
- The observed bid reached **81,811 USDPR/BTC**, matching the approved minimum. The tape showed 0.0012 BTC bid depth at that limit against the 0.0002 BTC requested close. That was a market observation, not a fill.
- The worker refreshed its full preflight, consumed its single closing path and reached the existing unresolved-order barrier. It halted with `QUALIFICATION_EXIT_UNRESOLVED_ORDER`.
- Terminal result: 15 October 2026 20:26:49 IST. New exit intents: **0**. Signed API actions since acceptance: **0**. Actual SELL fills: **0**.
- Worker 70469 and its process-bound caffeinate helper 70470 have exited. Signing authority was revoked. The heartbeat is **PAUSED**. This consumed mandate cannot be resumed, retried or extended.

## Exact local blocker

`algo-trading-bot/exchange/qualification_protection.py:require_settled_exit_orders` checks raw `executor.journal.intents()` rows. The raw journal deliberately retains the original 14 October `UNKNOWN` entry:
`certification:3b744e33e2de25c1afd6764eac3268ba8d51ac8ef905200e62230bc4a2261ddf:entry`

Its cloid is `0x3486c3b8e88add1a77175c9c5965350f`. The immutable nontransmission certificate remains present and valid; `effective_rows()` excludes this one certified historical identity. The effective qualification view contains only the genuinely filled original BUY. The exit barrier uses the raw view and rejects the old UNKNOWN anyway.
This is a confirmed mismatch between local recovery views. It is not evidence of an exchange rejection or a new uncertain SELL. The old row and certificate were preserved. No source repair was made by this read-only supervisor.

## Actual account evidence

Final authoritative worker read: **15 October 2026 20:26:49 IST**.

| Item | Verified final observation |
|---|---|
| Account | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Market | Hyperliquid TESTNET `par:BTC` |
| Remaining position | LONG **0.0002 BTC** |
| Leverage | **1x CROSS** |
| Open exchange orders | **0** |
| Account reconciliation | Ready, no reported reasons |
| Original BUY | Order `62755970305`, fill `800659111758533` |
| Entry price / cost | 81,512 / 16.30240 TEST USDPR |
| Actual entry fee | 0.014672 USDPR |
| Reported funding since entry | **+0.000937 USDPR** |
| Actual closing fill / fee | None / no closing fee established |
| Completed round-trip net P&L | **Unavailable — position remains open** |
| Exchange-reported unrealized P&L | 0.09 USDPR, before a verified closing fill |

The accounting ledger reports −0.013735 USDPR for observed fees plus funding with zero closed price P&L. This is not the final P&L of a closed trade. The final candidate estimated +0.001887060 USDPR only conditionally under the conservative 0.27% exit-fee bound; no SELL executed at that estimate.
Last observation used a break-even of about **81,801.54** and the approved rising-only floor of **81,811**. These values were timestamped worker inputs, not a fresh proposal or current executable price.

## Monitoring and connection evidence

- **23,593 logged observation rows**; observer counter **23,594** includes one additional fresh closing-preflight observation that is not appended to the tape.
- Logged market candidates: **1**. Counter totals describe this session only.
- Observed bid range: **79640.0–81811.0**. These are historical observations, not current quotes.
- Full account-history refreshes: **92**; light account refreshes: **358**.
- Tape transport counts: `{'WS_STARTUP_GRACE': 5, 'WS_ACKNOWLEDGED_REPEATED': 1605, 'RATE_LIMITED_REST': 20925, 'NO_FRESH_BOOK': 1058}`.
- Three bounded WS connection attempts, with two reconnections after the first. Every connection reported one confirmed subscription and no duplicates. Generic close errors had no exchange close code/reason; venue responsibility is unknown.
- Recorded connection lifetimes were about 698.4, 609.7 and 667.0 seconds. The reported maximum WS receiver gap was 1.037 seconds. These diagnostics do not establish continuous full-session WS uptime.
- Fresh data continued through the rate-controlled REST fallback after the WS attempt cap. `RATE_LIMITED_REST` labels the polling policy and does not establish an HTTP429.
- Short `NO_FRESH_BOOK` observations occurred between fresh observations; no safety threshold was changed. Exact HTTP429 totals and rate headroom are not exposed in the tape.
- The Mac, app, power and internet were required while the watcher ran. Sleep prevention ended with its worker; it provided no protection against host/network failure.

## Integrity and test evidence

- The tested source hash matches the launch, mandate, terminal result and regression receipt:
`62c42d3d627716b0749c933fefdc7b8d4e1c6216de90b1b563403d5a149172b6`

- Existing matching full regression receipt: **2,363 passed; 0 failures, 0 errors, 0 skipped**. The XML digest matches. The full suite was not rerun by this monitor because no source change was made.
- Final read-only strategy-freeze and Phase-0 checks passed. `signal_brain.py`, frozen rules, PAPER/false defaults and disabled protection were unchanged.
- Both qualification.sqlite and nonces.sqlite passed SQLite integrity checks. Both retained recovery snapshot checksums and their structured source identity passed. The latest account checkpoint equals the latest recovery snapshot account data.
- Important limit: `last_clean_shutdown=false` remains in the checkpoint. A handled halt, terminal result and authority revocation are evidenced; a clean checkpoint flag is **not** established. There is no recorded checkpoint corruption.
- Both original `WHITELIST_TRADE_PROOF.json` files match their saved hashes and were not overwritten.

## Required next action

Keep all exchange writes stopped. A separately requested narrow engineering repair must make the isolated exit barrier honor the existing validated historical nontransmission certificate while continuing to reject every genuinely unresolved order. Verify that repair with focused and full regression tests, fresh account/market reconciliation and a **new exact SELL-only approval**. Do not reuse this consumed session.
No loss-making fallback, automatic retry, new BUY, native protection activation or next-day authorization is granted here.
No `EXIT_RECOVERY_PROOF.json` was created: there is no genuine SELL fill or pair of authoritative flat/zero-order readbacks. Protection remains UNVERIFIED; PRACTICE_READY and LIVE_READY remain false. Organizer whitelisting is unconfirmed.

Machine-readable details and artifact hashes: [final_summary.json](final_summary.json).
